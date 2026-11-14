"""Static description of one legacy system. Immutable; all episode state lives in Episode."""

from dataclasses import dataclass

OK = "ok"
REFUSED = "refused"
CRASH = "crash"
DATA_LOSS = "data_loss"

# Roles and the layer each belongs to. A tier is banked when every service
# up to a given layer is serving.
ROLE_LAYER = {"storage": 1, "database": 2, "middleware": 3, "application": 4, "gateway": 5}
TIER_MAX_LAYER = {1: 1, 2: 2, 3: 4, 4: 5}

# Budget cost of each tool, in maintenance-window minutes.
COST_RUN = 1
COST_INSPECT = 2
COST_DRY_RUN = 4
COST_RESTART = 4

SYNC_COMMAND = "sync"
LAG_REGISTER = "replication_lag"


@dataclass(frozen=True)
class Step:
    """One command of a service's recovery procedure."""

    command: str
    register: str
    requires: tuple[str, ...]  # codenames that must be serving when the command runs


@dataclass(frozen=True)
class Service:
    codename: str
    role: str
    steps: tuple[Step, ...]  # in the hidden order they must be applied; the last one starts it
    idle: tuple[tuple[str, str], ...]  # (command, register) pairs that are already satisfied
    decoys: tuple[tuple[str, str], ...]  # (command, outcome) pairs that are never needed
    order_violation: str  # outcome when a step is applied before its turn
    dependency_violation: str  # outcome when a step runs before a service it requires
    has_sync: bool = False
    # Probability that a dry run of one of this service's steps reports the truth about
    # whether the step can be applied now. 1.0 means dry runs are exact.
    accuracy: float = 1.0

    @property
    def layer(self) -> int:
        return ROLE_LAYER[self.role]

    @property
    def commands(self) -> tuple[str, ...]:
        names = [step.command for step in self.steps]
        names += [command for command, _ in self.idle]
        names += [command for command, _ in self.decoys]
        if self.has_sync:
            names.append(SYNC_COMMAND)
        return tuple(sorted(names))


@dataclass(frozen=True)
class System:
    seed: int
    level: int
    services: tuple[Service, ...]  # sorted by codename
    initial_lag: int
    lag_service: str  # the database that reports replication lag and accepts `sync`

    def service(self, codename: str) -> Service | None:
        for service in self.services:
            if service.codename == codename:
                return service
        return None

    def tier_members(self, tier: int) -> tuple[Service, ...]:
        limit = TIER_MAX_LAYER[tier]
        return tuple(service for service in self.services if service.layer <= limit)
