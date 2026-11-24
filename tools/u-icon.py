"""SB3 UTAGE:INDO launcher icon from the game's title screen (Dolphin screenshot of S3HJ08's title).
The logo is lifted off the title's light checker background (flood fill from the crop's edges through
light, unsaturated pixels), set on a dark red backdrop with an INDO pill. Writes the adaptive
foreground at every density plus a preview with round and squircle masks.
python make_icon.py PREVIEW.png [write]"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import colorsys
import sys
from collections import deque

SRC = r'F:\utage\emulator\Dolphin-x64\User\ScreenShots\S3HJ08\S3HJ08_2026-11-21_15-26-45.png'
RES = r'F:\basara_work\U3Wii-Android\app\src\main\res'
OUT = sys.argv[1]
WRITE = len(sys.argv) > 2 and sys.argv[2] == 'write'
N = 1296  # 3x of 432

title = Image.open(SRC).convert('RGB')
logo = title.crop((345, 120, 1505, 712))
lw, lh = logo.size
px = logo.load()


def background_like(rgb):
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return v > 0.55 and s < 0.36


bg = bytearray(1 if background_like(px[x, y]) else 0 for y in range(lh) for x in range(lw))


def components(value):
    """Connected areas of pixels where bg == value: (pixel indices, touches the edge)."""
    label = bytearray(lw * lh)
    for start in range(lw * lh):
        if label[start] or bg[start] != value:
            continue
        label[start] = 1
        q = deque([start])
        area = []
        edge = False
        while q:
            i = q.popleft()
            area.append(i)
            x, y = i % lw, i // lw
            if x == 0 or y == 0 or x == lw - 1 or y == lh - 1:
                edge = True
            for j in (i - 1 if x > 0 else -1, i + 1 if x < lw - 1 else -1, i - lw if y > 0 else -1, i + lw if y < lh - 1 else -1):
                if j >= 0 and not label[j] and bg[j] == value:
                    label[j] = 1
                    q.append(j)
        yield area, edge


seen = bytearray(lw * lh)
# Background: everything light and grey touching the edge, and any enclosed light area bigger than a
# letter's highlight (the hole of the 3, the gaps between letters).
for area, edge in components(1):
    if edge or len(area) > 500:
        for i in area:
            seen[i] = 1
# Specks of the checker's darker tone left over: small opaque islands go too.
for i in range(lw * lh):
    bg[i] = seen[i]
for area, edge in components(0):
    if len(area) < 400:
        for i in area:
            seen[i] = 1
alpha = Image.frombytes('L', (lw, lh), bytes(0 if s else 255 for s in seen))
# Close small holes, keep a thin soft edge.
alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
# Drop the bits of the character portraits at the right edge (right of the 宴, above it).
cut = ImageDraw.Draw(alpha)
cut.rectangle((int(lw * 0.80), 0, lw, int(lh * 0.40)), fill=0)
cut.rectangle((0, 0, int(lw * 0.25), int(lh * 0.28)), fill=0)  # a gold line of the title's clouds
logo_rgba = logo.convert('RGBA')
logo_rgba.putalpha(alpha)
bbox = alpha.point(lambda a: 255 if a > 40 else 0).getbbox()
logo_rgba = logo_rgba.crop(bbox)

# Backdrop: dark red to near black, a soft light behind the logo.
back = Image.new('RGB', (N, N), (0, 0, 0))
bd = ImageDraw.Draw(back)
for r in range(N, 0, -6):
    t = r / N
    col = (int(150 * (1 - t) + 40 * t), int(26 * (1 - t) + 8 * t), int(28 * (1 - t) + 10 * t))
    bd.ellipse((N / 2 - r * 0.75, N * 0.46 - r * 0.75, N / 2 + r * 0.75, N * 0.46 + r * 0.75), fill=col)
back = back.filter(ImageFilter.GaussianBlur(30)).convert('RGBA')

# Logo inside the inner 72 of 108 dp (a launcher's mask), with room for round masks.
w = int(N * 0.63)
h = int(logo_rgba.height * w / logo_rgba.width)
logo_rgba = logo_rgba.resize((w, h), Image.LANCZOS)
top = int(N * 0.47 - h / 2)
glow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
glow.paste((255, 225, 160, 150), ((N - w) // 2, top), logo_rgba.split()[3])
glow = glow.filter(ImageFilter.GaussianBlur(18))
icon = Image.alpha_composite(back, glow)
layer = Image.new('RGBA', (N, N), (0, 0, 0, 0))
layer.paste(logo_rgba, ((N - w) // 2, top), logo_rgba)
icon = Image.alpha_composite(icon, layer)

# "INDO" on a red pill under it (the launcher's accent, 0xE5484D).
font = ImageFont.truetype(r'C:\Windows\Fonts\ariblk.ttf', int(N * 0.060))
text = 'INDO'
tb = font.getbbox(text)
tw, th = tb[2] - tb[0], tb[3] - tb[1]
pw, ph = int(tw + N * 0.07), int(th + N * 0.04)
pxl = (N - pw) // 2
py = top + h + int(N * 0.012)
pill = Image.new('RGBA', (N, N), (0, 0, 0, 0))
pd = ImageDraw.Draw(pill)
pd.rounded_rectangle((pxl, py, pxl + pw, py + ph), radius=ph // 2, fill=(229, 72, 77, 255),
                     outline=(255, 226, 170, 255), width=max(4, N // 300))
pd.text(((N - tw) // 2 - tb[0], py + (ph - th) // 2 - tb[1]), text, font=font, fill=(255, 255, 255, 255))
icon = Image.alpha_composite(icon, pill)

if WRITE:
    for dens, size in (('mdpi', 108), ('hdpi', 162), ('xhdpi', 216), ('xxhdpi', 324), ('xxxhdpi', 432)):
        icon.resize((size, size), Image.LANCZOS).save(RES + r'\mipmap-%s\ic_launcher_foreground.png' % dens, optimize=True)

full = icon.resize((432, 432), Image.LANCZOS)
inner = full.crop((72, 72, 360, 360))
prev = Image.new('RGB', (288 * 3 + 40, 288 + 20), (238, 238, 242))
prev.paste(full.resize((288, 288)), (10, 10))
for i, shape in enumerate(('circle', 'squircle')):
    m = Image.new('L', (288, 288), 0)
    md = ImageDraw.Draw(m)
    if shape == 'circle':
        md.ellipse((0, 0, 287, 287), fill=255)
    else:
        md.rounded_rectangle((0, 0, 287, 287), radius=80, fill=255)
    prev.paste(inner, (10 + 298 * (i + 1), 10), m)
prev.save(OUT)
print('ok', 'written' if WRITE else 'preview only')
