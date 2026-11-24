#!/usr/bin/env python3
"""Preview the touch-control glyphs (app/.../TouchGlyphs.java): python -I tools/u-glyphs.py OUT.png [NAME ...]
Parses each `static final Path NAME = TouchIcons.svg("...")` (absolute M L H V C Q A Z, a 512x512 box, non-zero
fill like android.graphics.Path's default) and draws them white on dark circles, as the overlay does."""
import math
import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parent.parent / 'app/src/main/java/io/github/dezer04/sb3utage/TouchGlyphs.java'


def glyphs(text):
    out = {}
    for m in re.finditer(r'static final Path (\w+) = TouchIcons\.svg\(((?:\s*"[^"]*"\s*\+?)+)\)', text):
        out[m.group(1)] = ''.join(re.findall(r'"([^"]*)"', m.group(2)))
    for m in re.finditer(r'static final Path (\w+) = (\w+);', text):
        if m.group(2) in out:
            out[m.group(1)] = out[m.group(2)]
    return out


def arc_points(x0, y0, rx, ry, rot, large, sweep, x1, y1, n=24):
    # SVG endpoint arc to centre form (rotation ignored when rx == ry, as in these glyphs).
    if rx == 0 or ry == 0:
        return [(x1, y1)]
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    lam = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    k = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        k = -k
    cx = k * rx * dy / ry + (x0 + x1) / 2
    cy = -k * ry * dx / rx + (y0 + y1) / 2
    a0 = math.atan2((y0 - cy) / ry, (x0 - cx) / rx)
    a1 = math.atan2((y1 - cy) / ry, (x1 - cx) / rx)
    da = a1 - a0
    if sweep and da < 0:
        da += 2 * math.pi
    elif not sweep and da > 0:
        da -= 2 * math.pi
    return [(cx + rx * math.cos(a0 + da * i / n), cy + ry * math.sin(a0 + da * i / n)) for i in range(1, n + 1)]


def polylines(data):
    tok = data.replace(',', ' ').split()
    i = 0
    subs = []
    cur = []
    x = y = sx = sy = 0.0
    cmd = 'M'
    f = lambda: float(tok[i])
    while i < len(tok):
        if tok[i][0].isalpha():
            cmd = tok[i][0]
            i += 1
            if cmd == 'Z':
                if cur:
                    subs.append(cur)
                cur = []
                x, y = sx, sy
                continue
        if cmd == 'M':
            if cur:
                subs.append(cur)
            x, y = float(tok[i]), float(tok[i + 1]); i += 2
            sx, sy = x, y
            cur = [(x, y)]
            cmd = 'L'
        elif cmd == 'L':
            x, y = float(tok[i]), float(tok[i + 1]); i += 2
            cur.append((x, y))
        elif cmd == 'H':
            x = float(tok[i]); i += 1
            cur.append((x, y))
        elif cmd == 'V':
            y = float(tok[i]); i += 1
            cur.append((x, y))
        elif cmd == 'C':
            x1, y1, x2, y2, x3, y3 = (float(t) for t in tok[i:i + 6]); i += 6
            for s in range(1, 13):
                t = s / 12
                mt = 1 - t
                cur.append((mt ** 3 * x + 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t ** 3 * x3,
                            mt ** 3 * y + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t ** 3 * y3))
            x, y = x3, y3
        elif cmd == 'Q':
            x1, y1, x2, y2 = (float(t) for t in tok[i:i + 4]); i += 4
            for s in range(1, 9):
                t = s / 8
                mt = 1 - t
                cur.append((mt * mt * x + 2 * mt * t * x1 + t * t * x2, mt * mt * y + 2 * mt * t * y1 + t * t * y2))
            x, y = x2, y2
        elif cmd == 'A':
            rx, ry, rot, large, sweep, ex, ey = (float(t) for t in tok[i:i + 7]); i += 7
            cur.extend(arc_points(x, y, rx, ry, rot, large != 0, sweep != 0, ex, ey))
            x, y = ex, ey
        else:
            raise ValueError('svg command ' + cmd)
    if cur:
        subs.append(cur)
    return subs


def rasterize(data, size):
    """Non-zero winding scanline fill into an L image of size x size (the 512 box scaled)."""
    s = size / 512.0
    edges = []
    for sub in polylines(data):
        pts = [(px * s, py * s) for px, py in sub]
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            if ay != by:
                edges.append((ax, ay, bx, by))
    img = Image.new('L', (size, size), 0)
    px = img.load()
    for row in range(size):
        yc = row + 0.5
        xs = []
        for ax, ay, bx, by in edges:
            if (ay <= yc < by) or (by <= yc < ay):
                xs.append((ax + (yc - ay) * (bx - ax) / (by - ay), 1 if by > ay else -1))
        xs.sort()
        wind = 0
        for j, (xv, d) in enumerate(xs):
            wind += d
            if wind != 0 and j + 1 < len(xs):
                for col in range(max(0, int(xv + 0.5)), min(size, int(xs[j + 1][0] + 0.5))):
                    px[col, row] = 255
    return img


def sheet(items, out, size=160):
    cols = min(6, len(items))
    rows = (len(items) + cols - 1) // cols
    W = Image.new('RGB', (cols * (size + 20), rows * (size + 40)), (18, 19, 24))
    d = ImageDraw.Draw(W)
    for k, (name, data) in enumerate(items):
        x, y = (k % cols) * (size + 20) + 10, (k // cols) * (size + 40) + 10
        d.ellipse((x, y, x + size, y + size), fill=(40, 42, 52), outline=(150, 150, 160), width=3)
        g = rasterize(data, int(size * 0.62))
        off = (size - g.size[0]) // 2
        W.paste((235, 235, 240), (x + off, y + off), g)
        d.text((x + 4, y + size + 8), name, fill=(255, 220, 90))
    W.save(out)


if __name__ == '__main__':
    gl = glyphs(SRC.read_text(encoding='utf-8'))
    names = sys.argv[2:] or list(gl)
    sheet([(n, gl[n]) for n in names if n in gl], sys.argv[1])
    print('drew', [n for n in names if n in gl])
