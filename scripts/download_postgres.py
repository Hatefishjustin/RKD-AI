"""Fetch the pinned EDB archive in resumable ranges; verify its full SHA-256."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1] / "var/tools/postgresql-17.11-5"
URL = "https://get.enterprisedb.com/postgresql/postgresql-17.11-5-windows-x64-binaries.zip"
SIZE = 381531864
DIGEST = "80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f"
ARCHIVE = ROOT / URL.rsplit("/", 1)[1]


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    current = ARCHIVE.stat().st_size if ARCHIVE.exists() else 0
    if current > SIZE:
        raise RuntimeError("existing download is larger than the pinned archive")
    if current != SIZE:
        ranges = []
        for start in range(current, SIZE, 32 * 1024 * 1024):
            end = min(start + 32 * 1024 * 1024, SIZE) - 1
            ranges.append((start, end, ROOT / f"segment-{start}-{end}.part"))

        def fetch(item):
            start, end, path = item
            if not path.exists() or path.stat().st_size != end - start + 1:
                subprocess.run(["curl.exe", "--silent", "--show-error", "--fail", "--location",
                                "--retry", "3", "--retry-all-errors", "--connect-timeout", "20",
                                "--speed-time", "30", "--speed-limit", "1024", "--max-time", "300",
                                "--range", f"{start}-{end}", "--output", str(path), URL], check=True)
            if path.stat().st_size != end - start + 1:
                raise RuntimeError("EDB response range size mismatch")
            print(f"Downloaded PostgreSQL range {start}-{end}", flush=True)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch, ranges))
        temporary = ROOT / "assembled.zip"
        with temporary.open("wb") as output:
            if current:
                with ARCHIVE.open("rb") as source:
                    shutil.copyfileobj(source, output)
            for _, _, path in ranges:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, output)
        with temporary.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != DIGEST:
                raise RuntimeError("PostgreSQL archive checksum mismatch; download retained")
        temporary.replace(ARCHIVE)
    with ARCHIVE.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != DIGEST:
            raise RuntimeError("PostgreSQL archive checksum mismatch")
    print("PostgreSQL archive SHA-256 verified", flush=True)


if __name__ == "__main__":
    main()
