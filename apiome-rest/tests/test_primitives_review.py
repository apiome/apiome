"""Unit tests for the pure import-review logic (#3464).

:mod:`app.primitives_review` classifies an imported definition against the existing registry
(New / Identical / Conflict) and turns a caller's resolution choice (keep / overwrite / rename)
into a concrete commit decision. These tests exercise that logic in isolation — no DB, no HTTP.
"""

from app.primitives_review import (
    ACTION_KEEP,
    ACTION_OVERWRITE,
    ACTION_RENAME,
    OUTCOME_IDENTICAL,
    OUTCOME_IMPORTED,
    OUTCOME_OVERWRITTEN,
    OUTCOME_RENAMED,
    OUTCOME_SKIPPED,
    STATUS_CONFLICT,
    STATUS_IDENTICAL,
    STATUS_NEW,
    allowed_resolutions,
    classify_status,
    decide,
    schemas_equivalent,
)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def test_classify_new_when_no_existing():
    assert classify_status(None, {"type": "string"}) == STATUS_NEW


def test_classify_identical_when_schema_matches():
    existing = {"schema": {"type": "string", "$id": "x"}}
    assert classify_status(existing, {"type": "string", "$id": "x"}) == STATUS_IDENTICAL


def test_classify_conflict_when_schema_differs():
    existing = {"schema": {"type": "string", "$id": "x"}}
    assert classify_status(existing, {"type": "number", "$id": "x"}) == STATUS_CONFLICT


def test_schemas_equivalent_is_deep():
    a = {"type": "object", "properties": {"a": {"type": "string"}}}
    b = {"type": "object", "properties": {"a": {"type": "string"}}}
    c = {"type": "object", "properties": {"a": {"type": "number"}}}
    assert schemas_equivalent(a, b)
    assert not schemas_equivalent(a, c)


# --------------------------------------------------------------------------- #
# Allowed resolutions (for the review UI)
# --------------------------------------------------------------------------- #


def test_only_conflicts_offer_resolutions():
    assert allowed_resolutions(STATUS_CONFLICT) == [
        ACTION_KEEP,
        ACTION_OVERWRITE,
        ACTION_RENAME,
    ]
    assert allowed_resolutions(STATUS_NEW) == []
    assert allowed_resolutions(STATUS_IDENTICAL) == []


# --------------------------------------------------------------------------- #
# Decision logic
# --------------------------------------------------------------------------- #


def test_new_decides_create():
    d = decide(STATUS_NEW)
    assert d.action == "create"
    assert d.outcome == OUTCOME_IMPORTED


def test_identical_dedupes_by_default():
    d = decide(STATUS_IDENTICAL, dedupe=True)
    assert d.action == "skip"
    assert d.outcome == OUTCOME_IDENTICAL


def test_identical_without_dedupe_falls_through_to_resolution():
    # With dedupe off, an identical type honors the caller's resolution (here: overwrite).
    d = decide(STATUS_IDENTICAL, action=ACTION_OVERWRITE, dedupe=False)
    assert d.action == "update"
    assert d.outcome == OUTCOME_OVERWRITTEN


def test_conflict_keep_is_the_default_and_surfaces_as_skipped():
    d = decide(STATUS_CONFLICT)
    assert d.action == "skip"
    assert d.outcome == OUTCOME_SKIPPED
    assert "unresolved" in (d.reason or "")


def test_conflict_overwrite_decides_update():
    d = decide(STATUS_CONFLICT, action=ACTION_OVERWRITE)
    assert d.action == "update"
    assert d.outcome == OUTCOME_OVERWRITTEN


def test_conflict_rename_decides_rename_with_new_name():
    d = decide(STATUS_CONFLICT, action=ACTION_RENAME, new_name="money_v2")
    assert d.action == "rename"
    assert d.outcome == OUTCOME_RENAMED
    assert d.new_name == "money_v2"


def test_rename_without_new_name_is_an_error():
    d = decide(STATUS_CONFLICT, action=ACTION_RENAME, new_name=None)
    assert d.action == "error"
    assert "new_name" in (d.reason or "")


def test_unknown_action_defaults_to_keep():
    d = decide(STATUS_CONFLICT, action="bogus")
    assert d.action == "skip"
    assert d.outcome == OUTCOME_SKIPPED


def test_empty_string_action_defaults_to_keep():
    # An empty action string is just another unrecognized value: it degrades to the safe
    # default (keep → surfaced as skipped), never overwrite/rename. The HTTP layer rejects it
    # upstream with a 400; this documents the pure function's defensive fallback explicitly.
    d = decide(STATUS_CONFLICT, action="")
    assert d.action == "skip"
    assert d.outcome == OUTCOME_SKIPPED
