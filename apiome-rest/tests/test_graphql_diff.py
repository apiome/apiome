"""Tests for the GraphQL diff / breaking-change classifier (MFI-10.5, #3774).

The acceptance criterion is that **removing a field is breaking** and **adding an enum value is
dangerous**, both **correctly surfaced** — i.e. as per-change grades on a
:class:`~app.breaking_change.ClassificationResult`, 1:1 with the canonical diff. These tests pin
four layers, mirroring ``tests/test_asyncapi_diff.py``:

* the **tool seam** (:func:`app.graphql_diff.run_graphql_diff`) — the wrapper contract is adapted
  into typed :class:`~app.graphql_diff.GraphQlDiffChange` changes, infrastructure failures raise
  :class:`~app.graphql_diff.GraphQlDiffError`, and both SDL strings are fed on ``stdin``;
* the **join** (:func:`app.graphql_diff._coordinate_for`) — a tool change's schema-coordinate
  path maps onto the canonical ``(category, key)`` it grades — a field/operation by its exact
  key, an enum-value/union-member change folded onto its owning type, a bare type by its name —
  and a non-joining change does not;
* the **overlay** (:meth:`app.graphql_diff.GraphQlBreakingChangeClassifier.classify_async` /
  :func:`app.graphql_diff.classify_graphql`) — GraphQL-Inspector's authoritative verdict replaces
  the structural grade where it joins, and the whole thing **degrades gracefully** to the
  structural baseline with no SDL / no tool;
* the **SPI registration** — the classifier resolves for the ``graphql`` format through
  :func:`app.breaking_change.classify`.

Everything here is pure (no DB/network) except the gated real-tool class, which exercises the
bundled GraphQL-Inspector end-to-end when it is present. Canonical models are built by the real
MFI-10.1/10.2 parser + normalizer so their keys match production exactly.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import pytest

from app.breaking_change import (
    ChangeClassification,
    ClassificationResult,
    Severity,
    available_breaking_change_formats,
    classify,
    get_breaking_change_classifier,
)
from app.canonical_model import CanonicalApi
from app.diff import ChangeKind, EntityCategory, diff
from app.graphql_diff import (
    GRAPHQL_DIFF_TOOL_KEY,
    GraphQlBreakingChangeClassifier,
    GraphQlDiffError,
    GraphQlDiffResult,
    _coerce_changes,
    _coordinate_for,
    classify_graphql,
    run_graphql_diff,
)
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolchainError,
    ToolExecutionError,
    ToolNotAvailableError,
)

# ===========================================================================
# SDL + model fixtures (built through the real parser + normalizer)
# ===========================================================================


def _normalize(sdl: str) -> CanonicalApi:
    """Build ``sdl`` with the real MFI-10.1 parser and normalize it (the full 10.1→10.2 path)."""
    schema = build_graphql_schema(sdl)
    return GraphQlNormalizer().normalize(schema)


def _base_sdl() -> str:
    """A schema with a root query, an object type, and an enum."""
    return """
    type Query {
      user(id: ID!): User
    }

    type User {
      id: ID!
      name: String!
      email: String
    }

    enum Status {
      ACTIVE
      INACTIVE
    }
    """


def _target_sdl() -> str:
    """The base schema with ``User.email`` removed (breaking), ``Status.PENDING`` added
    (dangerous), and a new ``Query.users`` field added (safe)."""
    return """
    type Query {
      user(id: ID!): User
      users: [User!]!
    }

    type User {
      id: ID!
      name: String!
    }

    enum Status {
      ACTIVE
      INACTIVE
      PENDING
    }
    """


# ===========================================================================
# Fake runner replaying the graphql-inspector-diff wrapper contract
# ===========================================================================


@dataclass
class _FakeRunResult:
    parsed_json: Any


class _FakeRunner:
    """A toolchain runner double returning a fixed graphql-inspector-diff wrapper payload."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: List[dict] = []

    async def run(
        self,
        key: str,
        args: Sequence[str] = (),
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        **_: Any,
    ) -> _FakeRunResult:
        self.calls.append({"key": key, "stdin": stdin, "timeout": timeout})
        return _FakeRunResult(parsed_json=self._payload)


class _RaisingRunner:
    """A toolchain runner double that raises a given error from ``run``."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise self._error


def _change(criticality: str, change_type: str, path: Optional[str], message: str = "") -> dict:
    """Build one wrapper-shaped change dict."""
    return {"criticality": criticality, "type": change_type, "path": path, "message": message}


def _diff_payload() -> dict:
    """The wrapper payload GraphQL-Inspector emits for ``_base_sdl`` → ``_target_sdl``."""
    return {
        "ok": True,
        "changes": [
            _change(
                "BREAKING",
                "FIELD_REMOVED",
                "User.email",
                "Field 'email' was removed from object type 'User'",
            ),
            _change(
                "DANGEROUS",
                "ENUM_VALUE_ADDED",
                "Status.PENDING",
                "Enum value 'PENDING' was added to enum 'Status'",
            ),
            _change(
                "NON_BREAKING",
                "FIELD_ADDED",
                "Query.users",
                "Field 'users' was added to object type 'Query'",
            ),
        ],
    }


def _grade_for(result: ClassificationResult, key: str) -> ChangeClassification:
    """Return the single classification for ``key`` (asserting exactly one)."""
    matches = [c for c in result.classifications if c.key == key]
    assert len(matches) == 1, f"expected exactly one grade for {key!r}, got {matches}"
    return matches[0]


def _build_change(criticality: str, change_type: str, path: Optional[str]):
    """Build a GraphQlDiffChange from the wrapper-shaped dict (test helper)."""
    return _coerce_changes([_change(criticality, change_type, path)])[0]


# ===========================================================================
# Tool seam: run_graphql_diff over a fake runner
# ===========================================================================


async def test_run_graphql_diff_parses_and_classifies_payload() -> None:
    runner = _FakeRunner(_diff_payload())
    result = await run_graphql_diff("type Query { x: String }", "type Query { x: String }", runner=runner)

    assert isinstance(result, GraphQlDiffResult)
    assert result.has_breaking
    assert {c.path for c in result.breaking} == {"User.email"}
    assert {c.path for c in result.dangerous} == {"Status.PENDING"}
    assert {c.path for c in result.non_breaking} == {"Query.users"}


async def test_run_graphql_diff_feeds_both_sdl_strings_on_stdin() -> None:
    runner = _FakeRunner({"ok": True, "changes": []})
    await run_graphql_diff("old sdl", "new sdl", runner=runner, timeout=12.5)

    assert runner.calls and runner.calls[0]["key"] == GRAPHQL_DIFF_TOOL_KEY
    assert runner.calls[0]["timeout"] == 12.5
    import json as _json

    sent = _json.loads(runner.calls[0]["stdin"])
    assert sent == {"old": "old sdl", "new": "new sdl"}


async def test_run_graphql_diff_skips_malformed_changes() -> None:
    payload = {
        "ok": True,
        "changes": [
            _change("BREAKING", "FIELD_REMOVED", "User.email"),
            "not-a-dict",
            {"criticality": "MADE_UP", "type": "FIELD_REMOVED", "path": "X.y"},  # bad criticality
            {"criticality": "BREAKING", "path": "X.y"},  # missing type
            {"criticality": "DANGEROUS", "type": "TYPE_REMOVED"},  # missing path -> defaults to None
        ],
    }
    result = await run_graphql_diff("a", "b", runner=_FakeRunner(payload))
    assert [(c.criticality, c.change_type) for c in result.changes] == [
        ("BREAKING", "FIELD_REMOVED"),
        ("DANGEROUS", "TYPE_REMOVED"),
    ]
    assert result.changes[1].path is None


async def test_run_graphql_diff_non_object_payload_raises() -> None:
    with pytest.raises(GraphQlDiffError, match="non-object"):
        await run_graphql_diff("a", "b", runner=_FakeRunner(["not", "an", "object"]))


async def test_run_graphql_diff_tool_unavailable_raises_diff_error() -> None:
    runner = _RaisingRunner(ToolNotAvailableError(GRAPHQL_DIFF_TOOL_KEY, "graphql-inspector-diff"))
    with pytest.raises(GraphQlDiffError, match="not available"):
        await run_graphql_diff("a", "b", runner=runner)


async def test_run_graphql_diff_tool_failure_raises_diff_error() -> None:
    runner = _RaisingRunner(ToolExecutionError(GRAPHQL_DIFF_TOOL_KEY, 1, "", "boom"))
    with pytest.raises(GraphQlDiffError, match="failed"):
        await run_graphql_diff("a", "b", runner=runner)
    assert isinstance(ToolExecutionError(GRAPHQL_DIFF_TOOL_KEY, 1, "", "boom"), ToolchainError)


# ===========================================================================
# The join: a tool change → a canonical coordinate
# ===========================================================================


def test_coordinate_for_field_matches_exact_two_segment_key() -> None:
    key_to_category = {"User.email": EntityCategory.FIELD, "User": EntityCategory.TYPE}
    change = _build_change("BREAKING", "FIELD_REMOVED", "User.email")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.FIELD, "User.email")


def test_coordinate_for_operation_matches_root_field_key() -> None:
    key_to_category = {"Query.users": EntityCategory.OPERATION}
    change = _build_change("NON_BREAKING", "FIELD_ADDED", "Query.users")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.OPERATION, "Query.users")


def test_coordinate_for_enum_value_falls_back_to_owning_type() -> None:
    key_to_category = {"Status": EntityCategory.TYPE}
    change = _build_change("DANGEROUS", "ENUM_VALUE_ADDED", "Status.PENDING")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.TYPE, "Status")


def test_coordinate_for_union_member_falls_back_to_owning_type() -> None:
    key_to_category = {"SearchResult": EntityCategory.TYPE}
    change = _build_change("DANGEROUS", "UNION_MEMBER_ADDED", "SearchResult.Article")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.TYPE, "SearchResult")


def test_coordinate_for_bare_type_matches_one_segment_key() -> None:
    key_to_category = {"User": EntityCategory.TYPE}
    change = _build_change("BREAKING", "TYPE_REMOVED", "User")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.TYPE, "User")


def test_coordinate_for_argument_change_falls_back_to_owning_operation() -> None:
    key_to_category = {"Query.user": EntityCategory.OPERATION}
    change = _build_change("BREAKING", "FIELD_ARGUMENT_REMOVED", "Query.user.id")
    assert _coordinate_for(change, key_to_category) == (EntityCategory.OPERATION, "Query.user")


def test_coordinate_for_no_match_returns_none() -> None:
    change = _build_change("BREAKING", "DIRECTIVE_REMOVED", "auth")
    assert _coordinate_for(change, {}) is None


def test_coordinate_for_no_path_returns_none() -> None:
    change = _build_change("BREAKING", "SCHEMA_QUERY_TYPE_CHANGED", None)
    assert _coordinate_for(change, {"Query": EntityCategory.TYPE}) is None


# ===========================================================================
# Acceptance: removing a field is breaking, adding an enum value is dangerous (overlay)
# ===========================================================================


async def test_overlay_grades_removed_field_breaking_and_added_enum_value_dangerous() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    runner = _FakeRunner(_diff_payload())

    result = await classify_graphql(base, target, runner=runner)

    # Grades line up 1:1 with the canonical diff (the diff-view join contract).
    model_diff = diff(base, target)
    assert len(result.classifications) == len(model_diff.changes)
    assert result.classifier == "graphql-inspector-diff"

    # MFI-10.5 acceptance criterion: removing a field is BREAKING...
    removed_field = _grade_for(result, "User.email")
    assert removed_field.kind is ChangeKind.REMOVED
    assert removed_field.category is EntityCategory.FIELD
    assert removed_field.severity is Severity.BREAKING
    assert removed_field.rule_id == "graphql-inspector-diff.FIELD_REMOVED"

    # ...and adding an enum value is DANGEROUS, folded onto the owning enum TYPE.
    enum_change = _grade_for(result, "Status")
    assert enum_change.kind is ChangeKind.MODIFIED
    assert enum_change.category is EntityCategory.TYPE
    assert enum_change.severity is Severity.DANGEROUS
    assert enum_change.rule_id == "graphql-inspector-diff.ENUM_VALUE_ADDED"

    # A plain addition is graded SAFE.
    added_operation = _grade_for(result, "Query.users")
    assert added_operation.kind is ChangeKind.ADDED
    assert added_operation.category is EntityCategory.OPERATION
    assert added_operation.severity is Severity.SAFE
    assert added_operation.rule_id == "graphql-inspector-diff.FIELD_ADDED"

    assert result.overall_severity is Severity.BREAKING
    assert result.breaking is True


async def test_overlay_non_joining_changes_leave_baseline_untouched() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    # Only a change with no diffed-entity match — nothing joins, so every grade stays structural.
    payload = {"ok": True, "changes": [_change("BREAKING", "DIRECTIVE_REMOVED", "auth")]}
    result = await classify_graphql(base, target, runner=_FakeRunner(payload))
    assert all(not c.rule_id.startswith("graphql-inspector-diff.") for c in result.classifications)
    # The structural baseline still grades the removed field BREAKING.
    assert _grade_for(result, "User.email").severity is Severity.BREAKING


# ===========================================================================
# Graceful degradation to the structural baseline
# ===========================================================================


async def test_degrades_when_source_sdl_absent() -> None:
    base = _normalize(_base_sdl()).model_copy(update={"raw": None})
    target = _normalize(_target_sdl())  # target.raw present, base.raw missing
    runner = _FakeRunner(_diff_payload())

    result = await classify_graphql(base, target, runner=runner)
    assert runner.calls == []  # the tool was never invoked
    # Structural grades still classify the removed field as breaking.
    assert _grade_for(result, "User.email").severity is Severity.BREAKING
    assert all(not c.rule_id.startswith("graphql-inspector-diff.") for c in result.classifications)


async def test_degrades_when_tool_unavailable() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    runner = _RaisingRunner(ToolNotAvailableError(GRAPHQL_DIFF_TOOL_KEY, "graphql-inspector-diff"))

    result = await classify_graphql(base, target, runner=runner)
    assert runner.calls == 1  # it tried, then fell back
    assert _grade_for(result, "User.email").severity is Severity.BREAKING
    assert result.classifier == "graphql-inspector-diff"
    assert all(not c.rule_id.startswith("graphql-inspector-diff.") for c in result.classifications)


async def test_identical_models_classify_safe_with_tool() -> None:
    base = _normalize(_base_sdl())
    runner = _FakeRunner({"ok": True, "changes": []})
    result = await classify_graphql(base, _normalize(_base_sdl()), runner=runner)
    assert result.classifications == []
    assert result.overall_severity is Severity.SAFE
    assert result.breaking is False
    assert result.counts_by_severity == {}


# ===========================================================================
# Determinism + serialization
# ===========================================================================


async def test_overlay_is_deterministic() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    first = await classify_graphql(base, target, runner=_FakeRunner(_diff_payload()))
    second = await classify_graphql(base, target, runner=_FakeRunner(_diff_payload()))
    assert first.model_dump() == second.model_dump()


async def test_result_round_trips_through_json() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    result = await classify_graphql(base, target, runner=_FakeRunner(_diff_payload()))
    reloaded = ClassificationResult.model_validate_json(result.model_dump_json())
    assert reloaded == result


# ===========================================================================
# SPI registration + sync (structural) dispatch
# ===========================================================================


def test_classifier_registered_for_graphql() -> None:
    cls = get_breaking_change_classifier("graphql")
    assert cls is not None
    assert issubclass(cls, GraphQlBreakingChangeClassifier)
    assert "graphql" in available_breaking_change_formats()


def test_sync_classify_dispatches_to_graphql_structural_baseline() -> None:
    """The sync SPI resolves the GraphQL classifier and grades structurally (no tool)."""
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    result = classify(diff(base, target), base, target)
    assert result.classifier == "graphql-inspector-diff"
    # A removed field is breaking even on the pure, tool-free path.
    assert _grade_for(result, "User.email").severity is Severity.BREAKING
    assert result.overall_severity is Severity.BREAKING


async def test_classify_graphql_matches_classifier_classify_async() -> None:
    base = _normalize(_base_sdl())
    target = _normalize(_target_sdl())
    via_convenience = await classify_graphql(base, target, runner=_FakeRunner(_diff_payload()))
    classifier = GraphQlBreakingChangeClassifier()
    via_method = await classifier.classify_async(
        diff(base, target), base, target, runner=_FakeRunner(_diff_payload())
    )
    assert via_convenience == via_method


# ===========================================================================
# End-to-end (gated): the real bundled GraphQL-Inspector over normalized models
# ===========================================================================

_DIFF_AVAILABLE = bool(getattr(probe_tool(GRAPHQL_DIFF_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _DIFF_AVAILABLE,
    reason="graphql-inspector-diff tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_GRAPHQL_INSPECTOR_DIFF_BIN)",
)
class TestRealGraphQlDiff:
    """Classifies a real breaking + dangerous change end-to-end when GraphQL-Inspector is present."""

    async def test_field_removed_and_enum_value_added_classified(self) -> None:
        base = _normalize(_base_sdl())
        target = _normalize(_target_sdl())
        result = await classify_graphql(base, target)

        assert result.classifier == "graphql-inspector-diff"
        assert _grade_for(result, "User.email").severity is Severity.BREAKING
        assert _grade_for(result, "User.email").rule_id == "graphql-inspector-diff.FIELD_REMOVED"
        assert _grade_for(result, "Status").severity is Severity.DANGEROUS
        assert result.overall_severity is Severity.BREAKING

        # Deterministic: the same pair grades identically.
        again = await classify_graphql(base, target)
        assert again.model_dump() == result.model_dump()

    async def test_identical_documents_have_no_changes(self) -> None:
        base = _normalize(_base_sdl())
        result = await classify_graphql(base, _normalize(_base_sdl()))
        assert result.classifications == []
        assert result.overall_severity is Severity.SAFE
