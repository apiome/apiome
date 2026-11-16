"""Tests for AsyncAPI channel and operation compatibility per side and mode (XPC-4.4, #5748).

The acceptance criteria pinned here:

* **every rule, per side and mode, in both majors** — the fixture pairs in
  ``tests/fixtures/asyncapi_compatibility/cases.json`` name each change's rule id, its consumer and
  producer grades and its verdict under ``BACKWARD`` / ``FORWARD`` / ``FULL``; AsyncAPI 2 and 3 both
  have a pair for every rule (``reply`` is AsyncAPI 3 only);
* **payload delegation** — an Avro payload change reports the Avro rule id, a JSON Schema payload
  the JSON Schema rule id, a ``.proto`` payload the Protobuf rule id;
* **the ``@asyncapi/diff`` overlay** still wins where it joins, and the sharpened baseline (with its
  unattributed findings) stands elsewhere;
* **side and mode are shown** — on the rule id and in the rationale every surface renders.

Models are built with the real AsyncAPI normalizer, so keys match production exactly.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import asyncapi_payload_compatibility as payloads
from app.asyncapi_compatibility_rules import (
    MODE_TEXT,
    coerce_mode,
    mode_sides,
    severity_under,
)
from app.asyncapi_diff import AsyncApiBreakingChangeClassifier, classify_asyncapi
from app.asyncapi_normalizer import AsyncApiNormalizer
from app.asyncapi_payload_compatibility import (
    SideFinding,
    compare_payloads,
    payload_of,
    schema_family,
    schema_format_identity,
    side_rule_id,
)
from app.breaking_change import Severity, classify
from app.diff import diff
from app.proto_normalizer import ProtoNormalizer

_FIXTURES = Path(__file__).parent / "fixtures"
_CASES: List[Dict[str, Any]] = json.loads((_FIXTURES / "asyncapi_compatibility" / "cases.json").read_text())["cases"]
_MODES = ("BACKWARD", "FORWARD", "FULL")

#: Every side rule the classifier owns (payload rules come from the payload's own check).
_SIDE_RULES = (
    "asyncapi.consumer.address-changed",
    "asyncapi.consumer.parameter-added",
    "asyncapi.both.parameter-added-with-default",
    "asyncapi.both.protocol-changed",
    "asyncapi.both.binding-changed",
    "asyncapi.both.action-flipped",
    "asyncapi.consumer.reply-removed",
    "asyncapi.consumer.message-removed",
    "asyncapi.producer.message-added",
    "asyncapi.both.schema-format-changed",
    "asyncapi.both.server-changed",
    "asyncapi.both.security-changed",
    "asyncapi.both.payload-compatible",
)

#: Rules AsyncAPI 2 cannot express.
_V3_ONLY = {"asyncapi.consumer.reply-removed"}


# ===========================================================================
# Helpers
# ===========================================================================


def _normalize(document: Dict[str, Any]):
    """A canonical model of a dereferenced AsyncAPI document (with ``raw`` kept)."""
    return AsyncApiNormalizer().normalize(copy.deepcopy(document))


def _grade(case: Dict[str, Any], mode: str):
    """Grade a fixture pair under ``mode`` with the sync classifier."""
    base, target = _normalize(case["old"]), _normalize(case["new"])
    return AsyncApiBreakingChangeClassifier(mode).classify(diff(base, target), base, target)


def _found(result, expect: Dict[str, Any]):
    """The classification or unattributed finding an expectation names."""
    if expect.get("unattributed"):
        hits = [u for u in result.unattributed if u.shape == expect["shape"] and u.rule_id == expect["rule_id"]]
    else:
        hits = [
            c
            for c in result.classifications
            if c.category.value == expect["category"] and c.key == expect["key"] and c.kind.value == expect["kind"]
        ]
    assert hits, f"no grade for {expect}; got {[(c.key, c.rule_id) for c in result.classifications]}"
    return hits[0]


def _case_params():
    return [
        pytest.param(case, expect, mode, id=f"{case['id']}-{i}-{mode}")
        for case in _CASES
        for i, expect in enumerate(case["expect"])
        for mode in _MODES
    ]


# ===========================================================================
# Fixture pairs: every rule, per side and mode, both majors
# ===========================================================================


@pytest.mark.parametrize(("case", "expect", "mode"), _case_params())
def test_fixture_pair_grades_per_mode(case: Dict[str, Any], expect: Dict[str, Any], mode: str) -> None:
    grade = _found(_grade(case, mode), expect)
    assert grade.rule_id == expect["rule_id"]
    assert grade.severity.value == expect["modes"][mode]


@pytest.mark.parametrize("rule_id", _SIDE_RULES)
def test_every_rule_has_a_pair_in_both_majors(rule_id: str) -> None:
    majors = {case["major"] for case in _CASES for e in case["expect"] if e["rule_id"] == rule_id}
    assert majors == ({3} if rule_id in _V3_ONLY else {2, 3})


@pytest.mark.parametrize("prefix", ["avro-compatibility.", "jsonschema."])
def test_payload_delegation_pairs_exist_in_both_majors(prefix: str) -> None:
    majors = {case["major"] for case in _CASES for e in case["expect"] if e["rule_id"].startswith(prefix)}
    assert majors == {2, 3}


def test_fixture_side_grades_match_the_rationale() -> None:
    """The rationale names the mode and both sides' grades (what the diff view and CLI show)."""
    for case in _CASES:
        for expect in case["expect"]:
            if expect["rule_id"] == "removed-entity":
                continue
            grade = _found(_grade(case, "FULL"), expect)
            assert grade.rationale.startswith(f"[FULL: {MODE_TEXT['FULL']}]")
            assert f"consumers: {expect['consumer']}, producers: {expect['producer']}" in grade.rationale


def test_message_removed_reads_by_mode() -> None:
    """The issue's example: breaking for consumers, safe for producers."""
    case = next(c for c in _CASES if c["id"] == "v3-message-removed")
    expect = case["expect"][0]
    assert _found(_grade(case, "BACKWARD"), expect).severity is Severity.BREAKING
    assert _found(_grade(case, "FORWARD"), expect).severity is Severity.DANGEROUS
    assert _found(_grade(case, "FULL"), expect).severity is Severity.BREAKING


def test_message_added_is_safe_under_backward() -> None:
    case = next(c for c in _CASES if c["id"] == "v2-message-added")
    expect = case["expect"][0]
    assert _found(_grade(case, "BACKWARD"), expect).severity is Severity.SAFE
    assert _found(_grade(case, "FORWARD"), expect).severity is Severity.DANGEROUS


def test_message_with_its_whole_operation_keeps_the_baseline() -> None:
    """A message that leaves with its operation is that operation's removal, not a union change."""
    case = next(c for c in _CASES if c["id"] == "v2-action-flipped-unnamed")
    result = _grade(case, "BACKWARD")
    messages = [c for c in result.classifications if c.category.value == "message"]
    assert messages and all(c.rule_id in ("added-entity", "removed-entity") for c in messages)


# ===========================================================================
# Modes and sides
# ===========================================================================


def test_mode_sides() -> None:
    assert mode_sides("BACKWARD") == {"consumer"}
    assert mode_sides("FORWARD") == {"producer"}
    assert mode_sides("FULL") == {"consumer", "producer"}
    assert mode_sides("FULL_TRANSITIVE") == {"consumer", "producer"}


def test_coerce_mode() -> None:
    assert coerce_mode(None) == "BACKWARD"
    assert coerce_mode(" forward ") == "FORWARD"
    assert coerce_mode("backward_transitive") == "BACKWARD_TRANSITIVE"
    with pytest.raises(ValueError):
        coerce_mode("SIDEWAYS")
    with pytest.raises(ValueError):
        AsyncApiBreakingChangeClassifier("SIDEWAYS")


@pytest.mark.parametrize(
    ("consumer", "producer", "expected"),
    [
        (Severity.BREAKING, Severity.SAFE, {"BACKWARD": "breaking", "FORWARD": "dangerous", "FULL": "breaking"}),
        (Severity.SAFE, Severity.DANGEROUS, {"BACKWARD": "safe", "FORWARD": "dangerous", "FULL": "dangerous"}),
        (Severity.BREAKING, Severity.DANGEROUS, {"BACKWARD": "breaking", "FORWARD": "dangerous", "FULL": "breaking"}),
        (
            Severity.DANGEROUS,
            Severity.DANGEROUS,
            {"BACKWARD": "dangerous", "FORWARD": "dangerous", "FULL": "dangerous"},
        ),
    ],
)
def test_severity_under_drops_an_unchecked_side_one_tier(consumer, producer, expected) -> None:
    finding = SideFinding("asyncapi.x.y", consumer, producer, "m")
    assert {mode: severity_under(finding, mode).value for mode in _MODES} == expected


def test_side_rule_id_names_the_worse_side() -> None:
    assert side_rule_id("message-removed", Severity.BREAKING, Severity.SAFE) == "asyncapi.consumer.message-removed"
    assert side_rule_id("message-added", Severity.SAFE, Severity.DANGEROUS) == "asyncapi.producer.message-added"
    assert side_rule_id("binding-changed", Severity.BREAKING, Severity.BREAKING) == "asyncapi.both.binding-changed"


def test_transitive_mode_grades_like_its_plain_mode() -> None:
    case = next(c for c in _CASES if c["id"] == "v3-message-removed")
    expect = case["expect"][0]
    grade = _found(_grade(case, "FORWARD_TRANSITIVE"), expect)
    assert grade.severity is Severity.DANGEROUS
    assert grade.rationale.startswith("[FORWARD_TRANSITIVE: old consumers against new producers]")


def test_sync_dispatch_grades_by_backward() -> None:
    case = next(c for c in _CASES if c["id"] == "v3-message-removed")
    base, target = _normalize(case["old"]), _normalize(case["new"])
    result = classify(diff(base, target), base, target)
    grade = next(c for c in result.classifications if c.key == "onOrder#event.OrderCancelled")
    assert grade.rule_id == "asyncapi.consumer.message-removed"
    assert grade.severity is Severity.BREAKING
    assert grade.rationale.startswith("[BACKWARD:")


# ===========================================================================
# Unhandled attributes keep the baseline grade
# ===========================================================================


def test_unhandled_move_is_graded_by_the_baseline_alongside_the_rule() -> None:
    """A compatible payload edit plus a content-type change: the content type's baseline grade wins."""
    case = next(c for c in _CASES if c["id"] == "v3-payload-compatible")
    new = copy.deepcopy(case["new"])
    new["channels"]["orders"]["messages"]["OrderPlaced"]["contentType"] = "application/avro"
    base, target = _normalize(case["old"]), _normalize(new)
    result = AsyncApiBreakingChangeClassifier().classify(diff(base, target), base, target)
    grade = next(c for c in result.classifications if c.key == "onOrder#event.OrderPlaced")
    assert grade.severity is Severity.DANGEROUS
    assert grade.rule_id == "modified-dangerous"
    assert "also changed content_types" in grade.rationale
    assert "asyncapi.both.payload-compatible" not in grade.rationale  # the rationale is prose
    assert "the json-schema payload check reads the change both ways" in grade.rationale


def test_payload_delegation_without_raw_uses_the_canonical_payload() -> None:
    case = next(c for c in _CASES if c["id"] == "v3-jsonschema-payload")
    base = _normalize(case["old"]).model_copy(update={"raw": None})
    target = _normalize(case["new"]).model_copy(update={"raw": None})
    result = AsyncApiBreakingChangeClassifier().classify(diff(base, target), base, target)
    grade = next(c for c in result.classifications if c.key == "onOrder#event.OrderPlaced")
    assert grade.rule_id == "jsonschema.backward.required-added"


def test_unsupported_schema_format_keeps_the_baseline() -> None:
    case = next(c for c in _CASES if c["id"] == "v2-jsonschema-payload")
    old, new = copy.deepcopy(case["old"]), copy.deepcopy(case["new"])
    for doc in (old, new):
        doc["channels"]["orders/{region}"]["subscribe"]["message"]["oneOf"][0]["schemaFormat"] = (
            "application/raml+yaml;version=1.0"
        )
    base, target = _normalize(old), _normalize(new)
    result = AsyncApiBreakingChangeClassifier().classify(diff(base, target), base, target)
    grade = next(c for c in result.classifications if c.key == "onOrder#event.OrderPlaced")
    assert grade.rule_id == "modified-breaking"  # the baseline's payload_schema grade


# ===========================================================================
# Payload helpers
# ===========================================================================


@pytest.mark.parametrize(
    ("schema_format", "identity", "family"),
    [
        (None, "application/vnd.aai.asyncapi", payloads.JSON_SCHEMA),
        ("application/vnd.aai.asyncapi+json;version=3.0.0", "application/vnd.aai.asyncapi", payloads.JSON_SCHEMA),
        ("application/schema+yaml;version=draft-07", "application/schema", payloads.JSON_SCHEMA),
        ("application/vnd.apache.avro;version=1.9.0", "application/vnd.apache.avro", payloads.AVRO),
        ("application/vnd.apache.avro+json;version=1.11.0", "application/vnd.apache.avro", payloads.AVRO),
        ("application/vnd.google.protobuf", "application/vnd.google.protobuf", payloads.PROTOBUF),
        ("application/raml+yaml;version=1.0", "application/raml", None),
    ],
)
def test_schema_format_identity_and_family(schema_format, identity, family) -> None:
    assert schema_format_identity(schema_format) == identity
    assert schema_family(schema_format) == family


def test_avro_version_parameter_is_not_a_format_change() -> None:
    old = {"schemaFormat": "application/vnd.apache.avro;version=1.9.0", "payload": "string"}
    new = {"schemaFormat": "application/vnd.apache.avro;version=1.11.0", "payload": "string"}
    assert compare_payloads(old, new) == []


def test_payload_of_reads_v3_multi_format_schema() -> None:
    assert payload_of({"payload": {"schemaFormat": "x", "schema": {"type": "string"}}}) == ("x", {"type": "string"})
    assert payload_of({"schemaFormat": "y", "payload": {"type": "string"}}) == ("y", {"type": "string"})


def test_unreadable_avro_payload_is_not_compared() -> None:
    avro = "application/vnd.apache.avro;version=1.9.0"
    assert (
        compare_payloads(
            {"schemaFormat": avro, "payload": {"type": "nope"}}, {"schemaFormat": avro, "payload": "string"}
        )
        is None
    )


def _proto_models(case_id: str):
    """The old/new Protobuf models of a recorded XPC-4.3 corpus case."""
    recordings = json.loads((_FIXTURES / "proto_breaking_categories" / "recordings.json").read_text())
    descriptors = recordings[case_id]["descriptors"]
    normalizer = ProtoNormalizer()
    return (
        normalizer.normalize(base64.b64decode(descriptors["old"])),
        normalizer.normalize(base64.b64decode(descriptors["new"])),
    )


def test_protobuf_payload_reports_the_protobuf_rule(monkeypatch) -> None:
    """A ``.proto`` text payload is compiled and graded by the Protobuf classifier."""
    old_model, new_model = _proto_models("field-number-reused")
    monkeypatch.setattr(payloads, "_proto_model", lambda text: old_model if text == "OLD" else new_model)
    proto = "application/vnd.google.protobuf"
    doc = {
        "asyncapi": "2.6.0",
        "info": {"title": "Orders", "version": "1.0.0"},
        "channels": {
            "orders": {
                "subscribe": {
                    "operationId": "onOrder",
                    "message": {"name": "Order", "schemaFormat": proto, "payload": "OLD"},
                }
            }
        },
    }
    new = copy.deepcopy(doc)
    new["channels"]["orders"]["subscribe"]["message"]["payload"] = "NEW"
    base, target = _normalize(doc), _normalize(new)
    result = AsyncApiBreakingChangeClassifier().classify(diff(base, target), base, target)
    # The canonical model keeps no text payload, so the diff lists no message: the finding is unattributed.
    assert result.classifications == []
    assert result.unattributed
    assert all(u.rule_id.startswith("protobuf.") and u.shape == "onOrder#event.Order" for u in result.unattributed)
    assert result.overall_severity is Severity.BREAKING


def test_protobuf_payload_without_buf_is_not_compared(monkeypatch) -> None:
    monkeypatch.setattr(payloads, "_proto_model", lambda text: None)
    proto = "application/vnd.google.protobuf"
    assert compare_payloads({"schemaFormat": proto, "payload": "a"}, {"schemaFormat": proto, "payload": "b"}) is None


# ===========================================================================
# The @asyncapi/diff overlay over the sharpened baseline
# ===========================================================================


class _FakeRunner:
    """A toolchain runner returning a canned ``@asyncapi/diff`` payload."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload

    async def run(self, tool_key, args, *, stdin=None, timeout=None):
        class _Result:
            parsed_json = self.payload

        return _Result()


async def test_overlay_wins_where_it_joins_and_the_sharpened_baseline_stands_elsewhere() -> None:
    case = next(c for c in _CASES if c["id"] == "v3-action-flipped")
    old = copy.deepcopy(case["old"])
    new = copy.deepcopy(case["new"])
    new["servers"]["prod"]["protocol"] = "amqp"
    del new["channels"]["orders"]["messages"]["OrderCancelled"]
    base, target = _normalize(old), _normalize(new)
    tool = {
        "changes": [
            {
                "action": "edit",
                "type": "non-breaking",
                "pointer": "/operations/onOrder",
                "path": ["operations", "onOrder"],
            }
        ]
    }

    result = await classify_asyncapi(base, target, runner=_FakeRunner(tool))

    operation = next(c for c in result.classifications if c.key == "onOrder")
    assert operation.rule_id == "asyncapi-diff.non-breaking"  # the tool's verdict joined
    message = next(c for c in result.classifications if c.key == "onOrder#event.OrderCancelled")
    assert message.rule_id == "asyncapi.consumer.message-removed"  # the sharpened baseline stands
    assert [u.rule_id for u in result.unattributed] == ["asyncapi.both.protocol-changed"]  # kept through the overlay
    assert result.overall_severity is Severity.BREAKING


async def test_classify_asyncapi_takes_a_mode() -> None:
    case = next(c for c in _CASES if c["id"] == "v2-message-removed")
    base, target = _normalize(case["old"]), _normalize(case["new"])
    result = await classify_asyncapi(base, target, runner=_FakeRunner({"changes": []}), mode="FORWARD")
    grade = next(c for c in result.classifications if c.key == "onOrder#event.OrderCancelled")
    assert grade.severity is Severity.DANGEROUS
    assert grade.rationale.startswith("[FORWARD:")


def test_named_operations_are_never_paired_as_a_flip() -> None:
    """Two differently named v3 operations on one channel are a removal and an addition, not a flip."""
    case = next(c for c in _CASES if c["id"] == "v3-action-flipped")
    new = copy.deepcopy(case["new"])
    new["operations"]["sendOrder"] = new["operations"].pop("onOrder")
    base, target = _normalize(case["old"]), _normalize(new)
    result = AsyncApiBreakingChangeClassifier().classify(diff(base, target), base, target)
    operations = {c.key: c.rule_id for c in result.classifications if c.category.value == "operation"}
    assert operations == {"onOrder": "removed-entity", "sendOrder": "added-entity"}
