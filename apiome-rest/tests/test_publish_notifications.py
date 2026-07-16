"""Publish-event webhook fan-out with classified changelog payloads (CTG-3.3, #4477)."""

from unittest.mock import MagicMock, patch

import pytest

from app.publish_notifications import (
    EVENT_TYPE_VERSION_PUBLISHED,
    TOP_CHANGES_LIMIT,
    build_publish_notification,
    notify_version_published,
    notify_version_published_on_publish,
    should_deliver_publish_event,
)

TENANT = "550e8400-e29b-41d4-a716-446655440000"
PROJECT = "33333333-3333-3333-3333-333333333333"
REVISION = "44444444-4444-4444-4444-444444444444"


def _entry(severity="breaking", rule_id="ctg.path.removed", pointer="/paths/~1pets"):
    return {
        "severity": severity,
        "pathGroup": pointer,
        "pointer": pointer,
        "ruleId": rule_id,
        "changeKind": "removed",
        "summary": f"{severity} change at {pointer}",
        "before": {},
        "after": None,
        "unclassified": False,
        "fromVersion": "1.0.0",
        "toVersion": "2.0.0",
    }


def _changelog_row(
    *,
    status="ready",
    max_severity="breaking",
    entries=None,
    counts=None,
    extra_json=None,
):
    changelog_json = {
        "schemaVersion": "ctg.changelog.v1",
        "fromVersion": "1.0.0",
        "toVersion": "2.0.0",
        "counts": counts
        if counts is not None
        else {"breaking": 1, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": 1},
        "maxSeverity": max_severity,
        "entries": entries if entries is not None else [_entry()],
    }
    if extra_json:
        changelog_json.update(extra_json)
    return {
        "id": "55555555-5555-5555-5555-555555555555",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "published_revision_id": REVISION,
        "baseline_revision_id": "66666666-6666-6666-6666-666666666666",
        "changelog_json": changelog_json,
        "max_severity": max_severity,
        "status": status,
        "error": None,
    }


# --- should_deliver_publish_event ------------------------------------------


@pytest.mark.parametrize("max_severity", ["breaking", "non-breaking", "docs-only", None])
@pytest.mark.parametrize("status", ["ready", "initial", "failed", None])
def test_no_filter_always_delivers(max_severity, status):
    assert should_deliver_publish_event(
        None, max_severity=max_severity, changelog_status=status
    )


@pytest.mark.parametrize(
    ("min_severity", "max_severity", "expected"),
    [
        ("breaking", "breaking", True),
        ("breaking", "non-breaking", False),
        ("breaking", "docs-only", False),
        ("non-breaking", "breaking", True),
        ("non-breaking", "non-breaking", True),
        ("non-breaking", "docs-only", False),
        ("docs-only", "breaking", True),
        ("docs-only", "non-breaking", True),
        ("docs-only", "docs-only", True),
    ],
)
def test_threshold_matrix_on_ready_changelog(min_severity, max_severity, expected):
    assert (
        should_deliver_publish_event(
            min_severity, max_severity=max_severity, changelog_status="ready"
        )
        is expected
    )


@pytest.mark.parametrize("min_severity", ["breaking", "non-breaking", "docs-only"])
def test_filtered_subscription_skips_initial_publication(min_severity):
    assert not should_deliver_publish_event(
        min_severity, max_severity=None, changelog_status="initial"
    )


@pytest.mark.parametrize("min_severity", ["breaking", "non-breaking", "docs-only"])
def test_filtered_subscription_skips_empty_ready_changelog(min_severity):
    assert not should_deliver_publish_event(
        min_severity, max_severity=None, changelog_status="ready"
    )


@pytest.mark.parametrize("status", ["failed", None])
def test_filtered_subscription_fails_safe_when_unclassified(status):
    # Classification failed or never ran: we cannot prove the publish is below
    # the threshold, so it must be delivered (taxonomy fail-safe parity).
    assert should_deliver_publish_event(
        "breaking", max_severity=None, changelog_status=status
    )


def test_unrecognized_threshold_fails_open():
    assert should_deliver_publish_event(
        "catastrophic", max_severity="docs-only", changelog_status="ready"
    )


# --- build_publish_notification ---------------------------------------------


def test_payload_shape_with_ready_changelog():
    payload = build_publish_notification(
        project_id=PROJECT,
        version_record_id=REVISION,
        version_label="2.0.0",
        actor_id="user-a",
        changelog_row=_changelog_row(),
    )
    assert payload["event"] == EVENT_TYPE_VERSION_PUBLISHED
    assert payload["projectId"] == PROJECT
    assert payload["versionId"] == REVISION
    assert payload["versionLabel"] == "2.0.0"
    assert payload["publishedBy"] == "user-a"
    assert payload["maxSeverity"] == "breaking"

    cl = payload["changelog"]
    assert cl["status"] == "ready"
    assert cl["maxSeverity"] == "breaking"
    assert cl["schemaVersion"] == "ctg.changelog.v1"
    assert cl["fromVersion"] == "1.0.0"
    assert cl["toVersion"] == "2.0.0"
    assert cl["counts"]["breaking"] == 1
    assert cl["totalChanges"] == 1
    assert cl["topChangesTruncated"] is False
    assert cl["topChanges"] == [
        {
            "severity": "breaking",
            "ruleId": "ctg.path.removed",
            "path": "/paths/~1pets",
            "pointer": "/paths/~1pets",
            "summary": "breaking change at /paths/~1pets",
        }
    ]


def test_payload_truncates_top_changes():
    entries = [
        _entry(pointer=f"/paths/~1pets~1{i}") for i in range(TOP_CHANGES_LIMIT + 5)
    ]
    payload = build_publish_notification(
        project_id=PROJECT,
        version_record_id=REVISION,
        changelog_row=_changelog_row(entries=entries),
    )
    cl = payload["changelog"]
    assert len(cl["topChanges"]) == TOP_CHANGES_LIMIT
    assert cl["totalChanges"] == TOP_CHANGES_LIMIT + 5
    assert cl["topChangesTruncated"] is True
    # Most-severe-first ordering from the stored changelog is preserved.
    assert cl["topChanges"][0]["pointer"] == "/paths/~1pets~10"


def test_payload_for_initial_publication_marker():
    row = _changelog_row(
        status="initial",
        max_severity=None,
        entries=[],
        counts={"breaking": 0, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": 0},
        extra_json={"initialPublication": True, "fromVersion": None},
    )
    payload = build_publish_notification(
        project_id=PROJECT, version_record_id=REVISION, changelog_row=row
    )
    assert payload["maxSeverity"] is None
    cl = payload["changelog"]
    assert cl["status"] == "initial"
    assert cl["initialPublication"] is True
    assert cl["topChanges"] == []
    assert cl["totalChanges"] == 0


def test_payload_without_changelog_row():
    payload = build_publish_notification(project_id=PROJECT, version_record_id=REVISION)
    assert payload["maxSeverity"] is None
    assert payload["changelog"]["status"] == "unavailable"
    assert payload["changelog"]["topChanges"] == []
    assert "versionLabel" not in payload
    assert "publishedBy" not in payload


def test_payload_for_failed_classification():
    row = _changelog_row(status="failed", max_severity=None, entries=[], counts={})
    row["changelog_json"] = None
    row["error"] = "boom"
    payload = build_publish_notification(
        project_id=PROJECT, version_record_id=REVISION, changelog_row=row
    )
    cl = payload["changelog"]
    assert cl["status"] == "failed"
    assert cl["counts"] == {}
    assert cl["topChanges"] == []


# --- notify_version_published ------------------------------------------------


def _subs(*pairs):
    return [{"id": sid, "min_severity": sev} for sid, sev in pairs]


def test_fanout_filters_by_min_severity():
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_filters.return_value = _subs(
        ("aaaaaaaa-0000-0000-0000-000000000001", None),
        ("aaaaaaaa-0000-0000-0000-000000000002", "breaking"),
        ("aaaaaaaa-0000-0000-0000-000000000003", "docs-only"),
    )
    mdb.enqueue_push_webhook_delivery.side_effect = [
        {"id": "ev-1"},
        {"id": "ev-3"},
    ]

    enqueued = notify_version_published(
        mdb,
        tenant_id=TENANT,
        project_id=PROJECT,
        version_record_id=REVISION,
        version_label="2.0.0",
        changelog_row=_changelog_row(max_severity="non-breaking"),
    )

    # breaking-only subscription is skipped for a non-breaking publish.
    assert enqueued == ["ev-1", "ev-3"]
    called_subs = [
        c.args[1] for c in mdb.enqueue_push_webhook_delivery.call_args_list
    ]
    assert called_subs == [
        "aaaaaaaa-0000-0000-0000-000000000001",
        "aaaaaaaa-0000-0000-0000-000000000003",
    ]
    for c in mdb.enqueue_push_webhook_delivery.call_args_list:
        assert c.args[2] == EVENT_TYPE_VERSION_PUBLISHED
        assert c.args[3]["event"] == EVENT_TYPE_VERSION_PUBLISHED
        assert c.args[3]["maxSeverity"] == "non-breaking"


def test_fanout_unfiltered_subscription_receives_everything():
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_filters.return_value = _subs(
        ("aaaaaaaa-0000-0000-0000-000000000001", None),
    )
    mdb.enqueue_push_webhook_delivery.return_value = {"id": "ev-1"}

    row = _changelog_row(
        status="initial",
        max_severity=None,
        entries=[],
        counts={"total": 0},
        extra_json={"initialPublication": True},
    )
    enqueued = notify_version_published(
        mdb,
        tenant_id=TENANT,
        project_id=PROJECT,
        version_record_id=REVISION,
        changelog_row=row,
    )
    assert enqueued == ["ev-1"]


def test_fanout_survives_listing_failure():
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_filters.side_effect = RuntimeError("db down")
    enqueued = notify_version_published(
        mdb,
        tenant_id=TENANT,
        project_id=PROJECT,
        version_record_id=REVISION,
        changelog_row=_changelog_row(),
    )
    assert enqueued == []
    mdb.enqueue_push_webhook_delivery.assert_not_called()


def test_fanout_skips_failed_enqueue_and_continues():
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_filters.return_value = _subs(
        ("aaaaaaaa-0000-0000-0000-000000000001", None),
        ("aaaaaaaa-0000-0000-0000-000000000002", None),
    )
    mdb.enqueue_push_webhook_delivery.side_effect = [
        ValueError("subscription_inactive"),
        {"id": "ev-2"},
    ]
    enqueued = notify_version_published(
        mdb,
        tenant_id=TENANT,
        project_id=PROJECT,
        version_record_id=REVISION,
        changelog_row=_changelog_row(),
    )
    assert enqueued == ["ev-2"]


# --- notify_version_published_on_publish (background-task entrypoint) --------


def test_on_publish_entrypoint_fans_out_with_changelog():
    with patch("app.publish_notifications.default_db") as mdb:
        mdb.get_version_by_id.return_value = {
            "id": REVISION,
            "published": True,
            "version_id": "2.0.0",
        }
        mdb.get_version_changelog.return_value = _changelog_row()
        mdb.list_active_push_webhook_subscription_filters.return_value = _subs(
            ("aaaaaaaa-0000-0000-0000-000000000001", "breaking"),
        )
        mdb.enqueue_push_webhook_delivery.return_value = {"id": "ev-1"}

        notify_version_published_on_publish(
            tenant_id=TENANT,
            project_id=PROJECT,
            published_revision_id=REVISION,
            actor_id="user-a",
        )

        mdb.get_version_changelog.assert_called_once_with(REVISION, TENANT, PROJECT)
        mdb.enqueue_push_webhook_delivery.assert_called_once()
        payload = mdb.enqueue_push_webhook_delivery.call_args.args[3]
        assert payload["versionLabel"] == "2.0.0"
        assert payload["publishedBy"] == "user-a"
        assert payload["changelog"]["status"] == "ready"


def test_on_publish_entrypoint_skips_unpublished_revision():
    with patch("app.publish_notifications.default_db") as mdb:
        mdb.get_version_by_id.return_value = {"id": REVISION, "published": False}
        notify_version_published_on_publish(
            tenant_id=TENANT,
            project_id=PROJECT,
            published_revision_id=REVISION,
            actor_id=None,
        )
        mdb.enqueue_push_webhook_delivery.assert_not_called()


def test_on_publish_entrypoint_skips_missing_revision():
    with patch("app.publish_notifications.default_db") as mdb:
        mdb.get_version_by_id.return_value = None
        notify_version_published_on_publish(
            tenant_id=TENANT,
            project_id=PROJECT,
            published_revision_id=REVISION,
            actor_id=None,
        )
        mdb.enqueue_push_webhook_delivery.assert_not_called()


def test_on_publish_entrypoint_notifies_even_when_changelog_lookup_fails():
    # A filtered subscription still hears about the publish when classification
    # state cannot be read (fail-safe), and the entrypoint never raises.
    with patch("app.publish_notifications.default_db") as mdb:
        mdb.get_version_by_id.return_value = {
            "id": REVISION,
            "published": True,
            "version_id": "2.0.0",
        }
        mdb.get_version_changelog.side_effect = RuntimeError("db hiccup")
        mdb.list_active_push_webhook_subscription_filters.return_value = _subs(
            ("aaaaaaaa-0000-0000-0000-000000000001", "breaking"),
        )
        mdb.enqueue_push_webhook_delivery.return_value = {"id": "ev-1"}

        notify_version_published_on_publish(
            tenant_id=TENANT,
            project_id=PROJECT,
            published_revision_id=REVISION,
            actor_id=None,
        )

        mdb.enqueue_push_webhook_delivery.assert_called_once()
        payload = mdb.enqueue_push_webhook_delivery.call_args.args[3]
        assert payload["changelog"]["status"] == "unavailable"


def test_on_publish_entrypoint_never_raises():
    with patch("app.publish_notifications.default_db") as mdb:
        mdb.get_version_by_id.side_effect = RuntimeError("total db failure")
        notify_version_published_on_publish(
            tenant_id=TENANT,
            project_id=PROJECT,
            published_revision_id=REVISION,
            actor_id=None,
        )
