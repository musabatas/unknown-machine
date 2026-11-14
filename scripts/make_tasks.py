"""Generate Harbor task directories from scripts/task_template.

    poetry run python scripts/make_tasks.py                       # the whole evaluation set
    poetry run python scripts/make_tasks.py 2 14 38               # level 2, seeds 14 and 38
    poetry run python scripts/make_tasks.py 4 7 --theme aircraft  # the same, in another theme

Each task gets a copy of the simulator package inside the sidecar's build
context, the solver inside solution/, the instruction of its theme, and a
result-signing key (kept when the task already exists, so regenerating leaves a
clean diff).
"""

import argparse
import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "task_template"
INSTRUCTIONS = TEMPLATE / "instructions"
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

# A theme changes the words of a system and nothing else, so the same seeds qualify
# in every theme. The themes other than the first are generated at the levels that
# separate an agent from the reference.
LEGACY = "legacy"
DESCRIPTIONS = {
    LEGACY: "Bring an undocumented legacy production system back online without losing data",
    "aircraft": "Bring a captured aircraft of an unknown type to take-off without damaging it",
    "residency": "Obtain a residence permit from a state that publishes none of its rules",
}
THEMED_LEVELS = (3, 4)

TEXT_FILES = ("task.toml", "environment/docker-compose.yaml")


def task_dir(level: int, seed: int, theme: str = LEGACY) -> Path:
    base = TASKS if theme == LEGACY else TASKS / theme
    return base / f"level-{level}" / f"seed-{seed}"


def evaluation_tasks() -> list[tuple[int, int, str]]:
    """(level, seed, theme) of every task of the evaluation set."""
    return [
        (level, seed, theme)
        for theme in DESCRIPTIONS
        for level, seeds in EVALUATION_SEEDS.items()
        if theme == LEGACY or level in THEMED_LEVELS
        for seed in seeds
    ]


def existing_key(target: Path) -> str | None:
    """The key of an already generated task, so regenerating does not rotate it."""
    config = target / "task.toml"
    if not config.exists():
        return None
    match = re.search(r'^RESULT_KEY = "([0-9a-f]+)"$', config.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def make_task(level: int, seed: int, theme: str = LEGACY) -> Path:
    target = task_dir(level, seed, theme)
    key = existing_key(target) or secrets.token_hex(24)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, target, ignore=shutil.ignore_patterns("instructions", "__pycache__"))
    shutil.copy(INSTRUCTIONS / f"{theme}.md", target / "instruction.md")

    shutil.copytree(
        PACKAGE,
        target / "environment" / "machine" / "unknown_machine",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(PACKAGE / "reference" / "solver.py", target / "solution" / "solver.py")

    prefix = "" if theme == LEGACY else f"{theme}-"
    values = {
        "__NAME__": f"{prefix}level-{level}-seed-{seed}",
        "__DESCRIPTION__": DESCRIPTIONS[theme],
        "__SEED__": str(seed),
        "__LEVEL__": str(level),
        "__THEME__": theme,
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("level", type=int, nargs="?", help="one level (default: evaluation set)")
    parser.add_argument("seeds", type=int, nargs="*", help="seeds of that level")
    parser.add_argument("--theme", choices=sorted(DESCRIPTIONS), default=LEGACY)
    arguments = parser.parse_args()

    if arguments.level is None:
        tasks = evaluation_tasks()
    else:
        tasks = [(arguments.level, seed, arguments.theme) for seed in arguments.seeds]
    for level, seed, theme in tasks:
        print(make_task(level, seed, theme).relative_to(ROOT))


if __name__ == "__main__":
    main()
