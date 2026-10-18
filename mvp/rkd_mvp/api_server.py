from __future__ import annotations

import json
import hashlib
import hmac
import mimetypes
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from .api_service import ApiError, ApiService
from .identity import DevHeaderIdentityProvider, IdentityProvider, LocalIdentityProvider
from .account_identity import AccountIdentityProvider, COOKIE_NAME, SESSION_SECONDS


class ApiHandler(BaseHTTPRequestHandler):
    service: ApiService
    identity_provider: IdentityProvider
    static_dir: Path | None = None
    download_secret: bytes

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            close_thread_connection = getattr(self.service.app.store, "close_thread_connection", None)
            if close_thread_connection:
                close_thread_connection()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    @property
    def accounts(self) -> AccountIdentityProvider | None:
        return self.identity_provider if isinstance(self.identity_provider, AccountIdentityProvider) else None

    def _guard(self) -> None:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "").lower()
        if host not in allowed:
            raise ApiError(403, "INVALID_HOST", "仅允许本机回环地址")
        if self.command != "GET":
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                raise ApiError(403, "INVALID_ORIGIN", "请从工作台页面提交操作")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise ApiError(403, "INVALID_ORIGIN", "拒绝跨站写入")
        self.connection.settimeout(30)

    def _json(self, status: int, body: dict[str, Any], cookie: str | None = None) -> None:
        data = json.dumps(body, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, error: ApiError) -> None:
        self._json(error.status, {"error_code": error.code, "message": error.message, "request_id": self.headers.get("X-Request-Id", "local-request"), "retryable": error.retryable})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 1024 * 1024:
            raise ApiError(413, "BODY_TOO_LARGE", "请求内容超出 1 MiB 限制")
        if self.accounts and self.headers.get_content_type() != "application/json":
            raise ApiError(415, "JSON_REQUIRED", "此接口需要 JSON 请求")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ApiError(400, "INVALID_JSON", "request body must be an object")
        return value

    def _identity(self) -> tuple[str, str]:
        identity = self.identity_provider.authenticate(self.headers)
        if isinstance(self.identity_provider, LocalIdentityProvider) and urlsplit(self.path).path.endswith("/commands"):
            raise ApiError(403, "FORMAL_RELEASE_DISABLED", "本地试用未开放旧模拟命令或正式发布")
        if self.accounts:
            if self.command != "GET" and not hmac.compare_digest(identity.csrf_token.encode(), self.headers.get("X-CSRF-Token", "").encode()):
                raise ApiError(403, "CSRF_FAILED", "登录校验已变化，请刷新页面后重试")
            self.accounts.authorize(identity, urlsplit(self.path).path, self.command)
        self.authenticated_identity = identity
        return identity.organization_id, identity.actor_id

    def _static(self, path: str) -> bool:
        """Serve the built workbench without allowing traversal outside dist/."""
        if self.static_dir is None or path.startswith("/api/"):
            return False
        relative = unquote(path.lstrip("/")) or "index.html"
        candidate = (self.static_dir / relative).resolve()
        try:
            candidate.relative_to(self.static_dir.resolve())
        except ValueError:
            raise ApiError(404, "NOT_FOUND", "route not found")
        if not candidate.is_file():
            if "." in Path(relative).name:
                raise ApiError(404, "NOT_FOUND", "route not found")
            candidate = (self.static_dir / "index.html").resolve()
        if not candidate.is_file():
            raise ApiError(404, "NOT_FOUND", "frontend build not found")
        data = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def _file(self, organization_id: str, project_id: str, file_id: str) -> None:
        metadata, path = self.service.get_file_content(organization_id, project_id, file_id)
        preview = urlsplit(self.path).query == "preview=1"
        inline = preview and (metadata["content_type"] == "application/pdf" or metadata["content_type"].startswith("image/"))
        self.send_response(200)
        self.send_header("Content-Type", metadata["content_type"])
        self.send_header("Content-Length", str(metadata["size_bytes"]))
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(metadata['filename'])}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _spatial_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> None:
        metadata, path = self.service.get_spatial_artifact(organization_id, project_id, artifact_id)
        self.send_response(200)
        self.send_header("Content-Type", metadata["content_type"])
        self.send_header("Content-Length", str(metadata["size_bytes"]))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(metadata['filename'])}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _estimate_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> None:
        metadata, path = self.service.get_estimate_artifact(organization_id, project_id, artifact_id)
        self.send_response(200)
        self.send_header("Content-Type", metadata["content_type"])
        self.send_header("Content-Length", str(metadata["size_bytes"]))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(metadata['filename'])}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _download_url(self, organization_id: str, project_id: str, file_id: str) -> str:
        if self.accounts:
            return f"/api/v1/projects/{quote(project_id)}/files/{quote(file_id)}/content"
        expires = int(time.time()) + 3600
        message = f"{organization_id}\0{project_id}\0{file_id}\0{expires}".encode("utf-8")
        signature = hmac.new(self.download_secret, message, hashlib.sha256).hexdigest()
        query = urlencode({"org": organization_id, "expires": expires, "signature": signature})
        return f"/api/v1/projects/{quote(project_id)}/files/{quote(file_id)}/content?{query}"

    def _file_identity(self, project_id: str, file_id: str) -> str:
        if self.accounts:
            return self._identity()[0]
        if self.headers.get("X-Organization-Id"):
            return self._identity()[0]
        query = parse_qs(urlsplit(self.path).query)
        organization_id = query.get("org", [""])[0]
        signature = query.get("signature", [""])[0]
        try:
            expires = int(query.get("expires", ["0"])[0])
        except ValueError:
            expires = 0
        if not organization_id or not signature or not int(time.time()) <= expires <= int(time.time()) + 3600:
            raise ApiError(401, "UNAUTHORIZED", "download link is missing or expired")
        message = f"{organization_id}\0{project_id}\0{file_id}\0{expires}".encode("utf-8")
        expected = hmac.new(self.download_secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ApiError(401, "UNAUTHORIZED", "download link is invalid")
        return organization_id

    def do_GET(self) -> None:
        try:
            self._guard()
            path = urlsplit(self.path).path
            if path == "/api/v1/auth/config":
                return self._json(200, {"mode": "accounts" if self.accounts else "local", "initialized": self.accounts.has_users() if self.accounts else True})
            if path == "/api/health/live":
                return self._json(200, {"status": "ok"})
            if path == "/api/health/ready":
                return self._json(200, {"status": "ready"})
            if self._static(path):
                return None
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/files/([^/]+)/content", path)
            if match:
                return self._file(self._file_identity(match.group(1), match.group(2)), match.group(1), match.group(2))
            organization_id, _ = self._identity()
            if self.accounts and path == "/api/v1/auth/session":
                return self._json(200, self.accounts.session(self.authenticated_identity))
            if self.accounts and path == "/api/v1/auth/users":
                return self._json(200, self.accounts.list_users(self.authenticated_identity))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/members", path)
            if self.accounts and match:
                return self._json(200, self.accounts.list_members(self.authenticated_identity, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/design/artifacts/([^/]+)/content", path)
            if match:
                metadata, file_path = self.service.get_design_artifact(organization_id, match.group(1), match.group(2))
                self.send_response(200)
                self.send_header("Content-Type", metadata["content_type"])
                self.send_header("Content-Length", str(metadata["size_bytes"]))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(metadata['filename'])}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with file_path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        self.wfile.write(chunk)
                return
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/design(?:/revisions/(\d+))?", path)
            if match:
                return self._json(200, self.service.get_design(organization_id, match.group(1), int(match.group(2)) if match.group(2) else None))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/spatial/artifacts/([^/]+)/content", path)
            if match:
                return self._spatial_artifact(organization_id, match.group(1), match.group(2))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates/artifacts/([^/]+)/content", path)
            if match:
                return self._estimate_artifact(organization_id, match.group(1), match.group(2))
            if path == "/api/v1/projects":
                result = self.service.list_projects(organization_id)
                if self.accounts:
                    result = self.accounts.filter_projects(self.authenticated_identity, result)
                return self._json(200, result)
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/files", path)
            if match:
                result = self.service.list_files(organization_id, match.group(1))
                for item in result["items"]:
                    item["download_url"] = self._download_url(organization_id, match.group(1), item["file_id"])
                return self._json(200, result)
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/decisions", path)
            if match:
                return self._json(200, self.service.list_decisions(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/issues", path)
            if match:
                return self._json(200, self.service.list_issues(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/issues/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_issue(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/jobs", path)
            if match:
                return self._json(200, self.service.list_jobs(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates", path)
            if match:
                return self._json(200, self.service.list_estimates(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_estimate(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/spatial", path)
            if match:
                return self._json(200, self.service.get_spatial_model(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/requirements", path)
            if match:
                return self._json(200, self.service.get_requirement(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/procurement/orders", path)
            if match:
                return self._json(200, self.service.list_procurement_orders(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/procurement/orders/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_procurement_order(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes", path)
            if match:
                return self._json(200, self.service.list_changes(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_change(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes/artifacts/([^/]+)/content", path)
            if match:
                metadata, file_path = self.service.get_change_artifact(organization_id, match.group(1), match.group(2))
                self.send_response(200)
                self.send_header("Content-Type", metadata["content_type"])
                self.send_header("Content-Length", str(metadata["size_bytes"]))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(metadata['filename'])}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with file_path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        self.wfile.write(chunk)
                return
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/spatial/artifacts", path)
            if match:
                return self._json(200, self.service.list_spatial_artifacts(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_project(organization_id, match.group(1)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/commands/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_command(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/workflows/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_workflow(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/artifacts/([^/]+)", path)
            if match:
                return self._json(200, self.service.get_artifact(organization_id, match.group(1), match.group(2)))
            raise ApiError(404, "NOT_FOUND", "route not found")
        except ApiError as error:
            self._error(error)
        except (ValueError, json.JSONDecodeError) as error:
            self._error(ApiError(400, "INVALID_REQUEST", str(error)))

    def do_POST(self) -> None:
        try:
            self._guard()
            path = urlsplit(self.path).path
            if self.accounts and path == "/api/v1/auth/login":
                body = self._body()
                token, session = self.accounts.login(body.get("username", ""), body.get("password", ""), self.client_address[0])
                return self._json(200, session, f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}")
            if path == "/api/v1/projects":
                organization_id, actor_id = self._identity()
                body = self._body()
                return self._json(201, self.service.create_project(organization_id, str(body.get("name", "")), body.get("project_id"), actor_id=actor_id))
            organization_id, actor_id = self._identity()
            if self.accounts and path == "/api/v1/auth/logout":
                self.accounts.logout(self.headers, self.authenticated_identity)
                return self._json(200, {"status": "signed_out"}, f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
            if self.accounts and path == "/api/v1/auth/users":
                return self._json(201, self.accounts.create_user(self.authenticated_identity, self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/members", path)
            if self.accounts and match:
                return self._json(200, self.accounts.set_member(self.authenticated_identity, match.group(1), self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/design/revisions", path)
            if match:
                return self._json(201, self.service.create_design(organization_id, match.group(1), actor_id, self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/uploads", path)
            if match:
                return self._json(201, self.service.initiate_upload(organization_id, match.group(1), self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/uploads/([^/]+)/complete", path)
            if match:
                return self._json(201, self.service.complete_upload(organization_id, match.group(1), match.group(2), str(self._body().get("completed_sha256", ""))))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/commands", path)
            if match:
                key = self.headers.get("Idempotency-Key", "")
                return self._json(202, self.service.submit_command(organization_id, match.group(1), actor_id, self._body(), key))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/jobs/([^/]+)/retry", path)
            if match:
                return self._json(202, self.service.retry_job(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/jobs/([^/]+)/cancel", path)
            if match:
                return self._json(200, self.service.cancel_job(organization_id, match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates/([^/]+)/calculations", path)
            if match:
                return self._json(200, self.service.calculate_estimate(
                    organization_id, match.group(1), match.group(2), self._body(), actor_id,
                ))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates/([^/]+)/export", path)
            if match:
                result = self.service.export_estimate(organization_id, match.group(1), match.group(2), actor_id)
                for item in result["items"]:
                    item["download_url"] = f"/api/v1/projects/{quote(match.group(1))}/estimates/artifacts/{quote(item['artifact_id'])}/content"
                return self._json(201, result)
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/spatial/revisions", path)
            if match:
                return self._json(201, self.service.create_spatial_revision(
                    organization_id, match.group(1), self._body(), actor_id,
                ))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/requirements/drafts", path)
            if match:
                return self._json(201, self.service.create_requirement_draft(organization_id, match.group(1), actor_id, self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/procurement/orders", path)
            if match:
                return self._json(201, self.service.create_procurement_order(organization_id, match.group(1), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/procurement/orders/([^/]+)/receipts", path)
            if match:
                return self._json(201, self.service.receive_procurement(organization_id, match.group(1), match.group(2), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/procurement/orders/([^/]+)/allocations", path)
            if match:
                return self._json(201, self.service.allocate_procurement(organization_id, match.group(1), match.group(2), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes", path)
            if match:
                return self._json(201, self.service.create_change(organization_id, match.group(1), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes/([^/]+)/analyze", path)
            if match:
                return self._json(200, self.service.analyze_change(organization_id, match.group(1), match.group(2), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/changes/([^/]+)/acceptance", path)
            if match:
                return self._json(200, self.service.accept_change(organization_id, match.group(1), match.group(2), actor_id, self._body(), self.headers.get("Idempotency-Key", "")))
            raise ApiError(404, "NOT_FOUND", "route not found")
        except ApiError as error:
            self._error(error)
        except (ValueError, json.JSONDecodeError) as error:
            self._error(ApiError(400, "INVALID_REQUEST", str(error)))

    def do_PUT(self) -> None:
        try:
            self._guard()
            path = urlsplit(self.path).path
            organization_id, _ = self._identity()
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/uploads/([^/]+)/content", path)
            if match:
                length = int(self.headers.get("Content-Length", "0"))
                return self._json(200, self.service.receive_upload(
                    organization_id, match.group(1), match.group(2), self.rfile, length,
                ))
            raise ApiError(404, "NOT_FOUND", "route not found")
        except ApiError as error:
            self._error(error)
        except ValueError as error:
            self._error(ApiError(400, "INVALID_REQUEST", str(error)))

    def do_PATCH(self) -> None:
        try:
            self._guard()
            path = urlsplit(self.path).path
            organization_id, actor_id = self._identity()
            match = re.fullmatch(r"/api/v1/auth/users/([^/]+)", path)
            if self.accounts and match:
                return self._json(200, self.accounts.update_user(self.authenticated_identity, match.group(1), self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/requirements", path)
            if match:
                return self._json(200, self.service.update_requirement(organization_id, match.group(1), actor_id, self._body()))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)", path)
            if match:
                return self._json(200, self.service.update_project(organization_id, match.group(1), self._body(), actor_id=actor_id))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/issues/([^/]+)", path)
            if match:
                return self._json(200, self.service.record_issue_disposition(
                    organization_id, match.group(1), match.group(2), self._body(), actor_id,
                ))
            match = re.fullmatch(r"/api/v1/projects/([^/]+)/estimates/([^/]+)/lines/([^/]+)", path)
            if match:
                return self._json(200, self.service.update_estimate_line(
                    organization_id, match.group(1), match.group(2), match.group(3), self._body(), actor_id,
                ))
            raise ApiError(404, "NOT_FOUND", "route not found")
        except ApiError as error:
            self._error(error)
        except (ValueError, json.JSONDecodeError) as error:
            self._error(ApiError(400, "INVALID_REQUEST", str(error)))


def create_server(service: ApiService | None = None, identity_provider: IdentityProvider | None = None,
                  host: str = "127.0.0.1", port: int = 8080,
                  static_dir: Path | None = None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("M5 account pilot is loopback-only; network deployment has not passed acceptance")
    service = service or ApiService()
    identity_provider = identity_provider or DevHeaderIdentityProvider()

    class BoundHandler(ApiHandler):
        pass

    BoundHandler.service = service
    BoundHandler.identity_provider = identity_provider
    BoundHandler.static_dir = static_dir.resolve() if static_dir else None
    BoundHandler.download_secret = secrets.token_bytes(32)
    return ThreadingHTTPServer((host, port), BoundHandler)
