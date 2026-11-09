"""Tests for the MCP public publish workflow + guards (V2-MCP-23.5 / MCAT-9.5, #3695).

Covers the pure guards in :mod:`app.mcp_publish_guards` (credentials scan of the public view's
fields, minimum lint grade, reachability) and the routes that use them:
``POST …/endpoints/{id}/publish``, ``POST …/endpoints/{id}/unpublish`` and the PATCH path that
would otherwise bypass the guards.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_publish_guards import (
    GUARD_CREDENTIALS,
    GUARD_GRADE,
    GUARD_REACHABLE,
    HEALTH_PROBE_WINDOW_HOURS,
    check_credentials,
    check_grade,
    check_reachable,
    evaluate_publish_guards,
    failed_guards,
    grade_meets_minimum,
    normalize_min_grade,
    public_text_fields,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
_EP = "11111111-1111-1111-1111-111111111111"
_VID = "22222222-2222-2222-2222-222222222222"

#: A healthy, discovered, private endpoint — every guard passes for it by default.
_ENDPOINT = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "description": "Forecasts and alerts",
    "category": "weather",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "last_discovered_at": _NOW,
    "last_discovery_status": "changed",
    "consecutive_failures": 0,
    "quarantined_at": None,
    "current_version_id": _VID,
    "created_at": _NOW,
    "updated_at": _NOW,
}

_VERSION = {
    "id": _VID,
    "endpoint_id": _EP,
    "server_name": "acme-weather",
    "server_title": "Acme Weather",
    "instructions": "Ask for a forecast by city.",
    "score": 84,
    "grade": "B",
}

_ITEMS = [
    {"item_type": "tool", "name": "get_forecast", "title": "Forecast", "description": "City forecast"},
    {"item_type": "prompt", "name": "summary", "title": None, "description": "Summarize alerts"},
]

_UP_PROBE = {"status": "up", "error_code": None, "checked_at": _NOW}
_DOWN_PROBE = {"status": "down", "error_code": "timeout", "checked_at": _NOW}

#: A fake GitHub token — matched by the scrubber's provider-key patterns.
_GH_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_db(mdb, *, endpoint=None, version=_VERSION, items=_ITEMS, probes=(_UP_PROBE,)):
    """Wire a patched ``db`` with an endpoint, its current surface and health probes."""
    row = dict(endpoint or _ENDPOINT)
    mdb.get_mcp_endpoint.return_value = row
    mdb.get_mcp_endpoint_version.return_value = version
    mdb.get_mcp_capability_items.return_value = list(items)
    mdb.list_mcp_health_checks.return_value = list(probes)
    mdb.update_mcp_endpoint.side_effect = lambda _t, _id, fields: {**row, **fields}
    return row


# ===========================================================================
# Grade setting / comparison
# ===========================================================================


@pytest.mark.parametrize("raw, expected", [("C", "C"), ("b", "B"), (" a ", "A"), ("F", "F")])
def test_normalize_min_grade_letters(raw, expected):
    assert normalize_min_grade(raw) == expected


@pytest.mark.parametrize("raw", ["off", "OFF", "none", "disabled", "", None])
def test_normalize_min_grade_disabled(raw):
    assert normalize_min_grade(raw) is None


@pytest.mark.parametrize("raw", ["E", "A+", "90", "best"])
def test_normalize_min_grade_rejects_unknown(raw):
    with pytest.raises(ValueError):
        normalize_min_grade(raw)


@pytest.mark.parametrize(
    "grade, minimum, ok",
    [("A", "C", True), ("C", "C", True), ("D", "C", False), ("F", "A", False), ("b", "B", True),
     (None, "F", False), ("?", "F", False)],
)
def test_grade_meets_minimum(grade, minimum, ok):
    assert grade_meets_minimum(grade, minimum) is ok


# ===========================================================================
# Guards (pure)
# ===========================================================================


def test_public_text_fields_lists_view_and_surface_text():
    fields = dict(public_text_fields(_ENDPOINT, _VERSION, _ITEMS))
    assert fields["name"] == "Acme Weather"
    assert fields["host"] == "mcp.acme.example"
    assert fields["version.instructions"] == "Ask for a forecast by city."
    assert fields["tool:get_forecast.description"] == "City forecast"
    # Empty values are skipped, and the raw URL is never a scanned public field.
    assert "prompt:summary.title" not in fields
    assert "endpoint_url" not in fields


def test_public_text_fields_host_strips_userinfo():
    row = {**_ENDPOINT, "endpoint_url": f"https://user:{_GH_TOKEN}@mcp.acme.example/mcp"}
    assert dict(public_text_fields(row, None, []))["host"] == "mcp.acme.example"


def test_check_credentials_passes_clean_fields():
    result = check_credentials(public_text_fields(_ENDPOINT, _VERSION, _ITEMS))
    assert result.passed and result.guard == GUARD_CREDENTIALS
    assert result.details["findings"] == []


def test_check_credentials_flags_secret_in_description_without_echoing_it():
    row = {**_ENDPOINT, "description": f"Use token {_GH_TOKEN} to connect"}
    result = check_credentials(public_text_fields(row, _VERSION, _ITEMS))
    assert not result.passed
    assert {f["field"] for f in result.details["findings"]} == {"description"}
    assert _GH_TOKEN not in result.reason
    assert _GH_TOKEN not in str(result.as_dict())


def test_check_credentials_flags_secret_in_capability_description():
    items = [*_ITEMS, {"item_type": "tool", "name": "call", "description": f"Authorization: Bearer {_GH_TOKEN}"}]
    result = check_credentials(public_text_fields(_ENDPOINT, _VERSION, items))
    assert not result.passed
    assert "tool:call.description" in result.reason


def test_check_credentials_flags_secret_in_instructions():
    version = {**_VERSION, "instructions": "password=hunter2-SuperSecret!"}
    result = check_credentials(public_text_fields(_ENDPOINT, version, []))
    assert not result.passed
    assert result.details["findings"][0]["field"] == "version.instructions"


def test_check_grade_passes_at_or_above_minimum():
    result = check_grade(_VERSION, "C")
    assert result.passed and result.guard == GUARD_GRADE
    assert result.details == {"grade": "B", "score": 84, "min_grade": "C"}


def test_check_grade_fails_below_minimum():
    result = check_grade({**_VERSION, "grade": "D", "score": 61}, "C")
    assert not result.passed
    assert "D" in result.reason and "C" in result.reason


def test_check_grade_fails_when_unscored():
    result = check_grade({**_VERSION, "grade": None, "score": None}, "F")
    assert not result.passed
    assert "no lint grade" in result.reason


def test_check_grade_fails_when_never_discovered():
    assert not check_grade(None, "F").passed


def test_check_grade_disabled_always_passes():
    result = check_grade(None, None)
    assert result.passed
    assert "turned off" in result.reason


def test_check_reachable_healthy_with_up_probe():
    result = check_reachable(_ENDPOINT, _UP_PROBE)
    assert result.passed and result.guard == GUARD_REACHABLE
    assert result.details["health"] == "healthy"
    assert result.details["probe_status"] == "up"


def test_check_reachable_healthy_without_probe():
    assert check_reachable(_ENDPOINT, None).passed


@pytest.mark.parametrize(
    "overrides, health",
    [
        ({"quarantined_at": _NOW}, "quarantined"),
        ({"enabled": False}, "disabled"),
        ({"current_version_id": None}, "undiscovered"),
        ({"consecutive_failures": 2}, "failing"),
    ],
)
def test_check_reachable_fails_on_unhealthy_state(overrides, health):
    result = check_reachable({**_ENDPOINT, **overrides}, _UP_PROBE)
    assert not result.passed
    assert result.details["health"] == health


def test_check_reachable_fails_on_down_probe():
    result = check_reachable(_ENDPOINT, _DOWN_PROBE)
    assert not result.passed
    assert "timeout" in result.reason
    assert result.details["probe_error_code"] == "timeout"


def test_evaluate_publish_guards_runs_every_guard_in_order():
    results = evaluate_publish_guards(
        endpoint={**_ENDPOINT, "enabled": False, "description": f"key {_GH_TOKEN}"},
        version={**_VERSION, "grade": "F"},
        capability_items=_ITEMS,
        latest_probe=None,
        min_grade="C",
    )
    assert [r.guard for r in results] == [GUARD_CREDENTIALS, GUARD_GRADE, GUARD_REACHABLE]
    assert [r.guard for r in failed_guards(results)] == [GUARD_CREDENTIALS, GUARD_GRADE, GUARD_REACHABLE]


# ===========================================================================
# POST …/publish
# ===========================================================================


def test_publish_ok_sets_published_public():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["endpoint"]["published"] is True
    assert body["endpoint"]["visibility"] == "public"
    assert [g["guard"] for g in body["guards"]] == ["credentials", "grade", "reachable"]
    assert all(g["passed"] for g in body["guards"])
    args = mdb.update_mcp_endpoint.call_args.args
    assert args[:2] == ("t1", _EP)
    assert args[2] == {"published": True, "visibility": "public"}
    mdb.list_mcp_health_checks.assert_called_once_with(
        _EP, window_hours=HEALTH_PROBE_WINDOW_HOURS, limit=1
    )


def test_publish_blocked_lists_every_failed_guard():
    endpoint = {**_ENDPOINT, "description": f"token {_GH_TOKEN}", "quarantined_at": _NOW}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint, version={**_VERSION, "grade": "D"})
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "publish_guards_failed"
    assert detail["failed_guards"] == ["credentials", "grade", "reachable"]
    assert detail["message"].startswith("Publish blocked:")
    assert len(detail["guards"]) == 3
    assert _GH_TOKEN not in r.text
    mdb.update_mcp_endpoint.assert_not_called()


def test_publish_blocked_when_grade_below_minimum():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, version={**_VERSION, "grade": "D", "score": 62})
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["grade"]


def test_publish_blocked_when_probe_down():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, probes=(_DOWN_PROBE,))
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["reachable"]


def test_publish_blocked_when_never_discovered():
    endpoint = {**_ENDPOINT, "current_version_id": None}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint, version=None, items=[])
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["grade", "reachable"]
    mdb.get_mcp_endpoint_version.assert_not_called()


def test_publish_respects_configured_min_grade():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.settings.mcp_publish_min_grade", "A"
    ):
        _mock_db(mdb)
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["grade"]


def test_publish_grade_guard_off_allows_unscored():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.settings.mcp_publish_min_grade", "off"
    ):
        _mock_db(mdb, version={**_VERSION, "grade": None, "score": None})
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 200


def test_publish_misconfigured_min_grade_503():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.settings.mcp_publish_min_grade", "Z"
    ):
        _mock_db(mdb)
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 503
    mdb.update_mcp_endpoint.assert_not_called()


def test_publish_response_redacts_endpoint_url_credentials():
    endpoint = {**_ENDPOINT, "endpoint_url": f"https://bot:{_GH_TOKEN}@mcp.acme.example/mcp"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint)
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 200
    assert _GH_TOKEN not in r.text
    assert r.json()["endpoint"]["endpoint_url"] == "https://***@mcp.acme.example/mcp"


def test_publish_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code == 404
    assert mdb.get_mcp_endpoint.call_args.args == ("t1", _EP)
    mdb.update_mcp_endpoint.assert_not_called()


def test_publish_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/publish")
    assert r.status_code in (401, 403)


# ===========================================================================
# POST …/unpublish
# ===========================================================================


def test_unpublish_reverts_to_private():
    endpoint = {**_ENDPOINT, "published": True, "visibility": "public"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint)
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/unpublish")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoint"]["published"] is False
    assert body["endpoint"]["visibility"] == "private"
    assert body["guards"] == []
    assert mdb.update_mcp_endpoint.call_args.args[2] == {"published": False, "visibility": "private"}
    # No guard runs on unpublish.
    mdb.list_mcp_health_checks.assert_not_called()


def test_unpublish_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/unpublish")
    assert r.status_code == 404
    mdb.update_mcp_endpoint.assert_not_called()


# ===========================================================================
# PATCH cannot bypass the guards
# ===========================================================================


def test_patch_to_public_published_runs_guards_and_blocks():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, version={**_VERSION, "grade": "F"})
        r = client.patch(
            f"/v1/mcp/acme/endpoints/{_EP}", json={"published": True, "visibility": "public"}
        )
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["grade"]
    mdb.update_mcp_endpoint.assert_not_called()


def test_patch_to_public_published_passes_when_guards_pass():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.patch(
            f"/v1/mcp/acme/endpoints/{_EP}", json={"published": True, "visibility": "public"}
        )
    assert r.status_code == 200
    assert r.json()["endpoint"]["published"] is True


def test_patch_publishing_with_secret_in_new_description_blocked():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.patch(
            f"/v1/mcp/acme/endpoints/{_EP}",
            json={"published": True, "visibility": "public", "description": f"key {_GH_TOKEN}"},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["failed_guards"] == ["credentials"]


def test_patch_public_endpoint_text_runs_credentials_guard_only():
    endpoint = {**_ENDPOINT, "published": True, "visibility": "public", "quarantined_at": _NOW}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint)
        bad = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"description": f"tok {_GH_TOKEN}"})
        # A clean edit passes even though the endpoint is quarantined: only credentials are checked.
        ok = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"description": "Forecasts"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["failed_guards"] == ["credentials"]
    assert ok.status_code == 200
    mdb.list_mcp_health_checks.assert_not_called()


def test_patch_private_endpoint_skips_guards():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, version={**_VERSION, "grade": "F"})
        r = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"published": True})
    # Published but still private: not in the public view, so no guard applies.
    assert r.status_code == 200
    mdb.get_mcp_endpoint_version.assert_not_called()


def test_patch_unpublish_skips_guards():
    endpoint = {**_ENDPOINT, "published": True, "visibility": "public"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, endpoint=endpoint, version={**_VERSION, "grade": "F"})
        r = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"published": False})
    assert r.status_code == 200


def test_patch_non_public_fields_do_not_read_endpoint():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.update_mcp_endpoint.return_value = _ENDPOINT
        r = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"enabled": False})
    assert r.status_code == 200
    mdb.get_mcp_endpoint.assert_not_called()


def test_patch_public_fields_cross_tenant_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.patch(f"/v1/mcp/acme/endpoints/{_EP}", json={"published": True})
    assert r.status_code == 404
    mdb.update_mcp_endpoint.assert_not_called()
