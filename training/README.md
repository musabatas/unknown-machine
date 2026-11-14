# Post-training experiment

Does fine-tuning a small open model on the reference's trajectories teach it the reference's decision rule: when to dry-run, when to run, when to wait for a dependency?

Answer from this run: **it improves a lot, and it does not get there.** On 40 held-out seeds the base model scores 0.000 in all six conditions it was tried in. After three passes over the reference's decisions the fine-tuned model scores 0.400 with free decoding and 0.428 restricted to legal actions, and it completes the whole recovery on 13 and 14 of the 40 seeds. A policy that draws legal actions at random scores 0.000. The fine-tuned model is above the scripted baseline that never dry-runs (0.29), below the one that always does (0.52) and far below the reference (1.00), and unlike the reference it destroys data on 3 of 40 seeds. The gain grows with training: 0.003 after a quarter pass, 0.086 after one, 0.400 after three. One model, one level, one training run per point.

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
- **Model.** `mlx-community/Qwen2.5-0.5B-Instruct-4bit`, LoRA with mlx-lm 0.32.2: rank 16 on the last 16 of 24 blocks, 7200 iterations of batch 8 at learning rate 1e-4 (three passes over the training pairs), loss on the action line only. `train.py` owns the hyperparameters.
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

Wall time on an M4 Pro with 24 GB, shared with other work: dataset 2 seconds, scoring 29 minutes. Training was not timed for 7200 iterations; 2400 took 30 minutes, and this run took between two and three hours while agent runs used the same machine.

## Results

One training run, 40 held-out seeds (5000 to 5039), level 1. The score has no step below tier 1 (0.10), so two more columns show progress under it: "Commands done" is the share of the system's commands run successfully at least once, "Tiers" the mean number of tiers banked, of four. "Ended at step 1" is the share of episodes the policy ended with its first action: it did not play, whatever its score says.

| Arm | Mean score | Commands done | Tiers | Episodes with data loss | Window used | Invalid actions | Ended at step 1 | Cut at 120 steps |
|---|---|---|---|---|---|---|---|---|
| Base, rules prompt, free | 0.000 | 0% | 0.00 | 0% | 0% | 0% | 100% | 0 |
| Base, rules prompt, legal only | 0.000 | 0% | 0.00 | 0% | 0% | 0% | 100% | 0 |
| Base, rules prompt, legal only, finish withheld | 0.000 | 0.1% | 0.00 | 5% | 39% | 0% | 0% | 36 |
| Base, one-line prompt, free | 0.000 | 0% | 0.00 | 0% | 0% | 100% | 0% | 40 |
| Base, one-line prompt, legal only | 0.000 | 0.1% | 0.00 | 2.5% | 35% | 0% | 0% | 34 |
| Base, one-line prompt, legal only, finish withheld | 0.000 | 0.1% | 0.00 | 2.5% | 35% | 0% | 0% | 34 |
| Fine-tuned, one-line prompt, free | 0.400 | 51% | 1.98 | 7.5% | 68% | 38% | 0% | 21 |
| Fine-tuned, one-line prompt, legal only | 0.428 | 55% | 2.08 | 7.5% | 89% | 0% | 0% | 15 |
| Fine-tuned, one-line prompt, legal only, finish withheld | 0.428 | 55% | 2.08 | 7.5% | 89% | 0% | 0% | 15 |
| Fine-tuned, rules prompt, free (robustness) | 0.054 | 12% | 0.50 | 0% | 54% | 60% | 0% | 36 |
| Fine-tuned, rules prompt, legal only (robustness) | 0.055 | 15% | 0.57 | 5% | 99% | 0% | 0% | 31 |
| Random legal action, finish offered | 0.000 | 2.8% | 0.00 | 92.5% | 77% | 0% | 0% | 0 |
| Random legal action, finish withheld | 0.000 | 3.6% | 0.00 | 100% | 100% | 0% | 0% | 0 |
| Reference | 1.000 | 100% | 4.00 | 0% | 70% | 0% | 0% | 0 |
| Cautious | 0.519 | 87% | 2.88 | 0% | 99% | 0% | 0% | 0 |
| Greedy | 0.291 | 56% | 1.85 | 72.5% | 32% | 0% | 0% | 0 |

The fairest pairs, same decoding, best base row against the fine-tuned model with its training prompt:

| Decoding | Best base row | Fine-tuned | Difference |
|---|---|---|---|
| Free | 0.000 (either prompt) | 0.400 | +0.400 |
| Legal only | 0.000 (either prompt) | 0.428 | +0.428 |
| Legal only, finish withheld | 0.000 (either prompt) | 0.428 | +0.428 |

Scores of the fine-tuned model per episode (one-line prompt). No base row and no random row banks a tier in any episode.

| Score | Free | Legal only (finish offered or withheld) |
|---|---|---|
| 0.00 | 11 | 12 |
| 0.10 | 9 | 5 |
| 0.25 | 5 | 7 |
| 0.35 | 1 | 1 |
| 0.50 | 1 | 1 |
| 1.00 (full recovery) | 13 | 14 |

Three episodes in each column lost a service's data, which takes 0.15 off whatever was banked.

Agreement with the reference in the reference's own states (1904 decisions):

| Reference's action | Decisions | Base, rules, free | Base, rules, legal | Base, one-line, free | Base, one-line, legal | Fine-tuned, free | Fine-tuned, legal |
|---|---|---|---|---|---|---|---|
| `inspect` | 262 | 0.0% | 0.8% | 0.0% | 5.7% | 100% | 100% |
| `dry_run` | 611 | 0.0% | 0.0% | 0.0% | 0.0% | 90.7% | 91.2% |
| `run` | 991 | 0.7% | 11.9% | 0.0% | 1.0% | 94.9% | 95.3% |
| `finish` | 40 | 97.5% | 97.5% | 0.0% | 0.0% | 100% | 100% |
| All | 1904 | 2.4% | 8.4% | 0.0% | 1.3% | 94.3% | 94.7% |

Where the fine-tuned model differs from the reference (free decoding, 5.7% of the decisions):

| Difference | Share of all decisions |
|---|---|
| Another service | 2.2% |
| The same service, another command | 1.6% |
| The same service and command, `dry_run` and `run` swapped | 1.9% |

### More training, same setup

Three runs, differing only in the number of iterations. The `results.json` of the 600-iteration run is in commit b4c1cfe and that of the 2400-iteration run in a4a178d. Same data, same seeds, free decoding, one-line prompt for the fine-tuned model:

| Iterations | Passes | Mean score | Full recoveries of 40 | Episodes with data loss | Invalid actions | Agreement, all | Agreement on `dry_run` | Agreement on `run` |
|---|---|---|---|---|---|---|---|---|
| 0 (base model, rules prompt) | 0 | 0.000 | 0 | 0% | 0% | 2.4% | 0.0% | 0.7% |
| 600 | 0.25 | 0.003 | 0 | 2.5% | 82% | 68.8% | 36.3% | 79.5% |
| 2400 | 1 | 0.086 | 1 | 0% | 74% | 72.4% | 74.3% | 63.4% |
| 7200 | 3 | 0.400 | 13 | 7.5% | 38% | 94.3% | 90.7% | 94.9% |

Three points on a curve, one run each. The score rose at every step; whether it keeps rising beyond 7200 iterations was not measured.

## What the numbers say

- **The base model's 0.000 is not one failure but three.** With the rules prompt it answers `finish` on the first turn of all 40 episodes, free or legal-only: it does not play. With the one-line prompt and free decoding it never writes an action line (100% unparsable). Made to play (legal actions, `finish` withheld or never chosen), it plays for about 115 steps, banks no tier in any episode and loses data in 1 or 2 of 40.
- **The improvement holds in every pairing.** Under each decoding the best base row is 0.000 and the fine-tuned model is 0.400 to 0.428, n = 40. The fine-tuned model banks at least tier 1 in 30 of 40 episodes free and 29 of 40 legal-only, and completes the whole recovery in 13 and 14. It never chooses `finish` early, so withholding `finish` changes nothing for it.
- **It beats random among legal actions**, which scores 0.000 and destroys data in 37 to 40 of 40 episodes.
- **It is not safe.** Three of 40 episodes lose a service's data under either decoding; the reference loses none at level 1, and the one-pass adapter lost none either. More training made the model run more commands unchecked: it finishes far more often and is burnt sometimes.
- **Legal-only decoding helps a little.** It removes every invalid action (38% of steps to 0%) and moves the mean score from 0.400 to 0.428. Naming a valid command is not what holds the score down; choosing among valid ones is.
- **It is all or little.** Fourteen episodes score 1.00 and twenty-four score 0.25 or less; only two fall between. An episode either stays on the reference's path to the end or leaves it early.
- **The prompt matters to the fine-tuned model.** With the rules prompt it was not trained on, it falls to 0.054 free and 0.055 legal-only and completes no recovery: still above every base row, an eighth of its score with its own prompt.
- **Against the scripted baselines.** The fine-tuned model is above `greedy` (0.291) and below `cautious` (0.519). It loses data far less often than `greedy` (7.5% of episodes against 72.5%) and, unlike `cautious`, not never.

Inference, not measured:

- At 94% agreement per decision and 48 decisions per episode, an episode that follows the reference's states would stay on its path about 6% of the time if decisions were independent (0.943 to the 48th); 13 of 40 do, so the disagreements cluster in some systems. Imitation of a perfect player never shows a mistake being repaired: the reference is never refused for an unknown command and never crashes a service at level 1 (`restart` does not occur in the training data). Once the model is off the path it is in states it was not trained on, which would explain the all-or-little scores.
- Between 2400 and 7200 iterations agreement on `run` rose from 63% to 95% and data loss appeared. The one-pass model dry-ran too often and ran out of window; the three-pass model runs when the reference runs, and where it runs when the reference would have dry-run, it can destroy data.

## Limits

- One model (0.5B parameters, 4-bit), one level, one theme, one training run per iteration count, greedy decoding, 40 seeds. No variance across training runs was measured, so the size of the improvement has no error bar; that it is above zero rests on every base row scoring exactly 0 on all 40 seeds while the fine-tuned model scores above 0 on 28 or 29 of them.
- It is level 1 only: small systems and exact dry runs. Nothing here says a small model learns the levels the frontier agent fails on, where dry runs can be wrong and certainty has to be bought by repeating them.
- The fine-tuned model is still under the `cautious` script and at 0.43 of the reference's 1.00, and it destroys data the reference never does.
- The base model was tried under two prompts, not tuned. A better prompt for it, or a few examples in context, might lift it off zero; neither was tried.
- The model was chosen for time, not merit. `Qwen2.5-1.5B-Instruct-4bit` takes four times as long per decision on this machine. A zero-shot smoke run of it on 8 held-out seeds scored 0.00 with 94% invalid actions; that run is not in `results.json`.
- The harness is part of the policy. It decides what the model sees; a different observation could make the rule easier or harder to learn. It keeps one report per command, which is enough only where dry runs are exact, so it does not carry over to levels 2 to 4 as it is.
- Legal-only decoding is greedy over a token trie. A search for the most probable legal line could choose differently; that was not tried. Neither was sampling, which would let a model leave some of its loops.
- The random control is one seeded draw per episode, not an average over draws.
- The step cap and the definition of an invalid action are choices.
