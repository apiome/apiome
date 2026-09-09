"""Route tests for the anonymous SDK-2.3 snippet endpoint (#4487).

Exercises ``GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/snippets/{operation_id}``
with the public source loader patched (no live Postgres): anonymous access, the slug
coordinates echo, uniform-404 passthrough from the loader, lang/operation validation, the
non-HTTP-operation 422, and ETag / 304 conditional caching.

Since SDK-3.3 (#4493) the route is also gated by the project's ``publicSdkEnabled`` setting. The
autouse fixture below opens that gate so the SDK-2.3 behaviours above are exercised on their own;
the gate itself is pinned by ``test_public_snippet_requires_public_sdk_access``.
"""

from __future__ import annotations

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
from app.export_source import ExportSource, ExportSourceError
from app.main import app

client = TestClient(app)

_BASE = "/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/snippets"

_LOADER = "app.snippet_routes.load_public_export_source"
_GATE = "app.snippet_routes.load_public_sdk_enabled"


@pytest.fixture(autouse=True)
def _public_sdk_enabled():
    """Open the SDK-3.3 public-SDK gate for every test that is not about the gate."""
    with patch(_GATE, return_value=True):
        yield


def _source() -> ExportSource:
    """A loaded public source: a REST API with one HTTP and one non-HTTP operation."""
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
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
    )


_NOT_FOUND = ExportSourceError(
    "Published version '1.0.0' was not found for 'acme'/'widgets'.", status_code=404
)


def test_public_snippet_no_auth_required() -> None:
    """The snippet is served to a fully anonymous caller — no credentials of any kind."""
    with patch(_LOADER, return_value=_source()) as loader:
        resp = client.get(f"{_BASE}/listWidgets", params={"lang": "curl"})

    assert resp.status_code == 200
    loader.assert_called_once_with("acme", "widgets", "1.0.0")
    assert resp.headers["cache-control"] == "public, max-age=300"
    body = resp.json()
    assert body["lang"] == "curl"
    assert body["code"] == "curl 'https://api.widgets.dev/widgets'"
    # Coordinates echo, mirroring the public export responses.
    assert body["tenant_slug"] == "acme"
    assert body["project_slug"] == "widgets"
    assert body["version_slug"] == "1.0.0"
    assert body["version_record_id"] == "rev-uuid-1"
    assert body["version_label"] == "1.0.0"


def test_public_snippet_all_langs() -> None:
    with patch(_LOADER, return_value=_source()):
        for lang, needle in (
            ("ts", "await fetch("),
            ("python", "import httpx"),
            ("curl", "curl "),
        ):
            resp = client.get(f"{_BASE}/listWidgets", params={"lang": lang})
            assert resp.status_code == 200
            assert needle in resp.json()["code"]


def test_public_snippet_loader_404_passthrough() -> None:
    """Private, draft, and unknown versions are one uniform 404 from the loader."""
    with patch(_LOADER, side_effect=_NOT_FOUND):
        resp = client.get(f"{_BASE}/listWidgets", params={"lang": "curl"})
    assert resp.status_code == 404


def test_public_snippet_loader_422_passthrough() -> None:
    with patch(_LOADER, side_effect=ExportSourceError("no source", status_code=422)):
        resp = client.get(f"{_BASE}/listWidgets", params={"lang": "curl"})
    assert resp.status_code == 422


def test_public_snippet_unknown_lang_400_before_load() -> None:
    """Lang validation fails fast — the loader is never consulted."""
    with patch(_LOADER, return_value=_source()) as loader:
        resp = client.get(f"{_BASE}/listWidgets", params={"lang": "go"})
    assert resp.status_code == 400
    loader.assert_not_called()


def test_public_snippet_unknown_operation_404() -> None:
    with patch(_LOADER, return_value=_source()):
        resp = client.get(f"{_BASE}/nope", params={"lang": "curl"})
    assert resp.status_code == 404
    assert "Operation not found" in resp.json()["detail"]


def test_public_snippet_non_http_operation_422() -> None:
    with patch(_LOADER, return_value=_source()):
        resp = client.get(f"{_BASE}/widgetsQuery", params={"lang": "curl"})
    assert resp.status_code == 422


def test_public_snippet_requires_public_sdk_access() -> None:
    """A project that has not opted into public SDK access serves no snippets (SDK-3.3).

    The refusal is a 404 rather than a 403: it has to be indistinguishable from the loader's own
    "no such published public version", or it would confirm that the project exists and merely
    declined.
    """
    with patch(_LOADER, return_value=_source()), patch(_GATE, return_value=False) as gate:
        resp = client.get(f"{_BASE}/listWidgets", params={"lang": "curl"})

    assert resp.status_code == 404
    assert "No public snippets are available" in resp.json()["detail"]
    # Asked about the tenant and project the loader resolved, not about the URL slugs.
    gate.assert_called_once_with("tenant-1", "artifact-1")


def test_public_snippet_etag_304() -> None:
    with patch(_LOADER, return_value=_source()):
        first = client.get(f"{_BASE}/listWidgets", params={"lang": "python"})
        assert first.status_code == 200
        etag = first.headers["etag"]
        second = client.get(
            f"{_BASE}/listWidgets",
            params={"lang": "python"},
            headers={"If-None-Match": etag},
        )
    assert second.status_code == 304
    assert second.content == b""
