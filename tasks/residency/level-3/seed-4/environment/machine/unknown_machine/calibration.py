"""Seed -> episode with its maintenance window.

The window is set from the reference run: the reference finishes the whole
recovery using REFERENCE_WINDOW_SHARE of it. That keeps every seed solvable
with slack, and equally tight for every seed.
"""

import math

from unknown_machine.machine.episode import Episode
from unknown_machine.machine.generate import generate
from unknown_machine.machine.model import System
from unknown_machine.machine.themes import LEGACY
from unknown_machine.reference.solver import solve

REFERENCE_WINDOW_SHARE = 0.7
UNLIMITED = 10**9


def reference_cost(system: System) -> int:
    """Window minutes the reference needs to finish this system."""
    episode = Episode(system, UNLIMITED)
    solve(episode)
    return episode.result()["window_used"]


def window_for(system: System) -> int:
    return math.ceil(reference_cost(system) / REFERENCE_WINDOW_SHARE)


def build_episode(seed: int, level: int = 1, theme: str = LEGACY) -> Episode:
    system = generate(seed, level, theme)
    return Episode(system, window_for(system))
