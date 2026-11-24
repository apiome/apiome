"""The apiome-mcp statements in ``apiome-db/plan-check/hot-queries.json`` — DBP-1.22 (#7205).

``apiome-db plan-check`` runs ``EXPLAIN (ANALYZE, BUFFERS)`` on a list of hot statements against
the scale database (nightly and on database pull requests) and fails on a sequential scan of a
large table or a blown time budget. The catalog tools build their SQL in Python, so the entries
are generated here from the same builders the tools call, and
``tests/test_plan_check_queries.py`` fails when the file and the builders disagree.

Regenerate after changing one of those statements (from ``apiome-mcp/``)::

    uv run python tests/plan_check_queries.py --write
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from apiome_mcp import project_list_tool, spec_list_tags_tool, spec_list_tool, spec_openapi_loaders, spec_search_tool
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope

HOT_QUERIES = Path(__file__).resolve().parents[2] / "apiome-db" / "plan-check" / "hot-queries.json"

#: Entries this module owns: every name starts with one of these.
OWNED_PREFIXES = ("mcp.spec_", "mcp.project_list", "mcp.openapi_")

REGENERATE = "uv run python tests/plan_check_queries.py --write   (from apiome-mcp/)"

# Stand-ins for seeded ids while a statement is built; written to the file as plan-check tokens.
_TOKENS = {
    UUID("00000000-0000-4000-8000-0000000000a1"): "scale:tenant:7",
    UUID("00000000-0000-4000-8000-0000000000b1"): "scale:project:0",
    UUID("00000000-0000-4000-8000-0000000000c2"): "scale:version:1",
}
_TENANT, _PROJECT, _VERSION = _TOKENS


def to_dollar(sql: str, params: Any) -> tuple[str, list[Any]]:
    """Rewrite a psycopg statement to ``$n`` placeholders with a positional parameter list.

    Args:
        sql: SQL with ``%s`` or ``%(name)s`` placeholders (not both).
        params: The sequence or mapping the statement is executed with.

    Returns:
        ``(sql, params)``: whitespace collapsed, placeholders numbered in order of first use (a
        named placeholder used twice keeps one number), ids replaced by their plan-check tokens.
    """
    values: list[Any] = []
    if isinstance(params, dict):
        numbers: dict[str, int] = {}

        def named(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in numbers:
                values.append(params[name])
                numbers[name] = len(values)
            return f"${numbers[name]}"

        sql = re.sub(r"%\((\w+)\)s", named, sql)
    else:
        pending = list(params or [])

        def positional(_match: re.Match[str]) -> str:
            values.append(pending.pop(0))
            return f"${len(values)}"

        sql = re.sub(r"%s", positional, sql)
        assert not pending, "more parameters than placeholders"
    sql = re.sub(r"\s+", " ", sql.replace("%%", "%")).strip()
    return sql, [_plain(v) for v in values]


def _plain(value: Any) -> Any:
    """A parameter as plan-check reads it: a seeded-id token, or a JSON scalar / list."""
    if isinstance(value, UUID):
        return _TOKENS[value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _entry(name: str, source: str, sql: str, params: Any, **extra: Any) -> dict[str, Any]:
    dollar_sql, dollar_params = to_dollar(sql, params)
    return {"name": name, "source": source, "sql": dollar_sql, "params": dollar_params, **extra}


def mcp_plan_check_entries() -> list[dict[str, Any]]:
    """The entries, in file order, built from the statements the tools run."""
    src = "apiome-mcp/src/apiome_mcp/"
    key = McpAuthContext(key_id="plan-check", tenant_id=str(_TENANT), label="plan-check", scope=Scope())
    entries: list[dict[str, Any]] = []

    def spec_list(name: str, what: str, **kwargs: Any) -> None:
        sql, params = spec_list_tool.build_spec_list_query(
            **{"auth_ctx": None, "tenant": None, "project": None, "cursor": None, "limit": 51, **kwargs}
        )
        entries.append(
            _entry(name, f"{src}spec_list_tool.py build_spec_list_query ({what}; DBP-1.22 #7205)", sql, params)
        )

    spec_list("mcp.spec_list_page", "spec.list, anonymous, one page of 50 on idx_versions_mcp_public_listed")
    spec_list(
        "mcp.spec_list_project",
        "spec.list with a project_id filter, on idx_versions_mcp_project_listed",
        project=_PROJECT,
    )
    spec_list(
        "mcp.spec_list_authenticated",
        "spec.list for an API key: the public page merged with the key tenant's private revisions",
        auth_ctx=key,
    )

    for name, what, auth in (
        ("mcp.project_list_page", "project.list, anonymous, one page of the rollup", None),
        ("mcp.project_list_authenticated", "project.list for an API key: other tenants merged with its own", key),
    ):
        sql, params = project_list_tool.build_project_list_query(
            auth_ctx=auth, tenant=None, project=None, cursor=None, limit=51
        )
        entries.append(
            _entry(name, f"{src}project_list_tool.py build_project_list_query ({what}; DBP-1.22 #7205)", sql, params)
        )

    entries.append(
        _entry(
            "mcp.spec_search_page",
            f"{src}spec_search_tool.py build_spec_search_query (spec.search: rank and page on versions, "
            "then join the page; about 5,000 matches; DBP-1.22 #7205)",
            spec_search_tool.build_spec_search_query(has_cursor=False),
            {"q": "revision 7", "lim": 51},
        )
    )
    entries.append(
        _entry(
            "mcp.spec_list_tags_histogram",
            f"{src}spec_list_tags_tool.py _HISTOGRAM_QUERY (spec.list_tags: every public tag counted once per "
            "cache lifetime, 45 s by default, then paged from memory; DBP-1.22 #7205)",
            spec_list_tags_tool._HISTOGRAM_QUERY,
            [],
            budgetMs=500,
            allowSeqScan=[
                {
                    "relation": "apiome.version_tags",
                    "reason": "the histogram counts every tag of every public revision; it runs once "
                    "per cache lifetime, not per call",
                },
                {
                    "relation": "apiome.versions",
                    "reason": "joined to every tag row: reading the public revisions once is the cheapest plan",
                },
            ],
        )
    )

    loader = f"{src}spec_openapi_loaders.py"
    for name, what, sql, version, extra in (
        (
            "mcp.openapi_class_properties",
            "load_classes_and_properties, statement 2 of 2: every property of a revision's classes, "
            "keyed by the revision instead of an IN list of class ids",
            "CLASS_PROPERTIES_SQL",
            _VERSION,
            {},
        ),
        ("mcp.openapi_operations", "load_paths_tree: every operation of a revision", "_OPERATIONS_SQL", _VERSION, {}),
        (
            "mcp.openapi_parameters",
            "load_paths_tree: every operation's parameters",
            "_PARAMETERS_SQL",
            _VERSION,
            {},
        ),
        (
            "mcp.openapi_request_bodies",
            "load_paths_tree: every operation's request body with its content types",
            "_REQUEST_BODIES_SQL",
            _VERSION,
            {},
        ),
        (
            "mcp.openapi_responses",
            "load_paths_tree: every operation's responses with their content types",
            "_RESPONSES_SQL",
            _VERSION,
            {},
        ),
    ):
        entries.append(
            _entry(name, f"{loader} {what} (DBP-1.22 #7205)", getattr(spec_openapi_loaders, sql), [version], **extra)
        )
    return entries


def owned(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The entries of ``queries`` this module generates."""
    return [q for q in queries if str(q.get("name", "")).startswith(OWNED_PREFIXES)]


def write() -> None:
    """Replace this module's entries in ``hot-queries.json`` (appended after the other ``mcp.`` ones)."""
    spec = json.loads(HOT_QUERIES.read_text())
    kept = [q for q in spec["queries"] if q not in owned(spec["queries"])]
    last_mcp = max((i for i, q in enumerate(kept) if str(q["name"]).startswith("mcp.")), default=len(kept) - 1)
    spec["queries"] = kept[: last_mcp + 1] + mcp_plan_check_entries() + kept[last_mcp + 1 :]
    HOT_QUERIES.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit(f"usage: {REGENERATE}")
    write()
