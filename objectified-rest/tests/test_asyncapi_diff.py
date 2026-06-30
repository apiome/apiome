"""Tests for the AsyncAPI diff / breaking-change classifier (MFI-8.4, #3762).

The acceptance criterion is that **a breaking and a safe change are classified correctly** and
**surfaced on the diff view** — i.e. as per-change grades on a
:class:`~app.breaking_change.ClassificationResult`, 1:1 with the canonical diff. These tests
pin four layers:

* the **tool seam** (:func:`app.asyncapi_diff.run_asyncapi_diff`) — the wrapper contract is
  adapted into typed :class:`~app.asyncapi_diff.AsyncApiDiffResult` changes, infrastructure
  failures raise :class:`~app.asyncapi_diff.AsyncApiDiffError`, and the two documents are fed
  on ``stdin``;
* the **join** (:func:`app.asyncapi_diff._coordinate_for`) — a tool change maps onto the
  canonical ``(category, key)`` it grades for v2 and v3, and deep edits do not;
* the **overlay** (:meth:`app.asyncapi_diff.AsyncApiBreakingChangeClassifier.classify_async` /
  :func:`app.asyncapi_diff.classify_asyncapi`) — ``@asyncapi/diff``'s authoritative verdict
  replaces the structural grade where it joins, ``unclassified`` keeps the structural grade,
  and the whole thing **degrades gracefully** to the structural baseline with no documents /
  no tool;
* the **SPI registration** — the classifier resolves for both AsyncAPI families through
  :func:`app.breaking_change.classify`.

Everything here is pure (no DB/network) except the gated real-tool class, which exercises the
bundled ``@asyncapi/diff`` end-to-end when it is present. Canonical models are built by the
real MFI-8.2 normalizer so their keys match production exactly.
"""

import copy
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import pytest

from app.asyncapi_diff import (
    ASYNCAPI_DIFF_TOOL_KEY,
    AsyncApiBreakingChangeClassifier,
    AsyncApiDiffError,
    AsyncApiDiffResult,
    _coordinate_for,
    classify_asyncapi,
    run_asyncapi_diff,
)
from app.asyncapi_normalizer import AsyncApiNormalizer
from app.breaking_change import (
    ChangeClassification,
    ClassificationResult,
    Severity,
    available_breaking_change_formats,
    classify,
    get_breaking_change_classifier,
)
from app.diff import ChangeKind, EntityCategory, diff
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolchainError,
    ToolExecutionError,
    ToolNotAvailableError,
)

# ===========================================================================
# Document + model fixtures (built through the real normalizer)
# ===========================================================================


def _normalize(document: dict):
    """Normalize a dereferenced AsyncAPI document into a CanonicalApi (with ``raw`` set)."""
    return AsyncApiNormalizer().normalize(copy.deepcopy(document))


def _v3_base_document() -> dict:
    """A v3 document with two channels/operations; channel map names differ from addresses."""
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "User Service", "version": "1.0.0"},
        "channels": {
            "userSignedUp": {
                "address": "user/signedup",
                "messages": {"UserSignedUp": {"name": "UserSignedUp", "payload": {"type": "object"}}},
            },
            "legacyPing": {
                "address": "legacy/ping",
                "messages": {"Ping": {"name": "Ping", "payload": {"type": "object"}}},
            },
        },
        "operations": {
            "onUserSignedUp": {"action": "receive", "channel": {"$ref": "#/channels/userSignedUp"}},
            "onLegacyPing": {"action": "receive", "channel": {"$ref": "#/channels/legacyPing"}},
        },
    }


def _v3_target_document() -> dict:
    """The v3 base with ``legacyPing`` removed (breaking) and ``userDeleted`` added (safe)."""
    document = _v3_base_document()
    document["info"]["version"] = "2.0.0"
    del document["channels"]["legacyPing"]
    del document["operations"]["onLegacyPing"]
    document["channels"]["userDeleted"] = {
        "address": "user/deleted",
        "messages": {"UserDeleted": {"name": "UserDeleted", "payload": {"type": "object"}}},
    }
    document["operations"]["onUserDeleted"] = {
        "action": "receive",
        "channel": {"$ref": "#/channels/userDeleted"},
    }
    return document


def _v2_base_document() -> dict:
    """A v2 document; channel map keys are the wire addresses, operations carry operationIds."""
    return {
        "asyncapi": "2.6.0",
        "info": {"title": "Streetlights", "version": "1.0.0"},
        "channels": {
            "light/measured": {
                "publish": {
                    "operationId": "recvLight",
                    "message": {"name": "LightMeasured", "payload": {"type": "object"}},
                }
            },
            "old/topic": {
                "subscribe": {"message": {"name": "Old", "payload": {"type": "object"}}}
            },
        },
    }


# ===========================================================================
# Fake runner replaying the asyncapi-diff wrapper contract
# ===========================================================================


@dataclass
class _FakeRunResult:
    parsed_json: Any


class _FakeRunner:
    """A toolchain runner double returning a fixed asyncapi-diff wrapper payload."""

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


def _change(action: str, change_type: str, path: List[str]) -> dict:
    """Build one wrapper-shaped change dict (pointer derived from the segments)."""
    pointer = "/" + "/".join(seg.replace("~", "~0").replace("/", "~1") for seg in path)
    return {"action": action, "type": change_type, "pointer": pointer, "path": path}


def _v3_diff_payload() -> dict:
    """The wrapper payload @asyncapi/diff emits for ``_v3_base`` → ``_v3_target``."""
    return {
        "ok": True,
        "changes": [
            _change("remove", "breaking", ["operations", "onLegacyPing"]),
            _change("add", "non-breaking", ["operations", "onUserDeleted"]),
            _change("remove", "breaking", ["channels", "legacyPing"]),
            _change("add", "non-breaking", ["channels", "userDeleted"]),
            _change("edit", "breaking", ["info", "version"]),  # does not join — stays out
        ],
    }


def _grade_for(result: ClassificationResult, key: str) -> ChangeClassification:
    """Return the single classification for ``key`` (asserting exactly one)."""
    matches = [c for c in result.classifications if c.key == key]
    assert len(matches) == 1, f"expected exactly one grade for {key!r}, got {matches}"
    return matches[0]


# ===========================================================================
# Tool seam: run_asyncapi_diff over a fake runner
# ===========================================================================


async def test_run_asyncapi_diff_parses_and_classifies_payload() -> None:
    runner = _FakeRunner(_v3_diff_payload())
    result = await run_asyncapi_diff({"asyncapi": "3.0.0"}, {"asyncapi": "3.0.0"}, runner=runner)

    assert isinstance(result, AsyncApiDiffResult)
    assert result.has_breaking
    assert {c.pointer for c in result.breaking} == {"/operations/onLegacyPing", "/channels/legacyPing", "/info/version"}
    assert {c.pointer for c in result.non_breaking} == {"/operations/onUserDeleted", "/channels/userDeleted"}
    assert result.unclassified == []


async def test_run_asyncapi_diff_feeds_both_documents_on_stdin() -> None:
    runner = _FakeRunner({"ok": True, "changes": []})
    await run_asyncapi_diff({"asyncapi": "2.6.0"}, {"asyncapi": "3.0.0"}, runner=runner, timeout=12.5)

    assert runner.calls and runner.calls[0]["key"] == ASYNCAPI_DIFF_TOOL_KEY
    assert runner.calls[0]["timeout"] == 12.5
    import json as _json

    sent = _json.loads(runner.calls[0]["stdin"])
    assert sent == {"old": {"asyncapi": "2.6.0"}, "new": {"asyncapi": "3.0.0"}}


async def test_run_asyncapi_diff_skips_malformed_changes() -> None:
    payload = {
        "ok": True,
        "changes": [
            _change("remove", "breaking", ["channels", "a"]),
            "not-a-dict",
            {"action": "explode", "type": "breaking", "path": []},  # bad action
            {"action": "add", "type": "made-up", "path": []},  # bad type
            {"action": "edit", "type": "unclassified"},  # missing path → defaults to []
        ],
    }
    result = await run_asyncapi_diff({}, {}, runner=_FakeRunner(payload))
    assert [(c.action, c.change_type) for c in result.changes] == [
        ("remove", "breaking"),
        ("edit", "unclassified"),
    ]
    assert result.changes[1].path == []


async def test_run_asyncapi_diff_non_object_payload_raises() -> None:
    with pytest.raises(AsyncApiDiffError, match="non-object"):
        await run_asyncapi_diff({}, {}, runner=_FakeRunner(["not", "an", "object"]))


async def test_run_asyncapi_diff_tool_unavailable_raises_diff_error() -> None:
    runner = _RaisingRunner(ToolNotAvailableError(ASYNCAPI_DIFF_TOOL_KEY, "asyncapi-diff"))
    with pytest.raises(AsyncApiDiffError, match="not available"):
        await run_asyncapi_diff({}, {}, runner=runner)


async def test_run_asyncapi_diff_tool_failure_raises_diff_error() -> None:
    runner = _RaisingRunner(ToolExecutionError(ASYNCAPI_DIFF_TOOL_KEY, 1, "", "boom"))
    with pytest.raises(AsyncApiDiffError, match="failed"):
        await run_asyncapi_diff({}, {}, runner=runner)
    assert isinstance(ToolExecutionError(ASYNCAPI_DIFF_TOOL_KEY, 1, "", "boom"), ToolchainError)


# ===========================================================================
# The join: a tool change → a canonical coordinate
# ===========================================================================


def test_coordinate_for_v3_channel_resolves_address() -> None:
    base = _v3_base_document()
    target = _v3_target_document()
    removed = run_change("remove", "breaking", ["channels", "legacyPing"])
    added = run_change("add", "non-breaking", ["channels", "userDeleted"])
    assert _coordinate_for(removed, base, target) == (EntityCategory.CHANNEL, "legacy/ping")
    assert _coordinate_for(added, base, target) == (EntityCategory.CHANNEL, "user/deleted")


def test_coordinate_for_v3_operation_uses_name() -> None:
    base = _v3_base_document()
    target = _v3_target_document()
    change = run_change("remove", "breaking", ["operations", "onLegacyPing"])
    assert _coordinate_for(change, base, target) == (EntityCategory.OPERATION, "onLegacyPing")


def test_coordinate_for_v2_operation_uses_operation_id_then_falls_back() -> None:
    base = _v2_base_document()
    with_id = run_change("remove", "breaking", ["channels", "light/measured", "publish"])
    assert _coordinate_for(with_id, base, base) == (EntityCategory.OPERATION, "recvLight")

    no_id = run_change("remove", "breaking", ["channels", "old/topic", "subscribe"])
    assert _coordinate_for(no_id, base, base) == (EntityCategory.OPERATION, "subscribe old/topic")


def test_coordinate_for_v2_channel_uses_map_key_as_address() -> None:
    base = _v2_base_document()
    change = run_change("remove", "breaking", ["channels", "old/topic"])
    assert _coordinate_for(change, base, base) == (EntityCategory.CHANNEL, "old/topic")


def test_coordinate_for_deep_edit_does_not_join() -> None:
    base = _v3_base_document()
    deep = run_change("edit", "breaking", ["channels", "userSignedUp", "messages", "UserSignedUp"])
    meta = run_change("edit", "breaking", ["info", "version"])
    assert _coordinate_for(deep, base, base) is None
    assert _coordinate_for(meta, base, base) is None


def run_change(action: str, change_type: str, path: List[str]):
    """Build an AsyncApiDiffChange from the wrapper-shaped dict (test helper)."""
    from app.asyncapi_diff import _coerce_changes

    return _coerce_changes([_change(action, change_type, path)])[0]


# ===========================================================================
# Acceptance: a breaking and a safe change classified correctly (overlay)
# ===========================================================================


async def test_overlay_grades_breaking_and_safe_from_tool_verdict() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    runner = _FakeRunner(_v3_diff_payload())

    result = await classify_asyncapi(base, target, runner=runner)

    # Grades line up 1:1 with the canonical diff (the diff-view join contract).
    model_diff = diff(base, target)
    assert len(result.classifications) == len(model_diff.changes)
    assert result.classifier == "asyncapi-diff"

    # The removed channel + operation are graded BREAKING by @asyncapi/diff...
    breaking_channel = _grade_for(result, "legacy/ping")
    assert breaking_channel.kind is ChangeKind.REMOVED
    assert breaking_channel.severity is Severity.BREAKING
    assert breaking_channel.rule_id == "asyncapi-diff.breaking"
    assert _grade_for(result, "onLegacyPing").severity is Severity.BREAKING

    # ...and the added channel + operation NON-BREAKING.
    safe_channel = _grade_for(result, "user/deleted")
    assert safe_channel.kind is ChangeKind.ADDED
    assert safe_channel.severity is Severity.SAFE
    assert safe_channel.rule_id == "asyncapi-diff.non-breaking"
    assert _grade_for(result, "onUserDeleted").severity is Severity.SAFE

    assert result.overall_severity is Severity.BREAKING
    assert result.breaking is True


async def test_overlay_unclassified_change_keeps_structural_grade() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    # The tool declines to classify the removed channel; the structural baseline must still
    # grade the removal BREAKING (via its own rule), never silently downgrading it.
    payload = {
        "ok": True,
        "changes": [_change("remove", "unclassified", ["channels", "legacyPing"])],
    }
    result = await classify_asyncapi(base, target, runner=_FakeRunner(payload))
    grade = _grade_for(result, "legacy/ping")
    assert grade.severity is Severity.BREAKING
    assert grade.rule_id == "removed-entity"  # structural, not asyncapi-diff.*


async def test_overlay_non_joining_changes_leave_baseline_untouched() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    # Only a deep/meta change the tool reports — nothing joins, so every grade stays structural.
    payload = {"ok": True, "changes": [_change("edit", "breaking", ["info", "version"])]}
    result = await classify_asyncapi(base, target, runner=_FakeRunner(payload))
    assert all(not c.rule_id.startswith("asyncapi-diff.") for c in result.classifications)
    # The structural baseline still grades the removed channel BREAKING.
    assert _grade_for(result, "legacy/ping").severity is Severity.BREAKING


# ===========================================================================
# Graceful degradation to the structural baseline
# ===========================================================================


async def test_degrades_when_source_documents_absent() -> None:
    base = _normalize(_v3_base_document()).model_copy(update={"raw": None})
    target = _normalize(_v3_target_document())  # target.raw present, base.raw missing
    runner = _FakeRunner(_v3_diff_payload())

    result = await classify_asyncapi(base, target, runner=runner)
    assert runner.calls == []  # the tool was never invoked
    # Structural grades still classify the removed channel as breaking.
    assert _grade_for(result, "legacy/ping").severity is Severity.BREAKING
    assert all(not c.rule_id.startswith("asyncapi-diff.") for c in result.classifications)


async def test_degrades_when_tool_unavailable() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    runner = _RaisingRunner(ToolNotAvailableError(ASYNCAPI_DIFF_TOOL_KEY, "asyncapi-diff"))

    result = await classify_asyncapi(base, target, runner=runner)
    assert runner.calls == 1  # it tried, then fell back
    assert _grade_for(result, "legacy/ping").severity is Severity.BREAKING
    assert result.classifier == "asyncapi-diff"
    assert all(not c.rule_id.startswith("asyncapi-diff.") for c in result.classifications)


async def test_identical_models_classify_safe_with_tool() -> None:
    base = _normalize(_v3_base_document())
    runner = _FakeRunner({"ok": True, "changes": []})
    result = await classify_asyncapi(base, _normalize(_v3_base_document()), runner=runner)
    assert result.classifications == []
    assert result.overall_severity is Severity.SAFE
    assert result.breaking is False
    assert result.counts_by_severity == {}


# ===========================================================================
# Determinism + serialization
# ===========================================================================


async def test_overlay_is_deterministic() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    first = await classify_asyncapi(base, target, runner=_FakeRunner(_v3_diff_payload()))
    second = await classify_asyncapi(base, target, runner=_FakeRunner(_v3_diff_payload()))
    assert first.model_dump() == second.model_dump()


async def test_result_round_trips_through_json() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    result = await classify_asyncapi(base, target, runner=_FakeRunner(_v3_diff_payload()))
    reloaded = ClassificationResult.model_validate_json(result.model_dump_json())
    assert reloaded == result


# ===========================================================================
# SPI registration + sync (structural) dispatch
# ===========================================================================


@pytest.mark.parametrize("format_key", ["asyncapi-2", "asyncapi-3"])
def test_classifier_registered_for_both_families(format_key: str) -> None:
    cls = get_breaking_change_classifier(format_key)
    assert cls is not None
    assert issubclass(cls, AsyncApiBreakingChangeClassifier)
    assert format_key in available_breaking_change_formats()


def test_sync_classify_dispatches_to_asyncapi_structural_baseline() -> None:
    """The sync SPI resolves the AsyncAPI classifier and grades structurally (no tool)."""
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    result = classify(diff(base, target), base, target)
    assert result.classifier == "asyncapi-diff"
    # A removed channel is breaking even on the pure, tool-free path.
    assert _grade_for(result, "legacy/ping").severity is Severity.BREAKING
    assert result.overall_severity is Severity.BREAKING


async def test_classify_asyncapi_matches_classifier_classify_async() -> None:
    base = _normalize(_v3_base_document())
    target = _normalize(_v3_target_document())
    via_convenience = await classify_asyncapi(
        base, target, runner=_FakeRunner(_v3_diff_payload())
    )
    classifier = AsyncApiBreakingChangeClassifier()
    via_method = await classifier.classify_async(
        diff(base, target), base, target, runner=_FakeRunner(_v3_diff_payload())
    )
    assert via_convenience == via_method


# ===========================================================================
# End-to-end (gated): the real bundled @asyncapi/diff over normalized models
# ===========================================================================

_DIFF_AVAILABLE = bool(getattr(probe_tool(ASYNCAPI_DIFF_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _DIFF_AVAILABLE,
    reason="asyncapi-diff tool is not resolvable in this environment "
    "(bundled only in the image / via OBJECTIFIED_ASYNCAPI_DIFF_BIN)",
)
class TestRealAsyncApiDiff:
    """Classifies a real breaking + safe change end-to-end when @asyncapi/diff is present."""

    async def test_v3_breaking_and_safe_change_classified(self) -> None:
        base = _normalize(_v3_base_document())
        target = _normalize(_v3_target_document())
        result = await classify_asyncapi(base, target)

        assert result.classifier == "asyncapi-diff"
        assert _grade_for(result, "legacy/ping").severity is Severity.BREAKING
        assert _grade_for(result, "legacy/ping").rule_id == "asyncapi-diff.breaking"
        assert _grade_for(result, "user/deleted").severity is Severity.SAFE
        assert result.overall_severity is Severity.BREAKING

        # Deterministic: the same pair grades identically.
        again = await classify_asyncapi(base, target)
        assert again.model_dump() == result.model_dump()

    async def test_identical_documents_have_no_changes(self) -> None:
        base = _normalize(_v3_base_document())
        result = await classify_asyncapi(base, _normalize(_v3_base_document()))
        assert result.classifications == []
        assert result.overall_severity is Severity.SAFE
