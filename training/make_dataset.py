"""Reference episodes as (observation, action) pairs for next-action training.

    poetry run python -m training.make_dataset

The reference plays each training seed through the harness: before every tool
call it makes, the observation the harness shows at that moment is paired with
that call written as an action line. Writes `training/artifacts/data/train.jsonl`
and `valid.jsonl` in the chat format mlx-lm reads.
"""

import json
from pathlib import Path

from training.observation import (
    DRY_RUN,
    FINISH,
    INSPECT,
    RESTART,
    RUN,
    Action,
    Harness,
    format_action,
    messages,
)
from unknown_machine.calibration import build_episode
from unknown_machine.reference.solver import solve

LEVEL = 1

# The three sets are disjoint, and none touches the repository's evaluation seeds
# (0 to 5 across the levels, `EVALUATION_SEEDS` in scripts/make_tasks.py).
TRAIN_SEEDS = range(1000, 1400)
VALIDATION_SEEDS = range(2000, 2020)
HELD_OUT_SEEDS = range(5000, 5040)  # consecutive, not selected; used by training.evaluate

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
DATA = ARTIFACTS / "data"


class Recorder:
    """The six tools as the reference calls them, played through the harness as text."""

    def __init__(self, harness: Harness) -> None:
        self._harness = harness
        self.pairs: list[tuple[str, str]] = []

    def status(self) -> dict:
        return self._harness.status

    def inspect(self, service: str) -> dict:
        return self._play(Action(INSPECT, service))

    def dry_run(self, service: str, command: str) -> dict:
        return self._play(Action(DRY_RUN, service, command))

    def run(self, service: str, command: str) -> dict:
        return self._play(Action(RUN, service, command))

    def restart(self, service: str) -> dict:
        return self._play(Action(RESTART, service))

    def finish(self) -> dict:
        return self._play(Action(FINISH))

    def _play(self, action: Action) -> dict:
        text = format_action(action)
        self.pairs.append((self._harness.observation(), text))
        return self._harness.step(text).result


def reference_pairs(episode) -> list[tuple[str, str]]:
    """Every decision of the reference on this episode: (observation, action line)."""
    recorder = Recorder(Harness(episode))
    solve(recorder)
    return recorder.pairs


def write(seeds: range, path: Path) -> tuple[int, int]:
    """Returns (pairs written, observations that occur with more than one action)."""
    actions_of: dict[str, set[str]] = {}
    with path.open("w") as output:
        for seed in seeds:
            for observation, action in reference_pairs(build_episode(seed, LEVEL)):
                turn = messages(observation, rules=False)
                turn.append({"role": "assistant", "content": action})
                output.write(json.dumps({"messages": turn}) + "\n")
                actions_of.setdefault(observation, set()).add(action)
    ambiguous = sum(len(actions) > 1 for actions in actions_of.values())
    return sum(len(actions) for actions in actions_of.values()), ambiguous


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, seeds in (("train", TRAIN_SEEDS), ("valid", VALIDATION_SEEDS)):
        pairs, ambiguous = write(seeds, DATA / f"{name}.jsonl")
        print(
            f"{name}: seeds {seeds.start} to {seeds.stop - 1}, {pairs} distinct pairs, "
            f"{ambiguous} observations with more than one action"
        )


if __name__ == "__main__":
    main()
