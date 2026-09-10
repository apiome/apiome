"""Tenant registry credentials — SDK-4.1 (#4495).

The security properties of :mod:`app.sdk_registry_credentials`, which are the ones the acceptance
criteria name: a token is stored **encrypted** and never returned, a log or an error never carries
one, and the credential a publish uses is chosen by the documented precedence. The store layer is
exercised against a patched ``db`` so nothing here needs a database.
"""

from __future__ import annotations

import base64
import json
import logging
from unittest.mock import patch

import pytest

from app.config import settings
from app.envelope_crypto import EnvelopeEncryptionError
from app.sdk_registry_credentials import (
    DEFAULT_REGISTRY_URLS,
    REDACTION_MARKER,
    TOKEN_MAX_CHARS,
    RegistryCredentialError,
    credential_encryption_configured,
    delete_credential,
    describe_token,
    list_credentials,
    normalize_registry_url,
    redact_secrets,
    resolve_credential,
    save_credential,
    validate_registry_credential_keys,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_KEY = base64.b64encode(b"s" * 32).decode()


@pytest.fixture
def configured(monkeypatch):
    """One configured master key, so credentials can be sealed."""
    monkeypatch.setattr(
        settings, "sdk_registry_credential_encryption_keys", json.dumps({"1": _KEY})
    )
    monkeypatch.setattr(settings, "sdk_registry_credential_active_key_version", None)


@pytest.fixture
def unconfigured(monkeypatch):
    """No master key: the deployment cannot store credentials at all."""
    monkeypatch.setattr(settings, "sdk_registry_credential_encryption_keys", None)
    monkeypatch.setattr(settings, "sdk_registry_credential_active_key_version", None)


# --------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ecosystem", ["gomod", "cargo", "", "NPM "])
def test_only_npm_and_pypi_can_hold_a_credential(ecosystem, configured):
    if ecosystem.strip().lower() in {"npm", "pypi"}:
        pytest.skip("case-folded to a publishable ecosystem")
    with pytest.raises(RegistryCredentialError, match="ecosystem must be one of"):
        save_credential(_TENANT, ecosystem=ecosystem, token="npm_abcdefghijkl")


@pytest.mark.parametrize(
    "token, problem",
    [
        ("", "token is required"),
        ("short", "shorter than"),
        ("x" * (TOKEN_MAX_CHARS + 1), "longer than"),
        ("has space in it", "whitespace or control"),
        ("has\nnewline-in-it", "whitespace or control"),
    ],
)
def test_a_token_that_could_not_work_is_refused(token, problem, configured):
    with pytest.raises(RegistryCredentialError, match=problem):
        save_credential(_TENANT, ecosystem="npm", token=token)


def test_the_refusal_never_quotes_the_token(configured):
    secret = "this-token-has spaces and must not be echoed"
    with pytest.raises(RegistryCredentialError) as exc:
        save_credential(_TENANT, ecosystem="npm", token=secret)
    assert secret not in str(exc.value)


def test_a_registry_url_must_be_https():
    with pytest.raises(RegistryCredentialError, match="https"):
        normalize_registry_url("npm", "http://registry.internal/")


def test_an_absent_registry_url_takes_the_public_default():
    assert normalize_registry_url("pypi", None) == DEFAULT_REGISTRY_URLS["pypi"]
    assert normalize_registry_url("npm", "  ") == DEFAULT_REGISTRY_URLS["npm"]


def test_a_private_registry_url_is_accepted_when_it_is_https():
    assert normalize_registry_url("npm", "https://npm.acme.dev/") == "https://npm.acme.dev/"


# --------------------------------------------------------------------------------------------
# Describing without revealing
# --------------------------------------------------------------------------------------------
def test_describe_projects_only_public_facts():
    described = describe_token("npm_abcdefghijklmnop")
    assert described["token_prefix"] == "npm_"
    assert described["token_length"] == len("npm_abcdefghijklmnop")
    assert described["token_fingerprint"].startswith("sha256:")
    # No part of the secret body appears anywhere in the projection.
    assert "abcdefghijklmnop" not in json.dumps(described)


def test_two_tokens_are_distinguishable_by_fingerprint():
    assert (
        describe_token("npm_aaaaaaaaaaaa")["token_fingerprint"]
        != describe_token("npm_bbbbbbbbbbbb")["token_fingerprint"]
    )


def test_an_unrecognised_scheme_reports_no_prefix():
    assert describe_token("opaque-token-value")["token_prefix"] is None


# --------------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------------
def test_a_known_secret_is_replaced_wherever_it_appears():
    text = "registry said: token npm_supersecrettoken is invalid (npm_supersecrettoken)"
    redacted = redact_secrets(text, ["npm_supersecrettoken"])
    assert "npm_supersecrettoken" not in redacted
    assert redacted.count(REDACTION_MARKER) == 2


def test_redaction_ignores_values_too_short_to_be_secrets():
    """Replacing every ``ab`` in a log would destroy it."""
    assert redact_secrets("a table of abbreviations", ["ab"]) == "a table of abbreviations"


def test_redaction_tolerates_empty_input():
    assert redact_secrets("", ["npm_secrettoken"]) == ""


# --------------------------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------------------------
def test_a_stored_credential_is_ciphertext_and_its_metadata(configured):
    captured = {}

    def _upsert(**kwargs):
        captured.update(kwargs)
        return {
            "id": "33333333-3333-4333-8333-333333333333",
            "tenant_id": _TENANT,
            "project_id": None,
            "ecosystem": kwargs["ecosystem"],
            "registry_url": kwargs["registry_url"],
            "encrypted_token": kwargs["encrypted_token"],
            "key_version": kwargs["key_version"],
            "token_metadata": kwargs["token_metadata"],
        }

    with patch("app.sdk_registry_credentials.db.upsert_sdk_registry_credential", _upsert):
        out = save_credential(_TENANT, ecosystem="npm", token="npm_supersecrettoken")

    # What reached the database is ciphertext, and the plaintext is nowhere in the row.
    assert b"npm_supersecrettoken" not in captured["encrypted_token"]
    assert captured["key_version"] == 1
    assert "npm_supersecrettoken" not in json.dumps(captured["token_metadata"])
    # And what comes back describes the token without carrying it.
    assert out.token_prefix == "npm_"
    assert out.readable is True
    assert "npm_supersecrettoken" not in out.model_dump_json()


def test_a_pasted_token_loses_its_trailing_newline(configured):
    seen = {}

    def _upsert(**kwargs):
        seen.update(kwargs)
        return {"id": "x", "ecosystem": "npm", "registry_url": "u", "token_metadata": {}}

    with patch("app.sdk_registry_credentials.db.upsert_sdk_registry_credential", _upsert):
        save_credential(_TENANT, ecosystem="npm", token="  npm_abcdefghijkl\n")
    assert seen["token_metadata"]["token_length"] == len("npm_abcdefghijkl")


def test_storing_without_an_encryption_key_fails_closed(unconfigured):
    """A token that cannot be sealed must never be written in the clear."""
    with patch("app.sdk_registry_credentials.db.upsert_sdk_registry_credential") as upsert:
        with pytest.raises(EnvelopeEncryptionError, match="not configured"):
            save_credential(_TENANT, ecosystem="npm", token="npm_abcdefghijkl")
    upsert.assert_not_called()


def test_encryption_configured_reports_the_deployment_state(configured, monkeypatch):
    assert credential_encryption_configured() is True
    monkeypatch.setattr(settings, "sdk_registry_credential_encryption_keys", None)
    assert credential_encryption_configured() is False


def test_startup_validation_accepts_no_keys_but_rejects_broken_ones(monkeypatch, unconfigured):
    validate_registry_credential_keys()
    monkeypatch.setattr(settings, "sdk_registry_credential_encryption_keys", "not json")
    with pytest.raises(EnvelopeEncryptionError):
        validate_registry_credential_keys()


def test_deleting_names_the_exact_scope(configured):
    with patch(
        "app.sdk_registry_credentials.db.delete_sdk_registry_credential", return_value=1
    ) as delete:
        assert delete_credential(_TENANT, ecosystem="npm", project_id=_PROJECT) is True
    delete.assert_called_once_with(_TENANT, "npm", _PROJECT)


def test_listing_never_returns_a_token(configured):
    blob, version = _seal("npm_supersecrettoken")
    rows = [
        {
            "id": "row-1",
            "project_id": None,
            "ecosystem": "npm",
            "registry_url": DEFAULT_REGISTRY_URLS["npm"],
            "encrypted_token": blob,
            "key_version": version,
            "token_metadata": describe_token("npm_supersecrettoken"),
        }
    ]
    with patch("app.sdk_registry_credentials.db.get_sdk_registry_credentials", return_value=rows):
        listed = list_credentials(_TENANT)
    assert len(listed) == 1
    assert listed[0].readable is True
    assert "npm_supersecrettoken" not in listed[0].model_dump_json()


def test_listing_marks_a_row_whose_key_is_gone_as_unreadable(configured, monkeypatch):
    blob, version = _seal("npm_supersecrettoken")
    monkeypatch.setattr(
        settings,
        "sdk_registry_credential_encryption_keys",
        json.dumps({"1": base64.b64encode(b"z" * 32).decode()}),
    )
    rows = [{"id": "row-1", "ecosystem": "npm", "registry_url": "u", "encrypted_token": blob,
             "key_version": version, "token_metadata": {}}]
    with patch("app.sdk_registry_credentials.db.get_sdk_registry_credentials", return_value=rows):
        listed = list_credentials(_TENANT)
    assert listed[0].readable is False


def test_a_store_failure_lists_nothing_rather_than_raising(configured):
    with patch(
        "app.sdk_registry_credentials.db.get_sdk_registry_credentials",
        side_effect=RuntimeError("db down"),
    ):
        assert list_credentials(_TENANT) == []


# --------------------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------------------
def _seal(token: str):
    """Seal a token the way the store does, for a fixture row."""
    from app.sdk_registry_credentials import _CIPHER

    return _CIPHER.seal({"token": token})


def _row(token: str, *, project_id=None, url="https://registry.npmjs.org"):
    """A stored credential row holding ``token``."""
    blob, version = _seal(token)
    return {
        "id": f"row-{project_id or 'tenant'}",
        "project_id": project_id,
        "ecosystem": "npm",
        "registry_url": url,
        "encrypted_token": blob,
        "key_version": version,
        "token_metadata": describe_token(token),
    }


def test_a_project_credential_replaces_the_tenant_one(configured):
    rows = [_row("npm_tenanttokenvalue"), _row("npm_projecttokenvalue", project_id=_PROJECT)]
    with patch("app.sdk_registry_credentials.db.get_sdk_registry_credentials", return_value=rows):
        resolved = resolve_credential(_TENANT, ecosystem="npm", project_id=_PROJECT)
    assert resolved.token == "npm_projecttokenvalue"
    assert resolved.scope == "project"


def test_the_tenant_credential_is_used_when_a_project_has_none(configured):
    with patch(
        "app.sdk_registry_credentials.db.get_sdk_registry_credentials",
        return_value=[_row("npm_tenanttokenvalue")],
    ):
        resolved = resolve_credential(_TENANT, ecosystem="npm", project_id=_PROJECT)
    assert resolved.token == "npm_tenanttokenvalue"
    assert resolved.scope == "tenant"


def test_a_project_row_that_cannot_be_opened_falls_through_to_the_tenant(configured, caplog):
    """A tenant token that still opens beats a project token nobody can read."""
    broken = _row("npm_projecttokenvalue", project_id=_PROJECT)
    broken["encrypted_token"] = b"OSRV\x01" + b"0" * 120  # right magic, wrong contents
    rows = [_row("npm_tenanttokenvalue"), broken]
    with caplog.at_level(logging.WARNING):
        with patch(
            "app.sdk_registry_credentials.db.get_sdk_registry_credentials", return_value=rows
        ):
            resolved = resolve_credential(_TENANT, ecosystem="npm", project_id=_PROJECT)
    assert resolved.scope == "tenant"
    assert "npm_tenanttokenvalue" not in caplog.text


def test_no_stored_credential_resolves_to_none(configured):
    with patch("app.sdk_registry_credentials.db.get_sdk_registry_credentials", return_value=[]):
        assert resolve_credential(_TENANT, ecosystem="npm", project_id=_PROJECT) is None


def test_a_store_failure_resolves_to_none_rather_than_publishing_unauthenticated(configured):
    with patch(
        "app.sdk_registry_credentials.db.get_sdk_registry_credentials",
        side_effect=RuntimeError("db down"),
    ):
        assert resolve_credential(_TENANT, ecosystem="npm") is None


def test_resolving_an_unpublishable_ecosystem_is_refused(configured):
    with pytest.raises(RegistryCredentialError, match="ecosystem must be one of"):
        resolve_credential(_TENANT, ecosystem="gomod")
