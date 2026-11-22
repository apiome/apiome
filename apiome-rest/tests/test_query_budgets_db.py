"""Statement budgets for the hot REST endpoints, against Postgres — DBP-1.1 (#7184).

Each guarded endpoint is called through the real app (``TestClient``) with a real JWT, so its
count includes authentication and permission checks, and must stay within the budget recorded in
``tests/query_budgets.json``. The DBP tickets that cut statements lower the budget in the same PR;
a change that adds statements fails here with the list of statements it ran.

Refresh the recorded counts (after a deliberate change)::

    DATABASE_URL=… UPDATE_QUERY_BUDGETS=1 uv run pytest tests/test_query_budgets_db.py

Skips when no database with V403 is reachable. Runs nightly on the scale database in
``.github/workflows/apiome-db-scale.yml``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterator

import jwt
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import execute_values

from app import database as database_module
from app.config import settings
from app.statement_stats import CountingDictCursor, QueryBudgetExceededError, assert_max_queries, capture
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_rendered_documents_db import _seed_order

pytestmark = pytest.mark.requires_db

BUDGETS_FILE = Path(__file__).with_name("query_budgets.json")


def _load_budgets() -> Dict[str, int]:
    return {k: int(v) for k, v in json.loads(BUDGETS_FILE.read_text())["budgets"].items()}


_MEASURED: Dict[str, int] = {}


@pytest.fixture(scope="module", autouse=True)
def _write_measured_budgets() -> Iterator[None]:
    """With ``UPDATE_QUERY_BUDGETS=1``, write the counts this run measured back to the file."""
    yield
    if os.environ.get("UPDATE_QUERY_BUDGETS") == "1" and _MEASURED:
        payload = json.loads(BUDGETS_FILE.read_text())
        payload["budgets"].update(_MEASURED)
        payload["budgets"] = dict(sorted(payload["budgets"].items()))
        BUDGETS_FILE.write_text(json.dumps(payload, indent=2) + "\n")


@pytest.fixture
def ctx(stamp_env: Dict[str, Any], monkeypatch) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision, served by the real app on the test's (counting) connection.

    The seed user becomes an active member of the seeded tenant, the process-wide database handle
    is pinned to the test connection, and every cursor on it counts statements.
    """
    conn = stamp_env["conn"]
    conn.cursor_factory = CountingDictCursor
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.tenant_users (tenant_id, user_id, status) VALUES (%s, %s, 'active') "
            "ON CONFLICT DO NOTHING",
            (stamp_env["tenant"], stamp_env["user"]),
        )
        cur.execute(
            "INSERT INTO apiome.tenant_administrators (tenant_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (stamp_env["tenant"], stamp_env["user"]),
        )
        cur.execute("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (stamp_env["tenant"],))
        stamp_env["tenant_slug"] = cur.fetchone()["slug"]
    conn.commit()
    monkeypatch.setattr(database_module.db, "connection", conn)
    from app.main import app

    token = jwt.encode(
        {"user_id": stamp_env["user"], "sub": stamp_env["user"]},
        settings.effective_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    stamp_env["client"] = TestClient(app)
    stamp_env["headers"] = {"Authorization": f"Bearer {token}"}
    try:
        yield stamp_env
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.tenant_users WHERE tenant_id = %s::uuid", (stamp_env["tenant"],))
            cur.execute("DELETE FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid", (stamp_env["tenant"],))
        conn.commit()


def _guarded(ctx: Dict[str, Any], label: str, call: Callable[[], Any]) -> int:
    """Run ``call`` under the recorded budget for ``label``; return the statement count."""
    budget = _load_budgets()[label]
    if os.environ.get("UPDATE_QUERY_BUDGETS") == "1":
        with capture() as stats:
            response = call()
        _MEASURED[label] = stats.count
    else:
        with assert_max_queries(budget, label) as stats:
            response = call()
    assert response.status_code == 200, response.text
    return stats.count


def _get(ctx: Dict[str, Any], path: str) -> Callable[[], Any]:
    return lambda: ctx["client"].get(path, headers=ctx["headers"])


# ───────────────────────────── guarded endpoints ─────────────────────────────


def test_list_projects_stays_within_budget(ctx) -> None:
    _guarded(ctx, "GET /v1/projects/{tenant}", _get(ctx, f"/v1/projects/{ctx['tenant_slug']}"))


def test_get_project_stays_within_budget(ctx) -> None:
    _guarded(
        ctx, "GET /v1/projects/{tenant}/{project}", _get(ctx, f"/v1/projects/{ctx['tenant_slug']}/{ctx['project']}")
    )


def test_list_versions_stays_within_budget(ctx) -> None:
    _guarded(
        ctx, "GET /v1/versions/{tenant}/{project}", _get(ctx, f"/v1/versions/{ctx['tenant_slug']}/{ctx['project']}")
    )


def test_get_version_stays_within_budget(ctx) -> None:
    _seed_order(ctx)
    _guarded(
        ctx,
        "GET /v1/versions/{tenant}/{project}/{version}",
        _get(ctx, f"/v1/versions/{ctx['tenant_slug']}/{ctx['project']}/{ctx['version']}"),
    )


def test_document_render_cold_and_warm_stay_within_budget(ctx) -> None:
    _seed_order(ctx)
    path = f"/v1/versions/{ctx['tenant_slug']}/{ctx['project']}/{ctx['version']}/document"
    cold = _guarded(ctx, "GET /v1/versions/{tenant}/{project}/{version}/document (cold)", _get(ctx, path))
    warm = _guarded(ctx, "GET /v1/versions/{tenant}/{project}/{version}/document (warm)", _get(ctx, path))
    assert warm < cold


def test_project_detail_response_is_unchanged(ctx) -> None:
    """The detail endpoint keeps the full row (DBP-1.5, #7188): guards moved to the core lookup,
    this response did not — versions rollup, creator and metadata included."""
    response = ctx["client"].get(f"/v1/projects/{ctx['tenant_slug']}/{ctx['project']}", headers=ctx["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PROJECT_DETAIL_KEYS
    assert body["id"] == ctx["project"]
    assert body["versionsCount"] == 1
    assert isinstance(body["metadata"], dict)
    assert body["creator_name"] is not None or body["creator_email"] is not None


#: The ``GET /v1/projects/{tenant}/{project}`` response keys, captured from ``main`` before
#: DBP-1.5 (#7188) moved the guards to the core lookups.
PROJECT_DETAIL_KEYS = frozenset(
    {
        "changeReportTemplateVersionId",
        "created_at",
        "creator_email",
        "creator_id",
        "creator_name",
        "deleted_at",
        "description",
        "enabled",
        "id",
        "identityGroupId",
        "metadata",
        "name",
        "owner",
        "publishable",
        "qualityGrade",
        "qualityScore",
        "relatedArtifacts",
        "slug",
        "tenant_id",
        "updated_at",
        "versionsCount",
    }
)


# ─────────────────── guarded writes: the tenant guard is part of the write ───────────────────


def _guarded_call(label: str, call: Callable[[], Any]) -> Any:
    """Run a ``Database`` method under the recorded budget for ``label``; return its result."""
    budget = _load_budgets()[label]
    if os.environ.get("UPDATE_QUERY_BUDGETS") == "1":
        with capture() as stats:
            result = call()
        _MEASURED[label] = stats.count
        return result
    with assert_max_queries(budget, label):
        return call()


def test_class_path_and_operation_writes_stay_within_budget(ctx) -> None:
    """Update and delete of a class, path and operation are one statement each (#7188)."""
    db = database_module.db
    tenant = ctx["tenant"]
    class_id = str(db.create_class(ctx["version"], "Pet", {"type": "object"})["id"])
    path_id = str(db.create_path(ctx["version"], "/pets")["id"])
    operation_id = str(db.create_operation(path_id, "get")["id"])
    assert _guarded_call("Database.update_class", lambda: db.update_class(class_id, tenant, {"name": "Dog"}))
    assert _guarded_call("Database.update_path", lambda: db.update_path(path_id, tenant, {"pathname": "/dogs"}))
    assert _guarded_call(
        "Database.update_operation", lambda: db.update_operation(operation_id, tenant, {"operation": "put"})
    )
    assert _guarded_call("Database.delete_operation", lambda: db.delete_operation(operation_id, tenant))
    assert _guarded_call("Database.delete_path", lambda: db.delete_path(path_id, tenant))
    assert _guarded_call("Database.delete_class", lambda: db.delete_class(class_id, tenant))
    for label in (
        "Database.update_class",
        "Database.delete_class",
        "Database.update_path",
        "Database.delete_path",
        "Database.update_operation",
        "Database.delete_operation",
    ):
        assert _load_budgets()[label] == 1, label


# ─────────── set-based loaders: the same count at 10 and at 1,000 operations (#7189) ───────────


def _spec(operations: int) -> Dict[str, Any]:
    """An OpenAPI document with ``operations`` operations, four per path (GET, POST, PUT, DELETE).

    Each operation has a description, a path parameter and two responses with content; POST and
    PUT have a request body. Content refers to the ``Thing`` schema or is inline.
    """
    methods = ["get", "post", "put", "delete"]
    paths: Dict[str, Dict[str, Any]] = {}
    thing = {"schema": {"$ref": "#/components/schemas/Thing"}}
    header = {"X-Request-Id": {"schema": {"type": "string"}}}
    for i in range(operations):
        operation: Dict[str, Any] = {
            "operationId": f"op{i}",
            "summary": f"Operation {i}",
            "tags": ["things"],
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
            # Each response carries a header: the write plan stores it as the response's ``data``,
            # which ``check_response_schema_defined`` wants when the class is on the content.
            "responses": {
                code: {"description": text, "headers": header, "content": {"application/json": content}}
                for code, text, content in (("200", "OK", thing), ("404", "Missing", {"schema": {"type": "object"}}))
            },
        }
        if methods[i % 4] in ("post", "put"):
            operation["requestBody"] = {"content": {"application/json": thing, "application/xml": thing}}
        paths.setdefault(f"/things{i // 4:04d}/{{id}}", {})[methods[i % 4]] = operation
    return {
        "openapi": "3.1.0",
        "info": {"title": "Things", "version": "1.0.0"},
        "components": {"schemas": {"Thing": {"type": "object", "properties": {"id": {"type": "string"}}}}},
        "paths": paths,
    }


def _revision_with(ctx: Dict[str, Any], operations: int) -> Dict[str, Any]:
    """A new revision holding :func:`_spec` as relational rows and as its canonical model."""
    from app.canonical_persistence import persist_canonical_api
    from app.openapi_normalizer import OpenApiNormalizer
    from app.source_change_apply import build_canonical_writes

    db = database_module.db
    spec = _spec(operations)
    version = str(db.create_version(ctx["project"], ctx["user"], f"{operations}.0.0")["id"])
    conn = ctx["conn"]
    with conn.cursor() as cur:
        db._cursor_write_canonical_rows(cur, ctx["project"], version, build_canonical_writes(spec))
    conn.commit()
    persist_canonical_api(
        db, tenant_id=ctx["tenant"], creator_id=ctx["user"], version_id=version,
        model=OpenApiNormalizer().normalize(spec),
    )
    paths = db.get_paths_for_version(version)
    return {"version": version, "path": str(paths[0]["id"]), "paths": len(paths)}


_SIZES = (10, 1000)


def test_revision_loads_run_the_same_statements_at_10_and_1000_operations(ctx) -> None:
    """Document render, the canvas path read, the source-apply read and the canonical load (#7189)."""
    from app.canonical_persistence import load_canonical_api

    db = database_module.db
    conn = ctx["conn"]
    tenant, slug = ctx["tenant"], ctx["tenant_slug"]
    # Warm the per-process authentication lookups, so the first measured request is not the one
    # that pays for them.
    assert _get(ctx, f"/v1/projects/{slug}")().status_code == 200
    try:
        for size in _SIZES:
            rev = _revision_with(ctx, size)
            version = rev["version"]
            paths = _guarded_call(
                f"Database.load_paths_for_version ({size:,} operations)",
                lambda: db.load_paths_for_version(version),
            )
            assert sum(len(p["operations"]) for p in paths) == size
            _guarded(
                ctx,
                f"GET /v1/paths/{{tenant}}/{{version}}/{{path}}/full ({size:,} operations)",
                _get(ctx, f"/v1/paths/{slug}/{version}/{rev['path']}/full"),
            )
            _guarded(
                ctx,
                f"GET /v1/versions/{{tenant}}/{{project}}/{{version}}/document (cold, {size:,} operations)",
                _get(ctx, f"/v1/versions/{slug}/{ctx['project']}/{version}/document"),
            )
            with conn.cursor() as cur:
                row = db._source_apply_version_row(cur, tenant, ctx["project"], version)
                merged, _fingerprint, _claims = _guarded_call(
                    f"Database._cursor_current_merged_document ({size:,} operations)",
                    lambda: db._cursor_current_merged_document(cur, tenant, slug, row, "openapi"),
                )
            conn.rollback()
            assert len(merged["paths"]) == rev["paths"]
            api = _guarded_call(
                f"load_canonical_api ({size:,} operations)",
                lambda: load_canonical_api(db, tenant_id=tenant, version_id=version),
            )
            assert sum(len(service.operations) for service in api.services) == size
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            # Paths before classes: deleting a class nulls its content rows' class_id.
            cur.execute(
                "DELETE FROM apiome.version_path WHERE version_id IN "
                "(SELECT id FROM apiome.versions WHERE project_id = %s::uuid)",
                (ctx["project"],),
            )
        conn.commit()

    budgets = _load_budgets()
    for family in (
        "Database.load_paths_for_version",
        "GET /v1/paths/{tenant}/{version}/{path}/full",
        "Database._cursor_current_merged_document",
        "load_canonical_api",
    ):
        assert budgets[f"{family} (10 operations)"] == budgets[f"{family} (1,000 operations)"], family
    cold = "GET /v1/versions/{tenant}/{project}/{version}/document (cold, %s operations)"
    assert budgets[cold % "10"] == budgets[cold % "1,000"]


# ───────────────────────────── the guard itself ─────────────────────────────


def test_an_endpoint_over_its_budget_fails_and_names_its_statements(ctx) -> None:
    """The acceptance criterion: exceeding the recorded budget fails the test."""
    label = "GET /v1/projects/{tenant}"
    budget = _load_budgets()[label]
    with pytest.raises(QueryBudgetExceededError) as exc:
        with assert_max_queries(budget - 1 if budget > 0 else 0, label):
            _get(ctx, f"/v1/projects/{ctx['tenant_slug']}")()
            _get(ctx, f"/v1/projects/{ctx['tenant_slug']}")()
    assert f"{label} ran " in str(exc.value)
    assert "FROM apiome.tenants" in str(exc.value)


def test_the_counting_cursor_counts_execute_executemany_and_execute_values(ctx) -> None:
    conn = ctx["conn"]
    with capture() as stats:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS one")
            assert cur.fetchone() == {"one": 1}  # still a RealDictCursor
            cur.executemany("SELECT %s", [(1,), (2,), (3,)])
            execute_values(cur, "SELECT * FROM (VALUES %s) AS t(a)", [(i,) for i in range(5)], page_size=2)
    conn.rollback()
    # execute + executemany (one call) + execute_values (3 pages of 2).
    assert stats.count == 1 + 1 + 3
    assert stats.total_ms > 0


def test_a_failed_statement_is_still_counted(ctx) -> None:
    conn = ctx["conn"]
    with capture() as stats:
        with pytest.raises(Exception):
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM apiome.no_such_table")
    conn.rollback()
    assert stats.count == 1
