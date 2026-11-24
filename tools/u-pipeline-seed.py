#!/usr/bin/env python3
"""Build the bundled shader list (initial_pipeline_cache.db) from phones' pipeline_cache.db files.
python -I tools/u-pipeline-seed.py SOURCE [MORE ...] OUT.db
python -I tools/u-pipeline-seed.py --check DB   (b-android.ps1 -Mode stage: versions and sizes)
python -I tools/u-pipeline-seed.py --compare SEED.db SOURCE [MORE ...]   (what a merge would add; writes nothing)

A SOURCE is a pipeline_cache.db pulled from a phone (its -wal beside it is read too) or a log zip
from the app's Share Logs (shaders/pipeline_cache.db with device.txt). Aurora merges
<runtime>/initial_pipeline_cache.db into the player's own list (pipeline_cache.cpp
seed_pipeline_cache, once per bundled list), so a new install builds every known shader on the
Preparing shaders screen instead of mid-game. b-android.ps1 -Mode stage ships
assets/pipeline/initial_pipeline_cache.db when it exists, after --check.

What keys a shader besides the game: Disable Fog (fog type none) and the vertex loader a GPU needs
(ShaderConfig.vtxInput). The loader applies the player's own to every row (gx apply_setting_keys),
so rows from any phone fit any player, except a Disable Fog list: its rows lost the fog the game
asks for. Such a source is refused (device.txt says "disable fog: on", or most of its rows have no
fog; --allow-fog-off overrides). Graphics Compatibility (the safe vertex fetch) changes only the
generated code, not the key, so one list covers both.

GX rows that differ only in the alpha compare references (the key keeps 0, 255 or 1 since the
alpha_ref uniform, gx.hpp alpha_compare_key) or in vtxInput are one shader: one row of each such
group is kept, an already normalized one when there is. Rows keep their own content hash (the
loader checks it on the stored bytes and normalizes after), so nothing here needs aurora's xxh3.
OUT.manifest.json records the sources and counts (the list itself is not in git)."""
import datetime
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GX_TYPE, CLEAR_TYPE = 1, 0
CONFIG_SIZE = 2768          # sizeof(gx::PipelineConfig) for version 20; a new layout bumps the version
REF_OFFSETS = (2648, 2660)  # PipelineConfig: 8 + ShaderConfig.alphaCompare.ref0 / ref1
FOG_TYPE = 8                # 8 + ShaderConfig.fogType
FLAGS = 10                  # 8 + the ShaderConfig bit field: lineMode 0-1, fogRangeAdjust 3, vtxInput 4
VTX_INPUT = 0x10
FOG_RANGE_ADJUST = 0x08
ATTRS = 16                  # 8 + ShaderConfig.attrs: 26 AttrConfig of 8 bytes, frac at +5
ATTR_COUNT, ATTR_SIZE, ATTR_FRAC = 26, 8, 5
GX_FOG_NONE, GX_FOG_PERSP_LIN = 0, 2
FOG_OFF_SHARE = 0.5         # normal play: about 12% of the rows have no fog


def header_version(rel, name):
    text = (ROOT / rel).read_text(encoding='utf-8')
    return int(re.search(r'constexpr uint32_t %s = (\d+);' % name, text).group(1))


GX_VERSION = header_version('aurora/lib/gx/pipeline.hpp', 'GXPipelineConfigVersion')
CLEAR_VERSION = header_version('aurora/lib/gfx/clear.hpp', 'ClearPipelineConfigVersion')


def ref_key(ref):
    return ref if ref in (0, 255) else 1


def key_of(blob):
    """The shader a row stands for once loaded: refs normalized, vtxInput left to the player's GPU, and
    the merged variants (gx apply_setting_keys): any fog type one, no range adjust, and with vertex
    pulling (most GPUs) no fraction bits."""
    b = bytearray(blob)
    for off in REF_OFFSETS:
        struct.pack_into('<I', b, off, ref_key(struct.unpack_from('<I', b, off)[0]))
    b[FLAGS] &= ~VTX_INPUT & 0xFF
    if b[FOG_TYPE] != GX_FOG_NONE:
        b[FOG_TYPE] = GX_FOG_PERSP_LIN
        b[FLAGS] &= ~FOG_RANGE_ADJUST & 0xFF
    for i in range(ATTR_COUNT):
        b[ATTRS + i * ATTR_SIZE + ATTR_FRAC] = 0
    return bytes(b)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def problems(db):
    """Rows the runtime would not load as they are: another config version or size."""
    out = []
    for typ, version, size, n in db.execute(
            'SELECT type, config_version, length(config), count(*) FROM pipeline_cache GROUP BY 1, 2, 3'):
        if typ == GX_TYPE and (version != GX_VERSION or size != CONFIG_SIZE):
            out.append('%d GX rows of version %d, %d bytes (want %d, %d)' % (n, version, size, GX_VERSION, CONFIG_SIZE))
        elif typ == CLEAR_TYPE and version != CLEAR_VERSION:
            out.append('%d clear rows of version %d (want %d)' % (n, version, CLEAR_VERSION))
    return out


def check(path):
    db = sqlite3.connect('file:%s?mode=ro' % Path(path).as_posix(), uri=True)
    bad = problems(db)
    gx = db.execute('SELECT count(*) FROM pipeline_cache WHERE type = ?', (GX_TYPE,)).fetchone()[0]
    db.close()
    for line in bad:
        print('initial_pipeline_cache.db: ' + line)
    if bad:
        print('initial_pipeline_cache.db does not match this aurora: rebuild it with tools/u-pipeline-seed.py')
        return 1
    print('initial_pipeline_cache.db: %d GX rows, version %d' % (gx, GX_VERSION))
    return 0


def open_source(src, work, allow_fog_off):
    """(db path, manifest entry) for a .db or a Share Logs zip; refuses a Disable Fog list."""
    entry = {'source': str(src), 'sha256': sha256(src)}
    fog_flag = None
    if zipfile.is_zipfile(src):
        dest = Path(tempfile.mkdtemp(dir=work))
        with zipfile.ZipFile(src) as z:
            names = set(z.namelist())
            if 'shaders/pipeline_cache.db' not in names:
                sys.exit('%s: no shaders/pipeline_cache.db in the zip' % src)
            for name in ('shaders/pipeline_cache.db', 'shaders/pipeline_cache.db-wal'):
                if name in names:
                    (dest / Path(name).name).write_bytes(z.read(name))
            if 'device.txt' in names:
                device = z.read('device.txt').decode('utf-8', 'replace')
                entry['device'] = device.strip().splitlines()[:6]
                m = re.search(r'disable fog: (on|off)', device)
                fog_flag = m.group(1) if m else None
        db_path = dest / 'pipeline_cache.db'
    else:
        db_path = Path(src)
    # A copy, so the WAL folds in without touching the source.
    copy = Path(tempfile.mkdtemp(dir=work)) / 'p.db'
    shutil.copyfile(db_path, copy)
    if Path(str(db_path) + '-wal').exists():
        shutil.copyfile(str(db_path) + '-wal', str(copy) + '-wal')
    db = sqlite3.connect(copy)
    fogs = [c[FOG_TYPE] for (c,) in db.execute('SELECT config FROM pipeline_cache WHERE type = ?', (GX_TYPE,))
            if len(c) == CONFIG_SIZE]
    db.close()
    share = sum(1 for f in fogs if f == 0) / max(1, len(fogs))
    entry.update(rows=len(fogs), fog_off_share=round(share, 3), disable_fog=fog_flag)
    if not allow_fog_off and (fog_flag == 'on' or share > FOG_OFF_SHARE):
        sys.exit('%s: a Disable Fog list (%s, %.0f%% of its rows without fog): its shaders lost the fog the '
                 'game asks for. Leave it out, or pass --allow-fog-off.'
                 % (src, 'device.txt says on' if fog_flag == 'on' else 'no device.txt flag', 100 * share))
    return copy, entry


def build(sources, out, allow_fog_off):
    work = Path(tempfile.mkdtemp())
    opened = [open_source(Path(s), work, allow_fog_off) for s in sources]
    shutil.copyfile(opened[0][0], out)
    if Path(str(opened[0][0]) + '-wal').exists():
        shutil.copyfile(str(opened[0][0]) + '-wal', out + '-wal')
    db = sqlite3.connect(out)
    db.execute('PRAGMA journal_mode=DELETE')  # folds the WAL in: one file to ship
    cols = 'type, hash, config_version, config_size, config, first_frame_used'
    for path, entry in opened[1:]:
        other = sqlite3.connect(path)
        got = other.execute('SELECT %s FROM pipeline_cache' % cols).fetchall()
        other.close()
        db.executemany('INSERT OR IGNORE INTO pipeline_cache (%s) VALUES (?, ?, ?, ?, ?, ?)' % cols, got)
        db.commit()
        print('merged %d rows from %s' % (len(got), entry['source']))
    stale = db.execute('SELECT count(*) FROM pipeline_cache WHERE (type = ? AND (config_version != ? OR length(config) != ?)) '
                       'OR (type = ? AND config_version != ?)',
                       (GX_TYPE, GX_VERSION, CONFIG_SIZE, CLEAR_TYPE, CLEAR_VERSION)).fetchone()[0]
    db.execute('DELETE FROM pipeline_cache WHERE (type = ? AND (config_version != ? OR length(config) != ?)) '
               'OR (type = ? AND config_version != ?)', (GX_TYPE, GX_VERSION, CONFIG_SIZE, CLEAR_TYPE, CLEAR_VERSION))
    rows = db.execute('SELECT rowid, type, config FROM pipeline_cache').fetchall()
    keep = {}
    drop = []
    for rowid, typ, config in rows:
        if typ != GX_TYPE:
            continue
        key = key_of(config)
        plain = key == config  # refs already normalized and vertex pulling: the row as most players load it
        if key not in keep:
            keep[key] = (rowid, plain)
        elif plain and not keep[key][1]:
            drop.append(keep[key][0])
            keep[key] = (rowid, plain)
        else:
            drop.append(rowid)
    db.executemany('DELETE FROM pipeline_cache WHERE rowid = ?', [(r,) for r in drop])
    db.commit()
    db.execute('VACUUM')
    left = dict(db.execute('SELECT type, count(*) FROM pipeline_cache GROUP BY type').fetchall())
    db.close()
    print('%d rows in, %d of another version dropped, %d duplicates dropped, left by type %s'
          % (len(rows) + stale, stale, len(drop), left))
    manifest = {
        'built': datetime.datetime.now().isoformat(timespec='seconds'),
        'gx_config_version': GX_VERSION,
        'clear_config_version': CLEAR_VERSION,
        'sources': [entry for _, entry in opened],
        'rows_in': len(rows) + stale,
        'dropped_other_version': stale,
        'dropped_duplicates': len(drop),
        'gx_rows': left.get(GX_TYPE, 0),
        'clear_rows': left.get(CLEAR_TYPE, 0),
        'sha256': sha256(out),
    }
    man = Path(out).with_suffix('.manifest.json')
    man.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('manifest', man)


def gx_keys(path):
    """The shaders a database stands for once loaded (key_of), and rows of another version."""
    db = sqlite3.connect(path)
    keys, other = set(), 0
    for typ, version, config in db.execute('SELECT type, config_version, config FROM pipeline_cache'):
        if typ != GX_TYPE:
            continue
        if version != GX_VERSION or len(config) != CONFIG_SIZE:
            other += 1
            continue
        keys.add(key_of(config))
    db.close()
    return keys, other


def compare(seed, sources, allow_fog_off):
    """What merging `sources` into the bundled list `seed` would add, without writing anything."""
    work = Path(tempfile.mkdtemp())
    base, _ = gx_keys(seed)
    print('%s: %d shaders' % (seed, len(base)))
    union = set()
    for src in sources:
        path, entry = open_source(Path(src), work, allow_fog_off)
        keys, other = gx_keys(path)
        new = keys - base
        union |= new
        fog_none = sum(1 for k in new if k[FOG_TYPE] == GX_FOG_NONE)
        print('%s: %d rows -> %d shaders (%d of another version); %d already bundled, %d NEW (%d of them '
              'without fog); %d bundled ones it never used; fog-off share of its rows %.0f%%'
              % (src, entry['rows'], len(keys), other, len(keys & base), len(new), fog_none, len(base - keys),
                 100 * entry['fog_off_share']))
    print('all sources together add %d shaders to the %d bundled' % (len(union), len(base)))


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['--check'] and len(args) == 2:
        sys.exit(check(args[1]))
    if args[:1] == ['--compare'] and len(args) >= 3:
        compare(args[1], [a for a in args[2:] if a != '--allow-fog-off'], '--allow-fog-off' in args)
        sys.exit(0)
    allow = '--allow-fog-off' in args
    args = [a for a in args if a != '--allow-fog-off']
    if len(args) < 2:
        sys.exit(__doc__)
    build(args[:-1], args[-1], allow)
