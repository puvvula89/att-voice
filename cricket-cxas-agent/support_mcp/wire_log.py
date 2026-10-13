"""Optional request/response wire logging for the MCP endpoint.

Enabled with MCP_WIRE_LOG=1. Prints each JSON-RPC request and the first part of
the response body to stdout so Cloud Run logs show exactly what the platform
sent during tool discovery. Diagnostic only; off by default.
"""
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class WireLog(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        body = await request.body()
        print(f"WIRE> {request.method} {request.url.path} ua={request.headers.get('user-agent','')!r} "
              f"accept={request.headers.get('accept','')!r} proto={request.headers.get('mcp-protocol-version','')!r} "
              f"body={body[:600]!r}", flush=True)
        response = await call_next(request)
        chunks = []
        async for c in response.body_iterator:
            chunks.append(c)
        raw = b"".join(chunks)
        print(f"WIRE< {response.status_code} ct={response.headers.get('content-type','')!r} body={raw[:800]!r}", flush=True)
        from starlette.responses import Response
        return Response(content=raw, status_code=response.status_code, headers=dict(response.headers),
                        media_type=response.media_type)


def install(app):
    if os.environ.get("MCP_WIRE_LOG") == "1":
        app.add_middleware(WireLog)
    return app
