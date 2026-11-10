"""Reproduce AUD-01..04 over real HTTP and restart only our isolated server."""
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))


def serve(runtime):
    from rkd_mvp.api_server import create_server
    from rkd_mvp.api_service import ApiService
    from rkd_mvp.engine import MVPApp
    from rkd_mvp.identity import LocalIdentityProvider
    from rkd_mvp.sqlite_store import SQLiteStore
    if not runtime.is_relative_to((ROOT / "var/evidence/m2-audit-fixes").resolve()):
        raise ValueError("isolated runtime required")
    store = SQLiteStore(runtime / "app.sqlite3")
    server = create_server(ApiService(MVPApp(store)), LocalIdentityProvider(), port=0)
    print(json.dumps({"port": server.server_address[1], "pid": os.getpid()}), flush=True)
    server.serve_forever()


def main():
    runtime = ROOT / "var/evidence/m2-audit-fixes" / (datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6])
    runtime.mkdir(parents=True)
    process = None
    checks = {}
    processes = []
    report = {"passed": False, "checks": checks, "runtime": str(runtime), "processes": processes}

    def start():
        nonlocal process
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--server", str(runtime)],
                                   stdout=subprocess.PIPE, stderr=log, text=True)
        # The child prints only after its loopback socket has bound.
        info = json.loads(process.stdout.readline())
        processes.append(info)
        return info["port"]

    def stop():
        nonlocal process
        if process is not None:
            process.terminate()
            process.wait(timeout=20)
            process.stdout.close()
            process = None

    def request(method, path, body=None, expected=200):
        conn = HTTPConnection("127.0.0.1", port, timeout=20)
        try:
            conn.request(method, path, json.dumps(body) if body is not None else None,
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            data = response.read()
            assert response.status == expected, (response.status, data)
            return data
        finally:
            conn.close()

    def save(revision, width="10", cost="100", unit="floor-a"):
        return json.loads(request("POST", "/api/v1/projects/audit/spatial/revisions", {
            "spatial_unit_id": unit, "width": width, "length": "5", "expected_revision": revision,
            "pricing": {"unit_cost_net": cost, "cost_markup": "0.20", "trial_tax_rate": "0.05"},
            "change_reason": "AUD regression via real HTTP",
        }, 201))

    with (runtime / "server.log").open("w", encoding="utf-8") as log:
        try:
            port = start()
            request("POST", "/api/v1/projects", {"name": "M2 隔离审核复验", "project_id": "audit"}, 201)
            # HTTP allocates project IDs, so discover the actual ID and keep the
            # request helper's route rewriting local to this isolated run.
            projects = json.loads(request("GET", "/api/v1/projects"))["items"]
            project_id = projects[0]["project_id"]
            raw_request = request
            def request(method, path, body=None, expected=200):
                return raw_request(method, path.replace("/projects/audit/", f"/projects/{project_id}/"), body, expected)
            first = save(0)
            originals = {a["artifact_id"]: request("GET", a["download_url"]) for a in first["artifacts"]}
            priced = save(1, cost="200")
            assert priced["quote"]["result"]["sale_gross"] == "12600.00"
            checks["AUD-01"] = {"passed": True, "before_gross": first["quote"]["result"]["sale_gross"], "after_gross": priced["quote"]["result"]["sale_gross"]}
            save(2, width="12", cost="200")
            reverted = save(3, cost="200")
            assert reverted["revision_no"] == 4 and reverted["width"] == "10"
            assert save(4, cost="200")["geometry_revision_id"] == reverted["geometry_revision_id"]
            save(0, width="8", unit="floor-b")
            for a in first["artifacts"]:
                data = request("GET", a["download_url"])
                assert data == originals[a["artifact_id"]]
                assert hashlib.sha256(data).hexdigest() == a["sha256"]
            checks["AUD-03"] = {"passed": True, "old_files_unchanged": len(originals)}
            archive_item = next(a for a in reverted["artifacts"] if a["artifact_kind"] == "package_zip")
            package = request("GET", archive_item["download_url"])
            (runtime / "downloaded-production-v4.zip").write_bytes(package)
            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                manifest = json.loads(archive.read("manifest-v4.json"))
                row = next(csv.DictReader(io.StringIO(archive.read("quantity-v4.csv").decode("utf-8-sig"))))
                quantity_id = reverted["quantity_items"][0]["quantity_item_id"]
                assert manifest["quantity_item_id"] == row["quantity_item_id"] == quantity_id
                for item in manifest["files"]:
                    assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
            checks["AUD-04"] = {"passed": True, "quantity_id": quantity_id}
            stop()
            port = start()
            current = json.loads(request("GET", "/api/v1/projects/audit/spatial"))["items"][0]
            assert current["geometry_revision_id"] == reverted["geometry_revision_id"]
            assert current["width"] == "10" and current["quote"]["result"]["sale_gross"] == "12600.00"
            assert len(processes) == 2 and processes[0]["pid"] != processes[1]["pid"]
            checks["AUD-02"] = {"passed": True, "revision_after_process_restart": current["revision_no"], "width": current["width"]}
            item = first["artifacts"][0]
            with closing(sqlite3.connect(runtime / "app.sqlite3")) as db:
                relative = db.execute("SELECT relative_path FROM spatial_artifacts WHERE artifact_id=?", (item["artifact_id"],)).fetchone()[0]
            path = runtime / relative
            data = path.read_bytes()
            path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            assert json.loads(request("GET", item["download_url"], expected=500))["error_code"] == "ARTIFACT_INTEGRITY"
            checks["tampered_download_rejected"] = True
            report["passed"] = True
        finally:
            stop()
            (runtime / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        serve(Path(sys.argv[2]).resolve())
    else:
        main()
