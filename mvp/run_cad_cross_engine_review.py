from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.cad_cross_engine_review import CadCrossEngineReviewBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Match DXF and DWG plan candidates by preserved CAD handles.")
    parser.add_argument("--dxf-review", required=True, type=Path)
    parser.add_argument("--dwg-plan-candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--direct-tolerance-mm", type=float, default=0.01)
    parser.add_argument("--arc-tolerance-mm", type=float, default=0.5)
    args = parser.parse_args()
    result = CadCrossEngineReviewBuilder().build(
        json.loads(args.dxf_review.read_text(encoding="utf-8")),
        json.loads(args.dwg_plan_candidates.read_text(encoding="utf-8")),
        direct_tolerance_mm=args.direct_tolerance_mm,
        arc_tolerance_mm=args.arc_tolerance_mm,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
