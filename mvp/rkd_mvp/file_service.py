from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .api_service import ApiError, ApiService
from .models import new_id, now_iso
from .file_repository import SQLiteFileRepository


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
NINGBO_PROJECT_ID = "project_ningbo_xiecheng_2026"


class FileService:
    def __init__(self, db_path: Path | None, runtime_root: Path, *, repository=None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self.runtime_root = Path(runtime_root).resolve()
        if self.db_path is None and repository is None:
            raise ValueError("an explicit file repository is required")
        self.repository = repository or SQLiteFileRepository(self._db)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if self.db_path is None:
            raise RuntimeError("SQLite connection is unavailable in PostgreSQL mode")
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _scope_dir(self, organization_id: str, project_id: str) -> Path:
        digest = hashlib.sha256(f"{organization_id}\0{project_id}".encode("utf-8")).hexdigest()[:24]
        return self.runtime_root / "projects" / digest

    def _storage_path(self, storage_key: str) -> Path:
        path = (self.runtime_root / storage_key).resolve()
        if not path.is_relative_to(self.runtime_root):
            raise ApiError(500, "INVALID_STORAGE_KEY", "stored file path is invalid")
        return path

    @staticmethod
    def _verify_bytes(path: Path, expected_size: int, expected_hash: str) -> bool:
        if not path.is_file() or path.stat().st_size != expected_size:
            return False
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == expected_hash.lower()

    @staticmethod
    def _public_file(row: sqlite3.Row) -> dict[str, Any]:
        result = {key: row[key] for key in (
            "file_id", "organization_id", "project_id", "filename", "kind", "content_type",
            "size_bytes", "sha256", "source_kind", "source_ref", "format_status", "created_at", "revision",
        )}
        if hasattr(result["created_at"], "isoformat"):
            result["created_at"] = result["created_at"].isoformat()
        return result

    @staticmethod
    def _format_status(filename: str, header: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        signatures = {
            ".pdf": header.startswith(b"%PDF-"),
            ".jpg": header.startswith(b"\xff\xd8"),
            ".jpeg": header.startswith(b"\xff\xd8"),
            ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
            ".dwg": header.startswith(b"AC1"),
            ".dxf": header.lstrip().startswith(b"0\nSECTION") or header.lstrip().startswith(b"0\r\nSECTION"),
            ".xls": header.startswith(b"\xd0\xcf\x11\xe0"),
            ".xlsx": header.startswith(b"PK\x03\x04"),
        }
        return "signature_checked" if signatures.get(suffix, False) else "format_unverified"

    def initiate(self, organization_id: str, project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        filename = Path(str(request.get("filename", ""))).name.strip()
        try:
            size = int(request.get("size_bytes", 0))
        except (TypeError, ValueError) as error:
            raise ApiError(400, "INVALID_UPLOAD", "size_bytes must be an integer") from error
        if not filename or filename in {".", ".."} or not 0 < size <= MAX_UPLOAD_BYTES:
            raise ApiError(400, "INVALID_UPLOAD", "filename and size_bytes (1 to 100 MiB) are required")
        declared_hash = str(request.get("sha256") or "").lower()
        if declared_hash and (len(declared_hash) != 64 or any(c not in "0123456789abcdef" for c in declared_hash)):
            raise ApiError(400, "INVALID_UPLOAD", "sha256 must be a 64-character hex digest")
        upload_id = new_id("upload")
        with self.repository.transaction(organization_id, project_id, write=True) as transaction:
            transaction.insert_upload({"upload_id": upload_id, "organization_id": organization_id,
                                       "project_id": project_id, "filename": filename, "declared_size": size,
                                       "declared_sha256": declared_hash or None, "status": "initiated", "created_at": now_iso()})
        return {"upload_id": upload_id, "status": "initiated", "upload_url": f"/api/v1/projects/{project_id}/uploads/{upload_id}/content"}

    @staticmethod
    def _required_upload(transaction, upload_id):
        row = transaction.upload(upload_id)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "upload not found")
        return row

    def _upload(self, organization_id: str, project_id: str, upload_id: str):
        with self.repository.transaction(organization_id, project_id) as transaction:
            return self._required_upload(transaction, upload_id)

    def receive(self, organization_id: str, project_id: str, upload_id: str,
                stream: BinaryIO, content_length: int) -> dict[str, Any]:
        staging = self._scope_dir(organization_id, project_id) / "staging" / f"{upload_id}.part"
        created = False
        try:
            # The repository locks this upload until bytes and metadata agree;
            # a competing request cannot delete or replace the active writer.
            with self.repository.transaction(organization_id, project_id, write=True) as transaction:
                upload = self._required_upload(transaction, upload_id)
                if upload["status"] != "initiated":
                    raise ApiError(409, "UPLOAD_STATE", "upload is not waiting for content")
                if content_length > MAX_UPLOAD_BYTES:
                    raise ApiError(413, "UPLOAD_TOO_LARGE", "upload exceeds 100 MiB")
                if content_length != upload["declared_size"] or content_length <= 0:
                    raise ApiError(409, "UPLOAD_SIZE_MISMATCH", "content length differs from upload session")
                staging.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                remaining = content_length
                try:
                    with staging.open("xb") as output:
                        created = True
                        while remaining:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ApiError(400, "INCOMPLETE_UPLOAD", "upload ended before declared size")
                            output.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                except FileExistsError as error:
                    raise ApiError(409, "UPLOAD_STAGING_EXISTS", "staged bytes already exist; start a new upload") from error
                received_hash = digest.hexdigest()
                transaction.stage(upload_id, received_hash)
        except Exception:
            if created:
                staging.unlink(missing_ok=True)
            raise
        return {"upload_id": upload_id, "status": "staged", "received_sha256": received_hash, "received_bytes": content_length}

    def complete(self, organization_id: str, project_id: str, upload_id: str,
                 completed_sha256: str) -> dict[str, Any]:
        staging = self._scope_dir(organization_id, project_id) / "staging" / f"{upload_id}.part"
        destination = None
        published = False
        try:
            with self.repository.transaction(organization_id, project_id, write=True) as transaction:
                upload = self._required_upload(transaction, upload_id)
                if upload["status"] != "staged":
                    raise ApiError(409, "UPLOAD_STATE", "upload has no complete content")
                if not staging.is_file():
                    raise ApiError(409, "UPLOAD_MISSING_CONTENT", "staged bytes are missing")
                with staging.open("rb") as source:
                    actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
                if actual_hash != upload["received_sha256"] or staging.stat().st_size != upload["declared_size"]:
                    raise ApiError(409, "UPLOAD_CONTENT_CHANGED", "staged bytes changed")
                if upload["declared_sha256"] and upload["declared_sha256"] != actual_hash:
                    raise ApiError(409, "UPLOAD_HASH_MISMATCH", "declared hash does not match received bytes")
                if completed_sha256 and completed_sha256.lower() != actual_hash:
                    raise ApiError(409, "UPLOAD_HASH_MISMATCH", "completed hash does not match received bytes")
                file_id = new_id("file")
                destination = self._scope_dir(organization_id, project_id) / "raw" / file_id
                destination.parent.mkdir(parents=True, exist_ok=True)
                with staging.open("rb") as source:
                    format_status = self._format_status(upload["filename"], source.read(4096))
                revision = transaction.next_revision(upload["filename"])
                row = {"file_id": file_id, "organization_id": organization_id, "project_id": project_id,
                       "filename": upload["filename"], "kind": "uploaded_file",
                       "content_type": mimetypes.guess_type(upload["filename"])[0] or "application/octet-stream",
                       "size_bytes": upload["declared_size"], "sha256": actual_hash,
                       "storage_key": destination.relative_to(self.runtime_root).as_posix(), "source_kind": "local_upload",
                       "source_ref": upload_id, "format_status": format_status, "created_at": now_iso(), "revision": revision}
                # No-overwrite publication. Leave staging until commit succeeds,
                # so an ordinary transaction failure can be retried with bytes intact.
                os.link(staging, destination)
                published = True
                transaction.insert_file(row, upload_id)
        except Exception:
            if published:
                destination.unlink(missing_ok=True)
            raise
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass  # Committed immutable raw bytes remain valid; staging is an orphan.
        return {"file_id": file_id, "status": "stored_unparsed", "sha256": actual_hash,
                "size_bytes": upload["declared_size"], "revision": revision}

    def list_files(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as transaction:
            return {"items": [self._public_file(row) for row in transaction.files()]}

    def get_content(self, organization_id: str, project_id: str, file_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as transaction:
            row = transaction.file(file_id)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "file not found")
        path = self._storage_path(row["storage_key"])
        if not self._verify_bytes(path, row["size_bytes"], row["sha256"]):
            raise ApiError(500, "FILE_INTEGRITY", "stored file bytes are missing or changed")
        return self._public_file(row), path

    def list_decisions(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as transaction:
            return {"items": transaction.decisions()}

    def seed_ningbo(self, service: ApiService, fixture_root: Path) -> None:
        manifest = json.loads((fixture_root / "样本清单.json").read_text(encoding="utf-8"))
        organization_id = "org-local"
        project_id = NINGBO_PROJECT_ID
        if (organization_id, project_id) not in service.app.store.projects:
            service.create_project(organization_id, manifest["project_name"], project_id)
        decisions = (
            ("contract_target_gross_cny", "600000.00", "user_confirmed", "source_workbook_labels_discounted_price_before_tax"),
            ("trial_tax_rate", "0.05", "user_confirmed_trial", "source_manifest_rate_pending"),
            ("construction_cost_markup", "0.20", "user_confirmed", None),
            ("design_cost_markup", "0.60", "user_confirmed", None),
            ("excluded_scopes", ["mep", "fire_protection"], "user_confirmed", None),
        )
        with self._db() as connection:
            for key, value, status, conflict in decisions:
                connection.execute(
                    "INSERT OR IGNORE INTO project_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (organization_id, project_id, key, json.dumps(value, ensure_ascii=False),
                     "user-confirmed-2026-09-29", status, conflict, now_iso()),
                )
        for asset in manifest["assets"]:
            source = (fixture_root / asset["path"]).resolve()
            if not source.is_relative_to(fixture_root.resolve()) or not source.is_file():
                raise RuntimeError(f"invalid seed source: {asset['path']}")
            with self._db() as connection:
                row = connection.execute(
                    "SELECT * FROM file_assets WHERE organization_id = ? AND project_id = ? "
                    "AND source_kind = 'seed_fixture' AND source_ref = ?",
                    (organization_id, project_id, asset["asset_id"]),
                ).fetchone()
            if row:
                existing = self._storage_path(row["storage_key"])
                if not self._verify_bytes(existing, row["size_bytes"], row["sha256"]):
                    raise RuntimeError(f"seed bytes missing or changed in runtime: {asset['asset_id']}")
                continue
            file_id = new_id("file")
            destination = self._scope_dir(organization_id, project_id) / "raw" / file_id
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".part")
            digest = hashlib.sha256()
            length = 0
            with source.open("rb") as input_file, temporary.open("xb") as output:
                while chunk := input_file.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
            if digest.hexdigest().upper() != asset["sha256"].upper() or length != asset["size_bytes"]:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"seed hash or size mismatch: {asset['asset_id']}")
            os.replace(temporary, destination)
            with self._db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                revision = connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) + 1 FROM file_assets "
                    "WHERE organization_id = ? AND project_id = ? AND filename = ?",
                    (organization_id, project_id, source.name),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO file_assets(file_id, organization_id, project_id, filename, kind, content_type, "
                    "size_bytes, sha256, storage_key, source_kind, source_ref, format_status, created_at, revision) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (file_id, organization_id, project_id, source.name, asset["kind"],
                     mimetypes.guess_type(source.name)[0] or "application/octet-stream", length,
                     digest.hexdigest(), destination.relative_to(self.runtime_root).as_posix(),
                     "seed_fixture", asset["asset_id"], "source_manifest_verified", now_iso(), revision),
                )
