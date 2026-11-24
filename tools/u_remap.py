#!/usr/bin/env python3
"""Move the runtime's Basara 2 Heroes hooks to Sengoku Basara 3 Utage (S3HJ08) addresses.

Like b_remap.py (NSMBW -> Basara), two ways to find a hooked function in the other game:
1. By SDK name: both main.dols are matched against Dolphin's totaldb.dsy (checksum + size).
2. By body: a Basara function whose whole body (Dolphin's masked checksum over its full length) occurs
   exactly once among Utage's functions, for the hooks with no SDK name.
Writes generated/u/hooks.csv (one row per hook) and generated/u/utage_sdk_names.tsv; --apply
rewrites resolved addresses in runtime/src and wraps the rest in "#if 0".

  python -I tools/u_remap.py [--apply]
"""
import argparse
import bisect
import difflib
import csv
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import w1  # noqa: E402
from b_remap import HOOK, checksum_step, statement_end  # noqa: E402

DSY = Path('F:/utage/emulator/Dolphin-x64/Sys/totaldb.dsy')
B_DOL = Path('F:/basara_work/wii/extracted/DATA/sys/main.dol')
B_MAP = ROOT / 'config' / 'basara' / 'MAP.txt'
U_DOL = ROOT / 'assets' / 'utage' / 'sys' / 'main.dol'
U_MAP = ROOT / 'generated' / 'u' / 'utage_functions.txt'  # the translator's function starts (metadata.json)
RT = ROOT / 'runtime' / 'src'
OUT = ROOT / 'generated' / 'u'

# Found by hand (raw instruction sequences, SDK library order): Basara address -> Utage address.
MANUAL = {
    0x8039C5A0: 0x8082DA50,   # debugger trap stub "tw 31,r0,r0; blr" (first of four)
    0x8035AD04: 0x805B96C0,   # __OSSetInterruptHandler (same rlwinm; 0x805BF860 is the exception one)
    0x803A1C5C: 0x805A64D0,   # IOS_Read (unique 8-instruction match, after IOS_ReadAsync 0x805A63D0)
    0x803A1E64: 0x805A66E0,   # IOS_Write (after IOS_WriteAsync 0x805A65E0, same spacing as Basara)
    0x8036DE94: 0x805CEC30,   # VISetPreRetraceCallback (VI library; its r13 slot moved by the VI block delta)
    0x8036DED8: 0x805CEC80,   # VISetPostRetraceCallback
    0x8039779C: 0x805CA050,   # SIInit: calls SISetSamplingRate (0x805CA9A0) and writes SICOMCSR 0xCD006434
}


def load_dsy():
    b = DSY.read_bytes()
    n = struct.unpack_from('<I', b, 0)[0]
    db = defaultdict(set)
    for i in range(n):
        ck, size, name = struct.unpack_from('<II128s', b, 4 + 136 * i)
        db[(ck, size)].add(name.split(b'\0')[0].decode('ascii', 'replace').split('\t')[0].strip())
    return db


class Dol:
    """A main.dol with function starts: each function runs to the next start (or its section end)."""

    def __init__(self, dol, starts_file):
        self.data = dol.read_bytes()
        secs, self.entry, _, _ = w1.parse_dol(self.data)
        self.text = [(o, a, s) for o, a, s, t in secs if t]
        self.starts = sorted(int(l.split()[0], 16) for l in starts_file.read_text().splitlines() if l.strip())

    def words(self, start):
        """The function's instruction words."""
        seg = next(((o, a, s) for o, a, s in self.text if a <= start < a + s), None)
        if seg is None:
            return []
        o, a, s = seg
        i = bisect.bisect_right(self.starts, start)
        nxt = self.starts[i] if i < len(self.starts) else a + s
        limit = min(nxt, a + s, start + 0x8000)
        p = o + start - a
        return list(struct.unpack_from('>%dI' % ((limit - start) // 4), self.data, p))

    @property
    def _index(self):
        if not hasattr(self, '_ix'):
            self._ix = set(self.starts)
        return self._ix

    def names(self, db):
        """SDK name -> addresses (Dolphin's rule: the first prefix whose checksum and size match)."""
        out = defaultdict(set)
        for start in self.starts:
            sm = 0
            for k, w in enumerate(self.words(start)):
                sm = checksum_step(sm, w)
                for nm in db.get((sm, 4 * (k + 1)), ()):
                    out[nm].add(start)
        return out

    def bodies(self):
        """Full-length masked checksum -> starts."""
        out = defaultdict(list)
        for start in self.starts:
            ws = self.words(start)
            if len(ws) < 4:
                continue
            sm = 0
            for w in ws:
                sm = checksum_step(sm, w)
            out[(sm, len(ws))].append(start)
        return out


def token(w):
    """An instruction without its registers and immediates (the part Dolphin's checksum keeps)."""
    return checksum_step(0, w) ^ 0  # the step's xor term: op | op2 | op3 (seed 0)


def raw(w):
    """An instruction with what moves between games masked: branch displacements, SDA (r2/r13)
    offsets and the high half of RAM addresses. Register numbers and other constants stay, so tiny
    look-alike setters (GXSetDither / GXSetZCompLoc...) can be told apart."""
    op, ra = w >> 26, (w >> 16) & 31
    if op == 18:
        return w & 0xFC000003
    if op == 16:
        return w & 0xFFFF0003
    if op == 15 and ra == 0 and 0x8000 <= (w & 0xFFFF) < 0x8180:
        return w & 0xFFFF0000
    if (op == 14 or 32 <= op <= 55) and ra in (2, 13):
        return w & 0xFFFF0000
    return w


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


class Mapper:
    """Basara function -> Utage function: unique SDK names and unique whole bodies are anchors; the
    rest is the most similar Utage function between the anchors around it (libraries keep their order)."""

    def __init__(self, b, u, bn, un):
        self.b, self.u = b, u
        self.btok = {x: [token(w) for w in b.words(x)] for x in b.starts}
        self.utok = {x: [token(w) for w in u.words(x)] for x in u.starts}
        self.braw = {x: [raw(w) for w in b.words(x)] for x in b.starts}
        self.uraw = {x: [raw(w) for w in u.words(x)] for x in u.starts}
        anchors = {}
        for nm, ba in bn.items():
            ua = un.get(nm, ())
            if len(ba) == 1 and len(ua) == 1:
                anchors[next(iter(ba))] = next(iter(ua))
        bb, ub = b.bodies(), u.bodies()
        for key, bl in bb.items():
            ul = ub.get(key, [])
            if len(bl) == 1 and len(ul) == 1 and key[1] >= 8:
                anchors.setdefault(bl[0], ul[0])
        # keep anchors whose order agrees with their neighbours (drop crossings)
        items = sorted(anchors.items())
        keep, prev = [], 0
        for i, (ba, ua) in enumerate(items):
            nxt = items[i + 1][1] if i + 1 < len(items) else 0xFFFFFFFF
            if prev < ua < nxt or (i + 1 < len(items) and items[i + 1][1] < prev):
                keep.append((ba, ua))
                prev = ua
        self.anchors = dict(keep)
        self.akeys = sorted(self.anchors)
        self.bcalls = {x: self._calls(b, x) for x in b.starts}
        self.ucalls = {x: self._calls(u, x) for x in u.starts}
        self.bcallers, self.ucallers = defaultdict(set), defaultdict(set)
        for x, cs in self.bcalls.items():
            for c in cs:
                self.bcallers[c].add(x)
        for x, cs in self.ucalls.items():
            for c in cs:
                self.ucallers[c].add(x)
        self.matched = {}
        self._grow()

    @staticmethod
    def _calls(dol, x):
        """Function starts the function at x calls (bl)."""
        out = set()
        for k, w in enumerate(dol.words(x)):
            if w >> 26 == 18 and (w & 3) == 1:
                t = (x + 4 * k + ((w & 0x03FFFFFC) - (0x04000000 if w & 0x02000000 else 0))) & 0xFFFFFFFF
                if t in dol._index:
                    out.add(t)
        return out

    # The SDK and the libraries beside it in Basara: where a match can grow from the call graph.
    PROPAGATE = (0x80340000, 0x80430000)

    def _grow(self):
        """Confident similarity matches, then the call graph: a function whose mapped callers call one
        Utage function, or whose mapped callees are called by one, maps there when its body agrees."""
        used = set(self.anchors.values())
        for ba in self.b.starts:
            if ba in self.anchors or not (self.PROPAGATE[0] <= ba < self.PROPAGATE[1]):
                continue
            x, score, how = self._similar(ba)
            if x is not None and score >= 0.85 and x not in used:
                self.matched[ba] = (x, score, how)
                used.add(x)
        for _ in range(8):
            grew = 0
            known = {k: v for k, v in self.anchors.items()}
            known.update({k: v[0] for k, v in self.matched.items()})
            for ba in self.b.starts:
                if ba in known or not (self.PROPAGATE[0] <= ba < self.PROPAGATE[1]):
                    continue
                callees = {known[g] for g in self.bcalls[ba] if g in known}
                callers = {known[h] for h in self.bcallers[ba] if h in known}
                cands = None
                for h in callers:
                    cands = set(self.ucalls[h]) if cands is None else cands & self.ucalls[h]
                if cands is not None and not cands:
                    cands = {x for h in callers for x in self.ucalls[h]}
                if callees:
                    by_callee = {x for c in callees for x in self.ucallers[c]}
                    cands = by_callee if cands is None else (cands & by_callee or cands)
                if not cands:
                    continue
                cands -= used
                if not cands or len(cands) > 60:
                    continue
                want = self.btok[ba]
                scored = []
                for x in cands:
                    sim = similarity(want, self.utok.get(x) or [])
                    if callees:
                        sim = 0.6 * sim + 0.4 * len(self.ucalls[x] & callees) / len(callees)
                    scored.append((sim, x))
                scored.sort(reverse=True)
                best, x = scored[0]
                second = scored[1][0] if len(scored) > 1 else 0.0
                if best >= 0.5 and best - second >= 0.08:
                    self.matched[ba] = (x, best, 'callgraph')
                    used.add(x)
                    known[ba] = x
                    grew += 1
            if not grew:
                break

    def function(self, ba, among=None, minimum=0.75):
        """(Utage start, score, how) for the Basara function at ba, or (None, best score, why)."""
        if ba in self.anchors:
            return self.anchors[ba], 1.0, 'anchor'
        if ba in self.matched and among is None:
            return self.matched[ba]
        return self._similar(ba, among, minimum)

    def _similar(self, ba, among=None, minimum=0.75):
        i = bisect.bisect_left(self.akeys, ba)
        lo = self.anchors[self.akeys[i - 1]] if i > 0 else 0
        hi = self.anchors[self.akeys[i]] if i < len(self.akeys) else 0xFFFFFFFF
        cands = among if among else [x for x in self.u.starts[bisect.bisect_right(self.u.starts, lo):
                                                                bisect.bisect_left(self.u.starts, hi)]]
        if not cands or len(cands) > 400:
            return None, 0.0, 'range %d' % len(cands)
        want = self.btok.get(ba) or [token(w) for w in self.b.words(ba)]
        scored = sorted(((similarity(want, self.utok.get(x) or []), x) for x in cands), reverse=True)
        best, x = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best >= minimum and best - second >= 0.05:
            return x, best, 'similar'
        if best >= 0.6 and best - second >= 0.25:
            return x, best, 'similar (clear lead)'
        if best >= minimum or best - second < 0.05:
            # a tie on the instruction kinds: compare the instructions themselves
            wraw = self.braw.get(ba) or [raw(w) for w in self.b.words(ba)]
            tied = [x for sc, x in scored if best - sc < 0.05]
            rs = sorted(((similarity(wraw, self.uraw.get(x) or []), x) for x in tied), reverse=True)
            lead = rs[0][0] - (rs[1][0] if len(rs) > 1 else 0.0)
            if (rs[0][0] >= 0.8 and lead >= 0.03) or (rs[0][0] >= 0.6 and lead >= 0.25):
                return rs[0][1], rs[0][0], 'similar+raw'
            return None, best, 'weak %.2f/%.2f raw %.2f/%.2f' % (best, second, rs[0][0], rs[1][0] if len(rs) > 1 else 0)
        return None, best, 'weak %.2f/%.2f' % (best, second)

    def address(self, ba):
        """Any Basara code address (function start or inside one) -> Utage address, score, how."""
        i = bisect.bisect_right(self.b.starts, ba) - 1
        if i < 0:
            return None, 0.0, 'before code'
        fb = self.b.starts[i]
        fu, score, how = self.function(fb)
        if fu is None or fb == ba:
            return fu, score, how
        # inside a function: the matching instruction of the aligned bodies
        k = (ba - fb) // 4
        sm = difflib.SequenceMatcher(None, self.btok[fb], self.utok.get(fu) or [], autojunk=False)
        for a0, b0, n in sm.get_matching_blocks():
            if a0 <= k < a0 + n:
                return fu + 4 * (b0 + k - a0), score, how + '+inside'
        return None, score, 'inside: no aligned instruction'


def inventory():
    rows = []
    for f in sorted(RT.rglob('*')):
        if f.suffix not in ('.cpp', '.h', '.hpp', '.inc'):
            continue
        depth = []
        for i, line in enumerate(f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(), 1):
            s = line.strip()
            if s.startswith('#if'):
                depth.append(s.startswith('#if 0') or bool(depth and depth[-1]))
                continue
            if s.startswith('#endif'):
                if depth:
                    depth.pop()
                continue
            if s.startswith('#else') and depth:
                depth[-1] = not depth[-1] if not (len(depth) > 1 and depth[-2]) else True
                continue
            for m in HOOK.finditer(line):
                rows.append((f, i, m.group(1), int(m.group(3), 16), bool(depth and depth[-1])))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    db = load_dsy()
    b, u = Dol(B_DOL, B_MAP), Dol(U_DOL, U_MAP)
    bn, un = b.names(db), u.names(db)
    b_by_addr = defaultdict(set)
    for nm, addrs in bn.items():
        for x in addrs:
            b_by_addr[x].add(nm)
    print('SDK names: Basara %d, Utage %d, shared %d' % (len(bn), len(un), len(set(bn) & set(un))))
    (OUT / 'utage_sdk_names.tsv').write_text(
        ''.join('%s\t%s\n' % (n, ','.join('%08X' % x for x in sorted(v))) for n, v in sorted(un.items())))
    mapper = Mapper(b, u, bn, un)
    print('anchors: %d' % len(mapper.anchors))

    stats = defaultdict(int)
    verdicts = {}
    with (OUT / 'hooks.csv').open('w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['file', 'line', 'macro', 'basara', 'disabled', 'names', 'verdict', 'utage'])
        for f, ln, macro, addr, disabled in inventory():
            names = sorted(b_by_addr.get(addr, ()))
            cand = sorted({x for nm in names for x in un.get(nm, ())})
            if addr in MANUAL:
                new, score, how = MANUAL[addr], 1.0, 'manual'
            elif len(cand) == 1:
                new, score, how = cand[0], 1.0, 'name'
            elif cand:
                new, score, how = mapper.function(addr, among=cand, minimum=0.6)
                how = 'name+' + how
                if new is None and len(names) == 1:
                    # look-alike twins (one SDK name on several functions): the same position among the
                    # twins between the anchors around the function, i.e. within the same library
                    i = bisect.bisect_left(mapper.akeys, addr)
                    blo = mapper.akeys[i - 1] if i > 0 else 0
                    bhi = mapper.akeys[i] if i < len(mapper.akeys) else 0xFFFFFFFF
                    ulo, uhi = mapper.anchors.get(blo, 0), mapper.anchors.get(bhi, 0xFFFFFFFF)
                    bl = sorted(x for x in bn[names[0]] if blo < x < bhi)
                    ul = sorted(x for x in un[names[0]] if ulo < x < uhi)
                    if bl and len(bl) == len(ul) and addr in bl:
                        new, score, how = ul[bl.index(addr)], 1.0, 'name twin #%d/%d' % (bl.index(addr) + 1, len(bl))
            else:
                new, score, how = mapper.address(addr)
            v = ('resolved' if new is not None else 'unresolved') + ' ' + how
            if not disabled:  # hooks already off in the source stay as they are
                verdicts[(f, ln, addr)] = (v, new)
            stats[('off-' if disabled else '') + v.split()[0]] += 1
            wr.writerow([f.relative_to(RT).as_posix(), ln, macro, '%08X' % addr, int(disabled), ';'.join(names[:3]), v,
                         '%08X %.2f' % (new, score) if new is not None else '%.2f' % score])
    print('hooks:', dict(sorted(stats.items())), '->', OUT / 'hooks.csv')
    if not a.apply:
        return

    by_file = defaultdict(list)
    for (f, ln, addr), (v, new) in verdicts.items():
        by_file[f].append((ln, addr, new))
    changed = defaultdict(int)
    for f, items in by_file.items():
        lines = f.read_text(encoding='utf-8', errors='surrogateescape').splitlines(keepends=True)
        disable = []
        for ln, addr, new in items:
            i = ln - 1
            for m in HOOK.finditer(lines[i]):
                if int(m.group(3), 16) != addr:
                    continue
                if new is not None:
                    tok = '%08X' % new
                    if m.group(3) == m.group(3).lower() and any(c.isalpha() for c in m.group(3)):
                        tok = tok.lower()
                    # every spelling of the address on the line: GX_FATAL_STUB(addr) + OVERRIDE(addr, gx_stub_addr)
                    # (inside names only for GX_FATAL_STUB's generated gx_stub_<addr>)
                    old = re.compile('(?:(?<![0-9A-Za-z_])|(?<=0x)|(?<=0X)|(?<=gx_stub_))' + m.group(3) + '(?![0-9A-Fa-f])', re.I)
                    if not old.search(lines[i]):
                        sys.exit('u_remap: %s:%d: address %s not rewritten' % (f.name, ln, m.group(3)))
                    lines[i] = old.sub(lambda mm: tok if mm.group(0).isupper() or not any(c.isalpha() for c in mm.group(0)) else tok.lower(), lines[i])
                    changed['moved'] += 1
                else:
                    disable.append((i, statement_end(lines, i, m.start())))
                break
        for s, e in sorted(set(disable), reverse=True):
            ind = re.match(r'\s*', lines[s]).group(0)
            lines.insert(e + 1, ind + '#endif\n')
            lines.insert(s, ind + '#if 0  // u_remap: no Utage address\n')
            changed['disabled'] += 1
        f.write_text(''.join(lines), encoding='utf-8', errors='surrogateescape')
    print('apply:', dict(changed))


if __name__ == '__main__':
    main()
