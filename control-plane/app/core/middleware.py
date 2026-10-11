"""Trace id per request: taken from or generated for `X-Request-ID`, echoed in the response."""

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TRACE_ID_HEADER = "X-Request-ID"

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

# A client-supplied id must be short and boring: it ends up in logs.
_SAFE_ID = re.compile(r"[\w.\-]{1,64}")


class TraceIdMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware: it breaks contextvars and streaming)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for key, value in scope["headers"]:
            if key == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        trace_id = incoming if _SAFE_ID.fullmatch(incoming) else uuid.uuid4().hex

        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_var.set(trace_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[TRACE_ID_HEADER] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            trace_id_var.reset(token)
