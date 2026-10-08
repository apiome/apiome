#!/usr/bin/env python3
"""
Generate the REST API reference pages of the documentation site (DOCS-1.11, #5628).

Writes:
  - apiome-docs/docs/reference/rest/index.mdx (version, authentication, every tag)
  - apiome-docs/docs/reference/rest/<tag>.md (one page per tag, plus untagged.md)
  - apiome-docs/docs/reference/rest/_category_.json

The pages are rendered from apiome-rest/openapi.yaml by :mod:`app.rest_reference_doc`. A test
(`tests/test_rest_reference_docs.py`) regenerates them in memory and compares them with the
committed copies, and `yarn docs:check` compares the index's `openapi_sha256` with the document, so
a REST change that is not regenerated fails CI.

Run from apiome-rest:
    uv run python scripts/generate_rest_reference_docs.py

With `--check`, nothing is written: the script exits non-zero and lists every stale, missing or
extra file when the committed folder differs from a fresh generation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import yaml

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.rest_reference_doc import (  # noqa: E402
    OPENAPI_PATH,
    REGENERATE_COMMAND,
    REST_REFERENCE_DIR,
    render_rest_reference,
)

MONOREPO = project_root.parent


def render() -> Dict[str, str]:
    """Render every file of the folder from the committed OpenAPI document.

    Returns:
        File name → contents.
    """
    source = (MONOREPO / OPENAPI_PATH).read_bytes()
    return render_rest_reference(yaml.safe_load(source), source)


def differences(target: Path, rendered: Dict[str, str]) -> List[str]:
    """Compare the folder on disk with a fresh rendering.

    Args:
        target: The output folder.
        rendered: File name → expected contents.

    Returns:
        One line per stale, missing or extra file; empty when the folder is up to date.
    """
    problems: List[str] = []
    on_disk = {path.name for path in target.iterdir() if path.is_file()} if target.is_dir() else set()
    for name, text in rendered.items():
        path = target / name
        if name not in on_disk:
            problems.append(f"missing: {name}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"stale: {name}")
    for name in sorted(on_disk - set(rendered)):
        problems.append(f"extra: {name}")
    return problems


def main() -> int:
    """Write (or check) the generated pages.

    Returns:
        ``0`` on success; ``1`` when ``--check`` found the committed folder out of date.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed pages differ from a fresh generation.",
    )
    args = parser.parse_args()

    target = MONOREPO / REST_REFERENCE_DIR
    rendered = render()

    if args.check:
        problems = differences(target, rendered)
        if problems:
            print(f"{REST_REFERENCE_DIR} is out of date:", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            print(f"Regenerate with: {REGENERATE_COMMAND}", file=sys.stderr)
            return 1
        print(f"{REST_REFERENCE_DIR} is up to date ({len(rendered)} files).")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    for path in target.iterdir():
        if path.is_file() and path.name not in rendered:
            path.unlink()
    for name, text in rendered.items():
        (target / name).write_text(text, encoding="utf-8")
    print(f"Wrote {len(rendered)} files to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
