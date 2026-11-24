"""Pact publication against a live Postgres — PFX-1.2 (#6915).

The acceptance criteria only the real schema and the real routes can prove (apiome-db V433):

* publishing registers both pacticipants, records the consumer version, and stores the pact;
* the same pact published for ten consumer versions yields one ``pact_version``;
* a changed pact for an already-published consumer version is a 409 that stores nothing — and is
  a replacement, with a higher revision, where the deployment allows it;
* a bulk publish is all or nothing;
* the pact reads back by version, as latest, and by content address, with HAL links;
* nothing crosses a tenant, and a pact goes when its pacticipant goes.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``). Skipped when no database is reachable or V433 is not applied.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_cleanup_store import delete_pacticipant, purge_deleted
from app.pact_publication import PactPublicationError, prepare_pact
from app.pact_publication_store import get_latest_pact, publish_pacts
from app.pacticipant import PacticipantValidationError
from app.pacticipant_store import get_pacticipant
from tests import test_usage_index_db as index_db

tx = index_db.tx

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
BASE = "/v1/tenants/t/pact-broker"
PAIR = f"{BASE}/pacts/provider/ledger-api/consumer/billing-service"


def _pact(total: int = 1999, **extra: Any) -> Dict[str, Any]:
    """A small v2 pact between Billing Service and Ledger API."""
    return {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "request": {"method": "GET", "path": "/invoices/42"},
                "response": {"status": 200, "body": {"id": 42, "total": total}},
            }
        ],
        "metadata": {"pactSpecification": {"version": "2.0.0"}},
        **extra,
    }


@pytest.fixture
def stack(tx: Tuple[Any, Any]) -> Iterator[Dict[str, Any]]:
    """Two tenants and a client whose broker routes run on ``tx`` as the first."""
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.pact_publication') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V433 not applied")
    seed = index_db._tenant(cursor)
    other = index_db._tenant(cursor)
    auth = {"tenant_id": seed["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_broker_authentication] = lambda: auth
    app.dependency_overrides[validate_authentication] = lambda: auth
    with (
        patch("app.pact_broker_routes.db", db),
        patch("app.pact_broker_routes.enforce_permission", return_value=None),
        patch("app.pacticipant_routes.db", db),
        patch("app.pacticipant_routes.enforce_permission", return_value=None),
    ):
        yield {"db": db, "cursor": cursor, "seed": seed, "other": other, "client": TestClient(app)}
    app.dependency_overrides.clear()


_COUNTS = {
    "pacticipant": "SELECT count(*) AS n FROM apiome.pacticipant WHERE tenant_id = ANY(%s::uuid[])",
    "pact_version": "SELECT count(*) AS n FROM apiome.pact_version WHERE tenant_id = ANY(%s::uuid[])",
    "pact_publication": (
        "SELECT count(*) AS n FROM apiome.pact_publication p "
        "JOIN apiome.pact_version pv ON pv.id = p.pact_version_id WHERE pv.tenant_id = ANY(%s::uuid[])"
    ),
}


def _count(stack: Dict[str, Any], table: str) -> int:
    """Rows of ``table`` owned by the test's two tenants."""
    stack["cursor"].execute(_COUNTS[table], ([stack["seed"]["tenant"], stack["other"]["tenant"]],))
    return int(stack["cursor"].fetchone()["n"])


def _bulk(version: str, *documents: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {
        "pacticipantName": "Billing Service",
        "pacticipantVersionNumber": version,
        "contracts": [
            {
                "consumerName": "Billing Service",
                "providerName": document["provider"]["name"],
                "specification": "pact",
                "contentType": "application/json",
                "content": base64.b64encode(json.dumps(document).encode()).decode(),
            }
            for document in documents
        ],
        **extra,
    }


def test_put_publishes_registers_and_reads_back(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    response = client.put(f"{PAIR}/version/1.0.0", json=_pact())
    assert response.status_code == 201, response.text
    assert response.headers["content-type"].startswith("application/hal+json")
    body = response.json()
    assert body["interactions"] == _pact()["interactions"]
    assert body["metadata"] == _pact()["metadata"]
    assert body["_links"]["self"]["href"].endswith(f"{PAIR}/version/1.0.0")
    sha = body["_links"]["pb:pact-version"]["name"]
    assert len(sha) == 64

    # Both applications are pacticipants now, under the names the pact gave them.
    assert get_pacticipant(stack["db"], stack["seed"]["tenant"], "billing-service").name == "Billing Service"
    assert get_pacticipant(stack["db"], stack["seed"]["tenant"], "Ledger API").slug == "ledger-api"
    versions = client.get("/v1/tenants/t/pacticipants/billing-service/versions").json()["versions"]
    assert [version["number"] for version in versions] == ["1.0.0"]

    for path in (f"{PAIR}/version/1.0.0", f"{PAIR}/latest", f"{PAIR}/pact-version/{sha}"):
        read = client.get(path)
        assert read.status_code == 200, read.text
        assert read.json()["interactions"] == _pact()["interactions"]
        assert read.json()["_links"]["pb:pact-version"]["name"] == sha

    # The same pact again: nothing changes, and it is not a creation.
    again = client.put(f"{PAIR}/version/1.0.0", json=_pact())
    assert again.status_code == 200
    assert _count(stack, "pact_publication") == 1


def test_ten_versions_of_one_pact_share_one_pact_version(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    shas = set()
    for number in range(10):
        # A Pact library stamps its own version in the metadata; that is not a different pact.
        document = _pact(metadata={"pactSpecification": {"version": "2.0.0"}, "pact-js": {"version": f"12.{number}.0"}})
        response = client.post(f"{BASE}/contracts/publish", json=_bulk(f"build-{number}", document, branch="main"))
        assert response.status_code == 200, response.text
        shas.add(response.json()["_links"]["pb:contracts"][0]["pactVersionSha"])
    assert len(shas) == 1
    assert _count(stack, "pact_version") == 1
    assert _count(stack, "pact_publication") == 10
    assert client.get(f"{PAIR}/latest").json()["_links"]["self"]["href"].endswith("/version/build-9")
    branches = client.get("/v1/tenants/t/pacticipants/billing-service/branches").json()["branches"]
    assert [(branch["name"], branch["head_version"]) for branch in branches] == [("main", "build-9")]


def test_changed_content_for_a_published_version_is_a_conflict(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    assert client.put(f"{PAIR}/version/1.0.0", json=_pact()).status_code == 201
    refused = client.put(f"{PAIR}/version/1.0.0", json=_pact(total=5))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "pact-content-conflict"
    assert _count(stack, "pact_version") == 1
    assert client.get(f"{PAIR}/version/1.0.0").json()["interactions"][0]["response"]["body"]["total"] == 1999

    # A new consumer version takes the changed pact.
    assert client.put(f"{PAIR}/version/1.0.1", json=_pact(total=5)).status_code == 201
    assert _count(stack, "pact_version") == 2


def test_modification_can_be_allowed_and_counts_revisions(stack: Dict[str, Any]) -> None:
    db, tenant = stack["db"], stack["seed"]["tenant"]

    def publish(total: int) -> Any:
        pact = prepare_pact(
            json.dumps(_pact(total=total)).encode(),
            consumer_name="Billing Service",
            provider_name="Ledger API",
            max_bytes=10_000,
        )
        return publish_pacts(
            db,
            tenant,
            consumer_name="Billing Service",
            version_number="1.0.0",
            pacts=[pact],
            actor=ACTOR,
            allow_modification=True,
        ).pacts[0]

    first = publish(1)
    assert (first.created, first.replaced, first.new_content, first.pact.revision) == (True, False, True, 1)
    second = publish(2)
    assert (second.created, second.replaced, second.new_content, second.pact.revision) == (False, True, True, 2)
    assert second.pact.content["interactions"][0]["response"]["body"]["total"] == 2
    back = publish(1)
    assert (back.replaced, back.new_content, back.pact.revision) == (True, False, 3)
    assert back.pact.sha == first.pact.sha


def test_a_bulk_publish_is_all_or_nothing(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    other = {**_pact(), "provider": {"name": "Tax API"}}
    assert client.post(f"{BASE}/contracts/publish", json=_bulk("1", _pact())).status_code == 200

    # Version 2 carries a new pact for Tax API and — wrongly — version 1 is republished changed.
    changed = _pact(total=7)
    refused = client.post(f"{BASE}/contracts/publish", json=_bulk("1", other, changed, tags=["rc"]))
    assert refused.status_code == 409, refused.text
    with pytest.raises(PacticipantValidationError):
        get_pacticipant(stack["db"], stack["seed"]["tenant"], "tax-api")
    version = client.get("/v1/tenants/t/pacticipants/billing-service/versions/1").json()
    assert version["tags"] == []
    assert _count(stack, "pact_publication") == 1

    accepted = client.post(f"{BASE}/contracts/publish", json=_bulk("2", other, changed, tags=["rc"], branch="main"))
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert len(body["_links"]["pb:contracts"]) == 2
    version = body["_embedded"]["version"]
    assert (version["number"], version["buildUrl"]) == ("2", None)
    assert version["_embedded"] == {"branchVersions": [{"name": "main"}], "tags": [{"name": "rc"}]}
    assert any("Tax API" in notice["text"] for notice in body["notices"])


def test_message_and_v4_pacts_are_stored_as_published(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    message_pact = {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "messages": [{"description": "an invoice was paid", "contents": {"id": 42}}],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }
    v4 = {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {"type": "Asynchronous/Messages", "description": "paid", "contents": {"content": {"id": 1}}},
            {
                "type": "Synchronous/HTTP",
                "description": "get",
                "request": {"method": "GET", "path": "/x"},
                "response": {"status": 200},
            },
        ],
        "metadata": {"pactSpecification": {"version": "4.0"}},
    }
    assert client.put(f"{PAIR}/version/m1", json=message_pact).status_code == 201
    assert client.put(f"{PAIR}/version/v4", json=v4).status_code == 201
    assert client.get(f"{PAIR}/version/m1").json()["messages"] == message_pact["messages"]
    assert client.get(f"{PAIR}/version/v4").json()["interactions"] == v4["interactions"]
    stack["cursor"].execute(
        "SELECT specification_version, interaction_count FROM apiome.pact_version "
        "WHERE tenant_id = %s::uuid ORDER BY specification_version",
        (stack["seed"]["tenant"],),
    )
    assert [tuple(row.values()) for row in stack["cursor"].fetchall()] == [("3.0.0", 1), ("4.0", 2)]


def test_an_invalid_pact_is_located_and_stores_nothing(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    broken = _pact()
    broken["interactions"][0]["request"].pop("method")
    refused = client.put(f"{PAIR}/version/1.0.0", json=broken)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["pointer"] == "/interactions/0/request/method"
    assert _count(stack, "pacticipant") == 0


def test_nothing_crosses_a_tenant(stack: Dict[str, Any]) -> None:
    db, client = stack["db"], stack["client"]
    assert client.put(f"{PAIR}/version/1.0.0", json=_pact()).status_code == 201
    with pytest.raises(PacticipantValidationError):
        get_latest_pact(db, stack["other"]["tenant"], "ledger-api", "billing-service")

    # The other tenant publishes the same names: its own pacticipants, its own pact version.
    pact = prepare_pact(
        json.dumps(_pact()).encode(), consumer_name="Billing Service", provider_name="Ledger API", max_bytes=10_000
    )
    publish_pacts(
        db, stack["other"]["tenant"], consumer_name="Billing Service", version_number="1.0.0", pacts=[pact], actor=ACTOR
    )
    assert _count(stack, "pact_version") == 2
    assert _count(stack, "pacticipant") == 4


def test_deleting_a_pacticipant_hides_its_pacts_and_the_purge_removes_them(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    tenant = stack["seed"]["tenant"]
    assert client.put(f"{PAIR}/version/1.0.0", json=_pact()).status_code == 201
    delete_pacticipant(stack["db"], tenant, get_pacticipant(stack["db"], tenant, "ledger-api"), actor=ACTOR)
    # Soft (PFX-1.11): hidden at once, still stored until the grace period has passed.
    assert client.get(f"{PAIR}/latest").status_code == 404
    assert _count(stack, "pact_publication") == 1
    later = datetime.now(timezone.utc) + timedelta(days=365)
    assert purge_deleted(stack["db"], now=later)["pacticipants"] >= 1
    assert _count(stack, "pact_version") == 0
    assert _count(stack, "pact_publication") == 0


def test_unknown_pacts_are_404(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    assert client.get(f"{PAIR}/latest").json()["detail"]["code"] == "pacticipant-not-found"
    assert client.put(f"{PAIR}/version/1.0.0", json=_pact()).status_code == 201
    missing = client.get(f"{PAIR}/version/9.9.9")
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "pact-not-found")
    assert client.get(f"{PAIR}/pact-version/{'0' * 64}").status_code == 404


def test_conflict_error_is_raised_by_the_store(stack: Dict[str, Any]) -> None:
    db, tenant = stack["db"], stack["seed"]["tenant"]

    def pact(total: int) -> Any:
        return prepare_pact(
            json.dumps(_pact(total=total)).encode(),
            consumer_name="Billing Service",
            provider_name="Ledger API",
            max_bytes=10_000,
        )

    publish_pacts(db, tenant, consumer_name="Billing Service", version_number="1", pacts=[pact(1)], actor=ACTOR)
    with pytest.raises(PactPublicationError) as refused:
        publish_pacts(db, tenant, consumer_name="Billing Service", version_number="1", pacts=[pact(2)], actor=ACTOR)
    assert refused.value.code == "pact-content-conflict"


def test_a_document_the_database_cannot_hold_is_refused_not_a_500(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    document = _pact()
    document["interactions"][0]["response"]["body"]["note"] = "nul\x00byte"
    refused = client.put(f"{PAIR}/version/1.0.0", json=document)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "pact-invalid"
    assert _count(stack, "pacticipant") == 0
