"""Tests for the Protobuf breaking-change classifier (MFI-9.5, #3768).

The acceptance criteria are: **a field-number reuse / type change is detected as breaking**, and
**safe additions pass**. These tests pin the layers, mirroring ``test_proto_lint.py`` and
``test_graphql_diff.py``:

* the **structural baseline** — :class:`app.proto_breaking.ProtobufBreakingChangeClassifier`,
  registered under the ``protobuf`` format key and inheriting the format-agnostic built-in
  ruleset, grades a Protobuf diff (built through the *real* MFI-9.2
  :class:`~app.proto_normalizer.ProtoNormalizer` over synthetic descriptor sets, no ``buf``): a
  reused ``field_number`` and a changed ``type`` are breaking, an added optional field is safe;
* the **strictness config** — :func:`app.proto_breaking.buf_breaking_module_yaml` enables the
  right ``buf`` breaking category, defaulting to ``WIRE_JSON``;
* the **buf breaking mapping** (:func:`app.proto_breaking.breaking_changes` /
  :func:`app.proto_breaking.parse_buf_breaking_output`) — ``buf breaking`` JSON becomes
  namespaced, ``breaking``-severity changes;
* the **runner** (:func:`app.proto_breaking.run_buf_breaking`) — driven with an injected fake
  toolchain runner (no ``buf``): exit-100 breaks are returned, build failures raise
  :class:`~app.proto_breaking.ProtoBreakingError`, and the two scratch modules carry the breaking
  vs build-only ``buf.yaml``;
* the **overlay** — :meth:`app.proto_breaking.ProtobufBreakingChangeClassifier.classify_async`
  forces the overall verdict to breaking when ``buf`` finds a break and caps structural
  over-approximations to ``dangerous`` when ``buf`` finds the diff wire/JSON-compatible, plus a
  gated end-to-end test over real ``.proto`` sources with the real bundled ``buf``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest
from google.protobuf import descriptor_pb2

from app.breaking_change import (
    Severity,
    available_breaking_change_formats,
    classify_models,
    get_breaking_change_classifier,
)
from app.diff import diff
from app.proto_breaking import (
    BUF_BREAKING_RULE_PREFIX,
    DEFAULT_BREAKING_STRICTNESS,
    BufBreakingStrictness,
    ProtoBreakingError,
    ProtoBreakingResult,
    ProtobufBreakingChangeClassifier,
    breaking_changes,
    buf_breaking_module_yaml,
    classify_protobuf,
    parse_buf_breaking_output,
    run_buf_breaking,
)
from app.proto_descriptor import BUF_TOOL_KEY, ProtoCompileError, ProtoFile
from app.proto_normalizer import ProtoNormalizer
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolExecutionError,
    ToolNotAvailableError,
    ToolSpec,
    ToolTimeoutError,
)

_FD = descriptor_pb2.FieldDescriptorProto


# ===========================================================================
# Synthetic descriptor builders (real models via MFI-9.2, no buf)
# ===========================================================================


def _model(fds: descriptor_pb2.FileDescriptorSet):
    """Normalize a hand-built descriptor set into the canonical model (every file a target)."""
    return ProtoNormalizer().normalize(fds)


def _file(fds: descriptor_pb2.FileDescriptorSet, name: str, package: str):
    f = fds.file.add()
    f.name = name
    f.package = package
    f.syntax = "proto3"
    return f


def _scalar(message, name: str, number: int, *, type_: int = _FD.TYPE_STRING):
    field_proto = message.field.add()
    field_proto.name = name
    field_proto.number = number
    field_proto.type = type_
    field_proto.label = _FD.LABEL_OPTIONAL
    return field_proto


def _user_set(*, name_number: int = 2, name_type: int = _FD.TYPE_STRING, extra: bool = False):
    """A ``acme.user.v1.User`` message: ``id=1`` plus a ``name`` field whose number/type vary.

    ``name_number`` / ``name_type`` let a test move the wire identity or the type of ``name`` (the
    two breaking cases), and ``extra`` adds a new optional ``nickname`` field (the safe case).
    """
    fds = descriptor_pb2.FileDescriptorSet()
    f = _file(fds, "user/user.proto", "acme.user.v1")
    user = f.message_type.add()
    user.name = "User"
    _scalar(user, "id", 1)
    _scalar(user, "name", name_number, type_=name_type)
    if extra:
        _scalar(user, "nickname", 3)
    return fds


# ===========================================================================
# Registry — the classifier is resolved for the ``protobuf`` format
# ===========================================================================


def test_classifier_registered_under_protobuf_format() -> None:
    assert get_breaking_change_classifier("protobuf") is ProtobufBreakingChangeClassifier
    assert "protobuf" in available_breaking_change_formats()


def test_sync_classify_dispatches_to_protobuf_classifier() -> None:
    base = _model(_user_set())
    target = _model(_user_set(extra=True))
    result = classify_models(base, target)
    assert result.classifier == "buf-breaking"
    assert result.format == "protobuf"


# ===========================================================================
# Structural baseline (sync) — the acceptance cases without buf
# ===========================================================================


def test_field_number_reuse_is_breaking() -> None:
    # ``name`` keeps its key but moves from field number 2 to 3 — a reused wire identity.
    base = _model(_user_set(name_number=2))
    target = _model(_user_set(name_number=3))
    result = classify_models(base, target)
    assert result.overall_severity is Severity.BREAKING
    assert result.breaking
    graded = {c.key: c.severity for c in result.classifications}
    assert graded.get("acme.user.v1.User.name") is Severity.BREAKING


def test_type_change_is_breaking() -> None:
    base = _model(_user_set(name_type=_FD.TYPE_STRING))
    target = _model(_user_set(name_type=_FD.TYPE_INT32))
    result = classify_models(base, target)
    assert result.overall_severity is Severity.BREAKING


def test_safe_addition_passes() -> None:
    base = _model(_user_set())
    target = _model(_user_set(extra=True))  # adds an optional ``nickname``
    result = classify_models(base, target)
    assert not result.breaking
    assert result.overall_severity is Severity.SAFE


# ===========================================================================
# Strictness config
# ===========================================================================


def test_default_strictness_is_wire_json() -> None:
    assert DEFAULT_BREAKING_STRICTNESS is BufBreakingStrictness.WIRE_JSON
    yaml = buf_breaking_module_yaml()
    assert "breaking:" in yaml
    assert "WIRE_JSON" in yaml


@pytest.mark.parametrize("strictness", list(BufBreakingStrictness))
def test_strictness_yaml_names_its_category(strictness: BufBreakingStrictness) -> None:
    yaml = buf_breaking_module_yaml(strictness)
    assert f"- {strictness.value}\n" in yaml
    assert yaml.startswith("version: v2\n")


# ===========================================================================
# buf breaking output → typed changes
# ===========================================================================


def test_breaking_changes_namespace_and_severity() -> None:
    report = [
        {
            "path": "user/user.proto",
            "start_line": 5,
            "start_column": 3,
            "type": "FIELD_SAME_TYPE",
            "message": "Field \"2\" changed type.",
        },
        {"path": "user/user.proto", "start_line": 8, "type": "FIELD_NO_DELETE", "message": "gone"},
    ]
    changes = breaking_changes(report)
    assert [c.rule for c in changes] == [
        f"{BUF_BREAKING_RULE_PREFIX}.field_same_type",
        f"{BUF_BREAKING_RULE_PREFIX}.field_no_delete",
    ]
    assert all(c.severity is Severity.BREAKING for c in changes)
    assert changes[0].start_line == 5 and changes[0].start_column == 3
    assert changes[1].start_column is None  # column omitted


def test_breaking_changes_missing_fields_degrade() -> None:
    changes = breaking_changes([{"message": "orphan"}])  # no type, no path
    assert changes[0].rule == f"{BUF_BREAKING_RULE_PREFIX}.unknown"
    assert changes[0].path == "(proto)"
    assert changes[0].start_line is None


def test_breaking_changes_accepts_single_str_and_empty() -> None:
    single = {"path": "a.proto", "type": "ENUM_NO_DELETE", "message": "m"}
    assert len(breaking_changes(single)) == 1
    jsonl = (
        '{"path":"a.proto","start_line":1,"type":"FIELD_SAME_TYPE","message":"m"}\n'
        "\n"  # blank line skipped
        "not json at all\n"  # non-JSON line skipped
        '{"path":"a.proto","start_line":2,"type":"MESSAGE_NO_DELETE","message":"m"}'
    )
    assert len(breaking_changes(jsonl)) == 2
    assert breaking_changes(None) == []
    assert breaking_changes("") == []
    assert breaking_changes([]) == []


def test_parse_buf_breaking_output_skips_noise() -> None:
    out = '  {"type":"X","message":"a"}  \n\n  garbage \n[1,2,3]\n{"type":"Y","message":"b"}'
    parsed = parse_buf_breaking_output(out)
    # The bare-array line is valid JSON but not a finding object → skipped.
    assert [p["type"] for p in parsed] == ["X", "Y"]


# ===========================================================================
# run_buf_breaking — driven with a fake toolchain runner (no real buf)
# ===========================================================================


@dataclass
class _FakeRunResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass
class _Call:
    spec: ToolSpec
    args: List[str]
    modules: Dict[str, Dict[str, str]] = field(default_factory=dict)


class _FakeBreakingRunner:
    """A toolchain-runner double for ``buf breaking``.

    Snapshots both materialised scratch modules (target + against), then returns a fixed result or
    raises a fixed error — exactly the two outcomes :func:`run_buf_breaking` must handle.
    """

    def __init__(
        self,
        *,
        result: Optional[_FakeRunResult] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self._result = result if result is not None else _FakeRunResult()
        self._error = error
        self.calls: List[_Call] = []

    @staticmethod
    def _snapshot(root: str) -> Dict[str, str]:
        base = Path(root)
        return {
            str(p.relative_to(base)): p.read_text(encoding="utf-8")
            for p in sorted(base.rglob("*"))
            if p.is_file()
        }

    async def run_spec(
        self,
        spec: ToolSpec,
        args: Sequence[str] = (),
        *,
        timeout: Optional[float] = None,
        policy: Any = None,
        **_: Any,
    ) -> _FakeRunResult:
        args = list(args)
        modules = {"target": self._snapshot(args[0]), "against": self._snapshot(args[2])}
        self.calls.append(_Call(spec=spec, args=args, modules=modules))
        if self._error is not None:
            raise self._error
        return self._result


_NEW = ProtoFile(
    path="user/user.proto",
    content='syntax = "proto3";\npackage user;\nmessage User { int32 id = 1; }\n',
)
_OLD = ProtoFile(
    path="user/user.proto",
    content='syntax = "proto3";\npackage user;\nmessage User { string id = 1; }\n',
)


async def test_run_buf_breaking_clean_exit_returns_no_changes() -> None:
    runner = _FakeBreakingRunner(result=_FakeRunResult(stdout="", exit_code=0))
    result = await run_buf_breaking([_NEW], [_OLD], runner=runner)
    assert isinstance(result, ProtoBreakingResult)
    assert not result.has_breaking
    assert result.strictness is BufBreakingStrictness.WIRE_JSON


async def test_run_buf_breaking_materializes_two_modules() -> None:
    runner = _FakeBreakingRunner()
    await run_buf_breaking([_NEW], [_OLD], runner=runner, strictness=BufBreakingStrictness.WIRE)
    call = runner.calls[0]
    assert call.spec.key == BUF_TOOL_KEY
    assert call.spec.base_args == ("breaking",)
    assert call.args[1] == "--against"
    assert call.args[-1] == "--error-format=json"
    # The new module carries the breaking-enabled buf.yaml (at the requested strictness); the
    # against module carries the plain build-only config.
    assert call.modules["target"]["user/user.proto"] == _NEW.content
    assert "breaking:" in call.modules["target"]["buf.yaml"]
    assert "WIRE\n" in call.modules["target"]["buf.yaml"]
    assert call.modules["against"]["user/user.proto"] == _OLD.content
    assert "breaking:" not in call.modules["against"]["buf.yaml"]


async def test_run_buf_breaking_returns_breaks_on_exit_100() -> None:
    stdout = '{"path":"user/user.proto","start_line":1,"type":"FIELD_SAME_TYPE","message":"bad"}'
    runner = _FakeBreakingRunner(error=ToolExecutionError(BUF_TOOL_KEY, 100, stdout, ""))
    result = await run_buf_breaking([_NEW], [_OLD], runner=runner)
    assert result.has_breaking
    assert [c.rule for c in result.changes] == [f"{BUF_BREAKING_RULE_PREFIX}.field_same_type"]


async def test_run_buf_breaking_build_failure_raises() -> None:
    runner = _FakeBreakingRunner(
        error=ToolExecutionError(BUF_TOOL_KEY, 1, "", "a.proto:1:1: syntax error")
    )
    with pytest.raises(ProtoBreakingError, match="failed to process"):
        await run_buf_breaking([_NEW], [_OLD], runner=runner)


async def test_run_buf_breaking_unavailable_and_timeout_map_to_error() -> None:
    unavailable = _FakeBreakingRunner(error=ToolNotAvailableError(BUF_TOOL_KEY, "buf"))
    with pytest.raises(ProtoBreakingError, match="not available"):
        await run_buf_breaking([_NEW], [_OLD], runner=unavailable)

    timed_out = _FakeBreakingRunner(error=ToolTimeoutError(BUF_TOOL_KEY, 5.0))
    with pytest.raises(ProtoBreakingError, match="timed out"):
        await run_buf_breaking([_NEW], [_OLD], runner=timed_out)


async def test_run_buf_breaking_empty_files_raise() -> None:
    with pytest.raises(ProtoBreakingError, match="new .proto"):
        await run_buf_breaking([], [_OLD], runner=_FakeBreakingRunner())
    with pytest.raises(ProtoBreakingError, match="baseline .proto"):
        await run_buf_breaking([_NEW], [], runner=_FakeBreakingRunner())


async def test_run_buf_breaking_rejects_unsafe_path() -> None:
    bad = ProtoFile(path="../escape.proto", content='syntax = "proto3";')
    with pytest.raises(ProtoCompileError):
        await run_buf_breaking([bad], [_OLD], runner=_FakeBreakingRunner())


# ===========================================================================
# classify_async / classify_protobuf overlay
# ===========================================================================


async def test_overlay_without_sources_returns_structural_baseline() -> None:
    base = _model(_user_set(name_type=_FD.TYPE_STRING))
    target = _model(_user_set(name_type=_FD.TYPE_INT32))
    classifier = ProtobufBreakingChangeClassifier()
    result = await classifier.classify_async(diff(base, target), base, target)
    # No proto sources supplied → the structural baseline (a breaking type change) stands.
    assert result.overall_severity is Severity.BREAKING


async def test_overlay_tool_error_degrades_to_baseline() -> None:
    base = _model(_user_set(name_type=_FD.TYPE_STRING))
    target = _model(_user_set(name_type=_FD.TYPE_INT32))
    runner = _FakeBreakingRunner(error=ToolNotAvailableError(BUF_TOOL_KEY, "buf"))
    result = await classify_protobuf(
        base, target, against_files=[_OLD], target_files=[_NEW], runner=runner
    )
    assert result.overall_severity is Severity.BREAKING  # baseline preserved


async def test_overlay_buf_reports_break_forces_breaking() -> None:
    # A safe structural diff (added optional field), but buf authoritatively reports a break.
    base = _model(_user_set())
    target = _model(_user_set(extra=True))
    stdout = '{"path":"user/user.proto","start_line":1,"type":"FIELD_SAME_TYPE","message":"bad"}'
    runner = _FakeBreakingRunner(error=ToolExecutionError(BUF_TOOL_KEY, 100, stdout, ""))
    result = await classify_protobuf(
        base, target, against_files=[_OLD], target_files=[_NEW], runner=runner
    )
    assert result.overall_severity is Severity.BREAKING
    assert result.breaking


async def test_overlay_buf_clean_caps_breaking_to_dangerous() -> None:
    # A structural type change (breaking), but buf finds it wire/JSON-compatible → cap to dangerous.
    base = _model(_user_set(name_type=_FD.TYPE_STRING))
    target = _model(_user_set(name_type=_FD.TYPE_INT32))
    baseline = classify_models(base, target)
    assert baseline.overall_severity is Severity.BREAKING  # precondition: structural says breaking

    runner = _FakeBreakingRunner(result=_FakeRunResult(stdout="", exit_code=0))  # buf: no breaks
    result = await classify_protobuf(
        base, target, against_files=[_OLD], target_files=[_NEW], runner=runner
    )
    assert not result.breaking
    assert result.overall_severity is Severity.DANGEROUS
    capped = [c for c in result.classifications if c.severity is Severity.DANGEROUS]
    assert capped and all(c.rule_id == "buf-breaking.wire-compatible" for c in capped)


async def test_overlay_result_is_1to1_with_diff() -> None:
    base = _model(_user_set())
    target = _model(_user_set(extra=True))
    model_diff = diff(base, target)
    runner = _FakeBreakingRunner(result=_FakeRunResult(stdout="", exit_code=0))
    result = await classify_protobuf(
        base, target, against_files=[_OLD], target_files=[_NEW], runner=runner
    )
    assert len(result.classifications) == len(model_diff.changes)


# ===========================================================================
# End-to-end: the real bundled buf through the real runner (gated)
# ===========================================================================

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))

_E2E_OLD = ProtoFile(
    path="user/user.proto",
    content=(
        'syntax = "proto3";\n'
        "package acme.user.v1;\n"
        "message User {\n"
        "  string id = 1;\n"
        "  string name = 2;\n"
        "}\n"
    ),
)
_E2E_TYPE_CHANGE = ProtoFile(
    path="user/user.proto",
    content=(
        'syntax = "proto3";\n'
        "package acme.user.v1;\n"
        "message User {\n"
        "  string id = 1;\n"
        "  int32 name = 2;\n"  # string -> int32 is a wire break
        "}\n"
    ),
)
_E2E_SAFE_ADDITION = ProtoFile(
    path="user/user.proto",
    content=(
        'syntax = "proto3";\n'
        "package acme.user.v1;\n"
        "message User {\n"
        "  string id = 1;\n"
        "  string name = 2;\n"
        "  string nickname = 3;\n"  # additive
        "}\n"
    ),
)


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
async def test_run_buf_breaking_detects_type_change_end_to_end() -> None:
    result = await run_buf_breaking([_E2E_TYPE_CHANGE], [_E2E_OLD])
    assert result.has_breaking
    assert all(c.severity is Severity.BREAKING for c in result.changes)
    assert all(c.rule.startswith(BUF_BREAKING_RULE_PREFIX) for c in result.changes)


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
async def test_run_buf_breaking_safe_addition_passes_end_to_end() -> None:
    result = await run_buf_breaking([_E2E_SAFE_ADDITION], [_E2E_OLD])
    assert not result.has_breaking
