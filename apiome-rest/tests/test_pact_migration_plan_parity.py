"""The server's migration plan module is the CLI's — PFX-8.16 (#7313).

The Migration wizard and ``apiome pact migrate`` must read a source broker the same way, so
``app/pact_migration_plan.py`` is a copy of ``apiome_cli/pact_migration_plan.py`` (the two packages
share no code). This test fails when one is changed without the other.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REST = Path(__file__).resolve().parents[1] / "src" / "app" / "pact_migration_plan.py"
_CLI = Path(__file__).resolve().parents[2] / "apiome-cli" / "src" / "apiome_cli" / "pact_migration_plan.py"


def _code(path: Path) -> str:
    """The module's syntax tree without its docstring, as text (formatting and comments do not count)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    first = tree.body[0]
    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
        tree.body = tree.body[1:]
    return ast.dump(tree)


def test_the_server_copy_matches_the_cli_module() -> None:
    """Both files hold the same code; only the module docstring differs."""
    if not _CLI.exists():
        pytest.skip("apiome-cli is not checked out beside apiome-rest (a packaged image)")
    assert _code(_REST) == _code(_CLI), (
        "app/pact_migration_plan.py and apiome_cli/pact_migration_plan.py differ: change both together"
    )
