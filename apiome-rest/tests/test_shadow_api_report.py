"""The shadow-API report (CDG-1.6, #5957): sections, match tiers, ignore and staleness rules.

Pure tests over plain rows (:func:`app.shadow_api_report.build_shadow_report`); the SQL that loads
them is covered by ``test_shadow_api_report_live.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.shadow_api_report import (
    TIER_HOST,
    TIER_REMOTE_ID,
    TIER_TITLE,
    Endpoint,
    build_shadow_report,
    failing_categories,
    item_endpoints,
    match_item,
    server_endpoint,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
CONNECTOR = {"id": "c1", "name": "Prod Kong", "kind": "kong-admin", "status": "active", "last_success_at": NOW}


def _item(n: int, **fields: Any) -> Dict[str, Any]:
    row = {
        "id": f"i{n}",
        "connector_id": "c1",
        "remote_id": f"svc-{n}",
        "remote_name": f"Service {n}",
        "environment": "prod",
        "hosts": [f"svc{n}.example.com"],
        "base_path": None,
        "remote_revision": None,
        "remote_updated_at": None,
        "imported_revision": None,
        "imported_remote_updated_at": None,
        "status": "discovered",
        "project_id": None,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
    }
    row.update(fields)
    return row


def _entry(project_id: str, name: str, servers: List[str], **fields: Any) -> Dict[str, Any]:
    return {
        "project_id": project_id,
        "name": name,
        "publishable": True,
        "version_id": f"v-{project_id}",
        "version_label": "1.0.0",
        "servers": servers,
        "remote_ids": [],
        "remote_revision": None,
        **fields,
    }


def _report(items, entries, connectors=(CONNECTOR,)):
    return build_shadow_report(connectors=list(connectors), items=items, entries=entries, now=NOW)


def acceptance_fixture():
    """5 gateway items: 2 linked, 1 host-matches a published version, 2 match nothing."""
    items = [
        _item(1, project_id="p-linked-1", status="imported"),
        _item(2, project_id="p-linked-2", status="imported"),
        _item(3, remote_name="Orders gateway", hosts=["orders.example.com"], base_path="/v2"),
        _item(4, remote_name="Legacy billing"),
        _item(5, remote_name="Internal metrics"),
    ]
    entries = [
        _entry("p-linked-1", "Service 1", ["https://svc1.example.com"]),
        _entry("p-linked-2", "Service 2", []),
        _entry("p-orders", "Orders API", ["https://orders.example.com/v2"]),
    ]
    return items, entries


# --- the acceptance criteria -------------------------------------------------------------


def test_two_shadow_apis_and_one_possible_match_with_its_tier():
    report = _report(*acceptance_fixture())
    assert report["summary"] == {"shadow": 2, "possibleMatches": 1, "undeployed": 0, "drift": 0, "ignored": 0}
    assert [row["name"] for row in report["shadow"]] == ["Internal metrics", "Legacy billing"]
    (possible,) = report["possibleMatches"]
    assert possible["itemId"] == "i3"
    assert possible["match"]["tier"] == TIER_HOST and possible["match"]["confidence"] == 0.9
    assert possible["match"]["target"] == {
        "projectId": "p-orders",
        "name": "Orders API",
        "kind": "project",
        "versionId": "v-p-orders",
        "versionLabel": "1.0.0",
    }


def test_nothing_is_linked_by_the_report():
    items, entries = acceptance_fixture()
    before = [dict(i) for i in items]
    _report(items, entries)
    assert items == before  # the report never writes; linking takes a person's click


def test_an_ignored_item_keeps_its_reason_and_reappears_when_its_host_changes():
    ignored = _item(
        4,
        status="ignored",
        ignored_reason="Internal health check",
        ignored_at=NOW,
        ignored_hosts=["svc4.example.com"],
        ignored_base_path=None,
    )
    report = _report([ignored], [])
    assert report["summary"]["shadow"] == 0 and report["ignored"][0]["ignored"]["reason"] == "Internal health check"
    assert report["ignored"][0]["ignored"]["reappeared"] is False

    moved = {**ignored, "hosts": ["svc4.example.net"]}
    report = _report([moved], [])
    assert report["summary"] == {"shadow": 1, "possibleMatches": 0, "undeployed": 0, "drift": 0, "ignored": 0}
    again = report["shadow"][0]["ignored"]
    assert again["reappeared"] is True and again["reason"] == "Internal health check"
    assert again["hosts"] == ["svc4.example.com"]

    repathed = {**ignored, "base_path": "/v2"}
    assert _report([repathed], [])["summary"]["shadow"] == 1


def test_a_failing_connector_reports_its_inventory_as_stale():
    failing = {**CONNECTOR, "status": "failing", "last_success_at": datetime(2026, 10, 17, 9, 30, tzinfo=timezone.utc)}
    report = _report([_item(1)], [], connectors=[failing])
    (stale,) = report["stale"]
    assert stale["since"] == "2026-10-17T09:30:00+00:00"
    assert stale["message"].startswith("Inventory stale since 2026-10-17T09:30:00+00:00")
    assert report["shadow"][0]["stale"] is True
    assert report["connectors"][0]["stale"] is True

    never = {**failing, "last_success_at": None}
    assert "never synced successfully" in _report([], [], connectors=[never])["stale"][0]["message"]


def test_an_empty_inventory_from_a_failing_connector_is_not_a_clean_report():
    failing = {**CONNECTOR, "status": "failing"}
    report = _report([], [], connectors=[failing])
    assert report["summary"]["shadow"] == 0 and report["stale"]


@pytest.mark.parametrize(
    "fail_on,expected",
    [
        (["shadow"], ["shadow"]),
        (["drift"], []),
        (["shadow", "drift"], ["shadow"]),
        (["possible-matches", "undeployed"], ["possible-matches"]),
        ([], []),
    ],
)
def test_failing_categories_are_only_the_named_non_empty_ones(fail_on, expected):
    assert failing_categories(_report(*acceptance_fixture()), fail_on) == expected


# --- sections ----------------------------------------------------------------------------


def test_drift_uses_the_comparator_against_the_catalog_revision():
    linked = _item(1, project_id="p1", status="imported", remote_revision="rev-9", imported_revision="rev-8")
    entries = [_entry("p1", "Service 1", [], publishable=False, remote_revision="rev-8")]
    report = _report([linked], entries)
    (drift,) = report["drift"]
    assert drift["deployedRevision"] == "rev-9" and drift["catalogRevision"] == "rev-8"
    assert drift["catalogItemId"] == "p1" and drift["reasonCode"]

    in_step = {**linked, "remote_revision": "rev-8"}
    assert _report([in_step], entries)["drift"] == []


def test_a_gateway_without_a_revision_signal_never_drifts():
    linked = _item(1, project_id="p1", status="imported", imported_revision="rev2-abc")
    assert _report([linked], [_entry("p1", "Service 1", [])])["drift"] == []


def test_undeployed_lists_described_apis_no_gateway_serves():
    items = [_item(1, project_id="p-served", status="imported"), _item(2, hosts=["near.example.com"])]
    entries = [
        _entry("p-served", "Served", ["https://svc1.example.com"]),
        _entry("p-near", "Near", ["https://near.example.com/api"]),  # host-matched by item 2
        _entry("p-idle", "Idle API", ["https://idle.example.com", "/relative"]),
        _entry("p-schema", "Schema only", []),  # no HTTP server: cannot be served
    ]
    report = _report(items, entries)
    assert [(u["projectId"], u["servers"]) for u in report["undeployed"]] == [("p-idle", ["https://idle.example.com"])]


def test_missing_rows_are_not_served():
    report = _report([_item(1, status="missing")], [])
    assert report["summary"]["shadow"] == 0 and report["connectors"][0]["itemCount"] == 0


def test_filters_are_echoed():
    report = build_shadow_report(
        connectors=[CONNECTOR], items=[], entries=[], connector_filter="c1", environment="prod"
    )
    assert report["filters"] == {"connector": "c1", "environment": "prod"}


# --- matching ----------------------------------------------------------------------------


def test_remote_id_beats_host_and_title():
    item = _item(3, remote_id="orders-api", remote_name="Orders API", hosts=["orders.example.com"])
    entries = [
        _entry("p-host", "Orders API", ["https://orders.example.com"]),
        _entry("p-rid", "Something else", [], publishable=False, remote_ids=["orders-api"]),
    ]
    matches = match_item(item, entries)
    assert [(m["target"]["projectId"], m["tier"]) for m in matches] == [
        ("p-rid", TIER_REMOTE_ID),
        ("p-host", TIER_HOST),
    ]


def test_host_only_and_title_tiers():
    item = _item(3, remote_name="Payments Service", hosts=["pay.example.com"], base_path="/v1/charges")
    host_only = match_item(item, [_entry("p", "Unrelated", ["https://pay.example.com"])])[0]
    assert host_only["tier"] == TIER_HOST and host_only["confidence"] == 0.7
    under_prefix = match_item(item, [_entry("p", "Unrelated", ["https://pay.example.com/v1"])])[0]
    assert under_prefix["confidence"] == 0.7
    other_path = match_item(item, [_entry("p", "Unrelated", ["https://pay.example.com/v2"])])
    assert other_path == []
    title = match_item(_item(9, remote_name="Payments service", hosts=[]), [_entry("p", "Payments Service", [])])[0]
    assert title["tier"] == TIER_TITLE and 0 < title["confidence"] <= 0.5
    assert match_item(_item(9, remote_name="Billing", hosts=[]), [_entry("p", "Payments Service", [])]) == []


def test_projects_rank_before_catalog_items_on_a_tie():
    item = _item(3, hosts=["orders.example.com"])
    entries = [
        _entry("p-cat", "A catalog item", ["https://orders.example.com"], publishable=False),
        _entry("p-proj", "Z project", ["https://orders.example.com"]),
    ]
    assert [m["target"]["projectId"] for m in match_item(item, entries)] == ["p-proj", "p-cat"]


@pytest.mark.parametrize(
    "hosts,base_path,expected",
    [
        (["API.Example.com"], "/v2/", [Endpoint("api.example.com", "/v2")]),
        (["api.example.com:8443"], None, [Endpoint("api.example.com", "")]),
        (
            ["https://abc.execute-api.eu-west-1.amazonaws.com/prod"],
            "/ignored",
            [Endpoint("abc.execute-api.eu-west-1.amazonaws.com", "/prod")],
        ),
        (["", "{host}.example.com"], None, []),
    ],
)
def test_item_endpoints(hosts, base_path, expected):
    assert item_endpoints(hosts, base_path) == expected


def test_server_endpoint_skips_relative_and_templated_servers():
    assert server_endpoint("https://api.example.com/v1/") == Endpoint("api.example.com", "/v1")
    assert server_endpoint("/v1") is None
    assert server_endpoint("https://{region}.example.com") is None
