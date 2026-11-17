"""Reproduce the six 2253899 trust findings against a given code root.

The SAME harness runs on the frozen baseline copy and on the fixed working tree;
only the target code root changes.  Every case drives real code: a real provider
call through a protocol stub that captures request bytes, the real SQLite
repository, the real adapter, the real package builder and the real manifest
checker.  No case merely re-reads a JSON field that a script wrote.

Cases
  C1 legacy 动线矩形零宽（纵向被按横向重构）
  C2 公开 issue 自签伪真实运行 + 任意父链
  C3 完整快照摘要与底图文件摘要混用
  C4 实际模型请求缺入口/快照，仍带 12x8 示例
  C5 绕过场地校验（skip_site_integrity）
  C6 无渲染 ZIP 内嵌自身且清单校验失败

  python scripts/w3_trust_findings.py --code-root <dir> --label before|after --out <dir>
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import io
import json
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASEMAP = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class StubResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = canon(payload)
        self.headers = {"X-Request-Id": "local-stub-request"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _n=None):
        return self._raw


class CapturingOpener:
    """Protocol stub that keeps the EXACT request body bytes it was asked to send."""

    def __init__(self, candidates: dict) -> None:
        self.candidates = candidates
        self.requests: list[dict] = []
        self.responses: list[bytes] = []

    def open(self, request, timeout=None):
        body = bytes(request.data or b"")
        payload = json.loads(body.decode("utf-8"))
        content = canon({"candidates": [self.candidates["branch"], self.candidates["loop"]]})
        self.requests.append({"url": request.full_url, "body": payload,
                              "body_sha256": hashlib.sha256(body).hexdigest(),
                              "body_bytes": len(body)})
        response = canon({"choices": [{"message": {"content": content.decode("utf-8")}}],
                          "model": payload.get("model"), "usage": {}})
        self.responses.append(response)
        return StubResponse(json.loads(response))


def candidate(kind: str, entrance_y: float) -> dict:
    y_bottom = round(entrance_y - 0.6, 2)       # covers the entrance y
    y_top = round(entrance_y + 0.6, 2)
    base = {
        "strategy_id": f"{kind}-stub", "concept": "本地协议桩候选，非设计成果",
        "statement": "本地协议桩候选，非设计成果", "tradeoffs": ["仅验证工程链"],
        "entrance_side": "left", "circulation_kind": kind,
        "walls": [], "furniture": [], "paths": [], "connections": [],
        "materials": [{"material_id": "mat-warm", "name": "暖木意向", "intent": "未选产品"}],
        "cost_unknown": ["材料单价与价源"], "relationships": [],
    }
    base["paths"] = [
        {"segment_id": "path-entry", "x": 0, "y": y_bottom, "width": 24.0, "length": 1.2},
        {"segment_id": "path-west", "x": 3.0, "y": y_top, "width": 1.2, "length": 4.1},
        {"segment_id": "path-north", "x": 3.0, "y": round(y_top + 4.1, 2), "width": 17.0, "length": 1.2},
    ]
    base["connections"] = [["path-entry", "path-west"], ["path-west", "path-north"]]
    if kind == "loop":
        base["paths"].append({"segment_id": "path-east", "x": 19.0, "y": y_top,
                              "width": 1.2, "length": 4.1})
        base["connections"] += [["path-entry", "path-east"], ["path-east", "path-north"]]
    base["zones"] = [
        {"object_id": "zone:foyer", "name": "前厅", "x": 4.6, "y": y_top,
         "width": 5.0, "length": 3.5, "zone_role": "foyer", "sequence_role": "opening",
         "intent": "品牌第一眼", "min_area_m2": "4"},
        {"object_id": "zone:display", "name": "主展", "x": 10.0, "y": y_top,
         "width": 5.0, "length": 3.5, "zone_role": "primary_display",
         "sequence_role": "climax", "intent": "主展停留", "min_area_m2": "4"},
        {"object_id": "zone:talk", "name": "洽谈", "x": 15.4, "y": y_top,
         "width": 3.4, "length": 3.4, "zone_role": "deep_talk",
         "sequence_role": "closing", "intent": "半私密洽谈", "min_area_m2": "4"},
    ]
    base["walls"] = [{"object_id": "wall:feature", "name": "形象墙", "x": 14.9,
                      "y": round(y_top + 0.4, 2), "width": 0.14, "length": 2.0,
                      "wall_type": "feature"}]
    base["furniture"] = [{"object_id": "f:desk", "name": "前台", "x": 5.2,
                          "y": round(y_top + 0.6, 2), "width": 1.2, "length": 0.6,
                          "furniture_type": "reception_desk", "parent_object_id": "zone:foyer"}]
    base["focal_point"] = {"object_id": "focal:hero", "name": "中岛", "x": 11.5,
                           "y": round(y_top + 0.8, 2), "width": 1.4, "length": 0.9,
                           "furniture_type": "island", "statement": "视觉焦点"}
    return base


def legacy_snapshot(facts: dict, entrance_y: float) -> dict:
    """The 2253899 snapshot shape (for comparability of before/after audits)."""
    payload = {
        "schema_version": "rkd-site-snapshot.v1",
        "contract_version": "rkd-site-basemap.v2",
        "boundary_source": "rkd-site-basemap.v2",
        "width_m": 26.17, "length_m": 17.92,
        "boundary_mm": facts["boundary_mm"],
        "facts": {"keepouts": facts["keepouts"], "entrance_fact": facts["entrance_fact"],
                  "boundary_mm": facts["boundary_mm"], "files": facts["files"],
                  "json_sha256": facts["json_sha256"], "svg_sha256": facts["svg_sha256"]},
        "assumption": {"entrance": {"kind": "concept_replaceable",
                                    "value_m": [0, entrance_y],
                                    "reason": "底图仅推断西门厅；概念暂用点位，现场复核后替换",
                                    "site_verified": False}},
        "unverified_facts": facts["unverified_facts"], "site_verified": False,
    }
    payload["sha256"] = sha(payload)
    return payload


def legacy_provider_site(snap: dict) -> dict:
    obstacles = []
    for k in snap["facts"]["keepouts"]:
        x, y, w, h = k["rect_m"]
        obstacles.append({"object_id": k["object_id"], "name": k["name"],
                          "shape": {"type": "rect", "x": str(x), "y": str(y),
                                    "width": str(w), "length": str(h)},
                          "properties": {"source": snap["contract_version"], "site_verified": False}})
    ex, ey = snap["assumption"]["entrance"]["value_m"]
    return {"width": snap["width_m"], "length": snap["length_m"], "unit": "m",
            "boundary_source": "manual_boundary_not_site_verified",
            "site_snapshot_sha256": snap["sha256"], "obstacles": obstacles,
            "entrance": {"side": "left", "point": [str(ex), str(ey)], "width": "1.2",
                         "source": "concept_assumption", "site_verified": False}}


def legacy_adapter_site(snap: dict) -> dict:
    return {
        "contract_version": snap["contract_version"],
        "boundary_source": snap["boundary_source"],
        "width_m": snap["width_m"], "length_m": snap["length_m"],
        "snapshot_sha256": snap["sha256"],
        "keepouts": [{"object_id": k["object_id"], "name": k["name"], "rect_m": k["rect_m"],
                      "status": k["status"]} for k in snap["facts"]["keepouts"]],
        "entrance": {"side": snap["facts"]["entrance_fact"]["side"],
                     "point_m": snap["assumption"]["entrance"]["value_m"],
                     "width_m": None, "status": snap["facts"]["entrance_fact"]["status"],
                     "assumption": snap["assumption"]["entrance"]},
        "unverified_facts": snap["unverified_facts"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--render-png", default="")
    args = ap.parse_args()
    code_root = Path(args.code_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for path in (code_root / "mvp", code_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    sys.path.insert(0, str(ROOT / "scripts"))

    from rkd_mvp import realmodel_spatial_adapter as A
    from rkd_mvp.ai_design_option_provider import (DesignOptionConfig, DesignOptionProviderFailure,
                                                   RealModelDesignOptionProvider)
    from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
    from rkd_mvp.ai_spatial_outputs import (build_package, finalize_package,
                                            check_zip_against_manifest)
    from rkd_mvp.sqlite_store import SQLiteStore

    try:
        from rkd_mvp import site_snapshot as SS
    except ImportError:
        SS = None
    cases: dict[str, dict] = {}
    stamp = now()
    facts = A._load_basemap_facts(BASEMAP)

    # ---- one real pipeline: snapshot -> stub request -> provider -> SQLite ----
    if SS is not None:
        snap = SS.build_snapshot(facts=facts, entrance_point_m=[0, 10.3],
                                 entrance_reason="底图仅推断西门厅；概念暂用点位，现场复核后替换")
        psite, asite = SS.provider_site(snap), SS.adapter_site(snap)
        snapshot_sha = snap["sha256"]
        basemap_sha = snap["basemap_files_sha256"]
    else:
        snap = legacy_snapshot(facts, 10.3)
        psite, asite = legacy_provider_site(snap), legacy_adapter_site(snap)
        snapshot_sha = snap["sha256"]
        basemap_sha = None

    opener = CapturingOpener({"branch": candidate("branch", 10.3),
                              "loop": candidate("loop", 10.3)})
    exchanges: list[dict] = []

    def on_exchange(**kwargs):
        exchanges.append(kwargs)

    run_slug = args.label + "-" + stamp.replace(":", "").replace("+", "_").replace("-", "")[:15]
    ledger_base = out / "runservice" / run_slug
    service = None
    if hasattr(A, "verify_geometry_projection_consistency"):
        from rkd_mvp.controlled_run_ledger import ControlledRunService
        service = ControlledRunService(ledger_base)
    else:
        from rkd_mvp.controlled_run_ledger import ControlledRunLedger
        ledger = ControlledRunLedger()

    config = DesignOptionConfig(kind="openai_compatible", name="本地协议桩（模拟）",
                                adapter_version="rkd-real-design-provider.stub",
                                prompt_version="design-stub.zh-CN.v1",
                                schema_version="rkd-ai-design-option.v1", max_candidates=2,
                                real_model=True, configuration_errors=[],
                                base_url="http://127.0.0.1:9/local-stub", model_id="stub-model",
                                api_key_present=True, max_attempts=2, timeout_seconds=5,
                                external_context_allowed=False)
    provider_kwargs = {"run_log_dir": str(out / "runs")}
    if service is not None:
        provider_kwargs["on_exchange"] = on_exchange
    provider = RealModelDesignOptionProvider(config, api_key="stub-not-a-real-key",
                                             opener=opener, **provider_kwargs)
    brief = {"requirements": [], "design_intent": [], "conflicts": [],
             "cost": {"known_items": [], "unknown_items": []}}
    models, provider_error = [], ""
    try:
        models = provider.generate(set_id="w3-stub-set", brief=brief, site=psite,
                                   input_hash=snapshot_sha, generated_at=stamp)
    except DesignOptionProviderFailure as error:
        provider_error = f"{error.code}: {error.message}"

    db = out / "runtime" / "app.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    store = SQLiteStore(str(db))
    conn = store._connection()
    conn.execute("INSERT OR IGNORE INTO projects(organization_id, project_id, name, status, version) "
                 "VALUES (?,?,?,?,?)", ("org-local", "ningbo-xiecheng", "隔离桩库", "active", 1))
    conn.commit()
    repo = SQLiteAIDesignOptionRepository(str(db))
    persisted: list[dict] = []
    run_refs: list[str] = []
    with repo.transaction("org-local", "ningbo-xiecheng", write=True) as tx:
        tx.insert_set({"set_id": "w3-stub-set", "brief_id": "w3-stub-brief",
                       "input_hash": snapshot_sha, "status": "succeeded", "phase": "completed",
                       "attempt_count": 1, "config": config.public(), "context": {},
                       "error_code": None, "error_message": None,
                       "idempotency_key": "w3-stub-set-v1", "actor_id": "stub",
                       "created_at": stamp, "updated_at": stamp})
        for i, model in enumerate(models):
            oid = f"ai-option-revision-stub-{i}"
            tx.insert_revision({"option_revision_id": oid, "set_id": "w3-stub-set",
                                "option_id": f"w3-stub-set:stub-{i}", "revision_no": 1,
                                "parent_revision_id": None,
                                "strategy_id": model["strategy"]["strategy_id"],
                                "strategy": model["strategy"], "model": model,
                                "validation": model["validation"], "materials": model["materials"],
                                "cost": model["cost"], "feedback": model["feedback"],
                                "diff": model["diff"], "conflicts": model["conflicts"],
                                "structure_signature": model["structure_signature"],
                                "lifecycle_status": "candidate", "source_kind": model["source_kind"],
                                "change_reason": "本地协议桩候选", "actor_id": "stub",
                                "created_at": stamp})
            persisted.append(tx.revision(oid)["model"])

    if service is not None:
        observations = []
        for exchange in exchanges:
            observations.append(service.observe_exchange(project_id="ningbo-xiecheng", **exchange))
        for i, model in enumerate(persisted):
            cand, _ = A.candidate_from_persisted(model)
            service.register_revision(project_id="ningbo-xiecheng",
                                      revision_id=f"ai-option-revision-stub-{i}",
                                      candidate_sha256=sha(cand))
            rec = service.issue(observation=observations[min(i, len(observations) - 1)],
                                project_id="ningbo-xiecheng", candidate_sha256=sha(cand),
                                input_hash=snapshot_sha, output_sha256=sha(model),
                                model=config.model_id, prompt_version=config.prompt_version,
                                site_snapshot_sha256=snapshot_sha,
                                basemap_files_sha256=basemap_sha,
                                details={"adapter": "stub"})
            run_refs.append(rec["run_id"])
        verifier = service.verifier()
    else:
        for i, model in enumerate(persisted):
            cand, _ = A.candidate_from_persisted(model)
            rec = ledger.issue(kind="local_protocol_stub_run", simulated=True,
                               project_id="ningbo-xiecheng", candidate_sha256=sha(cand),
                               input_hash=snapshot_sha, output_sha256=sha(model),
                               model=config.model_id, prompt_version=config.prompt_version,
                               request_id=opener.requests[min(i, len(opener.requests) - 1)]["body_sha256"],
                               details={"site_snapshot_sha256": snapshot_sha})
            run_refs.append(rec["run_id"])
        verifier = None

    def provenance(index: int, cand: dict, *, kind="fixture", refs=None, parent=None,
                   parent_sha=None) -> dict:
        return {"artifact_id": f"stub-{index}", "sha256": sha(cand), "set_id": "w3-stub-set",
                "option_id": f"w3-stub-set:stub-{index}", "revision_no": 1,
                "parent_revision_id": parent, "actor_id": "offline-verifier",
                "model_site_boundary_m": [26.17, 17.92], "project_id": "ningbo-xiecheng",
                "provider_kind": "local_protocol_stub", "prompt_version": config.prompt_version,
                "model_id": config.model_id, "site_snapshot_sha256": snapshot_sha,
                "parent_evidence": {"candidate_sha256": parent_sha} if parent else {},
                "design_origin": {"kind": kind, "declared_by": "local_protocol_stub",
                                  "declaration": "本地协议桩模拟，不是真实模型调用",
                                  "run_refs": refs if refs is not None else []}}

    adapt_kwargs = {"run_verifier": verifier} if service is not None else {"run_ledger": ledger}
    adapted: list[dict] = []
    adapt_errors: list[str] = []
    for i, model in enumerate(persisted):
        cand, _ = A.candidate_from_persisted(model)
        try:
            doc, _note = A.adapt_persisted_candidate(
                model, site=asite, basemap_dir=BASEMAP,
                provenance=provenance(i, cand, refs=run_refs[i:i + 1]), created_at=stamp,
                **adapt_kwargs)
            adapted.append(doc)
        except Exception as error:  # noqa: BLE001
            adapt_errors.append(f"{type(error).__name__}: {getattr(error, 'code', '')} {error}")
    sample = adapted[0] if adapted else {}

    # ---------------- C1: legacy circulation rectangles ----------------------
    try:
        spatial_paths = {c["object_id"]: c for c in sample.get("spatial", {}).get("circulation", [])}
        legacy_segments = {s["segment_id"]: s for s in sample.get("circulation", {}).get("segments", [])}
        per_segment = []
        zeros = []
        mismatches = []
        for sid, path in spatial_paths.items():
            seg = legacy_segments.get(sid) or {}
            shape = seg.get("shape") or {}
            width, length = float(shape.get("width") or 0), float(shape.get("length") or 0)
            declared = path.get("declared_rect_mm")
            source = (seg.get("properties") or {}).get("source_rect_mm")
            zero = width <= 0 or length <= 0
            mismatch = bool(declared) and (
                [round(width * 1000), round(length * 1000)] != [declared[2], declared[3]]
                or (source is not None and list(source) != list(declared)))
            if zero:
                zeros.append(sid)
            if mismatch:
                mismatches.append(sid)
            per_segment.append({"segment_id": sid, "axis": path.get("axis"),
                                "spatial_width_mm": path.get("width_mm"),
                                "spatial_length_mm": (max(p[1] for p in path["path_mm"]) -
                                                      min(p[1] for p in path["path_mm"])),
                                "declared_rect_mm": declared,
                                "legacy_width_m": width, "legacy_length_m": length,
                                "source_rect_mm": source})
        vertical = [p for p in per_segment if p["axis"] == "vertical"]
        horizontal = [p for p in per_segment if p["axis"] == "horizontal"]
        ok = bool(per_segment) and not zeros and not mismatches and bool(vertical) and bool(horizontal)
        cases["C1_legacy_zero_width"] = {
            "ok": ok, "zero_dimension_segments": zeros, "mismatched_segments": mismatches,
            "vertical_checked": len(vertical), "horizontal_checked": len(horizontal),
            "segments": per_segment,
        }
    except Exception as error:  # noqa: BLE001
        cases["C1_legacy_zero_width"] = {"ok": False, "error": str(error),
                                         "adapt_errors": adapt_errors}

    # ---------------- C2: self-issued real run / arbitrary parent ------------
    cand0, _ = A.candidate_from_persisted(persisted[0]) if persisted else ({}, {})
    if service is None:
        try:
            fake = ledger.issue(kind="real_model_run", simulated=False,
                                project_id="ningbo-xiecheng", candidate_sha256=sha(cand0),
                                input_hash=sha({"anything": True}), output_sha256=sha({"fake": True}),
                                model="invented-model", prompt_version="invented-prompt",
                                request_id="invented", parent_revision_id="invented-parent-uid",
                                parent_candidate_sha256=sha({"parent": "invented"}),
                                parent_project_id="ningbo-xiecheng")
            forged_prov = provenance(0, cand0, kind="real_model", refs=[fake["run_id"]],
                                     parent="invented-parent-uid", parent_sha=sha({"parent": "invented"}))
            doc = A.adapt_candidate(cand0, site=asite, basemap_dir=BASEMAP,
                                    provenance=forged_prov, created_at=stamp, run_ledger=ledger)
            cases["C2_self_issued_real_run"] = {
                "ok": False, "accepted": True,
                "issued_kind": fake["kind"], "issued_simulated": fake["simulated"],
                "generation_real_model": doc["generation"]["real_model"],
                "parent_link_status": doc["spatial"]["source"]["parent_link_status"],
                "run_signature_present": bool(fake.get("issuer_signature")),
                "note": "公开 issue 接受调用者自报 real_model_run 与任意父链，并被适配器采信",
            }
        except Exception as error:  # noqa: BLE001
            cases["C2_self_issued_real_run"] = {"ok": True, "accepted": False,
                                                "error": f"{type(error).__name__}: {error}"}
    else:
        from rkd_mvp.controlled_run_ledger import ExchangeObservation
        attempts: dict[str, dict] = {}
        # (a) forged observation object
        try:
            forged_obs = ExchangeObservation(observation_id="obs-forged", project_id="ningbo-xiecheng",
                                             transport="live_http", endpoint="https://api.example.com",
                                             request_sha256=sha({"r": 1}), response_sha256=sha({"r": 2}),
                                             request_bytes=1, response_bytes=1, captured_at=stamp,
                                             simulated=False, _token=None)
            service.issue(observation=forged_obs, project_id="ningbo-xiecheng",
                          candidate_sha256=sha(cand0), input_hash=sha({"a": 1}),
                          output_sha256=sha({"o": 1}), model="invented", prompt_version="invented",
                          site_snapshot_sha256=snapshot_sha, basemap_files_sha256=basemap_sha)
            attempts["伪造观测"] = {"rejected": False}
        except Exception as error:  # noqa: BLE001
            attempts["伪造观测"] = {"rejected": True, "code": getattr(error, "code", type(error).__name__)}
        # (b) arbitrary parent that the repository never registered
        try:
            service.issue(observation=observations[0], project_id="ningbo-xiecheng",
                          candidate_sha256=sha(cand0), input_hash=snapshot_sha,
                          output_sha256=sha({"o": 2}), model=config.model_id,
                          prompt_version=config.prompt_version,
                          site_snapshot_sha256=snapshot_sha, basemap_files_sha256=basemap_sha,
                          parent_revision_id="invented-parent-uid")
            attempts["任意父链"] = {"rejected": False}
        except Exception as error:  # noqa: BLE001
            attempts["任意父链"] = {"rejected": True, "code": getattr(error, "code", type(error).__name__)}
        # (c) a second, independently constructed service must not verify these records
        try:
            from rkd_mvp.controlled_run_ledger import ControlledRunService
            rogue = ControlledRunService(out / "rogue-service" / run_slug)
            rogue.verifier().verify(run_refs[0], project_id="ningbo-xiecheng",
                                    candidate_sha256=sha(cand0))
            attempts["自建服务核验"] = {"rejected": False}
        except Exception as error:  # noqa: BLE001
            attempts["自建服务核验"] = {"rejected": True, "code": getattr(error, "code", type(error).__name__)}
        # (d) a stub-recorded observation can never be labelled real
        try:
            doc = A.adapt_candidate(cand0, site=asite, basemap_dir=BASEMAP,
                                    provenance=provenance(0, cand0, kind="real_model",
                                                          refs=[run_refs[0]], parent=None),
                                    created_at=stamp, run_verifier=verifier)
            attempts["桩记录冒充真实"] = {"rejected": False,
                                       "generation_real_model": doc["generation"]["real_model"]}
        except Exception as error:  # noqa: BLE001
            attempts["桩记录冒充真实"] = {"rejected": True,
                                       "code": getattr(error, "code", type(error).__name__)}
        cases["C2_self_issued_real_run"] = {
            "ok": all(v.get("rejected") for v in attempts.values()),
            "attempts": attempts,
            "issued_kind": service.export_public()[0]["kind"],
            "issued_simulated": service.export_public()[0]["simulated"],
            "issuer_id": service.issuer_id,
        }

    # ---------------- C3: snapshot digest vs basemap digest ------------------
    try:
        model_snap = (sample.get("site_snapshot") or {})
        site_source = ((sample.get("spatial") or {}).get("source") or {})
        model_snapshot_sha = model_snap.get("sha256")
        model_basemap_sha = model_snap.get("basemap_files_sha256")
        record_sha = None
        if service is not None:
            record_sha = service.export_public()[0].get("site_snapshot_sha256")
        same = (model_snapshot_sha == snapshot_sha and
                (record_sha in (None, snapshot_sha)) and
                (basemap_sha is None or model_basemap_sha == basemap_sha) and
                (basemap_sha is None or model_snapshot_sha != model_basemap_sha))
        # entrance change must change the snapshot digest
        moved = None
        if SS is not None:
            moved = SS.build_snapshot(facts=facts, entrance_point_m=[0, 9.4],
                                      entrance_reason="改入口以验证哈希随数据变化")["sha256"]
        cases["C3_snapshot_hash"] = {
            "ok": bool(same and (moved is None or moved != snapshot_sha)),
            "audit_snapshot_sha256": snapshot_sha,
            "model_site_snapshot_sha256": model_snapshot_sha,
            "model_basemap_files_sha256": model_basemap_sha,
            "confirmed_basemap_files_sha256": basemap_sha,
            "run_record_snapshot_sha256": record_sha,
            "spatial_source_snapshot_sha256": site_source.get("site_snapshot_sha256"),
            "entrance_moved_sha256": moved,
            "hashes_equal": model_snapshot_sha == snapshot_sha,
            "separately_named": (model_snapshot_sha != model_basemap_sha) if model_basemap_sha else False,
        }
    except Exception as error:  # noqa: BLE001
        cases["C3_snapshot_hash"] = {"ok": False, "error": str(error)}

    # ---------------- C4: actual model request body --------------------------
    try:
        envelope = (opener.requests[0]["body"] if opener.requests else {})
        # The design payload is the user message inside the chat envelope; that
        # string is exactly what the model would read.
        body = envelope
        for message in envelope.get("messages") or []:
            if message.get("role") == "user":
                try:
                    body = json.loads(message.get("content") or "{}")
                except ValueError:
                    body = {}
                break
        boundary = body.get("boundary") or {}
        entrance = boundary.get("entrance") or {}
        point = entrance.get("point")
        text = json.dumps(envelope, ensure_ascii=False)
        request_snapshot = body.get("site_snapshot") or {}
        keepouts = request_snapshot.get("keepouts") if isinstance(request_snapshot, dict) else None
        legal_12x8 = any(token in text for token in ("legal_path_example", "12x8m", "12x8",
                                                     "12 x 8", "12, 1.0"))
        ok = (point is not None and abs(float(point[0])) < 1e-9 and abs(float(point[1]) - 10.3) < 1e-6
              and boundary.get("site_snapshot_sha256") == snapshot_sha
              and bool(keepouts) and bool(request_snapshot.get("unverified_facts")))
        cases["C4_model_request"] = {
            "ok": bool(ok and not legal_12x8),
            "has_entrance_point": point is not None,
            "entrance_point": point,
            "boundary_snapshot_sha256": boundary.get("site_snapshot_sha256"),
            "has_site_snapshot_block": bool(request_snapshot),
            "snapshot_block_keepouts": len(keepouts or []),
            "snapshot_block_unverified": len(request_snapshot.get("unverified_facts") or []),
            "ships_12x8_example": legal_12x8,
            "request_sha256": opener.requests[0]["body_sha256"] if opener.requests else None,
            "request_bytes": opener.requests[0]["body_bytes"] if opener.requests else 0,
            "provider_error": provider_error,
        }
    except Exception as error:  # noqa: BLE001
        cases["C4_model_request"] = {"ok": False, "error": str(error)}

    # ---------------- C5: bypass the site gate -------------------------------
    try:
        tampered = copy.deepcopy(persisted[0])
        tampered["boundary"]["entrance"]["point"] = ["0", "2.24"]
        bypass_param = "skip_site_integrity" in inspect.signature(
            A.adapt_persisted_candidate).parameters
        result: dict = {"bypass_parameter_present": bypass_param}
        if bypass_param:
            doc, note = A.adapt_persisted_candidate(
                tampered, site=asite, basemap_dir=BASEMAP,
                provenance=provenance(0, A.candidate_from_persisted(tampered)[0], refs=[]),
                created_at=stamp, skip_site_integrity=True, **adapt_kwargs)
            result.update({"accepted": True,
                           "output_entrance": doc["boundary"]["entrance"]["point"],
                           "site_integrity_status": (note.get("site_snapshot_integrity") or {}).get("status"),
                           "ok": False})
        else:
            try:
                A.adapt_persisted_candidate(
                    tampered, site=asite, basemap_dir=BASEMAP,
                    provenance=provenance(0, A.candidate_from_persisted(tampered)[0], refs=[]),
                    created_at=stamp, **adapt_kwargs)
                result.update({"accepted": True, "ok": False})
            except Exception as error:  # noqa: BLE001
                result.update({"accepted": False, "code": getattr(error, "code", type(error).__name__),
                               "message": str(error)[:200], "ok": True})
        cases["C5_site_gate_bypass"] = result
    except Exception as error:  # noqa: BLE001
        cases["C5_site_gate_bypass"] = {"ok": False, "error": str(error)}

    # ---------------- C6: incomplete ZIP ------------------------------------
    try:
        if service is None:
            # 2253899 --no-render branch, executed verbatim with baseline modules
            pkg = build_package(sample, project_id="ningbo-xiecheng-stub",
                                option_revision_id="w3-stub-r1")
            files = dict(pkg["files"])
            final = finalize_package(files, pkg["manifest"])
            mbytes = final["files"]["manifest.json"][2]
            manifest = json.loads(mbytes.decode("utf-8"))
            manifest["package_completeness"] = {"status": "incomplete",
                                                "reason": "render 未成功；不得登记为完整成果",
                                                "render_status": "not_run"}
            mbytes = canon(manifest)
            final["files"]["manifest.json"] = ("manifest_json", "application/json", mbytes)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, (_, _, data) in final["files"].items():
                    archive.writestr(name, data)
            final["files"]["package.zip"] = ("package_zip", "application/zip", buffer.getvalue())
            zbytes = final["files"]["package.zip"][2]
            check = check_zip_against_manifest(zbytes, mbytes)
            with zipfile.ZipFile(io.BytesIO(zbytes)) as archive:
                names = sorted(archive.namelist())
            cases["C6_incomplete_zip"] = {
                "ok": False, "zip_check_ok": check["ok"], "problems": check["problems"],
                "names": names, "self_nested": "package.zip" in names,
                "declares_incomplete": True,
                "path": "2253899 verify_w3_control_trust.py --no-render 代码路径",
            }
        else:
            from rkd_mvp.ai_spatial_outputs import assert_complete_package, build_delivery_package
            incomplete = build_delivery_package(sample, project_id="ningbo-xiecheng-stub",
                                                option_revision_id="w3-stub-r1")
            with zipfile.ZipFile(io.BytesIO(incomplete["zip_bytes"])) as archive:
                names = sorted(archive.namelist())
            render_path = Path(args.render_png) if args.render_png else None
            complete = None
            if render_path and render_path.is_file():
                complete = build_delivery_package(sample, project_id="ningbo-xiecheng-stub",
                                                  option_revision_id="w3-stub-r1",
                                                  render_bytes=render_path.read_bytes(),
                                                  render_status="rendered")
            ok = (incomplete["zip_check"]["ok"] and not incomplete["complete"]
                  and incomplete["registration"]["ok"] is False
                  and "package.zip" not in names
                  and names.count("manifest.json") == 1
                  and (complete is None or (complete["zip_check"]["ok"]
                                            and complete["complete"]
                                            and complete["registration"]["ok"] is True)))
            cases["C6_incomplete_zip"] = {
                "ok": bool(ok),
                "incomplete_zip_check_ok": incomplete["zip_check"]["ok"],
                "incomplete_names": names,
                "incomplete_registration_ok": incomplete["registration"]["ok"],
                "incomplete_status": incomplete["completeness"]["status"],
                "self_nested": "package.zip" in names,
                "complete_checked": complete is not None,
                "complete_registration_ok": (complete["registration"]["ok"]
                                             if complete is not None else None),
                "path": "ai_spatial_outputs.build_delivery_package（唯一文件集）",
            }
    except Exception as error:  # noqa: BLE001
        cases["C6_incomplete_zip"] = {"ok": False, "error": str(error),
                                      "trace": traceback.format_exc()[-800:]}

    evidence = {
        "schema_version": "rkd-w3-trust-findings.v2", "label": args.label,
        "code_root": str(code_root), "executed_at": stamp,
        "pipeline": {"provider_error": provider_error, "models": len(models),
                     "persisted": len(persisted), "adapted": len(adapted),
                     "adapt_errors": adapt_errors,
                     "requests": [{"body_sha256": r["body_sha256"], "bytes": r["body_bytes"],
                                   "url": r["url"]} for r in opener.requests],
                     "run_refs": run_refs},
        "site_snapshot_sha256": snapshot_sha,
        "basemap_files_sha256": basemap_sha,
        "cases": cases,
        "summary": {key: value.get("ok") for key, value in cases.items()},
        "external_calls": 0, "cost_cny": 0, "keys_used": False,
    }
    (out / f"findings-{args.label}.json").write_bytes(canon(evidence))
    (out / "findings.json").write_bytes(canon(evidence))
    print(json.dumps(evidence["summary"], ensure_ascii=False))
    for key, value in cases.items():
        print(" ", key, json.dumps(value, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
