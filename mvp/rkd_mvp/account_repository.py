"""Explicit account storage boundaries. SQL is selected by operation, never translated at runtime."""
from contextlib import contextmanager
import json

from .api_service import ApiError
from .file_repository import mapping
from .models import TenantContext

SQLITE_QUERIES = {
    'review_checklists': 'SELECT * FROM review_checklists WHERE organization_id=? AND project_id=?',
    'insert_review_checklist': 'INSERT INTO review_checklists VALUES (?,?,?,?)',
    'review_tasks': 'SELECT * FROM review_tasks WHERE organization_id=? AND project_id=? ORDER BY created_at,task_id',
    'insert_review_task': 'INSERT INTO review_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
    'finish_review_task': 'UPDATE review_tasks SET status=?,reviewer_id=?,note=?,updated_at=?,version=version+1 WHERE organization_id=? AND project_id=? AND task_id=? AND version=?',
    'review_positions': 'SELECT * FROM review_positions WHERE organization_id=? ORDER BY position_key',
    'review_position_members': 'SELECT user_id FROM review_position_members WHERE organization_id=? AND position_key=? ORDER BY user_id',
    'save_review_position': 'INSERT INTO review_positions VALUES (?,?,?,?,?) ON CONFLICT(organization_id,position_key) DO UPDATE SET name=excluded.name,active=excluded.active,version=excluded.version',
    'clear_review_position_members': 'DELETE FROM review_position_members WHERE organization_id=? AND position_key=?',
    'add_review_position_member': 'INSERT INTO review_position_members VALUES (?,?,?)',
    'audit': 'INSERT INTO auth_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
    'insert_user': 'INSERT INTO auth_users VALUES (?, ?, ?, ?, ?, ?, 1, ?)',
    'expire_limits': 'DELETE FROM auth_login_limits WHERE window_started_at < ?',
    'touch_session': 'UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?',
    'delete_session': 'DELETE FROM auth_sessions WHERE token_hash = ?',
    'set_active': 'UPDATE auth_users SET active = ? WHERE user_id = ?',
    'delete_user_sessions': 'DELETE FROM auth_sessions WHERE user_id = ?',
    'admin': 'SELECT is_admin, active FROM auth_users WHERE user_id = ? AND organization_id = ?',
    'clear_limit': 'DELETE FROM auth_login_limits WHERE bucket = ?',
    'expire_sessions': 'DELETE FROM auth_sessions WHERE expires_at <= ? OR last_seen_at <= ?',
    'insert_session': 'INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?)',
    'delete_member': 'DELETE FROM auth_memberships WHERE organization_id = ? AND project_id = ? AND user_id = ?',
    'set_member': 'INSERT INTO auth_memberships VALUES (?, ?, ?, ?, ?) ON CONFLICT(organization_id, project_id, user_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at',
    'username_exists': 'SELECT 1 FROM auth_users WHERE username = ?',
    'username': 'SELECT * FROM auth_users WHERE username = ?',
    'increment_limit': 'INSERT INTO auth_login_limits VALUES (?, 1, ?) ON CONFLICT(bucket) DO UPDATE SET failures = failures + 1',
    'session_identity': 'SELECT u.*, s.csrf_token FROM auth_sessions s JOIN auth_users u ON u.user_id = s.user_id WHERE token_hash = ? AND expires_at > ? AND last_seen_at > ? AND active = 1',
    'user': 'SELECT * FROM auth_users WHERE user_id = ?',
    'member': 'SELECT role FROM auth_memberships WHERE organization_id = ? AND project_id = ? AND user_id = ?',
    'roles': 'SELECT project_id, role FROM auth_memberships WHERE organization_id = ? AND user_id = ?',
    'scoped_user': 'SELECT * FROM auth_users WHERE organization_id = ? AND user_id = ?',
    'has_users': 'SELECT 1 FROM auth_users LIMIT 1',
    'limit': 'SELECT failures FROM auth_login_limits WHERE bucket = ?',
    'project': 'SELECT 1 FROM projects WHERE organization_id = ? AND project_id = ?',
    'users': 'SELECT * FROM auth_users WHERE organization_id = ? ORDER BY username',
    'members': 'SELECT m.user_id, u.username, u.display_name, u.active, m.role FROM auth_memberships m JOIN auth_users u ON u.user_id = m.user_id WHERE m.organization_id = ? AND m.project_id = ? ORDER BY u.username',
    'active_user': 'SELECT 1 FROM auth_users WHERE user_id = ? AND organization_id = ? AND active = 1',
}

POSTGRES_QUERIES = {
    'review_checklists': 'SELECT * FROM rkd.review_checklist WHERE organization_id=%s AND project_id=%s',
    'insert_review_checklist': 'INSERT INTO rkd.review_checklist VALUES (%s,%s,%s,%s)',
    'review_tasks': 'SELECT * FROM rkd.review_task WHERE organization_id=%s AND project_id=%s ORDER BY created_at,task_id',
    'insert_review_task': 'INSERT INTO rkd.review_task VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
    'finish_review_task': 'UPDATE rkd.review_task SET status=%s,reviewer_id=%s,note=%s,updated_at=%s,version=version+1 WHERE organization_id=%s AND project_id=%s AND task_id=%s AND version=%s',
    'review_positions': 'SELECT * FROM rkd.review_position WHERE organization_id=%s ORDER BY position_key',
    'review_position_members': 'SELECT user_id FROM rkd.review_position_member WHERE organization_id=%s AND position_key=%s ORDER BY user_id',
    'save_review_position': 'INSERT INTO rkd.review_position VALUES (%s,%s,%s,%s,%s) ON CONFLICT(organization_id,position_key) DO UPDATE SET name=excluded.name,active=excluded.active,version=excluded.version',
    'clear_review_position_members': 'DELETE FROM rkd.review_position_member WHERE organization_id=%s AND position_key=%s',
    'add_review_position_member': 'INSERT INTO rkd.review_position_member VALUES (%s,%s,%s)',
    'audit': 'INSERT INTO rkd.auth_audit VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)',
    'insert_user': 'INSERT INTO rkd.auth_user VALUES (%s, %s, %s, %s, %s, %s, true, %s)',
    'expire_limits': 'DELETE FROM rkd.auth_login_throttle WHERE organization_id=%s AND window_started_at < to_timestamp(%s)',
    'touch_session': 'UPDATE rkd.auth_session SET last_seen_at = to_timestamp(%s) WHERE token_hash = %s',
    'delete_session': 'DELETE FROM rkd.auth_session WHERE token_hash = %s',
    'set_active': 'UPDATE rkd.auth_user SET active = %s WHERE user_id = %s',
    'delete_user_sessions': 'DELETE FROM rkd.auth_session WHERE user_id = %s',
    'admin': 'SELECT is_admin, active FROM rkd.auth_user WHERE user_id = %s AND organization_id = %s',
    'clear_limit': 'DELETE FROM rkd.auth_login_throttle WHERE organization_id=%s AND bucket=%s',
    'expire_sessions': 'DELETE FROM rkd.auth_session WHERE expires_at <= to_timestamp(%s) OR last_seen_at <= to_timestamp(%s)',
    'insert_session': 'INSERT INTO rkd.auth_session VALUES (%s, %s, %s, to_timestamp(%s), to_timestamp(%s), to_timestamp(%s))',
    'delete_member': 'DELETE FROM rkd.auth_membership WHERE organization_id = %s AND project_id = %s AND user_id = %s',
    'set_member': 'INSERT INTO rkd.auth_membership VALUES (%s, %s, %s, %s, %s) ON CONFLICT(organization_id, project_id, user_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at',
    'username_exists': 'SELECT 1 FROM rkd.auth_user WHERE username = %s',
    'username': 'SELECT * FROM rkd.auth_user WHERE username = %s',
    'increment_limit': 'INSERT INTO rkd.auth_login_throttle VALUES (%s, %s, 1, to_timestamp(%s)) ON CONFLICT(organization_id,bucket) DO UPDATE SET failures = auth_login_throttle.failures + 1',
    'session_identity': 'SELECT u.*, s.csrf_token FROM rkd.auth_session s JOIN rkd.auth_user u ON u.user_id = s.user_id WHERE token_hash = %s AND expires_at > to_timestamp(%s) AND last_seen_at > to_timestamp(%s) AND active = true',
    'user': 'SELECT * FROM rkd.auth_user WHERE user_id = %s',
    'member': 'SELECT role FROM rkd.auth_membership WHERE organization_id = %s AND project_id = %s AND user_id = %s',
    'roles': 'SELECT * FROM rkd.list_account_project_roles(%s)',
    'scoped_user': 'SELECT * FROM rkd.auth_user WHERE organization_id = %s AND user_id = %s',
    'has_users': 'SELECT 1 FROM rkd.auth_user LIMIT 1',
    'limit': 'SELECT failures FROM rkd.auth_login_throttle WHERE organization_id=%s AND bucket=%s',
    'project': 'SELECT 1 FROM rkd.project WHERE organization_id = %s AND project_id = %s',
    'users': 'SELECT * FROM rkd.auth_user WHERE organization_id = %s ORDER BY username',
    'members': 'SELECT m.user_id, u.username, u.display_name, u.active, m.role FROM rkd.auth_membership m JOIN rkd.auth_user u ON u.user_id = m.user_id WHERE m.organization_id = %s AND m.project_id = %s ORDER BY u.username',
    'active_user': 'SELECT 1 FROM rkd.auth_user WHERE user_id = %s AND organization_id = %s AND active = true',
}


class AccountRows:
    def __init__(self, cursor):
        self.items = mapping(cursor) if cursor.description else []

    def fetchone(self):
        return self.items[0] if self.items else None

    def __iter__(self):
        return iter(self.items)


class SQLiteAccountTransaction:
    organization_id = None

    def __init__(self, db):
        self.db = db

    def query(self, operation, params=()):
        return self.db.execute(SQLITE_QUERIES[operation], params)


class SQLiteAccountRepository:
    def __init__(self, context):
        self.context = context

    @contextmanager
    def transaction(self, *, project_id="account-service", write=False):
        with self.context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteAccountTransaction(db)


class PostgresAccountTransaction:
    def __init__(self, db, organization_id):
        self.db, self.organization_id = db, organization_id

    def query(self, operation, params=()):
        from psycopg.errors import UniqueViolation
        if operation in {"expire_limits", "limit", "increment_limit", "clear_limit"}:
            params = (self.organization_id, *params)
        elif operation == "roles":
            if params[0] != self.organization_id:
                raise ApiError(403, "FORBIDDEN", "账号组织不匹配")
            params = (params[1],)
        elif operation == "insert_user":
            params = (*params[:5], bool(params[5]), params[6])
        elif operation == "set_active":
            params = (bool(params[0]), params[1])
        try:
            return AccountRows(self.db.execute(POSTGRES_QUERIES[operation], params))
        except UniqueViolation as error:
            if operation == "insert_user":
                raise ApiError(409, "ACCOUNT_EXISTS", "该账号已存在") from error
            raise


class PostgresAccountRepository:
    def __init__(self, store, organization_id="org-local"):
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise ValueError("trusted deployment organization required")
        self.store, self.organization_id = store, organization_id

    @contextmanager
    def transaction(self, *, project_id="account-service", write=False):
        org = self.organization_id
        with self.store.tenant_transaction(TenantContext(org, project_id, "account-service")) as db:
            if write:
                # Serialize account changes and failed login reservations within
                # one deployment organization, across processes and connections.
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (json.dumps([org,"account-write"]),))
                db.execute("INSERT INTO rkd.organization(organization_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (org,org))
            yield PostgresAccountTransaction(db, org)
