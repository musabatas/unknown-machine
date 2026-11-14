"""Reference run for the smoke task: the same three MCP tools the agent gets."""

import asyncio

from mcp import Client

MACHINE_URL = "http://machine:8000/mcp"


async def call(client: Client, tool: str, arguments: dict) -> None:
    result = await client.call_tool(tool, arguments)
    text = " ".join(block.text for block in result.content if hasattr(block, "text"))
    print(tool, arguments, "->", text, f"(is_error={result.is_error})")


async def main() -> None:
    async with Client(MACHINE_URL) as client:
        await call(client, "run", {"service": "kestrel", "command": "start"})
        await call(client, "run", {"service": "kestrel", "command": "serve"})
        await call(client, "status", {})
        await call(client, "finish", {})


if __name__ == "__main__":
    asyncio.run(main())
