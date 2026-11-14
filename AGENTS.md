# Unknown Machine: repository contract

Rules for everyone who changes this repository, human or coding agent. `PLAN.md` owns the design (environment, score, gate thresholds, timeline); this file owns how the code is built. When a change alters something either file states, update that file in the same commit.

## What this is

An RL environment for the AfterQuery "Break the Agent" challenge (Junction 2026). An agent brings an orphaned legacy production system back online through six MCP tools. Judges rerun our reference, three agent runs, a do-nothing baseline and a stop-early baseline, then spend 15 minutes hunting reward exploits. Every rule below protects one of the four rubric items: the gap, meaningful difficulty, reward integrity, craft.

## Invariants

These are not style preferences. Breaking one can zero a rubric item.

1. **Hidden state lives only in the sidecar.** Guards, roles, seed, budget and score never reach the agent container: not in files, environment variables, tool output, error messages or logs the agent can read.
2. **The score is computed from server-side system state only.** Nothing the agent says or writes earns credit. Doing nothing scores 0; stopping early keeps only banked tiers.
3. **Everything is deterministic per seed.** One seeded `random.Random` passed explicitly. No module-level `random`, no wall clock, no unordered iteration that affects behaviour, no network calls in the simulator.
4. **The tool surface is exactly six tools:** `status`, `run`, `dry_run`, `inspect`, `restart`, `finish`. Adding, removing or changing the meaning of a tool is a design change: update `PLAN.md` first.
5. **Every destructive rule is discoverable by `dry_run`, to whatever certainty the agent pays for.** At level 1 a dry run is exact. At level 2 it is right with the per-service probability that `inspect` states, independently on each call, so repeating it buys certainty; it is never wrong about how a service reacts to a mistake, and `run` is always real. A rule that can only be learned by losing data is a bug. Certainty at level 2 is never total: the reference accepts a 0.2% chance of data loss per command and does lose data on a small share of seeds. State that share wherever reference results are reported, and never present seed selection as if it did not exist.
6. **The reference solver uses the same six tools and nothing else.** `reference/solver.py` imports only the standard library, never the simulator, and never special-cases a seed. It is copied verbatim into every task's `solution/`, so it must stay a single self-contained file.
7. **The simulator core is pure.** `machine/` has no I/O, no MCP, no Harbor imports. The server wraps it; tests call it in-process.
8. **Codenames carry no hint of a service's role.**
9. **Every exploit found gets a test** under `tests/exploits/` in the same commit as its fix.
10. **Tool costs and error codes are stated in three places that must agree:** `machine/model.py` and `machine/episode.py`, `reference/solver.py`, and `scripts/task_template/instruction.md`. Change all three together; the agent is only treated fairly if the instruction matches the rules.
11. **A service reacts to a kind of mistake the same way every time.** The instruction promises this and the reference depends on it. A rule that breaks it makes the reference lose data.

## Layout

```
src/unknown_machine/
  machine/            simulator core: model, seeded generator, episode, score
  calibration.py      seed -> episode with its window (reference cost / 0.7)
  server/app.py       MCP server and verifier endpoint around one episode
  reference/solver.py reference and scripted policies, standard library only
  baselines/          do-nothing, stop-early, cautious, greedy, random
scripts/
  task_template/      the Harbor task every seed is generated from
  make_tasks.py       template + package -> tasks/level-<l>/seed-<n>/
  evaluate.py, eval.sh  the one-command evaluation
  export_trajectories.py  reference episodes as training data
tasks/level-<l>/seed-<n>/  generated evaluation tasks, five seeds per level
tasks/smoke/          hand-maintained harness smoke test
tests/                simulator rules, baseline scores, exploits
analysis/analyze.py   episode log -> decisions that cost score or window
```

`tasks/level-*/seed-*` is generated: change `src/` or `scripts/task_template/`, then run `poetry run python scripts/make_tasks.py` and commit the output with the change. Never edit a generated task by hand; it would differ from what the generator produces and from the other seeds. `tasks/smoke/` is the one hand-maintained task: a toy that proves the harness wiring (sidecar, MCP, signed result, reward file).

Free checks, run after any change to the simulator, the template or the task wiring:

```
poetry run pytest
harbor lint tasks/level-1/seed-0
harbor run -p tasks/level-1/seed-0 -a oracle   # expect reward 1.0
harbor run -p tasks/level-1/seed-0 -a nop      # expect reward 0.0
```

A change to the generator or to tool costs moves every seed. After one, rerun the tests: `tests/test_baselines.py` holds the scores the README states and the property that picked the evaluation seeds.

## Tooling

- Python 3.12 or newer, Poetry. Never `pip install`; add dependencies with `poetry add` and commit `poetry.lock`.
- Before adding or changing a call into Harbor, the MCP SDK or OpenCode, read the current documentation for the installed version. The organiser requirements in `PLAN.md` section 5 (Harbor task format, `-a opencode`, score in `/logs/verifier/reward.txt`) override public Harbor docs where they differ; record any new difference there.
- Checks, scoped to what changed:

```
poetry run ruff check .
poetry run pytest tests/path/to/test_file.py
```

- Pass API keys to Harbor with `--env-file <path to .env>`. Do not export them in a shell that also runs other commands.

## Reserved actions

Ask the maintainer before any of these:

- Running a frontier model through the harness (`harbor run` with a paid model). It spends the team's limited credits. In-process simulator runs, the reference and the scripted baselines are free and need no approval.
- Pushing, opening or merging a pull request, changing repository visibility or collaborators.
- Changing gate thresholds, tier points or tool costs in `PLAN.md`.

## Working in the repository

- Several people and several agents work here at once. Treat changes you did not make as someone's live work: no stash, reset, clean or checkout over them.
- Work in the main checkout. Work left in a worktree is invisible to the rest of the team; `.claude/settings.json` turns off the worktree isolation of background agent sessions for this reason. A session that is still forced into `.claude/worktrees/` (ignored by git) commits there and fast-forwards `main` to it after every commit.
- One logical change per commit, conventional lowercase subject, body stating why. Stage explicit paths.
- Secrets go in `.env`, which is ignored. Never commit keys, never print them, never put personal data in source, fixtures or task files; the repository is handed to judges.
- Do not create `CLAUDE.md`; it would shadow this file.
- No reports or worklogs. The lessons and exploit logs required by the challenge live where `PLAN.md` section 10 puts them.

## Reporting a change

State what was verified and at which layer (static check, in-process simulator test, Harbor run with the reference, Harbor run with a frontier agent). A green unit test does not show that a Harbor run works.
