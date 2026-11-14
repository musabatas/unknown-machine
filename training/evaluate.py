"""Score every arm on the held-out seeds and write `training/results.json`.

    poetry run python -m training.evaluate

Arms, all on the same seeds: the base model with the task rules in its prompt,
the same model with the adapter from `training.train`, the reference, and the
scripted `cautious` and `greedy` baselines. The models play through the harness;
the scripted policies call the six tools directly, which `tests/test_training.py`
shows is the same thing for the reference.

Also reported: how often each model picks the reference's own action in the
states the reference visits on those seeds. That separates "has not learned the
rule" from "learned it, and one early slip ruined the episode".
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import mlx.core as mx
from mlx_lm import batch_generate, load
from mlx_lm.models.cache import make_prompt_cache

from training.make_dataset import HELD_OUT_SEEDS, LEVEL, TRAIN_SEEDS, reference_pairs
from training.observation import DRY_RUN, RUN, Action, Harness, messages, parse_action
from training.train import ADAPTER, HYPERPARAMETERS, MODEL
from unknown_machine.baselines.policies import BASELINES
from unknown_machine.calibration import build_episode

RESULTS = Path(__file__).resolve().parent / "results.json"

# A model's episode ends after this many action lines, whatever they did. Text that
# is not an action costs no window, so without a cap a model that repeats itself
# would never end. The reference needs at most 70 actions on a level 1 system.
STEP_CAP = 120
MAX_TOKENS = 16  # twice the longest action line the reference writes
SCRIPTED = ("reference", "cautious", "greedy")
BASE = "base model, zero-shot"
TUNED = "fine-tuned model"


class Model:
    """Greedy decoding, one action line per observation."""

    def __init__(self, adapter: Path | None) -> None:
        self._model, self._tokenizer = load(MODEL, adapter_path=str(adapter) if adapter else None)
        self._rules_in_prompt = adapter is None
        # Every prompt starts with the same system message. It is read once and kept,
        # so a turn only costs the observation: a third of the tokens with the rules.
        first, second = self._tokens("a"), self._tokens("b")
        self._shared = next(
            i for i, pair in enumerate(zip(first, second, strict=True)) if pair[0] != pair[1]
        )
        self._read = make_prompt_cache(self._model)
        self._model(mx.array([first[: self._shared]]), cache=self._read)
        mx.eval([entry.state for entry in self._read])

    def _tokens(self, observation: str) -> list[int]:
        return self._tokenizer.apply_chat_template(
            messages(observation, rules=self._rules_in_prompt), add_generation_prompt=True
        )

    def act(self, observations: list[str]) -> list[str]:
        prompts = [self._tokens(observation)[self._shared :] for observation in observations]
        return batch_generate(
            self._model,
            self._tokenizer,
            prompts,
            prompt_caches=[self._read] * len(prompts),
            max_tokens=MAX_TOKENS,
        ).texts


def play_model(model: Model, seeds: range) -> list[dict]:
    """All episodes side by side, so every turn is one batch for the model."""
    episodes = {seed: build_episode(seed, LEVEL) for seed in seeds}
    harnesses = {seed: Harness(episode) for seed, episode in episodes.items()}
    for _ in range(STEP_CAP):
        live = [harness for harness in harnesses.values() if not harness.finished]
        if not live:
            break
        for harness, text in zip(
            live, model.act([harness.observation() for harness in live]), strict=True
        ):
            harness.step(text)
    return [
        _row(seed, episodes[seed].result(), harness.steps, harness.invalid, harness.unparsable)
        | {"capped": not harness.finished}
        for seed, harness in harnesses.items()
    ]


def play_scripted(name: str, seeds: range) -> list[dict]:
    rows = []
    for seed in seeds:
        episode = build_episode(seed, LEVEL)
        BASELINES[name](episode)
        result = episode.result()
        rows.append(_row(seed, result, len(result["log"]), 0, 0) | {"capped": False})
    return rows


def _row(seed: int, result: dict, steps: int, invalid: int, unparsable: int) -> dict:
    return {
        "seed": seed,
        "score": result["score"],
        "data_lost": len(result["data_lost"]),
        "window_used": result["window_used"],
        "window_total": result["window_total"],
        "steps": steps,
        "invalid": invalid,
        "unparsable": unparsable,
    }


def summary(rows: list[dict]) -> dict:
    steps = sum(row["steps"] for row in rows)
    return {
        "episodes": len(rows),
        "mean_score": round(statistics.mean(row["score"] for row in rows), 4),
        "data_loss_share": round(sum(row["data_lost"] > 0 for row in rows) / len(rows), 4),
        "mean_window_used": round(statistics.mean(row["window_used"] for row in rows), 1),
        "mean_window_share": round(
            statistics.mean(row["window_used"] / row["window_total"] for row in rows), 4
        ),
        "invalid_action_share": round(sum(row["invalid"] for row in rows) / steps, 4),
        "unparsable_action_share": round(sum(row["unparsable"] for row in rows) / steps, 4),
        "mean_steps": round(steps / len(rows), 1),
        "capped_episodes": sum(row["capped"] for row in rows),
    }


def agreement(model: Model, pairs: list[tuple[str, str]], batch: int = 32) -> dict:
    """Share of the reference's decisions the model reproduces, by the tool the reference chose."""
    hits: dict[str, list[bool]] = {}
    differences = dict.fromkeys(DIFFERENCES, 0)
    for start in range(0, len(pairs), batch):
        chunk = pairs[start : start + batch]
        for (_, expected), text in zip(
            chunk, model.act([observation for observation, _ in chunk]), strict=True
        ):
            wanted, chosen = parse_action(expected), parse_action(text)
            hits.setdefault(wanted.tool, []).append(chosen == wanted)
            if chosen != wanted:
                differences[_difference(wanted, chosen)] += 1
    everything = [hit for tool in hits.values() for hit in tool]
    by_tool = {
        tool: {"decisions": len(found), "same": round(sum(found) / len(found), 4)}
        for tool, found in sorted(hits.items())
    }
    return {
        "decisions": len(everything),
        "same": round(sum(everything) / len(everything), 4),
        "by_reference_tool": by_tool,
        "differences": {
            kind: round(count / len(everything), 4) for kind, count in differences.items()
        },
    }


OTHER_SERVICE = "another service"
OTHER_COMMAND = "the same service, another command"
OTHER_TOOL = "the same service and command, dry_run and run swapped"
OTHER = "anything else"
DIFFERENCES = (OTHER_SERVICE, OTHER_COMMAND, OTHER_TOOL, OTHER)


def _difference(wanted: Action, chosen: Action | None) -> str:
    """How a choice differs from the reference's. The swap is the decision under test."""
    if chosen is None or not chosen.service or not wanted.service:
        return OTHER
    if chosen.service != wanted.service:
        return OTHER_SERVICE
    if chosen.command != wanted.command:
        return OTHER_COMMAND
    return OTHER_TOOL if {chosen.tool, wanted.tool} == {DRY_RUN, RUN} else OTHER


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episodes", type=int, default=len(HELD_OUT_SEEDS))
    parser.add_argument("--out", type=Path, default=RESULTS)
    arguments = parser.parse_args()
    seeds = HELD_OUT_SEEDS[: arguments.episodes]

    started = time.monotonic()
    rows = {name: play_scripted(name, seeds) for name in SCRIPTED}
    pairs = [pair for seed in seeds for pair in reference_pairs(build_episode(seed, LEVEL))]
    agreements, seconds = {}, {}
    for name, adapter in ((BASE, None), (TUNED, ADAPTER)):
        arm_started = time.monotonic()
        model = Model(adapter)
        rows[name] = play_model(model, seeds)
        agreements[name] = agreement(model, pairs)
        seconds[name] = round(time.monotonic() - arm_started)
        print(name, summary(rows[name]), agreements[name], flush=True)

    order = (BASE, TUNED, *SCRIPTED)
    results = {
        "model": MODEL,
        "level": LEVEL,
        "train_seeds": [TRAIN_SEEDS.start, TRAIN_SEEDS.stop - 1],
        "held_out_seeds": [seeds.start, seeds.stop - 1],
        "step_cap": STEP_CAP,
        "hyperparameters": {
            key: value
            for key, value in HYPERPARAMETERS.items()
            if key not in ("model", "data", "adapter_path", "train")
        },
        "arms": {name: summary(rows[name]) for name in order},
        "agreement_with_reference": agreements,
        "seconds": seconds | {"total": round(time.monotonic() - started)},
        "episodes": {name: rows[name] for name in order},
    }
    arguments.out.write_text(json.dumps(results, indent=2) + "\n")
    for name in order:
        print(f"{name:24}", results["arms"][name])
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()
