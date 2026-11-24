"""DBP-1.22 (#7205): statement budgets of the spec tools, and the document cache they share.

Acceptance criteria, as tests:

* each spec tool runs a constant number of statements for any spec size — the same statements at
  10 and at 1,000 operations, and never more than the budget in :data:`BUDGETS`;
* a second call for an unchanged revision runs none for the document (only the resolve statement,
  which authorizes the caller);
* a changed revision (new ``content_stamp`` or ``updated_at``) is rebuilt.

The pool answers the real SQL from an in-memory spec (:class:`spec_fakes.FakeSpecDb`) and records
every statement. ``tests/test_spec_openapi_loaders_db.py`` runs the same budgets on a database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastmcp.exceptions import NotFoundError

from agent_invocation_fakes import RecordingPool
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_describe_component_tool import build_spec_describe_component_response
from apiome_mcp.spec_describe_operation_tool import build_spec_describe_operation_response
from apiome_mcp.spec_document_cache import DOCUMENT_CACHE
from apiome_mcp.spec_export_yaml_tool import build_spec_export_yaml_response
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response
from apiome_mcp.spec_list_components_tool import build_spec_list_components_response
from apiome_mcp.spec_list_operations_tool import build_spec_list_operations_response
from spec_fakes import DOCUMENT_STATEMENTS, FakeSpecDb

Call = Callable[[Any, str], Awaitable[Any]]

#: tool → (how to call it, the statement kinds a cold call runs after the resolve statement).
TOOLS: dict[str, tuple[Call, tuple[str, ...]]] = {
    "spec.get_openapi": (lambda pool, sid: build_spec_get_openapi_response(pool, spec_id=sid), DOCUMENT_STATEMENTS),
    "spec.export_yaml": (lambda pool, sid: build_spec_export_yaml_response(pool, spec_id=sid), DOCUMENT_STATEMENTS),
    "spec.describe_operation": (
        lambda pool, sid: build_spec_describe_operation_response(
            pool, spec_id=sid, path="/resources00000/{id}", method="get"
        ),
        DOCUMENT_STATEMENTS,
    ),
    "spec.describe_component": (
        lambda pool, sid: build_spec_describe_component_response(pool, spec_id=sid, kind="schemas", name="Model00000"),
        DOCUMENT_STATEMENTS,
    ),
    "spec.list_operations": (
        lambda pool, sid: build_spec_list_operations_response(pool, spec_id=sid),
        ("paths", "operations", "descriptions"),
    ),
    "spec.list_components": (
        lambda pool, sid: build_spec_list_components_response(pool, spec_id=sid),
        ("classes", "properties", "security", "pins"),
    ),
}

#: The most statements a cold call may run, the resolve statement included.
BUDGETS = {name: 1 + len(kinds) for name, (_, kinds) in TOOLS.items()}


def _run(tool: str, db: FakeSpecDb, pool: RecordingPool) -> Any:
    with (
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
        patch("apiome_mcp.spec_export_yaml_tool.get_settings") as ys,
    ):
        gs.return_value.openapi_max_json_bytes = ys.return_value.openapi_max_json_bytes = 100_000_000
        return asyncio.run(TOOLS[tool][0](pool, str(db.spec_id)))


def test_budgets_are_what_the_loader_documents() -> None:
    assert BUDGETS == {
        "spec.get_openapi": 12,
        "spec.export_yaml": 12,
        "spec.describe_operation": 12,
        "spec.describe_component": 12,
        "spec.list_operations": 4,
        "spec.list_components": 5,
    }


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_cold_call_runs_the_same_statements_at_10_and_1000_operations(tool: str) -> None:
    kinds_by_size = {}
    for operations in (10, 1000):
        DOCUMENT_CACHE.clear()
        db = FakeSpecDb(operations=operations)
        pool = RecordingPool(db)
        _run(tool, db, pool)
        kinds_by_size[operations] = tuple(db.kinds)
        assert len(pool.statements) <= BUDGETS[tool]
        # No statement text depends on the size of the spec (no per-class or per-operation lists).
        assert all(sql.count("%s") + sql.count("%(") <= 3 for sql, _ in pool.statements)
    assert kinds_by_size[10] == kinds_by_size[1000] == ("resolve", *TOOLS[tool][1])


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_second_call_for_an_unchanged_revision_runs_only_the_resolve_statement(tool: str) -> None:
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    first = _run(tool, db, pool)
    db.kinds.clear()
    second = _run(tool, db, pool)
    assert db.kinds == ["resolve"]
    assert second == first


@pytest.mark.parametrize("tool", ["spec.list_operations", "spec.list_components"])
def test_narrow_tools_reuse_a_cached_full_document(tool: str) -> None:
    """After ``spec.get_openapi``, the index tools derive from its document: no loader statement."""
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    cold = _run(tool, db, pool)
    DOCUMENT_CACHE.clear()
    _run("spec.get_openapi", db, pool)
    db.kinds.clear()
    assert _run(tool, db, pool) == cold  # the narrow load and the full document agree
    assert db.kinds == ["resolve"]


def test_narrow_results_match_the_full_document() -> None:
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    operations = _run("spec.list_operations", db, pool)
    components = _run("spec.list_components", db, pool)
    document = _run("spec.get_openapi", db, pool)
    assert [(o["path"], o["method"], o["operation_id"]) for o in operations] == [
        (path, method, item[method]["operationId"])
        for path, item in sorted(document["paths"].items())
        for method in sorted(m for m in item if m in ("get", "post"))
    ]
    assert len(operations) == 10
    assert components == {
        "schemas": sorted(document["components"]["schemas"]),
        "securitySchemes": ["ApiKeyHeader"],
    }


@pytest.mark.parametrize("change", ["content_stamp", "version_updated_at", "project_description"])
def test_a_changed_revision_is_rebuilt(change: str) -> None:
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    _run("spec.get_openapi", db, pool)
    if change == "content_stamp":
        db.row["content_stamp"] += 1
    elif change == "version_updated_at":
        db.row["version_updated_at"] += timedelta(seconds=1)
    else:
        db.row["project_description"] = "Renamed"
    db.kinds.clear()
    document = _run("spec.get_openapi", db, pool)
    assert tuple(db.kinds) == ("resolve", *DOCUMENT_STATEMENTS)
    if change == "project_description":
        assert document["info"]["description"] == "Renamed"


def test_cache_off_loads_every_time() -> None:
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    with patch("apiome_mcp.spec_document_cache.setting_or_default", return_value=0):
        _run("spec.get_openapi", db, pool)
        db.kinds.clear()
        _run("spec.get_openapi", db, pool)
    assert tuple(db.kinds) == ("resolve", *DOCUMENT_STATEMENTS)


def test_the_cache_is_read_only_after_the_caller_is_authorized() -> None:
    """A cached document does not answer for a revision the resolve statement refuses."""
    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    _run("spec.get_openapi", db, pool)

    refusing = RecordingPool(lambda sql, params: [])
    with pytest.raises(NotFoundError):
        asyncio.run(build_spec_get_openapi_response(refusing, spec_id=str(db.spec_id)))
    assert len(refusing.statements) == 1


def test_a_cached_private_document_is_still_audited() -> None:
    db = FakeSpecDb(operations=10, visibility="private")
    pool = RecordingPool(db)
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000042",
        tenant_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        label="k",
        scope=Scope(),
    )
    with (
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 100_000_000
        for _ in range(2):
            asyncio.run(build_spec_get_openapi_response(pool, spec_id=str(db.spec_id), auth_ctx=auth))
    assert audit.call_count == 2
    assert db.kinds.count("resolve") == 2 and db.kinds.count("classes") == 1


def test_the_payload_cap_applies_to_a_cached_document() -> None:
    from fastmcp.exceptions import ToolError

    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    _run("spec.get_openapi", db, pool)
    with patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs:
        gs.return_value.openapi_max_json_bytes = 1024
        with pytest.raises(ToolError, match="exceeds server limit"):
            asyncio.run(build_spec_get_openapi_response(pool, spec_id=str(db.spec_id)))


def test_describe_tools_do_not_mutate_the_shared_document() -> None:
    import copy

    db = FakeSpecDb(operations=10)
    pool = RecordingPool(db)
    document = _run("spec.get_openapi", db, pool)
    before = copy.deepcopy(document)
    detail = _run("spec.describe_operation", db, pool)
    component = _run("spec.describe_component", db, pool)
    detail["parameters"].append({"mutated": True})
    component["mutated"] = True
    assert _run("spec.get_openapi", db, pool) == before
