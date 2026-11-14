# Post-training experiment

Does fine-tuning a small open model on the reference's trajectories teach it the reference's decision rule: when to dry-run, when to run, when to wait for a dependency?

Answer from this run: **no, not at this size and this amount of training.** The fine-tuned model learned the format and the routine parts, picks the reference's action in 69% of the reference's own states, and still scores 0.00 when it plays, because its first decision after the inspection is usually wrong in a way it cannot recover from. Numbers and limits below.

## Design

- **Level 1, legacy theme.** 5 to 8 services, exact dry runs, 31 to 70 tool calls per reference episode.
- **Next-action prediction, not transcripts.** A small model cannot hold an episode in context. `observation.py` is a harness between the model and the tools: each turn it writes one compact observation from the tool results seen so far, the model answers with one action line, and the harness makes that tool call. It holds a console with the six tools and nothing else; `tests/test_training.py` shows that systems differing only in hidden state (seed, step order, reactions to mistakes) produce the same observation.
- **Observation.** Window left; per service its role, mode, pending commands by name, the reaction seen so far to each of the two kinds of mistake (`?` until a tool has shown it), the lag where it applies, and what dry runs and failed runs showed since the service last advanced, marked `stale` once the set of serving services has changed; then the last action and its result.

  ```
  window: 132
  alder | gateway | stopped | pending: cutover renew-cert sync-routes | order: ? | dep: ?
  osprey | storage | partial | pending: attach start | order: refused | dep: refused | notes: dry_run attach E_DEP
  thistle | database | stopped | pending: migrate recover reindex start | order: ? | dep: ? | lag: 1
  wren | storage | partial | pending: attach replay-journal start | order: data_loss | dep: ? | notes: dry_run attach E_ORDER
  last: dry_run wren attach -> data_loss E_ORDER
  ```

- **Action.** One line: `inspect <service>`, `dry_run <service> <command>`, `run <service> <command>`, `restart <service>` or `finish`. `status` is not an action: it is free, so the harness calls it after every step.
- **Data.** The reference plays through the harness; every tool call it makes becomes one (observation, action) pair. 19397 pairs from seeds 1000 to 1399, 931 from seeds 2000 to 2019 for validation. No observation occurs with two different actions.
- **Seeds.** Training 1000 to 1399, validation 2000 to 2019, held out 5000 to 5039. The held-out seeds are consecutive, not selected. None overlaps the repository's evaluation seeds (0 to 5). `make_dataset.py` owns the ranges and a test checks them.
- **Model.** `mlx-community/Qwen2.5-0.5B-Instruct-4bit`, LoRA with mlx-lm 0.32.2: rank 16 on the last 16 of 24 blocks, 600 iterations of batch 8 at learning rate 1e-4, loss on the action line only. `train.py` owns the hyperparameters.
- **Arms**, all on the same 40 held-out seeds, greedy decoding:
  - base model, zero-shot, with the task rules in its system prompt (`RULES_PROMPT`);
  - the same model with the adapter, with a one-line system prompt (`SHORT_PROMPT`);
  - the reference, and the scripted `cautious` (one dry run before every command) and `greedy` (never dry-run) baselines, calling the tools directly.
- **Invalid actions.** Text that is not an action line, or a line naming a service or command that does not exist, costs a step and no window. A model's episode is cut after 120 action lines (`STEP_CAP`); the reference needs at most 70. What was banked by then is the score.
- **Agreement.** Besides playing, each model is asked for its action in every state the reference visits on the held-out seeds (1904 decisions). That separates "does not know the rule" from "knows most of it and one slip ends the episode".

## Reproduce

Apple Silicon only. From the repository root:

```
poetry install --with training
poetry run python -m training.make_dataset
poetry run python -m training.train
poetry run python -m training.evaluate
```

The first run downloads the model (a few hundred MB) from Hugging Face. Datasets and the adapter go to `training/artifacts/`, which is ignored by git. The last command writes `training/results.json`, with one row per arm and seed.

Wall time on an M4 Pro with 24 GB, under memory pressure from other work: dataset 2 seconds, training 16 minutes, scoring 6 minutes. Decoding is greedy, so scoring the same adapter twice gives the same numbers; that was checked once.

## Results

One training run, 40 held-out seeds, level 1.

| Arm | Mean score | Episodes with data loss | Mean window used | Invalid actions | Episodes cut at 120 steps |
|---|---|---|---|---|---|
| Base model, zero-shot | 0.000 | 0% | 0% (0 min) | 0% | 0 |
| Fine-tuned model | 0.003 | 2.5% (1 of 40) | 22% (27 min) | 82% | 40 |
| Reference | 1.000 | 0% | 70% (99 min) | 0% | 0 |
| Cautious | 0.519 | 0% | 99% (140 min) | 0% | 0 |
| Greedy | 0.291 | 72.5% (29 of 40) | 32% (44 min) | 0% | 0 |

Agreement with the reference in the reference's own states (1904 decisions):

| Reference's action | Decisions | Base model | Fine-tuned model |
|---|---|---|---|
| `inspect` | 262 | 0.0% | 99.2% |
| `dry_run` | 611 | 0.0% | 36.3% |
| `run` | 991 | 0.7% | 79.5% |
| `finish` | 40 | 97.5% | 100% |
| All | 1904 | 2.4% | 68.8% |

Where the fine-tuned model differs from the reference (31.2% of the 1904 decisions):

| Difference | Share of all decisions |
|---|---|
| Another service | 16.3% |
| The same service, another command | 5.3% |
| The same service and command, `dry_run` and `run` swapped | 9.6% |

What the numbers say:

- The base model answers `finish` on the first turn of every episode. Its 0% invalid actions and its 97.5% on `finish` are that one answer, not competence.
- The fine-tuned model never writes an unparsable line. All of its invalid actions are well-formed lines naming a command the chosen service does not have (for example a storage command on a database).
- It scores above zero on one seed and loses data on one. Every episode ends at the step cap: once an action is refused as unknown, the observation barely changes, greedy decoding repeats the answer, and the episode is spent.
- It is below both scripted baselines. Fine-tuning moved the model from doing nothing to inspecting every service and then stalling, not to the rule.
- The decision under test, `dry_run` or `run` on a command both agree on, is the smaller part of the disagreement (9.6% of decisions). Picking the wrong service is the larger part (16.3%).

Inference, not measured:

- The rule has two parts: which service to work on (the lowest layer that can move) and whether its next command needs a dry run. The model has learned neither reliably, and the first fails first: in a trace of the first 10 held-out seeds (a one-off, not in `results.json`), 9 episodes went wrong at the first decision after the inspection, by pairing a storage command with a service of another role.
- 600 iterations see 4800 of the 19397 pairs, a quarter of one pass. Validation loss was still falling when training stopped (0.35 at 200 iterations, 0.14 at 600). More training may close part of the gap; this run does not show that it would.
- Imitation of a perfect player never shows a mistake being repaired. The reference is never refused for an unknown command and never crashes a service at level 1 (`restart` does not occur in the training data), so the model has no example of what to do after its own error. At 69% agreement per decision and 48 decisions per episode, almost no episode stays on the reference's path.

## Limits

- One model (0.5B parameters, 4-bit), one level, one theme, one training run, one decoding setting, 40 seeds. No variance across training runs was measured.
- The model was chosen for time, not merit. `Qwen2.5-1.5B-Instruct-4bit` takes four times as long per decision on this machine. A zero-shot smoke run of it on 8 held-out seeds scored 0.00 with 94% invalid actions; that run is not in `results.json`.
- The two model arms do not get the same prompt: the base model is told the rules, the fine-tuned model is not. The rules are two thirds of the tokens of a turn, and training on them would have cut the training data by the same factor in the same time.
- The comparison against the base model is weak evidence, because the base model does not play at all. The scripted baselines are the meaningful bar, and the fine-tuned model is under both.
- The harness is part of the policy. It decides what the model sees; a different observation could make the rule easier or harder to learn. It keeps one report per command, which is enough only where dry runs are exact, so it does not carry over to levels 2 to 4 as it is.
- The step cap and the definition of an invalid action are choices. With sampling instead of greedy decoding the model would leave some of its loops; that was not tried.
