#!/usr/bin/env python3
"""Lists the runtime functions nothing uses, for tools/u_clean.py (tools/u_clean_unused.txt).

A function is listed only when both hold:
1. the linker dropped it: a non-LTO Android build with -ffunction-sections, linked with
   -Wl,--gc-sections -Wl,--print-gc-sections and a version script exporting only the real entry points
   ({ global: Java_*; JNI_OnLoad; JNI_OnUnload; SDL_main; main; ANativeActivity_onCreate; local: *; }):
   without it libmain.so exports every function and the linker keeps them all (tools/b-android.ps1
   -BuildDir generated\\android-build-dev -Extra '-DMKW_PGO=off','-DMKW_THINLTO=OFF',
   '-DCMAKE_SHARED_LINKER_FLAGS=-Wl,--gc-sections -Wl,--print-gc-sections -Wl,--version-script=<map>'),
   whose build.log is BUILD_LOG;
2. its name appears nowhere else: not in runtime/src or include (any platform, so PC-only callers keep
   it), aurora, the app, or the translated code; only in its own definition, declarations and comments.
Only functions defined once in runtime/src are considered; templates and operators are left alone.

  python -I tools/u_unused.py BUILD_LOG [--write]
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RT = ROOT / 'runtime'
CXXFILT = Path(r'E:\Installers\andr_1\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-cxxfilt.exe')
OUT = ROOT / 'tools' / 'u_clean_unused.txt'
DEF_TAIL = r'\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?\{'
DECL_TAIL = r'\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?;'


KEYWORDS = {'else', 'return', 'case', 'do', 'goto', 'throw', 'delete', 'new', 'co_return', 'sizeof', 'decltype'}


def is_declaration(before):
    """A declaration names a type before the function ("void Foo(", "static int* Foo("); a call has
    nothing, an object, an operator or a keyword there."""
    m = re.search(r'([A-Za-z_][\w:<>]*)[ \t\*&]+$', before)
    return bool(m) and m.group(1) not in KEYWORDS and not re.search(r'(\.|->)\s*$', before)


def corpus_files():
    globs = [(RT / 'src', '*.cpp'), (RT / 'src', '*.h'), (RT / 'include', '*.h'), (RT / 'disc', '*.cpp'),
             (RT / 'disc', '*.h'), (ROOT / 'aurora', '*.cpp'), (ROOT / 'aurora', '*.hpp'), (ROOT / 'aurora', '*.h'),
             (ROOT / 'app' / 'src', '*.java'), (ROOT / 'generated' / 'build_shards', '*.cpp')]
    for base, pattern in globs:
        for p in base.rglob(pattern):
            if 'third_party' not in p.parts:
                yield p
    yield from (ROOT / 'generated').glob('*.cpp')


def main():
    log = Path(sys.argv[1])
    mangled = set()
    for line in log.read_text(encoding='utf-8', errors='replace').split('\n'):
        m = re.search(r"removing unused section '?([^'(]*):\(\.text\.([^)]+)\)", line)
        if m and ('mkw_runtime_common' in m.group(1) or 'WiiCompiled.dir' in m.group(1)):
            mangled.add(m.group(2))
    names = sorted(mangled)
    demangled = subprocess.run([str(CXXFILT)], input='\n'.join(names), capture_output=True, text=True).stdout.split('\n')
    cands = {}
    skipped = {'template/operator': 0, 'named elsewhere': 0, 'not defined once in runtime/src': 0}
    for plain in demangled:
        qual = plain.split('(')[0] if '(' in plain else ''
        if not qual or '<' in qual or 'operator' in qual or qual.startswith(('std::', 'thread-local', 'typeinfo', 'vtable')):
            skipped['template/operator'] += bool(plain)
            continue
        name = qual.split('::')[-1]
        if re.match(r'^[A-Za-z_]\w*$', name):
            cands.setdefault(name, plain)
    if not cands:
        sys.exit('no dropped runtime functions in %s' % log)
    pattern = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, cands), key=len, reverse=True)) + r')\b')
    defs = {n: [] for n in cands}
    other = {n: 0 for n in cands}
    for p in corpus_files():
        t = p.read_text(encoding='utf-8', errors='replace')
        in_src = p.suffix == '.cpp' and p.is_relative_to(RT / 'src')
        for m in pattern.finditer(t):
            name = m.group(1)
            line_start = t.rfind('\n', 0, m.start()) + 1
            before = t[line_start:m.start()]
            rest = t[m.end():m.end() + 600]
            if '//' in before or before.lstrip().startswith(('*', '/*')):
                continue  # a comment
            if re.match(DECL_TAIL, rest) and is_declaration(before):
                continue  # a declaration
            if re.match(DEF_TAIL, rest) and not re.search(r'[=(,!&|?:]\s*$|return\s*$|\b(if|while|for|switch)\b', before):
                if in_src:
                    defs[name].append(p)
                else:
                    other[name] += 1
                continue
            other[name] += 1
    picked = []
    for name, plain in sorted(cands.items()):
        if len(defs[name]) != 1:
            skipped['not defined once in runtime/src'] += 1
        elif other[name]:
            skipped['named elsewhere'] += 1
        else:
            picked.append((str(defs[name][0].relative_to(RT)).replace('\\', '/'), name, plain))
    for rel, name, plain in picked:
        print('%s %s    // %s' % (rel, name, plain[:120]))
    print('%d unused of %d dropped (%s)' % (len(picked), len(names), ', '.join('%s %d' % kv for kv in skipped.items())),
          file=sys.stderr)
    if '--write' in sys.argv:
        OUT.write_text('# Runtime functions nothing uses (tools/u_unused.py), removed by tools/u_clean.py.\n'
                       '# <file under runtime/> <function name>\n' +
                       ''.join('%s %s\n' % (rel, name) for rel, name, plain in picked), encoding='utf-8', newline='\n')
        print('written %s' % OUT, file=sys.stderr)


if __name__ == '__main__':
    main()
