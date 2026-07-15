"""Minimal HTTP front for the API Lambda, so gate-verify can boot the real
read path and hit it over the wire.

Translates an incoming HTTP GET into the API Gateway (HTTP API v2) event shape
the router expects, invokes `api.router.lambda_handler`, and writes its
statusCode/headers/body straight back. No framework — stdlib http.server keeps
the gate dependency-free.

Port is GATE_API_PORT (default 8001); 8000 is taken by DynamoDB Local.
"""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from v1.api.router import lambda_handler

PORT = int(os.environ.get("GATE_API_PORT", "8001"))


def _path_parameters(path: str) -> dict:
    """Extract path params the handlers read. Only /predictions/{round} has one."""
    parts = [p for p in path.split("/") if p]
    if len(parts) == 2 and parts[0] == "predictions":
        return {"round": parts[1]}
    return {}


def _to_event(path: str) -> dict:
    return {
        "rawPath": path,
        "path": path,
        "pathParameters": _path_parameters(path),
        "queryStringParameters": {},
        "requestContext": {"http": {"method": "GET", "sourceIp": "127.0.0.1"}},
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        path = urlparse(self.path).path.rstrip("/") or "/"
        result = lambda_handler(_to_event(path), None)

        body = (result.get("body") or "").encode("utf-8")
        self.send_response(result.get("statusCode", 200))
        for key, value in (result.get("headers") or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _method_not_allowed(self):
        # Mirror API Gateway: unsupported methods get 405, not http.server's
        # stdlib 501 (which reads as a server fault to fuzzers and clients).
        body = b'{"error": "Method not allowed"}'
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def __getattr__(self, name):
        # BaseHTTPRequestHandler dispatches on do_<METHOD>; answer 405 for any
        # verb we don't implement (POST, TRACE, QUERY, ...) instead of 501.
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)

    def log_message(self, *args):  # quieten default per-request stderr noise
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"local_api_server: listening on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
