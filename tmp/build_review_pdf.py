"""One-off: render the generated review HTML to a printable A4 PDF."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(r"D:/Github/RKD AI")
SRC = ROOT / "var" / "review" / "2026-11-08" / "design-review-2026-11-08.html"
OUT = ROOT / "var" / "review" / "2026-11-08" / "design-review-2026-11-08.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\EdgeCore\150.0.4078.65\msedge.exe")

env = {key: value for key, value in os.environ.items()
       if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"}}
user_data = Path(tempfile.gettempdir()) / f"rkd-review-pdf-{os.getpid()}"
cmd = [
    str(EDGE), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
    "--no-default-browser-check", "--virtual-time-budget=15000", "--no-pdf-header-footer",
    "--no-proxy-server", f"--user-data-dir={user_data}", f"--print-to-pdf={OUT}",
    SRC.as_uri(),
]
result = subprocess.run(cmd, capture_output=True, timeout=240, env=env, text=True, errors="replace")
print("returncode:", result.returncode)
print("exists:", OUT.exists(), "bytes:", OUT.stat().st_size if OUT.exists() else 0)
if OUT.exists():
    raw = OUT.read_bytes()
    print("pages:", len(re.findall(rb"/Type\s*/Page[^s]", raw)))
    print("a4_mediabox:", b"/MediaBox" in raw)
print("stderr tail:", (result.stderr or "")[-500:])
