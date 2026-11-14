"""Reference solver and scripted baselines.

Standard library only and no imports from the simulator: this file is copied
verbatim into each task's `solution/` directory and driven over MCP there.
It uses nothing but the six tools the agent gets, through a `console` object
exposing status(), inspect(s), dry_run(s, c), run(s, c), restart(s), finish().

The reference relies on three facts stated in the task instruction:
  * the last command of every service is `start` (`cutover` for the gateway);
  * a service reacts to a given kind of mistake the same way every time;
  * tool costs: run 1, inspect 2, dry_run 4, restart 4.
"""

OK = "ok"
REFUSED = "refused"
CRASH = "crash"
DATA_LOSS = "data_loss"

E_ORDER = "E_ORDER"
E_DEP = "E_DEP"
E_LAG = "E_LAG"

COST_RUN = 1
COST_INSPECT = 2
COST_DRY_RUN = 4
COST_RESTART = 4

ROLE_LAYER = {"storage": 1, "database": 2, "middleware": 3, "application": 4, "gateway": 5}
CUTOVER_COMMAND = "cutover"
FINAL_COMMANDS = ("start", CUTOVER_COMMAND)
SYNC_COMMAND = "sync"
LAG_REGISTER = "replication_lag"

# Prior that a command with unknown requirements hits a service that is not up yet.
DEPENDENCY_FAILURE_PRIOR = 0.25

REFERENCE = "reference"  # dry-run only where a mistake would cost more than the dry run
CAUTIOUS = "cautious"  # dry-run before every command
GREEDY = "greedy"  # never dry-run


class _Service:
    def __init__(self, name: str, report: dict) -> None:
        self.name = name
        self.layer = ROLE_LAYER[report["role"]]
        self.pending = [item["cleared_by"] for item in report["pending"]]
        self.lag = report.get(LAG_REGISTER)
        self.order_class: str | None = None
        self.dependency_class: str | None = None
        self.not_next: set[str] = set()
        self.blocked: dict[str, frozenset] = {}
        self.serving = not self.pending
        self.dead = False


class Solver:
    def __init__(self, console, policy: str = REFERENCE, stop_after_tier: int | None = None):
        self.console = console
        self.policy = policy
        self.stop_after_tier = stop_after_tier
        self.remaining = 0
        self.services: dict[str, _Service] = {}
        self.lag_owner: str | None = None
        self.banked: list[int] = []

    # ---- entry point --------------------------------------------------------

    def solve(self) -> None:
        status = self.console.status()
        self.remaining = status["window_remaining"]
        self.banked = status["tiers_banked"]
        for name in sorted(status["services"]):
            if not self._afford(COST_INSPECT):
                break
            report = self._call(self.console.inspect(name))
            self.services[name] = _Service(name, report)
            if LAG_REGISTER in report:
                self.lag_owner = name
        if len(self.services) == len(status["services"]):
            self._recover()
        self.console.finish()

    # ---- main loop ----------------------------------------------------------

    def _recover(self) -> None:
        while True:
            if self.stop_after_tier is not None and self.stop_after_tier in self.banked:
                return
            choice = self._next_action()
            if choice is None:
                return
            service, command = choice
            if command == CUTOVER_COMMAND and not self._clear_lag():
                return
            if not self._attempt(service, command):
                return

    def _next_action(self) -> tuple[_Service, str] | None:
        serving = self._serving_set()
        for service in sorted(self.services.values(), key=lambda s: (s.layer, s.name)):
            if service.serving or service.dead:
                continue
            for command in self._candidates(service):
                if service.blocked.get(command) == serving:
                    continue
                return service, command
        return None

    def _candidates(self, service: _Service) -> list[str]:
        preparation = sorted(c for c in service.pending if c not in FINAL_COMMANDS)
        if preparation:
            return [c for c in preparation if c not in service.not_next]
        return [c for c in service.pending if c in FINAL_COMMANDS]

    def _attempt(self, service: _Service, command: str) -> bool:
        """Apply one command, dry-running first when the policy calls for it."""
        if self._should_dry_run(service, command):
            if not self._afford(COST_DRY_RUN):
                return False
            preview = self._call(self.console.dry_run(service.name, command))
            if preview["would"] != OK:
                self._learn(service, command, preview["would"], preview["code"], ran=False)
                return True
        if not self._afford(COST_RUN):
            return False
        result = self._call(self.console.run(service.name, command))
        self._learn(service, command, result["outcome"], result["code"], ran=True)
        return True

    # ---- the decision under test -------------------------------------------

    def _should_dry_run(self, service: _Service, command: str) -> bool:
        if self.policy == CAUTIOUS:
            return True
        if self.policy == GREEDY:
            return False

        candidates = self._candidates(service)
        order_risk = 1 - 1 / len(candidates) if len(candidates) > 1 else 0.0
        peers_up = all(
            other.serving
            for other in self.services.values()
            if other is not service and other.layer <= service.layer
        )
        dependency_risk = 0.0 if peers_up else DEPENDENCY_FAILURE_PRIOR

        crash_risk = 0.0
        for risk, outcome in (
            (order_risk, service.order_class),
            (dependency_risk, service.dependency_class),
        ):
            if risk == 0.0:
                continue
            if outcome is None or outcome == DATA_LOSS:
                return True  # unknown or unrecoverable: never gamble
            if outcome == CRASH:
                crash_risk = 1 - (1 - crash_risk) * (1 - risk)
        if crash_risk == 0.0:
            return False  # the worst case is a refusal, which costs the same as a success

        failure = 1 - (1 - order_risk) * (1 - dependency_risk)
        dry_first = COST_DRY_RUN + (1 - failure) * COST_RUN
        direct = COST_RUN + crash_risk * COST_RESTART
        return dry_first < direct

    # ---- bookkeeping --------------------------------------------------------

    def _learn(self, service: _Service, command: str, outcome: str, code, ran: bool) -> None:
        if outcome == OK:
            service.pending.remove(command)
            service.not_next.clear()
            service.blocked.clear()
            service.serving = not service.pending
            return
        if code == E_ORDER:
            service.order_class = outcome
            service.not_next.add(command)
        elif code == E_DEP:
            service.dependency_class = outcome
            service.blocked[command] = self._serving_set()
        elif code == E_LAG:
            self._refresh_lag()
        if not ran:
            return
        if outcome == CRASH:
            self._count_crash()
            if self._afford(COST_RESTART):
                self._call(self.console.restart(service.name))
            else:
                service.dead = True
        elif outcome == DATA_LOSS:
            service.dead = True
        elif code not in (E_ORDER, E_DEP, E_LAG):
            service.dead = True  # an unexpected refusal: stop working on this service

    def _clear_lag(self) -> bool:
        """Bring replication lag to zero before the cutover. False if the window ran out."""
        owner = self.services[self.lag_owner] if self.lag_owner else None
        if owner is None or not owner.serving:
            return True
        while owner.lag:
            if not self._afford(COST_RUN):
                return False
            result = self._call(self.console.run(owner.name, SYNC_COMMAND))
            if result["outcome"] != OK:
                self._refresh_lag()
                if result["outcome"] == CRASH:
                    return False
                continue
            owner.lag -= 1
        return True

    def _count_crash(self) -> None:
        if self.lag_owner:
            self.services[self.lag_owner].lag += 1

    def _refresh_lag(self) -> None:
        if self.lag_owner and self._afford(COST_INSPECT):
            report = self._call(self.console.inspect(self.lag_owner))
            self.services[self.lag_owner].lag = report.get(LAG_REGISTER, 0)

    def _serving_set(self) -> frozenset:
        return frozenset(name for name, service in self.services.items() if service.serving)

    def _afford(self, cost: int) -> bool:
        return self.remaining >= cost

    def _call(self, response: dict) -> dict:
        self.remaining = response.get("window_remaining", self.remaining)
        self.banked = response.get("tiers_banked", self.banked)
        return response


def solve(console, policy: str = REFERENCE, stop_after_tier: int | None = None) -> None:
    Solver(console, policy=policy, stop_after_tier=stop_after_tier).solve()
