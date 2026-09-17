"""The three-way merge engine — GNC-2.3 (#4739).

Pure rules, asserted against literals: no database, no network, no clock. Each group of tests
anchors one of the ticket's acceptance criteria.

1. *Overlapping changes become explicit conflicts* — a conflict names the exact value both sides
   moved, widening only to a subtree one side replaced outright, and carries all three values with
   a source location.
2. *Non-overlapping changes apply deterministically* — same three documents, same changes, same
   order, same merged document, however the inputs are shuffled.
3. *An active draft is never overwritten* — the engine never mutates any input, and its merged
   document is a copy the caller may do nothing with.
4. *Merge results record base, Git and draft digests* — :func:`plan_fingerprint` is the key those
   three facts form, and it is computable before any read.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from app.spec_sync import (
    MAX_VALUE_BYTES,
    STATUS_CLEAN,
    STATUS_CONFLICTED,
    STATUS_MERGEABLE,
    bounded_value,
    locate_pointer_lines,
    merge_documents,
    plan_fingerprint,
    pointer_segments,
    source_location_url,
)


def _spec(**overrides: Any) -> Dict[str, Any]:
    """A small OpenAPI document with the shapes the merge has to get right."""
    document: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/pets": {
                "get": {"summary": "List pets", "operationId": "listPets"},
                "post": {"summary": "Create a pet"},
            }
        },
        "components": {"schemas": {"Pet": {"type": "object", "properties": {"id": {"type": "string"}}}}},
    }
    document.update(copy.deepcopy(overrides))
    return document


def _at(document: Dict[str, Any], pointer: str) -> Any:
    """The value a pointer addresses, for assertions."""
    current: Any = document
    for segment in pointer_segments(pointer):
        current = current[int(segment)] if isinstance(current, list) else current[segment]
    return current


# ---------------------------------------------------------------------------------------------
# Nothing to merge
# ---------------------------------------------------------------------------------------------


def test_a_repository_that_changed_nothing_is_clean():
    base = _spec()
    outcome = merge_documents(base, _spec(), _spec(info={"title": "Pets", "version": "9.9.9"}))
    assert outcome.status == STATUS_CLEAN
    assert outcome.changes == []
    assert outcome.conflicts == []
    # The draft's own edit is still there; the merge simply had nothing to say about it.
    assert outcome.local_count == 1
    assert outcome.merged == _spec(info={"title": "Pets", "version": "9.9.9"})


def test_identical_documents_produce_a_clean_empty_merge():
    outcome = merge_documents(_spec(), _spec(), _spec())
    assert (outcome.status, outcome.local_count, outcome.agreed_count) == (STATUS_CLEAN, 0, 0)


# ---------------------------------------------------------------------------------------------
# Non-overlapping changes apply deterministically
# ---------------------------------------------------------------------------------------------


def test_an_incoming_change_the_draft_did_not_touch_is_applied():
    base = _spec()
    git = _spec()
    git["paths"]["/pets"]["get"]["description"] = "Every pet"
    draft = _spec()
    draft["paths"]["/pets"]["post"]["summary"] = "Add a pet"

    outcome = merge_documents(base, git, draft)

    assert outcome.status == STATUS_MERGEABLE
    assert [(c.pointer, c.kind) for c in outcome.changes] == [
        ("/paths/~1pets/get/description", "addition")
    ]
    assert outcome.conflicts == []
    assert outcome.local_count == 1
    # Both sides' work survives: the incoming description, and the draft's own summary.
    assert _at(outcome.merged, "/paths/~1pets/get/description") == "Every pet"
    assert _at(outcome.merged, "/paths/~1pets/post/summary") == "Add a pet"


def test_an_incoming_change_is_grouped_the_way_every_other_change_list_is():
    base = _spec()
    git = _spec()
    git["paths"]["/pets"]["get"]["summary"] = "List every pet"
    change = merge_documents(base, git, _spec()).changes[0]
    assert (change.scope, change.group) == ("operation", "GET /pets")
    assert change.label == "Changed operation GET /pets at /paths/~1pets/get/summary"


def test_a_deletion_the_draft_did_not_touch_is_applied():
    base = _spec()
    git = _spec()
    del git["paths"]["/pets"]["post"]
    outcome = merge_documents(base, git, _spec())
    assert [(c.pointer, c.kind) for c in outcome.changes] == [("/paths/~1pets/post", "deletion")]
    assert "post" not in outcome.merged["paths"]["/pets"]


def test_a_trailing_array_addition_lands_where_the_repository_put_it():
    base = _spec()
    git = _spec(servers=[{"url": "https://api.example.com"}, {"url": "https://eu.example.com"}])
    outcome = merge_documents(base, git, _spec())
    assert outcome.merged["servers"] == [
        {"url": "https://api.example.com"},
        {"url": "https://eu.example.com"},
    ]


def test_several_trailing_array_deletions_do_not_shift_each_other():
    base = _spec(servers=[{"url": "a"}, {"url": "b"}, {"url": "c"}])
    git = _spec(servers=[{"url": "a"}])
    outcome = merge_documents(base, git, _spec(servers=[{"url": "a"}, {"url": "b"}, {"url": "c"}]))
    # Removing index 1 before index 2 would leave one behind; the engine removes from the top down.
    assert outcome.merged["servers"] == [{"url": "a"}]


def test_the_merge_is_a_function_of_its_three_inputs_alone():
    base = _spec()
    git = _spec()
    git["info"]["description"] = "Pets as a service"
    git["paths"]["/pets"]["get"]["description"] = "Every pet"
    git["components"]["schemas"]["Tag"] = {"type": "object"}
    draft = _spec()
    draft["paths"]["/pets"]["post"]["operationId"] = "createPet"

    first = merge_documents(base, git, draft)
    second = merge_documents(copy.deepcopy(base), copy.deepcopy(git), copy.deepcopy(draft))
    assert [c.pointer for c in first.changes] == [c.pointer for c in second.changes]
    assert first.merged == second.merged
    # And the order of the applied changes is stable, not incidental.
    assert [c.pointer for c in first.changes] == sorted(c.pointer for c in first.changes)


def test_neither_side_is_modified_by_merging():
    base, git, draft = _spec(), _spec(), _spec()
    git["info"]["description"] = "Pets as a service"
    draft["info"]["contact"] = {"name": "Platform"}
    before = (copy.deepcopy(base), copy.deepcopy(git), copy.deepcopy(draft))
    merge_documents(base, git, draft)
    assert (base, git, draft) == before


# ---------------------------------------------------------------------------------------------
# Overlapping changes become explicit conflicts
# ---------------------------------------------------------------------------------------------


def test_two_sides_changing_one_value_conflict_with_all_three_shown():
    base = _spec()
    git = _spec()
    git["info"]["version"] = "2.0.0"
    draft = _spec()
    draft["info"]["version"] = "1.5.0"

    outcome = merge_documents(base, git, draft)

    assert outcome.status == STATUS_CONFLICTED
    assert outcome.changes == []
    conflict = outcome.conflicts[0]
    assert conflict.pointer == "/info/version"
    assert (conflict.git_kind, conflict.draft_kind) == ("update", "update")
    assert (conflict.base_value, conflict.git_value, conflict.draft_value) == (
        "1.0.0",
        "2.0.0",
        "1.5.0",
    )
    # Nothing is applied while the collision is outstanding.
    assert outcome.merged == draft


def test_a_collision_is_reported_at_the_exact_value_both_sides_moved():
    base = _spec()
    git = _spec()
    git["paths"]["/pets"]["get"]["summary"] = "List every pet"
    draft = _spec()
    # The draft edited the same operation, but only the summary collides; dropping the
    # operationId is the draft's own business and stays out of the conflict.
    draft["paths"]["/pets"]["get"] = {"summary": "Pets"}

    outcome = merge_documents(base, git, draft)
    conflict = outcome.conflicts[0]
    assert [c.pointer for c in outcome.conflicts] == ["/paths/~1pets/get/summary"]
    assert (conflict.scope, conflict.group) == ("operation", "GET /pets")
    assert conflict.draft_value == "Pets"
    assert outcome.local_count == 1


def test_a_conflict_widens_to_the_subtree_a_side_replaced_outright():
    base = _spec()
    git = _spec()
    git["paths"]["/pets"]["get"]["summary"] = "List every pet"
    draft = _spec()
    # The draft replaced the operation with something of another shape, so there is no narrower
    # place to describe the collision at — and saying "summary" would hide what really happened.
    draft["paths"]["/pets"]["get"] = "see the guide"

    conflict = merge_documents(base, git, draft).conflicts[0]
    assert conflict.pointer == "/paths/~1pets/get"
    assert (conflict.scope, conflict.group) == ("operation", "GET /pets")
    assert conflict.draft_value == "see the guide"
    assert conflict.git_value["summary"] == "List every pet"


def test_two_incoming_changes_under_one_replaced_subtree_are_one_conflict():
    base = _spec()
    git = _spec()
    git["components"]["schemas"]["Pet"]["properties"]["name"] = {"type": "string"}
    git["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    git["components"]["schemas"]["Pet"]["description"] = "A pet"
    draft = _spec()
    # The draft dropped the whole property bag, which both incoming additions land inside.
    del draft["components"]["schemas"]["Pet"]["properties"]

    outcome = merge_documents(base, git, draft)
    assert [c.pointer for c in outcome.conflicts] == ["/components/schemas/Pet/properties"]
    assert outcome.conflicts[0].scope == "schema"
    assert outcome.conflicts[0].draft_kind == "deletion"
    # The description touched nothing the draft touched, so it still applies.
    assert [c.pointer for c in outcome.changes] == ["/components/schemas/Pet/description"]


def test_one_side_deleting_what_the_other_changed_is_a_conflict():
    base = _spec()
    git = _spec()
    git["paths"]["/pets"]["post"]["summary"] = "Add a pet"
    draft = _spec()
    del draft["paths"]["/pets"]["post"]

    conflict = merge_documents(base, git, draft).conflicts[0]
    assert conflict.pointer == "/paths/~1pets/post"
    assert (conflict.git_kind, conflict.draft_kind) == ("update", "deletion")
    assert conflict.draft_value is None


def test_both_sides_adding_the_same_value_is_not_a_conflict():
    base = _spec()
    git = _spec()
    git["info"]["description"] = "Pets as a service"
    draft = _spec()
    draft["info"]["description"] = "Pets as a service"

    outcome = merge_documents(base, git, draft)
    assert outcome.conflicts == []
    assert outcome.changes == []
    assert outcome.agreed_count == 1
    assert outcome.status == STATUS_MERGEABLE


def test_both_sides_deleting_the_same_thing_is_not_a_conflict():
    base = _spec()
    git = _spec()
    draft = _spec()
    del git["paths"]["/pets"]["post"]
    del draft["paths"]["/pets"]["post"]
    outcome = merge_documents(base, git, draft)
    assert (outcome.conflicts, outcome.agreed_count) == ([], 1)


def test_conflicts_come_back_in_pointer_order_and_are_capped():
    base = _spec(components={"schemas": {}})
    git = _spec(components={"schemas": {}})
    draft = _spec(components={"schemas": {}})
    for index in range(5):
        base["components"]["schemas"][f"S{index}"] = {"type": "object"}
        git["components"]["schemas"][f"S{index}"] = {"type": "string"}
        draft["components"]["schemas"][f"S{index}"] = {"type": "integer"}

    outcome = merge_documents(base, git, draft, max_conflicts=3)
    assert outcome.conflicts_truncated is True
    assert [c.pointer for c in outcome.conflicts] == [
        "/components/schemas/S0/type",
        "/components/schemas/S1/type",
        "/components/schemas/S2/type",
    ]


def test_a_conflict_carries_the_source_location_it_was_given():
    base = _spec()
    git = _spec()
    git["info"]["version"] = "2.0.0"
    draft = _spec()
    draft["info"]["version"] = "1.5.0"
    conflict = merge_documents(
        base,
        git,
        draft,
        lines={"/info/version": 4},
        source_file="spec/openapi.yaml",
    ).conflicts[0]
    assert (conflict.source_file, conflict.source_line) == ("spec/openapi.yaml", 4)


# ---------------------------------------------------------------------------------------------
# Locating a pointer in the source
# ---------------------------------------------------------------------------------------------


YAML_SOURCE = """openapi: 3.1.0
info:
  title: Pets
  version: 1.0.0
servers:
  - url: https://api.example.com
paths:
  /pets:
    get:
      summary: List pets
"""


def test_a_yaml_pointer_reports_the_line_of_its_key_not_its_value():
    lines = locate_pointer_lines(YAML_SOURCE)
    # `version: 1.0.0` is on line 4; a block value's own node would say the same, but a nested
    # mapping's would not — `/info` must be the `info:` line, not `title:`.
    assert lines["/info/version"] == 4
    assert lines["/info"] == 2
    assert lines["/paths/~1pets/get/summary"] == 10
    assert lines["/servers/0/url"] == 6
    assert lines[""] == 1


def test_json_is_located_by_the_same_composer():
    lines = locate_pointer_lines('{\n  "openapi": "3.1.0",\n  "info": {\n    "title": "Pets"\n  }\n}')
    assert lines["/info/title"] == 4


@pytest.mark.parametrize("text", ["", "   ", "openapi: [unclosed"])
def test_source_that_cannot_be_composed_simply_has_no_lines(text):
    assert locate_pointer_lines(text) == {}


def test_an_oversized_document_is_not_composed_at_all():
    assert locate_pointer_lines(YAML_SOURCE, max_bytes=8) == {}


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("github", "https://github.com/o/r/blob/abc123/spec/openapi.yaml#L4"),
        ("gitlab", "https://gitlab.com/o/r/-/blob/abc123/spec/openapi.yaml#L4"),
        ("bitbucket", "https://bitbucket.org/o/r/src/abc123/spec/openapi.yaml#lines-4"),
    ],
)
def test_a_source_location_links_a_line_at_a_commit(provider, expected):
    host = {"github": "github.com", "gitlab": "gitlab.com", "bitbucket": "bitbucket.org"}[provider]
    assert (
        source_location_url(provider, f"https://{host}/o/r", "abc123", "spec/openapi.yaml", 4)
        == expected
    )


def test_a_source_location_without_a_line_still_links_the_file():
    assert source_location_url(
        "github", "https://github.com/o/r", "abc123", "openapi.yaml", None
    ) == "https://github.com/o/r/blob/abc123/openapi.yaml"


@pytest.mark.parametrize(
    "provider,repo,sha,path",
    [
        ("gitea", "https://gitea.io/o/r", "abc", "openapi.yaml"),
        ("github", "", "abc", "openapi.yaml"),
        ("github", "https://github.com/o/r", "", "openapi.yaml"),
        ("github", "https://github.com/o/r", "abc", ""),
    ],
)
def test_a_location_that_cannot_be_linked_says_nothing(provider, repo, sha, path):
    assert source_location_url(provider, repo, sha, path, 1) == ""


# ---------------------------------------------------------------------------------------------
# The rerun key and the stored bounds
# ---------------------------------------------------------------------------------------------


def test_the_same_three_documents_fingerprint_the_same_way():
    first = plan_fingerprint("binding", "base-sha", "git-sha", "sha256:draft")
    assert first == plan_fingerprint("binding", "base-sha", "git-sha", "sha256:draft")
    assert first.startswith("sha256:")


@pytest.mark.parametrize("position", [0, 1, 2, 3])
def test_changing_any_one_input_changes_the_rerun_key(position):
    parts = ["binding", "base-sha", "git-sha", "sha256:draft"]
    moved = list(parts)
    moved[position] = "other"
    assert plan_fingerprint(*parts) != plan_fingerprint(*moved)


def test_the_rerun_key_cannot_be_forged_by_moving_a_boundary():
    # Length-prefixing is what stops ("ab", "c", …) and ("a", "bc", …) colliding.
    assert plan_fingerprint("ab", "c", "x", "y") != plan_fingerprint("a", "bc", "x", "y")


def test_an_ordinary_value_is_stored_as_it_is():
    value = {"type": "object", "properties": {"id": {"type": "string"}}}
    assert bounded_value(value) is value


def test_an_enormous_value_is_replaced_by_a_marker():
    marker = bounded_value({"blob": "x" * (MAX_VALUE_BYTES + 1)})
    assert marker["$truncated"] is True
    assert marker["bytes"] > MAX_VALUE_BYTES


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_every_legal_json_value_survives_bounding(value):
    assert bounded_value(value) == value
