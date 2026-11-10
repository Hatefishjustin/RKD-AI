"""Local operator entry: backup / restore to a new isolated directory."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.local_backup import create_backup, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--database", default=os.environ.get("RKD_MVP_DB_PATH", str(ROOT / "var/app.sqlite3")))
    backup.add_argument("--output")
    restore = sub.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("destination")
    args = parser.parse_args()
    if args.command == "backup":
        database = Path(args.database)
        if not database.is_absolute():
            database = ROOT / database
        output = args.output or ROOT / "var/backups" / (datetime.now(timezone.utc).strftime("complete-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6] + ".zip")
        result = create_backup(database, output, ROOT)
        # The archive contains the detailed inventory; keep console output compact.
        result = {key: value for key, value in result.items() if key not in {"files", "tables"}}
    else:
        result = restore_backup(args.archive, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
