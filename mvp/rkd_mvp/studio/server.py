"""Studio HTTP service (A1): roster, timeline, artifacts, gates.

Runs on 127.0.0.1:8099 next to the frozen production app so nothing in the
workbench's own API is touched. Loopback only; CORS limited to local origins.

ARC-04: boss messages / rejections become versioned feedback; gates are bound
to a concrete artifact baseline and replay cannot overwrite a decision; project
ids are explicitly mapped and this local experiment service is labelled as such.
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .llm import Config
from .orchestrator import Studio
from .roles import ROSTER
from .store import Store

ALLOWED_ORIGINS = {"http://127.0.0.1:8080", "http://localhost:8080",
                   "http://127.0.0.1:5173", "http://localhost:5173"}

SERVICE_SCOPE = {
    "mode": "local_experiment",
    "label": "本机设计公司实验服务（独立 var/studio/studio.db）",
    "team_nas_supported": False,
    "team_nas_note": "未接入团队/NAS 服务；不冒称已支持多人或正式生产",
    "supported_project_ids": ["ningbo-xiecheng"],
    "project_id_mapping": "Studio 内部 id 与主系统 project_id 可不同；唯一显式映射见 /studio/projects 的 project_mapping（fixture 的 source_project_id）。按名称推断或回退宁波均被拒绝",
}

STUDIO: Studio | None = None


def studio() -> Studio:
    global STUDIO
    if STUDIO is None:
        STUDIO = Studio(Store())
        STUDIO.seed_from_fixtures()
    return STUDIO


class Handler(BaseHTTPRequestHandler):
    server_version = "rkd-studio/0.1"

    def log_message(self, fmt: str, *args) -> None:  # keep the console clean
        return None

    # ------------------------------------------------------------------ helpers
    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _text(self, status: int, body: str, ctype: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _known_project(self, pid: str) -> str | None:
        """Resolve via the explicit mapping table; never fall back to Ningbo."""
        return studio().store.resolve_project_id(pid)

    # --------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/studio/health":
            cfg = Config.from_env()
            return self._json(200, {"status": "ok", "channel_configured": cfg.configured,
                                    "model": cfg.model, "base_url": cfg.base_url,
                                    "service_scope": SERVICE_SCOPE,
                                    "project_mapping": studio().store.project_mapping()})
        if path == "/studio/roles":
            return self._json(200, {"roster": ROSTER})
        if path == "/studio/projects":
            return self._json(200, {"items": studio().store.list_projects(),
                                    "project_mapping": studio().store.project_mapping(),
                                    "service_scope": SERVICE_SCOPE})
        m = re.fullmatch(r"/studio/projects/([^/]+)/state", path)
        if m:
            pid = self._known_project(m.group(1))
            if not pid:
                return self._json(404, {
                    "error": f"项目 {m.group(1)} 未接入本机 Studio 实验服务",
                    "hint": "本机只开放已显式映射的试验项目；不会回退显示或写入宁波项目结果",
                    "service_scope": SERVICE_SCOPE})
            return self._json(200, _state(pid))
        m = re.fullmatch(r"/studio/artifacts/([^/]+)/svg", path)
        if m:
            for a in studio().store.artifacts(_project_of_artifact(m.group(1))):
                if a["id"] == m.group(1):
                    return self._text(200, a["payload"].get("svg", ""),
                                      "image/svg+xml; charset=utf-8")
            return self._json(404, {"error": "artifact not found"})
        return self._json(404, {"error": "not found"})

    # -------------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._body()
        m = re.fullmatch(r"/studio/projects/([^/]+)/run", path)
        if m:
            pid = self._known_project(m.group(1))
            if not pid:
                return self._json(404, {"error": f"项目 {m.group(1)} 未接入本机 Studio 实验服务",
                                        "service_scope": SERVICE_SCOPE})
            cfg = Config.from_env()
            if not cfg.configured:
                return self._json(409, {"error": "未配置模型通道：RKD_AI_API_KEY 不在环境变量里",
                                        "hint": "密钥只放当前会话环境变量，不写入任何文件"})
            result = studio().run_a1(pid, background=True)
            return self._json(202, result)
        m = re.fullmatch(r"/studio/projects/([^/]+)/messages", path)
        if m:
            pid = self._known_project(m.group(1))
            if not pid:
                return self._json(404, {"error": f"项目 {m.group(1)} 未接入本机 Studio 实验服务",
                                        "service_scope": SERVICE_SCOPE})
            text = (body.get("text") or "").strip()
            if not text:
                return self._json(400, {"error": "空消息"})
            st = studio().store
            mid = st.add_message(pid, "BOSS", "boss", text,
                                 evidence=[{"type": "boss"}])
            # ARC-04: versioned feedback, not timeline-only. Binds the current
            # valid candidate baseline so the next revision has a real target.
            baseline = _latest_valid_plan(st, pid)
            fb = st.add_feedback(
                pid, "boss_message", text,
                source_message_id=mid,
                baseline_artifact_id=baseline["id"] if baseline else None,
                baseline_revision_uid=baseline["revision_uid"] if baseline else None,
            )
            # persistent cancellation: a late result from the previous input
            # must not become the current version (checked again at run finish).
            for r in st.runs(pid):
                if r["status"] == "running":
                    st.request_cancel(r["id"])
            return self._json(201, {"ok": True, "message_id": mid,
                                    "feedback": fb,
                                    "effective_requirement_hash":
                                        st.effective_requirement(pid)["effective_input_hash"],
                                    "note": "留言已进入版本化有效需求；下一轮修订将读取该输入并给出对象 diff"})
        m = re.fullmatch(r"/studio/gates/([^/]+)/decide", path)
        if m:
            gid = m.group(1)
            decision = (body.get("decision") or "").strip()
            comment = (body.get("comment") or "").strip()
            scope = (body.get("decision_scope") or "allow_continue").strip()
            if decision not in {"approve", "reject"}:
                return self._json(400, {"error": "decision 只能是 approve 或 reject"})
            if scope not in {"allow_continue", "direction_approval"}:
                return self._json(400, {"error":
                    "decision_scope 只能是 allow_continue（允许继续试验）或 "
                    "direction_approval（认可设计方向）；两者都不等于设计通过"})
            if decision == "reject" and not comment:
                return self._json(400, {"error": "驳回必须写理由：这条理由会进入版本化反馈"})
            st = studio().store
            gate = st.gate(gid)
            if not gate:
                return self._json(404, {"error": "gate not found"})
            result = st.decide_gate(gid, decision, comment, decision_scope=scope)
            pid = gate["project_id"]
            # A rejection reason is real feedback; an approval is not a design pass.
            if decision == "reject":
                st.add_feedback(
                    pid, "gate_rejection", comment, gate_id=gid,
                    baseline_artifact_id=gate.get("baseline_artifact_id"),
                    baseline_revision_uid=gate.get("baseline_revision_uid"))
            st.add_message(
                pid, "BOSS", "decision",
                ("批准：" if decision == "approve" else "驳回：") + comment
                + f"（{_scope_label(scope)}；不等于设计通过）",
                evidence=[{"type": "gate", "id": gid, "decision": decision,
                           "decision_scope": scope, "replay_applied": result["applied"],
                           "baseline_artifact_id": gate.get("baseline_artifact_id"),
                           "baseline_revision_uid": gate.get("baseline_revision_uid")}])
            return self._json(200, {
                "ok": True, **result,
                "baseline_artifact_id": gate.get("baseline_artifact_id"),
                "baseline_revision_uid": gate.get("baseline_revision_uid"),
                "note": ("原决定已存在：本次作为新决定记录追加，未覆盖旧决定"
                         if result["reason"] == "already_decided_correction_recorded"
                         else "闸口决定已记录；允许继续试验/认可设计方向均不等于设计通过")})
        return self._json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()


def _scope_label(scope: str) -> str:
    return "允许继续试验" if scope == "allow_continue" else "认可设计方向"


def _latest_valid_plan(st: Store, pid: str) -> dict | None:
    valid = [a for a in st.artifacts(pid)
             if a["kind"] == "spatial-plan" and a["contract_status"] == "valid_candidate"
             and a["status"] not in ("superseded", "invalid_raw")]
    return valid[-1] if valid else None


def _project_of_artifact(artifact_id: str) -> str:
    st = studio().store
    for p in st.list_projects():
        for a in st.artifacts(p["id"]):
            if a["id"] == artifact_id:
                return p["id"]
    return ""


def _state(project_id: str) -> dict:
    st = studio().store
    state = st.project_state(project_id)
    cfg = Config.from_env()
    arts = []
    for a in state["artifacts"]:
        payload = a["payload"]
        item = {k: a[k] for k in ("id", "kind", "option_id", "revision", "parent_revision",
                                  "author", "sha256", "status", "created_at", "run_id",
                                  "candidate_group_id", "revision_uid", "parent_revision_uid",
                                  "input_hash", "check_report_id", "contract_status")}
        # Historical bytes are NEVER deleted. Old rows without a contract_status
        # are explicitly labelled legacy/unvalidated and grouped separately.
        if not item["contract_status"]:
            item["contract_status"] = "legacy_unvalidated"
            item["display_group"] = "history"
        elif item["contract_status"] == "valid_candidate" and item["status"] not in ("superseded",):
            item["display_group"] = "valid"
        else:
            item["display_group"] = "history"
        if a["kind"] == "plan-sketch":
            item["svg_url"] = f"/studio/artifacts/{a['id']}/svg"
        else:
            item["payload"] = payload
        if a["diagnostics"]:
            item["diagnostics"] = a["diagnostics"]
        arts.append(item)
    state["artifacts"] = arts
    state["roster"] = ROSTER
    state["channel"] = {"configured": cfg.configured, "model": cfg.model,
                        "base_url": cfg.base_url,
                        "run_limit": cfg.run_token_limit,
                        "project_limit": cfg.project_token_limit}
    state["service_scope"] = SERVICE_SCOPE
    state["project_mapping"] = st.project_mapping()
    state["running"] = project_id in studio()._running
    state["valid_candidate_ids"] = [a["id"] for a in arts
                                    if a.get("display_group") == "valid"]
    state["stage_status"] = {
        "flow_finished": any(r["status"] in ("succeeded", "incomplete", "failed",
                                             "budget_stopped", "model_failed", "superseded")
                             for r in state["runs"]),
        "valid_artifact_exists": bool(state["valid_candidate_ids"]),
        "waiting_user": any(g["status"] == "waiting" for g in state["gates"]),
        "design_approved_by_user": False,
        "note": "流程跑完 / 成果有效 / 等待用户 / 设计认可分别表达；设计认可只能由用户给出",
    }
    return state


def main(port: int = 8099) -> None:
    studio()  # seed + migrate before serving
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"status": "serving", "url": f"http://127.0.0.1:{port}/studio/health",
                      "service_scope": SERVICE_SCOPE}, ensure_ascii=False), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
