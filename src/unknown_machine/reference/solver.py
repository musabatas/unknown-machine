"""Reference solver and scripted baselines.

Standard library only and no imports from the simulator: this file is copied
verbatim into each task's `solution/` directory and driven over MCP there.
It uses nothing but the six tools the agent gets, through a `console` object
exposing status(), inspect(s), dry_run(s, c), run(s, c), restart(s), finish().

The reference relies only on facts stated in the task instruction:
  * the last command of every service is `start` (`cutover` for the gateway);
  * a service reacts to a given kind of mistake the same way every time, and a
    dry run always shows that reaction truthfully;
  * a dry run is right about whether a command can be applied now with the
    probability `inspect` reports, independently each time; `run` is always real;
  * tool costs: run 1, inspect 2, dry_run 4, restart 4.

Its rule: keep, for every service, the probability of each explanation of the
reports seen so far (which command is next, and whether its dependencies are up).
Run a command only when the chance of destroying data is below LOSS_TOLERANCE and
the chance of a crash is below CRASH_TOLERANCE; otherwise buy another dry run.
A service known to only refuse mistakes is driven by trial and error.
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
ACCURACY_FIELD = "dry_run_accuracy"

# Prior that a command's dependencies are up while some service of its layer or below is not.
DEPENDENCIES_UP_PRIOR = 0.75
LOSS_TOLERANCE = 0.002  # accepted chance of destroying data, per command run
CRASH_TOLERANCE = 0.3  # accepted chance of a crash loop, per command run
WAIT_CONFIDENCE = 0.6  # belief that a dependency is missing before moving on
BLOCKED_CONFIDENCE = 0.98  # the same belief, before giving a service up as blocked

REFERENCE = "reference"  # dry-run until the risk is acceptable, and only where it matters
CAUTIOUS = "cautious"  # one dry run before every command, believed as reported
GREEDY = "greedy"  # never dry-run


class _Service:
    def __init__(self, name: str, report: dict) -> None:
        self.name = name
        self.layer = ROLE_LAYER[report["role"]]
        self.accuracy = report.get(ACCURACY_FIELD, 1.0)
        self.pending = [item["cleared_by"] for item in report["pending"]]
        self.lag = report.get(LAG_REGISTER)
        self.order_class: str | None = None
        self.dependency_class: str | None = None
        self.not_next: set[str] = set()  # ruled out by a real refusal, so certain
        self.reports: list[tuple[str, str | None, frozenset]] = []  # (command, code, serving)
        self.waiting: frozenset | None = None  # serving set at which a dependency looked missing
        self.blocked: frozenset | None = None  # serving set at which it certainly was
        self.serving = not self.pending
        self.dead = False

    def candidates(self) -> list[str]:
        preparation = sorted(c for c in self.pending if c not in FINAL_COMMANDS)
        if preparation:
            return [c for c in preparation if c not in self.not_next]
        return [c for c in self.pending if c in FINAL_COMMANDS]


class Solver:
    def __init__(self, console, policy: str = REFERENCE, stop_after_tier: int | None = None):
        self.console = console
        self.policy = policy
        self.stop_after_tier = stop_after_tier
        self.remaining = 0
        self.services: dict[str, _Service] = {}
        self.lag_owner: str | None = None
        self.banked: list[int] = []
        self.patient = False

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
            service = self._next_service()
            if service is None:
                return
            if not self._advance(service):
                return

    def _next_service(self) -> _Service | None:
        """The lowest service that can make progress.

        A service believed to be waiting for a dependency is skipped while anything
        else can move. When nothing else can, that belief may just be a run of wrong
        reports, so it is tested again with a much higher bar (`self.patient`).
        """
        serving = self._serving_set()
        ordered = sorted(self.services.values(), key=lambda s: (s.layer, s.name))
        self.patient = False
        for service in ordered:
            if service.serving or service.dead or service.waiting == serving:
                continue
            if service.candidates():
                return service
        self.patient = True
        for service in ordered:
            if service.serving or service.dead or service.blocked == serving:
                continue
            if service.candidates():
                return service
        return None

    def _advance(self, service: _Service) -> bool:
        """One tool call on this service. False when the window cannot pay for it."""
        command, belief = self._belief(service)
        confidence = BLOCKED_CONFIDENCE if self.patient else WAIT_CONFIDENCE
        if belief["dependency"] >= confidence:
            service.waiting = self._serving_set()
            if self.patient:
                service.blocked = service.waiting
            return True
        if command == CUTOVER_COMMAND and self._lag_pending():
            return self._sync()

        if self._acceptable(service, belief):
            if not self._afford(COST_RUN):
                return False
            result = self._call(self.console.run(service.name, command))
            self._after_run(service, command, result["outcome"], result["code"])
            return True

        if not self._afford(COST_DRY_RUN):
            return False
        preview = self._call(self.console.dry_run(service.name, command))
        self._after_dry_run(service, command, preview["would"], preview["code"])
        return True

    # ---- the decision under test -------------------------------------------

    def _acceptable(self, service: _Service, belief: dict) -> bool:
        """Is running the most likely next command now worth the risk?"""
        if self.policy == GREEDY:
            return True
        if self.policy == CAUTIOUS:
            return belief["confirmed"]

        loss = crash = 0.0
        for chance, reaction in (
            (belief["order"], service.order_class),
            (belief["dependency"], service.dependency_class),
        ):
            if reaction is None or reaction == DATA_LOSS:
                loss += chance  # an unknown reaction is treated as the worst one
            elif reaction == CRASH:
                crash += chance
        return loss <= LOSS_TOLERANCE and crash <= CRASH_TOLERANCE

    def _belief(self, service: _Service) -> tuple[str, dict]:
        """Most likely next command, and the chance that running it fails each way.

        Explanations of the reports: command n is next (uniform prior over the
        candidates) and its dependencies are up or not. A report on any other
        command should say E_ORDER; a report on n should say ok or E_DEP. Each
        report is right with the service's accuracy, otherwise one of the other
        two answers with equal chance.
        """
        candidates = service.candidates()
        serving = self._serving_set()
        right = service.accuracy
        wrong = (1 - right) / 2
        up_prior = self._dependencies_up_prior(service)

        weights: dict[str, tuple[float, float]] = {}  # command -> (deps up, deps missing)
        for candidate in candidates:
            others = up = missing = 1.0
            for command, code, seen_at in service.reports:
                if command not in candidates:
                    continue
                if command != candidate:
                    others *= right if code == E_ORDER else wrong
                elif seen_at == serving:
                    up *= right if code is None else wrong
                    missing *= right if code == E_DEP else wrong
                else:
                    # Dependencies may have come up since; only "not its turn" still counts.
                    factor = wrong if code == E_ORDER else 1.0
                    up *= factor
                    missing *= factor
            weights[candidate] = (others * up * up_prior, others * missing * (1 - up_prior))

        total = sum(up + missing for up, missing in weights.values())
        if total == 0.0:  # contradictory exact reports cannot happen; fall back to the prior
            weights = {c: (up_prior, 1 - up_prior) for c in candidates}
            total = float(len(candidates))
        best = max(candidates, key=lambda c: sum(weights[c]))
        up, missing = weights[best]
        confirmed = any(
            command == best and code is None and seen_at == serving
            for command, code, seen_at in service.reports
        )
        return best, {
            "order": 1 - (up + missing) / total,
            "dependency": missing / total,
            "confirmed": confirmed,
        }

    def _dependencies_up_prior(self, service: _Service) -> float:
        others_up = all(
            other.serving
            for other in self.services.values()
            if other is not service and other.layer <= service.layer
        )
        return 1.0 if others_up else DEPENDENCIES_UP_PRIOR

    # ---- bookkeeping --------------------------------------------------------

    def _after_dry_run(self, service: _Service, command: str, outcome: str, code) -> None:
        if code == E_ORDER:
            service.order_class = outcome  # the reaction shown is always the real one
        elif code == E_DEP:
            service.dependency_class = outcome
        elif code == E_LAG:
            self._refresh_lag()
            return
        elif code is not None:
            service.dead = True  # not a step of the recovery after all
            return
        service.reports.append((command, code, self._serving_set()))
        if self.policy == CAUTIOUS and code == E_ORDER:
            service.not_next.add(command)  # believes a single report
        if self.policy == CAUTIOUS and code == E_DEP:
            service.waiting = self._serving_set()

    def _after_run(self, service: _Service, command: str, outcome: str, code) -> None:
        if outcome == OK:
            service.pending.remove(command)
            service.not_next.clear()
            service.reports.clear()
            service.waiting = None
            service.serving = not service.pending
            return
        if code == E_ORDER:
            service.order_class = outcome
            service.not_next.add(command)
            if not service.candidates():  # a single believed report ruled out the real one
                service.not_next = {command}
        elif code == E_DEP:
            service.dependency_class = outcome
            service.waiting = service.blocked = self._serving_set()  # a real run is certain
        elif code == E_LAG:
            self._refresh_lag()

        if outcome == CRASH:
            if self.lag_owner:
                self.services[self.lag_owner].lag += 1
            if self._afford(COST_RESTART):
                self._call(self.console.restart(service.name))
            else:
                service.dead = True
        elif outcome == DATA_LOSS or code not in (E_ORDER, E_DEP, E_LAG):
            service.dead = True

    def _lag_pending(self) -> bool:
        owner = self.services[self.lag_owner] if self.lag_owner else None
        return bool(owner and owner.serving and owner.lag)

    def _sync(self) -> bool:
        """One `sync` towards zero replication lag. False if the window ran out."""
        owner = self.services[self.lag_owner]
        if not self._afford(COST_RUN):
            return False
        result = self._call(self.console.run(owner.name, SYNC_COMMAND))
        if result["outcome"] == OK:
            owner.lag -= 1
            return True
        self._refresh_lag()
        return result["outcome"] != CRASH

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
