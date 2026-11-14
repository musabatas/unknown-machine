# Unknown Machine

An RL environment for the AfterQuery "Break the Agent" challenge at Junction 2026.

The last administrator of a legacy production system has left. There is no documentation and the system is down. The agent has one maintenance window to bring it back without losing data, and has to find the start-up order and the dependencies by experiment.

Design, scoring and timeline: [PLAN.md](PLAN.md). Rules for contributors and coding agents: [AGENTS.md](AGENTS.md).

## Status

Repository setup only. The simulator, the MCP server, the Harbor tasks and the one-command evaluation are not built yet; this file gets the reproduction command when they are.

## Development

```
poetry install
poetry run ruff check .
poetry run pytest
```
