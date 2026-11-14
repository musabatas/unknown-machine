"""Reproduce the evaluation: reference, baselines and (optionally) agent runs.

    poetry run python scripts/evaluate.py
        Free. Reference, do-nothing and stop-early through Harbor, the other
        scripted baselines in-process, on every evaluation task.

    poetry run python scripts/evaluate.py --model openai/gpt-6.1-sol --env-file .env
        Also runs the OpenCode agent --runs times per task. Costs API credits.

Every Harbor run is kept under jobs/<name>/ with its trajectory and verifier output.
"""

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from make_tasks import EVALUATION_SEEDS  # noqa: E402

from unknown_machine.baselines.policies import BASELINES  # noqa: E402
from unknown_machine.calibration import build_episode  # noqa: E402

IN_PROCESS = ("cautious", "greedy", "random")
# The stop-early baseline is the task's own solution told to stop after tier 1.
STOP_EARLY = ["--ae", "POLICY=stop_early"]


def harbor_rewards(task: Path, agent: str, job: str, extra: list[str]) -> list[float]:
    """Run one Harbor job and return the reward of each trial."""
    command = ["harbor", "run", "-p", str(task), "-a", agent, "--job-name", job, "-q", *extra]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    rewards = [
        float(path.read_text().strip())
        for path in sorted((ROOT / "jobs" / job).glob("*/verifier/reward.txt"))
    ]
    if completed.returncode != 0 or not rewards:
        print(completed.stdout[-2000:], completed.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"harbor run failed for {task.name} with agent {agent}")
    return rewards


def in_process(policy: str, seed: int, level: int) -> float:
    episode = build_episode(seed, level)
    BASELINES[policy](episode)
    return episode.result()["score"]


def evaluate_level(level: int, seeds: list[int], arguments, stamp: str, columns: list[str]) -> None:
    rows: dict[int, dict[str, list[float]]] = {}
    for seed in seeds:
        task = ROOT / "tasks" / f"level-{level}" / f"seed-{seed}"
        if not task.exists():
            raise SystemExit(f"{task} is missing; run scripts/make_tasks.py {level} {seed}")
        job = f"eval-{stamp}-l{level}s{seed}"
        row = {
            "reference": harbor_rewards(task, "oracle", f"{job}-reference", []),
            "do_nothing": harbor_rewards(task, "nop", f"{job}-nothing", []),
            "stop_early": harbor_rewards(task, "oracle", f"{job}-stopearly", STOP_EARLY),
        }
        for policy in IN_PROCESS:
            row[policy] = [in_process(policy, seed, level)]
        if arguments.model:
            extra = ["-m", arguments.model, "-k", str(arguments.runs), "-n", str(arguments.runs)]
            if arguments.env_file:
                extra += ["--env-file", arguments.env_file]
            row["agent"] = harbor_rewards(task, "opencode", f"{job}-agent", extra)
        rows[seed] = row
        print(f"level {level} seed {seed} done", file=sys.stderr)

    print(f"\nLevel {level}\n")
    print("| seed | " + " | ".join(columns) + " |")
    print("|---|" + "---|" * len(columns))
    for seed, row in rows.items():
        cells = [" ".join(f"{value:.2f}" for value in row[column]) for column in columns]
        print(f"| {seed} | " + " | ".join(cells) + " |")
    means = [
        f"{statistics.mean(value for row in rows.values() for value in row[column]):.2f}"
        for column in columns
    ]
    print("| mean | " + " | ".join(means) + " |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model", help="provider/model for the OpenCode agent, e.g. openai/gpt-6.1-sol"
    )
    parser.add_argument("--runs", type=int, default=3, help="agent runs per task (default 3)")
    parser.add_argument("--env-file", help="file with the API key for --model")
    parser.add_argument("--level", type=int, choices=sorted(EVALUATION_SEEDS), help="one level")
    parser.add_argument("--seeds", type=int, nargs="*", help="seeds (default: evaluation set)")
    arguments = parser.parse_args()

    stamp = time.strftime("%m%d-%H%M%S")
    columns = ["reference", "do_nothing", "stop_early", *IN_PROCESS]
    if arguments.model:
        columns.append("agent")
    levels = [arguments.level] if arguments.level else sorted(EVALUATION_SEEDS)
    for level in levels:
        seeds = arguments.seeds or list(EVALUATION_SEEDS[level])
        evaluate_level(level, seeds, arguments, stamp, columns)

    if arguments.model:
        print(f"\nagent: opencode with {arguments.model}, {arguments.runs} runs per task")
    print("\nreference, do_nothing and stop_early ran through Harbor; the others in-process.")
    print("cautious = one dry run before every command; greedy = no dry runs.")


if __name__ == "__main__":
    main()
