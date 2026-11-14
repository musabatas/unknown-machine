"""Static description of one system. Immutable; all episode state lives in Episode."""

from dataclasses import dataclass

from unknown_machine.machine.themes import LEGACY, ROLE_LAYER, THEMES, Theme

OK = "ok"
REFUSED = "refused"
CRASH = "crash"
DATA_LOSS = "data_loss"

# ROLE_LAYER (owned by themes) gives the layer of every role. A tier is banked when
# every service up to a given layer is serving.
TIER_MAX_LAYER = {1: 1, 2: 2, 3: 4, 4: 5}
LAST_LAYER = max(TIER_MAX_LAYER.values())

# Budget cost of each tool, in maintenance-window minutes.
COST_RUN = 1
COST_INSPECT = 2
COST_DRY_RUN = 4
COST_RESTART = 4

# The legacy theme's names, for callers that only deal with that theme.
SYNC_COMMAND = THEMES[LEGACY].sync_command
LAG_REGISTER = THEMES[LEGACY].lag_register


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
    sync_command: str = SYNC_COMMAND  # what `has_sync` adds to the commands, in its theme
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
            names.append(self.sync_command)
        return tuple(sorted(names))


@dataclass(frozen=True)
class System:
    seed: int
    level: int
    services: tuple[Service, ...]  # sorted by codename
    initial_lag: int
    lag_service: str  # the layer 2 service that reports the lag and accepts the sync command
    theme: str = LEGACY

    @property
    def vocabulary(self) -> Theme:
        return THEMES[self.theme]

    def service(self, codename: str) -> Service | None:
        for service in self.services:
            if service.codename == codename:
                return service
        return None

    def tier_members(self, tier: int) -> tuple[Service, ...]:
        limit = TIER_MAX_LAYER[tier]
        return tuple(service for service in self.services if service.layer <= limit)
