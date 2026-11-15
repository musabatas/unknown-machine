# Unknown Machine

An RL environment for the AfterQuery "Break the Agent" challenge at Junction 2026.

The last administrator of a legacy production system has left. There is no documentation and the system is down. The agent has one maintenance window to bring it back, and some commands destroy data if they are used at the wrong moment.

## The task to run

The submitted task is **`tasks/level-4/seed-0`**:

```
harbor run -p tasks/level-4/seed-0 -a opencode -m openai/gpt-6.1-sol --env-file .env
harbor run -p tasks/level-4/seed-0 -a oracle                           # reference: 1.0
harbor run -p tasks/level-4/seed-0 -a nop                              # do nothing: 0.0
harbor run -p tasks/level-4/seed-0 -a oracle --ae POLICY=stop_early    # stop early: 0.1
```

Or all of it in one command, which runs the reference, do-nothing, stop-early and three agent runs through Harbor and prints the table:

```
./scripts/eval.sh --level 4 --seeds 0 --model openai/gpt-6.1-sol --env-file .env
```

That command, run on 2026-11-14 (`runs/eval-1114-174254-legacy-l4s0-*`):

| Reference | Do nothing | Stop early | `gpt-6.1-sol`, three runs |
|---|---|---|---|
| 1.00 | 0.00 | 0.10 | 0.00, 0.00, 0.00 |

All three agent runs ended by their own `finish`, with no error. Each destroyed a service's data with a command it had not checked. A smaller model, `gpt-5.4-mini`, scored 0.10 on the same task for the opposite reason: it destroyed nothing and spent the whole window on dry runs. The repository holds more tasks than this one: four levels of difficulty with five seeds each, and the hardest two levels again in two other scenarios. Levels 1 and 2 are solved by a frontier model and are here to show where the difficulty comes from, not to be judged on. Everything below explains the task, the levels and the measurements.

## What the agent has to do

The system's services are known only by codenames. Each comes up by applying its pending commands in an order nobody wrote down, and some commands need other services to be serving first. The agent works through six MCP tools:

| Tool | Effect | Cost (window minutes) |
|---|---|---|
| `status()` | Mode and command list of every service, banked tiers, window left | 0 |
| `inspect(service)` | Role, which commands are still pending, how reliable its dry runs are | 2 |
| `dry_run(service, command)` | What the command would do right now | 4 |
| `run(service, command)` | Executes it | 1 |
| `restart(service)` | Clears a crash loop | 4 |
| `finish()` | Ends the window | 0 |

A command used too early is refused, or crashes the service, or destroys its data. Which of the three is fixed per service and per kind of mistake, and the agent is told so. The full task statement is in [`tasks/level-1/seed-0/instruction.md`](tasks/level-1/seed-0/instruction.md); it is the same at every level.

There are four levels. The tools, their costs and the score do not change between them.

| Level | System | Dry runs |
|---|---|---|
| 1 | 5 to 8 services, 2 or 3 preparation commands each | Always right |
| 2 | Same | Right 70% to 100% of the time, depending on the service |
| 3 | 12 to 14 services, 3 or 4 preparation commands each | As level 2 |
| 4 | As level 3, and at least four services must wait for another service of their own layer, and lose their data if started without it | As level 2 |

Above level 1 `inspect` tells the agent how reliable each service's dry runs are. Every dry run is wrong independently of the others, so repeating one buys certainty at four minutes a repeat. A dry run can only be wrong about whether a command can be applied now; how the service reacts to a mistake is always reported truthfully, and `run` is always real.

## Why it is hard

A dry run costs four runs. The window is too short to dry-run everything, and running blindly destroys data. So every command is a decision: is what I could lose here worth four minutes of certainty? Above level 1 it is also a question of how many: one report from a service that is right 70% of the time is not enough to stake its data on, and five reports on every command do not fit in the window.

The information to decide well is there. One observed mistake on a service tells you how that service reacts to that kind of mistake from then on. A service that only refuses can be driven by trial and error at one minute a try. A service that destroys data must be dry-run whenever the order is uncertain, as often as its reliability demands. The reference does exactly this and nothing else, with the same six tools. The window of every task is the reference's own cost divided by 0.7, so it always finishes with 30% to spare.

The two obvious strategies both fail, for opposite reasons. Mean score in the simulator, over the first 300 seeds at levels 1 and 2 and the first 60 at levels 3 and 4:

| Policy | Level 1 | Level 2 | Level 3 | Level 4 | Why |
|---|---|---|---|---|---|
| Reference | 1.00 | 0.99 | 1.00 | 1.00 | Buys certainty only where a mistake costs more than the dry runs |
| One dry run before every command | 0.54 | 0.25 | 0.03 | 0.01 | Runs out of window; above level 1 it also acts on wrong reports |
| Never dry-run | 0.15 | 0.15 | 0.00 | 0.00 | Destroys data on almost every seed |
| Stop after tier 1 | 0.10 | 0.10 | 0.10 | 0.10 | |
| Random commands | 0.00 | 0.00 | 0.00 | 0.00 | |
| Do nothing | 0.00 | 0.00 | 0.00 | 0.00 | |

Two things these numbers do not say by themselves:

- **The reference is not perfect where dry runs can be wrong.** It runs a command once the chance of destroying data is below 0.2%, and that risk is real: at level 2 it lost data on 2 of the 300 seeds. At level 1 it never does.
- **The evaluation tasks are selected seeds.** Per level they are the first five seeds on which the reference scores 1.0 and neither naive strategy scores above 0.5; about two seeds in three qualify. The table above is over all seeds, selected or not. The rule is a test in `tests/test_baselines.py`.

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

This runs the reference, the do-nothing agent and the stop-early baseline through Harbor on the twenty evaluation tasks (five per level) and the other scripted baselines in-process, then prints the table. It needs no API key.

To add three agent runs per task:

```
./scripts/eval.sh --model openai/gpt-6.1-sol --env-file .env
```

Both run all four levels; `--level 3` limits them to one, `--seeds 3` to one task, and `--theme aircraft` or `--theme residency` runs the other scenarios. Run agent evaluations one task at a time: nine concurrent agent runs exceeded the provider's rate limit.

A single run:

```
harbor run -p tasks/level-4/seed-3 -a oracle                           # reference, 1.0
harbor run -p tasks/level-4/seed-3 -a nop                              # do nothing, 0.0
harbor run -p tasks/level-4/seed-3 -a oracle --ae POLICY=stop_early    # stop after tier 1, 0.1
harbor run -p tasks/level-4/seed-3 -a opencode -m openai/gpt-6.1-sol --env-file .env
```

Every run is kept under `jobs/`. To see which decisions cost an agent score or window:

```
poetry run python analysis/analyze.py jobs/<job-name>
```

To watch a run live while the agent is playing it, start this next to `harbor run` and open the address it prints:

```
poetry run python scripts/watch.py                              # the Harbor run in progress
poetry run python scripts/watch.py --demo reference --level 3   # a scripted policy, no API key
```

The page shows one tile per run, all live, and each run's actions as they happen on the layered system with the hidden rules beside them. The state is read from inside the sidecar, so no sidecar port is opened. The page itself is a server on the host, which an agent's container can reach (checked: it can), and it shows hidden rules; so every address sits under a secret drawn at start and printed only in the terminal, and anything else answers 404 (also checked from inside a container).

To replay a finished episode step by step:

```
poetry run python scripts/make_replay.py jobs/<job-name> --out replays/
```

This writes one self-contained HTML page per episode; open it by double-click. `viewer/samples/` holds six recorded episodes of the scripted policies.

## Results

Through Harbor, the reference scores 1.0 and the do-nothing agent 0.0 on all five level 1 tasks. The reference also scores 1.0 on `level-2/seed-0` (252 of 360 window minutes) and `level-3/seed-3` (499 of 713).

Agent runs so far, one run each:

| Task | Agent | Score | Window used | What it did |
|---|---|---|---|---|
| `level-1/seed-0` | OpenCode, `openai/gpt-5.4-mini` | 0.00 | 27 of 146 | Never dry-ran. Three services tolerated its wrong guesses with refusals; it treated the fourth the same way and destroyed a database |
| `level-1/seed-0` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 85 of 146 | Solved it, in less window than the reference (102) |
| `level-2/seed-0` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 282 of 360 | Solved it by repeating dry runs; used more window than the reference (252) |
| `level-3/seed-3` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 339 of 713 | Solved it in far less window than the reference (499). It took single dry runs where the worst case was a crash, and ran every `start` unchecked |
| `level-3/seed-0` | OpenCode, `openai/gpt-6.1-sol` | 0.00 | 1073 of 1443 | Ran `start` on a database unchecked while another service of the same layer was still down; that was a dependency, and the data was gone. The reference scores 1.0 here in 1010 minutes |
| `level-3/seed-1` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 560 of 800 | Solved it in the reference's own window use |
| `level-3/seed-2` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 817 of 1050 | Solved it; the reference used 735 |
| `level-3/seed-4` | OpenCode, `openai/gpt-6.1-sol` | 1.00 | 1018 of 1123 | Solved it with 231 dry runs and little window to spare; the reference used 786 |
| `level-4/seed-3` | OpenCode, `openai/gpt-6.1-sol` | 0.00 | 884 of 1195 | The system it solved at level 3. Seven unchecked commands went through; the eighth, `start` on a database, destroyed its data. The reference scores 1.0 in 836 minutes |

Levels 1 and 2 do not separate a frontier model from the reference. At level 3, over the five evaluation seeds with one run each, the model averages 0.80 against the reference's 1.00, and the whole difference is seed 0.

The reason is one habit. The model checks the order of a service's commands carefully, and it runs `start` unchecked as soon as the layer below is up, although the task says a command may need any other service. Whether that costs anything depends on the system: the order in which it brings a layer up meets a dependency that destroys data on seed 0 and on no other level 3 seed. That was read off the systems before the runs on seeds 0, 1, 2 and 4, and all four went as predicted. Level 4 puts such dependencies into every system.

Level 4, `gpt-6.1-sol` against the reference's 1.00 on every task. Complete runs only: each ended by the agent's own `finish`, with no error.

| Task | Complete runs | Scores | Runs that destroyed data |
|---|---|---|---|
| `level-4/seed-0` (submitted) | 6 | 0.00 six times | 6 |
| `level-4/seed-1` | 3 | 1.00, 0.10, 1.00 | 1 |
| `level-4/seed-2` | 3 | 0.00, 0.00, 1.00 | 2 |
| `level-4/seed-3` | 4 | 0.00, 1.00, 1.00, 0.00 | 2 |
| `level-4/seed-4` | 3 | 1.00, 0.10, 1.00 | 1 |

Nineteen complete runs, mean 0.38, and twelve of them destroyed a service's data. Read this with its limits:

- **The gap is not the same on every task.** On seed 0 the model lost data in every one of six complete runs, from two separate invocations of the evaluation command. On the other four seeds it solved the task in eight runs of thirteen and lost data in the other five. Level 4 does not lock the model out; it makes the unchecked `start` expensive often enough to halve its score, and on seed 0 the model's order of work meets such a dependency every time.
- **The same task swings between 1.00 and 0.00 across identical runs.** Three runs per task are few; the per-task means above are rough.
- **Five further runs are not in the table.** They come from a batch of nine started at once on seeds 0, 1 and 2, none of which reached `finish`: the provider's rate limit ended two and the account's spending limit ended seven. Five of them (three on seed 0, two on seed 2) had already destroyed a database when they were cut off, so their score of 0.00 could not have changed; the other four were cut off with no data lost and prove nothing.

Other models on the submitted task, one complete run each through OpenCode:

| Model | Score | What happened |
|---|---|---|
| `big-pickle` (OpenCode Zen) | 1.00 | Solved it: every tier, nothing destroyed, 1157 of 1170 minutes in 364 calls. The reference uses 819 |
| `gemini-3.8-flash` | 0.25 | Destroyed nothing, reached tier 2, used 1155 of 1170 minutes |
| `gpt-6-luna` | 0.25 | Destroyed nothing, reached tier 2, used 1158 of 1170 minutes |
| `gpt-5.4-mini` | 0.10 | Destroyed nothing, reached tier 1, used the whole window |
| `deepseek-v4-pro` | 0.00 | Destroyed two services' data before any tier |
| `deepseek-v4.1-flash` | 0.00 | Destroyed a storage service's data before any tier |

One of the six models solved the submitted task in its single run. That is the evidence that the task is solvable by an agent through OpenCode and not only by the scripted reference; it also means the gap is a property of the model as much as of the task.

The same system in the other two scenarios (same structure, window and reference run, other words), `gpt-6.1-sol`, three complete runs each, every one ended by `finish` with no error:

| Task | Scores | What happened |
|---|---|---|
| `level-4/seed-0` (legacy, submitted) | 0.00 six times | Above |
| `aircraft/level-4/seed-0` | 0.00, 1.00, 0.00 | Both zeros banked tier 1 and then destroyed data (one service, then two) and stopped early, after 210 and 310 of 1170 minutes |
| `residency/level-4/seed-0` | 1.00, 1.00, 1.00 | Solved in 860, 975 and 944 of 1170 minutes |

So the six zeros on the legacy wording do not carry over to every wording of the same system: the model lost it six times of six in one wording, twice of three in another and never in the third. A theme changes only words (role names, command names, codenames), so the model's choice of which command to run unchecked depends on what the commands are called. Three runs per scenario are few, and this was not investigated further.

The logs of the counted runs are in `runs/`.

### The mistake, step by step

`level-4/seed-3`, the database `bramble` (dry runs right 80% of the time; destroys its data on a wrong order and on a missing dependency). From `runs/l4s3-gpt61sol-1`, the server's own log:

| Step | Action | Result |
|---|---|---|
| 59 | `dry_run bramble start` | `data_loss`, `E_ORDER` |
| 60-65 | `dry_run bramble recover`, six times | `ok` five times; once `data_loss`, `E_DEP` |
| 66 | `run bramble recover` | `ok` |
| 67-75 | nine dry runs on `unlock` and `reindex` | `reindex` is next; one report again says `data_loss`, `E_DEP` |
| 76 | `run bramble reindex` | `ok` |
| 77 | `run bramble unlock` | `ok`. Not checked: it was the only preparation command left |
| 78 | `run bramble start` | **`data_loss`, `E_DEP`**. Not checked: it was the only command left |

The model spent sixteen dry runs, 64 minutes, making sure of the order, and it was right about the order every time. By step 69 it had been shown twice what this service does when a dependency is missing. At step 78 two of the three databases were still down, so a missing dependency was possible, and `start` needed one of them. One more dry run, four minutes, would have said so with 80% reliability; two would have settled it. It had 960 minutes left.

That is the decision the environment is built to test: the model treated "which command is next" as the only open question, and "is everything this command needs up" as answered by the layer below being up. The reference asks both questions before every command whose mistake would destroy data, and on this seed it spends 836 minutes and loses nothing. `analysis/analyze.py` reports these as `unchecked_risk` (a command that went through although a fatal mistake was possible) and `blind_data_loss` (the one that did not): seven and one in this run, none of either for the reference.

### What we tried against our own reward

Each of these is a test in `tests/` that fails if it regresses:

- Reconnecting, or calling `finish` twice, does not reset the episode or the window.
- Concurrent calls cannot spend more window than there is.
- Calls after the end change nothing and cost nothing.
- Malformed arguments (wrong type, oversized, unknown names) are refused free of charge and leak nothing. This found a real crash on a null command, now fixed.
- No tool result contains a hidden field; codenames do not predict roles.
- Dry-running everything earns nothing by itself and cannot finish inside the window.
- `finish` at step 0 scores 0; after tier 1 it scores 0.10.
- A forged, replayed or out-of-range result is rejected by the verifier and scores 0.

One known weakness is not covered by a test. The result-signing key is a constant in each task and the agent's container can reach the internet. The repository was private while the runs reported here were made and was made public on 2026-11-15 so that the judges can run the task; from then on an agent that finds this repository can read the key and sign a result of its own. Rotating the key per run and cutting the agent's network would close this; neither is done.

The same systems are also told as two other scenarios, with the rules, costs and score unchanged: bringing a captured aircraft to take-off (`tasks/aircraft/`) and obtaining a residence permit from a state that publishes no rules (`tasks/residency/`), at levels 3 and 4. A seed has the same structure in all three, and the reference plays the identical episode in each (1.0 through Harbor on `level-4/seed-3` of both). No agent has been run on them yet.

## Repository

| Path | Contents |
|---|---|
| `src/unknown_machine/machine/` | The simulator: system generator, episode state and rules, score |
| `src/unknown_machine/reference/solver.py` | The reference and the scripted policies; uses only the six tools |
| `src/unknown_machine/server/app.py` | MCP server and verifier endpoint around one episode |
| `scripts/task_template/`, `scripts/make_tasks.py` | The Harbor task and the generator that stamps one per seed |
| `tasks/level-1` to `level-4` | The evaluation tasks, five seeds per level |
| `tasks/aircraft`, `tasks/residency` | The same systems at levels 3 and 4, told as two other scenarios |
| `runs/` | Harbor logs of the runs reported below (`scripts/keep_run.py` copies them from `jobs/`) |
| `tests/` | Rules of the simulator, baseline scores, reward exploits |
| `analysis/analyze.py` | Episode log to decisions |
| `viewer/index.html`, `scripts/watch.py`, `scripts/make_replay.py` | Live view of a run in progress, and replay of a finished one |
| `PLAN.md` | Design, measurements, open items |
| `AGENTS.md` | Rules for contributors and coding agents |

## Development

```
poetry install
poetry run pytest
poetry run ruff check .
poetry run python scripts/make_tasks.py    # after changing src/ or the template
```
