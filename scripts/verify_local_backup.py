"""Read-only daily snapshot and actual HTTP recovery/authentication rehearsal."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.local_backup import create_backup, restore_backup
from rkd_mvp.sqlite_store import SQLiteStore


def main():
    runtime = ROOT / "var/evidence/local-backup" / (datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6])
    runtime.mkdir(parents=True)
    report = {"passed": False, "runtime": str(runtime), "processes": []}
    process = None

    def start(database, app=ROOT):
        nonlocal process, port
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve_isolated.py"), "--database", str(database), "--application", str(app)], stdout=subprocess.PIPE, stderr=log, text=True)
        info = json.loads(process.stdout.readline())
        report["processes"].append(info)
        port = info["port"]

    def stop():
        nonlocal process
        if process:
            process.terminate()
            process.wait(timeout=20)
            process.stdout.close()
            process = None

    def request(method, path, body=None, cookie=None, expected=200):
        connection = HTTPConnection("127.0.0.1", port, timeout=20)
        try:
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = cookie
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            data, headers = response.read(), dict(response.getheaders())
            assert response.status == expected, (response.status, data[:200])
            return data, headers
        finally:
            connection.close()

    port = None
    with (runtime / "server.log").open("w", encoding="utf-8") as log:
        try:
            # Daily database is read-only throughout creation. Full application
            # sources, seed fixtures and built frontend are in this archive.
            backup = create_backup(ROOT / "var/app.sqlite3", runtime / "daily-complete.zip", ROOT)
            (runtime / "backup-manifest.json").write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
            destination = runtime / "daily-restored"
            restored = restore_backup(runtime / "daily-complete.zip", destination)
            (runtime / "daily-restore.json").write_text(json.dumps(restored, ensure_ascii=False, indent=2), encoding="utf-8")
            start(destination / "runtime/app.sqlite3", destination / "application")
            projects = json.loads(request("GET", "/api/v1/projects")[0])["items"]
            assert projects
            downloads = 0
            for project in projects:
                base = f"/api/v1/projects/{project['project_id']}"
                request("GET", base)
                for suffix in ("/jobs", "/issues", "/estimates", "/spatial", "/requirements", "/design", "/procurement/orders", "/changes"):
                    request("GET", base + suffix)
                for asset in json.loads(request("GET", base + "/files")[0])["items"]:
                    data = request("GET", asset["download_url"])[0]
                    assert hashlib.sha256(data).hexdigest() == asset["sha256"]
                    downloads += 1
                for floor in json.loads(request("GET", base + "/spatial")[0])["items"]:
                    for artifact in floor["artifacts"]:
                        data = request("GET", artifact["download_url"])[0]
                        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
                        downloads += 1
                design = json.loads(request("GET", base + "/design")[0])["item"]
                if design:
                    for artifact in design["artifacts"]:
                        data = request("GET", artifact["download_url"])[0]
                        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
                        downloads += 1
            stop()
            start(destination / "runtime/app.sqlite3", destination / "application")
            assert json.loads(request("GET", "/api/v1/projects")[0])["items"] == projects
            stop()
            report["daily"] = {"tables_verified": restored["tables_verified"], "runtime_files_verified": restored["runtime_files_verified"],
                              "application_files_verified": restored["application_files_verified"], "projects_http": len(projects),
                              "downloads_http": downloads, "restore_seconds": restored["duration_seconds"], "snapshot_at": restored["snapshot_at"],
                              "archived_application_served": True, "process_restart_verified": True}
            # Separate account data; never initialize accounts in the daily DB.
            auth_root = runtime / "identity-source"
            auth_root.mkdir()
            database = auth_root / "app.sqlite3"
            store = SQLiteStore(database)
            service = ApiService(MVPApp(store), file_service=FileService(database, auth_root))
            service.create_project("org-local", "恢复账号测试", "recovery-auth")
            data = b"%PDF-1.4 recovery auth test %%EOF"
            upload = service.initiate_upload("org-local", "recovery-auth", {"filename": "test.pdf", "size_bytes": len(data)})
            service.receive_upload("org-local", "recovery-auth", upload["upload_id"], io.BytesIO(data), len(data))
            asset = service.complete_upload("org-local", "recovery-auth", upload["upload_id"], hashlib.sha256(data).hexdigest())
            provider, password = AccountIdentityProvider(database), secrets.token_urlsafe(30)
            provider.bootstrap("recovery-admin", "恢复测试管理员", password)
            token, _ = provider.login("recovery-admin", password, "isolated")
            identity = provider.authenticate({"Cookie": f"rkd_session={token}"})
            user = provider.create_user(identity, {"username": "recovery-viewer", "display_name": "恢复测试只读", "password": password})
            provider.set_member(identity, "recovery-auth", {"user_id": user["user_id"], "role": "viewer"})
            store.close()
            create_backup(database, runtime / "identity.zip", ROOT, baseline_files=["requirements.lock"])
            identity_target = runtime / "identity-restored"
            identity_report = restore_backup(runtime / "identity.zip", identity_target)
            start(identity_target / "runtime/app.sqlite3")
            request("GET", "/api/v1/projects", cookie=f"rkd_session={token}", expected=401)
            _, headers = request("POST", "/api/v1/auth/login", {"username": "recovery-viewer", "password": password})
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            projects = json.loads(request("GET", "/api/v1/projects", cookie=cookie)[0])["items"]
            assert len(projects) == 1 and projects[0]["role"] == "viewer"
            files = json.loads(request("GET", "/api/v1/projects/recovery-auth/files", cookie=cookie)[0])["items"]
            assert request("GET", files[0]["download_url"], cookie=cookie)[0] == data
            request("POST", "/api/v1/projects/recovery-auth/spatial/revisions", {}, cookie=cookie, expected=403)
            stop()
            report["identity"] = {"old_session_rejected": True, "password_and_role_retained": True, "authenticated_download": True,
                                  "viewer_write_rejected": True, "sessions_invalidated": identity_report["sessions_invalidated"]}
            report["passed"] = True
        finally:
            stop()
            (runtime / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
