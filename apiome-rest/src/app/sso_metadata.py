"""What an SSO provider is, and how its IdP's published metadata is read — EID-1.1 (#5011).

A workspace's own identity provider is registered by an installation admin (the admin console,
:mod:`app.sso_provider_routes`) and signed in through Better Auth's SSO plugin in apiome-ui. This
module is the pure half of that registration: no database, no session. It

* validates the identifiers an admin types — the provider **slug** (``sso:<slug>`` must fit the
  ``VARCHAR(32)`` provider columns of ``auth_events`` / ``oauth_signup_pending``, so it is capped at
  28 characters) and email **domains**;
* fetches and checks an **OIDC discovery document** — the issuer must match, and the endpoints the
  sign-in needs (authorize, token, JWKS) must be HTTPS;
* parses **SAML 2.0 IdP metadata** with ``defusedxml`` (no entity expansion, no external entities)
  and extracts the entity id, the single sign-on URL and binding, and the signing certificates. An
  IdP that does not offer the binding the SP sends requests over (HTTP-Redirect) — an HTTP-POST,
  HTTP-Artifact or SOAP-only IdP — is refused with
  ``sso-binding-unsupported`` rather than silently downgraded.

Every refusal is an :class:`SsoConfigError` carrying a stable ``sso-*`` code, which the routes
return as a ``422`` body ``{"error": code, "message": ...}``.

Every outbound fetch goes through :func:`app.ssrf_guard.build_guarded_async_client`, so a
discovery or metadata URL cannot reach a private address — on any hop of a redirect chain.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .ssrf_guard import SSRFError, build_guarded_async_client

# ---------------------------------------------------------------------------
# Stable error codes
# ---------------------------------------------------------------------------

CODE_SLUG_INVALID = "sso-slug-invalid"
CODE_SLUG_RESERVED = "sso-slug-reserved"
CODE_SLUG_TAKEN = "sso-slug-taken"
CODE_DOMAIN_INVALID = "sso-domain-invalid"
CODE_DOMAIN_CLAIMED = "sso-domain-claimed"
CODE_ISSUER_INVALID = "sso-issuer-invalid"
CODE_DISCOVERY_FAILED = "sso-discovery-failed"
CODE_DISCOVERY_MISMATCH = "sso-discovery-mismatch"
CODE_METADATA_INVALID = "sso-metadata-invalid"
CODE_METADATA_TOO_LARGE = "sso-metadata-too-large"
CODE_BINDING_UNSUPPORTED = "sso-binding-unsupported"
CODE_CERTIFICATE_MISSING = "sso-certificate-missing"
CODE_EMAIL_SOURCE_INVALID = "sso-email-source-invalid"
CODE_ENABLE_INCOMPLETE = "sso-enable-incomplete"

#: The longest slug: ``sso:`` + 28 characters fills a ``VARCHAR(32)`` provider column.
MAX_SLUG_LENGTH = 28

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,27}$")
_DOMAIN_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_RE = re.compile(rf"^{_DOMAIN_LABEL}(?:\.{_DOMAIN_LABEL})+$")

#: Discovery documents and IdP metadata are small; anything larger is refused before parsing.
MAX_DISCOVERY_BYTES = 100 * 1024
MAX_METADATA_BYTES = 100 * 1024
FETCH_TIMEOUT_SECONDS = 10.0

PROTOCOL_OIDC = "oidc"
PROTOCOL_SAML = "saml"
PROTOCOLS = (PROTOCOL_OIDC, PROTOCOL_SAML)

EMAIL_SOURCE_NAMEID = "nameid"
EMAIL_SOURCE_ATTRIBUTE = "attribute"
EMAIL_SOURCES = (EMAIL_SOURCE_NAMEID, EMAIL_SOURCE_ATTRIBUTE)

BINDING_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
BINDING_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
#: The bindings Better Auth's SAML SP can send an AuthnRequest over. `@better-auth/sso` always
#: builds the request with ``createLoginRequest(idp, "redirect")``, so an IdP must offer
#: HTTP-Redirect; an HTTP-POST-only (or Artifact/SOAP-only) IdP could never be signed in to.
SUPPORTED_SSO_BINDINGS = (BINDING_REDIRECT,)

_MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"


class SsoConfigError(ValueError):
    """A provider registration was refused, with a stable ``sso-*`` code.

    Attributes:
        code: The stable error code (``CODE_*``).
        message: A human-readable explanation, safe to show an admin (never carries a secret).
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def body(self) -> Dict[str, str]:
        """The ``422`` response body for this refusal."""
        return {"error": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def normalize_slug(raw: Any, *, reserved: Sequence[str] = ()) -> str:
    """Validate a provider slug.

    Args:
        raw: The slug as typed.
        reserved: Slugs that may not be used — the installation OAuth provider ids, so that
            ``sso:okta`` can never be mistaken for the ``okta`` OAuth provider in an audit trail.

    Returns:
        The slug, trimmed and lower-cased.

    Raises:
        SsoConfigError: ``sso-slug-invalid`` for a bad shape; ``sso-slug-reserved`` for a reserved id.
    """
    slug = str(raw or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise SsoConfigError(
            CODE_SLUG_INVALID,
            "Use 2–28 lower-case letters, digits and hyphens, starting with a letter or digit.",
        )
    if slug in set(reserved):
        raise SsoConfigError(
            CODE_SLUG_RESERVED,
            f"“{slug}” is the id of a built-in sign-in provider; choose another, e.g. “{slug}-sso”.",
        )
    return slug


def normalize_domain(raw: Any) -> str:
    """Validate an email domain an SSO provider will sign in.

    Accepts an address (``ada@acme.com``) or a bare domain, and returns the lower-cased domain.
    Wildcards, IP literals and single-label names are refused.

    Args:
        raw: The domain or address as typed.

    Returns:
        The lower-cased domain, without a trailing dot.

    Raises:
        SsoConfigError: ``sso-domain-invalid``.
    """
    value = str(raw or "").strip().lower()
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    value = value.rstrip(".")
    # The top-level label must hold a letter: that refuses IPv4 literals (``10.0.0.1``), which the
    # label grammar alone would accept.
    if len(value) > 253 or not _DOMAIN_RE.match(value) or not re.search(r"[a-z]", value.rsplit(".", 1)[-1]):
        raise SsoConfigError(CODE_DOMAIN_INVALID, f"“{raw}” is not an email domain such as acme.com.")
    return value


def provider_identity_kind(slug: str) -> str:
    """The identity kind an SSO provider's users carry: ``sso:<slug>``.

    This is the value written to ``external_auth_providers.provider`` and ``auth_events.provider``.

    Args:
        slug: A validated provider slug.

    Returns:
        ``sso:<slug>``.
    """
    return f"sso:{slug}"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _require_https(url: str, code: str, what: str) -> str:
    """Return ``url`` when it is an absolute HTTPS URL with a host, else refuse with ``code``."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SsoConfigError(code, f"{what} must be an https:// URL (got “{url}”).")
    return parsed.geturl()


async def _fetch_bounded(url: str, *, limit: int, code: str, too_large_code: str) -> bytes:
    """GET ``url`` through the SSRF guard, refusing a body over ``limit`` bytes.

    Args:
        url: An HTTPS URL.
        limit: The largest acceptable body, in bytes.
        code: The code for a failed fetch (unreachable, non-2xx, blocked by the SSRF guard).
        too_large_code: The code for an oversized body.

    Returns:
        The response body.

    Raises:
        SsoConfigError: On any failure; the message names the URL, never a credential.
    """
    try:
        async with build_guarded_async_client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            async with client.stream(
                "GET", url, headers={"Accept": "application/json, application/xml, text/xml"}
            ) as response:
                if response.status_code >= 400:
                    raise SsoConfigError(code, f"{url} answered HTTP {response.status_code}.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise SsoConfigError(too_large_code, f"{url} returned more than {limit // 1024} KB.")
                return bytes(body)
    except SsoConfigError:
        raise
    except SSRFError as exc:
        raise SsoConfigError(code, f"{url} cannot be fetched: {exc}") from exc
    except httpx.HTTPError as exc:
        raise SsoConfigError(code, f"Could not reach {url}.") from exc


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------


def _strip_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def oidc_config_from_discovery(issuer: str, document: Dict[str, Any], *, client_id: str) -> Dict[str, Any]:
    """Check a discovery document against its issuer and build the stored OIDC config.

    Args:
        issuer: The issuer the admin registered (HTTPS).
        document: The parsed ``/.well-known/openid-configuration``.
        client_id: The OAuth client id registered at the IdP.

    Returns:
        The non-secret ``oidc_config`` JSONB: client id, the discovery-hydrated endpoints, scopes,
        PKCE and token-endpoint authentication method.

    Raises:
        SsoConfigError: ``sso-discovery-mismatch`` when the document names another issuer or lacks
            an HTTPS authorize / token / JWKS endpoint.
    """
    if not isinstance(document, dict):
        raise SsoConfigError(CODE_DISCOVERY_FAILED, "The discovery document is not a JSON object.")
    published = str(document.get("issuer") or "")
    if _strip_slash(published) != _strip_slash(issuer):
        raise SsoConfigError(
            CODE_DISCOVERY_MISMATCH,
            f"The discovery document names issuer “{published}”, not “{issuer}”.",
        )
    endpoints: Dict[str, str] = {}
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(key)
        if not value:
            raise SsoConfigError(CODE_DISCOVERY_MISMATCH, f"The discovery document has no {key}.")
        endpoints[key] = _require_https(value, CODE_DISCOVERY_MISMATCH, key)
    userinfo = document.get("userinfo_endpoint")
    auth_methods = document.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    token_auth = (
        "client_secret_basic"
        if "client_secret_basic" in auth_methods
        else "client_secret_post"
        if "client_secret_post" in auth_methods
        else "client_secret_basic"
    )
    client = str(client_id or "").strip()
    if not client:
        raise SsoConfigError(CODE_ENABLE_INCOMPLETE, "An OIDC provider needs the client id the IdP issued.")
    return {
        "client_id": client,
        "discovery_endpoint": f"{_strip_slash(issuer)}/.well-known/openid-configuration",
        "authorization_endpoint": endpoints["authorization_endpoint"],
        "token_endpoint": endpoints["token_endpoint"],
        "jwks_uri": endpoints["jwks_uri"],
        "userinfo_endpoint": _require_https(userinfo, CODE_DISCOVERY_MISMATCH, "userinfo_endpoint")
        if userinfo
        else None,
        "scopes": ["openid", "email", "profile"],
        "pkce": True,
        "token_endpoint_authentication": token_auth,
    }


async def discover_oidc(issuer: str, *, client_id: str) -> Dict[str, Any]:
    """Fetch an issuer's discovery document and build the stored OIDC config.

    Args:
        issuer: The issuer URL the admin typed.
        client_id: The OAuth client id registered at the IdP.

    Returns:
        ``{"issuer": <normalized issuer>, "oidc_config": {...}}``.

    Raises:
        SsoConfigError: ``sso-issuer-invalid``, ``sso-discovery-failed`` or ``sso-discovery-mismatch``.
    """
    normalized = _strip_slash(_require_https(issuer, CODE_ISSUER_INVALID, "The issuer"))
    url = f"{normalized}/.well-known/openid-configuration"
    raw = await _fetch_bounded(
        url, limit=MAX_DISCOVERY_BYTES, code=CODE_DISCOVERY_FAILED, too_large_code=CODE_DISCOVERY_FAILED
    )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SsoConfigError(CODE_DISCOVERY_FAILED, f"{url} did not return JSON.") from exc
    return {"issuer": normalized, "oidc_config": oidc_config_from_discovery(normalized, document, client_id=client_id)}


# ---------------------------------------------------------------------------
# SAML
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SamlIdpMetadata:
    """What the SP needs from an IdP's SAML 2.0 metadata.

    Attributes:
        entity_id: The IdP's ``entityID`` — the assertion ``Issuer`` the SP will require.
        sso_url: The ``SingleSignOnService`` location the AuthnRequest goes to.
        sso_binding: The binding of that location (always HTTP-Redirect today).
        certificates: Base64 DER signing certificates (whitespace removed), at least one.
        name_id_formats: The ``NameIDFormat`` values the IdP advertises, for display.
    """

    entity_id: str
    sso_url: str
    sso_binding: str
    certificates: List[str] = field(default_factory=list)
    name_id_formats: List[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_saml_metadata(xml: Any) -> SamlIdpMetadata:
    """Parse SAML 2.0 IdP metadata safely.

    Accepts an ``EntityDescriptor``, or an ``EntitiesDescriptor`` holding exactly the IdP (the
    first descriptor with an ``IDPSSODescriptor`` is used).

    Args:
        xml: The metadata document, as text or bytes.

    Returns:
        The extracted :class:`SamlIdpMetadata`.

    Raises:
        SsoConfigError: ``sso-metadata-too-large``, ``sso-metadata-invalid`` (not XML, unsafe XML,
            no IdP descriptor, no entity id or SSO location), ``sso-binding-unsupported`` (only
            Artifact/SOAP bindings), or ``sso-certificate-missing``.
    """
    data = xml.encode("utf-8") if isinstance(xml, str) else bytes(xml or b"")
    if len(data) > MAX_METADATA_BYTES:
        raise SsoConfigError(CODE_METADATA_TOO_LARGE, f"The metadata is larger than {MAX_METADATA_BYTES // 1024} KB.")
    if not data.strip():
        raise SsoConfigError(CODE_METADATA_INVALID, "The metadata is empty.")
    try:
        root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise SsoConfigError(
            CODE_METADATA_INVALID, "The metadata uses XML features that are not allowed (DTD or entities)."
        ) from exc
    except SafeET.ParseError as exc:
        raise SsoConfigError(CODE_METADATA_INVALID, "The metadata is not well-formed XML.") from exc

    candidates = [root] if _local(root.tag) == "EntityDescriptor" else list(root.iter(f"{{{_MD_NS}}}EntityDescriptor"))
    entity = None
    idp = None
    for candidate in candidates:
        found = candidate.find(f"{{{_MD_NS}}}IDPSSODescriptor")
        if found is not None:
            entity, idp = candidate, found
            break
    if entity is None or idp is None:
        raise SsoConfigError(CODE_METADATA_INVALID, "The metadata has no IdP descriptor (IDPSSODescriptor).")

    entity_id = (entity.get("entityID") or "").strip()
    if not entity_id:
        raise SsoConfigError(CODE_METADATA_INVALID, "The IdP descriptor has no entityID.")

    services = [
        ((svc.get("Binding") or "").strip(), (svc.get("Location") or "").strip())
        for svc in idp.findall(f"{{{_MD_NS}}}SingleSignOnService")
    ]
    if not services:
        raise SsoConfigError(CODE_METADATA_INVALID, "The IdP descriptor has no SingleSignOnService.")
    chosen = None
    for binding in SUPPORTED_SSO_BINDINGS:
        chosen = next(((b, loc) for b, loc in services if b == binding and loc), None)
        if chosen:
            break
    if chosen is None:
        offered = ", ".join(sorted({b.rsplit(":", 1)[-1] for b, _ in services if b})) or "none"
        raise SsoConfigError(
            CODE_BINDING_UNSUPPORTED,
            f"The IdP offers single sign-on only over {offered}; Apiome sends sign-in requests over HTTP-Redirect.",
        )
    sso_binding, sso_url = chosen
    _require_https(sso_url, CODE_METADATA_INVALID, "The single sign-on URL")

    certificates: List[str] = []
    for key in idp.findall(f"{{{_MD_NS}}}KeyDescriptor"):
        use = (key.get("use") or "signing").strip()
        if use != "signing":
            continue
        for cert in key.iter(f"{{{_DS_NS}}}X509Certificate"):
            text = "".join((cert.text or "").split())
            if text and text not in certificates:
                certificates.append(text)
    if not certificates:
        raise SsoConfigError(CODE_CERTIFICATE_MISSING, "The IdP metadata publishes no signing certificate.")

    formats = [(fmt.text or "").strip() for fmt in idp.findall(f"{{{_MD_NS}}}NameIDFormat") if (fmt.text or "").strip()]
    return SamlIdpMetadata(
        entity_id=entity_id,
        sso_url=sso_url,
        sso_binding=sso_binding,
        certificates=certificates,
        name_id_formats=formats,
    )


async def fetch_saml_metadata(url: str) -> SamlIdpMetadata:
    """Fetch IdP metadata over HTTPS (through the SSRF guard) and parse it.

    Args:
        url: The metadata URL the admin typed.

    Returns:
        The parsed metadata.

    Raises:
        SsoConfigError: As :func:`parse_saml_metadata`, plus ``sso-metadata-invalid`` for a bad
            URL or a failed fetch.
    """
    checked = _require_https(url, CODE_METADATA_INVALID, "The metadata URL")
    raw = await _fetch_bounded(
        checked, limit=MAX_METADATA_BYTES, code=CODE_METADATA_INVALID, too_large_code=CODE_METADATA_TOO_LARGE
    )
    return parse_saml_metadata(raw)


def saml_config_from_metadata(
    metadata: SamlIdpMetadata,
    *,
    metadata_url: Optional[str],
    email_source: str,
    email_attribute: Optional[str],
) -> Dict[str, Any]:
    """Build the stored, non-secret ``saml_config`` JSONB.

    The roadmap's email rule: a SAML identity's email comes from an email-format NameID or from a
    named attribute, and the provider row records which, so the resolution engine's "one verified
    email = one user" invariant has one source per provider.

    Args:
        metadata: The parsed IdP metadata.
        metadata_url: Where it came from, when fetched (kept for a later refresh).
        email_source: ``nameid`` or ``attribute``.
        email_attribute: The attribute name, required when ``email_source`` is ``attribute``.

    Returns:
        The ``saml_config`` dict.

    Raises:
        SsoConfigError: ``sso-email-source-invalid``.
    """
    source = str(email_source or "").strip().lower()
    if source not in EMAIL_SOURCES:
        raise SsoConfigError(
            CODE_EMAIL_SOURCE_INVALID, "Choose where the email comes from: the NameID or an attribute."
        )
    attribute = str(email_attribute or "").strip() or None
    if source == EMAIL_SOURCE_ATTRIBUTE and not attribute:
        raise SsoConfigError(CODE_EMAIL_SOURCE_INVALID, "Name the attribute that carries the email address.")
    return {
        "idp_entity_id": metadata.entity_id,
        "sso_url": metadata.sso_url,
        "sso_binding": metadata.sso_binding,
        "certificates": list(metadata.certificates),
        "name_id_formats": list(metadata.name_id_formats),
        "metadata_url": metadata_url,
        "email_source": source,
        "email_attribute": attribute if source == EMAIL_SOURCE_ATTRIBUTE else None,
    }
