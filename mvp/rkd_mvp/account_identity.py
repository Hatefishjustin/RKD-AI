"""Local account pilot. No external publication authority or network deployment.

Passwords and sessions are never stored in plaintext. Every request rechecks
account activity and project membership, including file and artifact downloads.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .api_service import ApiError
from .identity import RequestIdentity, LocalIdentityProvider
from .account_repository import SQLiteAccountRepository
from .models import new_id, now_iso


COOKIE_NAME = "rkd_session"
SESSION_SECONDS = 8 * 60 * 60
IDLE_SECONDS = 30 * 60
PASSWORD_ITERATIONS = 600_000


class AccountGuardedLocalIdentityProvider(LocalIdentityProvider):
    """Fail closed if a trusted operator enables accounts in a running pilot."""
    def __init__(self, accounts):
        self.accounts = accounts

    def check_mode(self):
        if self.accounts.has_users():
            raise ApiError(401, "ACCOUNT_MODE_REQUIRED", "账号已启用，请重启服务并登录")

    def authenticate(self, headers):
        self.check_mode()
        return super().authenticate(headers)


class AccountIdentityProvider:
    mode = "accounts"

    def __init__(self, db_path: str | Path | None, *, repository=None):
        self.db_path = Path(db_path) if db_path is not None else None
        if repository is None and self.db_path is None:
            raise ValueError("account storage required")
        self.repository = repository or SQLiteAccountRepository(self._db)
        self._dummy_hash = self._hash_password(secrets.token_urlsafe(24))

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _hash_password(password: str) -> str:
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ApiError(400, "INVALID_PASSWORD", "密码需要 8–128 个字符，可使用长句")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
        return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        if not isinstance(password, str) or len(password) > 128:
            return False
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _public(row):
        return {key: row[key] for key in ("user_id", "username", "display_name", "organization_id", "is_admin", "active")}

    @staticmethod
    def _audit(db, actor, org, action, target, details=None, project=None):
        db.query('audit',
                   (new_id("auth-audit"), actor, org, project, action, target,
                    json.dumps(details or {}, ensure_ascii=True), now_iso()))

    def has_users(self):
        with self.repository.transaction() as db:
            return db.query('has_users').fetchone() is not None

    def bootstrap(self, username: str, display_name: str, password: str, organization_id="org-local"):
        """Trusted local CLI only; there is deliberately no HTTP bootstrap endpoint."""
        return self._create_user(None, username, display_name, password, organization_id)

    def _create_user(self, actor, username, display_name, password, organization_id):
        username = str(username).strip().lower()
        display_name = str(display_name).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username) or not 1 <= len(display_name) <= 100:
            raise ApiError(400, "INVALID_ACCOUNT", "账号需 3–64 位字母、数字或 ._-；姓名需 1–100 字")
        encoded = self._hash_password(password)
        with self.repository.transaction(write=True) as db:
            if actor is None:
                if db.query('has_users').fetchone():
                    raise ApiError(409, "ALREADY_INITIALIZED", "管理员已初始化，请登录后管理账号")
            else:
                self._require_admin(db, actor)
            if db.query('username_exists', (username,)).fetchone():
                raise ApiError(409, "ACCOUNT_EXISTS", "该账号已存在")
            user_id = new_id("user")
            db.query('insert_user',
                       (user_id, organization_id, username, display_name, encoded, int(actor is None), now_iso()))
            self._audit(db, actor.actor_id if actor else user_id, organization_id, "account.created", user_id,
                        {"bootstrap": actor is None})
            return self._public(db.query('user', (user_id,)).fetchone())

    def create_user(self, actor, body):
        with self.repository.transaction() as db:
            self._require_admin(db, actor)
        return self._create_user(actor, body.get("username", ""), body.get("display_name", ""),
                                 body.get("password", ""), actor.organization_id)

    @staticmethod
    def _require_admin(db, actor):
        row = db.query('admin',
                         (actor.actor_id, actor.organization_id)).fetchone()
        if not row or not row["active"] or not row["is_admin"]:
            raise ApiError(403, "FORBIDDEN", "此操作需要账号管理员")

    def login(self, username, password, remote_address):
        username = str(username).strip().lower()[:128]
        now = time.time()
        buckets = [("account:" + hashlib.sha256(username.encode()).hexdigest(), 5),
                   ("client:" + remote_address, 30)]
        failure = None
        result = None
        with self.repository.transaction(write=True) as db:
            # Reserve the attempt before checking the password; concurrent failures
            # cannot all pass the limit check. Failure counters must commit.
            db.query('expire_limits', (now - 900,))
            for bucket, limit in buckets:
                row = db.query('limit', (bucket,)).fetchone()
                if row and row["failures"] >= limit:
                    raise ApiError(429, "LOGIN_RATE_LIMITED", "登录尝试过多，请 15 分钟后重试")
            user = db.query('username', (username,)).fetchone()
            valid = self._verify_password(password, user["password_hash"] if user else self._dummy_hash)
            if not user or not valid or not user["active"]:
                for bucket, _ in buckets:
                    db.query('increment_limit', (bucket, now))
                self._audit(db, "anonymous", db.organization_id or "unknown", "login.failed", buckets[0][0])
                failure = ApiError(401, "INVALID_CREDENTIALS", "账号或密码不正确，或账号已停用")
            else:
                db.query('clear_limit', (buckets[0][0],))
                db.query('expire_sessions', (now, now - IDLE_SECONDS))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.query('insert_session',
                           (hashlib.sha256(token.encode()).hexdigest(), user["user_id"], csrf, now, now + SESSION_SECONDS, now))
                self._audit(db, user["user_id"], user["organization_id"], "login.succeeded", user["user_id"])
                result = (token, {"mode": self.mode, "user": self._public(user), "csrf_token": csrf})
        if failure:
            raise failure
        return result

    @staticmethod
    def _token_hash(headers):
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("Cookie", ""))
        except CookieError:
            raise ApiError(401, "UNAUTHORIZED", "请登录") from None
        token = cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ApiError(401, "UNAUTHORIZED", "请登录")
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, headers):
        token_hash = self._token_hash(headers)
        now = time.time()
        with self.repository.transaction() as db:
            row = db.query('session_identity',
                             (token_hash, now, now - IDLE_SECONDS)).fetchone()
            if not row:
                raise ApiError(401, "UNAUTHORIZED", "登录已失效，请重新登录")
            db.query('touch_session', (now, token_hash))
            return RequestIdentity(row["organization_id"], row["user_id"], "human", bool(row["is_admin"]), row["csrf_token"])

    def session(self, identity):
        with self.repository.transaction() as db:
            row = db.query('user', (identity.actor_id,)).fetchone()
            return {"mode": self.mode, "user": self._public(row), "csrf_token": identity.csrf_token}

    def logout(self, headers, identity):
        with self.repository.transaction(write=True) as db:
            db.query('delete_session', (self._token_hash(headers),))
            self._audit(db, identity.actor_id, identity.organization_id, "logout", identity.actor_id)

    def authorize(self, identity, path, method):
        """Default-deny all project writes; viewers only read, managers accept."""
        match = re.match(r"^/api/v1/projects/([^/]+)(?:/|$)", path)
        if not match:
            if path == "/api/v1/projects" and method != "GET" and not identity.is_admin:
                raise ApiError(403, "FORBIDDEN", "只有管理员可以创建项目")
            return
        project_id = match.group(1)
        with self.repository.transaction(project_id=project_id) as db:
            if not db.query('project', (identity.organization_id, project_id)).fetchone():
                raise ApiError(404, "NOT_FOUND", "项目不存在或未授权")
            row = db.query('member',
                             (identity.organization_id, project_id, identity.actor_id)).fetchone()
        role = "manager" if identity.is_admin else row["role"] if row else None
        if role is None:
            raise ApiError(404, "NOT_FOUND", "项目不存在或未授权")
        if method != "GET":
            if role == "viewer" and not re.fullmatch(r'/api/v1/projects/[^/]+/review-tasks/[^/]+',path):
                raise ApiError(403, "READ_ONLY", "你在此项目中只有查看权限")
            if (path.endswith("/members") or path.endswith("/acceptance") or path.endswith("/reproduce") or path == f"/api/v1/projects/{project_id}") and role != "manager":
                raise ApiError(403, "MANAGER_REQUIRED", "此操作需要项目负责人")
            if path.endswith("/commands"):
                raise ApiError(403, "FORMAL_RELEASE_DISABLED", "账号试用阶段未开放旧模拟命令、正式发布、下单或付款")

    def filter_projects(self, identity, result):
        with self.repository.transaction() as db:
            roles = {row["project_id"]: row["role"] for row in db.query('roles', (identity.organization_id, identity.actor_id))}
        return {**result, "items": [{**item, "role": "manager" if identity.is_admin else roles[item["project_id"]]} for item in result["items"] if identity.is_admin or item["project_id"] in roles]}

    def list_users(self, identity):
        with self.repository.transaction() as db:
            self._require_admin(db, identity)
            return {"items": [self._public(row) for row in db.query('users', (identity.organization_id,))]}

    REVIEW_POSITIONS = {'design_reviewer': '设计/图纸审核', 'commercial_reviewer': '报价/税务核验'}

    def review_positions(self, identity):
        with self.repository.transaction() as db:
            self._require_admin(db, identity)
            saved = {row['position_key']:dict(row) for row in db.query('review_positions', (identity.organization_id,))}
            items=[]
            for key, name in self.REVIEW_POSITIONS.items():
                item=saved.get(key, {'position_key':key,'name':name,'active':True,'version':0})
                item['user_ids']=[row['user_id'] for row in db.query('review_position_members',(identity.organization_id,key))]
                item.pop('organization_id',None)
                items.append(item)
            return {'items':items, 'grants_formal_signature':False}

    def save_review_position(self, identity, key, body):
        if key not in self.REVIEW_POSITIONS:
            raise ApiError(404,'NOT_FOUND','岗位不存在')
        name=body.get('name'); active=body.get('active'); users=body.get('user_ids')
        if not isinstance(name,str) or not 1<=len(name.strip())<=100 or not isinstance(active,bool) or not isinstance(users,list) or len(users)>100 or any(not isinstance(u,str) for u in users) or len(set(users))!=len(users):
            raise ApiError(400,'INVALID_POSITION','岗位名称、状态或成员格式无效')
        with self.repository.transaction(write=True) as db:
            self._require_admin(db,identity)
            saved={r['position_key']:r for r in db.query('review_positions',(identity.organization_id,))}
            version=saved[key]['version'] if key in saved else 0
            if type(body.get('expected_version')) is not int or body['expected_version']!=version:
                raise ApiError(409,'STALE_POSITION','岗位已被修改，请刷新后重试')
            for user in users:
                row=db.query('scoped_user',(identity.organization_id,user)).fetchone()
                if not row or not row['active']:
                    raise ApiError(400,'INVALID_POSITION_MEMBER','只能分配本组织的有效账号')
            db.query('save_review_position',(identity.organization_id,key,name.strip(),active,version+1))
            db.query('clear_review_position_members',(identity.organization_id,key))
            for user in users: db.query('add_review_position_member',(identity.organization_id,key,user))
            self._audit(db,identity.actor_id,identity.organization_id,'review_position.updated',key,{'name':name.strip(),'active':active,'user_ids':users,'version':version+1})
        return self.review_positions(identity)

    def update_user(self, identity, user_id, body):
        if not isinstance(body.get("active"), bool):
            raise ApiError(400, "INVALID_ACCOUNT", "active 必须是布尔值")
        with self.repository.transaction(write=True) as db:
            self._require_admin(db, identity)
            row = db.query('scoped_user', (identity.organization_id, user_id)).fetchone()
            if not row:
                raise ApiError(404, "NOT_FOUND", "账号不存在")
            if row["is_admin"]:
                raise ApiError(403, "ADMIN_PROTECTED", "不能从此入口停用管理员")
            db.query('set_active', (int(body["active"]), user_id))
            db.query('delete_user_sessions', (user_id,))
            self._audit(db, identity.actor_id, identity.organization_id, "account.active_changed", user_id, {"active": body["active"]})
        return {"user_id": user_id, "active": body["active"]}

    def list_members(self, identity, project):
        with self.repository.transaction(project_id=project) as db:
            return {"items": [dict(row) for row in db.query('members', (identity.organization_id, project))]}

    def set_member(self, identity, project, body):
        # Account administrators manage assignment; project managers manage work.
        # This also prevents a manager from silently elevating other accounts.
        user_id, role = body.get("user_id"), body.get("role")
        if role not in {"manager", "editor", "viewer", "none"}:
            raise ApiError(400, "INVALID_ROLE", "项目角色不支持")
        with self.repository.transaction(project_id=project, write=True) as db:
            self._require_admin(db, identity)
            if not db.query('active_user', (user_id, identity.organization_id)).fetchone():
                raise ApiError(404, "NOT_FOUND", "账号不存在或已停用")
            if role == "none":
                db.query('delete_member', (identity.organization_id, project, user_id))
            else:
                db.query('set_member', (identity.organization_id, project, user_id, role, now_iso()))
            self._audit(db, identity.actor_id, identity.organization_id, "membership.changed", user_id, {"role": role}, project)
        return {"user_id": user_id, "role": role}
