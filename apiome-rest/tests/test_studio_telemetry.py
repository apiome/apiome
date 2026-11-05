"""Export studio usage telemetry — MFX-46.5 (#4383).

The rules (:func:`app.studio_telemetry.normalize_event`): each kind needs its own field, a target must be
a registered export target and is recorded as its canonical format, the lossy events take only a lossy
or severe verdict, and unknown fields or values are refused. The counters (``kind``, ``kind:surface``,
``kind:<value>``) and the acknowledge-lossy rate. Then the route: auth, 200 / 422, and nothing but the
controlled vocabulary in the log line.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import validate_authentication
from app.main import app
from app.studio_telemetry import StudioMetricRequest, StudioTelemetry, normalize_event, studio_telemetry

client = TestClient(app)
_URL = "/v1/export/acme/studio-metrics"


def _event(**fields: Any) -> Dict[str, Any]:
    return normalize_event(StudioMetricRequest.model_validate(fields))


# ===========================================================================
# The rules
# ===========================================================================


def test_a_chosen_target_is_recorded_as_its_canonical_format() -> None:
    assert _event(kind="target_chosen", target="openapi") == {
        "kind": "target_chosen", "surface": "studio", "target": "openapi-3.1", "mode": "single"}
    assert _event(kind="target_chosen", target="protobuf", mode="multi", surface="dialog")["target"] == "proto3"
    with pytest.raises(ValueError, match="unknown export target"):
        _event(kind="target_chosen", target="not-a-format")
    with pytest.raises(ValidationError):
        StudioMetricRequest.model_validate({"kind": "target_chosen", "target": "Orders API/v1"})


def test_each_kind_needs_its_field() -> None:
    for kind, field in (("target_chosen", "target"), ("verify_verdict", "verdict"), ("lossy_prompt_shown", "verdict"),
                        ("lossy_acknowledged", "verdict"), ("test_drive_used", "tool"), ("viz_used", "view")):
        with pytest.raises(ValueError, match=field):
            _event(kind=kind)


def test_verdicts_tools_and_views_are_recorded() -> None:
    assert _event(kind="verify_verdict", verdict="error")["verdict"] == "error"
    assert _event(kind="lossy_acknowledged", verdict="severe")["verdict"] == "severe"
    with pytest.raises(ValueError, match="lossy or severe"):
        _event(kind="lossy_prompt_shown", verdict="clean")
    assert _event(kind="test_drive_used", tool="graphiql") == {
        "kind": "test_drive_used", "surface": "studio", "tool": "graphiql", "action": "open"}
    assert _event(kind="test_drive_used", tool="toolchain", action="run")["action"] == "run"
    assert _event(kind="viz_used", view="erd") == {"kind": "viz_used", "surface": "studio", "view": "erd"}
    # Only the kind's own field is recorded.
    assert "view" not in _event(kind="verify_verdict", verdict="clean", view="erd")


def test_anything_outside_the_vocabulary_is_refused() -> None:
    for bad in ({"kind": "page_view"}, {"kind": "viz_used", "view": "sankey"},
                {"kind": "verify_verdict", "verdict": "fine"}, {"kind": "test_drive_used", "tool": "curl"},
                {"kind": "viz_used", "view": "erd", "artifact": "Orders API"}, {"kind": "viz_used", "view": "erd",
                                                                                 "surface": "cli"}):
        with pytest.raises(ValidationError):
            StudioMetricRequest.model_validate(bad)


def test_counters_and_the_acknowledge_lossy_rate() -> None:
    telemetry = StudioTelemetry()
    assert telemetry.acknowledge_lossy_rate() is None
    telemetry.record(_event(kind="verify_verdict", verdict="lossy"))
    telemetry.record(_event(kind="lossy_prompt_shown", verdict="lossy"))
    telemetry.record(_event(kind="lossy_prompt_shown", verdict="severe", surface="dialog"))
    telemetry.record(_event(kind="lossy_prompt_shown", verdict="lossy"))
    telemetry.record(_event(kind="lossy_acknowledged", verdict="lossy"))
    telemetry.record(_event(kind="test_drive_used", tool="toolchain", action="run"))
    counts = telemetry.snapshot()
    assert counts["verify_verdict:lossy"] == 1
    assert counts["lossy_prompt_shown"] == 3 and counts["lossy_prompt_shown:dialog"] == 1
    assert counts["test_drive_used:toolchain:run"] == 1
    assert telemetry.acknowledge_lossy_rate() == pytest.approx(0.3333)
    telemetry.reset()
    assert telemetry.snapshot() == {}


# ===========================================================================
# The route
# ===========================================================================


@pytest.fixture()
def _authed():
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t1", "user_id": "u1",
                                                                 "auth_method": "jwt"}
    studio_telemetry.reset()
    yield
    app.dependency_overrides.clear()
    studio_telemetry.reset()


def test_the_route_records_an_event(_authed) -> None:
    response = client.post(_URL, json={"kind": "target_chosen", "target": "graphql", "mode": "multi"})
    assert response.status_code == 200, response.text
    assert response.json() == {"recorded": True, "kind": "target_chosen"}
    assert studio_telemetry.snapshot() == {"target_chosen": 1, "target_chosen:studio": 1, "target_chosen:graphql": 1}


def test_the_route_refuses_a_bad_event(_authed) -> None:
    assert client.post(_URL, json={"kind": "viz_used"}).status_code == 422
    assert client.post(_URL, json={"kind": "target_chosen", "target": "nope"}).status_code == 422
    assert client.post(_URL, json={"kind": "viz_used", "view": "erd", "name": "x"}).status_code == 422
    assert studio_telemetry.snapshot() == {}


def test_the_route_needs_authentication() -> None:
    app.dependency_overrides.clear()
    assert client.post(_URL, json={"kind": "viz_used", "view": "erd"}).status_code in (401, 403)
