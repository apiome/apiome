"""The tenant-host alias of the Pact Broker surface — PFX-1.2 (#6915).

``<tenant>.<suffix>/<path>`` is served as ``/v1/tenants/<tenant>/pact-broker/<path>``; anything
else is left alone, and the alias is off unless a suffix is configured.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.config import settings
from app.pact_broker_host import PactBrokerHostAliasMiddleware, alias_base_url, tenant_from_host


@pytest.mark.parametrize(
    ("host", "tenant"),
    [
        ("acme.pact.example.com", "acme"),
        ("ACME.Pact.Example.com:8443", "acme"),
        ("acme-corp.pact.example.com.", "acme-corp"),
        ("pact.example.com", None),
        ("a.b.pact.example.com", None),
        ("-bad.pact.example.com", None),
        ("acme.pact.example.com.evil.test", None),
        ("evilpact.example.com", None),
        ("api.example.com", None),
        ("", None),
    ],
)
def test_tenant_from_host(host: str, tenant: Optional[str]) -> None:
    assert tenant_from_host(host, "pact.example.com") == tenant


def test_no_suffix_means_no_alias() -> None:
    assert tenant_from_host("acme.pact.example.com", "") is None
    assert tenant_from_host("acme.pact.example.com", " . ") is None


def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"path": request.url.path, "alias": alias_base_url(request.scope)})


def _client(suffix: Optional[str]) -> TestClient:
    app = Starlette(routes=[Route("/{rest:path}", _echo)])
    app.add_middleware(PactBrokerHostAliasMiddleware, suffix=suffix)
    return TestClient(app)


def test_an_aliased_request_is_served_from_the_tenant_broker_path() -> None:
    client = _client("pact.example.com")
    seen: List[Dict[str, Any]] = [
        client.get("/", headers={"host": "acme.pact.example.com"}).json(),
        client.get("/contracts/publish", headers={"host": "acme.pact.example.com"}).json(),
        client.get("/v1/tenants/other/projects", headers={"host": "acme.pact.example.com"}).json(),
    ]
    assert [entry["path"] for entry in seen] == [
        "/v1/tenants/acme/pact-broker",
        "/v1/tenants/acme/pact-broker/contracts/publish",
        # Every path on the alias host is prefixed: nothing outside the broker is reachable there.
        "/v1/tenants/acme/pact-broker/v1/tenants/other/projects",
    ]
    assert {entry["alias"] for entry in seen} == {"http://acme.pact.example.com"}


def test_other_hosts_pass_through_untouched() -> None:
    client = _client("pact.example.com")
    body = client.get("/v1/tenants/acme/projects", headers={"host": "api.example.com"}).json()
    assert body == {"path": "/v1/tenants/acme/projects", "alias": None}


def test_the_suffix_is_read_from_settings_per_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(None)
    headers = {"host": "acme.pact.example.com"}
    monkeypatch.setattr(settings, "pact_broker_host_suffix", "")
    assert client.get("/x", headers=headers).json()["path"] == "/x"
    monkeypatch.setattr(settings, "pact_broker_host_suffix", "pact.example.com")
    assert client.get("/x", headers=headers).json()["path"] == "/v1/tenants/acme/pact-broker/x"
