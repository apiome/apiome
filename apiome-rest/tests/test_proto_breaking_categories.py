"""Tests for the Protobuf ``buf breaking`` category rules — XPC-4.3 (#5747).

The acceptance criteria are: fixture pairs covering each added rule classify correctly in all
four categories **with and without** ``buf``; the overlay agrees with the structural rules on the
Buf rule corpus or the disagreement is reported; each finding names its category; and a caller
can request a category.

The corpus is ``tests/fixtures/proto_breaking_categories``: ``cases.json`` is hand-written (the
``.proto`` change, the grade expected per category, the categories where the roadmap departs
from ``buf``), ``recordings.json`` is written by ``scripts/record_proto_breaking_fixtures.py``
(each side's descriptor set and the ``buf breaking`` rules per category). Without ``buf`` the
descriptor sets are graded structurally and the recorded ``buf`` output is replayed through the
overlay; with ``buf`` the same cases are also compiled and checked live.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from google.protobuf import descriptor_pb2

from app.breaking_change import Severity, classify_models
from app.canonical_model import CanonicalApi
from app.diff import diff
from app.fingerprint import fingerprint
from app.proto_breaking import (
    DEFAULT_BREAKING_STRICTNESS,
    BufBreakingCategory,
    BufBreakingStrictness,
    ProtoBreakingChange,
    ProtoBreakingResult,
    ProtobufBreakingChangeClassifier,
    classify_protobuf,
    coerce_category,
    overlay_disagreement,
    run_buf_breaking,
)
from app.proto_breaking_rules import (
    CATEGORY_ORDER,
    COMPATIBLE_RULE_ID,
    _uncovered,
    category_findings,
    category_rule_id,
    grades_summary,
)
from app.proto_descriptor import BUF_TOOL_KEY, ProtoFile, compile_proto_descriptor_set
from app.proto_emitter import ProtoEmitter
from app.proto_normalizer import (
    JSON_NAME_EXTRA_KEY,
    PROTOBUF_FILES_EXTRA_KEY,
    ProtoNormalizer,
    default_json_name,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import ToolExecutionError

_FIXTURES = Path(__file__).parent / "fixtures" / "proto_breaking_categories"
_CASES: List[Dict[str, Any]] = json.loads((_FIXTURES / "cases.json").read_text())["cases"]
_RECORDINGS: Dict[str, Any] = json.loads((_FIXTURES / "recordings.json").read_text())
_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))
_RULE_ID = re.compile(r"^protobuf\.(wire|wire_json|package|file)\.[a-z-]+$")


# ===========================================================================
# Helpers
# ===========================================================================


def _models(case_id: str) -> tuple[CanonicalApi, CanonicalApi]:
    """The old and new canonical models of a corpus case, from its recorded descriptor sets."""
    descriptors = _RECORDINGS[case_id]["descriptors"]
    normalizer = ProtoNormalizer()
    return (
        normalizer.normalize(base64.b64decode(descriptors["old"])),
        normalizer.normalize(base64.b64decode(descriptors["new"])),
    )


def _grade(case_id: str, category: str):
    """Grade a corpus case structurally at ``category``."""
    base, target = _models(case_id)
    return ProtobufBreakingChangeClassifier(category).classify(diff(base, target), base, target)


def _rule_ids(result) -> List[str]:
    """Every rule id in a result, per change and unattributed."""
    return [c.rule_id for c in result.classifications] + [f.rule_id for f in result.unattributed]


def _files(side: Dict[str, str]) -> List[ProtoFile]:
    return [ProtoFile(path=path, content=content) for path, content in sorted(side.items())]


def _case(case_id: str) -> Dict[str, Any]:
    return next(case for case in _CASES if case["id"] == case_id)


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = 0


class _ReplayRunner:
    """A toolchain runner that answers ``buf breaking`` with a recorded list of rule types."""

    def __init__(self, rules: List[str]) -> None:
        self.rules = rules

    async def run_spec(self, spec: Any, args: Any, *, timeout: Any = None, policy: Any = None) -> Any:
        if not self.rules:
            return _Result("")
        stdout = "\n".join(
            json.dumps({"path": "acme/v1/a.proto", "start_line": 1, "type": rule, "message": rule})
            for rule in self.rules
        )
        raise ToolExecutionError(BUF_TOOL_KEY, 100, stdout, "")


_CASE_CATEGORIES = [(case["id"], category) for case in _CASES for category in CATEGORY_ORDER]


# ===========================================================================
# The corpus, without buf: every case in every category
# ===========================================================================


def test_corpus_has_a_recording_per_case() -> None:
    assert {case["id"] for case in _CASES} == set(_RECORDINGS)


def test_corpus_covers_every_rule() -> None:
    covered = {case["rule"] for case in _CASES}
    assert covered >= {
        "reserved-removed",
        "reserved-number-reused",
        "reserved-name-reused",
        "field-deleted-unreserved",
        "field-deleted",
        "field-renamed",
        "field-number-reused",
        "json-name-changed",
        "type-moved-file",
        "package-changed",
        "enum-value-number-reused",
        "enum-value-number-changed",
        "oneof-membership-changed",
        "cardinality-changed",
        "required-changed",
        "presence-changed",
    }


@pytest.mark.parametrize("case_id,category", _CASE_CATEGORIES)
def test_case_grades_as_expected(case_id: str, category: str) -> None:
    case = _case(case_id)
    result = _grade(case_id, category)
    assert result.overall_severity.value == case["expected"][category], [
        (c.key, c.severity.value, c.rationale) for c in result.classifications
    ] + [(f.shape, f.severity.value, f.rationale) for f in result.unattributed]
    if case["rule"] == "compatible":
        assert COMPATIBLE_RULE_ID in _rule_ids(result)
    else:
        assert any(rule.endswith("." + case["rule"]) for rule in _rule_ids(result))


@pytest.mark.parametrize("case_id", [case["id"] for case in _CASES])
def test_every_grade_names_its_category(case_id: str) -> None:
    for category in CATEGORY_ORDER:
        result = _grade(case_id, category)
        for rationale in [c.rationale for c in result.classifications] + [
            f.rationale for f in result.unattributed
        ]:
            assert rationale.startswith(f"[{category}] ")
        for rule in _rule_ids(result):
            if rule.startswith("protobuf.") and rule != COMPATIBLE_RULE_ID:
                assert _RULE_ID.match(rule), rule


def test_rule_id_names_the_narrowest_worst_category() -> None:
    result = _grade("json-name-changed", "WIRE")
    (change,) = result.classifications
    assert change.rule_id == "protobuf.wire_json.json-name-changed"
    assert change.severity is Severity.SAFE  # wire-safe…
    assert "breaking under WIRE_JSON, PACKAGE, FILE" in change.rationale  # …and says where it breaks


def test_file_move_is_reported_unattributed() -> None:
    # A file move is not part of the canonical diff, so it is reported on its own.
    result = _grade("type-moved-file", "FILE")
    assert result.classifications == []
    (finding,) = result.unattributed
    assert finding.rule_id == "protobuf.file.type-moved-file"
    assert finding.shape == "acme.v1.N"
    assert finding.severity is Severity.BREAKING
    assert _grade("type-moved-file", "PACKAGE").unattributed[0].severity is Severity.SAFE


def test_deleted_field_rationale_names_the_missing_reservation() -> None:
    result = _grade("field-deleted-name-unreserved", "WIRE_JSON")
    graded = {c.key: c for c in result.classifications}
    change = graded["acme.v1.M.b"]
    assert "without reserving its name" in change.rationale
    assert graded["acme.v1.M"].rule_id == COMPATIBLE_RULE_ID  # the added reservation
    assert change.rule_id == "protobuf.wire_json.field-deleted-unreserved"


def test_package_move_grades_the_moved_fields_with_the_type() -> None:
    result = _grade("package-changed", "WIRE")
    graded = {c.key: c.rule_id for c in result.classifications}
    assert graded["acme.v1.M"] == "protobuf.wire.package-changed"
    assert graded["acme.v1.M.a"] == "protobuf.wire.package-changed"
    assert graded["acme.v2.M"] == "added-entity"


# ===========================================================================
# Agreement with buf (recorded corpus)
# ===========================================================================


@pytest.mark.parametrize("case_id,category", _CASE_CATEGORIES)
def test_structural_rules_agree_with_buf_or_list_the_disagreement(case_id: str, category: str) -> None:
    case = _case(case_id)
    buf_breaks = bool(_RECORDINGS[case_id]["buf"][category])
    structural_breaks = _grade(case_id, category).breaking
    listed = category in case.get("known_disagreements", {})
    # A listed disagreement must still be one, and an unlisted one is a failure.
    assert (structural_breaks != buf_breaks) == listed


@pytest.mark.parametrize("case_id,category", _CASE_CATEGORIES)
async def test_overlay_replaying_buf_reports_disagreement(case_id: str, category: str) -> None:
    case = _case(case_id)
    rules = _RECORDINGS[case_id]["buf"][category]
    base, target = _models(case_id)
    result = await classify_protobuf(
        base,
        target,
        against_files=_files(case["old"]),
        target_files=_files(case["new"]),
        strictness=category,
        runner=_ReplayRunner(rules),
    )
    # buf is authoritative for the overall breaking call at the category.
    assert result.breaking == bool(rules)
    rationales = " ".join(
        [c.rationale for c in result.classifications] + [f.rationale for f in result.unattributed]
    )
    assert ("disagreement:" in rationales) == (category in case.get("known_disagreements", {}))
    for rule in rules:
        assert f"protobuf.buf-breaking.{rule.lower()}" in _rule_ids(result)


def test_overlay_disagreement_sentence() -> None:
    structural = _grade("reserved-removed", "WIRE_JSON")
    buf = ProtoBreakingResult(
        strictness=BufBreakingStrictness.WIRE_JSON,
        changes=[ProtoBreakingChange(path="a.proto", rule="protobuf.buf-breaking.reserved_message_no_delete")],
    )
    sentence = overlay_disagreement(structural, buf)
    assert sentence is not None and "WIRE_JSON break" in sentence
    assert "reserved_message_no_delete" in sentence
    agreeing = ProtoBreakingResult(strictness=BufBreakingStrictness.WIRE_JSON, changes=[])
    assert overlay_disagreement(structural, agreeing) is None


# ===========================================================================
# The corpus with the real buf (gated)
# ===========================================================================


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
@pytest.mark.parametrize("case_id", [case["id"] for case in _CASES])
async def test_live_buf_matches_recordings(case_id: str) -> None:
    case = _case(case_id)
    for category in BufBreakingStrictness:
        live = await run_buf_breaking(_files(case["new"]), _files(case["old"]), strictness=category)
        rules = sorted({c.rule.rsplit(".", 1)[-1].upper() for c in live.changes})
        assert rules == _RECORDINGS[case_id]["buf"][category.value]


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
@pytest.mark.parametrize("case_id", [case["id"] for case in _CASES])
async def test_live_compile_grades_as_expected(case_id: str) -> None:
    case = _case(case_id)
    normalizer = ProtoNormalizer()
    base = normalizer.normalize(await compile_proto_descriptor_set(_files(case["old"])))
    target = normalizer.normalize(await compile_proto_descriptor_set(_files(case["new"])))
    for category in CATEGORY_ORDER:
        result = ProtobufBreakingChangeClassifier(category).classify(diff(base, target), base, target)
        assert result.overall_severity.value == case["expected"][category]


# ===========================================================================
# Requesting a category
# ===========================================================================


def test_default_category_is_wire_json() -> None:
    assert ProtobufBreakingChangeClassifier().category is DEFAULT_BREAKING_STRICTNESS
    assert DEFAULT_BREAKING_STRICTNESS is BufBreakingStrictness.WIRE_JSON
    assert BufBreakingCategory is BufBreakingStrictness


@pytest.mark.parametrize("value", ["file", "FILE", " File ", BufBreakingStrictness.FILE])
def test_coerce_category_accepts_any_case(value: Any) -> None:
    assert coerce_category(value) is BufBreakingStrictness.FILE


@pytest.mark.parametrize("value", [None, "", "  "])
def test_coerce_category_blank_is_default(value: Optional[str]) -> None:
    assert coerce_category(value) is DEFAULT_BREAKING_STRICTNESS


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="WIRE_JSON"):
        ProtobufBreakingChangeClassifier("STRICT")


def test_sync_dispatch_grades_at_the_default_category() -> None:
    base, target = _models("json-name-changed")
    result = classify_models(base, target)
    assert result.classifier == "buf-breaking"
    assert result.overall_severity is Severity.BREAKING  # WIRE_JSON


async def test_classify_protobuf_grades_at_the_requested_category_without_sources() -> None:
    base, target = _models("json-name-changed")
    wire = await classify_protobuf(base, target, against_files=None, target_files=None, strictness="WIRE")
    assert wire.overall_severity is Severity.SAFE
    file_ = await classify_protobuf(base, target, against_files=None, target_files=None, strictness="FILE")
    assert file_.overall_severity is Severity.BREAKING


async def test_classify_async_strictness_overrides_the_instance_category() -> None:
    base, target = _models("json-name-changed")
    classifier = ProtobufBreakingChangeClassifier("FILE")
    result = await classifier.classify_async(diff(base, target), base, target, strictness="WIRE")
    assert result.overall_severity is Severity.SAFE
    assert classifier.category is BufBreakingStrictness.FILE  # the instance is unchanged


# ===========================================================================
# Rule helpers
# ===========================================================================


def test_category_rule_id_picks_the_narrowest_worst_category() -> None:
    s, d, b = Severity.SAFE, Severity.DANGEROUS, Severity.BREAKING
    assert category_rule_id("x", (s, s, b, b)) == "protobuf.package.x"
    assert category_rule_id("x", (d, d, d, d)) == "protobuf.wire.x"
    assert category_rule_id("x", (s, s, s, b)) == "protobuf.file.x"


def test_grades_summary_lists_worst_first() -> None:
    d, b = Severity.DANGEROUS, Severity.BREAKING
    assert grades_summary((d, b, b, b)) == "breaking under WIRE_JSON, PACKAGE, FILE; dangerous under WIRE"


@pytest.mark.parametrize(
    "ranges,cover,expected",
    [
        ([(5, 5)], [], [(5, 5)]),
        ([(5, 5)], [(1, 10)], []),
        ([(1, 10)], [(3, 4), (8, 20)], [(1, 2), (5, 7)]),
        ([(1, 3), (7, 7)], [(7, 7)], [(1, 3)]),
    ],
)
def test_uncovered_ranges(ranges, cover, expected) -> None:
    assert _uncovered(ranges, cover) == expected


def test_no_findings_for_identical_versions() -> None:
    base, _ = _models("json-name-changed")
    assert category_findings(base, base).findings == []


def test_models_without_a_file_record_skip_move_rules() -> None:
    base, target = _models("type-moved-file")
    base.extras.pop(PROTOBUF_FILES_EXTRA_KEY)
    target.extras.pop(PROTOBUF_FILES_EXTRA_KEY)
    assert category_findings(base, target).findings == []


# ===========================================================================
# Normalizer and emitter support
# ===========================================================================


def _json_name_set(json_name: Optional[str]) -> descriptor_pb2.FileDescriptorSet:
    fds = descriptor_pb2.FileDescriptorSet()
    file_proto = fds.file.add(name="a.proto", package="acme.v1", syntax="proto3")
    message = file_proto.message_type.add(name="M")
    field = message.field.add(
        name="user_name",
        number=1,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    )
    if json_name is not None:
        field.json_name = json_name
    return fds


@pytest.mark.parametrize("name,expected", [("user_name", "userName"), ("id", "id"), ("a_b_c", "aBC")])
def test_default_json_name(name: str, expected: str) -> None:
    assert default_json_name(name) == expected


def test_normalizer_records_only_a_custom_json_name() -> None:
    normalizer = ProtoNormalizer()
    default = normalizer.normalize(_json_name_set("userName")).types[0].fields[0]
    assert JSON_NAME_EXTRA_KEY not in default.extras
    custom = normalizer.normalize(_json_name_set("login")).types[0].fields[0]
    assert custom.extras[JSON_NAME_EXTRA_KEY] == "login"


def test_normalizer_records_files_outside_the_fingerprint() -> None:
    base, target = _models("file-renamed")
    assert base.extras[PROTOBUF_FILES_EXTRA_KEY] == {
        "acme/v1/a.proto": {"package": "acme.v1", "syntax": "proto3", "types": ["acme.v1.M"]}
    }
    assert set(target.extras[PROTOBUF_FILES_EXTRA_KEY]) == {"acme/v1/b.proto"}
    # Renaming a file mints no version and is no change in the diff.
    assert fingerprint(base) == fingerprint(target)
    assert diff(base, target).changes == []


def test_emitter_writes_a_custom_json_name() -> None:
    model = ProtoNormalizer().normalize(_json_name_set("login"))
    text = str(ProtoEmitter().emit(model).files[0].content)
    assert 'string user_name = 1 [json_name = "login"];' in text
