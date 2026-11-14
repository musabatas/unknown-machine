"""Reproduce the evaluation: reference, baselines and (optionally) agent runs.

    poetry run python scripts/evaluate.py
        Free. Reference and do-nothing through Harbor, the scripted baselines
        in-process, on every evaluation task.

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

IN_PROCESS = ("stop_early", "cautious", "greedy", "random")


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


def in_process(policy: str, seed: int) -> float:
    episode = build_episode(seed)
    BASELINES[policy](episode)
    return episode.result()["score"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model", help="provider/model for the OpenCode agent, e.g. openai/gpt-6.1-sol"
    )
    parser.add_argument("--runs", type=int, default=3, help="agent runs per task (default 3)")
    parser.add_argument("--env-file", help="file with the API key for --model")
    parser.add_argument("--seeds", type=int, nargs="*", default=list(EVALUATION_SEEDS))
    arguments = parser.parse_args()

    stamp = time.strftime("%m%d-%H%M%S")
    columns = ["reference", "do_nothing", *IN_PROCESS]
    if arguments.model:
        columns.append("agent")
    rows: dict[int, dict[str, list[float]]] = {}

    for seed in arguments.seeds:
        task = ROOT / "tasks" / f"seed-{seed}"
        if not task.exists():
            raise SystemExit(f"{task} is missing; run scripts/make_tasks.py {seed}")
        row = {
            "reference": harbor_rewards(task, "oracle", f"eval-{stamp}-seed{seed}-reference", []),
            "do_nothing": harbor_rewards(task, "nop", f"eval-{stamp}-seed{seed}-nothing", []),
        }
        for policy in IN_PROCESS:
            row[policy] = [in_process(policy, seed)]
        if arguments.model:
            extra = ["-m", arguments.model, "-k", str(arguments.runs), "-n", str(arguments.runs)]
            if arguments.env_file:
                extra += ["--env-file", arguments.env_file]
            row["agent"] = harbor_rewards(task, "opencode", f"eval-{stamp}-seed{seed}-agent", extra)
        rows[seed] = row
        print(f"seed {seed} done", file=sys.stderr)

    print("\n| seed | " + " | ".join(columns) + " |")
    print("|---|" + "---|" * len(columns))
    for seed, row in rows.items():
        cells = [" ".join(f"{value:.2f}" for value in row[column]) for column in columns]
        print(f"| {seed} | " + " | ".join(cells) + " |")
    means = [
        f"{statistics.mean(value for row in rows.values() for value in row[column]):.2f}"
        for column in columns
    ]
    print("| mean | " + " | ".join(means) + " |")
    if arguments.model:
        print(f"\nagent: opencode with {arguments.model}, {arguments.runs} runs per task")
    print("reference and do_nothing ran through Harbor; the other baselines in-process.")


if __name__ == "__main__":
    main()
