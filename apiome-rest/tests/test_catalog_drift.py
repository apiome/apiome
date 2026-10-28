"""Catalog drift rules: classification, delivery decisions and payloads (MFI-31.3, #4400).

Pure — real GraphQL models from the import pipeline (dry run), no database and no network.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.catalog_drift import (
    DELIVERY_DAILY_DIGEST,
    MAX_STORED_CHANGES,
    NOTIFICATION_NONE,
    NOTIFICATION_PENDING_DIGEST,
    NOTIFICATION_SENT,
    TOP_FINDINGS,
    DriftSettings,
    classify_drift,
    delivery_for,
    digest_payload,
    drift_link,
    drift_payload,
    drift_summary,
    settings_from_row,
)
from app.catalog_refresh import pipeline_discovery_result

_V1 = "type Order { id: ID! total: Float }\ntype Query { order(id: ID!): Order }\n"
#: v1 minus a field (breaking) plus a query (safe).
_V2 = "type Order { id: ID! }\ntype Query { order(id: ID!): Order orders: [Order!]! }\n"
#: v1 plus a query only (safe).
_V3 = "type Order { id: ID! total: Float }\ntype Query { order(id: ID!): Order orders: [Order!]! }\n"


def _model(sdl: str):
    return pipeline_discovery_result("graphql", sdl.encode(), "schema.graphql").model


# --- classification --------------------------------------------------------------------------


def test_a_removed_field_is_breaking_and_listed_first():
    drift = classify_drift(_model(_V1), _model(_V2))
    assert drift.severity == "breaking"
    assert drift.counts == {"safe": 2, "dangerous": 0, "breaking": 1}
    assert drift.change_count == 3
    first = drift.changes[0]
    assert (first["severity"], first["key"], first["ruleId"]) == ("breaking", "Order.total", "removed-entity")
    assert set(first) == {"severity", "category", "kind", "key", "ruleId", "rationale"}


def test_an_addition_is_safe():
    drift = classify_drift(_model(_V1), _model(_V3))
    assert drift.severity == "safe"
    assert drift.counts["breaking"] == 0 and drift.counts["safe"] >= 1


def test_no_change_is_safe_and_empty():
    drift = classify_drift(_model(_V1), _model(_V1))
    assert (drift.severity, drift.change_count, drift.changes) == ("safe", 0, [])


def test_stored_changes_are_capped_but_counted(monkeypatch):
    from app import breaking_change
    from app.breaking_change import ChangeClassification, ClassificationResult

    many = [
        ChangeClassification(category="field", kind="added", key=f"T.f{i}", severity="safe", rule_id="r", rationale="x")
        for i in range(MAX_STORED_CHANGES + 5)
    ]
    monkeypatch.setattr(
        breaking_change,
        "classify_models",
        lambda a, b: ClassificationResult(
            format="graphql", classifier="builtin", overall_severity="safe", classifications=many
        ),
    )
    drift = classify_drift(object(), object())
    assert drift.change_count == MAX_STORED_CHANGES + 5
    assert len(drift.changes) == MAX_STORED_CHANGES


# --- settings --------------------------------------------------------------------------------


def test_no_row_means_the_defaults():
    settings = settings_from_row(None)
    assert settings == DriftSettings()
    assert (settings.notifies("breaking"), settings.notifies("dangerous"), settings.notifies("safe")) == (
        True,
        True,
        False,
    )


def test_a_row_is_read_and_an_unknown_delivery_falls_back():
    settings = settings_from_row({"notify_safe": True, "delivery": "hourly", "email_enabled": True})
    assert settings.notify_safe and settings.email_enabled
    assert settings.delivery == "immediate"


# --- delivery --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings,severity,trigger,expected",
    [
        (DriftSettings(), "breaking", "sweep", NOTIFICATION_SENT),
        (DriftSettings(), "dangerous", "sweep", NOTIFICATION_SENT),
        (DriftSettings(), "safe", "sweep", NOTIFICATION_NONE),  # safe badges quietly
        (DriftSettings(notify_safe=True), "safe", "sweep", NOTIFICATION_SENT),
        (DriftSettings(notify_breaking=False), "breaking", "sweep", NOTIFICATION_NONE),
        (DriftSettings(), "breaking", "manual", NOTIFICATION_NONE),  # Check now is never announced
        (DriftSettings(delivery=DELIVERY_DAILY_DIGEST), "dangerous", "sweep", NOTIFICATION_PENDING_DIGEST),
        (DriftSettings(delivery=DELIVERY_DAILY_DIGEST), "breaking", "sweep", NOTIFICATION_SENT),
        (
            DriftSettings(delivery=DELIVERY_DAILY_DIGEST, breaking_immediate=False),
            "breaking",
            "sweep",
            NOTIFICATION_PENDING_DIGEST,
        ),
    ],
)
def test_delivery_follows_the_settings(settings, severity, trigger, expected):
    assert delivery_for(settings, severity, trigger) == expected


# --- payloads --------------------------------------------------------------------------------

_WHEN = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _event(**overrides):
    changes = [
        {
            "severity": "breaking",
            "key": f"T.f{i}",
            "ruleId": "removed-entity",
            "rationale": "gone",
            "category": "field",
            "kind": "removed",
        }
        for i in range(TOP_FINDINGS + 2)
    ]
    event = {
        "id": "e-1",
        "tenant_id": "t-1",
        "project_id": "item-1",
        "version_id": "v-2",
        "parent_version_id": "v-1",
        "version_label": "2026-10-27T12:00Z",
        "parent_version_label": "1.0.0",
        "trigger": "sweep",
        "severity": "breaking",
        "counts": {"safe": 0, "dangerous": 0, "breaking": 7},
        "change_count": 7,
        "changes": changes,
        "created_at": _WHEN,
    }
    event.update(overrides)
    return event


def test_the_detected_payload_names_artifact_versions_severity_and_top_findings():
    payload = drift_payload(_event(), {"id": "item-1", "name": "Orders", "slug": "orders"})
    assert payload["event"] == "catalog.drift.detected"
    assert payload["artifact"] == {"kind": "catalog_item", "id": "item-1", "name": "Orders", "slug": "orders"}
    assert payload["versions"] == {
        "from": {"id": "v-1", "label": "1.0.0"},
        "to": {"id": "v-2", "label": "2026-10-27T12:00Z"},
    }
    assert payload["severity"] == "breaking" and payload["changeCount"] == 7
    assert len(payload["topFindings"]) == TOP_FINDINGS
    assert set(payload["topFindings"][0]) == {"severity", "key", "ruleId", "rationale"}
    assert payload["link"] == "/ade/dashboard/catalog/item-1?tab=versions&drift=e-1"
    assert payload["summary"] == "Orders drifted: 7 breaking changes."
    assert payload["detectedAt"] == _WHEN.isoformat()


def test_summary_is_singular_for_one_change():
    assert drift_summary("Orders", "dangerous", {"dangerous": 1}) == "Orders drifted: 1 dangerous change."


def test_the_link_escapes_the_item_id():
    assert drift_link("a/b", "e") == "/ade/dashboard/catalog/a%2Fb?tab=versions&drift=e"


def test_the_digest_totals_events_by_severity():
    entries = [
        _event(id="e-1", item_name="Orders", item_slug="orders"),
        _event(id="e-2", severity="dangerous", project_id="item-2", item_name="Users", item_slug="users"),
    ]
    payload = digest_payload(entries, window_start=_WHEN, window_end=_WHEN)
    assert payload["event"] == "catalog.drift.digest"
    assert payload["eventCount"] == 2
    assert payload["bySeverity"] == {"safe": 0, "dangerous": 1, "breaking": 1}
    assert [e["artifact"]["name"] for e in payload["events"]] == ["Orders", "Users"]
    assert "event" not in payload["events"][0]
