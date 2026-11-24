#!/usr/bin/env python3
"""Checks a launcher .patch (tools/u_make_patch.py, SB3UPAT1) the way the app applies it, with xdelta3 as
an independent decoder: every entry rebuilt from the original game and compared with its SHA-1 (and,
with --package, byte for byte with the package it was made from).

  python -I tools/u_check_patch.py PATCH --original F:/utage/extracted/DATA [--package DIR]
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

XDELTA = Path(os.environ.get('XDELTA3', r'F:\basara_work\tools\xdelta_dl\xdelta3-3.1.0-x86_64.exe'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('patch', type=Path)
    ap.add_argument('--original', required=True, type=Path)
    ap.add_argument('--package', type=Path)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp())
    bad = 0
    with open(a.patch, 'rb') as f:
        if f.read(8) != b'SB3UPAT1':
            sys.exit('not a SB3UPAT1 patch')
        header = json.loads(f.read(struct.unpack('>I', f.read(4))[0]).decode('utf-8'))
        print('%s %s v%s: %d files, %.1f MB' % (header['id'], header['name'], header['version'], header['files'],
                                                header['bytes'] / 1e6))
        for _ in range(header['files']):
            out = f.read(struct.unpack('>H', f.read(2))[0]).decode('utf-8')
            disc = f.read(struct.unpack('>H', f.read(2))[0]).decode('utf-8')
            kind, ssize = struct.unpack('>BI', f.read(5))
            ssha = f.read(20)
            dsize = struct.unpack('>I', f.read(4))[0]
            dsha = f.read(20)
            payload = zlib.decompress(f.read(struct.unpack('>I', f.read(4))[0]))
            if kind == 0:
                src = (a.original / disc).read_bytes()
                if len(src) != ssize or hashlib.sha1(src).digest() != ssha:
                    print('SOURCE MISMATCH', disc)
                    bad += 1
                    continue
                (tmp / 'd').write_bytes(payload)
                subprocess.run([str(XDELTA), '-d', '-f', '-s', str(a.original / disc), str(tmp / 'd'), str(tmp / 'o')],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result = (tmp / 'o').read_bytes()
            else:
                result = payload
            ok = len(result) == dsize and hashlib.sha1(result).digest() == dsha
            if ok and a.package:
                ok = (a.package / out).read_bytes() == result
            if not ok:
                print('RESULT MISMATCH', out)
                bad += 1
        if f.read(8) != b'SB3UEND1' or struct.unpack('>I', f.read(4))[0] != header['files']:
            print('bad trailer')
            bad += 1
    print('ok: every file rebuilt and checked' if not bad else '%d problem(s)' % bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
