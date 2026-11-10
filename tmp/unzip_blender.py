import sys, time, zipfile
from pathlib import Path

zip_path = Path(r"D:\Github\RKD AI\tools\blender\blender-4.2.9-windows-x64.zip")
dest = Path(r"D:\Github\RKD AI\tools\blender")
log = Path(r"D:\Github\RKD AI\tmp\unzip_blender.log")

lines = []
t0 = time.time()
lines.append(f"zip={zip_path} size={zip_path.stat().st_size}")
try:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        lines.append(f"entries={len(names)} first={names[0] if names else None}")
        zf.extractall(dest)
    lines.append(f"OK extract {time.time()-t0:.1f}s")
except Exception as exc:
    lines.append(f"FAIL {type(exc).__name__}: {exc}")

exe = list(dest.glob("blender-*/blender.exe"))
lines.append("exe=" + str(exe))
log.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
