#!/usr/bin/env python3
"""
Generate the CLI reference pages of the documentation site (DOCS-1.11, #5628).

Writes apiome-docs/docs/reference/cli/ — an index, one page per top-level command, and the exit
codes — from the CLI's own command tree (see ``apiome_cli.reference_doc``). Files in that folder
that the generator no longer produces are removed. A test
(``tests/test_cli_reference_docs.py``) renders the pages in memory and compares them with the
committed copies, so CI fails when they drift.

Run from apiome-cli:
    uv run python scripts/generate_cli_reference_docs.py          # write
    uv run python scripts/generate_cli_reference_docs.py --check  # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apiome_cli.reference_doc import (
    CLI_REFERENCE_DIR,
    REGENERATE_COMMAND,
    render_cli_reference,
)

MONOREPO = Path(__file__).resolve().parents[2]


def compare(target: Path, pages: dict[str, str]) -> list[str]:
    """List how the folder differs from the rendered pages.

    :param target: The reference folder.
    :param pages: File name → expected content.
    :returns: One line per stale, missing or extra file; empty when up to date.
    """
    problems: list[str] = []
    for name, content in pages.items():
        path = target / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"stale:   {name}")
    if target.is_dir():
        for path in sorted(target.iterdir()):
            if path.is_file() and path.name not in pages:
                problems.append(f"extra:   {path.name}")
    return problems


def main() -> int:
    """Write (or check) the CLI reference.

    :returns: ``0`` on success; ``1`` when ``--check`` found the committed pages out of date.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed pages differ from a fresh render.",
    )
    args = parser.parse_args()

    target = MONOREPO / CLI_REFERENCE_DIR
    pages = render_cli_reference()

    if args.check:
        problems = compare(target, pages)
        if problems:
            print(f"{CLI_REFERENCE_DIR} is out of date:", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            print(f"Regenerate with: {REGENERATE_COMMAND}", file=sys.stderr)
            return 1
        print(f"{CLI_REFERENCE_DIR} is up to date ({len(pages)} files).")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    for path in target.iterdir():
        if path.is_file() and path.name not in pages:
            path.unlink()
    for name, content in pages.items():
        (target / name).write_text(content, encoding="utf-8")
    print(f"Wrote {len(pages)} files to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
