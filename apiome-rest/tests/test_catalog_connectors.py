"""Catalog connector rules (CDG-1.1, #5952): validation, the base-URL SSRF check, provenance.

Pure tests: DNS is replaced by an injected resolver, so every address case is a literal.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.catalog_connectors import (
    CODE_BASE_URL_REFUSED,
    CODE_INVALID,
    INPUT_KIND_CONNECTOR,
    KINDS,
    REASON_CREDENTIALS,
    REASON_MALFORMED,
    REASON_NO_HOST,
    REASON_PRIVATE,
    REASON_SCHEME,
    REASON_UNRESOLVABLE,
    ConnectorCreate,
    ConnectorError,
    ConnectorUpdate,
    build_connector_http_client,
    check_connector_base_url,
    connector_provenance_metadata,
    parse_private_network_allowlist,
    revision_label,
    validate_credentials,
    validate_name,
    validate_scope,
)
from app.config import settings
from app.ssrf_guard import SSRFError


def _resolver(*addresses: str):
    """A resolver answering ``addresses`` for every host."""
    return lambda host: list(addresses)


def _refused(url: str, **kwargs) -> ConnectorError:
    with pytest.raises(ConnectorError) as info:
        check_connector_base_url(url, **kwargs)
    assert info.value.code == CODE_BASE_URL_REFUSED
    return info.value


# --- base URL -------------------------------------------------------------------------


def test_public_base_url_is_accepted_and_trimmed():
    assert (
        check_connector_base_url("  https://us.api.konghq.com/v2  ", resolver=_resolver("93.184.216.34"))
        == "https://us.api.konghq.com/v2"
    )


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.20", "172.16.4.4", "::1", "fd00::1"],
)
def test_private_range_base_url_is_refused_with_a_stable_reason(address):
    error = _refused("https://kong-admin.internal:8001", resolver=_resolver(address))
    assert error.reason == REASON_PRIVATE
    assert error.as_detail() == {
        "code": CODE_BASE_URL_REFUSED,
        "reason": REASON_PRIVATE,
        "message": str(error),
    }


def test_one_private_address_among_public_ones_is_refused():
    error = _refused("https://mixed.example", resolver=_resolver("93.184.216.34", "10.1.2.3"))
    assert error.reason == REASON_PRIVATE


def test_allowlisted_private_range_is_accepted():
    url = "http://kong-admin.internal:8001"
    allow = parse_private_network_allowlist("10.20.0.0/16")
    assert check_connector_base_url(url, allowlist=allow, resolver=_resolver("10.20.3.4")) == url


def test_allowlist_must_cover_every_private_address():
    allow = parse_private_network_allowlist("10.20.0.0/16")
    error = _refused("http://x.internal", allowlist=allow, resolver=_resolver("10.20.3.4", "10.99.0.1"))
    assert error.reason == REASON_PRIVATE


def test_ssrf_allow_private_skips_the_address_rule_but_not_the_shape_rules():
    assert check_connector_base_url("http://localhost:8001", allow_private=True) == "http://localhost:8001"
    assert _refused("ftp://localhost", allow_private=True).reason == REASON_SCHEME


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", REASON_SCHEME),
        ("gopher://example.com", REASON_SCHEME),
        ("https://user:pass@example.com", REASON_CREDENTIALS),
        ("https://", REASON_NO_HOST),
        ("", REASON_MALFORMED),
    ],
)
def test_shape_refusals_have_stable_reasons(url, reason):
    assert _refused(url, resolver=_resolver("93.184.216.34")).reason == reason


def test_unresolvable_host_is_refused():
    def _fail(host):
        raise OSError("no such host")

    assert _refused("https://nowhere.invalid", resolver=_fail).reason == REASON_UNRESOLVABLE
    assert _refused("https://empty.invalid", resolver=_resolver()).reason == REASON_UNRESOLVABLE


def test_allowlist_parsing_skips_bad_entries():
    assert parse_private_network_allowlist(" 10.0.0.0/8, nonsense ,192.168.4.7,, 10.0.0.1/24") == (
        "10.0.0.0/8",
        "192.168.4.7/32",
    )
    assert parse_private_network_allowlist(None) == ()


def test_connector_http_client_refuses_a_private_hop(monkeypatch):
    """Every request through the source client re-runs the check, so a redirect target is too."""
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    monkeypatch.setattr(settings, "connector_private_network_allowlist", "")
    with build_connector_http_client() as client:
        with pytest.raises(SSRFError):
            client.get("http://127.0.0.1:9/never")


def test_connector_http_client_does_not_trust_proxy_env():
    with build_connector_http_client() as client:
        assert client._trust_env is False  # noqa: SLF001 - pinning the safety default


# --- names, scope, credentials ---------------------------------------------------------


def test_names_are_trimmed_and_checked():
    assert validate_name("  Prod gateway ") == "Prod gateway"
    for bad in ("   ", "bad\x07name", "x" * 201):
        with pytest.raises(ConnectorError) as info:
            validate_name(bad)
        assert info.value.code == CODE_INVALID


def test_scope_refuses_secret_like_keys_anywhere():
    with pytest.raises(ConnectorError) as info:
        validate_scope({"controlPlaneId": "cp-1", "auth": {"client_secret": "x"}, "items": [{"apiKey": "k"}]})
    message = str(info.value)
    assert "auth.client_secret" in message and "items[0].apiKey" in message
    assert '"x"' not in message and "'k'" not in message


def test_scope_accepts_coordinates_and_refuses_oversize():
    assert validate_scope({"region": "eu-west-1", "accountId": "123"}) == {"region": "eu-west-1", "accountId": "123"}
    with pytest.raises(ConnectorError):
        validate_scope({"blob": "x" * 20_000})


def test_credentials_validation_never_echoes_values():
    assert validate_credentials({"token": SecretStr("abc")}) == {"token": "abc"}
    for bad in ({}, {"token": SecretStr("")}, {"token": SecretStr("y" * 5000)}):
        with pytest.raises(ConnectorError) as info:
            validate_credentials(bad)
        assert "y" * 50 not in str(info.value)
    with pytest.raises(ConnectorError):
        validate_credentials({f"k{i}": SecretStr("v") for i in range(17)})


def test_create_body_rejects_unknown_kinds_and_fields():
    assert ConnectorCreate(kind="kong-konnect", name="n").conflict_policy == "hold-for-review"
    with pytest.raises(ValidationError):
        ConnectorCreate(kind="ftp-server", name="n")
    with pytest.raises(ValidationError):
        ConnectorCreate(kind="url", name="n", token="secret")
    with pytest.raises(ValidationError):
        ConnectorCreate(kind="url", name="n", refreshIntervalSeconds=0)


def test_update_body_cannot_set_failing_or_kind():
    with pytest.raises(ValidationError):
        ConnectorUpdate(status="failing")
    with pytest.raises(ValidationError):
        ConnectorUpdate(kind="url")


def test_kinds_are_the_issue_vocabulary():
    assert set(KINDS) == {
        "kong-konnect",
        "kong-admin",
        "aws-apigateway",
        "azure-apim",
        "apigee",
        "url",
        "schema-registry",
        "mcp-registry",
    }


# --- revision labels and provenance -----------------------------------------------------


def test_revision_label_uses_the_remote_revision_safely():
    assert revision_label("v2.3.1") == "v2.3.1"
    assert revision_label("rev 7 / prod") == "rev-7-prod"
    assert len(revision_label("a" * 200)) == 64


def test_revision_label_without_a_revision_is_a_timestamp():
    now = datetime(2026, 10, 17, 9, 30, 5, tzinfo=timezone.utc)
    assert revision_label(None, now=now) == "sync-20261017T093005Z"
    assert revision_label(" // ", now=now) == "sync-20261017T093005Z"


def test_provenance_metadata_is_the_connector_descriptor():
    meta = connector_provenance_metadata(
        {"id": "c-1", "kind": "kong-konnect", "name": "Prod", "scope": {"token": "never"}},
        remote_id="svc-1",
        remote_revision="r3",
        remote_name="Orders",
        source_uri="https://cloud.konghq.com/x",
    )
    assert meta == {
        "inputKind": INPUT_KIND_CONNECTOR,
        "connectorId": "c-1",
        "connectorKind": "kong-konnect",
        "connectorName": "Prod",
        "remoteId": "svc-1",
        "remoteRevision": "r3",
        "remoteName": "Orders",
        "sourceUri": "https://cloud.konghq.com/x",
    }


def test_connector_http_client_accepts_a_transport():
    """Sources pass a mock transport in their own tests; the guard still runs first."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with build_connector_http_client(transport=transport) as client:
        with pytest.raises(SSRFError):
            client.get("http://10.0.0.1/x")
