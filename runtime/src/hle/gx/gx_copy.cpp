// gx_copy.cpp - Framebuffer Copy Operations
#include "gx_internal.h"

#include "settings_overlay.h"

#include <dolphin/gx/GXAurora.h>
#include <aurora/aurora.h>
#include <aurora/gfx.h>
#include "runtime_config.h"
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <thread>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <string>
#include <map>
#include <mutex>
#include <vector>

namespace {
// Copy destinations stay GPU-only until an explicit/lazy readback. Track the
// guest ranges that own those results so a later data-cache flush over a reused
// allocation can retire the stale GPU texture before it is considered by a
// subsequent GXLoadTexObj. There is at most one live range per destination;
// rewriting the destination replaces its previous extent.
std::mutex g_efbCopyDestinationsMutex;
std::map<uint32_t, uint32_t> g_efbCopyDestinations;
uint32_t g_largestEfbCopyDestination = 0;

void RememberEfbCopyDestination(uint32_t addr, uint32_t size) {
    if (size == 0) {
        return;
    }
    std::lock_guard<std::mutex> guard(g_efbCopyDestinationsMutex);
    g_efbCopyDestinations[CanonicalizeGxMainRamAddress(addr)] = size;
    // A conservative monotonic maximum lets invalidation jump directly to
    // the only map interval that could overlap instead of walking every copy
    // destination on every DCStoreRange.
    g_largestEfbCopyDestination = std::max(g_largestEfbCopyDestination, size);
}

} // namespace

void InvalidateEfbCopyDestinationsForRange(uint32_t addr, uint32_t size) {
    if (size == 0) {
        return;
    }

    const uint64_t dirtyStart = CanonicalizeGxMainRamAddress(addr);
    const uint64_t dirtyEnd = dirtyStart + size;
    std::vector<uint32_t> retired;
    {
        std::lock_guard<std::mutex> guard(g_efbCopyDestinationsMutex);
        const uint64_t earliestCandidate =
            dirtyStart > g_largestEfbCopyDestination ? dirtyStart - g_largestEfbCopyDestination : 0;
        for (auto it = g_efbCopyDestinations.lower_bound(static_cast<uint32_t>(earliestCandidate));
             it != g_efbCopyDestinations.end() && static_cast<uint64_t>(it->first) < dirtyEnd;) {
            const uint64_t copyStart = it->first;
            const uint64_t copyEnd = copyStart + it->second;
            if (dirtyEnd <= copyStart || dirtyStart >= copyEnd) {
                ++it;
                continue;
            }
            retired.push_back(it->first);
            it = g_efbCopyDestinations.erase(it);
        }
    }

    // Preserve FIFO ordering: the destroy command is emitted before any later
    // texture load that can consume the freshly flushed RAM bytes.
    for (const uint32_t copyAddr : retired) {
        GXDestroyCopyTex(GuestToHostPtr(copyAddr));
    }
}

// ============================================================================
// Display Copy Source/Destination
// ============================================================================

extern "C" bool AuroraGxThreadEnabled();

extern "C" void GX__SetDispCopySrc_8016f438(uint32_t l, uint32_t t, uint32_t w, uint32_t h) {
    // Basara's 448x392 frame ends in a dark column, hidden by overscan on a TV; in a window it shows
    // as a dark line on the right, so the picture is taken without it.
    const bool fullFrame = l == 0 && t == 0 && w == 448 && h == 392;
    GXSetDispCopySrc((u16)l, (u16)t, (u16)(fullFrame ? 447 : w), (u16)h);
}
// Basara: 0x80382150 writes gxData+0x230/0x234 (display copy), 0x80382190 writes +0x240/0x244 (texture copy).
PPC_NATIVE_OVERRIDE_VOID(805A1190, GX__SetDispCopySrc_8016f438, (uint32_t l, uint32_t t, uint32_t w, uint32_t h), (l, t, w, h));

// The hardware register (BP 0x4D) holds only the XFB stride; the SDK ignores the height argument.
// Basara's callers leave r4 unrelated (1 at 0x80338D64), which made aurora present a 1-line display
// copy stretched over the screen (vertical stripes). 0 makes aurora take the copy source height.
extern "C" void GX__SetDispCopyDst_8016f4b8(uint32_t w, uint32_t h) {
    (void)h;
    GXSetDispCopyDst((u16)w, 0);
}
PPC_NATIVE_OVERRIDE_VOID(805a1210, GX__SetDispCopyDst_8016f4b8, (uint32_t w, uint32_t h), (w, h));

// ============================================================================
// Texture Copy Source/Destination
// ============================================================================

extern "C" void GX__SetTexCopySrc_8016f478(uint32_t l, uint32_t t, uint32_t w, uint32_t h) {
    GXSetTexCopySrc((u16)l, (u16)t, (u16)w, (u16)h);
    g_texCopyState.srcLeft=(u16)l; g_texCopyState.srcTop=(u16)t;
    g_texCopyState.srcWidth=(u16)w; g_texCopyState.srcHeight=(u16)h;
}
PPC_NATIVE_OVERRIDE_VOID(805A11D0, GX__SetTexCopySrc_8016f478, (uint32_t l, uint32_t t, uint32_t w, uint32_t h), (l, t, w, h));

extern "C" void GX__SetTexCopyDst_8016f4dc(uint32_t w, uint32_t h, uint32_t f, uint32_t m) {
    GXSetTexCopyDst((u16)w, (u16)h, (GXTexFmt)f, (GXBool)m);
    g_texCopyState.dstWidth=(u16)w; g_texCopyState.dstHeight=(u16)h;
    g_texCopyState.dstFormat=f; g_texCopyState.dstMipmap=m;
}
PPC_NATIVE_OVERRIDE_VOID(805a1240, GX__SetTexCopyDst_8016f4dc, (uint32_t w, uint32_t h, uint32_t f, uint32_t m), (w, h, f, m));

extern "C" void GX__SetCopyFilter_8016fa40(uint32_t aa, uint32_t spa, uint32_t vf, uint32_t vfa) {
    uint8_t sp[12][2]={}, vfb[7]={};
    if(spa) std::memcpy(sp, GuestToHostPtr(spa, 24), 24);
    if(vfa) std::memcpy(vfb, GuestToHostPtr(vfa, 7), 7);
    GXSetCopyFilter((GXBool)aa, sp, (GXBool)vf, vfb);
}
PPC_NATIVE_OVERRIDE_VOID(805a1720, GX__SetCopyFilter_8016fa40, (uint32_t aa, uint32_t spa, uint32_t vf, uint32_t vfa), (aa, spa, vf, vfa));

extern "C" void GX__SetDispCopyGamma_8016fc24(uint32_t g) { GXSetDispCopyGamma((GXGamma)g); }
PPC_NATIVE_OVERRIDE_VOID(805a1910, GX__SetDispCopyGamma_8016fc24, (uint32_t g), (g));

// ============================================================================
// Copy Execution
// ============================================================================

extern "C" bool AuroraGxThreadEnabled();
extern "C" uint64_t AuroraGxThreadMark();
extern "C" void AuroraGxThreadWaitMark(uint64_t ticket);
// Holds the boot at GXInit until the boot pipeline prewarm has drained, presenting the
// precompile screen meanwhile (settings_overlay::SetBootShaderProgress).
void UtageWaitForBootShaders() {
    static bool s_done = false;
    if (s_done) {
        return;
    }
    s_done = true;
    // The cached shaders wait unbuilt in aurora: a draw builds the one it needs. This hold builds
    // them all only to fill the translated-shader and driver caches (0.6.0).
    const uint32_t total = aurora_get_queued_pipeline_count() + aurora_get_dormant_pipeline_count();
    RT_LOGF(RT_TAG_GX, "boot: %u cached pipelines at GX init\n", total);
    if (total <= 64) {
        return;
    }
    // A start skips this only when the driver pipeline cache (AURORA_VK_CACHE_DIR, Android) holds
    // what it needs: the last hold built at least this many shaders, under the same settings that
    // key them (Graphics Compatibility, Disable Fog), as utage_prewarm.txt there records. A new
    // install, an update with new shaders, or a changed setting waits here. Building thousands
    // behind the game left it unresponsive for minutes and effects missing (0.5.8 test).
    const char* cacheDir = std::getenv("AURORA_VK_CACHE_DIR");
    // The shader generation too (aurora_shader_generation): an update that makes different shaders
    // for the same pipelines needs the build once more.
    std::string stamp = "compat" + std::to_string(RuntimeConfigFile::GpuCompat()) + (aurora_get_disable_fog() ? "-nofog" : "");
    if (const char* generation = aurora_shader_generation(); generation != nullptr && generation[0] != '\0') {
        stamp += std::string("-") + generation;
    }
    // And the driver's cache identity: one another driver wrote (a system update, a custom GPU
    // driver) is ignored by this one, so the shaders build again behind the game (1.0.0).
    if (const char* driver = aurora_driver_cache_id(); driver != nullptr && driver[0] != '\0') {
        stamp += std::string("-") + driver;
    }
    if (cacheDir != nullptr) {
        const std::filesystem::path dir(cacheDir);
        std::error_code ec;
        const auto bytes = std::filesystem::file_size(dir / "vk_pipeline_cache.bin", ec);
        uint32_t built = 0;
        std::string builtStamp;
        {
            std::ifstream f(dir / "utage_prewarm.txt");
            f >> built >> builtStamp;
        }
        if (!ec && bytes > (4u << 20) && total <= built + 64u && builtStamp == stamp) {
            RT_LOGF(RT_TAG_GX, "boot: driver pipeline cache present (%llu MiB, %u shaders built before): each builds when first drawn\n",
                    static_cast<unsigned long long>(bytes >> 20), built);
            aurora_discard_cached_pipelines();
            return;
        }
        RT_LOGF(RT_TAG_GX, "boot: %u shaders, %u built before (%s, now %s)\n", total, built,
                builtStamp.empty() ? "-" : builtStamp.c_str(), stamp.c_str());
        // No Preparing shaders screen (0.6.0): they build behind the game on aurora's background
        // workers (small cores, lowest priority, only to fill the caches) while a draw that needs
        // one builds it first. A corner counter shows the progress and writes the stamp when
        // done. BASARA_SHADER_HOLD=1 waits here as before.
        if (const char* hold = std::getenv("BASARA_SHADER_HOLD"); hold == nullptr || hold[0] != '1') {
            // The stamp names only a build that completed: a swipe out of Recents mid-build left
            // the last stamp with a half-filled driver cache, and the next start took it for warm
            // (1.0.0). The background build writes it again when done.
            std::filesystem::remove(dir / "utage_prewarm.txt", ec);
            const uint32_t queued = aurora_prewarm_cached_pipelines(false);
            settings_overlay::StartBootShaderBackground(queued, (dir / "utage_prewarm.txt").string(),
                                                        std::to_string(total) + ' ' + stamp + '\n');
            RT_LOGF(RT_TAG_GX, "boot: %u shaders build in the background\n", queued);
            return;
        }
    }
    if (AuroraGxThreadEnabled()) AuroraGxThreadWaitMark(AuroraGxThreadMark());  // nothing in flight
    EnsureAuroraFrameActive();
    const auto start = std::chrono::steady_clock::now();
    // Kept only where no driver cache carries them to the next start (the PC).
    aurora_prewarm_cached_pipelines(cacheDir == nullptr);
    settings_overlay::SetBootShaderProgress(total);
    while (aurora_get_queued_pipeline_count() > 0 && std::chrono::steady_clock::now() - start < std::chrono::minutes(5)) {
        settings_overlay::Draw();
        VI_HLE_PresentFrame(false, false);
        UpdateAuroraAndProcessEvents();
        std::this_thread::sleep_for(std::chrono::milliseconds(33));
        EnsureAuroraFrameActive();
        aurora_wait_for_frame_worker();
    }
    settings_overlay::SetBootShaderProgress(0);
    if (cacheDir != nullptr && aurora_get_queued_pipeline_count() == 0) {
        std::ofstream f(std::filesystem::path(cacheDir) / "utage_prewarm.txt", std::ios::trunc);
        f << total << ' ' << stamp << '\n';
    }
    RT_LOGF(RT_TAG_GX, "boot: pipelines built in %.1f s\n",
            std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count());
}

extern "C" void GX__CopyDisp_8016fc38(uint32_t da, uint32_t c) {
    EnsureAuroraFrameActive();
    // GX copies are FIFO-ordered on hardware. Drain submitted draws before
    // resolving the EFB so high-level copies see the same contents. The GX thread
    // runs the copy after the queued draws anyway.
    if (!AuroraGxThreadEnabled()) GXDrawDone();
    GXCopyDisp(GuestToHostPtr(da), (GXBool)c);
    // No second GXDrawDone here: the frame-worker wait below is for the DONE
    // phase, which strictly subsumes the drain this call would perform.
    ++g_gxFrameCount;
    VI_HLE_SetXfbReady(da);
    // Present immediately so post-copy draws don't leak into this frame. Join at the DONE phase
    // (not the cheaper SEALED phase GXDrawDone waits for) because ImGui's draw lists, owned by
    // Aurora's render worker, replay during encode; aurora_end_frame would join here anyway.
    aurora_wait_for_frame_worker();
    settings_overlay::Draw();
    // Seal, pace to the VI retrace boundary (Aurora renders the sealed frame
    // during the wait), and pre-warm the next frame.
    VI_HLE_PresentFrame(/*presentedXfb=*/true, /*paceToRetrace=*/true);
}

PPC_NATIVE_OVERRIDE_VOID(805a1930, GX__CopyDisp_8016fc38, (uint32_t da, uint32_t c), (da, c));


extern "C" void GX__CopyTex_8016fd74(uint32_t da, uint32_t c) {
    EnsureAuroraFrameActive();
    // Match GX FIFO ordering: texture copies observe all prior draws (the GX thread's queue
    // keeps that order by itself).
    if (!AuroraGxThreadEnabled()) GXDrawDone();
    const uint16_t rawSrcLeft = g_texCopyState.srcLeft;
    const uint16_t rawSrcTop = g_texCopyState.srcTop;
    const uint16_t rawSrcWidth = g_texCopyState.srcWidth;
    const uint16_t rawSrcHeight = g_texCopyState.srcHeight;

    // Keep the source in guest EFB coordinates. Aurora maps it to the scaled
    // EFB exactly once, matching Dolphin's ConvertEFBRectangle path.
    GXSetTexCopySrc(rawSrcLeft, rawSrcTop, rawSrcWidth, rawSrcHeight);
    // EFB copies stay GPU-only except probe-sized ones (e.g. the 4x4 lens-flare depth probe),
    // which Aurora reads back asynchronously via efb_ram::schedule and land in guest RAM a frame
    // later. RISK: copies above the probe threshold, or on the offscreen list, are not
    // auto-downloaded, so guest reads see stale RAM; call aurora_flush_efb_copies_to_ram if a
    // copy needs reading back.
    // BASARA_LOG_COPY_FRAMES: per frame, the texture copies made (size, format, source, destination),
    // logged with the time whenever that list changes from the previous frame's.
    if (static const bool logFrames = std::getenv("BASARA_LOG_COPY_FRAMES") != nullptr; logFrames) {
        static uint32_t frame = ~0u;
        static std::string current, previous;
        if (frame != static_cast<uint32_t>(g_gxFrameCount)) {
            if (current != previous) {
                const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                    std::chrono::steady_clock::now().time_since_epoch()).count();
                std::fprintf(stderr, "[copyframe] t=%lld frame %u:%s\n", static_cast<long long>(ms), frame,
                             current.c_str());
                previous = current;
            }
            current.clear();
            frame = static_cast<uint32_t>(g_gxFrameCount);
        }
        char item[96];
        std::snprintf(item, sizeof(item), " %ux%u/%u@%u,%u>%08X", g_texCopyState.dstWidth, g_texCopyState.dstHeight,
                      g_texCopyState.dstFormat, rawSrcLeft, rawSrcTop, da);
        current += item;
    }
    // BASARA_LOG_COPIES: each distinct texture copy (destination size, format, source rectangle) once,
    // with the guest code that asked for it (profiling).
    if (static const bool logCopies = std::getenv("BASARA_LOG_COPIES") != nullptr; logCopies) {
        static std::vector<uint64_t> seen;
        const uint64_t key = (uint64_t(g_texCopyState.dstWidth) << 48) | (uint64_t(g_texCopyState.dstHeight) << 32) |
                             (uint64_t(rawSrcWidth) << 16) | rawSrcHeight;
        if (std::find(seen.begin(), seen.end(), key) == seen.end() && seen.size() < 64) {
            seen.push_back(key);
            uint32_t lr = 0, ra[4] = {};
            if (const CpuContext* cpu = TryGetCpuContext()) {
                lr = cpu->lr;
                uint32_t sp = cpu->gpr[1];
                for (int d = 0; d < 4 && sp != 0; ++d) {
                    uint32_t back = 0;
                    if (!Memory::TryRead32(sp, back) || back == 0) break;
                    Memory::TryRead32(back + 4, ra[d]);
                    sp = back;
                }
            }
            std::fprintf(stderr, "[copytex] dst %ux%u fmt %u src %u,%u %ux%u dest %08X lr %08X %08X %08X %08X %08X\n",
                         g_texCopyState.dstWidth, g_texCopyState.dstHeight, g_texCopyState.dstFormat, rawSrcLeft,
                         rawSrcTop, rawSrcWidth, rawSrcHeight, da, lr, ra[0], ra[1], ra[2], ra[3]);
        }
    }
    GXCopyTex(GuestToHostPtr(da), (GXBool)c);
    // The extent the copy writes: a destination bigger than the source is a patch into a larger
    // texture (aurora sizes its copy the same way), not a claim on that whole texture's memory.
    const uint32_t copiedWidth = std::max<uint32_t>(rawSrcWidth >> (g_texCopyState.dstMipmap ? 1 : 0), 1);
    const uint32_t copiedHeight = std::max<uint32_t>(rawSrcHeight >> (g_texCopyState.dstMipmap ? 1 : 0), 1);
    static const bool partialReadback = std::getenv("BASARA_PARTIAL_COPY_READBACK") != nullptr;
    if (partialReadback && copiedHeight < g_texCopyState.dstHeight && copiedWidth >= g_texCopyState.dstWidth &&
        aurora_flush_efb_copy_to_ram(GuestToHostPtr(da))) {
        GxNotifyGuestRamDmaWrite(da, GXGetTexBufferSize(g_texCopyState.dstWidth, copiedHeight, g_texCopyState.dstFormat, GX_FALSE, 0));
    }
    RememberEfbCopyDestination(
        da, GXGetTexBufferSize(std::min<uint32_t>(g_texCopyState.dstWidth, copiedWidth),
                               std::min<uint32_t>(g_texCopyState.dstHeight, copiedHeight),
                               g_texCopyState.dstFormat, GX_FALSE, 0));
    GXSetTexCopySrc(rawSrcLeft, rawSrcTop, rawSrcWidth, rawSrcHeight);
}
PPC_NATIVE_OVERRIDE_VOID(805a1a70, GX__CopyTex_8016fd74, (uint32_t da, uint32_t c), (da, c));
