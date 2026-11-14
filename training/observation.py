"""The harness between a policy that reads text and the six tools.

A small model cannot hold a whole episode in context, so it never sees the
transcript. Each turn it gets one compact observation, built here from the tool
results seen so far, and answers with one action line. The harness turns that
line into a tool call and folds the result into the next observation.

Everything in an observation comes from a tool result or from a fact the task
instruction states (the layer of a role, the last command of a service, a crash
adds 1 to the lag). The harness holds a console, never an Episode's internals.

`status` is not an action: it is free, so the harness calls it after every step
and the observation is its content plus what the charged tools have shown.

Level 1 and the legacy theme only: one report per (tool, command) is kept, which
is all an exact dry run has to say. Inexact dry runs would need the whole list.
"""

from dataclasses import dataclass, field

from unknown_machine.machine.episode import E_DEP, E_ORDER, E_UNKNOWN
from unknown_machine.machine.model import CRASH, LAG_REGISTER, OK, REFUSED, SYNC_COMMAND

INSPECT = "inspect"
DRY_RUN = "dry_run"
RUN = "run"
RESTART = "restart"
FINISH = "finish"
ARGUMENTS = {INSPECT: 1, DRY_RUN: 2, RUN: 2, RESTART: 1, FINISH: 0}

UNKNOWN = "?"

SHORT_PROMPT = "Legacy system recovery. Answer with the next action: one line, nothing else."

RULES_PROMPT = f"""\
You are bringing a legacy production system back online inside a maintenance window. \
Each turn you see the state of the system and answer with the next action: one line, nothing else.

{INSPECT} <service>            cost 2: shows the role, the pending commands and the lag
{DRY_RUN} <service> <command>  cost 4: exact forecast of what run would do now; changes nothing
{RUN} <service> <command>      cost 1: executes the command for real
{RESTART} <service>            cost 4: clears a crash loop
{FINISH}                       cost 0: ends the window

Rules:
- Roles, lowest layer first: storage, database, middleware, application, gateway.
- A service is serving once all its pending commands are applied in the right order. The order \
is hidden, except that `start` (`cutover` for the gateway) is last. Some commands also need \
other services to be serving first. Commands that are not pending are never needed.
- A command applied before its turn gives {E_ORDER}; before a service it depends on, {E_DEP}. \
The service reacts with `refused` (nothing changes), `crash` (it needs a restart, and the lag \
grows by 1) or `data_loss` (the service is gone for good). A service reacts to each of the two \
kinds of mistake the same way every time: `order` and `dep` show the reaction once it has been \
seen, `{UNKNOWN}` until then.
- One database shows `lag`. `{RUN} <that database> {SYNC_COMMAND}` lowers it by 1 once that \
database is serving. `cutover` with a lag above 0 destroys the gateway.
- `notes` list what dry runs and failed runs showed since the service last advanced. `stale` \
means the set of serving services has changed since.
- Score: storage serving, then databases, then middleware and applications, then the gateway. \
Every service that loses its data costs points. The window is too short to dry-run everything.
Finish when everything is serving or nothing more can be done safely."""


@dataclass(frozen=True)
class Action:
    tool: str
    service: str | None = None
    command: str | None = None


def format_action(action: Action) -> str:
    return " ".join(part for part in (action.tool, action.service, action.command) if part)


def parse_action(text: str) -> Action | None:
    """The first line of `text` as an action, or None when it is not one.

    Only the shape is checked here. A well-formed action on a service or command
    that does not exist reaches the tools and is refused there.
    """
    lines = text.strip().splitlines()
    words = lines[0].split() if lines else []
    if not words or ARGUMENTS.get(words[0]) != len(words) - 1:
        return None
    return Action(*words)


def messages(observation: str, rules: bool) -> list[dict]:
    """The prompt of one turn.

    The model that was not trained is told the rules. The training data and the
    fine-tuned model get the short prompt: the rules are what training has to teach,
    and they are two thirds of the tokens of a turn, so of the training time.
    """
    return [
        {"role": "system", "content": RULES_PROMPT if rules else SHORT_PROMPT},
        {"role": "user", "content": observation},
    ]


@dataclass
class _Known:
    """What the tools have shown about one service."""

    mode: str
    role: str | None = None
    pending: list[str] | None = None  # None until inspected
    order: str = UNKNOWN  # reaction to a command applied before its turn
    dependency: str = UNKNOWN  # reaction to a command run before a service it needs
    lag: int | None = None
    # (tool, command) -> (what it showed, serving set at that moment); cleared on progress
    notes: dict[tuple[str, str], tuple[str, frozenset]] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    action: Action | None  # None when the text was not an action
    result: dict | None  # the tool's own response
    valid: bool  # False for unparsable text and for names that do not exist


class Harness:
    def __init__(self, console) -> None:
        self._console = console
        self._services: dict[str, _Known] = {}
        self._last = "none"
        self.steps = 0
        self.invalid = 0  # text that is not an action, or names that do not exist
        self.unparsable = 0  # the first kind only
        self.status: dict = {}
        self._refresh()

    @property
    def finished(self) -> bool:
        return self.status["finished"]

    def observation(self) -> str:
        serving = self._serving()
        lines = [f"window: {self.status['window_remaining']}"]
        for name, known in self._services.items():
            if known.pending is None:
                lines.append(f"{name} | not inspected | {known.mode}")
                continue
            parts = [name, known.role, known.mode]
            if known.pending:
                parts.append("pending: " + " ".join(known.pending))
                parts.append(f"order: {known.order}")
                parts.append(f"dep: {known.dependency}")
            if known.lag is not None:
                parts.append(f"lag: {known.lag}")
            notes = [
                f"{tool} {command} {shown}"
                + (" stale" if shown != E_ORDER and seen_at != serving else "")
                for (tool, command), (shown, seen_at) in known.notes.items()
            ]
            if notes:
                parts.append("notes: " + ", ".join(notes))
            lines.append(" | ".join(parts))
        lines.append(f"last: {self._last}")
        return "\n".join(lines)

    def step(self, text: str) -> Step:
        """Play one action line. Text that is not an action costs a step and nothing else."""
        self.steps += 1
        action = parse_action(text)
        if action is None:
            self.invalid += 1
            self.unparsable += 1
            self._last = "invalid action"
            return Step(None, None, False)
        arguments = [part for part in (action.service, action.command) if part]
        result = getattr(self._console, action.tool)(*arguments)
        valid = result.get("code") != E_UNKNOWN
        if not valid:
            self.invalid += 1
        elif action.tool != FINISH:
            self._learn(action, result)
        self._last = f"{format_action(action)} -> {_summary(action, result)}"
        self._refresh()
        return Step(action, result, valid)

    # ---- internals ----------------------------------------------------------

    def _refresh(self) -> None:
        self.status = self._console.status()
        for name in sorted(self.status["services"]):
            mode = self.status["services"][name]["mode"]
            if name in self._services:
                self._services[name].mode = mode
            else:
                self._services[name] = _Known(mode)

    def _serving(self) -> frozenset:
        return frozenset(name for name, known in self._services.items() if known.mode == "serving")

    def _learn(self, action: Action, result: dict) -> None:
        known = self._services[action.service]
        code = result.get("code")
        if action.tool == INSPECT:
            if "pending" in result:
                known.role = result["role"]
                known.pending = sorted(item["cleared_by"] for item in result["pending"])
                known.lag = result.get(LAG_REGISTER)
            return
        shown = "would" if action.tool == DRY_RUN else "mode"
        if action.tool == RESTART or shown not in result:
            return  # refused before it was looked at: no window left, or the episode is over

        outcome = result["would"] if action.tool == DRY_RUN else result["outcome"]
        if code == E_ORDER:
            known.order = outcome
        elif code == E_DEP:
            known.dependency = outcome
        if action.tool == RUN and outcome == OK:
            if known.pending and action.command in known.pending:
                known.pending.remove(action.command)
                known.notes.clear()
            elif action.command == SYNC_COMMAND and known.lag:
                known.lag -= 1
            return
        if action.tool == RUN and outcome == CRASH:
            for other in self._services.values():
                if other.lag is not None:
                    other.lag += 1  # stated in the instruction: every crash adds 1
        known.notes[(action.tool, action.command)] = (code or OK, self._serving())


def _summary(action: Action, result: dict) -> str:
    if action.tool == FINISH:
        return "finished"
    outcome = result.get("would") or result.get("outcome") or OK
    code = result.get("code")
    if outcome == REFUSED or code:
        return f"{outcome} {code}"
    return outcome
