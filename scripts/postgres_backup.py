"""Explicit trusted maintenance CLI; credentials only in the process environment."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.postgres_backup import create_postgres_backup, restore_postgres_backup
from rkd_mvp.local_backup import BackupRejected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--binary-directory", type=Path, default=ROOT / "var/tools/postgresql-17.11-5/pgsql/bin")
    args = parser.parse_args()
    dsn = os.environ.get("RKD_POSTGRES_MAINTENANCE_DSN")
    if not dsn:
        parser.error("Set RKD_POSTGRES_MAINTENANCE_DSN to an explicit loopback maintenance connection; no application fallback")
    try:
        if args.action == "backup":
            runtime = os.environ.get("RKD_POSTGRES_RUNTIME")
            if not runtime:
                parser.error("Set RKD_POSTGRES_RUNTIME to the matching PostgreSQL runtime")
            archive = args.archive or (ROOT / "var/backups" / datetime.now(timezone.utc).strftime("postgres-complete-%Y%m%dT%H%M%S-%f.zip"))
            report = create_postgres_backup(dsn, runtime, archive, ROOT, args.binary_directory)
        else:
            if not args.archive or not args.destination:
                parser.error("restore requires --archive and --destination; the target DSN must select an empty application database")
            report = restore_postgres_backup(args.archive, dsn, args.destination, args.binary_directory,
                                             application_role=os.environ.get("RKD_POSTGRES_APP_ROLE"))
    except BackupRejected as error:
        raise SystemExit(str(error)) from None
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
