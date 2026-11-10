"""Design -> measured floor objects -> quote -> procurement draft, one transaction."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from .design_rules import DesignError
from .models import new_id, now_iso
from .procurement_service import ProcurementService
from .production_outputs import generate_production_outputs
from .requirement_service import RequirementService
from .spatial_outputs import FORMULA_VERSION, quote_result
from .model_repository import SQLiteModelRepository


RULE_VERSION = "design-floor-boq.v1"
DEFAULTS = {"unit_cost_net": None, "cost_markup": "0.2", "trial_tax_rate": "0.05", "source_label": "unknown",
            "include_aisle": False, "material_specification": None, "supplier_name": None, "delivery_location": None}


def measure_floor(model, settings, identifier):
    objects = [{"object_id": "zone:" + z["zone_id"], "description": z["name"] + "地坪", "width": z["width"], "length": z["length"]} for z in model["zones"]]
    if settings["include_aisle"]:
        objects.append({"object_id": "aisle:main", "description": "预留通道地坪", "width": model["width"], "length": model["aisle_width"]})
    quantities = []
    for obj in objects:
        quantity = (Decimal(obj["width"]) * Decimal(obj["length"])).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if quantity <= 0:
            raise DesignError(422, "PRODUCTION_QUANTITY_PRECISION", "地坪对象面积小于支持的计量精度")
        quantities.append({**obj, "quantity_item_id": f"boq-{identifier}-{obj['object_id']}", "quantity": format(quantity, "f"),
                           "unit": "m²", "formula": f"{obj['width']} × {obj['length']}（逐项四位小数）", "source_kind": "calculated_from_saved_design"})
    total = sum(Decimal(item["quantity"]) for item in quantities)
    return quantities, quote_result(total, settings)


class ProductionService(RequirementService):
    def __init__(self, db_path, *, repository=None, runtime_root=None):
        self.model_repository = repository or SQLiteModelRepository(self._db)
        super().__init__(db_path, repository=self.model_repository.requirements)
        if runtime_root is None and self.db_path is None:
            raise ValueError("PostgreSQL model services require an explicit runtime root")
        self.runtime_root = Path(runtime_root or self.db_path.parent).resolve()

    def _settings(self, connection, org, project):
        row = connection.settings()
        return {"version": row["version"], **json.loads(row["settings_json"])} if row else {"version": 0, **DEFAULTS}

    @staticmethod
    def normalize(raw):
        settings = dict(DEFAULTS)
        if not isinstance(raw, dict):
            raise DesignError(400, "INVALID_PRODUCTION_SETTINGS", "量价参数格式无效")
        for name, maximum in (("unit_cost_net", "1000000000"), ("cost_markup", "10"), ("trial_tax_rate", "1")):
            value = raw.get(name, settings[name])
            if name == "unit_cost_net" and value is None:
                settings[name] = None
                continue
            try:
                number = Decimal(str(value))
                if not number.is_finite() or number < 0 or number > Decimal(maximum) or len(str(value)) > 40 or number != number.quantize(Decimal("0.000001")):
                    raise ValueError()
                settings[name] = format(number.normalize(), "f")
            except (InvalidOperation, ValueError, TypeError):
                raise DesignError(400, "INVALID_PRODUCTION_SETTINGS", f"{name} 超出有效范围") from None
        include = raw.get("include_aisle", False)
        if not isinstance(include, bool):
            raise DesignError(400, "INVALID_PRODUCTION_SETTINGS", "是否包含通道必须为布尔值")
        settings["include_aisle"] = include
        for name in ("source_label", "material_specification", "supplier_name", "delivery_location"):
            value = raw.get(name)
            if value is not None and not isinstance(value, str):
                raise DesignError(400, "INVALID_PRODUCTION_SETTINGS", f"{name} 格式无效")
            value = (value or "").strip()
            if len(value) > 500:
                raise DesignError(400, "INVALID_PRODUCTION_SETTINGS", "量价说明最多 500 字")
            settings[name] = value or ("unknown" if name == "source_label" else None)
        if settings["unit_cost_net"] is not None and settings["source_label"] == "unknown":
            settings["source_label"] = "人工输入（未专业核验）"
        return settings

    def _public(self, connection, row):
        item = dict(row)
        for name in ("baseline", "quantities", "quote", "procurement", "settings"):
            item[name] = json.loads(item.pop(name + "_json"))
        latest = connection.latest_production()
        design = connection.latest_design()
        requirement = connection.current_requirement()
        outdated = (not design or not requirement or design["design_revision_id"] != row["design_revision_id"]
                    or design["requirement_revision_no"] != requirement["current_revision_no"])
        item["status"] = "superseded" if row["revision_no"] != latest["revision_no"] else "source_outdated" if outdated else "draft"
        item["artifacts"] = [{**{k: a[k] for k in ("artifact_id", "artifact_kind", "filename", "content_type", "sha256", "size_bytes")},
                              "download_url": f"/api/v1/projects/{row['project_id']}/production/artifacts/{a['artifact_id']}/content"}
                             for a in connection.production_artifacts(row["production_revision_id"])]
        return item

    def get(self, org, project, revision_no=None):
        with self.model_repository.transaction(org, project) as db:
            row = db.production(revision_no)
            if revision_no is not None and row is None:
                raise DesignError(404, "NOT_FOUND", "生产修订不存在")
            return {"settings": self._settings(db, org, project), "item": self._public(db, row) if row else None,
                    "revisions": db.production_history()}

    def save_settings(self, org, project, actor, request):
        settings = self.normalize(request.get("settings"))
        with self.model_repository.transaction(org, project, write=True) as db:
            current = self._settings(db, org, project)
            if request.get("expected_version") != current["version"]:
                raise DesignError(409, "STALE_PRODUCTION_SETTINGS", "量价参数已变化，请重新读取")
            design = db.latest_design()
            if request.get("expected_design_revision") != (design["revision_no"] if design else 0):
                raise DesignError(409, "STALE_DESIGN_REVISION", "设计已变化，请重新读取")
            if design:
                requirement = db.current_requirement()["current_revision_no"]
                if requirement != design["requirement_revision_no"]:
                    raise DesignError(409, "PRODUCTION_SOURCE_OUTDATED", "请先按最新需求保存设计，再更新量价草稿")
            previous = {key: value for key, value in current.items() if key != "version"}
            if previous != settings:
                db.save_settings(current["version"] + 1, self._json(settings), actor, now_iso())
            if design:
                self.sync(db, design, actor)
        return self.get(org, project)

    def sync(self, db, design, actor):
        org, project = design["organization_id"], design["project_id"]
        if not hasattr(db, "latest_production"):
            db = self.model_repository.bind(db, org, project)
        stored = self._settings(db, org, project)
        settings = {key: value for key, value in stored.items() if key != "version"}
        latest = db.latest_production()
        if latest and latest["design_revision_id"] == design["design_revision_id"] and json.loads(latest["settings_json"]) == settings:
            return latest["production_revision_id"]
        revision, identifier = (latest["revision_no"] + 1 if latest else 1), new_id("production")
        model = json.loads(design["model_json"])
        baseline = {"organization_id": org, "project_id": project, "design_revision_id": design["design_revision_id"],
                    "design_revision_no": design["revision_no"], "requirement_id": design["requirement_id"],
                    "requirement_revision_no": design["requirement_revision_no"], "requirement_hash": design["requirement_hash"],
                    "design_input_hash": design["input_hash"], "boundary_source": model["boundary_source"],
                    "rule_version": RULE_VERSION, "formula_version": FORMULA_VERSION}
        quantities, quote = measure_floor(model, settings, identifier)
        digest = hashlib.sha256(self._json({"baseline": baseline, "settings": settings, "parent_revision_id": latest["production_revision_id"] if latest else None}).encode()).hexdigest()
        procurement = {"status": "awaiting_details", "supplier_name": settings["supplier_name"], "delivery_location": settings["delivery_location"],
                       "material_specification": settings["material_specification"], "quantity_basis": "net_geometry_without_wastage", "wastage_rate": None,
                       "external_effects_enabled": False, "order_id": None, "source_ref": identifier,
                       "lines": [{"quantity_item_id": q["quantity_item_id"], "object_id": q["object_id"], "item_name": q["description"], "ordered_quantity": q["quantity"], "unit": q["unit"]} for q in quantities]}
        has_facts = db.production_has_facts()
        if has_facts:
            procurement["status"] = "requires_reconciliation"
        elif all(settings[key] for key in ("supplier_name", "delivery_location", "material_specification")):
            order = ProcurementService(self.db_path, repository=self.model_repository.procurement).create_order(org, project, actor,
                {"supplier_name": settings["supplier_name"], "delivery_location": settings["delivery_location"], "source_kind": "design_boq_draft", "source_ref": identifier,
                 "lines": [{**line, "item_code": line["quantity_item_id"], "specification": settings["material_specification"]} for line in procurement["lines"]]},
                "production-draft:" + identifier, connection=db.db)
            procurement.update({"status": "order_draft_created", "order_id": order["order_id"]})
        scope = "功能分区及预留通道地坪" if settings["include_aisle"] else "功能分区地坪（不含通道）"
        snapshot = {"production_revision_id": identifier, "revision_no": revision, "input_hash": digest, "baseline": baseline,
                    "settings": settings, "scope_label": scope, "quantities": quantities, "quote": quote, "procurement": procurement}
        drawings = {}
        for artifact in db.design_artifacts(design["design_revision_id"]):
            if artifact["artifact_kind"] not in {"layout_svg", "layout_dxf"}:
                continue
            path = (self.runtime_root / artifact["relative_path"]).resolve()
            if not path.is_relative_to(self.runtime_root.resolve()) or not path.is_file():
                raise DesignError(500, "ARTIFACT_INTEGRITY", "设计图面缺失或路径无效")
            data = path.read_bytes()
            if len(data) != artifact["size_bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise DesignError(500, "ARTIFACT_INTEGRITY", "设计图面字节发生变化")
            drawings[artifact["artifact_kind"]] = ("design-" + artifact["filename"], artifact["content_type"], data)
        if len(drawings) != 2:
            raise DesignError(500, "DESIGN_DRAWINGS_REQUIRED", "同基线的 SVG/DXF 图面不完整")
        outputs = generate_production_outputs(snapshot, drawings)
        db.insert_production({"production_revision_id": identifier, "revision_no": revision, "design_revision_id": design["design_revision_id"],
                              "settings_version": stored["version"], "input_hash": digest, "baseline_json": self._json(baseline),
                              "quantities_json": self._json(quantities), "quote_json": self._json(quote), "procurement_json": self._json(procurement),
                              "settings_json": self._json(settings), "actor_id": actor, "created_at": now_iso()})
        root = self.runtime_root / "projects/production-exports" / identifier
        root.mkdir(parents=True, exist_ok=False)
        for kind, (filename, mime, data) in outputs.items():
            path = root / filename
            path.write_bytes(data)
            db.insert_production_artifact({"artifact_id": new_id("production-artifact"), "production_revision_id": identifier,
                                           "artifact_kind": kind, "filename": filename, "content_type": mime,
                                           "relative_path": path.relative_to(self.runtime_root).as_posix(),
                                           "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
        return identifier

    def get_artifact(self, org, project, artifact_id):
        with self.model_repository.transaction(org, project) as db:
            row = db.production_artifact(artifact_id)
        if row is None:
            raise DesignError(404, "NOT_FOUND", "生产成果不存在")
        path = (self.runtime_root / row["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root.resolve()) or not path.is_file() or path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise DesignError(500, "ARTIFACT_INTEGRITY", "生产成果字节缺失或发生变化")
        return dict(row), path
