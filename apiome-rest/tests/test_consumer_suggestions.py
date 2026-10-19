"""Suggested consumers, the parts that need no database — CDG-3.5 (#5970).

* a hashed client's id never contains its HMAC, and ids are stable;
* a suggestion reads as its user-agent token, or as the kind of credential plus an opaque tag;
* registering refuses a hashed client without a binding name before touching anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.consumer_binding import BindingError
from app.consumer_suggestions import _ID, _binding_for, _Row, _suggestion, suggestion_id

HMAC = "ab" * 32
T = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def _row(kind: str, key: str) -> _Row:
    return _Row(client_kind=kind, client_key=key, calls=12, days_seen=2, first_seen_at=T, last_seen_at=T)


def test_a_user_agent_id_is_its_token() -> None:
    assert suggestion_id("user_agent", "checkout-web") == "ua:checkout-web"


def test_a_hashed_id_is_opaque_stable_and_valid() -> None:
    sid = suggestion_id("api_key", HMAC)
    assert sid.startswith("api_key:") and HMAC not in sid and HMAC[:20] not in sid
    assert sid == suggestion_id("api_key", HMAC)
    assert _ID.match(sid) and _ID.match("ua:checkout-web")
    assert not _ID.match("ua:Checkout") and not _ID.match(f"api_key:{HMAC}")


def test_a_user_agent_suggestion_reads_as_its_token() -> None:
    out = _suggestion(_row("user_agent", "checkout-web"))
    assert (out.label, out.suggested_name, out.suggested_slug, out.needs_binding_name) == (
        "checkout-web",
        "checkout-web",
        "checkout-web",
        False,
    )
    assert out.calls == 12 and out.days_seen == 2


def test_a_hashed_suggestion_reads_as_its_kind_and_never_shows_the_hash() -> None:
    out = _suggestion(_row("jwt_claim", HMAC))
    assert out.label.startswith("Unrecognised JWT claim ") and out.suggested_slug is None
    assert out.needs_binding_name is True
    assert HMAC not in out.model_dump_json()


def test_the_binding_for_a_user_agent_is_its_token_glob() -> None:
    assert _binding_for(_row("user_agent", "checkout-web"), None) == ("user_agent", "checkout-web/*", None, None)


def test_a_one_letter_token_is_too_broad_to_bind() -> None:
    with pytest.raises(BindingError):
        _binding_for(_row("user_agent", "a"), None)


@pytest.mark.parametrize("name", [None, "", "  ", "x client"])
def test_a_hashed_client_needs_a_valid_binding_name(name: str) -> None:
    with pytest.raises(BindingError) as refused:
        _binding_for(_row("header", HMAC), name)
    assert refused.value.status == 400
