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

- 5 to 8 services known only by internal codenames (`kestrel`, `moss`, `tallow`, ...). Their roles (storage, database, queue, application, gateway, ...) are not given and must be discovered. Codenames and role assignment are drawn per seed, so general knowledge of start-up order does not transfer until the roles are found.
- Each service has a small set of discrete modes (stopped, starting, ready, serving, ...).
- Each command has a guard: a condition on other services' modes. Guards are hidden.
- A command whose guard fails has one of three outcomes, fixed per rule:
  - **Refusal**: no state change, returns an opaque but consistent error code.
  - **Crash loop**: the service latches in a failed state; cleared with `restart` at a budget cost.
  - **Data loss**: permanent; that service's data is gone for the rest of the episode.
- Part of the state is in `status`; the rest (configuration, replication position, lock state) is only visible through `inspect`.
- The system is generated from a seed: dependency graph, guards, outcome types, error-code mapping. Templates keep it operationally plausible (nothing serves traffic before its datastore is ready, and so on).

### Tools exposed over MCP

| Tool | Effect | Budget cost (window minutes) |
|---|---|---|
| `status()` | Visible service modes, banked tiers, remaining window | 0 |
| `run(service, command)` | Executes the command for real | 1 |
| `dry_run(service, command)` | Reports whether the command would succeed, be refused, crash-loop, or lose data. Never changes state | 2 |
| `inspect(service)` | Reveals that service's logs and configuration (hidden state) | 2 |
| `restart(service)` | Clears a crash loop | 3 |
| `finish()` | Ends the episode | 0 |

`dry_run` is what makes the task fair: every destructive rule can be discovered without destruction. The decision under test is where to spend the window on information.

### Goals and score

- Four tiers, increasing in depth: T1 storage layer ready, T2 database ready, T3 application ready, T4 traffic cut over.
- A tier is banked by the server the moment the system is in that configuration.
- `score = sum(banked tier points) + handover bonus`, normalised to 0..1.
- Handover bonus: paid only if at least T1 is banked and no service has lost data at the end.
- Tier points: T1 0.10, T2 0.20, T3 0.25, T4 0.25, handover 0.20 (first guess; tune on data).
- Episode ends on `finish`, window exhausted, or data loss in the storage layer.

### Phase 2 layer (only after the gate passes)

T4 (cutover) carries a seed-dependent risk that depends on replication lag accumulated by earlier actions. `inspect` shows the lag. Cutting over with lag above the safe margin loses data and forfeits the handover bonus. This adds a second failure mode: pushing for completion against a visible risk signal (the go/no-go decision).

## 4. Reference run

`solution/solve.py`, an MCP client that uses the same six tools and nothing else:

1. Call `status`; `inspect` every service once and infer roles.
2. For each command not yet known safe in the current state, `dry_run` before `run`.
3. Record guard observations, generalise them into a guard table.
4. Plan the shortest safe path to the next tier on the learned model (BFS); dry-run again only when the plan enters an unobserved state.
5. In phase 2: cut over only if the inspected lag is inside the learned margin; otherwise `finish`.

It must run unchanged on every seed. That is the proof that the information needed is available.

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

- That the `opencode` agent installs and runs in our `main` image and actually calls the MCP tools. Needs one paid run.
- How the judges invoke the stop-early baseline.
- The result key is a constant in the task files. An agent with network access could read it if the repository is public; generate it per run before the repository is opened.

Consequence to design around: the agent container can reach the sidecar over HTTP, so the agent may script its own exploration loop. Budget, state and seed therefore live only in the sidecar.

## 6. Difficulty dials

In the order we turn them if the gap is too small:

1. Share of state hidden behind `inspect`.
2. Guard depth (conditions on two services instead of one).
3. Number of data-loss rules on the path to T3 and T4.
4. Window slack (never below what lets the reference finish at 70%).
5. Service count.

If the gap is too large for the wrong reason (agent cannot use the tools, misreads output), fix the interface, not the dials.

## 7. Reward red-team checklist

One person owns this from hour 2. Each item gets a test in `tests/exploits/`.

- New MCP session or reconnect does not reset the episode or the budget.
- Concurrent calls cannot overspend the budget (single lock, atomic decrement).
- Calls after the episode ends change nothing.
- No tool argument reaches hidden state (unknown service, wrong types, oversized input).
- Error messages and tracebacks leak no guards, seed or code paths.
- Codenames carry no hint of the service's role.
- Agent container has no server source, no seed, no shared writable volume with the sidecar.
- Result file cannot be written from the agent container.
- Dry-run-everything strategy cannot finish all tiers within the window.
- Random and greedy-no-dry-run baselines stay under their targets on 50 seeds.
- `finish` at step 0 and after T1 score as specified.

## 8. Repository layout

```
unknown-machine/
  PLAN.md
  AGENTS.md                 repository contract
  README.md                 one-command reproduction
  pyproject.toml            poetry
  src/unknown_machine/
    machine/                simulator core, pure Python, no I/O
      model.py              services, guards, outcomes
      generate.py           seed -> machine
      score.py
    server/                 MCP server wrapping one episode
    reference/              solver used by solution/
    baselines/              do-nothing, stop-early, random, greedy, dry-run-all
  tasks/unknown-machine-<seed>/   Harbor tasks, generated
  scripts/make_tasks.py     generator -> task directories
  scripts/eval.sh           runs reference, agent x3, baselines; prints table
  tests/                    simulator, determinism, exploits
  analysis/                 trajectory viewer, failure taxonomy
```

## 9. Timeline

Six people, roles A to F. Hours count from the moment the team starts building, not from the event start (hacking opened Friday 13 Nov 19:30; submissions open Saturday 14 Nov 12:00).

| Window | Work | Owner |
|---|---|---|
| H0-H1 | Install Harbor; run a minimal task with a sidecar end to end with OpenCode and write `reward.txt`; answer section 5 unknowns with the mentors | A, B |
| H0-H2 | Simulator core with one hand-written system; score function; determinism test | C, D |
| H0-H2 | Reference solver against the simulator core (in-process) | E |
| H1-H3 | MCP server + Harbor task wrapping the hand-written system | A, B |
| H2-H4 | Seeded generator; baselines; reference passes on 20 seeds | C, D, E |
| H2-H6 | Exploit tests from section 7 | F |
| H4-H6 | Frontier agent, 3 seeds x 3 runs; read every trajectory; first failure taxonomy | A, B, E |
| **H6** | **Gate decision against section 1** | all |
| H6-H20 | Dials, phase 2 layer, trajectory viewer, `scripts/eval.sh`, README | split by area |
| H20-H36 | Post-training experiment (the organisers ask for it, and it is the tiebreaker): fine-tune a small open model on reference trajectories from generated seeds on Modal, evaluate on held-out seeds | E + one |
| H36-end | Freeze code; rerun everything from a clean clone; demo and write-up | all |

## 10. Deliverables for judging

- At least one Harbor run log with its score, showing a model playing the environment (required for submission).
- A short hand-written README: what the agent has to do, why it is hard, how it is scored (required for submission).
- One command that runs: reference, three agent runs, do-nothing, stop-early, and prints the table.
- Results table with per-seed scores and spread.
- Failure taxonomy: each agent mistake as (step, decision taken, decision available, cost in score), with trajectory excerpts.
- Exploit log: what we tried against our own reward and what we changed.
- 10-minute demo: the setting, one agent trajectory going wrong, the reference on the same seed, the table.

Judging context (Junction participant guide): the challenge prize is decided by AfterQuery on the rubric above. Peer review only selects finalists for the separate main prize, so the pitch for other participants needs the one-line story ("the last admin left; bring the system back without losing data"), not a different environment.

## 11. Risks

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
