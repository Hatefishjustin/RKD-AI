from __future__ import annotations

import hashlib
import csv
import html
import io
import json
import sqlite3
from contextlib import contextmanager, nullcontext
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso
from .estimate_repository import SQLiteEstimateRepository


FORMULA_VERSION = "estimate-cost-markup-tax.v1"
MONEY = Decimal("0.01")


class EstimateServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class EstimateService:
    """Persistent estimate revisions and Decimal calculations for the local M1 workbench."""

    def __init__(self, db_path: str | Path | None, *, repository=None, runtime_root=None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self.repository = repository or SQLiteEstimateRepository(self._db)
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
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decimal(value: Any, field: str, allow_none: bool = False) -> Decimal | None:
        if value is None or str(value).strip() == "":
            if allow_none:
                return None
            raise EstimateServiceError(400, "INVALID_ESTIMATE_VALUE", f"{field} 不能为空")
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as error:
            raise EstimateServiceError(400, "INVALID_ESTIMATE_VALUE", f"{field} 不是有效数字") from error
        if not result.is_finite() or result < 0:
            raise EstimateServiceError(400, "INVALID_ESTIMATE_VALUE", f"{field} 必须是非负有限数字")
        return result

    @classmethod
    def _decimal_text(cls, value: Any, field: str, allow_none: bool = False) -> str | None:
        parsed = cls._decimal(value, field, allow_none)
        if parsed is None:
            return None
        return format(parsed.normalize() if parsed else Decimal("0"), "f")

    @staticmethod
    def _money(value: Decimal | None) -> str | None:
        return None if value is None else format(value.quantize(MONEY, rounding=ROUND_HALF_UP), "f")

    @staticmethod
    def _source_amount(line: dict[str, Any]) -> Decimal:
        return sum(
            Decimal(str(line.get(field) or "0"))
            for field in ("main_material_amount", "auxiliary_amount", "labor_amount")
        )

    def _decisions(self, connection: sqlite3.Connection, organization_id: str, project_id: str) -> dict[str, Any]:
        rows = connection.query(
            'decisions',
            (organization_id, project_id),
        ).fetchall()
        return {row["decision_key"]: json.loads(row["value_json"]) for row in rows}

    def seed_ningbo(self, organization_id: str, project_id: str, fixture_root: Path) -> dict[str, Any]:
        extract_path = fixture_root / "derived" / "budget-source-extract.json"
        source_path = fixture_root / "source" / "20260721宁波协诚集团样品展厅装修预算.xls"
        extract = json.loads(extract_path.read_text(encoding="utf-8"))
        with source_path.open("rb") as source_stream:
            source_hash = hashlib.file_digest(source_stream, "sha256").hexdigest().upper()
        if source_hash != str(extract["source"]["sha256"]).upper():
            raise RuntimeError("budget source hash does not match normalized extract")

        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            existing = connection.query(
                'by_source',
                (organization_id, project_id, source_hash.lower()),
            ).fetchone()
            if existing:
                estimate_id = existing["estimate_id"]
            else:
                file_row = connection.query(
                    'source_file',
                    (organization_id, project_id, extract["source"]["asset_id"]),
                ).fetchone()
                if file_row is None:
                    raise RuntimeError("budget source file was not seeded before estimate import")
                decisions = self._decisions(connection, organization_id, project_id)
                assumptions = {
                    "trial_tax_rate": decisions.get("trial_tax_rate", "0.05"),
                    "construction_cost_markup": decisions.get("construction_cost_markup", "0.20"),
                    "design_cost_markup": decisions.get("design_cost_markup", "0.60"),
                    "design_cost_net": None,
                    "contract_target_gross_cny": decisions.get("contract_target_gross_cny", "600000.00"),
                }
                estimate_id = new_id("estimate")
                now = now_iso()
                connection.query(
                    'insert_estimate',
                    (estimate_id, organization_id, project_id, "宁波协诚展厅预算工作副本", file_row["file_id"],
                     source_hash.lower(), self._json(extract["source_summary"]), self._json(extract["source_notes"]), now, now),
                )
                connection.query(
                    'insert_initial_revision',
                    (estimate_id, organization_id, project_id, "从只读 XLS 规范化导入", self._json(assumptions), now),
                )
                for order_index, line in enumerate(extract["lines"], start=1):
                    source_amount = self._source_amount(line)
                    connection.query(
                        'insert_line',
                        (estimate_id, line["line_id"], order_index, line["category"], line["section"], line["sequence"],
                         line["name"], line["unit"], line["quantity"], line["main_material_unit_cost"],
                         line["auxiliary_unit_cost"], line["labor_unit_cost"], line["quantity"],
                         line["main_material_unit_cost"], line["auxiliary_unit_cost"], line["labor_unit_cost"],
                         format(source_amount, "f"), line.get("material_name") or "", line.get("auxiliary_description") or "",
                         line["inclusion_status"], line.get("exclusion_reason"), int(bool(line.get("source_scope_conflict"))),
                         line["source_sheet"], int(line["source_row"]), line["source_locator"]),
                    )
                self._calculate(connection, organization_id, project_id, estimate_id, 1)
        return self.get_estimate(organization_id, project_id, estimate_id)

    def _require_estimate(self, connection: sqlite3.Connection, organization_id: str,
                          project_id: str, estimate_id: str) -> sqlite3.Row:
        row = connection.query(
            'estimate',
            (estimate_id, organization_id, project_id),
        ).fetchone()
        if row is None:
            raise EstimateServiceError(404, "NOT_FOUND", "estimate not found")
        return row

    def _revision(self, connection: sqlite3.Connection, estimate_id: str, revision_no: int) -> sqlite3.Row:
        row = connection.query(
            'revision',
            (estimate_id, revision_no),
        ).fetchone()
        if row is None:
            raise EstimateServiceError(404, "NOT_FOUND", "estimate revision not found")
        return row

    @staticmethod
    def _line_values(row: sqlite3.Row) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        def value(name: str) -> Decimal | None:
            raw = row[name]
            return None if raw is None else Decimal(raw)
        return value("quantity_text"), value("main_material_unit_cost_text"), value("auxiliary_unit_cost_text"), value("labor_unit_cost_text")

    def _calculation_result(self, lines: list[sqlite3.Row], assumptions: dict[str, Any],
                            source_summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
        tax_rate = self._decimal(assumptions.get("trial_tax_rate"), "试用税率")
        construction_markup = self._decimal(assumptions.get("construction_cost_markup"), "施工成本加成")
        design_markup = self._decimal(assumptions.get("design_cost_markup"), "设计成本加成")
        design_cost = self._decimal(assumptions.get("design_cost_net"), "设计成本", allow_none=True)
        contract_target = self._decimal(assumptions.get("contract_target_gross_cny"), "合同含税目标")
        if any(rate is not None and rate > Decimal("10") for rate in (tax_rate, construction_markup, design_markup)):
            raise EstimateServiceError(400, "INVALID_ESTIMATE_VALUE", "税率或加成率超出本地试算范围")

        source_line_total = Decimal("0")
        included_total = Decimal("0")
        excluded_total = Decimal("0")
        unknown_included = 0
        excluded_count = 0
        source_conflicts = 0
        for row in lines:
            source_line_total += Decimal(row["source_amount_text"])
            if row["source_scope_conflict"]:
                source_conflicts += 1
            quantity, main, auxiliary, labor = self._line_values(row)
            current = None if any(value is None for value in (quantity, main, auxiliary, labor)) else quantity * (main + auxiliary + labor)
            if row["inclusion_status"] == "included":
                if current is None:
                    unknown_included += 1
                else:
                    included_total += current
            else:
                excluded_count += 1
                if current is not None:
                    excluded_total += current

        construction_cost = None if unknown_included else included_total
        construction_net = None if construction_cost is None else construction_cost * (Decimal("1") + construction_markup)
        construction_gross = None if construction_net is None else construction_net * (Decimal("1") + tax_rate)
        design_net = None if design_cost is None else design_cost * (Decimal("1") + design_markup)
        design_gross = None if design_net is None else design_net * (Decimal("1") + tax_rate)
        combined_net = None if construction_net is None or design_net is None else construction_net + design_net
        combined_gross = None if construction_gross is None or design_gross is None else construction_gross + design_gross
        source_total = Decimal(str(source_summary["source_total_before_tax"]))

        warnings: list[dict[str, str]] = []
        if design_cost is None:
            warnings.append({"code": "DESIGN_COST_UNKNOWN", "message": "设计成本尚未输入，合并报价保持未知，不按 0 计算。"})
        if unknown_included:
            warnings.append({"code": "LINE_COST_UNKNOWN", "message": f"{unknown_included} 条纳入范围的明细缺少数量或成本。"})
        if excluded_count:
            warnings.append({"code": "PROJECT_SCOPE_EXCLUDED", "message": f"{excluded_count} 条机电/消防相关明细按当前项目决定排除。"})
        if source_conflicts:
            warnings.append({"code": "SOURCE_SCOPE_CONFLICT", "message": f"{source_conflicts} 条家具明细与源表排除备注存在口径冲突，当前按源表汇总保留。"})
        warnings.append({"code": "TAX_BASIS_TRIAL", "message": "5% 为本地试用参数；源优惠价标注不含税，合同目标按用户确认的含税口径单独显示。"})
        reconciliation = (source_line_total - source_total).quantize(MONEY, rounding=ROUND_HALF_UP)
        if reconciliation != 0:
            warnings.append({"code": "SOURCE_RECONCILIATION", "message": "明细来源金额与源表汇总不一致。"})

        result = {
            "currency": "CNY",
            "formula_version": FORMULA_VERSION,
            "included_line_count": len(lines) - excluded_count,
            "excluded_line_count": excluded_count,
            "unknown_included_line_count": unknown_included,
            "source_line_total_before_tax": self._money(source_line_total),
            "source_total_before_tax": self._money(source_total),
            "source_discounted_before_tax": self._money(Decimal(str(source_summary["source_discounted_before_tax"]))),
            "source_reconciliation_difference": self._money(reconciliation),
            "included_construction_cost": self._money(construction_cost),
            "excluded_source_cost": self._money(excluded_total),
            "construction_net_sale": self._money(construction_net),
            "construction_tax": self._money(None if construction_net is None else construction_gross - construction_net),
            "construction_gross_sale": self._money(construction_gross),
            "design_cost_net": self._money(design_cost),
            "design_net_sale": self._money(design_net),
            "design_tax": self._money(None if design_net is None else design_gross - design_net),
            "design_gross_sale": self._money(design_gross),
            "combined_net_sale": self._money(combined_net),
            "combined_tax": self._money(None if combined_net is None else combined_gross - combined_net),
            "combined_gross_sale": self._money(combined_gross),
            "contract_target_gross": self._money(contract_target),
            "gross_gap_to_contract_target": self._money(None if combined_gross is None else combined_gross - contract_target),
            "trial_tax_rate": format(tax_rate, "f"),
            "construction_cost_markup": format(construction_markup, "f"),
            "design_cost_markup": format(design_markup, "f"),
        }
        return result, warnings

    def _calculate(self, connection: sqlite3.Connection, organization_id: str, project_id: str,
                   estimate_id: str, revision_no: int) -> dict[str, Any]:
        estimate = self._require_estimate(connection, organization_id, project_id, estimate_id)
        revision = self._revision(connection, estimate_id, revision_no)
        lines = connection.query(
            'lines',
            (estimate_id, revision_no),
        ).fetchall()
        assumptions = json.loads(revision["assumptions_json"])
        source_summary = json.loads(estimate["source_summary_json"])
        result, warnings = self._calculation_result(lines, assumptions, source_summary)
        fingerprint = hashlib.sha256(self._json({
            "formula_version": FORMULA_VERSION,
            "assumptions": assumptions,
            "lines": [{key: row[key] for key in (
                "line_id", "quantity_text", "main_material_unit_cost_text", "auxiliary_unit_cost_text",
                "labor_unit_cost_text", "inclusion_status", "exclusion_reason",
            )} for row in lines],
        }).encode("utf-8")).hexdigest()
        run_id = new_id("calculation")
        now = now_iso()
        connection.query(
            'insert_calculation',
            (run_id, organization_id, project_id, estimate_id, revision_no, FORMULA_VERSION, fingerprint,
             self._json(result), self._json(warnings), now),
        )
        row = connection.query(
            'calculation',
            (estimate_id, revision_no, fingerprint),
        ).fetchone()
        return self._public_calculation(row)

    @staticmethod
    def _public_calculation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "calculation_run_id": row["calculation_run_id"],
            "revision_no": row["revision_no"],
            "formula_version": row["formula_version"],
            "input_hash": row["input_hash"],
            "result": json.loads(row["result_json"]),
            "warnings": json.loads(row["warnings_json"]),
            "created_at": row["created_at"],
        }

    def _public_line(self, row: sqlite3.Row) -> dict[str, Any]:
        quantity, main, auxiliary, labor = self._line_values(row)
        current = None if any(value is None for value in (quantity, main, auxiliary, labor)) else quantity * (main + auxiliary + labor)
        return {
            "line_id": row["line_id"],
            "order_index": row["order_index"],
            "category": row["category"],
            "section": row["section_name"],
            "sequence": row["sequence_label"],
            "name": row["item_name"],
            "unit": row["unit"],
            "quantity": row["quantity_text"],
            "main_material_unit_cost": row["main_material_unit_cost_text"],
            "auxiliary_unit_cost": row["auxiliary_unit_cost_text"],
            "labor_unit_cost": row["labor_unit_cost_text"],
            "current_cost": self._money(current),
            "source_quantity": row["source_quantity_text"],
            "source_main_material_unit_cost": row["source_main_material_unit_cost_text"],
            "source_auxiliary_unit_cost": row["source_auxiliary_unit_cost_text"],
            "source_labor_unit_cost": row["source_labor_unit_cost_text"],
            "source_amount": self._money(Decimal(row["source_amount_text"])),
            "material_name": row["material_name"],
            "auxiliary_description": row["auxiliary_description"],
            "inclusion_status": row["inclusion_status"],
            "exclusion_reason": row["exclusion_reason"],
            "source_scope_conflict": bool(row["source_scope_conflict"]),
            "source_sheet": row["source_sheet"],
            "source_row": row["source_row"],
            "source_locator": row["source_locator"],
        }

    def list_estimates(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=False) as connection:
            rows = connection.query(
                'estimates',
                (organization_id, project_id),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    def get_estimate(self, organization_id: str, project_id: str, estimate_id: str, *, connection=None) -> dict[str, Any]:
        context = nullcontext(connection) if connection is not None else self.repository.transaction(organization_id, project_id)
        with context as connection:
            estimate = self._require_estimate(connection, organization_id, project_id, estimate_id)
            revision_no = int(estimate["current_revision_no"])
            revision = self._revision(connection, estimate_id, revision_no)
            lines = connection.query(
                'lines',
                (estimate_id, revision_no),
            ).fetchall()
            calculation = connection.query(
                'latest_calculation',
                (estimate_id, revision_no),
            ).fetchone()
        return {
            "estimate_id": estimate["estimate_id"],
            "organization_id": estimate["organization_id"],
            "project_id": estimate["project_id"],
            "name": estimate["name"],
            "currency": estimate["currency"],
            "status": estimate["status"],
            "source_file_id": estimate["source_file_id"],
            "source_hash": estimate["source_hash"],
            "source_summary": json.loads(estimate["source_summary_json"]),
            "source_notes": json.loads(estimate["source_notes_json"]),
            "revision_no": revision_no,
            "revision": {
                "source_kind": revision["source_kind"],
                "change_reason": revision["change_reason"],
                "actor_id": revision["actor_id"],
                "created_at": revision["created_at"],
            },
            "assumptions": json.loads(revision["assumptions_json"]),
            "lines": [self._public_line(row) for row in lines],
            "calculation": self._public_calculation(calculation),
            "updated_at": estimate["updated_at"],
        }

    def _copy_revision(self, connection: sqlite3.Connection, estimate: sqlite3.Row, actor_id: str,
                       change_reason: str, source_kind: str, assumptions: dict[str, Any] | None = None) -> int:
        current = int(estimate["current_revision_no"])
        next_revision = current + 1
        current_revision = self._revision(connection, estimate["estimate_id"], current)
        assumptions = assumptions or json.loads(current_revision["assumptions_json"])
        now = now_iso()
        connection.query(
            'insert_revision',
            (estimate["estimate_id"], next_revision, estimate["organization_id"], estimate["project_id"],
             source_kind, change_reason, actor_id, self._json(assumptions), now),
        )
        connection.query(
            'copy_lines',
            (next_revision, estimate["estimate_id"], current),
        )
        connection.query(
            'advance',
            (next_revision, now, estimate["estimate_id"]),
        )
        connection.query(
            'supersede',
            (estimate["estimate_id"],),
        )
        return next_revision

    def update_line(self, organization_id: str, project_id: str, estimate_id: str, line_id: str,
                    request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        reason = str(request.get("change_reason", "")).strip()
        if not reason:
            raise EstimateServiceError(400, "INVALID_ESTIMATE_CHANGE", "修改理由不能为空")
        expected_revision = int(request.get("expected_revision", -1))
        updates: dict[str, Any] = {}
        fields = {
            "quantity": ("quantity_text", "工程量"),
            "main_material_unit_cost": ("main_material_unit_cost_text", "主材单位成本"),
            "auxiliary_unit_cost": ("auxiliary_unit_cost_text", "辅材单位成本"),
            "labor_unit_cost": ("labor_unit_cost_text", "人工单位成本"),
        }
        for request_key, (column, label) in fields.items():
            if request_key in request:
                updates[column] = self._decimal_text(request[request_key], label, allow_none=True)
        if "inclusion_status" in request:
            status = str(request["inclusion_status"])
            if status not in {"included", "excluded"}:
                raise EstimateServiceError(400, "INVALID_ESTIMATE_CHANGE", "纳入状态不支持")
            updates["inclusion_status"] = status
            updates["exclusion_reason"] = None if status == "included" else str(request.get("exclusion_reason", "manual_exclusion")).strip()
        if not updates:
            raise EstimateServiceError(400, "INVALID_ESTIMATE_CHANGE", "没有可保存的预算明细变化")

        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            estimate = self._require_estimate(connection, organization_id, project_id, estimate_id)
            if int(estimate["current_revision_no"]) != expected_revision:
                raise EstimateServiceError(409, "STALE_ESTIMATE_REVISION", "预算修订已变化，请重新读取")
            exists = connection.query(
                'line_exists',
                (estimate_id, expected_revision, line_id),
            ).fetchone()
            if not exists:
                raise EstimateServiceError(404, "NOT_FOUND", "estimate line not found")
            revision_no = self._copy_revision(connection, estimate, actor_id, reason, "user_edit")
            connection.update_line(estimate_id, revision_no, line_id, updates)
            self._calculate(connection, organization_id, project_id, estimate_id, revision_no)
        return self.get_estimate(organization_id, project_id, estimate_id)

    def calculate(self, organization_id: str, project_id: str, estimate_id: str,
                  request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        reason = str(request.get("change_reason", "试算参数更新")).strip() or "试算参数更新"
        expected_revision = int(request.get("expected_revision", -1))
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            estimate = self._require_estimate(connection, organization_id, project_id, estimate_id)
            if int(estimate["current_revision_no"]) != expected_revision:
                raise EstimateServiceError(409, "STALE_ESTIMATE_REVISION", "预算修订已变化，请重新读取")
            current_revision = self._revision(connection, estimate_id, expected_revision)
            assumptions = json.loads(current_revision["assumptions_json"])
            for key, label, allow_none in (
                ("trial_tax_rate", "试用税率", False),
                ("construction_cost_markup", "施工成本加成", False),
                ("design_cost_markup", "设计成本加成", False),
                ("design_cost_net", "设计成本", True),
            ):
                if key in request:
                    assumptions[key] = self._decimal_text(request[key], label, allow_none=allow_none)
            revision_no = self._copy_revision(connection, estimate, actor_id, reason, "trial_calculation", assumptions)
            self._calculate(connection, organization_id, project_id, estimate_id, revision_no)
        return self.get_estimate(organization_id, project_id, estimate_id)

    def _artifact_outputs(self, estimate: dict[str, Any]) -> dict[str, tuple[str, str, bytes]]:
        calculation = estimate["calculation"]
        result = calculation["result"]
        revision = estimate["revision_no"]
        esc = html.escape
        fields = [
            ("源表明细未税合计", result["source_line_total_before_tax"]),
            ("纳入范围施工成本", result["included_construction_cost"] or "未知"),
            ("施工含税试算", result["construction_gross_sale"] or "未知"),
            ("设计含税试算", result["design_gross_sale"] or "未知"),
            ("合并含税试算", result["combined_gross_sale"] or "未知"),
            ("合同含税目标", result["contract_target_gross"]),
            ("与合同目标差额", result["gross_gap_to_contract_target"] or "未知"),
        ]
        summary_rows = "".join(f"<tr><th>{esc(label)}</th><td>{esc(str(value))}</td></tr>" for label, value in fields)
        line_rows = "".join(
            "<tr>" + "".join(f"<td>{esc(str(line.get(key) or '未知'))}</td>" for key in (
                "section", "sequence", "name", "unit", "quantity", "current_cost", "inclusion_status", "source_locator"
            )) + "</tr>"
            for line in estimate["lines"]
        )
        warnings = "".join(f"<li>{esc(item['code'])}: {esc(item['message'])}</li>" for item in calculation["warnings"])
        html_bytes = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>预算试算 v{revision}</title><style>body{{font:14px 'Microsoft YaHei',sans-serif;color:#263342;margin:32px auto;padding:0 20px;max-width:1100px}}h1{{font-size:24px}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #ddd;vertical-align:top}}th{{background:#f1f4f6}}.wide{{font-size:12px}}code{{overflow-wrap:anywhere}}@media print{{body{{margin:0}}}}</style>
<h1>预算试算 / 修订 v{revision}</h1><p>本地试算成果 · 非正式报价。源文件只读，税率为试用参数。</p>
<p>项目：{esc(str(estimate['project_id']))}<br>预算：{esc(str(estimate['estimate_id']))}<br>计算运行：<code>{esc(str(calculation['calculation_run_id']))}</code><br>输入哈希：<code>{esc(str(calculation['input_hash']))}</code></p>
<h2>汇总</h2><table>{summary_rows}</table><h2>计算提示</h2><ul>{warnings or '<li>无</li>'}</ul>
<h2>明细</h2><table class="wide"><thead><tr><th>区域</th><th>序号</th><th>项目</th><th>单位</th><th>工程量</th><th>当前成本</th><th>范围</th><th>来源</th></tr></thead><tbody>{line_rows}</tbody></table>
<p>公式版本：{esc(str(calculation['formula_version']))}。导出绑定预算修订 v{revision}。</p></html>'''.encode("utf-8")
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["estimate_id", "revision_no", "calculation_run_id", "input_hash", "section", "sequence", "item", "unit", "quantity", "current_cost", "inclusion_status", "source_locator"])
        for line in estimate["lines"]:
            writer.writerow([estimate["estimate_id"], revision, calculation["calculation_run_id"], calculation["input_hash"], *[line.get(key) or "" for key in ("section", "sequence", "name", "unit", "quantity", "current_cost", "inclusion_status", "source_locator")]])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return {
            "estimate_report_html": (f"estimate-v{revision}.html", "text/html; charset=utf-8", html_bytes),
            "estimate_detail_csv": (f"estimate-v{revision}.csv", "text/csv; charset=utf-8", csv_bytes),
        }

    def export_estimate(self, organization_id: str, project_id: str, estimate_id: str, actor_id: str = "local-user") -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            estimate = self.get_estimate(organization_id, project_id, estimate_id, connection=connection)
            revision = estimate["revision_no"]
            existing = connection.query('artifacts', (estimate_id, revision)).fetchall()
            if existing:
                for artifact in existing:
                    self._artifact_path(artifact)
                return {"estimate_id": estimate_id, "revision_no": revision, "items": [dict(row) for row in existing]}
            export_root = self.runtime_root / "projects" / "estimate-exports" / new_id("estimate-export")
            export_root.mkdir(parents=True, exist_ok=False)
            items = []
            now = now_iso()
            for kind, (filename, content_type, data) in self._artifact_outputs(estimate).items():
                path = export_root / filename
                with path.open("xb") as target:
                    target.write(data)
                digest = hashlib.sha256(data).hexdigest()
                artifact_id = new_id("estimate-artifact")
                connection.query('insert_artifact', (artifact_id, organization_id, project_id, estimate_id, revision, kind, filename, content_type, str(path.relative_to(self.runtime_root)), digest, len(data), now))
                items.append({"artifact_id": artifact_id, "estimate_id": estimate_id, "revision_no": revision, "artifact_kind": kind, "filename": filename, "content_type": content_type, "sha256": digest, "size_bytes": len(data), "status": "draft", "created_at": now})
        items.sort(key=lambda item: item["artifact_kind"])
        return {"estimate_id": estimate_id, "revision_no": revision, "items": items}

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id, write=False) as connection:
            row = connection.query('artifact', (artifact_id, organization_id, project_id)).fetchone()
        if row is None:
            raise EstimateServiceError(404, "NOT_FOUND", "预算成果不存在")
        return dict(row), self._artifact_path(row)

    def _artifact_path(self, row):
        path = (self.runtime_root / row["relative_path"]).resolve()
        try:
            path.relative_to(self.runtime_root.resolve())
        except ValueError as error:
            raise EstimateServiceError(500, "INVALID_ARTIFACT_PATH", "预算成果路径无效") from error
        if not path.is_file():
            raise EstimateServiceError(404, "ARTIFACT_MISSING", "预算成果文件不存在")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if path.stat().st_size != row["size_bytes"] or digest != row["sha256"]:
            raise EstimateServiceError(409, "ARTIFACT_INTEGRITY", "预算成果字节与保存的版本不一致，请保留现场并检查备份")
        return path
