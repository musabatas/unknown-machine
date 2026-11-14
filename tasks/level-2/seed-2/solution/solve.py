"""Reference run: the solver in solver.py, driven through the same six MCP tools.

POLICY selects a scripted baseline instead: reference (default), cautious, greedy,
stop_early.
"""

import json
import os

import anyio
from mcp import Client
from solver import solve

MACHINE_URL = "http://machine:8000/mcp"


class McpConsole:
    """The console the solver expects, backed by MCP tool calls.

    The solver is synchronous and runs in a worker thread; each call hops back
    to the event loop that owns the MCP session.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    def _call(self, tool: str, **arguments: str) -> dict:
        result = anyio.from_thread.run(self._client.call_tool, tool, arguments)
        text = next(block.text for block in result.content if hasattr(block, "text"))
        return json.loads(text)

    def status(self) -> dict:
        return self._call("status")

    def inspect(self, service: str) -> dict:
        return self._call("inspect", service=service)

    def dry_run(self, service: str, command: str) -> dict:
        return self._call("dry_run", service=service, command=command)

    def run(self, service: str, command: str) -> dict:
        return self._call("run", service=service, command=command)

    def restart(self, service: str) -> dict:
        return self._call("restart", service=service)

    def finish(self) -> dict:
        return self._call("finish")


def play(console: McpConsole) -> None:
    policy = os.environ.get("POLICY", "reference")
    if policy == "stop_early":
        solve(console, stop_after_tier=1)
    else:
        solve(console, policy=policy)
    print(json.dumps(console.status(), indent=2))


async def main() -> None:
    async with Client(MACHINE_URL) as client:
        await anyio.to_thread.run_sync(play, McpConsole(client))


if __name__ == "__main__":
    anyio.run(main)
