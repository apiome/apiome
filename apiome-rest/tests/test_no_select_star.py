"""No ``SELECT *`` outside :mod:`app.database` — DBP-1.13 (#7196).

A store used to read a table with ``SELECT *`` (or write it with ``RETURNING *``) and hand the row
on. Every column a later migration added — a JSONB document, a text blob, a vector — then
travelled with every read, whether or not anything looked at it. Each statement now names the
columns it returns, most of them through one module-level column list per table. This test keeps
it that way: it reads the code of every module under ``src/app`` except ``database.py`` and fails
when SQL in a string (not a docstring or a comment) has

* ``SELECT *`` or ``SELECT alias.*`` (``DISTINCT`` or not);
* ``, alias.*`` further along a select list; or
* ``RETURNING *`` or ``RETURNING alias.*``.

``count(*)`` is not a projection and is not matched.

The statements in :data:`ALLOWED` keep their star on purpose. Each is listed by module and by a
piece of the line the star is on, with the reason; an entry that no longer matches anything fails
the test too, so the list cannot outlive the code it excuses.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"

#: ``database.py`` is out of scope here; its own projections are narrowed statement by statement.
SKIPPED = {"database.py"}

#: The stars that stay: ``module -> {piece of the line: why}``.
ALLOWED: Dict[str, Dict[str, str]] = {
    "db_bulk.py": {
        # bulk_insert / bulk_upsert: INSERT INTO t (named columns) SELECT * FROM unnest(arrays).
        # unnest() of N typed arrays yields exactly the N columns the INSERT names, in order;
        # there is no table behind the star to grow a column.
        "SELECT * FROM unnest(": "the unnest() of the typed arrays an INSERT names the columns for",
    },
    "usage_ingest_store.py": {
        # The same shape with the tenant / project / source ids prepended as bound values:
        # INSERT INTO t (named columns) SELECT %s, %s, g.* FROM unnest(arrays) AS g.
        "%s::uuid, g.*": "the unnest() of the typed arrays an INSERT names the columns for",
    },
    "primitives_search_store.py": {
        # The search statement is a chain of CTEs. `visible` selects _PRIMITIVE_COLUMNS from the
        # table; each later step adds derived columns to the step before it and never reads the
        # table again, so the stars carry an explicit list forward.
        "SELECT p.*,": "classified: the `visible` CTE's explicit columns plus derived ones",
        "SELECT *, ({}) AS rank": "matched: the `classified` CTE's columns plus the rank",
        "SELECT *": "the page: every column of the `matched` CTE",
    },
}

_STAR = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?(?:\w+\.)?\*"  # SELECT * / SELECT alias.*
    r"|\bRETURNING\s+(?:\w+\.)?\*"  # RETURNING * / RETURNING alias.*
    r"|,\s*\w+\.\*(?!\*)",  # , alias.*   (not Markdown's ``, word.**``)
    re.IGNORECASE,
)
_SQL = re.compile(r"\b(SELECT|RETURNING)\b", re.IGNORECASE)


def _docstrings(tree: ast.AST) -> Set[int]:
    """Return the ids of the string nodes that are docstrings."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def _code_strings(source: str) -> List[Tuple[int, str]]:
    """Every string in code, as ``(line, text)``; an f-string is one string with ``{}`` holes."""
    tree = ast.parse(source)
    skipped = _docstrings(tree)
    strings: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            pieces = []
            for value in node.values:
                skipped.add(id(value))
                literal = isinstance(value, ast.Constant) and isinstance(value.value, str)
                pieces.append(value.value if literal else "{}")
            strings.append((node.lineno, "".join(pieces)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skipped:
            strings.append((node.lineno, node.value))
    return strings


def star_projections(source: str) -> List[str]:
    """Return the line of SQL each star projection in ``source`` is written on.

    Args:
        source: Python source text.

    Returns:
        One stripped line of SQL per star, in the order the strings appear in the module.
    """
    found: List[Tuple[int, str]] = []
    for lineno, text in _code_strings(source):
        if not _SQL.search(text):
            continue
        for match in _STAR.finditer(text):
            star = match.end() - 1
            start = text.rfind("\n", 0, star) + 1
            end = text.find("\n", star)
            line = text[start : len(text) if end < 0 else end].strip()
            found.append((lineno + text.count("\n", 0, star), line))
    return [line for _, line in sorted(found, key=lambda item: item[0])]


@functools.lru_cache(maxsize=1)
def _found() -> Dict[str, List[str]]:
    """Scan every module under ``src/app`` once and return the ones with a star projection."""
    found: Dict[str, List[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        name = path.relative_to(APP_DIR).as_posix()
        if name in SKIPPED:
            continue
        lines = star_projections(path.read_text(encoding="utf-8"))
        if lines:
            found[name] = lines
    return found


def _allowed(name: str, line: str) -> bool:
    return any(piece in line for piece in ALLOWED.get(name, {}))


def test_no_statement_projects_a_star():
    offenders = {
        name: [line for line in lines if not _allowed(name, line)] for name, lines in _found().items()
    }
    offenders = {name: lines for name, lines in offenders.items() if lines}
    assert not offenders, (
        "These statements project `*`. Name the columns the callers read (one module-level "
        "column list per table when a list is used twice); a star that is deliberate goes in "
        f"ALLOWED with its reason: {offenders}"
    )


def test_every_allowed_star_is_still_there():
    stale = [
        (name, piece)
        for name, pieces in ALLOWED.items()
        for piece in pieces
        if not any(piece in line for line in _found().get(name, []))
    ]
    assert not stale, f"ALLOWED lists stars that are gone; drop these entries: {stale}"


class TestTheScanItself:
    """The scan catches each form of star and leaves counts, prose and docstrings alone."""

    def test_select_star_is_caught(self):
        assert star_projections('Q = "SELECT * FROM apiome.projects"\n') == ["SELECT * FROM apiome.projects"]

    def test_select_alias_star_is_caught(self):
        assert star_projections('Q = "SELECT DISTINCT p.* FROM apiome.projects p"\n') == [
            "SELECT DISTINCT p.* FROM apiome.projects p"
        ]

    def test_a_star_later_in_the_select_list_is_caught(self):
        assert star_projections('Q = "SELECT p.id, v.* FROM p JOIN v ON TRUE"\n') == [
            "SELECT p.id, v.* FROM p JOIN v ON TRUE"
        ]

    def test_returning_star_is_caught(self):
        source = 'Q = """\n    UPDATE apiome.projects SET name = %s\n    RETURNING *\n"""\n'
        assert star_projections(source) == ["RETURNING *"]

    def test_a_star_on_the_line_after_select_is_caught(self):
        assert star_projections('Q = """\n    SELECT\n        *\n      FROM t\n"""\n') == ["*"]

    def test_an_f_string_is_caught(self):
        source = 'def f(cols):\n    return f"SELECT {cols}, p.* FROM apiome.projects p"\n'
        assert star_projections(source) == ["SELECT {}, p.* FROM apiome.projects p"]

    def test_lowercase_sql_is_caught(self):
        assert star_projections('Q = "select * from apiome.projects"\n') == ["select * from apiome.projects"]

    def test_counts_and_explicit_columns_are_not_stars(self):
        source = (
            'A = "SELECT count(*) FROM apiome.projects"\n'
            'B = "SELECT id, name, count(*) OVER () AS total FROM apiome.projects"\n'
            'C = "INSERT INTO t (a) VALUES (%s) RETURNING id, a"\n'
        )
        assert star_projections(source) == []

    def test_docstrings_comments_and_prose_are_not_stars(self):
        source = (
            '"""Reads with SELECT * FROM t."""\n'
            "def f():\n"
            '    """Was RETURNING * once."""\n'
            "    # SELECT t.* FROM t\n"
            '    return "**Select the run, unchanged.** Then go on."\n'
        )
        assert star_projections(source) == []
