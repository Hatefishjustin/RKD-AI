import sys
from pathlib import Path
from PIL import Image

src = Path(sys.argv[1])
out_dir = src.parent
im = Image.open(src)
W, H = im.size
print("size", W, H)
crops = {
    "c_arrival": (0.02, 0.13, 0.26, 0.46),
    "c_island": (0.24, 0.25, 0.55, 0.60),
    "c_bath": (0.60, 0.42, 0.73, 0.75),
    "c_legend": (0.74, 0.00, 1.00, 0.55),
    "c_table": (0.36, 0.74, 0.78, 1.00),
}
for name, (x0, y0, x1, y1) in crops.items():
    box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
    part = im.crop(box)
    scale = min(3.0, 1400 / max(1, part.size[0]))
    part = part.resize((int(part.size[0] * scale), int(part.size[1] * scale)), Image.LANCZOS)
    p = out_dir / f"{name}.png"
    part.save(p)
    print(p, part.size)
