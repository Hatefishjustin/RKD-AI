from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.cad_topology_review import CadTopologyReviewBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Create category-specific CAD topology review work.")
    parser.add_argument("--plan-candidates", required=True, type=Path)
    parser.add_argument("--object-groups", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    candidates = json.loads(args.plan_candidates.read_text(encoding="utf-8"))
    groups = json.loads(args.object_groups.read_text(encoding="utf-8"))
    result = CadTopologyReviewBuilder().build(candidates, groups)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
