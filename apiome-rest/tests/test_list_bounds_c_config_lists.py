"""Tenant-configuration lists page by ``limit`` + ``cursor`` (DBP-1.13, #7196).

Export credentials, profiles, presets and auto-exports; agent keys; consumers and their bindings;
teams; API products; catalog agents and models; connectors; gateway configs; URL imports; and a
catalog item's conversion history. Each used to return every row. Each now reads one page (1,000
at most; 200 for the history), says whether another follows and hands out the cursor that reads
it. One parametrized test shows the four facts for every route; the SQL tests show a later page
is a predicate on the list's own sort key with a ``LIMIT``, never an ``OFFSET``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import (
    api_product_store,
    catalog_agent_store,
    catalog_connector_store,
    consumer_binding_store,
    gateway_config_store,
    team_store,
    url_import_store,
)
from app.auth import validate_authentication
from app.catalog_agents import ModelOut
from app.consumer_binding import BindingRecord
from app.consumer_contract import ConsumerSummary
from app.database import db
from app.keyset_pagination import MAX_PAGE_LIMIT, MAX_REVISION_PAGE_LIMIT
from app.main import app
from app.tenant_config_list_orders import (
    AGENT_KEYS_ORDER,
    CONSUMERS_ORDER,
    CONVERSIONS_BY_SOURCE_ORDER,
    EXPORT_AUTO_SUBSCRIPTIONS_ORDER,
    EXPORT_DELIVERY_PROFILES_ORDER,
    EXPORT_PRESETS_ORDER,
    EXPORT_STORAGE_CREDENTIALS_ORDER,
)
from tests.catalog_connector_fakes import FakeConnectorStore
from tests.keyset_paging_fakes import check_list_paging, ordered_rows
from tests.test_api_product_routes import _record as _product
from tests.test_catalog_agents import _agent
from tests.test_consumer_binding_routes import _CONSUMER as _BOUND_CONSUMER
from tests.test_consumer_binding_routes import _PROJECT as _BOUND_PROJECT
from tests.test_consumer_contract_routes import _consumer, _project
from tests.test_conversion_evidence_routes import _CATALOG_ITEM
from tests.test_conversion_evidence_routes import _row as _conversion_row
from tests.test_export_auto import _sub_row
from tests.test_export_delivery_profiles import _stored as _profile_row
from tests.test_export_object_storage_delivery import _credential_row
from tests.test_export_presets import _row as _preset_row
from tests.test_gateway_configs import _config
from tests.test_team_store import _team_row
from tests.test_url_import_routes import _row as _url_import_row

client = TestClient(app)
TENANT = "11111111-1111-4111-8111-111111111111"
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
_AUTH = {"tenant_id": TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "ada@example.com"}

#: ``(fetch, items_key, expected ids, id_of, has_more_key, next_cursor_key, maximum)``.
Case = Tuple[Callable[[Dict[str, Any]], Any], str, List[str], Callable[[Any], Any], str, str, int]


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture(autouse=True)
def _signed_in() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _get(url: str) -> Callable[[Dict[str, Any]], Any]:
    return lambda params: client.get(url, params=params)


def _windowed(order: Any, rows: List[Any]) -> Callable[..., List[Any]]:
    """A stand-in for a store's ``(…, limit, cursor)`` row reader with positional arguments."""
    page = ordered_rows(order, rows)
    return lambda *args: page(limit=args[-2], cursor=args[-1])


def _export_tenant() -> Any:
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": TENANT})


def _camel(url: str, key: str, expected: List[str], id_of: Callable[[Any], Any] = lambda i: i["id"]) -> Case:
    return _get(url), key, expected, id_of, "hasMore", "nextCursor", MAX_REVISION_PAGE_LIMIT


def _snake(url: str, key: str, expected: List[str], id_of: Callable[[Any], Any] = lambda i: i["id"]) -> Case:
    return _get(url), key, expected, id_of, "has_more", "next_cursor", MAX_REVISION_PAGE_LIMIT


# --- one context manager per list: wires the route to three rows and describes the call -------


@contextlib.contextmanager
def _storage_credentials() -> Iterator[Case]:
    rows = [_credential_row(id=_uuid(n), name=f"lake-{n}") for n in range(3)]
    module = "app.export_object_storage_delivery_routes"
    with patch(f"{module}.enforce_permission"), _export_tenant(), patch.object(
        db, "list_export_storage_credentials", side_effect=ordered_rows(EXPORT_STORAGE_CREDENTIALS_ORDER, rows)
    ):
        yield _camel("/v1/export/acme/storage-credentials", "credentials", [r["id"] for r in rows])


@contextlib.contextmanager
def _delivery_profiles() -> Iterator[Case]:
    rows = [_profile_row(id=_uuid(n), name=f"ci-{n}") for n in range(3)]
    with patch("app.export_delivery_profile_routes.enforce_permission"), _export_tenant(), patch.object(
        db, "list_export_delivery_profiles", side_effect=ordered_rows(EXPORT_DELIVERY_PROFILES_ORDER, rows)
    ):
        yield _camel("/v1/export/acme/delivery-profiles", "profiles", [r["id"] for r in rows])


@contextlib.contextmanager
def _presets() -> Iterator[Case]:
    rows = [_preset_row(id=_uuid(n), name=f"nightly-{n}") for n in range(3)]
    with patch("app.export_preset_routes.enforce_permission"), _export_tenant(), patch.object(
        db, "list_export_presets", side_effect=ordered_rows(EXPORT_PRESETS_ORDER, rows)
    ):
        yield _camel("/v1/export/acme/presets", "presets", [r["id"] for r in rows])


@contextlib.contextmanager
def _auto_exports() -> Iterator[Case]:
    rows = [_sub_row(id=_uuid(n), project_name="Orders API", preset_name=f"nightly-{n}") for n in range(3)]
    with patch("app.export_auto_routes.enforce_permission"), _export_tenant(), patch.object(
        db, "list_export_auto_subscriptions", side_effect=ordered_rows(EXPORT_AUTO_SUBSCRIPTIONS_ORDER, rows)
    ):
        yield _camel("/v1/export/acme/auto-exports", "subscriptions", [r["id"] for r in rows])


@contextlib.contextmanager
def _agent_keys() -> Iterator[Case]:
    from app.agent_keys import AgentKeyOut

    keys = [
        AgentKeyOut.model_construct(id=_uuid(n), name=f"key-{n}", created_at=T0 - timedelta(minutes=n))
        for n in range(3)
    ]
    with patch("app.agent_key_routes.enforce_permission"), patch(
        "app.agent_key_routes.list_agent_keys", side_effect=ordered_rows(AGENT_KEYS_ORDER, keys)
    ):
        yield _camel("/v1/tenants/acme/agent-keys", "keys", [k.id for k in keys])


class _BySummaryConsumer:
    """``CONSUMERS_ORDER`` read off a summary's consumer, as the route does."""

    decode = staticmethod(CONSUMERS_ORDER.decode)

    @staticmethod
    def cursor_of(summary: ConsumerSummary) -> str:
        return CONSUMERS_ORDER.cursor_of(summary.consumer)


@contextlib.contextmanager
def _consumers() -> Iterator[Case]:
    summaries = [
        ConsumerSummary(
            consumer=_consumer(
                id=_uuid(n), slug=f"svc-{n}", created_at=(T0 - timedelta(minutes=n)).isoformat()
            )
        )
        for n in range(3)
    ]
    with patch("app.consumer_contract_routes.enforce_permission"), patch(
        "app.consumer_contract_routes.resolve_project", return_value=_project()
    ), patch(
        "app.consumer_contract_routes.list_consumer_summaries",
        side_effect=ordered_rows(_BySummaryConsumer, summaries),
    ), patch(
        "app.consumer_binding_routes.attach_runtime_summaries", side_effect=lambda t, p, rows, days: list(rows)
    ):
        yield _snake(
            "/v1/tenants/acme/projects/pets/consumers",
            "consumers",
            [s.consumer.id for s in summaries],
            lambda item: item["consumer"]["id"],
        )


@contextlib.contextmanager
def _bindings() -> Iterator[Case]:
    bindings = [
        BindingRecord(
            id=_uuid(n),
            consumer_id=_BOUND_CONSUMER.id,
            kind="user_agent",
            name=f"billing-{n}/*",
            hashed=False,
            created_at=(T0 - timedelta(minutes=n)).isoformat(),
        )
        for n in range(3)
    ]
    module = "app.consumer_binding_routes"
    with patch(f"{module}.enforce_permission"), patch(
        f"{module}.resolve_project", return_value=_BOUND_PROJECT
    ), patch(f"{module}.get_consumer", return_value=_BOUND_CONSUMER), patch(
        f"{module}.list_bindings", side_effect=ordered_rows(consumer_binding_store.BINDINGS_ORDER, bindings)
    ):
        yield _snake(
            "/v1/tenants/acme/projects/pets/consumers/billing-service/bindings",
            "bindings",
            [b.id for b in bindings],
        )


@contextlib.contextmanager
def _teams() -> Iterator[Case]:
    rows = [
        {**_team_row(id=_uuid(n), slug=f"team-{n}", name=f"Team {n}"), "name_key": f"team {n}"}
        for n in range(3)
    ]
    with patch("app.team_routes.enforce_permission"), patch.object(
        team_store, "_team_rows", side_effect=_windowed(team_store.TEAMS_ORDER, rows)
    ):
        yield _snake("/v1/tenants/acme/teams", "teams", [r["slug"] for r in rows], lambda item: item["slug"])


@contextlib.contextmanager
def _products() -> Iterator[Case]:
    rows = [{"slug": f"product-{n}", "name_key": f"product {n}"} for n in range(3)]
    with patch("app.api_product_routes.enforce_permission"), patch.object(
        api_product_store, "_product_rows", side_effect=_windowed(api_product_store.PRODUCTS_ORDER, rows)
    ), patch.object(api_product_store, "_record", side_effect=lambda row: _product(row["slug"])):
        yield _snake(
            "/v1/tenants/acme/products", "products", [r["slug"] for r in rows], lambda item: item["slug"]
        )


@contextlib.contextmanager
def _catalog_agents() -> Iterator[Case]:
    rows = [{"id": _uuid(n), "slug": f"bot-{n}", "name_key": f"bot {n}"} for n in range(3)]
    with patch("app.catalog_agent_routes._permit"), patch.object(
        catalog_agent_store, "_agent_rows", side_effect=_windowed(catalog_agent_store.AGENTS_ORDER, rows)
    ), patch.object(
        catalog_agent_store,
        "_agent_out",
        side_effect=lambda row: _agent().model_copy(update={"slug": row["slug"]}),
    ):
        yield _camel(
            "/v1/tenants/acme/catalog-agents", "agents", [r["slug"] for r in rows], lambda item: item["slug"]
        )


@contextlib.contextmanager
def _catalog_models() -> Iterator[Case]:
    rows = [{"id": _uuid(n), "slug": f"model-{n}", "name_key": f"model {n}"} for n in range(3)]

    def out(row: Dict[str, Any]) -> ModelOut:
        return ModelOut(
            id=row["id"], slug=row["slug"], name=row["slug"], provider="Anthropic", model_name="claude",
            hosting="api", deprecated=False,
        )

    with patch("app.catalog_agent_routes._permit"), patch.object(
        catalog_agent_store, "_model_rows", side_effect=_windowed(catalog_agent_store.MODELS_ORDER, rows)
    ), patch.object(catalog_agent_store, "_model_out", side_effect=out):
        yield _camel("/v1/tenants/acme/catalog-models", "models", [r["id"] for r in rows])


@contextlib.contextmanager
def _connectors() -> Iterator[Case]:
    with pytest.MonkeyPatch.context() as monkeypatch, patch("app.catalog_connector_routes.enforce_permission"):
        store = FakeConnectorStore().install(monkeypatch)
        ids = [store.add_connector(TENANT, id=_uuid(n), name=f"gateway-{n}")["id"] for n in range(3)]
        yield _camel("/v1/tenants/acme/connectors", "connectors", ids)


@contextlib.contextmanager
def _gateway_configs() -> Iterator[Case]:
    rows = [{"id": _uuid(n), "slug": f"kong-{n}", "name_key": f"kong {n}"} for n in range(3)]
    with patch("app.gateway_config_routes.enforce_permission"), patch.object(
        gateway_config_store,
        "_gateway_config_rows",
        side_effect=_windowed(gateway_config_store.GATEWAY_CONFIGS_ORDER, rows),
    ), patch.object(
        gateway_config_store,
        "_out",
        side_effect=lambda row: _config().model_copy(update={"slug": row["slug"]}),
    ):
        yield _camel(
            "/v1/tenants/acme/gateway-configs", "gatewayConfigs", [r["slug"] for r in rows], lambda i: i["slug"]
        )


@contextlib.contextmanager
def _url_imports() -> Iterator[Case]:
    rows = [_url_import_row(id=_uuid(n), updated_at=T0 - timedelta(minutes=n)) for n in range(3)]
    with patch("app.url_import_routes.enforce_permission"), patch.object(
        url_import_store, "list_specs", side_effect=ordered_rows(url_import_store.SPECS_ORDER, rows)
    ):
        yield _camel("/v1/tenants/acme/url-imports", "urlImports", [r["id"] for r in rows])


@contextlib.contextmanager
def _conversions() -> Iterator[Case]:
    rows = [_conversion_row(id=_uuid(n), created_at=T0 - timedelta(minutes=n)) for n in range(3)]
    with patch("app.catalog_routes.db") as mock_db:
        mock_db.get_catalog_item_by_id.return_value = _CATALOG_ITEM
        mock_db.get_conversions_for_source.side_effect = ordered_rows(CONVERSIONS_BY_SOURCE_ORDER, rows)
        fetch, key, expected, _, more, cursor, _ = _camel(
            "/v1/catalog/acme/cat-1/conversions", "conversions", [r["id"] for r in rows]
        )
        yield fetch, key, expected, lambda item: item["provenanceId"], more, cursor, MAX_PAGE_LIMIT


CASES = {
    "export storage credentials": _storage_credentials,
    "export delivery profiles": _delivery_profiles,
    "export presets": _presets,
    "auto-exports": _auto_exports,
    "agent keys": _agent_keys,
    "consumers": _consumers,
    "consumer bindings": _bindings,
    "teams": _teams,
    "API products": _products,
    "catalog agents": _catalog_agents,
    "catalog models": _catalog_models,
    "connectors": _connectors,
    "gateway configs": _gateway_configs,
    "URL imports": _url_imports,
    "catalog conversions": _conversions,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_configuration_list_pages_by_cursor_up_to_its_maximum(name: str) -> None:
    with CASES[name]() as (fetch, items_key, expected, id_of, has_more_key, next_cursor_key, maximum):
        check_list_paging(
            fetch,
            items_key,
            expected,
            maximum=maximum,
            id_of=id_of,
            has_more_key=has_more_key,
            next_cursor_key=next_cursor_key,
        )


def test_an_unpaged_request_reads_the_maximum_page_and_says_there_is_no_more() -> None:
    with _teams() as (fetch, *_):
        body = fetch({}).json()
    assert body["count"] == 3 and body["has_more"] is False and body["next_cursor"] is None


# --- SQL: a later page is a predicate on the sort key plus a LIMIT ---------------------------


def _captured(call: Callable[[], Any], target: Any = db) -> Tuple[str, Tuple[Any, ...]]:
    with patch.object(target, "execute_query", return_value=[]) as query:
        call()
    sql, params = query.call_args.args
    return " ".join(sql.split()), tuple(params)


@pytest.mark.parametrize(
    ("call", "cursor", "after", "order_by"),
    [
        (
            lambda c: db.list_export_storage_credentials(TENANT, limit=3, cursor=c),
            ["lake", _uuid(1)],
            "(name > %s) OR (name = %s AND id > %s::uuid)",
            "ORDER BY name ASC, id ASC LIMIT %s",
        ),
        (
            lambda c: db.list_export_delivery_profiles(TENANT, "git", limit=3, cursor=c),
            ["ci", _uuid(1)],
            "(name > %s) OR (name = %s AND id > %s::uuid)",
            "ORDER BY name ASC, id ASC LIMIT %s",
        ),
        (
            lambda c: db.list_export_presets(TENANT, limit=3, cursor=c),
            ["nightly", _uuid(1)],
            "(x.name > %s) OR (x.name = %s AND x.id > %s::uuid)",
            "ORDER BY x.name ASC, x.id ASC LIMIT %s",
        ),
        (
            lambda c: db.list_export_auto_subscriptions(TENANT, limit=3, cursor=c),
            ["Orders", "nightly", _uuid(1)],
            "(p.name = %s AND x.name = %s AND s.id > %s::uuid)",
            "ORDER BY p.name ASC, x.name ASC, s.id ASC LIMIT %s",
        ),
        (
            lambda c: db.list_agent_keys(TENANT, limit=3, cursor=c),
            [T0, _uuid(1)],
            "(ak.created_at < %s::timestamptz) OR (ak.created_at = %s::timestamptz AND ak.id > %s::uuid)",
            "ORDER BY ak.created_at DESC, ak.id ASC LIMIT %s",
        ),
        (
            lambda c: db.list_consumers(TENANT, TENANT, limit=3, cursor=c),
            [T0, "billing"],
            "(consumer.created_at = %s::timestamptz AND consumer.slug > %s)",
            "ORDER BY consumer.created_at DESC, consumer.slug ASC LIMIT %s",
        ),
        (
            lambda c: db.get_conversions_for_source(TENANT, _uuid(9), limit=3, cursor=c),
            [T0, _uuid(1)],
            "(cp.created_at = %s::timestamptz AND cp.id < %s::uuid)",
            "ORDER BY cp.created_at DESC, cp.id DESC LIMIT %s",
        ),
    ],
)
def test_a_database_accessor_continues_after_its_cursor_with_a_limit(call, cursor, after, order_by) -> None:
    sql, params = _captured(lambda: call(cursor))
    assert after in sql and sql.rstrip().endswith(order_by) and "OFFSET" not in sql
    assert params[-1] == 3 and cursor[-1] in params


@pytest.mark.parametrize(
    "call",
    [
        lambda: db.list_export_storage_credentials(TENANT),
        lambda: db.list_export_delivery_profiles(TENANT),
        lambda: db.list_export_presets(TENANT),
        lambda: db.list_export_auto_subscriptions(TENANT),
        lambda: db.list_agent_keys(TENANT),
        lambda: db.list_consumers(TENANT, TENANT),
        lambda: db.get_conversions_for_source(TENANT, _uuid(9)),
    ],
)
def test_an_internal_caller_still_reads_the_whole_list(call) -> None:
    sql, _ = _captured(call)
    assert "LIMIT %s" not in sql and " AND ((" not in sql


@pytest.mark.parametrize(
    ("module", "call", "after", "tail"),
    [
        (
            team_store,
            lambda c: team_store._team_rows(TENANT, 3, c),
            "(lower(t.name) = %s AND t.slug > %s)",
            "ORDER BY lower(t.name) ASC, t.slug ASC LIMIT %s",
        ),
        (
            api_product_store,
            lambda c: api_product_store._product_rows(TENANT, 3, c),
            "(lower(ap.name) = %s AND ap.slug > %s)",
            "ORDER BY lower(ap.name) ASC, ap.slug ASC LIMIT %s",
        ),
        (
            catalog_agent_store,
            lambda c: catalog_agent_store._agent_rows(TENANT, 3, c),
            "(lower(a.name) = %s AND a.id > %s",
            "ORDER BY lower(a.name) ASC, a.id ASC LIMIT %s",
        ),
        (
            catalog_agent_store,
            lambda c: catalog_agent_store._model_rows(TENANT, 3, c),
            "(lower(m.name) = %s AND m.id > %s",
            "ORDER BY lower(m.name) ASC, m.id ASC LIMIT %s",
        ),
    ],
)
def test_a_name_ordered_store_selects_its_sort_key_and_windows_on_it(module, call, after, tail) -> None:
    cursor = ["payments", "payments"] if "slug" in after else ["payments", _uuid(1)]
    sql, params = _captured(lambda: call(cursor), module.db)
    assert "AS name_key" in sql and after in sql and sql.rstrip().endswith(tail)
    assert params[-1] == 3


def test_the_stores_that_take_a_database_handle_window_the_same_way() -> None:
    handle = MagicMock()
    handle.execute_query.return_value = []
    catalog_connector_store.list_connectors(handle, TENANT, limit=3, cursor=["kong", _uuid(1)])
    gateway_config_store.page_gateway_configs(handle, TENANT, limit=2, cursor=["kong", _uuid(1)])
    url_import_store.list_specs(handle, TENANT, limit=3, cursor=[T0, _uuid(1)])
    consumer_binding_store.list_bindings(handle, TENANT, _uuid(2), limit=3, cursor=[T0, _uuid(1)])
    connectors, gateways, imports, bindings = (
        (" ".join(call.args[0].split()), call.args[1]) for call in handle.execute_query.call_args_list
    )
    assert connectors[0].endswith("ORDER BY lower(c.name) ASC, c.id ASC LIMIT %s") and connectors[1][-1] == 3
    assert "(lower(c.name) = %s AND c.id > %s::uuid)" in connectors[0]
    # A page reads one row more than it returns, to learn whether another follows.
    assert gateways[0].endswith("ORDER BY lower(g.name) ASC, g.id ASC LIMIT %s") and gateways[1][-1] == 3
    assert imports[0].endswith("ORDER BY s.updated_at DESC, s.id ASC LIMIT %s")
    assert "(s.updated_at = %s::timestamptz AND s.id > %s::uuid)" in imports[0]
    assert bindings[0].endswith("ORDER BY created_at DESC, id ASC LIMIT %s")
    assert "(created_at = %s::timestamptz AND id > %s::uuid)" in bindings[0]


# --- lists bounded by a fixed cap rather than a cursor -----------------------------------------


def test_the_shadow_report_cuts_each_section_to_the_limit_and_keeps_the_full_summary() -> None:
    report = {
        "generatedAt": "2026-11-22T09:00:00+00:00",
        "filters": {},
        "connectors": [],
        "stale": [],
        "summary": {"shadow": 3, "possibleMatches": 0, "undeployed": 0, "drift": 0, "ignored": 0},
        "shadow": [
            {"itemId": _uuid(n), "connectorId": _uuid(9), "remoteId": f"r{n}", "status": "seen"} for n in range(3)
        ],
        "possibleMatches": [],
        "undeployed": [],
        "drift": [],
        "ignored": [],
    }
    module = "app.shadow_api_routes"
    with patch(f"{module}.enforce_permission"), patch(f"{module}.shadow_api_store") as store, patch(
        f"{module}.build_shadow_report", side_effect=lambda **_: {**report, "shadow": list(report["shadow"])}
    ):
        store.load_report_connectors.return_value = []
        cut = client.get("/v1/tenants/acme/shadow-report", params={"limit": 2})
        whole = client.get("/v1/tenants/acme/shadow-report")
        too_many = client.get("/v1/tenants/acme/shadow-report", params={"limit": MAX_REVISION_PAGE_LIMIT + 1})
    assert cut.status_code == 200, cut.text
    assert len(cut.json()["shadow"]) == 2 and cut.json()["summary"]["shadow"] == 3
    assert len(whole.json()["shadow"]) == 3
    assert too_many.status_code == 422


def test_the_shadow_report_inventory_read_is_capped() -> None:
    from app import shadow_api_store

    handle = MagicMock()
    handle.execute_query.return_value = []
    shadow_api_store.load_report_items(handle, [_uuid(1)])
    assert f"LIMIT {shadow_api_store.REPORT_ITEM_CAP}" in handle.execute_query.call_args.args[0]


def test_the_usage_source_listing_and_the_mock_usage_rollups_have_a_fixed_cap() -> None:
    from app import usage_controls_store

    handle = MagicMock()
    handle.execute_query.return_value = []
    usage_controls_store.list_sources(handle, TENANT, _uuid(1))
    usage_controls_store.list_toolsets(handle, TENANT, _uuid(1))
    for call in handle.execute_query.call_args_list:
        assert f"LIMIT {usage_controls_store.LIST_CAP}" in call.args[0]
    sql, _ = _captured(lambda: db.list_mock_usage_rollups(TENANT, days=400))
    assert sql.endswith("LIMIT 5000")
