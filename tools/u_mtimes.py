#!/usr/bin/env python3
"""Keep modification times across tools/u_port.sh: `save` records a hash and mtime for every file
under runtime/src and runtime/include, `restore` puts the old mtime back on each file whose content
came out identical. Regenerating the sources then rebuilds only the objects of files that changed."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / 'runtime' / 'src', ROOT / 'runtime' / 'include']
STATE = ROOT / 'generated' / 'u' / 'mtimes.json'


def files():
    for d in DIRS:
        for f in d.rglob('*'):
            if f.is_file():
                yield f


def digest(f):
    return hashlib.sha1(f.read_bytes()).hexdigest()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'save':
        state = {str(f.relative_to(ROOT)): [digest(f), f.stat().st_mtime_ns] for f in files()}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding='utf-8')
        print('u_mtimes: saved %d' % len(state))
    elif mode == 'restore':
        if not STATE.exists():
            sys.exit('u_mtimes: nothing saved')
        state = json.loads(STATE.read_text(encoding='utf-8'))
        kept = changed = 0
        for f in files():
            old = state.get(str(f.relative_to(ROOT)))
            if old and old[0] == digest(f):
                os.utime(f, ns=(old[1], old[1]))
                kept += 1
            else:
                changed += 1
        print('u_mtimes: %d unchanged (old mtime kept), %d changed' % (kept, changed))
    else:
        sys.exit('usage: u_mtimes.py save|restore')


if __name__ == '__main__':
    main()
