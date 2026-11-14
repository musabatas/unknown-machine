"""The rules of the simulator: determinism, truthful dry runs, consistent reactions."""

import random
from dataclasses import replace

from unknown_machine.calibration import UNLIMITED, build_episode
from unknown_machine.machine.episode import E_DEP, E_ORDER, Episode
from unknown_machine.machine.generate import generate
from unknown_machine.machine.model import CRASH, OK
from unknown_machine.reference.solver import solve

SEEDS = range(40)


def play_randomly(episode: Episode, seed: int, steps: int = 80) -> list[dict]:
    """Arbitrary commands, dry-running each first; returns (preview, result) pairs."""
    rng = random.Random(seed)
    pairs = [
        (name, command)
        for name, service in sorted(episode.status()["services"].items())
        for command in service["commands"]
    ]
    observations = []
    for _ in range(steps):
        name, command = rng.choice(pairs)
        preview = episode.dry_run(name, command)
        result = episode.run(name, command)
        observations.append({"service": name, "preview": preview, "result": result})
        if result["outcome"] == CRASH:
            episode.restart(name)
    return observations


def test_same_seed_gives_the_same_system():
    for seed in SEEDS:
        assert generate(seed) == generate(seed)


def test_same_seed_gives_the_same_episode():
    for seed in SEEDS:
        first, second = build_episode(seed), build_episode(seed)
        solve(first)
        solve(second)
        assert first.result() == second.result()


def test_dry_run_always_predicts_the_real_outcome_at_level_1():
    for seed in SEEDS:
        episode = Episode(generate(seed), UNLIMITED)
        for observation in play_randomly(episode, seed):
            preview, result = observation["preview"], observation["result"]
            assert preview["would"] == result["outcome"]
            assert preview["code"] == result["code"]


def test_a_seed_describes_the_same_system_at_both_levels():
    for seed in SEEDS:
        exact, noisy = generate(seed, 1), generate(seed, 2)
        assert all(service.accuracy == 1.0 for service in exact.services)
        for first, second in zip(exact.services, noisy.services, strict=True):
            assert replace(second, accuracy=1.0) == first


def test_level_2_dry_runs_are_wrong_as_often_as_inspect_says():
    right: dict[float, list[bool]] = {}
    for seed in range(150):
        system = generate(seed, 2)
        episode = Episode(system, UNLIMITED)
        accuracy = {service.codename: service.accuracy for service in system.services}
        for observation in play_randomly(episode, seed):
            preview, result = observation["preview"], observation["result"]
            if result["code"] in (None, E_ORDER, E_DEP):  # the only question that can be wrong
                correct = preview["code"] == result["code"]
                right.setdefault(accuracy[observation["service"]], []).append(correct)
    assert set(right) == {1.0, 0.9, 0.8, 0.7}
    for stated, outcomes in right.items():
        assert abs(sum(outcomes) / len(outcomes) - stated) < 0.03, stated


def test_a_wrong_dry_run_still_shows_the_real_reaction():
    for seed in SEEDS:
        system = generate(seed, 2)
        episode = Episode(system, UNLIMITED)
        reactions = {
            service.codename: {
                E_ORDER: service.order_violation,
                E_DEP: service.dependency_violation,
            }
            for service in system.services
        }
        for observation in play_randomly(episode, seed):
            preview = observation["preview"]
            if preview["code"] in (E_ORDER, E_DEP) and observation["service"] != system.lag_service:
                assert preview["would"] == reactions[observation["service"]][preview["code"]]


def test_the_same_calls_get_the_same_wrong_reports():
    for seed in SEEDS:
        first = play_randomly(Episode(generate(seed, 2), UNLIMITED), seed)
        second = play_randomly(Episode(generate(seed, 2), UNLIMITED), seed)
        assert first == second


def test_dry_run_changes_nothing_but_the_window():
    for seed in SEEDS:
        episode = Episode(generate(seed), UNLIMITED)
        rng = random.Random(seed)
        for name, service in sorted(episode.status()["services"].items()):
            before = episode.status()
            episode.dry_run(name, rng.choice(service["commands"]))
            after = episode.status()
            assert before["services"] == after["services"]
            assert before["tiers_banked"] == after["tiers_banked"]


def test_a_service_reacts_to_a_kind_of_mistake_the_same_way_every_time():
    for seed in SEEDS:
        episode = Episode(generate(seed), UNLIMITED)
        reactions: dict[tuple[str, str], set[str]] = {}
        for observation in play_randomly(episode, seed, steps=200):
            result = observation["result"]
            if result["code"] in (E_ORDER, E_DEP) and result["outcome"] != OK:
                key = (observation["service"], result["code"])
                reactions.setdefault(key, set()).add(result["outcome"])
        for key, outcomes in reactions.items():
            if key[0] == episode._system.lag_service and key[1] == E_ORDER:
                continue  # `sync` before the database serves is always a plain refusal
            assert len(outcomes) == 1, (seed, key, outcomes)


def test_inspect_lists_pending_registers_without_revealing_their_order():
    for seed in SEEDS:
        episode = Episode(generate(seed), UNLIMITED)
        for name in episode.status()["services"]:
            registers = [item["register"] for item in episode.inspect(name)["pending"]]
            assert registers == sorted(registers)


def test_codenames_do_not_identify_roles():
    roles_by_codename: dict[str, set[str]] = {}
    for seed in range(300):
        for service in generate(seed).services:
            roles_by_codename.setdefault(service.codename, set()).add(service.role)
    assert all(len(roles) == 5 for roles in roles_by_codename.values())


def test_banked_tiers_survive_a_later_crash():
    for seed in SEEDS:
        system = generate(seed)
        episode = Episode(system, UNLIMITED)
        solve(episode, stop_after_tier=1)
        assert episode.result()["tiers_banked"] == [1]
        again = Episode(system, UNLIMITED)
        solve(again)
        assert again.result()["tiers_banked"] == [1, 2, 3, 4]
