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
  foreign            touched a command no pending register asked for
  redundant_dry_run  dry-ran the same command again with nothing changed since
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


def analyze(result: dict) -> dict:
    log = result["log"]
    findings: list[dict] = []
    spent = Counter()
    known: dict[tuple[str, str], str] = {}  # (service, kind) -> outcome seen for that mistake
    previewed: set[tuple[str, str]] = set()  # dry-run since the last state change
    last_preview: dict[tuple[str, str], str] = {}
    inspected: set[str] = set()
    lag_service = next((entry["service"] for entry in log if entry["command"] == "sync"), None)

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
            if last_preview.get(pair) == outcome and pair in previewed:
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
            last_preview[pair] = outcome

        if tool == "run":
            if outcome in DESTRUCTIVE and pair not in previewed and code != "E_FOREIGN":
                category = "blind_data_loss" if outcome == "data_loss" else "blind_crash"
                cost = COSTS["restart"] if outcome == "crash" else 0
                note(category, step, entry, f"{outcome} ({code}) without a dry run", cost)
            if outcome == "ok" or outcome in DESTRUCTIVE:
                previewed.clear()
                last_preview.clear()

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
            if finding["category"] in ("blind_data_loss", "blind_crash", "foreign"):
                print(
                    f"  step {finding['step']}: {finding['category']} "
                    f"{finding['service']} {finding['command']}: {finding['detail']}"
                )


if __name__ == "__main__":
    main()
