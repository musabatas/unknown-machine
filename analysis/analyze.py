"""Turn an episode log into a list of decisions that cost score or window.

    poetry run python analysis/analyze.py jobs/<job>            every trial of a job
    poetry run python analysis/analyze.py path/to/episode.json  one episode

The log is the server-side record written by the verifier (verifier/episode.json):
every charged action with its outcome. Nothing here reads the agent's own account.

Categories, each tied to a decision the agent made:
  blind_data_loss    ran a command that destroyed data without dry-running it in that
                     state first; never justified, the dry run would have said so
  blind_crash        ran a command that crashed without dry-running it first; a fair
                     gamble when a crash was the worst case and unlikely (the reference
                     takes it), a mistake when the reaction was still unknown
  trusted_wrong_dry_run  ran a command that crashed or destroyed data after dry-running
                     it, on a service whose dry runs are not exact: too few readings
                     for what was at stake
  unchecked_risk     ran a command that went through, with no dry run on that service
                     since its last change, although a mistake was possible from what
                     the agent could know and this service answers that mistake by
                     destroying its data: the score was kept by luck. Needs the system
                     description in the result, so older episode files do not report it
  foreign            touched a command no pending register asked for
  redundant_dry_run  dry-ran the same command again with nothing changed since, on a
                     service whose dry runs are exact
  safe_dry_run       dry-ran on a service already known to only refuse that kind of mistake
  repeat_inspect     inspected a service again without needing its replication lag
"""

import json
import sys
from collections import Counter
from pathlib import Path

COSTS = {"run": 1, "inspect": 2, "dry_run": 4, "restart": 4}
DESTRUCTIVE = ("crash", "data_loss")
KINDS = ("E_ORDER", "E_DEP")
FINAL_COMMANDS = ("start", "cutover")
LAYER = {"storage": 1, "database": 2, "middleware": 3, "application": 4, "gateway": 5}


class _Risk:
    """Which mistakes were possible, from the agent's side, when it ran a command."""

    def __init__(self, system: dict) -> None:
        self.specs = {spec["codename"]: spec for spec in system["services"]}
        self.done = {name: 0 for name in self.specs}
        self.lost: set[str] = set()
        self.ruled_out: dict[str, set[str]] = {name: set() for name in self.specs}

    def serving(self, name: str) -> bool:
        return self.done[name] == len(self.specs[name]["steps"]) and name not in self.lost

    def fatal_mistakes(self, name: str, order_checked: bool, dependency_checked: bool) -> list[str]:
        """Kinds of mistake an unchecked run on this service could have been, that would
        have destroyed its data."""
        spec = self.specs[name]
        fatal = []
        # Every preparation command still pending could be the next one, unless a real
        # refusal has ruled it out; the final command is known to come last.
        open_order = len(spec["steps"]) - 1 - self.done[name] - len(self.ruled_out[name])
        if not order_checked and open_order > 1 and spec["order_violation"] == "data_loss":
            fatal.append("wrong order")
        below = (
            other
            for other in self.specs
            if other != name and LAYER[self.specs[other]["role"]] <= LAYER[spec["role"]]
        )
        if (
            not dependency_checked
            and spec["dependency_violation"] == "data_loss"
            and not all(map(self.serving, below))
        ):
            fatal.append("missing dependency")
        return fatal

    def record(self, entry: dict) -> None:
        name = entry["service"]
        if entry["outcome"] == "ok" and entry["command"] != "sync":
            self.done[name] += 1
            self.ruled_out[name].clear()
        elif entry["outcome"] == "data_loss":
            self.lost.add(name)
        elif entry["code"] == "E_ORDER":
            self.ruled_out[name].add(entry["command"])


def analyze(result: dict) -> dict:
    log = result["log"]
    findings: list[dict] = []
    spent = Counter()
    known: dict[tuple[str, str], str] = {}  # (service, kind) -> outcome seen for that mistake
    previewed: set[tuple[str, str]] = set()  # dry-run since the last state change
    last_preview: dict[tuple[str, str], str] = {}
    previews: Counter = Counter()  # dry runs per (service, command) since the last change
    accuracy: dict[str, float] = {}  # stated dry-run accuracy per service
    inspected: set[str] = set()
    lag_service = next((entry["service"] for entry in log if entry["command"] == "sync"), None)
    risk = _Risk(result["system"]) if "system" in result else None
    order_checked: set[str] = set()  # services dry-run since their own last step

    def note(category: str, step: int, entry: dict, detail: str, cost: int) -> None:
        findings.append(
            {
                "category": category,
                "step": step,
                "service": entry["service"],
                "command": entry["command"],
                "detail": detail,
                "window_cost": cost,
            }
        )

    for step, entry in enumerate(log):
        tool, service, command = entry["tool"], entry["service"], entry["command"]
        outcome, code = entry["outcome"], entry["code"]
        pair = (service, command)
        spent[tool] += COSTS[tool]

        if tool == "inspect":
            if service in inspected and service != lag_service:
                note("repeat_inspect", step, entry, "already inspected", COSTS["inspect"])
            inspected.add(service)
            continue

        if code == "E_FOREIGN":
            note("foreign", step, entry, f"{tool} of a command nothing asked for", COSTS[tool])

        if tool == "dry_run":
            exact = entry.get("accuracy", 1.0) == 1.0
            accuracy[service] = entry.get("accuracy", 1.0)
            if exact and last_preview.get(pair) == outcome and pair in previewed:
                note("redundant_dry_run", step, entry, "same answer as before", COSTS["dry_run"])
            elif all(known.get((service, kind)) == "refused" for kind in KINDS):
                note(
                    "safe_dry_run",
                    step,
                    entry,
                    "this service only refuses mistakes; a direct run costs 1",
                    COSTS["dry_run"],
                )
            previewed.add(pair)
            order_checked.add(service)
            previews[pair] += 1
            last_preview[pair] = outcome

        if tool == "run":
            cost = COSTS["restart"] if outcome == "crash" else 0
            if outcome in DESTRUCTIVE and code != "E_FOREIGN":
                if pair not in previewed:
                    category = "blind_data_loss" if outcome == "data_loss" else "blind_crash"
                    note(category, step, entry, f"{outcome} ({code}) without a dry run", cost)
                else:
                    note(
                        "trusted_wrong_dry_run",
                        step,
                        entry,
                        f"{outcome} ({code}) after {previews[pair]} dry run(s) on a service "
                        f"whose dry runs are right {accuracy.get(service, 1.0):.0%} of the time",
                        cost,
                    )
            if risk and outcome == "ok" and command != "sync":
                # A dry run speaks about the order until its service moves, and about
                # dependencies until the set of serving services does.
                fatal = risk.fatal_mistakes(
                    service,
                    order_checked=service in order_checked,
                    dependency_checked=any(name == service for name, _ in previewed),
                )
                if fatal:
                    note(
                        "unchecked_risk",
                        step,
                        entry,
                        f"no dry run, and a {' or '.join(fatal)} would have destroyed its data",
                        0,
                    )
            if risk:
                risk.record(entry)
            if outcome == "ok":
                order_checked.discard(service)
            if outcome == "ok" or outcome in DESTRUCTIVE:
                # What a dry run said stays valid until its own service moves, or until
                # the set of serving services does (a final command, a crash, a loss).
                everything = command in FINAL_COMMANDS or outcome in DESTRUCTIVE
                for record in (previewed, previews, last_preview):
                    for stale in [p for p in record if everything or p[0] == service]:
                        if isinstance(record, set):
                            record.discard(stale)
                        else:
                            del record[stale]

        if code in KINDS and outcome != "ok":
            known[(service, code)] = outcome

    by_category = Counter(finding["category"] for finding in findings)
    wasted = Counter()
    for finding in findings:
        wasted[finding["category"]] += finding["window_cost"]
    return {
        "score": result["score"],
        "tiers_banked": result["tiers_banked"],
        "data_lost": result["data_lost"],
        "window": f"{result['window_used']}/{result['window_total']}",
        "window_by_tool": dict(spent),
        "findings_by_category": dict(by_category),
        "window_lost_by_category": dict(wasted),
        "findings": findings,
    }


def episodes(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("**/verifier/episode.json"))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    paths = episodes(Path(sys.argv[1]))
    if not paths:
        raise SystemExit("no episode.json found")
    for path in paths:
        report = analyze(json.loads(path.read_text()))
        findings = report.pop("findings")
        print(f"\n== {path}")
        print(json.dumps(report, indent=2))
        for finding in findings:
            if finding["category"] in (
                "blind_data_loss",
                "blind_crash",
                "trusted_wrong_dry_run",
                "unchecked_risk",
                "foreign",
            ):
                print(
                    f"  step {finding['step']}: {finding['category']} "
                    f"{finding['service']} {finding['command']}: {finding['detail']}"
                )


if __name__ == "__main__":
    main()
