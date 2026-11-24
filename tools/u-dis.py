#!/usr/bin/env python3
"""Disassemble a function of the Utage main.dol: python -I tools/u-dis.py [-b] START_ADDR [END_ADDR]
-b: Basara's main.dol instead (the port's source game), for side-by-side comparison.
Same as b-dis.py, for assets/utage; bl targets carry the SDK name when generated/u has one
(utage_sdk_names.tsv from u_remap.py, utage_dsy_names.tsv from Dolphin's signatures)."""
import sys
from pathlib import Path
from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, CS_MODE_PS
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import w1
BASARA = len(sys.argv) > 1 and sys.argv[1] == '-b'
if BASARA:
    del sys.argv[1]
d = (Path('F:/basara_work/wii/extracted/DATA/sys/main.dol') if BASARA
     else ROOT.joinpath('assets/utage/sys/main.dol')).read_bytes()
secs, _, _, _ = w1.parse_dol(d)
names = {}
for f in ('utage_dsy_names.tsv', 'utage_sdk_names.tsv'):
    p = ROOT / 'generated' / 'u' / f
    if p.exists() and not BASARA:
        for line in p.read_text().splitlines():
            a, b = line.split('\t')[:2]
            # either "ADDR\tname" or "name\tADDR"
            if all(c in '0123456789ABCDEFabcdef' for c in a) and len(a) == 8:
                names[int(a, 16)] = b
            else:
                for x in b.split()[0].split(','):
                    names.setdefault(int(x, 16), a)
a0 = int(sys.argv[1], 16)
a1 = int(sys.argv[2], 16) if len(sys.argv) > 2 else a0 + 0x200
# Gekko paired singles (ps_*, psq_*), otherwise decoded as AltiVec.
cs = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN | CS_MODE_PS)
R13, R2 = (0x80667C80, 0x8066B100) if BASARA else (0x808FA520, 0x808FC1C0)
hi = {}
for a in range(a0, a1, 4):
    w = w1.word(d, secs, a)
    if w is None: break
    ins = next(cs.disasm(w.to_bytes(4, 'big'), a), None)
    txt = '%s %s' % (ins.mnemonic, ins.op_str) if ins else '.long 0x%08X' % w
    note = ''
    op, rd, ra, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
    s = imm - 0x10000 if imm & 0x8000 else imm
    if op == 15 and ra == 0: hi[rd] = imm << 16
    if op in (32, 34, 36, 38, 40, 44, 48, 50, 52, 54) or op in (33, 35, 37, 39, 41, 45):
        if ra == 13: note = '  ; SDA r13 -> %08X' % ((R13 + s) & 0xFFFFFFFF)
        elif ra == 2: note = '  ; SDA2 r2 -> %08X' % ((R2 + s) & 0xFFFFFFFF)
        elif ra in hi: note = '  ; %08X' % ((hi[ra] + s) & 0xFFFFFFFF)
    if op == 14 and ra in hi: note = '  ; %08X' % ((hi[ra] + s) & 0xFFFFFFFF)
    if op == 14 and ra == 13: note = '  ; &SDA %08X' % ((R13 + s) & 0xFFFFFFFF)
    if op == 14 and ra == 2: note = '  ; &SDA2 %08X' % ((R2 + s) & 0xFFFFFFFF)
    if op == 18:
        t = (a + ((w & 0x3FFFFFC) - (0x4000000 if w & 0x2000000 else 0))) & 0xFFFFFFFF
        if t in names: note = '  ; %s' % names[t]
    print('%08X  %s%s' % (a, txt, note))
