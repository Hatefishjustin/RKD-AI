"""Studio store: the shared project desk every agent reads and writes.

A1 uses its own SQLite file under var/studio so the frozen production database
is untouched. Every message, artifact revision, review and gate is recorded.

ARC-04 additions (additive columns + two small tables, no rewrite of history):
  * feedback        versioned boss messages / gate rejections that become the
                    effective requirement, instead of timeline-only text
  * gate_revisions  append-only decision records, so replay can never overwrite
  * artifacts       run_id / candidate_group_id / revision_uid /
                    parent_revision_uid / input_hash / check_report_id /
                    contract_status / diagnostics_json
  * gates           baseline_artifact_id / baseline_revision_uid / decision_scope
  * runs            input_hash / expected_feedback_revision / candidate_group_id
                    / cancel_requested / calls / image counts / cost_status
  * projects        source_project_id / mapping_note / seeded_at

`ensure_project` inserts only when absent: restarting the service never
rewrites an existing project's requirement or site facts.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
# Only a local file path (never a secret) may be overridden, for isolated tests.
# Default is the daily studio database; the override keeps daily data untouched.
DB_PATH = Path(os.environ.get("RKD_STUDIO_DB") or (ROOT / "var" / "studio" / "studio.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  site_json TEXT NOT NULL,
  requirement_json TEXT NOT NULL,
  golden_ref TEXT,
  created_at TEXT NOT NULL,
  source_project_id TEXT,
  mapping_note TEXT,
  seeded_at TEXT
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
  detail_json TEXT,
  run_id TEXT
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
  created_at TEXT NOT NULL,
  run_id TEXT,
  candidate_group_id TEXT,
  revision_uid TEXT,
  parent_revision_uid TEXT,
  input_hash TEXT,
  check_report_id TEXT,
  contract_status TEXT,
  diagnostics_json TEXT
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
  decided_at TEXT,
  baseline_artifact_id TEXT,
  baseline_revision_uid TEXT,
  decision_scope TEXT
);
CREATE TABLE IF NOT EXISTS gate_revisions (
  id TEXT PRIMARY KEY,
  gate_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  comment TEXT NOT NULL,
  decision_scope TEXT NOT NULL,
  baseline_artifact_id TEXT,
  baseline_revision_uid TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  revision_no INTEGER NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  source_message_id INTEGER,
  gate_id TEXT,
  baseline_artifact_id TEXT,
  baseline_revision_uid TEXT,
  status TEXT NOT NULL DEFAULT 'current',
  superseded_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, revision_no)
);
CREATE TABLE IF NOT EXISTS check_reports (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  artifact_id TEXT,
  run_id TEXT,
  report_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL
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
  error TEXT,
  input_hash TEXT,
  expected_feedback_revision INTEGER,
  candidate_group_id TEXT,
  cancel_requested INTEGER DEFAULT 0,
  calls INTEGER DEFAULT 0,
  images_sent INTEGER DEFAULT 0,
  images_generated INTEGER DEFAULT 0,
  cost_amount REAL,
  cost_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_project ON messages(project_id, id);
CREATE INDEX IF NOT EXISTS idx_art_project ON artifacts(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_project ON feedback(project_id, revision_no);
CREATE INDEX IF NOT EXISTS idx_gate_rev ON gate_revisions(gate_id, created_at);
"""

# additive columns for databases created by earlier versions
_MIGRATIONS: dict[str, dict[str, str]] = {
    "projects": {"source_project_id": "TEXT", "mapping_note": "TEXT", "seeded_at": "TEXT"},
    "tasks": {"run_id": "TEXT"},
    "artifacts": {
        "run_id": "TEXT", "candidate_group_id": "TEXT", "revision_uid": "TEXT",
        "parent_revision_uid": "TEXT", "input_hash": "TEXT", "check_report_id": "TEXT",
        "contract_status": "TEXT", "diagnostics_json": "TEXT",
    },
    "gates": {"baseline_artifact_id": "TEXT", "baseline_revision_uid": "TEXT",
              "decision_scope": "TEXT"},
    "runs": {
        "input_hash": "TEXT", "expected_feedback_revision": "INTEGER",
        "candidate_group_id": "TEXT", "cancel_requested": "INTEGER DEFAULT 0",
        "calls": "INTEGER DEFAULT 0", "images_sent": "INTEGER DEFAULT 0",
        "images_generated": "INTEGER DEFAULT 0", "cost_amount": "REAL", "cost_status": "TEXT",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def input_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate(c)

    def _migrate(self, c: sqlite3.Connection) -> None:
        for table, cols in _MIGRATIONS.items():
            existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, decl in cols.items():
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ---------------------------------------------------------------- projects
    def ensure_project(self, project_id: str, name: str, site: dict, requirement: dict,
                       golden_ref: str | None = None, source_project_id: str | None = None,
                       mapping_note: str | None = None) -> bool:
        """Seed only when absent. Returns True when a row was inserted.

        Restarting the service never rewrites an existing project's facts.
        """
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO projects(id,name,site_json,requirement_json,golden_ref,"
                "created_at,source_project_id,mapping_note,seeded_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (project_id, name, json.dumps(site, ensure_ascii=False),
                 json.dumps(requirement, ensure_ascii=False), golden_ref, now(),
                 source_project_id or project_id,
                 mapping_note or "本机 Studio 实验项目；显式映射到主系统项目 ID，未接入团队/NAS 服务",
                 now()))
            return cur.rowcount > 0

    def upsert_project(self, project_id: str, name: str, site: dict, requirement: dict,
                       golden_ref: str | None = None) -> None:
        """Explicit update only (kept for callers that really intend to write)."""
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO projects(id,name,site_json,requirement_json,golden_ref,created_at,"
                "source_project_id,mapping_note,seeded_at) VALUES(?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, site_json=excluded.site_json,"
                " requirement_json=excluded.requirement_json, golden_ref=excluded.golden_ref",
                (project_id, name, json.dumps(site, ensure_ascii=False),
                 json.dumps(requirement, ensure_ascii=False), golden_ref, now(),
                 project_id, "本机 Studio 实验项目；未接入团队/NAS 服务", now()))

    def get_project(self, project_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "name": row["name"],
                "site": json.loads(row["site_json"]),
                "requirement": json.loads(row["requirement_json"]),
                "golden_ref": row["golden_ref"], "created_at": row["created_at"],
                "source_project_id": row["source_project_id"],
                "mapping_note": row["mapping_note"], "seeded_at": row["seeded_at"]}

    def list_projects(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id,name,created_at,source_project_id,mapping_note FROM projects ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_project_id(self, pid: str) -> str | None:
        """Explicit mapping: accept either the studio id or the mapped main-system id.

        Returns the studio id, or None when the project is not explicitly mapped.
        NEVER falls back to another project's data.
        """
        with self._conn() as c:
            row = c.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone()
            if row:
                return row["id"]
            row = c.execute("SELECT id FROM projects WHERE source_project_id=?", (pid,)).fetchone()
            return row["id"] if row else None

    def project_mapping(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id,name,source_project_id,mapping_note FROM projects "
                             "ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- versioned feedback
    def feedback_revision(self, project_id: str) -> int:
        with self._conn() as c:
            row = c.execute("SELECT MAX(revision_no) AS m FROM feedback WHERE project_id=?",
                            (project_id,)).fetchone()
        return int(row["m"] or 0)

    def add_feedback(self, project_id: str, kind: str, text: str,
                     *, gate_id: str | None = None,
                     baseline_artifact_id: str | None = None,
                     baseline_revision_uid: str | None = None,
                     source_message_id: int | None = None) -> dict:
        """Versioned, immutable feedback. Returns {id, revision_no, input_hash}."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT MAX(revision_no) AS m FROM feedback WHERE project_id=?",
                            (project_id,)).fetchone()
            rev = int(row["m"] or 0) + 1
            fid = new_id("fb")
            ih = input_hash(project_id, kind, text, rev, baseline_artifact_id,
                            baseline_revision_uid)
            c.execute(
                "INSERT INTO feedback(id,project_id,revision_no,kind,text,input_hash,"
                "source_message_id,gate_id,baseline_artifact_id,baseline_revision_uid,"
                "status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'current',?)",
                (fid, project_id, rev, kind, text, ih, source_message_id, gate_id,
                 baseline_artifact_id, baseline_revision_uid, now()))
            return {"id": fid, "revision_no": rev, "input_hash": ih,
                    "baseline_artifact_id": baseline_artifact_id,
                    "baseline_revision_uid": baseline_revision_uid}

    def feedback(self, project_id: str, current_only: bool = True) -> list[dict]:
        with self._conn() as c:
            q = "SELECT * FROM feedback WHERE project_id=?"
            if current_only:
                q += " AND status='current'"
            rows = c.execute(q + " ORDER BY revision_no", (project_id,)).fetchall()
        return [dict(r) for r in rows]

    def effective_requirement(self, project_id: str) -> dict:
        """Original requirement + all current feedback, as the real design input."""
        p = self.get_project(project_id)
        if not p:
            raise KeyError(project_id)
        items = self.feedback(project_id)
        req = dict(p["requirement"])
        req["effective_addenda"] = [
            {"feedback_id": f["id"], "revision_no": f["revision_no"],
             "kind": f["kind"], "text": f["text"],
             "baseline_artifact_id": f["baseline_artifact_id"],
             "baseline_revision_uid": f["baseline_revision_uid"]}
            for f in items
        ]
        req["effective_input_hash"] = input_hash(req["text"], req["must_have"],
                                                  req["effective_addenda"])
        return req

    # ------------------------------------------------------------------- tasks
    def create_task(self, project_id: str, role: str, title: str, round_no: int = 1,
                    detail: dict | None = None, run_id: str | None = None) -> str:
        tid = new_id("task")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO tasks(id,project_id,role,title,status,round,created_at,"
                      "updated_at,detail_json,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (tid, project_id, role, title, "assigned", round_no, now(), now(),
                       json.dumps(detail or {}, ensure_ascii=False), run_id))
        return tid

    def update_task(self, task_id: str, status: str, detail: dict | None = None) -> None:
        with self._lock, self._conn() as c:
            if detail is None:
                c.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                          (status, now(), task_id))
            else:
                c.execute("UPDATE tasks SET status=?, updated_at=?, detail_json=? WHERE id=?",
                          (status, now(), json.dumps(detail, ensure_ascii=False), task_id))

    # ---------------------------------------------------------------- messages
    def add_message(self, project_id: str, role: str, kind: str, body: str,
                    task_id: str | None = None, evidence: list[dict] | None = None,
                    tokens_in: int = 0, tokens_out: int = 0, model: str | None = None) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO messages(project_id,task_id,role,kind,body,evidence_json,"
                "tokens_in,tokens_out,model,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project_id, task_id, role, kind, body,
                 json.dumps(evidence or [], ensure_ascii=False), tokens_in, tokens_out,
                 model, now()))
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
                      status: str = "draft", *, run_id: str | None = None,
                      candidate_group_id: str | None = None,
                      revision_uid: str | None = None,
                      parent_revision_uid: str | None = None,
                      input_hash_value: str | None = None,
                      check_report_id: str | None = None,
                      contract_status: str | None = None,
                      diagnostics: dict | None = None) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        aid = new_id("art")
        uid = revision_uid or new_id("revuid")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO artifacts(id,project_id,task_id,kind,option_id,revision,"
                      "parent_revision,author,payload_json,sha256,status,created_at,run_id,"
                      "candidate_group_id,revision_uid,parent_revision_uid,input_hash,"
                      "check_report_id,contract_status,diagnostics_json) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, project_id, task_id, kind, option_id, revision, parent_revision,
                       author, raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), status,
                       now(), run_id, candidate_group_id, uid, parent_revision_uid,
                       input_hash_value, check_report_id, contract_status,
                       json.dumps(diagnostics, ensure_ascii=False) if diagnostics else None))
        return aid

    def artifacts(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at, id",
                             (project_id,)).fetchall()
        keys = ("id", "kind", "option_id", "revision", "parent_revision", "author", "sha256",
                "status", "created_at", "run_id", "candidate_group_id", "revision_uid",
                "parent_revision_uid", "input_hash", "check_report_id", "contract_status")
        out = []
        for r in rows:
            item = {k: r[k] for k in keys}
            item["diagnostics"] = json.loads(r["diagnostics_json"]) if r["diagnostics_json"] else None
            item["payload"] = json.loads(r["payload_json"])
            out.append(item)
        return out

    def artifact_by_revision_uid(self, revision_uid: str) -> dict | None:
        for a in self.artifacts_for_uid_scan(revision_uid):
            if a["revision_uid"] == revision_uid:
                return a
        return None

    def artifacts_for_uid_scan(self, revision_uid: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT project_id FROM artifacts WHERE revision_uid=?",
                             (revision_uid,)).fetchall()
        result = []
        for r in rows:
            result.extend(self.artifacts(r["project_id"]))
        return result

    def latest_artifact(self, project_id: str, option_id: str) -> dict | None:
        items = [a for a in self.artifacts(project_id) if a["option_id"] == option_id]
        return items[-1] if items else None

    def invalidate_artifacts(self, run_id: str, status: str = "superseded") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE artifacts SET status=? WHERE run_id=? AND status NOT IN "
                            "('superseded','invalid_raw')", (status, run_id))
            return cur.rowcount

    # ----------------------------------------------------------- check reports
    def save_check_report(self, project_id: str, report: dict,
                          artifact_id: str | None = None,
                          run_id: str | None = None) -> str:
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)
        rid = new_id("chk")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO check_reports(id,project_id,artifact_id,run_id,report_json,"
                      "sha256,created_at) VALUES(?,?,?,?,?,?,?)",
                      (rid, project_id, artifact_id, run_id, raw,
                       hashlib.sha256(raw.encode("utf-8")).hexdigest(), now()))
        return rid

    def check_reports(self, project_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM check_reports WHERE project_id=? ORDER BY created_at",
                             (project_id,)).fetchall()
        return [{"id": r["id"], "artifact_id": r["artifact_id"], "run_id": r["run_id"],
                 "sha256": r["sha256"], "created_at": r["created_at"],
                 "report": json.loads(r["report_json"])} for r in rows]

    # ----------------------------------------------------------------- reviews
    def save_review(self, project_id: str, artifact_id: str, reviewer: str, verdict: str,
                    summary: str, issues: list[dict]) -> str:
        rid = new_id("rev")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO reviews(id,project_id,artifact_id,reviewer,verdict,summary,"
                      "issues_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
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
    def open_gate(self, project_id: str, title: str, detail: str, *,
                  baseline_artifact_id: str | None = None,
                  baseline_revision_uid: str | None = None,
                  decision_scope: str = "allow_continue") -> str:
        gid = new_id("gate")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO gates(id,project_id,title,detail,status,created_at,"
                      "baseline_artifact_id,baseline_revision_uid,decision_scope) "
                      "VALUES(?,?,?,?,'waiting',?,?,?,?)",
                      (gid, project_id, title, detail, now(), baseline_artifact_id,
                       baseline_revision_uid, decision_scope))
        return gid

    def amend_gate(self, gate_id: str, extra: str, title: str | None = None) -> None:
        """Append a later round's findings to a gate the boss has NOT decided yet."""
        with self._lock, self._conn() as c:
            if title:
                c.execute("UPDATE gates SET title=?, detail=detail || ? "
                          "WHERE id=? AND status='waiting'",
                          (title, "\n\n【后续轮次补充】" + extra, gate_id))
            else:
                c.execute("UPDATE gates SET detail=detail || ? WHERE id=? AND status='waiting'",
                          ("\n\n【后续轮次补充】" + extra, gate_id))

    def decide_gate(self, gate_id: str, decision: str, comment: str,
                    decision_scope: str = "allow_continue") -> dict:
        """Append-only decision. Replay CANNOT overwrite a decided record.

        Returns {applied, reason, revision_id, decision_scope}. A later change of
        mind is expressed as a NEW gate_revisions row, never by rewriting history.
        """
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM gates WHERE id=?", (gate_id,)).fetchone()
            if not row:
                return {"applied": False, "reason": "gate_not_found", "revision_id": None}
            rid = new_id("gdec")
            c.execute("INSERT INTO gate_revisions(id,gate_id,project_id,decision,comment,"
                      "decision_scope,baseline_artifact_id,baseline_revision_uid,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (rid, gate_id, row["project_id"], decision, comment, decision_scope,
                       row["baseline_artifact_id"], row["baseline_revision_uid"], now()))
            if row["status"] == "decided":
                # correction = new record + visible note; original stays intact
                c.execute("UPDATE gates SET detail=detail || ? WHERE id=?",
                          ("\n\n【决定修正（原决定保留）】" + f"{decision}：{comment}", gate_id))
                return {"applied": False, "reason": "already_decided_correction_recorded",
                        "revision_id": rid, "decision_scope": decision_scope}
            cur = c.execute("UPDATE gates SET status='decided', decision=?, comment=?, "
                            "decided_at=?, decision_scope=? WHERE id=? AND status='waiting'",
                            (decision, comment, now(), decision_scope, gate_id))
            return {"applied": cur.rowcount > 0,
                    "reason": "decided" if cur.rowcount else "not_waiting",
                    "revision_id": rid, "decision_scope": decision_scope}

    def gate_decisions(self, gate_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM gate_revisions WHERE gate_id=? ORDER BY created_at, id",
                             (gate_id,)).fetchall()
        return [dict(r) for r in rows]

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
    def start_run(self, project_id: str, model: str, *, input_hash_value: str | None = None,
                  expected_feedback_revision: int | None = None,
                  candidate_group_id: str | None = None) -> str:
        rid = new_id("run")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO runs(id,project_id,status,started_at,model,input_hash,"
                      "expected_feedback_revision,candidate_group_id) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, project_id, "running", now(), model, input_hash_value,
                       expected_feedback_revision, candidate_group_id))
        return rid

    def request_cancel(self, run_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))

    def is_cancelled(self, run_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT cancel_requested FROM runs WHERE id=?", (run_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def feedback_changed_since(self, project_id: str, expected: int | None) -> bool:
        return expected is not None and self.feedback_revision(project_id) != expected

    def finish_run(self, run_id: str, status: str, tokens_in: int, tokens_out: int,
                   error: str | None = None, *, calls: int | None = None,
                   images_sent: int | None = None, images_generated: int | None = None,
                   cost_amount: float | None = None, cost_status: str | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE runs SET status=?,ended_at=?,tokens_in=?,tokens_out=?,error=?,"
                      "calls=COALESCE(?,calls),images_sent=COALESCE(?,images_sent),"
                      "images_generated=COALESCE(?,images_generated),"
                      "cost_amount=?,cost_status=? WHERE id=?",
                      (status, now(), tokens_in, tokens_out, error, calls, images_sent,
                       images_generated, cost_amount, cost_status, run_id))

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
        usage = {"tokens_in": sum(r["tokens_in"] or 0 for r in runs),
                 "tokens_out": sum(r["tokens_out"] or 0 for r in runs)}
        usage["tokens_total"] = usage["tokens_in"] + usage["tokens_out"]
        return {"project": project, "messages": msgs, "artifacts": arts, "reviews": revs,
                "gates": gates, "runs": runs, "usage": usage,
                "feedback": self.feedback(project_id),
                "feedback_revision": self.feedback_revision(project_id),
                "effective_requirement": self.effective_requirement(project_id),
                "check_reports": self.check_reports(project_id)}
