"""What the reference and the scripted baselines score. These are the claims in the README."""

import importlib.util
import statistics
from pathlib import Path

import pytest

from unknown_machine.baselines.policies import BASELINES
from unknown_machine.calibration import REFERENCE_WINDOW_SHARE, build_episode

SEEDS = range(100)
LEVELS = (1, 2, 3, 4)

spec = importlib.util.spec_from_file_location(
    "make_tasks", Path(__file__).resolve().parent.parent / "scripts" / "make_tasks.py"
)
make_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_tasks)


def play(policy: str, seed: int, level: int) -> dict:
    episode = build_episode(seed, level)
    BASELINES[policy](episode)
    return episode.result()


def test_reference_finishes_every_level_1_seed_without_losing_data():
    for seed in SEEDS:
        result = play("reference", seed, 1)
        assert result["score"] == 1.0, seed
        assert not result["data_lost"], seed


@pytest.mark.parametrize("level", (2, 3, 4))
def test_reference_almost_always_finishes_where_dry_runs_can_be_wrong(level):
    """A small accepted risk remains there, so not every seed is perfect."""
    results = [play("reference", seed, level) for seed in SEEDS]
    assert statistics.mean(result["score"] for result in results) >= 0.97
    assert sum(bool(result["data_lost"]) for result in results) <= 3


@pytest.mark.parametrize("level", LEVELS)
def test_reference_stays_inside_its_share_of_the_window(level):
    for seed in SEEDS:
        result = play("reference", seed, level)
        assert result["window_used"] <= REFERENCE_WINDOW_SHARE * result["window_total"] + 1, seed


@pytest.mark.parametrize("level", LEVELS)
def test_doing_nothing_scores_zero(level):
    for seed in SEEDS:
        assert play("do_nothing", seed, level)["score"] == 0.0


@pytest.mark.parametrize("level", LEVELS)
def test_stopping_after_the_first_tier_scores_at_most_a_tenth(level):
    for seed in SEEDS:
        assert play("stop_early", seed, level)["score"] <= 0.10


@pytest.mark.parametrize("level", LEVELS)
def test_random_commands_score_nothing(level):
    scores = [play("random", seed, level)["score"] for seed in SEEDS]
    assert max(scores) <= 0.15
    assert statistics.mean(scores) <= 0.02


def test_one_dry_run_before_every_command_runs_out_of_window_at_level_1():
    scores = [play("cautious", seed, 1)["score"] for seed in SEEDS]
    assert statistics.mean(scores) <= 0.60


def test_believing_a_single_dry_run_fails_at_level_2():
    """It runs out of window as at level 1, and on about a third of seeds it also
    destroys data by acting on a wrong report."""
    results = [play("cautious", seed, 2) for seed in SEEDS]
    assert statistics.mean(result["score"] for result in results) <= 0.35
    assert sum(bool(result["data_lost"]) for result in results) >= 0.2 * len(results)


@pytest.mark.parametrize("level", LEVELS)
def test_never_dry_running_loses_data(level):
    results = [play("greedy", seed, level) for seed in SEEDS]
    assert statistics.mean(result["score"] for result in results) <= 0.25
    assert sum(bool(result["data_lost"]) for result in results) >= 0.7 * len(results)


def test_the_evaluation_seeds_are_the_first_five_that_qualify():
    """Reference 1.0, both naive policies at or below 0.5: the stated selection rule."""
    for level, chosen in make_tasks.EVALUATION_SEEDS.items():
        qualifying = []
        seed = 0
        while len(qualifying) < len(chosen):
            if (
                play("reference", seed, level)["score"] == 1.0
                and play("cautious", seed, level)["score"] <= 0.5
                and play("greedy", seed, level)["score"] <= 0.5
            ):
                qualifying.append(seed)
            seed += 1
        assert tuple(qualifying) == chosen, level
