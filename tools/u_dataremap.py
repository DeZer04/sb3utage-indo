#!/usr/bin/env python3
"""Map the runtime's literal Basara addresses (0x80xxxxxx outside the hook macros) to Utage.

Code addresses go through u_remap's function mapper (start or inside a function). Data addresses
(SDK globals in .data/.sdata/.bss) are found from the instructions that use them: every Basara
function the mapper pairs with a Utage one is aligned instruction by instruction, and each address
both sides load the same way (lis/addi pairs, r13/r2 SDA offsets) is a vote; the address with most
votes wins. Writes generated/u/literals.csv; nothing in runtime/src is changed (see --apply in
u_remap.py for hooks).

  python -I tools/u_dataremap.py
"""
import bisect
import csv
import difflib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import u_remap  # noqa: E402
from b_remap import HOOK  # noqa: E402

RT = ROOT / 'runtime' / 'src'
OUT = ROOT / 'generated' / 'u'
LIT = re.compile(r'0x(8[0-1][0-9A-Fa-f]{6})u?\b')
FUNC = re.compile(r'\bfunc_(8[0-1][0-9A-Fa-f]{6})\b')  # direct calls into translated code

SDA = {'b': (0x80667C80, 0x8066B100), 'u': (0x808FA520, 0x808FC1C0)}
# Known outright: the SDA bases themselves.
MANUAL = {0x80667C80: 0x808FA520, 0x8066B100: 0x808FC1C0}
# Blocks that moved as a whole (checked: every variable of the block found in Utage's code at the delta).
BLOCKS = [
    (0x80662AE8, 0x80662BA0, 0x291060, 'VI .sbss (IsInitialized..retraceCount)'),
    (0x805A6B80, 0x805A6CC0, 0x3E46C0, 'VI .bss (HorVer and tables)'),
]


def sext(v):
    return v - 0x10000 if v & 0x8000 else v


def data_refs(words, start, sda):
    """(instruction index, address) for each data address the instructions form."""
    r13, r2 = sda
    hi = {}
    out = []
    for i, w in enumerate(words):
        op, rd, ra, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 15 and ra == 0:                       # lis rD, imm
            hi[rd] = imm << 16
            continue
        if op in (14, 24) or 32 <= op <= 55:           # addi / ori / loads & stores
            base = None
            if ra == 13:
                base = r13
            elif ra == 2:
                base = r2
            elif ra in hi and op != 24:
                base = hi[ra]
            elif op == 24 and rd in hi:                 # ori rA, rS, imm: rS is in rd's slot
                out.append((i, (hi[rd] | imm) & 0xFFFFFFFF))
                continue
            if base is not None:
                a = (base + sext(imm)) & 0xFFFFFFFF
                if 0x80000000 <= a < 0x81800000:
                    out.append((i, a))
        if op == 18 or op == 16 or (op == 19 and (w >> 1) & 0x3FF in (16, 528)):
            hi.clear()                                  # a branch ends what we know
    return out


def main():
    apply = '--apply' in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    db = u_remap.load_dsy()
    b, u = u_remap.Dol(u_remap.B_DOL, u_remap.B_MAP), u_remap.Dol(u_remap.U_DOL, u_remap.U_MAP)
    bn, un = b.names(db), u.names(db)
    mapper = u_remap.Mapper(b, u, bn, un)
    btext = [(a, a + s) for _, a, s in b.text]

    # votes: Basara data address -> Counter(Utage address), from every confident function pair
    votes = defaultdict(Counter)
    pairs = 0
    # function pairs: the mapper's confident ones, plus every hook u_remap resolved (twins, manual)
    hook_pairs = {}
    hooks_csv = OUT / 'hooks.csv'
    if hooks_csv.exists():
        for r in csv.DictReader(hooks_csv.open()):
            if r['verdict'].startswith('resolved') and r['utage']:
                ba, ua = int(r['basara'], 16), int(r['utage'].split()[0], 16)
                if ba in b._index and ua in u._index:
                    hook_pairs[ba] = ua
    for fb in b.starts:
        if fb in hook_pairs:
            fu, score = hook_pairs[fb], 1.0
        else:
            fu, score, how = mapper.function(fb)
        if fu is None or score < 0.8:
            continue
        pairs += 1
        rb = data_refs(b.words(fb), fb, SDA['b'])
        ru = dict(data_refs(u.words(fu), fu, SDA['u']))
        if not rb or not ru:
            continue
        sm = difflib.SequenceMatcher(None, mapper.btok[fb], mapper.utok.get(fu) or [], autojunk=False)
        blocks = sm.get_matching_blocks()
        for i, ab in rb:
            for a0, b0, n in blocks:
                if a0 <= i < a0 + n:
                    au = ru.get(b0 + i - a0)
                    if au is not None:
                        votes[ab][au] += 1
                    break
    print('function pairs used: %d, data addresses with votes: %d' % (pairs, len(votes)))

    # a confident delta per voted address (uncontested), for the neighbour rule
    deltas = sorted((ab, c.most_common(1)[0][0] - ab) for ab, c in votes.items()
                    if len(c) == 1 or c.most_common(2)[1][1] * 2 < c.most_common(1)[0][1])

    def neighbour(ab):
        """An address no code formed, inside a block whose voted neighbours below and above (within
        2 KiB) moved by the same delta: it moved with them."""
        i = bisect.bisect_left(deltas, (ab, -1 << 40))
        lo = next((d for d in reversed(deltas[:i]) if ab - d[0] <= 0x800), None)
        hi = next((d for d in deltas[i:] if d[0] - ab <= 0x800), None)
        if lo and hi and lo[1] == hi[1]:
            return ab + lo[1], 'neighbours %08X/%08X' % (lo[0], hi[0])
        return None, 'no votes'

    hooked = set()
    rows = []
    for f in sorted(RT.rglob('*')):
        if f.suffix not in ('.cpp', '.h', '.hpp', '.inc'):
            continue
        for i, line in enumerate(f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(), 1):
            hook_spans = [m.span(3) for m in HOOK.finditer(line)]
            code = line.split('//')[0]
            for m in LIT.finditer(code):
                if any(s <= m.start(1) < e for s, e in hook_spans):
                    continue
                ab = int(m.group(1), 16)
                is_code = any(lo <= ab < hi for lo, hi in btext)
                block = next((x for x in BLOCKS if x[0] <= ab < x[1]), None)
                if ab in MANUAL:
                    au, kind, detail = MANUAL[ab], 'manual', 'SDA base'
                elif block:
                    au, kind, detail = ab + block[2], 'manual', block[3]
                elif ab < 0x80004000 or ab >= 0x81000000:
                    # OS low memory and MEM1's end: the same in every game
                    au, kind, detail = ab, 'fixed', 'lomem/mem1 end'
                elif is_code:
                    au, score, how = mapper.address(ab)
                    kind = 'code'
                    detail = how
                else:
                    c = votes.get(ab)
                    kind = 'data'
                    if c:
                        (au, n), *rest = c.most_common(2) + [(None, 0)]
                        second = rest[0][1] if rest else 0
                        detail = 'votes %d/%d' % (n, n + second)
                        if second and second * 2 >= n:
                            detail = 'contested ' + detail + ' cand %08X' % au
                            au = None
                    else:
                        au, detail = neighbour(ab)
                rows.append([f.relative_to(RT).as_posix(), i, '%08X' % ab, kind,
                             '%08X' % au if au is not None else '', detail, line.strip()[:110]])
    with (OUT / 'literals.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'line', 'basara', 'kind', 'utage', 'detail', 'source'])
        w.writerows(rows)
    # r13-relative offsets written as numbers: "r13 - 0x4ddcu", "gpr[13] - 0x52ccu", and constants
    # named k...Sda1Offset / k...OffsetFromR13. Basara address = Basara r13 - offset, mapped like any data
    # address; the Utage offset = Utage r13 - Utage address.
    def resolve_data(ab):
        block = next((x for x in BLOCKS if x[0] <= ab < x[1]), None)
        if block:
            return ab + block[2], block[3]
        c = votes.get(ab)
        if c:
            (au, n), *rest = c.most_common(2) + [(None, 0)]
            second = rest[0][1] if rest else 0
            if second and second * 2 >= n:
                return None, 'contested'
            return au, 'votes %d' % n
        return neighbour(ab)

    sda_forms = [re.compile(r'(?:\br13|gpr\[13\])\s*-\s*0x([0-9A-Fa-f]{3,4})u?\b'),
                 re.compile(r'\bconstexpr\s+uint32_t\s+k\w*(?:Sda1Offset|OffsetFromR13)\s*=\s*0x([0-9A-Fa-f]{3,4})u?\b')]
    sda_rows = []
    for f in sorted(RT.rglob('*')):
        if f.suffix not in ('.cpp', '.h', '.hpp', '.inc'):
            continue
        for i, line in enumerate(f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(), 1):
            code = line.split('//')[0]
            for form in sda_forms:
                for m in form.finditer(code):
                    off = int(m.group(1), 16)
                    ab = (SDA['b'][0] - off) & 0xFFFFFFFF
                    au, detail = resolve_data(ab)
                    new = (SDA['u'][0] - au) & 0xFFFFFFFF if au is not None else None
                    if new is not None and not (0 < new < 0x8000):
                        new, detail = None, 'outside r13 reach %08X' % au
                    sda_rows.append((f, i, m.group(1), new, ab, au, detail))
    with (OUT / 'sda_offsets.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'line', 'offset', 'basara', 'utage', 'new_offset', 'detail'])
        for f, i, off, new, ab, au, detail in sda_rows:
            w.writerow([f.relative_to(RT).as_posix(), i, off, '%08X' % ab, '%08X' % au if au is not None else '',
                        '%04X' % new if new is not None else '', detail])
    print('r13 offsets: %d uses, %d resolved' % (len(sda_rows), sum(1 for r in sda_rows if r[3] is not None)))
    if apply:
        by_file = defaultdict(list)
        for f, i, off, new, ab, au, detail in sda_rows:
            if new is not None:
                by_file[f].append((i, off, new))
        for f, items in by_file.items():
            lines = f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(keepends=True)
            for i, off, new in items:
                code, sep, comment = lines[i - 1].partition('//')
                txt = '%04X' % new if off.isupper() or not any(ch.isalpha() for ch in off) else '%04x' % new
                code = re.sub(r'(?<=0x)' + off + r'(?![0-9A-Fa-f])', txt, code, count=1)
                lines[i - 1] = code + sep + comment
            f.write_text(''.join(lines), encoding='utf-8', errors='surrogateescape')

    # func_<address> names: translated functions the runtime calls directly
    renames = defaultdict(list)
    for f in sorted(RT.rglob('*')):
        if f.suffix not in ('.cpp', '.h', '.hpp', '.inc'):
            continue
        text = f.read_text(encoding='utf-8', errors='surrogateescape')
        for ab in sorted({int(x, 16) for x in FUNC.findall(text)}):
            if ab in b._index:
                au, score, how = mapper.function(ab)
                if au is not None and 'inside' not in how:
                    renames[f].append((ab, au))
    print('func_ renames: %d' % sum(len(v) for v in renames.values()))
    if apply:
        for f, subs in renames.items():
            text = f.read_text(encoding='utf-8', errors='surrogateescape')
            for ab, au in subs:
                text = re.sub(r'\bfunc_%08X\b' % ab, 'func_%08X' % au, text, flags=re.I)
            f.write_text(text, encoding='utf-8', errors='surrogateescape')
        edits = defaultdict(dict)
        for r in rows:
            # code literals only at function starts ('+inside' ones are mostly NSMBW leftovers that point
            # into Basara code too, i.e. paths Basara never takes; review those by hand)
            if r[4] and r[4] != r[2] and (r[3] in ('data', 'manual') or (r[3] == 'code' and 'inside' not in r[5])):
                edits[RT / r[0]][int(r[1])] = edits[RT / r[0]].get(int(r[1]), []) + [(r[2], r[4])]
        moved = 0
        for f, by_line in edits.items():
            lines = f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(keepends=True)
            for ln, subs in by_line.items():
                line = lines[ln - 1]
                code, sep, comment = line.partition('//')
                for old, new in subs:
                    pat = re.compile(r'0x(' + old + r')(u?)(?![0-9A-Fa-f])', re.I)
                    def sub(m):
                        txt = new if m.group(1).isupper() or not any(c.isalpha() for c in m.group(1)) else new.lower()
                        return '0x' + txt + m.group(2)
                    code, n = pat.subn(sub, code)
                    moved += n
                lines[ln - 1] = code + sep + comment
            f.write_text(''.join(lines), encoding='utf-8', errors='surrogateescape')
        print('apply: %d literals moved' % moved)
    uniq = {(r[2], r[3], bool(r[4])) for r in rows}
    stat = Counter((k, ok) for _, k, ok in uniq)
    print('literals: %d uses, %d distinct; resolved: code %d/%d, data %d/%d -> %s' % (
        len(rows), len({r[2] for r in rows}), stat[('code', True)], stat[('code', True)] + stat[('code', False)],
        stat[('data', True)], stat[('data', True)] + stat[('data', False)], OUT / 'literals.csv'))


if __name__ == '__main__':
    main()
