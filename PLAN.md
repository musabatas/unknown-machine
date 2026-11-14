# Unknown Machine: prototype plan

Junction 2026, AfterQuery "Break the Agent". Challenge page: https://hackjunction.app/participate/45/challenges/328

## 1. Goal of the prototype

Answer one question within the first 6 hours: does a frontier agent (OpenCode on Harbor) score reproducibly below our scripted reference on this environment, for reasons we can tie to its decisions?

If yes, harden and extend. If no, turn the difficulty dials (section 6) once, re-measure, then switch to the fallback idea (Blind Desk).

Gate targets (our own thresholds, normalised score 0..1, 3 seeds, 3 agent runs each):

| Run | Target |
|---|---|
| Reference | >= 0.85 on every seed, using <= 70% of the budget |
| Frontier agent | mean <= 0.60, best run below the worst reference run |
| Do-nothing | 0 |
| Stop-early (finish after tier 1) | <= 0.20 |
| Random actions | <= 0.15 |

## 2. Rubric mapping

| Rubric item | Points | How the design earns it |
|---|---|---|
| The gap | 30 | Deterministic machine per seed, so agent and reference runs repeat exactly; reference is a script, not a human |
| Meaningful difficulty | 30 | Every hidden rule is discoverable through a dry run; mistakes are logged as specific decisions (skipped dry run, destructive command first, ignored lag reading) |
| Reward integrity | 25 | Score computed only from server-side system state; no credit for claims, doing nothing, or stopping early |
| Craft | 15 | Rules follow real operations logic (dependencies, start-up order); one command reproduces all runs and the results table |

## 3. Environment design

### Setting

The "machine" is an orphaned legacy production system. The last administrator has left, there is no documentation, and the system is down. The agent is the on-call engineer with one maintenance window to bring it back. The task statement gives the goal states and the complete tool list, and says plainly that start-up order and dependencies must be found by experiment and that some commands can destroy data.

Why this machine type: the failure it measures (running a destructive command without checking) is one agents make on real infrastructure, and every mechanic of the engine has a literal counterpart in operations work.

### Machine model

As built (`src/unknown_machine/machine/`):

- 5 to 8 services known only by codenames. Each has one role: storage, database, middleware, application or gateway. Codenames and roles are drawn per seed; every codename takes every role across seeds.
- A service comes up by applying its pending commands in a hidden order: two or three preparation commands (drawn from four per role, e.g. `fsck`, `migrate`, `drain`), then `start` (`cutover` for the gateway). Some commands also need other services serving. Dependencies follow the layers (database on storage, application on database and middleware, gateway on application), plus dependencies inside a layer.
- `inspect` lists the pending registers and the command that clears each, sorted by name, so it says which commands are needed but not their order or their dependencies.
- A command applied too early (`E_ORDER`) or before a service it needs (`E_DEP`) has one of three outcomes: refusal, crash loop (cleared by `restart`, adds 1 to replication lag), or permanent data loss.
- The outcome is fixed per service and per kind of mistake. This is the structure the task rewards learning: once a service has shown it only refuses, it can be run without dry runs; once it has shown it loses data, it never can. At least two services per system lose data on a wrong order.
- Each service also exposes two commands that are never needed and crash or destroy data, and the preparation commands it does not need (refused, harmless).
- One database carries replication lag (0 to 3 at the start). `sync` lowers it by 1; `cutover` with lag above 0 destroys the gateway's data.

### Tools exposed over MCP

| Tool | Effect | Budget cost (window minutes) |
|---|---|---|
| `status()` | Mode and command list of every service, banked tiers, remaining window | 0 |
| `run(service, command)` | Executes the command for real; charged whatever the outcome | 1 |
| `inspect(service)` | Role, pending registers with the command that clears each, replication lag | 2 |
| `dry_run(service, command)` | Reports whether the command would succeed, be refused, crash-loop, or lose data. Never changes state | 4 |
| `restart(service)` | Clears a crash loop | 4 |
| `finish()` | Ends the episode | 0 |

`dry_run` is what makes the task fair: every destructive rule can be discovered without destruction. The decision under test is where to spend the window on information.

A dry run costs four runs on purpose. At that price dry-running everything does not fit in the window, and never dry-running loses data, so the agent has to decide command by command. The window of each seed is the reference's own cost divided by 0.7.

### Goals and score

- Four tiers: T1 every storage service serving, T2 plus every database, T3 plus middleware and application, T4 plus the gateway (traffic cut over).
- A tier is banked by the server the moment it is reached and stays banked.
- `score = sum(banked tier points) - 0.15 per service that lost data`, clamped to 0..1.
- Tier points: T1 0.10, T2 0.15, T3 0.25, T4 0.50. Half the score is the cutover, because a system that is not taking traffic has not been recovered.
- The episode ends on `finish` or when the window is used up.

The handover bonus of the first draft was replaced by the data-loss penalty: the bonus let a run that stopped after tier 1 score 0.30, above our own stop-early target.

### Cutover decision

The lag rule is built in, not a later phase. With little window left, the cheap move is to run `cutover` without checking; if lag is not zero that destroys the gateway and costs 0.15. Stopping at tier 3 keeps 0.50.

## 4. Reference run

`src/unknown_machine/reference/solver.py`, copied into each task's `solution/` and driven over MCP with the same six tools and nothing else:

1. `inspect` every service once: roles, pending commands, initial lag.
2. Work layer by layer. For the next command of a service, list which mistakes are still possible: wrong order (more than one candidate left) and missing dependency (some service at or below its layer is not serving).
3. Dry-run first if the service's reaction to a possible mistake is unknown or is data loss. If the worst case is a crash, dry-run only when that is cheaper in expectation than risking a restart. If the worst case is a refusal, run directly.
4. Record what each failure teaches: the service's reaction to that kind of mistake, which command is not next, which command is blocked until another service comes up.
5. Before `cutover`, bring lag to zero with `sync`, counting its own crashes.

It runs unchanged on every seed and never loses data. That is the proof that the information needed is available.

Measured in-process over 300 seeds (`tests/test_baselines.py` enforces these on 100):

| Policy | Mean score | Notes |
|---|---|---|
| Reference | 1.00 | every seed, 70% of the window, no data loss |
| Dry-run everything | 0.52 | runs out of window, usually at tier 3 |
| Never dry-run | 0.14 | loses data on most seeds |
| Stop after tier 1 | 0.10 | |
| Random commands | 0.00 | |
| Do nothing | 0.00 | |

## 5. Harbor integration

Required by AfterQuery (organiser announcement on the Junction Discord, 2026-11-14). This overrides anything else in this section:

- Framework: Harbor (https://github.com/laude-institute/harbor). The environment is a Harbor task: `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/`, `solution/`.
- Harness: OpenCode, run as `harbor run -p ./my-task -a opencode -m <provider/model>`.
- Reward: the verifier writes one score between 0 and 1 to `/logs/verifier/reward.txt`. Partial credit is welcome.
- Submission must include at least one Harbor run log with its score, and a short README (what the agent has to do, why it is hard, how it is scored). A hand-written README is preferred.
- AfterQuery provides no inference credits. Frontier runs are paid from the team's Google, OpenAI and Modal credits.
- No scoring skeleton was distributed, so the implementation language inside the container is our choice.
- They explicitly want post-training experiments alongside the environment.

Verified by reading the installed Harbor 0.26.0 source on 2026-11-14 (`tasks/smoke` implements all of it):

- **Sidecar.** The agent container must be the compose service `main`; Harbor builds it from `environment/Dockerfile` and merges `environment/docker-compose.yaml` on top. Sidecars share the default network, so `main` reaches `http://machine:8000`. Harbor waits for sidecar health checks before starting the agent.
- **MCP.** `[[environment.mcp_servers]]` needs `transport = "streamable-http"` set explicitly (the default is `sse`). The `opencode` agent writes the server into its own config automatically, so no OpenCode config is shipped in the image. `opencode` cannot send MCP headers; `opencode-v2` can.
- **Verifier mode must be `shared`.** In `separate` mode Harbor tears the whole agent environment down, sidecars included, before the verifier starts, so the server-side score is gone. In `shared` mode `tests/test.sh` runs in `main` with the sidecar still up. `harbor lint` flags shared mode; that warning is accepted.
- **Score integrity in shared mode.** `/tests` is copied into `main` only after the agent has finished, and `[verifier.env]` reaches only the verifier command. The verifier therefore asks the sidecar for the result with a fresh nonce and checks an HMAC signature with a key the agent never sees; anything unverifiable scores 0. The key lives in the sidecar's compose environment and in `[verifier.env]`, never in `main`.
- **Reward.** Harbor reads `/logs/verifier/reward.json` first, then `reward.txt`; any finite float is accepted and a missing file counts as 0. We write `reward.txt` and enforce 0..1 ourselves.
- **Baselines.** `-a nop` is a built-in agent that does nothing; `-a oracle` runs `solution/solve.sh`. Both ignore MCP server declarations.
- **Model strings.** Gemini must be `-m gemini/<model>` (with `google/<model>` no API key is forwarded into the container); OpenAI is `-m openai/<model>` with `OPENAI_API_KEY`.

Not verified:

- How the judges invoke the stop-early baseline.
- How a frontier model scores. Only `openai/gpt-5.4-mini` has been run so far (section 11).
- The result key is a constant in the task files. An agent with network access could read it if the repository is public; generate it per run before the repository is opened.

Consequence to design around: the agent container can reach the sidecar over HTTP, so the agent may script its own exploration loop. Budget, state and seed therefore live only in the sidecar.

## 6. Difficulty dials

In the order we turn them if the gap is too small:

1. `REFERENCE_WINDOW_SHARE` in `calibration.py` (0.7): raise it and the window shrinks. Never above what leaves the reference clear slack.
2. `COST_DRY_RUN` in `model.py` and `solver.py` (4): the price of information.
3. `VIOLATION_WEIGHTS` and `MIN_FRAGILE` in `generate.py`: how many services destroy data on a mistake.
4. Preparation commands per service (2 or 3) and service count (5 to 8).
5. `PREP_STEP_NEEDS_DEPENDENCY` and `SAME_LAYER_DEPENDENCY`: how often order inside a layer matters.

After turning a dial: regenerate tasks, rerun `pytest`, and re-pick `EVALUATION_SEEDS` so the naive policies still stay at or below 0.5 on them.

If the gap is too large for the wrong reason (agent cannot use the tools, misreads output), fix the interface, not the dials.

## 7. Reward red-team checklist

Status of each item. "Tested" means a test in `tests/` fails if it regresses.

| Item | Status |
|---|---|
| Reconnecting or finishing twice does not reset the episode or the window | Tested |
| Concurrent calls cannot overspend the window | Tested |
| Calls after the episode ends change and cost nothing | Tested |
| Malformed arguments (wrong type, oversized, unknown names) are refused free and leak nothing | Tested; found and fixed a crash on a null command |
| Tool results never contain hidden rule fields | Tested |
| Codenames carry no hint of the role | Tested |
| Dry-running everything earns nothing by itself and cannot finish in the window | Tested |
| Random and never-dry-run policies stay under their targets | Tested on 100 seeds |
| `finish` at step 0 scores 0, after tier 1 scores 0.10 | Tested |
| A forged, replayed or out-of-range result is rejected by the verifier | Tested |
| Agent container has no server source, seed or shared volume with the sidecar | By construction of the compose file; not tested |
| The agent cannot write the reward: `/tests` arrives only after it has finished and the score must carry the sidecar's signature | By Harbor's order of operations (read in its source); not tested against a hostile agent |
| The signing key is a constant in the task files | Open: readable by an agent with network access once the repository is public |
| The agent container has public network access | Open: lets an agent download our own solver if the repository is public |

## 8. Repository layout

```
unknown-machine/
  PLAN.md
  AGENTS.md                 repository contract
  README.md                 one-command reproduction
  pyproject.toml            poetry
  src/unknown_machine/
    machine/                simulator core, pure Python, no I/O
      model.py              services, steps, tool costs
      generate.py           seed -> system
      episode.py            mutable state of one episode, the six tools
      score.py
    calibration.py          seed -> episode with its window
    server/app.py           MCP server and control port around one episode
    reference/solver.py     reference and scripted policies; standard library only
    baselines/policies.py   do-nothing, stop-early, cautious, greedy, random
  scripts/task_template/    the Harbor task every seed is generated from
  scripts/make_tasks.py     template + package -> tasks/seed-<n>/
  scripts/eval.sh           one command: reference, baselines, optional agent runs
  tasks/seed-<n>/           generated evaluation tasks (seeds 0 to 4)
  tasks/smoke/              hand-maintained harness smoke test
  tests/                    simulator rules, baseline scores, exploits
  analysis/analyze.py       episode log -> decisions that cost score or window
```

## 9. Status

As of Saturday 14 Nov. Hacking opened Friday 13 Nov 19:30; submissions opened Saturday 14 Nov 12:00.

| Work | State |
|---|---|
| Harbor installed; sidecar, MCP, signed result and reward file proven on `tasks/smoke` with oracle, nop and OpenCode | Done |
| Simulator core, seeded generator, score | Done |
| Reference solver and scripted baselines | Done |
| MCP server, task template, generator, five evaluation tasks | Done |
| Tests for simulator rules, baseline scores and exploits | Done (34 tests) |
| One-command evaluation and episode analysis | Done |
| **Gate: frontier agent, 3 runs per task, against section 1** | **Open: needs paid runs** |
| Read the frontier trajectories; write the failure taxonomy from `analysis/analyze.py` output | Open, after the gate |
| Turn dials if the gate fails (section 6) | Open, after the gate |
| Post-training experiment: fine-tune a small open model on reference trajectories, evaluate on held-out seeds | Open: `scripts/export_trajectories.py` produces the data; training not started |
| Hand-written README, demo video, submission | Open: team |
| Rotate the signing key per run and cut the agent's network before opening the repository | Open |

## 10. Deliverables for judging

- At least one Harbor run log with its score, showing a model playing the environment (required for submission).
- A short hand-written README: what the agent has to do, why it is hard, how it is scored (required for submission).
- One command that runs: reference, three agent runs, do-nothing, stop-early, and prints the table.
- Results table with per-seed scores and spread.
- Failure taxonomy: each agent mistake as (step, decision taken, decision available, cost in score), with trajectory excerpts.
- Exploit log: what we tried against our own reward and what we changed.
- 10-minute demo: the setting, one agent trajectory going wrong, the reference on the same seed, the table.

Judging context (Junction participant guide): the challenge prize is decided by AfterQuery on the rubric above. Peer review only selects finalists for the separate main prize, so the pitch for other participants needs the one-line story ("the last admin left; bring the system back without losing data"), not a different environment.

## 11. Agent runs so far

| Date | Task | Agent | Score | What happened | Cost |
|---|---|---|---|---|---|
| 2026-11-14 | seed-0 | OpenCode, `openai/gpt-5.4-mini` | 0.00 | Inspected all seven services, then ran pending commands directly, never dry-running. Three services came up because their wrong-order mistakes were only refused. It treated the fourth the same way: `migrate` on the second database, out of order, destroyed its data (0.10 for tier 1, minus 0.15). It called `finish` at once, with 119 of 146 minutes unused | USD 0.08 |

The mistake is the one the task is built around: two refusals on one service were taken as evidence about a different service. One run of a small model is not evidence about a frontier model; the gate needs the frontier runs.

## 12. Risks

| Risk | Signal | Response |
|---|---|---|
| Frontier agent writes its own systematic explorer and matches the reference | Agent mean > 0.75 at the gate | Dials 1-3 once; if still closed, switch to fallback |
| Operations is the agent's strongest domain: it dry-runs everything by habit and stays safe | Agent never loses data but runs out of window below T3 or T4 | This is still a gap if the reference finishes; if the agent also finishes, tighten the window (dial 4) and raise hidden state (dial 1) |
| Gap exists but for an unfair-looking reason | Trajectories show tool misuse or misread output | Fix tool descriptions and outputs; re-measure |
| Rules feel arbitrary to judges | Mentor review at H3 | Tighten operational templates; explain each rule in the README |
| Codenames leak roles, so prior knowledge replaces exploration | Agent reaches T2 without `inspect` or `dry_run` | Regenerate the codename list; add the leak check to the exploit tests |
| Post-training experiment eats core time | Core not frozen by H20 | Cut it to one small run; never at the cost of the reproducible evaluation |
| Harness differs from the public Harbor docs | Found in H0-H1 | Follow the organiser announcement and the mentors; update section 5 |
| Frontier runs exhaust the team's own credits | Spend tracked per run from the first gate run | Develop against the in-process simulator and scripted baselines; batch frontier runs; fix seeds and run count before starting |
