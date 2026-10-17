"""``POST /v1/versions/{tenant}/{project}/fork`` duplicate label → 409 (CLI 4.4, #3211).

Forking into a target that already has the ``versionId`` hits the ``(project_id, version_id)``
unique key; it used to surface as a 400 carrying the raw database message. It is now a ``409``
with ``detail.code`` ``version_exists``, which ``apiome versions fork`` maps to exit 6. (The
database message was confirmed against a live database: ``duplicate key value violates unique
constraint "versions_project_id_version_id_key"``.)
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}


def _post(error: str):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.versions_routes.db") as mock_db, patch(
            "app.versions_routes.enforce_permission"
        ), patch("app.versions_routes.get_authenticated_user_id", return_value="user-1"):
            mock_db.get_project_by_id.return_value = {"id": "tgt", "metadata": {}}
            mock_db.create_forked_version.return_value = {"success": False, "error": error}
            return client.post(
                "/v1/versions/acme/tgt/fork",
                json={"sourceRevisionId": "src-rev", "versionId": "3.0.0", "shortMessage": "fork"},
            )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_a_duplicate_version_label_is_a_409() -> None:
    response = _post(
        'duplicate key value violates unique constraint "versions_project_id_version_id_key"'
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail == {
        "code": "version_exists",
        "message": "Version 3.0.0 already exists in this project.",
        "version_id": "3.0.0",
    }


def test_a_same_project_fork_is_still_a_400() -> None:
    response = _post(
        "Fork requires a different target project than the source. Use “Branch from here” for "
        "named branches within the same project."
    )
    assert response.status_code == 400


def test_a_missing_source_is_still_a_404() -> None:
    assert _post("Source revision not found or not accessible").status_code == 404
