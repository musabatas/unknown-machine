"""Watch every run live in the browser while it is being played.

    poetry run python scripts/watch.py                       every Harbor run in progress
    poetry run python scripts/watch.py --demo reference greedy cautious --level 4
    poetry run python scripts/watch.py --demo greedy --theme aircraft --delay 0.2

It serves `viewer/index.html` on 127.0.0.1 with one tile per run. Runs that end
stay on the page, and the most recent finished runs under jobs/ are listed too, so
there is always something to open.

For a Harbor run the state is read from the machine sidecar, which is the only
place it exists. The sidecar hands its result only to a caller that proves it holds
the result key, and that key never leaves the sidecar: the request is made by a
process started inside the sidecar itself, through `docker exec`. Nothing is
published on a sidecar port.

What this server shows includes the hidden rules of runs in progress, and an agent's
container can reach a server on the host. So every path sits under a secret drawn
at start and printed only to this terminal; any other path is 404.
"""

import argparse
import contextlib
import hmac
import json
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer" / "index.html"
JOBS = ROOT / "jobs"
MARKER = "<!--EPISODE-->"
SIDECAR_SUFFIX = "__env-machine-1"
REFRESH_SECONDS = 1.0
FINISHED_SHOWN = 12  # finished runs from jobs/ listed at start

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
    """Docker could not be asked; the message says why."""


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


def trial_facts(trial: str) -> dict:
    """Agent, model and start time of a Harbor trial, from its directory under jobs/.

    A sidecar is named after its trial in lower case; the directory keeps the case.
    """
    for config in JOBS.glob("*/*/config.json"):
        if config.parent.name.lower() != trial:
            continue
        try:
            agent = json.loads(config.read_text()).get("agent", {})
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            "agent": agent.get("name"),
            "model": agent.get("model_name"),
            "started": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(config.stat().st_mtime)
            ),
        }
    return {}


class Runs:
    """Every run this session knows, with its latest episode. Refreshed by one thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._episodes: dict[str, dict] = {}
        self._facts: dict[str, dict] = {}
        self._live: set[str] = set()
        self._order: list[str] = []  # first seen first, so tiles keep their place
        self.error: str | None = None
        self._demos: dict[str, object] = {}

    # ---- sources -----------------------------------------------------------

    def add_finished_jobs(self) -> None:
        episodes = sorted(
            JOBS.glob("*/*/verifier/episode.json"), key=lambda path: path.stat().st_mtime
        )
        for path in episodes[-FINISHED_SHOWN:]:
            try:
                episode = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if "system" not in episode:  # recorded before the result carried the rules
                continue
            trial = path.parent.parent.name.lower()
            self._put(trial, episode, live=False, facts=trial_facts(trial))

    def add_demo(self, policy: str, seed: int, level: int, theme: str, delay: float) -> None:
        from unknown_machine.baselines.policies import BASELINES
        from unknown_machine.calibration import build_episode

        if policy not in BASELINES:
            raise SystemExit(f"unknown policy {policy!r}; one of: {', '.join(sorted(BASELINES))}")
        episode = build_episode(seed, level, theme)
        name = f"demo-{policy}"
        self._demos[name] = episode
        self._put(name, episode.result(), live=True, facts={"agent": policy, "model": None})
        threading.Thread(
            target=BASELINES[policy], args=(_Slowed(episode, delay),), daemon=True
        ).start()

    def refresh(self, watch_docker: bool) -> None:
        for name, episode in self._demos.items():
            result = episode.result()
            self._put(name, result, live=not result["finished"])
        if not watch_docker:
            return
        try:
            names = docker("ps", "--format", "{{.Names}}").split()
            self.error = None
        except Unavailable as reason:
            self.error = str(reason)
            return
        running = {
            name.removesuffix(SIDECAR_SUFFIX): name
            for name in names
            if name.endswith(SIDECAR_SUFFIX)
        }
        for trial, container in running.items():
            try:
                episode = json.loads(docker("exec", container, "python", "-c", INSIDE_SIDECAR))
            except (Unavailable, json.JSONDecodeError):
                continue  # starting up or just torn down; the next pass settles it
            facts = None if trial in self._facts else trial_facts(trial)
            self._put(trial, episode, live=True, facts=facts)
        with self._lock:
            # A sidecar that is gone has ended: what was last seen is final.
            for trial in self._live - set(running) - set(self._demos):
                self._live.discard(trial)

    def _put(self, name: str, episode: dict, live: bool, facts: dict | None = None) -> None:
        with self._lock:
            if name not in self._episodes:
                self._order.append(name)
            self._episodes[name] = episode
            if facts is not None:
                self._facts[name] = facts
            if live:
                self._live.add(name)
            else:
                self._live.discard(name)

    # ---- what the page asks for --------------------------------------------

    def listing(self) -> dict:
        with self._lock:
            rows = [self._row(name) for name in self._order]
        live = [row for row in rows if row["state"] == "live"]
        finished = [row for row in rows if row["state"] == "finished"]
        answer: dict = {"runs": live + finished[::-1]}
        if self.error:
            answer["error"] = self.error
        return answer

    def _row(self, name: str) -> dict:
        episode = self._episodes[name]
        system = episode["system"]
        facts = self._facts.get(name, {})
        theme = system.get("theme", "legacy")
        prefix = "" if theme == "legacy" else f"{theme}/"
        done: dict[str, int] = {}
        sync = system.get("sync_command", "sync")
        for entry in episode["log"]:
            if entry["tool"] == "run" and entry["outcome"] == "ok" and entry["command"] != sync:
                done[entry["service"]] = done.get(entry["service"], 0) + 1
        serving = sum(
            done.get(spec["codename"], 0) == len(spec["steps"])
            and spec["codename"] not in episode["data_lost"]
            for spec in system["services"]
        )
        last = episode["log"][-1] if episode["log"] else None
        return {
            "id": name,
            "state": "live" if name in self._live else "finished",
            "task": f"{prefix}level-{system['level']}/seed-{system['seed']}",
            "theme": theme,
            "level": system["level"],
            "seed": system["seed"],
            "agent": facts.get("agent"),
            "model": facts.get("model"),
            "started": facts.get("started"),
            "score": episode["score"],
            "tiers_banked": episode["tiers_banked"],
            "data_lost": episode["data_lost"],
            "window_used": episode["window_used"],
            "window_total": episode["window_total"],
            "calls": episode["calls"],
            "services": len(system["services"]),
            "serving": serving,
            "last": last
            and {key: last[key] for key in ("tool", "service", "command", "outcome", "code")},
        }

    def episode(self, name: str) -> dict | None:
        with self._lock:
            episode = self._episodes.get(name)
            if episode is None:
                return None
            # The page ends its polling on `finished`; a run cut off before `finish`
            # has ended all the same once its sidecar is gone.
            return episode | {"finished": episode["finished"] or name not in self._live}


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


def handler(runs: Runs, page: bytes, base: str) -> type[BaseHTTPRequestHandler]:
    """Everything is served under `base`, a path holding this session's secret.

    The episodes served here contain the hidden rules of runs in progress, and a
    container can reach a server on the host. Without the secret every path is 404,
    so an agent that finds the port learns nothing from it.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
            url = urlsplit(self.path)
            prefix, path = url.path[: len(base)], url.path[len(base) :]
            if not hmac.compare_digest(prefix.encode(), base.encode()):
                self._send(404, "text/plain", b"not found")
            elif path == "/":
                self._send(200, "text/html; charset=utf-8", page)
            elif path == "/runs":
                self._json(200, runs.listing())
            elif path == "/episode":
                name = parse_qs(url.query).get("run", [""])[0]
                episode = runs.episode(name)
                if episode is None:
                    self._json(503, {"error": f"no run named {name!r}"})
                else:
                    self._json(200, episode)
            else:
                self._send(404, "text/plain", b"not found")

        def _json(self, code: int, payload: dict) -> None:
            self._send(code, "application/json", json.dumps(payload).encode())

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
    parser.add_argument(
        "--demo", metavar="POLICY", nargs="+", help="play scripted policies instead of Harbor runs"
    )
    parser.add_argument("--seed", type=int, default=0, help="seed for --demo (default 0)")
    parser.add_argument("--level", type=int, default=1, help="level for --demo (default 1)")
    parser.add_argument(
        "--theme", default="legacy", help="scenario for --demo: legacy, aircraft or residency"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="seconds between calls for --demo (default 0.5)"
    )
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    arguments = parser.parse_args()

    runs = Runs()
    if arguments.demo:
        try:
            for policy in arguments.demo:
                runs.add_demo(
                    policy, arguments.seed, arguments.level, arguments.theme, arguments.delay
                )
        except ValueError as error:  # unknown theme or level
            raise SystemExit(str(error)) from error
    else:
        runs.add_finished_jobs()

    def keep_fresh() -> None:
        while True:
            runs.refresh(watch_docker=not arguments.demo)
            time.sleep(REFRESH_SECONDS)

    threading.Thread(target=keep_fresh, daemon=True).start()

    template = VIEWER.read_text(encoding="utf-8")
    if MARKER not in template:
        raise SystemExit(f"{VIEWER}: the {MARKER} marker is missing.")
    base = f"/{secrets.token_urlsafe(24)}"  # new on every start, never written anywhere
    live = json.dumps({"runs": f"{base}/runs", "episode": f"{base}/episode"})
    page = template.replace(MARKER, f"<script>window.LIVE = {live};</script>", 1).encode()

    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), handler(runs, page, base))
    print(f"http://127.0.0.1:{arguments.port}{base}/  (Ctrl-C to stop)")
    print("The address holds this session's secret: it shows the hidden rules of every run.")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
