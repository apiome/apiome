"""Pact commit statuses against a live Postgres — PFX-4.4 (#6941).

What only the real schema and the real routes prove (apiome-db V443):

* **publishing a pact puts ``pending`` on the consumer's commit** of a registered GitHub
  repository, context ``apiome-pact/<consumer>/<provider>``, linking to the pact;
* **a verification result puts ``pass`` / ``fail`` on both commits** — the provider's version and
  the consumer's — and a newer verdict moves the status (one row per version and context);
* a pact already verified by the provider's main branch gets that verdict at once;
* nothing is dropped silently: a version that is not a commit SHA, a pacticipant with no
  repository URL and an unregistered repository are recorded ``suppressed`` with the reason, and
  a provider refusal is recorded ``failed``; a retry after the cause is fixed sends it;
* nothing crosses a tenant, and the list endpoint reads only the caller's statuses.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_webhook_db``).
Skipped when no database is reachable or V443 is not applied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import httpx
import pytest

from app import pact_commit_status_store as store
from app.pact_commit_status import (
    CODE_NO_REPOSITORY,
    CODE_NOT_A_COMMIT,
    CODE_REPOSITORY_NOT_REGISTERED,
    CODE_STATUS_NOT_FOUND,
    CODE_STATUS_NOT_RETRYABLE,
    PactCommitStatusError,
)
from tests import test_pact_publication_db as publication_db
from tests import test_pact_webhook_db as webhook_db

tx = publication_db.tx
stack = publication_db.stack
broker = webhook_db.broker

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PAIR = publication_db.PAIR
CONSUMER_SHA = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
PROVIDER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
CONTEXT = "apiome-pact/billing-service/ledger-api"
STATUSES = "/v1/tenants/t/pact-commit-statuses"


class _GitHub:
    """A stand-in for api.github.com that records every request and answers ``status``."""

    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.status = 201

    def __call__(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json={"message": "refused"} if self.status >= 400 else {})

        return httpx.Client(transport=httpx.MockTransport(handle))

    def bodies(self) -> List[Dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]

    def urls(self) -> List[str]:
        return [str(request.url) for request in self.requests]


@pytest.fixture
def statuses(broker: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """The broker stack with the status routes on its transaction and GitHub stubbed out."""
    broker["cursor"].execute("SELECT to_regclass('apiome.pact_commit_status') AS t")
    if not broker["cursor"].fetchone()["t"]:
        pytest.skip("V443 not applied")
    github = _GitHub()
    monkeypatch.setattr(store, "CLIENT_FACTORY", github)
    monkeypatch.setattr("app.provider_check_store._repository_token", lambda *_args: "gh-token-secret")
    patches = [
        patch("app.pact_commit_status_routes.db", broker["db"]),
        patch("app.pact_commit_status_routes.enforce_permission", return_value=None),
    ]
    for started in patches:
        started.start()
    try:
        yield {**broker, "github": github}
    finally:
        for started in patches:
            started.stop()


def _register(stack: Dict[str, Any], tenant: str, slug: str, url: str, *, register: bool = True) -> None:
    """Set a pacticipant's repository URL and, optionally, register the repository for the tenant."""
    cursor = stack["cursor"]
    cursor.execute(
        "UPDATE apiome.pacticipant SET repository_url = %s WHERE tenant_id = %s::uuid AND slug = %s",
        (url, tenant, slug),
    )
    if register:
        full_name = url.split("github.com/", 1)[1]
        cursor.execute(
            """
            INSERT INTO apiome.tenant_repositories
              (tenant_id, source, provider, clone_url, clone_url_normalized, repository_full_name)
            VALUES (%s::uuid, 'linked_account', 'github', %s, %s, %s)
            """,
            (tenant, url + ".git", f"https://github.com/{full_name.lower()}.git", full_name),
        )


def _publish(stack: Dict[str, Any], version: str) -> None:
    response = stack["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk(version, publication_db._pact(), branch="main")
    )
    assert response.status_code == 200, response.text


def _verify(stack: Dict[str, Any], version: str, *, success: bool, provider_version: str = PROVIDER_SHA) -> None:
    sha = webhook_db._sha(stack, version)
    response = stack["client"].post(
        f"{PAIR}/pact-version/{sha}/verification-results",
        json={"success": success, "providerApplicationVersion": provider_version},
    )
    assert response.status_code == 201, response.text


def _rows(stack: Dict[str, Any]) -> List[Dict[str, Any]]:
    stack["cursor"].execute(
        "SELECT s.*, v.number FROM apiome.pact_commit_status s "
        "JOIN apiome.pacticipant_version v ON v.id = s.pacticipant_version_id "
        "WHERE s.tenant_id = %s::uuid ORDER BY s.side, v.number",
        (stack["seed"]["tenant"],),
    )
    return [dict(row) for row in stack["cursor"].fetchall()]


def _wire_up(stack: Dict[str, Any]) -> None:
    """Publish once so both pacticipants exist, then give both a registered repository."""
    tenant = stack["seed"]["tenant"]
    _publish(stack, "1.0.0")
    _register(stack, tenant, "billing-service", "https://github.com/Acme/billing-service")
    _register(stack, tenant, "ledger-api", "https://github.com/acme/ledger-api")


def test_publish_then_verify_puts_the_verdict_on_both_commits(statuses: Dict[str, Any]) -> None:
    _wire_up(statuses)
    github = statuses["github"]
    github.requests.clear()

    _publish(statuses, CONSUMER_SHA)
    assert github.urls() == [f"https://api.github.com/repos/acme/billing-service/statuses/{CONSUMER_SHA}"]
    pending = github.bodies()[0]
    assert pending["state"] == "pending" and pending["context"] == CONTEXT
    assert pending["description"] == "Pact awaiting verification by Ledger API"
    assert "/pacts/provider/ledger-api/consumer/billing-service/" in pending["target_url"]
    assert github.requests[0].headers["Authorization"] == "Bearer gh-token-secret"

    _verify(statuses, CONSUMER_SHA, success=False)
    assert github.urls()[1:] == [
        f"https://api.github.com/repos/acme/ledger-api/statuses/{PROVIDER_SHA}",
        f"https://api.github.com/repos/acme/billing-service/statuses/{CONSUMER_SHA}",
    ]
    assert [body["state"] for body in github.bodies()[1:]] == ["failure", "failure"]
    assert github.bodies()[2]["description"] == "Pact failed verification by Ledger API fedcba987654"
    assert "/verification-results/1" in github.bodies()[1]["target_url"]

    _verify(statuses, CONSUMER_SHA, success=True)
    assert [body["state"] for body in github.bodies()[3:]] == ["success", "success"]

    # One row per version and context; the newest verdict moved it. No token stored anywhere.
    rows = [row for row in _rows(statuses) if row["number"] in (CONSUMER_SHA, PROVIDER_SHA)]
    assert [(row["side"], row["state"], row["outcome"], row["attempts"]) for row in rows] == [
        ("consumer", "pass", "dispatched", 3),
        ("provider", "pass", "dispatched", 2),
    ]
    assert all(row["context"] == CONTEXT and row["http_status"] == 201 for row in rows)
    assert "gh-token-secret" not in json.dumps(rows, default=str)


def test_a_pact_main_has_verified_gets_that_verdict_on_publish(statuses: Dict[str, Any]) -> None:
    _wire_up(statuses)
    statuses["cursor"].execute(
        "UPDATE apiome.pacticipant SET main_branch = 'main' WHERE tenant_id = %s::uuid AND slug = 'ledger-api'",
        (statuses["seed"]["tenant"],),
    )
    webhook_db._provider_version(statuses, PROVIDER_SHA, "main")
    _verify(statuses, "1.0.0", success=True)
    statuses["github"].requests.clear()

    _publish(statuses, CONSUMER_SHA)  # the same pact content as 1.0.0
    body = statuses["github"].bodies()[0]
    assert body["state"] == "success"
    assert body["description"] == "Pact verified by Ledger API fedcba987654"


def test_nothing_is_dropped_silently(statuses: Dict[str, Any]) -> None:
    tenant = statuses["seed"]["tenant"]
    _publish(statuses, "1.0.0")  # no repository URL yet
    _register(statuses, tenant, "billing-service", "https://github.com/acme/billing-service", register=False)
    _publish(statuses, CONSUMER_SHA)  # a repository nobody registered
    _register(statuses, tenant, "billing-service", "https://github.com/acme/billing-service")
    _publish(statuses, "2.0.0")  # registered, but not a commit
    assert statuses["github"].requests == []

    reasons = {row["number"]: (row["outcome"], row["reason_code"]) for row in _rows(statuses)}
    assert reasons == {
        "1.0.0": ("suppressed", CODE_NO_REPOSITORY),
        CONSUMER_SHA: ("suppressed", CODE_REPOSITORY_NOT_REGISTERED),
        "2.0.0": ("suppressed", CODE_NOT_A_COMMIT),
    }

    # Once the repository is registered, a retry of the unregistered one sends it.
    listing = statuses["client"].get(STATUSES, params={"version": CONSUMER_SHA}).json()["items"]
    assert len(listing) == 1 and listing[0]["reason_code"] == CODE_REPOSITORY_NOT_REGISTERED
    retried = statuses["client"].post(f"{STATUSES}/{listing[0]['id']}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["outcome"] == "dispatched"
    assert retried.json()["repository"] == "acme/billing-service"
    assert len(statuses["github"].requests) == 1

    # A dispatched status is not retried; a version that is still no commit stays suppressed.
    again = statuses["client"].post(f"{STATUSES}/{listing[0]['id']}/retry")
    assert again.status_code == 409 and again.json()["detail"]["code"] == CODE_STATUS_NOT_RETRYABLE
    not_a_commit = statuses["client"].get(STATUSES, params={"version": "2.0.0"}).json()["items"][0]
    still = statuses["client"].post(f"{STATUSES}/{not_a_commit['id']}/retry").json()
    assert (still["outcome"], still["reason_code"]) == ("suppressed", CODE_NOT_A_COMMIT)


def test_a_provider_refusal_is_failed_and_retryable(statuses: Dict[str, Any]) -> None:
    _wire_up(statuses)
    statuses["github"].status = 403
    _publish(statuses, CONSUMER_SHA)
    failed = statuses["client"].get(STATUSES, params={"outcome": "failed"}).json()["items"]
    assert len(failed) == 1
    assert failed[0]["reason_code"] == "check-provider-forbidden"
    assert failed[0]["http_status"] == 403 and failed[0]["attempts"] == 1

    statuses["github"].status = 201
    retried = statuses["client"].post(f"{STATUSES}/{failed[0]['id']}/retry").json()
    assert (retried["outcome"], retried["attempts"], retried["http_status"]) == ("dispatched", 2, 201)


def test_nothing_crosses_a_tenant(statuses: Dict[str, Any]) -> None:
    _wire_up(statuses)
    _publish(statuses, CONSUMER_SHA)
    db, other = statuses["db"], statuses["other"]["tenant"]
    items, _ = store.list_commit_statuses(db, other)
    assert items == []
    mine = statuses["client"].get(STATUSES).json()["items"]
    assert mine and all(item["consumer"] == "billing-service" for item in mine)
    with pytest.raises(PactCommitStatusError) as missing:
        store.retry_commit_status(db, other, mine[0]["id"])
    assert missing.value.code == CODE_STATUS_NOT_FOUND


def test_the_list_pages_newest_first(statuses: Dict[str, Any]) -> None:
    for number in ("1.0.0", "2.0.0", "3.0.0"):
        _publish(statuses, number)
    first = statuses["client"].get(STATUSES, params={"limit": 2})
    assert first.status_code == 200
    page = first.json()
    assert [item["version"] for item in page["items"]] == ["3.0.0", "2.0.0"]
    assert first.headers["X-Next-Cursor"] == page["next_cursor"]
    rest = statuses["client"].get(STATUSES, params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [item["version"] for item in rest["items"]] == ["1.0.0"] and rest["next_cursor"] is None
    assert statuses["client"].get(STATUSES, params={"pacticipant": "ledger-api"}).json()["items"] == []
