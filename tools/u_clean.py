#!/usr/bin/env python3
"""Takes the Basara 2 Heroes leftovers out of the Utage runtime (the last step of tools/u_port.sh, after
u_manual.py). The runtime is rebuilt from the Basara 2 sources at every port, so what Utage does not have
is removed here, not by hand:

- every disabled "#if 0" block: the hooks u_remap.py found no Utage address for, and the NSMBW / Mario
  Kart code the Basara 2 tree still carried switched off;
- Basara-only modules whose every hook is gone (CRI loader and movie, task wait, angle wrap, grid
  walk, bucket pool, EGG draw);
- the Basara main loop (frameskip, Skip Boot, its step counters), the CRI ADX server pass logic
  (Utage has no CRI middleware), the RBSJ08 archive-size disc check and the Basara cheats;
- code that still used Basara addresses in this game: the camera aspect written every frame, the
  thread creation's __OSErrorTable read, the AX DSP task's microcode and callbacks, the profiler's
  code range, a debug log reading Basara's button words;
- texts and comments that named Basara 2 Heroes, RBSJ08 or its folders.

Every anchor must match exactly once: a change upstream stops the port instead of passing silently.

  python -I tools/u_clean.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RT = ROOT / 'runtime'

DELETE = [
    'src/hle/basara_criload.cpp',   # CRI file loader (Utage has no CRI middleware)
    'src/hle/basara_movie.cpp',     # CRI Sofdec movie colour conversion
    'src/hle/basara_taskwait.cpp',  # Basara's task wait and HBM sound shutdown
    'src/hle/basara_angle.cpp',     # Basara's angle wrap
    'src/hle/basara_gridwalk.cpp',  # Basara's grid walk
    'src/hle/basara_otpool.cpp',    # Basara's bucket pool
    'src/hle/gx/gx_egg.cpp',        # EGG draw helpers at Basara addresses
    'src/dynamic_aspect.cpp',       # Mario Kart's EGG screens; its one live call swept nothing
    'src/hle/gx/gx_dynamic_aspect.h',
]


def text(rel):
    return (RT / rel).read_text(encoding='utf-8')


def write(rel, s):
    (RT / rel).write_text(s, encoding='utf-8', newline='\n')


def replace(rel, old, new, count=1):
    s = text(rel)
    n = s.count(old)
    if n != count:
        sys.exit('u_clean: %s: %r found %d times, expected %d' % (rel, old[:70], n, count))
    write(rel, s.replace(old, new))


def cut(rel, start, end, keep_end=True):
    """Removes from `start` up to `end` (kept when keep_end); both must occur once, in that order."""
    s = text(rel)
    for anchor in (start, end):
        if s.count(anchor) != 1:
            sys.exit('u_clean: %s: %r found %d times' % (rel, anchor[:70], s.count(anchor)))
    a = s.index(start)
    b = s.index(end)
    if b < a:
        sys.exit('u_clean: %s: %r comes before %r' % (rel, end[:40], start[:40]))
    write(rel, s[:a] + s[b if keep_end else b + len(end):])


def drop_disabled_blocks(marker=None):
    """Removes every "#if 0" block (with `marker` in its line, or any) from runtime/src and include, up to
    its matching #endif. An #else or #elif of the block keeps what follows it (as plain code, or as #if)."""
    removed = 0
    for path in sorted(list((RT / 'src').rglob('*.cpp')) + list((RT / 'src').rglob('*.h')) +
                       list((RT / 'include').rglob('*.h'))):
        lines = path.read_text(encoding='utf-8').split('\n')
        out = []
        depth = 0
        keeping = False  # in the #else branch of a dropped block
        for line in lines:
            t = line.strip()
            if depth:
                if t.startswith('#if'):
                    depth += 1
                elif t.startswith('#endif'):
                    depth -= 1
                    if depth == 0:
                        if keeping and t != '#endif' and not t.startswith('#endif '):
                            sys.exit('u_clean: %s: odd #endif %r' % (path, t))
                        keeping = False
                        continue
                elif depth == 1 and t.startswith('#else') and not keeping:
                    keeping = True
                    continue
                elif depth == 1 and t.startswith('#elif') and not keeping:
                    # "#if 0 ... #elif X ... #endif" is "#if X ... #endif".
                    out.append(line.replace('#elif', '#if', 1))
                    depth = 0
                    continue
                if keeping:
                    out.append(line)
                continue
            if re.match(r'#if 0\b', t) and (marker is None or marker in t):
                depth = 1
                removed += 1
                continue
            out.append(line)
        if depth:
            sys.exit('u_clean: %s: unterminated #if 0 block' % path)
        if len(out) != len(lines):
            # A block between two blank lines leaves one.
            joined = re.sub(r'\n\n\n+', '\n\n', '\n'.join(out))
            path.write_text(joined, encoding='utf-8', newline='\n')
    return removed


DEF_TAIL = r'\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?\{'


def matching_brace(s, i):
    """The index of the brace that closes the one at s[i], skipping strings, chars and comments."""
    depth = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '/' and s.startswith('//', i):
            i = s.find('\n', i)
            if i < 0:
                break
        elif c == '/' and s.startswith('/*', i):
            i = s.find('*/', i) + 1
        elif c in '"\'':
            if c == '"' and i > 0 and s[i - 1] == 'R':  # raw string R"x(...)x"
                d = s[i + 1:s.index('(', i)]
                i = s.index(')' + d + '"', i) + len(d) + 1
            else:
                j = i + 1
                while s[j] != c:
                    j += 2 if s[j] == '\\' else 1
                i = j
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    sys.exit('u_clean: unbalanced braces')


def comment_above(s, start):
    """Where the // comment block right above `start` (a line start) begins, else `start`."""
    while start > 0:
        prev = s.rfind('\n', 0, start - 1) + 1
        if s[prev:start].strip().startswith('//'):
            start = prev
        else:
            break
    return start


def drop_variable(rel, name):
    """Removes the namespace-scope variable `name` declared in `rel` (to its ';', with its comment)."""
    s = text(rel)
    found = [m for m in re.finditer(r'^(?P<pre>[A-Za-z_][^\n;{}()=]*?)\b' + re.escape(name) + r'\b\s*(?:=|\{|\[|;)', s, re.M)]
    if len(found) != 1:
        sys.exit('u_clean: %s: variable %s declared %d times' % (rel, name, len(found)))
    m = found[0]
    depth = 0
    i = m.start()
    while True:
        c = s[i]
        if c in '"\'':
            j = i + 1
            while s[j] != c:
                j += 2 if s[j] == '\\' else 1
            i = j
        elif c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
        elif c == ',' and depth == 0:
            sys.exit('u_clean: %s: %s shares its declaration with others' % (rel, name))
        elif c == ';' and depth == 0:
            break
        i += 1
    line_end = s.find('\n', i)
    start = comment_above(s, m.start())
    s = s[:start] + s[line_end + 1 if line_end >= 0 else len(s):]
    write(rel, re.sub(r'\n\n\n+', '\n\n', s))


def drop_function(rel, name, local=False):
    """Removes function `name`'s one definition in `rel` (with its comment) and its declarations (only in
    `rel` for a file-local one)."""
    s = text(rel)
    defs = [m for m in re.finditer(r'^(?P<pre>[^\n;{}]*?)\b' + re.escape(name) + DEF_TAIL, s, re.M)
            if not re.search(r'\b(if|while|for|switch|return)\b|[=(,]\s*$', m.group('pre'))]
    if len(defs) != 1:
        sys.exit('u_clean: %s: %s defined %d times' % (rel, name, len(defs)))
    m = defs[0]
    start = m.start()
    # A return type on the line above ("extern \"C\" void" / "static int").
    prev = s.rfind('\n', 0, start - 1) + 1
    above = s[prev:start].strip()
    if start > 0 and above and not above.startswith(('//', '#', '*', '/*')) and above[-1] not in ';{}:,)':
        start = prev
    start = comment_above(s, start)
    end = matching_brace(s, m.end() - 1)
    line_end = s.find('\n', end)
    s = s[:start] + s[line_end + 1 if line_end >= 0 else len(s):]
    write(rel, re.sub(r'\n\n\n+', '\n\n', s))
    decl = re.compile(r'^[ \t]*(?:extern "C"\s*)?(?:[\w:<>]+[ \t\*&]+)+' + re.escape(name) +
                      r'\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?;[^\n]*\n', re.M)
    paths = [RT / rel] if local else \
        list((RT / 'src').rglob('*.cpp')) + list((RT / 'src').rglob('*.h')) + list((RT / 'include').rglob('*.h'))
    for path in paths:
        t = path.read_text(encoding='utf-8')
        if name not in t:
            continue
        out = t
        for d in reversed(list(decl.finditer(t))):
            a = comment_above(out, d.start())
            out = out[:a] + out[d.end():]
        if out != t:
            path.write_text(re.sub(r'\n\n\n+', '\n\n', out), encoding='utf-8', newline='\n')


def drop_unused_functions():
    """What tools/u_unused.py and u_unused_static.py found nothing using (tools/u_clean_unused.txt):
    "<file> <name>" a function the linker dropped, "<file> <name> static" a file-local function or
    namespace-scope variable the compiler found unused."""
    listing = ROOT / 'tools' / 'u_clean_unused.txt'
    if not listing.exists():
        return 0
    count = 0
    for line in listing.read_text(encoding='utf-8').split('\n'):
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        rel, name = parts[0], parts[1]
        if len(parts) > 2 and parts[2] == 'static':
            s = text(rel)
            if re.search(r'^[^\n;{}]*?\b' + re.escape(name) + DEF_TAIL, s, re.M):
                drop_function(rel, name, local=True)
            else:
                drop_variable(rel, name)
        else:
            drop_function(rel, name)
        count += 1
    return count


def main():
    for rel in DELETE:
        path = RT / rel
        if not path.exists():
            sys.exit('u_clean: %s is already gone' % rel)
        path.unlink()
    # Every disabled block: the hooks u_remap found no Utage address for, and older NSMBW / MKW code.
    blocks = drop_disabled_blocks()

    # --- the Basara main loop: frameskip, Skip Boot and its step counters --------------------------
    f = 'src/hle/basara_frameskip.cpp'
    cut(f, '// Basara\'s main loop (802BE4F4), native so it can skip drawing a frame.',
        '#include "hle_stubs.h"\n')
    replace(f, '#include "hle_stubs.h"\n',
            '// Frameskip and Game Speed for Utage (MT Framework\'s sMain, below), the camera distance and Lock\n'
            '// Target. Config: [video] frameskip = 0 off, 1 auto, 2 30 fps lock. BASARA_FRAMESKIP=0/1/2\n'
            '// overrides it.\n'
            '#include "hle_stubs.h"\n')
    replace(f, 'extern "C" bool AuroraGxThreadEnabled();\nextern "C" uint64_t AuroraGxThreadMark();\n'
               'extern "C" void AuroraGxThreadWaitMark(uint64_t ticket);\n\n', '')
    cut(f, 'constexpr uint32_t kGameState = 0x80564768u;', '// Thermal Control: while the phone runs hot')
    cut(f, '// Skip Boot: from start to the save check', 'const char* ModeName(int value)')
    cut(f, 'void Call(CpuContext* ctx, uint32_t target) {', '} // namespace\n\nvoid BasaraBootSkip_SaveAccess() {')
    cut(f, 'void BasaraBootSkip_SaveAccess() {', 'void BasaraFrameskip_SetMode(int mode) {')
    cut(f, 'void BasaraFrameskip_Stats(uint64_t* frames, uint64_t* skipped) {',
        '// Utage (MT Framework): sMain (pointer at 0x808F3FD8)')
    replace(f, ' (Basara 2: moving it back went into walls)', ' (moving it back went into walls)')
    f = 'include/hle_stubs.h'
    replace(f, '// Basara: whether CRI\'s ADX server thread owes itself another pass for a retrace it missed (vi.cpp).\n'
               'bool VI_HLE_TakeOwedCriServerPass();\n', '')
    replace(f, 'void BasaraFrameskip_Stats(uint64_t* frames, uint64_t* skipped);\n', '')
    replace(f, 'void BasaraBootSkip_SaveAccess();\n', '')
    replace('src/hle/storage/nand_fs.cpp',
            '    if (wiiPathStr.find("/00010000/5242534a") != std::string::npos) {\n'
            '        BasaraBootSkip_SaveAccess();\n'
            '    }\n', '')

    # --- vi.cpp: the CRI server pass, the summary's Basara step counters, the disc check -----------
    f = 'src/hle/vi.cpp'
    cut(f, '// CRI\'s V-sync thread (804072FC) wakes on every retrace',
        '    if (now - s_due > interval * kMaxOwedPasses) {\n'
        '        s_due = now - interval * kMaxOwedPasses;\n'
        '    }\n'
        '    return true;\n'
        '}\n', keep_end=False)
    replace(f, '                static uint64_t s_sumSkipBase = 0, s_sumStepBase = 0, s_sumPausedBase = 0;\n',
               '                static uint64_t s_sumPausedBase = 0;\n')
    replace(f, '                    s_sumPausedBase = pausedTotal;\n'
               '                    BasaraFrameskip_Stats(&s_sumStepBase, &s_sumSkipBase);\n',
               '                    s_sumPausedBase = pausedTotal;\n')
    replace(f, '                    uint64_t steps = 0, skipped = 0;\n'
               '                    BasaraFrameskip_Stats(&steps, &skipped);\n', '')
    replace(f, '"summary %.0f s: %.1f fps shown, %.1f steps/s (%llu skipped), frame %.1f ms, "',
               '"summary %.0f s: %.1f fps shown, frame %.1f ms, "')
    replace(f, '                            span, s_sumFrames / span, (steps - s_sumStepBase) / span,\n'
               '                            static_cast<unsigned long long>(skipped - s_sumSkipBase), s_sumMs / s_sumFrames,\n',
               '                            span, s_sumFrames / span, s_sumMs / s_sumFrames,\n')
    replace(f, '                    s_sumStepBase = steps;\n                    s_sumSkipBase = skipped;\n', '')
    cut(f, '            {\n                // The game\'s own steps (main loop passes), drawn or skipped: its speed, against 60.\n',
        '                s_lastSteps = steps;\n                s_lastSkipped = skipped;\n            }\n', keep_end=False)
    replace(f, '// say how fast the game ran. Shown pictures a second, frameskip skips, frame and thread-cpu\n',
               '// say how fast the game ran. Shown pictures a second, frame and thread-cpu\n')
    replace(f, 'bool DvdDiscChanged();\n', '')
    replace(f, '                        "preload %lld MiB%s\\n",\n', '                        "preload %lld MiB\\n",\n')
    replace(f, '                        static_cast<long long>(preload < 0 ? -1 : preload >> 20),\n'
               '                        DvdDiscChanged() ? ", disc NOT ORIGINAL" : "");\n',
               '                        static_cast<long long>(preload < 0 ? -1 : preload >> 20));\n')
    replace(f, '                if (frames > 2 && !black) {  // Basara: also dump when stalled after the first frame\n',
               '                if (frames > 2 && !black) {  // also dump when stalled after the first frame\n')

    # --- dvd.cpp: the RBSJ08 archive sizes ----------------------------------------------------------
    f = 'src/hle/storage/dvd.cpp'
    cut(f, '// Basara: the three archives\' sizes on the original RBSJ08 disc.',
        'bool DvdDiscChanged() { return g_discChanged.load(std::memory_order_relaxed); }\n', keep_end=False)
    replace(f, '    CheckDiscArchives();\n', '')

    # --- os_thread.cpp: CRI's server thread, and Utage's __OSErrorTable ----------------------------
    f = 'src/hle/os/os_thread.cpp'
    replace(f, '    // Basara: CRI\'s ADX server thread suspending itself at the end of a pass (the call in 804073FC\'s\n'
               '    // loop) runs straight into another pass for each retrace it missed (VI_HLE_TakeOwedCriServerPass).\n'
               '    constexpr uint32_t kCriServerSuspendReturn = 0x804074A4u;\n'
               '    if (cpu->lr == kCriServerSuspendReturn && VI_HLE_TakeOwedCriServerPass()) {\n'
               '        cpu->gpr[3] = 0;  // previous suspend count: it was running\n'
               '        return;\n'
               '    }\n\n', '')
    replace(f, '        constexpr uint32_t kSchedulerInitFlagAddr = 0x805903D0u;  // &__OSErrorTable[16]\n',
               '        constexpr uint32_t kSchedulerInitFlagAddr = 0x8097E5B0u;  // &__OSErrorTable[16] (805C2C44)\n')

    # --- cheats: Basara's money, unlock-all and argument hooks --------------------------------------
    f = 'src/cheats.cpp'
    cut(f, '// The save/progress record at 0x80558F18', '// Read on the guest thread, set from Config.toml')
    cut(f, '// Unlock all. The save lives at 0x8051DC10;', '} // namespace\n\nbool Available() {')
    replace(f, 'bool InfiniteHp() { return g_infiniteHp.load(std::memory_order_relaxed) && Available(); }\n'
               'bool InfiniteBasara() { return g_infiniteBasara.load(std::memory_order_relaxed) && Available(); }\n'
               'bool InfiniteMoney() { return g_money.load(std::memory_order_relaxed) == kMoneyInfinite && Available(); }\n\n',
            '')
    s = text(f)
    end = '} // namespace Cheats\n'
    if s.count(end) != 1:
        sys.exit('u_clean: %s: namespace end not found once' % f)
    write(f, s[:s.index(end) + len(end)])
    f = 'include/cheats.h'
    replace(f, '// Cheats for Sengoku Basara 2 Heroes (RBSJ08), first written by a friend\'s Linux port of this tree.\n',
               '// Cheats for Sengoku Basara 3 Utage (S3HJ08): cheats.cpp Apply, from the fps manager hook.\n')
    replace(f, '// The money cap the game clamps to when it adds a battle\'s earnings (func_80280B74).\n',
               '// The money Infinite holds and Once sets at most.\n')
    replace(f, '// Keeps the enabled cheats applied. Call once a frame on the guest thread. Unlock all gives every\n'
               '// character, stage, skill, weapon and item the game has a place for in the save, once a second; what\n'
               '// the game saves with them stays after the cheat is turned off.\n',
               '// Keeps the enabled cheats applied. Call once a frame on the guest thread. Unlock all opens the\n'
               '// generals, extra costumes, Japan game destinations and gallery; what the game saves with them stays\n'
               '// after the cheat is turned off.\n')
    s = text(f)
    tail = '\n// Argument hooks (abi_bridge.h ApplyRuntimeCallOptions).\n'
    if s.count(tail) != 1:
        sys.exit('u_clean: %s: argument hooks not found once' % f)
    write(f, s[:s.index(tail) + 1])
    replace('include/abi_bridge.h',
            '    // Utage: the Basara 2 cheat hooks lived here, at Basara 2 addresses that are other functions in this\n'
            '    // game. Utage\'s cheats write data instead (cheats.cpp Apply, from its fps manager hook).\n',
            '')

    # --- display_settings.cpp: Basara's camera aspect, written every frame -------------------------
    f = 'src/display_settings.cpp'
    cut(f, '// Basara\'s only MTXPerspective wrapper (802BF3F4, every camera)', '// Real widescreen (Hor+, 1.1)')
    cut(f, 'void ApplyGuestCameraAspect(float pictureAspect) {', '// Fill: aurora\'s 3D projection widens')
    replace(f, '    AuroraSetFill2D(fitted && s_fill2D);\n'
               '    ApplyGuestCameraAspect(fitted ? static_cast<float>(g_surfaceWidth) / static_cast<float>(g_surfaceHeight)\n'
               '                                  : aspect == kAspect16x9 ? kRatio16x9 : 4.0f / 3.0f);\n',
               '    AuroraSetFill2D(fitted && s_fill2D);\n')

    # --- virtual_remote.cpp: a debug log of Basara's button words ---------------------------------
    f = 'src/virtual_remote.cpp'
    replace(f, '// The game\'s own button word, built from the Classic buttons each frame (BASARA_LOG_CLASSIC).\n'
               'constexpr uint32_t kGameButtonHold = 0x80564770;\n', '')
    cut(f, '    static const bool logClassic = std::getenv("BASARA_LOG_CLASSIC") != nullptr;\n',
        '    return true;\n}\n')

    # --- the AX DSP task: Utage's microcode and callbacks (__AXOutInitDSP 8055BD30) -----------------
    f = 'src/hle/audio/ax_internal.h'
    replace(f, 'constexpr uint32_t kAxIramMmemAddr = 0x804EE5C0u;  // Basara   // axDspSlave microcode (NSMBW)\n',
               'constexpr uint32_t kAxIramMmemAddr = 0x808B24A0u;  // axDspSlave microcode\n')
    replace(f, 'constexpr uint32_t kAxDoneCallback = 0x803740B8u;  // Basara    // __AXDSPDoneCallback (task+0x30 in NSMBW __AXOutInitDSP)\n',
               'constexpr uint32_t kAxDoneCallback = 0x8055BD10u;  // __AXDSPDoneCallback (task+0x30)\n')
    replace(f, 'constexpr uint32_t kAxRequestCallback = 0x803740C8u;  // Basara // __AXDSPRequestCallback (task+0x34)\n',
               'constexpr uint32_t kAxRequestCallback = 0x8055BD20u;  // __AXDSPRequestCallback (task+0x34)\n')

    # --- the profiler's game code range: Utage's .text ends at 0x808335E0 ---------------------------
    replace('src/guest_profiler.cpp', '{std::pair{0x80004000u, 0x804921E0u}}', '{std::pair{0x80004000u, 0x808335E0u}}', 2)

    # --- texts and comments ------------------------------------------------------------------------
    replace('src/hle/os/os_reset.cpp', '    RT_LOGF(RT_TAG_OS, "exit(status=%d) called via 0x801B89E0\\n", status);\n',
            '    RT_LOGF(RT_TAG_OS, "exit(status=%d) called\\n", status);\n')
    replace('src/hle/os/os_reset.cpp', '// 0x801B89E0 -> exit(int status)\n', '// exit(int status)\n')
    replace('src/android/android_bridge.cpp', '(com.shiinobu.basara)', '(io.github.dezer04.sb3utage)')
    replace('src/game_folder.cpp', 'Sengoku Basara 2 Heroes', 'Sengoku Basara 3 Utage', 7)
    replace('include/game_folder.h',
            '// The player\'s own copy of Sengoku Basara 2 Heroes, extracted with Dolphin ("Extract Entire Disc"):\n'
            '// a folder holding files/ and sys/. This port runs only the Japanese disc (RBSJ08); other discs\n',
            '// The player\'s own copy of Sengoku Basara 3 Utage, extracted with Dolphin ("Extract Entire Disc"):\n'
            '// a folder holding files/ and sys/. This port runs only the Japanese disc (S3HJ08); other discs\n')
    replace('include/runtime_config.h', '"# paths.dvd_root is your Sengoku Basara 2 Heroes (RBSJ08), extracted with\\n"',
            '"# paths.dvd_root is your Sengoku Basara 3 Utage (S3HJ08), extracted with\\n"')
    replace('src/hle/os/os_font.cpp', '// RBSJ08 is a Japanese game', '// S3HJ08 is a Japanese game')
    replace('src/hle/os/os_internal.h', '// Basara RBSJ08 addresses (from SelectThread/OSCreateThread/__OSSetInterruptHandler disassembly; was NSMBW).',
            '// Utage addresses (from SelectThread/OSCreateThread/__OSSetInterruptHandler).')
    replace('src/hle/gx/gx_pixel.cpp', '// GXSetFog (0x803848b8 in RBSJ08) is not overridden', '// GXSetFog is not overridden')
    replace('src/system_bridge.cpp', '// Basara RBSJ08 __ArenaLo (OSInit 0x8035A768)', '// Utage __ArenaLo')
    replace('src/hle/gx/gx_hud.cpp', '// Basara 2D layer (HUD, markers over characters, menus)', '// The game\'s 2D layer (HUD, markers over characters, menus)')
    replace('src/hle/gx/gx_internal.h', '// gx_hud.cpp: the Basara 2D layer (BASARA_LOG_2D).', '// gx_hud.cpp: the game\'s 2D layer (BASARA_LOG_2D).')
    replace('src/main.cpp', '/sdcard/Basara2Heroes(-Beta)', '/sdcard/SB3UtageINDO')
    replace('src/main.cpp', '/sdcard/Basara2Heroes-Beta/env.txt', '/sdcard/SB3UtageINDO/env.txt')
    replace('src/main.cpp', '/sdcard/Basara2Heroes[-Beta]/Textures', '/sdcard/SB3UtageINDO/Textures')

    # Mario Kart's offscreen-screen bypass: called on every viewport read, it swept nothing in this game.
    replace('src/hle/gx/gx_transform.cpp',
            '    // EGG::StateGX::GXSetViewport (0x802418D0) reads the current viewport unconditionally, and\n'
            '    // every offscreen bake reaches it via its clear pass (0x802D1900) before building its own\n'
            '    // projection, so arming the frustum-scale bypass here always beats the bake, including\n'
            '    // RaceScene::createSubsystems\'s frame-boundary-less ones. Gated to one walk per GX frame to\n'
            '    // skip the cross-TU call on repeats, while the first viewport read of each frame stays unthrottled.\n'
            '    static int lastBypassFrame = -1;\n'
            '    if (lastBypassFrame != g_gxFrameCount) {\n'
            '        lastBypassFrame = g_gxFrameCount;\n'
            '        AssertMkwOffscreenScreenBypass();\n'
            '    }\n', '')
    replace('include/aurora_events.h',
            '// Arms the "keep EGG::Frustum\'s projection scale" flag on every screen that\n'
            '// renders to a fixed-size offscreen target. Cheap and idempotent; called from\n'
            '// the GX viewport path so it beats bakes that never cross a frame boundary.\n'
            'void AssertMkwOffscreenScreenBypass();\n', '')
    # GameActivity.nativeGraphicsInfo: no Java code asks for it any more.
    drop_function('src/android/android_bridge.cpp', 'Java_io_github_dezer04_sb3utage_GameActivity_nativeGraphicsInfo')
    unused = drop_unused_functions()
    print('u_clean: %d files removed, %d disabled blocks dropped, %d unused functions removed, Basara 2 '
          'leftovers cleaned' % (len(DELETE), blocks, unused))


if __name__ == '__main__':
    main()
