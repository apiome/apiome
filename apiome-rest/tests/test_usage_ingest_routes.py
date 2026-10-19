"""``POST /v1/tenants/{tenant}/usage/ingest`` — the HTTP layer of RDG-1.2 (#5760).

The store is stubbed: these tests pin what the route itself owns — API keys only (never a
session), naming the source by header or body, gzip, the size limits, the shape of the echoed
ledger counts, and how a refusal (``429`` with ``retryAt`` and ``Retry-After``, ``422``) reaches the
caller. The credential path against the real database is ``test_usage_ingest_db.py``; the scope
allowlist is pinned here too.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from app.auth import API_KEY_SCOPE_USAGE_INGEST, acceptable_scopes_for_request, validate_authentication
from app.main import app
from app.usage_ingest import BatchPlan, UsageIngestError
from app.usage_ingest_store import IngestOutcome

TENANT = "acme"
URL = f"/v1/tenants/{TENANT}/usage/ingest"
SOURCE = "6f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"
NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)

_API_KEY_AUTH = {"auth_method": "api_key", "tenant_id": "t-1", "id": "k-1", "scopes": ["usage:ingest"]}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[List[Dict[str, Any]]]:
    """Stub the store; yield what it was called with."""
    seen: List[Dict[str, Any]] = []

    def fake_ingest(_db: Any, **kwargs: Any) -> IngestOutcome:
        seen.append(kwargs)
        plan = BatchPlan(received=len(kwargs["raw_events"]), accepted=len(kwargs["raw_events"]))
        return IngestOutcome(batch_id="b-1", received_at=NOW, plan=plan)

    monkeypatch.setattr("app.usage_ingest_routes.ingest_batch", fake_ingest)
    app.dependency_overrides[validate_authentication] = lambda: dict(_API_KEY_AUTH)
    yield seen
    app.dependency_overrides.pop(validate_authentication, None)


def _batch(**extra: Any) -> Dict[str, Any]:
    return {"events": [{"observed_at": NOW.isoformat(), "method": "GET", "path": "/pets/1", "status": 200,
                        "latency_ms": 5}], **extra}


def test_the_scope_admits_the_ingest_route_and_nothing_else() -> None:
    assert acceptable_scopes_for_request("POST", URL) == [API_KEY_SCOPE_USAGE_INGEST]
    assert acceptable_scopes_for_request("POST", URL + "/") == [API_KEY_SCOPE_USAGE_INGEST]
    assert API_KEY_SCOPE_USAGE_INGEST not in acceptable_scopes_for_request("GET", URL)
    assert API_KEY_SCOPE_USAGE_INGEST not in acceptable_scopes_for_request("POST", f"/v1/projects/{TENANT}")


def test_an_admitted_batch_echoes_its_ledger_counts(calls: List[Dict[str, Any]]) -> None:
    response = TestClient(app).post(URL, json=_batch(source_id=SOURCE))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["batchId"] == "b-1" and body["sourceId"] == SOURCE
    assert (body["received"], body["accepted"], body["rejected"], body["basis"]) == (1, 1, 0, "complete")
    assert body["samples"] == {"stored": 0, "dropped": 0} and body["rejectionsTruncated"] is False
    assert calls[0]["tenant_id"] == "t-1" and calls[0]["api_key_id"] == "k-1"
    assert len(calls[0]["digest"]) == 64


def test_the_source_may_be_named_by_header_and_the_body_may_be_gzip(calls: List[Dict[str, Any]]) -> None:
    payload = gzip.compress(json.dumps(_batch()).encode())
    response = TestClient(app).post(
        URL,
        content=payload,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json", "X-Apiome-Usage-Source": SOURCE},
    )
    assert response.status_code == 200, response.text
    assert calls[0]["source_ref"] == SOURCE


def test_a_session_is_refused(calls: List[Dict[str, Any]]) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"auth_method": "jwt", "tenant_id": "t-1"}
    response = TestClient(app).post(URL, json=_batch(source_id=SOURCE))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "usage-ingest-key-required"
    assert calls == []


@pytest.mark.parametrize(
    ("body", "headers", "status", "code"),
    [
        (_batch(), {}, 400, "usage-source-required"),
        (_batch(source_id=SOURCE), {"X-Apiome-Usage-Source": "8f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"}, 400,
         "usage-batch-invalid"),
        ({"events": [{}] * 5001, "source_id": SOURCE}, {}, 413, "usage-batch-too-large"),
    ],
)
def test_malformed_batches_are_refused_before_the_store(
    calls: List[Dict[str, Any]], body: Dict[str, Any], headers: Dict[str, str], status: int, code: str
) -> None:
    response = TestClient(app).post(URL, json=body, headers=headers)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert calls == []


def test_a_quota_refusal_carries_retry_at_and_the_ledger_row(monkeypatch: pytest.MonkeyPatch) -> None:
    retry_at = datetime.now(timezone.utc) + timedelta(hours=3)

    def over_cap(_db: Any, **_kwargs: Any) -> IngestOutcome:
        raise UsageIngestError(429, "usage-quota-exceeded", "over the cap", retry_at=retry_at, batch_id="b-9")

    monkeypatch.setattr("app.usage_ingest_routes.ingest_batch", over_cap)
    app.dependency_overrides[validate_authentication] = lambda: dict(_API_KEY_AUTH)
    try:
        response = TestClient(app).post(URL, json=_batch(source_id=SOURCE))
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "usage-quota-exceeded" and detail["batchId"] == "b-9"
    assert datetime.fromisoformat(detail["retryAt"].replace("Z", "+00:00")) == retry_at
    assert 0 < int(response.headers["Retry-After"]) <= 3 * 3600


def test_the_operation_is_documented_under_the_usage_tag() -> None:
    operation = app.openapi()["paths"]["/v1/tenants/{tenant_slug}/usage/ingest"]["post"]
    assert operation["tags"] == ["usage"]
    assert "events" in operation["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert {"413", "422", "429"} <= set(operation["responses"])
