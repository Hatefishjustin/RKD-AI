from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.dxf_intake import DxfSecondaryValidator, compare_dxf_to_dwg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read an ASCII DXF summary and optionally compare it with a DWG inspection."
    )
    parser.add_argument("--dxf", required=True, type=Path)
    parser.add_argument("--source-asset-id", required=True)
    parser.add_argument("--dwg-inspection", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    dxf = DxfSecondaryValidator().parse(args.dxf)
    comparison = None
    status = dxf["status"]
    reference_dwg_sha256 = None
    source_relationship_status = "not-specified"
    if args.dwg_inspection:
        dwg = json.loads(args.dwg_inspection.read_text(encoding="utf-8"))
        reference_dwg_sha256 = dwg.get("sha256")
        source_relationship_status = "registered-reference-unverified"
        try:
            comparison = compare_dxf_to_dwg(dxf, dwg)
            status = comparison["comparison_status"]
        except (KeyError, TypeError, ValueError) as error:
            status = "comparison-blocked"
            comparison = None
            dxf["warnings"].append({"code": "COMPARISON_BLOCKED", "message": str(error)})

    result = {
        "contract_version": "1.0",
        "source_asset_id": args.source_asset_id,
        "reference_dwg_sha256": reference_dwg_sha256,
        "source_relationship_status": source_relationship_status,
        "dxf": dxf,
        "comparison": comparison,
        "status": status,
        "warnings": [
            {
                "code": "DXF_DOES_NOT_REPLACE_DWG",
                "message": "The DXF is a separate source and does not overwrite the registered DWG or its derived artifacts.",
            },
            {
                "code": "PROFESSIONAL_CONFIRMATION_REQUIRED",
                "message": "Do not use this report as approval for construction drawings, quantities, pricing, or site setting-out.",
            },
        ],
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
