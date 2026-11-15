"""``GET …/projects/{project}/sdk-compatibility`` — SGD-2.1 (#4735), route level."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import sdk_compat_routes
from app.auth import validate_authentication
from app.export_source import ExportSource, ExportSourceError
from app.main import app
from test_sdk_compat_manifest import _fixture_api

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
REVISION = "33333333-3333-4333-8333-333333333333"
BASELINE = "44444444-4444-4444-8444-444444444444"
URL = "/v1/tenants/acme/projects/widgets/sdk-compatibility"


class FakeDb:
    def __init__(self) -> None:
        self.changelog: Optional[Dict[str, Any]] = {
            "status": "ready", "max_severity": "breaking", "baseline_revision_id": BASELINE
        }

    def get_project_by_slug(self, slug: str, tenant_id: str):
        return {"id": PROJECT, "slug": "widgets"} if slug == "widgets" and tenant_id == TENANT else None

    def get_project_by_id(self, project_id: str, tenant_id: str):
        return {"id": PROJECT, "slug": "widgets"} if project_id == PROJECT else None

    def get_version_changelog(self, revision_id: str, tenant_id: str, project_id: str):
        return self.changelog

    def get_version_by_id(self, revision_id: str, tenant_id: str):
        return {"version_id": "0.9.0"} if revision_id == BASELINE else None


@pytest.fixture
def fake(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(sdk_compat_routes, "db", db)
    monkeypatch.setattr(sdk_compat_routes, "enforce_permission", lambda *a, **k: "u-1")
    loaded: Dict[str, Any] = {}

    def load(tenant_id: str, artifact_id: str, version: Optional[str] = None) -> ExportSource:
        loaded["version"] = version
        if version == "9.9.9":
            raise ExportSourceError("no such version", status_code=404)
        if version == "empty":
            raise ExportSourceError("no source", status_code=422)
        return ExportSource(
            api=_fixture_api(),
            artifact_id=PROJECT,
            version_record_id=REVISION,
            version_label="1.0.0",
            tenant_id=TENANT,
            source_text='{"openapi": "3.1.0"}',
            source_format="openapi-3.1",
        )

    monkeypatch.setattr(sdk_compat_routes, "load_export_source", load)
    monkeypatch.setattr(
        sdk_compat_routes,
        "load_settings",
        lambda *a, **k: SimpleNamespace(
            resolved=SimpleNamespace(package_names={}, license_header=None, user_agent=None),
            content_fingerprint="sha256:" + "a" * 64,
        ),
    )
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": TENANT, "user_id": "u-1", "auth_method": "jwt"}
    yield SimpleNamespace(db=db, loaded=loaded)
    app.dependency_overrides.pop(validate_authentication, None)


def test_the_manifest_is_served_for_the_latest_revision(fake) -> None:
    response = client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "apiome.sdk.compat-manifest/v1"
    assert body["source"]["version_record_id"] == REVISION
    assert fake.loaded["version"] is None
    assert body["semver"] == {
        "classification": "breaking", "baseline_version": "0.9.0", "required_bump": "major",
        "declared_bump": "major", "consistent": True,
    }
    assert response.headers["ETag"].startswith('"')


def test_a_named_version_is_passed_through(fake) -> None:
    assert client.get(URL, params={"version": "1.0.0"}).status_code == 200
    assert fake.loaded["version"] == "1.0.0"


def test_an_unchanged_manifest_is_304(fake) -> None:
    etag = client.get(URL).headers["ETag"]
    response = client.get(URL, headers={"If-None-Match": etag})
    assert response.status_code == 304 and response.headers["ETag"] == etag


@pytest.mark.parametrize(
    ("url", "params", "status", "code"),
    [
        ("/v1/tenants/acme/projects/nope/sdk-compatibility", {}, 404, "sdk-compat-project-not-found"),
        (URL, {"version": "9.9.9"}, 404, "sdk-compat-version-not-found"),
        (URL, {"version": "empty"}, 422, "sdk-compat-no-source"),
    ],
)
def test_refusals(fake, url, params, status, code) -> None:
    response = client.get(url, params=params)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("changelog", [None, {"status": "initial", "max_severity": None}, {"status": "failed"}])
def test_no_ready_changelog_is_unknown(fake, changelog) -> None:
    fake.db.changelog = changelog
    assert client.get(URL).json()["semver"]["classification"] == "unknown"


def test_a_changelog_read_failure_degrades_to_unknown(fake, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(fake.db, "get_version_changelog", boom)
    assert client.get(URL).json()["semver"]["classification"] == "unknown"


def test_it_needs_projects_view(fake, monkeypatch) -> None:
    def deny(*_a, **_k):
        raise HTTPException(status_code=403, detail="no")

    monkeypatch.setattr(sdk_compat_routes, "enforce_permission", deny)
    assert client.get(URL).status_code == 403
