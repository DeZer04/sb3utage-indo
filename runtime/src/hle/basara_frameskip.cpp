// Frameskip and Game Speed for Utage (MT Framework's sMain, below), the camera distance and Lock
// Target. Config: [video] frameskip = 0 off, 1 auto, 2 30 fps lock. BASARA_FRAMESKIP=0/1/2
// overrides it.
#include "hle_stubs.h"
#include "abi_bridge.h"
#include "ppc_runtime.h"
#include "memory.h"
#include "runtime_config.h"
#include "runtime_log.h"
#include "thermal.h"
#include "cheats.h"
#include "host_suspend.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <string>
#include <unordered_map>
#include <cstdlib>
#include <cstring>
#include <thread>

namespace {

using Clock = std::chrono::steady_clock;

// Thermal Control: while the phone runs hot, draw every second frame (the 30 FPS Lock; logic and audio
// stay at 60) for at least kThermalHoldSeconds, so the CPU and GPU do about half the drawing work.
constexpr double kThermalHoldSeconds = 60.0;
constexpr uint64_t kThermalCheckFrames = 60;

const char* ModeName(int value) { return value == 0 ? "off" : value == 1 ? "auto" : "30 fps lock"; }

// -1 until first read. The in-game settings can change it while playing (BasaraFrameskip_SetMode),
// unless BASARA_FRAMESKIP fixed it.
std::atomic<int> g_mode{-1};
std::atomic<bool> g_modeFromEnv{false};
// The launcher's choice from before the first read: GameActivity.onCreate sends it before main()
// has applied env.txt, so deciding then would miss BASARA_FRAMESKIP.
std::atomic<int> g_requested{-1};

int Mode() {
    int value = g_mode.load(std::memory_order_relaxed);
    if (value >= 0) return value;
    const int requested = g_requested.load(std::memory_order_relaxed);
    value = requested >= 0 ? requested : RuntimeConfigFile::Frameskip();
    if (const char* env = std::getenv("BASARA_FRAMESKIP")) {
        value = std::atoi(env);
        g_modeFromEnv.store(true, std::memory_order_relaxed);
    }
    value = std::clamp(value, 0, 2);
    int expected = -1;
    if (g_mode.compare_exchange_strong(expected, value, std::memory_order_relaxed)) {
        RT_LOGF(RT_TAG_VI, "frameskip: %s\n", ModeName(value));
    }
    return g_mode.load(std::memory_order_relaxed);
}

} // namespace

void BasaraFrameskip_SetMode(int mode) {
    mode = std::clamp(mode, 0, 2);
    if (g_mode.load(std::memory_order_relaxed) < 0) {
        g_requested.store(mode, std::memory_order_relaxed);  // decided at the game's first read
        return;
    }
    if (g_modeFromEnv.load(std::memory_order_relaxed)) return;
    if (g_mode.exchange(mode, std::memory_order_relaxed) != mode) {
        RT_LOGF(RT_TAG_VI, "frameskip: %s (changed in game)\n", ModeName(mode));
    }
}

int BasaraFrameskip_Mode() {
    return Mode();
}

// Utage (MT Framework): sMain (pointer at 0x808F3FD8) times each frame itself (0x80716A60). With
// mFrameWait (+0x40) set it waits out a whole 1/mFps and moves the game by exactly one step
// (mDeltaTime +0x68 = 1); without it mDeltaTime is the real time since the last frame in 1/mFps
// steps, capped at mDeltaTimeLimite (+0x70), and the game moves by that much. The game's fps manager
// (requests 0x800EA524/0x800EA604, applied every frame by 0x800EA558/0x800EA638) runs cutscenes at
// 30 fps with the frame wait, and battles at 60 fps without it but capped at 2 steps, so a phone
// drawing 20 fps played both at two-thirds speed.
// Frameskip Auto (1): the frame wait is never set and the cap at 60 fps is 4 steps, so the game
// keeps real-time speed down to 15 fps (at 30 fps the game's own cap, 16 steps, stays). 30 FPS Lock
// (2): the same, and a 60 fps scene draws at most 30 frames a second (mMaxFps), 2 steps each.
// Off (0) is the game's own behaviour.
namespace {
constexpr uint32_t kUtageMainPtr = 0x808F3FD8u;
int g_utageMode = -1;     // the mode last applied: the player's, or 30 FPS Lock while warm
bool g_utageThermalLock = false;
// Game Speed in percent (Settings > Performance, UtageSetGameSpeed), and as last applied.
std::atomic<int> g_utageSpeedPercent{100};
bool g_utageSpeedFromEnv = false;
float g_utageSpeedApplied = 1.0f;
Clock::time_point g_utageThermalSince{};
uint32_t g_utageThermalFrames = 0;
bool g_utageFpsSeen = false;
float g_utageFps = 60.0f;  // the game's last fps request
bool g_utageWaitSeen = false;
uint8_t g_utageWait = 0;   // and frame wait request
double g_utageGameSeconds = 0.0;
uint32_t g_utageFrames = 0;
Clock::time_point g_utageStatsStart{};
uint64_t g_utageStatsPaused = 0;  // HostSuspend::PausedNanoseconds() at g_utageStatsStart

float ReadF32(uint32_t addr) {
    const uint32_t bits = Memory::Read32(addr);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

void WriteF32(uint32_t addr, float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    Memory::Write32(addr, bits);
}

// sMain's deferred requests, as its own setters write them (frame wait 0x807168F0, fps 0x8071691C,
// max fps 0x80716944): its next timing pass applies them.
void UtageRequestWait(uint32_t main) {
    Memory::Write8(main + 0x82u, 1);
    Memory::Write8(main + 0x8Cu, (g_utageMode >= 0 ? g_utageMode : Mode()) != 0 ? 0 : g_utageWait);
}

// sMain::setFrameWait (0x8071696C): at once, restarting its frame clock.
void UtageSetWaitNow(uint32_t main, uint8_t wait) {
    Memory::Write8(main + 0x40u, wait);
    Memory::Write32(main + 0x54u, Memory::Read32(main + 0x4Cu));
    Memory::Write32(main + 0x50u, Memory::Read32(main + 0x48u));
    Memory::Write32(main + 0x5Cu, 0);
    Memory::Write32(main + 0x58u, 0);
    WriteF32(main + 0x68u, 1.0f);
    WriteF32(main + 0x78u, 0.0f);
}

// Game Speed: a 60 fps scene asks for 60 x speed. sMain moves the game by real time x its fps each
// frame, so the game runs that much faster while drawing keeps the display's pace (30 with 30
// FPS Lock, through mMaxFps). Cutscenes (30 fps with the frame wait, voices timed to it) keep
// their speed. The step cap grows with it, up to 6 steps a frame.
void UtageApplyFps(uint32_t main, int mode) {
    const bool cutscene = g_utageFps == 30.0f;
    const float speed = cutscene ? 1.0f : g_utageSpeedApplied;
    const float fps = cutscene ? 29.97f : g_utageFps * speed;
    Memory::Write8(main + 0x80u, 1);
    WriteF32(main + 0x84u, fps);
    Memory::Write8(main + 0x81u, 1);
    WriteF32(main + 0x88u, mode == 2 && !cutscene ? std::min(fps, 30.0f) : fps);
    WriteF32(main + 0x70u, cutscene ? 16.0f : std::min((mode != 0 ? 4.0f : 2.0f) * speed, 6.0f));  // mDeltaTimeLimite
    WriteF32(main + 0x6Cu, cutscene ? 10000.0f : 100.0f);                // mDeltaTimeBorder
}

// Game time per real second (1.00x is full speed), logged every 10 s.
void UtageSpeedStats(uint32_t main) {
    const Clock::time_point now = Clock::now();
    if (g_utageStatsStart == Clock::time_point{}) {
        g_utageStatsStart = now;
        g_utageStatsPaused = HostSuspend::PausedNanoseconds();
        return;
    }
    const float fps = ReadF32(main + 0x38u);
    // The last frame's step, in the scene's own time (a sped-up scene asks for fps x speed).
    const float sceneFps = g_utageFps == 30.0f ? fps : fps / g_utageSpeedApplied;
    if (sceneFps > 0.0f) g_utageGameSeconds += ReadF32(main + 0x68u) / sceneFps;
    ++g_utageFrames;
    // Time paused in the background is left out: it is neither game time nor real playing time.
    const double seconds = std::chrono::duration<double>(now - g_utageStatsStart).count()
            - (HostSuspend::PausedNanoseconds() - g_utageStatsPaused) / 1e9;
    if (seconds < 10.0) return;
    RT_LOGF(RT_TAG_VI, "utage speed: %.2fx, %.1f fps, scene %.0f fps%s, frameskip %s%s, game speed %d%%\n",
            g_utageGameSeconds / seconds, g_utageFrames / seconds, fps,
            Memory::Read8(main + 0x40u) != 0 ? " frame wait" : "", ModeName(Mode()),
            g_utageThermalLock ? " (30 fps: warm)" : "", static_cast<int>(g_utageSpeedApplied * 100.0f + 0.5f));
    g_utageGameSeconds = 0.0;
    g_utageFrames = 0;
    g_utageStatsStart = now;
    g_utageStatsPaused = HostSuspend::PausedNanoseconds();
}
} // namespace

// The fps manager's apply (0x800EA558), every frame before sMain's timing pass.
void UtageRefreshViews();  // the camera distance, below
void UtageLockOnUpdate();  // lock target, below

// GameActivity.nativeSetGameSpeed: Settings > Performance > Game Speed, in percent (100-200).
extern "C" void UtageSetGameSpeed(int percent) {
    if (!g_utageSpeedFromEnv) g_utageSpeedPercent.store(std::clamp(percent, 100, 200), std::memory_order_relaxed);
}

// Thermal Control: while the phone is warm (Thermal::Warm, ten seconds ahead) the player's mode
// becomes 30 FPS Lock, held kThermalHoldSeconds past the last warm reading so it does not flap.
// The game keeps full speed (2 steps a frame), the CPU and GPU do half the frames.
int UtageThermalMode(int mode) {
    if (++g_utageThermalFrames % kThermalCheckFrames == 0) {
        const Clock::time_point now = Clock::now();
        const bool warm = Thermal::Warm();
        if (warm && !g_utageThermalLock) {
            g_utageThermalLock = true;
            g_utageThermalSince = now;
            RT_LOGF(RT_TAG_VI, "thermal: warm, drawing at 30 fps (headroom %.2f)\n", Thermal::Headroom());
        } else if (warm) {
            g_utageThermalSince = now;
        } else if (g_utageThermalLock &&
                   now - g_utageThermalSince > std::chrono::duration<double>(kThermalHoldSeconds)) {
            g_utageThermalLock = false;
            RT_LOGF(RT_TAG_VI, "thermal: cooled down, back to the player's frame rate (headroom %.2f)\n",
                    Thermal::Headroom());
        }
    }
    return g_utageThermalLock ? 2 : mode;
}

extern "C" void UtageFpsApply_HLE(CpuContext* ctx) {
    UtageRefreshViews();
    UtageLockOnUpdate();
    Cheats::Apply();  // Settings > Cheats
    const uint32_t main = Memory::Read32(kUtageMainPtr);
    if (main == 0) return;
    const uint32_t manager = static_cast<uint32_t>(ctx->gpr[3]);
    const int mode = UtageThermalMode(Mode());
    bool apply = false;
    if (Memory::Read8(manager + 0x38u) == 1) {
        g_utageFps = ReadF32(manager + 0x3Cu);
        g_utageFpsSeen = true;
        Memory::Write8(manager + 0x38u, 0);
        apply = true;
    }
    if (mode != g_utageMode) {  // first frame, or changed in the in-game settings
        g_utageMode = mode;
        RT_LOGF(RT_TAG_VI, "utage speed: frameskip %s\n", ModeName(mode));
        apply = apply || g_utageFpsSeen;
        if (g_utageWaitSeen) UtageRequestWait(main);
    }
    static const bool s_speedEnv = [] {
        const char* env = std::getenv("UTAGE_GAME_SPEED");
        if (env == nullptr) return false;
        g_utageSpeedPercent.store(std::clamp(std::atoi(env), 100, 200), std::memory_order_relaxed);
        g_utageSpeedFromEnv = true;
        return true;
    }();
    (void)s_speedEnv;
    const float speed = static_cast<float>(g_utageSpeedPercent.load(std::memory_order_relaxed)) / 100.0f;
    if (speed != g_utageSpeedApplied) {
        g_utageSpeedApplied = speed;
        RT_LOGF(RT_TAG_VI, "utage speed: game speed %d%%\n", static_cast<int>(speed * 100.0f + 0.5f));
        apply = apply || g_utageFpsSeen;
    }
    if (apply) UtageApplyFps(main, mode);
    // A frame wait set some other way (MT's system properties at boot, the movie player's
    // setFrameWait): kept as the game's choice for Off, cleared for the other modes.
    if (mode != 0 && Memory::Read8(main + 0x40u) != 0 && Memory::Read8(main + 0x82u) == 0) {
        g_utageWait = 1;
        g_utageWaitSeen = true;
        UtageSetWaitNow(main, 0);
        RT_LOGF(RT_TAG_VI, "utage speed: frame wait cleared (scene %.0f fps)\n", ReadF32(main + 0x38u));
    }
    UtageSpeedStats(main);
    // UTAGE_SIM_FRAME_MS: a slow phone on a PC, this much longer every frame (testing the above).
    static const int simMs = [] {
        const char* env = std::getenv("UTAGE_SIM_FRAME_MS");
        return env != nullptr ? std::clamp(std::atoi(env), 0, 200) : 0;
    }();
    if (simMs > 0) std::this_thread::sleep_for(std::chrono::milliseconds(simMs));
}

// sMain::requestFrameWait (0x807168F0): the fps manager's frame wait apply and the movie player's
// restore go through it.
extern "C" void UtageMainRequestFrameWait_HLE(CpuContext* ctx) {
    if (static_cast<uint8_t>(ctx->gpr[4]) != g_utageWait || !g_utageWaitSeen) {
        RT_LOGF(RT_TAG_VI, "utage speed: the game asks for frame wait %u\n", static_cast<uint32_t>(ctx->gpr[4] & 0xFF));
    }
    g_utageWait = static_cast<uint8_t>(ctx->gpr[4]);
    g_utageWaitSeen = true;
    UtageRequestWait(static_cast<uint32_t>(ctx->gpr[3]));
}
PPC_NATIVE_OVERRIDE_VOID(800EA558, UtageFpsApply_HLE, (CpuContext* ctx), (ctx));
PPC_NATIVE_OVERRIDE_VOID(807168F0, UtageMainRequestFrameWait_HLE, (CpuContext* ctx), (ctx));

// Camera distance (Settings > Display > Camera Distance, Cheats::CameraDistance). MT's view update
// (calls at 0x80601F68 and 0x80602218; the view is r3 - 0x30: fovY +0xAC, aspect +0xB0, near +0xB4,
// far +0xB8) builds its projection with C_MTXPerspective (0x805B4A60), replaced here. The field of
// view is widened as if the eye stood k times farther back, tan(fov'/2) = k * tan(fov/2), and the
// eye stays where the game put it (moving it back went into walls). The game culls with
// this matrix, so the wider view stays filled. Cutscenes (the game asks for 30 fps) keep their framing.
// The view caches its projection (flag 0x80 at +0x70, set once built) and builds it again only when
// its lens changes, so a new distance clears that flag on the views seen here (once per change, from
// the per-frame fps apply above) and the next frame builds them with it. Battle views use the
// frustum form (C_MTXFrustum 0x805B49C0, flag 0x10), the rest the perspective one.
namespace {
uint32_t g_utageViews[8];
int g_utageViewCount = 0;
float g_utageViewK = 1.0f;

// The battle camera (uBasaraCamera) builds its own projection and hands it to the view, so these
// SDK builds only ever see menu views: the distance is applied where the view loads its matrix
// into GX instead (UtageWidenProjection, below). The views are still logged and refreshed.
bool UtageWidensView(uint32_t, float) { return false; }

void UtageRememberView(uint32_t lr, uint32_t matrix) {
    if (lr != 0x80601F6Cu && lr != 0x8060221Cu && lr != 0x80601F50u && lr != 0x80602200u) return;
    const uint32_t view = matrix - 0x30u;
    for (int i = 0; i < g_utageViewCount; ++i) {
        if (g_utageViews[i] == view) return;
    }
    g_utageViews[g_utageViewCount < 8 ? g_utageViewCount++ : 7] = view;
}

void UtageNoteView(uint32_t lr, const char* form, float a, float b, float n, float f, float k) {
    static uint32_t s_seen[24];
    static int s_count = 0;
    uint32_t bits;
    std::memcpy(&bits, &a, sizeof(bits));
    const uint32_t key = (lr & 0xFFFFu) ^ (bits >> 8);
    for (int i = 0; i < s_count; ++i) {
        if (s_seen[i] == key) return;
    }
    if (s_count == 24) return;
    s_seen[s_count++] = key;
    RT_LOGF(RT_TAG_VI, "camera: %s from %08X (%.3f, %.3f, near %.2f, far %.0f), scene %.0f fps, distance %.2f%s\n",
            form, lr, a, b, n, f, g_utageFps, k, UtageWidensView(lr, k) ? " widened" : "");
}
}  // namespace

// Once a frame (UtageFpsApply_HLE): a new camera distance rebuilds the views' projections.
void UtageRefreshViews() {
    const float k = Cheats::CameraDistance();
    if (k == g_utageViewK) return;
    g_utageViewK = k;
    int cleared = 0;
    for (int i = 0; i < g_utageViewCount; ++i) {
        uint32_t flags = 0;
        if (Memory::TryRead32(g_utageViews[i] + 0x70u, flags) && (flags & 0x80u) != 0 &&
            Memory::TryWrite32(g_utageViews[i] + 0x70u, flags & ~0x80u)) {
            ++cleared;
        }
    }
    RT_LOGF(RT_TAG_VI, "camera: distance %.2f, %d of %d views rebuild\n", k, cleared, g_utageViewCount);
}

// C_MTXFrustum(m, t, b, l, r, n, f) as the SDK computes it; a wider battle view scales t, b, l and r.
extern "C" void UtageMTXFrustum_HLE(CpuContext* ctx) {
    const uint32_t m = static_cast<uint32_t>(ctx->gpr[3]);
    float t = static_cast<float>(ctx->fpr[1].d), b = static_cast<float>(ctx->fpr[2].d);
    float l = static_cast<float>(ctx->fpr[3].d), r = static_cast<float>(ctx->fpr[4].d);
    const float n = static_cast<float>(ctx->fpr[5].d), f = static_cast<float>(ctx->fpr[6].d);
    const float k = Cheats::CameraDistance();
    UtageRememberView(ctx->lr, m);
    UtageNoteView(ctx->lr, "frustum", r - l, t - b, n, f, k);
    if (UtageWidensView(ctx->lr, k)) {
        const float s = std::min(k, 2.0f);
        t *= s;
        b *= s;
        l *= s;
        r *= s;
    }
    const float two_n = 2.0f * n;
    const float w = 1.0f / (r - l), h = 1.0f / (t - b), depth = 1.0f / (f - n);
    const float out[16] = {two_n * w, 0.0f, w * (r + l), 0.0f, 0.0f, two_n * h, h * (t + b), 0.0f,
                           0.0f, 0.0f, -n * depth, depth * -(f * n), 0.0f, 0.0f, -1.0f, 0.0f};
    for (int i = 0; i < 16; ++i) {
        uint32_t bits;
        std::memcpy(&bits, &out[i], sizeof(bits));
        Memory::Write32(m + 4u * static_cast<uint32_t>(i), bits);
    }
}
PPC_NATIVE_OVERRIDE_VOID(805B49C0, UtageMTXFrustum_HLE, (CpuContext* ctx), (ctx));

extern "C" void UtageMTXPerspective_HLE(CpuContext* ctx) {
    const uint32_t m = static_cast<uint32_t>(ctx->gpr[3]);
    const float fov = static_cast<float>(ctx->fpr[1].d);
    const float aspect = static_cast<float>(ctx->fpr[2].d);
    const float n = static_cast<float>(ctx->fpr[3].d);
    const float f = static_cast<float>(ctx->fpr[4].d);
    constexpr float kDegToRad = 0.01745329238f;  // the SDK's constant (SDA2 0x808FE2AC)
    float fovY = fov;
    const float k = Cheats::CameraDistance();
    UtageRememberView(ctx->lr, m);
    UtageNoteView(ctx->lr, "perspective", fov, aspect, n, f, k);
    if (UtageWidensView(ctx->lr, k) && fov > 1.0f && fov < 150.0f) {
        const float wide = 2.0f * std::atan(std::tan(fov * 0.5f * kDegToRad) * k) / kDegToRad;
        fovY = std::min(wide, 120.0f);
    }
    // C_MTXPerspective as the SDK computes it (Mtx44, row-major).
    const float cot = 1.0f / static_cast<float>(std::tan(static_cast<double>(kDegToRad * (0.5f * fovY))));
    const float depth = 1.0f / (f - n);
    const float out[16] = {cot / aspect, 0.0f, 0.0f, 0.0f, 0.0f, cot, 0.0f, 0.0f,
                           0.0f, 0.0f, -n * depth, depth * -(f * n), 0.0f, 0.0f, -1.0f, 0.0f};
    for (int i = 0; i < 16; ++i) {
        uint32_t bits;
        std::memcpy(&bits, &out[i], sizeof(bits));
        Memory::Write32(m + 4u * static_cast<uint32_t>(i), bits);
    }
}
PPC_NATIVE_OVERRIDE_VOID(805B4A60, UtageMTXPerspective_HLE, (CpuContext* ctx), (ctx));

// GXSetProjection (gx_transform.cpp) with a perspective matrix: MT's view loads its projection
// from 0x80602218 (return address 0x80602234), the battle camera's included (aspect 1.905 on PC).
// Widened as if the eye stood k times farther back: x and y scale over k. Cutscenes keep theirs.
// The game still culls with its own frustum, so things at the new edges can appear late.

// Lock target (R3, the touch LOCK button; BASARA_LOCKON=1 forces it on for a PC test): the camera
// turns toward an enemy general or a named enemy officer (never a plain soldier) by moving the right stick as a
// player would, so the game's own camera (its shakes, zooms, collision) does the turning and the
// player's own right stick always wins. From battle memory dumps: sUnit (pointer at 0x808F4020)
// keeps 64 move lines of 0x18 bytes from +0x20, each with its first unit at +0xC, and units chain
// through +0xC. Line 12 holds the generals (uPlNNN: the player and the computer's), line 20 the
// soldiers and captains (uEmNN), line 38 the player camera (uPlCamera: eye +0x30, look-at +0x50,
// player +0x2E8). Every unit's position is at +0x30. Line 10 holds every actor's uActorInfo (its unit at
// +0x1C0): a named officer's carries its name index at +0x1D8 (6, 7, 8.. in order; -1 for a plain
// soldier) and a general's the flag 0x2000 at +0x248, which is what the game's own life gauges read
// (0x802EEF08) to keep a named enemy's gauge up at any distance. Its army (cArmy, +0x280) keeps
// the side it fights on at +0x128: the player's 0, and in a three-way battle (Matsunaga against
// Date and Takeda) the other armies 1 and 2. Units on the player's side are never locked.
namespace {
constexpr uint32_t kUtageUnitPtr = 0x808F4020u;
constexpr int kLineActorInfo = 10, kLineGenerals = 12, kLineEnemies = 20, kLineCamera = 38;
constexpr float kLockRange = 3500.0f;  // battle units: a character runs about 500 a second
std::atomic<bool> g_lockRequested{false};
std::atomic<float> g_lockStickX{0.0f};
std::atomic<float> g_playerStickX{0.0f};  // the player's own right stick, for the flick that switches targets
bool g_lockFresh = true;                  // no target yet since the lock went on: a wider cone
bool g_lockTurning = false;               // turning toward the target (it left the comfortable middle)
float g_lockStickSmooth = 0.0f;
bool g_utageInBattle = false;  // the player camera exists (camera zoom applies only then)
uint32_t g_fovCamera = 0;      // the camera whose field of view the distance widened
float g_fovBase = 0.0f;        // its field of view as the game set it
float g_fovWritten = 0.0f;     // and as written here
uint32_t g_lockTarget = 0;
float g_lockSign = -1.0f;  // with the game's default camera (both PC tests); learned below all the same
int g_lockProbe = 0;
bool g_lockSignKnown = false;  // a probe showed which way the stick turns the camera
float g_lockProbeYaw = 0.0f;   // the camera heading when the probe began
float g_lockProbeDir = 0.0f;   // and the stick direction it holds
float g_lockTurnDir = 0.0f;    // the way the camera is turning (kept while the target is behind)

struct LockVec {
    float x, y, z;
};

LockVec UnitPos(uint32_t unit, uint32_t offset = 0x30u) {
    return {ReadF32(unit + offset), ReadF32(unit + offset + 4u), ReadF32(unit + offset + 8u)};
}

// An MT object's class: vtable slot 6 is getDTI, a lis/addi/blr returning its MtDTI, whose +4 is
// the class name. Cached per vtable.
const std::string& UnitClass(uint32_t obj) {
    static std::unordered_map<uint32_t, std::string> s_names;
    static const std::string s_none;
    uint32_t vt = 0;
    if (obj == 0 || !Memory::TryRead32(obj, vt) || vt < 0x80000000u) return s_none;
    if (const auto it = s_names.find(vt); it != s_names.end()) return it->second;
    std::string name;
    uint32_t fn = 0, i0 = 0, i1 = 0, i2 = 0, namePtr = 0;
    if (Memory::TryRead32(vt + 0x18u, fn) && Memory::TryRead32(fn, i0) && Memory::TryRead32(fn + 4u, i1) &&
        Memory::TryRead32(fn + 8u, i2) && (i0 >> 26) == 15u && (i1 >> 26) == 14u && i2 == 0x4E800020u) {
        const uint32_t dti = ((i0 & 0xFFFFu) << 16) +
                             static_cast<uint32_t>(static_cast<int32_t>(static_cast<int16_t>(i1 & 0xFFFFu)));
        if (Memory::TryRead32(dti + 4u, namePtr)) {
            for (uint32_t k = 0; k < 48; k += 4) {
                uint32_t word = 0;
                if (!Memory::TryRead32(namePtr + k, word)) break;
                bool end = false;
                for (int b = 3; b >= 0 && !end; --b) {
                    const char c = static_cast<char>((word >> (8 * b)) & 0xFFu);
                    if (c == 0) end = true; else name.push_back(c);
                }
                if (end) break;
            }
        }
    }
    return s_names.emplace(vt, std::move(name)).first->second;
}

bool ClassIs(uint32_t obj, const char* prefix) {
    return UnitClass(obj).rfind(prefix, 0) == 0;
}

uint32_t LineHead(uint32_t unitSystem, int line) {
    uint32_t head = 0;
    Memory::TryRead32(unitSystem + 0x20u + 0x18u * static_cast<uint32_t>(line) + 0xCu, head);
    return head;
}

template <typename F>
void ForEachUnit(uint32_t unitSystem, int line, F&& visit) {
    uint32_t unit = LineHead(unitSystem, line);
    for (int n = 0; unit != 0 && n < 512; ++n) {
        visit(unit);
        if (!Memory::TryRead32(unit + 0xCu, unit)) break;
    }
}

bool IsGeneral(uint32_t unit, uint32_t player) {
    if (unit == player) return false;
    const std::string& c = UnitClass(unit);
    return c.size() == 6 && c.rfind("uPl", 0) == 0;  // uPlNNN, not uPlCamera or uPlWep
}

// This frame's actors: the named enemies worth a lock (officers with a name, general-class units)
// and the units on the player's side.
struct LockActors {
    uint32_t named[64];
    uint32_t friends[128];
    int namedCount = 0, friendCount = 0;
    bool sideKnown = false;
    uint32_t playerSide = 0;
    bool Named(uint32_t unit) const { return std::find(named, named + namedCount, unit) != named + namedCount; }
    bool Friend(uint32_t unit) const { return std::find(friends, friends + friendCount, unit) != friends + friendCount; }
};

bool ActorSide(uint32_t info, uint32_t& side) {
    uint32_t army = 0;
    return Memory::TryRead32(info + 0x280u, army) && army != 0 && ClassIs(army, "cArmy") &&
           Memory::TryRead32(army + 0x128u, side);
}

LockActors CollectActors(uint32_t unitSystem, uint32_t player) {
    LockActors actors;
    ForEachUnit(unitSystem, kLineActorInfo, [&](uint32_t info) {
        uint32_t unit = 0;
        if (!actors.sideKnown && Memory::TryRead32(info + 0x1C0u, unit) && unit == player && player != 0 &&
            ClassIs(info, "uActorInfo")) {
            actors.sideKnown = ActorSide(info, actors.playerSide);
        }
    });
    ForEachUnit(unitSystem, kLineActorInfo, [&](uint32_t info) {
        uint32_t unit = 0, index = 0, flags = 0, side = 0;
        if (!Memory::TryRead32(info + 0x1C0u, unit) || unit == 0 || unit == player || !ClassIs(info, "uActorInfo")) return;
        if (actors.sideKnown && ActorSide(info, side) && side == actors.playerSide) {
            if (actors.friendCount < 128) actors.friends[actors.friendCount++] = unit;
            return;
        }
        if (actors.namedCount < 64 && Memory::TryRead32(info + 0x1D8u, index) && Memory::TryRead32(info + 0x248u, flags) &&
            (static_cast<int32_t>(index) >= 0 || (flags & 0x2000u) != 0)) {
            actors.named[actors.namedCount++] = unit;
        }
    });
    return actors;
}

void LockOff() {
    g_lockStickX.store(0.0f, std::memory_order_relaxed);
    g_lockTarget = 0;
    g_lockFresh = true;
    g_lockTurning = false;
    g_lockStickSmooth = 0.0f;
    g_lockTurnDir = 0.0f;
}
}  // namespace

// extern "C": android_bridge.cpp declares it inside its JNI extern "C" block.
extern "C" bool UtageLockOnToggle() {
    const bool on = !g_lockRequested.load(std::memory_order_relaxed);
    g_lockRequested.store(on, std::memory_order_relaxed);
    RT_LOGF(RT_TAG_VI, "lock: %s\n", on ? "on" : "off");
    return on;
}

float UtageLockOnStickX() { return g_lockStickX.load(std::memory_order_relaxed); }
void UtageLockOnPlayerStick(float x) { g_playerStickX.store(x, std::memory_order_relaxed); }

// Once a frame (UtageFpsApply_HLE, game thread).
void UtageLockOnUpdate() {
    static const bool s_forced = std::getenv("BASARA_LOCKON") != nullptr;
    if (s_forced) g_lockRequested.store(true, std::memory_order_relaxed);
    {
        uint32_t sys = 0;
        const uint32_t camera = Memory::TryRead32(kUtageUnitPtr, sys) && sys != 0 ? LineHead(sys, kLineCamera) : 0u;
        g_utageInBattle = camera != 0 && UnitClass(camera) == "uPlCamera";
        // Camera distance: the player camera's own field of view (uCamera mFov, +0x2C, degrees; 40
        // in battle), widened as if the eye stood k times farther back. Its projection (+0x100), the
        // culling and every screen position the game derives from it (enemy names, markers) follow,
        // where widening only the GX projection left the names behind. A value that differs from
        // the one written here is the game's own new one.
        if (g_utageInBattle) {
            const float current = ReadF32(camera + 0x2Cu);
            if (camera != g_fovCamera) {
                g_fovCamera = camera;
                g_fovBase = current;
            } else if (current != g_fovWritten) {
                g_fovBase = current;
            }
            const float k = Cheats::CameraDistance();
            float want = g_fovBase;
            if (k > 1.0f && g_utageFps != 30.0f && g_fovBase > 1.0f && g_fovBase < 150.0f) {
                constexpr float kDeg = 0.01745329252f;
                want = std::min(120.0f, 2.0f * std::atan(std::tan(g_fovBase * 0.5f * kDeg) * std::min(k, 2.0f)) / kDeg);
            }
            if (want != current) {
                uint32_t bits;
                std::memcpy(&bits, &want, sizeof(bits));
                Memory::TryWrite32(camera + 0x2Cu, bits);
                static float s_logged = 0.0f;
                if (s_logged != want) {
                    s_logged = want;
                    RT_LOGF(RT_TAG_VI, "camera: battle field of view %.1f -> %.1f (distance %.2f)\n", g_fovBase, want, k);
                }
            }
            g_fovWritten = want;
        } else {
            g_fovCamera = 0;
        }
    }
    if (!g_lockRequested.load(std::memory_order_relaxed) || g_utageFps == 30.0f) {  // cutscenes: hands off
        LockOff();
        return;
    }
    uint32_t sys = 0;
    if (!Memory::TryRead32(kUtageUnitPtr, sys) || sys == 0) return LockOff();
    const uint32_t cam = LineHead(sys, kLineCamera);
    if (cam == 0 || UnitClass(cam) != "uPlCamera") return LockOff();  // not in a battle
    uint32_t player = 0;
    Memory::TryRead32(cam + 0x2E8u, player);
    const LockVec eye = UnitPos(cam, 0x30u), look = UnitPos(cam, 0x50u);
    const LockVec me = (player != 0 && ClassIs(player, "uPl")) ? UnitPos(player) : look;
    float fx = look.x - eye.x, fz = look.z - eye.z;
    const float flen = std::sqrt(fx * fx + fz * fz);
    if (!(flen > 1.0f)) return LockOff();
    fx /= flen;
    fz /= flen;
    const auto distance = [&](const LockVec& t) {
        const float dx = t.x - me.x, dz = t.z - me.z;
        return std::sqrt(dx * dx + dz * dz);
    };
    // Framed from the player, as Elden Ring frames a lock: the camera should look along
    // player -> target, with the target anywhere in a comfortable middle of the screen.
    const auto angleTo = [&](const LockVec& t) {  // signed, from the view's heading to player -> target
        const float dx = t.x - me.x, dz = t.z - me.z;
        return std::atan2(fx * dz - fz * dx, fx * dx + fz * dz);
    };
    const auto alive = [&](uint32_t unit) {
        const LockVec t = UnitPos(unit);
        return t.x != 0.0f || t.z != 0.0f;
    };
    // A flick of the player's own right stick (from rest to past 0.8) moves the lock to the next
    // enemy on that side.
    static bool s_flickArmed = true;
    int flick = 0;
    const float own = g_playerStickX.load(std::memory_order_relaxed);
    if (std::fabs(own) < 0.3f) {
        s_flickArmed = true;
    } else if (s_flickArmed && std::fabs(own) > 0.8f) {
        s_flickArmed = false;
        flick = own > 0.0f ? 1 : -1;
    }
    const LockActors actors = CollectActors(sys, player);
    // The target stays until it is defeated (unlinked from its line, its slot reused) or far away.
    if (g_lockTarget != 0) {
        bool present = false;
        ForEachUnit(sys, kLineGenerals, [&](uint32_t u) { present = present || (u == g_lockTarget && IsGeneral(u, player) && !actors.Friend(u)); });
        ForEachUnit(sys, kLineEnemies, [&](uint32_t u) { present = present || (u == g_lockTarget && actors.Named(u)); });
        if (!present || !alive(g_lockTarget) || distance(UnitPos(g_lockTarget)) > kLockRange * 1.5f) {
            g_lockTarget = 0;
            g_lockTurning = false;
        }
    }
    // Generals and named officers only (the user: plain soldiers are left alone), a general
    // preferred unless an officer is clearly nearer.
    const auto pick = [&](float cone, float side, float fromAngle) {
        uint32_t best = 0;
        float bestScore = 1e30f;
        const auto consider = [&](uint32_t u, float rank) {
            if (u == g_lockTarget || !alive(u)) return;
            const LockVec t = UnitPos(u);
            const float d = distance(t), a = angleTo(t);
            if (d > kLockRange || std::fabs(a) > cone) return;
            float score = rank + d + 600.0f * std::fabs(a);  // near and near the middle
            if (side != 0.0f) {  // a flick: the next one on that side of the current target
                const float delta = (a - fromAngle) * side;
                if (delta < 0.05f) return;
                score = rank + 1000.0f * delta + 0.2f * d;
            }
            if (score < bestScore) {
                bestScore = score;
                best = u;
            }
        };
        ForEachUnit(sys, kLineGenerals, [&](uint32_t u) { if (IsGeneral(u, player) && !actors.Friend(u)) consider(u, 0.0f); });
        ForEachUnit(sys, kLineEnemies, [&](uint32_t u) { if (actors.Named(u) && ClassIs(u, "uEm")) consider(u, 800.0f); });
        return best;
    };
    if (flick != 0 && g_lockTarget != 0) {
        // The stick turns the view toward angles of sign g_lockSign, so that is "right" here.
        if (const uint32_t next = pick(3.2f, static_cast<float>(flick) * g_lockSign, angleTo(UnitPos(g_lockTarget)))) {
            g_lockTarget = next;
            g_lockTurning = true;
            RT_LOGF(RT_TAG_VI, "lock: switched to %s at %.0f\n", UnitClass(next).c_str(), distance(UnitPos(next)));
        }
    }
    if (g_lockTarget == 0) {
        // A new lock looks a little wider; after a target falls only enemies already in front are
        // taken, so the camera never swings around to one behind.
        g_lockTarget = pick(g_lockFresh ? 1.75f : 1.2f, 0.0f, 0.0f);
        if (g_lockTarget == 0) {
            g_lockStickSmooth = 0.0f;
            g_lockTurning = false;
            g_lockStickX.store(0.0f, std::memory_order_relaxed);
            static int s_waitFrames = 0;
            if (++s_waitFrames >= 300) {
                s_waitFrames = 0;
                float nearest = 1e30f;
                for (int n = 0; n < actors.namedCount; ++n) nearest = std::min(nearest, distance(UnitPos(actors.named[n])));
                RT_LOGF(RT_TAG_VI, "lock: waiting, %d named enemies (nearest %.0f), %d on the player's side %u%s\n",
                        actors.namedCount, actors.namedCount ? nearest : 0.0f, actors.friendCount, actors.playerSide,
                        actors.sideKnown ? "" : " (side unknown)");
            }
            return;  // armed: waits for an enemy in front
        }
        g_lockFresh = false;
        RT_LOGF(RT_TAG_VI, "lock: target %s at %.0f (%d named enemies, %d on the player's side %u%s)\n",
                UnitClass(g_lockTarget).c_str(), distance(UnitPos(g_lockTarget)), actors.namedCount, actors.friendCount,
                actors.playerSide, actors.sideKnown ? "" : ", side unknown");
    }
    const LockVec t = UnitPos(g_lockTarget);
    const float angle = angleTo(t), d = distance(t);
    // Turn only when the target leaves a comfortable middle, and stop once it is well inside it.
    // Up close (sword range) the middle is much wider: a general circling the player swung the
    // camera back and forth.
    const bool close = d < 450.0f;
    const float outer = close ? 0.75f : 0.32f;  // about 43 / 18 degrees
    const float inner = close ? 0.35f : 0.17f;  // about 20 / 10 degrees (7 kept it steering for seconds)
    if (std::fabs(angle) > outer) g_lockTurning = true;
    else if (std::fabs(angle) < inner) g_lockTurning = false;
    float want = 0.0f;
    if (g_lockTurning) {
        const float mag = std::clamp(0.4f + (std::fabs(angle) - inner) * 1.2f, 0.4f, close ? 0.55f : 0.85f);
        // Straight behind, the angle flips between +180 and -180 as the target moves: the turn
        // keeps its way until the target is back past the side (PC test: the stick flipped).
        float dir = angle > 0.0f ? 1.0f : -1.0f;
        if (std::fabs(angle) > 2.4f && g_lockTurnDir != 0.0f) dir = g_lockTurnDir;
        g_lockTurnDir = dir;
        want = dir * mag * g_lockSign;
    } else {
        g_lockTurnDir = 0.0f;
    }
    // Eased: the stick moves a third of the way each frame, and lets go at once.
    g_lockStickSmooth = want == 0.0f ? 0.0f : g_lockStickSmooth + (want - g_lockStickSmooth) * 0.33f;
    const float stick = g_lockStickSmooth;
    // Which way the stick turns this camera is learned, not assumed (the game has an invert
    // option): from the camera's own heading over 16 frames of steering one way. The angle to the
    // target was a poor witness, as the player and the target move too (PC test: a wrong flip).
    if (!g_lockSignKnown) {
        const float yaw = std::atan2(fz, fx);
        const float dir = want > 0.0f ? 1.0f : want < 0.0f ? -1.0f : 0.0f;
        if (dir == 0.0f) {
            g_lockProbe = 0;
        } else if (g_lockProbe == 0 || dir != g_lockProbeDir) {
            g_lockProbe = 1;
            g_lockProbeYaw = yaw;
            g_lockProbeDir = dir;
        } else if (++g_lockProbe == 16) {
            float turned = yaw - g_lockProbeYaw;
            if (turned > 3.14159265f) turned -= 6.2831853f;
            if (turned < -3.14159265f) turned += 6.2831853f;
            g_lockProbe = 0;
            if (std::fabs(turned) > 0.06f) {
                // A positive angle closes as the heading grows, so g_lockSign is the stick
                // direction that grows it.
                const float sign = turned * dir > 0.0f ? 1.0f : -1.0f;
                if (sign != g_lockSign) RT_LOGF(RT_TAG_VI, "lock: the stick turns the other way here\n");
                g_lockSign = sign;
                g_lockSignKnown = true;
            }
        }
    }
    g_lockStickX.store(stick, std::memory_order_relaxed);
    static int s_logFrames = 0;
    if (++s_logFrames >= 120) {
        s_logFrames = 0;
        RT_LOGF(RT_TAG_VI, "lock: %s at %.0f, %.1f degrees off, stick %.2f%s\n", UnitClass(g_lockTarget).c_str(), d,
                angle * 57.2958f, stick, close ? " (close)" : "");
    }
}

void UtageWidenProjection(float* m, uint32_t lr) {
    const float k = Cheats::CameraDistance();
    // Battle only (the player camera exists): menus draw their 3D backgrounds through the same view,
    // and a wider one showed black bands above and below them.
    // Off: the battle camera's own field of view is widened instead (UtageLockOnUpdate), so the
    // names and markers the game places from it follow the picture. Kept for reference.
    if (true || k <= 1.0f || lr != 0x80602234u || g_utageFps == 30.0f || !g_utageInBattle) return;
    const float s = 1.0f / std::min(k, 2.0f);
    m[0] *= s;
    m[1] *= s;
    m[2] *= s;
    m[4] *= s;
    m[5] *= s;
    m[6] *= s;
    static float s_logged = 0.0f;
    if (s_logged != k) {
        s_logged = k;
        RT_LOGF(RT_TAG_VI, "camera: battle view widened, distance %.2f (aspect %.3f)\n", k,
                m[0] != 0.0f ? m[5] / m[0] : 0.0f);
    }
}

