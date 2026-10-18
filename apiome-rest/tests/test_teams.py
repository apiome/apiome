"""Validation rules for teams — CDG-2.1 (#5960).

:mod:`app.teams` is where a malformed slug, a blank name, a link that is not http(s) or a
duplicated member is refused, before anything reaches the database. Each refusal carries the
``team-invalid`` code so the route can map it onto a 400.
"""

from __future__ import annotations

import pytest

from app.teams import (
    CODE_INVALID,
    TeamMemberInput,
    TeamMembersInput,
    TeamValidationError,
    normalize_contact_email,
    normalize_link,
    normalize_name,
    resolve_slug,
    validate_members,
)

_USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_slug_is_derived_from_the_name_when_omitted() -> None:
    assert resolve_slug(None, "Payments Platform") == "payments-platform"


def test_a_supplied_slug_is_normalized() -> None:
    assert resolve_slug("  Payments  ", "ignored") == "payments"


@pytest.mark.parametrize("slug", ["-payments", "payments-", "pay/ments", "pay ments", ""])
def test_a_malformed_slug_is_refused(slug: str) -> None:
    with pytest.raises(TeamValidationError) as caught:
        resolve_slug(slug, "Payments")
    assert caught.value.code == CODE_INVALID


def test_a_name_with_nothing_to_derive_a_slug_from_is_refused() -> None:
    with pytest.raises(TeamValidationError):
        resolve_slug(None, "!!!")


def test_a_blank_name_is_refused() -> None:
    with pytest.raises(TeamValidationError):
        normalize_name("   ")
    assert normalize_name("  Payments ") == "Payments"


def test_links_must_be_absolute_http_urls() -> None:
    assert normalize_link("chat_url", " https://chat.example/c/pay ") == "https://chat.example/c/pay"
    assert normalize_link("chat_url", "http://x.example") == "http://x.example"
    assert normalize_link("chat_url", "") is None
    assert normalize_link("chat_url", None) is None
    for bad in ("ftp://x.example", "javascript:alert(1)", "/relative", "https://"):
        with pytest.raises(TeamValidationError) as caught:
            normalize_link("docs_url", bad)
        assert "docs_url" in str(caught.value)


def test_contact_email_is_lowercased_and_shape_checked() -> None:
    assert normalize_contact_email(" Pay@Example.COM ") == "pay@example.com"
    assert normalize_contact_email(None) is None
    with pytest.raises(TeamValidationError):
        normalize_contact_email("not-an-address")


def test_members_are_normalized_and_keep_their_order() -> None:
    cleaned = validate_members(
        [TeamMemberInput(user_id=_USER_B.upper(), role="lead"), TeamMemberInput(user_id=_USER_A)]
    )
    assert [(m.user_id, m.role) for m in cleaned] == [(_USER_B, "lead"), (_USER_A, "member")]


def test_a_user_listed_twice_is_refused() -> None:
    with pytest.raises(TeamValidationError) as caught:
        validate_members([TeamMemberInput(user_id=_USER_A), TeamMemberInput(user_id=_USER_A)])
    assert "more than once" in str(caught.value)


def test_a_non_uuid_member_is_refused() -> None:
    with pytest.raises(TeamValidationError):
        validate_members([TeamMemberInput(user_id="alice")])


def test_a_role_outside_lead_and_member_does_not_parse() -> None:
    with pytest.raises(ValueError):
        TeamMembersInput(members=[{"user_id": _USER_A, "role": "owner"}])
