"""Episode JSON -> one self-contained replay page that opens by double-click.

    poetry run python scripts/make_replay.py <episode.json> --out replay.html
    poetry run python scripts/make_replay.py jobs/<job-name> --out replays/

The page is `viewer/index.html` with the episode embedded as `window.EPISODE`. Given a
Harbor job directory, every `**/verifier/episode.json` under it gets its own page.
Standard library only.
"""

import argparse
import json
import sys
from pathlib import Path

VIEWER = Path(__file__).resolve().parent.parent / "viewer" / "index.html"
MARKER = "<!--EPISODE-->"


def load_episode(path: Path) -> dict:
    try:
        episode = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{path}: cannot read an episode: {error}") from error
    if not isinstance(episode, dict) or not isinstance(episode.get("log"), list):
        raise SystemExit(f"{path}: not an episode file (no 'log').")
    if not isinstance(episode.get("system"), dict):
        raise SystemExit(
            f"{path}: this episode has no 'system' field. It was recorded before the "
            "environment stored the hidden rules with the result, so it cannot be "
            "replayed. Record the episode again."
        )
    return episode


def embed(template: str, episode: dict, label: str) -> str:
    """The viewer page with the episode inlined where the marker is."""

    def literal(value: object) -> str:
        # "</" would end the script element early; "<!--" would open a comment in it.
        text = json.dumps(value, separators=(",", ":"))
        return text.replace("</", "<\\/").replace("<!--", "<\\!--")

    script = (
        f"<script>window.EPISODE = {literal(episode)};"
        f"window.EPISODE_LABEL = {literal(label)};</script>"
    )
    return template.replace(MARKER, script, 1)


def targets(source: Path, out: Path | None) -> list[tuple[Path, Path, str]]:
    """(episode file, page to write, label shown in the page) for everything asked for."""
    if source.is_file():
        return [(source, out or source.with_suffix(".replay.html"), source.stem)]
    if not source.is_dir():
        raise SystemExit(f"{source}: no such file or directory.")
    episodes = sorted(source.glob("**/verifier/episode.json"))
    if not episodes:
        raise SystemExit(f"{source}: no verifier/episode.json found under this directory.")
    folder = out or source / "replays"
    if folder.suffix == ".html":
        if len(episodes) > 1:
            raise SystemExit(
                f"{source} holds {len(episodes)} episodes; --out must be a directory, "
                "one page is written per episode."
            )
        trial = episodes[0].parent.parent.relative_to(source)
        return [(episodes[0], folder, "-".join((source.name, *trial.parts)))]
    found = []
    for episode in episodes:
        trial = episode.parent.parent.relative_to(source)
        name = "-".join((source.name, *trial.parts))
        found.append((episode, folder / f"{name}.html", name))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="an episode JSON, or a Harbor job directory")
    parser.add_argument(
        "--out",
        type=Path,
        help="page to write; a directory when the source is a job directory "
        "(default: next to the episode, or <job>/replays/)",
    )
    args = parser.parse_args()

    template = VIEWER.read_text(encoding="utf-8")
    if MARKER not in template:
        raise SystemExit(f"{VIEWER}: the {MARKER} marker is missing.")
    for episode_path, page, label in targets(args.source, args.out):
        html = embed(template, load_episode(episode_path), label)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(html, encoding="utf-8")
        print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
