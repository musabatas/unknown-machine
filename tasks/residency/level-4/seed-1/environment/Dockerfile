FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 python3-venv nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# The OpenCode agent, installed when the image is built. Harbor installs it at the
# start of every trial otherwise, and a slow package mirror then ends the trial in
# its setup timeout before the agent has made a single call. Harbor uses an agent it
# finds already installed.
RUN npm install -g opencode-ai && opencode --version

# MCP client for the reference solution. The agent may use it too.
RUN python3 -m venv /opt/mcp-client \
    && /opt/mcp-client/bin/pip install --no-cache-dir mcp==2.3.0

WORKDIR /app
