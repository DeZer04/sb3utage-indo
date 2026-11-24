#include "frame_input.h"
#include "hle_stubs.h"
#include "memory.h"
#include "hle/controller_status_contract.h"
#include "wii_remote_input.h"

#include "runtime_log.h"
#include "virtual_remote.h"

#include <atomic>
#include <cstdint>
#include <dolphin/pad.h>

void NandQueueIosCallback(uint32_t callbackPtr, int32_t result, uint32_t callbackArg);

namespace {

constexpr uint32_t kDefaultWorkMemSize = 0x20000;
constexpr uint8_t kDefaultDpdSensitivity = 3;
constexpr int32_t kStatusOk = 0;

struct WpadStubState {
    bool initSubRan = false;
    bool simpleSyncActive = false;
    uint32_t syncDeviceCallback = 0;
    uint32_t workMemSize = kDefaultWorkMemSize;
    uint8_t dpdSensitivity = kDefaultDpdSensitivity;
    WpadContract::State contract{};
};

WpadStubState g_state{};

void InvokeWpadCallback(uint32_t callback, uint32_t chan, int32_t result)
{
    if (callback == 0) {
        return;
    }
    if (!TranslatedFunctionRegistry::FindByAddressPtr(callback)) {
        return;
    }
    auto& cpu = GetPersistentCpuContext();
    cpu.gpr[3] = chan;
    cpu.gpr[4] = static_cast<uint32_t>(result);
    InvokeIndirectCpu(callback, &cpu);
}

int32_t InitializeWpadLibrary()
{
    g_state.contract.Initialize();
    return kStatusOk;
}

// The async WPAD entry points all report their outcome to the guest callback and
// then return the same value.
int32_t CompleteWpadRequest(uint32_t chan, uint32_t callback, int32_t result)
{
    InvokeWpadCallback(callback, chan, result);
    return result;
}

} // namespace

extern "C" int32_t WPADGetStatus_HLE()
{
    // RVL::WPADGetStatus takes no channel arg; it reports global WUD library state.
    // Reading r3 here would leak a caller's stale register value into the result.
    return g_state.contract.GetLibraryStatus();
}

extern "C" uint32_t WPADGetDpdSensitivity_HLE()
{
    return static_cast<uint32_t>(g_state.dpdSensitivity);
}

extern "C" int32_t WPADInitSub_HLE()
{
    if (!g_state.initSubRan) {
        g_state.initSubRan = true;
        return InitializeWpadLibrary();
    }
    return kStatusOk;
}

extern "C" int32_t WPADInit_HLE()
{
    return InitializeWpadLibrary();
}
// Basara: WPADInit = 0x803D8218 (called by KPADInit 0x803EA608; calls WUDInit 0x803E4E64).
PPC_NATIVE_OVERRIDE(805D56A0, WPADInit_HLE, int32_t, (), ());

extern "C" int32_t WUDGetStatus_HLE()
{
    return WpadContract::kStatusReady;
}
PPC_NATIVE_OVERRIDE(805E7C30, WUDGetStatus_HLE, int32_t, (), ());

// WPADGetDataFormat reads the per-channel format set by WPADSetDataFormat. Can't reuse the
// translated SDK implementation: it dereferences Bluetooth control blocks that HLE'd WPADInit
// never constructs.
extern "C" int32_t WPADGetDataFormat_HLE(uint32_t chan)
{
    return g_state.contract.GetDataFormat(chan);
}

// WPADSetDataFormat: records the per-channel data format the game asked for.
extern "C" int32_t WPADSetDataFormat_HLE(uint32_t chan, int32_t format)
{
    return g_state.contract.SetDataFormat(chan, format);
}

// WPADProbe: reports the extension type of a Bluetooth remote on `chan`, or no controller.
extern "C" int32_t WPADProbe_HLE(uint32_t chan, uint32_t typePtr)
{
    if (chan >= WpadContract::kChannelCount) {
        return WpadContract::kErrorBadChannel;
    }

    // Drive the rescan state machine here too: a reconnect probe can arrive
    // before the next PADRead, and only Poll() brings a dropped remote back.
    WiiRemoteInput::Poll();

    if (FrameInput::Active()) {
        // Deterministic mode: connections change only at frame boundaries, like the input itself.
        const FrameInput::Remote& remote = FrameInput::Get(chan);
        if (typePtr != 0) {
            uint32_t type = WpadContract::kExtensionCore;
            if (remote.connected && remote.kind == WiiRemoteInput::Kind::RemoteWithNunchuk) type = 1u;
            if (remote.connected && remote.kind == WiiRemoteInput::Kind::RemoteWithClassic) type = 2u;
            Memory::Write32(typePtr, type);
        }
        return remote.connected ? kStatusOk : WpadContract::kErrorNoController;
    }

    // A real Bluetooth remote: WPAD_DEV_CORE (0) for a bare remote,
    // WPAD_DEV_FREESTYLE (1) with a Nunchuk, WPAD_DEV_CLASSIC (2) with a Classic
    // Controller. The game reads the type from here (not from
    // KPADStatus.dev_type) to pick its control scheme, and re-reads it when it
    // changes, which is what makes an extension swap mid-game work like on the
    // console. EffectiveKind keeps the last type through SDL's re-creation of
    // the joystick after a swap.
    const WiiRemoteInput::Kind kind = WiiRemoteInput::EffectiveKind(chan);
    if (WiiRemoteInput::IsRemoteChannel(chan)) {
        if (typePtr != 0) {
            uint32_t type = WpadContract::kExtensionCore;
            if (kind == WiiRemoteInput::Kind::RemoteWithNunchuk) type = 1u;
            if (kind == WiiRemoteInput::Kind::RemoteWithClassic) type = 2u;
            Memory::Write32(typePtr, type);
        }
        return kStatusOk;
    }
    if (typePtr != 0) {
        Memory::Write32(typePtr, WpadContract::kExtensionCore);
    }
    return WpadContract::kErrorNoController;
}
PPC_NATIVE_OVERRIDE(805D6F70, WPADProbe_HLE, int32_t, (uint32_t chan, uint32_t typePtr), (chan, typePtr));

// Game rumble (Settings > Controls > Rumble: 0 off, 1 the gamepad, 2 the gamepad and the phone). A
// motor that turns on or off goes to the gamepad playing that channel (aurora PADControlMotor, SDL
// rumble); the bits let the app pulse the phone's vibrator while it is on (nativeRumbleBits).
namespace {
std::atomic<uint32_t> g_wpadMotorBits{0};
std::atomic<int> g_wpadRumbleMode{1};
}  // namespace

extern "C" uint32_t WPAD_HLE_MotorBits() { return g_wpadMotorBits.load(std::memory_order_relaxed); }

extern "C" void WPAD_HLE_StopMotors() {
    const uint32_t bits = g_wpadMotorBits.exchange(0, std::memory_order_relaxed);
    for (uint32_t chan = 0; chan < 4; ++chan) {
        const int port = VirtualRemote::PadPortFor(chan);
        if ((bits & (1u << chan)) != 0 && port >= 0) PADControlMotor(static_cast<uint32_t>(port), PAD_MOTOR_STOP);
    }
}

extern "C" void WPAD_HLE_SetRumbleMode(int mode) {
    g_wpadRumbleMode.store(mode, std::memory_order_relaxed);
    if (mode == 0) WPAD_HLE_StopMotors();
}

extern "C" void WPADControlMotor_HLE(uint32_t chan, uint32_t command)
{
    if (chan >= 4) return;
    static bool s_logged = false;
    if (!s_logged && command != 0) {
        s_logged = true;
        RT_LOGF(RT_TAG_HLE, "rumble: the game drives the Wii Remote motor (channel %u)\n", chan);
    }
    const bool on = command != 0 && g_wpadRumbleMode.load(std::memory_order_relaxed) != 0;
    const uint32_t bit = 1u << chan;
    const uint32_t before = on ? g_wpadMotorBits.fetch_or(bit, std::memory_order_relaxed)
                               : g_wpadMotorBits.fetch_and(~bit, std::memory_order_relaxed);
    if (((before & bit) != 0) == on) return;  // unchanged: the game repeats its command every frame
    // The gamepad playing that channel (Two Players moves the first one to player 2).
    const int port = VirtualRemote::PadPortFor(chan);
    if (port >= 0) PADControlMotor(static_cast<uint32_t>(port), on ? PAD_MOTOR_RUMBLE : PAD_MOTOR_STOP);
}
PPC_NATIVE_OVERRIDE(805D7510, WPADControlMotor_HLE, void, (uint32_t chan, uint32_t command), (chan, command));

extern "C" int32_t WPADGetInfoAsync_HLE(uint32_t chan, uint32_t infoPtr, uint32_t callback)
{
    if (chan >= WpadContract::kChannelCount) {
        return CompleteWpadRequest(chan, callback, WpadContract::kErrorBadChannel);
    }

    (void)infoPtr;
    return CompleteWpadRequest(chan, callback, WpadContract::kErrorNoController);
}

extern "C" int32_t WPADControlLed_HLE(uint32_t chan, uint32_t ledMask, uint32_t callback)
{
    if (chan >= WpadContract::kChannelCount) {
        return CompleteWpadRequest(chan, callback, WpadContract::kErrorBadChannel);
    }
    (void)ledMask;
    return CompleteWpadRequest(chan, callback, WpadContract::kErrorNoController);
}

extern "C" int32_t WPADStartSimpleSync_HLE()
{
    if (g_state.simpleSyncActive) {
        return 0;
    }
    g_state.simpleSyncActive = true;
    return 1;
}

// due to multiplayer controller screen hle this to avoid startsyncdevice to return fail every frame
// causing you to get softlocked in the game
extern "C" int32_t WPADStopSimpleSync_HLE()
{
    if (g_state.simpleSyncActive) {
        g_state.simpleSyncActive = false;
        const uint32_t callback = g_state.syncDeviceCallback;
        if (callback != 0 && TranslatedFunctionRegistry::FindByAddressPtr(callback)) {
            NandQueueIosCallback(callback, 1, 0); // callback(WUD_SYNC_DONE, devicesSynced=0)
        }
    }
    return 1;
}

extern "C" uint32_t WPADSetSyncDeviceCallback_HLE(uint32_t callback)
{
    const uint32_t previous = g_state.syncDeviceCallback;
    g_state.syncDeviceCallback = callback;
    return previous;
}
