"""Sunset readiness — RDG-5.3 (#5788).

Unit tests with the database faked:

* the rules (:mod:`app.sunset_readiness`): the line for bound, anonymous-only and unused traffic,
  name redaction, the 0–30 day alert window, and the payloads;
* the store (:mod:`app.sunset_readiness_store`): what it asks ``usage_daily`` for, the "no usage
  source → no line" rule, and the claim that writes inbox rows only when it wins the week;
* the sweep (:mod:`app.sunset_readiness_sweep`): the acceptance criteria — a sunset in 20 days with
  two bound consumers sends one alert (inbox rows and a ``sunset.still_used`` webhook), a second
  tick in the same week sends none because the *stored* state says so, and anonymous traffic alone
  sends none;
* the route: ``GET /v1/versions/{tenant}/sunset-timeline`` carries ``stillUsed`` and never fails
  when the usage index cannot be read;
* V383: the notification CHECK and the alert table.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import sunset_readiness_store as store
from app.auth import validate_authentication
from app.main import app
from app.notification_fanout import NotificationDraft
from app.notifications import NOTIFICATION_TYPES, TYPE_SEAT_CAP_BLOCKED_SSO, TYPE_SUNSET_STILL_USED
from app.sunset_readiness import (
    ALERT_WITHIN_DAYS,
    EVENT_STILL_USED,
    STATE_ANONYMOUS,
    STATE_BOUND,
    STATE_UNUSED,
    SUNSET_TIMELINE_LINK,
    UsageRow,
    consumers_href,
    days_until_sunset,
    is_alert_due,
    notification_payload,
    still_used_summary,
    summarize_usage,
    usage_window,
    webhook_payload,
)
from app.sunset_readiness_sweep import check_sunset_still_used

TODAY = date(2026, 11, 16)
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECT = "11111111-1111-4111-8111-111111111111"
REVISION = "22222222-2222-4222-8222-222222222222"
USER_A = "44444444-4444-4444-8444-444444444444"
USER_B = "55555555-5555-4555-8555-555555555555"
BILLING = "33333333-3333-4333-8333-333333333333"
ORDERS = "66666666-6666-4666-8666-666666666666"

_REPO = Path(__file__).resolve().parents[2]
_MIGRATION = next((_REPO / "apiome-db" / "scripts").glob("V383__*.sql"))

BOUND_ROWS = [
    UsageRow(consumer_id=BILLING, slug="billing-service", name="Billing", calls=1000),
    UsageRow(consumer_id=ORDERS, slug="orders-web", name="Orders web", calls=240),
    UsageRow(consumer_id=None, slug=None, name=None, calls=60),
]


def _sunset_in(days: int) -> Dict[str, Any]:
    """Revision metadata with a sunset ``days`` after :data:`TODAY`."""
    return {"deprecated": True, "sunsetAt": f"{(TODAY + timedelta(days=days)).isoformat()}T00:00:00Z"}


# ---------------------------------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------------------------------


def test_bound_consumers_give_the_still_used_line_with_their_calls() -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=True)
    assert usage.state == STATE_BOUND
    assert usage.summary == "Still used by 2 consumers (1,240 calls, 7-day)"
    assert (usage.calls, usage.bound_calls, usage.anonymous_calls, usage.consumer_count) == (1300, 1240, 60, 2)
    assert [consumer.slug for consumer in usage.consumers or []] == ["billing-service", "orders-web"]
    assert usage.consumers_href == f"/ade/dashboard/projects/{PROJECT}/consumers"
    assert (usage.window_days, usage.environment) == (7, "prod")


def test_only_anonymous_traffic_asks_for_a_binding() -> None:
    usage = summarize_usage([UsageRow(None, None, None, 80)], project_id=PROJECT, consumers_visible=True)
    assert usage.state == STATE_ANONYMOUS
    assert usage.summary == "Anonymous traffic only — bind consumers to attribute it"
    assert usage.consumer_count == 0 and usage.consumers == []


def test_no_traffic_says_so() -> None:
    usage = summarize_usage([], project_id=PROJECT, consumers_visible=True)
    assert usage.state == STATE_UNUSED and usage.summary == "No traffic in the last 7 days"


def test_two_bindings_of_one_consumer_count_once_and_zero_rows_are_ignored() -> None:
    rows = [
        UsageRow(BILLING, "billing-service", "Billing", 1),
        UsageRow(BILLING, "billing-service", "Billing", 2),
        UsageRow(ORDERS, "orders-web", "Orders web", 0),
    ]
    usage = summarize_usage(rows, project_id=PROJECT, consumers_visible=True)
    assert usage.consumer_count == 1 and usage.bound_calls == 3
    assert usage.summary == "Still used by 1 consumer (3 calls, 7-day)"


def test_a_reader_without_consumer_view_gets_counts_but_no_names() -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=False)
    assert usage.consumers is None and usage.consumers_visible is False
    assert usage.consumer_count == 2
    dumped = usage.model_dump(by_alias=True)
    assert dumped["consumers"] is None and dumped["consumerCount"] == 2 and dumped["consumersVisible"] is False


def test_the_summary_pluralises_and_separates_thousands() -> None:
    assert still_used_summary(1, 1, 0) == "Still used by 1 consumer (1 call, 7-day)"
    assert still_used_summary(3, 12345, 9) == "Still used by 3 consumers (12,345 calls, 7-day)"


def test_the_window_is_the_seven_days_ending_today() -> None:
    assert usage_window(TODAY) == (date(2026, 11, 10), TODAY)


def test_consumers_href_escapes_the_id() -> None:
    assert consumers_href("a/b") == "/ade/dashboard/projects/a%2Fb/consumers"


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (_sunset_in(20), 20),
        ({"sunsetDate": "2026-11-16"}, 0),
        ({"sunset_date": "2026-11-01"}, -15),
        ({"deprecated": True}, None),
        ({"sunsetAt": "soon"}, None),
        (None, None),
    ],
)
def test_days_until_sunset(metadata: Any, expected: Optional[int]) -> None:
    assert days_until_sunset(metadata, TODAY) == expected


@pytest.mark.parametrize(
    ("days", "due"),
    [(-1, False), (0, True), (20, True), (ALERT_WITHIN_DAYS, True), (ALERT_WITHIN_DAYS + 1, False)],
)
def test_an_alert_is_due_from_the_sunset_day_back_to_thirty_days(days: int, due: bool) -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=True)
    assert is_alert_due(_sunset_in(days), usage, TODAY) is due


def test_anonymous_traffic_alone_never_alerts() -> None:
    usage = summarize_usage([UsageRow(None, None, None, 500)], project_id=PROJECT, consumers_visible=True)
    assert is_alert_due(_sunset_in(20), usage, TODAY) is False


def test_the_notification_payload_names_no_consumer_and_links_the_timeline() -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=True)
    payload = notification_payload(
        project={"slug": "pets", "name": "Pets"},
        version_label="1.2.0",
        sunset_at="2026-12-06T00:00:00Z",
        days_left=20,
        usage=usage,
    )
    assert payload["summary"] == "1.2.0 sunsets in 20 days and is still used by 2 consumers (1,240 calls, 7-day)"
    assert payload["link"] == SUNSET_TIMELINE_LINK
    assert payload["project_slug"] == "pets" and payload["project_name"] == "Pets"
    assert payload["consumer_count"] == 2 and payload["calls"] == 1240
    assert "billing-service" not in str(payload)


@pytest.mark.parametrize(("days", "phrase"), [(0, "today"), (1, "tomorrow"), (5, "in 5 days")])
def test_the_notification_says_when(days: int, phrase: str) -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=True)
    payload = notification_payload(project={}, version_label="v1", sunset_at=None, days_left=days, usage=usage)
    assert payload["summary"].startswith(f"v1 sunsets {phrase} and is still used")


def test_the_webhook_payload_carries_the_handles() -> None:
    usage = summarize_usage(BOUND_ROWS, project_id=PROJECT, consumers_visible=True)
    body = webhook_payload(
        tenant_id=TENANT,
        project={"id": PROJECT, "slug": "pets", "name": "Pets"},
        version_record_id=REVISION,
        version_label="1.2.0",
        sunset_at="2026-12-06T00:00:00Z",
        days_left=20,
        usage=usage,
    )
    assert body["event"] == EVENT_STILL_USED == "sunset.still_used"
    assert body["revisionId"] == REVISION and body["daysUntilSunset"] == 20
    assert [consumer["slug"] for consumer in body["consumers"]] == ["billing-service", "orders-web"]
    assert (body["calls"], body["anonymousCalls"], body["consumerCount"]) == (1240, 60, 2)


# ---------------------------------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------------------------------


class QueryDb:
    """Answers ``execute_query`` from a list of canned results and records the calls."""

    def __init__(self, *answers: List[Dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute_query(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        self.calls.append((query, params))
        return self.answers.pop(0) if self.answers else []


def test_usage_reads_the_prod_window_per_revision_and_consumer() -> None:
    db = QueryDb(
        [
            {"revision_id": REVISION, "consumer_id": BILLING, "consumer_slug": "billing-service",
             "consumer_name": "Billing", "calls": 5},
            {"revision_id": REVISION, "consumer_id": None, "consumer_slug": None, "consumer_name": None, "calls": 2},
        ]
    )
    rows = store.usage_for_revisions(db, TENANT, [(REVISION, PROJECT)], today=TODAY)
    assert rows == {
        REVISION: [UsageRow(BILLING, "billing-service", "Billing", 5), UsageRow(None, None, None, 2)]
    }
    query, params = db.calls[0]
    assert "apiome.usage_daily" in query and "usage_consumer_binding" in query
    assert params == (TENANT, [PROJECT], [REVISION], "prod", date(2026, 11, 10), TODAY)


def test_usage_ignores_ids_that_are_not_uuids_without_querying() -> None:
    db = QueryDb()
    assert store.usage_for_revisions(db, TENANT, [("nope", PROJECT)], today=TODAY) == {}
    assert store.usage_for_revisions(db, "tenant", [(REVISION, PROJECT)], today=TODAY) == {}
    assert db.calls == []


def test_a_project_without_a_usage_source_draws_no_line() -> None:
    other_revision, other_project = "77777777-7777-4777-8777-777777777777", "88888888-8888-4888-8888-888888888888"
    db = QueryDb(
        [{"project_id": PROJECT}],
        [{"revision_id": REVISION, "consumer_id": None, "consumer_slug": None, "consumer_name": None, "calls": 3}],
    )
    readiness = store.readiness_for_entries(
        db, TENANT, [(REVISION, PROJECT), (other_revision, other_project)], consumers_visible=True, today=TODAY
    )
    assert readiness[other_revision] is None
    assert readiness[REVISION] is not None and readiness[REVISION].state == STATE_ANONYMOUS
    assert "kind <> 'mock'" in db.calls[0][0]
    # The usage read only asks about the sourced project's revisions.
    assert db.calls[1][1][1] == [PROJECT] and db.calls[1][1][2] == [REVISION]


def test_readiness_of_nothing_queries_nothing() -> None:
    db = QueryDb()
    assert store.readiness_for_entries(db, TENANT, [], consumers_visible=True, today=TODAY) == {}
    assert db.calls == []


class AlertDb:
    """An in-memory stand-in for the sweep's tables.

    ``sunset_still_used_alert`` is a dict of revision → last alert time, and the claim's upsert is
    emulated with the migration's rule (new, or the last alert at least 7 days old). Inbox rows and
    webhook deliveries are recorded.
    """

    def __init__(
        self,
        *,
        candidates: List[Dict[str, Any]],
        usage: List[Dict[str, Any]],
        collaborators: List[str],
        subscriptions: Tuple[str, ...] = ("sub-1",),
    ) -> None:
        self.candidates = candidates
        self.usage = usage
        self.collaborators = collaborators
        self.subscriptions = subscriptions
        self.now = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)
        self.alerts: Dict[str, datetime] = {}
        self.notifications: List[NotificationDraft] = []
        self.deliveries: List[Tuple[str, str, Dict[str, Any]]] = []
        self.commits = 0

    # -- execute_query -----------------------------------------------------------------------
    def execute_query(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        if "FROM apiome.versions v" in query:
            window = params[3]
            return [
                row
                for row in self.candidates
                if row["revision_id"] not in self.alerts or self.alerts[row["revision_id"]] <= self.now - window
            ]
        if "FROM apiome.usage_daily d" in query:
            # The same traffic for whichever revision is asked about.
            return [dict(row, revision_id=params[2][0]) for row in self.usage]
        raise AssertionError(f"unexpected query {query}")

    def list_version_collaborators(self, *, tenant_id: str, project_id: str, version_id: str) -> List[str]:
        return list(self.collaborators)

    # -- the claim's transaction --------------------------------------------------------------
    def connect(self) -> "AlertDb._Conn":
        return AlertDb._Conn(self)

    def _insert_notifications(self, cursor: Any, *, tenant_id: str, notify: Any, produced: Any = None) -> int:
        drafts = list(notify({}))
        self.notifications.extend(drafts)
        return len(drafts)

    # -- push webhooks ------------------------------------------------------------------------
    def list_active_push_webhook_subscription_ids(self, tenant_id: str) -> List[str]:
        return list(self.subscriptions)

    def enqueue_push_webhook_delivery(self, tenant_id: str, subscription_id: str, event: str, payload: Dict) -> Dict:
        self.deliveries.append((subscription_id, event, payload))
        return {"id": f"event-{len(self.deliveries)}"}

    class _Conn:
        def __init__(self, db: "AlertDb") -> None:
            self.db = db

        def cursor(self) -> "AlertDb._Cursor":
            return AlertDb._Cursor(self.db)

        def commit(self) -> None:
            self.db.commits += 1

        def rollback(self) -> None:
            pass

    class _Cursor:
        def __init__(self, db: "AlertDb") -> None:
            self.db = db
            self.row: Optional[Tuple[str]] = None

        def __enter__(self) -> "AlertDb._Cursor":
            return self

        def __exit__(self, *_exc: Any) -> None:
            return None

        def execute(self, query: str, params: Tuple[Any, ...]) -> None:
            assert "INSERT INTO apiome.sunset_still_used_alert" in query
            revision, window = params[0], params[-1]
            last = self.db.alerts.get(revision)
            if last is None or last <= self.db.now - window:
                self.db.alerts[revision] = self.db.now
                self.row = (revision,)
            else:
                self.row = None

        def fetchone(self) -> Optional[Tuple[str]]:
            return self.row


def _candidate(metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "project_slug": "pets",
        "project_name": "Pets",
        "revision_id": REVISION,
        "version_label": "1.2.0",
        "metadata": metadata,
    }


_BOUND_USAGE = [
    {"revision_id": REVISION, "consumer_id": BILLING, "consumer_slug": "billing-service", "consumer_name": "Billing",
     "calls": 1000},
    {"revision_id": REVISION, "consumer_id": ORDERS, "consumer_slug": "orders-web", "consumer_name": "Orders web",
     "calls": 240},
]


def test_a_sunset_in_twenty_days_with_two_bound_consumers_sends_one_alert() -> None:
    db = AlertDb(candidates=[_candidate(_sunset_in(20))], usage=_BOUND_USAGE, collaborators=[USER_A, USER_B])
    assert check_sunset_still_used(db, today=TODAY) == 1

    assert [draft.user_id for draft in db.notifications] == [USER_A, USER_B]
    draft = db.notifications[0]
    assert draft.type == TYPE_SUNSET_STILL_USED
    assert draft.project_id == PROJECT and draft.version_id == REVISION
    assert draft.payload["summary"] == (
        "1.2.0 sunsets in 20 days and is still used by 2 consumers (1,240 calls, 7-day)"
    )
    assert db.commits == 1

    assert len(db.deliveries) == 1
    subscription, event, body = db.deliveries[0]
    assert (subscription, event) == ("sub-1", "sunset.still_used")
    assert [consumer["slug"] for consumer in body["consumers"]] == ["billing-service", "orders-web"]


def test_the_weekly_rule_is_the_stored_state_not_the_worker() -> None:
    db = AlertDb(candidates=[_candidate(_sunset_in(20))], usage=_BOUND_USAGE, collaborators=[USER_A])
    assert check_sunset_still_used(db, today=TODAY) == 1
    # A second tick the same day — or a restarted worker — finds the stored alert and sends nothing.
    assert check_sunset_still_used(db, today=TODAY) == 0
    db.now += timedelta(days=6, hours=23)
    assert check_sunset_still_used(db, today=TODAY + timedelta(days=6)) == 0
    assert len(db.notifications) == 1 and len(db.deliveries) == 1
    # Seven days on, the next alert is due.
    db.now += timedelta(hours=1)
    assert check_sunset_still_used(db, today=TODAY + timedelta(days=7)) == 1
    assert len(db.notifications) == 2 and len(db.deliveries) == 2


def test_the_claim_refuses_a_second_alert_even_when_the_candidate_list_is_stale() -> None:
    """Two replicas that both listed the revision send one alert between them."""
    db = AlertDb(candidates=[_candidate(_sunset_in(20))], usage=_BOUND_USAGE, collaborators=[USER_A])
    db.alerts[REVISION] = db.now - timedelta(days=1)
    with patch("app.sunset_readiness_sweep.alert_candidates", return_value=[_candidate(_sunset_in(20))]):
        assert check_sunset_still_used(db, today=TODAY) == 0
    assert db.notifications == [] and db.deliveries == []


def test_only_anonymous_traffic_sends_nothing() -> None:
    usage = [{"revision_id": REVISION, "consumer_id": None, "consumer_slug": None, "consumer_name": None,
              "calls": 900}]
    db = AlertDb(candidates=[_candidate(_sunset_in(20))], usage=usage, collaborators=[USER_A])
    assert check_sunset_still_used(db, today=TODAY) == 0
    assert db.notifications == [] and db.deliveries == [] and db.alerts == {}


@pytest.mark.parametrize("days", [31, -1])
def test_a_sunset_outside_the_window_sends_nothing(days: int) -> None:
    db = AlertDb(candidates=[_candidate(_sunset_in(days))], usage=_BOUND_USAGE, collaborators=[USER_A])
    assert check_sunset_still_used(db, today=TODAY) == 0
    assert db.alerts == {}


def test_no_collaborators_still_claims_the_week_and_sends_the_webhook() -> None:
    db = AlertDb(candidates=[_candidate(_sunset_in(3))], usage=_BOUND_USAGE, collaborators=[])
    assert check_sunset_still_used(db, today=TODAY) == 1
    assert db.notifications == [] and len(db.deliveries) == 1 and REVISION in db.alerts


def test_one_failing_revision_does_not_stop_the_next() -> None:
    other = dict(_candidate(_sunset_in(10)), revision_id="99999999-9999-4999-8999-999999999999")
    db = AlertDb(candidates=[_candidate(_sunset_in(20)), other], usage=_BOUND_USAGE, collaborators=[USER_A])
    calls = {"n": 0}
    real = db.list_version_collaborators

    def flaky(**kwargs: Any) -> List[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(**kwargs)

    db.list_version_collaborators = flaky  # type: ignore[method-assign]
    assert check_sunset_still_used(db, today=TODAY) == 1


def test_the_candidate_query_needs_a_sunset_bound_traffic_and_no_recent_alert() -> None:
    db = QueryDb()
    store.alert_candidates(db, today=TODAY, limit=0)
    query, params = db.calls[0]
    assert "sunsetAt" in query and "consumer_binding_id IS NOT NULL" in query
    assert "sunset_still_used_alert" in query
    assert params == ("prod", date(2026, 11, 10), TODAY, timedelta(days=7), 1)


# ---------------------------------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------------------------------

client = TestClient(app)
_AUTH = {"tenant_id": TENANT, "user_id": USER_A, "auth_method": "jwt"}
_TIMELINE_ROW = {
    "id": REVISION,
    "project_id": PROJECT,
    "version_id": "1.2.0",
    "metadata": _sunset_in(20),
    "published": True,
    "project_name": "Pets",
    "project_slug": "pets",
}


@pytest.fixture
def _signed_in() -> Any:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _timeline(visible: bool, usage: Any) -> Dict[str, Any]:
    with patch("app.versions_routes.db.list_sunset_timeline_entries", return_value=[_TIMELINE_ROW]), patch(
        "app.versions_routes.has_permission", return_value=visible
    ), patch("app.sunset_readiness_store.projects_with_usage_sources", return_value={PROJECT}), patch(
        "app.sunset_readiness_store.usage_for_revisions", **usage
    ):
        response = client.get("/v1/versions/acme/sunset-timeline")
    assert response.status_code == 200, response.text
    return response.json()["entries"][0]


def test_the_timeline_carries_still_used_with_handles_for_a_consumer_reader(_signed_in: Any) -> None:
    entry = _timeline(True, {"return_value": {REVISION: BOUND_ROWS}})
    still = entry["stillUsed"]
    assert still["summary"] == "Still used by 2 consumers (1,240 calls, 7-day)"
    assert still["state"] == "bound" and still["consumerCount"] == 2 and still["consumersVisible"] is True
    assert [consumer["slug"] for consumer in still["consumers"]] == ["billing-service", "orders-web"]
    assert still["consumersHref"] == f"/ade/dashboard/projects/{PROJECT}/consumers"


def test_the_timeline_hides_handles_from_a_reader_without_consumer_view(_signed_in: Any) -> None:
    still = _timeline(False, {"return_value": {REVISION: BOUND_ROWS}})["stillUsed"]
    assert still["consumers"] is None and still["consumerCount"] == 2


def test_the_timeline_loads_when_the_usage_index_does_not(_signed_in: Any) -> None:
    entry = _timeline(True, {"side_effect": RuntimeError("usage down")})
    assert entry["stillUsed"] is None and entry["versionLine"] == "1.2.0"


# ---------------------------------------------------------------------------------------------------
# V383
# ---------------------------------------------------------------------------------------------------


def _executable(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_v383_widens_the_notification_check_to_the_whole_vocabulary() -> None:
    text = _executable(_MIGRATION.read_text(encoding="utf-8"))
    check = text[text.index("CHECK (type IN (") : text.index("COMMENT ON COLUMN notifications.type")]
    # Everything the API knew when V383 shipped; types added since belong to their own migration.
    assert set(check.split("'")[1::2]) == set(NOTIFICATION_TYPES) - {TYPE_SEAT_CAP_BLOCKED_SSO}
    assert "sunset_still_used" in check


def test_v383_stores_the_weekly_state_per_revision() -> None:
    text = _executable(_MIGRATION.read_text(encoding="utf-8"))
    assert "CREATE TABLE IF NOT EXISTS sunset_still_used_alert" in text
    assert "version_record_id UUID PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE" in text
    assert "last_notified_at TIMESTAMPTZ NOT NULL" in text
