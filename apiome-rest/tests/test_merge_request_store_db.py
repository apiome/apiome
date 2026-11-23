"""Draft branches and merge requests against a live Postgres — COL-4.3 (#4527).

One always-rolled-back transaction per test, shared by every module through the ``db`` singleton,
so the real review store and the real merge-preview / merge routes run exactly as in production.
Seeds a project whose default branch ``main`` points at revision 1.0.0 with a ``Pet`` class;
Rita authors, Rex reviews.

Acceptance:

* a named branch created from a version line gets its own revision — edits on it leave the line
  untouched;
* reviewers decide through the COL-2.1 review; the merge runs through a persisted merge session and
  the existing merge path; the line gains the branch's change;
* conflicts surface as the merge session's conflict rows.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import merge_request_store as store
from app import review_store, version_merge_routes
from app.config import settings
from app.database import db
from app.merge_requests import (
    CODE_ALREADY_OPEN,
    CODE_BRANCH_EXISTS,
    CODE_CONFLICTS,
    CODE_LABEL_TAKEN,
    CODE_NOT_DRAFT_BRANCH,
    CODE_NOT_READY,
    DraftBranchCreate,
    MergeRequestCreate,
    MergeRequestMerge,
    MergeRequestReviewRequest,
    MergeRequestValidationError,
)
from app.reviews import ReviewDecisionCreate
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db

PET = {"type": "object"}
NAME = {"type": "string"}


@pytest.fixture
def world(monkeypatch) -> Iterator[Tuple[Dict[str, Any], Any]]:
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.merge_requests') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V377 not applied")
    monkeypatch.setattr(db, "connection", _NoCommitConnection(conn))
    # The merge routes check RBAC themselves; the seeded users hold no roles.
    monkeypatch.setattr(version_merge_routes, "enforce_permission", lambda *a, **k: None)
    try:
        with conn.cursor() as cur:
            sfx = uuid.uuid4().hex[:10]
            w: Dict[str, Any] = {"cur": cur}

            def one(sql, params):
                cur.execute(sql + " RETURNING id::text AS id", params)
                return cur.fetchone()["id"]

            for who in ("rita", "rex"):
                w[who] = one(
                    "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x')",
                    (who.title(), f"{who}-{sfx}@example.com"),
                )
            w["tenant"] = one("INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s)", (f"m {sfx}", f"m-{sfx}"))
            for who in ("rita", "rex"):
                one("INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES (%s, %s)", (w["tenant"], w[who]))
            w["project"] = one(
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'Pets', %s)",
                (w["tenant"], w["rita"], f"p-{sfx}"),
            )
            w["line_tip"] = one(
                # Older than anything the test creates: one transaction shares CURRENT_TIMESTAMP, and
                # "the latest version" (which labels a merge) is ordered by created_at.
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, created_at) "
                "VALUES (%s, %s, '1.0.0', now() - interval '1 hour')",
                (w["project"], w["rita"]),
            )
            pet = one(
                "INSERT INTO apiome.classes (version_id, name, description, schema) VALUES (%s, 'Pet', 'A pet', %s)",
                (w["line_tip"], json.dumps(PET)),
            )
            w["source_property"] = one(
                "INSERT INTO apiome.properties (project_id, name, data) VALUES (%s, 'shared', %s)",
                (w["project"], json.dumps(NAME)),
            )
            one(
                "INSERT INTO apiome.class_properties (class_id, property_id, name, data) VALUES (%s, %s, 'name', %s)",
                (pet, w["source_property"], json.dumps(NAME)),
            )
            w["main"] = one(
                "INSERT INTO apiome.version_branches "
                "(project_id, name, tip_version_id, is_default, branched_from_revision_id) "
                "VALUES (%s, 'main', %s, true, %s)",
                (w["project"], w["line_tip"], w["line_tip"]),
            )
            yield w, cur
    finally:
        conn.rollback()
        conn.close()


def _auth(w, who="rita") -> Dict[str, Any]:
    return {"tenant_id": w["tenant"], "user_id": w[who]}


def _pet(cur, revision_id) -> Dict[str, Any]:
    """``Pet``'s properties on a revision, as ``{name: data}`` — what the generated document shows."""
    cur.execute(
        "SELECT cp.name, cp.data FROM apiome.class_properties cp JOIN apiome.classes c ON c.id = cp.class_id "
        "WHERE c.version_id = %s AND c.name = 'Pet' AND c.deleted_at IS NULL",
        (revision_id,),
    )
    return {row["name"]: row["data"] for row in cur.fetchall()}


def _set_prop(w, revision_id, name, data) -> None:
    """Add or replace one ``Pet`` property on a revision — the edit the canvas makes."""
    cur = w["cur"]
    cur.execute(
        "SELECT id FROM apiome.classes WHERE version_id = %s AND name = 'Pet' AND deleted_at IS NULL", (revision_id,)
    )
    class_id = cur.fetchone()["id"]
    cur.execute("DELETE FROM apiome.class_properties WHERE class_id = %s AND name = %s", (class_id, name))
    cur.execute(
        "INSERT INTO apiome.class_properties (class_id, property_id, name, data) VALUES (%s, %s, %s, %s)",
        (class_id, w["source_property"], name, json.dumps(data)),
    )


def _branch_tip(cur, branch_id) -> str:
    cur.execute("SELECT tip_version_id::text AS tip FROM apiome.version_branches WHERE id = %s", (branch_id,))
    return cur.fetchone()["tip"]


def _advance(w, branch_id, label, prop, data) -> str:
    """Push a new revision onto a branch (as a direct push would) with ``Pet.<prop>`` set to ``data``."""
    cur = w["cur"]
    parent = _branch_tip(cur, branch_id)
    cur.execute(
        "INSERT INTO apiome.versions (project_id, creator_id, version_id, parent_version_id, created_at) "
        "VALUES (%s, %s, %s, %s, clock_timestamp()) RETURNING id::text AS id",
        (w["project"], w["rita"], label, parent),
    )
    rid = cur.fetchone()["id"]
    db.copy_classes_from_version_for_merge(cur, parent, rid)
    _set_prop(w, rid, prop, data)
    cur.execute("UPDATE apiome.version_branches SET tip_version_id = %s WHERE id = %s", (rid, branch_id))
    return rid


def _draft(w, name="feature/tags"):
    return store.create_draft_branch(w["tenant"], w["project"], DraftBranchCreate(name=name), w["rita"])


def _open(w, branch, reviewers=("rex",)):
    body = MergeRequestCreate(source_branch=branch.name, title="Add pet tags", reviewers=[w[r] for r in reviewers])
    return store.open_merge_request(w["tenant"], w["project"], body, w["rita"])


def _approve(w, review_id, who="rex"):
    review_store.record_decision(w["tenant"], w["project"], review_id, ReviewDecisionCreate(decision="approve"), w[who])


def _merge(w, mr_id):
    return store.merge_merge_request("acme", _auth(w), w["rita"], w["project"], mr_id, MergeRequestMerge())


def test_a_draft_branch_has_its_own_revision_so_edits_leave_the_line_alone(world):
    w, cur = world
    branch = _draft(w)
    assert branch.base_branch_name == "main" and branch.branched_from_revision_id == w["line_tip"]
    assert branch.tip_revision_id != w["line_tip"]
    assert branch.tip_version_label == "1.0.1"
    assert _pet(cur, branch.tip_revision_id) == {"name": NAME}

    _set_prop(w, branch.tip_revision_id, "name", {**NAME, "maxLength": 40})
    assert _pet(cur, w["line_tip"]) == {"name": NAME}
    assert _branch_tip(cur, w["main"]) == w["line_tip"]
    assert [b.name for b in store.list_draft_branches(w["tenant"], w["project"])] == ["feature/tags"]


def test_draft_branch_refuses_a_taken_name_or_label(world):
    w, _cur = world
    _draft(w)
    with pytest.raises(MergeRequestValidationError) as exc:
        _draft(w)
    assert exc.value.code == CODE_BRANCH_EXISTS
    with pytest.raises(MergeRequestValidationError) as exc:
        store.create_draft_branch(
            w["tenant"], w["project"], DraftBranchCreate(name="other", version_label="1.0.0"), w["rita"]
        )
    assert exc.value.code == CODE_LABEL_TAKEN


def test_review_gates_the_merge_which_runs_through_a_merge_session(world):
    w, cur = world
    branch = _draft(w)
    tags = {"type": "array", "items": {"type": "string"}}
    _set_prop(w, branch.tip_revision_id, "tags", tags)

    mr = _open(w, branch)
    assert mr.merge_request.target_branch_name == "main"
    assert mr.review is not None and mr.review.review.version_id == branch.tip_revision_id
    assert mr.merge_base_revision_id == w["line_tip"]
    assert [b.code for b in mr.readiness.blockers] == ["review-pending"]
    with pytest.raises(MergeRequestValidationError) as exc:
        _merge(w, mr.merge_request.id)
    assert exc.value.code == CODE_NOT_READY

    _approve(w, mr.review.review.id)
    assert store.get_merge_request(w["tenant"], w["project"], mr.merge_request.id).readiness.can_merge

    merged = _merge(w, mr.merge_request.id)
    record = merged.merge_request
    assert record.state == "merged" and record.merged_by == w["rita"] and record.merged_version_id
    assert _branch_tip(cur, w["main"]) == record.merged_version_id
    assert _pet(cur, record.merged_version_id) == {"name": NAME, "tags": tags}
    assert _pet(cur, w["line_tip"]) == {"name": NAME}
    assert merged.merge_session and merged.merge_session["status"] == "applied"
    # One transaction shares its timestamps, so the events are compared as a set, not in order.
    cur.execute(
        "SELECT to_status FROM apiome.merge_session_status_events WHERE merge_session_id = %s",
        (record.merge_session_id,),
    )
    assert sorted(r["to_status"] for r in cur.fetchall()) == ["applied", "preview", "resolving"]


def test_conflicts_surface_through_the_merge_session(world):
    w, cur = world
    branch = _draft(w)
    _set_prop(w, branch.tip_revision_id, "name", {**NAME, "maxLength": 10})
    _advance(w, w["main"], "1.0.2", "name", {**NAME, "maxLength": 20})
    mr = _open(w, branch)
    _approve(w, mr.review.review.id)

    with pytest.raises(MergeRequestValidationError) as exc:
        _merge(w, mr.merge_request.id)
    assert exc.value.code == CODE_CONFLICTS
    assert exc.value.extra["conflicts"]

    detail = store.get_merge_request(w["tenant"], w["project"], mr.merge_request.id)
    assert detail.merge_request.state == "open"
    assert detail.merge_session and detail.merge_session["status"] == "resolving"
    assert detail.conflicts and "conflicts" in [b.code for b in detail.readiness.blockers]


def test_check_supersedes_the_previous_session(world):
    w, cur = world
    branch = _draft(w)
    mr = _open(w, branch)
    first = (
        store.check_merge_request("acme", _auth(w), w["rita"], w["project"], mr.merge_request.id, MergeRequestMerge())
    )
    second = (
        store.check_merge_request("acme", _auth(w), w["rita"], w["project"], mr.merge_request.id, MergeRequestMerge())
    )
    assert first.merge_session["id"] != second.merge_session["id"]
    cur.execute("SELECT status FROM apiome.merge_sessions WHERE id = %s", (first.merge_session["id"],))
    assert cur.fetchone()["status"] == "aborted"


def test_open_refuses_a_non_draft_source_and_a_second_open_request(world):
    w, _cur = world
    with pytest.raises(MergeRequestValidationError) as exc:
        store.open_merge_request(
            w["tenant"],
            w["project"],
            MergeRequestCreate(source_branch="main", target_branch="main", title="x", reviewers=[w["rex"]]),
            w["rita"],
        )
    assert exc.value.code == CODE_NOT_DRAFT_BRANCH
    branch = _draft(w)
    _open(w, branch)
    with pytest.raises(MergeRequestValidationError) as exc:
        _open(w, branch)
    assert exc.value.code == CODE_ALREADY_OPEN


def test_a_moved_branch_outdates_the_review_until_its_tip_is_reviewed(world):
    w, _cur = world
    branch = _draft(w)
    mr = _open(w, branch)
    _approve(w, mr.review.review.id)
    new_tip = _advance(w, branch.id, "1.0.5", "name", {**NAME, "minLength": 1})

    detail = store.get_merge_request(w["tenant"], w["project"], mr.merge_request.id)
    assert detail.review_outdated and [b.code for b in detail.readiness.blockers] == ["review-outdated"]

    detail = store.request_merge_request_review(
        w["tenant"], w["project"], mr.merge_request.id, MergeRequestReviewRequest(), w["rita"]
    )
    assert detail.review.review.version_id == new_tip and not detail.review_outdated
    assert [r.user_id for r in detail.review.reviewers] == [w["rex"]]
    old = review_store.get_review(w["tenant"], w["project"], mr.review.review.id)
    assert old.review.closed_at is not None


def test_close_withdraws_the_review_and_frees_the_branch(world):
    w, _cur = world
    branch = _draft(w)
    mr = _open(w, branch)
    closed = store.close_merge_request(w["tenant"], w["project"], mr.merge_request.id, w["rita"])
    assert closed.merge_request.state == "closed" and closed.merge_request.closed_by == w["rita"]
    assert review_store.get_review(w["tenant"], w["project"], mr.review.review.id).review.closed_at is not None
    reopened = _open(w, branch)
    assert reopened.merge_request.id != mr.merge_request.id
    page, total = store.list_merge_requests(w["tenant"], w["project"], state="open", include_total=True)
    assert total == 1 and page.items[0].id == reopened.merge_request.id
    assert page.has_more is False and page.next_cursor is None
