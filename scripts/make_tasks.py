"""Generate Harbor task directories from scripts/task_template.

    poetry run python scripts/make_tasks.py            # the evaluation set
    poetry run python scripts/make_tasks.py 14 38      # specific seeds

Each task gets a copy of the simulator package inside the sidecar's build
context, the solver inside solution/, and a result-signing key (kept when the
task already exists, so regenerating leaves a clean diff).
"""

import re
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "task_template"
PACKAGE = ROOT / "src" / "unknown_machine"
TASKS = ROOT / "tasks"

# Seeds of the evaluation set. Chosen as the first seeds on which neither naive
# policy (dry-run everything, dry-run nothing) scores above 0.5; see
# tests/test_baselines.py, which enforces that property.
EVALUATION_SEEDS = (0, 1, 2, 3, 4)

TEXT_FILES = ("task.toml", "environment/docker-compose.yaml")


def existing_key(target: Path) -> str | None:
    """The key of an already generated task, so regenerating does not rotate it."""
    config = target / "task.toml"
    if not config.exists():
        return None
    match = re.search(r'^RESULT_KEY = "([0-9a-f]+)"$', config.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def make_task(seed: int) -> Path:
    name = f"seed-{seed}"
    target = TASKS / name
    key = existing_key(target) or secrets.token_hex(24)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATE, target)

    shutil.copytree(
        PACKAGE,
        target / "environment" / "machine" / "unknown_machine",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(PACKAGE / "reference" / "solver.py", target / "solution" / "solver.py")

    values = {"__NAME__": name, "__SEED__": str(seed), "__RESULT_KEY__": key}
    for relative in TEXT_FILES:
        path = target / relative
        text = path.read_text()
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        path.write_text(text)
    return target


def main() -> None:
    seeds = [int(argument) for argument in sys.argv[1:]] or list(EVALUATION_SEEDS)
    for seed in seeds:
        print(make_task(seed).relative_to(ROOT))


if __name__ == "__main__":
    main()
