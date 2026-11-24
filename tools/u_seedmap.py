#!/usr/bin/env python3
"""More function starts for config/utage/MAP.txt: what the recursive translation can't reach.

w1.py --seed takes bl targets and data pointers aimed at a prologue. Functions reached only through
a pointer and without a prologue (C++ vtable entries that are leaf functions, callbacks loaded with
lis/addi and called through ctr) stay out, and the game later jumps into untranslated code. Added here:
  - data words pointing into code right after a function boundary (blr, rfi, or padding before it),
    except runs that point inside one known function (switch jump tables)
  - addresses built in code by lis + addi/ori pairs, with the same boundary test
  - --add ADDR[,ADDR...]: addresses found by hand (a crash log's "not translated" target)
Writes the merged map back.

  python -I tools/u_seedmap.py [--add 805C2300,...]
"""
import argparse
import bisect
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import w1  # noqa: E402

DOL = ROOT / 'assets' / 'utage' / 'sys' / 'main.dol'
MAP = ROOT / 'config' / 'utage' / 'MAP.txt'
BLR, RFI, BCTR = 0x4E800020, 0x4C000064, 0x4E800420
# _ctors and _dtors (the runtime's "Loaded _ctors ... @" lines): lists of function pointers
CTORS = [(0x808335E0, 0x808335E0 + 2912), (0x80834140, 0x80834140 + 32)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--add', default='')
    a = ap.parse_args()
    data = DOL.read_bytes()
    secs, _, _, _ = w1.parse_dol(data)
    text = [(o, base, s) for o, base, s, t in secs if t]
    words = {}
    for o, base, s in text:
        for i, w in enumerate(struct.unpack_from('>%dI' % (s // 4), data, o)):
            words[base + 4 * i] = w

    def boundary(x, weak=True):
        """x starts a function: the word before ends one (blr, rfi) or is padding (strong), or is a
        plain b (weak: switch case labels sit there too); x itself isn't padding. Splitting a function at
        a label is safe here anyway: the translator treats a jump to a known start as a tail call."""
        if x % 4 or x not in words or words[x] == 0:
            return False
        p = words.get(x - 4)
        if p is None:
            return True
        return p in (BLR, RFI, BCTR, 0) or (weak and p >> 26 == 18 and (p & 3) == 0)

    old = {int(l.split()[0], 16) for l in MAP.read_text().splitlines() if l.strip()}
    olds = sorted(old)

    def owner(x):
        i = bisect.bisect_right(olds, x) - 1
        return olds[i] if i >= 0 else None

    found = set()
    for o, base, s, t in secs:
        if t:
            continue
        vals = struct.unpack_from('>%dI' % (s // 4), data, o)
        i = 0
        while i < len(vals):
            # a run of consecutive words that point into code
            j = i
            while j < len(vals) and vals[j] in words:
                j += 1
            if j == i:
                i += 1
                continue
            run = vals[i:j]
            inside = [owner(v) for v in run if v not in old]
            # a jump table: every entry inside one known function (case labels) and none a known start;
            # a vtable mixes known functions in. Never the static constructor/destructor lists.
            ctors = any(lo <= base + 4 * i < hi for lo, hi in CTORS)
            table = (not ctors and len(inside) >= 2 and len(set(inside)) == 1
                     and not any(v in old for v in run))
            for v in run:
                # constructor list entries always start functions; in a jump-table-looking run (a vtable
                # of small functions looks the same) only entries right after a blr do
                if ctors or boundary(v, weak=not table):
                    found.add(v)
            i = j
    hi = {}
    for pc in sorted(words):
        w = words[pc]
        op, rd, ra, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 15 and ra == 0:
            hi[rd] = imm << 16
            continue
        v = None
        if op == 14 and ra in hi:
            v = (hi[ra] + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
        elif op == 24 and rd in hi:
            v = hi[rd] | imm
        if v is not None and boundary(v):
            found.add(v)
        if op in (16, 18) or w in (BLR, RFI):
            hi.clear()
    manual = {int(x, 16) for x in a.add.replace(' ', '').split(',') if x}
    new = (found | manual) - old
    merged = sorted(old | found | manual)
    MAP.write_text(''.join('%08X sub_%08X\n' % (x, x) for x in merged), encoding='ascii')
    print('map: %d starts before, %d pointer-reached + %d by hand, %d new -> %d' % (
        len(old), len(found), len(manual), len(new), len(merged)))
    print('0x805C2300 now in map:', 0x805C2300 in merged)


if __name__ == '__main__':
    main()
