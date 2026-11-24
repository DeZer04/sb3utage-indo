#!/usr/bin/env python3
"""Finds the file-local functions and namespace-scope variables in runtime/src that nothing uses: the
compiler drops them before the linker sees them, so tools/u_unused.py cannot. Runs clang -fsyntax-only
with only the unused warnings on, over the runtime's compile commands from an Android build tree, and
prints "<file under runtime/> <name> static" lines for tools/u_clean_unused.txt.

  python -I tools/u_unused_static.py [BUILD_DIR] [--append]
"""
import re
import subprocess
import tempfile
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RT = ROOT / 'runtime'
NINJA = ROOT / 'third_party' / 'ninja' / 'ninja.exe'
OUT = ROOT / 'tools' / 'u_clean_unused.txt'
WARN = re.compile(r"^(.*?):(\d+):\d+: warning: unused (function|variable|const variable) '([A-Za-z_]\w*)'")


def commands(build_dir):
    out = subprocess.run([str(NINJA), '-C', str(build_dir), '-t', 'commands', 'WiiCompiled'],
                         capture_output=True, text=True).stdout.split('\n')
    picked = []
    for line in out:
        if 'clang++' not in line or ' -c ' not in line:
            continue
        src = line.rsplit(' -c ', 1)[1].strip().strip('"')
        if 'mkw_runtime_common' not in line and not src.replace('\\', '/').startswith(str(RT / 'src').replace('\\', '/')):
            continue
        cmd = re.sub(r' -o \S+', '', line.rsplit(' -c ', 1)[0])
        cmd = re.sub(r' -MD -MT \S+ -MF \S+', '', cmd)
        cmd = re.sub(r' -w\b', '', cmd)
        cmd = re.sub(r' -flto=\S+', '', cmd)
        cmd = re.sub(r' -fprofile-use=\S+', '', cmd)
        if src.endswith('cmake_pch.hxx.cxx'):
            continue
        # The precompiled header goes stale with every header change: include its source instead.
        cmd = re.sub(r' -Winvalid-pch', '', cmd)
        # A copy, away from its .pch: clang would pick the stale .pch up next to the original.
        def plain_header(m):
            src_header = Path(m.group(1))
            copy = Path(tempfile.gettempdir()) / ('u_unused_' + src_header.parent.name + '_' + src_header.name)
            copy.write_text(src_header.read_text(encoding='utf-8'), encoding='utf-8')
            return ' -include ' + str(copy).replace('\\', '/')
        cmd = re.sub(r' -Xclang -include-pch -Xclang \S+ -Xclang -include -Xclang (\S+)', plain_header, cmd)
        cmd += ' -fsyntax-only -Wno-everything -Wunused-function -Wunused-variable -Wunused-const-variable -Wunused-template'
        # clang only reports unused file-scope declarations of the main file: a unity batch's sources are
        # includes to it, so each source is checked on its own (with the batch's flags).
        sources = [src]
        if '/Unity/' in src.replace('\\', '/'):
            unity = Path(src) if Path(src).is_absolute() else Path(build_dir) / src
            sources = re.findall(r'#include "([^"]+\.cpp)"', unity.read_text(encoding='utf-8', errors='replace'))
        for source in sources:
            if Path(source).exists():  # a batch listing a source removed since it was generated
                picked.append((cmd + ' -c ' + source, build_dir))
    return picked


def run(job):
    cmd, cwd = job
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, encoding='utf-8', errors='replace').stderr


def main():
    build_dir = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else \
        ROOT / 'generated' / 'android-build-dev'
    jobs = commands(build_dir)
    if not jobs:
        sys.exit('no runtime compile commands in %s' % build_dir)
    found = set()
    errors = 0
    with ThreadPoolExecutor(6) as pool:
        for err in pool.map(run, jobs):
            errors += err.count(' error: ')
            for line in err.split('\n'):
                m = WARN.match(line.strip())
                if not m:
                    continue
                path = Path(m.group(1)).resolve()
                try:
                    rel = path.relative_to(RT)
                except ValueError:
                    continue
                if rel.parts[0] != 'src' or 'third_party' in rel.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace').split('\n')
                decl = text[int(m.group(2)) - 1]
                if m.group(3) == 'variable' and decl[:1].isspace():
                    continue  # a local variable: left to the code
                # Named again in the file (another platform's #ifdef branch, say): kept.
                uses = [l for l in text if re.search(r'\b' + re.escape(m.group(4)) + r'\b', l)
                        and not l.strip().startswith('//')]
                if len(uses) > 1:
                    continue
                found.add((str(rel).replace('\\', '/'), m.group(4), m.group(3)))
    for rel, name, kind in sorted(found):
        print('%s %s static    // unused %s' % (rel, name, kind))
    print('%d unused file-local functions and variables (%d compile commands, %d errors)' % (len(found), len(jobs), errors),
          file=sys.stderr)
    if errors:
        sys.exit('the check did not compile cleanly: fix that first')
    if '--append' in sys.argv and found:
        have = OUT.read_text(encoding='utf-8') if OUT.exists() else ''
        add = ''.join('%s %s static\n' % (rel, name) for rel, name, kind in sorted(found)
                      if '%s %s static\n' % (rel, name) not in have)
        OUT.write_text(have + add, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
