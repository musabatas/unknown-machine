"""Smoke-test machine: one service, two commands, score held server-side.

This is not the real environment. It exists to prove the harness wiring:
MCP sidecar -> agent tools -> server-side score -> signed result -> reward.txt.
"""

import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mcp.server import MCPServer

MCP_PORT = 8000
CONTROL_PORT = 8001
RESULT_KEY = os.environ["RESULT_KEY"].encode()

SERVICE = "kestrel"
# command -> (mode required before, mode after)
COMMANDS = {"start": ("stopped", "ready"), "serve": ("ready", "serving")}
SCORE_BY_MODE = {"stopped": 0.0, "ready": 0.5, "serving": 1.0}


class Episode:
    """All mutable state of one episode. Every access goes through the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = "stopped"
        self._finished = False
        self._calls = 0

    def status(self) -> dict:
        with self._lock:
            return {"services": {SERVICE: self._mode}, "finished": self._finished}

    def run(self, service: str, command: str) -> dict:
        with self._lock:
            if self._finished:
                return {"ok": False, "error": "E00 episode finished"}
            self._calls += 1
            if service != SERVICE:
                return {"ok": False, "error": "E01 unknown service"}
            if command not in COMMANDS:
                return {"ok": False, "error": "E02 unknown command"}
            required, after = COMMANDS[command]
            if self._mode != required:
                return {"ok": False, "error": "E03 refused"}
            self._mode = after
            return {"ok": True, "services": {SERVICE: self._mode}}

    def finish(self) -> dict:
        with self._lock:
            self._finished = True
            return {"finished": True}

    def result(self) -> dict:
        with self._lock:
            return {
                "score": SCORE_BY_MODE[self._mode],
                "finished": self._finished,
                "calls": self._calls,
            }


EPISODE = Episode()
mcp = MCPServer("machine")


@mcp.tool()
def status() -> dict:
    """Show the mode of every service and whether the episode has finished. Free."""
    return EPISODE.status()


@mcp.tool()
def run(service: str, command: str) -> dict:
    """Execute a command on a service for real. Returns ok or an error code."""
    return EPISODE.run(service, command)


@mcp.tool()
def finish() -> dict:
    """End the episode. No command is accepted afterwards."""
    return EPISODE.finish()


def sign(payload: bytes) -> str:
    return hmac.new(RESULT_KEY, payload, hashlib.sha256).hexdigest()


class Control(BaseHTTPRequestHandler):
    """Health check and the signed result read by the verifier."""

    def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(200, b'{"ok": true}')
            return
        if url.path == "/result":
            nonce = parse_qs(url.query).get("nonce", [""])[0]
            if not nonce or len(nonce) > 128:
                self._send(400, b'{"error": "nonce required"}')
                return
            body = json.dumps({"nonce": nonce, **EPISODE.result()}, sort_keys=True).encode()
            envelope = {"body": body.decode(), "signature": sign(body)}
            self._send(200, json.dumps(envelope).encode())
            return
        self._send(404, b'{"error": "not found"}')

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


if __name__ == "__main__":
    control = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Control)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_PORT)
