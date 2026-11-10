"""AI-DESIGN-01c and DELIVERY-01a/01b: source content + technical draft delivery.

Two independent, explicitly scoped services:

* ``AISourceExtractionService`` reads the immutable stored bytes of an original
  file and records locally locatable text segments, or an explicit unsupported
  reason. It never sends content to a model.
* ``AITechnicalDeliveryService`` derives one technical handover package from
  the currently adopted development package. It never touches the old design /
  production / procurement / release tables.

Both use one explicit SQLite/PostgreSQL repository and one new migration pair
(024/014); already-applied migrations and artifacts are left untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from .models import TenantContext, new_id, now_iso
from .source_content import EXTRACTOR_VERSION, SCHEMA_VERSION, build_extraction, extraction_summary
from .technical_outputs import (HANDOVER_VERSION, OUTPUT_VERSION, generate_technical_outputs)

ROOT = Path(__file__).resolve().parents[2]
EXTRACTION_SCHEMA_PATH = ROOT / "contracts" / "v1" / "ai-source-extraction.schema.json"
HANDOVER_SCHEMA_PATH = ROOT / "contracts" / "v1" / "ai-technical-handover.schema.json"


class AIProfessionalDeliveryError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "items"):
        return dict(value)
    return value


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class _DeliveryTransaction:
    def __init__(self, db: Any, organization_id: str, project_id: str, *, postgres: bool) -> None:
        self.db, self.scope = db, (organization_id, project_id)
        self.postgres = postgres
        prefix = "rkd.ai_" if postgres else "ai_"
        suffix = "" if postgres else "s"
        self.extraction_table = f"{prefix}source_extraction{suffix}"
        self.delivery_table = "rkd.ai_technical_delivery" if postgres else "ai_technical_deliveries"
        self.artifact_table = f"{prefix}technical_artifact{suffix}"

    @property
    def _p(self) -> str:
        return "%s" if self.postgres else "?"

    @property
    def _json_p(self) -> str:
        return "%s::jsonb" if self.postgres else "?"

    @property
    def _time_p(self) -> str:
        return "%s::timestamptz" if self.postgres else "?"

    def _time(self, value: Any) -> Any:
        return datetime.fromisoformat(value) if self.postgres and isinstance(value, str) else value

    def _json_column(self, name: str) -> str:
        return name if self.postgres else f"{name}_json"

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self.db.execute(sql, args)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def extraction_by_key(self, file_id: str, file_sha256: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.extraction_table} WHERE organization_id={self._p} AND project_id={self._p} "
            f"AND file_id={self._p} AND file_sha256={self._p} AND extractor_version={self._p}",
            (*self.scope, file_id, file_sha256, EXTRACTOR_VERSION))
        return self._public_extraction(rows[0]) if rows else None

    def extractions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.extraction_table} WHERE organization_id={self._p} AND project_id={self._p} "
            f"ORDER BY created_at DESC, extraction_id DESC LIMIT {self._p}",
            (*self.scope, limit))
        return [self._public_extraction(row) for row in rows]

    @staticmethod
    def _public_extraction(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        record = _decode(data.pop("record_json", data.pop("record", None)))
        data["record"] = record
        data["created_at"] = _iso(data["created_at"])
        return data

    def insert_extraction(self, record: dict[str, Any]) -> None:
        columns = ("extraction_id", "organization_id", "project_id", "file_id", "file_sha256",
                   "filename", "size_bytes", "extractor_kind", "extractor_version", "status",
                   "status_reason", "segment_count", "text_sha256", self._json_column("record"), "created_at")
        values = (record["extraction_id"], *self.scope, record["file_id"], record["file_sha256"],
                  record["filename"], record["size_bytes"], record["extractor_kind"],
                  record["extractor_version"], record["status"], record["status_reason"],
                  record["segment_count"], record["text_sha256"], _json(record), self._time(record["created_at"]))
        json_names = {"record", "record_json"}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.extraction_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def delivery_by_key(self, key: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.delivery_table} WHERE organization_id={self._p} AND project_id={self._p} AND idempotency_key={self._p}",
            (*self.scope, key))
        return self._public_delivery(rows[0]) if rows else None

    def deliveries(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.delivery_table} WHERE organization_id={self._p} AND project_id={self._p} "
            f"ORDER BY created_at DESC, delivery_id DESC LIMIT {self._p}",
            (*self.scope, limit))
        return [self._public_delivery(row) for row in rows]

    def latest_delivery(self) -> dict[str, Any] | None:
        rows = self.deliveries(limit=1)
        return rows[0] if rows else None

    def delivery(self, delivery_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.delivery_table} WHERE organization_id={self._p} AND project_id={self._p} AND delivery_id={self._p}",
            (*self.scope, delivery_id))
        return self._public_delivery(rows[0]) if rows else None

    @staticmethod
    def _public_delivery(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("handover", "source_extraction_ids"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        data["created_at"] = _iso(data["created_at"])
        return data

    def insert_delivery(self, row: dict[str, Any]) -> None:
        json_fields = ("handover", "source_extraction_ids")
        columns = ("delivery_id", "organization_id", "project_id", "production_revision_id",
                   "option_revision_id", "adoption_version", "input_hash", "status",
                   *(self._json_column(name) for name in json_fields),
                   "idempotency_key", "actor_id", "created_at")
        values = (row["delivery_id"], *self.scope, row["production_revision_id"], row["option_revision_id"],
                  row["adoption_version"], row["input_hash"], row["status"],
                  *(_json(row[name]) for name in json_fields), row["idempotency_key"],
                  row["actor_id"], self._time(row["created_at"]))
        json_names = set(json_fields) | {f"{name}_json" for name in json_fields}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.delivery_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} AND artifact_id={self._p}",
            (*self.scope, artifact_id))
        return self._public_artifact(rows[0]) if rows else None

    def artifacts(self, delivery_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} "
            f"AND delivery_id={self._p} ORDER BY artifact_kind",
            (*self.scope, delivery_id))
        return [self._public_artifact(row) for row in rows]

    @staticmethod
    def _public_artifact(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["created_at"] = _iso(data["created_at"])
        return data

    def insert_artifact(self, row: dict[str, Any]) -> None:
        columns = ("artifact_id", "delivery_id", "organization_id", "project_id", "artifact_kind",
                   "filename", "content_type", "relative_path", "sha256", "size_bytes", "created_at")
        values = (row["artifact_id"], row["delivery_id"], *self.scope, row["artifact_kind"],
                  row["filename"], row["content_type"], row["relative_path"], row["sha256"],
                  row["size_bytes"], self._time(row["created_at"]))
        placeholders = ",".join(self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.artifact_table} ({','.join(columns)}) VALUES ({placeholders})", values)


class SQLiteAIProfessionalDeliveryRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_DeliveryTransaction]:
        import sqlite3
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield _DeliveryTransaction(connection, organization_id, project_id, postgres=False)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresAIProfessionalDeliveryRepository:
    def __init__(self, store: Any) -> None:
        self.store = store

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_DeliveryTransaction]:
        context = TenantContext(organization_id, project_id, "ai-professional-delivery")
        with self.store.tenant_transaction(context) as connection:
            yield _DeliveryTransaction(connection, organization_id, project_id, postgres=True)


class AISourceExtractionService:
    """Reads original bytes; records locatable text or an explicit unknown reason."""

    def __init__(self, repository: Any, file_service: Any | None = None) -> None:
        self.repository = repository
        self.files = file_service
        self.schema = json.loads(EXTRACTION_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def extract(self, organization_id: str, project_id: str, file_id: str) -> dict[str, Any]:
        if self.files is None:
            raise AIProfessionalDeliveryError(501, "FILES_NOT_CONFIGURED", "文件存储未配置")
        if not isinstance(file_id, str) or not file_id:
            raise AIProfessionalDeliveryError(400, "INVALID_FILE_ID", "请提供原件 ID")
        metadata, path = self.files.get_content(organization_id, project_id, file_id)
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != metadata["sha256"] or len(raw) != metadata["size_bytes"]:
            raise AIProfessionalDeliveryError(500, "FILE_INTEGRITY", "原件字节与登记哈希不一致，未抽取")
        with self.repository.transaction(organization_id, project_id) as tx:
            existing = tx.extraction_by_key(file_id, actual)
        if existing:
            return {"item": existing["record"], "status": "unchanged"}
        record = build_extraction(
            extraction_id=new_id("ai-source-extraction"), file_id=file_id,
            filename=str(metadata["filename"]), file_sha256=actual,
            size_bytes=int(metadata["size_bytes"]), raw=raw, created_at=now_iso(),
        )
        errors = sorted(self.validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            raise AIProfessionalDeliveryError(500, "EXTRACTION_SCHEMA_INVALID", "抽取记录不符合版本化契约")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            again = tx.extraction_by_key(file_id, actual)
            if again:
                return {"item": again["record"], "status": "unchanged"}
            tx.insert_extraction(record)
        return {"item": record, "status": "extracted" if record["status"] == "extracted" else record["status"]}

    def list_extractions(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            items = tx.extractions()
        records = [item["record"] for item in items]
        current: dict[str, str] = {}
        if self.files is not None:
            current = {item["file_id"]: item["sha256"] for item in self.files.list_files(organization_id, project_id)["items"]}
        for record in records:
            record["current"] = current.get(record["file_id"]) == record["file_sha256"]
        return {"configured": True, "extractor_version": EXTRACTOR_VERSION,
                "items": records,
                "files": current,
                "external_content_allowed": False,
                "note": "抽取结果仅本地可查；未获明确批准前不进入外部模型上下文"}

    def summaries(self, organization_id: str, project_id: str) -> dict[str, dict[str, Any]]:
        with self.repository.transaction(organization_id, project_id) as tx:
            items = tx.extractions()
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            record = item["record"]
            if record["status"] != "extracted":
                continue
            # A newer extraction for the same file wins.
            existing = result.get(record["file_id"])
            if existing is None or record["created_at"] >= existing["created_at"]:
                result[record["file_id"]] = {**extraction_summary(record), "created_at": record["created_at"]}
        return result


class AITechnicalDeliveryService:
    """One adopted development package -> one downloadable technical draft pack."""

    def __init__(self, repository: Any, development_service: Any, extraction_service: Any | None,
                 runtime_root: str | Path) -> None:
        self.repository = repository
        self.development = development_service
        self.extractions = extraction_service
        self.runtime_root = Path(runtime_root).resolve()
        self.handover_schema = json.loads(HANDOVER_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.handover_schema)
        self.handover_validator = Draft202012Validator(self.handover_schema)

    def _current_package(self, organization_id: str, project_id: str) -> dict[str, Any]:
        if self.development is None:
            raise AIProfessionalDeliveryError(501, "AI_DEVELOPMENT_NOT_CONFIGURED", "同源深化量价服务未配置")
        state = self.development.status(organization_id, project_id)
        item = state.get("item")
        if not item:
            raise AIProfessionalDeliveryError(409, "DEVELOPMENT_REQUIRED", "请先生成一个采用候选的同源深化包")
        if item.get("status") != "draft":
            raise AIProfessionalDeliveryError(409, "DEVELOPMENT_SOURCE_OUTDATED", "采用基线已变化，旧深化包不能生成技术交付")
        revision = item["revision"]
        package = revision.get("package")
        if not isinstance(package, dict) or not package.get("objects"):
            raise AIProfessionalDeliveryError(422, "DEVELOPMENT_PACKAGE_INVALID", "同源深化包缺少对象，未生成技术成果")
        return package

    def submit(self, organization_id: str, project_id: str, actor_id: str,
               request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 255:
            raise AIProfessionalDeliveryError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键需为 8—255 字符")
        package = self._current_package(organization_id, project_id)
        expected = request.get("expected_revision")
        if expected is not None and expected != package["production_revision_id"]:
            raise AIProfessionalDeliveryError(409, "STALE_DEVELOPMENT_REVISION", "同源深化包版本已变化，请重新读取")
        extraction_records = []
        if self.extractions is not None:
            state = self.extractions.list_extractions(organization_id, project_id)
            extraction_records = [item for item in state["items"]
                                  if item.get("current") and item["status"] == "extracted"]
        input_hash = _digest({
            "production_revision_id": package["production_revision_id"],
            "option_revision_id": package["option_revision_id"],
            "adoption_version": package["adoption_version"],
            "package_input_hash": package["input_hash"],
            "object_ids": [obj["object_id"] for obj in package["objects"]],
            "quantity_item_ids": [item["quantity_item_id"] for item in package["quantity_items"]],
            "extraction_ids": [item["extraction_id"] for item in extraction_records],
            "output_version": OUTPUT_VERSION, "handover_version": HANDOVER_VERSION,
        })
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            existing = tx.delivery_by_key(idempotency_key)
            if existing:
                if existing["input_hash"] != input_hash:
                    raise AIProfessionalDeliveryError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同输入")
                return {"item": existing, "status": existing["status"]}
        delivery_id = new_id("ai-technical-delivery")
        delivery = {
            "delivery_id": delivery_id,
            "production_revision_id": package["production_revision_id"],
            "option_revision_id": package["option_revision_id"],
            "adoption_version": int(package["adoption_version"]),
            "input_hash": input_hash,
            "status": "draft",
            "actor_id": actor_id,
            "created_at": now_iso(),
        }
        try:
            outputs, manifest = generate_technical_outputs(package, delivery, extraction_records)
        except Exception as error:
            raise AIProfessionalDeliveryError(500, "TECHNICAL_OUTPUT_FAILED", "技术交付成果生成失败") from error
        handover = json.loads(outputs["handover_json"][2])
        errors = sorted(self.handover_validator.iter_errors(handover), key=lambda error: list(error.path))
        if errors:
            raise AIProfessionalDeliveryError(500, "HANDOVER_SCHEMA_INVALID", "技术交接说明不符合版本化契约")
        target = self.runtime_root / "projects" / "ai-technical-delivery" / delivery_id
        target.mkdir(parents=True, exist_ok=False)
        prepared = []
        try:
            for kind, (filename, mime, data) in outputs.items():
                path = target / filename
                path.write_bytes(data)
                prepared.append((kind, filename, mime, path.relative_to(self.runtime_root).as_posix(), data))
            # Re-check the adoption baseline immediately before the final write.
            current = self._current_package(organization_id, project_id)
            if current["production_revision_id"] != package["production_revision_id"]:
                raise AIProfessionalDeliveryError(409, "STALE_DEVELOPMENT_REVISION", "采用基线已变化，迟到结果未写入")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                again = tx.delivery_by_key(idempotency_key)
                if again:
                    if again["input_hash"] != input_hash:
                        raise AIProfessionalDeliveryError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同输入")
                    shutil.rmtree(target, ignore_errors=True)
                    return {"item": again, "status": again["status"]}
                tx.insert_delivery({
                    **delivery, "handover": handover,
                    "source_extraction_ids": [item["extraction_id"] for item in extraction_records],
                    "idempotency_key": idempotency_key,
                })
                for kind, filename, mime, relative, data in prepared:
                    tx.insert_artifact({
                        "artifact_id": new_id("ai-technical-artifact"), "delivery_id": delivery_id,
                        "artifact_kind": kind, "filename": filename, "content_type": mime,
                        "relative_path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data), "created_at": now_iso(),
                    })
                item = tx.delivery(delivery_id)
            return {"item": item, "status": "draft", "manifest_files": len(manifest["files"])}
        except AIProfessionalDeliveryError:
            shutil.rmtree(target, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            deliveries = tx.deliveries()
            latest = deliveries[0] if deliveries else None
            artifacts = tx.artifacts(latest["delivery_id"]) if latest else []
        current_revision = None
        try:
            state = self.development.status(organization_id, project_id)
            current_revision = (state.get("item") or {}).get("revision", {}).get("production_revision_id")
        except Exception:
            current_revision = None
        item = None
        if latest:
            item = {"delivery": latest, "artifacts": artifacts,
                    "status": "source_outdated" if current_revision != latest["production_revision_id"] else "draft"}
        return {"configured": True, "output_version": OUTPUT_VERSION,
                "handover_version": HANDOVER_VERSION, "item": item, "jobs": deliveries,
                "professional_review": "pending", "formal_quote": False,
                "construction_issue": False, "publication_status": "not_approved",
                "legacy_production_sync": False}

    def get_artifact(self, organization_id: str, project_id: str,
                     artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as tx:
            artifact = tx.artifact(artifact_id)
        if not artifact:
            raise AIProfessionalDeliveryError(404, "NOT_FOUND", "技术交付成果不存在")
        path = (self.runtime_root / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root) or not path.is_file():
            raise AIProfessionalDeliveryError(500, "ARTIFACT_MISSING", "技术交付成果文件缺失")
        data = path.read_bytes()
        if len(data) != artifact["size_bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise AIProfessionalDeliveryError(500, "ARTIFACT_INTEGRITY", "技术交付成果字节发生变化")
        return artifact, path
