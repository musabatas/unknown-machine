"""What the reference and the scripted baselines score. These are the claims in the README."""

import importlib.util
import statistics
from pathlib import Path

from unknown_machine.baselines.policies import BASELINES
from unknown_machine.calibration import REFERENCE_WINDOW_SHARE, build_episode

SEEDS = range(100)

spec = importlib.util.spec_from_file_location(
    "make_tasks", Path(__file__).resolve().parent.parent / "scripts" / "make_tasks.py"
)
make_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_tasks)


def play(policy: str, seed: int) -> dict:
    episode = build_episode(seed)
    BASELINES[policy](episode)
    return episode.result()


def test_reference_finishes_every_seed_inside_its_share_of_the_window():
    for seed in SEEDS:
        result = play("reference", seed)
        assert result["score"] == 1.0, seed
        assert not result["data_lost"], seed
        assert result["window_used"] <= REFERENCE_WINDOW_SHARE * result["window_total"] + 1, seed


def test_doing_nothing_scores_zero():
    for seed in SEEDS:
        assert play("do_nothing", seed)["score"] == 0.0


def test_stopping_after_the_first_tier_scores_a_tenth():
    for seed in SEEDS:
        assert play("stop_early", seed)["score"] == 0.10


def test_random_commands_score_nothing():
    scores = [play("random", seed)["score"] for seed in SEEDS]
    assert max(scores) <= 0.15
    assert statistics.mean(scores) <= 0.02


def test_dry_running_everything_runs_out_of_window():
    scores = [play("cautious", seed)["score"] for seed in SEEDS]
    assert statistics.mean(scores) <= 0.60


def test_never_dry_running_loses_data():
    results = [play("greedy", seed) for seed in SEEDS]
    assert statistics.mean(result["score"] for result in results) <= 0.25
    assert sum(bool(result["data_lost"]) for result in results) >= 0.7 * len(results)


def test_neither_naive_policy_gets_past_half_on_the_evaluation_seeds():
    for seed in make_tasks.EVALUATION_SEEDS:
        assert play("cautious", seed)["score"] <= 0.5, seed
        assert play("greedy", seed)["score"] <= 0.5, seed
