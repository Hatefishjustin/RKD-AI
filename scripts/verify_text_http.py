"""TEXT-01 真实 HTTP 验收：普通文字留言 → /run，全程不手填 objectives/locks。

隔离 Studio 库 + 真实 HTTP 服务 + 明确标注的本地模型桩（0 外部调用、0 密钥、
0 费用）。所有留言都按老板的正常入口提交，只发送 text 与选定基线；
结构化目标/锁一律由服务端从文字解析，验收脚本不替用户补。

用法：
  python scripts/verify_text_http.py --out <dir> --runtime <dir>
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arg(flag: str, default: Path) -> Path:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if a.startswith(flag + "="):
            return Path(a.split("=", 1)[1]).resolve()
    return default


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W0-文字反馈收口/after/http")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W0-文字反馈收口/runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
DB = RUNTIME / "text-http.db"
if DB.exists():
    DB.unlink()
os.environ["RKD_STUDIO_DB"] = str(DB)
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from rkd_mvp.studio import orchestrator, server as studio_server, vision  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
import verify_studio_loop as vsl  # noqa: E402

PID = "ningbo-xiecheng"
PORT = 8123
CHECKS: list[dict] = []


class StubConfig:
    configured = True
    model = "local-model-stub"
    base_url = "local://stub"
    run_token_limit = 600_000
    project_token_limit = 2_000_000

    @classmethod
    def from_env(cls):
        return cls()


def check(cid: str, name: str, ok: bool, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def http(path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def state() -> dict:
    code, body = http(f"/studio/projects/{PID}/state")
    assert code == 200, (code, body)
    return body


def wait_run(run_id: str, timeout: float = 180.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        code, body = http(f"/studio/projects/{PID}/runs/{run_id}")
        assert code == 200, (code, body)
        if body["finished"]:
            return body
        time.sleep(0.3)
    raise TimeoutError(run_id)


def post_text(text: str, baseline: dict) -> tuple[int, dict]:
    """The NORMAL user entry: text + selected baseline and nothing else."""
    return http(f"/studio/projects/{PID}/messages",
                {"text": text, "baseline_artifact_id": baseline["id"],
                 "baseline_revision_uid": baseline["revision_uid"]})


def run_once(text: str, baseline: dict,
             patch: list[dict] | None) -> dict:
    original = vsl.revision_payload
    vsl.revision_payload = lambda: {"responses": [], "patch": patch or []}
    try:
        code, posted = post_text(text, baseline)
        code2, started = http(f"/studio/projects/{PID}/run", {})
        assert code2 == 202, (code2, started)
        snap = wait_run(started["run_id"])
    finally:
        vsl.revision_payload = original
    return {"post": code, "run": code2, "run_id": started["run_id"],
            "snapshot": snap, "state": state()}


def rechecks(snap: dict) -> list[dict]:
    out: list[dict] = []
    for a in snap["artifacts"]:
        diag = a.get("diagnostics") or {}
        integ = diag.get("integrity") or {}
        out.extend(integ.get("objective_rechecks") or [])
    return out


def ran_diag(snap: dict) -> str:
    return json.dumps([a.get("diagnostics") for a in snap["artifacts"]],
                      ensure_ascii=False, default=str)


def pick_baseline(st: dict) -> dict:
    return next(a for a in st["artifacts"]
                if a["kind"] == "spatial-plan" and a["option_id"] == "A"
                and a["revision"] == 1 and a["contract_status"] == "valid_candidate")


def main() -> int:
    studio_server.Config = StubConfig
    orchestrator.Client = vsl.FakeClient
    vision.svg_to_jpeg = lambda svg, limit=720: vsl.FAKE_JPEG
    vision.reference_jpeg = lambda limit=720: vsl.FAKE_JPEG

    st = Store(DB)
    orchestrator.Studio(st).seed_from_fixtures()
    orchestrator.Studio(st).run_a1(PID, background=False)
    a1 = pick_baseline(st.project_state(PID))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), studio_server.Handler)
    import threading
    t = threading.Thread(target=httpd.serve_forever, name="text-http", daemon=True)
    t.start()
    try:
        # ---------------------------------------------------------------- 1 只改 F3
        r = run_once("把 F3 旋转到 -30 度，其他家具不动", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        snap = r["snapshot"]
        rows = rechecks(snap)
        meas = [x for x in rows if x.get("kind") == "measurable"]
        pres = [x for x in rows if x.get("kind") == "preserve"]
        diff = next((a.get("diagnostics", {}).get("object_diff") for a in snap["artifacts"]
                     if a["kind"] == "spatial-plan"), [])
        check("TEXT-01", "点名 F3 旋转：只改 F3 通过，目标对象是 F3 而不是整类家具",
              bool(r["post"] == 201 and snap["run_status"] == "succeeded"
                   and diff == ["furniture:F3"]
                   and meas and meas[0].get("target_objects") == ["F3"]
                   and meas[0].get("objective_rechecked") == "pass"),
              {"post": r["post"], "run_status": snap["run_status"],
               "object_diff": diff,
               "targets": [x.get("target_objects") for x in meas],
               "states": [x.get("objective_rechecked") for x in meas],
               "preserve": [(x.get("objective_rechecked"), x.get("user_confirmed"))
                            for x in pres]})

        # ------------------------------------------- 2 同一句话，误改其他家具被拦
        r = run_once("把 F3 旋转到 -30 度，其他家具不动", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}},
                      {"op": "update", "group": "furniture", "id": "F1",
                       "fields": {"rot": 45}}])
        snap = r["snapshot"]
        diag = ran_diag(snap)
        check("TEXT-02", "同一句话：误改「其他家具」被保留要求拦下，不落有效修订",
              bool(snap["run_status"] == "incomplete" and not snap["valid_artifacts"]
                   and ("LOCK-PRESERVE" in diag or "LOCK-REVISION" in diag)
                   and "F1" in diag),
              {"run_status": snap["run_status"],
               "valid_artifacts": len(snap["valid_artifacts"]),
               "LOCK_in_diagnostics": "LOCK-" in diag})

        # ------------------------------------------------- 3 两个对象只改一个
        r = run_once("把 F1 和 F3 都转到 30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": 30}}])
        snap = r["snapshot"]
        rows = rechecks(snap)
        meas = [x for x in rows if x.get("kind") == "measurable"]
        check("TEXT-03", "点名 F1 和 F3：只改 F3 被判部分达标失败",
              bool(snap["run_status"] == "incomplete" and not snap["valid_artifacts"]
                   and meas and meas[0].get("objective_rechecked") == "fail"
                   and (meas[0].get("target_objects") or []) == ["F1", "F3"]),
              {"run_status": snap["run_status"],
               "targets": [x.get("target_objects") for x in meas],
               "states": [x.get("objective_rechecked") for x in meas],
               "failing": [(x.get("evidence", {}).get("after", {}) or {})
                           .get("failing_object_ids") for x in meas]})

        # --------------------------------------------- 4 显式「所有/都」才整组
        r = run_once("把家具都转到 30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": 30}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        check("TEXT-04", "明确说「家具都」：整组是用户自己说的话，只改一个仍算失败",
              bool(snap["run_status"] == "incomplete"
                   and meas and (meas[0].get("target_objects") or []) == ["F1", "F2", "F3"]
                   and meas[0].get("objective_rechecked") == "fail"),
              {"run_status": snap["run_status"],
               "targets": [x.get("target_objects") for x in meas],
               "states": [x.get("objective_rechecked") for x in meas]})

        # ------------------------------------------------ 5 点名不存在的对象
        r = run_once("把 F9 旋转到 30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": 30}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        miss = [(x.get("evidence", {}).get("after", {}) or {}).get("missing_object_ids")
                for x in meas]
        check("TEXT-05", "点名 F9（不存在）不退化成整类家具，按对象缺失判失败",
              bool(snap["run_status"] == "incomplete" and meas
                   and meas[0].get("objective_rechecked") == "fail"
                   and miss == [["F9"]]),
              {"run_status": snap["run_status"],
               "targets": [x.get("target_objects") for x in meas],
               "missing": miss,
               "states": [x.get("objective_rechecked") for x in meas]})

        # ------------------------------------------------------- 6 上限不进反
        r = run_once("主动线净宽不超过 2400mm", a1,
                     [{"op": "update", "group": "circulation", "id": "CA1",
                       "fields": {"width_mm": 2600}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        comparators = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                       for x in meas]
        check("TEXT-06", "「不超过」进入 max（没有反转成默认 min）；超上限判失败",
              bool(snap["run_status"] == "incomplete" and comparators == ["max"]
                   and meas[0].get("objective_rechecked") == "fail"),
              {"run_status": snap["run_status"], "comparators": comparators,
               "states": [x.get("objective_rechecked") for x in meas],
               "measured": [(x.get("evidence", {}).get("after", {}) or {}).get("measured")
                            for x in meas]})

        # ------------------------------------------- 7 上限正例（色温，字段可测）
        r = run_once("L1 色温不超过 4000K", a1,
                     [{"op": "update", "group": "ceiling.fixtures", "id": "L1",
                       "fields": {"kelvin": 3500}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        comp = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                for x in meas]
        check("TEXT-07", "上限正例：3500K 满足「不超过 4000K」→ pass（方向没弄反）",
              bool(snap["run_status"] == "succeeded" and comp == ["max"]
                   and meas and meas[0].get("objective_rechecked") == "pass"),
              {"run_status": snap["run_status"], "comparators": comp,
               "states": [x.get("objective_rechecked") for x in meas]})

        # ------------------------------------------- 8 同一数据的下限必须失败
        r = run_once("L1 色温不低于 4000K", a1,
                     [{"op": "update", "group": "ceiling.fixtures", "id": "L1",
                       "fields": {"kelvin": 3600}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        comp = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                for x in meas]
        check("TEXT-08", "下限负例：3600K 不满足「不低于 4000K」→ fail（与上限相反）",
              bool(snap["run_status"] == "incomplete" and comp == ["min"]
                   and meas and meas[0].get("objective_rechecked") == "fail"),
              {"run_status": snap["run_status"], "comparators": comp,
               "states": [x.get("objective_rechecked") for x in meas]})

        # ------------------------------------------ 9 数值 + 保留 + 审美 三类共存
        r = run_once("主动线净宽至少 2100mm，保留入口，整体更有设计感", a1,
                     [{"op": "update", "group": "circulation", "id": "CA1",
                       "fields": {"width_mm": 2100}}])
        snap = r["snapshot"]
        rows = rechecks(snap)
        kinds = sorted({x.get("kind") for x in rows})
        pending = [x.get("objective_id") for x in rows
                   if x.get("user_confirmed") == "pending"]
        check("TEXT-09", "数值+保留+审美三类都在；审美不因数值通过而被吞掉",
              bool(snap["run_status"] == "succeeded"
                   and {"measurable", "preserve", "aesthetic"} <= set(kinds)
                   and pending),
              {"run_status": snap["run_status"], "kinds": kinds,
               "pending_objectives": pending,
               "states": [(x.get("kind"), x.get("objective_rechecked"),
                           x.get("user_confirmed")) for x in rows]})

        # ------------------------------------------------- 10 两个数值同一句
        r = run_once("F1 和 F3 分别转到 30 和 -30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F1",
                       "fields": {"rot": 30}},
                      {"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        snap = r["snapshot"]
        rows = rechecks(snap)
        pend = [(x.get("unparsed_reason"), x.get("source_text")) for x in rows
                if x.get("kind") in ("aesthetic", "unparsed")]
        verified = [x.get("objective_rechecked") for x in rows
                    if x.get("kind") == "measurable"]
        check("TEXT-10", "一句两个数值不取第一个：列为未解析待确认，不冒充已验证",
              bool(any(p[0] == "multiple_values_in_clause" for p in pend)
                   and not verified),
              {"run_status": snap["run_status"], "pending": pend,
               "measurable_states": verified})

        # ------------------------------------------------- 11 同基线矛盾要求
        code_a, _ = post_text("主动线净宽至少 2400mm", a1)
        code_b, _ = post_text("主动线净宽不超过 2100mm", a1)
        code2, started = http(f"/studio/projects/{PID}/run", {})
        snap = wait_run(started["run_id"])
        stt = state()
        gate = [m for m in stt["messages"] if m["kind"] == "gate"]
        gate_txt = json.dumps(gate[-1:], ensure_ascii=False)
        check("TEXT-11", "同基线两条互相矛盾的数值要求：显式 conflict，不开跑、不返工硬凑",
              bool(code_a == 201 and code_b == 201 and code2 == 202
                   and snap["run_status"] == "conflict"
                   and snap["artifact_count"] == 0
                   and "min 2400" in gate_txt and "max 2100" in gate_txt),
              {"post": [code_a, code_b], "run_status": snap["run_status"],
               "artifacts": snap["artifact_count"],
               "gate_has_both_requirements": ("min 2400" in gate_txt
                                              and "max 2100" in gate_txt)})

        # --------------------------------------- 12 单对象精确值正例（回归护栏）
        r = run_once("把 F1 旋转到 45 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F1",
                       "fields": {"rot": 45}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        comp = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                for x in meas]
        diff = next((a.get("diagnostics", {}).get("object_diff") for a in snap["artifacts"]
                     if a["kind"] == "spatial-plan"), [])
        check("TEXT-12", "普通单对象精确值：仍然正常通过（新解析没有把正常输入弄坏）",
              bool(snap["run_status"] == "succeeded" and comp == ["exact"]
                   and diff == ["furniture:F1"]),
              {"run_status": snap["run_status"], "comparators": comp,
               "object_diff": diff})
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(5)

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    out = {
        "task_id": "W0 文字反馈收口（TEXT-01 真实 HTTP）",
        "schema_version": "rkd-text-http-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": __import__("subprocess").run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "environment": {"python": sys.version.split()[0],
                        "model_channel": "local-model-stub (explicitly labelled)",
                        "service": f"studio HTTP 127.0.0.1:{PORT} (isolated DB)",
                        "keys_used": False},
        "entry_note": "所有留言都用正常入口 POST /messages（只给 text 与选定基线），"
                      "没有在验收脚本里注入 objectives 或 locks",
        "checks": CHECKS,
        "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
    }
    (EVIDENCE / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({"passed": len(CHECKS) - failed, "failed": failed,
                      "out": str(EVIDENCE / "checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
