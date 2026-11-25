#!/usr/bin/env python3
"""Fits a Dolphin texture pack made for the original Utage disc to a translation patch's game files.

python -I tools/u_rehash_textures.py --pack "<mod>/S3HJ08" --original F:/utage/extracted/DATA \
    --patched F:/utage/build/riivolution/S3HJ08 --utage-tools F:/utage/tools --out build/textures/sn

A Dolphin pack names each PNG after what it replaces: tex1_<w>x<h>_<texture hash>[_<palette hash>]_<format>,
the hashes being XXH64 of the texture's data and of the palette entries it uses. The translation patch
redraws many of those textures, so their hashes change and the pack no longer matches them. For every pack
PNG this finds the original textures it matches (archive, entry), hashes the same entries in the patched
files and writes the PNG under each name it needs there: the patched name where the patch redrew the
texture, the original name where it did not. The patch edits pixels and palettes in place, so sizes and
formats never change and the PNGs fit as they are. Played over the patch, the pack shows where it has a
texture, the patch everywhere else. A PNG that matches no texture is left out; when the patch made two of
the pack's textures identical, the PNG used by more archives wins. --keep-ours NAME leaves out the pack's
PNGs for the textures whose entry name contains NAME, so the patch's own show there (the title screen's
copyright line with the port credit: --keep-ours title/title_001_). map.tsv lists what went where.

--max-scale N shrinks a PNG larger than N times its texture to exactly N times (Sin-Nohara's pack has
some at 4x-16x, 669 MB of RGBA8 in all; at most 2x it is 453 MB), --optimize re-saves every PNG at the
highest compression. Both need Pillow; the pixels of a PNG left at its size are unchanged.

The archive and texture readers are the translation project's (utage/tools: arc, gxtex, xxh64, modmap).
"""
import argparse
import os
import re
import shutil
import sys
from multiprocessing import Pool

TOOLS = None


def load_tools(path):
    global TOOLS
    if TOOLS is None:
        sys.path.insert(0, path)
        import arc
        import gxtex
        import modmap
        TOOLS = (arc, gxtex, modmap)
    return TOOLS


def dolphin_names(path, wanted, tools):
    """{entry name: Dolphin name} for the textures in one archive (only sizes/formats in `wanted`)."""
    arc, gxtex, modmap = tools
    try:
        names = arc.read_names(path)
    except OSError:
        return {}
    if not any(h == modmap.TEX_TYPE for _, h in names):
        return {}
    _, entries = arc.read_arc(path)
    by = {(e.name, e.type_hash): e for e in entries}
    out = {}
    for e in entries:
        if e.type_hash != modmap.TEX_TYPE:
            continue
        t = gxtex.Tex0(e.data)
        if wanted is not None and (t.width, t.height, t.fmt) not in wanted:
            continue
        pe = by.get((e.name, modmap.PLT_TYPE))
        out[e.name] = modmap.dolphin_name(t, gxtex.Plt0(pe.data) if pe else None)
    return out


def scan(job):
    rel, wanted, original, patched, tools_path = job
    tools = load_tools(tools_path)
    before = dolphin_names(os.path.join(original, rel), wanted, tools)
    if not before:
        return rel, {}
    p = os.path.join(patched, rel)
    after = dolphin_names(p, None, tools) if os.path.exists(p) else before
    return rel, {name: (dn, after.get(name)) for name, dn in before.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pack', required=True, help="the pack's tex1_*.png folder (Load/Textures/S3HJ08)")
    ap.add_argument('--original', required=True, help='the unpacked original game (sys/, files/)')
    ap.add_argument('--patched', required=True, help="the patch's S3HJ08 folder (nativeWii/...)")
    ap.add_argument('--utage-tools', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--keep-ours', action='append', default=[], metavar='NAME',
                    help="leave out the pack's PNGs for entries whose name contains NAME (repeatable)")
    ap.add_argument('--jobs', type=int, default=4, help='archive readers in parallel (each holds a whole archive)')
    ap.add_argument('--max-scale', type=int, default=0, help='shrink PNGs larger than N times their texture')
    ap.add_argument('--optimize', action='store_true', help='re-save every PNG at the highest compression')
    a = ap.parse_args()
    _, _, modmap = load_tools(a.utage_tools)

    pngs = {}
    wanted = set()
    for dp, _, fn in os.walk(a.pack):
        for f in fn:
            m = modmap.NAME_RE.match(f)
            if m:
                pngs[re.sub(r'_mip\d+$', '', f[:-4])] = os.path.join(dp, f)
                wanted.add((int(m.group(1)), int(m.group(2)), int(m.group(6))))
    game = os.path.join(a.original, 'files', 'nativeWii')
    patched = os.path.join(a.patched, 'nativeWii')
    rels = sorted(os.path.relpath(os.path.join(dp, f), game).replace('\\', '/')
                  for dp, _, fn in os.walk(game) for f in fn if f.endswith('.arc'))
    # original Dolphin name -> [(archive, entry, name after the patch)]
    found = {}
    with Pool(a.jobs) as pool:
        for rel, names in pool.imap_unordered(scan, [(r, wanted, game, patched, a.utage_tools) for r in rels], chunksize=16):
            for entry, (before, after) in names.items():
                found.setdefault(before, []).append((rel, entry.replace('\\', '/'), after))

    claims = {}  # target name -> [(archives using it, pack name)]
    unmatched = []
    kept_ours = []
    for key in sorted(pngs):
        locs = found.get(key) or found.get(key.replace('_$_', '_')) or []
        if not locs:
            unmatched.append(key)
            continue
        if any(k in entry for k in a.keep_ours for _, entry, _ in locs):
            kept_ours.append(key)
            continue
        targets = {}
        for rel, entry, after in locs:
            if after:
                targets[after] = targets.get(after, 0) + 1
        for target, uses in targets.items():
            claims.setdefault(target, []).append((uses, key))

    shrunk = 0

    def write_png(src, target):
        nonlocal shrunk
        dst = os.path.join(a.out, target + '.png')
        if not a.max_scale and not a.optimize:
            shutil.copyfile(src, dst)
            return
        from PIL import Image
        m = modmap.NAME_RE.match(target + '.png')
        w0, h0 = int(m.group(1)), int(m.group(2))
        with Image.open(src) as img:
            out = img
            if a.max_scale and (img.width > w0 * a.max_scale or img.height > h0 * a.max_scale):
                out = img.resize((w0 * a.max_scale, h0 * a.max_scale), Image.LANCZOS)
                shrunk += 1
            if out is img and not a.optimize:
                shutil.copyfile(src, dst)
            else:
                out.save(dst, optimize=True, compress_level=9)

    shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(a.out)
    renamed = kept = dropped = 0
    with open(os.path.join(a.out, 'map.tsv'), 'w', encoding='utf-8', newline='\n') as tsv:
        tsv.write('target\tsource\n')
        for target in sorted(claims):
            ranked = sorted(claims[target], key=lambda c: (-c[0], c[1]))
            source = ranked[0][1]
            dropped += len(ranked) - 1
            write_png(pngs[source], target)
            tsv.write('%s.png\t%s.png\n' % (target, source))
            if target == source:
                kept += 1
            else:
                renamed += 1
    print('%d pack PNGs: %d written under the patched name, %d unchanged, %d unmatched (left out), '
          '%d lost to an identical patched texture, %d left to the patch (--keep-ours)' % (
              len(pngs), renamed, kept, len(unmatched), dropped, len(kept_ours)))
    if a.max_scale:
        print('%d PNGs shrunk to %dx their texture' % (shrunk, a.max_scale))
    for key in kept_ours:
        print('  patch keeps:', key)
    for key in unmatched:
        print('  unmatched:', key)


if __name__ == '__main__':
    main()
