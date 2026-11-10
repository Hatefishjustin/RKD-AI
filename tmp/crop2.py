import sys
from pathlib import Path
from PIL import Image

src = Path(sys.argv[1])
im = Image.open(src)
W, H = im.size
crops = {
    "z_corner": (0.265, 0.300, 0.340, 0.395),
    "z_bath": (0.635, 0.400, 0.785, 0.760),
    "z_arrival2": (0.02, 0.13, 0.20, 0.42),
    "z_south": (0.20, 0.45, 0.62, 0.62),
}
for name, (x0, y0, x1, y1) in crops.items():
    box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
    part = im.crop(box)
    scale = min(6.0, 1300 / max(1, part.size[0]))
    part = part.resize((int(part.size[0] * scale), int(part.size[1] * scale)), Image.LANCZOS)
    p = src.parent / f"{name}.png"
    part.save(p)
    print(p, part.size)
