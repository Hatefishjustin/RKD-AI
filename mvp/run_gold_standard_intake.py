from __future__ import annotations

import argparse
import json
from pathlib import Path

from rkd_mvp.gold_standard_intake import GoldStandardInventoryBuilder


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a read-only, privacy-aware inventory for a historical project package."
    )
    parser.add_argument("--source-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = args.source_directory.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Output must be outside the read-only historical source directory.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = GoldStandardInventoryBuilder().build(source, config)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
