"""HTTP contract of the RDG-5.4 routes, with the stores faked (#5789).

The live behaviour is in ``test_usage_controls_db``. This file pins what needs no database:

* each route checks the permission it documents, and a denial never reaches the store;
* a retention value above the cap is a 422 that names the cap, and nothing is written;
* a body-sample window without the acknowledgement sentence is a 422, and nothing is written;
* the export streams CSV or JSON (with totals), is an attachment, and is audited;
* ``DELETE …/bindings?erase=true`` erases and audits ``usage.consumer.erased``; without ``erase``
  it only stamps the bindings deleted; ``anonymous`` is refused.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract import ConsumerRecord
from app.main import app
from app.permissions import Action, Resource
from app.usage_controls import (
    BODY_SAMPLE_ACKNOWLEDGEMENT,
    CODE_ACK_REQUIRED,
    CODE_RETENTION_ABOVE_CAP,
    EXPORT_FORMAT,
    RetentionDays,
    ToolsetBodySamplesOut,
    UsageRetentionResponse,
    UsageSourceOut,
    body_samples,
)

client = TestClient(app)

_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_PROJECT = {"id": "11111111-1111-4111-8111-111111111111"}
_SOURCE_ID = "22222222-2222-4222-8222-222222222222"
_TOOLSET_ID = "44444444-4444-4444-8444-444444444444"
_CONSUMER = ConsumerRecord(
    id="33333333-3333-4333-8333-333333333333",
    tenant_id="test-tenant-id",
    project_id=_PROJECT["id"],
    slug="billing-service",
    name="Billing",
)
_ROUTES = "app.usage_controls_routes"
_RETENTION = UsageRetentionResponse(
    caps=RetentionDays(hourly_days=30, rollup_days=395),
    setting=RetentionDays(),
    effective=RetentionDays(hourly_days=30, rollup_days=395),
)
_SOURCE = UsageSourceOut(
    id=_SOURCE_ID,
    kind="otlp",
    environment="prod",
    enabled=True,
    sampling_rate=1.0,
    field_capture=False,
    body_samples=body_samples(0, None, max_rate=0.05),
)
_TOOLSET = ToolsetBodySamplesOut(
    id=_TOOLSET_ID, version_id="v1", version_label="1.0.0", enabled=True, body_samples=body_samples(0, None, max_rate=1)
)
_OPEN = {
    "rate": 0.02,
    "until": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    "acknowledgement": BODY_SAMPLE_ACKNOWLEDGEMENT,
}


@pytest.fixture(autouse=True)
def _wired() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with (
        patch(f"{_ROUTES}.resolve_project", return_value=_PROJECT),
        patch("app.consumer_binding_routes.resolve_project", return_value=_PROJECT),
        patch("app.consumer_binding_routes.get_consumer", return_value=_CONSUMER),
        patch(f"{_ROUTES}.db.write_access_audit"),
    ):
        yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "body", "resource", "action", "store", "module"),
    [
        ("get", "/v1/tenants/acme/usage/retention", None, Resource.PROJECTS, Action.VIEW, "read_retention", _ROUTES),
        (
            "put",
            "/v1/tenants/acme/usage/retention",
            {"hourlyDays": 7},
            Resource.MEMBERS,
            Action.EDIT,
            "write_retention",
            _ROUTES,
        ),
        (
            "get",
            "/v1/tenants/acme/projects/pets/usage/export",
            None,
            Resource.VERSIONS,
            Action.VIEW,
            "export_day_rows",
            _ROUTES,
        ),
        (
            "get",
            "/v1/tenants/acme/projects/pets/usage/sources",
            None,
            Resource.PROJECTS,
            Action.VIEW,
            "list_sources",
            _ROUTES,
        ),
        (
            "patch",
            f"/v1/tenants/acme/projects/pets/usage/sources/{_SOURCE_ID}",
            {"fieldCapture": True},
            Resource.PROJECTS,
            Action.EDIT,
            "update_source",
            _ROUTES,
        ),
        (
            "patch",
            f"/v1/tenants/acme/agent-toolsets/{_TOOLSET_ID}/body-samples",
            {"rate": 0},
            Resource.API_KEYS,
            Action.EDIT,
            "update_toolset_body_samples",
            _ROUTES,
        ),
        (
            "delete",
            "/v1/tenants/acme/projects/pets/consumers/billing-service/bindings?erase=true",
            None,
            Resource.CONSUMER_CONTRACTS,
            Action.DELETE,
            "erase_consumer",
            "app.consumer_binding_routes",
        ),
    ],
)
def test_each_route_checks_its_permission_and_a_denial_never_reaches_the_store(
    method: str, path: str, body: Any, resource: str, action: str, store: str, module: str
) -> None:
    with (
        patch(f"{module}.enforce_permission", side_effect=HTTPException(status_code=403, detail="no")) as gate,
        patch(f"{module}.{store}") as touched,
    ):
        response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 403
    assert gate.call_args.args[2] == resource and gate.call_args.args[3] == action
    touched.assert_not_called()


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


def test_retention_above_the_cap_is_refused_with_the_cap_named_and_nothing_written() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.read_retention", return_value=_RETENTION),
        patch(f"{_ROUTES}.write_retention") as write,
    ):
        response = client.put("/v1/tenants/acme/usage/retention", json={"rollupDays": 400})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == CODE_RETENTION_ABOVE_CAP
    assert "usage_rollup_retention_days may be at most 395 days" in detail["message"]
    write.assert_not_called()


def test_lowering_retention_writes_and_audits_before_and_after() -> None:
    lowered = _RETENTION.model_copy(update={"setting": RetentionDays(hourly_days=7)})
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.read_retention", side_effect=[_RETENTION, lowered]),
        patch(f"{_ROUTES}.write_retention") as write,
        patch(f"{_ROUTES}.audit") as audited,
    ):
        response = client.put("/v1/tenants/acme/usage/retention", json={"hourlyDays": 7})
    assert response.status_code == 200, response.text
    assert response.json()["setting"] == {"hourlyDays": 7, "rollupDays": None}
    assert write.call_args.kwargs == {"hourly_days": 7, "rollup_days": None, "user_id": "u"}
    assert audited.call_args.kwargs["action"] == "usage.retention.update"
    assert audited.call_args.kwargs["detail"]["after"] == {"hourlyDays": 7, "rollupDays": None}


# ---------------------------------------------------------------------------------------------
# Sources and toolsets
# ---------------------------------------------------------------------------------------------


def test_sources_and_toolsets_share_one_body_sample_shape() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        patch(f"{_ROUTES}.list_sources", return_value=[_SOURCE]),
        patch(f"{_ROUTES}.list_toolsets", return_value=[_TOOLSET]),
    ):
        response = client.get("/v1/tenants/acme/projects/pets/usage/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["acknowledgement"] == BODY_SAMPLE_ACKNOWLEDGEMENT
    assert body["sources"][0]["bodySamples"]["maxRate"] == 0.05
    assert body["agentToolsets"][0]["bodySamples"]["maxRate"] == 1
    assert set(body["sources"][0]["bodySamples"]) == set(body["agentToolsets"][0]["bodySamples"])


@pytest.mark.parametrize(
    ("path", "body", "store"),
    [
        (
            f"/v1/tenants/acme/projects/pets/usage/sources/{_SOURCE_ID}",
            {"bodySamples": {**_OPEN, "acknowledgement": None}},
            "update_source",
        ),
        (
            f"/v1/tenants/acme/agent-toolsets/{_TOOLSET_ID}/body-samples",
            {**_OPEN, "acknowledgement": "ok"},
            "update_toolset_body_samples",
        ),
    ],
)
def test_a_body_sample_window_without_the_sentence_is_refused(path: str, body: Dict[str, Any], store: str) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.get_source", return_value=_SOURCE),
        patch(f"{_ROUTES}.get_toolset", return_value=_TOOLSET),
        patch(f"{_ROUTES}.{store}") as write,
    ):
        response = client.patch(path, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_ACK_REQUIRED
    write.assert_not_called()


def test_an_acknowledged_source_window_is_written_and_audited() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.get_source", return_value=_SOURCE),
        patch(f"{_ROUTES}.update_source", return_value=_SOURCE) as write,
        patch(f"{_ROUTES}.audit") as audited,
    ):
        response = client.patch(
            f"/v1/tenants/acme/projects/pets/usage/sources/{_SOURCE_ID}", json={"bodySamples": _OPEN}
        )
    assert response.status_code == 200, response.text
    assert write.call_args.kwargs["body_sample_rate"] == 0.02
    assert write.call_args.kwargs["body_sample_until"] is not None
    assert audited.call_args.kwargs["action"] == "usage.source.update"
    assert audited.call_args.kwargs["detail"]["acknowledged"] is True


def test_a_source_patch_that_changes_nothing_or_names_no_source_is_refused() -> None:
    with patch(f"{_ROUTES}.enforce_permission", return_value="u"), patch(f"{_ROUTES}.get_source", return_value=None):
        empty = client.patch(f"/v1/tenants/acme/projects/pets/usage/sources/{_SOURCE_ID}", json={})
        missing = client.patch(
            f"/v1/tenants/acme/projects/pets/usage/sources/{_SOURCE_ID}", json={"fieldCapture": True}
        )
    assert empty.status_code == 422 and empty.json()["detail"]["code"] == "usage-settings-unchanged"
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "usage-source-not-found"


def test_closing_a_toolset_window_needs_no_sentence() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.get_toolset", return_value=_TOOLSET),
        patch(f"{_ROUTES}.update_toolset_body_samples", return_value=_TOOLSET) as write,
        patch(f"{_ROUTES}.audit") as audited,
    ):
        response = client.patch(f"/v1/tenants/acme/agent-toolsets/{_TOOLSET_ID}/body-samples", json={"rate": 0})
    assert response.status_code == 200, response.text
    assert write.call_args.kwargs["rate"] == 0 and write.call_args.kwargs["until"] is None
    assert audited.call_args.kwargs["action"] == "agent.toolset.body_samples.update"


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def _day_rows(_db: Any, _tenant: str, _project: str, day: date) -> Any:
    return [
        {
            "day": day,
            "environment": "prod",
            "source_id": "s1",
            "source_kind": "otlp",
            "version_id": None,
            "version_label": None,
            "operation_key": "/paths/~1pets/get",
            "status_code": 500,
            "consumer": "anonymous",
            "calls": 3,
            "errors": 3,
            "latency_sum_ms": 9,
            "latency_max_ms": 4,
            "request_bytes": 0,
            "response_bytes": 0,
        }
    ]


def test_the_csv_export_streams_one_row_per_rollup_as_an_attachment() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.export_day_rows", side_effect=_day_rows),
        patch(f"{_ROUTES}.audit") as audited,
    ):
        response = client.get("/v1/tenants/acme/projects/pets/usage/export?format=csv&days=3")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment;")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 3 and {row["consumer"] for row in rows} == {"anonymous"}
    assert audited.call_args.kwargs["action"] == "usage.export"
    assert audited.call_args.kwargs["detail"]["days"] == 3


def test_the_json_export_ends_with_totals() -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.export_day_rows", side_effect=_day_rows),
        patch(f"{_ROUTES}.audit"),
    ):
        response = client.get("/v1/tenants/acme/projects/pets/usage/export?format=json&days=2")
    assert response.status_code == 200
    body = response.json()
    assert body["format"] == EXPORT_FORMAT and body["projectId"] == _PROJECT["id"]
    assert len(body["rows"]) == 2
    assert body["totals"] == {"rows": 2, "calls": 6, "errors": 6}


@pytest.mark.parametrize("query", ["format=xml", "days=0", "days=731"])
def test_an_export_outside_its_bounds_is_refused(query: str) -> None:
    with patch(f"{_ROUTES}.enforce_permission", return_value="u"), patch(f"{_ROUTES}.export_day_rows") as read:
        response = client.get(f"/v1/tenants/acme/projects/pets/usage/export?{query}")
    assert response.status_code == 422
    read.assert_not_called()


# ---------------------------------------------------------------------------------------------
# Erasure
# ---------------------------------------------------------------------------------------------

_BINDINGS = "/v1/tenants/acme/projects/pets/consumers/billing-service/bindings"
_ERASED = {"bindings": 2, "hourly_rows": 4, "daily_rows": 2, "calls": 30, "unattributed_rows": 1, "edges": 1}


def test_erase_true_erases_and_audits_the_erasure() -> None:
    with (
        patch("app.consumer_binding_routes.enforce_permission", return_value="u"),
        patch("app.consumer_binding_routes.erase_consumer", return_value=dict(_ERASED)) as erase,
        patch("app.consumer_binding_routes.delete_all_bindings") as soft,
        patch("app.consumer_binding_routes.usage_audit") as audited,
    ):
        response = client.delete(f"{_BINDINGS}?erase=true")
    assert response.status_code == 200, response.text
    assert response.json() == {"consumer": "billing-service", "erased": True, **_ERASED}
    assert erase.call_args.args[1:] == ("test-tenant-id", _CONSUMER.id)
    soft.assert_not_called()
    assert audited.call_args.kwargs["action"] == "usage.consumer.erased"
    assert audited.call_args.kwargs["detail"]["calls"] == 30


def test_without_erase_the_bindings_are_only_stamped_deleted() -> None:
    with (
        patch("app.consumer_binding_routes.enforce_permission", return_value="u"),
        patch("app.consumer_binding_routes.erase_consumer") as erase,
        patch("app.consumer_binding_routes.delete_all_bindings", return_value=2),
        patch("app.consumer_binding_routes.usage_audit") as audited,
    ):
        response = client.delete(_BINDINGS)
    assert response.status_code == 200
    assert response.json()["erased"] is False and response.json()["bindings"] == 2
    erase.assert_not_called()
    audited.assert_not_called()


def test_anonymous_cannot_be_erased() -> None:
    with (
        patch("app.consumer_binding_routes.enforce_permission", return_value="u"),
        patch("app.consumer_binding_routes.erase_consumer") as erase,
    ):
        response = client.delete("/v1/tenants/acme/projects/pets/consumers/anonymous/bindings?erase=true")
    assert response.status_code == 400
    erase.assert_not_called()
