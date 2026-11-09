"""Tests for MCP change-notification events (V2-MCP-27.1 / MCAT-13.1, #3711).

Two layers, both DB-free:

* **Module** — change-summary folding, event assembly and payload shape, the deterministic
  event id, and the subscribe / unsubscribe / emit registry (failure isolation, de-duplicated
  subscription).
* **Engine** — :func:`app.mcp_discovery_engine._persist_outcome` emits exactly one event per new
  version (first run and changed surface), none on an unchanged re-discovery, and never lets a
  handler or event-building failure fail the discovery job.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import mcp_change_events, mcp_discovery_engine
from app.mcp_change_events import (
    EVENT_SCHEMA_VERSION,
    EVENT_TYPE_VERSION_CREATED,
    McpVersionCreatedEvent,
    build_change_summary,
    build_version_created_event,
    emit_version_created,
    event_id_for_version,
    subscribe,
    unsubscribe,
)
from app.mcp_client import DiscoveryListings, DiscoverySurface, InitializeResult, ServerInfo

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
_EP_UUID = "11111111-1111-1111-1111-111111111111"
_JOB_UUID = "22222222-2222-2222-2222-222222222222"

_ENDPOINT_ROW = {
    "id": _EP_UUID,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://user:secret@mcp.acme.example/mcp",
    "transport": "streamable_http",
}


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Give every test an empty handler registry so subscriptions never leak between tests."""
    monkeypatch.setattr(mcp_change_events, "_handlers", [])


def _tool(name: str, *, desc: str = "d", schema=None) -> dict:
    """A minimal MCP tool listing entry."""
    return {
        "name": name,
        "description": desc,
        "inputSchema": schema or {"type": "object", "properties": {}},
    }


def _surface(tools) -> DiscoverySurface:
    """A tools-only discovery surface with fixed server metadata."""
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Srv", version="1.0"),
        capabilities={"tools": {}},
        instructions=None,
        raw={},
    )
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=list(tools)))


def _version_row(surface: DiscoverySurface, *, version_id: str, version_seq: int) -> dict:
    """A stored ``mcp_endpoint_versions`` row mirroring ``surface``."""
    return {
        "id": version_id,
        "version_seq": version_seq,
        "version_tag": f"2026-11-08T11:0{version_seq}Z",
        **surface.to_version_row(),
    }


def _change(change_type: str, name: str, item_type: str = "tool", detail=None) -> dict:
    """An ``mcp_version_changes``-shaped row."""
    return {
        "change_type": change_type,
        "item_type": item_type,
        "item_name": name,
        "detail": detail or {},
    }


# ===========================================================================
# MODULE — change summary
# ===========================================================================


def test_summary_of_no_changes_is_all_zero():
    summary = build_change_summary([], initial=False)
    assert summary == {
        "initial": False,
        "total": 0,
        "by_change_type": {"added": 0, "removed": 0, "modified": 0},
        "by_item_type": {},
        "by_severity": {"additive": 0, "review": 0, "breaking": 0},
        "max_severity": None,
    }


def test_summary_counts_change_and_item_types():
    rows = [
        _change("added", "alpha"),
        _change("added", "file:///r", item_type="resource"),
        _change("removed", "bravo"),
    ]
    summary = build_change_summary(rows, initial=False)
    assert summary["total"] == 3
    assert summary["by_change_type"] == {"added": 2, "removed": 1, "modified": 0}
    assert summary["by_item_type"] == {"resource": 1, "tool": 2}


def test_summary_reports_worst_severity():
    # Additions are additive; a removal breaks clients built against the old surface.
    additive_only = build_change_summary([_change("added", "alpha")], initial=False)
    assert additive_only["max_severity"] == "additive"
    with_removal = build_change_summary(
        [_change("added", "alpha"), _change("removed", "bravo")], initial=False
    )
    assert with_removal["by_severity"]["breaking"] == 1
    assert with_removal["max_severity"] == "breaking"


def test_summary_marks_initial_version():
    assert build_change_summary([_change("added", "a")], initial=True)["initial"] is True


# ===========================================================================
# MODULE — event assembly
# ===========================================================================


def test_event_id_is_deterministic_per_version():
    assert event_id_for_version("ver-1") == event_id_for_version("ver-1")
    assert event_id_for_version("ver-1") != event_id_for_version("ver-2")


def _built_event(previous=None) -> McpVersionCreatedEvent:
    return build_version_created_event(
        _ENDPOINT_ROW,
        {"version_id": "ver-2", "version_seq": 2, "version_tag": "2026-11-08T12:00Z"},
        previous,
        [_change("added", "bravo")],
        discovered_at=_NOW,
        discovery_trigger="sweep",
    )


def test_build_event_carries_endpoint_version_and_summary():
    event = _built_event({"id": "ver-1", "version_seq": 1})
    assert event.event_type == EVENT_TYPE_VERSION_CREATED
    assert event.event_id == event_id_for_version("ver-2")
    assert event.endpoint_id == _EP_UUID
    assert event.tenant_id == "t1"
    assert event.version_seq == 2
    assert event.previous_version_seq == 1
    assert event.change_summary["total"] == 1
    assert event.change_summary["initial"] is False


def test_payload_shape_is_json_serializable_and_omits_url():
    payload = _built_event({"id": "ver-1", "version_seq": 1}).to_payload()
    # Round-trips through JSON (what a webhook transport will do).
    assert json.loads(json.dumps(payload)) == payload
    assert payload["event_type"] == "mcp.version.created"
    assert payload["schema_version"] == EVENT_SCHEMA_VERSION
    assert payload["endpoint"] == {
        "id": _EP_UUID,
        "tenant_id": "t1",
        "name": "Acme Weather",
        "slug": "acme-weather",
    }
    assert payload["version"] == {"id": "ver-2", "seq": 2, "tag": "2026-11-08T12:00Z"}
    assert payload["previous_version"] == {"id": "ver-1", "seq": 1}
    assert payload["discovered_at"] == _NOW.isoformat()
    assert payload["trigger"] == "sweep"
    # The stored URL may embed a credential; it must never appear anywhere in the payload.
    assert "secret" not in json.dumps(payload)
    assert "endpoint_url" not in json.dumps(payload)


def test_first_version_has_no_previous():
    event = _built_event(None)
    assert event.previous_version_id is None
    assert event.to_payload()["previous_version"] is None
    assert event.change_summary["initial"] is True


# ===========================================================================
# MODULE — registry
# ===========================================================================


def test_emit_delivers_to_every_subscriber_in_order():
    seen = []
    subscribe(lambda e: seen.append(("a", e.event_id)))
    subscribe(lambda e: seen.append(("b", e.event_id)))
    event = _built_event()
    assert emit_version_created(event) == 2
    assert seen == [("a", event.event_id), ("b", event.event_id)]


def test_emit_with_no_subscribers_is_a_no_op():
    assert emit_version_created(_built_event()) == 0


def test_subscribing_twice_delivers_once():
    handler = MagicMock()
    subscribe(handler)
    subscribe(handler)
    emit_version_created(_built_event())
    handler.assert_called_once()


def test_unsubscribe_stops_delivery_and_ignores_unknown():
    handler = MagicMock()
    subscribe(handler)
    unsubscribe(handler)
    unsubscribe(handler)  # unknown now — ignored
    emit_version_created(_built_event())
    handler.assert_not_called()


def test_failing_handler_is_isolated():
    after = MagicMock()
    subscribe(MagicMock(side_effect=RuntimeError("boom")))
    subscribe(after)
    # Never raises; the healthy handler still runs; only it counts as delivered.
    assert emit_version_created(_built_event()) == 1
    after.assert_called_once()


# ===========================================================================
# ENGINE — emission from the version-on-change pipeline
# ===========================================================================


def _persist(mdb: MagicMock, surface: DiscoverySurface, trigger=None):
    with patch.object(mcp_discovery_engine, "db", mdb):
        return mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW, None, trigger
        )


def test_first_discovery_emits_one_initial_event():
    handler = MagicMock()
    subscribe(handler)
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {
        "version_id": "ver-1",
        "version_seq": 1,
        "version_tag": "2026-11-08T12:00Z",
    }
    _persist(mdb, _surface([_tool("alpha"), _tool("bravo")]), trigger="manual")

    handler.assert_called_once()
    event = handler.call_args.args[0]
    assert event.version_id == "ver-1"
    assert event.version_seq == 1
    assert event.version_tag == "2026-11-08T12:00Z"
    assert event.discovery_trigger == "manual"
    assert event.change_summary["initial"] is True
    assert event.change_summary["by_change_type"]["added"] == 2


def test_changed_discovery_emits_one_event_with_diff_summary():
    handler = MagicMock()
    subscribe(handler)
    prev_surface = _surface([_tool("alpha"), _tool("charlie")])
    mdb = MagicMock()
    mdb.get_mcp_capability_items.return_value = prev_surface.to_capability_rows("ver-1")
    mdb.get_latest_mcp_endpoint_version.return_value = _version_row(
        prev_surface, version_id="ver-1", version_seq=1
    )
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-2", "version_seq": 2}
    # charlie removed, bravo added.
    _persist(mdb, _surface([_tool("alpha"), _tool("bravo")]))

    handler.assert_called_once()
    event = handler.call_args.args[0]
    assert event.version_seq == 2
    assert event.previous_version_seq == 1
    summary = event.change_summary
    assert summary["initial"] is False
    assert summary["total"] == 2
    assert summary["by_change_type"] == {"added": 1, "removed": 1, "modified": 0}
    assert summary["max_severity"] == "breaking"
    # The summary matches exactly what was persisted as mcp_version_changes rows.
    persisted_rows = mdb.record_mcp_discovery_version.call_args.kwargs["change_rows"]
    assert summary["total"] == len(persisted_rows)


def test_unchanged_discovery_emits_nothing():
    handler = MagicMock()
    subscribe(handler)
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = {
        "id": "ver-7",
        "version_seq": 7,
        "version_tag": "2026-11-08T11:07Z",
        "surface_fingerprint": surface.fingerprint(),
    }
    result = _persist(mdb, surface)
    assert result["changed"] is False
    handler.assert_not_called()


def test_handler_failure_does_not_fail_the_job():
    subscribe(MagicMock(side_effect=RuntimeError("subscriber down")))
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    result = _persist(mdb, _surface([_tool("alpha")]))
    assert result["changed"] is True
    assert mdb.finish_mcp_discovery_job.call_args.args[1] == "completed"


def test_event_build_failure_does_not_fail_the_job(monkeypatch):
    handler = MagicMock()
    subscribe(handler)
    monkeypatch.setattr(
        mcp_discovery_engine,
        "build_version_created_event",
        MagicMock(side_effect=KeyError("version_seq")),
    )
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    result = _persist(mdb, _surface([_tool("alpha")]))
    assert result["changed"] is True
    assert mdb.finish_mcp_discovery_job.call_args.args[1] == "completed"
    handler.assert_not_called()


def test_rediscovery_sequence_emits_exactly_once_per_new_version():
    """changed → unchanged → changed yields exactly two events, one per new version."""
    events = []
    subscribe(events.append)
    v1 = _surface([_tool("alpha")])
    v2 = _surface([_tool("alpha"), _tool("bravo")])

    # 1) First discovery → version 1.
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    _persist(mdb, v1)

    # 2) Same surface again → no version, no event.
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = _version_row(
        v1, version_id="ver-1", version_seq=1
    )
    _persist(mdb, v1)

    # 3) Surface changed → version 2.
    mdb = MagicMock()
    mdb.get_mcp_capability_items.return_value = v1.to_capability_rows("ver-1")
    mdb.get_latest_mcp_endpoint_version.return_value = _version_row(
        v1, version_id="ver-1", version_seq=1
    )
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-2", "version_seq": 2}
    _persist(mdb, v2)

    assert [e.version_seq for e in events] == [1, 2]
    assert len({e.event_id for e in events}) == 2
