#!/usr/bin/env python3
"""
Export the ``apiome pact`` command list for the CLI ↔ UI parity gate (PFX-8.2, #7299).

Writes ``apiome-cli/pact-commands.json`` from the CLI's own command tree (see
``apiome_cli.pact_command_list``). ``tests/test_pact_command_list.py`` compares the committed file
with a fresh render, and ``apiome-ui/tests/pact-parity-ledger.test.ts`` checks every command in it
against ``docs/pact-parity-ledger.json``.

Run from apiome-cli:
    uv run python scripts/export_pact_commands.py          # write
    uv run python scripts/export_pact_commands.py --check  # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apiome_cli.pact_command_list import (
    PACT_COMMANDS_FILE,
    REGENERATE_COMMAND,
    render_pact_commands,
)

MONOREPO = Path(__file__).resolve().parents[2]


def main() -> int:
    """Write (or check) the command list.

    :returns: ``0`` on success; ``1`` when ``--check`` found the committed file out of date.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed file differs from a fresh render.",
    )
    args = parser.parse_args()

    target = MONOREPO / PACT_COMMANDS_FILE
    content = render_pact_commands()

    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != content:
            print(f"{PACT_COMMANDS_FILE} is out of date.", file=sys.stderr)
            print(f"Regenerate with: {REGENERATE_COMMAND}", file=sys.stderr)
            return 1
        print(f"{PACT_COMMANDS_FILE} is up to date.")
        return 0

    target.write_text(content, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
