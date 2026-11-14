"""The harness of the post-training experiment (training/). No model is needed here."""

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from training.make_dataset import (  # noqa: E402
    HELD_OUT_SEEDS,
    LEVEL,
    TRAIN_SEEDS,
    VALIDATION_SEEDS,
    reference_pairs,
)
from training.observation import (  # noqa: E402
    UNKNOWN,
    Action,
    Harness,
    format_action,
    parse_action,
)

from unknown_machine.calibration import build_episode, window_for  # noqa: E402
from unknown_machine.machine.episode import E_DEP, E_ORDER, Episode  # noqa: E402
from unknown_machine.machine.generate import generate  # noqa: E402
from unknown_machine.machine.model import CRASH, DATA_LOSS, REFUSED  # noqa: E402
from unknown_machine.reference.solver import solve  # noqa: E402

spec = importlib.util.spec_from_file_location("make_tasks", ROOT / "scripts" / "make_tasks.py")
make_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_tasks)

SEEDS = (1000, 1001, 1002, 5000, 5001)
TOOLS = ("status", "inspect", "dry_run", "run", "restart", "finish")


class SixTools:
    """A console with the six tools and nothing else, which keeps what they returned."""

    def __init__(self, episode: Episode) -> None:
        self.returned: list[tuple[str, tuple, dict]] = []
        for tool in TOOLS:
            setattr(self, tool, self._wrap(tool, getattr(episode, tool)))

    def _wrap(self, tool: str, call):
        def wrapped(*arguments: str) -> dict:
            result = call(*arguments)
            if tool != "status":
                self.returned.append((tool, arguments, result))
            return result

        return wrapped


def fields(observation: str) -> dict[str, dict[str, str]]:
    """service -> the labelled fields of its line."""
    services = {}
    for line in observation.splitlines()[1:-1]:
        name, *parts = line.split(" | ")
        services[name] = dict(part.split(": ", 1) for part in parts if ": " in part)
    return services


# ---- action lines --------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    (
        Action("inspect", "moss"),
        Action("dry_run", "moss", "rotate-keys"),
        Action("run", "moss", "start"),
        Action("restart", "moss"),
        Action("finish"),
    ),
)
def test_an_action_survives_being_written_and_read_back(action):
    text = format_action(action)
    assert "\n" not in text
    assert parse_action(text) == action
    assert parse_action(f"  {text}\nand a second line") == action


@pytest.mark.parametrize(
    "text",
    (
        "",
        "\n",
        "status",
        "run moss",
        "finish now",
        "inspect",
        "dry_run moss start twice",
        "Run moss start",
        "The next action is run moss start",
        '{"tool": "finish"}',
    ),
)
def test_text_that_is_not_an_action_is_rejected(text):
    assert parse_action(text) is None


def test_an_invalid_action_is_a_wasted_step_that_changes_nothing():
    episode = build_episode(SEEDS[0], LEVEL)
    harness = Harness(episode)
    for text in ("please start everything", "run nobody start", "inspect"):
        harness.step(text)
    assert (harness.steps, harness.invalid) == (3, 3)
    assert episode.result()["window_used"] == 0
    assert not episode.result()["log"]


def test_a_call_the_window_cannot_pay_for_teaches_nothing():
    system = generate(SEEDS[0], LEVEL)
    harness = Harness(Episode(system, 3))
    name = system.services[0].codename
    harness.step(f"inspect {name}")
    before = harness.observation().splitlines()[:-1]
    for text in (f"dry_run {name} start", f"inspect {name}", f"restart {name}"):
        assert harness.step(text).valid
    assert harness.observation().splitlines()[:-1] == before
    assert harness.observation().endswith(f"last: restart {name} -> refused E_WINDOW")


# ---- nothing hidden reaches the observation ---------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_harness_needs_only_the_six_tools(seed):
    console = SixTools(build_episode(seed, LEVEL))
    assert reference_pairs(console)


@pytest.mark.parametrize("seed", SEEDS)
def test_systems_that_differ_only_in_hidden_state_look_the_same(seed):
    """Another seed number, the opposite step order and other reactions to mistakes."""
    system = generate(seed, LEVEL)
    swapped = {REFUSED: CRASH, CRASH: DATA_LOSS, DATA_LOSS: REFUSED}
    twin = replace(
        system,
        seed=seed + 1,
        services=tuple(
            replace(
                service,
                steps=(*reversed(service.steps[:-1]), service.steps[-1]),
                order_violation=swapped[service.order_violation],
                dependency_violation=swapped[service.dependency_violation],
            )
            for service in system.services
        ),
    )
    assert twin != system
    window = window_for(system)
    observations = []
    for hidden in (system, twin):
        harness = Harness(Episode(hidden, window))
        for service in sorted(harness.status["services"]):
            harness.step(f"inspect {service}")
        observations.append(harness.observation())
    assert observations[0] == observations[1]


@pytest.mark.parametrize("seed", SEEDS)
def test_a_reaction_is_shown_only_after_a_tool_returned_it(seed):
    console = SixTools(build_episode(seed, LEVEL))
    harness = Harness(console)
    recorded = reference_pairs(build_episode(seed, LEVEL))
    for _, action in recorded:
        shown = {
            (arguments[0], result["code"]): result.get("would") or result["outcome"]
            for tool, arguments, result in console.returned
            if tool in ("dry_run", "run") and result["code"] in (E_ORDER, E_DEP)
        }
        for service, line in fields(harness.observation()).items():
            if "order" in line:
                assert line["order"] == shown.get((service, E_ORDER), UNKNOWN)
                assert line["dep"] == shown.get((service, E_DEP), UNKNOWN)
        harness.step(action)
    assert any(code == E_ORDER for _, code in shown), "the episode never showed a reaction"


def test_pending_commands_are_listed_by_name_not_in_the_order_they_apply():
    harness = Harness(build_episode(SEEDS[0], LEVEL))
    for service in sorted(harness.status["services"]):
        harness.step(f"inspect {service}")
    for line in fields(harness.observation()).values():
        assert line["pending"].split() == sorted(line["pending"].split())


# ---- the reference, played through the harness -------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_reference_scores_the_same_through_the_harness(seed):
    direct = build_episode(seed, LEVEL)
    solve(direct)
    expected = direct.result()

    recorded = reference_pairs(build_episode(seed, LEVEL))

    # A policy that knows nothing but the recorded action lines, on a fresh episode.
    replayed = build_episode(seed, LEVEL)
    harness = Harness(replayed)
    for observation, action in recorded:
        assert harness.observation() == observation
        assert harness.step(action).valid
    result = replayed.result()

    assert harness.finished and harness.invalid == 0
    assert expected["score"] == 1.0
    for key in ("score", "data_lost", "window_used", "tiers_banked", "log"):
        assert result[key] == expected[key], key


def test_the_seed_sets_are_disjoint_and_avoid_the_evaluation_seeds():
    evaluation = {seed for seeds in make_tasks.EVALUATION_SEEDS.values() for seed in seeds}
    sets = (set(TRAIN_SEEDS), set(VALIDATION_SEEDS), set(HELD_OUT_SEEDS), evaluation)
    assert len(set().union(*sets)) == sum(map(len, sets))
    assert len(HELD_OUT_SEEDS) >= 30
