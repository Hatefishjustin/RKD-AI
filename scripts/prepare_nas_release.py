"""Build a byte-verified NAS candidate from a complete, consistent local backup."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "mvp"))
from rkd_mvp.local_backup import create_backup, restore_backup


def main():
    release = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    evidence = ROOT / "var/evidence/m5-nas" / release
    evidence.mkdir(parents=True)
    backup = create_backup(ROOT / "var/app.sqlite3",evidence / "complete-local.zip",ROOT)
    restored = restore_backup(evidence / "complete-local.zip",evidence / "snapshot")
    entries = {}
    output = evidence / ("rkd-ai-" + release + ".zip")
    with zipfile.ZipFile(output,"x",zipfile.ZIP_DEFLATED) as archive:
        for prefix, folder in (("application",evidence / "snapshot/application"),("snapshot/runtime",evidence / "snapshot/runtime")):
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    name = prefix + "/" + path.relative_to(folder).as_posix()
                    content = path.read_bytes()
                    entries[name] = {"sha256":hashlib.sha256(content).hexdigest(),"size_bytes":len(content)}
                    archive.writestr(name,content)
        manifest = {"release":release,"snapshot_at":backup['snapshot_at'],"runtime_files":backup['runtime_files'],
                    "files":entries,"authoritative_cutover":False,"formal_publication":False}
        archive.writestr("deployment-release.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    shutil.copyfile(ROOT / "scripts/deploy/host_prepare.py",evidence / "host_prepare.py")
    report = {"release":release,"archive":str(output),"sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
              "size_bytes":output.stat().st_size,"snapshot_at":backup['snapshot_at'],"runtime_files":backup['runtime_files'],
              "application_files":backup['application_files'],"restore":restored,"authoritative_cutover":False}
    (evidence / "release-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
