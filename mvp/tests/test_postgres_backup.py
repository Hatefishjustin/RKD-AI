"""Reject damaged or path-hostile recovery packages before database access."""
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from rkd_mvp.local_backup import BackupRejected
from rkd_mvp.postgres_backup import FORMAT, _extract


class PostgresArchiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def archive(self, name, members, *, recorded=None):
        manifest = {"schema_version":FORMAT,"database":"database/rkd.dump","files":{
            key:{"size_bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            for key,data in (recorded or members)}}
        target = self.root / name
        with zipfile.ZipFile(target,"x") as archive:
            archive.writestr("manifest.json",json.dumps(manifest))
            for key,data in members:
                archive.writestr(key,data)
        return target

    def test_corrupted_bytes_and_sizes_are_rejected(self):
        original = [("database/rkd.dump",b"PGDMP-original")]
        for index,data in enumerate((b"PGDMP-changed!",b"short")):
            archive = self.archive(str(index)+".zip",[(original[0][0],data)],recorded=original)
            with self.assertRaises(BackupRejected):
                _extract(archive,self.root / ("stage"+str(index)))

    def test_traversal_windows_aliases_and_undeclared_files_are_rejected(self):
        for index,name in enumerate(("runtime/../../escaped", "runtime/C:/escaped", "runtime/CON/file", "runtime/file. ")):
            archive = self.archive(str(index)+".zip",[("database/rkd.dump",b"dump"),(name,b"do not write")])
            with self.assertRaises(BackupRejected):
                _extract(archive,self.root / ("stage"+str(index)))
        self.assertFalse((self.root / "escaped").exists())
        archive = self.archive("undeclared.zip",[("database/rkd.dump",b"dump"),("runtime/extra",b"extra")],recorded=[("database/rkd.dump",b"dump")])
        with self.assertRaises(BackupRejected):
            _extract(archive,self.root / "undeclared")

    def test_case_collisions_and_symbolic_links_are_rejected(self):
        archive = self.archive("duplicate.zip",[("database/rkd.dump",b"dump"),("runtime/A",b"a"),("runtime/a",b"a")])
        with self.assertRaises(BackupRejected):
            _extract(archive,self.root / "duplicate")
        archive = self.root / "linked.zip"
        with zipfile.ZipFile(archive,"x") as target:
            info = zipfile.ZipInfo("runtime/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target.writestr(info,"../../escaped")
        with self.assertRaises(BackupRejected):
            _extract(archive,self.root / "linked")
