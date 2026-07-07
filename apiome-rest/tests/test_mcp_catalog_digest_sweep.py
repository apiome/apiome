"""Catalog digest sweep orchestration tests (MCAT-19.5, #4654).

Deterministic, DB-free fixtures over ``app.mcp_catalog_digest_sweep`` using a fake ``Database`` that
records calls. Covers the acceptance criteria and the sweep's contract:
  - opted-in due tenants get a digest compiled from the window reads and delivered to subscriptions;
  - an empty window sends nothing unless the tenant opted into "no changes" (send_empty);
  - the window anchor is advanced each tick (success, empty-skip, and compile failure);
  - per-tenant single-flight via the advisory lock (a held lock skips the tenant);
  - the global kill switch halts the tick.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.mcp_catalog_digest import EVENT_TYPE_DIGEST
from app.mcp_catalog_digest_sweep import process_mcp_catalog_digest_sweep

NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(days=7)


def _due(tenant_id, slug, *, send_empty=False):
    return {
        "tenant_id": tenant_id,
        "tenant_slug": slug,
        "window_start": START,
        "window_end": NOW,
        "send_empty": send_empty,
    }


def _removed_change(slug):
    return {
        "endpoint_id": f"ep-{slug}",
        "endpoint_name": f"Server {slug}",
        "endpoint_slug": slug,
        "version_id": f"v-{slug}",
        "change_type": "removed",
        "item_type": "tool",
        "item_name": "gone",
        "detail": {},
        "version_seq": 2,
        "version_tag": "t",
        "discovered_at": NOW - timedelta(hours=1),
    }


class FakeDB:
    """Records digest-sweep interactions; no real database."""

    def __init__(
        self,
        *,
        due=None,
        subscriptions=None,
        changes=None,
        new_endpoints=None,
        lock_result=True,
        compile_error_tenants=None,
    ):
        self._due = due or []
        self._subscriptions = subscriptions if subscriptions is not None else {}
        self._changes = changes or {}
        self._new_endpoints = new_endpoints or {}
        self._lock_result = lock_result
        self._compile_error_tenants = compile_error_tenants or set()
        self.acquired = []
        self.released = []
        self.enqueued = []
        self.marked = []

    # --- due selection / lock ---
    def list_due_mcp_catalog_digests(self, *, default_cadence_seconds):
        return list(self._due)

    def try_acquire_mcp_catalog_digest_lock(self, tenant_id):
        self.acquired.append(tenant_id)
        return self._lock_result

    def release_mcp_catalog_digest_lock(self, tenant_id):
        self.released.append(tenant_id)

    def mark_mcp_catalog_digest_sent(self, tenant_id, sent_at):
        self.marked.append((tenant_id, sent_at))
        return True

    # --- window reads ---
    def list_mcp_new_endpoints_in_window(self, tenant_id, since, until):
        if tenant_id in self._compile_error_tenants:
            raise RuntimeError("boom")
        return list(self._new_endpoints.get(tenant_id, []))

    def list_mcp_catalog_changes_in_window(self, tenant_id, since, until, *, limit=500):
        return list(self._changes.get(tenant_id, []))

    def list_mcp_grade_movements_in_window(self, tenant_id, since, until):
        return []

    def list_mcp_health_problems_in_window(self, tenant_id, since, until):
        return []

    # --- delivery ---
    def list_active_push_webhook_subscription_ids(self, tenant_id):
        return list(self._subscriptions.get(tenant_id, []))

    def enqueue_push_webhook_delivery(self, tenant_id, subscription_id, event_type, payload):
        self.enqueued.append((tenant_id, subscription_id, event_type, payload))
        return {"id": f"evt-{len(self.enqueued)}"}


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    """Default: kill switch on, weekly cadence."""
    from app.config import settings

    monkeypatch.setattr(settings, "mcp_digest_enabled", True, raising=False)
    monkeypatch.setattr(settings, "mcp_digest_default_cadence_seconds", 604800, raising=False)


def test_delivers_digest_to_subscriptions():
    db = FakeDB(
        due=[_due("t1", "acme")],
        subscriptions={"t1": ["sub-a", "sub-b"]},
        changes={"t1": [_removed_change("weather")]},
    )
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 1
    assert len(db.enqueued) == 2  # one per subscription
    _, _, event_type, payload = db.enqueued[0]
    assert event_type == EVENT_TYPE_DIGEST
    assert payload["totals"]["breakingChanges"] == 1
    # Anchor advanced to window_end, lock released.
    assert db.marked == [("t1", NOW)]
    assert db.released == ["t1"]


def test_empty_window_silent_by_default_but_anchor_advances():
    db = FakeDB(due=[_due("t1", "acme")], subscriptions={"t1": ["sub-a"]})
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 0
    assert db.enqueued == []  # nothing delivered
    assert db.marked == [("t1", NOW)]  # but anchor still advanced


def test_empty_window_sends_when_send_empty_true():
    db = FakeDB(
        due=[_due("t1", "acme", send_empty=True)],
        subscriptions={"t1": ["sub-a"]},
    )
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 1
    assert len(db.enqueued) == 1
    assert db.enqueued[0][3]["empty"] is True


def test_no_subscriptions_still_counts_and_advances():
    """A tenant with a non-empty window but no subscriptions is still processed (anchor advances)."""
    db = FakeDB(
        due=[_due("t1", "acme")],
        subscriptions={},
        changes={"t1": [_removed_change("weather")]},
    )
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 1
    assert db.enqueued == []
    assert db.marked == [("t1", NOW)]


def test_lock_held_skips_tenant():
    db = FakeDB(due=[_due("t1", "acme")], lock_result=False)
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 0
    assert db.acquired == ["t1"]
    assert db.released == []  # never released — never acquired
    assert db.marked == []  # not advanced


def test_compile_failure_advances_anchor_and_releases_lock():
    db = FakeDB(due=[_due("t1", "acme")], compile_error_tenants={"t1"})
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 0
    assert db.marked == [("t1", NOW)]  # anchor advances despite failure
    assert db.released == ["t1"]


def test_kill_switch_halts_tick(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "mcp_digest_enabled", False, raising=False)
    db = FakeDB(due=[_due("t1", "acme")], subscriptions={"t1": ["sub-a"]})
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 0
    assert db.acquired == []  # nothing selected/processed


def test_one_tenant_failure_does_not_abort_others():
    db = FakeDB(
        due=[_due("t1", "acme"), _due("t2", "globex")],
        subscriptions={"t2": ["sub-b"]},
        changes={"t2": [_removed_change("weather")]},
        compile_error_tenants={"t1"},
    )
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 1  # t2 delivered despite t1 failing
    assert {m[0] for m in db.marked} == {"t1", "t2"}


def test_delivery_error_does_not_break_sweep(monkeypatch):
    db = FakeDB(
        due=[_due("t1", "acme")],
        subscriptions={"t1": ["sub-a"]},
        changes={"t1": [_removed_change("weather")]},
    )

    def _boom(*a, **k):
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(db, "enqueue_push_webhook_delivery", _boom)
    sent = process_mcp_catalog_digest_sweep(db)
    assert sent == 1  # still counted; delivery is best-effort
    assert db.marked == [("t1", NOW)]
