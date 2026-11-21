"""Only :mod:`app.revision_source` reads the legacy source columns — COA-5.4 (#7080).

A captured source used to be read straight from ``versions.format_metadata.sourceContent`` or
``version_import_snapshots.source_text`` by whichever module needed it. Every reader now goes
through :func:`app.revision_source.revision_source`, which tries the document store first. This
test keeps it that way: it fails when a module under ``src/app`` names either column in code.

What counts as naming a column: a string in the code (not a docstring or a comment) that

* contains ``sourceContent``; or
* is exactly ``source_text`` (a row key); or
* is SQL that mentions ``source_text``.

A Python parameter or attribute called ``source_text`` is not a column read and is not counted.

The modules in :data:`WRITERS` still name the columns because they write them. Each is listed
with the number of strings it has today, so a new read added to one of them fails this test too.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path
from typing import Dict, List, Set

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"

#: The one module that may read the columns.
HELPER = "revision_source.py"

#: Modules that write the legacy columns, with how many strings name them and why.
WRITERS: Dict[str, int] = {
    # Builds the source fields an import writes, withholds them, and drops them once the
    # original is in the store (scrub_intake_source, _store_intake_original, persist_adapter_import).
    "import_source_pipeline.py": 6,
    # INSERT INTO version_import_snapshots (record_import_snapshot).
    "database.py": 1,
    # The one-off repair job (E1-6) that copies a legacy source between revisions and writes it
    # back to the legacy column. Moving existing sources into the store is COA-5.8 (#7084).
    "source_backfill.py": 4,
    # The migration job (COA-5.8, #7084) that copies both columns into the document store and,
    # in its purge step, drops them once the stored copy verifies.
    "document_migration.py": 8,
}

_SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b")
_SNAPSHOT_COLUMN = re.compile(r"\bsource_text\b")


def _docstrings(tree: ast.AST) -> Set[int]:
    """Return the ids of the string nodes that are docstrings."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def _names_a_source_column(text: str) -> bool:
    """Say whether a code string names one of the two legacy source columns."""
    if "sourceContent" in text or text == "source_text":
        return True
    return bool(_SQL.search(text) and _SNAPSHOT_COLUMN.search(text))


def column_strings(source: str) -> List[int]:
    """Return the line of every code string in ``source`` that names a legacy source column.

    Args:
        source: Python source text.

    Returns:
        Line numbers, one per string (an f-string counts once per literal piece).
    """
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _names_a_source_column(node.value)
    ]


@functools.lru_cache(maxsize=1)
def _found() -> Dict[str, List[int]]:
    """Scan every module under ``src/app`` once and return the ones that name a column."""
    found: Dict[str, List[int]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        lines = column_strings(path.read_text(encoding="utf-8"))
        if lines:
            found[path.relative_to(APP_DIR).as_posix()] = lines
    return found


def test_no_module_outside_the_helper_reads_the_source_columns():
    offenders = {name: lines for name, lines in _found().items() if name != HELPER and name not in WRITERS}
    assert not offenders, (
        "These modules name sourceContent / source_text in code. Read a revision's source with "
        f"app.revision_source.revision_source (or source_from_row) instead: {offenders}"
    )


@pytest.mark.parametrize("name,expected", sorted(WRITERS.items()))
def test_a_writer_names_the_columns_only_where_it_writes_them(name, expected):
    lines = _found().get(name, [])
    assert len(lines) == expected, (
        f"{name} names the source columns in {len(lines)} strings (lines {lines}); {expected} are "
        "its known writes. A new read belongs in app.revision_source; a new write updates WRITERS."
    )


def test_the_helper_is_where_the_columns_are_read():
    assert _found().get(HELPER), "app.revision_source no longer names the columns it is meant to read"


class TestTheScanItself:
    """The scan catches reads and leaves parameters, comments and docstrings alone."""

    def test_a_metadata_key_read_is_caught(self):
        assert column_strings('def f(fmd):\n    return fmd.get("sourceContent")\n') == [2]

    def test_a_json_path_in_sql_is_caught(self):
        assert column_strings("Q = \"SELECT v.format_metadata ->> 'sourceContent' FROM v\"\n") == [1]

    def test_a_snapshot_row_key_is_caught(self):
        assert column_strings('def f(row):\n    return row["source_text"]\n') == [2]

    def test_the_snapshot_column_in_sql_is_caught(self):
        assert column_strings('Q = "SELECT s.source_text FROM apiome.version_import_snapshots s"\n') == [1]

    def test_an_f_string_is_caught(self):
        assert column_strings("def f(a):\n    return f\"SELECT {a}.format_metadata ->> 'sourceContent'\"\n") == [2]

    def test_a_parameter_named_source_text_is_not_a_read(self):
        assert column_strings("def f(source_text):\n    return source.source_text or source_text\n") == []

    def test_docstrings_comments_and_prose_are_not_reads(self):
        source = (
            '"""Mentions sourceContent and source_text."""\n'
            "def f():\n"
            '    """Reads no source_text."""\n'
            "    # sourceContent is gone\n"
            '    return "Serialization of source_text."\n'
        )
        assert column_strings(source) == []
