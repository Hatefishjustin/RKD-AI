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


def geometry_projection_digest(document: dict) -> str:
    """Digest of the geometry-bearing projection of an adapted document.

    R3: volatile metadata (timestamps, run evidence text, notes) is excluded;
    zones/circulation/furniture/legacy objects and the site binding are included.
    Comparing this digest to one re-derived from the IMMUTABLE source candidate
    detects content edits (e.g. a 100mm furniture shift) that keep the old
    self-reported ``spatial.source.sha256``.
    """
    spatial = document.get("spatial") or {}
    view = {
        "boundary_mm": (spatial.get("origin") or {}).get("boundary_mm"),
        "zones": spatial.get("zones") or [],
        "circulation": spatial.get("circulation") or [],
        "furniture": spatial.get("furniture") or [],
        "platforms": spatial.get("platforms") or [],
        "objects": document.get("objects") or [],
        "legacy_circulation": document.get("circulation") or [],
        "site_snapshot_sha256": (spatial.get("source") or {}).get("site_snapshot_sha256"),
        "basemap_files_sha256": (spatial.get("source") or {}).get("basemap_files_sha256"),
    }
    return A.sha256_hex(view)


def _origin_consistency_problems(document: dict) -> list[str]:
    """R3: every declaration of model-vs-fixture origin must agree."""
    generation = document.get("generation") or {}
    spatial = document.get("spatial") or {}
    source = spatial.get("source") or {}
    origin = source.get("design_origin") or {}
    verification = (spatial.get("adaptation") or {}).get("source_verification") or {}
    problems: list[str] = []
    real = generation.get("real_model") is True
    kind = origin.get("kind")
    origin_kind = source.get("origin_kind")
    verification_real = verification.get("generation_real_model") is True
    if real and kind != "real_model":
        problems.append(f"generation.real_model=true 与 design_origin.kind={kind!r} 冲突")
    if real and origin_kind not in (None, "real_model_output"):
        problems.append(f"generation.real_model=true 与 origin_kind={origin_kind!r} 冲突")
    if real and not verification_real:
        problems.append("generation.real_model=true 与适配来源核验结果冲突")
    if not real and (kind == "real_model" or origin_kind == "real_model_output" or verification_real):
        problems.append("来源声明升级为 real_model，但 generation.real_model 不是 true")
    return problems


def admit_document(document: dict, *, site: dict, basemap_dir: str | Path,
                   run_verifier: Any = None,
                   registry: ContractRegistry | None = None,
                   organization_id: str | None = None,
                   project_id: str | None = None,
                   source_candidate: dict | None = None,
                   provenance: dict | None = None) -> dict:
    """The single controlled entrance. Returns an ``admission`` block.

    R3 trusted context (all optional for backward-compatible isolation tests,
    all REQUIRED for a site-bound adoptable admission):

    * ``organization_id``/``project_id`` come from the CURRENT SERVICE CONTEXT,
      never from a field inside ``document``;
    * ``source_candidate`` is the immutable persisted candidate supplied by the
      repository.  Its digest is recomputed and compared to every declaration;
    * ``provenance`` is the trusted provenance the service used for adaptation.
      Re-adapting the immutable candidate with it must reproduce the document's
      geometry projection.
    """
    registry = registry or ContractRegistry()
    trusted = any(value is not None for value in
                  (organization_id, project_id, source_candidate, provenance))
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

    # R3: identity and content binding.  Project/organization come from the
    # CURRENT SERVICE CONTEXT, never from document-declared fields.  The source
    # candidate digest is recomputed from the immutable candidate supplied by
    # the repository, not from the self-reported spatial.source.sha256.
    spatial_source = ((document.get("spatial") or {}).get("source") or {})
    origin = spatial_source.get("design_origin") or {}
    declared_sha = str(spatial_source.get("sha256") or "")
    claims_project_id = str(((document.get("spatial") or {}).get("adaptation") or {})
                            .get("source_verification", {}).get("project_id") or "")
    if trusted:
        if not organization_id or not project_id:
            return reject_admission("ADMISSION_CONTEXT_INCOMPLETE",
                                    "可信准入需要当前服务的 organization_id/project_id")
    context_project_id = str(project_id) if project_id else claims_project_id
    if claims_project_id and claims_project_id != context_project_id:
        return reject_admission("PROJECT_IDENTITY_MISMATCH",
                                f"文档声明项目 {claims_project_id} 与服务上下文 {context_project_id} 不符")
    run_refs = [str(r) for r in (origin.get("run_refs") or [])]

    if trusted:
        # Bind the immutable source candidate.  The service passes the EXACT
        # candidate bytes it persisted; re-derive both its digest and its spatial
        # projection and require the document to match, so a 100mm furniture
        # shift (or any geometry edit) with a preserved old digest is rejected.
        if source_candidate is None:
            return reject_admission("SOURCE_CANDIDATE_REQUIRED",
                                    "可信准入必须提供仓储中的不可变源候选")
        cand, _note = A.candidate_from_persisted(source_candidate)
        recomputed_sha = A.sha256_hex(cand)
        if declared_sha != recomputed_sha:
            return reject_admission("SOURCE_DIGEST_MISMATCH",
                                    f"文档自报来源摘要 {declared_sha[:12]} 与不可变源候选重算 "
                                    f"{recomputed_sha[:12]} 不符")
        prov = provenance or {}
        try:
            rederived, _ = A.adapt_persisted_candidate(
                source_candidate, site=site, basemap_dir=basemap_dir,
                provenance=prov, created_at=str(document.get("created_at") or "trusted"),
                run_verifier=run_verifier)
        except A.RealModelSpatialAdaptationError as error:
            return reject_admission(error.code, error.message)
        if geometry_projection_digest(rederived) != geometry_projection_digest(document):
            return reject_admission("SOURCE_CONTENT_TAMPERED",
                                    "文档几何投影与不可变源候选重新适配的结果不一致")

    # Declaration consistency: generation.real_model, design_origin.kind,
    # origin_kind and the adapter's verification note must all agree.
    conflicts = _origin_consistency_problems(document)
    if conflicts:
        return reject_admission("SOURCE_DECLARATION_CONFLICT", "；".join(conflicts))

    verified: list[dict] = []
    if run_refs:
        from .controlled_run_ledger import RunLedgerError, assert_trusted_verifier

        try:
            verifier = assert_trusted_verifier(run_verifier)
            for ref in run_refs:
                verified.append(verifier.verify(
                    ref, project_id=context_project_id, candidate_sha256=declared_sha,
                    site_snapshot_sha256=integrity["site_snapshot_sha256"],
                    parent_revision_id=document.get("parent_revision_id")))
        except RunLedgerError as error:
            return reject_admission(error.code, error.message)
    if origin.get("kind") == "real_model":
        if not verified or any(r.get("simulated") is not False or r.get("kind") != "real_model_run"
                               for r in verified):
            return reject_admission("DESIGN_ORIGIN_UNVERIFIED",
                                    "real_model 声明没有可核验的非模拟真实运行记录")
    if trusted:
        adoptable_scope = "site_bound"
        checks.append({"check": "identity", "ok": True,
                       "detail": {"organization_id": str(organization_id),
                                  "project_id": context_project_id,
                                  "source_candidate_sha256": declared_sha,
                                  "geometry_projection_sha256": geometry_projection_digest(document)}})
    else:
        # No service context: an isolated document can be inspected but never
        # promoted to a site-bound adoptable source.
        adoptable_scope = "isolated_test"
    checks.append({"check": "source", "ok": True,
                   "detail": {"kind": origin.get("kind") or "unknown",
                              "candidate_sha256": declared_sha,
                              "run_evidence_count": len(verified),
                              "generation_real_model": generation.get("real_model") is True,
                              "parent_verified": bool(verified) and
                              bool(document.get("parent_revision_id"))}})
    return {
        "status": "admitted" if trusted else "engineering_only",
        "adoptable": bool(trusted),
        "scope": adoptable_scope,
        "site_bound": bool(trusted),
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
