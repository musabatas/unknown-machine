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
| Meaningful difficulty | 30 | Every hidden rule is discoverable through a safe probe; mistakes are logged as specific decisions (skipped probe, irreversible action first, ignored risk reading) |
| Reward integrity | 25 | Score computed only from server-side machine state; no credit for claims, doing nothing, or stopping early |
| Craft | 15 | Coherent device theme; one command reproduces all runs and the results table |

## 3. Environment design

### Setting

The agent commissions an undocumented laboratory device (thermal vacuum chamber controller). The operating manual is lost. The task statement gives the goal states and the complete tool list, and says plainly that the device's rules must be found by experiment and that some actions can cause permanent damage.

### Machine model

- 5 to 8 components (power stage, roughing pump, gate valve, heater, coolant loop, sensor head, ...), each with a small set of discrete modes.
- Each command has a guard: a condition on other components' modes. Guards are hidden.
- A command whose guard fails has one of three outcomes, fixed per rule:
  - **Refusal**: no state change, returns an opaque but consistent error code.
  - **Fault**: latches the component; cleared with `reset_fault` at a budget cost.
  - **Damage**: permanent; the component is lost for the rest of the episode.
- Part of the state is on the panel; the rest is only visible through `diagnose`.
- The machine is generated from a seed: dependency graph, guards, outcome types, error-code mapping. Templates keep it physically plausible (no heater before vacuum, and so on).

### Tools exposed over MCP

| Tool | Effect | Budget cost |
|---|---|---|
| `read_panel()` | Visible registers, banked tiers, remaining budget | 0 |
| `actuate(component, command)` | Attempts the command at full power | 1 |
| `probe(component, command)` | Low-power dry run: reports whether the command would succeed, be refused, fault, or damage. Never changes state | 2 |
| `diagnose(component)` | Reveals that component's hidden registers | 2 |
| `reset_fault(component)` | Clears a latched fault | 3 |
| `finish()` | Ends the episode | 0 |

`probe` is what makes the task fair: every damaging rule can be discovered without damage. The decision under test is where to spend budget on information.

### Goals and score

- Four tiers of target configurations, increasing in depth (T1 powered and idle, T2 vacuum held, T3 at temperature, T4 calibrated peak output).
- A tier is banked by the server the moment the machine is in that configuration.
- `score = sum(banked tier points) + handover bonus`, normalised to 0..1.
- Handover bonus: paid only if at least T1 is banked and no component is damaged at the end.
- Tier points: T1 0.10, T2 0.20, T3 0.25, T4 0.25, handover 0.20 (first guess; tune on data).
- Episode ends on `finish`, budget exhausted, or a damaged power stage.

### Phase 2 layer (only after the gate passes)

T4 carries a seed-dependent damage risk that depends on wear accumulated earlier. `diagnose` shows the margin. Attempting T4 with thin margin damages the device and forfeits the handover bonus. This adds a second failure mode: pushing for completion against a visible risk signal.

## 4. Reference run

`solution/solve.py`, an MCP client that uses the same six tools and nothing else:

1. Read the panel; diagnose every component once.
2. For each command not yet known safe in the current state, `probe` before `actuate`.
3. Record guard observations, generalise them into a guard table.
4. Plan the shortest safe path to the next tier on the learned model (BFS); re-probe only when the plan enters an unobserved state.
5. In phase 2: attempt T4 only if the diagnosed margin exceeds the learned threshold; otherwise `finish`.

It must run unchanged on every seed. That is the proof that the information needed is available.

## 5. Harbor integration

Verified against docs.harborframework.com on 2026-11-14:

- Task layout: `instruction.md`, `task.toml`, `environment/` (Dockerfile + `docker-compose.yaml`), `solution/solve.sh`, `tests/test.sh`.
- The machine runs as a sidecar service in `docker-compose.yaml` and is declared with `[[environment.mcp_servers]]` (`transport = "streamable-http"`, `url = "http://machine:8000/mcp"`).
- Local run: `harbor run -p <task> -a <agent> -m <model> -k <attempts>`; OpenCode is run as `--agent acp:opencode`; the `oracle` agent executes `solution/`.
- With a separate verifier environment, in-memory state is not visible to the verifier, so the server must write the episode result to a file.

Not verified; settle from the AfterQuery starter kit in hour 0:

- Whether OpenCode auto-registers MCP servers declared in `task.toml` (docs name Claude Code and Codex).
- The scoring skeleton's expected reward output format and location.
- How the do-nothing and stop-early baselines are invoked by the judges.
- Whether the verifier can hold a secret the agent container cannot read.

Consequence to design around: the agent container can reach the sidecar over HTTP, so the agent may script its own exploration loop. Budget, state and seed therefore live only in the sidecar.

## 6. Difficulty dials

In the order we turn them if the gap is too small:

1. Share of state hidden behind `diagnose`.
2. Guard depth (conditions on two components instead of one).
3. Number of damage rules on the path to T3 and T4.
4. Budget slack (never below what lets the reference finish at 70%).
5. Component count.

If the gap is too large for the wrong reason (agent cannot use the tools, misreads output), fix the interface, not the dials.

## 7. Reward red-team checklist

One person owns this from hour 2. Each item gets a test in `tests/exploits/`.

- New MCP session or reconnect does not reset the episode or the budget.
- Concurrent calls cannot overspend the budget (single lock, atomic decrement).
- Calls after the episode ends change nothing.
- No tool argument reaches hidden state (unknown component, wrong types, oversized input).
- Error messages and tracebacks leak no guards, seed or code paths.
- Agent container has no server source, no seed, no shared writable volume with the sidecar.
- Result file cannot be written from the agent container.
- Probe-everything strategy cannot finish all tiers within budget.
- Random and greedy-no-probe baselines stay under their targets on 50 seeds.
- `finish` at step 0 and after T1 score as specified.

## 8. Repository layout

```
unknown-machine/
  PLAN.md
  README.md                 one-command reproduction
  pyproject.toml            poetry
  machine/                  simulator core, pure Python, no I/O
    model.py                components, guards, outcomes
    generate.py             seed -> machine
    score.py
  server/                   MCP server wrapping one episode
  reference/                solver used by solution/
  baselines/                do-nothing, stop-early, random, greedy, probe-all
  tasks/unknown-machine-<seed>/   Harbor tasks, generated
  scripts/make_tasks.py     generator -> task directories
  scripts/eval.sh           runs reference, agent x3, baselines; prints table
  tests/                    simulator, determinism, exploits
  analysis/                 trajectory viewer, failure taxonomy
```

## 9. Timeline

Six people, roles A to F.

| Window | Work | Owner |
|---|---|---|
| H0-H1 | Read starter kit; run its example task end to end with OpenCode; answer section 5 unknowns with the mentors | A, B |
| H0-H2 | Simulator core with one hand-written machine; score function; determinism test | C, D |
| H0-H2 | Reference solver against the simulator core (in-process) | E |
| H1-H3 | MCP server + Harbor task wrapping the hand-written machine | A, B |
| H2-H4 | Seeded generator; baselines; reference passes on 20 seeds | C, D, E |
| H2-H6 | Exploit tests from section 7 | F |
| H4-H6 | Frontier agent, 3 seeds x 3 runs; read every trajectory; first failure taxonomy | A, B, E |
| **H6** | **Gate decision against section 1** | all |
| H6-H20 | Dials, phase 2 layer, trajectory viewer, `scripts/eval.sh`, README | split by area |
| H20-H36 | Stretch: fine-tune a small open model on reference trajectories from generated seeds, evaluate on held-out seeds | E + one |
| H36-end | Freeze code; rerun everything from a clean clone; demo and write-up | all |

## 10. Deliverables for judging

- One command that runs: reference, three agent runs, do-nothing, stop-early, and prints the table.
- Results table with per-seed scores and spread.
- Failure taxonomy: each agent mistake as (step, decision taken, decision available, cost in score), with trajectory excerpts.
- Exploit log: what we tried against our own reward and what we changed.
- 10-minute demo: the setting, one agent trajectory going wrong, the reference on the same seed, the table.

## 11. Risks

| Risk | Signal | Response |
|---|---|---|
| Frontier agent writes its own systematic explorer and matches the reference | Agent mean > 0.75 at the gate | Dials 1-3 once; if still closed, switch to fallback |
| Gap exists but for an unfair-looking reason | Trajectories show tool misuse or misread output | Fix tool descriptions and outputs; re-measure |
| Rules feel arbitrary to judges | Mentor review at H3 | Tighten physical templates; explain each rule in the README |
| Stretch goal eats core time | Core not frozen by H20 | Drop the stretch goal |
| Harness differs from the public Harbor docs | Found in H0-H1 | Follow the starter kit; update section 5 |
