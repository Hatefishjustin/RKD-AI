"""Inspect downloaded M3 files and screenshot pixels using the bundled QA runtime."""
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.dxf_intake import DxfSecondaryValidator


def main():
    folder = Path(os.environ.get("RKD_QA_EVIDENCE_DIR", str(ROOT / "var/evidence/m3")))
    record = json.loads((folder / "browser-verification.json").read_text(encoding="utf-8"))
    design = record["final_design"]
    package = next(a for a in design["artifacts"] if a["artifact_kind"] == "package_zip")
    with zipfile.ZipFile(folder / package["filename"]) as archive:
        assert len(archive.namelist()) == 6
        manifest = json.loads(archive.read("manifest-v3.json"))
        snapshot = json.loads(archive.read("model-v3.json"))
        assert snapshot["model"] == design["model"]
        assert snapshot["baseline"]["input_hash"] == design["input_hash"] == manifest["input_hash"]
        for file in manifest["files"]:
            data = archive.read(file["filename"])
            assert len(data) == file["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == file["sha256"]
            assert data == (folder / file["filename"]).read_bytes()
        rows = list(csv.DictReader(io.StringIO(archive.read("zones-v3.csv").decode("utf-8-sig"))))
        assert sum(Decimal(row["area"]) for row in rows) == Decimal("104.00")
        assert all(row["unit"] == "m²" and row["design_revision_id"] == design["design_revision_id"] for row in rows)
        svg = ET.fromstring(archive.read("layout-v3.svg"))
        metadata = json.loads(svg.find("{http://www.w3.org/2000/svg}metadata").text)
        assert metadata["design_revision_id"] == design["design_revision_id"]
    dxf = DxfSecondaryValidator().parse(folder / "layout-v3.dxf")
    assert dxf["drawing_units"]["name"] == "meters"
    assert dxf["entities"]["entity_counts"]["LWPOLYLINE"] == 5
    assert dxf["entities"]["geometry_extents"]["maximum"] == [16.0, 8.0]
    pixels = {}
    for name in ("desktop-confirm-drawing.png", "mobile-confirm-drawing.png"):
        with Image.open(folder / name) as image:
            counts = Counter(image.convert("RGB").get_flattened_data())
            colored = [counts[color] for color in ((222, 240, 232), (232, 237, 248), (247, 234, 214))]
            assert min(colored) > 500, (name, colored)
            pixels[name] = {"size": image.size, "zone_color_pixels": colored, "nonblank": True}
    result = {"passed": True, "design_revision_id": design["design_revision_id"], "package_entries": 6, "manifest_hashes_verified": len(manifest["files"]), "csv_area_m2": "104.00", "dxf_units": "meters", "dxf_polylines": 5, "dxf_geometry_max": [16, 8], "screenshots": pixels}
    (folder / "artifact-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
