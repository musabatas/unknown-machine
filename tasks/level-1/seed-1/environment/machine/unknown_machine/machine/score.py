"""Score of an episode, computed only from server-side state."""

TIER_POINTS = {1: 0.10, 2: 0.15, 3: 0.25, 4: 0.50}
DATA_LOSS_PENALTY = 0.15  # per service whose data was destroyed


def score(banked_tiers: frozenset[int] | set[int], services_lost: int) -> float:
    total = sum(TIER_POINTS[tier] for tier in banked_tiers)
    total -= DATA_LOSS_PENALTY * services_lost
    return round(min(1.0, max(0.0, total)), 4)
