"""Unit and HTTP contract tests for the what-is-where board and the history — PFX-8.13 (#7310).

The pure parts of :mod:`app.pact_environment_board` and :mod:`app.pact_deployments`' verdict
helpers, and the two routes with the store faked (``test_pact_environment_board_db`` runs them
against the real schema):

* both routes need ``pacts:view`` before anything is read;
* the board's columns, its *next* rule, its verdict budget and how a cell renders;
* the history's cursor, its per-kind keyset and how an event renders;
* refusals map to 400 (cursor) and 404 (environment / pacticipant).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_deployments import (
    VERDICT_DEPLOYABLE,
    VERDICT_NOT_DEPLOYABLE,
    VERDICT_UNKNOWN,
    Check,
    Topology,
    TopologyEntry,
    verdict_when_recorded,
    verdict_word,
)
from app.pact_environment import CODE_ENVIRONMENT_NOT_FOUND, EnvironmentRecord
from app.pact_environment_board import (
    CODE_HISTORY_CURSOR_INVALID,
    EVENT_DEPLOYED,
    EVENT_RELEASED,
    EVENT_SUPPORT_ENDED,
    EVENT_UNDEPLOYED,
    MAX_BOARD_CHECKS,
    Board,
    BoardCell,
    BoardNext,
    BoardRelease,
    BoardRow,
    BoardVersion,
    HistoryEvent,
    HistoryPage,
    board_order,
    decode_history_cursor,
    encode_history_cursor,
    history_sql,
    next_candidate,
    read_board,
)
from app.pact_publication import PactPublicationError
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt"}
_BASE = "/v1/tenants/acme/pact-environments"
_ROUTES = "app.pact_deployment_routes"
_BOARD = "app.pact_environment_board"
_DEV = EnvironmentRecord(id="44444444-4444-4444-8444-444444444444", name="development", display_name="Development")
_STAGING = EnvironmentRecord(id="33333333-3333-4333-8333-333333333333", name="staging", display_name="Staging")
_PROD = EnvironmentRecord(
    id="22222222-2222-4222-8222-222222222222", name="production", display_name="Production", production=True
)
_UUID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def _check(deployable: Any) -> Check:
    return Check(
        deployable=deployable,
        reasons=[{"type": "success" if deployable else "error", "code": "c", "text": f"said {deployable}"}],
        counts={"success": 1, "failed": 0, "unknown": 0},
    )


def _v(number: str, seq: int) -> BoardVersion:
    return BoardVersion(number, seq, (None,), None)


def _entry(
    environment: EnvironmentRecord, version: str, seq: int, name: str = "Billing Service", **kw: Any
) -> TopologyEntry:
    return TopologyEntry(
        environment_id=environment.id,
        pacticipant_slug=name.lower().replace(" ", "-"),
        pacticipant_name=name,
        version_number=version,
        application_instance=kw.get("instance"),
        recorded_at="2026-11-27T10:00:00+00:00",
        version_seq=seq,
    )


# --- Verdict words -------------------------------------------------------------------------------


def test_a_verdict_is_one_of_three_words() -> None:
    assert verdict_word(True) == VERDICT_DEPLOYABLE
    assert verdict_word(False) == VERDICT_NOT_DEPLOYABLE
    assert verdict_word(None) == VERDICT_UNKNOWN


def test_the_verdict_when_recorded_is_not_known_when_the_question_is_refused() -> None:
    refused = PacticipantValidationError(CODE_NOT_FOUND, "no such pacticipant")
    with (
        patch("app.pact_deployments.get_environment", return_value=_PROD),
        patch("app.pact_deployments.get_pacticipant", side_effect=refused),
    ):
        assert verdict_when_recorded(MagicMock(), _TENANT, "nobody", "1", _PROD.id) is None


def test_the_verdict_when_recorded_asks_can_i_deploy_for_that_environment() -> None:
    pacticipant = MagicMock(slug="billing-service")
    with (
        patch("app.pact_deployments.get_environment", return_value=_PROD),
        patch("app.pact_deployments.get_pacticipant", return_value=pacticipant),
        patch("app.pact_deployments.verdict_for", return_value=_check(False)) as ask,
    ):
        assert verdict_when_recorded(MagicMock(), _TENANT, "Billing Service", "2.0", _PROD.id) == VERDICT_NOT_DEPLOYABLE
    assert ask.call_args.args[2:] == ("billing-service", "2.0", "production")


# --- Board: columns and the next rule -------------------------------------------------------------


def test_columns_put_production_last_and_keep_the_rest_in_order() -> None:
    assert [e.name for e in board_order([_DEV, _PROD, _STAGING])] == ["development", "staging", "production"]


def test_next_is_the_newest_version_in_the_nearest_column_to_the_left() -> None:
    cells = [[_v("2.8.0-rc1", 3)], [_v("2.7.0", 2)], [_v("2.6.1", 1)]]
    assert next_candidate(cells, 2) == (cells[1][0], 1)
    assert next_candidate(cells, 1) == (cells[0][0], 0)
    assert next_candidate(cells, 0) is None


def test_next_skips_empty_columns_but_stops_at_one_that_is_not_newer() -> None:
    assert next_candidate([[_v("5.2.0", 2)], [], [_v("5.1.0", 1)]], 2) is not None
    # Staging runs what production runs: nothing is offered from development past it.
    assert next_candidate([[_v("5.2.0", 3)], [_v("5.1.0", 2)], [_v("5.1.0", 2)]], 2) is None
    # A hotfix that went straight to production is not offered back to staging.
    assert next_candidate([[], [_v("1.0", 1)], [_v("1.1", 2)]], 1) is None


def test_an_empty_cell_is_offered_what_runs_to_its_left() -> None:
    cells = [[_v("1.0", 1)], []]
    assert next_candidate(cells, 1) == (cells[0][0], 0)


def _read(
    entries: List[TopologyEntry], released: List[TopologyEntry] = (), idle: Any = (), **kw: Any
) -> Tuple[Board, List[Any]]:
    topology = Topology(environments=[_PROD, _STAGING], deployed=entries, released=list(released), truncated=False)
    db = MagicMock()
    db.execute_query.return_value = list(idle)
    with (
        patch(f"{_BOARD}.read_topology", return_value=topology),
        patch(f"{_BOARD}.verdict_for", side_effect=kw.get("verdicts", lambda *a: _check(True))) as ask,
    ):
        board = read_board(db, _TENANT, **({"max_checks": kw["max_checks"]} if "max_checks" in kw else {}))
    return board, [call.args[2:] for call in ask.call_args_list]


def test_the_board_groups_instances_and_asks_each_cell_and_its_next_version() -> None:
    board, asked = _read(
        [
            _entry(_PROD, "2.6.1", 1, instance="eu-west"),
            _entry(_PROD, "2.6.1", 1, instance="us-east"),
            _entry(_STAGING, "2.7.0", 2),
        ]
    )
    assert [e.name for e in board.environments] == ["staging", "production"]
    row = board.rows[0]
    production = row.cells[1]
    assert production.deployed[0].application_instances == ("eu-west", "us-east")
    assert production.next == BoardNext("2.7.0", "staging", _check(True), None)
    assert asked == [
        ("billing-service", "2.7.0", "staging"),
        ("billing-service", "2.6.1", "production"),
        ("billing-service", "2.7.0", "production"),
    ]
    assert (board.checks, board.not_checked) == (3, 0)


def test_the_board_never_drops_a_verdict_past_its_budget() -> None:
    board, _ = _read([_entry(_STAGING, "2", 2), _entry(_PROD, "1", 1)], max_checks=1)
    production = board.rows[0].cells[1]
    assert production.deployed[0].check is None
    assert "Only 100 versions are checked" in (production.deployed[0].not_checked or "")
    assert production.next is not None and production.next.check is None
    assert (board.checks, board.not_checked) == (1, 2)


def test_a_refused_verdict_is_reported_with_its_reason() -> None:
    refused = PactPublicationError("pact-matrix-invalid", "the matrix refused it")
    board, _ = _read([_entry(_PROD, "1", 1)], verdicts=lambda *a: (_ for _ in ()).throw(refused))
    assert board.rows[0].cells[1].deployed[0].not_checked == "the matrix refused it"
    assert board.not_checked == 1


def test_releases_and_idle_pacticipants_have_rows() -> None:
    board, _ = _read(
        [], released=[_entry(_PROD, "1.9.2", 5, name="Mobile App")], idle=[{"slug": "orders", "name": "Orders"}]
    )
    names = [row.pacticipant_name for row in board.rows]
    assert names == ["Mobile App", "Orders"]
    assert board.rows[0].released[0] == BoardRelease("1.9.2", "production", "2026-11-27T10:00:00+00:00", _check(True))
    assert board.rows[1].idle is True and board.rows[0].idle is False


def test_the_board_route_needs_pacts_view_and_renders_each_cell() -> None:
    def denied(*_a: Any, **_k: Any) -> None:
        raise HTTPException(status_code=403, detail="Permission denied")

    with patch(f"{_ROUTES}.enforce_permission", side_effect=denied), patch(f"{_ROUTES}.read_board") as read:
        assert client.get(f"{_BASE}/board").status_code == 403
    read.assert_not_called()

    board = Board(
        environments=[_STAGING, _PROD],
        rows=[
            BoardRow(
                "billing-service",
                "Billing Service",
                [
                    BoardCell(_STAGING.id, [BoardVersion("2.7.0", 2, (None,), "t", _check(None))]),
                    BoardCell(
                        _PROD.id,
                        [BoardVersion("2.6.1", 1, ("eu-west",), "t", None, "budget")],
                        BoardNext("2.7.0", "staging", _check(False)),
                    ),
                ],
                [],
            )
        ],
        truncated=False,
        checks=2,
        not_checked=1,
        evaluated_at="now",
    )
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u") as enforce,
        patch(f"{_ROUTES}.read_board", return_value=board),
    ):
        body = client.get(f"{_BASE}/board").json()
    assert enforce.call_args.args[2:] == (Resource.PACTS, Action.VIEW)
    assert [e["name"] for e in body["environments"]] == ["staging", "production"]
    staging, production = body["rows"][0]["cells"]
    assert staging["deployed"][0]["verdict"]["deployable"] is None
    assert staging["deployed"][0]["verdict"]["checked"] is True
    assert production["deployed"][0] == {
        "version": "2.6.1",
        "applicationInstances": ["eu-west"],
        "deployedAt": "t",
        "verdict": {"checked": False, "notChecked": "budget"},
    }
    assert production["next"]["from"] == "staging"
    assert production["next"]["verdict"]["deployable"] is False
    assert (body["checks"], body["notChecked"], body["rows"][0]["idle"]) == (2, 1, False)
    assert MAX_BOARD_CHECKS == 100


# --- History: cursor and keyset ---------------------------------------------------------------------


def _event(kind: str = EVENT_DEPLOYED, at: str = "2026-11-27T10:00:00.123456+00:00") -> HistoryEvent:
    return HistoryEvent(kind, _UUID, at, "billing-service", "Billing Service", "2.7.0", _PROD)


def test_a_cursor_round_trips() -> None:
    at, kind, ident = decode_history_cursor(encode_history_cursor(_event(EVENT_SUPPORT_ENDED)))  # type: ignore[misc]
    assert (at, kind, ident) == (
        datetime(2026, 11, 27, 10, 0, 0, 123456, tzinfo=timezone.utc),
        EVENT_SUPPORT_ENDED,
        _UUID,
    )
    assert decode_history_cursor(None) is None


@pytest.mark.parametrize("cursor", ["nope", "x" * 300, encode_history_cursor(_event("other")), "bm90fGF8Yg"])
def test_a_cursor_this_api_did_not_give_out_is_refused(cursor: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        decode_history_cursor(cursor)
    assert caught.value.code == CODE_HISTORY_CURSOR_INVALID


def test_each_kind_continues_strictly_after_the_cursor() -> None:
    # Kinds sort deployed < released < support-ended < undeployed; the page is (at, kind, id) descending.
    assert "d.created_at <= %s" in history_sql(
        EVENT_DEPLOYED, after_kind=EVENT_RELEASED, environment=False, pacticipant=False
    )
    assert "(d.created_at, d.id) < (%s, %s::uuid)" in history_sql(
        EVENT_RELEASED, after_kind=EVENT_RELEASED, environment=False, pacticipant=False
    )
    assert "d.undeployed_at < %s" in history_sql(
        EVENT_UNDEPLOYED, after_kind=EVENT_RELEASED, environment=False, pacticipant=False
    )
    first = history_sql(EVENT_UNDEPLOYED, after_kind=None, environment=True, pacticipant=True)
    assert "d.environment_id = %s::uuid" in first and "d.pacticipant_id = %s::uuid" in first
    assert "ended_reason IS DISTINCT FROM 'replaced'" in first
    assert "d.tenant_id = %s::uuid" in first


def test_the_history_route_renders_events_and_maps_refusals(allowed: MagicMock) -> None:
    page = HistoryPage(
        events=[HistoryEvent(**{**_event().__dict__, "verdict": "unknown", "replaces": "2.6.1"})], next_cursor="c"
    )
    with patch(f"{_ROUTES}.list_history", return_value=page) as listed:
        body = client.get(f"{_BASE}/history", params={"environment": "production", "limit": 5}).json()
    assert listed.call_args.kwargs["environment_name"] == "production"
    assert listed.call_args.kwargs["limit"] == 5
    assert body["nextCursor"] == "c"
    event = body["events"][0]
    assert (event["kind"], event["verdict"], event["replaces"], event["environment"]["name"]) == (
        "deployed",
        "unknown",
        "2.6.1",
        "production",
    )

    for exc, status in (
        (PactPublicationError(CODE_HISTORY_CURSOR_INVALID, "bad"), 400),
        (PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, "none"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "none"), 404),
    ):
        with patch(f"{_ROUTES}.list_history", side_effect=exc):
            assert client.get(f"{_BASE}/history").status_code == status
    assert client.get(f"{_BASE}/history", params={"limit": 51}).status_code == 422
    assert EVENT_RELEASED == "released"


def test_the_history_route_needs_pacts_view() -> None:
    def denied(*_a: Any, **_k: Any) -> None:
        raise HTTPException(status_code=403, detail="Permission denied")

    with patch(f"{_ROUTES}.enforce_permission", side_effect=denied), patch(f"{_ROUTES}.list_history") as listed:
        assert client.get(f"{_BASE}/history").status_code == 403
    listed.assert_not_called()
