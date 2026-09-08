"""Tenant branding applied to snippets — SDK-3.4 (#4494).

SDK-3.4's visible half: the settings a tenant stores turn into an attribution ``User-Agent`` on the
example request and a licence comment above the code, on both the authenticated and the anonymous
snippet surfaces.

The load-bearing property these tests exist for is the *negative* one — an unbranded render is
byte-identical to what the renderer produced before SDK-3.4, which is what keeps the bulk
request-file emitter (FMT-2.4), which shares :func:`app.snippet_render.synthesize_request` and
:func:`app.snippet_render.render_curl`, unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    TypeRef,
)
from app.main import app
from app.sdk_generation_settings import ResolvedBranding
from app.snippet_render import license_comment_block, render_snippet, synthesize_request

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_VERSION = "44444444-4444-4444-8444-444444444444"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _TENANT, "auth_method": "jwt"}

_LICENSE = "Copyright (c) 2026 Acme, Inc.\nSPDX-License-Identifier: Apache-2.0"
_BRANDING = ResolvedBranding(
    package_names={"npm": "@acme/petstore-sdk"},
    license_header=_LICENSE,
    user_agent="acme-sdk/1.0.0",
)


def _list_pets(extra_parameters: Optional[List[Parameter]] = None) -> Operation:
    """``GET /pets`` with a required secret header, plus anything a test adds."""
    return Operation(
        key="GET /pets",
        name="listPets",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="get",
        http_path="/pets",
        extras={"operationId": "listPets"},
        parameters=[
            Parameter(
                key="GET /pets#header.X-API-Key",
                name="X-API-Key",
                location=ParameterLocation.HEADER,
                type=TypeRef(name="string"),
                required=True,
            ),
            *(extra_parameters or []),
        ],
    )


def _api(operations: Optional[List[Operation]] = None) -> CanonicalApi:
    """A one-operation canonical model."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pet Store"),
        servers=[Server(url="https://api.pets.dev/v1")],
        services=[
            Service(
                key="pets",
                name="pets",
                operations=operations if operations is not None else [_list_pets()],
            )
        ],
        types=[],
    )


# ===========================================================================
# The renderer
# ===========================================================================


def test_an_unbranded_render_is_unchanged() -> None:
    """The regression that would otherwise reach the request-file emitter."""
    api = _api()
    op = api.operations()[0]
    for lang in ("curl", "ts", "python"):
        assert render_snippet(api, op, lang).code == render_snippet(
            api, op, lang, user_agent=None, license_header=None
        ).code
    request, _ = synthesize_request(api, op)
    assert "User-Agent" not in request.headers


@pytest.mark.parametrize("lang", ["curl", "ts", "python"])
def test_the_user_agent_reaches_every_language(lang: str) -> None:
    api = _api()
    render = render_snippet(api, api.operations()[0], lang, user_agent="acme-sdk/1.0.0")
    assert render.request.headers["User-Agent"] == "acme-sdk/1.0.0"
    assert "acme-sdk/1.0.0" in render.code


def test_a_declared_user_agent_parameter_wins_over_the_tenant_default() -> None:
    """The spec is more authoritative about its own API than a workspace default is."""
    api = _api(
        [
            _list_pets(
                [
                    Parameter(
                        key="GET /pets#header.User-Agent",
                        name="User-Agent",
                        location=ParameterLocation.HEADER,
                        type=TypeRef(name="string"),
                        required=True,
                        default="spec-declared/9.9",
                    )
                ]
            )
        ]
    )
    op = api.operations()[0]
    request, _ = synthesize_request(api, op, "acme-sdk/1.0.0")
    assert request.headers["User-Agent"] == "spec-declared/9.9"
    assert list(request.headers).count("User-Agent") == 1


@pytest.mark.parametrize(
    ("lang", "prefix"), [("ts", "//"), ("python", "#"), ("curl", "#")]
)
def test_the_license_header_is_commented_per_language(lang: str, prefix: str) -> None:
    api = _api()
    render = render_snippet(api, api.operations()[0], lang, license_header=_LICENSE)
    lines = render.code.split("\n")
    assert lines[0] == f"{prefix} Copyright (c) 2026 Acme, Inc."
    assert lines[1] == f"{prefix} SPDX-License-Identifier: Apache-2.0"


def test_the_license_header_cannot_escape_its_comment() -> None:
    """Line comments, not block comments: ``*/`` in a licence must stay inert."""
    block = license_comment_block("Acme */ evil()", "ts")
    assert block == "// Acme */ evil()"
    assert "\n" not in block


def test_a_blank_line_in_a_license_does_not_leave_trailing_whitespace() -> None:
    assert license_comment_block("Acme\n\nInc.", "python") == "# Acme\n#\n# Inc."


def test_an_empty_license_adds_nothing() -> None:
    assert license_comment_block("   ", "ts") is None
    api = _api()
    assert render_snippet(
        api, api.operations()[0], "ts", license_header="  "
    ).code == render_snippet(api, api.operations()[0], "ts").code


def test_branded_rendering_stays_deterministic() -> None:
    """The ETag contract depends on this."""
    api = _api()
    op = api.operations()[0]
    first = render_snippet(
        api, op, "python", user_agent="acme/1.0", license_header=_LICENSE
    )
    second = render_snippet(
        api, op, "python", user_agent="acme/1.0", license_header=_LICENSE
    )
    assert first.code == second.code


# ===========================================================================
# The routes
# ===========================================================================


class _FakeDb:
    """The minimum the authenticated snippet route reads."""

    def get_project_by_id(self, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return {"id": _PROJECT, "slug": "petstore"} if project_id == _PROJECT else None

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return {
            "id": _VERSION,
            "project_id": _PROJECT,
            "published": True,
            "version_id": "1.0.0",
        }


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _authed_url(lang: str = "curl") -> str:
    return (
        f"/v1/versions/acme/{_PROJECT}/{_VERSION}/snippets/listPets?lang={lang}"
    )


def test_the_authenticated_route_applies_and_reports_branding() -> None:
    with patch("app.snippet_routes.db", _FakeDb()), patch(
        "app.snippet_routes.load_canonical_api", return_value=_api()
    ), patch(
        "app.snippet_routes.load_branding", return_value=_BRANDING
    ) as branding:
        resp = client.get(_authed_url())
    assert resp.status_code == 200
    body = resp.json()
    assert body["request"]["headers"]["User-Agent"] == "acme-sdk/1.0.0"
    assert body["code"].startswith("# Copyright (c) 2026 Acme, Inc.")
    assert body["branding"]["user_agent"] == "acme-sdk/1.0.0"
    assert body["branding"]["package_names"] == {"npm": "@acme/petstore-sdk"}
    # The version label reaches the pattern context, so `{version}` can resolve.
    context = branding.call_args.args[2]
    assert (context.tenant, context.project, context.version) == (
        "acme",
        "petstore",
        "1.0.0",
    )


def test_changing_the_branding_changes_the_etag() -> None:
    """No cache-key work is needed: the ETag digests the whole response."""
    etags: List[str] = []
    for branding in (ResolvedBranding(package_names={}), _BRANDING):
        with patch("app.snippet_routes.db", _FakeDb()), patch(
            "app.snippet_routes.load_canonical_api", return_value=_api()
        ), patch("app.snippet_routes.load_branding", return_value=branding):
            etags.append(client.get(_authed_url()).headers["etag"])
    assert etags[0] != etags[1]


def test_an_unbranded_response_reports_empty_branding() -> None:
    with patch("app.snippet_routes.db", _FakeDb()), patch(
        "app.snippet_routes.load_canonical_api", return_value=_api()
    ), patch(
        "app.snippet_routes.load_branding",
        return_value=ResolvedBranding(package_names={}),
    ):
        body = client.get(_authed_url()).json()
    assert body["branding"] == {
        "user_agent": None,
        "license_header": None,
        "package_names": {},
    }
    assert "User-Agent" not in body["request"]["headers"]


def test_the_public_route_brands_from_the_tenant_the_loader_resolved() -> None:
    """An anonymous caller supplies slugs; the loader is where a tenant id comes from."""
    from app.export_source import ExportSource

    source = ExportSource(
        api=_api(),
        artifact_id=_PROJECT,
        version_record_id=_VERSION,
        version_label="1.0.0",
        tenant_id=_TENANT,
    )
    with patch(
        "app.snippet_routes.load_public_export_source", return_value=source
    ), patch("app.snippet_routes.load_branding", return_value=_BRANDING) as branding:
        resp = client.get(
            "/v1/browse/tenants/acme/projects/petstore/versions/1.0.0/snippets/listPets?lang=ts"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"].startswith("// Copyright (c) 2026 Acme, Inc.")
    assert body["branding"]["user_agent"] == "acme-sdk/1.0.0"
    assert branding.call_args.args[0] == _TENANT
