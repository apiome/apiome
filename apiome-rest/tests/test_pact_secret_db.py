"""Workspace secrets against a live Postgres — PFX-6.5 (#6957).

What only the real schema (apiome-db V450) and the real routes prove:

* a secret is created, listed, read, rotated and deleted through ``/v1/tenants/{t}/pact-secrets``;
  only ciphertext is stored and no answer carries the value; a taken name is a 409;
* a webhook that writes ``${user.<name>}`` is refused until the secret exists **in its own
  workspace**, then stores the name in ``secret_refs`` and lists it as ``secretReferences``;
* a published pact's firing sends the resolved value — the rotated one after a rotation — and the
  execution log never holds it;
* a secret a webhook or a verification target refers to is not deleted; the refusal names them;
* the ``secret`` target reference kind is shape-checked by the CHECK constraint;
* another workspace's secret is a 404 and never listed.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_webhook_db``).
Skipped when no database is reachable or V450 is not applied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import httpx
import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_secret import SecretCreate
from app.pact_secret_store import create_secret, resolve_secrets
from app.push_webhook_delivery import deliver_one_due_event
from tests import test_pact_webhook_db as webhook_db

tx = webhook_db.tx
stack = webhook_db.stack
broker = webhook_db.broker

pytestmark = pytest.mark.requires_db

BASE = webhook_db.BASE
SECRETS = "/v1/tenants/acme/pact-secrets"
_VALUE = "ci-token-value-0123456789"
_ROTATED = "rotated-token-value-9876543210"


@pytest.fixture
def vault(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The webhook stack with the secret routes on its transaction."""
    broker["cursor"].execute("SELECT to_regclass('apiome.pact_secret') AS t")
    if not broker["cursor"].fetchone()["t"]:
        pytest.skip("V450 not applied")
    with (
        patch("app.pact_secret_routes.db", broker["db"]),
        patch("app.pact_secret_routes.enforce_permission", return_value=None),
    ):
        yield broker


def _secret(vault: Dict[str, Any], name: str = "ciToken", value: str = _VALUE) -> Dict[str, Any]:
    response = vault["client"].post(SECRETS, json={"name": name, "value": value, "description": "CI"})
    assert response.status_code == 201, response.text
    return response.json()


def _webhook(**request: Any) -> Dict[str, Any]:
    return {
        "events": [{"name": "contract_published"}],
        "request": {
            "method": "POST",
            "url": "https://ci.example.com/hooks/verify?key=${user.ciToken}",
            "headers": {"Authorization": "Bearer ${user.ciToken}"},
            "body": {"pactUrl": "${pactbroker.pactUrl}", "token": "${user.ciToken}"},
            **request,
        },
    }


class _Client:
    """The guarded client: records each request and answers 200 echoing its headers."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def request(self, method: str, url: str, *, content: bytes, headers: Dict[str, str]) -> httpx.Response:
        self.sent.append({"url": url, "content": content, "headers": dict(headers)})
        return httpx.Response(200, text=f"got {headers.get('Authorization')}")


def _deliver_all(vault: Dict[str, Any]) -> _Client:
    http = _Client()
    database = vault["db"]
    with patch("app.pact_webhook_delivery.build_guarded_client", return_value=http):
        for row in database.claim_due_push_webhook_deliveries(limit=50):
            if str(row["tenant_id"]) == vault["seed"]["tenant"]:
                deliver_one_due_event(database, row)
    return http


def test_a_secret_is_created_read_rotated_and_stored_only_as_ciphertext(vault: Dict[str, Any]) -> None:
    client = vault["client"]
    created = _secret(vault)
    assert created["name"] == "ciToken" and created["reference"] == "${user.ciToken}"
    assert _VALUE not in json.dumps(created)
    assert client.get(SECRETS).json()["secrets"][0]["id"] == created["id"]
    assert client.get(f"{SECRETS}/{created['id']}").json()["used_by"] == {"webhooks": [], "targets": []}

    vault["cursor"].execute(
        "SELECT secret_ciphertext, key_version FROM apiome.pact_secret WHERE id = %s::uuid", (created["id"],)
    )
    first = vault["cursor"].fetchone()
    assert _VALUE.encode() not in bytes(first["secret_ciphertext"]) and first["key_version"] == 1

    taken = client.post(SECRETS, json={"name": "ciToken", "value": "other"})
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "pact-secret-name-taken"

    rotated = client.put(f"{SECRETS}/{created['id']}", json={"value": _ROTATED, "description": "rotated"})
    assert rotated.status_code == 200 and rotated.json()["description"] == "rotated"
    assert resolve_secrets(vault["db"], vault["seed"]["tenant"], ["ciToken"]) == {"ciToken": _ROTATED}
    renamed = client.put(f"{SECRETS}/{created['id']}", json={"name": "other"})
    assert renamed.status_code == 422 and renamed.json()["detail"]["pointer"] == "/name"

    assert client.delete(f"{SECRETS}/{created['id']}").status_code == 204
    assert client.get(f"{SECRETS}/{created['id']}").status_code == 404


def test_another_workspaces_secret_is_invisible_and_cannot_be_referred_to(vault: Dict[str, Any]) -> None:
    webhook_db._publish(vault, "1.0.0")
    theirs = create_secret(
        vault["db"], vault["other"]["tenant"], SecretCreate(name="ciToken", value=_VALUE), actor=ConsumerActor()
    )
    client = vault["client"]
    assert client.get(SECRETS).json()["secrets"] == []
    assert client.get(f"{SECRETS}/{theirs.id}").status_code == 404
    assert client.put(f"{SECRETS}/{theirs.id}", json={"value": "x"}).status_code == 404
    assert client.delete(f"{SECRETS}/{theirs.id}").status_code == 404

    refused = client.post(f"{BASE}/webhooks", json=_webhook())
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["pointer"] == "/request/url"
    assert "no secret named 'ciToken'" in refused.json()["detail"]["message"]


def test_a_firing_sends_the_current_value_and_never_logs_it(vault: Dict[str, Any]) -> None:
    client = vault["client"]
    webhook_db._publish(vault, "1.0.0")
    secret = _secret(vault)
    created = client.post(f"{BASE}/webhooks", json=_webhook())
    assert created.status_code == 201, created.text
    webhook = created.json()
    assert webhook["secretReferences"] == ["ciToken"]
    assert webhook["request"]["headers"]["Authorization"] == "**********"
    vault["cursor"].execute("SELECT secret_refs FROM apiome.pact_webhook WHERE id = %s::uuid", (webhook["uuid"],))
    assert vault["cursor"].fetchone()["secret_refs"] == ["ciToken"]
    used = client.get(f"{SECRETS}/{secret['id']}").json()["used_by"]["webhooks"]
    assert [user["id"] for user in used] == [webhook["uuid"]]

    # Rotating changes what the next firing sends; the webhook itself is untouched.
    client.put(f"{SECRETS}/{secret['id']}", json={"value": _ROTATED})
    webhook_db._publish(vault, "2.0.0", total=2500)
    http = _deliver_all(vault)
    assert len(http.sent) == 1
    sent = http.sent[0]
    assert sent["headers"]["Authorization"] == f"Bearer {_ROTATED}"
    assert sent["url"].endswith(f"key={_ROTATED}") and _ROTATED.encode() in sent["content"]

    vault["cursor"].execute(
        """
        SELECT a.execution_log, a.error_message, a.response_body_preview
        FROM apiome.push_webhook_delivery_attempts a
        JOIN apiome.pact_triggered_webhook t ON t.delivery_event_id = a.delivery_event_id
        WHERE t.webhook_id = %s::uuid
        """,
        (webhook["uuid"],),
    )
    logged = json.dumps([dict(row) for row in vault["cursor"].fetchall()], default=str)
    assert "Webhook delivered" in logged and _ROTATED not in logged and _VALUE not in logged


def test_a_secret_in_use_is_not_deleted(vault: Dict[str, Any]) -> None:
    client = vault["client"]
    webhook_db._publish(vault, "1.0.0")
    secret = _secret(vault)
    webhook = client.post(f"{BASE}/webhooks", json=_webhook(description=None)).json()
    vault["cursor"].execute(
        """
        INSERT INTO apiome.verification_target
          (tenant_id, slug, name, environment, base_url, auth_kind, auth_scheme, auth_ref)
        VALUES (%s::uuid, 'ledger-staging', 'Ledger staging', 'staging', 'https://staging.example.com',
                'secret', 'bearer', 'ciToken')
        """,
        (vault["seed"]["tenant"],),
    )
    refused = client.delete(f"{SECRETS}/{secret['id']}")
    assert refused.status_code == 409, refused.text
    message = refused.json()["detail"]["message"]
    assert webhook["uuid"] in message and "'ledger-staging'" in message
    assert client.get(f"{SECRETS}/{secret['id']}").json()["used_by"]["targets"][0]["name"] == "ledger-staging"

    # Once nothing refers to it, it goes.
    assert client.delete(f"{BASE}/webhooks/{webhook['uuid']}").status_code == 204
    vault["cursor"].execute(
        "UPDATE apiome.verification_target SET deleted_at = CURRENT_TIMESTAMP WHERE tenant_id = %s::uuid",
        (vault["seed"]["tenant"],),
    )
    assert client.delete(f"{SECRETS}/{secret['id']}").status_code == 204


@pytest.mark.parametrize("ref", ["ci-token", "Bearer abc", "1token"])
def test_a_target_secret_reference_is_shape_checked(vault: Dict[str, Any], ref: str) -> None:
    cursor = vault["cursor"]
    cursor.execute("SAVEPOINT bad_ref")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            """
            INSERT INTO apiome.verification_target
              (tenant_id, slug, name, environment, base_url, auth_kind, auth_scheme, auth_ref)
            VALUES (%s::uuid, 'bad-ref', 'Bad', 'staging', 'https://staging.example.com', 'secret', 'bearer', %s)
            """,
            (vault["seed"]["tenant"], ref),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT bad_ref")


def test_a_secret_name_is_shape_checked_and_its_value_is_required(vault: Dict[str, Any]) -> None:
    cursor = vault["cursor"]
    for name, ciphertext in (("bad-name", b"x"), ("ok", None)):
        cursor.execute("SAVEPOINT bad_secret")
        with pytest.raises((psycopg2.errors.CheckViolation, psycopg2.errors.NotNullViolation)):
            cursor.execute(
                "INSERT INTO apiome.pact_secret (tenant_id, name, secret_ciphertext, key_version) "
                "VALUES (%s::uuid, %s, %s, 1)",
                (vault["seed"]["tenant"], name, ciphertext),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT bad_secret")
