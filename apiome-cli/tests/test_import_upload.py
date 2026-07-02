"""Unit tests for OpenAPI import upload helpers."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest
import typer

from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.import_.upload import (
    X_APIOME_PROJECT_NAME_FIELD,
    X_APIOME_PROJECT_SLUG,
    X_APIOME_VERSION_SLUG,
    apply_info_overrides,
    build_arazzo_import_body,
    build_json_schema_import_body,
    build_openapi_import_body,
    import_result_has_errors,
    resolve_import_result,
)

_TENANT_SLUG = "acme-corp"

_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Original", "version": "1.0.0"},
    "paths": {},
}


def test_apply_info_overrides_returns_same_object_when_empty() -> None:
    """No overrides avoids an unnecessary deep copy."""
    assert apply_info_overrides(_SPEC) is _SPEC


def test_apply_info_overrides_sets_title_and_version() -> None:
    """CLI overrides are written into the spec info block."""
    updated = apply_info_overrides(
        _SPEC,
        project_name="Renamed",
        version="2.0.0",
    )
    assert updated is not _SPEC
    assert updated["info"]["title"] == "Renamed"
    assert updated["info"]["version"] == "2.0.0"


def test_apply_info_overrides_sets_slug_extensions() -> None:
    """Slug overrides are embedded as x-apiome extensions on info."""
    updated = apply_info_overrides(
        _SPEC,
        project_slug="custom-project",
        version_slug="2.0.0-rc1",
    )
    assert updated["info"][X_APIOME_PROJECT_SLUG] == "custom-project"
    assert updated["info"][X_APIOME_VERSION_SLUG] == "2.0.0-rc1"


def test_apply_info_overrides_sets_project_name_field_extension() -> None:
    updated = apply_info_overrides(_SPEC, project_name_field="info.summary")
    assert updated["info"][X_APIOME_PROJECT_NAME_FIELD] == "info.summary"


def test_apply_info_overrides_rejects_invalid_project_slug() -> None:
    """Invalid project slug overrides raise ValueError before upload."""
    with pytest.raises(ValueError, match="Project slug"):
        apply_info_overrides(_SPEC, project_slug="Not Valid!")


def test_build_arazzo_import_body_includes_optional_fields() -> None:
    """Request body carries tenant, project, version, and dry-run flags."""
    tenant = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    project = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    version = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    spec = {"arazzo": "1.0.0", "info": {"title": "Flow", "version": "1.0.0"}}
    body = build_arazzo_import_body(
        spec,
        tenant_id=tenant,
        project_id=project,
        version_id=version,
        visibility="public",
        dry_run=True,
        source_url="https://example.com/flow.json",
    )
    assert body["spec"] is spec
    assert body["tenant_id"] == str(tenant)
    assert body["project_id"] == str(project)
    assert body["version_id"] == str(version)
    assert body["visibility"] == "public"
    assert body["dry_run"] is True
    assert body["source_url"] == "https://example.com/flow.json"


def test_build_openapi_import_body_includes_optional_fields() -> None:
    """Request body carries tenant, project, and dry-run flags."""
    tenant = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    project = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    body = build_openapi_import_body(
        _SPEC,
        tenant_id=tenant,
        project_id=project,
        visibility="public",
        dry_run=True,
    )
    assert body["spec"] is _SPEC
    assert body["tenant_id"] == str(tenant)
    assert body["project_id"] == str(project)
    assert body["visibility"] == "public"
    assert body["dry_run"] is True


def test_build_json_schema_import_body_sets_import_type() -> None:
    body = build_json_schema_import_body({"type": "string", "title": "Email"})
    assert body["import_type"] == "json-schema"


def test_build_json_schema_import_body_includes_optional_fields() -> None:
    """Request body carries tenant, target, links, and dry-run flags."""
    document = {"type": "string", "title": "Email"}
    tenant = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    project = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    version = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    body = build_json_schema_import_body(
        document,
        tenant_id=tenant,
        as_target="property",
        name="Email",
        description="Contact email",
        project_id=project,
        version_id=version,
        link_project_property=True,
        dry_run=True,
    )
    assert body["body"] is document
    assert body["tenant_id"] == str(tenant)
    assert body["as"] == "property"
    assert body["name"] == "Email"
    assert body["description"] == "Contact email"
    assert body["project_id"] == str(project)
    assert body["version_id"] == str(version)
    assert body["link_project_property"] is True
    assert body["dry_run"] is True


def test_resolve_import_result_rejects_sync_200() -> None:
    """Only HTTP 202 accept responses are supported on /v1 imports."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"project_id": "p", "errors": []}
    with pytest.raises(typer.Exit) as exc_info:
        resolve_import_result(
            response,
            MagicMock(),
            _TENANT_SLUG,
            timeout=30.0,
            no_progress=True,
        )
    assert exc_info.value.exit_code == EXIT_ERROR


def test_resolve_import_result_async_no_wait_returns_accept_body() -> None:
    """202 with wait=False returns the accept payload without polling."""
    post_response = MagicMock()
    post_response.status_code = 202
    accepted = {"job_id": "job-1", "status": "pending"}
    post_response.json.return_value = accepted

    result = resolve_import_result(
        post_response,
        MagicMock(),
        _TENANT_SLUG,
        wait=False,
        timeout=5.0,
        no_progress=True,
    )
    assert result.kind == "accepted"
    assert result.payload == accepted


def test_resolve_import_result_async_extracts_result(
    httpx_mock: object,
) -> None:
    """202 responses poll until ``result`` is available."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_SLUG}/imports/job-1",
        json={
            "state": "completed",
            "job_id": "job-1",
            "result": {"project_id": "p", "errors": []},
        },
    )
    from apiome_cli.client.http import RestClient
    from apiome_cli.config import CliSettings

    post_response = MagicMock()
    post_response.status_code = 202
    post_response.json.return_value = {"job_id": "job-1", "status": "pending"}

    result = resolve_import_result(
        post_response,
        RestClient(CliSettings(), timeout=30.0),
        _TENANT_SLUG,
        timeout=5.0,
        no_progress=True,
    )
    assert result.kind == "completed"
    assert result.payload["project_id"] == "p"


def test_import_result_has_errors() -> None:
    """Error detection respects empty and populated arrays."""
    assert import_result_has_errors({"errors": []}) is False
    assert import_result_has_errors({"errors": [{"message": "x"}]}) is True
    assert import_result_has_errors({}) is False


def test_resolve_import_result_invalid_200_exits() -> None:
    """Non-object JSON from a sync import exits with an error."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = []
    with pytest.raises(typer.Exit) as exc_info:
        resolve_import_result(
            response,
            MagicMock(),
            _TENANT_SLUG,
            timeout=30.0,
            no_progress=True,
        )
    assert exc_info.value.exit_code == EXIT_ERROR
