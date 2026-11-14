"""The sidecar: one episode behind six MCP tools, plus a control port for the verifier.

Everything hidden lives in this process and nowhere else: the seed, the rules,
the window and the score. The agent's container only ever sees tool results.
"""

import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mcp.server import MCPServer

from unknown_machine.calibration import build_episode

MCP_PORT = 8000
CONTROL_PORT = 8001
MAX_NONCE_LENGTH = 128

EPISODE = build_episode(int(os.environ["SEED"]), int(os.environ.get("LEVEL", "1")))
RESULT_KEY = os.environ["RESULT_KEY"].encode()

mcp = MCPServer("machine")


@mcp.tool()
def status() -> dict:
    """Mode of every service, the commands each accepts, banked tiers, window left. Free."""
    return EPISODE.status()


@mcp.tool()
def inspect(service: str) -> dict:
    """Read a service's logs: its role, which registers are pending and the command that
    clears each, and how accurate its dry runs are. Costs 2 minutes."""
    return EPISODE.inspect(service)


@mcp.tool()
def dry_run(service: str, command: str) -> dict:
    """Report what a command would do right now (ok, refused, crash, data_loss) without
    changing anything. Right with the probability `inspect` gives as dry_run_accuracy,
    independently on every call. Costs 4 minutes."""
    return EPISODE.dry_run(service, command)


@mcp.tool()
def run(service: str, command: str) -> dict:
    """Execute a command for real. Costs 1 minute, whatever the outcome."""
    return EPISODE.run(service, command)


@mcp.tool()
def restart(service: str) -> dict:
    """Bring a service out of a crash loop. Costs 4 minutes."""
    return EPISODE.restart(service)


@mcp.tool()
def finish() -> dict:
    """End the maintenance window now. Nothing is accepted afterwards."""
    return EPISODE.finish()


def sign(payload: bytes) -> str:
    return hmac.new(RESULT_KEY, payload, hashlib.sha256).hexdigest()


class Control(BaseHTTPRequestHandler):
    """Health check, and the signed result that only the verifier can validate."""

    def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(200, b'{"ok": true}')
            return
        if url.path == "/result":
            query = parse_qs(url.query)
            nonce = query.get("nonce", [""])[0]
            proof = query.get("proof", [""])[0]
            if not nonce or len(nonce) > MAX_NONCE_LENGTH:
                self._send(400, b'{"error": "nonce required"}')
                return
            # The result holds the whole episode log, including which dry runs were
            # wrong. Only a caller that already has the key may read it.
            if not hmac.compare_digest(proof, sign(nonce.encode())):
                self._send(403, b'{"error": "forbidden"}')
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


def main() -> None:
    control = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Control)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_PORT)


if __name__ == "__main__":
    main()
