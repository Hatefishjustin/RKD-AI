import os, subprocess, sys, tempfile, time
from pathlib import Path

EDGE_GLOBS = [
    r"C:\Program Files (x86)\Microsoft\EdgeCore",
    r"C:\Program Files\Microsoft\EdgeCore",
]


def find_edge() -> Path:
    best = []
    for root in EDGE_GLOBS:
        p = Path(root)
        if not p.exists():
            continue
        for d in p.iterdir():
            exe = d / "msedge.exe"
            if exe.exists():
                try:
                    parts = [int(x) for x in d.name.split(".")[:3]]
                except ValueError:
                    parts = [0]
                best.append((parts, exe))
    if not best:
        raise SystemExit("no msedge.exe found")
    best.sort(key=lambda t: t[0])
    return best[-1][1]


def shot(src: Path, dst: Path, width: int, height: int, extra_wait: int = 6000) -> tuple[int, str]:
    edge = find_edge()
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY", "NO_PROXY"}}
    for k in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        env.pop(k, None)
    tmp = Path(tempfile.mkdtemp(prefix="edgeshot_"))
    url = "file:///" + str(src).replace("\\", "/").replace(" ", "%20")
    cmd = [str(edge), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--hide-scrollbars", "--no-proxy-server",
           f"--user-data-dir={tmp}", f"--window-size={width},{height}",
           f"--virtual-time-budget={extra_wait}", f"--screenshot={dst}", url]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    return r.returncode, (r.stderr or b"").decode("utf-8", "replace")[-600:]


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 1400
    t0 = time.time()
    rc, err = shot(src, dst, w, h)
    ok = dst.exists()
    print(f"rc={rc} ok={ok} size={dst.stat().st_size if ok else 0} in {time.time()-t0:.1f}s")
    if err.strip():
        print(err)
