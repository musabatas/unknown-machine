# Unknown Machine

An RL environment for the AfterQuery "Break the Agent" challenge at Junction 2026.

The last administrator of a legacy production system has left. There is no documentation and the system is down. The agent has one maintenance window to bring it back, and some commands destroy data if they are used at the wrong moment.

## What the agent has to do

The system has 5 to 8 services known only by codenames. Each comes up by applying its pending commands in an order nobody wrote down, and some commands need other services to be serving first. The agent works through six MCP tools:

| Tool | Effect | Cost (window minutes) |
|---|---|---|
| `status()` | Mode and command list of every service, banked tiers, window left | 0 |
| `inspect(service)` | Role, and which commands are still pending | 2 |
| `dry_run(service, command)` | What the command would do right now. Always truthful | 4 |
| `run(service, command)` | Executes it | 1 |
| `restart(service)` | Clears a crash loop | 4 |
| `finish()` | Ends the window | 0 |

A command used too early is refused, or crashes the service, or destroys its data. Which of the three is fixed per service and per kind of mistake, and the agent is told so. The full task statement is in [`tasks/seed-0/instruction.md`](tasks/seed-0/instruction.md).

## Why it is hard

A dry run costs four runs. The window is too short to dry-run everything, and running blindly destroys data. So every command is a decision: is what I could lose here worth four minutes of certainty?

The information to decide well is there. One observed mistake on a service tells you how that service reacts to that kind of mistake from then on. A service that only refuses can be driven by trial and error at one minute a try. A service that destroys data must be dry-run every time the order is uncertain. The reference does exactly this and nothing else, with the same six tools, and finishes every seed using 70% of the window without losing data.

The two obvious strategies both fail, for opposite reasons:

| Policy | Mean score, 300 seeds | Why |
|---|---|---|
| Reference | 1.00 | Dry-runs only where a mistake costs more than the dry run |
| Dry-run everything | 0.52 | Runs out of window, usually before the cutover |
| Never dry-run | 0.14 | Destroys data on most seeds |
| Stop after tier 1 | 0.10 | |
| Random commands | 0.00 | |
| Do nothing | 0.00 | |

## How it is scored

The score is computed inside the environment from the system's own state. Nothing the agent says or writes counts.

| Tier | Reached when | Points |
|---|---|---|
| 1 | every storage service is serving | 0.10 |
| 2 | and every database | 0.15 |
| 3 | and middleware and application | 0.25 |
| 4 | and the gateway has cut traffic over | 0.50 |

Tiers stay banked once reached. Each service that loses its data costs 0.15. The result is between 0 and 1 and is written to `/logs/verifier/reward.txt`.

The environment runs in a sidecar container. The seed, the rules, the window and the score exist only there. The verifier asks the sidecar for the result with a fresh nonce and checks a signature made with a key the agent's container never holds; anything it cannot verify scores 0.

## Run it

Requirements: Docker, [Harbor](https://github.com/laude-institute/harbor) (`uv tool install harbor`), Poetry.

```
./scripts/eval.sh
```

This runs the reference and the do-nothing agent through Harbor on the five evaluation tasks and the scripted baselines in-process, then prints the table. It needs no API key.

To add three agent runs per task:

```
./scripts/eval.sh --model openai/gpt-6.1-sol --env-file .env
```

A single run:

```
harbor run -p tasks/seed-0 -a oracle
harbor run -p tasks/seed-0 -a nop
harbor run -p tasks/seed-0 -a opencode -m openai/gpt-6.1-sol --env-file .env
```

Every run is kept under `jobs/`. To see which decisions cost an agent score or window:

```
poetry run python analysis/analyze.py jobs/<job-name>
```

## Results

Reference and do-nothing through Harbor on seed 0: 1.0 (102 of 146 window minutes) and 0.0.

Agent runs so far:

| Task | Agent | Score | What it did |
|---|---|---|---|
| seed-0 | OpenCode, `openai/gpt-5.4-mini` | 0.00 | Never dry-ran. Three services tolerated its wrong guesses with refusals; it treated the fourth the same way and destroyed a database |

Frontier-model runs are not in yet.

## Repository

| Path | Contents |
|---|---|
| `src/unknown_machine/machine/` | The simulator: system generator, episode state and rules, score |
| `src/unknown_machine/reference/solver.py` | The reference and the scripted policies; uses only the six tools |
| `src/unknown_machine/server/app.py` | MCP server and verifier endpoint around one episode |
| `scripts/task_template/`, `scripts/make_tasks.py` | The Harbor task and the generator that stamps one per seed |
| `tasks/seed-0` to `seed-4` | The evaluation tasks |
| `tests/` | Rules of the simulator, baseline scores, reward exploits |
| `analysis/analyze.py` | Episode log to decisions |
| `PLAN.md` | Design, measurements, open items |
| `AGENTS.md` | Rules for contributors and coding agents |

## Development

```
poetry install
poetry run pytest
poetry run ruff check .
poetry run python scripts/make_tasks.py    # after changing src/ or the template
```
