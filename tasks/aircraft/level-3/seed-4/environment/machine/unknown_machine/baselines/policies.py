"""Scripted baselines. Each takes a console (the six tools) and plays one episode."""

import random

from unknown_machine.reference.solver import CAUTIOUS, GREEDY, REFERENCE, solve


def reference(console) -> None:
    solve(console, policy=REFERENCE)


def do_nothing(console) -> None:
    console.finish()


def stop_early(console) -> None:
    """Plays well until the first tier is banked, then walks away."""
    solve(console, policy=REFERENCE, stop_after_tier=1)


def cautious(console) -> None:
    """Dry-runs every command before running it."""
    solve(console, policy=CAUTIOUS)


def greedy(console) -> None:
    """Runs the commands the logs ask for and never dry-runs."""
    solve(console, policy=GREEDY)


def random_actions(console, seed: int = 0) -> None:
    """Runs arbitrary commands until the window is gone."""
    rng = random.Random(seed)
    status = console.status()
    pairs = [
        (name, command)
        for name, service in sorted(status["services"].items())
        for command in service["commands"]
    ]
    while not status["finished"] and status["window_remaining"] > 0:
        name, command = rng.choice(pairs)
        console.run(name, command)
        status = console.status()
    console.finish()


BASELINES = {
    "reference": reference,
    "do_nothing": do_nothing,
    "stop_early": stop_early,
    "cautious": cautious,
    "greedy": greedy,
    "random": random_actions,
}
