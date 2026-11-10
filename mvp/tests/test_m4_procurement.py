import tempfile
import unittest
from pathlib import Path
import json
from http.client import HTTPConnection
import threading
from concurrent.futures import ThreadPoolExecutor

from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.api_server import create_server
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class M4ProcurementTests(unittest.TestCase):
    def test_multi_line_dispatch_is_atomic_and_replays_once(self):
        order = self.service.create_procurement_order("org-local", "m4-project", "tester", {
            "supplier_name": "Supplier", "delivery_location": "Site", "lines": [
                {"item_code": "A", "item_name": "Floor A", "ordered_quantity": "10", "unit": "m2"},
                {"item_code": "B", "item_name": "Floor B", "ordered_quantity": "8", "unit": "m2"},
            ]}, "multi-order-key-0001")
        lines = [{"line_id": row["line_id"], "quantity": row["ordered_quantity"]} for row in order["lines"]]
        received = self.service.receive_procurement("org-local", "m4-project", order["order_id"], "tester",
            {"receiver": "Person", "evidence_ref": "local://receipt", "lines": lines}, "multi-receive-key-0001")
        request = {"target_area": "Room", "recipient": "Team", "evidence_ref": "local://dispatch", "lines": lines}
        allocated = self.service.allocate_procurement("org-local", "m4-project", order["order_id"], "tester", request, "multi-dispatch-key-0001")
        self.assertEqual(allocated["status"], "allocated")
        self.assertEqual(len(allocated["allocations"]), 2)
        repeated = self.service.allocate_procurement("org-local", "m4-project", order["order_id"], "tester", request, "multi-dispatch-key-0001")
        self.assertEqual(repeated, allocated)
        self.assertEqual([row["remaining_quantity"] for row in repeated["lines"]], ["0", "0"])
        with self.assertRaises(ApiError) as error:
            self.service.allocate_procurement("org-local", "m4-project", order["order_id"], "tester",
                {**request, "target_area": "Other room"}, "multi-dispatch-key-0001")
        self.assertEqual(error.exception.code, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(received["status"], "received")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "app.sqlite3"
        self.store = SQLiteStore(self.db_path)
        self.service = ApiService(MVPApp(self.store))
        self.service.create_project("org-local", "采购测试", "m4-project")
        self.service.create_project("org-local", "隔离项目", "m4-other")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_order_receipt_allocation_conserves_quantity_and_is_idempotent(self):
        order = self.service.create_procurement_order(
            "org-local", "m4-project", "tester",
            {"supplier_name": "测试供应商", "delivery_location": "宁波展厅", "source_ref": "BOQ-v1", "lines": [{"item_code": "L-01", "item_name": "线性灯", "specification": "4000K", "ordered_quantity": "10", "unit": "套"}]},
            "m4-order-key-0001",
        )
        self.assertEqual(order["status"], "draft")
        self.assertFalse(order["external_effects_enabled"])
        duplicate = self.service.create_procurement_order(
            "org-local", "m4-project", "tester",
            {"supplier_name": "测试供应商", "delivery_location": "宁波展厅", "source_ref": "BOQ-v1", "lines": [{"item_code": "L-01", "item_name": "线性灯", "specification": "4000K", "ordered_quantity": "10", "unit": "套"}]},
            "m4-order-key-0001",
        )
        self.assertEqual(duplicate["order_id"], order["order_id"])
        line_id = order["lines"][0]["line_id"]
        received = self.service.receive_procurement(
            "org-local", "m4-project", order["order_id"], "receiver",
            {"receipt_no": "R-01", "receiver": "现场人员", "evidence_ref": "photo://r-01", "lines": [{"line_id": line_id, "quantity": "6"}]},
            "m4-receipt-key-001",
        )
        self.assertEqual(received["status"], "partially_received")
        self.assertEqual(received["lines"][0]["received_quantity"], "6")
        with self.assertRaises(ApiError) as too_much:
            self.service.receive_procurement(
                "org-local", "m4-project", order["order_id"], "receiver",
                {"receiver": "现场人员", "evidence_ref": "photo://r-02", "lines": [{"line_id": line_id, "quantity": "5"}]},
                "m4-receipt-key-002",
            )
        self.assertEqual(too_much.exception.code, "RECEIPT_EXCEEDS_ORDER")
        allocated = self.service.allocate_procurement(
            "org-local", "m4-project", order["order_id"], "manager",
            {"target_area": "接待区", "recipient": "施工班组 A", "evidence_ref": "dispatch://a-01", "lines": [{"line_id": line_id, "quantity": "4"}]},
            "m4-allocation-key-001",
        )
        self.assertEqual(allocated["status"], "partially_allocated")
        self.assertEqual(allocated["lines"][0]["allocated_quantity"], "4")
        self.assertEqual(allocated["lines"][0]["remaining_quantity"], "2")
        with self.assertRaises(ApiError) as too_many:
            self.service.allocate_procurement(
                "org-local", "m4-project", order["order_id"], "manager",
                {"target_area": "展厅", "recipient": "施工班组 B", "evidence_ref": "dispatch://b-01", "lines": [{"line_id": line_id, "quantity": "3"}]},
                "m4-allocation-key-002",
            )
        self.assertEqual(too_many.exception.code, "ALLOCATION_EXCEEDS_RECEIPT")
        with self.assertRaises(ApiError) as stale:
            self.service.allocate_procurement(
                "org-local", "m4-project", order["order_id"], "manager",
                {"expected_version": 1, "target_area": "展厅", "recipient": "施工班组 B", "evidence_ref": "dispatch://stale", "lines": [{"line_id": line_id, "quantity": "1"}]},
                "m4-allocation-stale-01",
            )
        self.assertEqual(stale.exception.code, "STALE_ORDER_VERSION")
        with self.assertRaises(ApiError) as isolated:
            self.service.get_procurement_order("org-local", "m4-other", order["order_id"])
        self.assertEqual(isolated.exception.status, 404)

    def test_procurement_survives_store_restart(self):
        order = self.service.create_procurement_order(
            "org-local", "m4-project", "tester",
            {"supplier_name": "供应商", "delivery_location": "现场", "lines": [{"item_name": "地毯", "ordered_quantity": "2.5", "unit": "卷"}]},
            "m4-restart-order-001",
        )
        self.store.close()
        restored = SQLiteStore(self.db_path)
        service = ApiService(MVPApp(restored))
        self.assertEqual(service.get_procurement_order("org-local", "m4-project", order["order_id"])["lines"][0]["ordered_quantity"], "2.5")
        restored.close()

    def test_duplicate_lines_and_concurrent_receipts_preserve_quantity(self):
        with self.assertRaises(ApiError) as rounded_zero:
            self.service.create_procurement_order("org-local", "m4-project", "tester", {"supplier_name": "测试", "delivery_location": "现场", "lines": [{"item_name": "材料", "ordered_quantity": "0.000001", "unit": "套"}]}, "quantity-too-small-001")
        self.assertEqual(rounded_zero.exception.code, "INVALID_QUANTITY")
        order = self.service.create_procurement_order("org-local", "m4-project", "tester", {"supplier_name": "测试", "delivery_location": "测试现场", "lines": [{"item_name": "灯具", "ordered_quantity": "10", "unit": "套"}]}, "quantity-order-test-001")
        line_id = order["lines"][0]["line_id"]
        payload = {"receiver": "测试收货人", "evidence_ref": "test://receipt", "lines": [{"line_id": line_id, "quantity": "6"}]}
        with self.assertRaises(ApiError) as duplicate:
            self.service.receive_procurement("org-local", "m4-project", order["order_id"], "tester", {**payload, "lines": payload["lines"] * 2}, "duplicate-receipt-test-001")
        self.assertEqual(duplicate.exception.code, "DUPLICATE_LINE")
        barrier = threading.Barrier(2)
        def receive(index):
            barrier.wait(3)
            try:
                self.service.receive_procurement("org-local", "m4-project", order["order_id"], "tester", payload, f"concurrent-receipt-{index:03}")
                return "ok"
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(receive, (1, 2)))
        self.assertCountEqual(results, ["ok", "RECEIPT_EXCEEDS_ORDER"])
        saved = self.service.get_procurement_order("org-local", "m4-project", order["order_id"])
        self.assertEqual(saved["lines"][0]["received_quantity"], "6")
        self.assertEqual(len(saved["receipts"]), 1)
        allocation = {"target_area": "展厅", "recipient": "班组", "evidence_ref": "test://allocation", "lines": [{"line_id": line_id, "quantity": "4"}]}
        with self.assertRaises(ApiError) as duplicate:
            self.service.allocate_procurement("org-local", "m4-project", order["order_id"], "tester", {**allocation, "lines": allocation["lines"] * 2}, "duplicate-allocation-001")
        self.assertEqual(duplicate.exception.code, "DUPLICATE_LINE")
        def allocate(index):
            barrier.wait(3)
            try:
                self.service.allocate_procurement("org-local", "m4-project", order["order_id"], "tester", allocation, f"concurrent-allocation-{index:03}")
                return "ok"
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(allocate, (1, 2))), ["ok", "ALLOCATION_EXCEEDS_RECEIPT"])
        saved = self.service.get_procurement_order("org-local", "m4-project", order["order_id"])
        self.assertEqual(saved["lines"][0]["remaining_quantity"], "2")
        self.assertEqual(len(saved["allocations"]), 1)

    def test_http_order_receipt_allocation_slice(self):
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(method, path, body=None, key=None):
                connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
                headers = {"X-Organization-Id": "org-local", "Content-Type": "application/json"}
                if key:
                    headers["Idempotency-Key"] = key
                encoded = json.dumps(body).encode() if body is not None else None
                if encoded:
                    headers["Content-Length"] = str(len(encoded))
                connection.request(method, path, body=encoded, headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode())
                connection.close()
                return response.status, payload

            status, order = request("POST", "/api/v1/projects/m4-project/procurement/orders", {"supplier_name": "HTTP供应商", "delivery_location": "现场", "lines": [{"item_name": "门把手", "ordered_quantity": "3", "unit": "件"}]}, "http-m4-order-0001")
            self.assertEqual(status, 201)
            line_id = order["lines"][0]["line_id"]
            status, received = request("POST", f"/api/v1/projects/m4-project/procurement/orders/{order['order_id']}/receipts", {"receiver": "HTTP人员", "evidence_ref": "photo://http", "lines": [{"line_id": line_id, "quantity": "3"}]}, "http-m4-receive-001")
            self.assertEqual(status, 201)
            status, allocated = request("POST", f"/api/v1/projects/m4-project/procurement/orders/{order['order_id']}/allocations", {"target_area": "门厅", "recipient": "班组 A", "evidence_ref": "dispatch://http", "lines": [{"line_id": line_id, "quantity": "3"}]}, "http-m4-allocate-001")
            self.assertEqual(status, 201)
            self.assertEqual(allocated["status"], "allocated")
            status, listed = request("GET", "/api/v1/projects/m4-project/procurement/orders")
            self.assertEqual(status, 200)
            self.assertEqual(listed["items"][0]["order_id"], order["order_id"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
