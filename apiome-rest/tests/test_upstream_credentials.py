"""The upstream auth vault — AGX-2.2 (#4534).

The store is the in-memory :class:`~upstream_credential_fakes.FakeUpstreamStore` and encryption
uses a throwaway master key, so these tests run without a database. They pin the vault's
promises:

* a secret is validated, sealed under the vault's own magic, and never stored or reported in
  the clear, and no refusal message quotes it;
* one credential per (tenant, toolset, server URL), scoped by tenant everywhere;
* rotation replaces the secret in place, with no window in which a concurrent resolve finds
  nothing, and an invocation already holding the old secret keeps it;
* a secret is only opened for a request its server URL binds, the most specific binding wins,
  and a bound credential that won't open fails closed;
* every open is audited as metadata only, best-effort.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from typing import Any, Dict

import pytest
from upstream_credential_fakes import FakeUpstreamStore

from app import upstream_credentials as vault
from app.config import settings
from app.database import db
from app.envelope_crypto import EnvelopeEncryptionError
from app.mcp_credential_crypto import unseal_credential_payload
from app.upstream_credentials import (
    CODE_CREDENTIAL_EXISTS,
    CODE_CREDENTIAL_INVALID,
    CODE_CREDENTIAL_NOT_FOUND,
    SECRET_MAX_CHARS,
    USE_OUTCOME_INJECTED,
    USE_OUTCOME_UNAVAILABLE,
    UpstreamCredentialCreate,
    UpstreamCredentialError,
    UpstreamCredentialRotate,
    UpstreamCredentialUnavailableError,
    UpstreamSecretInput,
    create_credential,
    credential_encryption_configured,
    delete_credential,
    list_credentials,
    resolve_injection,
    rotate_credential,
    validate_secret,
    validate_upstream_credential_keys,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_TOOLSET = "22222222-2222-4222-8222-222222222222"
_OTHER_TOOLSET = "88888888-8888-4888-8888-888888888888"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_SECRET = "sk_live_TOPSECRET_value_123"
_ROTATED = "sk_live_ROTATED_value_456"


def _key() -> str:
    """A fresh base64 AES-256 master key."""
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def keys(monkeypatch):
    """Configure one upstream-vault master key (version 1); returns the key map."""
    key_map = {"1": _key()}
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps(key_map))
    monkeypatch.setattr(settings, "upstream_credential_active_key_version", None)
    return key_map


@pytest.fixture
def store(monkeypatch, keys) -> FakeUpstreamStore:
    """Swap the vault's accessors for the in-memory store."""
    return FakeUpstreamStore().install(monkeypatch, db)


def _create_body(**overrides: Any) -> UpstreamCredentialCreate:
    """An apiKey-in-header create request, with overrides."""
    data: Dict[str, Any] = {
        "serverUrl": "https://api.example.com/v1",
        "kind": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "secret": {"value": _SECRET},
    }
    data.update(overrides)
    return UpstreamCredentialCreate.model_validate(data)


def _rotate_body(**secret: str) -> UpstreamCredentialRotate:
    """A rotate request carrying ``secret``."""
    return UpstreamCredentialRotate.model_validate({"secret": secret})


def _secret(**fields: str) -> UpstreamSecretInput:
    """A secret input from plain strings."""
    return UpstreamSecretInput.model_validate(fields)


# ============================================================================
# Configuration
# ============================================================================
def test_unconfigured_vault_starts_but_reports_it(monkeypatch):
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    validate_upstream_credential_keys()  # no keys is a supported state
    assert credential_encryption_configured() is False


def test_a_malformed_key_map_fails_at_startup(monkeypatch):
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", '{"1": "short"}')
    with pytest.raises(EnvelopeEncryptionError) as caught:
        validate_upstream_credential_keys()
    assert "short" not in str(caught.value)


def test_configured_vault_reports_it(keys):
    assert credential_encryption_configured() is True


# ============================================================================
# validate_secret
# ============================================================================
@pytest.mark.parametrize(
    ("kind", "fields", "expected"),
    [
        ("apiKey", {"value": f"  {_SECRET}\n"}, {"value": _SECRET}),
        ("bearer", {"token": f"{_SECRET}\n"}, {"token": _SECRET}),
        ("basic", {"username": "svc", "password": " p w "}, {"username": "svc", "password": " p w "}),
        ("basic", {"username": "sk_key_as_user", "password": ""}, {"username": "sk_key_as_user", "password": ""}),
    ],
)
def test_validate_secret_returns_the_payload_to_seal(kind, fields, expected):
    assert validate_secret(kind, _secret(**fields)) == expected


@pytest.mark.parametrize(
    ("kind", "fields", "problem"),
    [
        ("apiKey", {}, "secret.value is required"),
        ("apiKey", {"value": "   "}, "secret.value must not be empty"),
        ("apiKey", {"value": _SECRET, "token": _SECRET}, "secret.token does not apply"),
        ("apiKey", {"value": "a" * (SECRET_MAX_CHARS + 1)}, "longer than"),
        ("apiKey", {"value": f"{_SECRET}\r\nX-Evil: 1"}, "control characters"),
        ("bearer", {"token": f"{_SECRET} extra"}, "must not contain whitespace"),
        ("bearer", {"value": _SECRET}, "secret.token is required"),
        ("basic", {"username": "svc"}, "secret.password is required"),
        ("basic", {"username": "s:vc", "password": _SECRET}, "must not contain ':'"),
        ("basic", {"username": "", "password": _SECRET}, "secret.username must not be empty"),
        ("basic", {"username": "u" * 257, "password": _SECRET}, "longer than 256"),
        ("basic", {"username": "svc", "password": f"{_SECRET}\n"}, "control characters"),
    ],
)
def test_validate_secret_refuses_without_quoting_the_secret(kind, fields, problem):
    with pytest.raises(UpstreamCredentialError) as caught:
        validate_secret(kind, _secret(**fields))
    assert caught.value.code == CODE_CREDENTIAL_INVALID
    assert any(problem in error for error in caught.value.errors)
    assert _SECRET not in str(caught.value)


@pytest.mark.parametrize(
    ("kind", "fields", "api_key_in", "accepted"),
    [
        # Sent in a header: must be printable ASCII.
        ("bearer", {"token": "tökén-value"}, None, False),
        ("apiKey", {"value": "ключ-значение"}, "header", False),
        ("apiKey", {"value": "key with spaces"}, "header", True),
        # Percent-encoded or base64-encoded on the wire: any UTF-8.
        ("apiKey", {"value": "ключ-значение"}, "query", True),
        ("basic", {"username": "üser", "password": "päss wörd"}, None, True),
    ],
)
def test_a_secret_sent_in_a_header_must_be_printable_ascii(kind, fields, api_key_in, accepted):
    if accepted:
        assert validate_secret(kind, _secret(**fields), api_key_in=api_key_in)
        return
    with pytest.raises(UpstreamCredentialError) as caught:
        validate_secret(kind, _secret(**fields), api_key_in=api_key_in)
    assert any("printable ASCII" in error for error in caught.value.errors)


def test_rotation_applies_the_stored_placement_rules(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    with pytest.raises(UpstreamCredentialError) as caught:
        rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value="ключ-значение"))
    assert "printable ASCII" in " ".join(caught.value.errors)


def test_secret_input_hides_its_values_from_repr():
    secret = _secret(value=_SECRET, username="svc-user", password=_SECRET)
    body = _create_body()
    for rendered in (repr(secret), str(secret), repr(body), str(body)):
        assert _SECRET not in rendered
        assert "svc-user" not in rendered


# ============================================================================
# create
# ============================================================================
def test_create_seals_the_secret_under_the_vault_magic(store):
    out = create_credential(_TENANT, _TOOLSET, _create_body(), actor_id=_ACTOR)
    row = store.rows[out.id]
    blob = row["encrypted_secret"]
    assert blob.startswith(b"OUCV")
    assert _SECRET.encode() not in blob
    assert base64.b64encode(_SECRET.encode()) not in blob
    assert vault._CIPHER.unseal(blob, row["key_version"]) == {"value": _SECRET}


def test_create_returns_metadata_only(store):
    out = create_credential(
        _TENANT,
        _TOOLSET,
        _create_body(serverUrl="https://API.example.com:443/v1/"),
        actor_id=_ACTOR,
    )
    dumped = out.model_dump(by_alias=True)
    assert set(dumped) == {
        "schemaVersion",
        "id",
        "toolsetId",
        "serverUrl",
        "kind",
        "in",
        "name",
        "keyVersion",
        "readable",
        "createdAt",
        "createdBy",
        "rotatedAt",
        "rotatedBy",
        "lastUsedAt",
    }
    assert dumped["serverUrl"] == "https://api.example.com/v1"
    assert dumped["toolsetId"] == _TOOLSET
    assert dumped["kind"] == "apiKey"
    assert (dumped["in"], dumped["name"]) == ("header", "X-Api-Key")
    assert dumped["keyVersion"] == 1
    assert dumped["readable"] is True
    assert dumped["createdBy"] == _ACTOR
    assert _SECRET not in json.dumps(dumped, default=str)


def test_a_blob_from_this_vault_does_not_open_in_the_mcp_vault(store, monkeypatch, keys):
    # Same master key configured for both vaults: the magic in the AAD still keeps them apart.
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps(keys))
    out = create_credential(_TENANT, _TOOLSET, _create_body())
    row = store.rows[out.id]
    assert unseal_credential_payload(row["encrypted_secret"], row["key_version"]) is None


def test_create_reports_every_problem_at_once(store):
    body = _create_body(serverUrl="http://api.example.com", name="Host", secret={"token": "x"})
    with pytest.raises(UpstreamCredentialError) as caught:
        create_credential(_TENANT, _TOOLSET, body)
    assert caught.value.code == CODE_CREDENTIAL_INVALID
    joined = " | ".join(caught.value.errors)
    assert "https://" in joined
    assert "managed by the HTTP client" in joined
    assert "secret.token does not apply" in joined
    assert "secret.value is required" in joined
    assert store.rows == {}


def test_bearer_and_basic_refuse_an_api_key_placement(store):
    body = _create_body(kind="bearer", secret={"token": _SECRET})
    with pytest.raises(UpstreamCredentialError) as caught:
        create_credential(_TENANT, _TOOLSET, body)
    assert "apply only to apiKey" in " ".join(caught.value.errors)


def test_create_never_overwrites_an_existing_binding(store):
    first = create_credential(_TENANT, _TOOLSET, _create_body())
    original_blob = store.rows[first.id]["encrypted_secret"]
    with pytest.raises(UpstreamCredentialError) as caught:
        create_credential(
            _TENANT,
            _TOOLSET,
            _create_body(serverUrl="https://api.example.com/v1/", secret={"value": _ROTATED}),
        )
    assert caught.value.code == CODE_CREDENTIAL_EXISTS
    assert "rotate" in str(caught.value)
    assert store.rows[first.id]["encrypted_secret"] == original_blob
    assert len(store.rows) == 1


def test_the_same_server_may_be_bound_by_another_toolset_or_tenant(store):
    create_credential(_TENANT, _TOOLSET, _create_body())
    create_credential(_TENANT, _OTHER_TOOLSET, _create_body())
    create_credential(_OTHER_TENANT, _TOOLSET, _create_body())
    assert len(store.rows) == 3


def test_create_fails_closed_without_a_master_key(store, monkeypatch):
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    with pytest.raises(EnvelopeEncryptionError):
        create_credential(_TENANT, _TOOLSET, _create_body())
    assert store.rows == {}


# ============================================================================
# list
# ============================================================================
def test_list_is_scoped_by_tenant_and_toolset(store):
    create_credential(_TENANT, _TOOLSET, _create_body())
    assert len(list_credentials(_TENANT, _TOOLSET)) == 1
    assert list_credentials(_OTHER_TENANT, _TOOLSET) == []
    assert list_credentials(_TENANT, _OTHER_TOOLSET) == []


def test_list_reports_a_credential_whose_key_is_gone_as_unreadable(store, monkeypatch):
    create_credential(_TENANT, _TOOLSET, _create_body())
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps({"2": _key()}))
    (listed,) = list_credentials(_TENANT, _TOOLSET)
    assert listed.readable is False


def test_list_degrades_to_empty_on_a_store_failure(store, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "list_upstream_credentials", boom)
    assert list_credentials(_TENANT, _TOOLSET) == []


def test_list_reports_when_a_credential_was_last_used(store):
    out = create_credential(_TENANT, _TOOLSET, _create_body())
    assert list_credentials(_TENANT, _TOOLSET)[0].last_used_at is None
    resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    assert list_credentials(_TENANT, _TOOLSET)[0].last_used_at is not None
    assert list_credentials(_TENANT, _TOOLSET)[0].id == out.id


# ============================================================================
# rotate
# ============================================================================
def test_rotate_replaces_the_secret_in_place(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    rotated = rotate_credential(
        _TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED), actor_id=_ACTOR
    )
    assert rotated.id == created.id
    assert rotated.server_url == created.server_url
    assert (rotated.api_key_in, rotated.api_key_name) == ("header", "X-Api-Key")
    assert rotated.rotated_at is not None
    assert rotated.rotated_by == _ACTOR
    injection = resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    assert injection.headers == (("X-Api-Key", _ROTATED),)


def test_rotate_issues_one_update_and_never_deletes(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    store.calls.clear()
    rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    assert store.calls == ["get_upstream_credential", "rotate_upstream_credential"]


def test_rotate_reseals_under_the_active_key(store, monkeypatch, keys):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    monkeypatch.setattr(
        settings,
        "upstream_credential_encryption_keys",
        json.dumps({**keys, "2": _key()}),
    )
    other = create_credential(_TENANT, _OTHER_TOOLSET, _create_body())
    assert other.key_version == 2
    # The row sealed under version 1 still opens while version 1 stays configured…
    assert resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1") is not None
    # …and rotating it moves it onto the active key.
    rotated = rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    assert rotated.key_version == 2


@pytest.mark.parametrize(
    ("tenant", "toolset", "credential"),
    [
        (_OTHER_TENANT, _TOOLSET, None),
        (_TENANT, _OTHER_TOOLSET, None),
        (_TENANT, _TOOLSET, "77777777-7777-4777-8777-777777777777"),
    ],
)
def test_rotate_refuses_a_credential_outside_the_scope(store, tenant, toolset, credential):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    before = store.rows[created.id]["encrypted_secret"]
    with pytest.raises(UpstreamCredentialError) as caught:
        rotate_credential(tenant, toolset, credential or created.id, _rotate_body(value=_ROTATED))
    assert caught.value.code == CODE_CREDENTIAL_NOT_FOUND
    assert store.rows[created.id]["encrypted_secret"] == before


def test_rotate_requires_the_secret_shape_of_the_stored_kind(store):
    created = create_credential(
        _TENANT,
        _TOOLSET,
        _create_body(kind="basic", secret={"username": "svc", "password": _SECRET}, **{"in": None, "name": None}),
    )
    before = store.rows[created.id]["encrypted_secret"]
    with pytest.raises(UpstreamCredentialError) as caught:
        rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    assert caught.value.code == CODE_CREDENTIAL_INVALID
    assert _ROTATED not in str(caught.value)
    assert store.rows[created.id]["encrypted_secret"] == before


def test_rotate_fails_closed_without_a_master_key(store, monkeypatch):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    before = store.rows[created.id]["encrypted_secret"]
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    with pytest.raises(EnvelopeEncryptionError):
        rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    assert store.rows[created.id]["encrypted_secret"] == before


def test_a_rotation_racing_a_delete_reports_not_found(store, monkeypatch):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    real_rotate = store.rotate_upstream_credential

    def delete_then_rotate(**fields):
        store.rows.clear()
        return real_rotate(**fields)

    monkeypatch.setattr(db, "rotate_upstream_credential", delete_then_rotate)
    with pytest.raises(UpstreamCredentialError) as caught:
        rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    assert caught.value.code == CODE_CREDENTIAL_NOT_FOUND


def test_rotation_has_no_downtime_for_concurrent_invocations(store):
    """AC: rotation succeeds with zero toolset downtime; concurrent invocations keep working.

    Resolver threads hammer the vault while another thread rotates the secret over and over.
    Every resolve must return an injection carrying one of the secrets that was ever current:
    never ``None``, never an exception, never a torn value.
    """
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    secrets = [f"sk_live_generation_{index:03d}" for index in range(40)]
    valid = {_SECRET, *secrets}
    url = "https://api.example.com/v1/pets"
    stop = threading.Event()
    failures: list = []
    seen: set = set()
    counts = {"resolves": 0}
    lock = threading.Lock()

    def resolver() -> None:
        while not stop.is_set():
            try:
                injection = resolve_injection(_TENANT, _TOOLSET, url)
            except Exception as exc:  # noqa: BLE001 - any failure is downtime
                failures.append(repr(exc))
                continue
            if injection is None:
                failures.append("resolved to no credential")
                continue
            (name, value), = injection.headers
            if value not in valid:
                failures.append("torn or unknown secret")
            with lock:
                seen.add(value)
                counts["resolves"] += 1

    threads = [threading.Thread(target=resolver) for _ in range(6)]
    for thread in threads:
        thread.start()
    try:
        for secret in secrets:
            rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=secret))
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=10)

    assert failures == []
    assert counts["resolves"] > 0
    assert seen <= valid
    # The last rotation is what the next invocation sees.
    final = resolve_injection(_TENANT, _TOOLSET, url)
    assert final.headers == (("X-Api-Key", secrets[-1]),)


def test_an_invocation_in_flight_keeps_the_secret_it_opened(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    in_flight = resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    rotate_credential(_TENANT, _TOOLSET, created.id, _rotate_body(value=_ROTATED))
    _, headers = in_flight.apply("https://api.example.com/v1/pets", {})
    assert headers == {"X-Api-Key": _SECRET}


# ============================================================================
# delete
# ============================================================================
def test_delete_removes_the_credential_and_keeps_its_use_history(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1")
    removed = delete_credential(_TENANT, _TOOLSET, created.id)
    assert removed.id == created.id
    assert store.rows == {}
    assert [use["credential_id"] for use in store.uses] == [created.id]
    assert delete_credential(_TENANT, _TOOLSET, created.id) is None
    assert resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1") is None


def test_delete_is_scoped_by_tenant_and_toolset(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    assert delete_credential(_OTHER_TENANT, _TOOLSET, created.id) is None
    assert delete_credential(_TENANT, _OTHER_TOOLSET, created.id) is None
    assert created.id in store.rows


# ============================================================================
# resolve_injection — the use path
# ============================================================================
def test_resolve_injects_only_toward_the_bound_server(store):
    create_credential(_TENANT, _TOOLSET, _create_body())
    assert resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets") is not None
    for url in (
        "https://evil.example.com/v1/pets",
        "http://api.example.com/v1/pets",
        "https://api.example.com/v2/pets",
        "https://api.example.com/v1/../admin",
        "https://api.example.com@evil.example.com/v1/pets",
    ):
        assert resolve_injection(_TENANT, _TOOLSET, url) is None, url
    # Unbound URLs are not uses: nothing was opened.
    assert len(store.uses) == 1


def test_resolve_is_scoped_by_tenant_and_toolset(store):
    create_credential(_TENANT, _TOOLSET, _create_body())
    url = "https://api.example.com/v1/pets"
    assert resolve_injection(_OTHER_TENANT, _TOOLSET, url) is None
    assert resolve_injection(_TENANT, _OTHER_TOOLSET, url) is None


def test_resolve_prefers_the_most_specific_binding(store):
    create_credential(
        _TENANT, _TOOLSET, _create_body(serverUrl="https://api.example.com", secret={"value": "root-key"})
    )
    specific = create_credential(
        _TENANT, _TOOLSET, _create_body(serverUrl="https://api.example.com/v2", secret={"value": "v2-key"})
    )
    injection = resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v2/pets")
    assert injection.credential_id == specific.id
    assert injection.headers == (("X-Api-Key", "v2-key"),)
    assert resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets").headers == (
        ("X-Api-Key", "root-key"),
    )


@pytest.mark.parametrize(
    ("body", "expected_headers", "expected_query"),
    [
        (
            {"kind": "bearer", "in": None, "name": None, "secret": {"token": _SECRET}},
            (("Authorization", f"Bearer {_SECRET}"),),
            (),
        ),
        (
            {"kind": "apiKey", "in": "query", "name": "api_key", "secret": {"value": _SECRET}},
            (),
            (("api_key", _SECRET),),
        ),
        (
            {
                "kind": "basic",
                "in": None,
                "name": None,
                "secret": {"username": "svc", "password": _SECRET},
            },
            (("Authorization", "Basic " + base64.b64encode(f"svc:{_SECRET}".encode()).decode()),),
            (),
        ),
    ],
)
def test_resolve_presents_each_kind(store, body, expected_headers, expected_query):
    create_credential(_TENANT, _TOOLSET, _create_body(**body))
    injection = resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/x")
    assert injection.headers == expected_headers
    assert injection.query == expected_query


def test_every_open_is_audited_as_metadata_only(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets?token=abc")
    (use,) = store.uses
    assert {key: use[key] for key in ("tenant_id", "credential_id", "toolset_id", "outcome")} == {
        "tenant_id": _TENANT,
        "credential_id": created.id,
        "toolset_id": _TOOLSET,
        "outcome": USE_OUTCOME_INJECTED,
    }
    assert set(use) == {"tenant_id", "credential_id", "toolset_id", "outcome", "used_at"}
    assert _SECRET not in json.dumps(use, default=str)


def test_a_bound_credential_that_will_not_open_fails_closed(store, monkeypatch):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps({"2": _key()}))
    with pytest.raises(UpstreamCredentialUnavailableError) as caught:
        resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    assert caught.value.credential_id == created.id
    assert _SECRET not in str(caught.value)
    assert [use["outcome"] for use in store.uses] == [USE_OUTCOME_UNAVAILABLE]


def test_a_tampered_blob_fails_closed(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    blob = bytearray(store.rows[created.id]["encrypted_secret"])
    blob[-1] ^= 0x01
    store.rows[created.id]["encrypted_secret"] = bytes(blob)
    with pytest.raises(UpstreamCredentialUnavailableError):
        resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")


def test_a_payload_that_does_not_fit_its_kind_fails_closed(store):
    created = create_credential(_TENANT, _TOOLSET, _create_body())
    sealed, version = vault._CIPHER.seal({"token": _SECRET})
    store.rows[created.id].update(encrypted_secret=sealed, key_version=version)
    with pytest.raises(UpstreamCredentialUnavailableError):
        resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    assert [use["outcome"] for use in store.uses] == [USE_OUTCOME_UNAVAILABLE]


def test_a_use_ledger_failure_does_not_fail_the_invocation(store):
    create_credential(_TENANT, _TOOLSET, _create_body())
    store.fail_uses = True
    injection = resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets")
    assert injection.headers == (("X-Api-Key", _SECRET),)


def test_a_store_without_the_toolset_resolves_to_nothing(store):
    assert resolve_injection(_TENANT, _TOOLSET, "https://api.example.com/v1/pets") is None
    assert store.uses == []
