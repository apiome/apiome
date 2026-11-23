"""The SQL of the tenant-configuration lists that page by cursor (DBP-1.13, #7196).

Without ``limit`` an accessor reads its whole list, as its internal callers expect. With one it
adds a ``LIMIT``, and with a cursor the keyset predicate of its declared ordering — never an
``OFFSET``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Sequence, Tuple
from unittest.mock import patch

import pytest

from app import (
    merge_request_store,
    schema_registry_store,
    slate_deployment_store,
    slate_git_preview_store,
    sso_provider_store,
    tenant_document_store,
)
from app.database import db
from app.keyset_lists import ListOrder
from app.tenant_list_orders import (
    CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER,
    MCP_API_KEYS_ORDER,
    MCP_CATEGORIES_ORDER,
    MCP_COLLECTIONS_ORDER,
    MCP_ENDPOINT_MANIFESTS_ORDER,
    MCP_ENDPOINT_NOTES_ORDER,
    MCP_SAVED_SEARCHES_ORDER,
    MEMBERS_ORDER,
    PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER,
    ROLES_ORDER,
    TENANT_REPOSITORIES_ORDER,
)
from tests.scripted_connection import ScriptedConnection, database_with

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
ENDPOINT = "33333333-3333-4333-8333-333333333333"
ROW = "44444444-4444-4444-8444-444444444444"
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)

#: accessor name, its leading arguments, its ordering, and a cursor for that ordering.
ACCESSORS: List[Tuple[str, Tuple[Any, ...], ListOrder, List[Any]]] = [
    ("list_roles", (TENANT,), ROLES_ORDER, [False, 4, "Release Manager", ROW]),
    ("list_members", (TENANT,), MEMBERS_ORDER, ["Ada", ROW]),
    ("list_push_webhook_subscriptions", (TENANT,), PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER, [T0, ROW]),
    (
        "list_change_report_template_version_summaries",
        (TENANT,),
        CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER,
        [None, "1.0.0", ROW],
    ),
    ("list_tenant_repositories", (TENANT,), TENANT_REPOSITORIES_ORDER, [T0, ROW]),
    ("list_mcp_categories", (TENANT,), MCP_CATEGORIES_ORDER, [3, "weather", "weather", ROW]),
    ("list_mcp_saved_searches", (TENANT, USER), MCP_SAVED_SEARCHES_ORDER, [True, T0, "Mine", ROW]),
    ("list_mcp_endpoint_notes", (TENANT, ENDPOINT), MCP_ENDPOINT_NOTES_ORDER, [T0, ROW]),
    ("list_mcp_collections", (TENANT,), MCP_COLLECTIONS_ORDER, [T0, "Geo tools", ROW]),
    ("list_mcp_endpoint_manifests", (ENDPOINT,), MCP_ENDPOINT_MANIFESTS_ORDER, [T0, ROW]),
    ("list_mcp_api_keys", (TENANT,), MCP_API_KEYS_ORDER, [T0, ROW]),
]


def _run(call: Callable[..., Any], *args: Any, **kwargs: Any) -> Tuple[str, Sequence[Any]]:
    with patch.object(db, "execute_query", return_value=[]) as query:
        call(*args, **kwargs)
    sql, params = query.call_args.args
    return " ".join(sql.split()), tuple(params)


@pytest.mark.parametrize("name, args, order, cursor", ACCESSORS, ids=[a[0] for a in ACCESSORS])
def test_an_accessor_reads_everything_without_a_limit(name, args, order, cursor) -> None:
    sql, params = _run(getattr(db, name), *args)
    assert f"ORDER BY {order.order_by}" in sql
    assert "LIMIT" not in sql.split("ORDER BY")[-1]
    assert "OFFSET" not in sql
    assert params[: len(args)] == args


@pytest.mark.parametrize("name, args, order, cursor", ACCESSORS, ids=[a[0] for a in ACCESSORS])
def test_an_accessor_continues_after_a_cursor_with_a_limit(name, args, order, cursor) -> None:
    sql, params = _run(getattr(db, name), *args, limit=11, cursor=cursor)
    after_sql, after_params, _, _ = order.window(11, cursor)
    assert " ".join(after_sql.split()) in sql
    assert sql.endswith(f"ORDER BY {order.order_by} LIMIT %s")
    assert "OFFSET" not in sql
    assert params[-(len(after_params) + 1) :] == (*after_params, 11)


def test_dead_letters_page_on_the_failure_time_with_an_id_tie_breaker() -> None:
    sql, params = _run(db.list_push_webhook_dead_letter_events, TENANT, 5, cursor=[T0, ROW])
    assert "status = 'dead_letter'" in sql
    assert sql.endswith("ORDER BY updated_at DESC, id DESC LIMIT %s")
    assert params == (TENANT, T0, T0, ROW, 5)


def test_the_role_list_carries_the_rank_its_cursor_needs() -> None:
    sql, _ = _run(db.list_roles, TENANT, limit=3)
    assert "END AS builtin_rank" in sql
    assert "r.is_builtin DESC, CASE r.slug WHEN 'owner' THEN 0" in sql


def test_the_category_list_carries_the_label_key_its_cursor_needs() -> None:
    sql, params = _run(db.list_mcp_categories, TENANT, limit=3)
    assert "lower(c.label) AS label_key" in sql
    assert "(c.tenant_id IS NULL OR c.tenant_id = %s::uuid)" in sql
    assert params == (TENANT, TENANT, 3)


def test_the_tag_vocabulary_pages_by_limit_and_offset() -> None:
    whole, whole_params = _run(db.list_mcp_tag_vocabulary, TENANT)
    assert "LIMIT" not in whole and whole_params == (TENANT,)
    paged, paged_params = _run(db.list_mcp_tag_vocabulary, TENANT, limit=10, offset=20)
    assert paged.endswith("ORDER BY endpoint_count DESC, t.tag ASC LIMIT %s OFFSET %s")
    assert paged_params == (TENANT, 10, 20)


# --- store modules ---------------------------------------------------------------------------


def _statements(monkeypatch, results: List[List[Any]], call: Callable[[Any], Any]):
    conn = ScriptedConnection(results)
    call(database_with(monkeypatch, conn))
    return [(" ".join(sql.split()), tuple(params or ())) for sql, params in conn.statements]


def test_subjects_page_by_name(monkeypatch) -> None:
    order = schema_registry_store.SUBJECTS_ORDER
    ((sql, params),) = _statements(
        monkeypatch,
        [[]],
        lambda database: schema_registry_store.list_subjects(
            database, TENANT, limit=4, cursor=["orders-value", ROW]
        ),
    )
    assert "(s.name > %s) OR (s.name = %s AND s.id > %s::uuid)" in sql
    assert sql.endswith(f"GROUP BY s.id ORDER BY {order.order_by} LIMIT %s")
    assert params == (TENANT, "orders-value", "orders-value", ROW, 4)


def test_subject_versions_page_by_version_number(monkeypatch) -> None:
    ((sql, params),) = _statements(
        monkeypatch,
        [[]],
        lambda database: schema_registry_store.list_versions(database, "s1", limit=4, cursor=[7]),
    )
    assert "v.deleted_at IS NULL AND ((v.version > %s::bigint))" in sql
    assert sql.endswith("ORDER BY v.version ASC LIMIT %s")
    assert params == ("s1", 7, 4)


def test_draft_branches_page_newest_first(monkeypatch) -> None:
    order = merge_request_store.DRAFT_BRANCHES_ORDER
    monkeypatch.setattr(merge_request_store, "_project", lambda _tenant, _ref: {"id": ROW})
    with patch.object(merge_request_store.db, "execute_query", return_value=[]) as query:
        merge_request_store.list_draft_branches(TENANT, "petstore", limit=4, cursor=[T0, "draft/a", ROW])
        merge_request_store.list_draft_branches(TENANT, "petstore")
    paged, params = query.call_args_list[0].args
    assert " ".join(paged.split()).endswith(f"ORDER BY {order.order_by} LIMIT %s")
    assert "b.created_at < %s::timestamptz" in paged
    assert params[0] == ROW and params[-1] == 4
    whole, whole_params = query.call_args_list[1].args
    assert "LIMIT" not in whole and whole_params == (ROW,)


def test_sso_providers_page_and_read_only_their_own_domains(monkeypatch) -> None:
    provider = {"id": ROW, "slug": "acme", "created_at": T0}
    statements = _statements(
        monkeypatch,
        [[provider], []],
        lambda database: sso_provider_store.list_providers(database, tenant_id=TENANT, limit=4),
    )
    (providers_sql, providers_params), (domains_sql, domains_params) = statements
    assert providers_sql.endswith("ORDER BY p.created_at DESC, p.slug ASC, p.id ASC LIMIT %s")
    assert providers_params == (TENANT, 4)
    assert "d.provider_id = ANY(%s::uuid[])" in domains_sql
    assert domains_params == ([ROW],)


def test_the_unpaged_sso_provider_read_is_unchanged_in_scope(monkeypatch) -> None:
    statements = _statements(
        monkeypatch, [[], []], lambda database: sso_provider_store.list_providers(database)
    )
    assert all("LIMIT" not in sql and params == () for sql, params in statements)


def test_routable_sso_providers_page_by_slug(monkeypatch) -> None:
    ((sql, params),) = _statements(
        monkeypatch,
        [[]],
        lambda database: sso_provider_store.list_routable_with_secrets(
            database, limit=4, cursor=["acme", ROW]
        ),
    )
    assert "(p.slug > %s) OR (p.slug = %s AND p.id > %s::uuid)" in sql
    assert sql.endswith("GROUP BY p.id ORDER BY p.slug ASC, p.id ASC LIMIT %s")
    assert params == ("acme", "acme", ROW, 4)


class _Cursor:
    """Records the one statement a store function runs."""

    def __init__(self) -> None:
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append((" ".join(sql.split()), tuple(params or ())))

    def fetchall(self) -> List[Any]:
        return []


class _CursorContext:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor = cursor

    def __enter__(self) -> _Cursor:
        return self.cursor

    def __exit__(self, *_: Any) -> None:
        return None


@pytest.mark.parametrize(
    "module, call, order",
    [
        (
            slate_deployment_store,
            lambda limit, cursor: slate_deployment_store.list_sites(
                object(), tenant_id=TENANT, project_id=ROW, limit=limit, cursor=cursor
            ),
            slate_deployment_store.SITES_ORDER,
        ),
        (
            slate_git_preview_store,
            lambda limit, cursor: slate_git_preview_store.list_connections(
                object(), tenant_id=TENANT, limit=limit, cursor=cursor
            ),
            slate_git_preview_store.CONNECTIONS_ORDER,
        ),
    ],
    ids=["slate-sites", "slate-git-connections"],
)
def test_slate_lists_page_newest_first(monkeypatch, module, call, order) -> None:
    cursor = _Cursor()
    monkeypatch.setattr(module, "db_cursor", lambda _db: _CursorContext(cursor))
    call(4, [T0, ROW])
    call(None, None)
    paged, paged_params = cursor.statements[0]
    assert paged.endswith(f"ORDER BY {order.order_by} LIMIT %s")
    assert "created_at < %s::timestamptz" in paged
    assert paged_params[0] == TENANT and paged_params[-4:] == (T0, T0, ROW, 4)
    whole, _ = cursor.statements[1]
    assert whole.endswith(f"ORDER BY {order.order_by}")


def test_tenant_buckets_are_read_up_to_a_limit(monkeypatch) -> None:
    cursor = _Cursor()
    monkeypatch.setattr(tenant_document_store, "db_cursor", lambda _db: _CursorContext(cursor))
    tenant_document_store.list_tenant_stores(object(), limit=7)
    tenant_document_store.list_tenant_stores(object())
    assert cursor.statements[0][0].endswith("ORDER BY t.slug LIMIT %s")
    assert cursor.statements[0][1] == (7,)
    assert cursor.statements[1][0].endswith("ORDER BY t.slug") and cursor.statements[1][1] == ()


def test_the_store_status_says_when_the_tenant_bucket_list_was_cut(monkeypatch) -> None:
    from app import document_store_health as health
    from app.document_store import DbDocumentStore
    from tests.test_document_store_health import FakeBlobDatabase

    asked: List[Any] = []

    def buckets(_database: Any, *, limit: Any = None) -> List[Any]:
        asked.append(limit)
        return [{"tenantId": str(n)} for n in range(3 if limit is None else min(3, limit))]

    monkeypatch.setattr(health, "tenant_buckets", buckets)
    store = DbDocumentStore(database=FakeBlobDatabase())
    cut = health.describe_store(FakeBlobDatabase(), store=store, tenant_bucket_limit=2)
    whole = health.describe_store(FakeBlobDatabase(), store=store)
    assert asked == [3, None]
    assert len(cut["tenantBuckets"]) == 2 and cut["tenantBucketsTruncated"] is True
    assert len(whole["tenantBuckets"]) == 3 and whole["tenantBucketsTruncated"] is False
