from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.dxf_geometry_review import DxfGeometryReviewBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare direct DXF model evidence with DWG plan candidates.")
    parser.add_argument("--dxf", required=True, type=Path)
    parser.add_argument("--plan-candidates", required=True, type=Path)
    parser.add_argument("--dwg-plan-candidates", required=True, type=Path)
    parser.add_argument("--semantic-rules", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = DxfGeometryReviewBuilder().build(
        args.dxf,
        json.loads(args.plan_candidates.read_text(encoding="utf-8")),
        json.loads(args.semantic_rules.read_text(encoding="utf-8")),
        json.loads(args.dwg_plan_candidates.read_text(encoding="utf-8")),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
