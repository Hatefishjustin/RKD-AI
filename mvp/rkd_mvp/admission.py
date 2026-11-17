"""One controlled admission entrance for formal design candidates.

The 2253899 review found three separate holes:

* ``adapt_persisted_candidate(skip_site_integrity=True)`` bypassed the only site
  gate and still produced an output that looked adoptable;
* the real service (``ai_design_option_service``) still loaded only the v1
  schema, so v2 was "authoritative" only inside a verification script;
* "old consumer rejects v2" was asserted by comparing version strings, not by
  running a consumer that dispatches on version.

This module makes the gate explicit and shared:

``ContractRegistry``
    Version dispatch.  An unknown version raises ``UNSUPPORTED_SCHEMA_VERSION``
    (a real consumer decision), not merely a schema mismatch.  A registry built
    with only v1 is the honest stand-in for the OLD consumer.

``admit_document``
    The single entrance: contract version -> site snapshot binding -> geometry
    (keep-outs, entrance connection, source/legacy/spatial projection) -> source
    evidence through the controlled verifier.  Returns an ``admission`` block
    with ``status``/``adoptable``/``scope`` that is persisted with the revision.
    ``not_validated`` is never adoptable.

No network, no external keys.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import realmodel_spatial_adapter as A

CONTRACTS = {
    "rkd-ai-design-option.v1": "contracts/v1/ai-design-option.schema.json",
    "rkd-ai-design-option.v2": "contracts/v2/ai-design-option.schema.json",
}
ROOT = Path(__file__).resolve().parents[2]
LEGACY_BOUNDARY_SOURCES = {"test_parameters_not_site_verified",
                           "manual_boundary_not_site_verified"}


class UnsupportedSchemaVersion(Exception):
    code = "UNSUPPORTED_SCHEMA_VERSION"

    def __init__(self, version: Any, supported: list[str]) -> None:
        self.version = version
        self.supported = supported
        super().__init__(f"不支持的契约版本 {version!r}；本消费者支持 {supported}")


class ContractViolation(Exception):
    code = "SCHEMA_INVALID"

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("；".join(errors[:4]))


class ContractRegistry:
    """Version-dispatching consumer. Restricting ``versions`` = an old consumer."""

    def __init__(self, root: str | Path | None = None, *, versions: tuple[str, ...] | None = None) -> None:
        base = Path(root).resolve() if root else ROOT
        self.schemas: dict[str, dict] = {}
        self.validators: dict[str, Draft202012Validator] = {}
        for version, relative in CONTRACTS.items():
            if versions is not None and version not in versions:
                continue
            schema = json.loads((base / relative).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.schemas[version] = schema
            self.validators[version] = Draft202012Validator(schema)
        if not self.validators:
            raise ValueError("契约注册表为空")

    @property
    def supported_versions(self) -> list[str]:
        return sorted(self.validators)

    def validate(self, document: Any) -> dict:
        if not isinstance(document, dict):
            raise ContractViolation(["候选不是 JSON 对象"])
        version = document.get("schema_version")
        if version not in self.validators:
            raise UnsupportedSchemaVersion(version, self.supported_versions)
        errors = sorted(self.validators[version].iter_errors(document),
                        key=lambda error: list(error.path))
        if errors:
            raise ContractViolation([f"{list(e.path)}: {e.message}" for e in errors])
        return document


def legacy_consumer_validate(document: dict, root: str | Path | None = None) -> dict:
    """Stand-in for a consumer that only knows v1 (the shipped service)."""
    return ContractRegistry(root, versions=("rkd-ai-design-option.v1",)).validate(document)


def engineering_admission(document: dict) -> dict:
    """Synthetic v1 engineering bridge: usable, but explicitly NOT site-bound."""
    return {
        "status": "engineering_only",
        "adoptable": True,
        "scope": "engineering_only",
        "site_bound": False,
        "site_snapshot_sha256": None,
        "basemap_files_sha256": None,
        "checks": [{"check": "contract", "ok": True, "detail": document.get("schema_version")}],
        "blockers": ["非场地绑定、非真实模型：只用于工程桥与回归，不作为真实设计成果"],
    }


def reject_admission(code: str, message: str, **extra: Any) -> dict:
    return {"status": "not_validated", "adoptable": False, "scope": "isolated_test",
            "site_bound": False, "site_snapshot_sha256": None, "basemap_files_sha256": None,
            "checks": [{"check": code, "ok": False, "detail": message}],
            "blockers": [f"{code}: {message}"], **extra}


def admit_document(document: dict, *, site: dict, basemap_dir: str | Path,
                   run_verifier: Any = None,
                   registry: ContractRegistry | None = None) -> dict:
    """The single controlled entrance. Returns an ``admission`` block."""
    registry = registry or ContractRegistry()
    try:
        registry.validate(document)
    except UnsupportedSchemaVersion as error:
        return reject_admission(error.code, str(error))
    except ContractViolation as error:
        return reject_admission(error.code, str(error))

    version = document.get("schema_version")
    generation = document.get("generation") or {}
    if version == "rkd-ai-design-option.v1":
        if generation.get("real_model") is True:
            return reject_admission(
                "REAL_MODEL_REQUIRES_V2",
                "v1 文档不能承载场地快照；声明真实模型时必须使用并核验 v2")
        if (document.get("boundary") or {}).get("boundary_source") not in LEGACY_BOUNDARY_SOURCES:
            return reject_admission("V1_BOUNDARY_UNKNOWN",
                                    "v1 边界来源不在已知工程测试取值内")
        return engineering_admission(document)

    checks: list[dict] = [{"check": "contract", "ok": True, "detail": version}]
    try:
        integrity = A.verify_persisted_site_snapshot(document, site, basemap_dir)
        geometry = A.validate_candidate_geometry_against_site(document, site, basemap_dir)
        projections = A.verify_geometry_projection_consistency(document)
    except A.RealModelSpatialAdaptationError as error:
        return reject_admission(error.code, error.message)
    checks.append({"check": "site_snapshot", "ok": True,
                   "detail": {"site_snapshot_sha256": integrity["site_snapshot_sha256"],
                              "basemap_files_sha256": integrity["basemap_files_sha256"],
                              "entrance_mm": integrity["entrance_mm"]}})
    checks.append({"check": "geometry", "ok": True, "detail": geometry})
    checks.append({"check": "projection_consistency", "ok": True, "detail": projections})

    # Source: verify the run references through the CONTROLLED verifier only.
    # The candidate digest is the one the adapter recorded for its input; a run
    # record must match it AND the site snapshot.  We do not re-derive it from
    # the output document (that would be a different object graph).
    spatial_source = ((document.get("spatial") or {}).get("source") or {})
    origin = spatial_source.get("design_origin") or {}
    declared_sha = str(spatial_source.get("sha256") or "")
    project_id = str(((document.get("spatial") or {}).get("adaptation") or {})
                     .get("source_verification", {}).get("project_id") or "unknown_project")
    run_refs = [str(r) for r in (origin.get("run_refs") or [])]
    verified: list[dict] = []
    if run_refs:
        from .controlled_run_ledger import RunLedgerError, assert_trusted_verifier

        try:
            verifier = assert_trusted_verifier(run_verifier)
            for ref in run_refs:
                verified.append(verifier.verify(
                    ref, project_id=project_id, candidate_sha256=declared_sha,
                    site_snapshot_sha256=integrity["site_snapshot_sha256"],
                    parent_revision_id=document.get("parent_revision_id")))
        except RunLedgerError as error:
            return reject_admission(error.code, error.message)
    if origin.get("kind") == "real_model":
        if not verified or any(r.get("simulated") is not False or r.get("kind") != "real_model_run"
                               for r in verified):
            return reject_admission("DESIGN_ORIGIN_UNVERIFIED",
                                    "real_model 声明没有可核验的非模拟真实运行记录")
    checks.append({"check": "source", "ok": True,
                   "detail": {"kind": origin.get("kind") or "unknown",
                              "candidate_sha256": declared_sha,
                              "run_evidence_count": len(verified),
                              "generation_real_model": origin.get("kind") == "real_model",
                              "parent_verified": bool(verified) and
                              bool(document.get("parent_revision_id"))}})
    return {
        "status": "admitted",
        "adoptable": True,
        "scope": "site_bound",
        "site_bound": True,
        "site_snapshot_sha256": integrity["site_snapshot_sha256"],
        "basemap_files_sha256": integrity["basemap_files_sha256"],
        "checks": checks,
        "blockers": [],
    }


def resolve_legacy_admission(document: dict) -> dict:
    """Admission for revisions persisted before the gate existed (no block)."""
    generation = document.get("generation") or {}
    if generation.get("real_model") is True:
        return reject_admission("REAL_MODEL_REQUIRES_V2", "历史 v1 真实模型声明无法核验")
    version = document.get("schema_version")
    if version == "rkd-ai-design-option.v1":
        return engineering_admission(document)
    return reject_admission("ADMISSION_NOT_RECORDED", "v2 候选没有准入党，不能采用")
