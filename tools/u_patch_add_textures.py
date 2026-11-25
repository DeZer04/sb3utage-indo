#!/usr/bin/env python3
"""Makes a launcher .patch that is another .patch plus a texture pack.

python -I tools/u_patch_add_textures.py BASE.patch TEXTURE_DIR --id full-sn --name "..." --version 1.2 \
    --description "..." --out OUT.patch

The base patch's entries are copied as they are (the same game files, byte for byte), then every file
of TEXTURE_DIR (tools/u_rehash_textures.py's PNGs, and any notes beside them) becomes a whole-file entry
under Textures/. Texture entries need header format 2: the app installs them in the patch's own
Textures folder and plays them while the patch is on (GamePatch.java), the web patcher writes them to
Dolphin's Load/Textures/S3HJ08 (docs/patcher). Older apps refuse format 2 with "needs a newer
SB3 UTAGE:INDO" instead of failing half way.
"""
import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('base', type=Path)
    ap.add_argument('textures', type=Path)
    ap.add_argument('--id', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--description', default='')
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()

    textures = sorted(p for p in a.textures.iterdir() if p.is_file() and p.name != 'map.tsv')
    if not textures:
        sys.exit('%s: no files' % a.textures)
    part = a.out.with_name(a.out.name + '.part')
    with open(a.base, 'rb') as f, open(part, 'wb') as out:
        if f.read(8) != b'SB3UPAT1':
            sys.exit('%s: not a SB3UPAT1 patch' % a.base)
        header = json.loads(f.read(struct.unpack('>I', f.read(4))[0]).decode('utf-8'))
        base_files = header['files']
        header.update({
            'format': 2, 'id': a.id, 'name': a.name, 'version': a.version, 'description': a.description,
            'files': base_files + len(textures),
            'bytes': header['bytes'] + sum(p.stat().st_size for p in textures),
            'textures': len(textures),
        })
        hb = json.dumps(header, ensure_ascii=False).encode('utf-8')
        out.write(b'SB3UPAT1' + struct.pack('>I', len(hb)) + hb)
        for _ in range(base_files):
            fixed = f.read(2)
            path = f.read(struct.unpack('>H', fixed)[0])
            n = f.read(2)
            disc = f.read(struct.unpack('>H', n)[0])
            meta = f.read(1 + 4 + 20 + 4 + 20)
            length = f.read(4)
            out.write(fixed + path + n + disc + meta + length + f.read(struct.unpack('>I', length)[0]))
        if f.read(8) != b'SB3UEND1' or struct.unpack('>I', f.read(4))[0] != base_files:
            sys.exit('%s: bad trailer' % a.base)
        for p in textures:
            data = p.read_bytes()
            name = ('Textures/' + p.name).encode('utf-8')
            payload = zlib.compress(data, 9)
            out.write(struct.pack('>H', len(name)) + name + struct.pack('>H', 0))
            out.write(struct.pack('>BI', 1, 0) + bytes(20) + struct.pack('>I', len(data)) + hashlib.sha1(data).digest())
            out.write(struct.pack('>I', len(payload)) + payload)
        out.write(b'SB3UEND1' + struct.pack('>I', header['files']))
    part.replace(a.out)
    sha = hashlib.sha256(a.out.read_bytes()).hexdigest()
    print('%s: %d game files + %d texture files, %.1f MB (installed %.1f MB), sha256 %s' % (
        a.out, base_files, len(textures), a.out.stat().st_size / 1e6, header['bytes'] / 1e6, sha))


if __name__ == '__main__':
    main()
