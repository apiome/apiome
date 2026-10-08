#!/usr/bin/env python3
"""
Generate the MCP reference pages of the documentation site (DOCS-1.11, #5628).

Writes:
  - apiome-docs/docs/reference/mcp/{_category_.json,index.mdx,tools.md,resources.md,prompts.md}

The pages are derived from the catalog server's registry (``apiome_mcp.server.mcp``), so adding or
re-describing a tool is all it takes to document it. A test (`tests/test_mcp_reference_docs.py`)
renders the pages in memory and compares them against the committed copies, so CI fails when they
drift. Any other file left in the folder is removed (or, with ``--check``, reported).

Run from apiome-mcp:
    uv run python scripts/generate_mcp_reference_docs.py

Exits non-zero when `--check` is passed and a committed page is stale, missing or extra, so the same
script can be used as a CI or pre-commit gate. Needs no database and no environment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from apiome_mcp.reference_doc import (  # noqa: E402
    MCP_REFERENCE_DOCS_DIR,
    REGENERATE_COMMAND,
    load_registry,
    render_pages,
)

MONOREPO = project_root.parent


def main() -> int:
    """Write (or check) the generated pages.

    Returns:
        ``0`` on success; ``1`` when ``--check`` found a stale, missing or extra file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed pages differ from a fresh generation.",
    )
    args = parser.parse_args()

    folder = MONOREPO / MCP_REFERENCE_DOCS_DIR
    pages = render_pages(load_registry())
    existing = {path.name for path in folder.iterdir() if path.is_file()} if folder.is_dir() else set()

    if args.check:
        problems = [
            f"{MCP_REFERENCE_DOCS_DIR}/{name} is {'out of date' if name in existing else 'missing'}"
            for name, content in pages.items()
            if name not in existing or (folder / name).read_text(encoding="utf-8") != content
        ]
        problems += [
            f"{MCP_REFERENCE_DOCS_DIR}/{name} is not generated (remove it)" for name in sorted(existing - set(pages))
        ]
        if problems:
            print("\n".join(problems) + f"\nRegenerate with: {REGENERATE_COMMAND}", file=sys.stderr)
            return 1
        print(f"{MCP_REFERENCE_DOCS_DIR} is up to date.")
        return 0

    folder.mkdir(parents=True, exist_ok=True)
    for name in sorted(existing - set(pages)):
        (folder / name).unlink()
        print(f"Removed {folder / name}")
    for name, content in pages.items():
        (folder / name).write_text(content, encoding="utf-8")
        print(f"Wrote {folder / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
