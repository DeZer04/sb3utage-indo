#include "cheats.h"

#include "memory.h"
#include "netplay_session.h"
#include "ppc_runtime.h"
#include "runtime_config.h"
#include "runtime_log.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cstring>

namespace Cheats {
namespace {

// Read on the guest thread, set from Config.toml at start and from the launcher (JNI, UI thread).
std::atomic<int32_t> g_money{RuntimeConfigFile::CheatMoneyMode()};
std::atomic<uint32_t> g_amount{std::min(RuntimeConfigFile::CheatMoneyAmount(), kMaxMoney)};
// The last Once request seen; one at start is already old (it was applied in an earlier run).
std::atomic<uint32_t> g_onceSeq{RuntimeConfigFile::CheatMoneyOnceSeq()};
std::atomic<bool> g_oncePending{false};
std::atomic<bool> g_infiniteHp{RuntimeConfigFile::CheatInfiniteHp()};
std::atomic<bool> g_infiniteBasara{RuntimeConfigFile::CheatInfiniteBasara()};
std::atomic<bool> g_unlockAll{RuntimeConfigFile::CheatUnlockAll()};

} // namespace

bool Available() {
    return !NetplaySession::Active();
}

namespace {
float ClampDistance(float distance) {
    return distance >= 1.0f && distance <= 2.0f ? distance : 1.0f;
}
std::atomic<float> g_cameraDistance{[] {
    const char* env = std::getenv("BASARA_CAMERA_DISTANCE");
    return ClampDistance(env != nullptr ? std::strtof(env, nullptr) : RuntimeConfigFile::CheatCameraDistance());
}()};
} // namespace

float CameraDistance() { return Available() ? g_cameraDistance.load(std::memory_order_relaxed) : 1.0f; }
void SetCameraDistance(float distance) { g_cameraDistance = ClampDistance(distance); }

void SetFromLauncher(int32_t money, uint32_t amount, uint32_t onceSeq, bool infiniteHp, bool infiniteBasara,
                     bool unlockAll) {
    g_money = std::clamp<int32_t>(money, kMoneyOff, kMoneyOnce);
    g_amount = std::min(amount, kMaxMoney);
    g_infiniteHp = infiniteHp;
    g_infiniteBasara = infiniteBasara;
    g_unlockAll = unlockAll;
    if (g_onceSeq.exchange(onceSeq) != onceSeq && money == kMoneyOnce) {
        g_oncePending = true;
    }
}

// Sengoku Basara 3 Utage (S3HJ08), from the community's Gecko code lists (A9VG thread 2071373, ameblo
// tales-of-bleach). Their addresses are a real Wii's; this runtime's MEM1 heap holds the same objects
// 0x2000 higher (battle memory dumps), so each base is tried at +0x2000, then as listed, and used only
// when what it holds makes sense.
// - P1's battle status (pointer at 0x810468B0, P2's at +4): HP at +0x204 of max +0x208, the BASARA
//   gauge at +0x220 of max +0x224 (func_8014A4F4 adds to it and clamps at the max).
// - The save's game data: money at 0x811AA454; open generals 0x811AA668, extra costumes 0x811AA64C,
//   Japan game destinations 0x811AA694 (bit masks); gallery movies 0x811AA830/834, music 0x811AA81C/820
//   and the u16 at 0x811AA826, titles 0x811AA808/80C; the 30 generals' levels at 0x811AB260, 0x60 apart.
namespace {
constexpr uint32_t kUtageShifts[] = {0x2000u, 0u};
constexpr uint32_t kUtageStatusPtr = 0x810468B0u;
constexpr uint32_t kUtageMoney = 0x811AA454u;

bool InGuestHeap(uint32_t p) { return p >= 0x80000000u && p < 0x81800000u - 0x400u; }

uint32_t UtageStatus() {
    for (const uint32_t shift : kUtageShifts) {
        uint32_t st = 0, hp = 0, hpMax = 0, gaugeMax = 0;
        if (Memory::TryRead32(kUtageStatusPtr + shift, st) && InGuestHeap(st) && Memory::TryRead32(st + 0x204u, hp) &&
            Memory::TryRead32(st + 0x208u, hpMax) && Memory::TryRead32(st + 0x224u, gaugeMax) && hpMax > 0 &&
            hpMax <= 10000000u && hp <= hpMax && gaugeMax > 0 && gaugeMax <= 10000000u) {
            return st;
        }
    }
    return 0;
}

// The shift the save's game data sits at, or ~0 while no save is loaded (every general's level 1..200).
uint32_t UtageGameDataShift() {
    for (const uint32_t shift : kUtageShifts) {
        bool ok = true;
        for (uint32_t i = 0; i < 30u && ok; ++i) {
            uint32_t level = 0;
            ok = Memory::TryRead32(0x811AB260u + shift + i * 0x60u, level) && level >= 1u && level <= 200u;
        }
        uint32_t generals = 0;
        if (ok && Memory::TryRead32(0x811AA668u + shift, generals) && generals != 0) return shift;
    }
    return ~0u;
}

void OrBits(uint32_t addr, uint32_t bits, uint32_t& opened) {
    uint32_t value = 0;
    if (Memory::TryRead32(addr, value) && (value | bits) != value && Memory::TryWrite32(addr, value | bits)) ++opened;
}

void LogOnce(bool& done, const char* what, uint32_t value) {
    if (!done) {
        done = true;
        RT_LOGF(RT_TAG_OS, "cheats: %s (%u)\n", what, value);
    }
}
}  // namespace

// Once a frame (Utage's fps manager hook, guest thread).
void Apply() {
    if (!Available()) {
        return;
    }
    static uint32_t s_frame = 0;
    static uint32_t s_shift = ~0u;
    ++s_frame;
    const int32_t money = g_money.load(std::memory_order_relaxed);
    const bool unlockAll = g_unlockAll.load(std::memory_order_relaxed);
    // The save's game data: looked for twice a second (a save loaded later puts it in place).
    if ((money != kMoneyOff || unlockAll || g_oncePending.load(std::memory_order_relaxed)) && s_frame % 30u == 1u) {
        s_shift = UtageGameDataShift();
    }
    if (s_shift != ~0u) {
        const uint32_t amount = g_amount.load(std::memory_order_relaxed);
        const uint32_t moneyAddr = kUtageMoney + s_shift;
        static bool s_loggedMoney = false, s_loggedOnce = false;
        uint32_t before = 0;
        if (money == kMoneyInfinite) {
            if (Memory::TryRead32(moneyAddr, before) && before != amount && Memory::TryWrite32(moneyAddr, amount)) {
                LogOnce(s_loggedMoney, "infinite money holds the amount", amount);
            }
        } else if (g_oncePending.exchange(false)) {
            if (Memory::TryWrite32(moneyAddr, amount)) LogOnce(s_loggedOnce, "money set once", amount);
        }
        if (unlockAll && s_frame % 60u == 1u) {
            uint32_t opened = 0;
            OrBits(0x811AA668u + s_shift, 0x3FFFFFFFu, opened);  // generals
            OrBits(0x811AA64Cu + s_shift, 0x3FFFFFFFu, opened);  // extra costumes
            OrBits(0x811AA694u + s_shift, 0x7FFFFFFFu, opened);  // Japan game destinations
            OrBits(0x811AA830u + s_shift, 0xFFFFFFFFu, opened);  // gallery: movies
            OrBits(0x811AA834u + s_shift, 0x1FFFFFFFu, opened);
            OrBits(0x811AA81Cu + s_shift, 0xFFFFFFFFu, opened);  // music
            OrBits(0x811AA820u + s_shift, 0xFFFFFFFFu, opened);
            OrBits(0x811AA824u + s_shift, 0x0000FFFFu, opened);  // the u16 at 0x811AA826
            OrBits(0x811AA808u + s_shift, 0xFFFFFFFFu, opened);  // titles
            OrBits(0x811AA80Cu + s_shift, 0x03FFFFFFu, opened);
            static int s_logged = 0;
            if (opened != 0 && s_logged < 4) {
                ++s_logged;
                RT_LOGF(RT_TAG_OS, "cheats: unlock all opened %u masks\n", opened);
            }
        }
    }
    const bool hp = g_infiniteHp.load(std::memory_order_relaxed);
    const bool basara = g_infiniteBasara.load(std::memory_order_relaxed);
    if (!hp && !basara) {
        return;
    }
    const uint32_t st = UtageStatus();
    if (st == 0) {
        return;
    }
    if (hp) {
        static bool s_logged = false;
        uint32_t now = 0, max = 0;
        if (Memory::TryRead32(st + 0x204u, now) && Memory::TryRead32(st + 0x208u, max) && now < max &&
            Memory::TryWrite32(st + 0x204u, max)) {
            LogOnce(s_logged, "infinite HP refilled", max - now);
        }
    }
    if (basara) {
        // Full as soon as it grows, as the Gecko code makes the game's own add do: using an art still
        // empties it, so arts run their course.
        static uint32_t s_status = 0, s_last = 0;
        static bool s_logged = false;
        uint32_t gauge = 0, max = 0;
        if (Memory::TryRead32(st + 0x220u, gauge) && Memory::TryRead32(st + 0x224u, max)) {
            if (st == s_status && gauge > s_last && gauge < max && Memory::TryWrite32(st + 0x220u, max)) {
                LogOnce(s_logged, "infinite BASARA filled the gauge", max);
                gauge = max;
            }
            s_status = st;
            s_last = gauge;
        }
    }
}
} // namespace Cheats
