"""Studio HTTP service (A1): roster, timeline, artifacts, gates.

Runs on 127.0.0.1:8099 next to the frozen production app so nothing in the
workbench's own API is touched. Loopback only; CORS limited to local origins.
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

    # --------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/studio/health":
            cfg = Config.from_env()
            return self._json(200, {"status": "ok", "channel_configured": cfg.configured,
                                    "model": cfg.model, "base_url": cfg.base_url})
        if path == "/studio/roles":
            return self._json(200, {"roster": ROSTER})
        if path == "/studio/projects":
            return self._json(200, {"items": studio().store.list_projects()})
        m = re.fullmatch(r"/studio/projects/([^/]+)/state", path)
        if m:
            return self._json(200, _state(m.group(1)))
        m = re.fullmatch(r"/studio/artifacts/([^/]+)/svg", path)
        if m:
            for a in studio().store.artifacts(_project_of_artifact(m.group(1))):
                if a["id"] == m.group(1):
                    return self._text(200, a["payload"].get("svg", ""), "image/svg+xml; charset=utf-8")
            return self._json(404, {"error": "artifact not found"})
        return self._json(404, {"error": "not found"})

    # -------------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._body()
        m = re.fullmatch(r"/studio/projects/([^/]+)/run", path)
        if m:
            pid = m.group(1)
            cfg = Config.from_env()
            if not cfg.configured:
                return self._json(409, {"error": "未配置模型通道：RKD_AI_API_KEY 不在环境变量里",
                                        "hint": "密钥只放当前会话环境变量，不写入任何文件"})
            result = studio().run_a1(pid, background=True)
            return self._json(202, result)
        m = re.fullmatch(r"/studio/projects/([^/]+)/messages", path)
        if m:
            pid = m.group(1)
            text = (body.get("text") or "").strip()
            if not text:
                return self._json(400, {"error": "空消息"})
            studio().store.add_message(pid, "BOSS", "boss", text,
                                       evidence=[{"type": "boss"}])
            return self._json(201, {"ok": True})
        m = re.fullmatch(r"/studio/gates/([^/]+)/decide", path)
        if m:
            gid = m.group(1)
            decision = (body.get("decision") or "").strip()
            comment = (body.get("comment") or "").strip()
            if decision not in {"approve", "reject"}:
                return self._json(400, {"error": "decision 只能是 approve 或 reject"})
            if decision == "reject" and not comment:
                return self._json(400, {"error": "驳回必须写理由：这条理由会进规范库候选"})
            st = studio().store
            st.decide_gate(gid, decision, comment)
            gate = st.gate(gid)
            pid = gate["project_id"] if gate else None
            if pid:
                st.add_message(pid, "BOSS", "decision",
                               ("批准：" if decision == "approve" else "驳回：") + comment,
                               evidence=[{"type": "gate", "id": gid, "decision": decision}])
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()


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
                                  "author", "sha256", "status", "created_at")}
        if a["kind"] == "plan-sketch":
            item["svg_url"] = f"/studio/artifacts/{a['id']}/svg"
        else:
            item["payload"] = payload
        arts.append(item)
    state["artifacts"] = arts
    state["roster"] = ROSTER
    state["channel"] = {"configured": cfg.configured, "model": cfg.model,
                        "base_url": cfg.base_url,
                        "run_limit": cfg.run_token_limit, "project_limit": cfg.project_token_limit}
    state["running"] = project_id in studio()._running
    return state


def main(port: int = 8099) -> None:
    studio()  # seed + migrate before serving
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"status": "serving", "url": f"http://127.0.0.1:{port}/studio/health"},
                     ensure_ascii=False), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
