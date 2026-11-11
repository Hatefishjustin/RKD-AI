"""Rasterise our own generated plan sketches for the director's visual review.

Nothing here sends source documents (CAD / PDF / budget sheets / site photos) to
any model. The only inputs are images produced by this project: the sketch SVG
rendered from a candidate's design data, and one frozen sample render used as a
case reference (explicitly labelled as a hand-written sample, not a system result).
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_RENDER_NAME = "03_效果图_C1_入口看中岛.png"
REFERENCE_RENDER = (ROOT / "var" / "deliverables" / "ningbo-xiecheng" / "2026-11-10"
                    / _RENDER_NAME)
# var/ is gitignored; the checked-in copy keeps the case reference reproducible
# after a fresh clone.
REFERENCE_FALLBACK = (ROOT / "deliverables-for-review" / "ningbo-xiecheng"
                      / "2026-11-10" / _RENDER_NAME)
EDGE_ROOT = Path(r"C:\Program Files (x86)\Microsoft\EdgeCore")
_PROXY_KEYS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
               "http_proxy", "https_proxy", "all_proxy"}

REFERENCE_NOTE = ("案例参照：宁波方案A第3版效果图（人工编写的手工样板，"
                  "只作观感对比，不计入系统自动生成成果）")


def _edge() -> Path:
    candidates = sorted(EDGE_ROOT.glob("*/msedge.exe")) if EDGE_ROOT.exists() else []
    if not candidates:
        raise RuntimeError("找不到 EdgeCore 的 msedge.exe，无法把草案图转成位图")
    return candidates[-1]


def _to_jpeg(png: Path, limit: int = 720) -> bytes:
    from PIL import Image
    im = Image.open(png).convert("RGB")
    im.thumbnail((limit, limit))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return buf.getvalue()


def svg_to_jpeg(svg: str, limit: int = 720) -> bytes:
    """Render a plan-sketch SVG via the local headless browser, then shrink it."""
    work = Path(tempfile.mkdtemp(prefix="rkd-vision-"))
    svg_path = work / "plan.svg"
    svg_path.write_text(svg, encoding="utf-8")
    png_path = work / "plan.png"
    env = {k: v for k, v in os.environ.items() if k.upper() not in _PROXY_KEYS}
    cmd = [str(_edge()), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--no-proxy-server", "--hide-scrollbars",
           f"--user-data-dir={work / 'profile'}", "--window-size=1000,760",
           "--virtual-time-budget=8000", f"--screenshot={png_path}", svg_path.as_uri()]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                            env=env, timeout=90)
    if not png_path.exists():
        raise RuntimeError(f"草案图转位图失败（rc={result.returncode}）")
    return _to_jpeg(png_path, limit)


def reference_jpeg(limit: int = 720) -> bytes:
    """The frozen hand-written sample render, used only as a visual case reference."""
    path = REFERENCE_RENDER if REFERENCE_RENDER.exists() else REFERENCE_FALLBACK
    if not path.exists():
        raise RuntimeError(f"案例参照图不存在：{REFERENCE_RENDER} / {REFERENCE_FALLBACK}")
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((limit, limit))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return buf.getvalue()
