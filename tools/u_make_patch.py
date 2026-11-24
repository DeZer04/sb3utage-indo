#!/usr/bin/env python3
"""Builds a translation .patch for the launcher's first page (HomePage, GamePatch.java)
from a Riivolution package and the original game.

python -I tools/u_make_patch.py --package F:/utage/build/riivolution --original F:/utage/extracted/DATA \
    --id full --name "Full Patch Indo" --version 1.0 --description "..." --out build/patch/full.patch

The package is the translation project's Riivolution build (utage/tools/build_rvz.py --riivolution):
riivolution/S3HJ08.xml beside S3HJ08/nativeWii/... Every file under S3HJ08/nativeWii becomes one entry,
a VCDIFF (xdelta3 -9, no secondary compression) against the same file of the original disc, or the whole
file when that is not smaller or the disc has none; each entry is zlib-compressed. The app reads the
originals from the player's own dump (the ISO/RVZ in place, or unpacked), checks their SHA-1, applies the
deltas, checks the results' SHA-1 and writes them where the runtime's Riivolution overlay reads them
(SB3UtageINDO/Riivolution), with the package's XML. Only differences ship: no whole game files unless
they are new.

Format (big-endian): "SB3UPAT1", u32 header length, header JSON (UTF-8: format, game, id, name, version,
description, files, bytes, xml_name, xml), then per entry: u16+UTF-8 output path (under the overlay root),
u16+UTF-8 disc path ("files/nativeWii/...", empty for a new file), u8 kind (0 VCDIFF, 1 whole file),
u32 source size, 20-byte source SHA-1, u32 result size, 20-byte result SHA-1, u32 payload length,
payload (zlib); then "SB3UEND1" and u32 entry count."""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

XDELTA = Path(os.environ.get('XDELTA3', r'F:\basara_work\tools\xdelta_dl\xdelta3-3.1.0-x86_64.exe'))


def encode(job):
    """(out path, disc path, kind, src bytes info, dst info, payload) for one changed file."""
    new_file, rel, original, tmp = job
    dst = new_file.read_bytes()
    dst_sha = hashlib.sha1(dst).digest()
    old_file = original / 'files' / 'nativeWii' / rel
    if old_file.is_file():
        src = old_file.read_bytes()
        delta_path = Path(tmp) / (hashlib.sha1(str(rel).encode()).hexdigest() + '.vcdiff')
        subprocess.run([str(XDELTA), '-e', '-9', '-S', 'none', '-A', '-f', '-s', str(old_file), str(new_file),
                        str(delta_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        delta = zlib.compress(delta_path.read_bytes(), 9)
        delta_path.unlink()
        whole = zlib.compress(dst, 9)
        if len(delta) < len(whole):
            return rel, 'files/nativeWii/' + rel.as_posix(), 0, len(src), hashlib.sha1(src).digest(), len(dst), dst_sha, delta
        return rel, 'files/nativeWii/' + rel.as_posix(), 1, len(src), hashlib.sha1(src).digest(), len(dst), dst_sha, whole
    return rel, '', 1, 0, bytes(20), len(dst), dst_sha, zlib.compress(dst, 9)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--original', required=True, type=Path, help='the unpacked original game (sys/, files/)')
    ap.add_argument('--id', required=True, choices=['full', 'desc'])
    ap.add_argument('--name', required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--description', default='')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()

    xmls = sorted((a.package / 'riivolution').glob('*.xml'))
    if not xmls:
        sys.exit('%s: no riivolution/*.xml' % a.package)
    root = a.package / 'S3HJ08' / 'nativeWii'
    files = sorted(p for p in root.rglob('*') if p.is_file())
    if not files:
        sys.exit('%s: no files' % root)
    tmp = tempfile.mkdtemp()
    jobs = [(p, p.relative_to(root), a.original, tmp) for p in files]
    with ThreadPoolExecutor(a.jobs) as pool:
        entries = []
        for i, e in enumerate(pool.map(encode, jobs), 1):
            entries.append(e)
            if i % 500 == 0 or i == len(jobs):
                print('%d/%d files' % (i, len(jobs)), flush=True)
    header = {
        'format': 1, 'game': 'S3HJ08', 'id': a.id, 'name': a.name, 'version': a.version,
        'description': a.description, 'files': len(entries), 'bytes': sum(e[5] for e in entries),
        'xml_name': xmls[0].name, 'xml': xmls[0].read_text(encoding='utf-8'),
    }
    hb = json.dumps(header, ensure_ascii=False).encode('utf-8')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    part = a.out.with_name(a.out.name + '.part')
    deltas = wholes = 0
    with open(part, 'wb') as f:
        f.write(b'SB3UPAT1' + struct.pack('>I', len(hb)) + hb)
        for rel, disc, kind, ssize, ssha, dsize, dsha, payload in entries:
            out = ('S3HJ08/nativeWii/' + rel.as_posix()).encode('utf-8')
            d = disc.encode('utf-8')
            f.write(struct.pack('>H', len(out)) + out + struct.pack('>H', len(d)) + d)
            f.write(struct.pack('>BI', kind, ssize) + ssha + struct.pack('>I', dsize) + dsha)
            f.write(struct.pack('>I', len(payload)) + payload)
            deltas += kind == 0
            wholes += kind == 1
        f.write(b'SB3UEND1' + struct.pack('>I', len(entries)))
    part.replace(a.out)
    sha = hashlib.sha256(a.out.read_bytes()).hexdigest()
    print('%s: %d files (%d deltas, %d whole), %.1f MB (game data %.1f MB), sha256 %s' % (
        a.out, len(entries), deltas, wholes, a.out.stat().st_size / 1e6, header['bytes'] / 1e6, sha))


if __name__ == '__main__':
    main()
