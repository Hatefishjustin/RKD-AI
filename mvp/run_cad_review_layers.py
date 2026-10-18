from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.cad_intake import LibreDwgParser
from rkd_mvp.cad_review_layers import CadReviewLayerAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Place CAD system-review layers in the localized plan.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--inspection", required=True, type=Path)
    parser.add_argument("--semantic-mapping", required=True, type=Path)
    parser.add_argument("--plan-candidates", required=True, type=Path)
    parser.add_argument("--libredwg-home", required=True, type=Path)
    parser.add_argument("--parser-timeout-seconds", type=int, default=180)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inspection = json.loads(args.inspection.read_text(encoding="utf-8"))
    semantic_mapping = json.loads(args.semantic_mapping.read_text(encoding="utf-8"))
    plan_candidates = json.loads(args.plan_candidates.read_text(encoding="utf-8"))
    payload = LibreDwgParser(args.libredwg_home, args.parser_timeout_seconds).load_payload(args.input)
    result = CadReviewLayerAnalyzer().analyze(
        payload, inspection, semantic_mapping, plan_candidates
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
