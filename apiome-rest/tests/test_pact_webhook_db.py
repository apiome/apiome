"""Contract webhooks against a live Postgres — PFX-1.9 (#6922).

What only the real schema and the real routes prove (apiome-db V436):

* ``pact-broker create-webhook`` and ``create-or-update-webhook`` work unmodified: they follow the
  index's ``pb:webhooks`` / ``pb:webhook`` links;
* secrets are stored only as ciphertext, read back redacted, kept by ``**********`` and removed
  when left out; without a key a webhook that carries one is refused, and one that does not is not;
* **a published pact fires ``contract_requiring_verification_published`` once per provider
  version that has to verify it** — the main-branch head and what is deployed — each firing
  carrying that version's branch; publishing the same pact again fires nothing; a version that has
  verified the content is skipped;
* ``contract_content_changed`` compares with the previous pact on the same branch;
  ``consumer_version_branch_created`` fires for a new branch;
* a verification result fires the three verification events with its outcome;
* a webhook fires only for its consumer and provider, and only while enabled;
* **a failed delivery is retried and then dead-lettered** by the shared push-webhook worker, and
  the execution log of every attempt can be read back — without the secret;
* nothing crosses a tenant; deleting a webhook removes its deliveries and its history.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V436 is not applied.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.consumer_contract_store import ConsumerActor
from app.pact_publication import PactPublicationError
from app.pact_webhook import CODE_WEBHOOK_NOT_FOUND, REDACTED, parse_webhook_request
from app.pact_webhook_store import create_webhook, get_webhook, list_webhooks
from app.push_webhook_delivery import MAX_DELIVERY_ATTEMPTS, deliver_one_due_event
from tests import test_pact_environment_db as environment_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PAIR = publication_db.PAIR
_path = environment_db._path

_TOKEN = "ci-token-0123456789-secret"
_SIGNING = "signing-secret-0123456789"
_REQUIRING = "contract_requiring_verification_published"


@pytest.fixture
def broker(stack: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """The publication stack with the webhook, verification and environment routes on its transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.pact_webhook') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V436 not applied")
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    # example.com hosts do not have to resolve for a webhook to be saved in a test.
    monkeypatch.setattr("app.pact_webhook.validate_host", lambda _host: None)
    modules = ("pact_broker_webhook_routes", "pact_broker_verification_routes", "pact_broker_environment_routes")
    patches = [patch(f"app.{module}.db", stack["db"]) for module in modules]
    patches += [patch(f"app.{module}.enforce_permission", return_value=None) for module in modules]
    for started in patches:
        started.start()
    try:
        yield stack
    finally:
        for started in patches:
            started.stop()


def _index(broker: Dict[str, Any]) -> Dict[str, Any]:
    return broker["client"].get(BASE).json()["_links"]


def _webhook_body(*events: str, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "description": "Verify the provider",
        "events": [{"name": name} for name in (events or (_REQUIRING,))],
        "request": {
            "method": "POST",
            "url": "https://ci.example.com/hooks/verify?provider=${pactbroker.providerName}",
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {_TOKEN}"},
            "body": {
                "pactUrl": "${pactbroker.pactUrl}",
                "providerVersion": "${pactbroker.providerVersionNumber}",
                "providerBranch": "${pactbroker.providerVersionBranch}",
            },
        },
        "signingSecret": _SIGNING,
    }
    body.update(overrides)
    return body


def _create(broker: Dict[str, Any], *events: str, **overrides: Any) -> Dict[str, Any]:
    """``pact-broker create-webhook``: post to the index's ``pb:webhooks``."""
    target = _path(_index(broker)["pb:webhooks"]["href"])
    response = broker["client"].post(target, json=_webhook_body(*events, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _publish(broker: Dict[str, Any], version: str, total: int = 1999, **extra: Any) -> None:
    response = broker["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk(version, publication_db._pact(total), **extra)
    )
    assert response.status_code == 200, response.text


def _provider_version(broker: Dict[str, Any], number: str, branch: str) -> None:
    response = broker["client"].put(f"{BASE}/pacticipants/ledger-api/branches/{branch}/versions/{number}", json={})
    assert response.status_code in (200, 201), response.text


def _firings(broker: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every firing of the test's tenant, oldest first, with its queued parameters."""
    broker["cursor"].execute(
        """
        SELECT t.id::text AS id, t.event_name, t.consumer_version_number, t.verification_number,
               t.webhook_id::text AS webhook_id, e.id::text AS delivery_event_id, e.status::text AS status,
               e.event_type, e.payload
        FROM apiome.pact_triggered_webhook t
        JOIN apiome.push_webhook_delivery_events e ON e.id = t.delivery_event_id
        WHERE t.tenant_id = %s::uuid
        ORDER BY t.created_at, e.created_at, t.event_name
        """,
        (broker["seed"]["tenant"],),
    )
    return [dict(row) for row in broker["cursor"].fetchall()]


def _events(broker: Dict[str, Any]) -> List[str]:
    return sorted(firing["event_name"] for firing in _firings(broker))


def _sha(broker: Dict[str, Any], version: str) -> str:
    return broker["client"].get(f"{PAIR}/version/{version}").json()["_links"]["pb:pact-version"]["name"]


@pytest.fixture
def integration(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Service 1.0.0 (main) has a pact with Ledger API, whose main branch is at ``p1``.

    Ledger API ``p0``, from ``release/1``, is deployed to production.
    """
    _publish(broker, "1.0.0", branch="main")
    _provider_version(broker, "p0", "release/1")
    _provider_version(broker, "p1", "main")
    environment_db._create_environment(broker, "production", production=True)
    deployed = environment_db._record(broker, "pb:record-deployment", "ledger-api", "p0", "production")
    assert deployed.status_code == 201, deployed.text
    return broker


# --- CRUD and secrets ----------------------------------------------------------------------------


def test_a_webhook_is_created_read_listed_replaced_and_deleted(broker: Dict[str, Any]) -> None:
    _publish(broker, "1.0.0")
    client = broker["client"]
    created = _create(broker, provider={"name": "Ledger API"})
    assert created["description"] == "Verify the provider" and created["enabled"] is True
    assert created["provider"] == {"name": "Ledger API"} and "consumer" not in created
    assert created["events"] == [{"name": _REQUIRING}] and created["signed"] is True
    # Secrets read back redacted — and nowhere in the response.
    assert created["request"]["headers"] == {"Content-Type": "application/json", "Authorization": REDACTED}
    assert _TOKEN not in json.dumps(created) and _SIGNING not in json.dumps(created)
    self_path = _path(created["_links"]["self"]["href"])
    assert self_path == f"{BASE}/webhooks/{created['uuid']}"
    assert created["_links"]["pb:provider"]["href"].endswith("/pacticipants/ledger-api")

    assert client.get(self_path).json()["uuid"] == created["uuid"]
    listing = client.get(f"{BASE}/webhooks").json()
    assert [link["name"] for link in listing["_links"]["pb:webhooks"]] == ["Verify the provider"]
    assert listing["_links"]["pb:webhooks"][0]["title"] == "A webhook for all pacts with provider Ledger API"
    # The scoped collections list exactly their scope.
    assert len(client.get(f"{BASE}/webhooks/provider/ledger-api").json()["_embedded"]["webhooks"]) == 1
    assert client.get(f"{BASE}/webhooks/provider/ledger-api/consumer/billing-service").json()["_embedded"] == {
        "webhooks": []
    }

    # Only ciphertext is stored.
    broker["cursor"].execute(
        "SELECT secret_ciphertext, key_version, secret_fields, request_headers::text AS headers "
        "FROM apiome.pact_webhook WHERE id = %s::uuid",
        (created["uuid"],),
    )
    row = broker["cursor"].fetchone()
    assert row["key_version"] == 1 and sorted(row["secret_fields"]) == ["header:Authorization", "signingSecret"]
    assert _TOKEN.encode() not in bytes(row["secret_ciphertext"]) and _TOKEN not in row["headers"]
    assert bytes(row["secret_ciphertext"]).startswith(b"OPWH")

    # Sending ********** back keeps a secret; leaving one out removes it.
    body = _webhook_body("contract_published", enabled=False)
    body["request"]["headers"]["Authorization"] = REDACTED
    del body["signingSecret"]
    replaced = client.put(self_path, json=body)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["signed"] is False and replaced.json()["enabled"] is False
    assert replaced.json()["events"] == [{"name": "contract_published"}] and "provider" not in replaced.json()
    assert replaced.json()["request"]["headers"]["Authorization"] == REDACTED

    assert client.delete(self_path).status_code == 204
    assert client.get(self_path).status_code == 404
    assert client.delete(self_path).json()["detail"]["code"] == CODE_WEBHOOK_NOT_FOUND


def test_create_or_update_with_a_uuid_creates_then_replaces(broker: Dict[str, Any]) -> None:
    """``pact-broker create-or-update-webhook --uuid``: PUT to the index's ``pb:webhook``."""
    chosen = str(uuid.uuid4())
    target = _path(_index(broker)["pb:webhook"]["href"]).replace("{uuid}", chosen)
    first = broker["client"].put(target, json=_webhook_body())
    assert first.status_code == 201, first.text
    assert first.json()["uuid"] == chosen
    second = broker["client"].put(target, json=_webhook_body(description="Renamed"))
    assert second.status_code == 200 and second.json()["description"] == "Renamed"
    assert len(list_webhooks(broker["db"], broker["seed"]["tenant"])) == 1


def test_a_webhook_for_a_pair_is_created_on_the_pair_route(broker: Dict[str, Any]) -> None:
    """``pact-broker create-webhook --consumer … --provider …`` posts to the pair's collection."""
    _publish(broker, "1.0.0")
    response = broker["client"].post(
        f"{BASE}/webhooks/provider/Ledger%20API/consumer/Billing%20Service", json=_webhook_body()
    )
    assert response.status_code == 201, response.text
    assert response.json()["consumer"] == {"name": "Billing Service"}
    assert response.json()["_links"]["pb:pact-webhooks"]["href"].endswith(
        "/webhooks/provider/ledger-api/consumer/billing-service"
    )
    assert len(broker["client"].get(f"{PAIR}/webhooks").json()["_links"]["pb:webhooks"]) == 1


def test_bad_webhooks_are_refused(broker: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    client = broker["client"]
    unknown = client.post(f"{BASE}/webhooks", json=_webhook_body(provider={"name": "No Such API"}))
    assert unknown.status_code == 422 and unknown.json()["detail"]["pointer"] == "/provider/name"
    kept = _webhook_body()
    kept["request"]["headers"]["Authorization"] = REDACTED
    nothing_stored = client.post(f"{BASE}/webhooks", json=kept)
    assert nothing_stored.status_code == 422
    assert nothing_stored.json()["detail"]["pointer"] == "/request/headers/Authorization"
    assert client.get(f"{BASE}/webhooks/not-a-uuid").status_code == 404
    assert client.get(f"{BASE}/webhooks/provider/no-such-api").status_code == 404

    # Without a key, a secret cannot be sealed — and is not stored unsealed.
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    refused = client.post(f"{BASE}/webhooks", json=_webhook_body())
    assert refused.status_code == 503, refused.text
    assert "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS" in refused.json()["detail"]["message"]
    assert list_webhooks(broker["db"], broker["seed"]["tenant"]) == []
    plain = {"request": {"method": "POST", "url": "https://ci.example.com/hook"}}
    assert client.post(f"{BASE}/webhooks", json=plain).status_code == 201


def test_a_workspace_has_a_webhook_limit(broker: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.pact_webhook_store.MAX_WEBHOOKS_PER_TENANT", 2)
    plain = {"request": {"method": "POST", "url": "https://ci.example.com/hook"}}
    assert [broker["client"].post(f"{BASE}/webhooks", json=plain).status_code for _ in range(3)] == [201, 201, 409]
    refused = broker["client"].post(f"{BASE}/webhooks", json=plain)
    assert refused.json()["detail"]["code"] == "pact-webhook-limit-reached"
    assert len(list_webhooks(broker["db"], broker["seed"]["tenant"])) == 2


def test_a_webhook_is_invisible_to_another_tenant(broker: Dict[str, Any]) -> None:
    created = _create(broker)
    other = broker["other"]["tenant"]
    assert list_webhooks(broker["db"], other) == []
    with pytest.raises(PactPublicationError) as caught:
        get_webhook(broker["db"], other, created["uuid"])
    assert caught.value.code == CODE_WEBHOOK_NOT_FOUND
    # Nor can another tenant take the id over.
    body = {"request": {"method": "POST", "url": "https://x.example.com/"}}
    webhook = parse_webhook_request(json.dumps(body).encode())
    with pytest.raises(PactPublicationError):
        create_webhook(broker["db"], other, webhook, actor=ConsumerActor(), webhook_id=created["uuid"])


# --- Publication events --------------------------------------------------------------------------


def test_a_published_pact_fires_requiring_verification_once_per_provider_branch(integration: Dict[str, Any]) -> None:
    _create(integration, _REQUIRING)
    _publish(integration, "2.0.0", total=2500, branch="main")

    firings = _firings(integration)
    assert [firing["event_name"] for firing in firings] == [_REQUIRING, _REQUIRING]
    assert {firing["event_type"] for firing in firings} == {f"pact.{_REQUIRING}"}
    by_version = {firing["payload"]["parameters"]["pactbroker.providerVersionNumber"]: firing for firing in firings}
    assert set(by_version) == {"p0", "p1"}
    main = by_version["p1"]["payload"]["parameters"]
    assert main["pactbroker.providerVersionBranch"] == "main"
    assert main["pactbroker.providerVersionDescriptions"] == "latest from main branch"
    assert main["pactbroker.githubVerificationStatus"] == "pending"
    deployed = by_version["p0"]["payload"]["parameters"]
    assert deployed["pactbroker.providerVersionBranch"] == "release/1"
    assert deployed["pactbroker.providerVersionDescriptions"] == "deployed in production"
    for parameters in (main, deployed):
        assert parameters["pactbroker.consumerName"] == "Billing Service"
        assert parameters["pactbroker.providerName"] == "Ledger API"
        assert parameters["pactbroker.consumerVersionNumber"] == "2.0.0"
        assert parameters["pactbroker.consumerVersionBranch"] == "main"
        assert parameters["pactbroker.eventName"] == _REQUIRING
        # The pact URL is fetchable and is the published pact.
        fetched = integration["client"].get(_path(parameters["pactbroker.pactUrl"]))
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["interactions"][0]["response"]["body"]["total"] == 2500
    # No secret is queued with a firing.
    assert _TOKEN not in json.dumps([firing["payload"] for firing in firings])

    # Publishing the same pact for the same version again fires nothing.
    _publish(integration, "2.0.0", total=2500, branch="main")
    assert len(_firings(integration)) == 2


def test_a_version_on_both_lists_fires_once_and_a_verified_one_is_skipped(integration: Dict[str, Any]) -> None:
    # p1 is now deployed as well: still one firing for it, with both reasons.
    deployed = environment_db._record(integration, "pb:record-deployment", "ledger-api", "p1", "production")
    assert deployed.status_code == 201, deployed.text
    _create(integration, _REQUIRING)
    _publish(integration, "2.0.0", total=2500, branch="main")
    firings = _firings(integration)
    assert len(firings) == 1
    parameters = firings[0]["payload"]["parameters"]
    assert parameters["pactbroker.providerVersionNumber"] == "p1"
    assert parameters["pactbroker.providerVersionDescriptions"] == "deployed in production, latest from main branch"
    assert parameters["pactbroker.providerVersionBranch"] == "main"

    # p1 verifies that content; a later consumer version with the same pact needs nothing from it.
    result = integration["client"].post(
        f"{PAIR}/pact-version/{_sha(integration, '2.0.0')}/verification-results",
        json={"success": True, "providerApplicationVersion": "p1"},
    )
    assert result.status_code == 201, result.text
    _publish(integration, "3.0.0", total=2500, branch="main")
    assert len(_firings(integration)) == 1


def test_content_changed_compares_with_the_previous_pact_on_the_branch(integration: Dict[str, Any]) -> None:
    _create(integration, "contract_published", "contract_content_changed", "consumer_version_branch_created")
    # Same content as 1.0.0 on main: published, not changed.
    _publish(integration, "1.1.0", branch="main")
    assert _events(integration) == ["contract_published"]
    # Different content: changed.
    _publish(integration, "2.0.0", total=2500, branch="main")
    assert _events(integration) == ["contract_content_changed", "contract_published", "contract_published"]
    # The first pact on a new branch is a change there, and the branch is new.
    _publish(integration, "2.1.0", total=2500, branch="feat/invoices")
    latest = [firing for firing in _firings(integration) if firing["consumer_version_number"] == "2.1.0"]
    assert sorted(firing["event_name"] for firing in latest) == [
        "consumer_version_branch_created",
        "contract_content_changed",
        "contract_published",
    ]
    assert latest[0]["payload"]["parameters"]["pactbroker.consumerVersionBranch"] == "feat/invoices"
    # The next version on that branch with the same pact: neither.
    _publish(integration, "2.2.0", total=2500, branch="feat/invoices")
    newest = [firing for firing in _firings(integration) if firing["consumer_version_number"] == "2.2.0"]
    assert [firing["event_name"] for firing in newest] == ["contract_published"]


def test_a_webhook_fires_only_for_its_scope_and_only_while_enabled(integration: Dict[str, Any]) -> None:
    other = dict(publication_db._pact(), provider={"name": "Audit API"})
    integration["client"].post(f"{BASE}/contracts/publish", json=publication_db._bulk("0.9.0", other))
    _create(integration, "contract_published", description="any")
    _create(integration, "contract_published", description="audit only", provider={"name": "Audit API"})
    _create(integration, "contract_published", description="ledger only", provider={"name": "Ledger API"})
    _create(integration, "contract_published", description="off", enabled=False)
    _create(integration, "provider_verification_published", description="other event")

    _publish(integration, "2.0.0", total=2500, branch="main")
    fired = {
        get_webhook(integration["db"], integration["seed"]["tenant"], firing["webhook_id"]).description
        for firing in _firings(integration)
    }
    assert fired == {"any", "ledger only"}


# --- Verification events -------------------------------------------------------------------------


def test_a_verification_result_fires_its_events(integration: Dict[str, Any]) -> None:
    _create(
        integration,
        "provider_verification_published",
        "provider_verification_succeeded",
        "provider_verification_failed",
    )
    sha = _sha(integration, "1.0.0")
    results = f"{PAIR}/pact-version/{sha}/verification-results"
    failed = integration["client"].post(
        results, json={"success": False, "providerApplicationVersion": "p1", "buildUrl": "https://ci.example.com/b/1"}
    )
    assert failed.status_code == 201, failed.text
    firings = _firings(integration)
    assert sorted(firing["event_name"] for firing in firings) == [
        "provider_verification_failed",
        "provider_verification_published",
    ]
    parameters = firings[0]["payload"]["parameters"]
    assert parameters["pactbroker.githubVerificationStatus"] == "failure"
    assert parameters["pactbroker.bitbucketVerificationStatus"] == "FAILED"
    assert parameters["pactbroker.providerVersionNumber"] == "p1"
    assert parameters["pactbroker.providerVersionBranch"] == "main"
    assert parameters["pactbroker.consumerVersionNumber"] == "1.0.0"
    assert parameters["pactbroker.buildUrl"] == "https://ci.example.com/b/1"
    assert parameters["pactbroker.verificationResultUrl"].endswith(f"/pact-version/{sha}/verification-results/1")
    assert integration["client"].get(_path(parameters["pactbroker.verificationResultUrl"])).status_code == 200

    passed = integration["client"].post(results, json={"success": True, "providerApplicationVersion": "p1"})
    assert passed.status_code == 201, passed.text
    assert _events(integration)[-1] == "provider_verification_succeeded"

    # What each result fired can be read from the result's link.
    link = failed.json()["_links"]["pb:triggered-webhooks"]["href"]
    triggered = integration["client"].get(_path(link)).json()["_embedded"]["triggeredWebhooks"]
    assert sorted(item["eventName"] for item in triggered) == [
        "provider_verification_failed",
        "provider_verification_published",
    ]


# --- Delivery: retry, dead-letter, the log -------------------------------------------------------


class _FailingClient:
    """Stands in for the guarded client: answers 500 and echoes the Authorization header."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    def __enter__(self) -> "_FailingClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def request(self, method: str, url: str, *, content: bytes, headers: Dict[str, str]) -> httpx.Response:
        self.sent.append({"method": method, "url": url, "content": content, "headers": headers})
        return httpx.Response(500, text=f"upstream rejected {headers.get('Authorization')}")


def test_a_failed_delivery_is_retried_then_dead_lettered_with_a_readable_log(integration: Dict[str, Any]) -> None:
    client = integration["client"]
    database = integration["db"]
    _create(integration, "contract_published")
    _publish(integration, "2.0.0", total=2500, branch="main")
    (firing,) = _firings(integration)

    status_before = client.get(f"{PAIR}/webhooks/status").json()
    assert status_before["summary"] == {"successful": 0, "failed": 0, "retrying": 0, "notRun": 1}
    logs_path = _path(status_before["_embedded"]["triggeredWebhooks"][0]["_links"]["pb:logs"]["href"])
    assert "has not executed yet" in client.get(logs_path).text

    http = _FailingClient()
    statuses = []
    with patch("app.pact_webhook_delivery.build_guarded_client", return_value=http):
        for _attempt in range(MAX_DELIVERY_ATTEMPTS):
            # The retry is scheduled for later; bring it forward as the passing of time would.
            integration["cursor"].execute(
                "UPDATE apiome.push_webhook_delivery_events "
                "SET next_retry_at = CURRENT_TIMESTAMP - interval '1 second' "
                "WHERE id = %s::uuid AND next_retry_at IS NOT NULL",
                (firing["delivery_event_id"],),
            )
            claimed = [
                row
                for row in database.claim_due_push_webhook_deliveries(limit=50)
                if str(row["event_id"]) == firing["delivery_event_id"]
            ]
            assert len(claimed) == 1 and str(claimed[0]["pact_webhook_id"]) == firing["webhook_id"]
            deliver_one_due_event(database, claimed[0])
            statuses.append(client.get(f"{PAIR}/webhooks/status").json()["_embedded"]["triggeredWebhooks"][0])
    assert [item["status"] for item in statuses] == ["retrying", "retrying", "retrying", "failure"]
    assert [item["attemptsMade"] for item in statuses] == [1, 2, 3, 4]
    assert [item["attemptsRemaining"] for item in statuses] == [3, 2, 1, 0]

    # The request was the webhook's own, rendered, with its sealed secrets.
    assert len(http.sent) == MAX_DELIVERY_ATTEMPTS
    assert http.sent[0]["url"] == "https://ci.example.com/hooks/verify?provider=Ledger+API"
    assert http.sent[0]["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert http.sent[0]["headers"]["X-Apiome-Signature"].startswith("sha256=")
    assert {sent["headers"]["X-Apiome-Delivery"] for sent in http.sent} == {firing["delivery_event_id"]}

    # Dead-lettered: nothing more is claimed, and it is on the tenant's dead-letter list.
    assert not [
        row
        for row in database.claim_due_push_webhook_deliveries(limit=50)
        if str(row["event_id"]) == firing["delivery_event_id"]
    ]
    dead = database.list_push_webhook_dead_letter_events(integration["seed"]["tenant"])
    assert [str(row["id"]) for row in dead] == [firing["delivery_event_id"]]
    final = client.get(f"{PAIR}/webhooks/status").json()
    assert final["summary"] == {"successful": 0, "failed": 1, "retrying": 0, "notRun": 0}
    assert [link["title"] for link in final["_links"]["pb:error-logs"]] == ["Error logs"]

    # The log of every attempt is readable, as text and as JSON — and holds no secret.
    text = client.get(logs_path).text
    assert text.count("HTTP/1.1 POST https://ci.example.com/hooks/verify?provider=Ledger+API") == 4
    assert text.count("HTTP/1.1 500") == 4 and "dead-letter" in text and f"Authorization: {REDACTED}" in text
    document = client.get(logs_path, headers={"Accept": "application/hal+json"}).json()
    assert [execution["attempt"] for execution in document["executions"]] == [1, 2, 3, 4]
    assert all(execution["success"] is False and execution["status"] == 500 for execution in document["executions"])
    assert document["status"] == "failure" and document["eventName"] == "contract_published"
    integration["cursor"].execute(
        "SELECT e.last_error, e.payload::text AS payload, a.response_body_preview, a.error_message, a.execution_log "
        "FROM apiome.push_webhook_delivery_events e "
        "JOIN apiome.push_webhook_delivery_attempts a ON a.delivery_event_id = e.id WHERE e.id = %s::uuid",
        (firing["delivery_event_id"],),
    )
    stored = json.dumps([dict(row) for row in integration["cursor"].fetchall()])
    for secret in (_TOKEN, _SIGNING):
        assert secret not in stored and secret not in text and secret not in json.dumps(document)

    # What the publication fired can be read from the pact's link.
    pact = client.get(f"{PAIR}/version/2.0.0").json()
    triggered = client.get(_path(pact["_links"]["pb:triggered-webhooks"]["href"])).json()
    assert [item["eventName"] for item in triggered["_embedded"]["triggeredWebhooks"]] == ["contract_published"]


def test_deleting_a_webhook_removes_its_deliveries_and_history(integration: Dict[str, Any]) -> None:
    created = _create(integration, "contract_published")
    _publish(integration, "2.0.0", total=2500, branch="main")
    (firing,) = _firings(integration)
    assert integration["client"].delete(f"{BASE}/webhooks/{created['uuid']}").status_code == 204
    assert _firings(integration) == []
    integration["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.push_webhook_delivery_events WHERE id = %s::uuid",
        (firing["delivery_event_id"],),
    )
    assert integration["cursor"].fetchone()["n"] == 0
    assert integration["client"].get(f"{BASE}/triggered-webhooks/{firing['id']}/logs").status_code == 404
