"""TEXT-01 保守判定：否定 / 并列缺失对象 / 同子句残余 —— 真实 HTTP 验收。

隔离 Studio 库 + 真实 HTTP 服务 + 明确标注的本地模型桩（0 外部调用、0 密钥、
0 费用）。所有留言都按老板的正常入口提交，只发送 text 与选定基线；
结构化目标/锁一律由服务端从文字解析，验收脚本不替用户补。

用法：
  python scripts/verify_conservative_http.py --out <dir> --runtime <dir>
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


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W0-文字反馈保守判定/after/conservative-http")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W0-文字反馈保守判定/runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
DB = RUNTIME / "conservative-http.db"
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
PORT = 8124
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
    import threading
    studio_server.Config = StubConfig
    orchestrator.Client = vsl.FakeClient
    vision.svg_to_jpeg = lambda svg, limit=720: vsl.FAKE_JPEG
    vision.reference_jpeg = lambda limit=720: vsl.FAKE_JPEG

    st = Store(DB)
    orchestrator.Studio(st).seed_from_fixtures()
    orchestrator.Studio(st).run_a1(PID, background=False)
    a1 = pick_baseline(st.project_state(PID))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), studio_server.Handler)
    t = threading.Thread(target=httpd.serve_forever, name="conservative-http", daemon=True)
    t.start()

    def gate_text(stt: dict) -> str:
        gates = [m for m in stt["messages"] if m.get("kind") == "gate"]
        # Only the gate produced by THIS case: earlier gates must not leak in.
        return json.dumps(gates[-1:], ensure_ascii=False, default=str)

    def notes(stt: dict) -> str:
        return json.dumps([m.get("body") for m in stt["messages"]
                           if m.get("kind") == "note"][-3:], ensure_ascii=False)

    try:
        # ------------------------------------------------ C01 否定不反转、不交稿
        r = run_once("不要把 F3 旋转到 -30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        snap = r["snapshot"]
        g = gate_text(r["state"])
        check("CONS-01", "否定要求：不生成相反目标，明确 conflict + unknown/pending",
              bool(r["post"] == 201 and snap["run_status"] == "conflict"
                   and snap["artifact_count"] == 0
                   and "否定要求" in g and "不要把 F3 旋转到 -30 度" in g
                   and "unknown + pending" in g),
              {"post": r["post"], "run_status": snap["run_status"],
               "artifacts": snap["artifact_count"],
               "gate_has_negation": "否定要求" in g,
               "gate_has_original_text": "不要把 F3 旋转到 -30 度" in g})

        # ------------------------------ C02 「不超过 / 不低于」不被否定守卫误杀
        r = run_once("主动线净宽不超过 2400mm", a1,
                     [{"op": "update", "group": "circulation", "id": "CA1",
                       "fields": {"width_mm": 2600}}])
        meas = [x for x in rechecks(r["snapshot"]) if x.get("kind") == "measurable"]
        comp = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                for x in meas]
        check("CONS-02", "「不超过」仍是 max（不是否定）；「不低于」仍是 min",
              bool(r["snapshot"]["run_status"] == "incomplete" and comp == ["max"]
                   and "否定要求" not in gate_text(r["state"])),
              {"run_status": r["snapshot"]["run_status"], "comparators": comp})

        r = run_once("L1 色温不低于 4000K", a1,
                     [{"op": "update", "group": "ceiling.fixtures", "id": "L1",
                       "fields": {"kelvin": 3600}}])
        comp = [(x.get("evidence", {}).get("after", {}) or {}).get("comparator")
                for x in rechecks(r["snapshot"]) if x.get("kind") == "measurable"]
        check("CONS-03", "「不低于」仍是 min，否定守卫没有把支持比较符一并拒绝",
              bool(r["snapshot"]["run_status"] == "incomplete" and comp == ["min"]
                   and "否定要求" not in gate_text(r["state"])),
              {"run_status": r["snapshot"]["run_status"], "comparators": comp})

        # ------------------------------------- C04 带「把」的否定也拒绝
        r = run_once("不要把主动线净宽扩大到 2400mm", a1,
                     [{"op": "update", "group": "circulation", "id": "CA1",
                       "fields": {"width_mm": 2400}}])
        snap = r["snapshot"]
        check("CONS-04", "「不要把净宽扩大到…」不变成 min 2400 的正向目标",
              bool(snap["run_status"] == "conflict" and snap["artifact_count"] == 0
                   and "否定要求" in gate_text(r["state"])),
              {"run_status": snap["run_status"], "artifacts": snap["artifact_count"]})

        # -------------------------------- C05 存在 + 缺失对象并列：完整引用
        r = run_once("把 F1 和 F9 旋转到 -30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F1",
                       "fields": {"rot": -30}}])
        snap = r["snapshot"]
        meas = [x for x in rechecks(snap) if x.get("kind") == "measurable"]
        ev = (meas[0].get("evidence", {}).get("after", {}) or {}) if meas else {}
        check("CONS-05", "F1+F9 并列：保留全部引用、F9 按缺失判 fail、不宣布绑定成功",
              bool(snap["run_status"] == "incomplete" and not snap["valid_artifacts"]
                   and meas
                   and (meas[0].get("target_objects") or []) == ["F1", "F9"]
                   and (meas[0].get("all_object_references") or []) == ["F1", "F9"]
                   and meas[0].get("objective_rechecked") == "fail"
                   and ev.get("missing_object_ids") == ["F9"]),
              {"run_status": snap["run_status"],
               "targets": [x.get("target_objects") for x in meas],
               "refs": [x.get("all_object_references") for x in meas],
               "missing": ev.get("missing_object_ids"),
               "states": [x.get("objective_rechecked") for x in meas]})

        # ------------------------------------------ C06 仅缺失对象（回归护栏）
        r = run_once("把 F9 旋转到 30 度", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": 30}}])
        meas = [x for x in rechecks(r["snapshot"]) if x.get("kind") == "measurable"]
        check("CONS-06", "仅缺失对象：仍按对象缺失阻断（旧行为保持）",
              bool(r["snapshot"]["run_status"] == "incomplete" and meas
                   and (meas[0].get("target_objects") or []) == ["F9"]
                   and meas[0].get("objective_rechecked") == "fail"),
              {"run_status": r["snapshot"]["run_status"],
               "targets": [x.get("target_objects") for x in meas]})

        # -------------------------------- C07 无逗号复合句：残余诉求不被吞
        r = run_once("把 F3 旋转到 -30 度并让整体更有设计感", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        snap = r["snapshot"]
        rows = rechecks(snap)
        meas = [x for x in rows if x.get("kind") == "measurable"]
        pend = [x for x in rows if x.get("kind") in ("aesthetic", "unparsed")]
        check("CONS-07", "无逗号复合句：数值 pass 之外，审美残余仍 unknown+pending",
              bool(snap["run_status"] == "succeeded" and len(meas) == 1
                   and meas[0].get("objective_rechecked") == "pass"
                   and any(x.get("unparsed_reason") == "unparsed_remainder_in_clause"
                           and "设计感" in str(x.get("residual_text"))
                           and x.get("user_confirmed") == "pending" for x in pend)
                   and "未验证" in notes(r["state"])),
              {"run_status": snap["run_status"],
               "states": [(x.get("kind"), x.get("objective_rechecked"),
                           x.get("user_confirmed")) for x in rows],
               "residual": [x.get("residual_text") for x in pend],
               "note_has_pending": "未验证" in notes(r["state"])})

        # ------------------------- C08 残余检测是通用的（换成非审美词也留痕）
        r = run_once("把 F3 旋转到 -30 度并复核北侧收口", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        pend = [x for x in rechecks(r["snapshot"])
                if x.get("kind") in ("aesthetic", "unparsed")]
        check("CONS-08", "非审美残余「复核北侧收口」同样留痕，不是词表补丁",
              bool(any(x.get("unparsed_reason") == "unparsed_remainder_in_clause"
                       and "收口" in str(x.get("residual_text"))
                       and x.get("user_confirmed") == "pending" for x in pend)),
              {"residual": [x.get("residual_text") for x in pend],
               "kinds": [x.get("kind") for x in pend]})

        # ----------------------------- C09 有标点的复合句仍 pending（回归护栏）
        r = run_once("把 F3 旋转到 -30 度，整体更有设计感", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        pend = [x for x in rechecks(r["snapshot"]) if x.get("kind") == "aesthetic"]
        check("CONS-09", "有标点时审美仍 pending，新残余逻辑没有把旧行为改坏",
              bool(r["snapshot"]["run_status"] == "succeeded" and pend
                   and all(x.get("user_confirmed") == "pending" for x in pend)),
              {"run_status": r["snapshot"]["run_status"],
               "pending": [(x.get("objective_rechecked"), x.get("user_confirmed"))
                           for x in pend]})

        # ------------------------- C10 保留表达里的「不」不被当成否定
        r = run_once("把 F3 旋转到 -30 度，其他家具不动", a1,
                     [{"op": "update", "group": "furniture", "id": "F3",
                       "fields": {"rot": -30}}])
        rows = rechecks(r["snapshot"])
        pres = [x for x in rows if x.get("kind") == "preserve"]
        check("CONS-10", "「其他家具不动」仍是保留约束，没有被否定守卫误杀",
              bool(r["snapshot"]["run_status"] == "succeeded"
                   and "否定要求" not in gate_text(r["state"])
                   and pres and pres[0].get("objective_rechecked") == "pass"),
              {"run_status": r["snapshot"]["run_status"],
               "preserve": [(x.get("objective_rechecked"), x.get("user_confirmed"))
                            for x in pres]})
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(5)


    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    out = {
        "task_id": "W0 文字反馈保守判定（TEXT-01 边界 · 真实 HTTP）",
        "schema_version": "rkd-conservative-http-checks.v1",
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
