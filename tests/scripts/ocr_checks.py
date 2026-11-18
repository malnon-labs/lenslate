"""Run by tests/test_ocr_engine.py with the engine environment's Python (RapidOCR, meikiocr): prints one JSON
result. Needs the OCR models already downloaded (no network: HF_HUB_OFFLINE)."""
import json
import os
import sys

sys.path.insert(0, sys.argv[1])
os.environ.update(LENSLATE_OCR_GPU="off", LENSLATE_OCR_THREADS="2", HF_HUB_OFFLINE="1")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import ocr_server as o  # noqa: E402

out, res = sys.argv[2], {}
FONTS = ["/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf",
         "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
font = next((f for f in FONTS if os.path.exists(f)), None)
if font is None:
    print(json.dumps({"skip": "no CJK font"}))
    sys.exit(0)
f = ImageFont.truetype(font, 32)
COLUMN = "最後のチェックポイント"

# vertical column, quick read (finder boxes -> reader)
img = Image.new("RGB", (300, 460), (20, 20, 40))
d = ImageDraw.Draw(img)
for i, ch in enumerate(COLUMN):
    d.text((130, 20 + i * 38), ch, font=f, fill=(240, 240, 240))
vp = os.path.join(out, "vertical.png")
img.save(vp)
res["vertical_quick"] = [ln["text"] for ln in o.read_lines(vp, o.detect(vp, 1280))]

# finder sizes are rounded: many area sizes, at most the two standard finders
for w in (600, 900, 1100, 1300, 1500, 1800, 1920):
    p = os.path.join(out, "g.png")
    Image.new("RGB", (w, 300), (0, 0, 0)).save(p)
    o.detect(p, min(1920, w))
res["finders"] = sorted(o._gates)

# tile seams (pure box logic): a line cut by a vertical seam, a column cut by a horizontal seam
seam = 960
res["row_join"] = o._merge_tiles([[500, 700, seam + 20, 740], [seam - 30, 702, 1600, 742]], [seam], [])
res["col_join"] = o._merge_tiles([[2200, 200, 2236, 500], [2201, 450, 2235, 680]], [], [480])
print(json.dumps(res, ensure_ascii=False))
