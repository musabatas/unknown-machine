"""Generate Harbor task directories from scripts/task_template.

    poetry run python scripts/make_tasks.py              # the evaluation set, every level
    poetry run python scripts/make_tasks.py 2 14 38      # level 2, seeds 14 and 38

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

# The evaluation set: per level, the first five seeds on which the reference scores
# 1.0 and neither naive policy (one dry run before every command; no dry runs)
# scores above 0.5. About two seeds in three qualify at levels 1 and 2; at levels 3
# and 4 the first five seeds all do.
# tests/test_baselines.py enforces the property.
EVALUATION_SEEDS = {
    1: (0, 1, 2, 3, 4),
    2: (0, 1, 2, 3, 5),
    3: (0, 1, 2, 3, 4),
    4: (0, 1, 2, 3, 4),
}

TEXT_FILES = ("task.toml", "environment/docker-compose.yaml")


def task_dir(level: int, seed: int) -> Path:
    return TASKS / f"level-{level}" / f"seed-{seed}"


def existing_key(target: Path) -> str | None:
    """The key of an already generated task, so regenerating does not rotate it."""
    config = target / "task.toml"
    if not config.exists():
        return None
    match = re.search(r'^RESULT_KEY = "([0-9a-f]+)"$', config.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def make_task(level: int, seed: int) -> Path:
    target = task_dir(level, seed)
    key = existing_key(target) or secrets.token_hex(24)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, target)

    shutil.copytree(
        PACKAGE,
        target / "environment" / "machine" / "unknown_machine",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(PACKAGE / "reference" / "solver.py", target / "solution" / "solver.py")

    values = {
        "__NAME__": f"level-{level}-seed-{seed}",
        "__SEED__": str(seed),
        "__LEVEL__": str(level),
        "__RESULT_KEY__": key,
    }
    for relative in TEXT_FILES:
        path = target / relative
        text = path.read_text()
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        path.write_text(text)
    return target


def main() -> None:
    if len(sys.argv) > 1:
        level, *seeds = (int(argument) for argument in sys.argv[1:])
        pairs = [(level, seed) for seed in seeds]
    else:
        pairs = [(level, seed) for level, seeds in EVALUATION_SEEDS.items() for seed in seeds]
    for level, seed in pairs:
        print(make_task(level, seed).relative_to(ROOT))


if __name__ == "__main__":
    main()
