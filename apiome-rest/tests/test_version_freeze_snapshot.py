"""Frozen OpenAPI snapshots (CLI 4.7, #3214).

The rules in :mod:`app.spec_snapshot`, the ``…/freeze-schema`` POST / GET / DELETE routes, and
``GET /v1/schema`` serving the stored bytes — all with the database mocked. (A live-database run
of the whole flow — freeze, edit a class, fetch byte-identical, unfreeze refused after downloads,
forced unfreeze — was done by hand for the PR.)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.spec_snapshot import (
    CODE_DOWNLOADED,
    CODE_FORCE_REQUIRES_ADMIN,
    SpecCounts,
    build_live_spec,
    render_spec_bytes,
    row_summary,
    snapshot_url,
    summarize,
    unfreeze_refusal,
)

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_BASE = "/v1/versions/acme/p1/v1/freeze-schema"


# --- rules ----------------------------------------------------------------------------------


def test_rendered_bytes_match_what_json_response_sends() -> None:
    from fastapi.responses import JSONResponse

    spec = {"openapi": "3.1.0", "info": {"title": "Zahlungen — API"}, "paths": {}}
    assert render_spec_bytes(spec) == JSONResponse(content=spec).body


def test_the_live_spec_counts_classes_properties_and_paths() -> None:
    db = MagicMock()
    db.get_classes_for_version.return_value = [{"id": "c1"}, {"id": "c2"}]
    db.get_properties_for_class.side_effect = [[{"name": "a"}, {"name": "b"}], [{"name": "c"}]]
    with patch(
        "app.spec_snapshot.generate_openapi_spec",
        return_value={"paths": {"/charges": {}, "/refunds": {}, "/x": {}}},
    ):
        spec, counts = build_live_spec(db, {"id": "v1"}, "acme", "payments", "2.1.0")
    assert counts == SpecCounts(classes=2, properties=3, paths=3)
    assert "/charges" in spec["paths"]


def test_the_summary_carries_sha_size_and_url() -> None:
    content = b'{"openapi":"3.1.0"}'
    body = summarize(content=content, counts=SpecCounts(1, 2, 3), url="/v1/schema/a/b/1.0.0", frozen=True)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["size_bytes"] == len(content)
    assert (body["class_count"], body["property_count"], body["path_count"]) == (1, 2, 3)
    assert snapshot_url("acme", "payments", "2.1.0") == "/v1/schema/acme/payments/2.1.0"


@pytest.mark.parametrize(
    ("downloads", "force", "admin", "owner", "expected"),
    [
        (0, False, False, True, None),
        (0, False, True, False, None),
        (0, False, False, False, (403, "forbidden")),
        (3, False, True, True, (409, CODE_DOWNLOADED)),
        (3, True, True, False, None),
        (3, True, False, True, (403, CODE_FORCE_REQUIRES_ADMIN)),
    ],
)
def test_unfreeze_refusal(downloads, force, admin, owner, expected) -> None:
    refusal = unfreeze_refusal(downloads, force=force, is_admin=admin, is_owner=owner)
    if expected is None:
        assert refusal is None
    else:
        assert (refusal[0], refusal[1]["code"]) == expected


# --- routes ---------------------------------------------------------------------------------

_VERSION = {
    "id": "v1",
    "project_id": "p1",
    "project_slug": "payments",
    "version_id": "2.1.0",
    "creator_id": "user-1",
    "published": True,
}
_SNAPSHOT = {
    "version_id": "v1",
    "sha256": "ab" * 32,
    "size_bytes": 10,
    "class_count": 1,
    "property_count": 2,
    "path_count": 3,
    "frozen_by": "user-1",
    "frozen_at": "2026-10-16T12:00:00Z",
    "download_count": 0,
}
_SPEC = {"openapi": "3.1.0", "paths": {"/charges": {}}}


def _call(
    method: str,
    url: str = _BASE,
    *,
    json_body: Any = None,
    version: Optional[Dict[str, Any]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    is_admin: bool = False,
    inserted: Any = "default",
):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with (
            patch("app.versions_routes.db") as mock_db,
            patch("app.versions_routes.enforce_permission"),
            patch("app.versions_routes.get_authenticated_user_id", return_value="user-1"),
            patch("app.versions_routes.build_live_spec", return_value=(_SPEC, SpecCounts(1, 2, 1))),
        ):
            mock_db.get_version_by_id.return_value = version if version is not None else _VERSION
            mock_db.get_version_by_slugs.return_value = {"id": "v1"}
            mock_db.get_spec_snapshot.return_value = snapshot
            mock_db.is_user_tenant_admin.return_value = is_admin
            mock_db.version_has_class_schema.return_value = True
            mock_db.insert_spec_snapshot.return_value = (
                {**_SNAPSHOT, "sha256": hashlib.sha256(render_spec_bytes(_SPEC)).hexdigest()}
                if inserted == "default"
                else inserted
            )
            mock_db.delete_spec_snapshot.return_value = snapshot
            kwargs = {"json": json_body} if json_body is not None else {}
            response = client.request(method, url, **kwargs)
            return response, mock_db
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_freeze_stores_the_rendered_bytes_and_returns_the_sha() -> None:
    response, db = _call("POST")
    assert response.status_code == 200, response.text
    body = response.json()
    content = render_spec_bytes(_SPEC)
    assert body["frozen"] is True and body["dryRun"] is False
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["sizeBytes"] == len(content)
    assert body["snapshotUrl"] == "/v1/schema/acme/payments/2.1.0"
    assert (body["classCount"], body["propertyCount"], body["pathCount"]) == (1, 2, 1)
    assert db.insert_spec_snapshot.call_args.kwargs["content"] == content
    db.freeze_version_schema.assert_not_called()  # class schemas were already captured


def test_freeze_captures_class_schemas_when_missing() -> None:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with (
            patch("app.versions_routes.db") as mock_db,
            patch("app.versions_routes.enforce_permission"),
            patch("app.versions_routes.get_authenticated_user_id", return_value="user-1"),
            patch("app.versions_routes.build_live_spec", return_value=(_SPEC, SpecCounts(1, 0, 1))),
        ):
            mock_db.get_version_by_id.return_value = _VERSION
            mock_db.get_spec_snapshot.return_value = None
            mock_db.is_user_tenant_admin.return_value = False
            mock_db.version_has_class_schema.return_value = False
            mock_db.insert_spec_snapshot.return_value = _SNAPSHOT
            assert client.post(_BASE).status_code == 200
            mock_db.freeze_version_schema.assert_called_once_with("v1", "tenant-1", "user-1")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_a_dry_run_writes_nothing() -> None:
    response, db = _call("POST", json_body={"dryRun": True})
    assert response.status_code == 200
    assert response.json()["dryRun"] is True and response.json()["frozen"] is False
    db.insert_spec_snapshot.assert_not_called()
    db.freeze_version_schema.assert_not_called()


def test_a_draft_cannot_be_frozen() -> None:
    response, db = _call("POST", version={**_VERSION, "published": False})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_not_published"
    db.insert_spec_snapshot.assert_not_called()


def test_freezing_twice_is_a_409_with_the_existing_sha() -> None:
    response, _ = _call("POST", snapshot=_SNAPSHOT)
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "already_frozen",
        "message": "2.1.0 is already frozen.",
        "sha256": "ab" * 32,
    }


def test_a_lost_insert_race_is_also_already_frozen() -> None:
    response, _ = _call("POST", inserted=None)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_frozen"


def test_only_the_creator_or_an_admin_may_freeze() -> None:
    response, db = _call("POST", version={**_VERSION, "creator_id": "someone-else"})
    assert response.status_code == 403
    db.insert_spec_snapshot.assert_not_called()


def test_status_of_an_unfrozen_version() -> None:
    response, _ = _call("GET")
    assert response.status_code == 200
    assert response.json()["frozen"] is False
    assert response.json()["snapshotUrl"] == "/v1/schema/acme/payments/2.1.0"


def test_status_of_a_frozen_version_reports_downloads() -> None:
    response, _ = _call("GET", snapshot={**_SNAPSHOT, "download_count": 4})
    body = response.json()
    assert body["frozen"] is True and body["downloadCount"] == 4 and body["sha256"] == "ab" * 32


def test_unfreeze_without_downloads() -> None:
    response, db = _call("DELETE", snapshot=_SNAPSHOT)
    assert response.status_code == 200
    assert response.json()["frozen"] is False
    db.delete_spec_snapshot.assert_called_once_with("v1")


def test_unfreeze_after_downloads_is_refused_without_force() -> None:
    response, db = _call("DELETE", snapshot={**_SNAPSHOT, "download_count": 2})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "snapshot_downloaded"
    assert response.json()["detail"]["download_count"] == 2
    db.delete_spec_snapshot.assert_not_called()


def test_force_unfreeze_needs_an_admin() -> None:
    response, db = _call("DELETE", f"{_BASE}?force=true", snapshot={**_SNAPSHOT, "download_count": 2})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "force_unfreeze_requires_admin"
    db.delete_spec_snapshot.assert_not_called()

    admin, db = _call(
        "DELETE", f"{_BASE}?force=true", snapshot={**_SNAPSHOT, "download_count": 2}, is_admin=True
    )
    assert admin.status_code == 200
    db.delete_spec_snapshot.assert_called_once()


def test_unfreezing_an_unfrozen_version_is_a_404() -> None:
    response, _ = _call("DELETE")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_frozen"


def test_row_summary_strips_the_char_padding() -> None:
    assert row_summary({**_SNAPSHOT, "sha256": "ab" * 32 + " "}, "/u", frozen=True)["sha256"] == "ab" * 32


# --- /v1/schema ------------------------------------------------------------------------------


def _schema_get(snapshot: Optional[Dict[str, Any]]):
    with (
        patch("app.main.db") as mock_db,
        patch("app.main.validate_private_access"),
        patch("app.main.build_live_spec", return_value=(_SPEC, SpecCounts(1, 0, 1))) as live,
    ):
        mock_db.get_version_by_slugs.return_value = {"id": "v1", "published": True, "visibility": "public"}
        mock_db.get_spec_snapshot.return_value = snapshot
        response = client.get("/v1/schema/acme/payments/2.1.0")
        return response, mock_db, live


def test_a_frozen_version_serves_the_stored_bytes_and_counts_the_download() -> None:
    stored = b'{"openapi":"3.1.0","frozen":true}'
    response, db, live = _schema_get({**_SNAPSHOT, "content": stored})
    assert response.status_code == 200
    assert response.content == stored
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-apiome-snapshot-sha256"] == "ab" * 32
    db.record_spec_snapshot_download.assert_called_once_with("v1")
    live.assert_not_called()


def test_an_unfrozen_version_is_generated_live() -> None:
    response, db, live = _schema_get(None)
    assert response.status_code == 200
    assert json.loads(response.content) == _SPEC
    assert response.content == render_spec_bytes(_SPEC)
    db.record_spec_snapshot_download.assert_not_called()
    live.assert_called_once()
