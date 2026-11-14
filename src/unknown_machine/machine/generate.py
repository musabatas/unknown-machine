"""Seed -> System. The only source of randomness is the Random built from the seed."""

import random
from dataclasses import dataclass, replace

from unknown_machine.machine.model import CRASH, DATA_LOSS, REFUSED, Service, Step, System

# role -> (preparation commands with the register each clears, commands never needed)
ROLE_COMMANDS: dict[str, tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = {
    "storage": (
        (
            ("fsck", "filesystem"),
            ("replay-journal", "journal"),
            ("attach", "volume"),
            ("scrub", "checksums"),
            ("verify-raid", "array"),
            ("resize", "quota"),
        ),
        ("format", "reinit"),
    ),
    "database": (
        (
            ("recover", "wal"),
            ("migrate", "schema"),
            ("reindex", "indexes"),
            ("unlock", "locks"),
            ("vacuum", "bloat"),
            ("promote", "replica-role"),
        ),
        ("reinit", "drop-wal"),
    ),
    "middleware": (
        (
            ("rehydrate", "snapshot"),
            ("rotate-keys", "keys"),
            ("drain", "backlog"),
            ("rebalance", "partitions"),
            ("compact", "log-segments"),
            ("reconnect", "peers"),
        ),
        ("purge", "reset-offsets"),
    ),
    "application": (
        (
            ("warm-cache", "cache"),
            ("load-config", "config"),
            ("register", "registration"),
            ("compile-assets", "assets"),
            ("migrate-sessions", "sessions"),
            ("seed-flags", "flags"),
        ),
        ("factory-reset", "rollback"),
    ),
    "gateway": (
        (
            ("sync-routes", "routes"),
            ("renew-cert", "certificate"),
            ("health-gate", "healthchecks"),
            ("pin-upstreams", "upstreams"),
            ("reload-acl", "acl"),
            ("warm-tls", "tls-sessions"),
        ),
        ("flush-routes", "force-failover"),
    ),
}

FINAL_STEP = {"gateway": ("cutover", "traffic")}
DEFAULT_FINAL_STEP = ("start", "process")

# Codenames carry no hint of a role.
CODENAMES = (
    "alder", "basalt", "bramble", "cobalt", "flint", "garnet", "heron", "juniper",
    "kestrel", "larch", "linden", "marrow", "moss", "onyx", "osprey", "pumice",
    "quartz", "saffron", "sedge", "sorrel", "tallow", "tern", "thistle", "wren",
)  # fmt: skip

VIOLATION_OUTCOMES = (REFUSED, CRASH, DATA_LOSS)
VIOLATION_WEIGHTS = (0.4, 0.3, 0.3)
DECOY_OUTCOMES = (DATA_LOSS, CRASH)
DECOY_WEIGHTS = (0.6, 0.4)

SAME_LAYER_DEPENDENCY = 0.6
EXTRA_DEPENDENCY = 0.3
PREP_STEP_NEEDS_DEPENDENCY = 0.35
MAX_INITIAL_LAG = 3


@dataclass(frozen=True)
class Size:
    """How large a system is."""

    services: dict[str, tuple[int, ...]]  # role -> possible number of services
    preparation: tuple[int, ...]  # possible number of preparation commands per service
    pool: int  # preparation commands each role exposes
    min_fragile: int  # services that destroy data when a command is applied out of order


SMALL = Size(
    services={
        "storage": (1, 2),
        "database": (1, 2),
        "middleware": (1, 2),
        "application": (1,),
        "gateway": (1,),
    },
    preparation=(2, 3),
    pool=4,
    min_fragile=2,
)
LARGE = Size(
    services={
        "storage": (3,),
        "database": (3,),
        "middleware": (3, 4),
        "application": (2, 3),
        "gateway": (1,),
    },
    preparation=(3, 4),
    pool=6,
    min_fragile=5,
)
EXACT = {1.0: 1.0}
NOISY = {1.0: 0.2, 0.9: 0.3, 0.8: 0.3, 0.7: 0.2}

# level -> (size, {dry-run accuracy: weight} drawn per service)
LEVELS = {1: (SMALL, EXACT), 2: (SMALL, NOISY), 3: (LARGE, NOISY)}


def generate(seed: int, level: int = 1) -> System:
    """Level 1: 5 to 8 services, exact dry runs. Level 2: the same systems, but each
    service's dry runs are only right with a stated probability. Level 3: 12 to 14
    services with longer procedures, and the same inexact dry runs."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level}")
    size, accuracy_weights = LEVELS[level]
    rng = random.Random(seed)

    roles: list[str] = []
    for role, counts in size.services.items():
        # A fixed count draws nothing, so levels of the same size share their systems.
        roles += [role] * (rng.choice(counts) if len(counts) > 1 else counts[0])
    codenames = rng.sample(CODENAMES, len(roles))
    by_role: dict[str, list[str]] = {}
    for role, codename in zip(roles, codenames, strict=True):
        by_role.setdefault(role, []).append(codename)

    services = []
    for role, codename in zip(roles, codenames, strict=True):
        dependencies = _dependencies(rng, role, codename, by_role)
        services.append(_service(rng, role, codename, dependencies, size))

    services = _ensure_fragile(rng, services, size.min_fragile)
    lag_service = by_role["database"][0]
    services = [
        _with_sync(service) if service.codename == lag_service else service for service in services
    ]
    initial_lag = rng.randint(0, MAX_INITIAL_LAG)

    # A separate stream, so a seed describes the same system at every level.
    level_rng = random.Random(f"accuracy-{seed}-{level}")
    values, weights = zip(*accuracy_weights.items(), strict=True)
    services = [
        replace(service, accuracy=level_rng.choices(values, weights)[0]) for service in services
    ]
    return System(
        seed=seed,
        level=level,
        services=tuple(sorted(services, key=lambda service: service.codename)),
        initial_lag=initial_lag,
        lag_service=lag_service,
    )


def _dependencies(
    rng: random.Random, role: str, codename: str, by_role: dict[str, list[str]]
) -> tuple[str, ...]:
    """Services that must be serving before this one can start."""
    required: list[str] = []
    lower: list[str] = []
    if role == "database":
        required.append(rng.choice(by_role["storage"]))
        lower = by_role["storage"]
    elif role == "middleware":
        required.append(rng.choice(by_role["database"]))
        lower = by_role["storage"] + by_role["database"]
    elif role == "application":
        required.append(rng.choice(by_role["database"]))
        required.append(rng.choice(by_role["middleware"]))
        lower = by_role["storage"] + by_role["database"] + by_role["middleware"]
    elif role == "gateway":
        required.extend(by_role["application"])
        lower = by_role["middleware"]

    peers = by_role[role]
    position = peers.index(codename)
    if position > 0 and rng.random() < SAME_LAYER_DEPENDENCY:
        required.append(peers[0])

    spare = [name for name in lower if name not in required]
    if spare and rng.random() < EXTRA_DEPENDENCY:
        required.append(rng.choice(spare))
    return tuple(sorted(set(required)))


def _service(
    rng: random.Random, role: str, codename: str, dependencies: tuple[str, ...], size: Size
) -> Service:
    pool, decoy_names = ROLE_COMMANDS[role]
    preparation = pool[: size.pool]
    chosen = rng.sample(preparation, rng.choice(size.preparation))
    steps = [
        Step(
            command=command,
            register=register,
            requires=tuple(
                name for name in dependencies if rng.random() < PREP_STEP_NEEDS_DEPENDENCY
            ),
        )
        for command, register in chosen
    ]
    final_command, final_register = FINAL_STEP.get(role, DEFAULT_FINAL_STEP)
    steps.append(Step(command=final_command, register=final_register, requires=dependencies))

    idle = tuple(pair for pair in preparation if pair not in chosen)
    decoys = tuple((name, rng.choices(DECOY_OUTCOMES, DECOY_WEIGHTS)[0]) for name in decoy_names)
    return Service(
        codename=codename,
        role=role,
        steps=tuple(steps),
        idle=idle,
        decoys=decoys,
        order_violation=rng.choices(VIOLATION_OUTCOMES, VIOLATION_WEIGHTS)[0],
        dependency_violation=rng.choices(VIOLATION_OUTCOMES, VIOLATION_WEIGHTS)[0],
    )


def _ensure_fragile(rng: random.Random, services: list[Service], minimum: int) -> list[Service]:
    """Every system has at least `minimum` services where a wrong order destroys data.

    Without this some seeds refuse every mistake, and running blindly is then optimal.
    """
    fragile = [s for s in services if DATA_LOSS in (s.order_violation, s.dependency_violation)]
    sturdy = [s for s in services if s not in fragile]
    missing = minimum - len(fragile)
    if missing <= 0:
        return services
    chosen = {s.codename for s in rng.sample(sturdy, missing)}
    return [replace(s, order_violation=DATA_LOSS) if s.codename in chosen else s for s in services]


def _with_sync(service: Service) -> Service:
    return replace(service, has_sync=True)
