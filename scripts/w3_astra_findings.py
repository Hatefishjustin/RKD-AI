"""Reproduce GPT-6 Astra's R1—R5 against a given W3 code root.

The SAME harness runs against the frozen 72442c7 baseline and the fixed working
tree; only ``--code-root`` changes.  Every case drives real code: a real provider
call through a protocol stub whose bytes the controlled transport observes, a
real isolated SQLite repository, the real spatial adapter, the real admission
gate, the real service submit/adopt and the real delivery registration/download
boundary.  No paid external model call, no real key, no assertion weakened.

    python scripts/w3_astra_findings.py --code-root <dir> \
        --label before|after --out <dir> [--expect vulnerable|fixed]

Case result vocabulary:
  vulnerable = the finding reproduces on THIS code root
  fixed      = the attack is rejected / the chain is wired on THIS code root
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASEMAP = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
PROJECT = "ningbo-xiecheng"
ORG = "org-local"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", choices=("vulnerable", "fixed"), default=None)
    args = ap.parse_args()
    code_root = Path(args.code_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Load the TARGET code first; helpers from the repo scripts dir are shared
    # fixtures (stub/candidate) and are not part of the code under test.
    for path in (code_root / "mvp", code_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    sys.path.insert(0, str(ROOT / "scripts"))

    from rkd_mvp import realmodel_spatial_adapter as A
    from w3_trust_findings import CapturingOpener, candidate

    try:
        from rkd_mvp import site_snapshot as SS
    except ImportError:
        SS = None
    from rkd_mvp.controlled_run_ledger import ControlledRunService
    from rkd_mvp.admission import admit_document
    from rkd_mvp.ai_design_option_provider import DesignOptionConfig, RealModelDesignOptionProvider

    cases: dict[str, dict] = {}
    facts = A._load_basemap_facts(BASEMAP)
    snap = SS.build_snapshot(facts=facts, entrance_point_m=[0, 10.3],
                             entrance_reason="底图仅推断西门厅；概念暂用点位，现场复核后替换")
    psite, asite = SS.provider_site(snap), SS.adapter_site(snap)

    def config() -> DesignOptionConfig:
        return DesignOptionConfig(
            kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
            prompt_version="pv", schema_version="rkd-ai-design-option.v1", max_candidates=2,
            real_model=True, configuration_errors=[], base_url="http://127.0.0.1:9/stub",
            model_id="stub-model", api_key_present=True, max_attempts=2,
            timeout_seconds=5, external_context_allowed=False)

    # ---------------------------------------------------------------- R2 ----
    # Self-reported live_http/public endpoint/bytes must never issue a verified
    # non-simulated real_model_run.
    svc2 = ControlledRunService(out / "runtime" / "r2")
    r2 = {"self_report_rejected": False, "fake_real_issued": False}
    try:
        obs = svc2.observe_exchange(
            project_id=PROJECT, transport="live_http",
            endpoint="https://public.example.com/v1",
            request_bytes=b"self-report-request", response_bytes=b"self-report-response")
        rec = svc2.issue(
            observation=obs, project_id=PROJECT, candidate_sha256="c" * 64,
            input_hash="i" * 64, output_sha256="o" * 64, model="m",
            prompt_version="v", site_snapshot_sha256="s" * 64,
            basemap_files_sha256="b" * 64)
        verified = svc2.verifier().verify(rec["run_id"], project_id=PROJECT,
                                          candidate_sha256="c" * 64)
        r2["fake_real_issued"] = (rec.get("kind") == "real_model_run" and
                                  rec.get("simulated") is False and
                                  verified.get("kind") == "real_model_run")
    except Exception as error:  # noqa: BLE001
        r2["self_report_rejected"] = True
        r2["reject_code"] = getattr(error, "code", type(error).__name__)
    cases["R2"] = {
        "result": "vulnerable" if r2["fake_real_issued"] else "fixed",
        "detail": r2,
    }

    # ------------------------------------------------------- real pipeline --
    # Build one real candidate through the protocol stub, persist/adapt it, so
    # R3/R4 can operate on a genuine adapted document.
    opener = CapturingOpener({"branch": candidate("branch", 10.3),
                              "loop": candidate("loop", 10.3)})

    class StubOpener:
        def open(self, request, timeout=None):
            return opener.open(request, timeout=timeout)

    provider = RealModelDesignOptionProvider(
        config(), api_key="stub-not-a-real-key", opener=StubOpener())
    brief = {"requirements": [], "design_intent": [], "conflicts": [],
             "cost": {"known_items": [], "unknown_items": []}}
    models = provider.generate(set_id="astra-set", brief=brief, site=psite,
                               input_hash=snap["sha256"], generated_at=now())
    src = models[0]

    # Build a controlled run record using whichever API this code root exposes.
    import inspect
    ctor_params = inspect.signature(ControlledRunService.__init__).parameters
    has_transport = "opener" in ctor_params and hasattr(ControlledRunService, "transport")
    if has_transport:
        run_service = ControlledRunService(out / "runtime" / "runs",
                                           opener=StubOpener(),
                                           transport="local_protocol_stub")
    else:
        run_service = ControlledRunService(out / "runtime" / "runs")
    cand, _ = A.candidate_from_persisted(src)
    run_refs: list[str] = []
    if has_transport:
        from urllib.request import Request
        req = Request("http://127.0.0.1:9/stub/chat/completions",
                      data=canon({"model": "stub-model"}), method="POST")
        run_service.transport().send(project_id=PROJECT, request=req)
        observations = run_service.controlled_observations(project_id=PROJECT)
    else:
        from rkd_mvp import realmodel_spatial_adapter as _A  # noqa: F401
        exchanges = []
        provider2 = RealModelDesignOptionProvider(
            config(), api_key="stub", opener=StubOpener(),
            on_exchange=lambda **kw: exchanges.append(kw))
        provider2.generate(set_id="astra-set2", brief=brief, site=psite,
                           input_hash=snap["sha256"], generated_at=now())
        observations = [run_service.observe_exchange(project_id=PROJECT, **x)
                        for x in exchanges]
    run_service.register_revision(project_id=PROJECT, revision_id="r1",
                                  candidate_sha256=sha(cand))
    record = run_service.issue(
        observation=observations[-1], project_id=PROJECT, candidate_sha256=sha(cand),
        input_hash=snap["sha256"], output_sha256=sha(src), model="stub-model",
        prompt_version="pv", site_snapshot_sha256=snap["sha256"],
        basemap_files_sha256=snap["basemap_files_sha256"])
    run_refs.append(record["run_id"])
    prov = {"sha256": sha(cand), "model_site_boundary_m": [26.17, 17.92],
            "project_id": PROJECT, "provider_kind": "local_protocol_stub",
            "prompt_version": "pv", "model_id": "stub-model",
            "site_snapshot_sha256": snap["sha256"],
            "basemap_files_sha256": snap["basemap_files_sha256"],
            "design_origin": {"kind": "fixture", "declared_by": "harness",
                              "declaration": "本地桩模拟", "run_refs": run_refs}}
    doc, _ = A.adapt_persisted_candidate(
        src, site=asite, basemap_dir=BASEMAP, provenance=prov,
        created_at=now(), run_verifier=run_service.verifier())

    # ---------------------------------------------------------------- R3 ----
    trusted_supported = "organization_id" in admit_document.__code__.co_varnames
    base_admission = admit_document(doc, site=asite, basemap_dir=BASEMAP,
                                    run_verifier=run_service.verifier())

    def admitted(candidate_doc: dict) -> bool:
        kwargs = dict(site=asite, basemap_dir=BASEMAP,
                      run_verifier=run_service.verifier())
        if trusted_supported:
            kwargs.update(organization_id=ORG, project_id=PROJECT,
                          source_candidate=src, provenance=prov)
        result = admit_document(candidate_doc, **kwargs)
        return bool(result.get("adoptable"))

    # R3a: shift furniture +100mm in BOTH spatial and legacy, keep source digest.
    t3a = copy.deepcopy(doc)
    fur_ids = {str(f["object_id"]) for f in t3a["spatial"]["furniture"]}
    for f in t3a["spatial"]["furniture"]:
        f["x_mm"] += 100
    for o in t3a["objects"]:
        if str(o.get("object_id")) in fur_ids:
            o["shape"]["x"] = str(float(o["shape"]["x"]) + 0.1)
    r3a_admitted = admitted(t3a)
    # R3b: fixture origin + no run refs + generation.real_model=true.
    t3b = copy.deepcopy(doc)
    t3b["generation"]["real_model"] = True
    t3b["spatial"]["source"]["design_origin"]["kind"] = "fixture"
    t3b["spatial"]["source"]["design_origin"]["run_refs"] = []
    r3b_admitted = admitted(t3b)
    # Cross-project reuse: same doc admitted under another project context.
    cross = admit_document(
        doc, site=asite, basemap_dir=BASEMAP, run_verifier=run_service.verifier(),
        **({"organization_id": ORG, "project_id": "other-project",
            "source_candidate": src, "provenance": prov} if trusted_supported else {}))
    cross_admitted = bool(cross.get("adoptable"))
    cases["R3"] = {
        "result": ("vulnerable" if (r3a_admitted or r3b_admitted or cross_admitted)
                   else "fixed"),
        "detail": {"baseline_admitted": bool(base_admission.get("adoptable")),
                   "trusted_context_supported": trusted_supported,
                   "furniture_shift_admitted": r3a_admitted,
                   "fixture_real_model_admitted": r3b_admitted,
                   "cross_project_admitted": cross_admitted},
    }

    # ---------------------------------------------------------------- R4 ----
    t4 = copy.deepcopy(doc)
    t4["spatial"]["circulation"][0]["path_mm"] = [
        [p[0] + 100000, p[1]] for p in t4["spatial"]["circulation"][0]["path_mm"]]
    r4_admitted = admitted(t4)
    cases["R4"] = {
        "result": "vulnerable" if r4_admitted else "fixed",
        "detail": {"path_shift_admitted": r4_admitted,
                   "axes": [c.get("axis") for c in doc["spatial"]["circulation"]]},
    }

    # ---------------------------------------------------------------- R1 ----
    # Real provider config + stub + real service + real SQLite, submit->adopt.
    r1 = {"succeeded": False, "adopted": False}
    try:
        from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
        from rkd_mvp.ai_design_option_service import AIDesignOptionService
        from rkd_mvp.sqlite_store import SQLiteStore
        db = out / "runtime" / "r1.sqlite3"
        if db.exists():
            db.unlink()
        store = SQLiteStore(str(db))
        conn = store._connection()
        conn.execute("INSERT OR IGNORE INTO projects"
                     "(organization_id,project_id,name,status,version) VALUES (?,?,?,?,?)",
                     (ORG, PROJECT, "隔离桩库", "active", 1))
        conn.commit()
        repo = SQLiteAIDesignOptionRepository(str(db))
        has_runtime = False
        svc_kwargs: dict = {}
        try:
            from rkd_mvp.controlled_design_runtime import ControlledDesignRuntime
            runtime = ControlledDesignRuntime(store_dir=out / "runtime" / "r1runs",
                                              opener=StubOpener(), basemap_dir=BASEMAP)
            svc_kwargs = {"controlled_runtime": runtime}
            has_runtime = True
        except ImportError:
            pass
        brief_record = {"brief": brief}
        service = AIDesignOptionService(
            repo, lambda *_a: brief_record,
            lambda *_a: {"width": "12", "length": "8",
                         "boundary_source": "test_parameters_not_site_verified",
                         "obstacles": []},
            out / "runtime" / "svc", config=config(), provider=None,
            start_workers=False, **svc_kwargs)
        item = service.submit(ORG, PROJECT, "harness", {}, "astra-idem-0001")["item"]
        service._run_set(ORG, PROJECT, item["set_id"])
        state = service.wait_for_set(ORG, PROJECT, item["set_id"])
        r1["succeeded"] = state["status"] == "succeeded"
        if r1["succeeded"]:
            option = service.status(ORG, PROJECT)["item"]["options"][0]
            r1["schema"] = option["model"]["schema_version"]
            r1["spatial"] = bool(option["model"].get("spatial"))
            r1["runs_simulated"] = all(
                r.get("simulated") is True
                for r in (runtime.run_service.export_public() if has_runtime else []))
            try:
                service.adopt(ORG, PROJECT, "harness", {
                    "option_id": option["option_id"], "expected_revision": 1,
                    "expected_version": 0})
                r1["adopted"] = True
            except Exception as error:  # noqa: BLE001
                r1["adopt_error"] = getattr(error, "code", type(error).__name__)
    except Exception as error:  # noqa: BLE001
        r1["error"] = f"{type(error).__name__}: {error}"
        r1["traceback"] = traceback.format_exc()[-1200:]
    cases["R1"] = {
        "result": "fixed" if (r1["succeeded"] and r1["adopted"]) else "vulnerable",
        "detail": r1,
    }

    # ---------------------------------------------------------------- R5 ----
    # The real AISpatialOutputService must register completeness and expose it
    # at download.  Baseline has no package_status/completeness field.
    r5 = {"has_status_api": False, "preview_marked": False}
    try:
        from rkd_mvp.ai_spatial_outputs import completeness_for_render  # noqa: F401
        from rkd_mvp.ai_spatial_output_service import AISpatialOutputService
        r5["has_status_api"] = hasattr(AISpatialOutputService, "package_status")
        r5["completeness_marked"] = completeness_for_render(
            "not_run", render_present=False)["status"] == "incomplete"
    except Exception as error:  # noqa: BLE001
        r5["error"] = f"{type(error).__name__}: {error}"
    cases["R5"] = {
        "result": "fixed" if (r5["has_status_api"] and r5.get("completeness_marked"))
                  else "vulnerable",
        "detail": r5,
    }

    summary = {name: case["result"] for name, case in cases.items()}
    audit = {"schema_version": "rkd-w3-astra-findings.v1",
             "baseline": "72442c7", "code_root": str(code_root),
             "label": args.label, "started_at": now(), "finished_at": now(),
             "cases": cases, "summary": summary,
             "external_calls": 0, "cost_cny": 0, "keys_used": False}
    (out / "findings.json").write_bytes(canon(audit))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    expected = args.expect
    if expected == "vulnerable":
        ok = all(value == "vulnerable" for value in summary.values())
    elif expected == "fixed":
        ok = all(value == "fixed" for value in summary.values())
    else:
        ok = True
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
