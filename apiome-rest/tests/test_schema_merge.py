"""Unit tests for Git-style schema merge helpers (#738)."""

import json

from app.schema_merge import (
    compare_schemas,
    compute_merge_bases_from_common,
    json_equal,
    merge_components_schemas_three_way,
    merge_json_three_way,
    schema_merge_materializable_paths,
)


def test_merge_json_three_way_simple() -> None:
    merged, conflicts = merge_json_three_way({"a": 1}, {"a": 1, "b": 2}, {"a": 1, "c": 3}, "root")
    assert not conflicts
    assert merged == {"a": 1, "b": 2, "c": 3}


def test_merge_json_three_way_conflict() -> None:
    merged, conflicts = merge_json_three_way({"a": 1}, {"a": 2}, {"a": 3}, "root")
    assert merged is None
    assert conflicts


def test_merge_components_three_way_no_conflict() -> None:
    base = {"A": {"type": "object"}}
    ours = {"A": {"type": "object"}, "B": {"type": "string"}}
    theirs = {"A": {"type": "object"}, "C": {"type": "number"}}
    merged, conflicts = merge_components_schemas_three_way(base, ours, theirs)
    assert not conflicts
    assert merged and "B" in merged and "C" in merged


def test_compare_schemas_detects_added_schema() -> None:
    s1 = {"components": {"schemas": {"X": {"type": "object"}}}}
    s2 = {"components": {"schemas": {"X": {"type": "object"}, "Y": {"type": "string"}}}}
    diff = compare_schemas(json.dumps(s1), json.dumps(s2))
    assert len(diff.added) >= 1
    assert any(d.path == "schemas.Y" for d in diff.added)


def test_json_equal_dict() -> None:
    assert json_equal({"a": 1}, {"a": 1})
    assert not json_equal({"a": 1}, {"a": 2})


def test_compute_merge_bases_linear() -> None:
    """Merge base is the newest common commit (not an ancestor of another common commit)."""

    def is_anc(anc: str, desc: str) -> bool:
        # a newest, then b, then c (oldest of this triple)
        chain = {"a": "b", "b": "c", "c": None}
        if anc == desc:
            return False
        cur: str | None = desc
        while cur:
            if cur == anc:
                return True
            cur = chain.get(cur)  # type: ignore[assignment]
        return False

    common = {"a", "b", "c"}
    bases = compute_merge_bases_from_common(common, is_anc)
    assert bases == ["a"]


def test_schema_merge_materializable_paths_ok() -> None:
    merged = {"A": {"x": 1}}
    ours = {"A": {"x": 1}}
    theirs = {"B": {"y": 2}}
    ok, bad = schema_merge_materializable_paths(merged, ours, theirs)
    assert ok
    assert not bad
