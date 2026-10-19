"""Runtime edges and suggested consumers against a live Postgres — CDG-3.5 (#5970).

What only the real schema, ingest and graph can prove:

* attributed usage materializes ``runtime_calls`` edges (provenance ``runtime``, ``source_ref
  usage:30d``, evidence = calls, errors, last-seen day and the binding kinds), idempotently, beside —
  never merged into — the contract's declared ``consumes`` edges;
* a runtime edge whose calls left the window goes stale, and is purged after 30 days;
* the blast radius follows runtime edges, and a consumer reached both ways carries both provenances;
* the usage sweep refreshes the edges after its rollup;
* unattributed calls become **suggested consumers** — by user-agent token, or by an opaque id for a
  hashed hint whose HMAC never appears in a response — and registering one creates the consumer and
  the binding, so the next batch is attributed and the suggestion disappears;
* V293 refuses a raw value as a client key.

Everything runs in one always-rolled-back transaction (the fixtures of ``test_consumer_binding_db``).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import psycopg2
import pytest

from app import catalog_graph
from app.blast_radius import BlastRadiusRequest, blast_radius
from app.runtime_graph import SOURCE_REF, materialize_runtime
from app.usage_sweep import run_usage_sweep
from tests import test_consumer_binding_db as binding_db

tx = binding_db.tx
seeded = binding_db.seeded
stack = binding_db.stack
NOW = binding_db.NOW
_event = binding_db._event
_ingest = binding_db._ingest
_bind = binding_db._bind
_hint = binding_db._hint
_rollup = binding_db._rollup

pytestmark = pytest.mark.requires_db

GET_PET = binding_db.GET_PET
ORDERS = binding_db.ORDERS
HINT_VALUE = "ak_live_unregistered_client_77"


@pytest.fixture
def graph(stack: Dict[str, Any]) -> Dict[str, Any]:
    """The binding stack, with V293 required."""
    stack["cursor"].execute("SELECT to_regclass('apiome.usage_unattributed_client_daily') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V293 not applied")
    return stack


def _runtime_edges(cursor: Any, tenant: str) -> List[Dict[str, Any]]:
    cursor.execute(
        """SELECT from_kind, from_id::text AS from_id, to_kind, to_id::text AS to_id, edge_kind, pointer,
                  provenance, source_ref, evidence, stale_since
           FROM apiome.catalog_edges WHERE tenant_id = %s AND provenance = 'runtime' ORDER BY pointer""",
        (tenant,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _billing_traffic(graph: Dict[str, Any]) -> None:
    """Billing calls GET /pets/{id} through a key and a user agent, and the orders route once."""
    _bind(graph, "billing-service", {"kind": "api_key", "name": "x-api-key", "value": binding_db.API_KEY_VALUE})
    _bind(graph, "billing-service", {"kind": "user_agent", "name": "billing-service/*"})
    _ingest(
        graph["db"],
        graph["seed"],
        [_event("/pets/1", consumer_hint=_hint(graph, "api_key", binding_db.API_KEY_VALUE)) for _ in range(3)]
        + [_event("/pets/2", user_agent="billing-service/2", status=500)]
        + [_event("/users/9/orders", user_agent="billing-service/2")],
    )
    _rollup(graph["cursor"])


# ---------------------------------------------------------------------------------------------
# Runtime edges
# ---------------------------------------------------------------------------------------------


def test_attributed_usage_materializes_runtime_edges(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _billing_traffic(graph)
    counts = materialize_runtime(db, seed["tenant"])
    assert counts["current"] == 2

    edges = _runtime_edges(cursor, seed["tenant"])
    billing = graph["consumers"]["billing-service"]
    assert [(e["from_kind"], e["from_id"], e["to_kind"], e["to_id"], e["edge_kind"], e["pointer"]) for e in edges] == [
        ("consumer", billing, "project", seed["project"], "runtime_calls", GET_PET),
        ("consumer", billing, "project", seed["project"], "runtime_calls", ORDERS),
    ]
    assert {e["source_ref"] for e in edges} == {SOURCE_REF} == {"usage:30d"}
    pet = edges[0]["evidence"]
    assert pet == {
        "calls": 4,
        "errors": 1,
        "last_seen_day": NOW.date().isoformat(),
        "window_days": 30,
        "via": ["api_key", "user_agent"],
        "consumer_slug": "billing-service",
    }
    # Idempotent: a second run touches the same rows and adds none.
    again = materialize_runtime(db, seed["tenant"])
    assert again["current"] == 2 and again["staled"] == 0
    assert len(_runtime_edges(cursor, seed["tenant"])) == 2


def test_runtime_edges_sit_beside_declared_ones_never_merged(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    billing = graph["consumers"]["billing-service"]
    cursor.execute(
        """INSERT INTO apiome.consumer_contract (tenant_id, project_id, consumer_id, revision, source, surface,
                                                  operation_count, surface_pointers)
           VALUES (%s, %s, %s, 1, 'manual', %s, 1, %s)""",
        (
            seed["tenant"],
            seed["project"],
            billing,
            json.dumps({"schema_version": "apiome.consumer.contract/v1", "operations": [
                {"method": "get", "path": "/pets/{petId}", "pointer": GET_PET, "fields": []}]}),
            [GET_PET],
        ),
    )
    catalog_graph.materialize(db, seed["tenant"], "test", families=["consumes"])
    _billing_traffic(graph)
    materialize_runtime(db, seed["tenant"])

    page = catalog_graph.list_edges(db, seed["tenant"], "consumer", billing, direction="out")
    pairs = sorted((e["edge_kind"], e["provenance"], e["pointer"]) for e in page.edges)
    assert pairs == [
        ("consumes", "derived", GET_PET),
        ("runtime_calls", "runtime", GET_PET),
        ("runtime_calls", "runtime", ORDERS),
    ]

    answer = blast_radius(db, seed["tenant"], BlastRadiusRequest(kind="project", entity=seed["project"],
                                                                 pointers=(GET_PET,)))
    node = next(n for n in answer["direct"] if n["id"] == billing)
    assert set(node["provenances"]) == {"derived", "runtime"}

    runtime_only = blast_radius(db, seed["tenant"], BlastRadiusRequest(
        kind="project", entity=seed["project"], pointers=(ORDERS,), provenances=("runtime",)))
    assert [(n["id"], n["edge_kind"], n["provenances"]) for n in runtime_only["direct"]] == [
        (billing, "runtime_calls", ["runtime"])
    ]
    assert runtime_only["provenance"] == ["runtime"]


def test_a_runtime_edge_whose_calls_left_the_window_goes_stale_then_is_purged(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _billing_traffic(graph)
    materialize_runtime(db, seed["tenant"])
    # The orders calls age out of the window; the edges were last touched before this run.
    cursor.execute(
        "UPDATE apiome.usage_daily SET day = day - 40 WHERE tenant_id = %s AND operation_key = %s",
        (seed["tenant"], ORDERS),
    )
    cursor.execute(
        "UPDATE apiome.catalog_edges SET last_seen_at = last_seen_at - interval '1 hour' WHERE tenant_id = %s",
        (seed["tenant"],),
    )
    counts = materialize_runtime(db, seed["tenant"])
    assert counts["staled"] == 1
    stale = {e["pointer"]: e["stale_since"] for e in _runtime_edges(cursor, seed["tenant"])}
    assert stale[ORDERS] is not None and stale[GET_PET] is None

    cursor.execute(
        "UPDATE apiome.catalog_edges SET stale_since = stale_since - interval '31 days' "
        "WHERE tenant_id = %s AND pointer = %s",
        (seed["tenant"], ORDERS),
    )
    assert materialize_runtime(db, seed["tenant"])["purged"] == 1
    assert [e["pointer"] for e in _runtime_edges(cursor, seed["tenant"])] == [GET_PET]


def test_unattributed_traffic_draws_no_runtime_edge(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _ingest(db, seed, [_event("/pets/1", user_agent="checkout-web/1")])
    _rollup(cursor)
    assert materialize_runtime(db, seed["tenant"])["current"] == 0


def test_the_usage_sweep_refreshes_runtime_edges(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _bind(graph, "search", {"kind": "user_agent", "name": "search-indexer/*"})
    _ingest(db, seed, [_event("/pets/1", user_agent="search-indexer/3")])
    result = run_usage_sweep(db, finalize_grace=timedelta(hours=6))
    assert result is not None and result.runtime_tenants >= 1
    assert [e["from_id"] for e in _runtime_edges(cursor, seed["tenant"])] == [graph["consumers"]["search"]]


# ---------------------------------------------------------------------------------------------
# Suggested consumers
# ---------------------------------------------------------------------------------------------


def _suggestions(graph: Dict[str, Any]) -> Dict[str, Any]:
    response = graph["client"].get(f"/v1/tenants/t/projects/{graph['seed']['project']}/consumer-suggestions")
    assert response.status_code == 200, response.text
    return response.json()


def _register(graph: Dict[str, Any], suggestion: str, body: Dict[str, Any]) -> Any:
    return graph["client"].post(
        f"/v1/tenants/t/projects/{graph['seed']['project']}/consumer-suggestions/{suggestion}/register", json=body
    )


def test_unattributed_clients_become_suggestions_without_their_hash(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    hint = _hint(graph, "api_key", HINT_VALUE)
    _ingest(
        db,
        seed,
        [_event("/pets/1", user_agent="checkout-web/4.2") for _ in range(3)]
        + [_event("/pets/2", consumer_hint=hint)]
        + [_event("/pets/3", user_agent="ghp_abcdefghijklmnopqrstuvwxyz0123456789/1")],
    )
    cursor.execute(
        "SELECT client_kind, client_key, calls FROM apiome.usage_unattributed_client_daily WHERE tenant_id = %s "
        "ORDER BY client_kind",
        (seed["tenant"],),
    )
    assert [(r["client_kind"], r["client_key"], r["calls"]) for r in cursor.fetchall()] == [
        ("api_key", hint["hmac"], 1),
        ("user_agent", "checkout-web", 3),
    ]

    body = _suggestions(graph)
    assert body["window_days"] == 30
    by_kind = {s["client_kind"]: s for s in body["suggestions"]}
    assert [s["client_kind"] for s in body["suggestions"]] == ["user_agent", "api_key"]
    assert by_kind["user_agent"]["id"] == "ua:checkout-web"
    assert by_kind["user_agent"]["suggested_slug"] == "checkout-web"
    assert by_kind["user_agent"]["calls"] == 3 and by_kind["user_agent"]["needs_binding_name"] is False
    assert by_kind["api_key"]["id"].startswith("api_key:") and by_kind["api_key"]["needs_binding_name"] is True
    text = json.dumps(body)
    assert hint["hmac"] not in text and HINT_VALUE not in text


def test_registering_a_user_agent_suggestion_attributes_the_next_batch(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _ingest(db, seed, [_event("/pets/1", user_agent="checkout-web/4.2")])
    response = _register(graph, "ua:checkout-web", {})
    assert response.status_code == 201, response.text
    registered = response.json()
    assert registered["created_consumer"] is True
    assert registered["consumer"]["slug"] == "checkout-web"
    assert (registered["binding"]["kind"], registered["binding"]["name"]) == ("user_agent", "checkout-web/*")

    assert _suggestions(graph)["suggestions"] == []
    outcome = _ingest(db, seed, [_event("/pets/1", user_agent="checkout-web/4.3")])
    assert outcome.plan.attributed == 1
    _rollup(cursor)
    materialize_runtime(db, seed["tenant"])
    assert [e["from_id"] for e in _runtime_edges(cursor, seed["tenant"])] == [registered["consumer"]["id"]]


def test_registering_a_hashed_suggestion_needs_a_binding_name_and_stores_the_edge_hash(
    graph: Dict[str, Any],
) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    hint = _hint(graph, "api_key", HINT_VALUE)
    _ingest(db, seed, [_event("/pets/2", consumer_hint=hint)])
    sid = _suggestions(graph)["suggestions"][0]["id"]

    missing = _register(graph, sid, {"name": "Partner portal"})
    assert missing.status_code == 400 and missing.json()["detail"]["code"] == "consumer-binding-invalid"
    cursor.execute("SELECT count(*) AS n FROM apiome.consumer WHERE tenant_id = %s", (seed["tenant"],))
    assert cursor.fetchone()["n"] == 2  # nothing was registered by the refusal

    response = _register(graph, sid, {"name": "Partner portal", "slug": "partner-portal", "binding_name": "X-API-Key"})
    assert response.status_code == 201, response.text
    assert hint["hmac"] not in response.text
    binding = response.json()["binding"]
    assert (binding["kind"], binding["name"], binding["hashed"]) == ("api_key", "x-api-key", True)
    cursor.execute("SELECT value_hmac FROM apiome.usage_consumer_binding WHERE id = %s", (binding["id"],))
    assert cursor.fetchone()["value_hmac"] == hint["hmac"]
    assert _ingest(db, seed, [_event("/pets/2", consumer_hint=hint)]).plan.attributed == 1


def test_a_suggestion_can_be_bound_to_an_existing_consumer(graph: Dict[str, Any]) -> None:
    db, seed = graph["db"], graph["seed"]
    _ingest(db, seed, [_event("/pets/1", user_agent="search-crawler/1")])
    response = _register(graph, "ua:search-crawler", {"consumer": "search"})
    assert response.status_code == 201, response.text
    assert response.json()["created_consumer"] is False
    assert response.json()["consumer"]["id"] == graph["consumers"]["search"]


def test_unknown_and_malformed_suggestions_are_404(graph: Dict[str, Any]) -> None:
    for sid in ("ua:nobody", "api_key:" + "0" * 20, "not-an-id", "ua:BAD"):
        response = _register(graph, sid, {})
        assert response.status_code == 404, sid
        assert response.json()["detail"]["code"] == "consumer-suggestion-not-found"


def test_v293_refuses_a_raw_value_as_a_client_key(graph: Dict[str, Any]) -> None:
    cursor, seed = graph["cursor"], graph["seed"]
    for kind, key in (("user_agent", "Bearer abc"), ("api_key", HINT_VALUE), ("header", "Checkout")):
        cursor.execute("SAVEPOINT v293")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                """INSERT INTO apiome.usage_unattributed_client_daily
                       (tenant_id, project_id, day, client_kind, client_key, calls, first_seen_at, last_seen_at)
                   VALUES (%s, %s, %s, %s, %s, 1, %s, %s)""",
                (seed["tenant"], seed["project"], NOW.date(), kind, key, NOW, NOW),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT v293")


def test_unattributed_rows_are_purged_with_the_rollup_retention(graph: Dict[str, Any]) -> None:
    cursor, seed = graph["cursor"], graph["seed"]
    for days_ago in (5, 120):
        cursor.execute(
            """INSERT INTO apiome.usage_unattributed_client_daily
                   (tenant_id, project_id, day, client_kind, client_key, calls, first_seen_at, last_seen_at)
               VALUES (%s, %s, %s, 'user_agent', 'old-client', 1, %s, %s)""",
            (seed["tenant"], seed["project"], NOW.date() - timedelta(days=days_ago), NOW, NOW),
        )
    cursor.execute("SELECT apiome.purge_usage_unattributed(%s, 1000) AS n", (NOW,))
    assert cursor.fetchone()["n"] >= 1
    cursor.execute(
        "SELECT day FROM apiome.usage_unattributed_client_daily WHERE tenant_id = %s", (seed["tenant"],)
    )
    assert [row["day"] for row in cursor.fetchall()] == [NOW.date() - timedelta(days=5)]


def test_the_blast_radius_route_accepts_runtime_only(graph: Dict[str, Any]) -> None:
    db, seed = graph["db"], graph["seed"]
    _billing_traffic(graph)
    materialize_runtime(db, seed["tenant"])
    with patch("app.graph_routes.db", db), patch("app.graph_routes.enforce_permission", return_value=None):
        response = graph["client"].post(
            "/v1/graph/t/blast-radius",
            json={"entity": {"kind": "project", "id": seed["project"]}, "provenance": ["runtime"]},
        )
    assert response.status_code == 200, response.text
    direct = response.json()["direct"]
    assert [(n["kind"], n["provenances"]) for n in direct] == [("consumer", ["runtime"])]


def test_registering_a_client_a_binding_already_recognises_is_refused_first(graph: Dict[str, Any]) -> None:
    db, cursor, seed = graph["db"], graph["cursor"], graph["seed"]
    _ingest(db, seed, [_event("/pets/1", user_agent="checkout-web/1")])
    _bind(graph, "search", {"kind": "user_agent", "name": "checkout-web/*"})
    response = _register(graph, "ua:checkout-web", {})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "consumer-binding-exists"
    cursor.execute("SELECT count(*) AS n FROM apiome.consumer WHERE tenant_id = %s", (seed["tenant"],))
    assert cursor.fetchone()["n"] == 2
