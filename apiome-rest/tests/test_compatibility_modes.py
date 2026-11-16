"""Tests for compatibility-mode policy and mode-aware grading — XPC-4.5 (#5749).

Covers :mod:`app.compatibility_policy` (the vocabulary, defaults and how a request overlays the
project's policy) and :mod:`app.compatibility_modes` (which classifier grades a pair, whether the
mode or category was applied, ``NONE``, the transitive merge and ``evaluatedUnder``).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.avro_breaking import AvroBreakingChangeClassifier, direction_severity
from app.avro_import_source import AvroImportSource
from app.breaking_change import Severity
from app.canonical_model import CanonicalApi
from app.compatibility_modes import (
    Baseline,
    FormatEvaluation,
    canonical_model_for_revision,
    classify_under,
    ctg_changes,
    evaluated_under,
    evaluated_under_markdown,
    graded_changes,
    is_mode_graded_format,
    merge_transitive,
    parse_candidate,
    revision_format,
    transitive_baselines,
)
from app.compatibility_policy import (
    DEFAULT_COMPATIBILITY_MODE,
    DEFAULT_PROTOBUF_CATEGORY,
    CompatibilityPolicy,
    PolicyValueError,
    effective_policy,
    normalize_compatibility_mode,
    normalize_protobuf_category,
    parse_category,
    parse_mode,
    policy_from_guide,
    requested_settings,
    resolve_policy,
)
from app.diff import diff
from app.proto_normalizer import ProtoNormalizer

_AVRO = AvroImportSource()
_USER = {"type": "record", "name": "User", "namespace": "com.example", "fields": [{"name": "id", "type": "long"}]}
_PROTO = json.loads(
    (Path(__file__).parent / "fixtures" / "proto_breaking_categories" / "recordings.json").read_text()
)


def _avro(*fields: Dict[str, Any]) -> CanonicalApi:
    schema = {**_USER, "fields": _USER["fields"] + list(fields)}
    return _AVRO.normalize(_AVRO.parse(json.dumps(schema), source_label="schema.avsc"))


def _proto(case_id: str) -> tuple[CanonicalApi, CanonicalApi]:
    descriptors = _PROTO[case_id]["descriptors"]
    normalizer = ProtoNormalizer()
    return (
        normalizer.normalize(base64.b64decode(descriptors["old"])),
        normalizer.normalize(base64.b64decode(descriptors["new"])),
    )


# ===========================================================================
# Policy vocabulary
# ===========================================================================


def test_defaults_are_backward_non_transitive_wire_json() -> None:
    policy = CompatibilityPolicy()
    assert (policy.mode, policy.transitive, policy.category) == ("BACKWARD", False, "WIRE_JSON")
    assert DEFAULT_COMPATIBILITY_MODE == "BACKWARD"
    assert DEFAULT_PROTOBUF_CATEGORY == "WIRE_JSON"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("forward", ("FORWARD", None)),
        (" Full ", ("FULL", None)),
        ("NONE", ("NONE", None)),
        ("full_transitive", ("FULL", True)),
        ("BACKWARD_TRANSITIVE", ("BACKWARD", True)),
        (None, (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_mode_splits_the_transitive_suffix(raw: Any, expected: Any) -> None:
    assert parse_mode(raw) == expected


@pytest.mark.parametrize("raw", ["sideways", "NONE_TRANSITIVE", "BACKWARDS"])
def test_parse_mode_rejects_unknown_modes(raw: str) -> None:
    with pytest.raises(PolicyValueError):
        parse_mode(raw)


def test_parse_category_accepts_any_case_and_rejects_unknown() -> None:
    assert parse_category("wire") == "WIRE"
    assert parse_category(None) is None
    with pytest.raises(PolicyValueError):
        parse_category("BYTES")


def test_stored_values_normalize_to_defaults_rather_than_raise() -> None:
    assert normalize_compatibility_mode("garbage") == "BACKWARD"
    assert normalize_compatibility_mode("forward") == "FORWARD"
    assert normalize_protobuf_category(None) == "WIRE_JSON"
    assert normalize_protobuf_category("file") == "FILE"


def test_policy_from_guide_reads_the_v382_columns() -> None:
    guide = {"compatibility_mode": "FULL", "compatibility_transitive": True, "protobuf_breaking_category": "FILE"}
    policy = policy_from_guide(guide)
    assert (policy.mode, policy.transitive, policy.category) == ("FULL", True, "FILE")
    assert policy.mode_name == "FULL_TRANSITIVE"
    assert policy.as_settings() == {
        "compatibilityMode": "FULL",
        "compatibilityTransitive": True,
        "protobufBreakingCategory": "FILE",
    }
    assert policy_from_guide(None) == CompatibilityPolicy()


def test_none_has_no_transitive_name() -> None:
    assert CompatibilityPolicy(mode="NONE", transitive=True).mode_name == "NONE"


def test_effective_policy_overlays_only_what_the_request_names() -> None:
    project = CompatibilityPolicy(mode="FULL", transitive=True, category="FILE")
    assert effective_policy(project) == project
    assert effective_policy(project, mode="forward") == CompatibilityPolicy("FORWARD", True, "FILE")
    assert effective_policy(project, transitive=False) == CompatibilityPolicy("FULL", False, "FILE")
    assert effective_policy(project, category="wire") == CompatibilityPolicy("FULL", True, "WIRE")


def test_a_transitive_mode_name_sets_transitive_unless_given_explicitly() -> None:
    plain = CompatibilityPolicy()
    assert effective_policy(plain, mode="FULL_TRANSITIVE") == CompatibilityPolicy("FULL", True, "WIRE_JSON")
    assert effective_policy(plain, mode="FULL_TRANSITIVE", transitive=False).transitive is False


def test_requested_settings_names_what_the_request_sent() -> None:
    assert requested_settings() == {"mode": False, "transitive": False, "category": False}
    assert requested_settings(mode="FULL_TRANSITIVE") == {"mode": True, "transitive": True, "category": False}
    assert requested_settings(transitive=False, category="WIRE") == {
        "mode": False,
        "transitive": True,
        "category": True,
    }


class _GuideDb:
    def __init__(self, guide: Any = None, *, fail: bool = False) -> None:
        self.guide = guide
        self.fail = fail
        self.calls: List[Any] = []

    def get_assigned_style_guide(self, tenant_id: str, project_id: Any) -> Any:
        self.calls.append((tenant_id, project_id))
        if self.fail:
            raise RuntimeError("db down")
        return self.guide


def test_resolve_policy_walks_the_guide_chain_for_the_project() -> None:
    db = _GuideDb({"compatibility_mode": "FORWARD"})
    assert resolve_policy(db, "t-1", "p-1").mode == "FORWARD"
    assert db.calls == [("t-1", "p-1")]


def test_resolve_policy_falls_back_to_defaults_when_the_lookup_fails() -> None:
    assert resolve_policy(_GuideDb(fail=True), "t-1", "p-1") == CompatibilityPolicy()


# ===========================================================================
# Avro mode (XPC-4.1 grading, made selectable)
# ===========================================================================


def test_avro_direction_severity_follows_the_mode() -> None:
    assert direction_severity("backward") is Severity.BREAKING
    assert direction_severity("forward") is Severity.DANGEROUS
    assert direction_severity("forward", "FORWARD") is Severity.BREAKING
    assert direction_severity("backward", "FORWARD") is Severity.DANGEROUS
    assert direction_severity("forward", "FULL_TRANSITIVE") is Severity.BREAKING


def test_avro_classifier_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError):
        AvroBreakingChangeClassifier("SIDEWAYS")


def test_the_same_avro_pair_grades_differently_under_backward_and_forward() -> None:
    """Acceptance: one Avro pair, two modes, two verdicts — and the response names the mode."""
    old, new = _avro(), _avro({"name": "email", "type": "string"})
    backward, ev_b = classify_under(old, new, CompatibilityPolicy(mode="BACKWARD"))
    forward, ev_f = classify_under(old, new, CompatibilityPolicy(mode="FORWARD"))
    assert backward.overall_severity is Severity.BREAKING
    assert forward.overall_severity is Severity.DANGEROUS
    assert ev_b.mode_applied and ev_f.mode_applied
    assert ev_b.ruleset == "avro-compatibility"
    (graded,) = [c for c in forward.classifications if c.key == "com.example.User.email"]
    assert graded.rationale.startswith("[FORWARD] breaks BACKWARD and FULL")


def test_removing_a_required_avro_field_breaks_forward_only() -> None:
    old, new = _avro({"name": "email", "type": "string"}), _avro()
    assert classify_under(old, new, CompatibilityPolicy(mode="BACKWARD"))[0].overall_severity is Severity.DANGEROUS
    assert classify_under(old, new, CompatibilityPolicy(mode="FORWARD"))[0].overall_severity is Severity.BREAKING
    assert classify_under(old, new, CompatibilityPolicy(mode="FULL"))[0].overall_severity is Severity.BREAKING


def test_none_lists_the_changes_but_breaks_nothing() -> None:
    old, new = _avro(), _avro({"name": "email", "type": "string"})
    result, evaluation = classify_under(old, new, CompatibilityPolicy(mode="NONE"))
    assert evaluation.mode_applied
    assert result.overall_severity is Severity.DANGEROUS
    (graded,) = [c for c in result.classifications if c.key == "com.example.User.email"]
    assert graded.rule_id == "avro-compatibility.reader-field-missing-default-value"
    assert graded.rationale.startswith("[NONE]")


# ===========================================================================
# Category, and formats without mode semantics
# ===========================================================================


def test_protobuf_is_graded_at_the_category_not_the_mode() -> None:
    old, new = _proto("json-name-changed")
    wire, ev_wire = classify_under(old, new, CompatibilityPolicy(category="WIRE"))
    wire_json, _ = classify_under(old, new, CompatibilityPolicy(category="WIRE_JSON"))
    assert (ev_wire.category_applied, ev_wire.mode_applied) == (True, False)
    assert wire.overall_severity is Severity.SAFE
    assert wire_json.overall_severity is Severity.BREAKING
    # A mode never reaches Protobuf, not even NONE.
    none, _ = classify_under(old, new, CompatibilityPolicy(mode="NONE"))
    assert none.overall_severity is Severity.BREAKING


def test_a_format_without_a_mode_aware_classifier_is_not_mode_applied() -> None:
    old, new = _avro(), _avro({"name": "email", "type": "string"})
    raml_old = old.model_copy(update={"format": "raml"})
    raml_new = new.model_copy(update={"format": "raml"})
    _, evaluation = classify_under(raml_old, raml_new, CompatibilityPolicy(mode="FORWARD"))
    assert (evaluation.mode_applied, evaluation.category_applied) == (False, False)
    assert evaluation.ruleset and evaluation.ruleset != "avro-compatibility"
    unknown_old = old.model_copy(update={"format": "nosuchformat"})
    unknown_new = new.model_copy(update={"format": "nosuchformat"})
    _, builtin = classify_under(unknown_old, unknown_new, CompatibilityPolicy())
    assert builtin.ruleset == "builtin"
    assert not builtin.mode_applied


@pytest.mark.parametrize(
    "format_key, graded",
    [
        ("avro", True),
        ("json-schema", True),
        ("jsonschema", True),
        ("asyncapi-3", True),
        ("asyncapi-2", True),
        ("protobuf", True),
        ("raml", False),
        ("openapi", False),
        (None, False),
    ],
)
def test_is_mode_graded_format(format_key: Any, graded: bool) -> None:
    assert is_mode_graded_format(format_key) is graded


# ===========================================================================
# Flattening and the transitive merge
# ===========================================================================


def test_graded_changes_and_ctg_changes_keep_the_rule_and_grade() -> None:
    old, new = _avro(), _avro({"name": "email", "type": "string"}, {"name": "a/b", "type": "string", "default": ""})
    result, _ = classify_under(old, new, CompatibilityPolicy())
    flat = {c.pointer: c for c in graded_changes(result)}
    email = flat["/field/com.example.User.email"]
    assert (email.rule_id, email.severity, email.change_kind) == (
        "avro-compatibility.reader-field-missing-default-value",
        "breaking",
        "added",
    )
    mapped = {change.pointer: (change.severity, grade) for change, grade in ctg_changes(result)}
    assert mapped["/field/com.example.User.email"] == ("breaking", "breaking")
    assert all(sev in {"breaking", "non-breaking"} for sev, _ in mapped.values())


def test_pointer_tokens_are_escaped() -> None:
    from app.breaking_change import ClassificationResult, UnattributedFinding

    result = ClassificationResult(
        format="avro",
        classifier="x",
        overall_severity=Severity.DANGEROUS,
        unattributed=[UnattributedFinding(severity=Severity.DANGEROUS, rule_id="r", rationale="why", shape="a/b~c")],
    )
    (only,) = graded_changes(result)
    assert only.pointer == "/unattributed/a~1b~0c"
    assert only.change_kind == "unattributed"


def test_merge_transitive_keeps_the_base_and_adds_only_new_breaks_from_older_revisions() -> None:
    base = Baseline("r3", "3.0.0", "base")
    older = Baseline("r2", "2.0.0", "prior")
    oldest = Baseline("r1", "1.0.0", "prior")
    pairs = [
        (base, [("a", "safe"), ("b", "breaking")]),
        (older, [("b", "breaking"), ("c", "dangerous"), ("d", "breaking")]),
        (oldest, [("d", "breaking"), ("e", "breaking")]),
    ]
    merged = merge_transitive(pairs, key=lambda f: f[0], is_breaking=lambda f: f[1] == "breaking")
    assert [(b.version_label, f[0]) for b, f in merged] == [
        ("3.0.0", "a"),
        ("3.0.0", "b"),
        ("2.0.0", "d"),
        ("1.0.0", "e"),
    ]


class _LineageDb:
    def __init__(self, rows: List[Dict[str, Any]], source: Any = None) -> None:
        self.rows = rows
        self.source = source
        self.limits: List[int] = []

    def list_prior_revisions_for_transitive_check(self, project_id: str, tenant_id: str, revision_id: str, *, limit: int):
        self.limits.append(limit)
        return self.rows[:limit]

    def get_revision_source_row(self, version_id: str, tenant_id: str):
        return self.source


def test_transitive_baselines_lists_the_base_then_its_predecessors() -> None:
    db = _LineageDb([{"id": "r2", "version_id": "2.0.0"}, {"id": "r1", "version_id": "1.0.0"}])
    baselines, truncated = transitive_baselines(
        db, tenant_id="t", project_id="p", base_revision_id="r3", base_label="3.0.0", transitive=True
    )
    assert [(b.revision_id, b.role) for b in baselines] == [("r3", "base"), ("r2", "prior"), ("r1", "prior")]
    assert truncated is False


def test_transitive_baselines_without_transitive_is_only_the_base() -> None:
    db = _LineageDb([{"id": "r2", "version_id": "2.0.0"}])
    baselines, _ = transitive_baselines(
        db, tenant_id="t", project_id="p", base_revision_id="r3", base_label="3.0.0", transitive=False
    )
    assert baselines == [Baseline("r3", "3.0.0", "base")]
    assert db.limits == []


def test_transitive_baselines_reports_truncation_at_the_cap() -> None:
    from app.compatibility_modes import MAX_TRANSITIVE_REVISIONS

    rows = [{"id": f"r{i}", "version_id": f"0.{i}.0"} for i in range(MAX_TRANSITIVE_REVISIONS + 5)]
    baselines, truncated = transitive_baselines(
        _LineageDb(rows), tenant_id="t", project_id="p", base_revision_id="base", base_label="9", transitive=True
    )
    assert len(baselines) == MAX_TRANSITIVE_REVISIONS + 1
    assert truncated is True


def test_evaluated_under_reports_what_ran() -> None:
    policy = CompatibilityPolicy(mode="FORWARD", transitive=True, category="FILE")
    out = evaluated_under(
        policy,
        [FormatEvaluation("avro", "avro-compatibility", mode_applied=True)] * 2,
        requested={"mode": True, "transitive": False, "category": False},
        compared=[Baseline("r2", "2.0.0", "base"), Baseline("r1", "1.0.0", "prior")],
    ).model_dump(by_alias=True)
    assert out["mode"] == "FORWARD"
    assert out["transitive"] is True
    assert out["category"] is None  # no Protobuf was compared
    assert out["formats"] == ["avro"]
    assert out["modeApplied"] is True
    assert out["ruleset"] == "avro-compatibility"
    assert out["source"] == {"mode": "request", "transitive": "policy", "category": "policy"}
    assert [r["role"] for r in out["comparedRevisions"]] == ["base", "prior"]


def test_evaluated_under_names_the_fallback_ruleset_and_the_category_when_applied() -> None:
    plain = evaluated_under(
        CompatibilityPolicy(),
        [FormatEvaluation("raml", "raml-breaking")],
        requested={},
    )
    assert (plain.mode_applied, plain.ruleset, plain.category) == (False, "raml-breaking", None)
    proto = evaluated_under(
        CompatibilityPolicy(category="WIRE"),
        [FormatEvaluation("protobuf", "buf-breaking", category_applied=True)],
        requested={},
    )
    assert (proto.category, proto.category_applied) == ("WIRE", True)
    assert evaluated_under(CompatibilityPolicy(), [], requested={}, default_ruleset="ctg").ruleset == "ctg"


# ===========================================================================
# Loading models
# ===========================================================================


def test_canonical_model_for_revision_rebuilds_a_captured_avro_source() -> None:
    schema = json.dumps({**_USER})
    db = _LineageDb(
        [],
        source={
            "project_id": "p",
            "source_format": "avro",
            "format_metadata": {"sourceContent": schema, "sourceLabel": "user.avsc"},
            "metadata": {},
        },
    )
    model = canonical_model_for_revision(db, "t", "r1")
    assert model is not None and model.format == "avro"
    assert revision_format(db, "t", "r1") == "avro"


def test_canonical_model_for_revision_skips_formats_without_mode_rules() -> None:
    db = _LineageDb([], source={"source_format": "raml", "format_metadata": {"sourceContent": "#%RAML 1.0"}})
    assert canonical_model_for_revision(db, "t", "r1") is None
    assert canonical_model_for_revision(_LineageDb([], source=None), "t", "r1") is None
    assert revision_format(_LineageDb([], source=None), "t", "r1") == "openapi"


def test_canonical_model_for_revision_without_a_captured_source_is_none() -> None:
    db = _LineageDb([], source={"source_format": "avro", "format_metadata": {}})
    assert canonical_model_for_revision(db, "t", "r1") is None


def test_parse_candidate_reads_the_base_format_and_reports_bad_text() -> None:
    model = parse_candidate("avro", json.dumps(_USER), source_label="schema.avsc")
    assert model.format == "avro"
    assert diff(model, _avro()).changes == []
    with pytest.raises(ValueError):
        parse_candidate("avro", "{not avro", source_label="schema.avsc")


def test_evaluated_under_markdown_is_silent_for_a_plain_openapi_diff() -> None:
    plain = evaluated_under(CompatibilityPolicy(), [FormatEvaluation("openapi", "ctg")], requested={})
    assert evaluated_under_markdown(plain) is None
    transitive = evaluated_under(
        CompatibilityPolicy(transitive=True),
        [FormatEvaluation("openapi", "ctg")],
        requested={},
        compared=[Baseline("r2", "2.0.0"), Baseline("r1", "1.0.0", "prior")],
    )
    assert evaluated_under_markdown(transitive) == "_Graded under every earlier version by ctg, against 2.0.0, 1.0.0._"
    proto = evaluated_under(
        CompatibilityPolicy(category="FILE"),
        [FormatEvaluation("protobuf", "buf-breaking", category_applied=True)],
        requested={},
    )
    assert evaluated_under_markdown(proto) == "_Graded under Protobuf category `FILE` by buf-breaking._"
