"""Fetch CC0 assets (Poly Haven) into tools/assets/, and record provenance.

Everything Poly Haven publishes is CC0 (public domain, commercial use allowed).
Binaries stay under tools/assets/ (git-ignored); the provenance manifest is
written to assets/CC0-素材清单.json which IS committed.

    python scripts/fetch_cc0_assets.py [--only textures|models] [--check]
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tools" / "assets"
MANIFEST = ROOT / "assets" / "CC0-素材清单.json"
API = "https://api.polyhaven.com"

TEXTURES = {
    # key in the design data -> poly haven id
    "floor_microcement": "white_plaster_rough_01",
    "wall_plaster": "painted_plaster_wall",
    "oak": "white_oak_veneer",
    "walnut": "rosewood_veneer_02",
    "stone": "marble_01",
    "fabric": "wool_boucle",
}

MODELS = [
    "sofa_02",
    "modern_arm_chair_01",
    "modern_coffee_table_01",
    "dining_table",
    "dining_chair_02",
    "potted_plant_01",
    "bar_chair_round_01",
    "round_wooden_table_01",
    "ceramic_vase_01",
    "wooden_bowl_01",
]


def get_json(url: str) -> dict:
    out = subprocess.run(["curl.exe", "-s", "--max-time", "40", url],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"GET failed: {url}")
    return json.loads(out.stdout)


def download(url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        r = subprocess.run(["curl.exe", "-sL", "--max-time", "180", "-o", str(dest), url],
                           capture_output=True, text=True, errors="replace")
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            if dest.exists():
                dest.unlink()
            raise RuntimeError(f"download failed: {url}")
    data = dest.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def pick_level(files: dict, want: str = "1k") -> str:
    """`files` is either {"Diffuse": {"1k": ...}} or {"1k": {...}}."""
    levels = {k for k in files if re.fullmatch(r"\d+k", k)}
    if not levels:
        for group in files.values():
            if isinstance(group, dict):
                levels |= {k for k in group if re.fullmatch(r"\d+k", k)}
    if want in levels:
        return want
    return sorted(levels, key=lambda s: int(s[:-1]))[0]


def texture_urls(files: dict, level: str) -> dict:
    out = {}
    for key in ("Diffuse", "nor_gl", "Rough", "AO"):
        group = files.get(key)
        if not isinstance(group, dict):
            continue
        lv = group.get(level)
        if not lv or "jpg" not in lv:
            continue
        out[key] = lv["jpg"]["url"]
    return out


def fetch_textures(manifest: dict) -> None:
    for slot, pid in TEXTURES.items():
        files = get_json(f"{API}/files/{pid}")
        level = pick_level(files)
        urls = texture_urls(files, level)
        if "Diffuse" not in urls:
            print(f"  ! {pid}: no diffuse at {level}", file=sys.stderr)
            continue
        folder = ASSETS / "pbr" / slot
        rows = {}
        for key, url in urls.items():
            name = url.rsplit("/", 1)[-1]
            size, sha = download(url, folder / name)
            rows[key] = {"file": name, "bytes": size, "sha256": sha, "url": url}
            print(f"  {slot:18s} {key:8s} {size/1024:8.0f} KB  {name}")
        info = get_json(f"{API}/info/{pid}")
        manifest["textures"][slot] = {
            "polyhaven_id": pid,
            "name": info.get("name", pid),
            "level": level,
            "license": "CC0 1.0",
            "license_url": "https://polyhaven.com/license",
            "authors": info.get("authors", {}),
            "source_page": f"https://polyhaven.com/a/{pid}",
            "files": rows,
        }


def fetch_models(manifest: dict) -> None:
    for pid in MODELS:
      try:
        files = get_json(f"{API}/files/{pid}")
        pkg = files.get("gltf", {})
        level = pick_level(pkg)
        item = pkg.get(level, {}).get("gltf")
        if not item:
            print(f"  ! {pid}: no gltf at {level}", file=sys.stderr)
            continue
        folder = ASSETS / "models" / pid
        rows = {}
        for rel, meta in item.get("include", {}).items():
            size, sha = download(meta["url"], folder / rel)
            rows[rel] = {"bytes": size, "sha256": sha, "url": meta["url"]}
            print(f"  {pid:24s} {rel:46s} {size/1024:8.0f} KB")
        main = item.get("url")
        size, sha = download(main, folder / f"{pid}.gltf")
        rows[f"{pid}.gltf"] = {"bytes": size, "sha256": sha, "url": main}
        info = get_json(f"{API}/info/{pid}")
        manifest["models"][pid] = {
            "name": info.get("name", pid),
            "level": level,
            "license": "CC0 1.0",
            "license_url": "https://polyhaven.com/license",
            "authors": info.get("authors", {}),
            "source_page": f"https://polyhaven.com/a/{pid}",
            "dimensions_mm": info.get("dimensions"),
            "files": rows,
        }
      except Exception as exc:  # asset without a glTF package, network hiccup, ...
        print(f"  ! {pid}: skipped ({exc})", file=sys.stderr)


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    manifest = {"generated_by": "scripts/fetch_cc0_assets.py",
                "source": "Poly Haven (polyhaven.com)",
                "license_note": "Poly Haven assets are CC0 1.0 — public domain, commercial use allowed, "
                                "no attribution required (credited here anyway).",
                "textures": {}, "models": {}}
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["textures"] = old.get("textures", {})
        manifest["models"] = old.get("models", {})
    if only in (None, "textures"):
        fetch_textures(manifest)
    if only in (None, "models"):
        fetch_models(manifest)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(MANIFEST),
                      "textures": len(manifest["textures"]),
                      "models": len(manifest["models"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
