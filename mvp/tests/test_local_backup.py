from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.local_backup import BackupRejected, application_files, create_backup, restore_backup
from rkd_mvp.sqlite_store import SQLiteStore


class LocalBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.database = self.runtime / "app.sqlite3"
        self.store = SQLiteStore(self.database)
        self.service = ApiService(MVPApp(self.store), file_service=FileService(self.database, self.runtime))
        self.service.create_project("org-local", "备份测试项目", "backup-project")
        data = b"%PDF-1.4 backup real bytes %%EOF"
        upload = self.service.initiate_upload("org-local", "backup-project", {"filename": "source.pdf", "size_bytes": len(data)})
        self.service.receive_upload("org-local", "backup-project", upload["upload_id"], io.BytesIO(data), len(data))
        self.file = self.service.complete_upload("org-local", "backup-project", upload["upload_id"], hashlib.sha256(data).hexdigest())
        self.spatial = self.service.create_spatial_revision("org-local", "backup-project", {"width": "10", "length": "5", "pricing": {"unit_cost_net": "100"}}, "backup-test")
        self.app = self.root / "application"
        self.app.mkdir()
        (self.app / "requirements.lock").write_text("# test baseline", encoding="utf-8")
        self.archive = self.root / "backup.zip"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def backup(self):
        return create_backup(self.database, self.archive, self.app, baseline_files=["requirements.lock"])

    def test_complete_restore_preserves_sources_revisions_roles_and_revokes_sessions(self):
        auth = AccountIdentityProvider(self.database)
        password = "Backup test passphrase 2026"
        auth.bootstrap("admin", "测试管理员", password)
        token, _ = auth.login("admin", password, "local-test")
        identity = auth.authenticate({"Cookie": f"rkd_session={token}"})
        user = auth.create_user(identity, {"username": "viewer", "display_name": "测试只读", "password": password})
        auth.set_member(identity, "backup-project", {"user_id": user["user_id"], "role": "viewer"})
        self.service.initiate_upload("org-local", "backup-project", {"filename": "unfinished.pdf", "size_bytes": 10})
        backup = self.backup()
        restored = self.root / "restored"
        report = restore_backup(self.archive, restored)
        self.assertEqual((backup["runtime_files"], report["runtime_files_verified"], report["sessions_invalidated"]), (7, 7, 1))
        recovered_auth = AccountIdentityProvider(restored / "runtime/app.sqlite3")
        with self.assertRaises(ApiError):
            recovered_auth.authenticate({"Cookie": f"rkd_session={token}"})
        new_token, _ = recovered_auth.login("viewer", password, "recovered")
        recovered_identity = recovered_auth.authenticate({"Cookie": f"rkd_session={new_token}"})
        self.assertEqual(recovered_auth.list_members(recovered_identity, "backup-project")["items"][0]["role"], "viewer")
        with closing(sqlite3.connect(restored / "runtime/app.sqlite3")) as db:
            row = db.execute("SELECT width_text,area_m2_text FROM geometry_revisions").fetchone()
            self.assertEqual(row, ("10", "50.00"))
            self.assertEqual(db.execute("SELECT status FROM file_uploads WHERE filename='unfinished.pdf'").fetchone()[0], "failed")
        # Restoring must not invalidate the original runtime's own sessions.
        self.assertEqual(auth.authenticate({"Cookie": f"rkd_session={token}"}).actor_id, identity.actor_id)
        self.assertEqual((restored / "application/requirements.lock").read_bytes(), (self.app / "requirements.lock").read_bytes())

    def test_backup_rejects_modified_runtime_bytes_and_does_not_publish_package(self):
        _, path = self.service.get_spatial_artifact("org-local", "backup-project", self.spatial["artifacts"][0]["artifact_id"])
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(BackupRejected, "hash/size"):
            self.backup()
        self.assertFalse(self.archive.exists())

    def test_restore_rejects_corrupt_content_before_publishing_destination(self):
        self.backup()
        altered = self.root / "altered.zip"
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(altered, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == "application/requirements.lock":
                    data = bytes([data[0] ^ 1]) + data[1:]
                target.writestr(name, data)
        destination = self.root / "restored"
        with self.assertRaisesRegex(BackupRejected, "hash mismatch"):
            restore_backup(altered, destination)
        self.assertFalse(destination.exists())

    def test_restore_refuses_traversal_and_case_collisions(self):
        for members in (("../escape",), ("runtime/A", "runtime/a"), ("runtime/CON.txt",)):
            with self.subTest(members=members):
                bad = self.root / (str(len(list(self.root.glob('bad*')))) + "bad.zip")
                with zipfile.ZipFile(bad, "w") as archive:
                    for name in members:
                        archive.writestr(name, b"bad")
                with self.assertRaises(BackupRejected):
                    restore_backup(bad, self.root / "refused")
                self.assertFalse((self.root / "escape").exists())

    def test_restore_and_backup_refuse_existing_targets(self):
        self.backup()
        original = self.archive.read_bytes()
        with self.assertRaises(BackupRejected):
            self.backup()
        self.assertEqual(self.archive.read_bytes(), original)
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "keep").write_bytes(b"user data")
        with self.assertRaises(BackupRejected):
            restore_backup(self.archive, destination)
        self.assertEqual((destination / "keep").read_bytes(), b"user data")

    def test_uncommitted_sqlite_changes_are_not_in_snapshot(self):
        with closing(sqlite3.connect(self.database)) as other:
            other.execute("UPDATE projects SET name='uncommitted'")
            self.backup()
            other.rollback()
        destination = self.root / "restored"
        restore_backup(self.archive, destination)
        with closing(sqlite3.connect(destination / "runtime/app.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT name FROM projects").fetchone()[0], "备份测试项目")

    def test_recovered_application_without_git_has_a_reusable_baseline(self):
        (self.app / "mvp").mkdir()
        (self.app / "mvp/run_api_server.py").write_text("# app baseline", encoding="utf-8")
        (self.app / "mvp/.env.secret").write_text("secret", encoding="utf-8")
        self.assertEqual(application_files(self.app), ["mvp/run_api_server.py", "requirements.lock"])


if __name__ == "__main__":
    unittest.main()
