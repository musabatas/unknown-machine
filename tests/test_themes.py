"""A theme changes the words of a system and nothing else."""

import importlib.util
import re
from pathlib import Path

import pytest

from unknown_machine.baselines.policies import BASELINES
from unknown_machine.calibration import build_episode
from unknown_machine.machine.generate import generate
from unknown_machine.machine.model import (
    COST_DRY_RUN,
    COST_INSPECT,
    COST_RESTART,
    COST_RUN,
    ROLE_LAYER,
)
from unknown_machine.machine.score import DATA_LOSS_PENALTY, TIER_POINTS
from unknown_machine.machine.themes import LEGACY, THEMES
from unknown_machine.reference import solver

ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS = ROOT / "scripts" / "task_template" / "instructions"
OTHERS = [name for name in THEMES if name != LEGACY]
SEEDS = range(30)
LEVELS = (1, 2, 3, 4)

spec = importlib.util.spec_from_file_location("make_tasks", ROOT / "scripts" / "make_tasks.py")
make_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_tasks)


def shape(system) -> list:
    """Everything about a system except its words, in codename order."""
    position = {service.codename: index for index, service in enumerate(system.services)}
    return [
        (
            ROLE_LAYER[service.role],
            [sorted(position[name] for name in step.requires) for step in service.steps],
            len(service.idle),
            [outcome for _, outcome in service.decoys],
            service.order_violation,
            service.dependency_violation,
            service.has_sync,
            service.accuracy,
        )
        for service in system.services
    ] + [system.initial_lag, position[system.lag_service]]


def test_every_theme_has_a_complete_vocabulary_of_its_own():
    for theme in THEMES.values():
        assert len(theme.roles) == 5
        assert set(theme.commands) == set(theme.roles)
        for preparation, decoys in theme.commands.values():
            assert len(preparation) == 6 and len(decoys) == 2
            names = [command for command, _ in preparation] + list(decoys)
            # The fixed commands must never be mistaken for a preparation command.
            fixed = {theme.final_step[0], theme.last_final_step[0], theme.sync_command}
            assert not fixed & set(names)
        assert len(set(theme.codenames)) == len(THEMES[LEGACY].codenames)
    roles = [role for theme in THEMES.values() for role in theme.roles]
    assert len(roles) == len(set(roles))


@pytest.mark.parametrize("theme", OTHERS)
@pytest.mark.parametrize("level", LEVELS)
def test_a_seed_has_the_same_structure_in_every_theme(theme, level):
    for seed in SEEDS:
        plain, told = generate(seed, level), generate(seed, level, theme)
        assert shape(told) == shape(plain), seed
        assert told.theme == theme
        words = THEMES[theme]
        for service in told.services:
            assert service.role in words.roles
            assert service.codename in words.codenames
            last = words.last_final_step if service.layer == 5 else words.final_step
            assert service.steps[-1].command == last[0]
            allowed = {command for command, _ in words.commands[service.role][0]}
            assert {step.command for step in service.steps[:-1]} <= allowed


@pytest.mark.parametrize("theme", list(THEMES))
def test_codenames_of_a_theme_do_not_identify_roles(theme):
    roles_by_codename: dict[str, set[str]] = {}
    for seed in range(300):
        for service in generate(seed, 1, theme).services:
            roles_by_codename.setdefault(service.codename, set()).add(service.role)
    assert all(len(roles) == 5 for roles in roles_by_codename.values())
    words = THEMES[theme]
    vocabulary = {word for role in words.roles for word in re.split(r"\W+", role)}
    for preparation, decoys in words.commands.values():
        for command, register in preparation:
            vocabulary |= set(re.split(r"\W+", command)) | set(re.split(r"\W+", register))
        for decoy in decoys:
            vocabulary |= set(re.split(r"\W+", decoy))
    assert not vocabulary & set(words.codenames)


@pytest.mark.parametrize("theme", OTHERS)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("policy", ("reference", "cautious", "greedy", "stop_early"))
def test_a_policy_plays_a_seed_the_same_in_every_theme(theme, level, policy):
    for seed in range(8):
        results = []
        for name in (LEGACY, theme):
            episode = build_episode(seed, level, name)
            BASELINES[policy](episode)
            result = episode.result()
            results.append(
                (
                    result["score"],
                    result["window_used"],
                    result["window_total"],
                    result["calls"],
                    len(result["data_lost"]),
                    [(entry["tool"], entry["outcome"], entry["code"]) for entry in result["log"]],
                )
            )
        assert results[0] == results[1], seed


def test_the_reference_knows_the_words_of_every_theme():
    """The solver is a single file that cannot import the themes; its table must agree."""
    stated = {
        (
            theme.roles,
            theme.final_step[0],
            theme.last_final_step[0],
            theme.lag_register,
            theme.sync_command,
        )
        for theme in THEMES.values()
    }
    assert set(solver.SCENARIOS) == stated


@pytest.mark.parametrize("theme", list(THEMES))
def test_the_instruction_of_a_theme_states_the_real_rules(theme):
    text = (INSTRUCTIONS / f"{theme}.md").read_text()
    words = THEMES[theme]

    def cost(tool: str) -> int:
        row = re.search(rf"^\| `{tool}\(.*\| (\d+) \|$", text, re.MULTILINE)
        assert row, tool
        return int(row.group(1))

    assert cost("status") == 0 and cost("finish") == 0
    assert cost("inspect") == COST_INSPECT
    assert cost("dry_run") == COST_DRY_RUN
    assert cost("run") == COST_RUN
    assert cost("restart") == COST_RESTART

    tiers = re.findall(r"^\| ([1-4]) \| (.*) \| (\d\.\d\d) \|$", text, re.MULTILINE)
    assert {int(tier): float(points) for tier, _, points in tiers} == TIER_POINTS
    named = [re.findall(r"`([^`]+)`", condition) for _, condition, _ in tiers]
    assert named == [[words.roles[0]], [words.roles[1]], list(words.roles[2:4]), [words.roles[4]]]
    assert f"costs {DATA_LOSS_PENALTY:.2f}" in text

    for word in (
        words.final_step[0],
        words.last_final_step[0],
        words.sync_command,
        words.lag_register,
        "dry_run_accuracy",
    ):
        assert f"`{word}`" in text, word
    for code in ("E_ORDER", "E_DEP", "E_DONE", "E_LAG", "E_FOREIGN", "E_CRASHED", "E_LOST",
                 "E_HEALTHY", "E_WINDOW", "E_UNKNOWN", "E_FINISHED"):  # fmt: skip
        assert f"| `{code}` |" in text, code
    # No theme's instruction borrows another theme's words.
    for other in THEMES.values():
        if other is not words:
            assert not any(f"`{role}`" in text for role in other.roles)


def test_every_theme_has_an_instruction_and_a_description():
    assert {path.stem for path in INSTRUCTIONS.glob("*.md")} == set(THEMES)
    assert set(make_tasks.DESCRIPTIONS) == set(THEMES)
    assert make_tasks.LEGACY == LEGACY


def test_legacy_tasks_keep_their_place_and_themed_ones_get_their_own():
    assert make_tasks.task_dir(3, 0) == make_tasks.TASKS / "level-3" / "seed-0"
    assert make_tasks.task_dir(3, 0, "aircraft") == make_tasks.TASKS / "aircraft/level-3/seed-0"
    tasks = make_tasks.evaluation_tasks()
    assert {level for level, _, theme in tasks if theme != LEGACY} == set(make_tasks.THEMED_LEVELS)
    assert {level for level, _, theme in tasks if theme == LEGACY} == set(
        make_tasks.EVALUATION_SEEDS
    )
