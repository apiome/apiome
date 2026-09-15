"""Server-side ``@name`` mention parsing — COL-1.1 (#4513).

``comments.mentions`` is the source of truth for notification fan-out (COL-3.1), so the parser is
pinned from both sides: what *is* a mention (handles, emails, display names, punctuation, Unicode)
and what is *not* (addresses, URLs, escapes, code), plus how collisions and caps resolve.
"""

from __future__ import annotations

import pytest

from app.comment_mentions import (
    MAX_MENTIONS,
    MentionCandidate,
    extract_mention_handles,
    member_handles,
    resolve_mentions,
)

JANE = MentionCandidate(user_id="u-jane", name="Jane Doe", email="jane.doe@example.com")
BOB = MentionCandidate(user_id="u-bob", name="Bob Brown", email="bob@example.com")
ALEX_KIM = MentionCandidate(user_id="u-alex-kim", name="Alex Kim", email="alex@kim.example")
ALEX_LEE = MentionCandidate(user_id="u-alex-lee", name="Alex Lee", email="alex@lee.example")
MEMBERS = [JANE, BOB, ALEX_KIM, ALEX_LEE]


def _ids(body: str, members=MEMBERS):
    """The resolved ids for a body."""
    return resolve_mentions(body, members).user_ids


# ---------------------------------------------------------------------------------------------
# What resolves
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "@jane.doe can you check this?",  # email local part
        "@jane.doe@example.com can you check this?",  # full email
        "@JaneDoe can you check this?",  # display name without spaces, any case
        "@JANE.DOE",
        "thanks @jane.doe.",  # trailing sentence punctuation
        "thanks @jane.doe, and more",
        "(@jane.doe)",
        "**@jane.doe**",
        "line one\n@jane.doe on line two",
        "`code` then @jane.doe",  # code before the mention does not swallow it
    ],
)
def test_a_member_is_mentioned_by_any_of_their_handles(body):
    assert _ids(body) == ["u-jane"]


def test_mentions_are_distinct_and_in_order_of_first_mention():
    assert _ids("@bob, then @jane.doe, then @bob again and @JaneDoe") == ["u-bob", "u-jane"]


def test_the_full_email_disambiguates_members_sharing_a_handle():
    assert _ids("@alex@lee.example") == ["u-alex-lee"]


def test_display_name_handle_drops_characters_a_handle_cannot_hold():
    member = MentionCandidate(user_id="u-obrien", name="Jane O'Brien", email="jo@example.com")
    assert "janeobrien" in member_handles(member)
    assert _ids("@JaneOBrien", [member]) == ["u-obrien"]


def test_unicode_names_are_mentionable():
    member = MentionCandidate(user_id="u-zoe", name="Zoë Ärger", email=None)
    assert member_handles(member) == {"zoëärger"}
    assert _ids("hi @ZoëÄrger!", [member]) == ["u-zoe"]


def test_member_handles_cover_email_local_part_and_name():
    assert member_handles(JANE) == {"jane.doe@example.com", "jane.doe", "janedoe"}


def test_a_member_without_email_or_name_answers_to_nothing():
    assert member_handles(MentionCandidate(user_id="u-x")) == set()


# ---------------------------------------------------------------------------------------------
# What does not resolve
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "write to jane.doe@example.com",  # an address in prose is not a mention
        "see https://medium.com/@jane.doe",  # nor is a URL path
        "a literal \\@jane.doe",  # Markdown escape
        "inline `@jane.doe` code",
        "inline ``a ` @jane.doe`` code with a backtick inside",
        "```\n@jane.doe\n```",
        "~~~python\n@jane.doe\n~~~",
        "```\nnever closed\n@jane.doe",  # an unclosed fence runs to the end
        "@",
        "",
    ],
)
def test_non_mentions_resolve_to_nobody(body):
    assert _ids(body) == []


def test_text_after_a_closed_fence_is_parsed_again():
    assert _ids("```\n@bob\n```\nnow @jane.doe") == ["u-jane"]


def test_a_handle_matching_several_members_is_ambiguous_not_guessed():
    result = resolve_mentions("@alex please", MEMBERS)
    assert result.user_ids == []
    assert result.ambiguous == ["alex"]
    assert result.unresolved == []


def test_a_handle_matching_nobody_is_unresolved():
    result = resolve_mentions("@nobody and @jane.doe", MEMBERS)
    assert result.user_ids == ["u-jane"]
    assert result.unresolved == ["nobody"]


def test_members_without_an_id_are_ignored():
    ghost = MentionCandidate(user_id="", name="Ghost", email="ghost@example.com")
    assert _ids("@ghost", [ghost]) == []


def test_no_tokens_means_no_member_matching_at_all():
    assert resolve_mentions("nothing to see", MEMBERS).user_ids == []


# ---------------------------------------------------------------------------------------------
# Extraction and caps
# ---------------------------------------------------------------------------------------------


def test_extracted_handles_are_lower_cased_and_distinct():
    assert extract_mention_handles("@Bob @BOB @jane.doe@Example.com") == ["bob", "jane.doe@example.com"]


def test_resolved_mentions_are_capped():
    members = [
        MentionCandidate(user_id=f"u-{n}", name=None, email=f"user{n}@example.com")
        for n in range(MAX_MENTIONS + 10)
    ]
    body = " ".join(f"@user{n}" for n in range(MAX_MENTIONS + 10))
    ids = _ids(body, members)
    assert len(ids) == MAX_MENTIONS
    assert ids[0] == "u-0" and ids[-1] == f"u-{MAX_MENTIONS - 1}"


def test_an_absurdly_long_handle_is_skipped():
    assert extract_mention_handles("@" + "a" * 300) == []
