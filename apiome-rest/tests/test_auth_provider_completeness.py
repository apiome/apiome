"""Required-field completeness beyond client id/secret (OLO-9.1, #4984).

OLO-9.1 lets a provider require fields past ``client_id`` / ``client_secret`` — notably an OIDC
``issuer``/``domain`` URL stored in the ``config`` JSONB. These tests exercise the completeness
machinery (:mod:`app.auth_provider_config_routes`) against a representative issuer-based provider
(the Okta/Auth0/OIDC shape of OLO-9.3–9.7), injected directly so the capability is covered without
shipping a half-built provider entry in the real registry:

* :func:`_missing_required_fields` names the issuer until a non-blank value is stored in ``config``;
* the masked view's ``missing_for_enable`` / ``can_enable`` reflect the issuer requirement;
* the enable-time guard blocks enabling with a structured ``422`` naming the missing issuer, and a
  ``config``-supplied issuer clears the block — matching classic client_id/secret behaviour.
"""

import pytest
from fastapi import HTTPException

from app.auth_provider_config_routes import (
    _guard_enable_completeness,
    _missing_required_fields,
    _provider_view,
)
from app.auth_provider_registry import (
    FIELD_KIND_CONFIG,
    STATUS_AVAILABLE,
    ProviderDescriptor,
    RequiredField,
    client_credential_fields,
)

# A representative issuer-based provider: the standard credential pair plus a config-kind issuer.
ISSUER_PROVIDER = ProviderDescriptor(
    "okta",
    "Okta",
    STATUS_AVAILABLE,
    client_credential_fields("OKTA_CLIENT_ID", "OKTA_CLIENT_SECRET")
    + (RequiredField("issuer", FIELD_KIND_CONFIG, "OKTA_ISSUER"),),
)

_ISSUER = "https://example.okta.com"


def test_missing_required_fields_names_issuer_until_stored():
    """The issuer is missing until a non-blank config value is stored under its env key."""
    # Creds present, issuer absent ⇒ only the issuer is missing.
    assert _missing_required_fields(
        ISSUER_PROVIDER, client_id="id", secret_set=True, config={}
    ) == ["issuer"]
    # A blank config value counts as absent (fallback, not set).
    assert _missing_required_fields(
        ISSUER_PROVIDER, client_id="id", secret_set=True, config={"OKTA_ISSUER": "   "}
    ) == ["issuer"]
    # All three present ⇒ nothing missing.
    assert (
        _missing_required_fields(
            ISSUER_PROVIDER, client_id="id", secret_set=True, config={"OKTA_ISSUER": _ISSUER}
        )
        == []
    )
    # Creds also missing ⇒ reported in field order alongside the issuer.
    assert _missing_required_fields(
        ISSUER_PROVIDER, client_id=None, secret_set=False, config={}
    ) == ["client_id", "client_secret", "issuer"]


def test_provider_view_surfaces_issuer_completeness():
    """The masked view lists the issuer in required_fields and blocks enable until it is stored."""
    incomplete = _provider_view(
        ISSUER_PROVIDER,
        {"client_id": "id", "enc_key_id": "k1", "config": {}},
    )
    assert incomplete.required_fields == ["client_id", "client_secret", "issuer"]
    assert incomplete.missing_for_enable == ["issuer"]
    assert incomplete.can_enable is False

    complete = _provider_view(
        ISSUER_PROVIDER,
        {"client_id": "id", "enc_key_id": "k1", "config": {"OKTA_ISSUER": _ISSUER}},
    )
    assert complete.missing_for_enable == []
    assert complete.can_enable is True


def test_enable_guard_blocks_until_issuer_present():
    """Enabling without a stored issuer raises a 422 naming it; a config issuer clears the block."""
    existing = {"client_id": "id", "enc_key_id": "k1", "config": {}}

    with pytest.raises(HTTPException) as exc:
        _guard_enable_completeness(ISSUER_PROVIDER, existing, {"enabled": True})
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "provider_incomplete"
    assert exc.value.detail["missing_fields"] == ["issuer"]

    # Supplying the issuer via the same write's config update satisfies the requirement.
    _guard_enable_completeness(
        ISSUER_PROVIDER,
        existing,
        {"enabled": True, "config": {"OKTA_ISSUER": _ISSUER}},
    )

    # An already-stored config issuer also satisfies it, with only enabled flipping.
    _guard_enable_completeness(
        ISSUER_PROVIDER,
        {"client_id": "id", "enc_key_id": "k1", "config": {"OKTA_ISSUER": _ISSUER}},
        {"enabled": True},
    )
