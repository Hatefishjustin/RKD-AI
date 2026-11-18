"""Stability check: repeated runs of the W3 source-record tests must be clean.

The previous teardown did not track the services it created, so a worker could
still be writing a layout SVG / SQLite row when the temporary directory was
removed.  The resulting thread traceback was printed while unittest still
reported OK.  This harness runs the module N times in fresh subprocesses and
fails on ANY unhandled-thread / cleanup traceback, while also requiring 5/5 OK.

    python scripts/verify_w3_test_thread_hygiene.py --runs 5 \
        --out var/evidence/roadmap/W3-test-hygiene/after
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PATTERN = "test_w3_r1r2_source_records.py"
BAD_PATTERNS = (
    "Exception in thread",
    "Unhandled exception in thread",
    "FileNotFoundError",
    "OperationalError: unable to open database file",
    "Traceback (most recent call last)",
    "worker 未安全收尾",
    "后台线程出现未处理异常",
)


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def run_once(index: int) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / part) for part in ("mvp", "scripts", "."))
    command = [sys.executable, "-m", "unittest", "discover",
               "-s", str(ROOT / "mvp" / "tests"), "-p", TEST_PATTERN]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                               text=True, errors="replace", timeout=300)
    output = (completed.stdout or "") + (completed.stderr or "")
    matched = sorted({pattern for pattern in BAD_PATTERNS if pattern in output})
    result_ok = bool(re.search(r"^Ran 5 tests\b", output, re.MULTILINE)
                     and re.search(r"^OK$", output, re.MULTILINE))
    return {"run": index, "exit_code": completed.returncode,
            "five_tests_ok": result_ok, "thread_or_cleanup_errors": matched,
            "ok": completed.returncode == 0 and result_ok and not matched,
            "tail": output.strip().splitlines()[-8:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    runs = [run_once(index + 1) for index in range(args.runs)]
    audit = {"schema_version": "rkd-w3-test-thread-hygiene.v1",
             "baseline": "26ae391", "test_module": TEST_PATTERN,
             "runs": args.runs, "results": runs,
             "summary": {"clean_runs": sum(1 for item in runs if item["ok"]),
                         "dirty_runs": sum(1 for item in runs if not item["ok"])},
             "external_calls": 0, "cost_cny": 0}
    (out / "test-hygiene.json").write_bytes(canon(audit))
    print(json.dumps(audit["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if audit["summary"]["dirty_runs"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
