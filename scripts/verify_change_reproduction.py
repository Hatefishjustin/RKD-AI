"""Real browser workflow, separate process restart, package and backup checks."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.local_backup import create_backup, restore_backup


def main():
    runtime = ROOT / "var/evidence/change-reproduction" / (datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6])
    runtime.mkdir(parents=True)
    database = runtime / "app.sqlite3"
    SQLiteStore(database).close()
    process = None
    report = {"passed": False, "runtime": str(runtime), "processes": []}

    def start():
        nonlocal process
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve_isolated.py"), "--database", str(database)], stdout=subprocess.PIPE, stderr=log, text=True)
        info = json.loads(process.stdout.readline())
        report["processes"].append(info)
        return f"http://127.0.0.1:{info['port']}"

    def stop():
        nonlocal process
        if process:
            process.terminate()
            process.wait(timeout=20)
            process.stdout.close()
            process = None

    with (runtime / "server.log").open("w", encoding="utf-8") as log:
        try:
            for restart in (False, True):
                url = start()
                with (runtime / ("browser-restart.log" if restart else "browser.log")).open("w", encoding="utf-8") as browser_log:
                    result = subprocess.run(["node", str(ROOT / "scripts/verify_change_browser.cjs"), *(["--restart"] if restart else [])],
                                            env={**os.environ, "RKD_QA_URL": url, "RKD_QA_EVIDENCE_DIR": str(runtime)}, stdout=browser_log, stderr=subprocess.STDOUT, timeout=150)
                stop()
                if result.returncode:
                    raise RuntimeError("browser verification failed; see browser log")
            browser = json.loads((runtime / "browser.json").read_text(encoding="utf-8"))
            production = browser["final"]
            package = runtime / f"production-v{production['revision_no']}.zip"
            with zipfile.ZipFile(package) as archive:
                manifest = json.loads(archive.read(f"manifest-v{production['revision_no']}.json"))
                for item in manifest["files"]:
                    assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
                assert manifest["quantity_item_ids"] == [q["quantity_item_id"] for q in production["quantities"]]
            backup = create_backup(database, runtime / "production-backup.zip", ROOT, baseline_files=["requirements.lock"])
            restored = restore_backup(runtime / "production-backup.zip", runtime / "production-restored")
            report.update({"passed": True, "browser": {"project_id": browser["project_id"], "quantity": production["quote"]["quantity"], "gross": production["quote"]["sale_gross"], "old_files_unchanged": browser["old_files_unchanged"], "views": browser["views"]},
                           "change": browser["applied"], "change_views": browser["changeViews"], "package_hashes_verified": True, "production_backup_files": backup["runtime_files"], "production_restore": restored})
        finally:
            stop()
            (runtime / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
