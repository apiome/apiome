"""Route tests for the anonymous "Get SDK" surface — SDK-3.3 (#4493).

Exercises ``GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/sdk`` and its ``/download``
sibling with the public source loader and the settings gate patched (no live Postgres): the
per-project gate and its deliberately indistinguishable 404, the info payload the browse panel
draws from, the zip's headers and conditional caching, the public size cap, and the rate limit.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Server,
    Service,
)
from app.config import settings
from app.export_source import ExportSource, ExportSourceError
from app.go_client_generator import DEFAULT_GO_VERSION
from app.main import app
from app.sdk_generation_settings import ResolvedBranding, SdkGenerationSettingsOut
from app.sdk_kit import KIT_SCHEMA_VERSION

client = TestClient(app)

_BASE = "/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/sdk"

_LOADER = "app.sdk_kit_routes.load_public_export_source"
#: Both routes read the settings exactly once, so patching this one loader drives the gate, the
#: branding and the provenance fingerprint together — and exercises the real gate rule rather than
#: mocking the decision away.
_SETTINGS = "app.sdk_kit_routes.load_settings"

_NOT_FOUND = ExportSourceError(
    "Published version '1.0.0' was not found for 'acme'/'widgets'.", status_code=404
)


def _source(source_text: Optional[str] = '{"openapi": "3.1.0"}') -> ExportSource:
    """A loaded public source: a REST API with one HTTP and one non-HTTP operation."""
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Widgets API",
        version="1.0.0",
        identity=ApiIdentity(name="widgets"),
        servers=[Server(url="https://api.widgets.dev")],
        services=[
            Service(
                key="widgets",
                name="widgets",
                operations=[
                    Operation(
                        key="GET /widgets",
                        name="listWidgets",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="get",
                        http_path="/widgets",
                        extras={"operationId": "listWidgets"},
                    ),
                    Operation(
                        key="Query.widgets",
                        name="widgetsQuery",
                        kind=OperationKind.QUERY,
                    ),
                ],
            )
        ],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
        tenant_id="tenant-1",
        source_text=source_text,
        source_format="openapi-3.1",
    )


_FINGERPRINT = "sha256:" + "b" * 64


def _settings_out(
    *,
    public_sdk_enabled: bool = True,
    branding: Optional[ResolvedBranding] = None,
    degraded: bool = False,
    fingerprint: str = _FINGERPRINT,
) -> SdkGenerationSettingsOut:
    """The settings in force for a project, as the store would report them."""
    brand = branding or ResolvedBranding(package_names={})
    return SdkGenerationSettingsOut.model_validate(
        {
            "source": "tenant",
            "contentFingerprint": fingerprint,
            "settings": {
                "packageNamePatterns": {},
                "licenseHeader": brand.license_header,
                "userAgent": brand.user_agent,
                "publicSdkEnabled": public_sdk_enabled,
            },
            "resolved": {
                "packageNames": brand.package_names,
                "licenseHeader": brand.license_header,
                "userAgent": brand.user_agent,
            },
            "degraded": degraded,
        }
    )


@pytest.fixture(autouse=True)
def _settings_reads():
    """A project that has opted in, with no branding — the baseline every test starts from."""
    with patch(_SETTINGS, return_value=_settings_out()):
        yield


# ===========================================================================
# The gate
# ===========================================================================


def test_info_is_404_when_the_project_has_not_opted_in() -> None:
    """Default-off means default-invisible: nothing is exposed until someone opts in."""
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(public_sdk_enabled=False)
    ) as settings_read:
        resp = client.get(_BASE)

    assert resp.status_code == 404
    assert "No public SDK is available" in resp.json()["detail"]
    # Asked about the tenant and project the loader resolved, not about the URL slugs.
    assert settings_read.call_args.args[:2] == ("tenant-1", "artifact-1")


def test_download_is_404_when_the_project_has_not_opted_in() -> None:
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(public_sdk_enabled=False)
    ):
        resp = client.get(f"{_BASE}/download")
    assert resp.status_code == 404


def test_unreadable_settings_fail_closed() -> None:
    """A store fault must never widen public exposure, whatever the row last said."""
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(public_sdk_enabled=True, degraded=True)
    ):
        resp = client.get(f"{_BASE}/download")
    assert resp.status_code == 404


def test_a_revision_whose_tenant_cannot_be_resolved_is_404() -> None:
    """Without a tenant there are no settings to consult, so there is no opt-in to honour."""
    source = _source()
    with patch(_LOADER, return_value=source.model_copy(update={"tenant_id": None})), patch(
        _SETTINGS
    ) as settings_read:
        resp = client.get(_BASE)
    assert resp.status_code == 404
    settings_read.assert_not_called()


def test_a_closed_project_is_indistinguishable_from_an_unknown_one() -> None:
    """A distinct 403 would confirm that the project exists and merely declined."""
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(public_sdk_enabled=False)
    ):
        closed = client.get(_BASE)
    with patch(_LOADER, side_effect=_NOT_FOUND):
        unknown = client.get(_BASE)

    assert closed.status_code == unknown.status_code == 404
    # Everything but the per-request id, which differs on any two requests whatsoever.
    assert closed.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert closed.json()["detail"] == unknown.json()["detail"]


def test_a_revision_with_no_usable_source_keeps_the_loaders_own_status() -> None:
    """A 422 is about the artifact, not about visibility, so it is not folded into the 404."""
    with patch(_LOADER, side_effect=ExportSourceError("no source", status_code=422)):
        resp = client.get(_BASE)
    assert resp.status_code == 422


# ===========================================================================
# The info payload
# ===========================================================================


def test_info_describes_the_languages_and_the_download() -> None:
    with patch(_LOADER, return_value=_source()) as loader:
        resp = client.get(_BASE)

    assert resp.status_code == 200
    loader.assert_called_once_with("acme", "widgets", "1.0.0")
    body = resp.json()
    assert body["tenant_slug"] == "acme"
    assert body["project_slug"] == "widgets"
    assert body["version_slug"] == "1.0.0"
    assert body["version_record_id"] == "rev-uuid-1"
    assert body["api_title"] == "Widgets API"
    assert [lang["lang"] for lang in body["languages"]] == ["ts", "python", "curl"]
    assert [lang["install"] for lang in body["languages"]] == [None, "pip install httpx", None]
    assert body["download"] == {
        "filename": "widgets-1.0.0-sdk.zip",
        "media_type": "application/zip",
        "schema_version": KIT_SCHEMA_VERSION,
    }


def test_info_counts_only_the_operations_a_kit_can_render() -> None:
    with patch(_LOADER, return_value=_source()):
        body = client.get(_BASE).json()
    assert body["operation_count"] == 1
    assert body["total_operation_count"] == 2
    assert body["truncated"] is False


def test_info_reports_the_resolved_package_names_and_their_install_commands() -> None:
    branding = ResolvedBranding(
        package_names={"npm": "@acme/widgets-sdk", "pypi": "acme-widgets"},
        license_header="Copyright (c) 2026 Acme, Inc.",
    )
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(branding=branding)
    ):
        body = client.get(_BASE).json()

    assert body["packages"] == [
        {
            "ecosystem": "npm",
            "name": "@acme/widgets-sdk",
            "install": "npm install @acme/widgets-sdk",
        },
        {"ecosystem": "pypi", "name": "acme-widgets", "install": "pip install acme-widgets"},
    ]
    assert body["license_header"] == "Copyright (c) 2026 Acme, Inc."


def test_info_names_the_go_client_the_download_carries() -> None:
    """SDK-2.4 (#4488): the Go client is a module inside the archive, not a snippet tab."""
    with patch(_LOADER, return_value=_source()):
        body = client.get(_BASE).json()

    assert body["go_client"] == {
        "directory": "go",
        "module_path": "example.com/acme/widgets-go",
        "package_name": "widgets",
        "go_version": DEFAULT_GO_VERSION,
        "install": "go get example.com/acme/widgets-go",
        # The Go client covers exactly the operations the kit can render.
        "method_count": 1,
    }


def test_info_names_the_server_stubs_the_download_carries() -> None:
    """SDK-2.5 (#4490): the archive also answers the opposite question — how to *implement* this."""
    with patch(_LOADER, return_value=_source()):
        body = client.get(_BASE).json()

    assert body["server_stubs"] == {
        "directory": "server",
        "targets": ["fastapi", "express"],
        "python_package": "widgets_server",
        "npm_package": "widgets-server",
        "route_count": 1,
    }


def test_info_never_offers_a_server_stub_under_the_client_packages_name() -> None:
    """A configured npm name is the *client* library; a server skeleton may not share its address."""
    branding = ResolvedBranding(package_names={"npm": "@acme/widgets-sdk"})
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(branding=branding)
    ):
        body = client.get(_BASE).json()

    assert body["server_stubs"]["npm_package"] == "@acme/widgets-sdk-server"


def test_info_prefers_a_configured_go_module_path() -> None:
    """A module path is what a consumer types into `go get`; a configured one is used verbatim."""
    branding = ResolvedBranding(package_names={"gomod": "github.com/acme/widgets-go"})
    with patch(_LOADER, return_value=_source()), patch(
        _SETTINGS, return_value=_settings_out(branding=branding)
    ):
        body = client.get(_BASE).json()

    assert body["go_client"]["module_path"] == "github.com/acme/widgets-go"
    assert body["go_client"]["install"] == "go get github.com/acme/widgets-go"
    assert body["packages"] == [
        {
            "ecosystem": "gomod",
            "name": "github.com/acme/widgets-go",
            "install": "go get github.com/acme/widgets-go",
        }
    ]


def test_info_reports_the_settings_fingerprint_as_provenance() -> None:
    with patch(_LOADER, return_value=_source()):
        body = client.get(_BASE).json()
    assert body["settings_fingerprint"] == _FINGERPRINT


def test_info_does_not_build_the_archive() -> None:
    """Rendering three snippets per operation to report three numbers would be the download's job."""
    with patch(_LOADER, return_value=_source()), patch(
        "app.sdk_kit_routes.build_client_kit"
    ) as build:
        assert client.get(_BASE).status_code == 200
    build.assert_not_called()


# ===========================================================================
# The download
# ===========================================================================


def test_the_download_is_a_zip_with_a_named_attachment() -> None:
    with patch(_LOADER, return_value=_source()):
        resp = client.get(f"{_BASE}/download")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"] == 'attachment; filename="widgets-1.0.0-sdk.zip"'
    assert resp.headers["content-length"] == str(len(resp.content))
    assert resp.headers["cache-control"] == "public, max-age=300"


def test_the_download_carries_provenance_headers() -> None:
    """A consumer can identify exactly what they downloaded without unzipping it."""
    with patch(_LOADER, return_value=_source()):
        resp = client.get(f"{_BASE}/download")

    assert resp.headers["x-apiome-version-record-id"] == "rev-uuid-1"
    assert resp.headers["x-apiome-kit-schema"] == KIT_SCHEMA_VERSION
    assert resp.headers["digest"].startswith("sha-256=")
    assert len(resp.headers["x-content-sha256"]) == 64


def test_the_archive_holds_the_kit_and_its_manifest() -> None:
    with patch(_LOADER, return_value=_source()):
        resp = client.get(f"{_BASE}/download")

    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = sorted(archive.namelist())
    assert "README.md" in names
    assert "manifest.json" in names
    assert "snippets/ts/listWidgets.ts" in names
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schema_version"] == KIT_SCHEMA_VERSION
    assert manifest["provenance"]["version_record_id"] == "rev-uuid-1"
    assert manifest["provenance"]["settings_fingerprint"] == _FINGERPRINT
    # The running API version, not a hard-coded string.
    assert manifest["provenance"]["apiome_version"] == app.version


def test_the_download_is_conditional_on_its_etag() -> None:
    with patch(_LOADER, return_value=_source()):
        first = client.get(f"{_BASE}/download")
        assert first.status_code == 200
        etag = first.headers["etag"]
        second = client.get(f"{_BASE}/download", headers={"If-None-Match": etag})

    assert second.status_code == 304
    assert second.content == b""
    # The validators still describe the resource a 304 stands for.
    assert second.headers["etag"] == etag
    assert second.headers["x-apiome-version-record-id"] == "rev-uuid-1"


def test_two_downloads_of_an_unchanged_revision_share_an_etag() -> None:
    with patch(_LOADER, return_value=_source()):
        first = client.get(f"{_BASE}/download")
        second = client.get(f"{_BASE}/download")
    assert first.headers["etag"] == second.headers["etag"]
    assert first.content == second.content


def test_changed_branding_changes_the_etag() -> None:
    """The ETag digests the bytes, so a tenant's settings change invalidates caches for free."""
    with patch(_LOADER, return_value=_source()):
        plain = client.get(f"{_BASE}/download").headers["etag"]
        with patch(
            _SETTINGS,
            return_value=_settings_out(
                branding=ResolvedBranding(package_names={}, user_agent="acme-sdk/1.0.0")
            ),
        ):
            branded = client.get(f"{_BASE}/download").headers["etag"]
    assert plain != branded


def test_a_kit_over_the_public_cap_is_refused() -> None:
    with patch(_LOADER, return_value=_source()), patch.object(
        settings, "public_browse_export_document_max_bytes", 10
    ):
        resp = client.get(f"{_BASE}/download")
    assert resp.status_code == 413
    assert "public download limit" in resp.json()["detail"]


# ===========================================================================
# Rate limiting
# ===========================================================================


def test_both_routes_share_the_public_export_rate_limit() -> None:
    """The conftest disables rate limiting suite-wide, so this test turns it back on."""
    with patch.object(settings, "rate_limit_enabled", True), patch.object(
        settings, "public_browse_export_rate_limit_per_minute", 1
    ), patch(_LOADER, return_value=_source()):
        first = client.get(_BASE)
        second = client.get(_BASE)

    assert first.status_code == 200
    assert second.status_code == 429
