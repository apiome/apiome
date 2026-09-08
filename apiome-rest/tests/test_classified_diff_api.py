"""Tests for POST /v1/diff/{tenant_slug}/classified (CTG-1.2 / #4468)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.classified_diff_routes import INLINE_SPEC_MAX_BYTES
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "tenant-1",
    "user_id": "user-1",
    "auth_method": "jwt",
}

_FAKE_PROJECT = {
    "id": "proj-1",
    "tenant_id": "tenant-1",
    "slug": "pets",
    "description": "d",
    "metadata": "{}",
}

_FAKE_BASE_VER = {
    "id": "base-rev",
    "project_id": "proj-1",
    "version_id": "1.0.0",
}

_FAKE_HEAD_VER = {
    "id": "head-rev",
    "project_id": "proj-1",
    "version_id": "1.1.0",
}

_BASE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}

_HEAD_REMOVED_PATH = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.1.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}

_HEAD_ADDED_PATH_YAML = yaml.dump(
    {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.1.0"},
        "paths": {
            "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/stores": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
    }
)


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture
def mock_auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_classified_diff_requires_auth():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(
        "/v1/diff/acme/classified",
        json={
            "base": {"project": "pets", "version": "1.0.0"},
            "head": {"project": "pets", "version": "1.1.0"},
        },
    )
    assert r.status_code == 401


def test_classified_diff_stored_vs_stored_breaking(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            side_effect=[_BASE_SPEC, _HEAD_REMOVED_PATH],
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.side_effect = lambda pid, ver, tid: (
            _FAKE_BASE_VER
            if ver == "1.0.0"
            else _FAKE_HEAD_VER
            if ver == "1.1.0"
            else None
        )
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"project": "pets", "version": "1.1.0"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["maxSeverity"] == "breaking"
    assert data["counts"]["breaking"] >= 1
    assert data["counts"]["total"] >= 1
    assert any(c["ruleId"] == "ctg.path_removed" for c in data["changes"])
    assert data["base"]["projectSlug"] == "pets"
    assert data["base"]["versionLabel"] == "1.0.0"
    assert data["head"]["source"] == "stored"
    assert data["head"]["versionLabel"] == "1.1.0"


def test_classified_diff_inline_vs_stored(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"inline": _HEAD_ADDED_PATH_YAML},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["head"]["source"] == "inline"
    assert data["head"]["projectId"] is None
    assert data["maxSeverity"] == "non-breaking"
    assert any(c["ruleId"] == "ctg.path_added" for c in data["changes"])
    assert data["counts"]["non-breaking"] >= 1


def test_classified_diff_inline_over_10mb_rejected(mock_auth):
    oversized = "x" * (INLINE_SPEC_MAX_BYTES + 1)
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        with patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ):
            r = client.post(
                "/v1/diff/acme/classified",
                json={
                    "base": {"project": "pets", "version": "1.0.0"},
                    "head": {"inline": oversized},
                },
                headers={"Authorization": "Bearer x"},
            )
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert str(INLINE_SPEC_MAX_BYTES) in detail
    assert "exceeds" in detail.lower()


def test_classified_diff_unknown_project_404(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = None
        mock_db.get_project_by_id.return_value = None
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "missing", "version": "1.0.0"},
                "head": {"project": "missing", "version": "1.1.0"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


def test_classified_diff_unknown_version_404(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = None
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "9.9.9"},
                "head": {"inline": _HEAD_ADDED_PATH_YAML},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 404
    assert "9.9.9" in r.json()["detail"]


def test_classified_diff_invalid_inline_400(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"inline": "not: valid: [yaml"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 400
    assert "not valid" in r.json()["detail"].lower() or "yaml" in r.json()["detail"].lower()


_HEAD_REMOVED_PROPERTY_YAML = yaml.dump(
    {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.1.0"},
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                }
            }
        },
    }
)

_BASE_WITH_PROPERTY = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {},
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
            }
        }
    },
}


def test_classified_diff_accept_markdown_changelog(mock_auth):
    """CTG-2.1: Accept text/markdown returns CTG-1.3 changelog with rule ids."""
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_WITH_PROPERTY,
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"inline": _HEAD_REMOVED_PROPERTY_YAML},
            },
            headers={
                "Authorization": "Bearer x",
                "Accept": "text/markdown",
            },
        )
    assert r.status_code == 200, r.text
    assert "text/markdown" in r.headers.get("content-type", "")
    body = r.text
    assert body.startswith("# Changelog")
    assert "ctg.property_removed" in body


# ---------------------------------------------------------------------------------------------
# CTG-4.2 consumer-aware breaking analysis (#4480)
# ---------------------------------------------------------------------------------------------

_PETS_BY_ID_GET = "/paths/~1pets~1{id}/get"
_PETS_GET = "/paths/~1pets/get"


def _consumer_summary(slug: str, operation_pointer: str | None):
    """Build a ConsumerSummary the way the registry would return one."""
    from app.consumer_contract import (
        ConsumerContractOperation,
        ConsumerContractRecord,
        ConsumerContractSurface,
        ConsumerRecord,
        ConsumerSummary,
    )

    consumer = ConsumerRecord(
        id=f"consumer-{slug}",
        tenant_id="tenant-1",
        project_id="proj-1",
        slug=slug,
        name=slug,
    )
    if operation_pointer is None:
        return ConsumerSummary(consumer=consumer, contract=None)
    method = operation_pointer.rsplit("/", 1)[1]
    surface = ConsumerContractSurface(
        operations=[
            ConsumerContractOperation(
                method=method,
                path="/pets" if operation_pointer == _PETS_GET else "/pets/{id}",
                pointer=operation_pointer,
                fields=[],
            )
        ]
    )
    return ConsumerSummary(
        consumer=consumer,
        contract=ConsumerContractRecord(
            id=f"contract-{slug}",
            consumer_id=consumer.id,
            revision=1,
            source="manual",
            version_id="base-rev",
            version_label="1.0.0",
            surface=surface,
            operation_count=1,
        ),
    )


def _stored_vs_stored_body(*, consumers: bool):
    body = {
        "base": {"project": "pets", "version": "1.0.0"},
        "head": {"project": "pets", "version": "1.1.0"},
    }
    if consumers:
        body["consumers"] = True
    return body


def _classified_call(mock_db, summaries, *, body, accept="application/json"):
    """Run the endpoint with a mocked registry read and the real impact engine."""
    with (
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            side_effect=[_BASE_SPEC, _HEAD_REMOVED_PATH],
        ),
        patch(
            "app.consumer_impact_service.list_consumer_summaries",
            return_value=summaries,
        ) as mock_list,
    ):
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.side_effect = lambda pid, ver, tid: (
            _FAKE_BASE_VER if ver == "1.0.0" else _FAKE_HEAD_VER if ver == "1.1.0" else None
        )
        response = client.post(
            "/v1/diff/acme/classified",
            json=body,
            headers={"Authorization": "Bearer x", "Accept": accept},
        )
    return response, mock_list


def test_classified_diff_consumers_flag_returns_per_consumer_verdicts(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        r, mock_list = _classified_call(
            mock_db,
            [
                _consumer_summary("billing-service", _PETS_BY_ID_GET),
                _consumer_summary("mobile-app", _PETS_GET),
                _consumer_summary("ghost", None),
            ],
            body=_stored_vs_stored_body(consumers=True),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    impact = data["consumers"]
    assert impact["schemaVersion"] == "ctg.consumer-impact.v1"
    assert impact["breakingConsumers"] == ["billing-service"]
    assert impact["summary"] == (
        "breaks 1 of 2 consumers: billing-service "
        "(1 registered consumer has declared no surface)"
    )
    assert impact["counts"]["consumers_total"] == 3
    verdicts = {v["consumerSlug"]: v["verdict"] for v in impact["consumers"]}
    assert verdicts == {
        "billing-service": "breaking",
        "mobile-app": "unaffected",
        "ghost": "undeclared",
    }
    # The registry is read for the base project, which is what consumers registered against.
    assert mock_list.call_args.args == ("tenant-1", "proj-1")

    removed = next(c for c in data["changes"] if c["ruleId"] == "ctg.path_removed")
    assert removed["consumers"] == ["billing-service"]


def test_classified_diff_flags_changes_no_consumer_is_affected_by(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        r, _ = _classified_call(
            mock_db,
            [_consumer_summary("mobile-app", _PETS_GET)],
            body=_stored_vs_stored_body(consumers=True),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["consumers"]["counts"]["changes_unattributed"] >= 1
    # Globally classified as before; the empty list is the "affects nobody" flag.
    removed = next(c for c in data["changes"] if c["ruleId"] == "ctg.path_removed")
    assert removed["severity"] == "breaking"
    assert removed["consumers"] == []
    assert data["maxSeverity"] == "breaking"


def test_classified_diff_without_the_flag_never_reads_the_registry(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        r, mock_list = _classified_call(
            mock_db,
            [_consumer_summary("billing-service", _PETS_BY_ID_GET)],
            body=_stored_vs_stored_body(consumers=False),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["consumers"] is None
    assert data["changes"][0]["consumers"] is None
    mock_list.assert_not_called()


def test_classified_diff_consumers_flag_requires_consumer_contracts_view(mock_auth):
    def _permission(tenant_id, user_id, resource, action):
        return resource != "consumer_contracts"

    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.side_effect = _permission
        r, mock_list = _classified_call(
            mock_db,
            [_consumer_summary("billing-service", _PETS_BY_ID_GET)],
            body=_stored_vs_stored_body(consumers=True),
        )
    assert r.status_code == 403
    mock_list.assert_not_called()


def test_classified_diff_markdown_gains_a_consumer_impact_section(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        r, _ = _classified_call(
            mock_db,
            [_consumer_summary("billing-service", _PETS_BY_ID_GET)],
            body=_stored_vs_stored_body(consumers=True),
            accept="text/markdown",
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert "# Changelog" in r.text
    assert "## Consumer impact" in r.text
    assert "breaks 1 of 1 consumer: billing-service" in r.text
    assert "### `billing-service` — breaking" in r.text


def test_classified_diff_markdown_without_the_flag_is_unchanged(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        r, _ = _classified_call(
            mock_db,
            [],
            body=_stored_vs_stored_body(consumers=False),
            accept="text/markdown",
        )
    assert r.status_code == 200, r.text
    assert "Consumer impact" not in r.text
