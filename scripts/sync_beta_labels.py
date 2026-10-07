#!/usr/bin/env python3
"""Create or update the private-beta triage labels on GitHub (RC1-4.1, #3620).

The label set lives in ``.github/beta-labels.json``; this script makes the repository match it.
It is idempotent: ``gh label create --force`` creates a missing label and overwrites the colour
and description of an existing one, so running it twice changes nothing the second time. It
never deletes a label.

Usage::

    python3 scripts/sync_beta_labels.py --dry-run        # print the gh commands, run nothing
    python3 scripts/sync_beta_labels.py                  # apply to the current gh repo
    python3 scripts/sync_beta_labels.py --repo apiome/apiome

Requires the GitHub CLI (``gh``), authenticated with permission to manage labels. See
``docs/runbooks/BETA_TRIAGE.md`` for what each label means.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

#: Repository root — this file lives in ``<root>/scripts``.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Default location of the declarative label set.
LABELS_FILE = REPO_ROOT / ".github" / "beta-labels.json"

#: GitHub label colours are six hex digits with no leading ``#``.
_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")

#: GitHub rejects label descriptions longer than this.
MAX_DESCRIPTION = 100


def load_labels(path: Path = LABELS_FILE) -> list[dict]:
    """Read and validate the label set.

    Args:
        path: The JSON file to read; defaults to ``.github/beta-labels.json``.

    Returns:
        The ``labels`` list, each entry a dict with at least ``name``, ``color`` and
        ``description`` (``wf:*`` entries also carry ``workflow``).

    Raises:
        ValueError: If the file has no ``labels`` list, a label is missing a field, a colour is
            not six hex digits, a description is over GitHub's limit, or a name repeats. The
            message names the offending label, so a bad edit fails before any ``gh`` call.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"{path}: expected a non-empty 'labels' list")

    seen: set[str] = set()
    for label in labels:
        name = label.get("name")
        for field in ("name", "color", "description"):
            if not isinstance(label.get(field), str) or not label[field]:
                raise ValueError(f"{path}: label {name!r} is missing '{field}'")
        if not _COLOR.match(label["color"]):
            raise ValueError(f"{path}: label {name!r} has colour {label['color']!r}; want 6 hex digits")
        if len(label["description"]) > MAX_DESCRIPTION:
            raise ValueError(f"{path}: label {name!r} description exceeds {MAX_DESCRIPTION} characters")
        if name.lower() in seen:
            raise ValueError(f"{path}: label {name!r} is declared twice")
        seen.add(name.lower())
    return labels


def build_commands(labels: Sequence[dict], repo: str | None = None) -> list[list[str]]:
    """Turn the label set into ``gh label create --force`` argument lists.

    Args:
        labels: Validated labels, as returned by :func:`load_labels`.
        repo: ``OWNER/REPO`` to target; ``None`` lets ``gh`` use the current checkout's repo.

    Returns:
        One argv list per label, in file order, ready for :func:`subprocess.run`.
    """
    commands = []
    for label in labels:
        cmd = [
            "gh", "label", "create", label["name"],
            "--color", label["color"],
            "--description", label["description"],
            "--force",
        ]
        if repo:
            cmd += ["--repo", repo]
        commands.append(cmd)
    return commands


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when every label was applied (or printed, with ``--dry-run``); ``1`` if the label
        file is invalid or any ``gh`` call failed. A failing label does not stop the rest.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", help="OWNER/REPO to target (default: the current gh repo)")
    parser.add_argument("--dry-run", action="store_true", help="print the gh commands without running them")
    parser.add_argument("--labels-file", type=Path, default=LABELS_FILE, help="label set to apply")
    args = parser.parse_args(argv)

    try:
        labels = load_labels(args.labels_file)
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    failures = 0
    for cmd in build_commands(labels, args.repo):
        print(shlex.join(cmd))
        if args.dry_run:
            continue
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            failures += 1
            print(f"  failed: {result.stderr.strip()}", file=sys.stderr)

    if failures:
        print(f"{failures} of {len(labels)} labels failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
