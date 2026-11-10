from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import contextmanager, nullcontext
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso
from .procurement_repository import SQLiteProcurementRepository


class ProcurementServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ProcurementService:
    """Local, side-effect-free procurement facts for the first M4 slice."""

    def __init__(self, db_path: str | Path | None, *, repository=None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self.repository = repository or SQLiteProcurementRepository(self._db)

    def _transaction(self, org, project, *, write=False, connection=None):
        return (nullcontext(self.repository.bind(connection, org, project)) if connection is not None
                else self.repository.transaction(org, project, write=write))

    @contextmanager
    def _db(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if self.db_path is None:
            raise ProcurementServiceError(501, "PROCUREMENT_NOT_CONFIGURED", "local procurement storage is not configured")
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _quantity(value: Any, label: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ProcurementServiceError(400, "INVALID_QUANTITY", f"{label} must be a positive decimal") from error
        if not result.is_finite() or result <= 0:
            raise ProcurementServiceError(400, "INVALID_QUANTITY", f"{label} must be a positive decimal")
        try:
            rounded = result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except InvalidOperation as error:
            raise ProcurementServiceError(400, "INVALID_QUANTITY", f"{label} 超出可计算范围") from error
        if rounded <= 0:
            raise ProcurementServiceError(400, "INVALID_QUANTITY", f"{label} 小于支持的四位小数精度")
        return rounded

    @staticmethod
    def _text(value: Decimal) -> str:
        return format(value.normalize(), "f") if value else "0"

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _fingerprint(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _order_status(lines: list[dict[str, Any]]) -> str:
        ordered = sum((Decimal(line["ordered_quantity"]) for line in lines), Decimal("0"))
        received = sum((Decimal(line["received_quantity"]) for line in lines), Decimal("0"))
        allocated = sum((Decimal(line["allocated_quantity"]) for line in lines), Decimal("0"))
        if allocated == ordered:
            return "allocated"
        if allocated > 0:
            return "partially_allocated"
        if received == ordered:
            return "received"
        if received > 0:
            return "partially_received"
        return "draft"

    def _write_event(self, connection: sqlite3.Connection, organization_id: str, project_id: str,
                     event_type: str, aggregate_id: str, actor_id: str,
                     payload: dict[str, Any], idempotency_key: str | None = None) -> None:
        connection.write_event({"event_id": new_id("proc-event"), "event_type": event_type, "aggregate_id": aggregate_id,
                                "idempotency_key": idempotency_key, "payload_json": self._json(payload), "actor_id": actor_id,
                                "created_at": now_iso()})

    def _public_order(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        lines = []
        for line in connection.lines(row["order_id"]):
            lines.append({
                "line_id": line["line_id"], "item_code": line["item_code"], "item_name": line["item_name"],
                "specification": line["specification"], "ordered_quantity": line["ordered_quantity_text"],
                "received_quantity": line["received_quantity_text"], "allocated_quantity": line["allocated_quantity_text"],
                "remaining_quantity": self._text(Decimal(line["received_quantity_text"]) - Decimal(line["allocated_quantity_text"])),
                "unit": line["unit"],
            })
        receipts = []
        for receipt in connection.receipts(row["order_id"]):
            receipt_lines = [dict(item) for item in connection.receipt_lines(receipt["receipt_id"])]
            receipts.append({**dict(receipt), "lines": receipt_lines})
        allocations = [dict(item) for item in connection.allocations(row["order_id"])]
        return {**dict(row), "external_effects_enabled": bool(row["external_effects_enabled"]), "lines": lines, "receipts": receipts, "allocations": allocations}

    def list_orders(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self._transaction(organization_id, project_id) as connection:
            rows = connection.orders()
            return {"items": [self._public_order(connection, row) for row in rows]}

    def get_order(self, organization_id: str, project_id: str, order_id: str) -> dict[str, Any]:
        with self._transaction(organization_id, project_id) as connection:
            row = connection.order(order_id)
            if row is None:
                raise ProcurementServiceError(404, "NOT_FOUND", "采购订单不存在")
            return self._public_order(connection, row)

    def create_order(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str, *, connection=None) -> dict[str, Any]:
        supplier = str(request.get("supplier_name") or "").strip()
        location = str(request.get("delivery_location") or "").strip()
        source_kind = str(request.get("source_kind") or "manual_draft").strip()
        source_ref = str(request.get("source_ref") or "人工采购草稿").strip()
        lines_input = request.get("lines")
        if not supplier or not location or not isinstance(lines_input, list) or not lines_input:
            raise ProcurementServiceError(400, "INVALID_ORDER", "supplier_name、delivery_location 和至少一条订单行是必需的")
        if len(idempotency_key) < 16:
            raise ProcurementServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        lines: list[dict[str, str]] = []
        for item in lines_input:
            if not isinstance(item, dict):
                raise ProcurementServiceError(400, "INVALID_ORDER_LINE", "订单行必须是对象")
            quantity = self._quantity(item.get("ordered_quantity"), "订单数量")
            name = str(item.get("item_name") or "").strip()
            unit = str(item.get("unit") or "").strip()
            if not name or not unit:
                raise ProcurementServiceError(400, "INVALID_ORDER_LINE", "item_name 和 unit 是必需的")
            lines.append({"item_code": str(item.get("item_code") or "").strip(), "item_name": name, "specification": str(item.get("specification") or "unknown").strip() or "unknown", "quantity": self._text(quantity), "unit": unit})
        request_hash = self._fingerprint({"supplier_name": supplier, "delivery_location": location, "source_kind": source_kind, "source_ref": source_ref, "lines": lines})
        with self._transaction(organization_id, project_id, write=True, connection=connection) as connection:
            existing = connection.event(idempotency_key)
            if existing:
                if json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ProcurementServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的采购订单请求")
                return self._public_order(connection, connection.order(existing["aggregate_id"]))
            revision = connection.next_revision()
            order_id, now = new_id("purchase-order"), now_iso()
            connection.insert_order({"order_id": order_id, "revision_no": revision, "supplier_name": supplier,
                                     "delivery_location": location, "source_kind": source_kind, "source_ref": source_ref, "now": now})
            for item in lines:
                connection.insert_line({**item, "line_id": new_id("order-line"), "order_id": order_id, "now": now})
            self._write_event(connection, organization_id, project_id, "procurement.order_draft_created", order_id, actor_id, {"line_count": len(lines), "external_effects_enabled": False, "request_hash": request_hash}, idempotency_key)
            return self._public_order(connection, connection.order(order_id))

    def receive(self, organization_id: str, project_id: str, order_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ProcurementServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        receiver, evidence = str(request.get("receiver") or "").strip(), str(request.get("evidence_ref") or "").strip()
        if not receiver or not evidence or not isinstance(request.get("lines"), list) or not request["lines"]:
            raise ProcurementServiceError(400, "INVALID_RECEIPT", "receiver、evidence_ref 和收货行是必需的")
        request_hash = self._fingerprint({"receiver": receiver, "evidence_ref": evidence, "lines": request["lines"], "received_at": request.get("received_at")})
        with self._transaction(organization_id, project_id, write=True) as connection:
            duplicate = connection.event(idempotency_key)
            if duplicate:
                if duplicate["aggregate_id"] != order_id:
                    raise ProcurementServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于其他采购订单")
                stored = duplicate
                if json.loads(stored["payload_json"]).get("request_hash") != request_hash:
                    raise ProcurementServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的收货请求")
                return self._public_order(connection, connection.order(order_id))
            order = connection.order(order_id)
            if order is None:
                raise ProcurementServiceError(404, "NOT_FOUND", "采购订单不存在")
            if order["source_kind"] == "design_boq_draft":
                if not connection.source_current(order["source_ref"]):
                    raise ProcurementServiceError(409, "ORDER_SOURCE_OUTDATED", "该订单的设计量价基线已变化，请核对最新草稿后登记收货")
            if request.get("expected_version") is not None and int(request["expected_version"]) != int(order["version"]):
                raise ProcurementServiceError(409, "STALE_ORDER_VERSION", "采购订单已变化，请重新读取")
            receipt_lines: list[dict[str, Any]] = []
            seen_lines: set[str] = set()
            for item in request["lines"]:
                line_id, quantity = str(item.get("line_id") or ""), self._quantity(item.get("quantity"), "收货数量")
                if line_id in seen_lines:
                    raise ProcurementServiceError(400, "DUPLICATE_LINE", "同一笔收货不能重复填写同一订单行")
                seen_lines.add(line_id)
                line = connection.line(order_id, line_id)
                if line is None:
                    raise ProcurementServiceError(404, "NOT_FOUND", "订单行不存在")
                if Decimal(line["received_quantity_text"]) + quantity > Decimal(line["ordered_quantity_text"]):
                    raise ProcurementServiceError(409, "RECEIPT_EXCEEDS_ORDER", f"收货数量超过订单行 {line_id} 的未收数量")
                receipt_lines.append({"line": line, "quantity": quantity})
            receipt_id, now = new_id("receipt"), now_iso()
            connection.insert_receipt({"receipt_id": receipt_id, "order_id": order_id, "receipt_no": str(request.get("receipt_no") or receipt_id),
                                       "received_at": str(request.get("received_at") or now), "receiver": receiver, "evidence_ref": evidence,
                                       "note": str(request.get("note") or ""), "idempotency_key": idempotency_key, "now": now})
            for item in receipt_lines:
                connection.insert_receipt_line({"receipt_line_id": new_id("receipt-line"), "receipt_id": receipt_id, "order_id": order_id,
                                                "line_id": item["line"]["line_id"], "quantity": self._text(item["quantity"]), "unit": item["line"]["unit"]})
                connection.update_line(order_id, item["line"]["line_id"], "received", self._text(Decimal(item["line"]["received_quantity_text"]) + item["quantity"]))
            lines = [{"ordered_quantity": item["ordered_quantity_text"], "received_quantity": item["received_quantity_text"], "allocated_quantity": item["allocated_quantity_text"]} for item in connection.lines(order_id)]
            status = self._order_status(lines)
            connection.update_order(order_id, status, now)
            self._write_event(connection, organization_id, project_id, "procurement.received", order_id, actor_id, {"receipt_id": receipt_id, "line_count": len(receipt_lines), "request_hash": request_hash}, idempotency_key)
            return self._public_order(connection, connection.order(order_id))

    def allocate(self, organization_id: str, project_id: str, order_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ProcurementServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        target, recipient, evidence = str(request.get("target_area") or "").strip(), str(request.get("recipient") or "").strip(), str(request.get("evidence_ref") or "").strip()
        if not target or not recipient or not evidence or not isinstance(request.get("lines"), list) or not request["lines"]:
            raise ProcurementServiceError(400, "INVALID_ALLOCATION", "target_area、recipient、evidence_ref 和分派行是必需的")
        request_hash = self._fingerprint({"target_area": target, "recipient": recipient, "evidence_ref": evidence, "lines": request["lines"]})
        with self._transaction(organization_id, project_id, write=True) as connection:
            duplicate = connection.event(idempotency_key)
            if duplicate:
                if duplicate["aggregate_id"] != order_id:
                    raise ProcurementServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于其他采购订单")
                stored = duplicate
                if json.loads(stored["payload_json"]).get("request_hash") != request_hash:
                    raise ProcurementServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的分派请求")
                return self._public_order(connection, connection.order(order_id))
            order = connection.order(order_id)
            if order is None:
                raise ProcurementServiceError(404, "NOT_FOUND", "采购订单不存在")
            if request.get("expected_version") is not None and int(request["expected_version"]) != int(order["version"]):
                raise ProcurementServiceError(409, "STALE_ORDER_VERSION", "采购订单已变化，请重新读取")
            allocations: list[tuple[sqlite3.Row, Decimal]] = []
            seen_lines: set[str] = set()
            for item in request["lines"]:
                line_id, quantity = str(item.get("line_id") or ""), self._quantity(item.get("quantity"), "分派数量")
                if line_id in seen_lines:
                    raise ProcurementServiceError(400, "DUPLICATE_LINE", "同一笔分派不能重复填写同一订单行")
                seen_lines.add(line_id)
                line = connection.line(order_id, line_id)
                if line is None:
                    raise ProcurementServiceError(404, "NOT_FOUND", "订单行不存在")
                if Decimal(line["allocated_quantity_text"]) + quantity > Decimal(line["received_quantity_text"]):
                    raise ProcurementServiceError(409, "ALLOCATION_EXCEEDS_RECEIPT", f"分派数量超过订单行 {line_id} 的已收货未分派数量")
                allocations.append((line, quantity))
            allocation_batch_id, now = new_id("allocation-batch"), now_iso()
            for line, quantity in allocations:
                connection.insert_allocation({"allocation_id": new_id("allocation"), "order_id": order_id, "line_id": line["line_id"],
                                              "quantity": self._text(quantity), "target_area": target, "recipient": recipient, "evidence_ref": evidence,
                                              "note": str(request.get("note") or ""), "idempotency_key": idempotency_key, "now": now})
                connection.update_line(order_id, line["line_id"], "allocated", self._text(Decimal(line["allocated_quantity_text"]) + quantity))
            lines = [{"ordered_quantity": item["ordered_quantity_text"], "received_quantity": item["received_quantity_text"], "allocated_quantity": item["allocated_quantity_text"]} for item in connection.lines(order_id)]
            status = self._order_status(lines)
            connection.update_order(order_id, status, now)
            self._write_event(connection, organization_id, project_id, "procurement.allocated", order_id, actor_id, {"allocation_batch_id": allocation_batch_id, "target_area": target, "line_count": len(allocations), "request_hash": request_hash}, idempotency_key)
            return self._public_order(connection, connection.order(order_id))
