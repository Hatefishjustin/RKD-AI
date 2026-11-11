"""Studio store: the shared project desk every agent reads and writes.

A1 uses its own SQLite file under var/studio so the frozen production database
is untouched. Every message, artifact revision, review and gate is recorded.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "var" / "studio" / "studio.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  site_json TEXT NOT NULL,
  requirement_json TEXT NOT NULL,
  golden_ref TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  role TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  round INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  detail_json TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  task_id TEXT,
  role TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  evidence_json TEXT,
  tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  model TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  task_id TEXT,
  kind TEXT NOT NULL,
  option_id TEXT,
  revision INTEGER NOT NULL,
  parent_revision INTEGER,
  author TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  verdict TEXT NOT NULL,
  summary TEXT,
  issues_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gates (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  status TEXT NOT NULL,
  decision TEXT,
  comment TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  tokens_in INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  model TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_project ON messages(project_id, id);
CREATE INDEX IF NOT EXISTS idx_art_project ON artifacts(project_id, created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ---------------------------------------------------------------- projects
    def upsert_project(self, project_id: str, name: str, site: dict, requirement: dict,
                       golden_ref: str | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO projects(id,name,site_json,requirement_json,golden_ref,created_at)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, site_json=excluded.site_json,"
                " requirement_json=excluded.requirement_json, golden_ref=excluded.golden_ref",
                (project_id, name, json.dumps(site, ensure_ascii=False),
                 json.dumps(requirement, ensure_ascii=False), golden_ref, now()))

    def get_project(self, project_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "name": row["name"],
                "site": json.loads(row["site_json"]),
                "requirement": json.loads(row["requirement_json"]),
                "golden_ref": row["golden_ref"], "created_at": row["created_at"]}

    def list_projects(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id,name,created_at FROM projects ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------- tasks
    def create_task(self, project_id: str, role: str, title: str, round_no: int = 1,
                    detail: dict | None = None) -> str:
        tid = new_id("task")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO tasks(id,project_id,role,title,status,round,created_at,updated_at,detail_json)"
                      " VALUES(?,?,?,?,?,?,?,?,?)",
                      (tid, project_id, role, title, "assigned", round_no, now(), now(),
                       json.dumps(detail or {}, ensure_ascii=False)))
        return tid

    def update_task(self, task_id: str, status: str, detail: dict | None = None) -> None:
        with self._lock, self._conn() as c:
            if detail is None:
                c.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now(), task_id))
            else:
                c.execute("UPDATE tasks SET status=?, updated_at=?, detail_json=? WHERE id=?",
                          (status, now(), json.dumps(detail, ensure_ascii=False), task_id))

    # ---------------------------------------------------------------- messages
    def add_message(self, project_id: str, role: str, kind: str, body: str,
                    task_id: str | None = None, evidence: list[dict] | None = None,
                    tokens_in: int = 0, tokens_out: int = 0, model: str | None = None) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO messages(project_id,task_id,role,kind,body,evidence_json,tokens_in,tokens_out,model,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project_id, task_id, role, kind, body,
                 json.dumps(evidence or [], ensure_ascii=False), tokens_in, tokens_out, model, now()))
            return int(cur.lastrowid)

    def messages(self, project_id: str, limit: int = 400) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM messages WHERE project_id=? ORDER BY id LIMIT ?",
                             (project_id, limit)).fetchall()
        return [{"id": r["id"], "task_id": r["task_id"], "role": r["role"], "kind": r["kind"],
                 "body": r["body"], "evidence": json.loads(r["evidence_json"] or "[]"),
                 "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                 "model": r["model"], "created_at": r["created_at"]} for r in rows]

    # --------------------------------------------------------------- artifacts
    def save_artifact(self, project_id: str, kind: str, payload: dict, author: str,
                      option_id: str | None = None, revision: int = 1,
                      parent_revision: int | None = None, task_id: str | None = None,
                      status: str = "draft") -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        aid = new_id("art")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO artifacts(id,project_id,task_id,kind,option_id,revision,parent_revision,"
                      "author,payload_json,sha256,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, project_id, task_id, kind, option_id, revision, parent_revision, author,
                       raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), status, now()))
        return aid

    def artifacts(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at",
                             (project_id,)).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "option_id": r["option_id"], "revision": r["revision"],
                 "parent_revision": r["parent_revision"], "author": r["author"], "sha256": r["sha256"],
                 "status": r["status"], "created_at": r["created_at"],
                 "payload": json.loads(r["payload_json"])} for r in rows]

    def latest_artifact(self, project_id: str, option_id: str) -> dict | None:
        items = [a for a in self.artifacts(project_id) if a["option_id"] == option_id]
        return items[-1] if items else None

    # ----------------------------------------------------------------- reviews
    def save_review(self, project_id: str, artifact_id: str, reviewer: str, verdict: str,
                    summary: str, issues: list[dict]) -> str:
        rid = new_id("rev")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO reviews(id,project_id,artifact_id,reviewer,verdict,summary,issues_json,created_at)"
                      " VALUES(?,?,?,?,?,?,?,?)",
                      (rid, project_id, artifact_id, reviewer, verdict, summary,
                       json.dumps(issues, ensure_ascii=False), now()))
        return rid

    def reviews(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM reviews WHERE project_id=? ORDER BY created_at",
                             (project_id,)).fetchall()
        return [{"id": r["id"], "artifact_id": r["artifact_id"], "reviewer": r["reviewer"],
                 "verdict": r["verdict"], "summary": r["summary"],
                 "issues": json.loads(r["issues_json"] or "[]"), "created_at": r["created_at"]}
                for r in rows]

    # ------------------------------------------------------------------- gates
    def open_gate(self, project_id: str, title: str, detail: str) -> str:
        gid = new_id("gate")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO gates(id,project_id,title,detail,status,created_at) VALUES(?,?,?,?,?,?)",
                      (gid, project_id, title, detail, "waiting", now()))
        return gid

    def amend_gate(self, gate_id: str, extra: str, title: str | None = None) -> None:
        """Append a later round's findings to a gate the boss has NOT decided yet."""
        with self._lock, self._conn() as c:
            if title:
                c.execute("UPDATE gates SET title=?, detail=detail || ? WHERE id=? AND status='waiting'",
                          (title, "\n\n【后续轮次补充】" + extra, gate_id))
            else:
                c.execute("UPDATE gates SET detail=detail || ? WHERE id=? AND status='waiting'",
                          ("\n\n【后续轮次补充】" + extra, gate_id))

    def decide_gate(self, gate_id: str, decision: str, comment: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE gates SET status='decided', decision=?, comment=?, decided_at=? WHERE id=?",
                      (decision, comment, now(), gate_id))

    def gate(self, gate_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM gates WHERE id=?", (gate_id,)).fetchone()
        return dict(row) if row else None

    def gates(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM gates WHERE project_id=? ORDER BY created_at",
                             (project_id,)).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------- runs
    def start_run(self, project_id: str, model: str) -> str:
        rid = new_id("run")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO runs(id,project_id,status,started_at,model) VALUES(?,?,?,?,?)",
                      (rid, project_id, "running", now(), model))
        return rid

    def finish_run(self, run_id: str, status: str, tokens_in: int, tokens_out: int,
                   error: str | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE runs SET status=?,ended_at=?,tokens_in=?,tokens_out=?,error=? WHERE id=?",
                      (status, now(), tokens_in, tokens_out, error, run_id))

    def runs(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs WHERE project_id=? ORDER BY started_at",
                             (project_id,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------- state
    def project_state(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        msgs = self.messages(project_id)
        arts = self.artifacts(project_id)
        revs = self.reviews(project_id)
        gates = self.gates(project_id)
        runs = self.runs(project_id)
        # The runs table is the authoritative ledger. Message-level counters are
        # per-call diagnostics and must not be summed into a project total.
        usage = {"tokens_in": sum(r["tokens_in"] or 0 for r in runs),
                 "tokens_out": sum(r["tokens_out"] or 0 for r in runs)}
        usage["tokens_total"] = usage["tokens_in"] + usage["tokens_out"]
        return {"project": project, "messages": msgs, "artifacts": arts, "reviews": revs,
                "gates": gates, "runs": runs, "usage": usage}
