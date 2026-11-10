from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso
from .spatial_repository import SQLiteSpatialRepository, SpatialUnitConflict
from .spatial_outputs import FORMULA_VERSION, generate_outputs, quote_result


AREA = Decimal("0.01")


class SpatialServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SpatialService:
    """Deterministic parameter geometry for the first M2 production slice."""

    def __init__(self, db_path: str | Path | None, *, repository=None, runtime_root=None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self.repository = repository or SQLiteSpatialRepository(self._db)
        self.runtime_root = Path(runtime_root) if runtime_root is not None else self.db_path.parent

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
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

    @staticmethod
    def _decimal(value: Any, field: str, positive: bool = False) -> Decimal:
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, AttributeError) as error:
            raise SpatialServiceError(400, "INVALID_GEOMETRY_VALUE", f"{field} 不是有效数字") from error
        if not result.is_finite() or (result <= 0 if positive else result < 0):
            qualifier = "必须大于 0" if positive else "必须是非负有限数字"
            raise SpatialServiceError(400, "INVALID_GEOMETRY_VALUE", f"{field}{qualifier}")
        return result

    @staticmethod
    def _text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @staticmethod
    def _area(value: Decimal) -> str:
        return format(value.quantize(AREA, rounding=ROUND_HALF_UP), "f")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _require_unit(self, connection: sqlite3.Connection, organization_id: str,
                      project_id: str, spatial_unit_id: str) -> sqlite3.Row:
        row = connection.query(
            'unit',
            (spatial_unit_id, organization_id, project_id),
        ).fetchone()
        if row is None:
            raise SpatialServiceError(404, "NOT_FOUND", "空间对象不存在")
        return row

    def _validate_deductions(self, width: Decimal, length: Decimal, raw: Any) -> list[dict[str, str]]:
        if raw is None:
            raw = []
        if not isinstance(raw, list) or len(raw) > 100:
            raise SpatialServiceError(400, "INVALID_GEOMETRY_VALUE", "扣除区必须是最多 100 项的数组")
        normalized: list[dict[str, str]] = []
        boxes: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise SpatialServiceError(400, "INVALID_GEOMETRY_VALUE", f"扣除区 {index + 1} 格式无效")
            deduction_id = str(item.get("deduction_id") or f"deduction-{index + 1}").strip()
            x = self._decimal(item.get("x"), f"扣除区 {deduction_id} x")
            y = self._decimal(item.get("y"), f"扣除区 {deduction_id} y")
            deduction_width = self._decimal(item.get("width"), f"扣除区 {deduction_id} 宽度", True)
            deduction_length = self._decimal(item.get("length"), f"扣除区 {deduction_id} 长度", True)
            if x + deduction_width > width or y + deduction_length > length:
                raise SpatialServiceError(400, "DEDUCTION_OUT_OF_BOUNDS", f"扣除区 {deduction_id} 超出外框")
            box = (x, y, x + deduction_width, y + deduction_length)
            for prior in boxes:
                overlap_width = min(box[2], prior[2]) - max(box[0], prior[0])
                overlap_length = min(box[3], prior[3]) - max(box[1], prior[1])
                if overlap_width > 0 and overlap_length > 0:
                    raise SpatialServiceError(400, "OVERLAPPING_DEDUCTIONS", f"扣除区 {deduction_id} 与其他扣除区重叠")
            boxes.append(box)
            normalized.append({
                "deduction_id": deduction_id,
                "x": self._text(x), "y": self._text(y),
                "width": self._text(deduction_width), "length": self._text(deduction_length),
            })
        return normalized

    def _public(self, connection: sqlite3.Connection, unit: sqlite3.Row,
                revision: sqlite3.Row | None) -> dict[str, Any]:
        if revision is None:
            return {"spatial_unit_id": unit["spatial_unit_id"], "name": unit["name"], "unit_kind": unit["unit_kind"], "revision_no": 0, "revisions": []}
        deductions = json.loads(revision["deductions_json"])
        quantities = [dict(row) for row in connection.query('quantities', (revision["geometry_revision_id"],)).fetchall()]
        for item in quantities:
            item["quantity"] = item.pop("quantity_text")
        artifacts = [dict(row) for row in connection.query(
            'revision_artifacts',
            (revision["geometry_revision_id"],),
        ).fetchall()]
        for item in artifacts:
            item["download_url"] = f"/api/v1/projects/{unit['project_id']}/spatial/artifacts/{item['artifact_id']}/content"
        quote = connection.query('quote', (revision["geometry_revision_id"],)).fetchone()
        revisions = [dict(row) for row in connection.query('revisions', (unit["spatial_unit_id"],)).fetchall()]
        return {
            "spatial_unit_id": unit["spatial_unit_id"], "name": unit["name"], "unit_kind": unit["unit_kind"],
            "geometry_revision_id": revision["geometry_revision_id"], "revision_no": revision["revision_no"],
            "width": revision["width_text"], "length": revision["length_text"], "area_m2": revision["area_m2_text"],
            "deductions": deductions, "quantity_items": quantities, "revisions": revisions,
            "artifacts": artifacts,
            "quote": None if quote is None else {
                "quote_revision_id": quote["quote_revision_id"],
                "formula_version": quote["formula_version"],
                "pricing": json.loads(quote["pricing_json"]),
                "result": json.loads(quote["result_json"]),
            },
            "source_kind": revision["source_kind"], "change_reason": revision["change_reason"],
            "input_hash": revision["input_hash"], "created_at": revision["created_at"],
        }

    def _write_artifacts(self, connection: sqlite3.Connection, organization_id: str, project_id: str,
                         revision_id: str, revision_no: int, width: Decimal, length: Decimal,
                         deductions: list[dict[str, str]], area: str, created_at: str,
                         input_hash: str, quote: dict) -> None:
        # Only server-generated revision IDs determine file paths. Project names,
        # caller object IDs and per-object revision numbers cannot collide here.
        export_root = self.runtime_root / "projects" / "spatial-exports" / revision_id
        export_root.mkdir(parents=True, exist_ok=False)
        quantity_id = connection.query(
            'quantity_id',
            (revision_id,),
        ).fetchone()["quantity_item_id"]
        baseline = {"organization_id": organization_id, "project_id": project_id, "geometry_revision_id": revision_id, "revision_no": revision_no, "width": self._text(width), "length": self._text(length), "quantity": area, "quantity_item_id": quantity_id, "input_hash": input_hash}
        outputs = generate_outputs(baseline, width, length, deductions, quote)
        for kind, (filename, content_type, data) in outputs.items():
            path = export_root / filename
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            digest = hashlib.sha256(data).hexdigest()
            connection.query(
                'insert_artifact',
                (new_id("artifact"), revision_id, organization_id, project_id, kind, filename,
                 content_type, str(path.relative_to(self.runtime_root)), digest, len(data), created_at),
            )

    def get_model(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as connection:
            unit = connection.query('first_unit', (organization_id, project_id)).fetchone()
            if unit is None:
                return {"items": []}
            revision = connection.query('latest_revision', (unit["spatial_unit_id"],)).fetchone()
            return {"items": [self._public(connection, unit, revision)]}

    def list_artifacts(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as connection:
            rows = connection.query(
                'artifacts',
                (organization_id, project_id),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as connection:
            row = connection.query(
                'artifact',
                (artifact_id, organization_id, project_id),
            ).fetchone()
        if row is None:
            raise SpatialServiceError(404, "NOT_FOUND", "空间成果不存在")
        path = (self.runtime_root / row["relative_path"]).resolve()
        try:
            path.relative_to(self.runtime_root.resolve())
        except ValueError as error:
            raise SpatialServiceError(500, "INVALID_ARTIFACT_PATH", "空间成果路径无效") from error
        if not path.is_file():
            raise SpatialServiceError(404, "ARTIFACT_MISSING", "空间成果文件不存在")
        if path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise SpatialServiceError(500, "ARTIFACT_INTEGRITY", "空间成果字节发生变化，请保留文件并重新生成新修订")
        metadata = dict(row)
        return metadata, path

    def create_revision(self, organization_id: str, project_id: str, request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        explicit_id = request.get("spatial_unit_id")
        legacy_default = f"space-{project_id}-test-floor"
        scope_key = hashlib.sha256(self._json([organization_id, project_id]).encode("utf-8")).hexdigest()[:32]
        spatial_unit_id = str(explicit_id or f"space-{scope_key}-test-floor").strip()
        name = str(request.get("name") or "测试地坪区域").strip()
        width = self._decimal(request.get("width"), "外框宽度", True)
        length = self._decimal(request.get("length"), "外框长度", True)
        deductions = self._validate_deductions(width, length, request.get("deductions", []))
        expected_revision = int(request.get("expected_revision", 0))
        payload = {"width": self._text(width), "length": self._text(length), "deductions": deductions}
        pricing = request.get("pricing") if isinstance(request.get("pricing"), dict) else {}
        unit_cost = pricing.get("unit_cost_net")
        if unit_cost is not None:
            unit_cost = self._decimal(unit_cost, "未税单位成本")
        pricing_payload = {
            "unit_cost_net": None if unit_cost is None else self._text(unit_cost),
            "cost_markup": self._text(self._decimal(pricing.get("cost_markup", "0.20"), "成本加成率")),
            "trial_tax_rate": self._text(self._decimal(pricing.get("trial_tax_rate", "0.05"), "试用税率")),
            "source_label": str(pricing.get("source_label") or "M2 测试成本快照（人工输入）"),
        }
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            # Existing defaults keep their identity. Only new defaults include
            # organization scope, so equal project IDs cannot collide.
            if not explicit_id and connection.query('unit', (legacy_default, organization_id, project_id)).fetchone():
                spatial_unit_id = legacy_default
            unit = connection.query('unit', (spatial_unit_id, organization_id, project_id)).fetchone()
            if unit is None:
                if expected_revision != 0:
                    raise SpatialServiceError(409, "STALE_GEOMETRY_REVISION", "空间修订已变化，请重新读取")
                now = now_iso()
                try:
                    connection.query('insert_unit', (spatial_unit_id, organization_id, project_id, name, now))
                except SpatialUnitConflict as error:
                    raise SpatialServiceError(409, "SPATIAL_ID_UNAVAILABLE", "该空间编号不可用，请使用项目内的新编号") from error
                unit = connection.query('unit_by_id', (spatial_unit_id,)).fetchone()
            latest = connection.query('latest_revision', (spatial_unit_id,)).fetchone()
            current = int(latest["revision_no"]) if latest else 0
            if current != expected_revision:
                raise SpatialServiceError(409, "STALE_GEOMETRY_REVISION", "空间修订已变化，请重新读取")
            if latest:
                previous_quote = connection.query('pricing', (latest["geometry_revision_id"],)).fetchone()
                same_geometry = (Decimal(latest["width_text"]) == width and Decimal(latest["length_text"]) == length
                                 and json.loads(latest["deductions_json"]) == deductions)
                if same_geometry and previous_quote and json.loads(previous_quote["pricing_json"]) == pricing_payload and previous_quote["formula_version"] == FORMULA_VERSION:
                    return self._public(connection, unit, latest)
            # A production input includes its parent revision. Returning to an
            # older shape is a new revision, while a no-op on current is reused.
            input_hash = hashlib.sha256(self._json({
                **payload, "pricing": pricing_payload, "formula_version": FORMULA_VERSION,
                "parent_revision_id": latest["geometry_revision_id"] if latest else None,
            }).encode("utf-8")).hexdigest()
            revision_no = current + 1
            area = width * length - sum(Decimal(item["width"]) * Decimal(item["length"]) for item in deductions)
            if area <= 0:
                raise SpatialServiceError(400, "INVALID_GEOMETRY_VALUE", "扣除区面积不能大于等于外框面积")
            connection.query(
                'supersede',
                (organization_id, project_id, spatial_unit_id),
            )
            revision_id = new_id("geometry")
            now = now_iso()
            connection.query('insert_revision', (revision_id, spatial_unit_id, organization_id, project_id, revision_no, self._text(width), self._text(length), self._json(deductions), self._area(area), input_hash, str(request.get("change_reason") or "更新参数几何"), actor_id, now))
            connection.query('insert_quantity', (f"quantity-{spatial_unit_id}-floor-area-v{revision_no}", revision_id, organization_id, project_id, self._area(area)))
            quote = {"quote_revision_id": new_id("quote"), "pricing": pricing_payload, "result": quote_result(Decimal(self._area(area)), pricing_payload)}
            connection.query('insert_quote', (revision_id, quote["quote_revision_id"], self._json(pricing_payload), self._json(quote["result"]), FORMULA_VERSION, now))
            self._write_artifacts(connection, organization_id, project_id, revision_id, revision_no, width, length, deductions, self._area(area), now, input_hash, quote)
            revision = connection.query('revision', (revision_id,)).fetchone()
            return self._public(connection, unit, revision)
