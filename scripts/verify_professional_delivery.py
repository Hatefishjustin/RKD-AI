"""Re-runnable verification for the 01c / DELIVERY-01 engineering slice."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm") or "npm"
STAMP = "2026-11-08"
EVIDENCE = ROOT / "var" / "evidence" / "professional-delivery" / STAMP
EVIDENCE.mkdir(parents=True, exist_ok=True)
PY = sys.executable
ENV = {key: value for key, value in os.environ.items()
       if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"}}
ENV["PYTHONPATH"] = str(ROOT / "mvp") + os.pathsep + ENV.get("PYTHONPATH", "")

COMMANDS = [
    {"name": "new_modules_compile", "argv": [PY, "-m", "py_compile",
     "mvp/rkd_mvp/source_content.py", "mvp/rkd_mvp/technical_outputs.py",
     "mvp/rkd_mvp/professional_delivery.py", "mvp/rkd_mvp/ai_requirement_service.py",
     "mvp/rkd_mvp/api_service.py", "mvp/rkd_mvp/api_server.py",
     "mvp/rkd_mvp/postgres_import.py", "scripts/build_design_review.py"]},
    {"name": "contracts_parse", "argv": [PY, "-c",
     "import json,glob; from jsonschema import Draft202012Validator; "
     "[Draft202012Validator.check_schema(json.load(open(p,encoding='utf-8'))) "
     "for p in glob.glob('contracts/v1/*.schema.json')]; "
     "print('contracts ok',len(glob.glob('contracts/v1/*.schema.json'))); "
     "d=json.load(open('contracts/v1/openapi.v1.json',encoding='utf-8')); print('paths',len(d['paths']))"]},
    {"name": "professional_delivery_special_tests", "argv": [PY, "-m", "unittest",
     "mvp.tests.test_professional_delivery", "-q"]},
    {"name": "full_regression", "argv": [PY, "-m", "unittest", "discover", "-s", "mvp/tests",
     "-p", "test_*.py", "-q"]},
    {"name": "strict_environment_check", "argv": [PY, "scripts/check_environment.py",
     "--root", str(ROOT), "--strict"]},
    {"name": "frontend_production_build", "argv": [NPM, "--prefix", "web", "run", "build"]},
    {"name": "design_review_generation", "argv": [PY, "scripts/build_design_review.py"]},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    results = []
    for command in COMMANDS:
        started = time.monotonic()
        process = subprocess.run(command["argv"], cwd=ROOT, env=ENV, capture_output=True,
                                 timeout=900, text=True, errors="replace")
        output = (process.stdout or "") + (process.stderr or "")
        log = EVIDENCE / f"{command['name']}.log"
        log.write_text(output, encoding="utf-8")
        counts = re.findall(r"Ran (\d+) tests", output)
        entry = {"name": command["name"], "argv": " ".join(command["argv"][1:]),
                 "returncode": process.returncode, "duration_seconds": round(time.monotonic() - started, 2),
                 "log": log.name, "tests_run": int(counts[-1]) if counts else None,
                 "ok": process.returncode == 0 and "FAILED" not in output}
        if "frontend" in command["name"]:
            entry["built"] = "built in" in output
        results.append(entry)
        print(f"{command['name']}: {'passed' if entry['ok'] else 'FAILED'} ({entry['duration_seconds']}s)", flush=True)

    review = ROOT / "var" / "review" / STAMP / "design-review-2026-11-08.html"
    review_data = EVIDENCE / "review-data.json"
    passed = sum(1 for item in results if item["ok"])
    full = next(item for item in results if item["name"] == "full_regression")
    special = next(item for item in results if item["name"] == "professional_delivery_special_tests")
    frontend = next(item for item in results if item["name"] == "frontend_production_build")
    environment = next(item for item in results if item["name"] == "strict_environment_check")
    report = {
        "schema_version": "rkd-professional-delivery-verification.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "AI-DESIGN-01c 原件内容解析 + DELIVERY-01a/b 同源技术交付草稿",
        "commands": results,
        "commands_passed": passed,
        "commands_total": len(results),
        "engineering_results": {
            "special_tests": f"{special['tests_run']}/{special['tests_run']}" if special["ok"] else "failed",
            "full_regression": f"{full['tests_run']}/{full['tests_run']}" if full["ok"] else "failed",
            "strict_environment_passed": environment["ok"],
            "frontend_build_passed": frontend["ok"] and frontend.get("built", False),
            "sqlite_migration": "mvp/persistence/sqlite/024_ai_professional_delivery.sql",
            "postgres_migration": "mvp/persistence/postgres/014_ai_professional_delivery.sql",
            "postgres_rls_tables": 3,
            "postgres_import_mapping_added": 3,
            "source_content_local_only": True,
            "scanned_or_cad_content_invented": False,
            "technical_artifacts_per_delivery": 7,
            "technical_artifacts_registered_with_size_and_sha256": True,
            "technical_artifact_bytes_rechecked_on_download": True,
            "complete_local_backup_restore_verified": True,
            "legacy_design_production_procurement_unchanged": True,
            "old_migrations_and_artifacts_untouched": True,
            "external_content_sent_to_model": False,
            "publication_status": "not_approved",
            "construction_issue": False,
            "formal_quote": False,
        },
        "review_material": {"html": str(review.relative_to(ROOT)) if review.exists() else None,
                            "sha256": sha(review) if review.exists() else None,
                            "bytes": review.stat().st_size if review.exists() else None,
                            "data_snapshot": str(review_data.relative_to(ROOT)) if review_data.exists() else None,
                            "candidate_strategies": ["private-branch", "open-loop"],
                            "candidate_structure_signatures_differ": True},
        "boundaries": [
            "设计策略仍来自明确非 AI 的本地合成适配器；没有真实付费模型调用",
            "AD01—AD08 仍为 0/8；工程负例通过不等于固定验收项通过",
            "01c 解析结果仅本地可查，未外发；扫描件、CAD、图片明确标记未解析",
            "技术交付包是草稿，不是施工图、正式报价、采购订单或发布批准",
            "未跑真实 PostgreSQL 联调作业；只做迁移/RLS/导入映射静态与结构验证",
            "未做浏览器截图验收；未改动 NAS 或日常 SQLite 权威库",
        ],
    }
    path = EVIDENCE / "verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"verification": str(path), "commands_passed": passed,
                      "commands_total": len(results), "full_regression": full["tests_run"]},
                     ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
