from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rkd_mvp.cad_semantics import CadLayerSemanticMapper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Map parsed CAD layers into versioned domain categories.")
    parser.add_argument("--inspection", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inspection = json.loads(args.inspection.read_text(encoding="utf-8"))
    result = CadLayerSemanticMapper.from_file(args.rules).map_inspection(inspection)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

