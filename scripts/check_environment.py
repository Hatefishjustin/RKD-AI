"""Check and prepare the local RKD runtime without touching source fixtures."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_PYTHON = (3, 12)
PINNED_PACKAGES = {
    "jsonschema": "4.25.1",
    "shapely": "2.1.2",
}
RUNTIME_DIRS = (
    Path("var"),
    Path("var") / "projects",
    Path("var") / "jobs",
    Path("var") / "logs",
)


def find_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "mvp").is_dir():
            return candidate
    raise RuntimeError("unable to locate RKD project root")


def version_tuple(version: str) -> tuple[int, ...]:
    values: list[int] = []
    for token in version.split("."):
        digits = "".join(character for character in token if character.isdigit())
        if not digits:
            break
        values.append(int(digits))
    return tuple(values)


def command_version(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if not executable:
        return {"status": "failed", "message": f"{command} not found on PATH"}
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "failed", "message": f"{command} version check failed: {error}"}
    output = (completed.stdout or completed.stderr).strip()
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "path": executable,
        "version": output,
        "returncode": completed.returncode,
    }


def package_check(name: str, expected: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError:
        return {"status": "skipped", "expected": expected, "message": "package is not installed"}
    except Exception as error:  # pragma: no cover - environment-specific import failures
        return {"status": "failed", "expected": expected, "message": str(error)}
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        actual = str(getattr(module, "__version__", "unknown"))
    return {
        "status": "passed" if actual == expected else "failed",
        "expected": expected,
        "actual": actual,
        "message": "version matches lock" if actual == expected else "version differs from lock",
    }


def ensure_runtime_dirs(root: Path) -> dict[str, Any]:
    created: list[str] = []
    for relative in RUNTIME_DIRS:
        directory = root / relative
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(relative.as_posix())
        if not directory.is_dir():
            raise RuntimeError(f"runtime path is not a directory: {directory}")
    runtime_root = (root / "var").resolve()
    fixture_root = (root / "fixtures").resolve()
    if runtime_root == fixture_root or fixture_root in runtime_root.parents:
        raise RuntimeError("runtime directory must stay outside the read-only fixtures tree")
    return {"status": "passed", "created": created, "path": str(runtime_root)}


def lock_digest(lock_path: Path) -> str:
    return hashlib.sha256(lock_path.read_bytes()).hexdigest()


def run_check(root: Path, strict: bool) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["python"] = {
        "status": "passed" if sys.version_info[:2] >= REQUIRED_PYTHON else "failed",
        "path": sys.executable,
        "version": platform.python_version(),
        "required": ".".join(map(str, REQUIRED_PYTHON)),
    }
    checks["node"] = command_version("node")
    checks["npm"] = command_version("npm")
    checks["runtime_directories"] = ensure_runtime_dirs(root)
    lock_path = root / "requirements.lock"
    checks["dependency_lock"] = {
        "status": "passed" if lock_path.is_file() else "failed",
        "path": str(lock_path),
        "sha256": lock_digest(lock_path) if lock_path.is_file() else None,
    }
    checks["packages"] = {
        name: package_check(name, version) for name, version in PINNED_PACKAGES.items()
    }
    checks["source_fixtures"] = {
        "status": "passed" if (root / "fixtures").is_dir() else "failed",
        "path": str((root / "fixtures").resolve()),
        "read_only_policy": "runtime writes are isolated under var/",
    }

    required_checks = ("python", "node", "npm", "runtime_directories", "dependency_lock", "source_fixtures")
    failures = [name for name in required_checks if checks[name].get("status") == "failed"]
    optional_missing = [name for name, result in checks["packages"].items() if result.get("status") == "skipped"]
    optional_failures = [name for name, result in checks["packages"].items() if result.get("status") == "failed"]
    if strict:
        failures.extend(optional_missing)
    failures.extend(optional_failures)
    status = "failed" if failures else ("skipped" if optional_missing else "passed")
    return {
        "schema_version": "rkd-environment-check.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "strict": strict,
        "status": status,
        "failures": failures,
        "skipped": optional_missing,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="project root; defaults to repository discovery")
    parser.add_argument("--strict", action="store_true", help="treat missing pinned packages as failures")
    args = parser.parse_args()
    root = (args.root or find_root()).resolve()
    report = run_check(root, strict=args.strict)
    report_path = root / "var" / "logs" / "environment-check.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(report_path)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
