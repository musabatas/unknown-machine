"""One episode: all mutable state of a system being recovered, behind a single lock.

No I/O. The MCP server and the tests both drive this class directly.
"""

import threading

from unknown_machine.machine.model import (
    COST_DRY_RUN,
    COST_INSPECT,
    COST_RESTART,
    COST_RUN,
    CRASH,
    DATA_LOSS,
    LAG_REGISTER,
    OK,
    REFUSED,
    SYNC_COMMAND,
    TIER_MAX_LAYER,
    Service,
    System,
)
from unknown_machine.machine.score import score

# Error codes. Their meaning is documented to the agent in the task instruction.
E_UNKNOWN = "E_UNKNOWN"  # no such service or command
E_FINISHED = "E_FINISHED"  # the episode is over
E_WINDOW = "E_WINDOW"  # not enough maintenance window left for this tool
E_LOST = "E_LOST"  # the service has lost its data
E_CRASHED = "E_CRASHED"  # the service is in a crash loop; restart it first
E_DONE = "E_DONE"  # nothing to do: this is already applied
E_ORDER = "E_ORDER"  # another command of this service has to be applied first
E_DEP = "E_DEP"  # a service this command depends on is not serving
E_LAG = "E_LAG"  # replication lag is not zero
E_FOREIGN = "E_FOREIGN"  # the command is not part of this service's recovery
E_HEALTHY = "E_HEALTHY"  # restart: the service is not in a crash loop

_NO_COMMAND = object()  # marks a tool that takes no command, as opposed to a bad one


class Episode:
    def __init__(self, system: System, budget: int) -> None:
        self._system = system
        self._budget = budget
        self._lock = threading.Lock()
        self._used = 0
        self._progress = {service.codename: 0 for service in system.services}
        self._crashed: set[str] = set()
        self._lost: set[str] = set()
        self._lag = system.initial_lag
        self._banked: set[int] = set()
        self._finished = False
        self._calls = 0
        self._log: list[dict] = []  # every charged action, for the failure analysis

    # ---- tools -------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            return self._status()

    def inspect(self, service: str) -> dict:
        with self._lock:
            refusal = self._precheck(service, COST_INSPECT)
            if refusal:
                return refusal
            spec = self._system.service(service)
            self._spend(COST_INSPECT)
            done = self._progress[service]
            pending = [
                {"register": step.register, "cleared_by": step.command}
                for step in spec.steps[done:]
            ]
            healthy = [step.register for step in spec.steps[:done]]
            healthy += [register for _, register in spec.idle]
            report = {
                "service": service,
                "role": spec.role,
                "mode": self._mode(spec),
                "pending": sorted(pending, key=lambda item: item["register"]),
                "healthy": sorted(healthy),
            }
            if spec.has_sync:
                report[LAG_REGISTER] = self._lag
            self._record("inspect", service, None, OK, None)
            return self._close(report)

    def dry_run(self, service: str, command: str) -> dict:
        with self._lock:
            refusal = self._precheck(service, COST_DRY_RUN, command)
            if refusal:
                return refusal
            self._spend(COST_DRY_RUN)
            outcome, code, register = self._evaluate(self._system.service(service), command)
            self._record("dry_run", service, command, outcome, code)
            return self._close({"would": outcome, "code": code, "changes": register})

    def run(self, service: str, command: str) -> dict:
        with self._lock:
            refusal = self._precheck(service, COST_RUN, command)
            if refusal:
                return refusal
            spec = self._system.service(service)
            self._spend(COST_RUN)
            outcome, code, register = self._evaluate(spec, command)
            if outcome == OK:
                if command == SYNC_COMMAND:
                    self._lag -= 1
                else:
                    self._progress[service] += 1
            elif outcome == CRASH:
                self._crashed.add(service)
                self._lag += 1
            elif outcome == DATA_LOSS:
                self._lost.add(service)
            self._bank_tiers()
            self._record("run", service, command, outcome, code)
            return self._close(
                {
                    "outcome": outcome,
                    "code": code,
                    "changes": register if outcome == OK else None,
                    "mode": self._mode(spec),
                }
            )

    def restart(self, service: str) -> dict:
        with self._lock:
            refusal = self._precheck(service, COST_RESTART)
            if refusal:
                return refusal
            if service in self._lost:
                return self._close({"outcome": REFUSED, "code": E_LOST})
            if service not in self._crashed:
                return self._close({"outcome": REFUSED, "code": E_HEALTHY})
            self._spend(COST_RESTART)
            self._crashed.discard(service)
            self._bank_tiers()
            self._record("restart", service, None, OK, None)
            return self._close({"outcome": OK, "code": None, "mode": self._mode_of(service)})

    def finish(self) -> dict:
        with self._lock:
            self._finished = True
            return self._close({"finished": True})

    # ---- read by the verifier, never by the agent ---------------------------

    def result(self) -> dict:
        with self._lock:
            return {
                "score": score(self._banked, len(self._lost)),
                "tiers_banked": sorted(self._banked),
                "data_lost": sorted(self._lost),
                "window_used": self._used,
                "window_total": self._budget,
                "finished": self._finished,
                "calls": self._calls,
                "log": list(self._log),
            }

    # ---- internals (lock held) ---------------------------------------------

    def _precheck(self, service: object, cost: int, command: object = _NO_COMMAND) -> dict | None:
        """Refuse without charging when the call cannot be executed at all.

        Arguments come straight from the agent, so they may be of any type.
        """
        self._calls += 1
        if self._finished:
            return self._close({"outcome": REFUSED, "code": E_FINISHED})
        spec = self._system.service(service) if isinstance(service, str) else None
        if spec is None:
            return self._close({"outcome": REFUSED, "code": E_UNKNOWN})
        if command is not _NO_COMMAND and (
            not isinstance(command, str) or command not in spec.commands
        ):
            return self._close({"outcome": REFUSED, "code": E_UNKNOWN})
        if self._budget - self._used < cost:
            return self._close({"outcome": REFUSED, "code": E_WINDOW})
        return None

    def _record(self, tool: str, service: str, command: str | None, outcome: str, code) -> None:
        self._log.append(
            {
                "tool": tool,
                "service": service,
                "command": command,
                "outcome": outcome,
                "code": code,
                "window_used": self._used,
                "tiers_banked": sorted(self._banked),
            }
        )

    def _spend(self, cost: int) -> None:
        self._used += cost
        if self._used >= self._budget:
            self._finished = True

    def _close(self, payload: dict) -> dict:
        payload["tiers_banked"] = sorted(self._banked)
        payload["window_remaining"] = self._budget - self._used
        return payload

    def _serving(self, service: str) -> bool:
        spec = self._system.service(service)
        return (
            self._progress[service] == len(spec.steps)
            and service not in self._crashed
            and service not in self._lost
        )

    def _mode(self, spec: Service) -> str:
        name = spec.codename
        if name in self._lost:
            return "lost"
        if name in self._crashed:
            return "crashed"
        done = self._progress[name]
        if done == len(spec.steps):
            return "serving"
        return "partial" if done else "stopped"

    def _mode_of(self, service: str) -> str:
        return self._mode(self._system.service(service))

    def _evaluate(self, spec: Service, command: str) -> tuple[str, str | None, str | None]:
        """What `command` does in the current state: (outcome, code, register changed)."""
        name = spec.codename
        if name in self._lost:
            return REFUSED, E_LOST, None
        if name in self._crashed:
            return REFUSED, E_CRASHED, None

        if command == SYNC_COMMAND:
            if not self._serving(name):
                return REFUSED, E_ORDER, None
            if self._lag == 0:
                return REFUSED, E_DONE, None
            return OK, None, LAG_REGISTER

        for decoy, outcome in spec.decoys:
            if command == decoy:
                return outcome, E_FOREIGN, None
        for idle, _ in spec.idle:
            if command == idle:
                return REFUSED, E_DONE, None

        done = self._progress[name]
        index = next(i for i, step in enumerate(spec.steps) if step.command == command)
        if index < done:
            return REFUSED, E_DONE, None
        if index > done:
            return spec.order_violation, E_ORDER, None
        step = spec.steps[index]
        if any(not self._serving(required) for required in step.requires):
            return spec.dependency_violation, E_DEP, None
        if index == len(spec.steps) - 1 and spec.role == "gateway" and self._lag > 0:
            return DATA_LOSS, E_LAG, None
        return OK, None, step.register

    def _bank_tiers(self) -> None:
        for tier in TIER_MAX_LAYER:
            if tier in self._banked:
                continue
            members = self._system.tier_members(tier)
            if all(self._serving(member.codename) for member in members):
                self._banked.add(tier)

    def _status(self) -> dict:
        return {
            "services": {
                spec.codename: {"mode": self._mode(spec), "commands": list(spec.commands)}
                for spec in self._system.services
            },
            "tiers_banked": sorted(self._banked),
            "window_remaining": self._budget - self._used,
            "finished": self._finished,
        }
