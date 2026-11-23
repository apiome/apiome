"""Store rules for comment threads that the HTTP tests do not isolate — COL-1.1 (#4513).

The ownership predicate, the mention short-circuit, version resolution across projects, and the
mapping of a list row's embedded opening comment.
"""

from __future__ import annotations

import pytest

from app import comment_store, notification_store
from app.comments import CommentThreadCreate, CommentValidationError
from tests.fake_comment_db import FakeCommentDb

TENANT = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0001"
PROJECT = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0002"
OTHER_PROJECT = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0003"
VERSION = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0010"
OTHER_VERSION = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0011"
CLASS_ID = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0020"
AUTHOR = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0101"
ADMIN = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0102"
STRANGER = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0103"


@pytest.fixture
def fake(monkeypatch) -> FakeCommentDb:
    """A seeded store beneath :mod:`app.comment_store`."""
    store = FakeCommentDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_version(OTHER_PROJECT, OTHER_VERSION, "9.9.9")
    store.add_anchor(VERSION, "class", CLASS_ID)
    store.add_member(AUTHOR, "Ada Author", "ada@example.com")
    store.admins.add((TENANT, ADMIN))
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(notification_store, "db", store)
    return store


def test_the_owner_and_a_tenant_admin_may_moderate(fake):
    assert comment_store.can_moderate(TENANT, AUTHOR, AUTHOR)
    assert comment_store.can_moderate(TENANT, ADMIN, AUTHOR)
    assert not comment_store.can_moderate(TENANT, STRANGER, AUTHOR)


def test_an_orphaned_comment_is_admin_only(fake):
    assert not comment_store.can_moderate(TENANT, STRANGER, None)
    assert comment_store.can_moderate(TENANT, ADMIN, None)


@pytest.mark.parametrize("actor", [None, "", "not-a-uuid"])
def test_an_unattributable_actor_never_moderates(fake, actor):
    fake.admins.add((TENANT, "not-a-uuid"))
    assert not comment_store.can_moderate(TENANT, actor, AUTHOR)


def test_a_body_without_an_at_sign_never_reads_the_member_list(fake):
    assert comment_store.resolve_body_mentions(TENANT, "no mentions here") == []
    assert fake.member_reads == 0
    assert comment_store.resolve_body_mentions(TENANT, "hey @ada") == [AUTHOR]
    assert fake.member_reads == 1


def test_a_version_is_resolved_only_inside_its_project(fake):
    assert comment_store.resolve_version(TENANT, PROJECT, "1.0.0")["id"] == VERSION
    assert comment_store.resolve_version(TENANT, PROJECT, VERSION)["id"] == VERSION
    for ref in (OTHER_VERSION, "9.9.9", "", "   "):
        with pytest.raises(CommentValidationError) as refusal:
            comment_store.resolve_version(TENANT, PROJECT, ref)
        assert refusal.value.code == "comment-version-not-found"


def test_a_project_of_another_tenant_is_not_found(fake):
    with pytest.raises(CommentValidationError) as refusal:
        comment_store.resolve_project("5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f9999", "pets")
    assert refusal.value.code == "comment-project-not-found"


def test_an_unattributable_insert_is_refused_rather_than_stored_anonymously(fake, monkeypatch):
    monkeypatch.setattr(fake, "insert_comment_thread", lambda **_: None)
    request = CommentThreadCreate(version=VERSION, anchor_type="class", anchor_id=CLASS_ID, body="hi")
    with pytest.raises(CommentValidationError) as refusal:
        comment_store.create_thread(TENANT, "pets", request, AUTHOR)
    assert refusal.value.code == "comment-forbidden"


def test_a_list_row_carries_its_opening_comment(fake):
    request = CommentThreadCreate(version=VERSION, anchor_type="class", anchor_id=CLASS_ID, body="first @ada")
    detail = comment_store.create_thread(TENANT, "pets", request, AUTHOR)
    comment_store.add_comment(TENANT, "pets", detail.thread.id, "second", AUTHOR)

    page, total = comment_store.list_threads(
        TENANT, "pets", comment_store.ThreadFilters(include_total=True), AUTHOR
    )
    assert total == 1
    assert page.has_more is False and page.next_cursor is None
    (summary,) = page.items
    assert summary.comment_count == 2
    assert summary.root_comment is not None
    assert summary.root_comment.body == "first @ada"
    assert summary.root_comment.thread_id == summary.id
    assert summary.root_comment.mentions == [AUTHOR]
    assert summary.root_comment.author_name == "Ada Author"


# --- narrow mention lookup (DBP-1.13, #7196) ---------------------------------------------------


def test_a_mention_looks_up_only_the_handles_in_the_body(fake):
    for index in range(40):
        fake.add_member(f"00000000-0000-4000-8000-{index:012d}", f"Member {index}", f"m{index}@example.com")
    assert comment_store.resolve_body_mentions(TENANT, "hey @ada and @m7") == [
        AUTHOR,
        "00000000-0000-4000-8000-000000000007",
    ]
    assert fake.full_member_reads == 0
    assert fake.mention_lookups == [["ada", "m7"]]


def test_an_at_sign_that_is_no_mention_reads_no_member(fake):
    assert comment_store.resolve_body_mentions(TENANT, "mail jane@example.com") == []
    assert fake.member_reads == 0


def test_a_body_with_too_many_handles_falls_back_to_the_member_list(fake):
    body = " ".join(f"@nobody{index}" for index in range(comment_store.MAX_MENTION_LOOKUP_HANDLES + 1))
    assert comment_store.resolve_body_mentions(TENANT, body + " @ada") == [AUTHOR]
    assert fake.full_member_reads == 1 and fake.mention_lookups == []


def test_the_narrow_lookup_keeps_every_member_a_handle_could_mean():
    """The SQL filter is a superset: emails and local parts exactly, names by characters in order."""
    from unittest.mock import patch

    from app.database import db as real_db

    with patch.object(real_db, "execute_query", return_value=[]) as query:
        real_db.find_comment_mention_candidates(TENANT, ["ada", "jane.doe@example.com"])
    sql, params = query.call_args.args
    assert "lower(u.email) = ANY(%s::text[])" in sql
    assert "lower(split_part(u.email, '@', 1)) = ANY(%s::text[])" in sql
    assert "lower(u.name) LIKE ANY(%s::text[])" in sql
    assert "tu.status IN ('active', 'pending')" in sql and "u.deleted_at IS NULL" in sql
    handles = ["ada", "jane.doe@example.com"]
    # An email handle can never be a display-name handle, so it gets no name pattern.
    assert params == (TENANT, handles, handles, ["%a%d%a%"])


def test_the_narrow_lookup_reads_nothing_without_handles_or_a_tenant():
    from unittest.mock import patch

    from app.database import db as real_db

    with patch.object(real_db, "execute_query") as query:
        assert real_db.find_comment_mention_candidates(TENANT, []) == []
        assert real_db.find_comment_mention_candidates("not-a-uuid", ["ada"]) == []
        assert real_db.filter_mentionable_member_ids(TENANT, ["not-a-uuid"]) == []
    query.assert_not_called()


def test_member_ids_are_checked_with_one_id_predicate():
    from unittest.mock import patch

    from app.database import db as real_db

    with patch.object(real_db, "execute_query", return_value=[{"user_id": AUTHOR}]) as query:
        assert real_db.filter_mentionable_member_ids(TENANT, [AUTHOR, "junk"]) == [AUTHOR]
    sql, params = query.call_args.args
    assert "u.id = ANY(%s::uuid[])" in sql
    assert params == (TENANT, [AUTHOR])
