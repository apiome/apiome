"""The suggestion patch model — COL-4.2 (#4526): the RFC 6902 applier and the rebase onto the
merge-session engine."""

from __future__ import annotations

import pytest

from app.suggestion_patch import MAX_PATCH_OPS, PatchError, apply_patch, parse_pointer, rebase_suggestion

PROP = {"description": "The pet's name", "data": {"type": "string", "maxLength": 50, "enum": ["a", "b"]}}


def test_replace_add_remove_and_test():
    out = apply_patch(PROP, [
        {"op": "test", "path": "/data/type", "value": "string"},
        {"op": "replace", "path": "/description", "value": "Display name"},
        {"op": "add", "path": "/data/minLength", "value": 1},
        {"op": "remove", "path": "/data/maxLength"},
        {"op": "add", "path": "/data/enum/-", "value": "c"},
        {"op": "add", "path": "/data/enum/0", "value": "z"},
    ])
    assert out == {"description": "Display name", "data": {"type": "string", "minLength": 1, "enum": ["z", "a", "b", "c"]}}
    assert PROP["data"]["maxLength"] == 50  # the input is never mutated


def test_pointer_escapes():
    assert parse_pointer("/data/a~1b/c~0d") == ["data", "a/b", "c~d"]
    out = apply_patch({"description": None, "data": {}}, [{"op": "add", "path": "/data/x~1y", "value": 1}])
    assert out["data"] == {"x/y": 1}


@pytest.mark.parametrize(
    "patch",
    [
        [],
        [{"op": "move", "path": "/description", "from": "/x"}],
        [{"op": "replace", "path": "", "value": {}}],
        [{"op": "replace", "path": "description", "value": "x"}],
        [{"op": "replace", "path": "/nope", "value": 1}],
        [{"op": "remove", "path": "/data/enum/5"}],
        [{"op": "replace", "path": "/data/enum/01", "value": 1}],
        [{"op": "test", "path": "/data/type", "value": "integer"}],
        [{"op": "add", "path": "/data/type/x", "value": 1}],
        [{"op": "replace", "path": "/description"}],
        [{"op": "add", "path": "/description", "value": 1}] * (MAX_PATCH_OPS + 1),
    ],
)
def test_malformed_or_inapplicable_patches_are_refused(patch):
    with pytest.raises(PatchError):
        apply_patch(PROP, patch)


def test_rebase_takes_the_proposal_when_nothing_changed():
    proposed = apply_patch(PROP, [{"op": "replace", "path": "/description", "value": "Display name"}])
    assert rebase_suggestion(PROP, PROP, proposed) == (proposed, [])


def test_rebase_merges_around_an_unrelated_edit():
    proposed = apply_patch(PROP, [{"op": "replace", "path": "/description", "value": "Display name"}])
    current = apply_patch(PROP, [{"op": "replace", "path": "/data/maxLength", "value": 80}])
    merged, conflicts = rebase_suggestion(PROP, current, proposed)
    assert conflicts == []
    assert merged == {"description": "Display name", "data": {**PROP["data"], "maxLength": 80}}


def test_rebase_reports_an_overlapping_edit():
    proposed = apply_patch(PROP, [{"op": "replace", "path": "/data/maxLength", "value": 100}])
    current = apply_patch(PROP, [{"op": "replace", "path": "/data/maxLength", "value": 80}])
    assert rebase_suggestion(PROP, current, proposed) == (None, ["data.maxLength"])


def test_rebase_reports_a_deleted_element():
    assert rebase_suggestion(PROP, None, PROP) == (None, ["<deleted>"])


def test_rebase_is_a_noop_when_already_applied_by_hand():
    proposed = apply_patch(PROP, [{"op": "replace", "path": "/description", "value": "Display name"}])
    assert rebase_suggestion(PROP, proposed, proposed) == (proposed, [])
