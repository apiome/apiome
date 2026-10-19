"""Consumer bindings and runtime edges against a live Postgres — RDG-1.8 (#5765).

The acceptance criteria only the real schema, the real ingest and the real routes can prove:

* **no table or response ever renders a bound value** — a sweep over every row of every
  ``apiome`` table carrying the tenant, and over every response the binding routes return;
* two bindings for the same consumer (an API key and a user agent) attribute to one consumer;
* an ``undeclared`` consumer with traffic shows ``used_undeclared`` operations;
* deleting a binding stops attribution on the next batch and leaves history attributed as it was;
* the V292 constraints: one live value per tenant, kind and name, no raw value in ``value_hmac``,
  and the reserved ``anonymous`` handle.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``, via the ``seeded`` fixture of ``test_usage_ingest_db``). Skipped when no
database is reachable or V292 is not applied.
"""

from __future__ import annotations

import base64
import json
import uuid
from contextlib import ExitStack
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.config import settings
from app.consumer_binding import consumer_hint_hmac
from app.main import app
from tests import test_usage_ingest_db as ingest_db

tx = ingest_db.tx
seeded = ingest_db.seeded
NOW = ingest_db.NOW
_event = ingest_db._event
_ingest = ingest_db._ingest

pytestmark = pytest.mark.requires_db

HEADER_VALUE = "hdr-Billing-Client-7f3a9c"
API_KEY_VALUE = "ak_live_9d8c7b6a5f4e3d2c1b0a"
CLAIM_VALUE = "billing-service-azp-claim-42"
RAW_VALUES = (HEADER_VALUE, API_KEY_VALUE, CLAIM_VALUE)

GET_PET = "/paths/~1pets~1{petId}/get"
ORDERS = "/paths/~1users~1{userId}~1orders/get"


@pytest.fixture
def stack(seeded: Tuple[Any, Any, Dict[str, str]], monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """The seeded tenant plus two consumers, a key map, and a client whose routes run on ``tx``."""
    db, cursor, seed = seeded
    cursor.execute("SELECT to_regclass('apiome.usage_consumer_binding') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V292 not applied")
    monkeypatch.setattr(
        settings, "linked_account_token_encryption_keys", json.dumps({"1": base64.b64encode(bytes(32)).decode()})
    )
    monkeypatch.setattr(settings, "linked_account_token_active_key_version", None)
    consumers = {}
    for slug in ("billing-service", "search"):
        cursor.execute(
            """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
               VALUES (%s, %s, %s, %s) RETURNING id::text AS id""",
            (seed["tenant"], seed["project"], slug, slug.title()),
        )
        consumers[slug] = cursor.fetchone()["id"]

    auth = {"tenant_id": seed["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_authentication] = lambda: auth
    with ExitStack() as patches:
        for target in (
            "app.consumer_binding_routes.db",
            "app.consumer_contract_store.db",
            "app.consumer_contract_routes.db",
        ):
            patches.enter_context(patch(target, db))
        for target in (
            "app.consumer_binding_routes.enforce_permission",
            "app.consumer_contract_routes.enforce_permission",
        ):
            patches.enter_context(patch(target, return_value=None))
        yield {
            "db": db,
            "cursor": cursor,
            "seed": seed,
            "consumers": consumers,
            "client": TestClient(app),
            "base": f"/v1/tenants/t/projects/{seed['project']}/consumers",
        }
    app.dependency_overrides.clear()


def _bind(stack: Dict[str, Any], slug: str, body: Dict[str, Any]) -> Dict[str, Any]:
    response = stack["client"].post(f"{stack['base']}/{slug}/bindings", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _hint(stack: Dict[str, Any], kind: str, value: str) -> Dict[str, str]:
    return {"kind": kind, "hmac": consumer_hint_hmac(stack["seed"]["tenant"], value)[0]}


def _rollup(cursor: Any) -> None:
    cursor.execute("SELECT apiome.rollup_usage_days(%s, %s::interval)", (NOW, "6 hours"))


def _runtime(stack: Dict[str, Any], slug: str) -> Dict[str, Any]:
    response = stack["client"].get(f"{stack['base']}/{slug}/runtime")
    assert response.status_code == 200, response.text
    return response.json()


def _calls(report: Dict[str, Any], side: str) -> Dict[str, int]:
    return {op["operation_key"]: op["calls"] for op in report[side]}


# ---------------------------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------------------------


def test_no_table_or_response_ever_renders_a_bound_value(stack: Dict[str, Any]) -> None:
    db, cursor, seed = stack["db"], stack["cursor"], stack["seed"]
    responses: List[str] = []
    for kind, name, value in (
        ("header", "X-Client-Id", HEADER_VALUE),
        ("api_key", "x-api-key", API_KEY_VALUE),
        ("jwt_claim", "azp", CLAIM_VALUE),
    ):
        created = _bind(stack, "billing-service", {"kind": kind, "name": name, "value": value})
        responses.append(json.dumps(created))
        assert created["hashed"] is True and "value" not in created and "value_hmac" not in created
    _bind(stack, "billing-service", {"kind": "user_agent", "name": "billing-service/*"})

    events = [_event("/pets/1", consumer_hint=_hint(stack, kind, value)) for kind, value in (
        ("header", HEADER_VALUE), ("api_key", API_KEY_VALUE), ("jwt_claim", CLAIM_VALUE)
    )]
    outcome = _ingest(db, seed, events + [_event("/pets/2", user_agent="billing-service/1.0")])
    assert outcome.plan.attributed == 4
    _rollup(cursor)

    client, base = stack["client"], stack["base"]
    for url in (
        f"{base}/billing-service/bindings?include_deleted=true",
        f"{base}/billing-service/runtime",
        f"{base}/anonymous/runtime",
        base,
        f"{base}/billing-service",
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
        responses.append(response.text)

    cursor.execute(
        """SELECT table_name FROM information_schema.columns
           WHERE table_schema = 'apiome' AND column_name = 'tenant_id'
             AND table_name IN (SELECT table_name FROM information_schema.tables
                                WHERE table_schema = 'apiome' AND table_type = 'BASE TABLE')"""
    )
    tables = sorted({row["table_name"] for row in cursor.fetchall()})
    assert "usage_consumer_binding" in tables and "usage_hourly" in tables
    scanned = 0
    for table in tables:
        cursor.execute(
            f"SELECT row_to_json(t)::text AS row FROM apiome.{table} t WHERE tenant_id = %s", (seed["tenant"],)
        )
        for row in cursor.fetchall():
            scanned += 1
            for value in RAW_VALUES:
                assert value not in row["row"], (table, value)
    assert scanned > 0
    for text in responses:
        for value in RAW_VALUES:
            assert value not in text
    # Not even the hash is ever returned.
    cursor.execute("SELECT value_hmac FROM apiome.usage_consumer_binding WHERE tenant_id = %s", (seed["tenant"],))
    hashes = [row["value_hmac"] for row in cursor.fetchall() if row["value_hmac"]]
    assert len(hashes) == 3
    for text in responses:
        for digest in hashes:
            assert digest not in text


# ---------------------------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------------------------


def test_a_key_and_a_user_agent_attribute_to_one_consumer(stack: Dict[str, Any]) -> None:
    db, cursor, seed = stack["db"], stack["cursor"], stack["seed"]
    _bind(stack, "billing-service", {"kind": "api_key", "name": "x-api-key", "value": API_KEY_VALUE})
    _bind(stack, "billing-service", {"kind": "user_agent", "name": "billing-service/*"})
    _ingest(
        db,
        seed,
        [_event("/pets/1", consumer_hint=_hint(stack, "api_key", API_KEY_VALUE)) for _ in range(3)]
        + [_event("/pets/2", user_agent="Billing-Service/4.2") for _ in range(2)]
        + [_event("/pets/3", user_agent="curl/8.0")],
    )
    _rollup(cursor)
    cursor.execute(
        "SELECT count(DISTINCT consumer_binding_id) AS n FROM apiome.usage_hourly WHERE tenant_id = %s "
        "AND consumer_binding_id IS NOT NULL",
        (seed["tenant"],),
    )
    assert cursor.fetchone()["n"] == 2

    report = _runtime(stack, "billing-service")
    assert report["contract_state"] == "undeclared"
    assert _calls(report, "used_undeclared") == {GET_PET: 5}
    assert _calls(_runtime(stack, "anonymous"), "used_undeclared") == {GET_PET: 1}

    cursor.execute(
        "SELECT runtime_last_seen_at FROM apiome.consumer WHERE id = %s", (stack["consumers"]["billing-service"],)
    )
    assert cursor.fetchone()["runtime_last_seen_at"] == NOW
    cursor.execute(
        "SELECT count(*) AS n FROM apiome.usage_consumer_binding WHERE tenant_id = %s AND last_matched_at = %s",
        (seed["tenant"], NOW),
    )
    assert cursor.fetchone()["n"] == 2


def test_an_undeclared_consumer_with_traffic_shows_used_undeclared_and_the_list_counts_it(
    stack: Dict[str, Any],
) -> None:
    db, cursor, seed = stack["db"], stack["cursor"], stack["seed"]
    _bind(stack, "search", {"kind": "header", "name": "x-client-id", "value": HEADER_VALUE})
    hint = _hint(stack, "header", HEADER_VALUE)
    _ingest(db, seed, [_event("/pets/9", consumer_hint=hint), _event("/users/5/orders", consumer_hint=hint)])
    _rollup(cursor)

    report = _runtime(stack, "search")
    assert report["contract_state"] == "undeclared"
    assert _calls(report, "used_undeclared") == {GET_PET: 1, ORDERS: 1}
    assert report["declared_and_used"] == [] and report["declared_unused"] == []

    listing = stack["client"].get(stack["base"]).json()
    rows = {row["consumer"]["slug"]: row for row in listing["consumers"]}
    assert rows["search"]["runtime"]["used_undeclared"] == 2
    assert rows["search"]["consumer"]["runtime_last_seen_at"] is not None
    assert rows["billing-service"]["runtime"]["calls"] == 0


def test_deleting_a_binding_stops_attribution_and_keeps_history(stack: Dict[str, Any]) -> None:
    db, cursor, seed = stack["db"], stack["cursor"], stack["seed"]
    binding = _bind(stack, "billing-service", {"kind": "header", "name": "x-client-id", "value": HEADER_VALUE})
    hint = _hint(stack, "header", HEADER_VALUE)
    _ingest(db, seed, [_event("/pets/1", consumer_hint=hint) for _ in range(4)])

    deleted = stack["client"].delete(f"{stack['base']}/billing-service/bindings/{binding['id']}")
    assert deleted.status_code == 204
    again = stack["client"].delete(f"{stack['base']}/billing-service/bindings/{binding['id']}")
    assert again.status_code == 404

    outcome = _ingest(db, seed, [_event("/pets/1", consumer_hint=hint) for _ in range(3)])
    assert outcome.plan.attributed == 0
    _rollup(cursor)

    assert _calls(_runtime(stack, "billing-service"), "used_undeclared") == {GET_PET: 4}
    assert _calls(_runtime(stack, "anonymous"), "used_undeclared") == {GET_PET: 3}
    live = stack["client"].get(f"{stack['base']}/billing-service/bindings").json()
    assert live["count"] == 0
    kept = stack["client"].get(f"{stack['base']}/billing-service/bindings?include_deleted=true").json()
    assert kept["count"] == 1 and kept["bindings"][0]["deleted_at"] is not None

    # The value can be bound again once the old binding is deleted.
    _bind(stack, "search", {"kind": "header", "name": "x-client-id", "value": HEADER_VALUE})


def test_a_declared_contract_splits_into_used_and_unused(stack: Dict[str, Any]) -> None:
    db, cursor, seed = stack["db"], stack["cursor"], stack["seed"]
    consumer = stack["consumers"]["billing-service"]
    surface = {
        "schema_version": "apiome.consumer.contract/v1",
        "operations": [
            {"method": "get", "path": "/pets/{petId}", "pointer": GET_PET, "fields": []},
            {"method": "get", "path": "/users/{userId}/orders", "pointer": ORDERS, "fields": []},
        ],
    }
    cursor.execute(
        """INSERT INTO apiome.consumer_contract (tenant_id, project_id, consumer_id, revision, source, surface,
                                                  operation_count, surface_pointers)
           VALUES (%s, %s, %s, 1, 'manual', %s, 2, %s)""",
        (seed["tenant"], seed["project"], consumer, json.dumps(surface), [GET_PET, ORDERS]),
    )
    _bind(stack, "billing-service", {"kind": "user_agent", "name": "billing-service/*"})
    _ingest(db, seed, [_event("/pets/1", user_agent="billing-service/1")])
    _rollup(cursor)
    report = _runtime(stack, "billing-service")
    assert report["contract_state"] == "declared"
    assert _calls(report, "declared_and_used") == {GET_PET: 1}
    assert [op["operation_key"] for op in report["declared_unused"]] == [ORDERS]
    assert report["used_undeclared"] == []


# ---------------------------------------------------------------------------------------------
# Refusals and constraints
# ---------------------------------------------------------------------------------------------


def test_one_value_identifies_one_consumer_per_tenant(stack: Dict[str, Any]) -> None:
    _bind(stack, "billing-service", {"kind": "header", "name": "x-client-id", "value": HEADER_VALUE})
    clash = stack["client"].post(
        f"{stack['base']}/search/bindings", json={"kind": "header", "name": "X-CLIENT-ID", "value": HEADER_VALUE}
    )
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "consumer-binding-exists"
    assert HEADER_VALUE not in clash.text
    # The same value under another header name is a different binding.
    _bind(stack, "search", {"kind": "header", "name": "x-team", "value": HEADER_VALUE})


def test_bad_bindings_and_unknown_consumers_are_refused(stack: Dict[str, Any]) -> None:
    client, base = stack["client"], stack["base"]
    broad = client.post(f"{base}/search/bindings", json={"kind": "user_agent", "name": "*"})
    assert broad.status_code == 400 and broad.json()["detail"]["code"] == "consumer-binding-invalid"
    missing = client.post(f"{base}/search/bindings", json={"kind": "header", "name": "x-client-id"})
    assert missing.status_code == 422
    unknown = client.get(f"{base}/nobody/bindings")
    assert unknown.status_code == 404
    bogus = client.delete(f"{base}/search/bindings/not-a-uuid")
    assert bogus.status_code == 404


def test_a_binding_without_a_key_map_is_refused_with_503(
    stack: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "linked_account_token_encryption_keys", None)
    response = stack["client"].post(
        f"{stack['base']}/search/bindings", json={"kind": "header", "name": "x-client-id", "value": HEADER_VALUE}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "consumer-binding-key-unavailable"


def test_v292_refuses_a_raw_value_and_the_anonymous_handle(stack: Dict[str, Any]) -> None:
    cursor, seed = stack["cursor"], stack["seed"]
    consumer = stack["consumers"]["search"]
    for value_hmac, key_version in ((HEADER_VALUE, 1), (None, None), ("a" * 64, None)):
        cursor.execute("SAVEPOINT v292")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                """INSERT INTO apiome.usage_consumer_binding
                       (tenant_id, project_id, consumer_id, kind, name, value_hmac, key_version)
                   VALUES (%s, %s, %s, 'header', 'x-client-id', %s, %s)""",
                (seed["tenant"], seed["project"], consumer, value_hmac, key_version),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT v292")
    cursor.execute("SAVEPOINT v292")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO apiome.consumer (tenant_id, project_id, slug, name) VALUES (%s, %s, 'anonymous', 'A')",
            (seed["tenant"], seed["project"]),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT v292")
    reserved = stack["client"].post(stack["base"], json={"name": "Anonymous", "slug": "anonymous"})
    assert reserved.status_code == 409 and reserved.json()["detail"]["code"] == "consumer-slug-reserved"
    assert uuid.UUID(consumer)
