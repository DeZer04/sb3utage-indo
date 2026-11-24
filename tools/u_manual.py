#!/usr/bin/env python3
"""Hand fixes for the Utage port, applied after u_remap.py and u_dataremap.py (tools/u_port.sh).
Each entry: file under runtime/, the text as the remap leaves it, the Utage text. Fails loudly when
a text is missing, so a change upstream shows here instead of silently skipping a fix."""
import sys
from pathlib import Path

RT = Path(__file__).resolve().parent.parent / 'runtime'  # entries name src/... or include/...

LOCK_CPP = '\n// Lock target (R3, the touch LOCK button; BASARA_LOCKON=1 forces it on for a PC test): the camera\n// turns toward an enemy general or a named enemy officer (never a plain soldier) by moving the right stick as a\n// player would, so the game\'s own camera (its shakes, zooms, collision) does the turning and the\n// player\'s own right stick always wins. From battle memory dumps: sUnit (pointer at 0x808F4020)\n// keeps 64 move lines of 0x18 bytes from +0x20, each with its first unit at +0xC, and units chain\n// through +0xC. Line 12 holds the generals (uPlNNN: the player and the computer\'s), line 20 the\n// soldiers and captains (uEmNN), line 38 the player camera (uPlCamera: eye +0x30, look-at +0x50,\n// player +0x2E8). Every unit\'s position is at +0x30. Line 10 holds every actor\'s uActorInfo (its unit at\n// +0x1C0): a named officer\'s carries its name index at +0x1D8 (6, 7, 8.. in order; -1 for a plain\n// soldier) and a general\'s the flag 0x2000 at +0x248, which is what the game\'s own life gauges read\n// (0x802EEF08) to keep a named enemy\'s gauge up at any distance. Its army (cArmy, +0x280) keeps\n// the side it fights on at +0x128: the player\'s 0, and in a three-way battle (Matsunaga against\n// Date and Takeda) the other armies 1 and 2. Units on the player\'s side are never locked.\nnamespace {\nconstexpr uint32_t kUtageUnitPtr = 0x808F4020u;\nconstexpr int kLineActorInfo = 10, kLineGenerals = 12, kLineEnemies = 20, kLineCamera = 38;\nconstexpr float kLockRange = 3500.0f;  // battle units: a character runs about 500 a second\nstd::atomic<bool> g_lockRequested{false};\nstd::atomic<float> g_lockStickX{0.0f};\nstd::atomic<float> g_playerStickX{0.0f};  // the player\'s own right stick, for the flick that switches targets\nbool g_lockFresh = true;                  // no target yet since the lock went on: a wider cone\nbool g_lockTurning = false;               // turning toward the target (it left the comfortable middle)\nfloat g_lockStickSmooth = 0.0f;\nbool g_utageInBattle = false;  // the player camera exists (camera zoom applies only then)\nuint32_t g_fovCamera = 0;      // the camera whose field of view the distance widened\nfloat g_fovBase = 0.0f;        // its field of view as the game set it\nfloat g_fovWritten = 0.0f;     // and as written here\nuint32_t g_lockTarget = 0;\nfloat g_lockSign = -1.0f;  // with the game\'s default camera (both PC tests); learned below all the same\nint g_lockProbe = 0;\nbool g_lockSignKnown = false;  // a probe showed which way the stick turns the camera\nfloat g_lockProbeYaw = 0.0f;   // the camera heading when the probe began\nfloat g_lockProbeDir = 0.0f;   // and the stick direction it holds\nfloat g_lockTurnDir = 0.0f;    // the way the camera is turning (kept while the target is behind)\n\nstruct LockVec {\n    float x, y, z;\n};\n\nLockVec UnitPos(uint32_t unit, uint32_t offset = 0x30u) {\n    return {ReadF32(unit + offset), ReadF32(unit + offset + 4u), ReadF32(unit + offset + 8u)};\n}\n\n// An MT object\'s class: vtable slot 6 is getDTI, a lis/addi/blr returning its MtDTI, whose +4 is\n// the class name. Cached per vtable.\nconst std::string& UnitClass(uint32_t obj) {\n    static std::unordered_map<uint32_t, std::string> s_names;\n    static const std::string s_none;\n    uint32_t vt = 0;\n    if (obj == 0 || !Memory::TryRead32(obj, vt) || vt < 0x80000000u) return s_none;\n    if (const auto it = s_names.find(vt); it != s_names.end()) return it->second;\n    std::string name;\n    uint32_t fn = 0, i0 = 0, i1 = 0, i2 = 0, namePtr = 0;\n    if (Memory::TryRead32(vt + 0x18u, fn) && Memory::TryRead32(fn, i0) && Memory::TryRead32(fn + 4u, i1) &&\n        Memory::TryRead32(fn + 8u, i2) && (i0 >> 26) == 15u && (i1 >> 26) == 14u && i2 == 0x4E800020u) {\n        const uint32_t dti = ((i0 & 0xFFFFu) << 16) +\n                             static_cast<uint32_t>(static_cast<int32_t>(static_cast<int16_t>(i1 & 0xFFFFu)));\n        if (Memory::TryRead32(dti + 4u, namePtr)) {\n            for (uint32_t k = 0; k < 48; k += 4) {\n                uint32_t word = 0;\n                if (!Memory::TryRead32(namePtr + k, word)) break;\n                bool end = false;\n                for (int b = 3; b >= 0 && !end; --b) {\n                    const char c = static_cast<char>((word >> (8 * b)) & 0xFFu);\n                    if (c == 0) end = true; else name.push_back(c);\n                }\n                if (end) break;\n            }\n        }\n    }\n    return s_names.emplace(vt, std::move(name)).first->second;\n}\n\nbool ClassIs(uint32_t obj, const char* prefix) {\n    return UnitClass(obj).rfind(prefix, 0) == 0;\n}\n\nuint32_t LineHead(uint32_t unitSystem, int line) {\n    uint32_t head = 0;\n    Memory::TryRead32(unitSystem + 0x20u + 0x18u * static_cast<uint32_t>(line) + 0xCu, head);\n    return head;\n}\n\ntemplate <typename F>\nvoid ForEachUnit(uint32_t unitSystem, int line, F&& visit) {\n    uint32_t unit = LineHead(unitSystem, line);\n    for (int n = 0; unit != 0 && n < 512; ++n) {\n        visit(unit);\n        if (!Memory::TryRead32(unit + 0xCu, unit)) break;\n    }\n}\n\nbool IsGeneral(uint32_t unit, uint32_t player) {\n    if (unit == player) return false;\n    const std::string& c = UnitClass(unit);\n    return c.size() == 6 && c.rfind("uPl", 0) == 0;  // uPlNNN, not uPlCamera or uPlWep\n}\n\n// This frame\'s actors: the named enemies worth a lock (officers with a name, general-class units)\n// and the units on the player\'s side.\nstruct LockActors {\n    uint32_t named[64];\n    uint32_t friends[128];\n    int namedCount = 0, friendCount = 0;\n    bool sideKnown = false;\n    uint32_t playerSide = 0;\n    bool Named(uint32_t unit) const { return std::find(named, named + namedCount, unit) != named + namedCount; }\n    bool Friend(uint32_t unit) const { return std::find(friends, friends + friendCount, unit) != friends + friendCount; }\n};\n\nbool ActorSide(uint32_t info, uint32_t& side) {\n    uint32_t army = 0;\n    return Memory::TryRead32(info + 0x280u, army) && army != 0 && ClassIs(army, "cArmy") &&\n           Memory::TryRead32(army + 0x128u, side);\n}\n\nLockActors CollectActors(uint32_t unitSystem, uint32_t player) {\n    LockActors actors;\n    ForEachUnit(unitSystem, kLineActorInfo, [&](uint32_t info) {\n        uint32_t unit = 0;\n        if (!actors.sideKnown && Memory::TryRead32(info + 0x1C0u, unit) && unit == player && player != 0 &&\n            ClassIs(info, "uActorInfo")) {\n            actors.sideKnown = ActorSide(info, actors.playerSide);\n        }\n    });\n    ForEachUnit(unitSystem, kLineActorInfo, [&](uint32_t info) {\n        uint32_t unit = 0, index = 0, flags = 0, side = 0;\n        if (!Memory::TryRead32(info + 0x1C0u, unit) || unit == 0 || unit == player || !ClassIs(info, "uActorInfo")) return;\n        if (actors.sideKnown && ActorSide(info, side) && side == actors.playerSide) {\n            if (actors.friendCount < 128) actors.friends[actors.friendCount++] = unit;\n            return;\n        }\n        if (actors.namedCount < 64 && Memory::TryRead32(info + 0x1D8u, index) && Memory::TryRead32(info + 0x248u, flags) &&\n            (static_cast<int32_t>(index) >= 0 || (flags & 0x2000u) != 0)) {\n            actors.named[actors.namedCount++] = unit;\n        }\n    });\n    return actors;\n}\n\nvoid LockOff() {\n    g_lockStickX.store(0.0f, std::memory_order_relaxed);\n    g_lockTarget = 0;\n    g_lockFresh = true;\n    g_lockTurning = false;\n    g_lockStickSmooth = 0.0f;\n    g_lockTurnDir = 0.0f;\n}\n}  // namespace\n\n// extern "C": android_bridge.cpp declares it inside its JNI extern "C" block.\nextern "C" bool UtageLockOnToggle() {\n    const bool on = !g_lockRequested.load(std::memory_order_relaxed);\n    g_lockRequested.store(on, std::memory_order_relaxed);\n    RT_LOGF(RT_TAG_VI, "lock: %s\\n", on ? "on" : "off");\n    return on;\n}\n\nfloat UtageLockOnStickX() { return g_lockStickX.load(std::memory_order_relaxed); }\nvoid UtageLockOnPlayerStick(float x) { g_playerStickX.store(x, std::memory_order_relaxed); }\n\n// Once a frame (UtageFpsApply_HLE, game thread).\nvoid UtageLockOnUpdate() {\n    static const bool s_forced = std::getenv("BASARA_LOCKON") != nullptr;\n    if (s_forced) g_lockRequested.store(true, std::memory_order_relaxed);\n    {\n        uint32_t sys = 0;\n        const uint32_t camera = Memory::TryRead32(kUtageUnitPtr, sys) && sys != 0 ? LineHead(sys, kLineCamera) : 0u;\n        g_utageInBattle = camera != 0 && UnitClass(camera) == "uPlCamera";\n        // Camera distance: the player camera\'s own field of view (uCamera mFov, +0x2C, degrees; 40\n        // in battle), widened as if the eye stood k times farther back. Its projection (+0x100), the\n        // culling and every screen position the game derives from it (enemy names, markers) follow,\n        // where widening only the GX projection left the names behind. A value that differs from\n        // the one written here is the game\'s own new one.\n        if (g_utageInBattle) {\n            const float current = ReadF32(camera + 0x2Cu);\n            if (camera != g_fovCamera) {\n                g_fovCamera = camera;\n                g_fovBase = current;\n            } else if (current != g_fovWritten) {\n                g_fovBase = current;\n            }\n            const float k = Cheats::CameraDistance();\n            float want = g_fovBase;\n            if (k > 1.0f && g_utageFps != 30.0f && g_fovBase > 1.0f && g_fovBase < 150.0f) {\n                constexpr float kDeg = 0.01745329252f;\n                want = std::min(120.0f, 2.0f * std::atan(std::tan(g_fovBase * 0.5f * kDeg) * std::min(k, 2.0f)) / kDeg);\n            }\n            if (want != current) {\n                uint32_t bits;\n                std::memcpy(&bits, &want, sizeof(bits));\n                Memory::TryWrite32(camera + 0x2Cu, bits);\n                static float s_logged = 0.0f;\n                if (s_logged != want) {\n                    s_logged = want;\n                    RT_LOGF(RT_TAG_VI, "camera: battle field of view %.1f -> %.1f (distance %.2f)\\n", g_fovBase, want, k);\n                }\n            }\n            g_fovWritten = want;\n        } else {\n            g_fovCamera = 0;\n        }\n    }\n    if (!g_lockRequested.load(std::memory_order_relaxed) || g_utageFps == 30.0f) {  // cutscenes: hands off\n        LockOff();\n        return;\n    }\n    uint32_t sys = 0;\n    if (!Memory::TryRead32(kUtageUnitPtr, sys) || sys == 0) return LockOff();\n    const uint32_t cam = LineHead(sys, kLineCamera);\n    if (cam == 0 || UnitClass(cam) != "uPlCamera") return LockOff();  // not in a battle\n    uint32_t player = 0;\n    Memory::TryRead32(cam + 0x2E8u, player);\n    const LockVec eye = UnitPos(cam, 0x30u), look = UnitPos(cam, 0x50u);\n    const LockVec me = (player != 0 && ClassIs(player, "uPl")) ? UnitPos(player) : look;\n    float fx = look.x - eye.x, fz = look.z - eye.z;\n    const float flen = std::sqrt(fx * fx + fz * fz);\n    if (!(flen > 1.0f)) return LockOff();\n    fx /= flen;\n    fz /= flen;\n    const auto distance = [&](const LockVec& t) {\n        const float dx = t.x - me.x, dz = t.z - me.z;\n        return std::sqrt(dx * dx + dz * dz);\n    };\n    // Framed from the player, as Elden Ring frames a lock: the camera should look along\n    // player -> target, with the target anywhere in a comfortable middle of the screen.\n    const auto angleTo = [&](const LockVec& t) {  // signed, from the view\'s heading to player -> target\n        const float dx = t.x - me.x, dz = t.z - me.z;\n        return std::atan2(fx * dz - fz * dx, fx * dx + fz * dz);\n    };\n    const auto alive = [&](uint32_t unit) {\n        const LockVec t = UnitPos(unit);\n        return t.x != 0.0f || t.z != 0.0f;\n    };\n    // A flick of the player\'s own right stick (from rest to past 0.8) moves the lock to the next\n    // enemy on that side.\n    static bool s_flickArmed = true;\n    int flick = 0;\n    const float own = g_playerStickX.load(std::memory_order_relaxed);\n    if (std::fabs(own) < 0.3f) {\n        s_flickArmed = true;\n    } else if (s_flickArmed && std::fabs(own) > 0.8f) {\n        s_flickArmed = false;\n        flick = own > 0.0f ? 1 : -1;\n    }\n    const LockActors actors = CollectActors(sys, player);\n    // The target stays until it is defeated (unlinked from its line, its slot reused) or far away.\n    if (g_lockTarget != 0) {\n        bool present = false;\n        ForEachUnit(sys, kLineGenerals, [&](uint32_t u) { present = present || (u == g_lockTarget && IsGeneral(u, player) && !actors.Friend(u)); });\n        ForEachUnit(sys, kLineEnemies, [&](uint32_t u) { present = present || (u == g_lockTarget && actors.Named(u)); });\n        if (!present || !alive(g_lockTarget) || distance(UnitPos(g_lockTarget)) > kLockRange * 1.5f) {\n            g_lockTarget = 0;\n            g_lockTurning = false;\n        }\n    }\n    // Generals and named officers only (the user: plain soldiers are left alone), a general\n    // preferred unless an officer is clearly nearer.\n    const auto pick = [&](float cone, float side, float fromAngle) {\n        uint32_t best = 0;\n        float bestScore = 1e30f;\n        const auto consider = [&](uint32_t u, float rank) {\n            if (u == g_lockTarget || !alive(u)) return;\n            const LockVec t = UnitPos(u);\n            const float d = distance(t), a = angleTo(t);\n            if (d > kLockRange || std::fabs(a) > cone) return;\n            float score = rank + d + 600.0f * std::fabs(a);  // near and near the middle\n            if (side != 0.0f) {  // a flick: the next one on that side of the current target\n                const float delta = (a - fromAngle) * side;\n                if (delta < 0.05f) return;\n                score = rank + 1000.0f * delta + 0.2f * d;\n            }\n            if (score < bestScore) {\n                bestScore = score;\n                best = u;\n            }\n        };\n        ForEachUnit(sys, kLineGenerals, [&](uint32_t u) { if (IsGeneral(u, player) && !actors.Friend(u)) consider(u, 0.0f); });\n        ForEachUnit(sys, kLineEnemies, [&](uint32_t u) { if (actors.Named(u) && ClassIs(u, "uEm")) consider(u, 800.0f); });\n        return best;\n    };\n    if (flick != 0 && g_lockTarget != 0) {\n        // The stick turns the view toward angles of sign g_lockSign, so that is "right" here.\n        if (const uint32_t next = pick(3.2f, static_cast<float>(flick) * g_lockSign, angleTo(UnitPos(g_lockTarget)))) {\n            g_lockTarget = next;\n            g_lockTurning = true;\n            RT_LOGF(RT_TAG_VI, "lock: switched to %s at %.0f\\n", UnitClass(next).c_str(), distance(UnitPos(next)));\n        }\n    }\n    if (g_lockTarget == 0) {\n        // A new lock looks a little wider; after a target falls only enemies already in front are\n        // taken, so the camera never swings around to one behind.\n        g_lockTarget = pick(g_lockFresh ? 1.75f : 1.2f, 0.0f, 0.0f);\n        if (g_lockTarget == 0) {\n            g_lockStickSmooth = 0.0f;\n            g_lockTurning = false;\n            g_lockStickX.store(0.0f, std::memory_order_relaxed);\n            static int s_waitFrames = 0;\n            if (++s_waitFrames >= 300) {\n                s_waitFrames = 0;\n                float nearest = 1e30f;\n                for (int n = 0; n < actors.namedCount; ++n) nearest = std::min(nearest, distance(UnitPos(actors.named[n])));\n                RT_LOGF(RT_TAG_VI, "lock: waiting, %d named enemies (nearest %.0f), %d on the player\'s side %u%s\\n",\n                        actors.namedCount, actors.namedCount ? nearest : 0.0f, actors.friendCount, actors.playerSide,\n                        actors.sideKnown ? "" : " (side unknown)");\n            }\n            return;  // armed: waits for an enemy in front\n        }\n        g_lockFresh = false;\n        RT_LOGF(RT_TAG_VI, "lock: target %s at %.0f (%d named enemies, %d on the player\'s side %u%s)\\n",\n                UnitClass(g_lockTarget).c_str(), distance(UnitPos(g_lockTarget)), actors.namedCount, actors.friendCount,\n                actors.playerSide, actors.sideKnown ? "" : ", side unknown");\n    }\n    const LockVec t = UnitPos(g_lockTarget);\n    const float angle = angleTo(t), d = distance(t);\n    // Turn only when the target leaves a comfortable middle, and stop once it is well inside it.\n    // Up close (sword range) the middle is much wider: a general circling the player swung the\n    // camera back and forth.\n    const bool close = d < 450.0f;\n    const float outer = close ? 0.75f : 0.32f;  // about 43 / 18 degrees\n    const float inner = close ? 0.35f : 0.17f;  // about 20 / 10 degrees (7 kept it steering for seconds)\n    if (std::fabs(angle) > outer) g_lockTurning = true;\n    else if (std::fabs(angle) < inner) g_lockTurning = false;\n    float want = 0.0f;\n    if (g_lockTurning) {\n        const float mag = std::clamp(0.4f + (std::fabs(angle) - inner) * 1.2f, 0.4f, close ? 0.55f : 0.85f);\n        // Straight behind, the angle flips between +180 and -180 as the target moves: the turn\n        // keeps its way until the target is back past the side (PC test: the stick flipped).\n        float dir = angle > 0.0f ? 1.0f : -1.0f;\n        if (std::fabs(angle) > 2.4f && g_lockTurnDir != 0.0f) dir = g_lockTurnDir;\n        g_lockTurnDir = dir;\n        want = dir * mag * g_lockSign;\n    } else {\n        g_lockTurnDir = 0.0f;\n    }\n    // Eased: the stick moves a third of the way each frame, and lets go at once.\n    g_lockStickSmooth = want == 0.0f ? 0.0f : g_lockStickSmooth + (want - g_lockStickSmooth) * 0.33f;\n    const float stick = g_lockStickSmooth;\n    // Which way the stick turns this camera is learned, not assumed (the game has an invert\n    // option): from the camera\'s own heading over 16 frames of steering one way. The angle to the\n    // target was a poor witness, as the player and the target move too (PC test: a wrong flip).\n    if (!g_lockSignKnown) {\n        const float yaw = std::atan2(fz, fx);\n        const float dir = want > 0.0f ? 1.0f : want < 0.0f ? -1.0f : 0.0f;\n        if (dir == 0.0f) {\n            g_lockProbe = 0;\n        } else if (g_lockProbe == 0 || dir != g_lockProbeDir) {\n            g_lockProbe = 1;\n            g_lockProbeYaw = yaw;\n            g_lockProbeDir = dir;\n        } else if (++g_lockProbe == 16) {\n            float turned = yaw - g_lockProbeYaw;\n            if (turned > 3.14159265f) turned -= 6.2831853f;\n            if (turned < -3.14159265f) turned += 6.2831853f;\n            g_lockProbe = 0;\n            if (std::fabs(turned) > 0.06f) {\n                // A positive angle closes as the heading grows, so g_lockSign is the stick\n                // direction that grows it.\n                const float sign = turned * dir > 0.0f ? 1.0f : -1.0f;\n                if (sign != g_lockSign) RT_LOGF(RT_TAG_VI, "lock: the stick turns the other way here\\n");\n                g_lockSign = sign;\n                g_lockSignKnown = true;\n            }\n        }\n    }\n    g_lockStickX.store(stick, std::memory_order_relaxed);\n    static int s_logFrames = 0;\n    if (++s_logFrames >= 120) {\n        s_logFrames = 0;\n        RT_LOGF(RT_TAG_VI, "lock: %s at %.0f, %.1f degrees off, stick %.2f%s\\n", UnitClass(g_lockTarget).c_str(), d,\n                angle * 57.2958f, stick, close ? " (close)" : "");\n    }\n}\n'

FIXES = [
    # The app's own Java package (io.github.dezer04.sb3utage, 0.6.0; Basara 2 Heroes' was
    # com.shiinobu.basara): every JNI entry point. First for this file, so the FIXES below use it.
    ('src/android/android_bridge.cpp', 'Java_com_shiinobu_basara_', 'Java_io_github_dezer04_sb3utage_'),
    # The app's name, SB3 UTAGE:INDO, where the runtime shows one (startup screen, PC menu bar and
    # window, Discord, the missing-game messages).
    ('src/settings_overlay.cpp', '        constexpr const char* kTitle = "Sengoku Basara 2 Heroes";\n',
     '        constexpr const char* kTitle = "SB3 UTAGE:INDO";\n'),
    ('src/settings_overlay.cpp', '    ImGui::TextUnformatted("Basara 2 Heroes Wii");\n',
     '    ImGui::TextUnformatted("SB3 UTAGE:INDO");\n'),
    ('src/product/base_product.cpp', '        "Basara 2 Heroes Wii",\n', '        "SB3 UTAGE:INDO",\n'),
    ('src/main.cpp', 'DiscordPresence::Initialize(RuntimeConfigFile::DiscordClientId(), "Basara 2 Heroes Wii");',
     'DiscordPresence::Initialize(RuntimeConfigFile::DiscordClientId(), "SB3 UTAGE:INDO");'),
    ('src/hle/storage/dvd.cpp', 'dvd_root in Config.toml to your Sengoku Basara 2 Heroes, ',
     'dvd_root in Config.toml to your Sengoku Basara 3 Utage, '),
    ('src/hle/storage/dvd.cpp', 'dvd_root in Config.toml to your Sengoku Basara 2 Heroes "\n               "(RBSJ08)',
     'dvd_root in Config.toml to your Sengoku Basara 3 Utage "\n               "(S3HJ08)'),
    # The screen starts black, as after the SDK's VIInit, until the game's VISetBlack(FALSE). Utage's
    # video setup (0x8071A07C) clears both XFBs with GXCopyDisp before it unblanks; this runtime
    # presents at every GXCopyDisp, so with the screen not black those copies showed as a grey
    # picture for a few frames before the Wii Remote strap screen (and lifted the startup cover on
    # them). Starting black keeps the cover up until the game shows its first real frame.
    ('src/hle/vi.cpp', '    uint32_t retraceCount = 0;\n    bool black = false;\n',
     '    uint32_t retraceCount = 0;\n    bool black = true;  // Utage: VIInit leaves the screen black\n'),
    ('src/hle/vi.cpp', '    uint32_t pendingNextFrameBuffer = 0;\n    bool pendingBlack = false;\n',
     '    uint32_t pendingNextFrameBuffer = 0;\n    bool pendingBlack = true;\n'),
    # The SDK's GXInit sets the copy clear colour to grey (64,64,64), so the first frame's EFB starts
    # grey; Utage's first GXCopyDisp (video setup, before it sets its own black clear) showed that
    # grey picture before the Wii Remote strap screen, for seconds on a PC. On a console the EFB holds
    # whatever was there, normally black. Utage clears to black everywhere (its colour table entry
    # 0x808F3D98 is 0x000000FF), so start with black.
    ('src/hle/gx/gx_init.cpp',
     '    GXInit(GuestToHostPtr(fifoBase, fifoSize), fifoSize);\n',
     '    GXInit(GuestToHostPtr(fifoBase, fifoSize), fifoSize);\n'
     '    GXSetCopyClear(GXColor{0, 0, 0, 255}, 0x00FFFFFFu);  // Utage: black, not the SDK\'s grey\n'
     '    UtageWaitForBootShaders();  // gx_copy.cpp: the precompile screen, before any frame\n'),
    ('src/hle/gx/gx_init.cpp', 'extern "C" uint32_t GX__Init_8016b850(uint32_t fifoBase, uint32_t fifoSize)\n',
     'void UtageWaitForBootShaders();\n'
     'extern "C" uint32_t GX__Init_8016b850(uint32_t fifoBase, uint32_t fifoSize)\n'),
    # HOME never reaches the game. Utage's Wii HOME Menu lives in a module it loads at run time
    # (files/nativeWii/rso/hbm.rso, read through NAND tmp), which this static translation of main.dol
    # does not contain: pressing HOME loaded it and jumped into it, "missing translated function"
    # 0x81236648 from 0x807F57CC (tester report, Infinix X6882, 2026-11-22). The app's own menu
    # replaces it.
    ('src/virtual_remote.cpp', '    sample.hasClassic = true;\n    sample.clHold = intent.cl;\n',
     '    sample.hasClassic = true;\n'
     '    intent.cl &= ~kClHome;  // Utage: the HOME Menu is an untranslated module (hbm.rso)\n'
     '    sample.clHold = intent.cl;\n'),
    # The disc this build runs (game_folder.cpp: the folder/ISO check before boot).
    ('src/game_folder.cpp', 'if (id != "RBSJ08") {', 'if (id != "S3HJ08") {'),
    ('src/game_folder.cpp', 'not Sengoku Basara 2 Heroes (RBSJ08). This port runs only the Japanese disc.',
     'not Sengoku Basara 3 Utage (S3HJ08). This port runs only the Japanese disc.'),
    ('src/game_folder.cpp', 'your own copy of Sengoku Basara 2 Heroes (Japan, RBSJ08). ',
     'your own copy of Sengoku Basara 3 Utage (Japan, S3HJ08). '),
    # Low memory the boot code fills in: game code, the title's IOS (TMD system version), MEM1 arena top.
    ('src/system_bridge.cpp', 'entries.push_back({0x80000000u, 0x5242534Au, "Disc game code"}); // RBSJ',
     'entries.push_back({0x80000000u, 0x5333484Au, "Disc game code"}); // S3HJ'),
    ('src/system_bridge.cpp', 'entries.push_back({0x80003180u, 0x5242534Au, "OS app game code"}); // RBSJ',
     'entries.push_back({0x80003180u, 0x5333484Au, "OS app game code"}); // S3HJ'),
    ('src/system_bridge.cpp', 'entries.push_back({0x80003194u, 0x5242534Au, "OS app gamename"});  // RBSJ',
     'entries.push_back({0x80003194u, 0x5333484Au, "OS app gamename"});  // S3HJ'),
    ('src/system_bridge.cpp', 'constexpr uint32_t kIos36Version = 0x0015040Fu;  // Basara RBSJ08 TMD: IOS21 v1039 (name kept from MKW)',
     'constexpr uint32_t kIos36Version = 0x0038171Eu;  // Utage S3HJ08 TMD: IOS56 (v5918, Dolphin VersionInfo; name kept from MKW)'),
    ('src/system_bridge.cpp', 'uint32_t mem1ArenaHiDefault = 0x817FF8A0u;  // Basara: MEM1 end - FST 0x748, 32-aligned.',
     'uint32_t mem1ArenaHiDefault = 0x8177A300u;  // Utage: MEM1 end - FST 0x85CF8 (548088 B), 32-aligned. Basara was 0x817FF8A0.'),
    ('src/system_bridge.cpp', '"Title\'s required IOS (IOS21)"', '"Title\'s required IOS (IOS56)"'),
    # ISFS_OpenLib: Basara's HLE rebuilt the 2006 SDK's IOS heap by hand (its IPC buffer used to be 0).
    # With IPCCltInit setting the buffer, Utage's own 2010 ISFS_OpenLib runs and keeps its own globals
    # (the HLE's heap was invisible to ISFS_OpenAsync, which then failed with ISFS_ENOMEM -> OSFatal).
    ('src/hle/storage/nand_isfs.cpp',
     'REGISTER_NATIVE_FUNCTION_AS(0x8059C210, ISFS_OpenLib_HLE_80169BCC, "ISFS_OpenLib_HLE_80169BCC");',
     "#if 0  // Utage: the game's own ISFS_OpenLib runs\n"
     'REGISTER_NATIVE_FUNCTION_AS(0x8059C210, ISFS_OpenLib_HLE_80169BCC, "ISFS_OpenLib_HLE_80169BCC");\n'
     '#endif'),
    # The DOL's entry point (__start), which main.cpp boots.
    ('include/system_bridge.h', 'inline constexpr uint32_t kDefaultEntryAddress = 0x8000403Cu;',
     'inline constexpr uint32_t kDefaultEntryAddress = 0x80004050u;  // Utage __start (Basara 0x8000403C)'),
    # VIGetScanMode (newer SDK, not in Basara): reads VICLK (0xCC00206C) and DCR. Interlaced, matching
    # VIGetDTVStatus's "no component cable".
    ('src/hle/vi.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(805D0910, VIGetDTVStatus_HLE_801bad38, (CpuContext* ctx), (ctx));',
     'PPC_NATIVE_OVERRIDE_VOID(805D0910, VIGetDTVStatus_HLE_801bad38, (CpuContext* ctx), (ctx));\n'
     '\n'
     '// VIGetScanMode (Utage 0x805D08B0; newer SDK than Basara\'s): 2 progressive when VICLK is 54 MHz,\n'
     '// else 1/0 from DCR. No VI hardware here: interlaced, as VIGetDTVStatus reports no component cable.\n'
     'extern "C" void VIGetScanMode_HLE_utage(CpuContext* ctx)\n'
     '{\n'
     '    ViSetR3(ctx, 0);\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805D08B0, VIGetScanMode_HLE_utage, (CpuContext* ctx), (ctx));'),
    # OSGetFontEncode's cache (r13-0x7688 = 0x808F2E98, 0xFFFF until set): the OS decides ANSI or SJIS
    # from VI register 0xCC00206E (the Japanese-console bit) the first time, in OSGetFontEncode
    # (0x805BE750) and in six copies inlined into the font functions. No VI hardware here: seed SJIS,
    # the encoding os_font.cpp reports, before any of them runs.
    ('src/hle/os/os_init.cpp',
     '    RT_LOG(RT_TAG_OS) << "__init_hardware_80006348 called (stubbed)" << std::endl;\n}',
     '    RT_LOG(RT_TAG_OS) << "__init_hardware_80006348 called (stubbed)" << std::endl;\n'
     '    // Utage: OSGetFontEncode\'s cached encoding (r13-0x7688): 1 = SJIS, so the font functions never\n'
     '    // read VI register 0xCC00206E to work it out.\n'
     '    ::Memory::Write16(0x808F2E98u, 1);\n}'),
    # The OS font HLE at Utage's addresses. OSInitFont (0x805BF410) would read the console's ROM font over
    # EXI (stubbed) and decode whatever came back, forever; the HLE reports "no font" as os_font.cpp says.
    ('src/hle/os/os_font.cpp',
     'PPC_NATIVE_OVERRIDE(801B00A0, OSGetFontEncode_HLE_801b00a0, uint32_t, (), ());\n#endif',
     'PPC_NATIVE_OVERRIDE(801B00A0, OSGetFontEncode_HLE_801b00a0, uint32_t, (), ());\n#endif\n'
     'PPC_NATIVE_OVERRIDE(805BE750, OSGetFontEncode_HLE_801b00a0, uint32_t, (), ());  // Utage OSGetFontEncode'),
    ('src/hle/os/os_font.cpp',
     'PPC_NATIVE_OVERRIDE(801B0D60, OSInitFont_HLE_801b0d60, uint32_t, (uint32_t fontData), (fontData));\n#endif',
     'PPC_NATIVE_OVERRIDE(801B0D60, OSInitFont_HLE_801b0d60, uint32_t, (uint32_t fontData), (fontData));\n#endif\n'
     'PPC_NATIVE_OVERRIDE(805BF410, OSInitFont_HLE_801b0d60, uint32_t, (uint32_t fontData), (fontData));  // Utage OSInitFont'),
    # GX setters Basara never called (their hooks stayed disabled) that only store into __GXData and set
    # a dirtyState bit (+0x5FC). The flush is __GXSetDirtyState inside GXBegin, an HLE here, so run
    # natively their state never reached aurora: NW4R's GXSetVtxDescv left POS unset ("unmapped vtx attr 9").
    ('src/hle/gx/gx_vertex.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(801c3a30, GX__SetVtxDescv_8016d608, (uint32_t la), (la));\n#endif',
     'PPC_NATIVE_OVERRIDE_VOID(801c3a30, GX__SetVtxDescv_8016d608, (uint32_t la), (la));\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(8059F6D0, GX__SetVtxDescv_8016d608, (uint32_t la), (la));  // Utage GXSetVtxDescv'),
    ('src/hle/gx/gx_transform.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(801C9BD0, GX__SetViewportJitter_80173378, (float l, float t, float w, float h, float nz, float fz, uint32_t f), (l, t, w, h, nz, fz, f));\n#endif',
     'PPC_NATIVE_OVERRIDE_VOID(801C9BD0, GX__SetViewportJitter_80173378, (float l, float t, float w, float h, float nz, float fz, uint32_t f), (l, t, w, h, nz, fz, f));\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(805A4CE0, GX__SetViewportJitter_80173378, (float l, float t, float w, float h, float nz, float fz, uint32_t f), (l, t, w, h, nz, fz, f));  // Utage GXSetViewportJitter'),
    ('src/hle/gx/gx_transform.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(80173400, GX__SetZScaleOffset_80173400, (float s, float o), (s, o));\n#endif\n#endif',
     'PPC_NATIVE_OVERRIDE_VOID(80173400, GX__SetZScaleOffset_80173400, (float s, float o), (s, o));\n#endif\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(805A4D50, GX__SetZScaleOffset_80173400, (float s, float o), (s, o));  // Utage GXSetZScaleOffset'),
    # KPADRead (0x805AAF80): "li r6,0; li r7,0; b KPADiRead" (0x805AAF90, the 2010 SDK's reader; 0x688-byte
    # channel state at 0x80978340, called from the game's input wrapper 0x807EB704). Its KPADStatus is 0xF0
    # bytes (MotionPlus fields after ex_status) against Basara's 0x84; the HLE fills entry 0's first 0x84,
    # whose offsets are unchanged (KPADiRead itself writes dev_type at 0x5C, wpad_err 0x5D, data_format 0x5F).
    ('src/hle/input/kpad.cpp',
     '#if 0  // u_remap: no Utage address\n'
     'PPC_NATIVE_OVERRIDE(803E9EF0, KPAD__Read_HLE, int32_t, (uint32_t chan, uint32_t statusPtr, uint32_t count),\n'
     '         (chan, statusPtr, count));\n#endif',
     '#if 0  // u_remap: no Utage address\n'
     'PPC_NATIVE_OVERRIDE(803E9EF0, KPAD__Read_HLE, int32_t, (uint32_t chan, uint32_t statusPtr, uint32_t count),\n'
     '         (chan, statusPtr, count));\n#endif\n'
     'PPC_NATIVE_OVERRIDE(805AAF80, KPAD__Read_HLE, int32_t, (uint32_t chan, uint32_t statusPtr, uint32_t count),\n'
     '         (chan, statusPtr, count));  // Utage KPADRead'),
    # VIGetRetraceCount: Basara's 0x8036F900 is "lwz r3,-0x50EC(r13); blr" (Dolphin's IPCGetBufferLo is a
    # look-alike), the counter in VI .sbss; with the VI block delta that is 0x808F3BF4 = r13-0x692C, which
    # Utage reads at 0x805D0710 (right after VISetBlack 0x805D0690). The HLE also polls the retrace.
    ('src/hle/vi.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(8036F900, VIGetRetraceCount_HLE_801baba4, (CpuContext* ctx), (ctx));\n#endif',
     'PPC_NATIVE_OVERRIDE_VOID(8036F900, VIGetRetraceCount_HLE_801baba4, (CpuContext* ctx), (ctx));\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(805D0710, VIGetRetraceCount_HLE_801baba4, (CpuContext* ctx), (ctx));  // Utage VIGetRetraceCount'),
    # GXInitTexObjWrapMode: Basara's five words (0x80383414) occur once in Utage. The HLE keeps the host
    # texobj's wrap mode in step; run natively only the guest word changed.
    ('src/hle/gx/gx_texture.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(80383414, GX__InitTexObjWrapMode_80170b50, (uint32_t oa, uint32_t ws, uint32_t wt), (oa, ws, wt));\n#endif',
     'PPC_NATIVE_OVERRIDE_VOID(80383414, GX__InitTexObjWrapMode_80170b50, (uint32_t oa, uint32_t ws, uint32_t wt), (oa, ws, wt));\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(805A28E0, GX__InitTexObjWrapMode_80170b50, (uint32_t oa, uint32_t ws, uint32_t wt), (oa, ws, wt));  // Utage GXInitTexObjWrapMode'),
    # NANDCreate / NANDPrivateCreateAsync: Utage links NANDCreate, NANDPrivateCreate (its twin, li r8,1)
    # and NANDPrivateCreateAsync back to back (0x805B4EF0/4F70/4FF0); Basara's two match the first and
    # the third instruction for instruction.
    ('src/hle/storage/nand_api.cpp',
     'PPC_NATIVE_OVERRIDE(803A2EA8, NANDCreate_HLE, int32_t, (uint32_t pathPtr, uint32_t perm, uint32_t attr), (pathPtr, perm, attr));\n#endif',
     'PPC_NATIVE_OVERRIDE(803A2EA8, NANDCreate_HLE, int32_t, (uint32_t pathPtr, uint32_t perm, uint32_t attr), (pathPtr, perm, attr));\n#endif\n'
     'PPC_NATIVE_OVERRIDE(805B4EF0, NANDCreate_HLE, int32_t, (uint32_t pathPtr, uint32_t perm, uint32_t attr), (pathPtr, perm, attr));  // Utage NANDCreate'),
    ('src/hle/storage/nand_async.cpp',
     'PPC_NATIVE_OVERRIDE(803A2F1C, NANDPrivateCreateAsync_HLE, int32_t,\n'
     '    (uint32_t pathPtr, uint32_t perm, uint32_t attr, uint32_t callbackPtr, uint32_t commandBlockPtr),\n'
     '    (pathPtr, perm, attr, callbackPtr, commandBlockPtr));\n#endif',
     'PPC_NATIVE_OVERRIDE(803A2F1C, NANDPrivateCreateAsync_HLE, int32_t,\n'
     '    (uint32_t pathPtr, uint32_t perm, uint32_t attr, uint32_t callbackPtr, uint32_t commandBlockPtr),\n'
     '    (pathPtr, perm, attr, callbackPtr, commandBlockPtr));\n#endif\n'
     'PPC_NATIVE_OVERRIDE(805B4FF0, NANDPrivateCreateAsync_HLE, int32_t,  // Utage NANDPrivateCreateAsync\n'
     '    (uint32_t pathPtr, uint32_t perm, uint32_t attr, uint32_t callbackPtr, uint32_t commandBlockPtr),\n'
     '    (pathPtr, perm, attr, callbackPtr, commandBlockPtr));'),
    # AIRegisterDMACallback: right before AIInitDMA (0x80559050) as in Basara (0x80371EEC before 0x80371F30);
    # Dolphin's name also fits every "swap a callback under OSDisableInterrupts" setter. Without it the
    # AI HLE never learns AX's DMA callback, so no audio frame is ever mixed.
    ('src/hle/audio/audio.cpp',
     'PPC_NATIVE_OVERRIDE(80371EEC, AIRegisterDMACallback_80123f88, uint32_t, (uint32_t callback), (callback));\n#endif',
     'PPC_NATIVE_OVERRIDE(80371EEC, AIRegisterDMACallback_80123f88, uint32_t, (uint32_t callback), (callback));\n#endif\n'
     'PPC_NATIVE_OVERRIDE(80559000, AIRegisterDMACallback_80123f88, uint32_t, (uint32_t callback), (callback));  // Utage AIRegisterDMACallback'),
    # The rest of the AI DMA block, which Basara never called (0x805590D0 AIStartDMA, 0x805590F0 AIStopDMA,
    # 0x80559110 AIGetDMABytesLeft, 0x80559120 AIGetDMAStartAddr, 0x80559140 AIGetDMALength). Utage's
    # sound system restarts the AI DMA when the opening movie ends (0x80732510: AIStopDMA, AIInitDMA,
    # AIRegisterDMACallback, AIStartDMA); the native AIStopDMA read-modify-wrote 0xCC005036 and the
    # MMIO guard stopped the game ("force close after the video").
    ('src/hle/audio/audio.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(805590D0, AIStartDMA_80124048, (), ());\n',
     'PPC_NATIVE_OVERRIDE_VOID(805590D0, AIStartDMA_80124048, (), ());\n\n'
     '// Utage: AIStopDMA clears the DMA enable bit; the length and the bytes-left count stay.\n'
     'extern "C" void AIStopDMA_utage()\n'
     '{\n'
     '    std::lock_guard<std::mutex> lock(g_ai.mutex);\n'
     '    g_ai.enabled = false;\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805590F0, AIStopDMA_utage, (), ());\n'),
    ('src/hle/audio/audio.cpp',
     'PPC_NATIVE_OVERRIDE(8019F1B0, AIGetDMAStartAddr_8012406c, uint32_t, (), ());\n#endif\n',
     'PPC_NATIVE_OVERRIDE(8019F1B0, AIGetDMAStartAddr_8012406c, uint32_t, (), ());\n#endif\n'
     'PPC_NATIVE_OVERRIDE(80559120, AIGetDMAStartAddr_8012406c, uint32_t, (), ());  // Utage AIGetDMAStartAddr\n'),
    ('src/hle/audio/audio.cpp',
     'PPC_NATIVE_OVERRIDE(8019F1D0, AIGetDMALength_80124084, uint32_t, (), ());\n#endif\n',
     'PPC_NATIVE_OVERRIDE(8019F1D0, AIGetDMALength_80124084, uint32_t, (), ());\n#endif\n'
     'PPC_NATIVE_OVERRIDE(80559140, AIGetDMALength_80124084, uint32_t, (), ());  // Utage AIGetDMALength\n'),
    # VIGetNextField (0x805D0720, between VIGetRetraceCount and VIGetCurrentLine): reads the VI beam
    # counters 0xCC00202C/E, which the MMIO guard stops; the game calls it at the end of a frame
    # (0x8071BDFC, 0x8071C110).
    ('src/hle/vi.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(801BDEE0, VIGetNextField_HLE_801babac, (CpuContext* ctx), (ctx));\n#endif\n',
     'PPC_NATIVE_OVERRIDE_VOID(801BDEE0, VIGetNextField_HLE_801babac, (CpuContext* ctx), (ctx));\n#endif\n'
     'PPC_NATIVE_OVERRIDE_VOID(805D0720, VIGetNextField_HLE_801babac, (CpuContext* ctx), (ctx));  // Utage VIGetNextField\n'),
    # OSSleepTicks (0x805C3A20) through the runtime's host-timer HLE (the scheduler peels the sleep in
    # SelectThread) instead of the native alarm + OSSuspendThread chain: natively a 1 ms sleep woke
    # ~5 s late, and Utage's loader sleeps 1 ms after every 64 KB it reads from its NAND cache, so the
    # "読み込み中" loading screen after the opening crawled for minutes. Ticks are in r3:r4 as there.
    ('src/hle/os/os_sleep.cpp',
     'REGISTER_NATIVE_FUNCTION(0x801AACA8, OS__SleepTicks_HLE_801aaca8);\n#endif\n#endif\n',
     'REGISTER_NATIVE_FUNCTION(0x801AACA8, OS__SleepTicks_HLE_801aaca8);\n#endif\n#endif\n'
     'REGISTER_NATIVE_FUNCTION(0x805C3A20, OS__SleepTicks_HLE_801aaca8);  // Utage OSSleepTicks\n'),
    # GameSaveKey fingerprinted every file of the game folder with std::filesystem::relative (several
    # stats per file): instant for Basara's handful of files, 35+ s at boot for Utage's 19,585 (worse on
    # a phone's shared storage). sys/ alone is enough: fst.bin lists every disc file with its size, so a
    # mod still gets its own key. The relative name is computed lexically, without touching the disk.
    ('include/nand_path.h',
     '    for (std::filesystem::recursive_directory_iterator it(root, ec), end; !ec && it != end; it.increment(ec)) {',
     '    // Utage: sys/ only (fst.bin carries every file\'s size); the whole folder is 19,585 files.\n'
     '    const std::filesystem::path scan = std::filesystem::is_directory(root / "sys", ec) ? root / "sys" : root;\n'
     '    for (std::filesystem::recursive_directory_iterator it(scan, ec), end; !ec && it != end; it.increment(ec)) {'),
    ('include/nand_path.h',
     '            const auto relative = std::filesystem::relative(it->path(), root, fileError).generic_u8string();',
     '            const auto relative = it->path().lexically_relative(root).generic_u8string();'),
    # IOS_Seek (synchronous, 0x805A68D0: builds IPC command 5 like IOS_Read/IOS_Write next to it): Basara
    # never called it, so only IOS_SeekAsync had an HLE. Utage's NANDSeek runs the real IPC code: no IOS
    # behind it, an error comes back, and the game's NAND fatal-error loop (0x807EFDA0: dimmed screen,
    # "Wii本体保存メモリ..." message, OSSleepTicks forever) took over while copying files to NAND /tmp.
    ('src/hle/ios.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(805A67F0, IOS_SeekAsync_HLE, (CpuContext* ctx), (ctx));\n',
     'PPC_NATIVE_OVERRIDE_VOID(805A67F0, IOS_SeekAsync_HLE, (CpuContext* ctx), (ctx));\n\n'
     '// Utage: IOS_Seek, the synchronous one (see tools/u_manual.py).\n'
     'extern "C" void IOS_Seek_HLE_utage(CpuContext* ctx) {\n'
     '    const uint32_t fd = ctx->gpr[3];\n'
     '    const int32_t offset = static_cast<int32_t>(ctx->gpr[4]);\n'
     '    const int32_t whence = static_cast<int32_t>(ctx->gpr[5]);\n'
     '    SetIosReturn(ctx, NAND_IOS_Seek_HLE(fd, offset, whence));\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805A68D0, IOS_Seek_HLE_utage, (CpuContext* ctx), (ctx));\n'),
    # NAND /tmp is emptied at every boot on the console. Here it kept what earlier runs left, 0-byte
    # copies from failed runs among them, and the game took those as its cached files.
    ('src/hle/storage/nand_fs.cpp',
     '        g_dolphinWiiBase = RuntimeNandPath::DiscoverNandRootPath();\n',
     '        g_dolphinWiiBase = RuntimeNandPath::DiscoverNandRootPath();\n'
     '        std::error_code tmpError;  // Utage: the console empties /tmp at boot\n'
     '        std::filesystem::remove_all(g_dolphinWiiBase / "tmp", tmpError);\n'),
    # IOS/NAND completion callbacks ran inside the async call itself (queued, then drained at once),
    # i.e. before IOS_OpenAsync & co. returned. On hardware they come later through the IPC
    # interrupt, and code that sets a "waiting" state after the async call returns would have its
    # callback's "done" overwritten. They now stay queued for the next alarm-queue pump (idle loop,
    # retrace, interrupt restore), which drains them and reschedules, like the IPC interrupt.
    ('src/hle/storage/nand_async.cpp',
     '        g_pendingNandCallbacks.push_back({callbackPtr, result, commandBlock});\n    }\n\n'
     '    if (g_nandCallbackDrainDepth == 0) {\n        NandProcessPendingCallbacks(nullptr, 64);\n    }\n}\n',
     '        g_pendingNandCallbacks.push_back({callbackPtr, result, commandBlock});\n    }\n'
     '    // Utage: delivered by the next ProcessAlarmQueue pump, never inside the async call.\n}\n'),
    # SCGetLanguage: NSMBW's USA logic answered 1 (English). Utage is a Japanese disc for Japanese
    # consoles (SC_LANG_JAPANESE = 0; the disc has rom/jpn only). With 0 it caches the Japanese HOME
    # menu (hbm_jpn.hbm) to NAND /tmp at boot as on a Japanese Wii.
    ('src/hle/sc.cpp',
     '        const uint32_t code = chosen == "es" ? 4u : chosen == "fr" ? 3u : 1u;\n',
     '        const uint32_t code = 0u;  // Utage: SC_LANG_JAPANESE (Japanese disc and console)\n'),
    # Utage save manager (singleton r13-0x644C = 0x808F40D4, state at +0xF30C under its mutex): the main
    # thread posts a request (state 2) and spins "while (state != 0)" in 0x8010E74C / 0x8010E7C0; the
    # worker thread polls every 5 ms (0x807F28F8: state 2? else OSSleepTicks(5 ms)). On hardware the
    # worker's alarm preempts the spinner; here the spin starved the host loop (no alarms, no
    # retraces): frozen on the "Load" dialog. From those two loops, the busy query now waits one
    # retrace while the manager is busy, which parks the main thread and lets the worker run.
    ('src/hle/vi.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(805CF540, VIWaitForRetrace_HLE_801b99ec, (CpuContext* ctx), (ctx));\n',
     'PPC_NATIVE_OVERRIDE_VOID(805CF540, VIWaitForRetrace_HLE_801b99ec, (CpuContext* ctx), (ctx));\n'
     '\n'
     '// Utage: the save manager\'s busy query (0x8010EA8C, state != 0). See tools/u_manual.py.\n'
     'extern "C" void UtageSaveBusy_HLE_8010ea8c(CpuContext* ctx)\n'
     '{\n'
     '    CpuContext* cpu = ctx ? ctx : &GetPersistentCpuContext();\n'
     '    const uint32_t caller = cpu->lr;\n'
     '    cpu->gpr[3] = ::Memory::Read32(0x808F40D4u);  // the manager (r13-0x644C)\n'
     '    InvokeIndirectCpu(0x807F187Cu, cpu);          // its state, read under its mutex\n'
     '    const uint32_t busy = cpu->gpr[3] != 0 ? 1u : 0u;\n'
     '    if (busy && (caller == 0x8010E77Cu || caller == 0x8010E7DCu)) {\n'
     '        VIWaitForRetrace_HLE_801b99ec(cpu);  // the spin loops: give the worker a frame\n'
     '    }\n'
     '    ViSetR3(cpu, busy);\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(8010EA8C, UtageSaveBusy_HLE_8010ea8c, (CpuContext* ctx), (ctx));\n'),
    # RunQueueBits out of step with RunQueue: at the stuck "Load" dialog RunQueue[2] held a READY
    # thread (priority 2) while its bit was clear, so SelectThread never saw it and the main thread
    # (priority 16) ran on alone. SelectThread now rebuilds the bits from the queue heads first (the
    # SDK's invariant: bit set <=> queue not empty), logging each correction.
    ('src/hle/os/os_scheduler.cpp',
     'extern "C" void SelectThread_801a9c08(CpuContext* ctx)\n{\n'
     '    CpuContext* cpu = ctx ? ctx : &GetPersistentCpuContext();\n'
     '    const uint32_t forceSwitch = cpu->gpr[3];\n\n'
     '    ProcessSleepTimers(cpu);\n',
     'namespace {\n'
     '// Utage: RunQueueBits from the RunQueue heads (see tools/u_manual.py).\n'
     'void ResyncRunQueueBits()\n'
     '{\n'
     '    uint32_t bits = 0;\n'
     '    for (uint32_t q = 0; q < 32u; ++q) {\n'
     '        if (::Memory::Read32(kThreadQueueArrayAddr + q * 8u) != 0) {\n'
     '            bits |= 1u << (31u - q);\n'
     '        }\n'
     '    }\n'
     '    const uint32_t old = ::Memory::Read32(kSchedulerPendingFlagAddr);\n'
     '    if (bits != old) {\n'
     '        static uint32_t s_reports = 0;\n'
     '        if (s_reports < 20) {\n'
     '            ++s_reports;\n'
     '            RT_LOGF(RT_TAG_OS, "SelectThread: RunQueueBits 0x%08X -> 0x%08X (from the queue heads)\\n", old, bits);\n'
     '        }\n'
     '        ::Memory::Write32(kSchedulerPendingFlagAddr, bits);\n'
     '    }\n'
     '}\n'
     '} // namespace\n\n'
     'extern "C" void SelectThread_801a9c08(CpuContext* ctx)\n{\n'
     '    CpuContext* cpu = ctx ? ctx : &GetPersistentCpuContext();\n'
     '    const uint32_t forceSwitch = cpu->gpr[3];\n\n'
     '    ProcessSleepTimers(cpu);\n'
     '    ResyncRunQueueBits();\n'),
    # GXDrawDone: on the console the caller sleeps on an OS queue until the GPU's draw-done interrupt,
    # so other threads run meanwhile. The HLE waited for aurora on the host thread (~13 ms a frame on a
    # phone) with no guest thread able to run: Utage's resource job thread and loader, which work in
    # small steps with 1 ms sleeps between them, only got the leftovers between frames, and the
    # "読み込み中" loading screen after the opening crawled. The main thread now parks 0.5 ms at a time
    # (up to 6 ms) before waiting for aurora, but only while that buys something: a guest thread is
    # ready, or a sleep timer is armed and the frame is still inside its 60 Hz budget (loading screens).
    # It stops as soon as the GX thread has drawn everything. Parking for the timers alone in every
    # frame (the first version) cost a busy battle about 6 ms a frame: the game thread slept 1 ms
    # seven times a frame, 23% of its time (Poco X6 sched trace, 2026-11-23).
    ('src/hle/gx/gx_stubs.cpp',
     'extern "C" void GX__DrawDone_8016eab0() {\n'
     '    try { Memory::Write8(kGxDrawDoneFlagAddr, 0); } catch (...) {}\n'
     '    GXDrawDone(); GX__FinishInterruptHandler_8016ed94();\n}\n',
     '// Utage: let other guest threads run while the GPU drains (see tools/u_manual.py).\n'
     'namespace OsHleInternal { uint64_t NextSleepTimerTicks(); }\n'
     'extern "C" void OS__SleepTicks_HLE_801aaca8(CpuContext* ctx);\n'
     'extern "C" bool AuroraGxThreadEnabled();\n'
     'extern "C" uint64_t AuroraGxThreadMark();\n'
     'extern "C" bool AuroraGxThreadMarkReached(uint64_t ticket);\n'
     'uint64_t VI_HLE_SinceRetraceNanos();\n'
     'static void UtageYieldWhileGpuDrains() {\n'
     '    CpuContext* cpu = TryGetCpuContext();\n'
     '    if (!cpu) return;\n'
     '    const bool gxThread = AuroraGxThreadEnabled();\n'
     '    const uint64_t mark = gxThread ? AuroraGxThreadMark() : 0;\n'
     '    constexpr uint64_t kFrameBudgetNanos = 12000000;  // well inside a 60 Hz frame\n'
     '    const auto start = std::chrono::steady_clock::now();\n'
     '    while (std::chrono::steady_clock::now() - start < std::chrono::milliseconds(6)) {\n'
     '        if (gxThread && AuroraGxThreadMarkReached(mark)) break;  // drawn: nothing left to wait for\n'
     '        const bool ready = Memory::Read32(0x808F3A60u) != 0;  // RunQueueBits\n'
     '        const bool timers = OsHleInternal::NextSleepTimerTicks() != std::numeric_limits<uint64_t>::max();\n'
     '        if (!ready && !(timers && VI_HLE_SinceRetraceNanos() < kFrameBudgetNanos)) break;\n'
     '        const uint32_t r3 = cpu->gpr[3], r4 = cpu->gpr[4];\n'
     '        cpu->gpr[3] = 0;\n'
     '        cpu->gpr[4] = 30375u;  // 0.5 ms of time base (243 MHz / 4 / 2000)\n'
     '        OS__SleepTicks_HLE_801aaca8(cpu);\n'
     '        cpu->gpr[3] = r3;\n'
     '        cpu->gpr[4] = r4;\n'
     '    }\n'
     '}\n\n'
     'extern "C" void GX__DrawDone_8016eab0() {\n'
     '    try { Memory::Write8(kGxDrawDoneFlagAddr, 0); } catch (...) {}\n'
     '    UtageYieldWhileGpuDrains();\n'
     '    GXDrawDone(); GX__FinishInterruptHandler_8016ed94();\n}\n'),
    ('src/hle/gx/gx_stubs.cpp', '#include "runtime_log.h"\n',
     '#include "runtime_log.h"\n#include "isa/ppc_isa_context.h"\n#include <chrono>\n#include <limits>\n'),
    # Camera distance in battle: the view's projection as it is loaded into GX (basara_frameskip.cpp,
    # UtageWidenProjection).
    ('src/hle/gx/gx_transform.cpp', 'extern "C" void GX__SetProjection_8017301c(uint32_t ma, uint32_t pt) {\n',
     'void UtageWidenProjection(float* m, uint32_t lr);\n\n'
     'extern "C" void GX__SetProjection_8017301c(uint32_t ma, uint32_t pt) {\n'),
    ('src/hle/gx/gx_transform.cpp',
     '    BasaraHud_SetProjection(pt == GX_ORTHOGRAPHIC, m[0]);\n    GXSetProjection(m, (GXProjectionType)pt);\n',
     '    if (pt == GX_PERSPECTIVE) {\n'
     '        if (const CpuContext* cpu = TryGetCpuContext()) UtageWidenProjection(m, cpu->lr);\n'
     '    }\n'
     '    BasaraHud_SetProjection(pt == GX_ORTHOGRAPHIC, m[0]);\n    GXSetProjection(m, (GXProjectionType)pt);\n'),
    # How far the current frame is from its retrace (gx_stubs.cpp's GXDrawDone yield).
    ('src/hle/vi.cpp', 'uint64_t VI_HLE_IdleNanosTotal() {\n',
     'uint64_t VI_HLE_SinceRetraceNanos() {\n'
     '    std::lock_guard<std::mutex> lock(g_viMutex);\n'
     '    return static_cast<uint64_t>(std::max<int64_t>(0, std::chrono::duration_cast<std::chrono::nanoseconds>(\n'
     '        Clock::now() - g_vi.lastRetrace).count()));\n'
     '}\n\n'
     'uint64_t VI_HLE_IdleNanosTotal() {\n'),
    # Diagnostic: per second, how many GX_QUADS draws of each vertex count (immediate GXBegin and raw FIFO),
    # to tell a one-glyph text draw from a multi-glyph draw that renders only its first quad.
    ('src/hle/gx/gx_vertex.cpp',
     'extern "C" void GX__Begin_8016f0f0(uint32_t t, uint32_t vf, uint32_t nv) {\n',
     'void UtageQuadDiag(uint32_t prim, uint32_t nv, const char* path) {  // Utage diagnostic\n'
     '    static std::mutex s_m;\n'
     '    static std::map<std::pair<std::string, uint32_t>, uint32_t> s_counts;\n'
     '    static auto s_last = std::chrono::steady_clock::now();\n'
     '    std::lock_guard<std::mutex> lock(s_m);\n'
     '    std::string key = std::string(path) + "/p" + std::to_string(prim);\n'
     '    if (nv == 4 && g_currentCpuContext) { char lr[16]; std::snprintf(lr, sizeof(lr), "@%08X", g_currentCpuContext->lr); key += lr; }\n'
     '    ++s_counts[{key, nv}];\n'
     '    const auto now = std::chrono::steady_clock::now();\n'
     '    if (now - s_last < std::chrono::seconds(5)) return;\n'
     '    s_last = now;\n'
     '    std::string line;\n'
     '    for (const auto& [k, n] : s_counts) line += " " + k.first + ":" + std::to_string(k.second) + "x" + std::to_string(n);\n'
     '    RT_LOGF(RT_TAG_GX, "[quads] 5s:%s\\n", line.c_str());\n'
     '    s_counts.clear();\n'
     '}\n\n'
     'extern "C" void GX__Begin_8016f0f0(uint32_t t, uint32_t vf, uint32_t nv) {\n'
     '    UtageQuadDiag(t, nv, "begin");\n'),
    ('src/hle/gx/gx_vertex.cpp', '#include <cstdio>\n', '#include <cstdio>\n#include <map>\n#include <mutex>\n#include <string>\n#include <chrono>\n#include "isa/ppc_isa_context.h"\n'),
    ('src/hle/gx/gx_fifo.cpp',
     'static bool TrySubmitRawDirectFifoDraw(const uint8_t* packet, uint32_t packetBytes, GXPrimitive prim,\n',
     'void UtageQuadDiag(uint32_t prim, uint32_t nv, const char* path);  // Utage diagnostic (gx_vertex.cpp)\n'
     'static bool TrySubmitRawDirectFifoDraw(const uint8_t* packet, uint32_t packetBytes, GXPrimitive prim,\n'),
    ('src/hle/gx/gx_fifo.cpp',
     '            const GXPrimitive prim = OpcodeToGXPrimitive(cmd);\n'
     '            uint32_t rawVertexSize = 0;\n',
     '            const GXPrimitive prim = OpcodeToGXPrimitive(cmd);\n'
     '            UtageQuadDiag(prim, vtxCount, "fifo");\n'
     '            uint32_t rawVertexSize = 0;\n'),
    ('src/hle/gx/gx_dl.cpp',
     '        ApplyAuroraVtxStateForDlBegin(vtxfmt);\n        GXBegin(OpcodeToGXPrimitive(opcode), vtxfmt, vtxCount);\n',
     '        ApplyAuroraVtxStateForDlBegin(vtxfmt);\n        UtageQuadDiag(OpcodeToGXPrimitive(opcode), vtxCount, "dl");  // Utage diagnostic\n'
     '        GXBegin(OpcodeToGXPrimitive(opcode), vtxfmt, vtxCount);\n'),
    ('src/hle/gx/gx_dl.cpp', 'extern "C" bool AuroraGxThreadMarkReached(uint64_t ticket);\n',
     'extern "C" bool AuroraGxThreadMarkReached(uint64_t ticket);\n'
     'void UtageQuadDiag(uint32_t prim, uint32_t nv, const char* path);  // Utage diagnostic (gx_vertex.cpp)\n'),
    # Diagnostic: OSDisableScheduler / OSEnableScheduler (0x805C25C0 / 0x805C2600: Reschedule += / -= 1
    # under disabled interrupts, the old value returned) as HLEs that remember who last raised the count
    # from 0 (thread, caller), printed with the [sched] line: during the stuck loading screen the count
    # sat at 1 and SelectThread never switched.
    ('src/hle/os/os_scheduler.cpp',
     'extern "C" void SelectThread_801a9c08(CpuContext* ctx)\n{\n',
     'static uint32_t g_utageSchedRaiseThread = 0, g_utageSchedRaiseLr = 0, g_utageSchedRaises = 0;\n'
     'extern "C" void UtageOSDisableScheduler(CpuContext* ctx)\n'
     '{\n'
     '    const int32_t irq = OS__DisableInterrupts_801a65ac();\n'
     '    const uint32_t old = ::Memory::Read32(kSchedulerIdleFlagAddr);\n'
     '    ::Memory::Write32(kSchedulerIdleFlagAddr, old + 1u);\n'
     '    if (old == 0) {\n'
     '        g_utageSchedRaiseThread = ::Memory::Read32(kOSRunningContextAddr);\n'
     '        g_utageSchedRaiseLr = ctx->lr;\n'
     '        ++g_utageSchedRaises;\n'
     '    }\n'
     '    OS__RestoreInterrupts_801a65d4(irq);\n'
     '    ctx->gpr[3] = old;\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805C25C0, UtageOSDisableScheduler, (CpuContext* ctx), (ctx));\n'
     'extern "C" void UtageOSEnableScheduler(CpuContext* ctx)\n'
     '{\n'
     '    const int32_t irq = OS__DisableInterrupts_801a65ac();\n'
     '    const uint32_t old = ::Memory::Read32(kSchedulerIdleFlagAddr);\n'
     '    ::Memory::Write32(kSchedulerIdleFlagAddr, old - 1u);\n'
     '    OS__RestoreInterrupts_801a65d4(irq);\n'
     '    ctx->gpr[3] = old;\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805C2600, UtageOSEnableScheduler, (CpuContext* ctx), (ctx));\n\n'
     'extern "C" void SelectThread_801a9c08(CpuContext* ctx)\n{\n'),
    # Two GX hooks the remap put on game code (tiny bodies that many functions share): GXSetTevDirect
    # on 0x80343CF4 (a game function starting "li r4,-1; li r5,0") and GXInitTexObjUserData on 0x800303CC
    # (a game setter). The SDK ones are 0x805A39B0 (calls GXSetTevIndirect 0x805A3610, Dolphin name) and
    # 0x805A2A50 ("stw r4,0x10(r3); blr" after GXInitTexObjMaxAniso). Those game functions run natively again.
    ('src/hle/gx/gx_indirect.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(80343CF4, GX__SetTevDirect_80171b58, (uint32_t s), (s));\n',
     'PPC_NATIVE_OVERRIDE_VOID(805A39B0, GX__SetTevDirect_80171b58, (uint32_t s), (s));  // Utage GXSetTevDirect\n'),
    ('src/hle/gx/gx_texture.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(800303CC, GX__InitTexObjUserData_80170be8,\n',
     'PPC_NATIVE_OVERRIDE_VOID(805A2A50, GX__InitTexObjUserData_80170be8,  // Utage GXInitTexObjUserData\n'),
    # VI startup retraces: g_catchUpRetraceNanos starts at kStartupRetraces (2 ms retraces, plus a
    # catch-up retrace on every idle poll) until Basara's main-loop hook (basara_frameskip, 0x802BE4F4)
    # sets its own value at its first frame. Utage has no such hook, so the mode never ended: the
    # retrace count ran into the tens of millions and the game's frame clock with it (message text
    # stopped at its first character). Utage starts in normal 60 Hz retraces.
    ('src/hle/vi.cpp',
     'std::atomic<int64_t> g_catchUpRetraceNanos{kStartupRetraces};\n',
     'std::atomic<int64_t> g_catchUpRetraceNanos{0};  // Utage: no Basara main-loop hook ends the startup mode\n'),
    # A thread whose entry function returns. On hardware it returns into OSExitThread(r3), which
    # terminates the thread and reschedules. The fiber wrapper instead cleared the OS running/current
    # thread to 0 and switched straight to the scheduler fiber, i.e. resumed the main thread wherever it
    # had last switched away, picked by nobody and possibly still meant to be waiting. With running = 0
    # every later SelectThread returned at once: no thread switch ever again. Basara's threads never
    # return; Utage's MT Framework workers do (the NAND cache copier, ~35 s in), and the loader then
    # starved on the "読み込み中" screen. A returning entry now goes through the OSExitThread HLE (the
    # old cleanup + scheduler switch stays as the fallback if no switch happens).
    ('src/fiber_manager.cpp', '#include "system_bridge.h"\n',
     '#include "system_bridge.h"\n'
     'extern "C" void OSExitThread_HLE_801aa0f0(CpuContext* ctx);  // Utage: returning thread entries\n'),
    ('src/fiber_manager.cpp',
     '    // Thread entry functions normally return into OSExitThread on hardware.\n',
     '    // Utage: exit the way the console does, through OSExitThread with the entry\'s return value.\n'
     '    if (Memory::Read32(kOSRunningContextAddr) == guestThreadAddr) {\n'
     '        OSExitThread_HLE_801aa0f0(cpu);\n'
     '    }\n\n'
     '    // Thread entry functions normally return into OSExitThread on hardware.\n'),
    # Diagnostic: a host backtrace (offsets into libmain.so) of SelectThread calls made with the
    # scheduler disabled and no running thread, every 3 s, to see which runtime path runs guest code there.
    ('src/hle/os/os_scheduler.cpp',
     'static uint32_t g_utageSchedRaiseThread = 0, g_utageSchedRaiseLr = 0, g_utageSchedRaises = 0;\n',
     'static uint32_t g_utageSchedRaiseThread = 0, g_utageSchedRaiseLr = 0, g_utageSchedRaises = 0;\n'
     '#if defined(__ANDROID__)\n'
     '#include <unwind.h>\n'
     '#include <dlfcn.h>\n'
     'namespace {\n'
     'struct UtageBt { uintptr_t pcs[48]; int n = 0; };\n'
     '_Unwind_Reason_Code UtageBtStep(struct _Unwind_Context* c, void* arg) {\n'
     '    auto* bt = static_cast<UtageBt*>(arg);\n'
     '    const uintptr_t pc = _Unwind_GetIP(c);\n'
     '    if (pc != 0 && bt->n < 48) bt->pcs[bt->n++] = pc;\n'
     '    return bt->n < 48 ? _URC_NO_REASON : _URC_END_OF_STACK;\n'
     '}\n'
     '} // namespace\n'
     'static void UtageLogHostBacktrace() {\n'
     '    UtageBt bt;\n'
     '    _Unwind_Backtrace(UtageBtStep, &bt);\n'
     '    Dl_info info{};\n'
     '    uintptr_t base = 0;\n'
     '    if (dladdr(reinterpret_cast<void*>(&UtageLogHostBacktrace), &info)) base = reinterpret_cast<uintptr_t>(info.dli_fbase);\n'
     '    std::string line;\n'
     '    char item[24];\n'
     '    for (int i = 0; i < bt.n; ++i) {\n'
     '        std::snprintf(item, sizeof(item), " 0x%lx", static_cast<unsigned long>(bt.pcs[i] - base));\n'
     '        line += item;\n'
     '    }\n'
     '    RT_LOGF(RT_TAG_OS, "[sched] host bt:%s\\n", line.c_str());\n'
     '}\n'
     '#else\n'
     'static void UtageLogHostBacktrace() {}\n'
     '#endif\n'),
    # Diagnostic: what SelectThread sees (every 3 s) and the switches it makes (rate-limited).
    ('src/hle/os/os_scheduler.cpp',
     '    ProcessSleepTimers(cpu);\n    ResyncRunQueueBits();\n',
     '    ProcessSleepTimers(cpu);\n    ResyncRunQueueBits();\n'
     '    {  // Utage diagnostic\n'
     '        static uint64_t s_calls = 0;\n'
     '        static std::chrono::steady_clock::time_point s_last{};\n'
     '        ++s_calls;\n'
     '        const auto now = std::chrono::steady_clock::now();\n'
     '        if (now - s_last > std::chrono::seconds(3)) {\n'
     '            s_last = now;\n'
     '            RT_LOGF(RT_TAG_OS, "[sched] calls=%llu force=%u idle=%u cur=0x%08X run=0x%08X pending=0x%08X lr=0x%08X fiber=0x%08X raised-by 0x%08X lr 0x%08X (x%u)\\n",\n'
     '                    static_cast<unsigned long long>(s_calls), cpu->gpr[3], ::Memory::Read32(kSchedulerIdleFlagAddr),\n'
     '                    ::Memory::Read32(kOSCurrentContextAddr), ::Memory::Read32(kOSRunningContextAddr),\n'
     '                    ::Memory::Read32(kSchedulerPendingFlagAddr), cpu->lr,\n'
     '                    Fiber::GuestFiberManager::IsInitialized() ? Fiber::GuestFiberManager::GetCurrentGuestThread() : 0u,\n'
     '                    g_utageSchedRaiseThread, g_utageSchedRaiseLr, g_utageSchedRaises);\n'
     '            if (::Memory::Read32(kSchedulerIdleFlagAddr) != 0 && ::Memory::Read32(kOSRunningContextAddr) == 0) {\n'
     '                UtageLogHostBacktrace();\n'
     '            }\n'
     '        }\n'
     '    }\n'),
    ('src/hle/os/os_scheduler.cpp',
     '    TryInvokeSwitchCallback(runningContext, nextThread, cpu);\n',
     '    {  // Utage diagnostic\n'
     '        static uint32_t s_switches = 0;\n'
     '        if (++s_switches <= 40 || (s_switches % 500) == 0) {\n'
     '            RT_LOGF(RT_TAG_OS, "[sched] switch #%u 0x%08X -> 0x%08X (prio %d)\\n", s_switches, runningContext, nextThread,\n'
     '                    static_cast<int>(priorityLevel));\n'
     '        }\n'
     '    }\n'
     '    TryInvokeSwitchCallback(runningContext, nextThread, cpu);\n'),
    # Diagnostic: the VI watchdog also looks at 30-60 s and dumps the guest threads whenever the frame
    # count stopped moving since its last look (Utage froze on the save-load dialog after the strap screen).
    ('src/hle/vi.cpp',
     '            const auto start = std::chrono::steady_clock::now();\n'
     '            for (const int seconds : {12, 20}) {\n',
     '            const auto start = std::chrono::steady_clock::now();\n'
     '            uint32_t prevFrames = 0;  // Utage: also dump when frames stop advancing later on\n'
     '            for (const int seconds : {12, 20, 30, 40, 50, 60, 80, 100, 120}) {\n'),
    ('src/hle/vi.cpp',
     '                if (frames > 2 && !black) {  // Basara: also dump when stalled after the first frame\n',
     '                const bool advanced = frames != prevFrames;\n'
     '                prevFrames = frames;\n'
     '                if (frames > 2 && !black && advanced && seconds != 100 && seconds != 120) {  // Basara: also dump when stalled after the first frame; Utage diagnostic: always at 100/120 s\n'),
    # Diagnostic: distinct pixel format / alpha update / dst alpha / color update calls, once each.
    ('src/hle/gx/gx_pixel.cpp', '// gx_pixel.cpp - Pixel Processing, Blending, and Fog\n#include "gx_internal.h"\n',
     '// gx_pixel.cpp - Pixel Processing, Blending, and Fog\n#include "gx_internal.h"\n#include "runtime_log.h"\n#include <cstdio>\n#include <set>\n#include <string>\n'
     'static void UtagePixDiag(const char* what, uint32_t a, uint32_t b) {  // Utage diagnostic\n'
     '    static std::set<std::string> s_seen;\n'
     '    char key[64]; std::snprintf(key, sizeof(key), "%s %u %u", what, a, b);\n'
     '    if (s_seen.size() < 100 && s_seen.insert(key).second) {\n'
     '        const CpuContext* cpu = TryGetCpuContext();\n'
     '        RT_LOGF(RT_TAG_GX, "[pixdiag] %s lr %08X\\n", key, cpu ? cpu->lr : 0);\n'
     '    }\n'
     '}\n'),
    ('src/hle/gx/gx_pixel.cpp',
     'extern "C" void GX__SetPixelFmt_80172888(uint32_t pf, uint32_t zf) {\n',
     'extern "C" void GX__SetPixelFmt_80172888(uint32_t pf, uint32_t zf) {\n'
     '    UtagePixDiag("pixelfmt", pf, zf);\n'),
    ('src/hle/gx/gx_pixel.cpp',
     'extern "C" void GX__SetAlphaUpdate_801727f8(uint32_t en) {\n',
     'extern "C" void GX__SetAlphaUpdate_801727f8(uint32_t en) {\n    UtagePixDiag("alphaupdate", en, 0);\n'),
    ('src/hle/gx/gx_pixel.cpp',
     'extern "C" void GX__SetDstAlpha_8017295c(uint32_t en, uint32_t a) {\n',
     'extern "C" void GX__SetDstAlpha_8017295c(uint32_t en, uint32_t a) {\n    UtagePixDiag("dstalpha", en, a);\n'),
    # Diagnostic: distinct TEV compare ops (op >= 8) and swap tables, once each.
    ('src/hle/gx/gx_tev.cpp', '#include "runtime_log.h"\n', '#include "runtime_log.h"\n#include <cstdio>\n#include <set>\n#include <string>\n'),
    ('src/hle/gx/gx_tev.cpp',
     'extern "C" void GX__SetTevColorOp_80171d60(uint32_t s, uint32_t op, uint32_t b, uint32_t sc, uint32_t cl, uint32_t or_) {\n',
     'static void UtageTevDiag(const char* what, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f) {  // Utage diagnostic\n'
     '    static std::set<std::string> s_seen;\n'
     '    char key[96]; std::snprintf(key, sizeof(key), "%s %u %u %u %u %u %u", what, a, b, c, d, e, f);\n'
     '    if (s_seen.size() < 200 && s_seen.insert(key).second) {\n'
     '        const CpuContext* cpu = TryGetCpuContext();\n'
     '        RT_LOGF(RT_TAG_GX, "[tevdiag] %s lr %08X\\n", key, cpu ? cpu->lr : 0);\n'
     '    }\n'
     '}\n\n'
     'extern "C" void GX__SetTevColorOp_80171d60(uint32_t s, uint32_t op, uint32_t b, uint32_t sc, uint32_t cl, uint32_t or_) {\n'
     '    if (op >= 8) UtageTevDiag("colorop", s, op, b, sc, cl, or_);\n'),
    ('src/hle/gx/gx_tev.cpp',
     'extern "C" void GX__SetTevAlphaOp_80171db8(uint32_t s, uint32_t op, uint32_t b, uint32_t sc, uint32_t cl, uint32_t or_) {\n',
     'extern "C" void GX__SetTevAlphaOp_80171db8(uint32_t s, uint32_t op, uint32_t b, uint32_t sc, uint32_t cl, uint32_t or_) {\n'
     '    if (op >= 8) UtageTevDiag("alphaop", s, op, b, sc, cl, or_);\n'),
    ('src/hle/gx/gx_tev.cpp',
     'extern "C" void GX__SetTevSwapModeTable_8017200c(uint32_t id, uint32_t r, uint32_t g, uint32_t b, uint32_t a) {\n',
     'extern "C" void GX__SetTevSwapModeTable_8017200c(uint32_t id, uint32_t r, uint32_t g, uint32_t b, uint32_t a) {\n'
     '    UtageTevDiag("swaptable", id, r, g, b, a, 0);\n'),
    # Diagnostic: every 5 s, the last perspective projection, viewport and immediate position matrices.
    ('src/hle/gx/gx_transform.cpp',
     '    const uint32_t* raw=(const uint32_t*)GuestToHostPtr(ma); float m[12];\n    SwapBeF32ArrayToHost(raw, m, 12);\n    GXLoadPosMtxImm((float(*)[4])m, id);\n',
     '    const uint32_t* raw=(const uint32_t*)GuestToHostPtr(ma); float m[12];\n    SwapBeF32ArrayToHost(raw, m, 12);\n    GXLoadPosMtxImm((float(*)[4])m, id);\n'
     '    {  // Utage diagnostic\n'
     '        static uint32_t s_count = 0; static auto s_last = std::chrono::steady_clock::now();\n'
     '        static uint32_t s_ids[64] = {};\n'
     '        ++s_count; ++s_ids[id & 63];\n'
     '        const auto now = std::chrono::steady_clock::now();\n'
     '        if (now - s_last > std::chrono::seconds(5)) {\n'
     '            s_last = now;\n'
     '            std::fprintf(stderr, "[mtx] %u posmtx/5s; id %u: %.3f %.3f %.3f %.2f | %.3f %.3f %.3f %.2f | %.3f %.3f %.3f %.2f; proj %.3f %.3f %.3f %.3f %.3f %.3f %.3f; vp %.1f %.1f %.1f %.1f %.3f %.3f\\n",\n'
     '                s_count, id, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11],\n'
     '                g_projectionVector[0], g_projectionVector[1], g_projectionVector[2], g_projectionVector[3], g_projectionVector[4], g_projectionVector[5], g_projectionVector[6],\n'
     '                g_viewportState[0], g_viewportState[1], g_viewportState[2], g_viewportState[3], g_viewportState[4], g_viewportState[5]);\n'
     '            std::string ids;\n'
     '            for (int i = 0; i < 64; ++i) if (s_ids[i]) { ids += " " + std::to_string(i) + ":" + std::to_string(s_ids[i]); s_ids[i] = 0; }\n'
     '            std::fprintf(stderr, "[mtx] ids%s\\n", ids.c_str());\n'
     '            s_count = 0;\n'
     '        }\n'
     '    }\n'),
    ('src/hle/gx/gx_transform.cpp', '#include <utility>\n', '#include <utility>\n#include <chrono>\n'),
    # Locked-cache DMA. MT Framework computes bone matrices in the locked cache and moves them with
    # LCLoadBlocks / LCStoreBlocks / LCStoreData (through tail-call wrappers 0x8060FCA0/B0/C0). The
    # native functions only program the DMA_U/DMA_L SPRs, which nothing emulates, so the matrix
    # palette the battle display lists load with GX_LOAD_INDX_A/B/C stayed zero and every skinned
    # model exploded into screen-sized polygons. The NSMBW-era synchronous copies, at Utage addresses.
    # Diagnostic: the first locked-cache transfers and a count every 5 s.
    ('src/hle/os/os_cache.cpp',
     'extern "C" void LCLoadBlocks_HLE_801a1894(CpuContext* ctx)\n{\n',
     'static void UtageLcDiag(const char* what, uint32_t dst, uint32_t src, uint32_t len) {  // Utage diagnostic\n'
     '    static uint32_t s_first = 0, s_count = 0; static auto s_last = std::chrono::steady_clock::now();\n'
     '    ++s_count;\n'
     '    if (s_first < 12) { ++s_first; RT_LOGF(RT_TAG_OS, "[lc] %s dst %08X src %08X len %u\\n", what, dst, src, len); }\n'
     '    const auto now = std::chrono::steady_clock::now();\n'
     '    if (now - s_last > std::chrono::seconds(5)) { s_last = now; RT_LOGF(RT_TAG_OS, "[lc] %u transfers/5s, last %s dst %08X src %08X len %u\\n", s_count, what, dst, src, len); s_count = 0; }\n'
     '}\n\n'
     'extern "C" void LCLoadBlocks_HLE_801a1894(CpuContext* ctx)\n{\n'
     '    UtageLcDiag("load", (uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4], DecodeLcBlockCount((uint32_t)ctx->gpr[5]) * kCacheOpLineSize);\n'),
    ('src/hle/os/os_cache.cpp', '#include <cstring>\n', '#include <cstring>\n#include <chrono>\n'),
    ('src/hle/os/os_cache.cpp',
     'extern "C" uint32_t LCStoreData_HLE_801a18dc(CpuContext* ctx)\n{\n',
     'extern "C" uint32_t LCStoreData_HLE_801a18dc(CpuContext* ctx)\n{\n'
     '    UtageLcDiag("storedata", (uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5]);\n'),
    ('src/hle/os/os_cache.cpp',
     'extern "C" void LCStoreBlocks_HLE_801a18b8(CpuContext* ctx)\n{\n',
     'extern "C" void LCStoreBlocks_HLE_801a18b8(CpuContext* ctx)\n{\n'
     '    UtageLcDiag("store", (uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4], DecodeLcBlockCount((uint32_t)ctx->gpr[5]) * kCacheOpLineSize);\n'),
    ('src/hle/os/os_cache.cpp',
     'PPC_NATIVE_OVERRIDE_VOID(805bad90, Cache_Maintenance_Stub, (), ()); // LCDisable\n',
     'PPC_NATIVE_OVERRIDE_VOID(805bad90, Cache_Maintenance_Stub, (), ()); // LCDisable\n'
     'PPC_NATIVE_OVERRIDE_VOID(805BADC0, LCLoadBlocks_HLE_801a1894, (CpuContext* ctx), (ctx));  // Utage LCLoadBlocks\n'
     'PPC_NATIVE_OVERRIDE_VOID(805BADF0, LCStoreBlocks_HLE_801a18b8, (CpuContext* ctx), (ctx));  // Utage LCStoreBlocks\n'
     'PPC_NATIVE_OVERRIDE(805BAE20, LCStoreData_HLE_801a18dc, uint32_t, (CpuContext* ctx), (ctx));  // Utage LCStoreData\n'
     'PPC_NATIVE_OVERRIDE(805BAEC0, LCQueueLength_HLE_801a197c, uint32_t, (CpuContext* ctx), (ctx));  // Utage LCQueueLength\n'
     'PPC_NATIVE_OVERRIDE_VOID(805BAED0, LCQueueWait_HLE_801a1988, (CpuContext* ctx), (ctx));  // Utage LCQueueWait\n'
     '// Utage: MT Framework\'s locked-cache manager. Its enable (0x8060FB10) calls LCEnable and sets the\n'
     '// flag byte 0x809AEC00 that every locked-cache user checks (acquire 0x8060FBF0). With the flag set,\n'
     '// model bone matrices are built at 0xE0000000 and DMA\'d out; that path comes out with zero rotation\n'
     '// rows here (cause not pinned down), so every skinned model exploded across the screen. With the\n'
     '// flag left at 0 MT builds the matrices straight into their buffers, which renders correctly and\n'
     '// skips a copy that buys nothing on a host CPU.\n'
     'extern "C" void UtageMtLockedCacheEnable_HLE() {}\n'
     'PPC_NATIVE_OVERRIDE_VOID(8060FB10, UtageMtLockedCacheEnable_HLE, (), ());\n'),
    # SDK 2010 GXSetZScaleOffset(scale, offset) only stores a depth multiplier (1 + 2^24-1 * scale) and
    # offset (2^24-1 * offset) that __GXSetViewport applies to near/far: zRange = (far - near) * mul,
    # farZ = far * mul + offset. Aurora's version writes mul/offset straight into the viewport's zRange
    # and farZ registers, so the game's GXSetZScaleOffset(1, 0) at every render pass (and per draw
    # group, 0x8071C7AC) collapsed the depth range to zero: znear = zfar = 1.0 and every 3D object
    # failed the depth test (battle world invisible, HUD fine). Keep the SDK's math instead.
    ('src/hle/gx/gx_transform.cpp',
     'extern "C" void GX__SetViewportJitter_80173378(float l, float t, float w, float h, float nz, float fz, uint32_t f) {\n'
     '    g_viewportState[0]=l; g_viewportState[1]=t; g_viewportState[2]=w; g_viewportState[3]=h; g_viewportState[4]=nz; g_viewportState[5]=fz;\n'
     '    GXSetViewportJitter(l, t, w, h, nz, fz, f);\n',
     'static bool g_utageZScaleSet = false;\n'
     'static float g_utageZMul = 16777215.0f;\n'
     'static float g_utageZOffset = 0.0f;\n'
     '// Rewrites the viewport depth registers (XF 0x101C zRange, 0x101F farZ) from the stored viewport and\n'
     '// the SDK depth multiplier/offset.\n'
     'static void UtageEmitViewportDepth() {\n'
     '    if (!g_utageZScaleSet) return;\n'
     '    const float zRange = (g_viewportState[5] - g_viewportState[4]) * g_utageZMul;\n'
     '    const float farZ = g_viewportState[5] * g_utageZMul + g_utageZOffset;\n'
     '    uint8_t packet[18];\n'
     '    packet[0] = 0x10; BigEndian::Write32(packet + 1, 0x0000101Cu); BigEndian::WriteFloat32(packet + 5, zRange);\n'
     '    packet[9] = 0x10; BigEndian::Write32(packet + 10, 0x0000101Fu); BigEndian::WriteFloat32(packet + 14, farZ);\n'
     '    GXCallDisplayList(packet, sizeof(packet));\n'
     '}\n\n'
     'extern "C" void GX__SetViewportJitter_80173378(float l, float t, float w, float h, float nz, float fz, uint32_t f) {\n'
     '    g_viewportState[0]=l; g_viewportState[1]=t; g_viewportState[2]=w; g_viewportState[3]=h; g_viewportState[4]=nz; g_viewportState[5]=fz;\n'
     '    GXSetViewportJitter(l, t, w, h, nz, fz, f);\n'
     '    UtageEmitViewportDepth();\n'),
    ('src/hle/gx/gx_transform.cpp',
     '    GXSetViewport(l, t, w, h, nz, fz);\n}\n',
     '    GXSetViewport(l, t, w, h, nz, fz);\n    UtageEmitViewportDepth();\n}\n'),
    ('src/hle/gx/gx_transform.cpp',
     'extern "C" void GX__SetZScaleOffset_80173400(float s, float o) {\n    GXSetZScaleOffset(s, o);\n',
     'extern "C" void GX__SetZScaleOffset_80173400(float s, float o) {\n'
     '    g_utageZScaleSet = true;\n'
     '    g_utageZMul = 1.0f + 16777215.0f * s;\n'
     '    g_utageZOffset = 16777215.0f * o;\n'
     '    UtageEmitViewportDepth();\n'),
    # Diagnostic: display-list calls per 5 s by vertex descriptor (attrs 0..20 as N/D/1/2 = none, direct,
    # index8, index16), with how many fell back to per-vertex decoding.
    ('src/hle/gx/gx_dl.cpp',
     'extern "C" void GX__CallDisplayList_80172f64(uint32_t listAddr, uint32_t nbytes) {\n    if (nbytes == 0 || listAddr == 0) return;\n',
     'void UtageDlDiag(int kind) {  // Utage diagnostic: kind 0 = call, 1 = fallback\n'
     '    static std::mutex s_m; static std::map<std::string, std::pair<uint32_t, uint32_t>> s_counts;\n'
     '    static auto s_last = std::chrono::steady_clock::now();\n'
     '    std::lock_guard<std::mutex> lock(s_m);\n'
     '    std::string key;\n'
     '    for (int a = 0; a <= 20; ++a) key += "ND12"[g_hleGxState.vtxDesc[a] & 3];\n'
     '    const auto& vf = g_hleGxState.vtxAttrFmt[g_hleGxState.currentVtxFmt];\n'
     '    char extra[160]; std::snprintf(extra, sizeof(extra), " fmt%u pos@%08X/%u vat pos %u/%u/%u nrm %u/%u/%u tex0 %u/%u/%u", (unsigned)g_hleGxState.currentVtxFmt, g_hleGxState.vtxArray[GX_VA_POS].base, g_hleGxState.vtxArray[GX_VA_POS].stride,\n'
     '        (unsigned)vf[GX_VA_POS].cnt, (unsigned)vf[GX_VA_POS].type, (unsigned)vf[GX_VA_POS].frac, (unsigned)vf[GX_VA_NRM].cnt, (unsigned)vf[GX_VA_NRM].type, (unsigned)vf[GX_VA_NRM].frac,\n'
     '        (unsigned)vf[GX_VA_TEX0].cnt, (unsigned)vf[GX_VA_TEX0].type, (unsigned)vf[GX_VA_TEX0].frac);\n'
     '    key += extra;\n'
     '    auto& c = s_counts[key]; (kind == 0 ? c.first : c.second)++;\n'
     '    const auto now = std::chrono::steady_clock::now();\n'
     '    if (now - s_last < std::chrono::seconds(5)) return;\n'
     '    s_last = now;\n'
     '    std::string line;\n'
     '    int shown = 0;\n'
     '    for (const auto& [k, v] : s_counts) { if (shown++ < 12) line += "\\n   " + k + " calls " + std::to_string(v.first) + " fallback " + std::to_string(v.second); }\n'
     '    RT_LOGF(RT_TAG_GX, "[dlcalls] %zu layouts:%s\\n", s_counts.size(), line.c_str());\n'
     '    s_counts.clear();\n'
     '}\n\n'
     'extern "C" void GX__CallDisplayList_80172f64(uint32_t listAddr, uint32_t nbytes) {\n    if (nbytes == 0 || listAddr == 0) return;\n'
     '    UtageDlDiag(0);\n'
     '    if (g_hleGxState.vtxDesc[GX_VA_PNMTXIDX] == GX_DIRECT) {  // Utage diagnostic: sample DL bytes\n'
     '        static uint32_t s_samples = 0, s_calls = 0;\n'
     '        if ((++s_calls % 3000) == 1 && s_samples < 40 && (++s_samples, true)) {\n'
     '            const uint8_t* p = static_cast<const uint8_t*>(GuestToHostPtr(listAddr, std::min<uint32_t>(nbytes, 96)));\n'
     '            std::string hex;\n'
     '            for (uint32_t i = 0; p && i < std::min<uint32_t>(nbytes, 96); ++i) { char b[4]; std::snprintf(b, sizeof(b), "%02x", p[i]); hex += b; if ((i & 3) == 3) hex += " "; }\n'
     '            RT_LOGF(RT_TAG_GX, "[dlbytes] %08X+%u: %s\\n", listAddr, nbytes, hex.c_str());\n'
     '            for (int a = GX_POS_MTX_ARRAY; a <= GX_LIGHT_ARRAY; ++a) {\n'
     '                const auto& arr = g_hleGxState.vtxArray[a];\n'
     '                std::string m;\n'
     '                if (p && arr.base && arr.stride && (p[0] & 0xF8) >= 0x20 && (p[0] & 0xF8) <= 0x38) {\n'
     '                    const uint32_t idx = (uint32_t(p[1]) << 8) | p[2];\n'
     '                    for (int i = 0; i < 12; ++i) { uint32_t w = 0; Memory::TryRead32(arr.base + idx * arr.stride + i * 4, w); float f; std::memcpy(&f, &w, 4); char b[24]; std::snprintf(b, sizeof(b), " %.3f", f); m += b; }\n'
     '                }\n'
     '                RT_LOGF(RT_TAG_GX, "[dlbytes]   array %d base %08X stride %u first-idx mtx:%s\\n", a, arr.base, arr.stride, m.c_str());\n'
     '            }\n'
     '        }\n'
     '    }\n'),
    ('src/hle/gx/gx_dl.cpp', '#include <unordered_map>\n', '#include <unordered_map>\n#include <map>\n#include <mutex>\n#include <string>\n'),
    ('src/hle/gx/gx_dl.cpp',
     '        if (haveStateBeforeScan) {\n            RestoreGxVertexState(stateBeforeScan);\n        }\n        EnsureAuroraFrameActive();\n',
     '        if (haveStateBeforeScan) {\n            RestoreGxVertexState(stateBeforeScan);\n        }\n        UtageDlDiag(1);\n        EnsureAuroraFrameActive();\n'),
    # Boot shader precompile: the cached pipelines (about 1300 after a few sessions) were rebuilt in
    # the background while the game booted, every core busy: the first minute stuttered and its audio
    # crackled on a phone. Now the boot is held at its first black frame until they are built, with a
    # progress bar; with the driver cache kept (AURORA_VK_CACHE_DIR) later starts take seconds.
    ('include/settings_overlay.h', '#include <aurora/event.h>\n', '#include <aurora/event.h>\n#include <string>\n'),
    ('include/settings_overlay.h', 'bool StartupScreenVisible() noexcept;\n',
     'bool StartupScreenVisible() noexcept;\n'
     '// The boot shader precompile screen: total pipelines to build (0 hides it); progress is read live.\n'
     'void SetBootShaderProgress(uint32_t total) noexcept;\n'
     'bool BootShaderProgressVisible() noexcept;\n'
     '// Shaders building behind the game: a small corner counter until the queue empties, then\n'
     '// stampLine is written to stampPath (the next start knows the caches are warm).\n'
     'void StartBootShaderBackground(uint32_t total, const std::string& stampPath, const std::string& stampLine);\n'),
    # The boot is held at its first frame while the shaders build: not a stall for the watchdog (its
    # thread dump and guest samples at 12 and 20 s only cluttered the log).
    ('src/hle/vi.cpp',
     '                if (HostSuspend::Paused() || HostSuspend::PausedNanoseconds() != 0) {\n',
     '                if (settings_overlay::BootShaderProgressVisible()) {\n'
     '                    RT_LOGF(RT_TAG_VI, "[watchdog] building shaders; no stall dump\\n");\n'
     '                    continue;\n'
     '                }\n'
     '                if (HostSuspend::Paused() || HostSuspend::PausedNanoseconds() != 0) {\n'),
    ('src/settings_overlay.cpp', 'void DrawStartupScreen() {\n',
     'std::atomic<uint32_t> g_bootShaderTotal{0};\n'
     'std::atomic<uint32_t> g_bootShaderBackground{0};\n'
     'std::string g_bootShaderStampPath, g_bootShaderStampLine;\n\n'
     '// The background build\'s corner counter (bottom left, small, no input); the stamp once done.\n'
     'void DrawBootShaderBackground() {\n'
     '    const uint32_t total = g_bootShaderBackground.load(std::memory_order_acquire);\n'
     '    if (total == 0) {\n'
     '        return;\n'
     '    }\n'
     '    const uint32_t remaining = std::min(aurora_get_queued_pipeline_count(), total);\n'
     '    if (remaining == 0) {\n'
     '        g_bootShaderBackground.store(0, std::memory_order_relaxed);\n'
     '        if (!g_bootShaderStampPath.empty()) {\n'
     '            if (std::FILE* f = std::fopen(g_bootShaderStampPath.c_str(), "w")) {\n'
     '                std::fputs(g_bootShaderStampLine.c_str(), f);\n'
     '                std::fclose(f);\n'
     '            }\n'
     '        }\n'
     '        RT_LOGF(RT_TAG_GX, "boot: background shader build done (%u)\\n", total);\n'
     '        return;\n'
     '    }\n'
     '    const ImGuiViewport* viewport = ImGui::GetMainViewport();\n'
     '    const float scale = std::clamp(viewport->Size.y / 400.0f, 1.2f, 2.6f);\n'
     '    char line[64];\n'
     '    std::snprintf(line, sizeof(line), "Shaders %d%%", static_cast<int>(100.0f * static_cast<float>(total - remaining) / static_cast<float>(total)));\n'
     '    ImGui::SetNextWindowPos(ImVec2(viewport->Pos.x + 8.0f * scale, viewport->Pos.y + viewport->Size.y - 8.0f * scale), ImGuiCond_Always, ImVec2(0.0f, 1.0f));\n'
     '    ImGui::SetNextWindowBgAlpha(0.45f);\n'
     '    constexpr ImGuiWindowFlags kCornerFlags = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoFocusOnAppearing |\n'
     '                                              ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoNav |\n'
     '                                              ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_AlwaysAutoResize;\n'
     '    if (ImGui::Begin("Boot Shader Background", nullptr, kCornerFlags)) {\n'
     '        ImGui::SetWindowFontScale(scale * 0.75f);\n'
     '        ImGui::TextColored(ImVec4(0.80f, 0.82f, 0.88f, 1.0f), "%s", line);\n'
     '        ImGui::SetWindowFontScale(1.0f);\n'
     '    }\n'
     '    ImGui::End();\n'
     '}\n\n'
     'void DrawBootShaderProgress() {\n'
     '    const uint32_t total = g_bootShaderTotal.load(std::memory_order_relaxed);\n'
     '    if (total == 0) {\n'
     '        DrawBootShaderBackground();\n'
     '        return;\n'
     '    }\n'
     '    const uint32_t remaining = std::min(aurora_get_queued_pipeline_count(), total);\n'
     '    const uint32_t done = total - remaining;\n'
     '    const ImGuiViewport* viewport = ImGui::GetMainViewport();\n'
     '    ImGui::SetNextWindowPos(viewport->Pos, ImGuiCond_Always);\n'
     '    ImGui::SetNextWindowSize(viewport->Size, ImGuiCond_Always);\n'
     '    ImGui::SetNextWindowBgAlpha(1.0f);\n'
     '    ImGui::PushStyleColor(ImGuiCol_WindowBg, IM_COL32(0, 0, 0, 255));\n'
     '    constexpr ImGuiWindowFlags kFlags = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoFocusOnAppearing |\n'
     '                                        ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoNav |\n'
     '                                        ImGuiWindowFlags_NoSavedSettings;\n'
     '    if (ImGui::Begin("Boot Shader Precompile", nullptr, kFlags)) {\n'
     '        // Sized from the screen height (a phone\'s default font is tiny at 1080p and up), in the\n'
     '        // launcher\'s colours: red accent bar on a dark track, rounded.\n'
     '        const float scale = std::clamp(viewport->Size.y / 400.0f, 1.4f, 3.2f);\n'
     '        const float width = std::min(viewport->Size.x * 0.62f, 520.0f * scale);\n'
     '        const float left = (viewport->Size.x - width) * 0.5f;\n'
     '        const float fraction = static_cast<float>(done) / static_cast<float>(total);\n'
     '        ImGui::SetWindowFontScale(scale * 1.25f);\n'
     '        constexpr const char* kTitle = "Preparing shaders";\n'
     '        float y = viewport->Size.y * 0.36f;\n'
     '        ImGui::SetCursorPos(ImVec2((viewport->Size.x - ImGui::CalcTextSize(kTitle).x) * 0.5f, y));\n'
     '        ImGui::TextUnformatted(kTitle);\n'
     '        y += ImGui::GetTextLineHeight() * 1.5f;\n'
     '        ImGui::SetWindowFontScale(scale);\n'
     '        char line[96];\n'
     '        std::snprintf(line, sizeof(line), "%u / %u   %d%%", done, total, static_cast<int>(fraction * 100.0f));\n'
     '        ImGui::SetCursorPos(ImVec2((viewport->Size.x - ImGui::CalcTextSize(line).x) * 0.5f, y));\n'
     '        ImGui::TextColored(ImVec4(0.74f, 0.76f, 0.82f, 1.0f), "%s", line);\n'
     '        y += ImGui::GetTextLineHeight() * 1.6f;\n'
     '        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, 999.0f);\n'
     '        ImGui::PushStyleColor(ImGuiCol_FrameBg, IM_COL32(36, 39, 49, 255));\n'
     '        ImGui::PushStyleColor(ImGuiCol_PlotHistogram, IM_COL32(229, 72, 77, 255));\n'
     '        ImGui::SetCursorPos(ImVec2(left, y));\n'
     '        ImGui::ProgressBar(fraction, ImVec2(width, 10.0f * scale), "");\n'
     '        ImGui::PopStyleColor(2);\n'
     '        ImGui::PopStyleVar();\n'
     '        y += 10.0f * scale + ImGui::GetTextLineHeight() * 1.2f;\n'
     '        ImGui::SetWindowFontScale(scale * 0.8f);\n'
     '        constexpr const char* kHint = "Only the first start after installing or updating takes long.";\n'
     '        ImGui::SetCursorPos(ImVec2((viewport->Size.x - ImGui::CalcTextSize(kHint).x) * 0.5f, y));\n'
     '        ImGui::TextColored(ImVec4(0.55f, 0.57f, 0.63f, 1.0f), "%s", kHint);\n'
     '        ImGui::SetWindowFontScale(1.0f);\n'
     '    }\n'
     '    ImGui::End();\n'
     '    ImGui::PopStyleColor();\n'
     '}\n\n'
     'void DrawStartupScreen() {\n'),
    ('src/settings_overlay.cpp', '    DrawStartupScreen();\n}\n',
     '    DrawStartupScreen();\n    DrawBootShaderProgress();\n}\n'),
    ('src/settings_overlay.cpp', 'void AdvancePresentedFrame() noexcept { ++g_presentedFrame; }\n',
     'void AdvancePresentedFrame() noexcept { ++g_presentedFrame; }\n\n'
     'void SetBootShaderProgress(uint32_t total) noexcept { g_bootShaderTotal.store(total, std::memory_order_relaxed); }\n'
     'bool BootShaderProgressVisible() noexcept { return g_bootShaderTotal.load(std::memory_order_relaxed) != 0; }\n'
     'void StartBootShaderBackground(uint32_t total, const std::string& stampPath, const std::string& stampLine) {\n'
     '    g_bootShaderStampPath = stampPath;\n'
     '    g_bootShaderStampLine = stampLine;\n'
     '    g_bootShaderBackground.store(total, std::memory_order_release);\n'
     '    // The startup screen counts as up (and the pads stay blocked, ApplyInputBlockState) until the\n'
     '    // pipeline queue is empty or 3 minutes pass: with the build behind the game, a dialog ignored\n'
     '    // A for minutes (0.5.8, 0.6.0-dev4). These shaders do not hold the boot.\n'
     '    g_bootShadersReady.store(true, std::memory_order_release);\n'
     '}\n'),
    # The hold runs from GXInit (gx_init.cpp, below), before the game has drawn or copied anything:
    # held at the game's first GXCopyDisp instead, with GX Thread on a frame was sealed while that
    # copy's resolve was still the last pass (aurora "Final render pass must not have resolve target",
    # tester report, Infinix X6882, 2026-11-22).
    ('src/hle/gx/gx_copy.cpp', 'extern "C" void GX__CopyDisp_8016fc38(uint32_t da, uint32_t c) {\n',
     'extern "C" bool AuroraGxThreadEnabled();\n'
     'extern "C" uint64_t AuroraGxThreadMark();\n'
     'extern "C" void AuroraGxThreadWaitMark(uint64_t ticket);\n'
     '// Holds the boot at GXInit until the boot pipeline prewarm has drained, presenting the\n'
     '// precompile screen meanwhile (settings_overlay::SetBootShaderProgress).\n'
     'void UtageWaitForBootShaders() {\n'
     '    static bool s_done = false;\n'
     '    if (s_done) {\n'
     '        return;\n'
     '    }\n'
     '    s_done = true;\n'
     '    // The cached shaders wait unbuilt in aurora: a draw builds the one it needs. This hold builds\n'
     '    // them all only to fill the translated-shader and driver caches (0.6.0).\n'
     '    const uint32_t total = aurora_get_queued_pipeline_count() + aurora_get_dormant_pipeline_count();\n'
     '    RT_LOGF(RT_TAG_GX, "boot: %u cached pipelines at GX init\\n", total);\n'
     '    if (total <= 64) {\n'
     '        return;\n'
     '    }\n'
     '    // A start skips this only when the driver pipeline cache (AURORA_VK_CACHE_DIR, Android) holds\n'
     '    // what it needs: the last hold built at least this many shaders, under the same settings that\n'
     '    // key them (Graphics Compatibility, Disable Fog), as utage_prewarm.txt there records. A new\n'
     '    // install, an update with new shaders, or a changed setting waits here. Building thousands\n'
     '    // behind the game left it unresponsive for minutes and effects missing (0.5.8 test).\n'
     '    const char* cacheDir = std::getenv("AURORA_VK_CACHE_DIR");\n'
     '    // The shader generation too (aurora_shader_generation): an update that makes different shaders\n'
     '    // for the same pipelines needs the build once more.\n'
     '    std::string stamp = "compat" + std::to_string(RuntimeConfigFile::GpuCompat()) + (aurora_get_disable_fog() ? "-nofog" : "");\n'
     '    if (const char* generation = aurora_shader_generation(); generation != nullptr && generation[0] != \'\\0\') {\n'
     '        stamp += std::string("-") + generation;\n'
     '    }\n'
     '    // And the driver\'s cache identity: one another driver wrote (a system update, a custom GPU\n'
     '    // driver) is ignored by this one, so the shaders build again behind the game (1.0.0).\n'
     '    if (const char* driver = aurora_driver_cache_id(); driver != nullptr && driver[0] != \'\\0\') {\n'
     '        stamp += std::string("-") + driver;\n'
     '    }\n'
     '    if (cacheDir != nullptr) {\n'
     '        const std::filesystem::path dir(cacheDir);\n'
     '        std::error_code ec;\n'
     '        const auto bytes = std::filesystem::file_size(dir / "vk_pipeline_cache.bin", ec);\n'
     '        uint32_t built = 0;\n'
     '        std::string builtStamp;\n'
     '        {\n'
     '            std::ifstream f(dir / "utage_prewarm.txt");\n'
     '            f >> built >> builtStamp;\n'
     '        }\n'
     '        if (!ec && bytes > (4u << 20) && total <= built + 64u && builtStamp == stamp) {\n'
     '            RT_LOGF(RT_TAG_GX, "boot: driver pipeline cache present (%llu MiB, %u shaders built before): each builds when first drawn\\n",\n'
     '                    static_cast<unsigned long long>(bytes >> 20), built);\n'
     '            aurora_discard_cached_pipelines();\n'
     '            return;\n'
     '        }\n'
     '        RT_LOGF(RT_TAG_GX, "boot: %u shaders, %u built before (%s, now %s)\\n", total, built,\n'
     '                builtStamp.empty() ? "-" : builtStamp.c_str(), stamp.c_str());\n'
     '        // No Preparing shaders screen (0.6.0): they build behind the game on aurora\'s background\n'
     '        // workers (small cores, lowest priority, only to fill the caches) while a draw that needs\n'
     '        // one builds it first. A corner counter shows the progress and writes the stamp when\n'
     '        // done. BASARA_SHADER_HOLD=1 waits here as before.\n'
     '        if (const char* hold = std::getenv("BASARA_SHADER_HOLD"); hold == nullptr || hold[0] != \'1\') {\n'
     '            // The stamp names only a build that completed: a swipe out of Recents mid-build left\n'
     '            // the last stamp with a half-filled driver cache, and the next start took it for warm\n'
     '            // (1.0.0). The background build writes it again when done.\n'
     '            std::filesystem::remove(dir / "utage_prewarm.txt", ec);\n'
     '            const uint32_t queued = aurora_prewarm_cached_pipelines(false);\n'
     '            settings_overlay::StartBootShaderBackground(queued, (dir / "utage_prewarm.txt").string(),\n'
     '                                                        std::to_string(total) + \' \' + stamp + \'\\n\');\n'
     '            RT_LOGF(RT_TAG_GX, "boot: %u shaders build in the background\\n", queued);\n'
     '            return;\n'
     '        }\n'
     '    }\n'
     '    if (AuroraGxThreadEnabled()) AuroraGxThreadWaitMark(AuroraGxThreadMark());  // nothing in flight\n'
     '    EnsureAuroraFrameActive();\n'
     '    const auto start = std::chrono::steady_clock::now();\n'
     '    // Kept only where no driver cache carries them to the next start (the PC).\n'
     '    aurora_prewarm_cached_pipelines(cacheDir == nullptr);\n'
     '    settings_overlay::SetBootShaderProgress(total);\n'
     '    while (aurora_get_queued_pipeline_count() > 0 && std::chrono::steady_clock::now() - start < std::chrono::minutes(5)) {\n'
     '        settings_overlay::Draw();\n'
     '        VI_HLE_PresentFrame(false, false);\n'
     '        UpdateAuroraAndProcessEvents();\n'
     '        std::this_thread::sleep_for(std::chrono::milliseconds(33));\n'
     '        EnsureAuroraFrameActive();\n'
     '        aurora_wait_for_frame_worker();\n'
     '    }\n'
     '    settings_overlay::SetBootShaderProgress(0);\n'
     '    if (cacheDir != nullptr && aurora_get_queued_pipeline_count() == 0) {\n'
     '        std::ofstream f(std::filesystem::path(cacheDir) / "utage_prewarm.txt", std::ios::trunc);\n'
     '        f << total << \' \' << stamp << \'\\n\';\n'
     '    }\n'
     '    RT_LOGF(RT_TAG_GX, "boot: pipelines built in %.1f s\\n",\n'
     '            std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count());\n'
     '}\n\n'
     'extern "C" void GX__CopyDisp_8016fc38(uint32_t da, uint32_t c) {\n'),
    ('src/hle/gx/gx_copy.cpp', '#include <dolphin/gx/GXAurora.h>\n', '#include <dolphin/gx/GXAurora.h>\n#include <aurora/gfx.h>\n#include "runtime_config.h"\n#include <cstdlib>\n#include <filesystem>\n#include <fstream>\n#include <thread>\n'),
    # Game speed on a slow phone. Utage is not stepped once per frame like Basara (whose main-loop
    # frameskip, above in the same file, has no Utage address): MT Framework's sMain times each frame
    # itself and the game moves by its mDeltaTime. See the comment in the code.
    ('src/hle/basara_frameskip.cpp', '#include <cstdlib>\n', '#include <cmath>\n#include <cstdlib>\n#include <cstring>\n#include <thread>\n'),
    ('src/hle/basara_frameskip.cpp',
     '#if 0  // u_remap: no Utage address\nPPC_NATIVE_OVERRIDE_VOID(802BE4F4,',
     '// Utage (MT Framework): sMain (pointer at 0x808F3FD8) times each frame itself (0x80716A60). With\n'
     '// mFrameWait (+0x40) set it waits out a whole 1/mFps and moves the game by exactly one step\n'
     '// (mDeltaTime +0x68 = 1); without it mDeltaTime is the real time since the last frame in 1/mFps\n'
     '// steps, capped at mDeltaTimeLimite (+0x70), and the game moves by that much. The game\'s fps manager\n'
     '// (requests 0x800EA524/0x800EA604, applied every frame by 0x800EA558/0x800EA638) runs cutscenes at\n'
     '// 30 fps with the frame wait, and battles at 60 fps without it but capped at 2 steps, so a phone\n'
     '// drawing 20 fps played both at two-thirds speed.\n'
     '// Frameskip Auto (1): the frame wait is never set and the cap at 60 fps is 4 steps, so the game\n'
     '// keeps real-time speed down to 15 fps (at 30 fps the game\'s own cap, 16 steps, stays). 30 FPS Lock\n'
     '// (2): the same, and a 60 fps scene draws at most 30 frames a second (mMaxFps), 2 steps each.\n'
     '// Off (0) is the game\'s own behaviour.\n'
     'namespace {\n'
     'constexpr uint32_t kUtageMainPtr = 0x808F3FD8u;\n'
     'int g_utageMode = -1;     // the mode last applied: the player\'s, or 30 FPS Lock while warm\n'
     'bool g_utageThermalLock = false;\n'
     '// Game Speed in percent (Settings > Performance, UtageSetGameSpeed), and as last applied.\n'
     'std::atomic<int> g_utageSpeedPercent{100};\n'
     'bool g_utageSpeedFromEnv = false;\n'
     'float g_utageSpeedApplied = 1.0f;\n'
     'Clock::time_point g_utageThermalSince{};\n'
     'uint32_t g_utageThermalFrames = 0;\n'
     'bool g_utageFpsSeen = false;\n'
     'float g_utageFps = 60.0f;  // the game\'s last fps request\n'
     'bool g_utageWaitSeen = false;\n'
     'uint8_t g_utageWait = 0;   // and frame wait request\n'
     'double g_utageGameSeconds = 0.0;\n'
     'uint32_t g_utageFrames = 0;\n'
     'Clock::time_point g_utageStatsStart{};\n'
     '\n'
     'float ReadF32(uint32_t addr) {\n'
     '    const uint32_t bits = Memory::Read32(addr);\n'
     '    float value;\n'
     '    std::memcpy(&value, &bits, sizeof(value));\n'
     '    return value;\n'
     '}\n'
     '\n'
     'void WriteF32(uint32_t addr, float value) {\n'
     '    uint32_t bits;\n'
     '    std::memcpy(&bits, &value, sizeof(bits));\n'
     '    Memory::Write32(addr, bits);\n'
     '}\n'
     '\n'
     '// sMain\'s deferred requests, as its own setters write them (frame wait 0x807168F0, fps 0x8071691C,\n'
     '// max fps 0x80716944): its next timing pass applies them.\n'
     'void UtageRequestWait(uint32_t main) {\n'
     '    Memory::Write8(main + 0x82u, 1);\n'
     '    Memory::Write8(main + 0x8Cu, (g_utageMode >= 0 ? g_utageMode : Mode()) != 0 ? 0 : g_utageWait);\n'
     '}\n'
     '\n'
     '// sMain::setFrameWait (0x8071696C): at once, restarting its frame clock.\n'
     'void UtageSetWaitNow(uint32_t main, uint8_t wait) {\n'
     '    Memory::Write8(main + 0x40u, wait);\n'
     '    Memory::Write32(main + 0x54u, Memory::Read32(main + 0x4Cu));\n'
     '    Memory::Write32(main + 0x50u, Memory::Read32(main + 0x48u));\n'
     '    Memory::Write32(main + 0x5Cu, 0);\n'
     '    Memory::Write32(main + 0x58u, 0);\n'
     '    WriteF32(main + 0x68u, 1.0f);\n'
     '    WriteF32(main + 0x78u, 0.0f);\n'
     '}\n'
     '\n'
     '// Game Speed: a 60 fps scene asks for 60 x speed. sMain moves the game by real time x its fps each\n'
     '// frame, so the game runs that much faster while drawing keeps the display\'s pace (30 with 30\n'
     '// FPS Lock, through mMaxFps). Cutscenes (30 fps with the frame wait, voices timed to it) keep\n'
     '// their speed. The step cap grows with it, up to 6 steps a frame.\n'
     'void UtageApplyFps(uint32_t main, int mode) {\n'
     '    const bool cutscene = g_utageFps == 30.0f;\n'
     '    const float speed = cutscene ? 1.0f : g_utageSpeedApplied;\n'
     '    const float fps = cutscene ? 29.97f : g_utageFps * speed;\n'
     '    Memory::Write8(main + 0x80u, 1);\n'
     '    WriteF32(main + 0x84u, fps);\n'
     '    Memory::Write8(main + 0x81u, 1);\n'
     '    WriteF32(main + 0x88u, mode == 2 && !cutscene ? std::min(fps, 30.0f) : fps);\n'
     '    WriteF32(main + 0x70u, cutscene ? 16.0f : std::min((mode != 0 ? 4.0f : 2.0f) * speed, 6.0f));  // mDeltaTimeLimite\n'
     '    WriteF32(main + 0x6Cu, cutscene ? 10000.0f : 100.0f);                // mDeltaTimeBorder\n'
     '}\n'
     '\n'
     '// Game time per real second (1.00x is full speed), logged every 10 s.\n'
     'void UtageSpeedStats(uint32_t main) {\n'
     '    const Clock::time_point now = Clock::now();\n'
     '    if (g_utageStatsStart == Clock::time_point{}) {\n'
     '        g_utageStatsStart = now;\n'
     '        return;\n'
     '    }\n'
     '    const float fps = ReadF32(main + 0x38u);\n'
     '    // The last frame\'s step, in the scene\'s own time (a sped-up scene asks for fps x speed).\n'
     '    const float sceneFps = g_utageFps == 30.0f ? fps : fps / g_utageSpeedApplied;\n'
     '    if (sceneFps > 0.0f) g_utageGameSeconds += ReadF32(main + 0x68u) / sceneFps;\n'
     '    ++g_utageFrames;\n'
     '    const double seconds = std::chrono::duration<double>(now - g_utageStatsStart).count();\n'
     '    if (seconds < 10.0) return;\n'
     '    RT_LOGF(RT_TAG_VI, "utage speed: %.2fx, %.1f fps, scene %.0f fps%s, frameskip %s%s, game speed %d%%\\n",\n'
     '            g_utageGameSeconds / seconds, g_utageFrames / seconds, fps,\n'
     '            Memory::Read8(main + 0x40u) != 0 ? " frame wait" : "", ModeName(Mode()),\n'
     '            g_utageThermalLock ? " (30 fps: warm)" : "", static_cast<int>(g_utageSpeedApplied * 100.0f + 0.5f));\n'
     '    g_utageGameSeconds = 0.0;\n'
     '    g_utageFrames = 0;\n'
     '    g_utageStatsStart = now;\n'
     '}\n'
     '} // namespace\n'
     '\n'
     '// The fps manager\'s apply (0x800EA558), every frame before sMain\'s timing pass.\n'
     'void UtageRefreshViews();  // the camera distance, below\n'
     '\n'
     '// GameActivity.nativeSetGameSpeed: Settings > Performance > Game Speed, in percent (100-200).\n'
     'extern "C" void UtageSetGameSpeed(int percent) {\n'
     '    if (!g_utageSpeedFromEnv) g_utageSpeedPercent.store(std::clamp(percent, 100, 200), std::memory_order_relaxed);\n'
     '}\n'
     '\n'
     '// Thermal Control: while the phone is warm (Thermal::Warm, ten seconds ahead) the player\'s mode\n'
     '// becomes 30 FPS Lock, held kThermalHoldSeconds past the last warm reading so it does not flap.\n'
     '// The game keeps full speed (2 steps a frame), the CPU and GPU do half the frames.\n'
     'int UtageThermalMode(int mode) {\n'
     '    if (++g_utageThermalFrames % kThermalCheckFrames == 0) {\n'
     '        const Clock::time_point now = Clock::now();\n'
     '        const bool warm = Thermal::Warm();\n'
     '        if (warm && !g_utageThermalLock) {\n'
     '            g_utageThermalLock = true;\n'
     '            g_utageThermalSince = now;\n'
     '            RT_LOGF(RT_TAG_VI, "thermal: warm, drawing at 30 fps (headroom %.2f)\\n", Thermal::Headroom());\n'
     '        } else if (warm) {\n'
     '            g_utageThermalSince = now;\n'
     '        } else if (g_utageThermalLock &&\n'
     '                   now - g_utageThermalSince > std::chrono::duration<double>(kThermalHoldSeconds)) {\n'
     '            g_utageThermalLock = false;\n'
     '            RT_LOGF(RT_TAG_VI, "thermal: cooled down, back to the player\'s frame rate (headroom %.2f)\\n",\n'
     '                    Thermal::Headroom());\n'
     '        }\n'
     '    }\n'
     '    return g_utageThermalLock ? 2 : mode;\n'
     '}\n'
     '\n'
     'extern "C" void UtageFpsApply_HLE(CpuContext* ctx) {\n'
     '    UtageRefreshViews();\n'
     '    const uint32_t main = Memory::Read32(kUtageMainPtr);\n'
     '    if (main == 0) return;\n'
     '    const uint32_t manager = static_cast<uint32_t>(ctx->gpr[3]);\n'
     '    const int mode = UtageThermalMode(Mode());\n'
     '    bool apply = false;\n'
     '    if (Memory::Read8(manager + 0x38u) == 1) {\n'
     '        g_utageFps = ReadF32(manager + 0x3Cu);\n'
     '        g_utageFpsSeen = true;\n'
     '        Memory::Write8(manager + 0x38u, 0);\n'
     '        apply = true;\n'
     '    }\n'
     '    if (mode != g_utageMode) {  // first frame, or changed in the in-game settings\n'
     '        g_utageMode = mode;\n'
     '        RT_LOGF(RT_TAG_VI, "utage speed: frameskip %s\\n", ModeName(mode));\n'
     '        apply = apply || g_utageFpsSeen;\n'
     '        if (g_utageWaitSeen) UtageRequestWait(main);\n'
     '    }\n'
     '    static const bool s_speedEnv = [] {\n'
     '        const char* env = std::getenv("UTAGE_GAME_SPEED");\n'
     '        if (env == nullptr) return false;\n'
     '        g_utageSpeedPercent.store(std::clamp(std::atoi(env), 100, 200), std::memory_order_relaxed);\n'
     '        g_utageSpeedFromEnv = true;\n'
     '        return true;\n'
     '    }();\n'
     '    (void)s_speedEnv;\n'
     '    const float speed = static_cast<float>(g_utageSpeedPercent.load(std::memory_order_relaxed)) / 100.0f;\n'
     '    if (speed != g_utageSpeedApplied) {\n'
     '        g_utageSpeedApplied = speed;\n'
     '        RT_LOGF(RT_TAG_VI, "utage speed: game speed %d%%\\n", static_cast<int>(speed * 100.0f + 0.5f));\n'
     '        apply = apply || g_utageFpsSeen;\n'
     '    }\n'
     '    if (apply) UtageApplyFps(main, mode);\n'
     '    // A frame wait set some other way (MT\'s system properties at boot, the movie player\'s\n'
     '    // setFrameWait): kept as the game\'s choice for Off, cleared for the other modes.\n'
     '    if (mode != 0 && Memory::Read8(main + 0x40u) != 0 && Memory::Read8(main + 0x82u) == 0) {\n'
     '        g_utageWait = 1;\n'
     '        g_utageWaitSeen = true;\n'
     '        UtageSetWaitNow(main, 0);\n'
     '        RT_LOGF(RT_TAG_VI, "utage speed: frame wait cleared (scene %.0f fps)\\n", ReadF32(main + 0x38u));\n'
     '    }\n'
     '    UtageSpeedStats(main);\n'
     '    // UTAGE_SIM_FRAME_MS: a slow phone on a PC, this much longer every frame (testing the above).\n'
     '    static const int simMs = [] {\n'
     '        const char* env = std::getenv("UTAGE_SIM_FRAME_MS");\n'
     '        return env != nullptr ? std::clamp(std::atoi(env), 0, 200) : 0;\n'
     '    }();\n'
     '    if (simMs > 0) std::this_thread::sleep_for(std::chrono::milliseconds(simMs));\n'
     '}\n'
     '\n'
     '// sMain::requestFrameWait (0x807168F0): the fps manager\'s frame wait apply and the movie player\'s\n'
     '// restore go through it.\n'
     'extern "C" void UtageMainRequestFrameWait_HLE(CpuContext* ctx) {\n'
     '    if (static_cast<uint8_t>(ctx->gpr[4]) != g_utageWait || !g_utageWaitSeen) {\n'
     '        RT_LOGF(RT_TAG_VI, "utage speed: the game asks for frame wait %u\\n", static_cast<uint32_t>(ctx->gpr[4] & 0xFF));\n'
     '    }\n'
     '    g_utageWait = static_cast<uint8_t>(ctx->gpr[4]);\n'
     '    g_utageWaitSeen = true;\n'
     '    UtageRequestWait(static_cast<uint32_t>(ctx->gpr[3]));\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(800EA558, UtageFpsApply_HLE, (CpuContext* ctx), (ctx));\n'
     'PPC_NATIVE_OVERRIDE_VOID(807168F0, UtageMainRequestFrameWait_HLE, (CpuContext* ctx), (ctx));\n'
     '\n'
     '// Camera distance (Settings > Display > Camera Distance, Cheats::CameraDistance). MT\'s view update\n'
     '// (calls at 0x80601F68 and 0x80602218; the view is r3 - 0x30: fovY +0xAC, aspect +0xB0, near +0xB4,\n'
     '// far +0xB8) builds its projection with C_MTXPerspective (0x805B4A60), replaced here. The field of\n'
     '// view is widened as if the eye stood k times farther back, tan(fov\'/2) = k * tan(fov/2), and the\n'
     '// eye stays where the game put it (Basara 2: moving it back went into walls). The game culls with\n'
     '// this matrix, so the wider view stays filled. Cutscenes (the game asks for 30 fps) keep their framing.\n'
     '// The view caches its projection (flag 0x80 at +0x70, set once built) and builds it again only when\n'
     '// its lens changes, so a new distance clears that flag on the views seen here (once per change, from\n'
     '// the per-frame fps apply above) and the next frame builds them with it. Battle views use the\n'
     '// frustum form (C_MTXFrustum 0x805B49C0, flag 0x10), the rest the perspective one.\n'
     'namespace {\n'
     'uint32_t g_utageViews[8];\n'
     'int g_utageViewCount = 0;\n'
     'float g_utageViewK = 1.0f;\n'
     '\n'
     '// The battle camera (uBasaraCamera) builds its own projection and hands it to the view, so these\n'
     '// SDK builds only ever see menu views: the distance is applied where the view loads its matrix\n'
     '// into GX instead (UtageWidenProjection, below). The views are still logged and refreshed.\n'
     'bool UtageWidensView(uint32_t, float) { return false; }\n'
     '\n'
     'void UtageRememberView(uint32_t lr, uint32_t matrix) {\n'
     '    if (lr != 0x80601F6Cu && lr != 0x8060221Cu && lr != 0x80601F50u && lr != 0x80602200u) return;\n'
     '    const uint32_t view = matrix - 0x30u;\n'
     '    for (int i = 0; i < g_utageViewCount; ++i) {\n'
     '        if (g_utageViews[i] == view) return;\n'
     '    }\n'
     '    g_utageViews[g_utageViewCount < 8 ? g_utageViewCount++ : 7] = view;\n'
     '}\n'
     '\n'
     'void UtageNoteView(uint32_t lr, const char* form, float a, float b, float n, float f, float k) {\n'
     '    static uint32_t s_seen[24];\n'
     '    static int s_count = 0;\n'
     '    uint32_t bits;\n'
     '    std::memcpy(&bits, &a, sizeof(bits));\n'
     '    const uint32_t key = (lr & 0xFFFFu) ^ (bits >> 8);\n'
     '    for (int i = 0; i < s_count; ++i) {\n'
     '        if (s_seen[i] == key) return;\n'
     '    }\n'
     '    if (s_count == 24) return;\n'
     '    s_seen[s_count++] = key;\n'
     '    RT_LOGF(RT_TAG_VI, "camera: %s from %08X (%.3f, %.3f, near %.2f, far %.0f), scene %.0f fps, distance %.2f%s\\n",\n'
     '            form, lr, a, b, n, f, g_utageFps, k, UtageWidensView(lr, k) ? " widened" : "");\n'
     '}\n'
     '}  // namespace\n'
     '\n'
     '// Once a frame (UtageFpsApply_HLE): a new camera distance rebuilds the views\' projections.\n'
     'void UtageRefreshViews() {\n'
     '    const float k = Cheats::CameraDistance();\n'
     '    if (k == g_utageViewK) return;\n'
     '    g_utageViewK = k;\n'
     '    int cleared = 0;\n'
     '    for (int i = 0; i < g_utageViewCount; ++i) {\n'
     '        uint32_t flags = 0;\n'
     '        if (Memory::TryRead32(g_utageViews[i] + 0x70u, flags) && (flags & 0x80u) != 0 &&\n'
     '            Memory::TryWrite32(g_utageViews[i] + 0x70u, flags & ~0x80u)) {\n'
     '            ++cleared;\n'
     '        }\n'
     '    }\n'
     '    RT_LOGF(RT_TAG_VI, "camera: distance %.2f, %d of %d views rebuild\\n", k, cleared, g_utageViewCount);\n'
     '}\n'
     '\n'
     '// C_MTXFrustum(m, t, b, l, r, n, f) as the SDK computes it; a wider battle view scales t, b, l and r.\n'
     'extern "C" void UtageMTXFrustum_HLE(CpuContext* ctx) {\n'
     '    const uint32_t m = static_cast<uint32_t>(ctx->gpr[3]);\n'
     '    float t = static_cast<float>(ctx->fpr[1].d), b = static_cast<float>(ctx->fpr[2].d);\n'
     '    float l = static_cast<float>(ctx->fpr[3].d), r = static_cast<float>(ctx->fpr[4].d);\n'
     '    const float n = static_cast<float>(ctx->fpr[5].d), f = static_cast<float>(ctx->fpr[6].d);\n'
     '    const float k = Cheats::CameraDistance();\n'
     '    UtageRememberView(ctx->lr, m);\n'
     '    UtageNoteView(ctx->lr, "frustum", r - l, t - b, n, f, k);\n'
     '    if (UtageWidensView(ctx->lr, k)) {\n'
     '        const float s = std::min(k, 2.0f);\n'
     '        t *= s;\n'
     '        b *= s;\n'
     '        l *= s;\n'
     '        r *= s;\n'
     '    }\n'
     '    const float two_n = 2.0f * n;\n'
     '    const float w = 1.0f / (r - l), h = 1.0f / (t - b), depth = 1.0f / (f - n);\n'
     '    const float out[16] = {two_n * w, 0.0f, w * (r + l), 0.0f, 0.0f, two_n * h, h * (t + b), 0.0f,\n'
     '                           0.0f, 0.0f, -n * depth, depth * -(f * n), 0.0f, 0.0f, -1.0f, 0.0f};\n'
     '    for (int i = 0; i < 16; ++i) {\n'
     '        uint32_t bits;\n'
     '        std::memcpy(&bits, &out[i], sizeof(bits));\n'
     '        Memory::Write32(m + 4u * static_cast<uint32_t>(i), bits);\n'
     '    }\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805B49C0, UtageMTXFrustum_HLE, (CpuContext* ctx), (ctx));\n'
     '\n'
     'extern "C" void UtageMTXPerspective_HLE(CpuContext* ctx) {\n'
     '    const uint32_t m = static_cast<uint32_t>(ctx->gpr[3]);\n'
     '    const float fov = static_cast<float>(ctx->fpr[1].d);\n'
     '    const float aspect = static_cast<float>(ctx->fpr[2].d);\n'
     '    const float n = static_cast<float>(ctx->fpr[3].d);\n'
     '    const float f = static_cast<float>(ctx->fpr[4].d);\n'
     '    constexpr float kDegToRad = 0.01745329238f;  // the SDK\'s constant (SDA2 0x808FE2AC)\n'
     '    float fovY = fov;\n'
     '    const float k = Cheats::CameraDistance();\n'
     '    UtageRememberView(ctx->lr, m);\n'
     '    UtageNoteView(ctx->lr, "perspective", fov, aspect, n, f, k);\n'
     '    if (UtageWidensView(ctx->lr, k) && fov > 1.0f && fov < 150.0f) {\n'
     '        const float wide = 2.0f * std::atan(std::tan(fov * 0.5f * kDegToRad) * k) / kDegToRad;\n'
     '        fovY = std::min(wide, 120.0f);\n'
     '    }\n'
     '    // C_MTXPerspective as the SDK computes it (Mtx44, row-major).\n'
     '    const float cot = 1.0f / static_cast<float>(std::tan(static_cast<double>(kDegToRad * (0.5f * fovY))));\n'
     '    const float depth = 1.0f / (f - n);\n'
     '    const float out[16] = {cot / aspect, 0.0f, 0.0f, 0.0f, 0.0f, cot, 0.0f, 0.0f,\n'
     '                           0.0f, 0.0f, -n * depth, depth * -(f * n), 0.0f, 0.0f, -1.0f, 0.0f};\n'
     '    for (int i = 0; i < 16; ++i) {\n'
     '        uint32_t bits;\n'
     '        std::memcpy(&bits, &out[i], sizeof(bits));\n'
     '        Memory::Write32(m + 4u * static_cast<uint32_t>(i), bits);\n'
     '    }\n'
     '}\n'
     'PPC_NATIVE_OVERRIDE_VOID(805B4A60, UtageMTXPerspective_HLE, (CpuContext* ctx), (ctx));\n'
     '\n'
     '// GXSetProjection (gx_transform.cpp) with a perspective matrix: MT\'s view loads its projection\n'
     '// from 0x80602218 (return address 0x80602234), the battle camera\'s included (aspect 1.905 on PC).\n'
     '// Widened as if the eye stood k times farther back: x and y scale over k. Cutscenes keep theirs.\n'
     '// The game still culls with its own frustum, so things at the new edges can appear late.\n'
     'void UtageWidenProjection(float* m, uint32_t lr) {\n'
     '    const float k = Cheats::CameraDistance();\n'
     '    // Battle only (the player camera exists): menus draw their 3D backgrounds through the same view,\n'
     '    // and a wider one showed black bands above and below them.\n'
     '    // Off: the battle camera\'s own field of view is widened instead (UtageLockOnUpdate), so the\n'
     '    // names and markers the game places from it follow the picture. Kept for reference.\n'
     '    if (true || k <= 1.0f || lr != 0x80602234u || g_utageFps == 30.0f || !g_utageInBattle) return;\n'
     '    const float s = 1.0f / std::min(k, 2.0f);\n'
     '    m[0] *= s;\n'
     '    m[1] *= s;\n'
     '    m[2] *= s;\n'
     '    m[4] *= s;\n'
     '    m[5] *= s;\n'
     '    m[6] *= s;\n'
     '    static float s_logged = 0.0f;\n'
     '    if (s_logged != k) {\n'
     '        s_logged = k;\n'
     '        RT_LOGF(RT_TAG_VI, "camera: battle view widened, distance %.2f (aspect %.3f)\\n", k,\n'
     '                m[0] != 0.0f ? m[5] / m[0] : 0.0f);\n'
     '    }\n'
     '}\n'
     '\n'
     '#if 0  // u_remap: no Utage address\nPPC_NATIVE_OVERRIDE_VOID(802BE4F4,'),
    # A texture copy shorter than its destination texture writes part of a texture the game assembles
    # in RAM: MT's pre-battle bloom builds one 160x112 texture from two EFB copies (0,448 160x80 at
    # 0x80FDE1E0 and 160,452 160x36 at row 76 of it) and samples it from RAM. EFB copies stay GPU-only
    # here, so that texture decoded stale RAM, the bloom saturated and the cutscene came out yellow/white.
    # Console copies always land in RAM; do that for these copies (Dolphin: partial texture updates).
    ('src/hle/gx/gx_copy.cpp',
     '    const uint32_t copiedHeight = std::max<uint32_t>(rawSrcHeight >> (g_texCopyState.dstMipmap ? 1 : 0), 1);\n',
     '    const uint32_t copiedHeight = std::max<uint32_t>(rawSrcHeight >> (g_texCopyState.dstMipmap ? 1 : 0), 1);\n'
     '    static const bool partialReadback = std::getenv("BASARA_PARTIAL_COPY_READBACK") != nullptr;\n'
     '    if (partialReadback && copiedHeight < g_texCopyState.dstHeight && copiedWidth >= g_texCopyState.dstWidth &&\n'
     '        aurora_flush_efb_copy_to_ram(GuestToHostPtr(da))) {\n'
     '        GxNotifyGuestRamDmaWrite(da, GXGetTexBufferSize(g_texCopyState.dstWidth, copiedHeight, g_texCopyState.dstFormat, GX_FALSE, 0));\n'
     '    }\n'),
    # Diagnostic: a file generated/b/copydump.req (holding an output prefix) makes the next frame's
    # texture copies read back into guest RAM and written as <prefix>_<n>_<w>x<h>_f<fmt>.raw.
    ('src/hle/gx/gx_copy.cpp',
     '    GXCopyTex(GuestToHostPtr(da), (GXBool)c);\n',
     '    GXCopyTex(GuestToHostPtr(da), (GXBool)c);\n'
     '    {  // Utage diagnostic\n'
     '        static int s_dumpFrame = -1, s_dumpIndex = 0, s_lastCheck = -1;\n'
     '        static std::string s_prefix;\n'
     '        if (s_lastCheck != g_gxFrameCount) {\n'
     '            s_lastCheck = g_gxFrameCount;\n'
     '            if (s_dumpFrame >= 0 && s_dumpFrame != g_gxFrameCount) s_dumpFrame = -1;\n'
     '            if (std::FILE* f = std::fopen("generated/b/copydump.req", "rb")) {\n'
     '                char buf[512] = {};\n'
     '                std::fgets(buf, sizeof(buf) - 1, f);\n'
     '                std::fclose(f);\n'
     '                std::remove("generated/b/copydump.req");\n'
     '                s_prefix = buf;\n'
     '                while (!s_prefix.empty() && (s_prefix.back() == \'\\n\' || s_prefix.back() == \'\\r\' || s_prefix.back() == \' \')) s_prefix.pop_back();\n'
     '                s_dumpFrame = g_gxFrameCount; s_dumpIndex = 0;\n'
     '            }\n'
     '        }\n'
     '        if (s_dumpFrame == g_gxFrameCount && !s_prefix.empty()) {\n'
     '            const bool ok = aurora_flush_efb_copy_to_ram(GuestToHostPtr(da));\n'
     '            const uint32_t bytes = GXGetTexBufferSize(g_texCopyState.dstWidth, g_texCopyState.dstHeight, g_texCopyState.dstFormat, GX_FALSE, 0);\n'
     '            char name[640];\n'
     '            std::snprintf(name, sizeof(name), "%s_%02d_%ux%u_f%u_%08X.raw", s_prefix.c_str(), s_dumpIndex++, g_texCopyState.dstWidth, g_texCopyState.dstHeight, g_texCopyState.dstFormat, da);\n'
     '            if (std::FILE* o = std::fopen(name, "wb")) { std::fwrite(GuestToHostPtr(da, bytes), 1, bytes, o); std::fclose(o); }\n'
     '            RT_LOGF(RT_TAG_GX, "[copydump] %s readback=%d src %u,%u %ux%u clear=%u\\n", name, ok ? 1 : 0, rawSrcLeft, rawSrcTop, rawSrcWidth, rawSrcHeight, c);\n'
     '        }\n'
     '    }\n'),
    ('src/hle/gx/gx_copy.cpp', '#include <dolphin/gx/GXAurora.h>\n', '#include <dolphin/gx/GXAurora.h>\n#include <aurora/aurora.h>\n'),
    # Diagnostic: a file generated/b/memdump.req (written by u-shots "SEC:dump", holding the output
    # path) makes the runtime write MEM1/MEM2 snapshots there.
    ('src/hle/vi.cpp',
     '    std::call_once(once, [] {\n        std::thread([] {\n            const auto start = std::chrono::steady_clock::now();\n',
     '    std::call_once(once, [] {\n'
     '        std::thread([] {  // Utage diagnostic\n'
     '            const std::filesystem::path req = std::filesystem::path("generated") / "b" / "memdump.req";\n'
     '            for (;;) {\n'
     '                std::this_thread::sleep_for(std::chrono::milliseconds(100));\n'
     '                std::error_code ec;\n'
     '                if (!std::filesystem::exists(req, ec)) continue;\n'
     '                std::string out;\n'
     '                { std::ifstream f(req); std::getline(f, out); }\n'
     '                std::filesystem::remove(req, ec);\n'
     '                while (!out.empty() && (out.back() == \'\\r\' || out.back() == \' \')) out.pop_back();\n'
     '                if (out.empty()) continue;\n'
     '                std::ostringstream log;\n'
     '                SystemBridge::WriteGuestMemorySnapshot(log, std::filesystem::path(out));\n'
     '                RT_LOGF(RT_TAG_VI, "[memdump] %s", log.str().c_str());\n'
     '            }\n'
     '        }).detach();\n'
     '        std::thread([] {\n            const auto start = std::chrono::steady_clock::now();\n'),
    ('src/hle/vi.cpp', '#include "system_stats.h"\n', '#include "system_stats.h"\n#include "system_bridge.h"\n#include <filesystem>\n#include <fstream>\n'),
    ('src/hle/vi.cpp',
     '                Fiber::GuestFiberManager::DumpGuestThreads(dump);\n',
     '                Fiber::GuestFiberManager::DumpGuestThreads(dump);\n'
     '                for (uint32_t q = 0; q < 32; ++q) {  // Utage diagnostic: RunQueue[q] head/tail\n'
     '                    uint32_t head = 0, tail = 0;\n'
     '                    ::Memory::TryRead32(0x8097EC30u + q * 8u, head);\n'
     '                    ::Memory::TryRead32(0x8097EC34u + q * 8u, tail);\n'
     '                    if (head || tail) dump << "[fiber] RunQueue[" << q << "] head=0x" << std::hex << head\n'
     '                                           << " tail=0x" << tail << std::dec << "\\n";\n'
     '                }\n'),
    # Diagnostic: one-frame GX trace, armed together with a copydump request ("SEC:copies").
    ('src/hle/gx/gx_copy.cpp', '#include <aurora/aurora.h>\n',
     '#include <aurora/aurora.h>\n#include <cstdarg>\n'
     'static int g_utageTraceFrame = -1;  // Utage diagnostic\n'
     'extern "C" void UtageTrace(const char* fmt, ...) {\n'
     '    if (g_utageTraceFrame != g_gxFrameCount) return;\n'
     '    char buf[256]; va_list ap; va_start(ap, fmt); std::vsnprintf(buf, sizeof(buf), fmt, ap); va_end(ap);\n'
     '    RT_LOGF(RT_TAG_GX, "[trace] %s\\n", buf);\n'
     '}\n'),
    ('src/hle/gx/gx_copy.cpp', '                s_dumpFrame = g_gxFrameCount; s_dumpIndex = 0;\n',
     '                s_dumpFrame = g_gxFrameCount; s_dumpIndex = 0; g_utageTraceFrame = g_gxFrameCount;\n'),
    ('src/hle/gx/gx_copy.cpp', 'extern "C" void GX__CopyDisp_8016fc38(uint32_t da, uint32_t c) {\n',
     'extern "C" void GX__CopyDisp_8016fc38(uint32_t da, uint32_t c) {\n    UtageTrace("copydisp %08X clear %u", da, c);\n'),
    ('src/hle/gx/gx_copy.cpp', '    GXCopyTex(GuestToHostPtr(da), (GXBool)c);\n',
     '    UtageTrace("copytex %08X %ux%u f%u src %u,%u %ux%u clear %u", da, g_texCopyState.dstWidth, g_texCopyState.dstHeight, g_texCopyState.dstFormat, rawSrcLeft, rawSrcTop, rawSrcWidth, rawSrcHeight, c);\n'
     '    GXCopyTex(GuestToHostPtr(da), (GXBool)c);\n'),
    ('src/hle/gx/gx_vertex.cpp', '    UtageQuadDiag(t, nv, "begin");\n',
     '    UtageQuadDiag(t, nv, "begin");\n    UtageTrace("begin p%u vf%u n%u", t, vf, nv);\n'),
    ('src/hle/gx/gx_vertex.cpp', 'void UtageQuadDiag(uint32_t prim, uint32_t nv, const char* path) {  // Utage diagnostic\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\nvoid UtageQuadDiag(uint32_t prim, uint32_t nv, const char* path) {  // Utage diagnostic\n'),
    ('src/hle/gx/gx_dl.cpp', '    UtageDlDiag(0);\n',
     '    UtageDlDiag(0);\n    UtageTrace("calldl %08X+%u", listAddr, nbytes);\n'),
    ('src/hle/gx/gx_dl.cpp', 'void UtageDlDiag(int kind) {  // Utage diagnostic: kind 0 = call, 1 = fallback\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\nvoid UtageDlDiag(int kind) {  // Utage diagnostic: kind 0 = call, 1 = fallback\n'),
    ('src/hle/gx/gx_pixel.cpp', 'static void UtagePixDiag(const char* what, uint32_t a, uint32_t b) {  // Utage diagnostic\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\nstatic void UtagePixDiag(const char* what, uint32_t a, uint32_t b) {  // Utage diagnostic\n'),
    ('src/hle/gx/gx_pixel.cpp', 'extern "C" void GX__SetBlendMode_8017277c(uint32_t t, uint32_t s, uint32_t d, uint32_t op) {\n',
     'extern "C" void GX__SetBlendMode_8017277c(uint32_t t, uint32_t s, uint32_t d, uint32_t op) {\n    UtageTrace("blend t%u s%u d%u op%u", t, s, d, op);\n'),
    ('src/hle/gx/gx_pixel.cpp', 'extern "C" void GX__SetZMode_80172824(uint32_t ce, uint32_t f, uint32_t ue) {\n',
     'extern "C" void GX__SetZMode_80172824(uint32_t ce, uint32_t f, uint32_t ue) {\n    UtageTrace("zmode %u f%u upd%u", ce, f, ue);\n'),
    ('src/hle/gx/gx_pixel.cpp', 'extern "C" void GX__SetAlphaCompare_80172088(uint32_t c0, uint32_t r0, uint32_t op, uint32_t c1, uint32_t r1) {\n',
     'extern "C" void GX__SetAlphaCompare_80172088(uint32_t c0, uint32_t r0, uint32_t op, uint32_t c1, uint32_t r1) {\n    UtageTrace("alphacmp %u %u op%u %u %u", c0, r0, op, c1, r1);\n'),
    ('src/hle/gx/gx_pixel.cpp', '    UtagePixDiag("alphaupdate", en, 0);\n', '    UtagePixDiag("alphaupdate", en, 0);\n    UtageTrace("alphaupdate %u", en);\n'),
    ('src/hle/gx/gx_pixel.cpp', 'extern "C" void GX__SetColorUpdate_801727cc(uint32_t en) {\n',
     'extern "C" void GX__SetColorUpdate_801727cc(uint32_t en) {\n    UtageTrace("colorupdate %u", en);\n'),
    ('src/hle/gx/gx_tev.cpp', 'static void UtageTevDiag(const char* what, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f) {  // Utage diagnostic\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\nstatic void UtageTevDiag(const char* what, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f) {  // Utage diagnostic\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetNumTevStages_801722a8(uint32_t n) {\n',
     'extern "C" void GX__SetNumTevStages_801722a8(uint32_t n) {\n    UtageTrace("numtev %u", n);\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevOrder_8017214c(uint32_t s, uint32_t c, uint32_t m, uint32_t col) {\n',
     'extern "C" void GX__SetTevOrder_8017214c(uint32_t s, uint32_t c, uint32_t m, uint32_t col) {\n    UtageTrace("tevorder s%u coord%u map%u chan%u", s, c, m, col);\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevColorIn_80171ce0(uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {\n',
     'extern "C" void GX__SetTevColorIn_80171ce0(uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {\n    UtageTrace("colorin s%u %u %u %u %u", s, a, b, c, d);\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevAlphaIn_80171d20(uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {\n',
     'extern "C" void GX__SetTevAlphaIn_80171d20(uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {\n    UtageTrace("alphain s%u %u %u %u %u", s, a, b, c, d);\n'),
    ('src/hle/gx/gx_tev.cpp', '    if (op >= 8) UtageTevDiag("colorop", s, op, b, sc, cl, or_);\n',
     '    if (op >= 8) UtageTevDiag("colorop", s, op, b, sc, cl, or_);\n    UtageTrace("colorop s%u op%u b%u sc%u cl%u out%u", s, op, b, sc, cl, or_);\n'),
    ('src/hle/gx/gx_tev.cpp', '    if (op >= 8) UtageTevDiag("alphaop", s, op, b, sc, cl, or_);\n',
     '    if (op >= 8) UtageTevDiag("alphaop", s, op, b, sc, cl, or_);\n    UtageTrace("alphaop s%u op%u b%u sc%u cl%u out%u", s, op, b, sc, cl, or_);\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevColor_80171e10(uint32_t id, uint32_t cp) {\n',
     'extern "C" void GX__SetTevColor_80171e10(uint32_t id, uint32_t cp) {\n    { uint32_t v = 0; Memory::TryRead32(cp, v); UtageTrace("tevcolor %u %08X", id, v); }\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevKColor_80171ed4(uint32_t id, uint32_t cp) {\n',
     'extern "C" void GX__SetTevKColor_80171ed4(uint32_t id, uint32_t cp) {\n    { uint32_t v = 0; Memory::TryRead32(cp, v); UtageTrace("kcolor %u %08X", id, v); }\n'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevKColorSel_80171f30(uint32_t s, uint32_t sel) {',
     'extern "C" void GX__SetTevKColorSel_80171f30(uint32_t s, uint32_t sel) { UtageTrace("kcsel s%u %u", s, sel);'),
    ('src/hle/gx/gx_tev.cpp', 'extern "C" void GX__SetTevKAlphaSel_80171f80(uint32_t s, uint32_t sel) {',
     'extern "C" void GX__SetTevKAlphaSel_80171f80(uint32_t s, uint32_t sel) { UtageTrace("kasel s%u %u", s, sel);'),
    ('src/hle/gx/gx_texture.cpp', 'extern "C" void GX__LoadTexObj_80170f2c(uint32_t oa, uint32_t tid) {\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\n'
     'extern "C" void GX__LoadTexObj_80170f2c(uint32_t oa, uint32_t tid) {\n'
     '    { uint32_t w[6] = {}; for (int i = 0; i < 6; ++i) Memory::TryRead32(oa + i * 4, w[i]); UtageTrace("loadtex map%u obj %08X: %08X %08X %08X %08X %08X %08X", tid, oa, w[0], w[1], w[2], w[3], w[4], w[5]); }\n'),
    ('src/hle/gx/gx_lighting.cpp', 'extern "C" void GX__SetChanCtrl_80170570(uint32_t ch, uint32_t en, uint32_t as, uint32_t ms, uint32_t lm, uint32_t df, uint32_t af) {\n',
     'extern "C" void UtageTrace(const char* fmt, ...);\n'
     'extern "C" void GX__SetChanCtrl_80170570(uint32_t ch, uint32_t en, uint32_t as, uint32_t ms, uint32_t lm, uint32_t df, uint32_t af) {\n'
     '    UtageTrace("chanctrl %u en%u amb%u mat%u lights%X df%u af%u", ch, en, as, ms, lm, df, af);\n'),
    # --- 0.5.8: the display-list path, from Perfetto CPU samples of busy battles on a Poco X6 ---
    # GX_HLE_FIFO_Write32 was 14-16% of the game thread: MT calls each display list with three raw
    # FIFO writes (805F0140, 805F0220), and GX__CallDisplayList_80172f64 runs inline under them.
    # Read BASARA_DL_SOFT once: getenv ran for every display list (35 of 6379 samples).
    ('src/hle/gx/gx_dl.cpp',
     '        if (static bool s_softLogged = false; !s_softLogged && std::getenv("BASARA_DL_SOFT")) {\n',
     '        static const bool s_dlSoft = std::getenv("BASARA_DL_SOFT") != nullptr;  // once: every list runs this\n'
     '        if (static bool s_softLogged = false; !s_softLogged && s_dlSoft) {\n'),
    # The vertex-state snapshot holds raw bytes: VtxAttrFmt and VtxArray have default member
    # initializers, so every snapshot (one or two per display list) first filled 208 + 26 entries
    # with defaults that the memcpy right after overwrote (12% of the FIFO path).
    ('src/hle/gx/gx_dl.cpp', '#include <unordered_map>\n', '#include <type_traits>\n#include <unordered_map>\n'),
    ('src/hle/gx/gx_dl.cpp',
     'struct HleGxVertexStateSnapshot {\n'
     '    GXAttrType vtxDesc[26];\n'
     '    VtxAttrFmt vtxAttrFmt[8][26];\n'
     '    HleGxState::VtxArray vtxArray[26];\n',
     '// Uninitialized storage for memcpy\'d copies (rows are copied in and out whole).\n'
     'template <typename T>\n'
     'struct alignas(T) RawCopyOf {\n'
     '    unsigned char bytes[sizeof(T)];\n'
     '};\n'
     'static_assert(std::is_trivially_copyable_v<VtxAttrFmt> && std::is_trivially_copyable_v<HleGxState::VtxArray>);\n'
     '\n'
     'struct HleGxVertexStateSnapshot {\n'
     '    GXAttrType vtxDesc[26];\n'
     '    RawCopyOf<VtxAttrFmt> vtxAttrFmt[8][26];\n'
     '    RawCopyOf<HleGxState::VtxArray> vtxArray[26];\n'),
    # The layout hash, recomputed after each real VCD/VAT change (MT changes them between most
    # lists): 650 serial FNV steps (17% of the FIFO path) become a packed copy and one XXH3.
    ('src/hle/gx/gx_dl.cpp',
     '    uint64_t hash = 1469598103934665603ull;\n'
     '    auto mix = [&hash](uint32_t value) {\n'
     '        hash ^= static_cast<uint64_t>(value);\n'
     '        hash *= 1099511628211ull;\n'
     '    };\n'
     '    for (int attr = 0; attr < 26; ++attr) {\n'
     '        mix(static_cast<uint32_t>(g_hleGxState.vtxDesc[attr]));\n'
     '    }\n'
     '    for (int fmt = 0; fmt < 8; ++fmt) {\n'
     '        for (int attr = 0; attr < 26; ++attr) {\n'
     '            const auto& f = g_hleGxState.vtxAttrFmt[fmt][attr];\n'
     '            mix(static_cast<uint32_t>(f.cnt));\n'
     '            mix(static_cast<uint32_t>(f.type));\n'
     '            mix(static_cast<uint32_t>(f.frac));\n'
     '        }\n'
     '    }\n'
     '    g_hleGxState.vtxLayoutHash = hash;\n',
     '    // Packed (desc words, then cnt/type/frac bytes per format and attribute) and hashed at once.\n'
     '    uint8_t packed[26 * 4 + 8 * 26 * 3];\n'
     '    size_t n = 0;\n'
     '    for (int attr = 0; attr < 26; ++attr) {\n'
     '        const uint32_t desc = static_cast<uint32_t>(g_hleGxState.vtxDesc[attr]);\n'
     '        std::memcpy(packed + n, &desc, sizeof(desc));\n'
     '        n += sizeof(desc);\n'
     '    }\n'
     '    for (int fmt = 0; fmt < 8; ++fmt) {\n'
     '        for (int attr = 0; attr < 26; ++attr) {\n'
     '            const auto& f = g_hleGxState.vtxAttrFmt[fmt][attr];\n'
     '            packed[n++] = static_cast<uint8_t>(f.cnt);\n'
     '            packed[n++] = static_cast<uint8_t>(f.type);\n'
     '            packed[n++] = f.frac;\n'
     '        }\n'
     '    }\n'
     '    g_hleGxState.vtxLayoutHash = static_cast<uint64_t>(XXH3_64bits(packed, n));\n'),
    # The scan cache's lookup (std::unordered_map: a prime modulo and a node chase, 31% of the FIFO
    # path) gets a direct-mapped front: the same few hundred lists come back every frame. Node
    # pointers survive inserts and rehashes; only the clear below drops them, and clears the front too.
    ('src/hle/gx/gx_dl.cpp',
     '    std::unordered_map<uint64_t, DlScanCacheRecord> entries{};\n',
     '    std::unordered_map<uint64_t, DlScanCacheRecord> entries{};\n'
     '    struct FrontSlot {\n'
     '        uint64_t key = 0;\n'
     '        DlScanCacheRecord* record = nullptr;\n'
     '    };\n'
     '    std::array<FrontSlot, 2048> front{};\n'),
    ('src/hle/gx/gx_dl.cpp',
     'static DlScanCacheProbe ProbeDlScanCache(',
     'static DlScanCacheRecord* DlScanCacheFind(DlScanCacheState& cache, uint64_t key) {\n'
     '    auto& slot = cache.front[(key ^ (key >> 21) ^ (key >> 42)) & (cache.front.size() - 1)];\n'
     '    if (slot.record != nullptr && slot.key == key) {\n'
     '        return slot.record;\n'
     '    }\n'
     '    const auto it = cache.entries.find(key);\n'
     '    if (it == cache.entries.end()) {\n'
     '        return nullptr;\n'
     '    }\n'
     '    slot.key = key;\n'
     '    slot.record = &it->second;\n'
     '    return slot.record;\n'
     '}\n\n'
     'static DlScanCacheProbe ProbeDlScanCache('),
    ('src/hle/gx/gx_dl.cpp',
     '    const auto it = s_cache.entries.find(key);\n'
     '    if (it != s_cache.entries.end()) {\n'
     '        auto& record = it->second;\n',
     '    if (DlScanCacheRecord* found = DlScanCacheFind(s_cache, key); found != nullptr) {\n'
     '        auto& record = *found;\n'),
    ('src/hle/gx/gx_dl.cpp',
     '        s_cache.entries.clear();\n',
     '        s_cache.entries.clear();\n'
     '        s_cache.front.fill({});\n'),
    # --- Lock target (basara_frameskip.cpp, UtageLockOnUpdate) ---
    ('src/hle/basara_frameskip.cpp', 'void UtageWidenProjection(float* m, uint32_t lr) {\n',
     LOCK_CPP + '\nvoid UtageWidenProjection(float* m, uint32_t lr) {\n'),
    ('src/hle/basara_frameskip.cpp', 'void UtageRefreshViews();  // the camera distance, below\n',
     'void UtageRefreshViews();  // the camera distance, below\nvoid UtageLockOnUpdate();  // lock target, below\n'),
    ('src/hle/basara_frameskip.cpp', '    UtageRefreshViews();\n    const uint32_t main = Memory::Read32(kUtageMainPtr);\n',
     '    UtageRefreshViews();\n    UtageLockOnUpdate();\n    const uint32_t main = Memory::Read32(kUtageMainPtr);\n'),
    ('src/hle/basara_frameskip.cpp', '#include <cmath>\n', '#include <cmath>\n#include <string>\n#include <unordered_map>\n'),
    ('src/virtual_remote.cpp', '#include "virtual_remote.h"\n',
     '#include "virtual_remote.h"\n\nfloat UtageLockOnStickX();  // lock target (hle/basara_frameskip.cpp)\n'
     'void UtageLockOnPlayerStick(float x);\n'),
    ('src/virtual_remote.cpp', '        merge(AutomationIntent());\n',
     '        merge(AutomationIntent());\n'
     '        // Lock target: turns the camera toward the locked enemy while the player\'s right stick rests.\n'
     '        UtageLockOnPlayerStick(intent.rStick[0]);  // a flick switches the locked enemy\n'
     '        if (intent.rStick[0] == 0.0f) intent.rStick[0] = UtageLockOnStickX();\n'),
    # Leaving the screen saves the driver's pipeline cache from here: the paused game thread never
    # sees SDL's background event (aurora window.cpp saves on it), so a swipe out of Recents during
    # the background shader build lost every shader built since the last save (0.6.0).
    ('src/android/android_bridge.cpp',
     '        HostSuspend::RequestPause(true);\n',
     '        HostSuspend::RequestPause(true);\n'
     '        // The shaders built so far go to disk now, off this (UI) thread: the paused game thread\n'
     '        // never sees SDL\'s background event, which aurora saves them on, and a swipe out of\n'
     '        // Recents then ends the process without one.\n'
     '        std::thread([] { aurora_save_pipeline_caches(); }).detach();\n'),
    ('src/android/android_bridge.cpp',
     '// GameActivity.nativeSetCameraDistance: Settings > Display > Camera Distance (cheats.cpp).\n',
     'bool UtageLockOnToggle();  // hle/basara_frameskip.cpp\n'
     'void UtageSetGameSpeed(int percent);  // hle/basara_frameskip.cpp\n\n'
     '// GameActivity.nativeSetGameSpeed: Settings > Performance > Game Speed (100-200%).\n'
     'JNIEXPORT void JNICALL Java_io_github_dezer04_sb3utage_GameActivity_nativeSetGameSpeed(JNIEnv*, jclass, jint percent)\n'
     '{\n'
     '    UtageSetGameSpeed(static_cast<int>(percent));\n'
     '}\n\n'
     '// GameActivity.nativeToggleLockOn: R3 and the touch LOCK button. Returns whether it is now on.\n'
     'JNIEXPORT jboolean JNICALL Java_io_github_dezer04_sb3utage_GameActivity_nativeToggleLockOn(JNIEnv*, jclass)\n'
     '{\n'
     '    return UtageLockOnToggle() ? JNI_TRUE : JNI_FALSE;\n'
     '}\n\n'
     '// GameActivity.nativeSetCameraDistance: Settings > Display > Camera Distance (cheats.cpp).\n'),
    # The overlay's CPU and game ms from the game thread's own CPU time (1.0.0): wall time minus its
    # idle and the producer's frame-worker waits read 0% with GX Thread on, where the GX thread waits.
    ('src/settings_overlay.cpp', '#include "system_stats.h"\n', '#include "system_stats.h"\n#include "guest_profiler.h"\n'),
    ('src/settings_overlay.cpp',
     '    static uint64_t s_lastIdle = 0, s_lastGx = 0, s_lastDraws = 0;\n',
     '    static uint64_t s_lastIdle = 0, s_lastGx = 0, s_lastDraws = 0;\n'
     '    static double s_lastCpuMs = 0.0;\n'),
    ('src/settings_overlay.cpp',
     '        s_stats.loadPercent = static_cast<float>(busyNs * 100.0 / wallNs);\n'
     '        s_stats.busyMs = n ? static_cast<float>(busyNs / 1e6 / n) : 0.0f;\n',
     '        // The game thread\'s own CPU time (this runs on it: settings_overlay::Draw from GXCopyDisp or\n'
     '        // the VI present). Wall time minus its idle and the producer\'s frame-worker waits read 0%\n'
     '        // with GX Thread on, where the GX thread is the one waiting (a GPU-bound menu showed 0%).\n'
     '        double cpuUser = 0.0, cpuKernel = 0.0;\n'
     '        GuestProfiler::ThreadCpuMs(&cpuUser, &cpuKernel);\n'
     '        const double cpuMs = cpuUser + cpuKernel - s_lastCpuMs;\n'
     '        const double usedNs = cpuMs > 0.0 ? cpuMs * 1e6 : busyNs;  // no thread clock: the old estimate\n'
     '        s_stats.loadPercent = static_cast<float>(usedNs * 100.0 / wallNs);\n'
     '        s_stats.busyMs = n ? static_cast<float>(usedNs / 1e6 / n) : 0.0f;\n'),
    ('src/settings_overlay.cpp',
     '    s_lastWorker = worker;\n'
     '    return s_stats;\n',
     '    s_lastWorker = worker;\n'
     '    {\n'
     '        double cpuUser = 0.0, cpuKernel = 0.0;\n'
     '        GuestProfiler::ThreadCpuMs(&cpuUser, &cpuKernel);\n'
     '        s_lastCpuMs = cpuUser + cpuKernel;\n'
     '    }\n'
     '    return s_stats;\n'),
    # Game rumble (1.0.0): the Wii Remote motor drives the gamepad on that channel and, through the app,
    # the phone's vibrator; Settings > Controls > Rumble.
    ('src/hle/input/wpad.cpp', '#include <cstdint>\n', '#include "runtime_log.h"\n#include "virtual_remote.h"\n\n#include <atomic>\n#include <cstdint>\n#include <dolphin/pad.h>\n'),
    ('src/hle/input/wpad.cpp',
     'extern "C" void WPADControlMotor_HLE(uint32_t chan, uint32_t command)\n'
     '{\n'
     '    (void)chan;\n'
     '    (void)command;\n'
     '}\n',
     '// Game rumble (Settings > Controls > Rumble: 0 off, 1 the gamepad, 2 the gamepad and the phone). A\n'
     '// motor that turns on or off goes to the gamepad playing that channel (aurora PADControlMotor, SDL\n'
     '// rumble); the bits let the app pulse the phone\'s vibrator while it is on (nativeRumbleBits).\n'
     'namespace {\n'
     'std::atomic<uint32_t> g_wpadMotorBits{0};\n'
     'std::atomic<int> g_wpadRumbleMode{1};\n'
     '}  // namespace\n'
     '\n'
     'extern "C" uint32_t WPAD_HLE_MotorBits() { return g_wpadMotorBits.load(std::memory_order_relaxed); }\n'
     '\n'
     'extern "C" void WPAD_HLE_StopMotors() {\n'
     '    const uint32_t bits = g_wpadMotorBits.exchange(0, std::memory_order_relaxed);\n'
     '    for (uint32_t chan = 0; chan < 4; ++chan) {\n'
     '        const int port = VirtualRemote::PadPortFor(chan);\n'
     '        if ((bits & (1u << chan)) != 0 && port >= 0) PADControlMotor(static_cast<uint32_t>(port), PAD_MOTOR_STOP);\n'
     '    }\n'
     '}\n'
     '\n'
     'extern "C" void WPAD_HLE_SetRumbleMode(int mode) {\n'
     '    g_wpadRumbleMode.store(mode, std::memory_order_relaxed);\n'
     '    if (mode == 0) WPAD_HLE_StopMotors();\n'
     '}\n'
     '\n'
     'extern "C" void WPADControlMotor_HLE(uint32_t chan, uint32_t command)\n'
     '{\n'
     '    if (chan >= 4) return;\n'
     '    static bool s_logged = false;\n'
     '    if (!s_logged && command != 0) {\n'
     '        s_logged = true;\n'
     '        RT_LOGF(RT_TAG_HLE, "rumble: the game drives the Wii Remote motor (channel %u)\\n", chan);\n'
     '    }\n'
     '    const bool on = command != 0 && g_wpadRumbleMode.load(std::memory_order_relaxed) != 0;\n'
     '    const uint32_t bit = 1u << chan;\n'
     '    const uint32_t before = on ? g_wpadMotorBits.fetch_or(bit, std::memory_order_relaxed)\n'
     '                               : g_wpadMotorBits.fetch_and(~bit, std::memory_order_relaxed);\n'
     '    if (((before & bit) != 0) == on) return;  // unchanged: the game repeats its command every frame\n'
     '    // The gamepad playing that channel (Two Players moves the first one to player 2).\n'
     '    const int port = VirtualRemote::PadPortFor(chan);\n'
     '    if (port >= 0) PADControlMotor(static_cast<uint32_t>(port), on ? PAD_MOTOR_RUMBLE : PAD_MOTOR_STOP);\n'
     '}\n'),
    ('src/android/android_bridge.cpp',
     'void UtageSetGameSpeed(int percent);  // hle/basara_frameskip.cpp\n',
     'void UtageSetGameSpeed(int percent);  // hle/basara_frameskip.cpp\n'
     'uint32_t WPAD_HLE_MotorBits();         // hle/input/wpad.cpp\n'
     'void WPAD_HLE_StopMotors();\n'
     'void WPAD_HLE_SetRumbleMode(int mode);\n\n'
     '// GameActivity.nativeSetRumble: Settings > Controls > Rumble (0 off, 1 gamepad, 2 gamepad and phone).\n'
     'JNIEXPORT void JNICALL Java_io_github_dezer04_sb3utage_GameActivity_nativeSetRumble(JNIEnv*, jclass, jint mode)\n'
     '{\n'
     '    WPAD_HLE_SetRumbleMode(static_cast<int>(mode));\n'
     '}\n\n'
     '// GameActivity.nativeRumbleBits: the Wii Remote motors on now (bit 0 = channel 0), for the phone\'s vibrator.\n'
     'JNIEXPORT jint JNICALL Java_io_github_dezer04_sb3utage_GameActivity_nativeRumbleBits(JNIEnv*, jclass)\n'
     '{\n'
     '    return static_cast<jint>(WPAD_HLE_MotorBits());\n'
     '}\n'),
    ('src/android/android_bridge.cpp',
     '        HostSuspend::RequestPause(true);\n'
     '        // The shaders built so far',
     '        HostSuspend::RequestPause(true);\n'
     '        WPAD_HLE_StopMotors();  // a motor left on would buzz until the game came back\n'
     '        // The shaders built so far'),
    ('src/android/android_bridge.cpp',
     '        HostSuspend::RequestPause(false);\n',
     '        HostSuspend::RequestPause(false);\n'
     '        WPAD_HLE_StopMotors();\n'),
    # Cheats for Utage (1.0.0): data writes from the community's S3HJ08 Gecko codes, +0x2000 on this
    # runtime's heap; the Basara 2 call hooks (other functions at their addresses here) go.
    ('include/abi_bridge.h',
     '    // Basara cheats (cheats.cpp). The target is a constant at every static call site, so these fold\n'
     '    // away everywhere else; indirect calls pay four compares.\n'
     '    // The shop\'s purchase (0x80048B20) stores money - price, then refreshes the shop through 0x80158650.\n'
     '    if (target == 0x80158650u) {\n'
     '        BasaraCheats_BeforeShopRefresh(ctx);\n'
     '    }\n'
     '    // cPl::hpSub(this, amount): every HP loss of a player character.\n'
     '    if (target == 0x80247BE0u) {\n'
     '        BasaraCheats_BeforeHpSub(ctx);\n'
     '    }\n'
     '    // The damage virtual (vtable slot 0x70) every character class shares, always reached via bctrl.\n'
     '    if (target == 0x8012C850u) {\n'
     '        BasaraCheats_BeforeDamage(ctx);\n'
     '    }\n'
     '    // cPl::plGaugeCalc: a character\'s Basara gauge update, once a frame.\n'
     '    if (target == 0x8022D4D8u) {\n'
     '        BasaraCheats_BeforeGaugeCalc(ctx);\n'
     '    }\n'
     '    // The cameras\' MTXPerspective wrapper: camera distance widens the main camera\'s field of view.\n'
     '    if (target == 0x802BF3F4u) {\n'
     '        BasaraCheats_BeforePerspective(ctx);\n'
     '    }\n'
     ,
     '    // Utage: the Basara 2 cheat hooks lived here, at Basara 2 addresses that are other functions in this\n'
     '    // game. Utage\'s cheats write data instead (cheats.cpp Apply, from its fps manager hook).\n'
    ),
    ('src/cheats.cpp',
     'void Apply() {\n'
     '    if (!Available()) {\n'
     '        return;\n'
     '    }\n'
     '    if (InfiniteMoney()) {\n'
     '        // Logged each time the game had changed it (boot, loading a save, spending), the first few times.\n'
     '        static int s_logged = 0;\n'
     '        uint32_t before = 0;\n'
     '        Memory::TryRead32(kMoneyAddr, before);\n'
     '        const uint32_t amount = g_amount.load(std::memory_order_relaxed);\n'
     '        if (Memory::TryWrite32(kMoneyAddr, amount) && before != amount && s_logged < 8) {\n'
     '            ++s_logged;\n'
     '            RT_LOGF(RT_TAG_OS, "cheats: infinite money holds %u (was %u)\\n", amount, before);\n'
     '        }\n'
     '    } else if (g_oncePending.exchange(false)) {\n'
     '        const uint32_t amount = g_amount.load(std::memory_order_relaxed);\n'
     '        if (Memory::TryWrite32(kMoneyAddr, amount)) {\n'
     '            RT_LOGF(RT_TAG_OS, "cheats: money set to %u once\\n", amount);\n'
     '        }\n'
     '    }\n'
     '    // Once a second: a save loaded later replaces what was opened before it.\n'
     '    static uint32_t s_frame = 0;\n'
     '    if (g_unlockAll.load(std::memory_order_relaxed) && ++s_frame % 60u == 1u) {\n'
     '        static int s_logged = 0;\n'
     '        const uint32_t opened = UnlockAllNow();\n'
     '        if (opened != 0 && s_logged < 8) {\n'
     '            ++s_logged;\n'
     '            RT_LOGF(RT_TAG_OS, "cheats: unlock all opened %u entries\\n", opened);\n'
     '        }\n'
     '    }\n'
     '}\n'
     '\n'
     ,
     '// Sengoku Basara 3 Utage (S3HJ08), from the community\'s Gecko code lists (A9VG thread 2071373, ameblo\n'
     '// tales-of-bleach). Their addresses are a real Wii\'s; this runtime\'s MEM1 heap holds the same objects\n'
     '// 0x2000 higher (battle memory dumps), so each base is tried at +0x2000, then as listed, and used only\n'
     '// when what it holds makes sense.\n'
     '// - P1\'s battle status (pointer at 0x810468B0, P2\'s at +4): HP at +0x204 of max +0x208, the BASARA\n'
     '//   gauge at +0x220 of max +0x224 (func_8014A4F4 adds to it and clamps at the max).\n'
     '// - The save\'s game data: money at 0x811AA454; open generals 0x811AA668, extra costumes 0x811AA64C,\n'
     '//   Japan game destinations 0x811AA694 (bit masks); gallery movies 0x811AA830/834, music 0x811AA81C/820\n'
     '//   and the u16 at 0x811AA826, titles 0x811AA808/80C; the 30 generals\' levels at 0x811AB260, 0x60 apart.\n'
     'namespace {\n'
     'constexpr uint32_t kUtageShifts[] = {0x2000u, 0u};\n'
     'constexpr uint32_t kUtageStatusPtr = 0x810468B0u;\n'
     'constexpr uint32_t kUtageMoney = 0x811AA454u;\n'
     '\n'
     'bool InGuestHeap(uint32_t p) { return p >= 0x80000000u && p < 0x81800000u - 0x400u; }\n'
     '\n'
     'uint32_t UtageStatus() {\n'
     '    for (const uint32_t shift : kUtageShifts) {\n'
     '        uint32_t st = 0, hp = 0, hpMax = 0, gaugeMax = 0;\n'
     '        if (Memory::TryRead32(kUtageStatusPtr + shift, st) && InGuestHeap(st) && Memory::TryRead32(st + 0x204u, hp) &&\n'
     '            Memory::TryRead32(st + 0x208u, hpMax) && Memory::TryRead32(st + 0x224u, gaugeMax) && hpMax > 0 &&\n'
     '            hpMax <= 10000000u && hp <= hpMax && gaugeMax > 0 && gaugeMax <= 10000000u) {\n'
     '            return st;\n'
     '        }\n'
     '    }\n'
     '    return 0;\n'
     '}\n'
     '\n'
     '// The shift the save\'s game data sits at, or ~0 while no save is loaded (every general\'s level 1..200).\n'
     'uint32_t UtageGameDataShift() {\n'
     '    for (const uint32_t shift : kUtageShifts) {\n'
     '        bool ok = true;\n'
     '        for (uint32_t i = 0; i < 30u && ok; ++i) {\n'
     '            uint32_t level = 0;\n'
     '            ok = Memory::TryRead32(0x811AB260u + shift + i * 0x60u, level) && level >= 1u && level <= 200u;\n'
     '        }\n'
     '        uint32_t generals = 0;\n'
     '        if (ok && Memory::TryRead32(0x811AA668u + shift, generals) && generals != 0) return shift;\n'
     '    }\n'
     '    return ~0u;\n'
     '}\n'
     '\n'
     'void OrBits(uint32_t addr, uint32_t bits, uint32_t& opened) {\n'
     '    uint32_t value = 0;\n'
     '    if (Memory::TryRead32(addr, value) && (value | bits) != value && Memory::TryWrite32(addr, value | bits)) ++opened;\n'
     '}\n'
     '\n'
     'void LogOnce(bool& done, const char* what, uint32_t value) {\n'
     '    if (!done) {\n'
     '        done = true;\n'
     '        RT_LOGF(RT_TAG_OS, "cheats: %s (%u)\\n", what, value);\n'
     '    }\n'
     '}\n'
     '}  // namespace\n'
     '\n'
     '// Once a frame (Utage\'s fps manager hook, guest thread).\n'
     'void Apply() {\n'
     '    if (!Available()) {\n'
     '        return;\n'
     '    }\n'
     '    static uint32_t s_frame = 0;\n'
     '    static uint32_t s_shift = ~0u;\n'
     '    ++s_frame;\n'
     '    const int32_t money = g_money.load(std::memory_order_relaxed);\n'
     '    const bool unlockAll = g_unlockAll.load(std::memory_order_relaxed);\n'
     '    // The save\'s game data: looked for twice a second (a save loaded later puts it in place).\n'
     '    if ((money != kMoneyOff || unlockAll || g_oncePending.load(std::memory_order_relaxed)) && s_frame % 30u == 1u) {\n'
     '        s_shift = UtageGameDataShift();\n'
     '    }\n'
     '    if (s_shift != ~0u) {\n'
     '        const uint32_t amount = g_amount.load(std::memory_order_relaxed);\n'
     '        const uint32_t moneyAddr = kUtageMoney + s_shift;\n'
     '        static bool s_loggedMoney = false, s_loggedOnce = false;\n'
     '        uint32_t before = 0;\n'
     '        if (money == kMoneyInfinite) {\n'
     '            if (Memory::TryRead32(moneyAddr, before) && before != amount && Memory::TryWrite32(moneyAddr, amount)) {\n'
     '                LogOnce(s_loggedMoney, "infinite money holds the amount", amount);\n'
     '            }\n'
     '        } else if (g_oncePending.exchange(false)) {\n'
     '            if (Memory::TryWrite32(moneyAddr, amount)) LogOnce(s_loggedOnce, "money set once", amount);\n'
     '        }\n'
     '        if (unlockAll && s_frame % 60u == 1u) {\n'
     '            uint32_t opened = 0;\n'
     '            OrBits(0x811AA668u + s_shift, 0x3FFFFFFFu, opened);  // generals\n'
     '            OrBits(0x811AA64Cu + s_shift, 0x3FFFFFFFu, opened);  // extra costumes\n'
     '            OrBits(0x811AA694u + s_shift, 0x7FFFFFFFu, opened);  // Japan game destinations\n'
     '            OrBits(0x811AA830u + s_shift, 0xFFFFFFFFu, opened);  // gallery: movies\n'
     '            OrBits(0x811AA834u + s_shift, 0x1FFFFFFFu, opened);\n'
     '            OrBits(0x811AA81Cu + s_shift, 0xFFFFFFFFu, opened);  // music\n'
     '            OrBits(0x811AA820u + s_shift, 0xFFFFFFFFu, opened);\n'
     '            OrBits(0x811AA824u + s_shift, 0x0000FFFFu, opened);  // the u16 at 0x811AA826\n'
     '            OrBits(0x811AA808u + s_shift, 0xFFFFFFFFu, opened);  // titles\n'
     '            OrBits(0x811AA80Cu + s_shift, 0x03FFFFFFu, opened);\n'
     '            static int s_logged = 0;\n'
     '            if (opened != 0 && s_logged < 4) {\n'
     '                ++s_logged;\n'
     '                RT_LOGF(RT_TAG_OS, "cheats: unlock all opened %u masks\\n", opened);\n'
     '            }\n'
     '        }\n'
     '    }\n'
     '    const bool hp = g_infiniteHp.load(std::memory_order_relaxed);\n'
     '    const bool basara = g_infiniteBasara.load(std::memory_order_relaxed);\n'
     '    if (!hp && !basara) {\n'
     '        return;\n'
     '    }\n'
     '    const uint32_t st = UtageStatus();\n'
     '    if (st == 0) {\n'
     '        return;\n'
     '    }\n'
     '    if (hp) {\n'
     '        static bool s_logged = false;\n'
     '        uint32_t now = 0, max = 0;\n'
     '        if (Memory::TryRead32(st + 0x204u, now) && Memory::TryRead32(st + 0x208u, max) && now < max &&\n'
     '            Memory::TryWrite32(st + 0x204u, max)) {\n'
     '            LogOnce(s_logged, "infinite HP refilled", max - now);\n'
     '        }\n'
     '    }\n'
     '    if (basara) {\n'
     '        // Full as soon as it grows, as the Gecko code makes the game\'s own add do: using an art still\n'
     '        // empties it, so arts run their course.\n'
     '        static uint32_t s_status = 0, s_last = 0;\n'
     '        static bool s_logged = false;\n'
     '        uint32_t gauge = 0, max = 0;\n'
     '        if (Memory::TryRead32(st + 0x220u, gauge) && Memory::TryRead32(st + 0x224u, max)) {\n'
     '            if (st == s_status && gauge > s_last && gauge < max && Memory::TryWrite32(st + 0x220u, max)) {\n'
     '                LogOnce(s_logged, "infinite BASARA filled the gauge", max);\n'
     '                gauge = max;\n'
     '            }\n'
     '            s_status = st;\n'
     '            s_last = gauge;\n'
     '        }\n'
     '    }\n'
     '}\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     '    UtageRefreshViews();\n'
     '    UtageLockOnUpdate();\n'
     ,
     '    UtageRefreshViews();\n'
     '    UtageLockOnUpdate();\n'
     '    Cheats::Apply();  // Settings > Cheats\n'
    ),
    # Two players on one phone (1.0.0): touch = player 1, the first gamepad = player 2.
    ('include/virtual_remote.h',
     'void SetGamepadMap(const char* map);\n'
     ,
     'void SetGamepadMap(const char* map);\n'
     '\n'
     '// Two players on one phone (Settings > Controls > Two Players (Touch + Gamepad)): the touch controls\n'
     '// play player 1 alone and the first gamepad plays player 2. Off: a gamepad plays player 1 with them.\n'
     'void SetTouchPlusPad(bool on);\n'
     '// The PAD port whose gamepad plays `chan`, or -1 when only touch does.\n'
     'int PadPortFor(uint32_t chan);\n'
    ),
    ('src/virtual_remote.cpp',
     'namespace VirtualRemote {\n'
     'namespace {\n'
     ,
     'namespace VirtualRemote {\n'
     'namespace {\n'
     '// Two Players (Touch + Gamepad): touch plays player 1 alone, the first gamepad (port 0) player 2.\n'
     'std::atomic<bool> g_touchPlusPad{[] {\n'
     '    const char* env = std::getenv("BASARA_TOUCH_PLUS_PAD");\n'
     '    return env != nullptr && env[0] == \'1\';\n'
     '}()};\n'
     '\n'
     '// The PAD port whose gamepad plays `chan`, or -1 for touch only.\n'
     'int PadPortForChannel(uint32_t chan) {\n'
     '    if (!g_touchPlusPad.load(std::memory_order_relaxed)) return static_cast<int>(chan);\n'
     '    if (chan == 0) return -1;\n'
     '    return chan == 1 ? 0 : static_cast<int>(chan);\n'
     '}\n'
    ),
    ('src/virtual_remote.cpp',
     'void AnnounceLocked(uint32_t chan, bool pad) {\n'
     ,
     'void AnnounceLocked(uint32_t chan, bool pad, uint32_t port) {\n'
    ),
    ('src/virtual_remote.cpp',
     '    if (pad) {\n'
     '        const s32 index = PADGetIndexForPort(chan);\n'
     ,
     '    if (pad) {\n'
     '        const s32 index = PADGetIndexForPort(port);\n'
    ),
    ('src/virtual_remote.cpp',
     '    return chan == 0 || g_pads[chan].err == PAD_ERR_NONE;\n'
     ,
     '    const int port = PadPortForChannel(chan);\n'
     '    return chan == 0 || (port >= 0 && g_pads[port].err == PAD_ERR_NONE);\n'
    ),
    ('src/virtual_remote.cpp',
     '    const bool pad = g_pads[chan].err == PAD_ERR_NONE;\n'
     '    if (chan != 0 && !pad) {\n'
     '        return false;\n'
     '    }\n'
     '    AnnounceLocked(chan, pad);\n'
     ,
     '    const int port = PadPortForChannel(chan);\n'
     '    const bool pad = port >= 0 && g_pads[port].err == PAD_ERR_NONE;\n'
     '    if (chan != 0 && !pad) {\n'
     '        return false;\n'
     '    }\n'
     '    AnnounceLocked(chan, pad, static_cast<uint32_t>(std::max(port, 0)));\n'
    ),
    ('src/virtual_remote.cpp',
     '        intent = PadIntent(chan, g_pads[chan]);\n'
     ,
     '        intent = PadIntent(static_cast<uint32_t>(port), g_pads[port]);\n'
    ),
    ('src/virtual_remote.cpp',
     '} // namespace VirtualRemote\n'
     ,
     'void SetTouchPlusPad(bool on) {\n'
     '    if (g_touchPlusPad.exchange(on) != on) {\n'
     '        std::lock_guard<std::mutex> lock(g_mutex);\n'
     '        g_announced[0] = g_announced[1] = false;  // say again who plays what\n'
     '        RT_LOGF(RT_TAG_RUNTIME, "two players: %s\\n", on ? "touch plays player 1, the first gamepad player 2" : "off");\n'
     '    }\n'
     '}\n'
     '\n'
     'int PadPortFor(uint32_t chan) { return chan < PAD_MAX_CONTROLLERS ? PadPortForChannel(chan) : -1; }\n'
     '\n'
     '} // namespace VirtualRemote\n'
    ),
    ('src/android/android_bridge.cpp',
     '// GameActivity.nativeSetRumble:',
     '// GameActivity.nativeSetTouchPlusPad: Settings > Controls > Two Players (Touch + Gamepad).\n'
     'JNIEXPORT void JNICALL Java_io_github_dezer04_sb3utage_GameActivity_nativeSetTouchPlusPad(JNIEnv*, jclass, jboolean on)\n'
     '{\n'
     '    VirtualRemote::SetTouchPlusPad(on == JNI_TRUE);\n'
     '}\n\n'
     '// GameActivity.nativeSetRumble:'),
    # Riivolution <id disc= version=> from the game's disc header (1.0.0): the Indonesian patch's XML
    # names disc 0 version 0 and was skipped with both unknown.
    ('src/hle/storage/dvd.cpp',
     'static const fs::path& GetDvdRoot() {\n'
     ,
     'static const fs::path& GetDvdRoot();\n'
     '\n'
     '// The disc header\'s disc number and revision (sys/boot.bin bytes 6 and 7, from the image or the\n'
     '// unpacked folder) for Riivolution\'s <id disc= version=> (riivolution.cpp). Low memory\n'
     '// 0x80000006 is no help: DVDInit below writes 1 there.\n'
     'bool DvdHeaderDiscAndRevision(uint8_t& discNumber, uint8_t& revision) {\n'
     '    uint8_t header[8] = {};\n'
     '    bool read = false;\n'
     '    if (g_discImage) {\n'
     '        for (const disc::DiscFile& file : g_discImage->Files()) {\n'
     '            if (file.path == "sys/boot.bin" && file.size >= sizeof(header)) {\n'
     '                read = g_discImage->Read(file.offset, header, sizeof(header));\n'
     '                break;\n'
     '            }\n'
     '        }\n'
     '    } else {\n'
     '        std::ifstream boot(GetDvdRoot() / "sys" / "boot.bin", std::ios::binary);\n'
     '        read = static_cast<bool>(boot.read(reinterpret_cast<char*>(header), sizeof(header)));\n'
     '    }\n'
     '    if (!read) return false;\n'
     '    discNumber = header[6];\n'
     '    revision = header[7];\n'
     '    return true;\n'
     '}\n'
     '\n'
     'static const fs::path& GetDvdRoot() {\n'
    ),
    ('src/hle/storage/riivolution.cpp',
     'namespace fs = std::filesystem;\n'
     ,
     'namespace fs = std::filesystem;\n'
     '\n'
     'bool DvdHeaderDiscAndRevision(uint8_t& discNumber, uint8_t& revision);  // dvd.cpp, global\n'
    ),
    ('src/hle/storage/riivolution.cpp',
     '        if (!disc->IsValidForGame(gameId, std::nullopt, std::nullopt)) {\n'
     ,
     '        // The disc number and revision from the game\'s own header, as Dolphin passes them: an XML\n'
     '        // naming them (<id disc="0" version="0"/>) was skipped with both unknown.\n'
     '        uint8_t headerDisc = 0, headerRevision = 0;\n'
     '        const bool headerKnown = DvdHeaderDiscAndRevision(headerDisc, headerRevision);\n'
     '        if (!disc->IsValidForGame(gameId,\n'
     '                                  headerKnown ? std::optional<uint16_t>(headerRevision) : std::nullopt,\n'
     '                                  headerKnown ? std::optional<uint8_t>(headerDisc) : std::nullopt)) {\n'
    ),
    # The 10 s summary and the utage speed line leave out time paused in the background (1.0.0):
    # a 70 s pause read as 7 fps and 0.12x.
    ('src/hle/vi.cpp',
     '            const double frame = ms(now - s_lastEnd);\n'
     ,
     '            // Time paused in the background (HostSuspend) is not the game\'s: left out of the frame it\n'
     '            // fell in and of the summary below.\n'
     '            static uint64_t s_framePausedBase = HostSuspend::PausedNanoseconds();\n'
     '            const uint64_t pausedTotal = HostSuspend::PausedNanoseconds();\n'
     '            const double framePausedMs = (pausedTotal - s_framePausedBase) / 1e6;\n'
     '            s_framePausedBase = pausedTotal;\n'
     '            const double frame = std::max(0.0, ms(now - s_lastEnd) - framePausedMs);\n'
    ),
    ('src/hle/vi.cpp',
     '                static uint64_t s_sumSkipBase = 0, s_sumStepBase = 0;\n'
     '                if (s_sumStart == Clock::time_point{}) {\n'
     '                    s_sumStart = now;\n'
     ,
     '                static uint64_t s_sumSkipBase = 0, s_sumStepBase = 0, s_sumPausedBase = 0;\n'
     '                if (s_sumStart == Clock::time_point{}) {\n'
     '                    s_sumStart = now;\n'
     '                    s_sumPausedBase = pausedTotal;\n'
    ),
    ('src/hle/vi.cpp',
     '                const double span = std::chrono::duration<double>(now - s_sumStart).count();\n'
     '                if (span >= 10.0) {\n'
     ,
     '                const double pausedSpan = (pausedTotal - s_sumPausedBase) / 1e9;\n'
     '                const double span = std::chrono::duration<double>(now - s_sumStart).count() - pausedSpan;\n'
     '                if (span >= 10.0) {\n'
     '                    char paused[48] = "";\n'
     '                    if (pausedSpan >= 0.5) std::snprintf(paused, sizeof(paused), " (%.0f s paused left out)", pausedSpan);\n'
    ),
    ('src/hle/vi.cpp',
     '                            "thread cpu %.1f ms, %u frames over 20 ms\\n",\n'
     '                            span, s_sumFrames / span, (steps - s_sumStepBase) / span,\n'
     '                            static_cast<unsigned long long>(skipped - s_sumSkipBase), s_sumMs / s_sumFrames,\n'
     '                            s_sumCpu / s_sumFrames, s_sumSlow);\n'
     '                    s_sumStart = now;\n'
     ,
     '                            "thread cpu %.1f ms, %u frames over 20 ms%s\\n",\n'
     '                            span, s_sumFrames / span, (steps - s_sumStepBase) / span,\n'
     '                            static_cast<unsigned long long>(skipped - s_sumSkipBase), s_sumMs / s_sumFrames,\n'
     '                            s_sumCpu / s_sumFrames, s_sumSlow, paused);\n'
     '                    s_sumStart = now;\n'
     '                    s_sumPausedBase = pausedTotal;\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     '#include "cheats.h"\n'
     ,
     '#include "cheats.h"\n'
     '#include "host_suspend.h"\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     'Clock::time_point g_utageStatsStart{};\n'
     ,
     'Clock::time_point g_utageStatsStart{};\n'
     'uint64_t g_utageStatsPaused = 0;  // HostSuspend::PausedNanoseconds() at g_utageStatsStart\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     '    if (g_utageStatsStart == Clock::time_point{}) {\n'
     '        g_utageStatsStart = now;\n'
     '        return;\n'
     ,
     '    if (g_utageStatsStart == Clock::time_point{}) {\n'
     '        g_utageStatsStart = now;\n'
     '        g_utageStatsPaused = HostSuspend::PausedNanoseconds();\n'
     '        return;\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     '    const double seconds = std::chrono::duration<double>(now - g_utageStatsStart).count();\n'
     ,
     '    // Time paused in the background is left out: it is neither game time nor real playing time.\n'
     '    const double seconds = std::chrono::duration<double>(now - g_utageStatsStart).count()\n'
     '            - (HostSuspend::PausedNanoseconds() - g_utageStatsPaused) / 1e9;\n'
    ),
    ('src/hle/basara_frameskip.cpp',
     '    g_utageFrames = 0;\n'
     '    g_utageStatsStart = now;\n'
     ,
     '    g_utageFrames = 0;\n'
     '    g_utageStatsStart = now;\n'
     '    g_utageStatsPaused = HostSuspend::PausedNanoseconds();\n'
    ),
    # A patch did nothing in Read mode: Riivolution checks the XML's <id disc= version=> at boot, from
    # the NAND's save redirect, before anything opened the disc. The header then came from
    # "<image>/sys/boot.bin", which is no file, and an XML naming disc and version was skipped.
    ('src/hle/storage/dvd.cpp',
     'bool DvdHeaderDiscAndRevision(uint8_t& discNumber, uint8_t& revision) {\n'
     '    uint8_t header[8] = {};\n'
     '    bool read = false;\n'
     '    if (g_discImage) {\n',
     'bool DvdHeaderDiscAndRevision(uint8_t& discNumber, uint8_t& revision) {\n'
     '    uint8_t header[8] = {};\n'
     '    bool read = false;\n'
     '    GetDvdRoot();  // opens the image in Read mode: Riivolution can ask before anything else did\n'
     '    if (g_discImage) {\n'
    ),
    # The in-app recorder (aurora/lib/recorder.cpp) hears what the output plays, before the volume.
    ('src/audio_backend.cpp',
     '#include <SDL3/SDL_timer.h>\n',
     '#include <SDL3/SDL_timer.h>\n'
     '\n'
     'extern "C" void aurora_recorder_audio(const int16_t* frames, uint32_t count, uint32_t sampleRate);\n'
    ),
    ('src/audio_backend.cpp',
     '    self->PullStretched(self->m_pullBuffer.data(), frames);\n',
     '    self->PullStretched(self->m_pullBuffer.data(), frames);\n'
     '    aurora_recorder_audio(self->m_pullBuffer.data(), static_cast<uint32_t>(frames), self->m_sampleRate);\n'
    ),
    ('src/audio_backend.cpp',
     '    self->PullStretched(out, static_cast<size_t>(numFrames));\n',
     '    self->PullStretched(out, static_cast<size_t>(numFrames));\n'
     '    aurora_recorder_audio(out, static_cast<uint32_t>(numFrames), self->m_sampleRate);\n'
    ),
]


# Investigation-only entries (logs, traces, dumps, the scheduler loggers): left out unless U_DIAG=1,
# since they cost frame time. Recognised by what they add.
DIAG_MARKERS = ('Utage diagnostic', 'UtageTrace', 'g_utageTraceFrame', 'UtagePixDiag', 'UtageTevDiag',
                'UtageLcDiag', 'UtageDlDiag', 'UtageQuadDiag', 'g_utageSchedRaise', 'UtageLogHostBacktrace',
                'prevFrames', '[sched] host bt')


def is_diag(new):
    return any(m in new for m in DIAG_MARKERS)


def main():
    import os
    diag = os.environ.get('U_DIAG') == '1'
    by_file = {}
    skipped = 0
    for name, old, new in FIXES:
        # U_MEMDUMP=1: only the memory snapshot hook (u-shots "SEC:dump"), for a PC investigation build.
        if not diag and is_diag(new) and not (os.environ.get('U_MEMDUMP') == '1' and 'memdump.req' in new):
            skipped += 1
            if os.environ.get('U_DIAG_LIST') == '1':
                print('  skip %s: %s' % (name, new.strip().splitlines()[0][:90]))
            continue
        by_file.setdefault(name, []).append((old, new))
    for name, pairs in by_file.items():
        f = RT / name
        s = f.read_text(encoding='utf-8')
        for old, new in pairs:
            if old not in s:
                sys.exit('u_manual: not found in %s: %s' % (name, old[:70]))
            s = s.replace(old, new)
        f.write_text(s, encoding='utf-8', newline='\n')
    print('u_manual: %d fixes in %d files%s' % (len(FIXES) - skipped, len(by_file),
                                                '' if diag else ' (%d diagnostic entries left out; U_DIAG=1 adds them)' % skipped))


if __name__ == '__main__':
    main()
