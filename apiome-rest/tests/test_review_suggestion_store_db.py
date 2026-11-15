"""Suggested changes against a live Postgres — COL-4.2 (#4526).

One always-rolled-back transaction. Seeds a draft version with a ``Pet`` class and its ``name``
property, an open review requested by Rita with Rex as reviewer, and Eddie as a project editor.

Acceptance: a reviewer proposes a concrete field edit and the author applies it in one click,
producing exactly the proposed model change; a rejection is recorded; an element changed since
the proposal is detected (``stale`` with conflict paths) and not silently misapplied.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import review_suggestion_store as store
from app.config import settings
from app.database import Database
from app.review_suggestions import (
    CODE_FORBIDDEN,
    CODE_INVALID_PATCH,
    CODE_NOT_OPEN,
    CODE_STALE,
    CODE_TARGET_NOT_FOUND,
    SuggestionCreate,
    SuggestionValidationError,
)
from app.reviews import CODE_VERSION_PUBLISHED
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db

PROP_DATA = {"type": "string", "maxLength": 50}
CLASS_SCHEMA = {"type": "object", "required": ["name"]}


@pytest.fixture
def world(monkeypatch) -> Iterator[Tuple[Dict[str, Any], Any]]:
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.review_suggestions') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V376 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(store, "db", db)
    try:
        with conn.cursor() as cur:
            sfx = uuid.uuid4().hex[:10]
            w: Dict[str, Any] = {}
            for who in ("rita", "rex", "eddie", "olga"):
                cur.execute(
                    "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x') RETURNING id::text AS id",
                    (who.title(), f"{who}-{sfx}@example.com"),
                )
                w[who] = cur.fetchone()["id"]

            def one(sql, params):
                cur.execute(sql + " RETURNING id::text AS id", params)
                return cur.fetchone()["id"]

            w["tenant"] = one("INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s)", (f"s {sfx}", f"s-{sfx}"))
            w["project"] = one(
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'P', %s)",
                (w["tenant"], w["rita"], f"p-{sfx}"),
            )
            w["version"] = one(
                "INSERT INTO apiome.versions (project_id, creator_id, version_id) VALUES (%s, %s, '1.0.0')",
                (w["project"], w["rita"]),
            )
            w["class"] = one(
                "INSERT INTO apiome.classes (version_id, name, description, schema) VALUES (%s, 'Pet', 'A pet', %s)",
                (w["version"], json.dumps(CLASS_SCHEMA)),
            )
            source = one(
                "INSERT INTO apiome.properties (project_id, name, data) VALUES (%s, 'name', %s)",
                (w["project"], json.dumps(PROP_DATA)),
            )
            w["prop"] = one(
                "INSERT INTO apiome.class_properties (class_id, property_id, name, description, data) "
                "VALUES (%s, %s, 'name', 'The pet''s name', %s)",
                (w["class"], source, json.dumps(PROP_DATA)),
            )
            w["review_id"] = one(
                "INSERT INTO apiome.reviews (tenant_id, project_id, version_id, requested_by, spec_fingerprint) "
                "VALUES (%s, %s, %s, %s, 'sha256:x')",
                (w["tenant"], w["project"], w["version"], w["rita"]),
            )
            one("INSERT INTO apiome.review_reviewers (review_id, round, user_id) VALUES (%s, 1, %s)", (w["review_id"], w["rex"]))
            w["review"] = {"id": w["review_id"], "project_id": w["project"], "requested_by": w["rita"], "round": 1, "closed_at": None}
            w["ver"] = {"id": w["version"], "published": False}
            w["cur"] = cur
            yield w, cur
    finally:
        conn.rollback()
        conn.close()


def _propose(w, who="rex", *, target="prop", patch=None, editor=False):
    body = SuggestionCreate(
        target_type="property" if target == "prop" else "class",
        target_id=w[target],
        patch=patch or [{"op": "replace", "path": "/data/maxLength", "value": 100}],
        note="Names can be longer",
    )
    return store.create_suggestion(w["tenant"], w["review"], w["ver"], w[who], body, is_editor=editor)


def _prop(cur, w):
    cur.execute("SELECT description, data FROM apiome.class_properties WHERE id = %s", (w["prop"],))
    return cur.fetchone()


def test_reviewer_proposes_and_requester_applies_the_exact_change(world):
    w, cur = world
    s = _propose(w)
    assert s.status == "open" and s.target_label == "Pet.name" and not s.stale
    assert s.base == {"description": "The pet's name", "data": PROP_DATA}
    assert s.proposed == {"description": "The pet's name", "data": {"type": "string", "maxLength": 100}}
    result = store.apply_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False)
    assert result.suggestion.status == "applied" and result.suggestion.decided_by == w["rita"]
    assert result.merged_around is False
    row = _prop(cur, w)
    assert {"description": row["description"], "data": row["data"]} == s.proposed


def test_class_suggestion_edits_the_class_row(world):
    w, cur = world
    s = _propose(w, target="class", patch=[{"op": "add", "path": "/schema/required/-", "value": "id"}])
    store.apply_suggestion(w["review"], w["ver"], s.id, w["eddie"], is_editor=True)
    cur.execute("SELECT schema FROM apiome.classes WHERE id = %s", (w["class"],))
    assert cur.fetchone()["schema"]["required"] == ["name", "id"]


def test_rejection_is_recorded_and_final(world):
    w, cur = world
    s = _propose(w)
    r = store.reject_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False, reason="Keep 50")
    assert (r.status, r.reason, r.decided_by) == ("rejected", "Keep 50", w["rita"])
    assert _prop(cur, w)["data"] == PROP_DATA
    with pytest.raises(SuggestionValidationError) as err:
        store.apply_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False)
    assert err.value.code == CODE_NOT_OPEN


def test_an_overlapping_edit_since_is_detected_not_misapplied(world):
    w, cur = world
    s = _propose(w)
    cur.execute("UPDATE apiome.class_properties SET data = %s WHERE id = %s",
                (json.dumps({"type": "string", "maxLength": 80}), w["prop"]))
    listed = store.list_suggestions(w["review"])[0]
    assert listed.stale is True and listed.conflict_paths == ["data.maxLength"]
    with pytest.raises(SuggestionValidationError) as err:
        store.apply_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False)
    assert err.value.code == CODE_STALE and err.value.conflict_paths == ["data.maxLength"]
    assert _prop(cur, w)["data"]["maxLength"] == 80
    after = store.list_suggestions(w["review"])[0]
    assert after.status == "stale" and after.conflict_paths == ["data.maxLength"]


def test_an_unrelated_edit_since_is_merged_around(world):
    w, cur = world
    s = _propose(w)
    cur.execute("UPDATE apiome.class_properties SET description = 'Display name' WHERE id = %s", (w["prop"],))
    result = store.apply_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False)
    assert result.merged_around is True
    row = _prop(cur, w)
    assert row["description"] == "Display name" and row["data"]["maxLength"] == 100


def test_a_deleted_target_goes_stale(world):
    w, cur = world
    s = _propose(w)
    cur.execute("DELETE FROM apiome.class_properties WHERE id = %s", (w["prop"],))
    with pytest.raises(SuggestionValidationError) as err:
        store.apply_suggestion(w["review"], w["ver"], s.id, w["rita"], is_editor=False)
    assert err.value.conflict_paths == ["<deleted>"]


def test_who_may_propose_and_decide(world):
    w, _ = world
    with pytest.raises(SuggestionValidationError) as outsider:
        _propose(w, "olga")
    assert outsider.value.code == CODE_FORBIDDEN
    s = _propose(w)
    for who, editor in (("rex", False), ("olga", False)):
        with pytest.raises(SuggestionValidationError) as err:
            store.apply_suggestion(w["review"], w["ver"], s.id, w[who], is_editor=editor)
        assert err.value.code == CODE_FORBIDDEN
    # An editor cannot apply their own suggestion either, but the author may withdraw it.
    mine = _propose(w, "eddie", editor=True, patch=[{"op": "replace", "path": "/description", "value": "x"}])
    with pytest.raises(SuggestionValidationError):
        store.apply_suggestion(w["review"], w["ver"], mine.id, w["eddie"], is_editor=True)
    assert store.reject_suggestion(w["review"], w["ver"], s.id, w["rex"], is_editor=False).status == "rejected"


@pytest.mark.parametrize(
    "patch",
    [
        [{"op": "add", "path": "/name", "value": "x"}],
        [{"op": "remove", "path": "/data"}],
        [{"op": "replace", "path": "/data", "value": "string"}],
        [{"op": "replace", "path": "/data/maxLength", "value": 50}],
        [{"op": "replace", "path": "/data/nope", "value": 1}],
    ],
)
def test_invalid_patches_are_refused(world, patch):
    w, _ = world
    with pytest.raises(SuggestionValidationError) as err:
        _propose(w, patch=patch)
    assert err.value.code == CODE_INVALID_PATCH


def test_targets_outside_the_version_and_published_versions_are_refused(world):
    w, _ = world
    w_other = dict(w, prop=str(uuid.uuid4()))
    with pytest.raises(SuggestionValidationError) as err:
        _propose(w_other)
    assert err.value.code == CODE_TARGET_NOT_FOUND
    w["ver"] = {"id": w["version"], "published": True}
    with pytest.raises(SuggestionValidationError) as pub:
        _propose(w)
    assert pub.value.code == CODE_VERSION_PUBLISHED
