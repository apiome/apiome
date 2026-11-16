"""Usage export, retention and erasure against a live Postgres — RDG-5.4 (#5789).

The acceptance criteria only the real schema (V384), the real ingest and the real routes can prove:

* **erasing a consumer leaves totals unchanged** — per day, operation and status, hourly and daily,
  on an open day and on a finalized one — **and the handle absent from every usage read**: the
  runtime report, the export, the bindings table, the suggested-consumer rows, the graph edges;
* the erasure is audited as ``usage.consumer.erased``;
* **a retention value above the tier cap is refused with the cap named**, and a lowered one makes
  ``purge_usage`` delete what the tier alone would have kept;
* **the export matches the totals** the runtime reads report for the same window;
* a body-sample window opens only with the acknowledgement, on a source and on an agent toolset,
  and the database's own 7-day trigger agrees.

Everything runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_consumer_binding_db``). Skipped when no database is reachable or V384 is not applied.
"""

from __future__ import annotations

import csv
import io
from contextlib import ExitStack
from datetime import timedelta
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import patch

import pytest

from app.usage_controls import BODY_SAMPLE_ACKNOWLEDGEMENT
from tests import test_consumer_binding_db as binding_db
from tests import test_usage_index_db as index_db

tx = binding_db.tx
seeded = binding_db.seeded
stack = binding_db.stack
NOW = binding_db.NOW
GET_PET = binding_db.GET_PET
ORDERS = binding_db.ORDERS
_event = binding_db._event
_ingest = binding_db._ingest
_hint = binding_db._hint
_bind = binding_db._bind
_rollup = binding_db._rollup

pytestmark = pytest.mark.requires_db


@pytest.fixture
def controls(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The binding stack with the RDG-5.4 routes also running on the test transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.usage_retention_setting') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V384 not applied")
    with ExitStack() as patches:
        patches.enter_context(patch("app.usage_controls_routes.db", stack["db"]))
        patches.enter_context(patch("app.usage_controls_routes.enforce_permission", return_value=None))
        patches.enter_context(
            patch("app.usage_controls_routes.resolve_project", return_value={"id": stack["seed"]["project"]})
        )
        yield stack


def _totals(cursor: Any, table: str, tenant: str) -> Dict[Tuple[Any, ...], Tuple[int, int, int]]:
    """Per grain without the consumer: (calls, latency sum, request bytes)."""
    when = "hour" if table == "usage_hourly" else "day"
    cursor.execute(
        f"""SELECT {when} AS t, operation_key, status_code, sum(calls)::bigint AS calls,
                   sum(latency_sum_ms)::bigint AS lat, sum(request_bytes)::bigint AS req
            FROM apiome.{table} WHERE tenant_id = %s GROUP BY 1, 2, 3""",
        (tenant,),
    )
    return {(r["t"], r["operation_key"], r["status_code"]): (r["calls"], r["lat"], r["req"]) for r in cursor.fetchall()}


def _binding_ids(cursor: Any, consumer: str) -> List[str]:
    cursor.execute("SELECT id::text AS id FROM apiome.usage_consumer_binding WHERE consumer_id = %s", (consumer,))
    return [r["id"] for r in cursor.fetchall()]


def _export(stack: Dict[str, Any], fmt: str, days: int = 30) -> Any:
    response = stack["client"].get(
        f"/v1/tenants/t/projects/{stack['seed']['project']}/usage/export", params={"format": fmt, "days": days}
    )
    assert response.status_code == 200, response.text
    return response.json() if fmt == "json" else list(csv.DictReader(io.StringIO(response.text)))


def _seed_traffic(stack: Dict[str, Any]) -> Dict[str, Any]:
    """Billing (header + user agent bindings) and anonymous traffic today, plus a finalized old day."""
    cursor, seed, db = stack["cursor"], stack["seed"], stack["db"]
    header = _bind(
        stack, "billing-service", {"kind": "header", "name": "X-Client-Id", "value": binding_db.HEADER_VALUE}
    )
    _bind(stack, "billing-service", {"kind": "user_agent", "name": "billing-service/*"})
    _bind(stack, "search", {"kind": "user_agent", "name": "search/*"})
    hint = _hint(stack, "header", binding_db.HEADER_VALUE)
    events = (
        [_event("/pets/7", consumer_hint=hint) for _ in range(4)]
        + [_event("/pets/7", user_agent="billing-service/2.0", status=500) for _ in range(2)]
        + [_event("/pets/7") for _ in range(3)]
        + [_event("/users/9/orders", user_agent="search/1.0") for _ in range(5)]
    )
    _ingest(db, seed, events)
    # A finalized day, ten days ago: billing and anonymous rows of the same grain, so the erasure
    # must merge them on a day that takes no new counts.
    old = NOW - timedelta(days=10)
    cursor.execute(
        """INSERT INTO apiome.usage_hourly (tenant_id, project_id, source_id, environment, hour, operation_key,
               status_code, consumer_binding_id, calls, latency_buckets, latency_sum_ms, latency_max_ms,
               request_bytes)
           VALUES (%(t)s, %(p)s, %(s)s, 'prod', %(h)s, %(op)s, 200, %(b)s, 6, %(bk6)s, 60, 20, 600),
                  (%(t)s, %(p)s, %(s)s, 'prod', %(h)s, %(op)s, 200, NULL, 4, %(bk4)s, 40, 30, 400)""",
        {
            "t": seed["tenant"],
            "p": seed["project"],
            "s": seed["source"],
            "h": old,
            "op": GET_PET,
            "b": header["id"],
            "bk6": index_db._buckets(b2=6),
            "bk4": index_db._buckets(b3=4),
        },
    )
    _rollup(cursor)
    # The suggested-consumer row that carried the header hash before it was bound.
    cursor.execute(
        """INSERT INTO apiome.usage_unattributed_client_daily (tenant_id, project_id, day, client_kind, client_key,
               calls, first_seen_at, last_seen_at)
           VALUES (%s, %s, %s, 'header', %s, 2, %s, %s)""",
        (seed["tenant"], seed["project"], old.date(), hint["hmac"], old, old),
    )
    return {"old": old, "hint": hint}


def test_erasing_a_consumer_keeps_totals_and_removes_its_handle_from_every_usage_read(controls: Dict[str, Any]) -> None:
    stack, cursor, seed = controls, controls["cursor"], controls["seed"]
    _seed_traffic(stack)
    billing = stack["consumers"]["billing-service"]
    bindings = _binding_ids(cursor, billing)
    hourly_before = _totals(cursor, "usage_hourly", seed["tenant"])
    daily_before = _totals(cursor, "usage_daily", seed["tenant"])
    assert binding_db._runtime(stack, "billing-service")["used_undeclared"]
    assert any(row["consumer"] == "billing-service" for row in _export(stack, "csv"))
    cursor.execute(
        "SELECT finalized_at FROM apiome.usage_rollup_days WHERE day = %s", ((NOW - timedelta(days=10)).date(),)
    )
    assert cursor.fetchone()["finalized_at"] is not None

    response = stack["client"].delete(f"{stack['base']}/billing-service/bindings", params={"erase": "true"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["erased"] is True and result["bindings"] == 2
    assert result["calls"] == 12 and result["unattributed_rows"] == 1

    # Totals per hour / day, operation and status are unchanged, at both grains.
    assert _totals(cursor, "usage_hourly", seed["tenant"]) == hourly_before
    assert _totals(cursor, "usage_daily", seed["tenant"]) == daily_before
    # Recomputing the open day from the re-attributed hourly rows still matches.
    _rollup(cursor)
    assert _totals(cursor, "usage_daily", seed["tenant"]) == daily_before

    # The handle is gone from every read.
    assert _binding_ids(cursor, billing) == []
    for table in ("usage_hourly", "usage_daily"):
        cursor.execute(
            f"SELECT count(*) AS n FROM apiome.{table} WHERE consumer_binding_id = ANY(%s::uuid[])", (bindings,)
        )
        assert cursor.fetchone()["n"] == 0
    runtime = binding_db._runtime(stack, "billing-service")
    assert runtime["declared_and_used"] == [] and runtime["used_undeclared"] == []
    assert all(row["consumer"] != "billing-service" for row in _export(stack, "csv"))
    cursor.execute(
        "SELECT count(*) AS n FROM apiome.usage_unattributed_client_daily WHERE tenant_id = %s", (seed["tenant"],)
    )
    assert cursor.fetchone()["n"] == 0
    cursor.execute("SELECT runtime_last_seen_at FROM apiome.consumer WHERE id = %s", (billing,))
    assert cursor.fetchone()["runtime_last_seen_at"] is None
    # Another consumer is untouched, and the erasure left the final day closed to new counts.
    assert binding_db._calls(binding_db._runtime(stack, "search"), "used_undeclared") == {ORDERS: 5}
    assert "finalized" in index_db._refused(
        cursor,
        """INSERT INTO apiome.usage_hourly (tenant_id, project_id, source_id, environment, hour, operation_key,
               status_code, calls, latency_buckets, latency_sum_ms, latency_max_ms)
           VALUES (%s, %s, %s, 'prod', %s, %s, 201, 1, %s, 1, 1)""",
        (seed["tenant"], seed["project"], seed["source"], NOW - timedelta(days=10), GET_PET, index_db._buckets(b0=1)),
    )
    cursor.execute(
        "SELECT action, detail FROM apiome.access_audit WHERE tenant_id = %s AND action = 'usage.consumer.erased'",
        (seed["tenant"],),
    )
    audited = cursor.fetchall()
    assert len(audited) == 1 and audited[0]["detail"]["consumer"] == "billing-service"


def test_deleting_without_erase_keeps_history_attributed(controls: Dict[str, Any]) -> None:
    stack = controls
    _seed_traffic(stack)
    response = stack["client"].delete(f"{stack['base']}/billing-service/bindings")
    assert response.status_code == 200 and response.json()["bindings"] == 2
    assert any(row["consumer"] == "billing-service" for row in _export(stack, "csv"))


def test_the_export_matches_the_runtime_totals_of_the_same_window(controls: Dict[str, Any]) -> None:
    stack, cursor, seed = controls, controls["cursor"], controls["seed"]
    _seed_traffic(stack)
    document = _export(stack, "json", days=30)
    cursor.execute(
        """SELECT sum(calls)::bigint AS calls, sum(errors)::bigint AS errors, count(*) AS n FROM apiome.usage_daily
           WHERE tenant_id = %s AND project_id = %s AND day > %s""",
        (seed["tenant"], seed["project"], NOW.date() - timedelta(days=30)),
    )
    index = cursor.fetchone()
    assert document["totals"] == {"rows": index["n"], "calls": index["calls"], "errors": index["errors"]}
    # The runtime reads (per consumer, plus anonymous) add up to the same calls.
    observed = sum(
        sum(
            op["calls"]
            for side in ("declared_and_used", "used_undeclared")
            for op in binding_db._runtime(stack, slug)[side]
        )
        for slug in ("billing-service", "search", "anonymous")
    )
    assert observed == document["totals"]["calls"] == 24
    by_consumer: Dict[str, int] = {}
    for row in document["rows"]:
        by_consumer[row["consumer"]] = by_consumer.get(row["consumer"], 0) + row["calls"]
    assert by_consumer == {"billing-service": 12, "search": 5, "anonymous": 7}
    assert not any("hmac" in key or "binding" in key for key in document["rows"][0])


def test_retention_is_refused_above_the_cap_and_a_lower_value_drives_the_purge(controls: Dict[str, Any]) -> None:
    stack, cursor = controls, controls["cursor"]
    seed = index_db._tenant(cursor, "paid")
    auth = {"tenant_id": seed["tenant"], "user_id": None, "auth_method": "jwt"}
    from app.auth import validate_authentication
    from app.main import app

    app.dependency_overrides[validate_authentication] = lambda: auth
    client = stack["client"]
    read = client.get("/v1/tenants/t/usage/retention").json()
    assert read["caps"] == {"hourlyDays": 30, "rollupDays": 395}
    assert read["effective"] == read["caps"] and read["sampleRetentionDays"] == 7

    refused = client.put("/v1/tenants/t/usage/retention", json={"hourlyDays": 31})
    assert refused.status_code == 422
    assert "usage_hourly_retention_days may be at most 30 days" in refused.json()["detail"]["message"]

    old = NOW - timedelta(days=10)
    index_db._hourly(cursor, seed, old)
    cursor.execute("SELECT apiome.rollup_usage_days(%s, %s::interval)", (NOW, "6 hours"))
    cursor.execute("SELECT apiome.purge_usage(%s) AS r", (NOW,))
    assert index_db._count(cursor, "usage_hourly", seed["tenant"]) == 1  # 10 days < the Paid cap of 30

    lowered = client.put("/v1/tenants/t/usage/retention", json={"hourlyDays": 3, "rollupDays": 200})
    assert lowered.status_code == 200, lowered.text
    assert lowered.json()["effective"] == {"hourlyDays": 3, "rollupDays": 200}
    cursor.execute("SELECT apiome.purge_usage(%s) AS r", (NOW,))
    assert index_db._count(cursor, "usage_hourly", seed["tenant"]) == 0
    assert index_db._count(cursor, "usage_daily", seed["tenant"]) == 1  # rollups keep their own, longer, retention

    # A downgrade below the stored setting is honoured by the purge, whatever the setting says.
    cursor.execute(
        "UPDATE apiome.usage_retention_setting SET rollup_retention_days = 5000 WHERE tenant_id = %s", (seed["tenant"],)
    )
    cursor.execute("SELECT rollup_cutoff FROM apiome.usage_retention(%s) WHERE tenant_id = %s", (NOW, seed["tenant"]))
    assert cursor.fetchone()["rollup_cutoff"] == NOW.date() - timedelta(days=395)


def test_a_body_sample_window_opens_only_with_the_acknowledgement(controls: Dict[str, Any]) -> None:
    stack, cursor, seed = controls, controls["cursor"], controls["seed"]
    path = f"/v1/tenants/t/projects/{seed['project']}/usage/sources/{seed['source']}"
    until = (NOW + timedelta(days=30)).isoformat()
    window = {"rate": 0.05, "until": (index_db.datetime.now(index_db.timezone.utc) + timedelta(days=6)).isoformat()}

    assert stack["client"].patch(path, json={"bodySamples": window}).status_code == 422
    too_far = stack["client"].patch(
        path, json={"bodySamples": {"rate": 0.01, "until": until, "acknowledgement": BODY_SAMPLE_ACKNOWLEDGEMENT}}
    )
    assert too_far.status_code == 422 and "7 days" in too_far.json()["detail"]["message"]
    opened = stack["client"].patch(
        path,
        json={
            "samplingRate": 0.5,
            "fieldCapture": True,
            "bodySamples": {**window, "acknowledgement": BODY_SAMPLE_ACKNOWLEDGEMENT},
        },
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["bodySamples"]["open"] is True and opened.json()["samplingRate"] == 0.5
    listed = stack["client"].get(f"/v1/tenants/t/projects/{seed['project']}/usage/sources").json()
    assert listed["sources"][0]["bodySamples"]["rate"] == 0.05
    closed = stack["client"].patch(path, json={"bodySamples": {"rate": 0}})
    closed_samples = closed.json()["bodySamples"]
    assert (closed_samples["rate"], closed_samples["until"], closed_samples["open"]) == (0.0, None, False)

    cursor.execute(
        "INSERT INTO apiome.agent_toolsets (tenant_id, version_id) VALUES (%s, %s) RETURNING id::text AS id",
        (seed["tenant"], seed["published"]),
    )
    toolset = cursor.fetchone()["id"]
    toolset_path = f"/v1/tenants/t/agent-toolsets/{toolset}/body-samples"
    assert stack["client"].patch(toolset_path, json={**window, "rate": 0.5}).status_code == 422
    captured = stack["client"].patch(
        toolset_path, json={**window, "rate": 0.5, "acknowledgement": BODY_SAMPLE_ACKNOWLEDGEMENT}
    )
    assert captured.status_code == 200, captured.text
    assert captured.json()["bodySamples"]["rate"] == 0.5 and captured.json()["bodySamples"]["open"] is True
    listed = stack["client"].get(f"/v1/tenants/t/projects/{seed['project']}/usage/sources").json()
    assert listed["agentToolsets"][0]["id"] == toolset and listed["agentToolsets"][0]["versionLabel"] == "1.0.0"
    cursor.execute(
        """SELECT count(*) AS n FROM apiome.access_audit WHERE tenant_id = %s
           AND action IN ('usage.source.update', 'agent.toolset.body_samples.update')""",
        (seed["tenant"],),
    )
    assert cursor.fetchone()["n"] == 3
