"""Copy Harbor run logs from jobs/ (ignored by git) into runs/ (committed).

    poetry run python scripts/keep_run.py jobs/<job-name> [jobs/<job-name> ...]

Kept per trial: Harbor's own result, config and log, the agent's trajectory and
console output, and the verifier's output with the signed episode. Left out: the
agent's local database and snapshots, which are large and add nothing to the log.
Absolute paths of the machine the run was made on are replaced, so the logs carry
no user name, and so are the account identifiers a failed API call writes into the
agent's output.
"""

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

KEEP = (
    "job.log",
    "result.json",
    "config.json",
    "*/result.json",
    "*/config.json",
    "*/trial.log",
    "*/agent/trajectory.json",
    "*/agent/opencode.txt",
    "*/agent/oracle.txt",
    "*/verifier/test-stdout.txt",
    "*/verifier/episode.json",
    "*/verifier/reward.txt",
)


def replacements() -> list[tuple[str, str]]:
    """Longest first: the checkout, then anything else under the home directory."""
    home = str(Path.home())
    checkouts = {str(ROOT), str(ROOT.resolve())}
    for parent in ROOT.parents:  # a worktree lives inside the main checkout
        if (parent / ".git").is_dir():
            checkouts.add(str(parent))
    pairs = [(path, "<repo>") for path in sorted(checkouts, key=len, reverse=True)]
    pairs.append((home, "<home>"))
    pairs.append((Path.home().name, "<user>"))
    return pairs


# A failed API call is logged with the provider's whole response: the organisation
# id of the account and its session cookies. Neither belongs in a kept log.
ACCOUNT = (
    (re.compile(r"\borg-[A-Za-z0-9]{8,}"), "<organisation>"),
    (re.compile(r'(\\?"set-cookie\\?":\s*\\?")[^"]*', re.IGNORECASE), r"\1<removed>"),
    (re.compile(r"\b(__cf_bm|_cfuvid)=[^;\"\\ ]+"), r"\1=<removed>"),
)


def keep(job: Path) -> Path:
    if not (job / "result.json").is_file():
        raise SystemExit(f"{job}: not a Harbor job directory (no result.json).")
    target = RUNS / job.name
    if target.exists():
        shutil.rmtree(target)
    swaps = replacements()
    for pattern in KEEP:
        for source in sorted(job.glob(pattern)):
            text = source.read_text(encoding="utf-8", errors="replace")
            for old, new in swaps:
                text = text.replace(old, new)
            for pattern_, replacement in ACCOUNT:
                text = pattern_.sub(replacement, text)
            destination = target / source.relative_to(job)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
    return target


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for argument in sys.argv[1:]:
        print(keep(Path(argument).resolve()).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
