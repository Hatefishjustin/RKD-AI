"""ASGI transport for the shared business routes, without a reference HTTP server.

Uvicorn parses HTTP. FastAPI streams bounded request bodies to temporary files,
and runs synchronous domain/database work in its thread pool. Forwarded headers
never grant identity or change the configured browser origin.
"""
from email.message import Message
import logging
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse

from .account_identity import AccountIdentityProvider
from .api_server import ApiRoutes
from .api_service import ApiError
from .file_service import MAX_UPLOAD_BYTES


class _RequestRoutes(ApiRoutes):
    def __init__(self, service, accounts, static_dir, origin, request, source, output):
        self.service, self.identity_provider = service, accounts
        self.static_dir, self.origin = static_dir, origin
        self.command = request.method
        self.path = request.scope.get("raw_path", b"/").decode("ascii")
        query = request.scope.get("query_string", b"").decode("ascii")
        if query:
            self.path += "?" + query
        self.client_address = (request.client.host if request.client else "unknown", 0)
        self.headers = Message()
        for key, value in request.scope["headers"]:
            self.headers[key.decode("latin1")] = value.decode("latin1")
        self.rfile, self.wfile = source, output
        self.status, self.response_headers = 500, []

    def _guard(self):
        # Even a locally connected proxy must preserve the configured Host.
        path = urlsplit(self.path).path
        host = self.headers.get("Host", "").lower()
        expected = urlsplit(self.origin).netloc.lower()
        if host != expected:
            # Container health checks use their own loopback authority, only for
            # these two probes; it is never accepted for business/auth routes.
            probe_host = urlsplit("http://" + host)
            if path not in {"/api/health/live", "/api/health/ready"} or probe_host.hostname not in {"127.0.0.1", "localhost"}:
                raise ApiError(403, "INVALID_HOST", "请使用已配置的系统地址")
        for name in ("Host", "Content-Length", "Content-Type", "Origin", "Cookie", "X-CSRF-Token"):
            if len(self.headers.get_all(name, [])) > 1:
                raise ApiError(400, "AMBIGUOUS_HEADERS", "请求头重复")
        if self.command != "GET":
            origin = self.headers.get("Origin")
            if origin is not None and origin != self.origin:
                raise ApiError(403, "INVALID_ORIGIN", "请从工作台页面提交操作")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise ApiError(403, "INVALID_ORIGIN", "拒绝跨站写入")
        self.service.validate_route(self.command, path) if hasattr(self.service, "validate_route") else None

    def send_response(self, status):
        self.status = status
        self.response_headers = []

    def send_header(self, name, value):
        if name.lower() == "set-cookie" and self.origin.startswith("https://"):
            value += "; Secure"
        self.response_headers.append((name.lower().encode("ascii"), str(value).encode("latin1")))

    def end_headers(self):
        for name, value in (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                            ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin")):
            self.send_header(name, value)

    def execute(self):
        try:
            getattr(self, "do_" + self.command)()
        except Exception as error:
            # Database exceptions may contain connection information or data.
            logging.getLogger(__name__).error("request failed: %s", type(error).__name__)
            self.wfile.seek(0)
            self.wfile.truncate()
            self._error(ApiError(500, "INTERNAL_ERROR", "操作失败，请稍后重试"))
        finally:
            close = getattr(self.service.app.store, "close_thread_connection", None)
            if close:
                close()
        self.wfile.seek(0)


def create_app(service, accounts, static_dir: Path, public_origin: str):
    if not isinstance(accounts, AccountIdentityProvider):
        raise ValueError("server transport requires real account identity")
    parsed = urlsplit(public_origin)
    if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("public origin must be an exact scheme and authority")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("remote browser origins require HTTPS")
    public_origin = public_origin.lower()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH"])
    async def dispatch(request: Request, path: str):
        source = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        output = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024)
        transferred = False
        try:
            routes = _RequestRoutes(service, accounts, static_dir.resolve(), public_origin, request, source, output)
            try:
                routes._guard()
                length = int(routes.headers.get("Content-Length", "0"))
                maximum = MAX_UPLOAD_BYTES if request.method == "PUT" else 1024 * 1024
                if length < 0 or length > maximum:
                    raise ApiError(413, "BODY_TOO_LARGE", "请求内容超出限制")
                # Streaming bytes are counted independently of the header. No
                # chunked request may bypass limits or the upload byte count.
                received = 0
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > maximum:
                        raise ApiError(413, "BODY_TOO_LARGE", "请求内容超出限制")
                    await run_in_threadpool(source.write, chunk)
                if received != length:
                    raise ApiError(400, "CONTENT_LENGTH_REQUIRED", "请求字节数与 Content-Length 不一致")
            except ApiError as error:
                return JSONResponse({"error_code": error.code, "message": error.message}, status_code=error.status,
                                    headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})
            except ValueError:
                return JSONResponse({"error_code":"INVALID_REQUEST", "message":"请求格式错误"}, status_code=400)
            source.seek(0)
            await run_in_threadpool(routes.execute)

            def chunks():
                try:
                    while chunk := output.read(1024 * 1024):
                        yield chunk
                finally:
                    output.close()

            response = StreamingResponse(chunks(), status_code=routes.status, background=BackgroundTask(output.close))
            response.raw_headers = routes.response_headers
            transferred = True
            return response
        finally:
            source.close()
            if not transferred:
                output.close()

    return app
