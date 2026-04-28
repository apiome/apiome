"""REPO-12.5 (#2954): repository import notification emission and preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.database import db
from app.repositories import import_notifications as rin


_TENANT = "11111111-2222-3333-4444-555555555555"
_REPO = "aaaaaaaa-bbbb-cccc-dddd-aaaaaaaaaaaa"
_USER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_emit_skips_without_selection_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_insert = MagicMock(return_value=True)
    monkeypatch.setattr(db, "insert_repository_import_notification_if_absent", mock_insert)
    rin.emit_repository_import_notifications(
        tenant_id=_TENANT,
        repository_id=_REPO,
        repository_full_name="o/r",
        import_selection_actor_id=None,
        repository_file_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        import_job_id="job-1",
        source_kind="repository_auto_import",
        state="failed",
        change_model=None,
        conflict_records=None,
        change_report_id=None,
    )
    mock_insert.assert_not_called()


def test_emit_inserts_when_failed_pref_default(monkeypatch: pytest.MonkeyPatch) -> None:
    inserts: list[dict] = []

    def fake_insert(**kwargs):
        inserts.append(kwargs)
        return True

    monkeypatch.setattr(db, "get_user_settings", lambda _u, _t: {})
    monkeypatch.setattr(db, "insert_repository_import_notification_if_absent", fake_insert)
    monkeypatch.setattr(db, "repository_import_notification_email_may_send", lambda _u, _t, _n: True)
    monkeypatch.setattr(db, "touch_repository_import_notification_email_digest", lambda *_a, **_k: None)

    rin.emit_repository_import_notifications(
        tenant_id=_TENANT,
        repository_id=_REPO,
        repository_full_name="acme/api",
        import_selection_actor_id=_USER,
        repository_file_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        import_job_id="job-2",
        source_kind="repository_auto_import",
        state="failed",
        change_model=None,
        conflict_records=None,
        change_report_id=None,
    )
    assert len(inserts) == 1
    assert inserts[0]["import_job_id"] == "job-2"
    assert inserts[0]["recipient_user_id"] == _USER


def test_emit_respects_failed_pref_off(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_insert = MagicMock(return_value=True)
    monkeypatch.setattr(
        db,
        "get_user_settings",
        lambda _u, _t: {"notifications": {"repository": {"auto_import_failed": False}}},
    )
    monkeypatch.setattr(db, "insert_repository_import_notification_if_absent", mock_insert)

    rin.emit_repository_import_notifications(
        tenant_id=_TENANT,
        repository_id=_REPO,
        repository_full_name="acme/api",
        import_selection_actor_id=_USER,
        repository_file_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        import_job_id="job-3",
        source_kind="repository_auto_import",
        state="failed",
        change_model=None,
        conflict_records=None,
        change_report_id=None,
    )
    mock_insert.assert_not_called()


def test_email_digest_window_blocks_within_15_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        db,
        "get_user_settings",
        lambda _u, _t: {
            "notifications": {"repository": {"emailDigestLastSentAt": "2026-04-27T11:59:00+00:00"}}
        },
    )
    assert db.repository_import_notification_email_may_send(_USER, _TENANT, now) is False


def test_email_digest_window_allows_after_15_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 27, 12, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(
        db,
        "get_user_settings",
        lambda _u, _t: {
            "notifications": {"repository": {"emailDigestLastSentAt": "2026-04-27T12:00:00+00:00"}}
        },
    )
    assert db.repository_import_notification_email_may_send(_USER, _TENANT, now) is True
