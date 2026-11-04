"""Read-only xRegistry API façade — MFX-34.2 (#4307).

Covers :mod:`app.xregistry_registry` (composition and entity rendering) and :mod:`app.xregistry_routes`
(the two mounts), against the issue's acceptance criteria:

* **a generic xRegistry client can list and fetch schemas and message definitions** — starting at the
  registry root and following only the ``*url`` attributes it is given, a client reaches every schema
  group, schema (its document and ``$details``), version, message group and message, and every
  message's ``dataschemaxid`` resolves to a schema it can fetch;
* **private artifacts are never exposed; the browse path is published-only** — the public mount reads
  the published, public slice whatever the caller's credentials and loads sources through the public
  gate; the member mount needs authentication for that tenant.

Plus ``/capabilities``, ``/model``, ``inline``, the 404s, the cache and the rate limit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.config import settings
from app.emitter import load_builtin_emitters
from app.export_source import ExportSourceError
from app.import_source import load_builtin_import_sources
from app.main import app
from app.rate_limit import FixedWindowRateLimiter
from app.xregistry_registry import (
    RegistryArtifact,
    XRegistryNotFoundError,
    XRegistryView,
    compose_registry,
    resource_ids,
)
from app.xregistry_routes import registry_cache

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_TENANT = {"id": "t-1", "slug": "acme", "name": "Acme Corp"}
_BASE = "http://testserver/v1/browse/tenants/acme/xregistry"
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    registry_cache.clear()
    yield
    registry_cache.clear()
    app.dependency_overrides.pop(validate_authentication, None)


def _corpus(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _orders() -> CanonicalApi:
    return _corpus("xregistry/02-typical-order-events.json", "xregistry")


def _pets() -> CanonicalApi:
    return _corpus("openapi/30-openapi-3.0-petstore.yaml", "openapi")


def _artifacts() -> List[RegistryArtifact]:
    return [
        RegistryArtifact("orders", "Order events", "2.0.0", "2026-10-01T12:00:00Z", _orders()),
        RegistryArtifact("pets", "Pet Store", "1.2.0", "2026-11-01T08:30:00+00:00", _pets()),
        RegistryArtifact("agent", "Agent", "1.0.0", None,
                         CanonicalApi(paradigm=ApiParadigm.AGENT, format="a2a", identity=ApiIdentity(name="a"))),
    ]


def _view() -> XRegistryView:
    return XRegistryView(compose_registry("acme", "Acme Corp", _artifacts()), _BASE)


# ===========================================================================
# Composition
# ===========================================================================


def test_each_artifact_contributes_a_schema_group_and_prefixed_message_groups() -> None:
    registry = compose_registry("acme", "Acme Corp", _artifacts())
    assert sorted(registry.groups["schemagroups"]) == ["orders", "pets"]  # the agent has nothing to project
    assert sorted(registry.groups["messagegroups"]) == ["orders.orders.mqtt"]
    assert registry.groups["messagegroups"]["orders.orders.mqtt"]["messagegroupid"] == "orders.orders.mqtt"
    assert registry.modified == "2026-11-01T08:30:00Z"
    assert "/schemagroups/pets/schemas/Pet" in resource_ids(registry)


def test_a_schema_version_is_named_after_the_artifact_version() -> None:
    registry = compose_registry("acme", "Acme Corp", _artifacts())
    schema = registry.groups["schemagroups"]["pets"]["schemas"]["Pet"]
    assert schema["defaultversionid"] == "1.2.0" and list(schema["versions"]) == ["1.2.0"]
    assert schema["versions"]["1.2.0"]["versionid"] == "1.2.0"


def test_every_message_payload_names_a_schema_of_the_registry() -> None:
    registry = compose_registry("acme", "Acme Corp", _artifacts())
    xids = set(resource_ids(registry))
    messages = [m for g in registry.groups["messagegroups"].values() for m in g["messages"].values()]
    assert messages and all(m["dataschemaxid"] in xids for m in messages if "dataschemaxid" in m)


# ===========================================================================
# Entities
# ===========================================================================


def test_the_root_names_each_collection_with_its_url_and_count() -> None:
    root = _view().root()
    assert root["registryid"] == "acme" and root["specversion"] == "1.0-rc1" and root["xid"] == "/"
    assert root["self"] == f"{_BASE}/" and root["epoch"] == 1
    assert root["schemagroupsurl"] == f"{_BASE}/schemagroups" and root["schemagroupscount"] == 2
    assert root["messagegroupsurl"] == f"{_BASE}/messagegroups" and root["messagegroupscount"] == 1
    assert "schemagroups" not in root


def test_inline_embeds_everything_below() -> None:
    root = _view().root(inline=True)
    assert root["schemagroups"]["pets"]["schemas"]["Pet"]["format"] == "JsonSchema/draft/2020-12"
    assert root["messagegroups"]["orders.orders.mqtt"]["messages"]


def test_capabilities_and_model() -> None:
    view = _view()
    assert view.capabilities()["mutable"] == [] and "inline" in view.capabilities()["flags"]
    model = view.model()["groups"]
    assert model["schemagroups"]["resources"]["schemas"]["hasdocument"] is True
    assert model["messagegroups"]["resources"]["messages"]["hasdocument"] is False


def test_a_group_and_its_resources() -> None:
    view = _view()
    group = view.group("schemagroups", "pets")
    assert group["schemagroupid"] == "pets" and group["xid"] == "/schemagroups/pets"
    assert group["schemasurl"] == f"{_BASE}/schemagroups/pets/schemas" and group["schemascount"] >= 2
    assert group["createdat"] == "2026-11-01T08:30:00Z"
    schemas = view.resources("schemagroups", "pets", "schemas")
    assert schemas["Pet"]["xid"] == "/schemagroups/pets/schemas/Pet"


def test_a_schema_document_and_its_details() -> None:
    view = _view()
    document, headers = view.document("schemagroups", "pets", "schemas", "Pet")
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema" and document["type"] == "object"
    assert headers["xRegistry-schemaid"] == "Pet" and headers["xRegistry-versionid"] == "1.2.0"
    details = view.details("schemagroups", "pets", "schemas", "Pet")
    assert details["self"] == f"{_BASE}/schemagroups/pets/schemas/Pet$details"
    assert details["schemaurl"] == f"{_BASE}/schemagroups/pets/schemas/Pet"
    assert details["defaultversionurl"] == f"{_BASE}/schemagroups/pets/schemas/Pet/versions/1.2.0"
    assert "schema" not in details and "versions" not in details


def test_a_message_is_its_attributes() -> None:
    view = _view()
    messages = view.resources("messagegroups", "orders.orders.mqtt", "messages")
    message = next(iter(messages.values()))
    assert message["envelope"] == "CloudEvents/1.0"
    assert message["envelopemetadata"]["type"]["value"].startswith("com.example.orders.")
    with pytest.raises(XRegistryNotFoundError):
        view.document("messagegroups", "orders.orders.mqtt", "messages", message["messageid"])


def test_versions() -> None:
    view = _view()
    versions = view.versions("schemagroups", "pets", "schemas", "Pet")
    assert list(versions) == ["1.2.0"]
    assert versions["1.2.0"]["self"] == f"{_BASE}/schemagroups/pets/schemas/Pet/versions/1.2.0$details"
    document, _headers = view.version_document("schemagroups", "pets", "schemas", "Pet", "1.2.0")
    assert document["type"] == "object"


@pytest.mark.parametrize("call", [
    lambda v: v.groups("widgets"),
    lambda v: v.group("schemagroups", "nope"),
    lambda v: v.resources("schemagroups", "pets", "messages"),
    lambda v: v.details("schemagroups", "pets", "schemas", "Nope"),
    lambda v: v.version_details("schemagroups", "pets", "schemas", "Pet", "9.9.9"),
])
def test_an_unknown_path_is_not_found(call: Any) -> None:
    with pytest.raises(XRegistryNotFoundError):
        call(_view())


# ===========================================================================
# HTTP: the public mount
# ===========================================================================


_PROJECTS = [{"slug": "pets", "name": "Pet Store", "latest_version": "1.2.0"},
             {"slug": "orders", "name": "Order events", "latest_version": "2.0.0"}]
_VERSIONS = {
    "pets": [{"version_id": "1.1.0", "published_at": "2026-10-01T00:00:00Z"},
             {"version_id": "1.2.0", "published_at": "2026-11-01T08:30:00Z"}],
    "orders": [{"version_id": "2.0.0", "published_at": "2026-10-01T12:00:00Z"}],
}


class _Source:
    def __init__(self, api: CanonicalApi) -> None:
        self.api = api


def _models() -> Dict[str, CanonicalApi]:
    return {"pets": _pets(), "orders": _orders()}


def _public(path: str, *, versions: Optional[Dict[str, Any]] = None, hidden: tuple = (), **headers: str) -> Any:
    """GET ``path`` on the public mount with a faked tenant directory and public source gate."""
    models = _models()

    def load(tenant_slug: str, slug: str, version: str) -> _Source:
        if slug in hidden:
            raise ExportSourceError("not public", status_code=404)
        return _Source(models[slug])

    with patch("app.xregistry_routes.db") as db, \
            patch("app.xregistry_routes.load_public_export_source", side_effect=load) as public, \
            patch("app.xregistry_routes.load_export_source") as member:
        db.get_tenant_row_by_slug.side_effect = lambda slug: _TENANT if slug == "acme" else None
        db.list_public_browse_projects_for_tenant.return_value = _PROJECTS
        db.list_public_browse_versions_for_project.side_effect = lambda tid, slug: (versions or _VERSIONS)[slug]
        response = client.get(path, headers=headers)
    response.db, response.public, response.member = db, public, member  # type: ignore[attr-defined]
    return response


def test_a_generic_client_walks_the_registry_by_its_links() -> None:
    """Follow only the URLs the server hands out, as an xRegistry client does."""
    seen: Dict[str, Any] = {}

    def fetch(url: str) -> Any:
        path = url.replace("http://testserver", "")
        response = _public(path)
        assert response.status_code == 200, (path, response.text)
        seen[path] = response
        return response

    root = fetch("/v1/browse/tenants/acme/xregistry").json()
    schemas_fetched = 0
    for group in fetch(root["schemagroupsurl"]).json().values():
        for schema in fetch(group["schemasurl"]).json().values():
            document = fetch(schema["schemaurl"])
            assert document.headers["content-type"].startswith("application/json")
            assert document.headers["xregistry-schemaid"] == schema["schemaid"]
            assert "type" in document.json() or "$ref" in document.json() or "enum" in document.json() \
                or "anyOf" in document.json()
            assert fetch(schema["self"]).json()["schemaid"] == schema["schemaid"]  # its $details
            for version in fetch(schema["versionsurl"]).json().values():
                assert version["versionid"] == schema["defaultversionid"]
            schemas_fetched += 1
    messages_fetched = 0
    for group in fetch(root["messagegroupsurl"]).json().values():
        for message in fetch(group["messagesurl"]).json().values():
            body = fetch(message["self"].replace("$details", "")).json()
            assert body["envelopemetadata"]["type"]["value"] and body["envelopemetadata"]["source"]["value"]
            assert body["datacontenttype"]
            if "dataschemaxid" in body:  # the payload schema resolves through the same API
                fetch(f"{_BASE}{body['dataschemaxid']}")
            messages_fetched += 1
    assert schemas_fetched >= 3 and messages_fetched == 2


def test_the_public_mount_reads_only_the_public_slice_whatever_the_credentials() -> None:
    response = _public("/v1/browse/tenants/acme/xregistry", Authorization="Bearer member-token")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    response.db.list_public_browse_projects_for_tenant.assert_called_once_with("t-1", require_published=True)
    assert not response.db.list_member_browse_projects_for_tenant.called
    assert not response.member.called
    # Each project's latest published version, through the public gate.
    assert sorted(c.args for c in response.public.call_args_list) == [("acme", "orders", "2.0.0"),
                                                                      ("acme", "pets", "1.2.0")]


def test_a_version_the_public_gate_refuses_is_never_served() -> None:
    response = _public("/v1/browse/tenants/acme/xregistry/schemagroups", hidden=("pets",))
    assert response.status_code == 200
    assert list(response.json()) == ["orders"]
    assert _public("/v1/browse/tenants/acme/xregistry/schemagroups/pets", hidden=("pets",)).status_code == 404


def test_details_suffix_and_inline_over_http() -> None:
    details = _public("/v1/browse/tenants/acme/xregistry/schemagroups/pets/schemas/Pet$details")
    assert details.status_code == 200 and details.json()["schemaid"] == "Pet"
    inline = _public("/v1/browse/tenants/acme/xregistry?inline=*")
    assert "Pet" in inline.json()["schemagroups"]["pets"]["schemas"]
    assert _public("/v1/browse/tenants/acme/xregistry/capabilities").json()["pagination"] is False
    assert "groups" in _public("/v1/browse/tenants/acme/xregistry/model").json()


@pytest.mark.parametrize("path", [
    "/v1/browse/tenants/nope/xregistry",
    "/v1/browse/tenants/acme/xregistry/widgets",
    "/v1/browse/tenants/acme/xregistry/schemagroups/nope",
    "/v1/browse/tenants/acme/xregistry/schemagroups/pets/messages",
    "/v1/browse/tenants/acme/xregistry/schemagroups/pets/schemas/Nope",
    "/v1/browse/tenants/acme/xregistry/schemagroups/pets/schemas/Pet/versions/0.0.1",
])
def test_unknown_paths_are_404(path: str) -> None:
    assert _public(path).status_code == 404


def test_the_registry_is_cached_until_a_version_changes() -> None:
    first = _public("/v1/browse/tenants/acme/xregistry")
    assert first.public.call_count == 2
    again = _public("/v1/browse/tenants/acme/xregistry/schemagroups")
    assert again.public.call_count == 0  # served from the cache
    newer = dict(_VERSIONS, orders=[{"version_id": "2.1.0", "published_at": "2026-11-03T00:00:00Z"}])
    rebuilt = _public("/v1/browse/tenants/acme/xregistry", versions=newer)
    assert rebuilt.public.call_count == 2


def test_the_public_export_rate_limit_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "public_browse_export_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with patch("app.public_export_guards._public_export_limiter", FixedWindowRateLimiter()):
        assert _public("/v1/browse/tenants/acme/xregistry/capabilities").status_code == 200
        assert _public("/v1/browse/tenants/acme/xregistry/capabilities").status_code == 429


# ===========================================================================
# HTTP: the member mount
# ===========================================================================


def _member(path: str, *, authenticated: bool = True) -> Any:
    """GET ``path`` on the member mount with a faked member directory and tenant source loader."""
    models = _models()
    if authenticated:
        app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t-1", "tenant_slug": "acme"}
    with patch("app.xregistry_routes.db") as db, \
            patch("app.xregistry_routes.load_export_source",
                  side_effect=lambda tid, pid, version: _Source(models[pid.removeprefix("id-")])) as member, \
            patch("app.xregistry_routes.load_public_export_source") as public:
        db.get_tenant_row_by_slug.side_effect = lambda slug: _TENANT if slug == "acme" else None
        db.list_member_browse_projects_for_tenant.return_value = _PROJECTS
        db.list_member_browse_versions_for_project.side_effect = lambda tid, slug: _VERSIONS[slug]
        db.get_project_by_slug.side_effect = lambda slug, tid: {"id": f"id-{slug}", "slug": slug}
        response = client.get(path)
    app.dependency_overrides.pop(validate_authentication, None)
    response.db, response.member, response.public = db, member, public  # type: ignore[attr-defined]
    return response


def test_the_member_mount_serves_the_tenants_published_versions() -> None:
    response = _member("/v1/xregistry/acme")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=60"
    root = response.json()
    assert root["self"] == "http://testserver/v1/xregistry/acme/" and root["schemagroupscount"] == 2
    response.db.list_member_browse_projects_for_tenant.assert_called_once_with("t-1", require_published=True)
    assert not response.public.called
    assert sorted(c.args for c in response.member.call_args_list) == [("t-1", "id-orders", "2.0.0"),
                                                                      ("t-1", "id-pets", "1.2.0")]


def test_the_member_mount_needs_authentication() -> None:
    assert _member("/v1/xregistry/acme", authenticated=False).status_code in (401, 403)


def test_the_member_and_public_registries_are_cached_apart() -> None:
    _public("/v1/browse/tenants/acme/xregistry")
    member = _member("/v1/xregistry/acme")
    assert member.member.call_count == 2  # not served from the public slice's cache entry


def test_a_schema_document_over_the_member_mount() -> None:
    response = _member("/v1/xregistry/acme/schemagroups/pets/schemas/Pet")
    assert response.status_code == 200 and json.loads(response.text)["type"] == "object"
    assert response.headers["xregistry-self"] == "http://testserver/v1/xregistry/acme/schemagroups/pets/schemas/Pet"
