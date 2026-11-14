"""Write reference trajectories as chat-format training data for a small model.

    poetry run python scripts/export_trajectories.py --seeds 1000 2000 --out data/train.jsonl
    poetry run python scripts/export_trajectories.py --seeds 5000 5100 --out data/heldout.jsonl

Each line is one episode: a system prompt with the task instruction, then
alternating assistant tool calls and tool results, exactly as the reference
played them. Seeds used for training must not overlap the evaluation seeds
(0 to 4) or the held-out range.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from make_tasks import EVALUATION_SEEDS  # noqa: E402

from unknown_machine.calibration import build_episode  # noqa: E402
from unknown_machine.reference.solver import solve  # noqa: E402

INSTRUCTION = (ROOT / "scripts" / "task_template" / "instructions" / "legacy.md").read_text()
TOOLS = ("status", "inspect", "dry_run", "run", "restart", "finish")


class Recorder:
    """Passes every tool call through to the episode and keeps the exchange."""

    def __init__(self, episode) -> None:
        self._episode = episode
        self.messages: list[dict] = [{"role": "system", "content": INSTRUCTION}]

    def __getattr__(self, tool: str):
        if tool not in TOOLS:
            raise AttributeError(tool)

        def call(*arguments: str) -> dict:
            names = ("service", "command")[: len(arguments)]
            result = getattr(self._episode, tool)(*arguments)
            self.messages.append(
                {
                    "role": "assistant",
                    "tool_call": {
                        "name": tool,
                        "arguments": dict(zip(names, arguments, strict=True)),
                    },
                }
            )
            self.messages.append({"role": "tool", "name": tool, "content": json.dumps(result)})
            return result

        return call


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs=2, metavar=("FIRST", "LAST"), required=True)
    parser.add_argument("--level", type=int, default=2, choices=sorted(EVALUATION_SEEDS))
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    first, last = arguments.seeds
    if any(first <= seed < last for seed in EVALUATION_SEEDS[arguments.level]):
        raise SystemExit("the seed range overlaps the evaluation seeds")

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    episodes = calls = skipped = 0
    with arguments.out.open("w") as output:
        for seed in range(first, last):
            episode = build_episode(seed, arguments.level)
            recorder = Recorder(episode)
            solve(recorder)
            if episode.result()["score"] != 1.0:
                skipped += 1  # only complete recoveries are worth imitating
                continue
            record = {"seed": seed, "level": arguments.level, "messages": recorder.messages}
            output.write(json.dumps(record) + "\n")
            episodes += 1
            calls += len(recorder.messages) // 2
    print(f"{episodes} episodes, {calls} tool calls, {skipped} skipped -> {arguments.out}")


if __name__ == "__main__":
    main()
