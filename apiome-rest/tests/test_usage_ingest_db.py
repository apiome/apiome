"""The usage ingest door against a live Postgres — RDG-1.2 (#5760).

The acceptance criteria only the real schema and the real credential path can prove:

* a batch carrying a bearer token in a path, a session cookie in a user agent and an email in a
  query value (and, with the body window open, the same secrets in a sample) produces **no row
  containing any of them** — a sweep over every column of every ``usage_*`` table;
* a source over its daily cap gets ``429 usage-quota-exceeded`` and the batch is ledgered as
  rejected;
* an event naming an operation only a **draft** revision declares is unmatched, not silently
  matched;
* the route is not reachable with a ``kind = 'agent'`` key, while a workspace key carrying
  ``usage:ingest`` reaches it (and nothing else);
* counters add up across batches, a finalized day takes no counts, and field presence keeps its
  denominator.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``). Skipped when no database is reachable or V290/V291 are not applied.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app import usage_ingest_store
from app.usage_ingest import UsageIngestError
from app.usage_ingest_store import ingest_batch
from tests import test_usage_index_db as index_db

EXPECTED_COLUMNS = index_db.EXPECTED_COLUMNS
_tenant = index_db._tenant
#: The always-rolled-back transaction fixture, shared with the RDG-1.1 schema tests.
tx = index_db.tx

pytestmark = pytest.mark.requires_db

NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)

PUBLISHED_DOC = {"openapi": "3.1.0", "paths": {"/pets/{petId}": {"get": {}}, "/users/{userId}/orders": {"get": {}}}}
DRAFT_DOC = {"openapi": "3.1.0", "paths": {**PUBLISHED_DOC["paths"], "/pets/{petId}/toys": {"get": {}}}}

BEARER_VALUE = "abcDEF1234567890ghiJKLmno"
SESSION_VALUE = "s3cr3tSessionValue42xyz"
EMAIL = "alice.secret@example.com"


@pytest.fixture
def seeded(tx: Tuple[Any, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Tuple[Any, Any, Dict[str, str]]]:
    """A tenant whose project has one published and one draft revision, documents stubbed."""
    db, cursor = tx
    seed = _tenant(cursor)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    documents: Dict[str, Dict[str, Any]] = {}
    for label, published, doc in (("1.0.0", True, PUBLISHED_DOC), ("1.1.0-draft", False, DRAFT_DOC)):
        cursor.execute(
            """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
               VALUES (%s, %s, %s, %s, %s) RETURNING id::text AS id""",
            (seed["project"], user, label, published, NOW - timedelta(days=1) if published else None),
        )
        version = cursor.fetchone()["id"]
        documents[version] = doc
        seed["published" if published else "draft"] = version
    monkeypatch.setattr(
        "app.blast_radius.version_document", lambda _db, _tenant_id, version: documents.get(version["id"])
    )
    usage_ingest_store._index_cache.clear()
    yield db, cursor, seed


def _event(path: str, **overrides: Any) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "observed_at": NOW.isoformat(),
        "method": "GET",
        "path": path,
        "status": 200,
        "latency_ms": 20,
        "scheme": "https",
    }
    event.update(overrides)
    return event


def _ingest(db: Any, seed: Dict[str, str], events: List[Dict[str, Any]], **kwargs: Any) -> Any:
    return ingest_batch(
        db,
        tenant_id=seed["tenant"],
        source_ref=seed["source"],
        raw_events=events,
        digest="0" * 64,
        api_key_id=None,
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def _rows(cursor: Any, table: str, tenant: str) -> List[Dict[str, Any]]:
    cursor.execute(f"SELECT * FROM apiome.{table} WHERE tenant_id = %s ORDER BY 1", (tenant,))
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------------------------
# The privacy sweep
# ---------------------------------------------------------------------------------------------


def test_no_usage_row_holds_a_token_a_cookie_or_an_email(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    cursor.execute(
        """UPDATE apiome.usage_source
           SET field_capture = true, body_sample_rate = 0.05, body_sample_until = %s
           WHERE id = %s""",
        (datetime.now(timezone.utc) + timedelta(days=2), seed["source"]),
    )
    sample = {
        "request": {"headers": {"Authorization": f"Bearer {BEARER_VALUE}", "Cookie": f"session={SESSION_VALUE}"}},
        "response": {"headers": {"Set-Cookie": f"session={SESSION_VALUE}"}, "body": {"email": EMAIL, "id": 1}},
    }
    events = [
        _event(f"/sessions/Bearer%20{BEARER_VALUE}"),
        _event(f"/pets/{BEARER_VALUE}"),
        _event("/pets/7", user_agent=f"probe/1.0 session={SESSION_VALUE}"),
        _event(f"/pets/8?owner={EMAIL}&limit=5"),
        _event(f"/users/{EMAIL}/orders", fields={"response": ["/id"]}),
    ]
    # Enough copies that the 5% body sample picks some (the hash spreads them by time).
    batch = [
        {**event, "observed_at": (NOW + timedelta(seconds=i)).isoformat(), "sample": sample}
        for i in range(60)
        for event in events
    ]
    outcome = _ingest(db, seed, batch)
    assert outcome.plan.rejected == 0 and outcome.plan.accepted > 0 and outcome.plan.unmatched > 0
    assert outcome.plan.scrub_findings > 0
    # The body window is open, so the sample path ran: chosen samples were stored or refused.
    assert len(outcome.plan.samples) + outcome.plan.samples_dropped > 0
    assert len(_rows(cursor, "usage_sample", seed["tenant"])) == len(outcome.plan.samples)

    written = 0
    for table in EXPECTED_COLUMNS:
        if "tenant_id" not in EXPECTED_COLUMNS[table]:
            continue
        cursor.execute(
            f"SELECT row_to_json(t)::text AS row FROM apiome.{table} t WHERE tenant_id = %s", (seed["tenant"],)
        )
        for row in cursor.fetchall():
            written += 1
            for secret in (BEARER_VALUE, SESSION_VALUE, EMAIL, "alice.secret"):
                assert secret not in row["row"], (table, secret)
    assert written > 0
    assert _rows(cursor, "usage_hourly", seed["tenant"])
    assert _rows(cursor, "usage_unmatched_daily", seed["tenant"])
    pointers = {row["pointer"] for row in _rows(cursor, "usage_field_daily", seed["tenant"])}
    assert {"/parameters/query:owner", "/parameters/query:limit"} <= pointers


# ---------------------------------------------------------------------------------------------
# Step 1 — the tier cap
# ---------------------------------------------------------------------------------------------


def test_a_source_over_its_daily_cap_gets_429_and_the_batch_is_ledgered_rejected(
    seeded: Tuple[Any, Any, Dict[str, str]],
) -> None:
    db, cursor, seed = seeded
    cursor.execute(
        """INSERT INTO apiome.licenses (name, license_type, seats)
           VALUES (%s, 'free', '{"usage_events_per_day": 3}'::jsonb) RETURNING id""",
        (f"usage cap {uuid.uuid4().hex[:8]}",),
    )
    cursor.execute(
        "INSERT INTO apiome.tenant_licenses (tenant_id, license_id) VALUES (%s, %s)",
        (seed["tenant"], cursor.fetchone()["id"]),
    )
    first = _ingest(db, seed, [_event("/pets/1"), _event("/pets/2")])
    assert first.plan.accepted == 2

    with pytest.raises(UsageIngestError) as caught:
        _ingest(db, seed, [_event("/pets/3"), _event("/pets/4")])
    assert (caught.value.status, caught.value.code) == (429, "usage-quota-exceeded")
    assert caught.value.retry_at == datetime.combine(NOW.date() + timedelta(days=1), datetime.min.time(), timezone.utc)

    ledger = _rows(cursor, "usage_ingest_batch", seed["tenant"])
    rejected = [row for row in ledger if str(row["id"]) == caught.value.batch_id]
    assert len(rejected) == 1
    assert (rejected[0]["received"], rejected[0]["rejected"], rejected[0]["accepted"]) == (2, 2, 0)
    hourly = _rows(cursor, "usage_hourly", seed["tenant"])
    assert sum(row["calls"] for row in hourly) == 2

    # One more event still fits (2 admitted + 1 = the cap of 3).
    assert _ingest(db, seed, [_event("/pets/5")]).plan.accepted == 1


# ---------------------------------------------------------------------------------------------
# Step 4 — published revisions only
# ---------------------------------------------------------------------------------------------


def test_an_operation_only_a_draft_declares_is_unmatched(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    outcome = _ingest(db, seed, [_event("/pets/42/toys"), _event("/pets/42")])
    assert (outcome.plan.accepted, outcome.plan.unmatched) == (1, 1)

    (hourly,) = _rows(cursor, "usage_hourly", seed["tenant"])
    assert hourly["operation_key"] == "/paths/~1pets~1{petId}/get"
    assert str(hourly["version_record_id"]) == seed["published"]
    (unmatched,) = _rows(cursor, "usage_unmatched_daily", seed["tenant"])
    assert (unmatched["method"], unmatched["path_template"]) == ("GET", "/pets/{param}/toys")


# ---------------------------------------------------------------------------------------------
# Counters, ledger, finalized days, field denominators
# ---------------------------------------------------------------------------------------------


def test_counters_add_up_across_batches_and_the_ledger_balances(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    _ingest(db, seed, [_event("/pets/1", latency_ms=3), _event("/pets/2", latency_ms=30_000, auth_present=True)])
    _ingest(db, seed, [_event("/pets/3", latency_ms=60), "not an event"])

    (hourly,) = _rows(cursor, "usage_hourly", seed["tenant"])
    assert hourly["calls"] == 3 and sum(hourly["latency_buckets"]) == 3
    assert hourly["latency_max_ms"] == 30_000 and hourly["auth_present_calls"] == 1 and hourly["https_calls"] == 3

    ledger = _rows(cursor, "usage_ingest_batch", seed["tenant"])
    assert sorted((row["received"], row["accepted"], row["rejected"]) for row in ledger) == [(2, 1, 1), (2, 2, 0)]
    cursor.execute("SELECT last_received_at FROM apiome.usage_source WHERE id = %s", (seed["source"],))
    assert cursor.fetchone()["last_received_at"] == NOW


def test_sampled_counts_are_scaled_in_the_index(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    cursor.execute("UPDATE apiome.usage_source SET sampling_rate = 0.5 WHERE id = %s", (seed["source"],))
    events = [_event(f"/pets/{i}", observed_at=(NOW + timedelta(seconds=i)).isoformat()) for i in range(400)]
    outcome = _ingest(db, seed, events)
    assert outcome.plan.basis == "sampled" and outcome.plan.sampled_out > 0
    assert outcome.plan.accepted + outcome.plan.sampled_out == 400
    calls = sum(row["calls"] for row in _rows(cursor, "usage_hourly", seed["tenant"]))
    assert calls == outcome.plan.accepted * 2


def test_an_event_on_a_finalized_day_is_rejected(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    old = NOW - timedelta(days=3)
    cursor.execute(
        "INSERT INTO apiome.usage_rollup_days (day, rolled_up_at, finalized_at) VALUES (%s, %s, %s)",
        (old.date(), NOW, NOW),
    )
    outcome = _ingest(db, seed, [_event("/pets/1", observed_at=old.isoformat()), _event("/pets/2")])
    assert outcome.plan.rejections == [(0, "day-finalized")] and outcome.plan.accepted == 1


def test_field_presence_keeps_its_denominator(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    cursor.execute("UPDATE apiome.usage_source SET field_capture = true WHERE id = %s", (seed["source"],))
    _ingest(db, seed, [_event("/pets/1", fields={"response": ["/id", "/name"]})])
    _ingest(db, seed, [_event("/pets/2", fields={"response": ["/id"]}), _event("/pets/3", fields={})])
    rows = {
        row["pointer"]: (row["calls_with_field"], row["calls_sampled"])
        for row in _rows(cursor, "usage_field_daily", seed["tenant"])
        if row["direction"] == "response"
    }
    assert rows == {"/id": (2, 3), "/name": (1, 3)}


# ---------------------------------------------------------------------------------------------
# Refusals before the ledger, and the credential path
# ---------------------------------------------------------------------------------------------


def test_unknown_disabled_and_closed_body_sources_are_refused(seeded: Tuple[Any, Any, Dict[str, str]]) -> None:
    db, cursor, seed = seeded
    with pytest.raises(UsageIngestError) as unknown:
        ingest_batch(db, tenant_id=seed["tenant"], source_ref=str(uuid.uuid4()), raw_events=[], digest="0" * 64,
                     api_key_id=None, now=NOW)
    assert unknown.value.status == 404

    with pytest.raises(UsageIngestError) as body:
        _ingest(db, seed, [_event("/pets/1", sample={"request": {"body": "x"}})])
    assert (body.value.status, body.value.code) == (422, "usage-body-not-accepted")

    cursor.execute("UPDATE apiome.usage_source SET enabled = false WHERE id = %s", (seed["source"],))
    with pytest.raises(UsageIngestError) as disabled:
        _ingest(db, seed, [_event("/pets/1")])
    assert disabled.value.status == 403
    assert _rows(cursor, "usage_ingest_batch", seed["tenant"]) == []


def _api_key(cursor: Any, tenant: str, *, kind: str, scopes: List[str], toolset: Optional[str] = None) -> str:
    """Insert an API key (an agent key bound to ``toolset``) and return its plaintext."""
    plaintext = "apk_" + secrets.token_hex(16)
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    columns = ["tenant_id", "name", "key_hash", "key_prefix", "scopes", "kind"]
    values: List[Any] = [tenant, f"{kind} {uuid.uuid4().hex[:6]}", hashed, plaintext[:12] + "...", scopes, kind]
    if kind == "agent":
        columns += ["toolset_id", "tool_allowlist"]
        values += [toolset, json.dumps([])]
    cursor.execute(
        f"INSERT INTO apiome.api_keys ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})",
        values,
    )
    return plaintext


def test_the_route_takes_a_usage_ingest_key_and_never_an_agent_key(
    seeded: Tuple[Any, Any, Dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, cursor, seed = seeded
    cursor.execute("SELECT slug FROM apiome.tenants WHERE id = %s", (seed["tenant"],))
    slug = cursor.fetchone()["slug"]
    ingest_key = _api_key(cursor, seed["tenant"], kind="workspace", scopes=["usage:ingest"])
    cursor.execute(
        "INSERT INTO apiome.agent_toolsets (tenant_id, version_id) VALUES (%s, %s) RETURNING id::text AS id",
        (seed["tenant"], seed["published"]),
    )
    toolset = cursor.fetchone()["id"]
    agent_key = _api_key(cursor, seed["tenant"], kind="agent", scopes=["agent:invoke"], toolset=toolset)

    # An agent key can never carry the scope (V269 kind/scope rule, restated by V291).
    cursor.execute("SAVEPOINT agent_scope")
    with pytest.raises(Exception, match="api_keys_kind_scopes_ck"):
        _api_key(cursor, seed["tenant"], kind="agent", scopes=["usage:ingest"], toolset=toolset)
    cursor.execute("ROLLBACK TO SAVEPOINT agent_scope")

    monkeypatch.setattr("app.auth.db", db)
    monkeypatch.setattr("app.usage_ingest_routes.db", db)
    from app.main import app

    client = TestClient(app)
    url = f"/v1/tenants/{slug}/usage/ingest"
    body = {"source_id": seed["source"], "events": [_event("/pets/1")]}

    accepted = client.post(url, json=body, headers={"X-API-Key": ingest_key})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] == 1

    assert client.post(url, json=body, headers={"X-API-Key": agent_key}).status_code == 401
    # The scope admits the ingest door and nothing else.
    assert client.get(f"/v1/projects/{slug}", headers={"X-API-Key": ingest_key}).status_code == 403
