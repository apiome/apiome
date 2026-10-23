"""SSO provider identifiers, OIDC discovery and SAML metadata — EID-1.1 (#5011).

Pure tests of :mod:`app.sso_metadata`: no database, no network (the one fetch helper is replaced).
They pin the refusals an admin can meet, each with its stable ``sso-*`` code:

* slugs fit ``sso:<slug>`` into a ``VARCHAR(32)`` and never reuse an OAuth provider id;
* a discovery document must name the registered issuer and HTTPS authorize / token / JWKS endpoints;
* SAML metadata is parsed without DTDs or entities, needs a signing certificate, and an IdP that
  offers only HTTP-Artifact is ``sso-binding-unsupported`` — never silently downgraded.
"""

from __future__ import annotations

import asyncio

import pytest

from app import sso_metadata as sm
from app.sso_metadata import SsoConfigError

ISSUER = "https://idp.example.com/realms/acme"

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
    "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
}

CERT = "MIIC" + "A" * 60


def _metadata(*services: tuple, cert: bool = True, entity_id: str = "https://idp.example.com/saml") -> str:
    """IdP metadata with the given ``(binding_suffix, location)`` single sign-on services."""
    key = (
        f"""<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data><ds:X509Certificate>
        {CERT}
        </ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"""
        if cert
        else ""
    )
    sso = "".join(
        f'<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:{binding}" Location="{location}"/>'
        for binding, location in services
    )
    return f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="{entity_id}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    {key}
    <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
    {sso}
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(SsoConfigError) as caught:
        fn(*args, **kwargs)
    return caught.value.code


# --- identifiers -------------------------------------------------------------------------------


class TestSlug:
    def test_accepts_and_normalizes(self) -> None:
        assert sm.normalize_slug("  Acme-Okta ") == "acme-okta"

    @pytest.mark.parametrize("raw", ["", "a", "-acme", "acme_okta", "acme.okta", "a" * 29, "Acme Okta"])
    def test_refuses_bad_shapes(self, raw: str) -> None:
        assert _code(sm.normalize_slug, raw) == sm.CODE_SLUG_INVALID

    def test_twenty_eight_characters_fill_the_provider_column(self) -> None:
        slug = "a" * sm.MAX_SLUG_LENGTH
        assert len(sm.provider_identity_kind(sm.normalize_slug(slug))) == 32

    def test_refuses_an_oauth_provider_id(self) -> None:
        assert _code(sm.normalize_slug, "okta", reserved=["okta", "google"]) == sm.CODE_SLUG_RESERVED

    def test_identity_kind(self) -> None:
        assert sm.provider_identity_kind("acme") == "sso:acme"


class TestDomain:
    @pytest.mark.parametrize(
        "raw,expected",
        [("acme.com", "acme.com"), ("ADA@Acme.COM", "acme.com"), ("eu.acme.co.uk.", "eu.acme.co.uk")],
    )
    def test_accepts(self, raw: str, expected: str) -> None:
        assert sm.normalize_domain(raw) == expected

    @pytest.mark.parametrize("raw", ["", "localhost", "*.acme.com", "acme..com", "-acme.com", "10.0.0.1", "acme com"])
    def test_refuses(self, raw: str) -> None:
        assert _code(sm.normalize_domain, raw) == sm.CODE_DOMAIN_INVALID


# --- OIDC --------------------------------------------------------------------------------------


class TestOidcDiscovery:
    def test_builds_the_stored_config(self) -> None:
        config = sm.oidc_config_from_discovery(ISSUER, DISCOVERY, client_id="apiome")
        assert config["client_id"] == "apiome"
        assert config["jwks_uri"] == DISCOVERY["jwks_uri"]
        assert config["token_endpoint"] == DISCOVERY["token_endpoint"]
        assert config["pkce"] is True
        assert config["scopes"] == ["openid", "email", "profile"]
        assert config["token_endpoint_authentication"] == "client_secret_basic"
        assert "client_secret" not in config

    def test_trailing_slash_does_not_matter(self) -> None:
        sm.oidc_config_from_discovery(ISSUER + "/", {**DISCOVERY, "issuer": ISSUER}, client_id="x")

    def test_refuses_another_issuer(self) -> None:
        doc = {**DISCOVERY, "issuer": "https://evil.example.com"}
        assert _code(sm.oidc_config_from_discovery, ISSUER, doc, client_id="x") == sm.CODE_DISCOVERY_MISMATCH

    @pytest.mark.parametrize("missing", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
    def test_refuses_a_missing_endpoint(self, missing: str) -> None:
        doc = {k: v for k, v in DISCOVERY.items() if k != missing}
        assert _code(sm.oidc_config_from_discovery, ISSUER, doc, client_id="x") == sm.CODE_DISCOVERY_MISMATCH

    def test_refuses_a_plain_http_jwks_uri(self) -> None:
        doc = {**DISCOVERY, "jwks_uri": "http://idp.example.com/certs"}
        assert _code(sm.oidc_config_from_discovery, ISSUER, doc, client_id="x") == sm.CODE_DISCOVERY_MISMATCH

    def test_needs_a_client_id(self) -> None:
        assert _code(sm.oidc_config_from_discovery, ISSUER, DISCOVERY, client_id=" ") == sm.CODE_ENABLE_INCOMPLETE

    def test_discover_fetches_the_well_known_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = {}

        async def fake_fetch(url, **_kw):
            seen["url"] = url
            import json

            return json.dumps(DISCOVERY).encode()

        monkeypatch.setattr(sm, "_fetch_bounded", fake_fetch)
        result = asyncio.run(sm.discover_oidc(ISSUER + "/", client_id="apiome"))
        assert seen["url"] == f"{ISSUER}/.well-known/openid-configuration"
        assert result["issuer"] == ISSUER
        assert result["oidc_config"]["client_id"] == "apiome"

    def test_discover_refuses_a_plain_http_issuer(self) -> None:
        with pytest.raises(SsoConfigError) as caught:
            asyncio.run(sm.discover_oidc("http://idp.example.com", client_id="x"))
        assert caught.value.code == sm.CODE_ISSUER_INVALID

    def test_discover_refuses_non_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_fetch(url, **_kw):
            return b"<html>"

        monkeypatch.setattr(sm, "_fetch_bounded", fake_fetch)
        with pytest.raises(SsoConfigError) as caught:
            asyncio.run(sm.discover_oidc(ISSUER, client_id="x"))
        assert caught.value.code == sm.CODE_DISCOVERY_FAILED


# --- SAML --------------------------------------------------------------------------------------


class TestSamlMetadata:
    def test_extracts_what_the_sp_needs(self) -> None:
        parsed = sm.parse_saml_metadata(
            _metadata(
                ("HTTP-POST", "https://idp.example.com/sso/post"), ("HTTP-Redirect", "https://idp.example.com/sso")
            )
        )
        assert parsed.entity_id == "https://idp.example.com/saml"
        # HTTP-Redirect is chosen over HTTP-POST.
        assert parsed.sso_binding == sm.BINDING_REDIRECT
        assert parsed.sso_url == "https://idp.example.com/sso"
        assert parsed.certificates == [CERT]
        assert parsed.name_id_formats == ["urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"]

    def test_refuses_a_post_only_idp(self) -> None:
        # Better Auth's SP always sends the AuthnRequest over HTTP-Redirect.
        xml = _metadata(("HTTP-Artifact", "https://idp.example.com/art"), ("HTTP-POST", "https://idp.example.com/post"))
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_BINDING_UNSUPPORTED

    def test_refuses_an_artifact_only_idp(self) -> None:
        xml = _metadata(("HTTP-Artifact", "https://idp.example.com/art"), ("SOAP", "https://idp.example.com/soap"))
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_BINDING_UNSUPPORTED

    def test_reads_an_entities_descriptor(self) -> None:
        inner = _metadata(("HTTP-Redirect", "https://idp.example.com/sso")).split("?>", 1)[1]
        wrapped = (
            f'<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata">{inner}</md:EntitiesDescriptor>'
        )
        assert sm.parse_saml_metadata(wrapped).entity_id == "https://idp.example.com/saml"

    def test_refuses_metadata_without_a_signing_certificate(self) -> None:
        xml = _metadata(("HTTP-Redirect", "https://idp.example.com/sso"), cert=False)
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_CERTIFICATE_MISSING

    def test_refuses_an_sp_descriptor(self) -> None:
        xml = _metadata(("HTTP-Redirect", "https://idp.example.com/sso")).replace("IDPSSODescriptor", "SPSSODescriptor")
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_METADATA_INVALID

    def test_refuses_a_plain_http_sso_url(self) -> None:
        xml = _metadata(("HTTP-Redirect", "http://idp.example.com/sso"))
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_METADATA_INVALID

    def test_refuses_a_dtd(self) -> None:
        # The billion-laughs shape: an entity declaration must never be expanded.
        xml = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
        assert _code(sm.parse_saml_metadata, xml) == sm.CODE_METADATA_INVALID

    def test_refuses_garbage_and_empty(self) -> None:
        assert _code(sm.parse_saml_metadata, "not xml") == sm.CODE_METADATA_INVALID
        assert _code(sm.parse_saml_metadata, "   ") == sm.CODE_METADATA_INVALID

    def test_refuses_oversized_metadata(self) -> None:
        assert _code(sm.parse_saml_metadata, "x" * (sm.MAX_METADATA_BYTES + 1)) == sm.CODE_METADATA_TOO_LARGE


class TestSamlConfig:
    def _parsed(self):
        return sm.parse_saml_metadata(_metadata(("HTTP-Redirect", "https://idp.example.com/sso")))

    def test_nameid_email(self) -> None:
        config = sm.saml_config_from_metadata(
            self._parsed(), metadata_url="https://idp.example.com/md", email_source="NameID", email_attribute="ignored"
        )
        assert config["email_source"] == "nameid"
        assert config["email_attribute"] is None
        assert config["idp_entity_id"] == "https://idp.example.com/saml"

    def test_attribute_email_needs_a_name(self) -> None:
        assert (
            _code(
                sm.saml_config_from_metadata,
                self._parsed(),
                metadata_url=None,
                email_source="attribute",
                email_attribute="",
            )
            == sm.CODE_EMAIL_SOURCE_INVALID
        )
        config = sm.saml_config_from_metadata(
            self._parsed(), metadata_url=None, email_source="attribute", email_attribute="mail"
        )
        assert config["email_attribute"] == "mail"

    def test_refuses_an_unknown_email_source(self) -> None:
        assert (
            _code(
                sm.saml_config_from_metadata, self._parsed(), metadata_url=None, email_source="", email_attribute=None
            )
            == sm.CODE_EMAIL_SOURCE_INVALID
        )


def test_fetch_saml_metadata_refuses_plain_http() -> None:
    with pytest.raises(SsoConfigError) as caught:
        asyncio.run(sm.fetch_saml_metadata("http://idp.example.com/md"))
    assert caught.value.code == sm.CODE_METADATA_INVALID


def test_fetch_refuses_a_private_address() -> None:
    # The SSRF guard runs on the request hook: a metadata URL on a loopback address never connects.
    with pytest.raises(SsoConfigError) as caught:
        asyncio.run(sm.fetch_saml_metadata("https://127.0.0.1/md"))
    assert caught.value.code == sm.CODE_METADATA_INVALID
