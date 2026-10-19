"""Consumer bindings, the pure half — RDG-1.8 (#5765).

What is asserted here:

* the tenant key is derived from the envelope key map (HKDF), differs per tenant and per master-key
  version, and a hash is 64 lower-case hex characters — the form ``consumer_hint.hmac`` carries;
* no key configured is a 503 refusal, never an unkeyed hash;
* a binding's value is required for hashed kinds, refused for a user-agent glob, and a glob too
  broad to identify one consumer is refused;
* the matcher prefers the exact hint over a glob, the most specific glob over a broad one, the
  oldest binding on a tie, and returns nothing (anonymous) when nothing matches;
* a binding record never carries its value or its hash.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import consumer_binding
from app.config import settings
from app.consumer_binding import (
    CODE_BINDING_INVALID,
    CODE_BINDING_KEY_UNAVAILABLE,
    BindingError,
    BindingInput,
    ConsumerMatcher,
    LiveBinding,
    binding_record_from_row,
    consumer_hint_hmac,
    derive_tenant_key,
    hash_bound_value,
    normalize_binding,
)
from app.usage_events import ConsumerHint

TENANT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MASTER_1 = bytes(range(32))
MASTER_2 = bytes(range(1, 33))
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a two-version linked-account key map with version 2 active."""
    monkeypatch.setattr(
        settings,
        "linked_account_token_encryption_keys",
        json.dumps({"1": base64.b64encode(MASTER_1).decode(), "2": base64.b64encode(MASTER_2).decode()}),
    )
    monkeypatch.setattr(settings, "linked_account_token_active_key_version", 2)


# ---------------------------------------------------------------------------------------------
# Keys and hashes
# ---------------------------------------------------------------------------------------------


def test_the_tenant_key_is_deterministic_and_differs_per_tenant_and_master_key() -> None:
    key = derive_tenant_key(MASTER_1, TENANT_A)
    assert len(key) == 32
    assert key == derive_tenant_key(MASTER_1, TENANT_A)
    assert key == derive_tenant_key(MASTER_1, TENANT_A.upper())
    assert key != derive_tenant_key(MASTER_1, TENANT_B)
    assert key != derive_tenant_key(MASTER_2, TENANT_A)
    assert key != MASTER_1


def test_a_hash_is_the_hint_form_and_never_contains_the_value() -> None:
    digest = hash_bound_value(derive_tenant_key(MASTER_1, TENANT_A), "billing-secret-client-id")
    assert len(digest) == 64 and digest == digest.lower()
    assert "billing" not in digest
    # The usage event contract accepts it as a hint as is.
    assert ConsumerHint(kind="header", hmac=digest).hmac == digest


def test_consumer_hint_hmac_uses_the_active_version_and_any_requested_one(keys: None) -> None:
    digest, version = consumer_hint_hmac(TENANT_A, "billing")
    assert version == 2
    assert digest == hash_bound_value(derive_tenant_key(MASTER_2, TENANT_A), "billing")
    old, old_version = consumer_hint_hmac(TENANT_A, "billing", key_version=1)
    assert old_version == 1 and old != digest
    assert consumer_hint_hmac(TENANT_B, "billing")[0] != digest


def test_no_configured_key_refuses_with_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "linked_account_token_encryption_keys", None)
    with pytest.raises(BindingError) as refused:
        consumer_hint_hmac(TENANT_A, "billing")
    assert refused.value.status == 503 and refused.value.code == CODE_BINDING_KEY_UNAVAILABLE


def test_an_unconfigured_version_refuses_with_503(keys: None) -> None:
    with pytest.raises(BindingError) as refused:
        consumer_hint_hmac(TENANT_A, "billing", key_version=9)
    assert refused.value.status == 503


def test_a_malformed_key_map_refuses_with_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "linked_account_token_encryption_keys", "not json")
    with pytest.raises(BindingError) as refused:
        consumer_hint_hmac(TENANT_A, "billing")
    assert refused.value.status == 503


# ---------------------------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["header", "api_key", "jwt_claim"])
def test_a_hashed_kind_needs_a_value(kind: str) -> None:
    with pytest.raises(ValidationError):
        BindingInput(kind=kind, name="x-client-id")
    with pytest.raises(ValidationError):
        BindingInput(kind=kind, name="x-client-id", value="")
    assert BindingInput(kind=kind, name="x-client-id", value="v").value is not None


def test_a_user_agent_binding_takes_no_value() -> None:
    with pytest.raises(ValidationError):
        BindingInput(kind="user_agent", name="billing/*", value="v")
    assert BindingInput(kind="user_agent", name="billing/*").value is None


def test_an_oversized_value_is_refused() -> None:
    with pytest.raises(ValidationError):
        BindingInput(kind="header", name="x-client-id", value="v" * 5000)


def test_the_value_never_appears_in_the_model_dump_or_repr() -> None:
    body = BindingInput(kind="header", name="x-client-id", value="super-secret-client")
    assert "super-secret-client" not in repr(body)
    assert "super-secret-client" not in body.model_dump_json()


def test_header_names_are_lowercased_and_validated() -> None:
    assert normalize_binding("header", " X-Client-Id ") == "x-client-id"
    assert normalize_binding("api_key", "X-API-Key") == "x-api-key"
    with pytest.raises(BindingError) as refused:
        normalize_binding("header", "x client id")
    assert refused.value.code == CODE_BINDING_INVALID


def test_claim_names_keep_their_case_and_refuse_whitespace() -> None:
    assert normalize_binding("jwt_claim", "clientId") == "clientId"
    with pytest.raises(BindingError):
        normalize_binding("jwt_claim", "client id")


@pytest.mark.parametrize("glob", ["*", "?*", "a*", "[ab]*?", "*ab*"])
def test_a_glob_that_could_match_every_caller_is_refused(glob: str) -> None:
    with pytest.raises(BindingError) as refused:
        normalize_binding("user_agent", glob)
    assert refused.value.code == CODE_BINDING_INVALID


def test_a_specific_glob_is_kept_as_written() -> None:
    assert normalize_binding("user_agent", "Billing-Service/*") == "Billing-Service/*"
    with pytest.raises(BindingError):
        normalize_binding("user_agent", "billing\tservice/*")


def test_a_record_never_carries_the_hash() -> None:
    record = binding_record_from_row(
        {
            "id": "1",
            "consumer_id": "2",
            "kind": "header",
            "name": "x-client-id",
            "value_hmac": "f" * 64,
            "key_version": 1,
            "created_at": T0,
        }
    )
    assert record.hashed is True
    assert "f" * 64 not in record.model_dump_json()
    glob = binding_record_from_row({"id": "1", "consumer_id": "2", "kind": "user_agent", "name": "billing/*"})
    assert glob.hashed is False


# ---------------------------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------------------------

H1 = "1" * 64
H2 = "2" * 64


def _binding(binding_id: str, kind: str, name: str, value_hmac: str | None = None, *, age: int = 0) -> LiveBinding:
    return LiveBinding(
        id=binding_id,
        consumer_id=f"consumer-of-{binding_id}",
        kind=kind,
        name=name,
        value_hmac=value_hmac,
        created_at=T0 + timedelta(minutes=age),
    )


def test_an_empty_matcher_is_falsy_and_matches_nothing() -> None:
    matcher = ConsumerMatcher([])
    assert not matcher
    assert matcher.match("header", H1, "billing/1.0") is None


def test_a_hint_matches_its_kind_and_hash_only() -> None:
    matcher = ConsumerMatcher([_binding("key", "api_key", "x-api-key", H1)])
    assert matcher.match("api_key", H1, None).id == "key"
    assert matcher.match("header", H1, None) is None
    assert matcher.match("api_key", H2, None) is None


def test_the_hint_wins_over_a_user_agent_glob() -> None:
    matcher = ConsumerMatcher(
        [_binding("glob", "user_agent", "billing-service/*"), _binding("key", "header", "x-client-id", H1)]
    )
    assert matcher.match("header", H1, "billing-service/2.0").id == "key"
    assert matcher.match(None, None, "billing-service/2.0").id == "glob"
    assert matcher.match("header", H2, "billing-service/2.0").id == "glob"


def test_globs_are_case_insensitive_and_anchored() -> None:
    matcher = ConsumerMatcher([_binding("glob", "user_agent", "billing-service/*")])
    assert matcher.match(None, None, "Billing-Service/3.1 (linux)").id == "glob"
    assert matcher.match(None, None, "not-billing-service/1") is None


def test_the_most_specific_glob_wins_then_the_oldest() -> None:
    matcher = ConsumerMatcher(
        [
            _binding("broad", "user_agent", "billing*", age=0),
            _binding("narrow", "user_agent", "billing-service/*", age=5),
            _binding("twin-new", "user_agent", "billing-service/?.*", age=9),
            _binding("twin-old", "user_agent", "billing-service/*.?", age=1),
        ]
    )
    # The two 17-literal globs both match: the older wins. Without a dot, the 16-literal one does.
    assert matcher.match(None, None, "billing-service/2.0").id == "twin-old"
    assert matcher.match(None, None, "billing-service/beta").id == "narrow"
    assert matcher.match(None, None, "billing-batch").id == "broad"


def test_the_oldest_binding_wins_two_identical_hashes() -> None:
    matcher = ConsumerMatcher(
        [_binding("new", "header", "x-team", H1, age=3), _binding("old", "header", "x-client-id", H1, age=1)]
    )
    assert matcher.match("header", H1, None).id == "old"


def test_the_matcher_is_order_independent() -> None:
    bindings = [
        _binding("a", "user_agent", "billing-service/*", age=2),
        _binding("b", "user_agent", "billing-service/*", age=1),
        _binding("c", "header", "x", H1, age=4),
        _binding("d", "header", "y", H1, age=3),
    ]
    forward = ConsumerMatcher(bindings)
    backward = ConsumerMatcher(list(reversed(bindings)))
    for args in ((None, None, "billing-service/1"), ("header", H1, None)):
        assert forward.match(*args).id == backward.match(*args).id


def test_the_module_exports_resolve() -> None:
    for name in consumer_binding.__all__:
        assert hasattr(consumer_binding, name), name
