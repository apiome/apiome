"""Tests for the MCP Registry API over the MCP server catalog (AAU-5.3, #5724).

Three layers:

* **Builder unit tests** exercise the pure :mod:`app.mcp_registry` layer: naming, credential-free
  remote URLs, version choice, text clipping, cursors, ETags and the trust-posture summary.
* **Conformance tests** validate built pages and entries against the vendored, pinned registry
  schema (``data/mcp_registry_v0_1_schema.json``).
* **CDG-4.1 (#5973)** — ``packages[]`` / ``repository`` from linked sources (never invented), the
  owner team, the lint gate verdict, ``sources: "none"``, the ``schema`` route and the
  ``/registry/mcp/{t}/v0.1`` mount, which serves exactly what the ``/v1/tenants`` mount does.
* **Route tests** drive the three ``/v1/tenants/{t}/mcp-registry/v0.1`` routes against an in-memory
  catalog that implements the same keyset contract as
  :meth:`app.database.Database.list_mcp_registry_endpoints`: a registry-client walk that follows
  ``nextCursor`` (and survives inserts mid-walk), anonymous vs. credentialed visibility, bad
  credentials, ``updated_since`` / ``search`` / ``version`` filters, ``404``s and ``304``s.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import mcp_registry
from app.database import db as real_db
from app.main import app
from app.mcp_registry import (
    CATALOG_META_KEY,
    OFFICIAL_META_KEY,
    InvalidCursorError,
    body_etag,
    build_packages,
    build_repository,
    build_server_response,
    decode_cursor,
    definition_schema,
    encode_cursor,
    endpoint_slug_from_name,
    entry_version,
    lint_gate_summary,
    owner_team,
    remote_url,
    server_list,
    server_name,
    trust_posture_summary,
)

client = TestClient(app)

_BASE = "/v1/tenants/acme/mcp-registry/v0.1/servers"
_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_POSTURE = {"score": 92, "grade": "A", "gatePassed": True}
_TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _row(slug: str, **overrides: Any) -> Dict[str, Any]:
    """Return a registry row shaped like ``list_mcp_registry_endpoints`` output."""
    row: Dict[str, Any] = {
        "id": f"00000000-0000-0000-0000-{abs(hash(slug)) % 10**12:012d}",
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "description": f"The {slug} server.",
        "transport": "streamable_http",
        "endpoint_url": f"https://mcp.example.com/{slug}",
        "visibility": "public",
        "published": True,
        "quarantined_at": None,
        "created_at": _T0,
        "updated_at": _T0,
        "current_version_id": "22222222-2222-2222-2222-222222222222",
        "tenant_slug": "acme",
        "version_tag": "2026-10-01T12:00Z",
        "server_version": "1.2.0",
        "server_title": None,
        "surface_fingerprint": f"fp-{slug}",
        "version_discovered_at": _T0,
        "entry_updated_at": _T0,
        "score": 88,
        "grade": "B",
    }
    row.update(overrides)
    return row


def _validate(definition: str, document: Any) -> None:
    """Validate ``document`` against one vendored registry definition (formats asserted)."""
    jsonschema.Draft7Validator(
        definition_schema(definition), format_checker=jsonschema.FormatChecker()
    ).validate(document)


# --------------------------------------------------------------------------- builder


def test_server_name_is_tenant_namespaced_reverse_dns():
    assert server_name("acme", "weather") == "apiome.acme/weather"
    assert server_name("ac me", "wea ther!") == "apiome.ac-me/wea-ther-"


def test_endpoint_slug_from_name_only_accepts_this_tenants_namespace():
    assert endpoint_slug_from_name("apiome.acme/weather", "acme") == "weather"
    assert endpoint_slug_from_name("apiome.other/weather", "acme") is None
    assert endpoint_slug_from_name("apiome.acme", "acme") is None
    assert endpoint_slug_from_name("apiome.acme/", "acme") is None


@pytest.mark.parametrize(
    "stored, expected",
    [
        ("https://user:secret@mcp.example.com/mcp?token=abc#frag", "https://mcp.example.com/mcp"),
        ("http://mcp.example.com:8080/sse", "http://mcp.example.com:8080/sse"),
        ("https://[::1]:9000/mcp", "https://[::1]:9000/mcp"),
        ("ftp://mcp.example.com/x", None),
        ("stdio://local", None),
        ("not a url", None),
        ("", None),
        (None, None),
    ],
)
def test_remote_url_never_carries_credentials(stored, expected):
    assert remote_url(stored) == expected


def test_entry_version_prefers_server_info_then_snapshot_label():
    assert entry_version(_row("a")) == "1.2.0"
    assert entry_version(_row("a", server_version="  ")) == "2026-10-01T12:00Z"


def test_build_server_response_shape_and_meta():
    entry = build_server_response(_row("weather"), trust_posture=_POSTURE)
    server = entry["server"]
    assert server["name"] == "apiome.acme/weather"
    assert server["$schema"] == mcp_registry.SERVER_SCHEMA_URL
    assert server["title"] == "Weather"
    assert server["version"] == "1.2.0"
    assert server["remotes"] == [{"type": "streamable-http", "url": "https://mcp.example.com/weather"}]
    official = entry["_meta"][OFFICIAL_META_KEY]
    assert official == {
        "status": "active",
        "isLatest": True,
        "publishedAt": "2026-10-01T12:00:00Z",
        "updatedAt": "2026-10-01T12:00:00Z",
    }
    catalog = entry["_meta"][CATALOG_META_KEY]
    assert catalog["grade"] == "B" and catalog["score"] == 88
    assert catalog["trustPosture"] == _POSTURE
    assert catalog["manifestDigest"] == "fp-weather"
    assert "endpoint_url" not in str(entry)


def test_build_server_response_stdio_and_sse_remotes():
    assert build_server_response(_row("a", transport="stdio"))["server"]["remotes"] == []
    sse = build_server_response(_row("a", transport="sse"))["server"]["remotes"]
    assert sse == [{"type": "sse", "url": "https://mcp.example.com/a"}]
    assert build_server_response(_row("a"))["_meta"][CATALOG_META_KEY]["trustPosture"] is None


def test_build_server_response_clips_text_and_falls_back_description():
    long = "word " * 60
    entry = build_server_response(_row("a", description=long, server_title=long))
    assert len(entry["server"]["description"]) == 100
    assert entry["server"]["description"].endswith("…")
    assert len(entry["server"]["title"]) == 100
    assert build_server_response(_row("a", description=None))["server"]["description"] == "A (MCP server)"


def test_naive_timestamps_are_treated_as_utc():
    naive = datetime(2026, 10, 2, 8, 30)
    entry = build_server_response(_row("a", created_at=naive, entry_updated_at=naive))
    assert entry["_meta"][OFFICIAL_META_KEY]["publishedAt"] == "2026-10-02T08:30:00Z"


def test_cursor_round_trip_and_rejection():
    token = encode_cursor("weather")
    assert "=" not in token
    assert decode_cursor(token) == "weather"
    for bad in ("!!!", "e30", encode_cursor("x")[:-2] + "zz"):
        with pytest.raises(InvalidCursorError):
            decode_cursor(bad)


def test_body_etag_is_content_addressed():
    a = build_server_response(_row("a"))
    assert body_etag(a) == body_etag(build_server_response(_row("a")))
    assert body_etag(a) != body_etag(build_server_response(_row("a", surface_fingerprint="fp-new")))
    assert body_etag(a).startswith('"') and body_etag(a).endswith('"')


def test_trust_posture_summary():
    report = {"score": 70, "grade": "C", "gate": {"passed": False}, "findings": []}
    assert trust_posture_summary(report) == {"score": 70, "grade": "C", "gatePassed": False}


def test_server_list_omits_next_cursor_on_last_page():
    assert server_list([], None) == {"servers": [], "metadata": {"count": 0}}
    assert server_list([], "abc")["metadata"]["nextCursor"] == "abc"


# --------------------------------------------------------------------------- conformance


def test_vendored_schema_is_pinned():
    schema = mcp_registry.registry_schema()
    assert "2025-12-11/server.schema.json" in schema["$comment"]
    assert {"ServerDetail", "ServerResponse", "ServerList"} <= set(schema["definitions"])


def test_built_entries_validate_against_vendored_schema():
    rows = [
        _row("weather"),
        _row("legacy", transport="sse", server_version=None, description=None),
        _row("local", transport="stdio", endpoint_url=None),
        _row("long", description="x" * 400, server_title="y" * 400),
    ]
    entries = [build_server_response(r, trust_posture=_POSTURE) for r in rows]
    for entry in entries:
        _validate("ServerResponse", entry)
        _validate("ServerDetail", entry["server"])
    _validate("ServerList", server_list(entries, encode_cursor("long")))


def test_schema_rejects_an_invalid_name():
    entry = build_server_response(_row("weather"))
    entry["server"]["name"] = "no-slash"
    with pytest.raises(jsonschema.ValidationError):
        _validate("ServerResponse", entry)


# --------------------------------------------------------------------------- routes


class _Catalog:
    """In-memory stand-in for ``list_mcp_registry_endpoints`` with the same keyset contract."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows

    def list(
        self,
        tenant_slug: str,
        *,
        include_private: bool,
        limit: int,
        after_slug: Optional[str] = None,
        slug: Optional[str] = None,
        search: Optional[str] = None,
        updated_since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        out = []
        for row in sorted(self.rows, key=lambda r: r["slug"]):
            if row["tenant_slug"] != tenant_slug:
                continue
            if not include_private and not (row["published"] and row["visibility"] == "public"):
                continue
            if after_slug is not None and row["slug"] <= after_slug:
                continue
            if slug is not None and row["slug"] != slug:
                continue
            if search and search.lower() not in (row["name"] + row["slug"]).lower():
                continue
            if updated_since is not None and row["entry_updated_at"] < updated_since:
                continue
            out.append(row)
        return out[:limit]


@pytest.fixture
def catalog():
    """Patch the routes' ``db`` with an in-memory catalog and a fixed posture summary."""
    cat = _Catalog(
        [
            _row("alpha"),
            _row("bravo"),
            _row("charlie", visibility="private"),
            _row("delta", published=False),
            _row("echo", entry_updated_at=_T0 + timedelta(days=3)),
        ]
    )

    async def _posture(_row):
        return _POSTURE

    with patch("app.mcp_registry_routes.db") as mdb, patch(
        "app.mcp_registry_routes._trust_posture", _posture
    ):
        mdb.list_mcp_registry_endpoints.side_effect = cat.list
        mdb.validate_api_key.return_value = None
        mdb.resolve_mcp_api_key_tenant_id.return_value = None
        mdb.get_active_tenant_auth_row.return_value = {"tenant_id": _TENANT_ID, "tenant_slug": "acme"}
        cat.db = mdb
        yield cat


def _names(body: Dict[str, Any]) -> List[str]:
    return [e["server"]["name"].split("/", 1)[1] for e in body["servers"]]


def test_anonymous_list_is_public_slice_and_schema_valid(catalog):
    resp = client.get(_BASE)
    assert resp.status_code == 200
    body = resp.json()
    assert _names(body) == ["alpha", "bravo", "echo"]
    assert body["metadata"] == {"count": 3}
    assert resp.headers["cache-control"] == "public, max-age=60"
    assert resp.headers["etag"]
    _validate("ServerList", body)
    assert catalog.db.list_mcp_registry_endpoints.call_args.kwargs["include_private"] is False


def test_registry_client_pages_through_with_stable_cursor(catalog):
    """A registry client following ``nextCursor`` sees every entry once, even with inserts mid-walk."""
    seen: List[str] = []
    url = f"{_BASE}?limit=1"
    pages = 0
    while True:
        body = client.get(url).json()
        _validate("ServerList", body)
        seen.extend(_names(body))
        pages += 1
        if pages == 2:
            # Inserted before the cursor (already walked past) and after it (still ahead).
            catalog.rows.append(_row("aardvark"))
            catalog.rows.append(_row("zulu"))
        cursor = body["metadata"].get("nextCursor")
        if not cursor:
            break
        url = f"{_BASE}?limit=1&cursor={cursor}"
    assert seen == ["alpha", "bravo", "echo", "zulu"]
    assert len(seen) == len(set(seen))


def test_limit_bounds(catalog):
    assert client.get(f"{_BASE}?limit=101").status_code == 422
    assert client.get(f"{_BASE}?limit=0").status_code == 422
    assert client.get(f"{_BASE}?limit=100").status_code == 200


def test_invalid_cursor_is_400(catalog):
    assert client.get(f"{_BASE}?cursor=garbage!!").status_code == 400


def test_updated_since_filters_on_entry_updated_at(catalog):
    body = client.get(_BASE, params={"updated_since": "2026-10-02T00:00:00Z"}).json()
    assert _names(body) == ["echo"]
    naive = client.get(_BASE, params={"updated_since": "2026-10-02T00:00:00"}).json()
    assert _names(naive) == ["echo"]
    passed = catalog.db.list_mcp_registry_endpoints.call_args.kwargs["updated_since"]
    assert passed.tzinfo is not None


def test_search_and_version_filters(catalog):
    assert _names(client.get(_BASE, params={"search": "BRA"}).json()) == ["bravo"]
    assert len(client.get(_BASE, params={"version": "latest"}).json()["servers"]) == 3
    assert len(client.get(_BASE, params={"version": "1.2.0"}).json()["servers"]) == 3
    assert client.get(_BASE, params={"version": "9.9.9"}).json()["servers"] == []


def test_unknown_tenant_is_empty_list(catalog):
    body = client.get("/v1/tenants/nobody/mcp-registry/v0.1/servers").json()
    assert body == {"servers": [], "metadata": {"count": 0}}


def test_mcp_key_of_tenant_sees_private_entries(catalog):
    catalog.db.resolve_mcp_api_key_tenant_id.return_value = _TENANT_ID
    with patch("app.mcp_registry_routes.decode_jwt", return_value=None):
        resp = client.get(_BASE, headers={"Authorization": "Bearer mcpk_live_secretsecret"})
    assert resp.status_code == 200
    assert _names(resp.json()) == ["alpha", "bravo", "charlie", "delta", "echo"]
    assert resp.headers["cache-control"] == "private, no-store"
    catalog.db.resolve_mcp_api_key_tenant_id.assert_called_with("mcpk_live_secretsecret")


def test_mcp_key_in_x_api_key_header(catalog):
    catalog.db.resolve_mcp_api_key_tenant_id.return_value = _TENANT_ID
    resp = client.get(_BASE, headers={"X-API-Key": "mcpk_live_secretsecret"})
    assert resp.status_code == 200
    assert "charlie" in _names(resp.json())


def test_workspace_api_key_sees_private_entries(catalog):
    catalog.db.validate_api_key.return_value = {"tenant_slug": "acme"}
    with patch(
        "app.mcp_registry_routes.resolve_optional_tenant_member_auth", return_value=True
    ) as resolver:
        resp = client.get(_BASE, headers={"X-API-Key": "apiome_workspace_key"})
    assert resp.status_code == 200
    assert "delta" in _names(resp.json())
    resolver.assert_called_once_with("acme", authorization=None, x_api_key="apiome_workspace_key")


def test_session_jwt_member_sees_private_entries(catalog):
    with patch("app.mcp_registry_routes.decode_jwt", return_value={"user_id": "u1"}), patch(
        "app.mcp_registry_routes.resolve_optional_tenant_member_auth", return_value=True
    ):
        resp = client.get(_BASE, headers={"Authorization": "Bearer eyJ.jwt"})
    assert resp.status_code == 200
    assert "charlie" in _names(resp.json())


def test_invalid_credential_is_401_not_public_view(catalog):
    with patch("app.mcp_registry_routes.decode_jwt", return_value=None):
        resp = client.get(_BASE, headers={"Authorization": "Bearer nope-nope-nope"})
    assert resp.status_code == 401


def test_other_tenants_mcp_key_is_403(catalog):
    catalog.db.resolve_mcp_api_key_tenant_id.return_value = "99999999-9999-9999-9999-999999999999"
    resp = client.get(_BASE, headers={"X-API-Key": "mcpk_other_tenant_key"})
    assert resp.status_code == 403


def test_versions_route_lists_current_version(catalog):
    resp = client.get(f"{_BASE}/apiome.acme%2Falpha/versions")
    assert resp.status_code == 200
    body = resp.json()
    _validate("ServerList", body)
    assert [e["server"]["version"] for e in body["servers"]] == ["1.2.0"]
    assert catalog.db.list_mcp_registry_endpoints.call_args.kwargs["slug"] == "alpha"


def test_private_server_is_404_anonymously_and_200_with_key(catalog):
    assert client.get(f"{_BASE}/apiome.acme%2Fcharlie/versions/latest").status_code == 404
    catalog.db.resolve_mcp_api_key_tenant_id.return_value = _TENANT_ID
    resp = client.get(
        f"{_BASE}/apiome.acme%2Fcharlie/versions/latest",
        headers={"X-API-Key": "mcpk_live_secretsecret"},
    )
    assert resp.status_code == 200
    _validate("ServerResponse", resp.json())


def test_version_route_latest_exact_and_unknown(catalog):
    latest = client.get(f"{_BASE}/apiome.acme%2Falpha/versions/latest")
    assert latest.status_code == 200
    _validate("ServerResponse", latest.json())
    exact = client.get(f"{_BASE}/apiome.acme%2Falpha/versions/1.2.0")
    assert exact.json() == latest.json()
    assert client.get(f"{_BASE}/apiome.acme%2Falpha/versions/0.1.0").status_code == 404


def test_server_in_another_namespace_is_404_without_a_query(catalog):
    assert client.get(f"{_BASE}/apiome.other%2Falpha/versions/latest").status_code == 404
    assert client.get(f"{_BASE}/io.github.x%2Falpha/versions").status_code == 404
    catalog.db.list_mcp_registry_endpoints.assert_not_called()


def test_version_route_etag_and_304(catalog):
    first = client.get(f"{_BASE}/apiome.acme%2Fbravo/versions/latest")
    etag = first.headers["etag"]
    again = client.get(
        f"{_BASE}/apiome.acme%2Fbravo/versions/latest", headers={"If-None-Match": etag}
    )
    assert again.status_code == 304
    assert again.headers["etag"] == etag
    catalog.rows[1]["surface_fingerprint"] = "fp-changed"
    changed = client.get(
        f"{_BASE}/apiome.acme%2Fbravo/versions/latest", headers={"If-None-Match": etag}
    )
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_trust_posture_is_computed_offline_and_degrades_to_null():
    import asyncio

    from app import mcp_registry_routes

    row = _row("alpha")
    report = MagicMock()
    report.report_dict.return_value = {"score": 80, "grade": "B", "gate": {"passed": True}}

    async def _context(*args, **kwargs):
        assert kwargs == {"scan_vulnerabilities": False}
        return object()

    with patch.object(mcp_registry_routes, "db") as mdb, patch.object(
        mcp_registry_routes, "_build_posture_context", _context
    ), patch.object(mcp_registry_routes, "run_trust_posture", return_value=report):
        mdb.get_mcp_endpoint_version.return_value = {"id": row["current_version_id"]}
        assert asyncio.run(mcp_registry_routes._trust_posture(row)) == {
            "score": 80,
            "grade": "B",
            "gatePassed": True,
        }
        mdb.get_mcp_endpoint_version.return_value = None
        assert asyncio.run(mcp_registry_routes._trust_posture(row)) is None
        mdb.get_mcp_endpoint_version.side_effect = RuntimeError("db down")
        assert asyncio.run(mcp_registry_routes._trust_posture(row)) is None


# --------------------------------------------------------------------------- database


def test_list_mcp_registry_endpoints_sql_public_gate_and_keyset():
    with patch.object(real_db, "execute_query", return_value=[]) as eq:
        real_db.list_mcp_registry_endpoints(
            "acme",
            include_private=False,
            limit=31,
            after_slug="bravo",
            search="50%_off",
            updated_since=_T0,
        )
    sql, params = eq.call_args.args
    assert "e.published IS TRUE" in sql and "e.visibility = 'public'" in sql
    assert "e.slug > %s" in sql and "ORDER BY e.slug ASC" in sql
    assert "JOIN apiome.mcp_endpoint_versions v ON v.id = e.current_version_id" in sql
    assert params == ("acme", "bravo", "%50\\%\\_off%", "%50\\%\\_off%", _T0, 31)


def test_list_mcp_registry_endpoints_sql_private_and_slug():
    with patch.object(real_db, "execute_query", return_value=[{"slug": "a"}]) as eq:
        rows = real_db.list_mcp_registry_endpoints("acme", include_private=True, limit=1, slug="a")
    sql, params = eq.call_args.args
    assert "e.published IS TRUE" not in sql
    assert "e.slug = %s" in sql
    assert params == ("acme", "a", 1)
    assert rows == [{"slug": "a"}]


def test_resolve_mcp_api_key_tenant_id_verifies_hash():
    secret = "mcpk_live_0123456789abcdef"
    stored = real_db.hash_mcp_api_key_secret(secret)
    with patch.object(
        real_db,
        "execute_query",
        return_value=[{"tenant_id": "bad", "key_hash": "not-a-hash"}, {"tenant_id": _TENANT_ID, "key_hash": stored}],
    ) as eq:
        assert real_db.resolve_mcp_api_key_tenant_id(secret) == _TENANT_ID
    sql, params = eq.call_args.args
    assert "revoked_at IS NULL" in sql and "expires_at" in sql
    assert params == (real_db.mcp_api_key_prefix(secret),)
    with patch.object(real_db, "execute_query", return_value=[{"tenant_id": _TENANT_ID, "key_hash": stored}]):
        assert real_db.resolve_mcp_api_key_tenant_id(secret + "x") is None
    with patch.object(real_db, "execute_query") as eq:
        assert real_db.resolve_mcp_api_key_tenant_id("short") is None
        eq.assert_not_called()



# --------------------------------------------------------------------------- CDG-4.1 (#5973)

_REGISTRY_BASE = "/registry/mcp/acme/v0.1/servers"

_NPM = {"source_kind": "package", "locator": "pkg:npm/%40acme/weather@1.4.2",
        "purl": "pkg:npm/%40acme/weather@1.4.2", "digest": "1.4.2"}
_PYPI_FLOATING = {"source_kind": "package", "locator": "pkg:pypi/weather-mcp@latest",
                  "purl": "pkg:pypi/weather-mcp@latest", "digest": None}
_IMAGE = {"source_kind": "image", "locator": "ghcr.io/acme/weather@sha256:" + "a" * 64,
          "purl": None, "digest": "sha256:" + "a" * 64}
_GIT = {"source_kind": "git", "locator": "https://github.com/acme/weather", "purl": None,
        "digest": None}
_REGISTRY_ID = {"source_kind": "registry", "locator": "io.github.acme/weather", "purl": None,
                "digest": None}


def test_build_packages_maps_package_and_image_sources():
    packages = build_packages([_NPM, _PYPI_FLOATING, _IMAGE, _GIT, _REGISTRY_ID])
    assert packages == [
        {"registryType": "npm", "identifier": "@acme/weather", "transport": {"type": "stdio"},
         "registryBaseUrl": "https://registry.npmjs.org", "version": "1.4.2"},
        {"registryType": "pypi", "identifier": "weather-mcp", "transport": {"type": "stdio"},
         "registryBaseUrl": "https://pypi.org"},
        {"registryType": "oci", "identifier": _IMAGE["locator"], "transport": {"type": "stdio"}},
    ]


def test_build_packages_never_invents_and_dedupes():
    assert build_packages([]) == []
    assert build_packages([_GIT, _REGISTRY_ID]) == []
    assert build_packages([{"source_kind": "package", "purl": "pkg:npm"}]) == []
    assert len(build_packages([_NPM, dict(_NPM)])) == 1
    unscoped = {"source_kind": "package", "purl": "pkg:npm/%40acme/tool", "digest": None}
    assert build_packages([unscoped])[0]["identifier"] == "@acme/tool"
    assert "version" not in build_packages([unscoped])[0]


def test_build_repository_uses_newest_git_source():
    assert build_repository([_NPM, _GIT]) == {"url": "https://github.com/acme/weather", "source": "github"}
    other = {"source_kind": "git", "locator": "https://git.acme.dev/team/weather"}
    assert build_repository([other, _GIT]) == {"url": "https://git.acme.dev/team/weather", "source": "git.acme.dev"}
    assert build_repository([_NPM, _IMAGE]) is None
    assert build_repository([]) is None


def test_lint_gate_summary_reads_stored_verdict():
    assert lint_gate_summary(_row("a")) == {"verdict": "not_evaluated", "evaluatedAt": None}
    assert lint_gate_summary(_row("a", lint_gate_passed=True, lint_gate_evaluated_at=_T0)) == {
        "verdict": "pass", "evaluatedAt": "2026-10-01T12:00:00Z"}
    assert lint_gate_summary(_row("a", lint_gate_passed=False))["verdict"] == "fail"


def test_owner_team_summary():
    owner = {"team": {"id": "t1", "slug": "platform", "name": "Platform"}, "status": "confirmed",
             "source": "manual"}
    assert owner_team(_row("a", entity_owner=owner)) == {
        "slug": "platform", "name": "Platform", "status": "confirmed"}
    assert owner_team(_row("a")) is None
    assert owner_team(_row("a", entity_owner={"team": None})) is None


def test_server_without_sources_has_empty_packages_and_sources_none():
    entry = build_server_response(_row("weather"))
    assert entry["server"]["packages"] == []
    assert "repository" not in entry["server"]
    catalog = entry["_meta"][CATALOG_META_KEY]
    assert catalog["sources"] == "none"
    assert catalog["ownerTeam"] is None
    assert catalog["lintGate"]["verdict"] == "not_evaluated"
    _validate("ServerResponse", entry)


def test_server_with_sources_validates_against_vendored_schema():
    row = _row("weather", sources=[_NPM, _IMAGE, _GIT, _REGISTRY_ID], lint_gate_passed=True,
               lint_gate_evaluated_at=_T0,
               entity_owner={"team": {"slug": "platform", "name": "Platform"}, "status": "suggested"})
    entry = build_server_response(row, trust_posture=_POSTURE)
    _validate("ServerResponse", entry)
    _validate("ServerDetail", entry["server"])
    assert [p["registryType"] for p in entry["server"]["packages"]] == ["npm", "oci"]
    assert entry["server"]["repository"]["url"] == "https://github.com/acme/weather"
    catalog = entry["_meta"][CATALOG_META_KEY]
    assert catalog["sources"] == "linked"
    assert catalog["lintGate"] == {"verdict": "pass", "evaluatedAt": "2026-10-01T12:00:00Z"}
    assert catalog["ownerTeam"]["slug"] == "platform"


def test_only_registry_sources_is_linked_but_packages_empty():
    entry = build_server_response(_row("weather", sources=[_REGISTRY_ID]))
    assert entry["server"]["packages"] == []
    assert entry["_meta"][CATALOG_META_KEY]["sources"] == "linked"


def test_registry_mount_serves_the_same_listing(catalog):
    legacy = client.get(_BASE)
    mounted = client.get(_REGISTRY_BASE)
    assert mounted.status_code == 200
    assert mounted.json() == legacy.json()
    assert mounted.headers["etag"] == legacy.headers["etag"]
    _validate("ServerList", mounted.json())


def test_registry_mount_pages_with_stable_cursor(catalog):
    seen: List[str] = []
    url = f"{_REGISTRY_BASE}?limit=2"
    while True:
        body = client.get(url).json()
        seen.extend(_names(body))
        cursor = body["metadata"].get("nextCursor")
        if not cursor:
            break
        catalog.rows.append(_row("able"))  # sorts before every cursor: never shows up mid-walk
        url = f"{_REGISTRY_BASE}?limit=2&cursor={cursor}"
    assert seen == ["alpha", "bravo", "echo"]


def test_registry_mount_unpublished_is_404_anonymously_and_200_with_key(catalog):
    path = f"{_REGISTRY_BASE}/apiome.acme%2Fdelta/versions/latest"
    assert client.get(path).status_code == 404
    assert client.get(f"{_REGISTRY_BASE}/apiome.acme%2Fdelta/versions").status_code == 404
    catalog.db.resolve_mcp_api_key_tenant_id.return_value = _TENANT_ID
    resp = client.get(path, headers={"X-API-Key": "mcpk_live_secretsecret"})
    assert resp.status_code == 200
    _validate("ServerResponse", resp.json())


def test_registry_mount_updated_since_and_limit(catalog):
    body = client.get(_REGISTRY_BASE, params={"updated_since": "2026-10-02T00:00:00Z"}).json()
    assert _names(body) == ["echo"]
    assert client.get(f"{_REGISTRY_BASE}?limit=101").status_code == 422


def test_schema_route_on_both_mounts():
    for path in ("/registry/mcp/acme/v0.1/schema", "/v1/tenants/acme/mcp-registry/v0.1/schema"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.json() == {
            "registryApiVersion": "v0.1",
            "serverSchema": mcp_registry.SERVER_SCHEMA_URL,
            "apiSpec": {"version": "2025-12-01",
                        "commit": "11b7b0e274d518b6f449c5ee3518a6151d9848b9"},
        }
        assert resp.headers["cache-control"] == "public, max-age=60"


def test_schema_info_matches_vendored_pin():
    comment = mcp_registry.registry_schema()["$comment"]
    info = mcp_registry.schema_info()
    assert info["apiSpec"]["commit"] in comment
    assert info["apiSpec"]["version"] in comment
    assert "2025-12-11/server.schema.json" in info["serverSchema"]


def test_list_mcp_registry_endpoints_sql_joins_sources_owner_and_lint_gate():
    with patch.object(real_db, "execute_query", return_value=[]) as eq:
        real_db.list_mcp_registry_endpoints("acme", include_private=False, limit=2)
    sql = eq.call_args.args[0]
    assert "FROM apiome.mcp_endpoint_sources ms" in sql and "ms.retired_at IS NULL" in sql
    assert "'[]'::jsonb" in sql
    assert "FROM apiome.lint_policy_evaluations pe" in sql
    assert "pe.mcp_version_id = e.current_version_id" in sql
    assert "own.entity_owner" in sql and "apiome.entity_owners" in sql


def test_listing_updated_since_covers_the_change_feed_timestamp():
    """A feed entry's stamp is its snapshot's ``discovered_at``; the listing's bound is never earlier."""
    with patch.object(real_db, "execute_query", return_value=[]) as eq:
        real_db.list_mcp_registry_endpoints("acme", include_private=False, limit=2, updated_since=_T0)
    sql = eq.call_args.args[0]
    assert "GREATEST(e.updated_at, COALESCE(v.discovered_at, v.created_at)) >= %s" in sql
