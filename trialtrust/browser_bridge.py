"""Narrow browser transport for the separately hosted workbench.

The managed gateway filters application-specific HTTP headers. The bridge
unpacks an envelope into the existing ASGI routes; authentication, ownership,
validation and background-task execution still run in those routes.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from starlette.responses import JSONResponse, Response

BRIDGE_PATH = "/api/browser-bridge"
MAX_BODY = 1_048_576
HEADER_NAMES = {
    "x-trialtrust-account", "x-trialtrust-browser", "x-trialtrust-session",
    "x-trialtrust-conversation",
}
ROUTES = {
    "GET": re.compile(r"/api/(?:catalog|skills|account/storage|conversations|trials(?:/[A-Za-z0-9-]+(?:/export)?)?)\Z"),
    "POST": re.compile(r"/api/(?:auth/(?:bootstrap|register|login|logout|recover|password)|session|analyze|compile|conversations(?:/[A-Za-z0-9-]+/(?:rename|delete|actions))?|trials(?:/[A-Za-z0-9-]+/(?:review|resume|actions))?|suites)\Z"),
    "PATCH": re.compile(r"/api/conversations/[A-Za-z0-9-]+\Z"),
    "DELETE": re.compile(r"/api/conversations/[A-Za-z0-9-]+\Z"),
}


class BrowserBridge:
    def __init__(self, app, *, origins=()):
        self.app = app
        self.origins = frozenset(origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != BRIDGE_PATH:
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        origin = headers.get(b"origin", b"").decode("latin-1")
        if not origin or origin not in self.origins or scope.get("query_string"):
            return await JSONResponse({"detail": "此页面未获准连接工作台"}, 403)(scope, receive, send)

        async def cors_send(message):
            if message["type"] == "http.response.start":
                filtered = [(k, v) for k, v in message.get("headers", [])
                            if k.lower() not in {b"set-cookie", b"access-control-allow-origin"}]
                message = {**message, "headers": filtered + [
                    (b"access-control-allow-origin", origin.encode("ascii")),
                    (b"vary", b"Origin"),
                    (b"cache-control", b"no-store"),
                ]}
            await send(message)

        if scope["method"] == "OPTIONS":
            return await Response(status_code=204, headers={
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            })(scope, receive, cors_send)
        if scope["method"] != "POST" or headers.get(b"content-type", b"").split(b";", 1)[0].strip() != b"application/json":
            return await JSONResponse({"detail": "请求格式不正确"}, 400)(scope, receive, cors_send)
        raw = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            raw.extend(message.get("body", b""))
            if len(raw) > MAX_BODY:
                return await JSONResponse({"detail": "请求内容过长"}, 413)(scope, receive, cors_send)
            if not message.get("more_body", False):
                break
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) - {"path", "method", "headers", "body"}:
                raise ValueError()
            path = envelope.get("path")
            method = envelope.get("method", "GET")
            if not isinstance(path, str) or len(path) > 256 or not path.startswith("/api/"):
                raise ValueError()
            target = urlsplit(path)
            path = target.path
            if target.scheme or target.netloc or target.fragment or not isinstance(method, str) or method not in ROUTES or not ROUTES[method].fullmatch(path):
                raise ValueError()
            if target.query:
                query = parse_qs(target.query, strict_parsing=True)
                if method != "GET" or path != "/api/trials" or set(query) != {"conversation_id"} or len(query["conversation_id"]) != 1 or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", query["conversation_id"][0]):
                    raise ValueError()
            supplied = envelope.get("headers", {})
            if not isinstance(supplied, dict):
                raise ValueError()
            forwarded = []
            for key, value in supplied.items():
                if key.lower() not in HEADER_NAMES or not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 or ord(c) > 126 for c in value):
                    raise ValueError()
                forwarded.append((key.lower().encode("ascii"), value.encode("ascii")))
            body = envelope.get("body")
            if method == "GET" and body is not None:
                raise ValueError()
            payload = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError):
            return await JSONResponse({"detail": "请求格式不正确"}, 400)(scope, receive, cors_send)

        # Retain gateway routing and client IP metadata, never ambient cookies or
        # arbitrary caller-supplied headers. Authentication uses opaque tokens.
        excluded = {b"origin", b"referer", b"cookie", b"authorization", b"content-type", b"content-length"}
        original = [(k, v) for k, v in scope.get("headers", [])
                    if k.lower() not in excluded and not k.lower().startswith(b"x-trialtrust-")]
        expected = scope.get("scheme", "https") + "://" + headers.get(b"host", b"localhost").decode("latin-1")
        inner_headers = original + forwarded + [
            (b"origin", expected.encode("latin-1")),
            (b"x-trialtrust-client", b"web"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]
        inner = {**scope, "path": path, "raw_path": path.encode("ascii"),
                 "method": method, "query_string": target.query.encode("ascii"), "headers": inner_headers,
                 "trialtrust_browser_bridge": True}
        sent = False

        async def inner_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(inner, inner_receive, cors_send)
