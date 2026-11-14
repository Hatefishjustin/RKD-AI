"""W1 版本谱系收口：源谱系身份、父 UID 映射、导入顺序不伪造父链、写内并发重检。

用法：
  python scripts/verify_w1_lineage.py --out <dir> --runtime <dir>

隔离主系统库 + 隔离 Studio 库；源是明确标记的本地夹具（真实 parent_revision_uid 链）。
0 外部调用、0 密钥、0 费用。
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arg(flag: str, default: Path) -> Path:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if a.startswith(flag + "="):
            return Path(a.split("=", 1)[1]).resolve()
    return default


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W1-版本谱系收口/after")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W1-版本谱系收口/runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
MAIN_DB = RUNTIME / "app.sqlite3"
STUDIO_DB = RUNTIME / "studio.db"
for f in (MAIN_DB, STUDIO_DB):
    if f.exists():
        f.unlink()

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, valid_proposal  # noqa: E402
from rkd_mvp.ai_design_option_provider import (  # noqa: E402
    DesignOptionConfig, build_design_option_provider)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_design_studio_adapter import StudioProposalSource  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import orchestrator, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
PID = NINGBO_PROJECT_ID
SPID = "ningbo-xiecheng"
CHECKS: list[dict] = []


def check(cid: str, name: str, ok: bool, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def plan_of(letter: str, mutate=None) -> dict:
    raw = valid_proposal(letter)
    if mutate:
        mutate(raw)
    rep = validation.validate_proposal(
        raw, project={"id": SPID, "site": SITE}, option_id=letter,
        revision=1, parent_revision=None)
    assert rep["ok"], rep["repair_feedback"][:300]
    return rep["plan"]


def save(studio: Store, letter: str, plan: dict, *, uid: str,
         parent_uid: str | None, source_label: str | None = "labelled_local_fixture"):
    aid = studio.save_artifact(
        SPID, "spatial-plan", plan, "D2", option_id=letter, revision=1,
        status="valid_candidate", contract_status="valid_candidate",
        run_id=f"run_{uid}", candidate_group_id=f"group_{uid}",
        revision_uid=uid, parent_revision_uid=parent_uid,
        input_hash_value=hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
        check_report_id=f"check_{uid}",
        diagnostics=({"source": source_label} if source_label else None))
    return studio.artifact_by_id(aid)


def http(method: str, path: str, body: dict | None = None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"X-Organization-Id": ORG, "Content-Type": "application/json"}
    if payload is not None:
        headers["Content-Length"] = str(len(payload))
    conn = HTTPConnection("127.0.0.1", PORT, timeout=30)
    conn.request(method, path, payload, headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {"_raw": raw[:200].decode("utf-8", "replace")}
    return resp.status, data


def body(art: dict, **extra) -> dict:
    return {"studio_project_id": SPID, "studio_artifact_id": art["id"],
            "source_project_id": PID, "expected_unit": "mm", **extra}


def revisions() -> list[dict]:
    import sqlite3
    c = sqlite3.connect(MAIN_DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT option_id, revision_no, parent_revision_id, option_revision_id, "
                     "model_json FROM ai_design_option_revisions ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        model = json.loads(r["model_json"])
        src = (model.get("spatial") or {}).get("source") or {}
        out.append({"option_id": r["option_id"], "revision_no": r["revision_no"],
                    "parent_revision_id": r["parent_revision_id"],
                    "option_revision_id": r["option_revision_id"],
                    "source_uid": src.get("revision_uid"),
                    "source_parent_uid": src.get("parent_revision_uid"),
                    "root_uid": src.get("root_revision_uid"),
                    "parent_link_status": src.get("parent_link_status"),
                    "design_origin": src.get("design_origin"),
                    "origin_kind": src.get("origin_kind")})
    c.close()
    return out


def svg_count() -> int:
    d = RUNTIME / "projects" / "ai-design-options" / "studio-import"
    return len(list(d.rglob("*.svg"))) if d.exists() else 0


def main() -> int:
    global PORT
    studio = Store(STUDIO_DB)
    orchestrator.Studio(studio).seed_from_fixtures()
    source = StudioProposalSource(studio)

    base_a = plan_of("A")
    base_b = plan_of("B")
    plan_a2 = plan_of("A", lambda p: (
        p["zones"][0].update(polygon=[[0, 8600], [5400, 8600], [5400, 13500],
                                     [1800, 13500], [0, 11900]]),
        p["furniture"][2].update(rot=-30)))
    plan_a2a = plan_of("A", lambda p: p["furniture"][0].update(x=8600))
    plan_a2b = plan_of("A", lambda p: p["furniture"][1].update(rot=15))
    plan_a_prime = plan_of("A", lambda p: p["zones"][0].update(
        polygon=[[0, 9000], [4800, 9000], [4800, 13000], [0, 13000]]))
    plan_orphan = plan_of("A", lambda p: p["furniture"][1].update(y=4400))

    art_a = save(studio, "A", base_a, uid="uid-A-1", parent_uid=None)
    art_b = save(studio, "B", base_b, uid="uid-B-1", parent_uid=None)
    art_a2 = save(studio, "A", plan_a2, uid="uid-A-2", parent_uid="uid-A-1")
    art_a2a = save(studio, "A", plan_a2a, uid="uid-A-2a", parent_uid="uid-A-1")
    art_a2b = save(studio, "A", plan_a2b, uid="uid-A-2b", parent_uid="uid-A-1")
    art_aprime = save(studio, "A", plan_a_prime, uid="uid-A-prime-1", parent_uid=None)
    # parent EXISTS in Studio but is deliberately NOT imported into the main
    # system: that is the "source parent not imported" case (allow_orphan).
    art_orphan_parent = save(studio, "A", base_a, uid="uid-A-orphan-1", parent_uid=None)
    art_orphan = save(studio, "A", plan_orphan, uid="uid-A-orphan-2",
                      parent_uid="uid-A-orphan-1")
    # parent does NOT exist in Studio at all: broken source chain, must reject.
    art_broken = save(studio, "A", base_b, uid="uid-A-broken-2",
                      parent_uid="uid-A-missing-1")
    art_nodecl = save(studio, "A", base_a, uid="uid-A-nodecl-1", parent_uid=None,
                      source_label=None)

    main_store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    brief_config = AIProviderConfig(
        kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
        prompt_version="requirement-understanding.zh-CN.v1",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    option_config = DesignOptionConfig(
        kind="synthetic", name="本地合成设计通道（非真实 AI）",
        adapter_version="rkd-design-option-provider.v1",
        prompt_version="design-option-strategy.zh-CN.v1",
        schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=False, configuration_errors=[])
    requirement_ai = AIRequirementService(
        SQLiteAIRequirementRepository(MAIN_DB), requirements, config=brief_config,
        provider_factory=lambda config: build_provider(config))
    options_ai = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(MAIN_DB),
        lambda org, project: requirement_ai.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified",
                              "obstacles": []},
        RUNTIME, config=option_config,
        provider=build_design_option_provider(option_config),
        studio_source=source)
    service = ApiService(MVPApp(main_store), files, requirement_service=requirements,
                         ai_requirement_service=requirement_ai,
                         ai_design_option_service=options_ai, runtime_root=RUNTIME,
                         studio_source=source)
    files.seed_ningbo(service, FIXTURE_ROOT)

    server = create_server(service, port=0, static_dir=ROOT / "web" / "dist")
    PORT = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"/api/v1/projects/{PID}/ai/design-options"
    try:
        # ------------------------------------------------ L01 independent A roots
        code1, imp_a = http("POST", f"{base}/import-studio", body(art_a))
        code2, imp_ap = http("POST", f"{base}/import-studio", body(art_aprime))
        rows = revisions()
        a_rows = [r for r in rows if r["source_uid"] == "uid-A-1"]
        ap_rows = [r for r in rows if r["source_uid"] == "uid-A-prime-1"]
        check("L01", "两个独立的 A 候选是不同谱系，不因字母相同被串成版本",
              bool(code1 == 200 and code2 == 200
                   and a_rows and ap_rows
                   and a_rows[0]["option_id"] != ap_rows[0]["option_id"]
                   and a_rows[0]["revision_no"] == 1 and ap_rows[0]["revision_no"] == 1
                   and a_rows[0]["parent_revision_id"] is None
                   and ap_rows[0]["parent_revision_id"] is None),
              {"option_ids": [a_rows[0]["option_id"] if a_rows else None,
                              ap_rows[0]["option_id"] if ap_rows else None],
               "revisions": [[r["revision_no"], r["parent_revision_id"]] for r in rows]})

        # ------------------------------------------- L02 same root v1 -> v2
        code, imp_a2 = http("POST", f"{base}/import-studio", body(art_a2))
        rows = revisions()
        r1 = next(r for r in rows if r["source_uid"] == "uid-A-1")
        r2 = next(r for r in rows if r["source_uid"] == "uid-A-2")
        check("L02", "同根 v1→v2：父链来自源 parent UID 映射，不是导入顺序",
              bool(code == 200 and r2["option_id"] == r1["option_id"]
                   and r2["revision_no"] == 2
                   and r2["parent_revision_id"] == r1["option_revision_id"]
                   and r2["source_parent_uid"] == "uid-A-1"
                   and r2["root_uid"] == "uid-A-1"
                   and r2["parent_link_status"] == "resolved"),
              {"v1": {"revision_no": r1["revision_no"], "main_id": r1["option_revision_id"]},
               "v2": {"revision_no": r2["revision_no"],
                      "parent": r2["parent_revision_id"],
                      "source_parent_uid": r2["source_parent_uid"],
                      "root_uid": r2["root_uid"],
                      "link": r2["parent_link_status"]}})

        # ------------------------------------------------------- L03 forks
        codea, _ = http("POST", f"{base}/import-studio", body(art_a2a))
        codeb, _ = http("POST", f"{base}/import-studio", body(art_a2b))
        rows = revisions()
        fa = next(r for r in rows if r["source_uid"] == "uid-A-2a")
        fb = next(r for r in rows if r["source_uid"] == "uid-A-2b")
        check("L03", "同一父的两个分叉：都指向 v1，彼此不是父子关系",
              bool(codea == 200 and codeb == 200
                   and fa["parent_revision_id"] == r1["option_revision_id"]
                   and fb["parent_revision_id"] == r1["option_revision_id"]
                   and fa["option_revision_id"] not in
                   {fa["parent_revision_id"], fb["option_revision_id"]}
                   and fa["revision_no"] != fb["revision_no"]),
              {"fork_a": {"rev": fa["revision_no"], "parent": fa["parent_revision_id"]},
               "fork_b": {"rev": fb["revision_no"], "parent": fb["parent_revision_id"]},
               "shared_parent": r1["option_revision_id"]})

        # --------------------------------------------------- L04 out of order
        art_new = save(studio, "A", plan_a2, uid="uid-A-order-3",
                       parent_uid="uid-A-order-2")
        art_old = save(studio, "A", plan_a2a, uid="uid-A-order-2",
                       parent_uid="uid-A-order-1")
        art_root = save(studio, "A", base_a, uid="uid-A-order-1", parent_uid=None)
        code_new1, resp_new1 = http("POST", f"{base}/import-studio", body(art_new))
        code_root, _ = http("POST", f"{base}/import-studio", body(art_root))
        code_old, _ = http("POST", f"{base}/import-studio", body(art_old))
        code_new2, resp_new2 = http("POST", f"{base}/import-studio", body(art_new))
        rows = revisions()
        o_root = next(r for r in rows if r["source_uid"] == "uid-A-order-1")
        o_old = next(r for r in rows if r["source_uid"] == "uid-A-order-2")
        o_new = next(r for r in rows if r["source_uid"] == "uid-A-order-3")
        check("L04", "乱序导入：父未导入时明确拒绝；补齐父后父链正确，不把旧稿接在新稿后",
              bool(code_new1 == 409
                   and resp_new1.get("error_code") == "SOURCE_PARENT_NOT_IMPORTED"
                   and code_root == 200 and code_old == 200 and code_new2 == 200
                   and o_old["parent_revision_id"] == o_root["option_revision_id"]
                   and o_new["parent_revision_id"] == o_old["option_revision_id"]
                   and o_root["parent_revision_id"] is None),
              {"first_new_import": [code_new1, resp_new1.get("error_code")],
               "root": [o_root["revision_no"], o_root["parent_revision_id"]],
               "old": [o_old["revision_no"], o_old["parent_revision_id"]],
               "new": [o_new["revision_no"], o_new["parent_revision_id"]]})

        # ------------------------------------------------------- L05 orphan
        code, imp_orphan = http("POST", f"{base}/import-studio",
                                body(art_orphan, allow_orphan=True))
        rows = revisions()
        orphan = next(r for r in rows if r["source_uid"] == "uid-A-orphan-2")
        check("L05", "缺父且显式 allow_orphan：parent 为 null 且标记缺父，不伪造父关系",
              bool(code == 200 and orphan["parent_revision_id"] is None
                   and orphan["parent_link_status"] == "source_parent_not_imported"
                   and orphan["root_uid"] == "uid-A-orphan-1"),
              {"status": code, "revision_no": orphan["revision_no"],
               "parent": orphan["parent_revision_id"],
               "link": orphan["parent_link_status"], "root": orphan["root_uid"]})

        # ------------------------------------------- L06 source chain broken
        code, resp = http("POST", f"{base}/import-studio", body(art_broken))
        check("L06", "源父 UID 在 Studio 库中不存在：明确拒绝，不猜谱系",
              bool(code == 409 and resp.get("error_code") == "SOURCE_PARENT_MISSING"),
              {"status": code, "error_code": resp.get("error_code")})

        # ----------------------------- L07 same-source concurrent (HTTP barrier)
        art_c = save(studio, "C", base_b, uid="uid-C-1", parent_uid=None)
        before_rows, before_svg = len(revisions()), svg_count()
        results: list[tuple[int, dict]] = []
        barrier = threading.Barrier(2)

        def same_source_worker():
            barrier.wait()
            results.append(http("POST", f"{base}/import-studio", body(art_c)))

        threads = [threading.Thread(target=same_source_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        rows = revisions()
        c_rows = [r for r in rows if r["source_uid"] == "uid-C-1"]
        check("L07", "同源并发（屏障同时发起）：只产生一个版本，另一个复用；无半记录/遗留文件",
              bool(len(results) == 2
                   and all(code == 200 for code, _ in results)
                   and sum(1 for _, r in results if r.get("reused") is False) == 1
                   and len(c_rows) == 1
                   and len(rows) == before_rows + 1
                   and svg_count() == before_svg + 1),
              {"responses": [(c, r.get("reused")) for c, r in results],
               "versions": len(c_rows), "rows_delta": len(rows) - before_rows,
               "svg_delta": svg_count() - before_svg})

        # ------------------------ L08 same-lineage concurrent (two forks at once)
        art_d1 = save(studio, "D", base_a, uid="uid-D-1", parent_uid=None)
        art_d2 = save(studio, "D", plan_a2, uid="uid-D-2", parent_uid="uid-D-1")
        art_d3 = save(studio, "D", plan_a2b, uid="uid-D-3", parent_uid="uid-D-1")
        http("POST", f"{base}/import-studio", body(art_d1))
        rows = revisions()
        d1 = next(r for r in rows if r["source_uid"] == "uid-D-1")
        before_rows, before_svg = len(rows), svg_count()
        results2: list[tuple[int, dict]] = []
        barrier2 = threading.Barrier(2)

        def lineage_worker(art):
            barrier2.wait()
            results2.append(http("POST", f"{base}/import-studio", body(art)))

        threads = [threading.Thread(target=lineage_worker, args=(a,))
                   for a in (art_d2, art_d3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        rows = revisions()
        d2 = next(r for r in rows if r["source_uid"] == "uid-D-2")
        d3 = next(r for r in rows if r["source_uid"] == "uid-D-3")
        check("L08", "同谱系并发（两个分叉同时导入）：版本号不冲突，父都指向 v1，无 500/唯一约束异常",
              bool(len(results2) == 2
                   and all(code == 200 for code, _ in results2)
                   and len(rows) == before_rows + 2
                   and svg_count() == before_svg + 2
                   and d2["parent_revision_id"] == d1["option_revision_id"]
                   and d3["parent_revision_id"] == d1["option_revision_id"]
                   and d2["revision_no"] != d3["revision_no"]),
              {"responses": [c for c, _ in results2],
               "versions": [d2["revision_no"], d3["revision_no"]],
               "parents": [d2["parent_revision_id"], d3["parent_revision_id"]],
               "shared_parent": d1["option_revision_id"],
               "rows_delta": len(rows) - before_rows,
               "svg_delta": svg_count() - before_svg})

        # --------------------------- L09 design origin vs adaptation origin
        code, imp_nodecl = http("POST", f"{base}/import-studio", body(art_nodecl))
        rows = revisions()
        nodecl = next((r for r in rows if r["source_uid"] == "uid-A-nodecl-1"), None)
        fixture_row = next(r for r in rows if r["source_uid"] == "uid-A-1")
        check("L09", "设计来源与适配来源分开：传输路径=studio_import，上游来源按声明保留，未声明保持 unknown",
              bool(code == 200 and nodecl is not None
                   and fixture_row["origin_kind"] == "studio_import"
                   and fixture_row["design_origin"]["kind"] == "fixture"
                   and nodecl["design_origin"]["kind"] == "unknown"
                   and nodecl["design_origin"]["declared_by"] == "not_declared"),
              {"fixture_origin": fixture_row["design_origin"],
               "undeclared_origin": nodecl["design_origin"] if nodecl else None,
               "transport_origin": fixture_row["origin_kind"]})

        # ------------------- L10 precise spatial authority + bbox loss visible
        code, detail = http("GET", f"{base}/studio-imports/{r2['option_revision_id']}")
        spatial = (detail.get("spatial") or {})
        model = (detail.get("item") or {}).get("model") or {}
        zone = (spatial.get("zones") or [{}])[0]
        legacy = next((o for o in model.get("objects", [])
                       if o["object_id"] == "ZA1"), {})
        check("L10", "精确 spatial 是权威：多边形原样、bbox 只作 legacy 显示且有损失声明",
              bool(code == 200
                   and zone.get("polygon_mm") == plan_a2["zones"][0]["polygon"]
                   and legacy.get("properties", {}).get("geometry_mode") == "bbox_derived"
                   and any("bounding_box_only" in json.dumps(l)
                           for l in spatial.get("adaptation", {}).get("losses", []))),
              {"polygon_equal": zone.get("polygon_mm") == plan_a2["zones"][0]["polygon"],
               "legacy_geometry_mode": legacy.get("properties", {}).get("geometry_mode"),
               "losses": spatial.get("adaptation", {}).get("losses")})

        # ---------------------- L11 adopt a selected fork, old one still rejected
        rows = revisions()
        lineage_rows = [r for r in rows if r["option_id"] == r2["option_id"]]
        head = max(lineage_rows, key=lambda r: r["revision_no"])
        code, adopted = http(
            "POST", f"{base}/{head['option_id']}/adopt",
            {"expected_revision": head["revision_no"], "expected_version": 0})
        code_old, stale = http(
            "POST", f"{base}/{r1['option_id']}/adopt",
            {"expected_revision": 1, "expected_version": 1})
        check("L11", "显式采用指定分叉版本成功；再采用旧版本被 CAS 拒绝（谱系身份可用于采用）",
              bool(code == 200 and adopted.get("formal_approval") is False
                   and code_old == 409 and stale.get("error_code") == "STALE_OPTION_REVISION"),
              {"adopt": code, "adopt_old": [code_old, stale.get("error_code")],
               "adopted_revision": head["revision_no"],
               "lineage_revisions": [r["revision_no"] for r in lineage_rows]})
        # ---------- L12/L13 deterministic seam: competing commit between prepare and write
        art_e = save(studio, "E", base_a, uid="uid-E-1", parent_uid=None)
        art_f = save(studio, "F", base_b, uid="uid-F-1", parent_uid=None)
        before_rows, before_svg = len(revisions()), svg_count()
        inner_done = {"same_source": False}
        outer_same = {}

        def competing_same_source():
            if inner_done["same_source"]:
                return
            inner_done["same_source"] = True
            outer_same["inner"] = options_ai.import_studio_proposal(
                ORG, PID, "tester", body(art_f))

        outer_same["outer"] = options_ai.import_studio_proposal(
            ORG, PID, "tester", body(art_f),
            after_prepare=competing_same_source)
        rows = revisions()
        f_rows = [r for r in rows if r["source_uid"] == "uid-F-1"]
        check("L12", "确定性并发（同源）：准备后、提交前另一个请求写入，写内重检复用且清理自己的文件",
              bool(outer_same["outer"].get("reused") is True
                   and outer_same["inner"].get("reused") is False
                   and len(f_rows) == 1
                   and len(rows) == before_rows + 1
                   and svg_count() == before_svg + 1),
              {"outer_reused": outer_same["outer"].get("reused"),
               "inner_reused": outer_same["inner"].get("reused"),
               "versions": len(f_rows),
               "rows_delta": len(rows) - before_rows,
               "svg_delta": svg_count() - before_svg})

        art_g1 = save(studio, "G", base_a, uid="uid-G-1", parent_uid=None)
        art_g2 = save(studio, "G", plan_a2, uid="uid-G-2", parent_uid="uid-G-1")
        art_g3 = save(studio, "G", plan_a2b, uid="uid-G-3", parent_uid="uid-G-1")
        http("POST", f"{base}/import-studio", body(art_g1))
        before_rows, before_svg = len(revisions()), svg_count()
        inner_done2 = {"done": False}
        outer_lineage = {}

        def competing_sibling():
            if inner_done2["done"]:
                return
            inner_done2["done"] = True
            outer_lineage["inner"] = options_ai.import_studio_proposal(
                ORG, PID, "tester", body(art_g3))

        outer_lineage["outer"] = options_ai.import_studio_proposal(
            ORG, PID, "tester", body(art_g2),
            after_prepare=competing_sibling)
        rows = revisions()
        g1 = next(r for r in rows if r["source_uid"] == "uid-G-1")
        g2 = next(r for r in rows if r["source_uid"] == "uid-G-2")
        g3 = next(r for r in rows if r["source_uid"] == "uid-G-3")
        check("L13", "确定性并发（同谱系两分叉）：写内重算版本号，父都指向 v1，无双写/唯一冲突",
              bool(outer_lineage["outer"].get("reused") is False
                   and outer_lineage["inner"].get("reused") is False
                   and g2["revision_no"] != g3["revision_no"]
                   and g2["parent_revision_id"] == g1["option_revision_id"]
                   and g3["parent_revision_id"] == g1["option_revision_id"]
                   and len(rows) == before_rows + 2
                   and svg_count() == before_svg + 2),
              {"revision_numbers": [g2["revision_no"], g3["revision_no"]],
               "parents": [g2["parent_revision_id"], g3["parent_revision_id"]],
               "shared_parent": g1["option_revision_id"],
               "rows_delta": len(rows) - before_rows,
               "svg_delta": svg_count() - before_svg})

    finally:
        server.shutdown(); server.server_close(); thread.join(3)
        main_store.close()

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    out = {
        "task_id": "W1 版本谱系收口（源谱系身份 / 父 UID 映射 / 写内并发重检）",
        "schema_version": "rkd-w1-lineage-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": __import__("subprocess").run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "environment": {"python": sys.version.split()[0],
                        "isolated_main_db": str(MAIN_DB),
                        "isolated_studio_db": str(STUDIO_DB),
                        "model_channel": "labelled local fixtures only",
                        "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "limitations": [
            "源是明确标记的本地夹具，不是真实 AI 设计，不计入 AD01—AD08",
            "并发用线程屏障同时发起真实 HTTP；不覆盖多进程/断电恢复",
            "W2 制图/渲染/量价未开始；Q10 仍 not_run",
        ],
    }
    (EVIDENCE / "lineage-checks.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(CHECKS) - failed, "failed": failed,
                      "out": str(EVIDENCE / "lineage-checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
