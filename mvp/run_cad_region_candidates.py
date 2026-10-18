from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.cad_region_candidates import CadRegionCandidateBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Polygonize floor and ceiling CAD linework candidates.")
    parser.add_argument("--plan-candidates", required=True, type=Path)
    parser.add_argument("--snap-tolerance-mm", type=float, default=2.0)
    parser.add_argument("--minimum-area-m2", type=float, default=0.01)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.plan_candidates.read_text(encoding="utf-8"))
    result = CadRegionCandidateBuilder().build(
        source, args.snap_tolerance_mm, args.minimum_area_m2
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
