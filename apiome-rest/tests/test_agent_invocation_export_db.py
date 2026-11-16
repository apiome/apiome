"""Agent invocation audit export against a live Postgres — ATQ-4.5 (#5847).

The acceptance criteria only the real schema (V271), the real rollup sweep and the real route can
prove:

* **an export of a finalized day equals a direct query row for row**, in both formats, and holds
  only the authenticated tenant's rows;
* **a non-final day is refused with the finalization time** (``409``);
* **a day past retention is ``410``** with the plan's retention stated;
* **the sweep finds no secret or ciphertext in any export**: neither the agent key's plaintext,
  its stored hash, its prefix, nor a captured body sample appears in a JSON Lines or CSV export;
* the export is audited as ``agent.invocations.export``.

Everything runs inside one always-rolled-back transaction (the ``seeded`` fixture of
``test_usage_ingest_db``). Skipped when no database is reachable or V271 is not applied.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agent_invocation_export import (
    AUDIT_EXPORT,
    CODE_DAY_NOT_FINAL,
    CODE_DAY_PAST_RETENTION,
    EXTRA_COLUMNS,
    export_record,
    key_fingerprint,
)
from app.auth import validate_authentication
from app.main import app
from tests import test_usage_ingest_db as ingest_db

tx = ingest_db.tx
seeded = ingest_db.seeded
_api_key = ingest_db._api_key

pytestmark = pytest.mark.requires_db

#: A body sample only the opt-in capture table holds; it must never reach an export.
SAMPLE_MARKER = "sample-body-SECRET-7c1e"


@pytest.fixture
def agent(seeded: Tuple[Any, Any, Dict[str, str]]) -> Iterator[Dict[str, Any]]:
    """The seeded (Free, 7-day) tenant with an agent key, a finalized day of calls and a client."""
    db, cursor, seed = seeded
    cursor.execute("SELECT to_regclass('apiome.agent_invocation_rollup_days') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V271 not applied")
    cursor.execute(
        "INSERT INTO apiome.agent_toolsets (tenant_id, version_id) VALUES (%s, %s) RETURNING id::text AS id",
        (seed["tenant"], seed["published"]),
    )
    toolset = cursor.fetchone()["id"]
    plaintext = _api_key(cursor, seed["tenant"], kind="agent", scopes=["agent:invoke"], toolset=toolset)
    cursor.execute(
        """SELECT id::text AS id, name, key_hash, key_prefix
           FROM apiome.api_keys WHERE tenant_id = %s AND kind = 'agent'""",
        (seed["tenant"],),
    )
    key = dict(cursor.fetchone())

    now = datetime.now(timezone.utc)
    final_day = now.date() - timedelta(days=2)
    start = datetime.combine(final_day, datetime.min.time(), tzinfo=timezone.utc)
    invocation_ids: List[str] = []
    for n, (outcome, error_code, status) in enumerate(
        [("success", None, 200), ("upstream_error", "upstream_timeout", None), ("quota_rejected", "quota.daily", None)]
        * 3
    ):
        cursor.execute(
            """INSERT INTO apiome.agent_invocations
                   (tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms, outcome,
                    error_code, http_status, request_bytes, response_bytes, sampled)
               VALUES (%s, %s, %s, 'listPets', 'prod', %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id::text AS id""",
            (
                seed["tenant"], key["id"], toolset, start + timedelta(minutes=7 * n), 30 + n, outcome,
                error_code, status, 10 + n, 200 + n, n == 0,
            ),
        )  # fmt: skip
        invocation_ids.append(cursor.fetchone()["id"])
    cursor.execute(
        """INSERT INTO apiome.agent_invocation_samples (invocation_id, tenant_id, request_body, response_body)
           VALUES (%s, %s, %s, %s)""",
        (invocation_ids[0], seed["tenant"], json.dumps({"q": SAMPLE_MARKER}), SAMPLE_MARKER),
    )
    # Today's call keeps today open; another tenant's call on the final day must not leak.
    cursor.execute(
        """INSERT INTO apiome.agent_invocations
               (tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms, outcome,
                request_bytes, response_bytes)
           VALUES (%s, %s, %s, 'listPets', 'mock', %s, 5, 'success', 1, 1)""",
        (seed["tenant"], key["id"], toolset, now - timedelta(minutes=1)),
    )
    other = ingest_db._tenant(cursor)["tenant"]
    cursor.execute(
        """INSERT INTO apiome.agent_invocations
               (tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms, outcome,
                request_bytes, response_bytes)
           VALUES (%s, %s, %s, 'otherTenantTool', 'prod', %s, 5, 'success', 1, 1)""",
        (other, str(uuid.uuid4()), str(uuid.uuid4()), start + timedelta(hours=1)),
    )
    # The real sweep: rolls up every open day and finalizes those that ended > 6 h ago.
    cursor.execute("DELETE FROM apiome.agent_invocation_rollup_days")
    cursor.execute("SELECT apiome.rollup_agent_invocation_days(%s)", (now,))

    auth = {"tenant_id": seed["tenant"], "user_id": None, "user_email": "ops@example.com", "auth_method": "jwt"}
    app.dependency_overrides[validate_authentication] = lambda: auth
    with (
        patch("app.agent_invocation_export_routes.db", db),
        patch("app.usage_controls_routes.db", db),
        patch("app.agent_invocation_export_routes.enforce_permission", return_value=None),
    ):
        yield {
            "db": db,
            "cursor": cursor,
            "seed": seed,
            "key": key,
            "plaintext": plaintext,
            "final_day": final_day,
            "today": now.date(),
            "client": TestClient(app),
        }
    app.dependency_overrides.clear()


def _export(agent: Dict[str, Any], day: date, fmt: str = "jsonl") -> Any:
    return agent["client"].get("/v1/tenants/t/agent-invocations/export", params={"day": day.isoformat(), "format": fmt})


def _direct(agent: Dict[str, Any], day: date) -> List[Dict[str, Any]]:
    """The day's stored rows straight from the table, with the key name, in export order."""
    cursor = agent["cursor"]
    cursor.execute(
        """SELECT i.*, ak.name AS key_name
           FROM apiome.agent_invocations i
           LEFT JOIN apiome.api_keys ak ON ak.id = i.key_id AND ak.tenant_id = i.tenant_id
           WHERE i.tenant_id = %s AND i.invoked_day = %s
           ORDER BY i.invoked_at, i.id""",
        (agent["seed"]["tenant"], day),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    columns = [name for name in rows[0] if name not in EXTRA_COLUMNS] + list(EXTRA_COLUMNS)
    return [export_record(row, columns) for row in rows]


def test_a_finalized_day_equals_a_direct_query_row_for_row(agent: Dict[str, Any]) -> None:
    expected = _direct(agent, agent["final_day"])
    assert len(expected) == 9

    jsonl = _export(agent, agent["final_day"])
    assert jsonl.status_code == 200, jsonl.text
    records = [json.loads(line) for line in jsonl.text.splitlines()]
    assert records == expected
    assert list(records[0]) == list(expected[0])  # stored column order, then the extras
    assert {r["tenant_id"] for r in records} == {agent["seed"]["tenant"]}
    assert {r["key_name"] for r in records} == {agent["key"]["name"]}
    assert {r["key_fingerprint"] for r in records} == {key_fingerprint(agent["key"]["id"])}

    as_csv = _export(agent, agent["final_day"], "csv")
    assert as_csv.status_code == 200, as_csv.text
    rows = list(csv.DictReader(io.StringIO(as_csv.text)))
    assert [r["id"] for r in rows] == [r["id"] for r in expected]
    assert list(rows[0]) == list(expected[0])
    assert [r["outcome"] for r in rows] == [r["outcome"] for r in expected]
    assert rows[0]["sampled"] == "true" and rows[0]["error_code"] == ""


def test_the_export_is_audited(agent: Dict[str, Any]) -> None:
    assert _export(agent, agent["final_day"]).status_code == 200
    cursor = agent["cursor"]
    cursor.execute(
        "SELECT action, target, detail FROM apiome.access_audit WHERE tenant_id = %s AND action = %s",
        (agent["seed"]["tenant"], AUDIT_EXPORT),
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["target"] == agent["final_day"].isoformat()
    assert rows[0]["detail"] == {"day": agent["final_day"].isoformat(), "format": "jsonl"}


def test_a_day_that_is_not_final_is_refused_with_the_finalization_time(agent: Dict[str, Any]) -> None:
    response = _export(agent, agent["today"])
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == CODE_DAY_NOT_FINAL
    tomorrow = datetime.combine(agent["today"] + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    assert detail["finalizesAfter"] == (tomorrow + timedelta(hours=6)).isoformat()


def test_a_day_past_retention_is_410(agent: Dict[str, Any]) -> None:
    response = _export(agent, agent["today"] - timedelta(days=30))
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == CODE_DAY_PAST_RETENTION
    assert detail["retentionDays"] == 7  # an unlicensed tenant gets the Free tier
    assert detail["oldestExportableDay"] == (agent["today"] - timedelta(days=6)).isoformat()


def test_the_sweep_finds_no_secret_or_ciphertext_in_any_export(agent: Dict[str, Any]) -> None:
    forbidden = [
        agent["plaintext"],
        agent["key"]["key_hash"],
        agent["key"]["key_prefix"],
        agent["plaintext"][4:],  # the secret without its scheme prefix
        SAMPLE_MARKER,
        "otherTenantTool",
    ]
    for fmt in ("jsonl", "csv"):
        response = _export(agent, agent["final_day"], fmt)
        assert response.status_code == 200, response.text
        for needle in forbidden:
            assert needle not in response.text, f"{needle!r} leaked into the {fmt} export"
