FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# MCP client for the reference solution. The agent may use it too.
RUN python3 -m venv /opt/mcp-client \
    && /opt/mcp-client/bin/pip install --no-cache-dir mcp==2.3.0

WORKDIR /app
