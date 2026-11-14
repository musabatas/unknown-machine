"""Score every arm on the held-out seeds and write `training/results.json`.

    poetry run python -m training.evaluate

Arms, all on the same seeds: the base model with the task rules in its prompt,
the same model with the adapter from `training.train`, the reference, and the
scripted `cautious` and `greedy` baselines. The models play through the harness;
the scripted policies call the six tools directly, which `tests/test_training.py`
shows is the same thing for the reference.

Each model plays twice. Free decoding: whatever it writes is the action. Legal
actions only: it can write nothing but an action line the tools would accept,
by what `status` lists (`Harness.legal_actions`). The second takes "cannot name
a valid command" out of the result and leaves "chooses badly among valid ones".

So that the comparison of the two models has no free variable, the base model
is scored under both prompts, and under a third decoding in which `finish` is
withheld while a service is down: a model that would stop on its first turn is
then made to play. A seeded policy that draws a legal action uniformly at
random is the control for "learned the format, not the decision".

Also reported: how often each model picks the reference's own action in the
states the reference visits on those seeds. That separates "has not learned the
rule" from "learned it, and one early slip ruined the episode".
"""

import argparse
import json
import random
import statistics
import time
from pathlib import Path

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import BatchGenerator
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
FREE = "free decoding"
LEGAL = "legal actions only"
FORCED = "legal actions only, finish withheld"  # a handicap removed, see Harness.legal_actions
RULES = "rules prompt"
ONE_LINE = "one-line prompt"

# (model, adapter, prompt, decodings, whether agreement with the reference is measured).
# The fine-tuned model was trained with the one-line prompt; the rules prompt is off its
# training distribution and is there as a robustness row. The base model gets both.
MODELS = (
    ("base model", None, RULES, (FREE, LEGAL, FORCED), True),
    ("base model", None, ONE_LINE, (FREE, LEGAL, FORCED), True),
    ("fine-tuned model", ADAPTER, ONE_LINE, (FREE, LEGAL, FORCED), True),
    ("fine-tuned model", ADAPTER, RULES, (FREE, LEGAL), False),
)
RANDOM = "random legal action"


class Model:
    """Greedy decoding, one action line per observation."""

    def __init__(self, adapter: Path | None, rules: bool) -> None:
        self._model, self._tokenizer = load(MODEL, adapter_path=str(adapter) if adapter else None)
        self._rules_in_prompt = rules
        self._lines: dict[str, tuple[int, ...]] = {}
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

    def _line(self, text: str) -> tuple[int, ...]:
        """An action line as the tokens the model would have to write, end of turn included."""
        if text not in self._lines:
            tokens = self._tokenizer.encode(text, add_special_tokens=False)
            self._lines[text] = (*tokens, self._tokenizer.eos_token_id)
        return self._lines[text]

    def act(self, observations: list[str], legal: list[list[str]] | None = None) -> list[str]:
        """One answer per observation. With `legal`, each answer is one of that turn's lines."""
        prompts = [self._tokens(observation)[self._shared :] for observation in observations]
        generator = BatchGenerator(
            self._model, stop_tokens=[[token] for token in self._tokenizer.eos_token_ids]
        )
        uids = generator.insert(
            prompts,
            [MAX_TOKENS] * len(prompts),
            caches=[self._read] * len(prompts),
            logits_processors=legal
            and [[LegalLines([self._line(text) for text in lines])] for lines in legal],
        )
        written: dict[int, list[int]] = {uid: [] for uid in uids}
        with generator.stats():
            while responses := generator.next_generated():
                for response in responses:
                    if response.finish_reason != "stop":
                        written[response.uid].append(response.token)
        generator.close()
        return [self._tokenizer.decode(written[uid]) for uid in uids]


class LegalLines:
    """Greedy decoding that can only spell one of the given token sequences.

    A logits processor for one sequence of a batch: at every step it leaves the most
    likely token among those that continue a legal line, and nothing else. The model
    still chooses, token by token; it cannot leave the set. This is not the legal line
    of highest total probability, which would need a search over the lines.
    """

    def __init__(self, lines: list[tuple[int, ...]]) -> None:
        self._node: dict = {}
        for line in lines:
            node = self._node
            for token in line:
                node = node.setdefault(token, {})

    def __call__(self, tokens: mx.array, logits: mx.array) -> mx.array:
        if not self._node:  # the line is complete; the generator may still look one step ahead
            return logits
        allowed = mx.array(list(self._node))
        chosen = allowed[mx.argmax(logits[0, allowed])].item()
        self._node = self._node[chosen]
        return mx.where(mx.arange(logits.shape[-1]) == chosen, logits, -mx.inf)


def play_model(model: Model, seeds: range, decoding: str) -> list[dict]:
    """All episodes side by side, so every turn is one batch for the model."""
    episodes = {seed: build_episode(seed, LEVEL) for seed in seeds}
    harnesses = {seed: Harness(episode) for seed, episode in episodes.items()}
    for _ in range(STEP_CAP):
        live = [harness for harness in harnesses.values() if not harness.finished]
        if not live:
            break
        legal = [harness.legal_actions(decoding != FORCED) for harness in live]
        answers = model.act(
            [harness.observation() for harness in live], None if decoding == FREE else legal
        )
        for harness, text in zip(live, answers, strict=True):
            harness.step(text)
    return [_played(seed, episodes[seed], harness) for seed, harness in harnesses.items()]


def play_random(seeds: range, finish_while_down: bool) -> list[dict]:
    """The control that needs no model: a legal action drawn uniformly, every turn."""
    rows = []
    for seed in seeds:
        rng = random.Random(f"random-legal-{seed}")
        episode = build_episode(seed, LEVEL)
        harness = Harness(episode)
        while not harness.finished and harness.steps < STEP_CAP:
            harness.step(rng.choice(harness.legal_actions(finish_while_down)))
        rows.append(_played(seed, episode, harness))
    return rows


def _played(seed: int, episode, harness: Harness) -> dict:
    row = _row(seed, episode.result(), harness.steps, harness.invalid, harness.unparsable)
    return row | {"capped": not harness.finished}


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
        # Ended by the policy's first action: it did not play, whatever its score says.
        "ended_at_first_step_share": round(
            sum(row["steps"] == 1 and not row["capped"] for row in rows) / len(rows), 4
        ),
    }


def reference_states(seed: int) -> list[tuple[str, str, list[str]]]:
    """Every decision of the reference: (observation, its action, the legal lines there)."""
    harness = Harness(build_episode(seed, LEVEL))
    states = []
    for observation, action in reference_pairs(build_episode(seed, LEVEL)):
        states.append((observation, action, harness.legal_actions()))
        harness.step(action)
    return states


def agreement(model: Model, states: list, legal_only: bool, batch: int = 32) -> dict:
    """Share of the reference's decisions the model reproduces, by the tool the reference chose."""
    hits: dict[str, list[bool]] = {}
    differences = dict.fromkeys(DIFFERENCES, 0)
    for start in range(0, len(states), batch):
        chunk = states[start : start + batch]
        answers = model.act(
            [observation for observation, _, _ in chunk],
            [legal for _, _, legal in chunk] if legal_only else None,
        )
        for (_, expected, _), text in zip(chunk, answers, strict=True):
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
    states = [state for seed in seeds for state in reference_states(seed)]
    rows[f"{RANDOM}, finish offered"] = play_random(seeds, finish_while_down=True)
    rows[f"{RANDOM}, finish withheld"] = play_random(seeds, finish_while_down=False)
    scripted = tuple(rows)
    agreements, seconds = {}, {}
    for model_name, adapter, prompt, decodings, measure_agreement in MODELS:
        model = Model(adapter, rules=prompt == RULES)
        for decoding in decodings:
            arm_started = time.monotonic()
            name = f"{model_name}, {prompt}, {decoding}"
            rows[name] = play_model(model, seeds, decoding)
            if measure_agreement and decoding != FORCED:
                agreements[name] = agreement(model, states, decoding == LEGAL)
            seconds[name] = round(time.monotonic() - arm_started)
            print(name, summary(rows[name]), agreements.get(name), flush=True)

    order = (*(name for name in rows if name not in scripted), *scripted)
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
        print(f"{name:72}", results["arms"][name])
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()
