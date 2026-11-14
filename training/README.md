# Post-training experiment

Does fine-tuning a small open model on the reference's trajectories teach it the reference's decision rule: when to dry-run, when to run, when to wait for a dependency?

Answer from this run: **it improves, and it does not get there.** On 40 held-out seeds, with both models restricted to legal actions and `finish` withheld so that neither can stop before playing, the base model scores 0.000 under either prompt and the fine-tuned model 0.099. The base model scores 0.000 in all six conditions it was tried in; the fine-tuned model's best is 0.099 and its free-decoding score is 0.086. A policy that draws legal actions at random scores 0.000. The fine-tuned model is still far below the scripted baselines (0.29 and 0.52) and the reference (1.00). One model, one level, one training run.

## Design

- **Level 1, legacy theme.** 5 to 8 services, exact dry runs, 31 to 70 tool calls per reference episode.
- **Next-action prediction, not transcripts.** A small model cannot hold an episode in context. `observation.py` is a harness between the model and the tools: each turn it writes one compact observation from the tool results seen so far, the model answers with one action line, and the harness makes that tool call. It holds a console with the six tools and nothing else; `tests/test_training.py` shows that systems differing only in hidden state (seed, step order, reactions to mistakes) produce the same observation and the same legal actions.
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
- **Model.** `mlx-community/Qwen2.5-0.5B-Instruct-4bit`, LoRA with mlx-lm 0.32.2: rank 16 on the last 16 of 24 blocks, 2400 iterations of batch 8 at learning rate 1e-4 (one pass over the training pairs), loss on the action line only. `train.py` owns the hyperparameters.
- **Two prompts.** The *rules prompt* states the task rules (`RULES_PROMPT`). The *one-line prompt* only asks for the next action (`SHORT_PROMPT`). The fine-tuned model was trained with the one-line prompt, so that is its prompt: anything else is off its training distribution. The base model is scored under both, so the comparison does not depend on which one it got. The fine-tuned model under the rules prompt is reported as a robustness row.
- **Three decodings**, greedy in all, applied the same way to both models:
  - *Free.* Whatever the model writes is the action. Text that is not an action line, or a line naming a service or command that does not exist, costs a step and no window.
  - *Legal actions only.* The model can write nothing but a line the tools would accept: a service `status` lists, with a command `status` lists for it, or `finish` (`Harness.legal_actions`, built from `status` alone). A logits processor walks a token trie of those lines and at every step leaves the most likely token that continues one. The model still chooses token by token; it cannot leave the set. This is not the legal line of highest total probability, which would need a search. The legal set includes the commands that are never needed, so a legal line can still destroy data.
  - *Legal actions only, finish withheld.* The same, without `finish` while any service is down. **This is a handicap removed from a model that would stop on its first turn, not a feature of the environment**, where stopping early is always allowed. It exists so that there is a row in which the untrained model is made to play.
- **Step cap.** A model's episode is cut after 120 action lines (`STEP_CAP`); the reference needs at most 70. What was banked by then is the score.
- **Controls without a model.** The reference, `cautious` (one dry run before every command) and `greedy` (never dry-run), calling the tools directly; and a seeded policy that draws uniformly among the legal actions, with `finish` offered and withheld, under the same step cap.
- **Agreement.** Besides playing, each model is asked for its action in every state the reference visits on the held-out seeds (1904 decisions).

## Reproduce

Apple Silicon only. From the repository root:

```
poetry install --with training
poetry run python -m training.make_dataset
poetry run python -m training.train
poetry run python -m training.evaluate
```

The first run downloads the model (a few hundred MB) from Hugging Face. Datasets and the adapter go to `training/artifacts/`, which is ignored by git. The last command writes `training/results.json`, with one row per arm and seed.

Wall time on an M4 Pro with 24 GB, shared with other work: dataset 2 seconds, training 30 minutes, scoring 29 minutes.

## Results

One training run, 40 held-out seeds (5000 to 5039), level 1. "Ended at step 1" is the share of episodes the policy ended with its first action: it did not play, whatever its score says.

| Arm | Mean score | Episodes with data loss | Window used | Invalid actions | Ended at step 1 | Cut at 120 steps |
|---|---|---|---|---|---|---|
| Base, rules prompt, free | 0.000 | 0% | 0% | 0% | 100% | 0 |
| Base, rules prompt, legal only | 0.000 | 0% | 0% | 0% | 100% | 0 |
| Base, rules prompt, legal only, finish withheld | 0.000 | 5% | 39% | 0% | 0% | 36 |
| Base, one-line prompt, free | 0.000 | 0% | 0% | 100% | 0% | 40 |
| Base, one-line prompt, legal only | 0.000 | 2.5% | 35% | 0% | 0% | 34 |
| Base, one-line prompt, legal only, finish withheld | 0.000 | 2.5% | 35% | 0% | 0% | 34 |
| Fine-tuned, one-line prompt, free | 0.086 | 0% | 39% | 74% | 0% | 36 |
| Fine-tuned, one-line prompt, legal only | 0.099 | 0% | 99% | 0% | 0% | 25 |
| Fine-tuned, one-line prompt, legal only, finish withheld | 0.099 | 0% | 99% | 0% | 0% | 25 |
| Fine-tuned, rules prompt, free (robustness) | 0.026 | 0% | 41% | 67% | 0% | 35 |
| Fine-tuned, rules prompt, legal only (robustness) | 0.031 | 0% | 99% | 0% | 0% | 29 |
| Random legal action, finish offered | 0.000 | 92.5% | 77% | 0% | 0% | 0 |
| Random legal action, finish withheld | 0.000 | 100% | 100% | 0% | 0% | 0 |
| Reference | 1.000 | 0% | 70% | 0% | 0% | 0 |
| Cautious | 0.519 | 0% | 99% | 0% | 0% | 0 |
| Greedy | 0.291 | 72.5% | 32% | 0% | 0% | 0 |

The fairest pairs, same decoding, best base row against the fine-tuned model with its training prompt:

| Decoding | Best base row | Fine-tuned | Difference |
|---|---|---|---|
| Free | 0.000 (either prompt) | 0.086 | +0.086 |
| Legal only | 0.000 (either prompt) | 0.099 | +0.099 |
| Legal only, finish withheld | 0.000 (either prompt) | 0.099 | +0.099 |

Scores of the fine-tuned model per episode (one-line prompt). No base row and no random row banks a tier in any episode.

| Score | Free | Legal only (finish offered or withheld) |
|---|---|---|
| 0.00 (nothing banked) | 22 | 20 |
| 0.10 (tier 1) | 12 | 12 |
| 0.25 (tiers 1 and 2) | 5 | 7 |
| 1.00 (full recovery) | 1 | 1 |

Agreement with the reference in the reference's own states (1904 decisions):

| Reference's action | Decisions | Base, rules, free | Base, rules, legal | Base, one-line, free | Base, one-line, legal | Fine-tuned, free | Fine-tuned, legal |
|---|---|---|---|---|---|---|---|
| `inspect` | 262 | 0.0% | 0.8% | 0.0% | 5.7% | 98.1% | 98.9% |
| `dry_run` | 611 | 0.0% | 0.0% | 0.0% | 0.0% | 74.3% | 75.1% |
| `run` | 991 | 0.7% | 11.9% | 0.0% | 1.0% | 63.4% | 63.5% |
| `finish` | 40 | 97.5% | 97.5% | 0.0% | 0.0% | 100% | 100% |
| All | 1904 | 2.4% | 8.4% | 0.0% | 1.3% | 72.4% | 72.9% |

Where the fine-tuned model differs from the reference (free decoding, 27.6% of the decisions):

| Difference | Share of all decisions |
|---|---|
| Another service | 10.7% |
| The same service, another command | 1.9% |
| The same service and command, `dry_run` and `run` swapped | 15.0% |

### More training, same setup

The first run of this experiment used 600 iterations (a quarter of one pass); its `results.json` is in commit b4c1cfe. Same data, same seeds, free decoding, one-line prompt for the fine-tuned model:

| Iterations | Mean score | Episodes with data loss | Invalid actions | Agreement, all | Agreement on `dry_run` | Agreement on `run` |
|---|---|---|---|---|---|---|
| 0 (base model, rules prompt) | 0.000 | 0% | 0% | 2.4% | 0.0% | 0.7% |
| 600 | 0.003 | 2.5% | 82% | 68.8% | 36.3% | 79.5% |
| 2400 | 0.086 | 0% | 74% | 72.4% | 74.3% | 63.4% |

Two points on a curve, one run each. The score rises with training; the slope beyond 2400 iterations was not measured.

## What the numbers say

- **The base model's 0.000 is not one failure but three.** With the rules prompt it answers `finish` on the first turn of all 40 episodes, free or legal-only: it does not play. With the one-line prompt and free decoding it never writes an action line (100% unparsable). Made to play (legal actions, `finish` withheld or never chosen), it plays for about 115 steps, banks no tier in any episode and loses data in 1 or 2 of 40.
- **The improvement holds in every pairing.** Under each decoding the best base row is 0.000 and the fine-tuned model is 0.086 to 0.099, n = 40. The fine-tuned model banks at least tier 1 in 18 of 40 episodes free and 20 of 40 legal-only, completes one recovery, and loses no data in any episode. It never chooses `finish` early, so withholding `finish` changes nothing for it.
- **It beats random among legal actions**, which scores 0.000 and destroys data in 37 to 40 of 40 episodes. The adapter learned more than the format: which actions are safe, and enough of the order to bring up storage in half the episodes.
- **Legal-only decoding barely helps the fine-tuned model.** It removes every invalid action (74% of steps to 0%) and moves the mean score from 0.086 to 0.099: two more episodes reach tier 2. The model then spends the whole window (99%, against 39%) on actions that are legal and do not advance the recovery. Naming a valid command was not what held the score down; choosing among valid ones is.
- **Where it chooses badly.** The largest disagreement with the reference is the decision the environment is about: `dry_run` and `run` swapped on the command both agree on, 15.0% of decisions. Picking another service is 10.7%.
- **The prompt matters to the fine-tuned model.** With the rules prompt it was not trained on, it falls to 0.026 free and 0.031 legal-only: still above every base row, a third of its score with its own prompt.
- **Against the scripted baselines.** The fine-tuned model is below both `greedy` (0.291) and `cautious` (0.519). Unlike `greedy` it loses no data.

Inference, not measured:

- At 72% agreement per decision and 48 decisions per episode, almost no episode stays on the reference's path, and imitation of a perfect player never shows a mistake being repaired: the reference is never refused for an unknown command and never crashes a service at level 1 (`restart` does not occur in the training data). Once the model is off the path it is in states it was not trained on. That would explain an agreement of 72% next to a score of 0.09.
- Between 600 and 2400 iterations agreement on `dry_run` doubled and agreement on `run` fell. The model moved from running too often towards dry-running too often, which is consistent with no data loss and with the window running out under legal-only decoding.

## Limits

- One model (0.5B parameters, 4-bit), one level, one theme, one training run per iteration count, greedy decoding, 40 seeds. No variance across training runs was measured, so the size of the improvement has no error bar; that it is above zero rests on every base row scoring exactly 0 on all 40 seeds while the fine-tuned model scores above 0 on 18 to 20 of them.
- The improvement is small in absolute terms: 0.099 of 1.000, mostly tier 1. "Better than the untrained model and than random" is a low bar. The scripted baselines are the meaningful one, and the fine-tuned model is under both.
- The base model was tried under two prompts, not tuned. A better prompt for it, or a few examples in context, might lift it off zero; neither was tried.
- The model was chosen for time, not merit. `Qwen2.5-1.5B-Instruct-4bit` takes four times as long per decision on this machine. A zero-shot smoke run of it on 8 held-out seeds scored 0.00 with 94% invalid actions; that run is not in `results.json`.
- The harness is part of the policy. It decides what the model sees; a different observation could make the rule easier or harder to learn. It keeps one report per command, which is enough only where dry runs are exact, so it does not carry over to levels 2 to 4 as it is.
- Legal-only decoding is greedy over a token trie. A search for the most probable legal line could choose differently; that was not tried. Neither was sampling, which would let a model leave some of its loops.
- The random control is one seeded draw per episode, not an average over draws.
- The step cap and the definition of an invalid action are choices.
