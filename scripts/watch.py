"""Watch an episode live in the browser while it is being played.

    poetry run python scripts/watch.py                    the Harbor run in progress
    poetry run python scripts/watch.py --demo reference   a scripted policy, slowed down
    poetry run python scripts/watch.py --demo greedy --theme aircraft --level 4 --delay 0.2

It serves `viewer/index.html` on 127.0.0.1 and feeds it the episode as it grows.

For a Harbor run the state is read from the machine sidecar, which is the only
place it exists. The sidecar hands its result only to a caller that proves it holds
the result key, and that key never leaves the sidecar: the request is made by a
process started inside the sidecar itself, through `docker exec`. Nothing is
published on a port and the agent's container learns nothing.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer" / "index.html"
MARKER = "<!--EPISODE-->"

# Runs inside the sidecar: asks its own control port for the result, with the proof
# computed from the key in its environment, and prints the result body.
INSIDE_SIDECAR = """
import hashlib, hmac, json, os, secrets, urllib.request
key = os.environ["RESULT_KEY"].encode()
nonce = secrets.token_hex(16)
proof = hmac.new(key, nonce.encode(), hashlib.sha256).hexdigest()
url = f"http://localhost:8001/result?nonce={nonce}&proof={proof}"
print(json.load(urllib.request.urlopen(url, timeout=5))["body"])
"""


class Unavailable(Exception):
    """There is no episode to show right now; the message says why."""


def docker(*arguments: str) -> str:
    try:
        done = subprocess.run(
            ("docker", *arguments), capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Unavailable(f"docker is not answering: {error}") from error
    if done.returncode != 0:
        raise Unavailable(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "docker")
    return done.stdout


class HarborRun:
    """The episode inside the machine sidecar of a running Harbor trial."""

    def __init__(self, container: str | None) -> None:
        self.container = container
        self.last: dict | None = None  # kept after the sidecar is torn down

    def label(self) -> str:
        return self.container or "Harbor run"

    def _sidecar(self) -> str:
        if self.container:
            return self.container
        names = docker("ps", "--format", "{{.Names}}").split()
        sidecars = sorted(name for name in names if name.endswith("-machine-1"))
        if not sidecars:
            raise Unavailable("no Harbor run in progress (no machine sidecar is running)")
        if len(sidecars) > 1:
            raise Unavailable(
                "several runs in progress; pick one with --container: " + ", ".join(sidecars)
            )
        return sidecars[0]

    def episode(self) -> dict:
        try:
            body = docker("exec", self._sidecar(), "python", "-c", INSIDE_SIDECAR)
            self.last = json.loads(body)
        except (Unavailable, json.JSONDecodeError):
            if self.last is None:
                raise
            # The trial ended and Harbor removed the sidecar: what was last seen is final.
            self.last["finished"] = True
        return self.last


class _Slowed:
    """The six tools of an episode, each call delayed so it can be followed by eye."""

    def __init__(self, episode, delay: float) -> None:
        self._episode = episode
        self._delay = delay

    def __getattr__(self, tool: str):
        call = getattr(self._episode, tool)

        def delayed(*arguments):
            time.sleep(self._delay)
            return call(*arguments)

        return delayed


class Demo:
    """A scripted policy playing one seed in this process."""

    def __init__(self, policy: str, seed: int, level: int, theme: str, delay: float) -> None:
        from unknown_machine.baselines.policies import BASELINES
        from unknown_machine.calibration import build_episode

        if policy not in BASELINES:
            raise SystemExit(f"unknown policy {policy!r}; one of: {', '.join(sorted(BASELINES))}")
        self._label = f"{policy}, {theme}, level {level}, seed {seed}"
        self._episode = build_episode(seed, level, theme)
        play = BASELINES[policy]
        threading.Thread(
            target=play, args=(_Slowed(self._episode, delay),), daemon=True
        ).start()

    def label(self) -> str:
        return self._label

    def episode(self) -> dict:
        return self._episode.result()


def handler(source, page: bytes) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", page)
            elif path == "/episode":
                try:
                    body = json.dumps(source.episode()).encode()
                    self._send(200, "application/json", body)
                except Unavailable as reason:
                    body = json.dumps({"error": str(reason)}).encode()
                    self._send(503, "application/json", body)
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, code: int, kind: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", metavar="POLICY", help="play a scripted policy instead")
    parser.add_argument("--seed", type=int, default=0, help="seed for --demo (default 0)")
    parser.add_argument("--level", type=int, default=1, help="level for --demo (default 1)")
    parser.add_argument(
        "--theme", default="legacy", help="scenario for --demo: legacy, aircraft or residency"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="seconds between calls for --demo (default 0.5)"
    )
    parser.add_argument("--container", help="machine sidecar to watch, when several are running")
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    arguments = parser.parse_args()

    if arguments.demo:
        try:
            source = Demo(
                arguments.demo, arguments.seed, arguments.level, arguments.theme, arguments.delay
            )
        except ValueError as error:  # unknown theme or level
            raise SystemExit(str(error)) from error
    else:
        source = HarborRun(arguments.container)

    template = VIEWER.read_text(encoding="utf-8")
    if MARKER not in template:
        raise SystemExit(f"{VIEWER}: the {MARKER} marker is missing.")
    live = json.dumps({"url": "/episode", "label": source.label()}).replace("</", "<\\/")
    page = template.replace(MARKER, f"<script>window.LIVE = {live};</script>", 1).encode()

    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), handler(source, page))
    print(f"http://127.0.0.1:{arguments.port}/  (Ctrl-C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
