"""Render the original Ningbo A3 PDF plan into a PNG using the bundled pdf.js.

Headless Edge cannot display a PDF file directly (blank screenshot), so the
page embeds the PDF bytes and pdf.js draws page 1 into a canvas, which the
headless browser then screenshots. No network access and no project data sent
anywhere. This is a local evidence tool for the floor-plan base map.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09" / "source" / "平面图.pdf"
PDFJS = ROOT / "web" / "node_modules" / "pdfjs-dist" / "build"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\EdgeCore\150.0.4078.65\msedge.exe")

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#fff}canvas{display:block}
</style></head><body><canvas id="c"></canvas>
<script type="module">
import * as pdfjsLib from './pdf.mjs';
pdfjsLib.GlobalWorkerOptions.workerSrc = './pdf.worker.mjs';
const b64 = '__PDF_BASE64__';
const data = Uint8Array.from(atob(b64), ch => ch.charCodeAt(0));
const pdf = await pdfjsLib.getDocument({data}).promise;
const page = await pdf.getPage(1);
const scale = __SCALE__;
const viewport = page.getViewport({scale});
const canvas = document.getElementById('c');
canvas.width = Math.ceil(viewport.width);
canvas.height = Math.ceil(viewport.height);
canvas.style.width = canvas.width + 'px';
canvas.style.height = canvas.height + 'px';
await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
document.documentElement.setAttribute('data-done','1');
document.title = 'DONE ' + pdf.numPages + ' ' + canvas.width + 'x' + canvas.height;
</script></body></html>"""


def main() -> int:
    out_dir = ROOT / "var" / "deliverables" / "ningbo-xiecheng" / "2026-11-10"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not PDF.exists() or not (PDFJS / "pdf.mjs").exists() or not EDGE.exists():
        print("missing PDF / pdf.js / EdgeCore", flush=True)
        return 2
    work = out_dir / "_pdf_render"
    work.mkdir(exist_ok=True)
    for name in ("pdf.mjs", "pdf.worker.mjs"):
        (work / name).write_bytes((PDFJS / name).read_bytes())
    encoded = base64.b64encode(PDF.read_bytes()).decode("ascii")
    (work / "render.html").write_text(
        HTML.replace("__PDF_BASE64__", encoded).replace("__SCALE__", "2.2"), encoding="utf-8")
    png = (out_dir / "00_原始平面图_PDF.png").resolve()
    env = {key: value for key, value in os.environ.items()
           if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"}}
    user_data = Path(tempfile.gettempdir()) / f"rkd-pdfjs-{os.getpid()}"
    command = [str(EDGE), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
               "--no-proxy-server", "--allow-file-access-from-files", "--virtual-time-budget=30000",
               f"--user-data-dir={user_data}", f"--screenshot={png}", "--window-size=2400,1750",
               (work / "render.html").resolve().as_uri()]
    result = subprocess.run(command, capture_output=True, timeout=240, env=env, text=True, errors="replace")
    print("rc", result.returncode, "png", png.stat().st_size if png.exists() else 0, flush=True)
    print((result.stderr or "")[-300:], flush=True)
    return 0 if result.returncode == 0 and png.exists() and png.stat().st_size > 20000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
