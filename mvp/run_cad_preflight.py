from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rkd_mvp.cad_intake import DwgIntakeAdapter, LibreDwgParser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a DWG source before geometry parsing.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source-asset-id", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--source-locator")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--libredwg-home",
        type=Path,
        help="Optional directory containing dwgread.exe and dwglayers.exe.",
    )
    parser.add_argument("--parser-timeout-seconds", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    geometry_parser = None
    if args.libredwg_home:
        geometry_parser = LibreDwgParser(args.libredwg_home, args.parser_timeout_seconds)
    inspection = DwgIntakeAdapter(geometry_parser).inspect(
        args.input,
        args.source_asset_id,
        expected_sha256=args.expected_sha256,
        source_locator=args.source_locator,
    )
    rendered = json.dumps(inspection.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    else:
        sys.stdout.write(rendered)
    if inspection.intake_status == "rejected":
        return 2
    if inspection.intake_status == "geometry-parse-failed":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
