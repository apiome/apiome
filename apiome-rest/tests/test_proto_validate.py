"""Tests for the Protovalidate ↔ canonical-constraint mapping — XPC-3.3 (#5743).

Three tiers, mirroring ``test_proto_normalizer.py``:

* **Fixture tests** (always run, no ``buf``) read the committed descriptor set of
  ``fixtures/proto/protovalidate/rules.proto`` — one message per rule family — and assert the
  mapping table, the acceptance criteria (``min_len = 3`` → ``minLength: 3`` in the canonical
  model and in the JSON Schema export), the CEL ledger and the write-back. A coverage test fails
  when a rule family of the vendored ``validate.proto`` has no fixture.
* **Synthetic tests** (always run) build options and canonical fields by hand for the shapes the
  fixture cannot hold: an unrecognized rule, a non-protobuf source model, unwritable facets.
* **Real-``buf`` tests** (gated) recompile the fixture and the vendored ``validate.proto`` to
  prove the committed descriptor sets are current, and round-trip ``normalize ∘ emit``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from google.protobuf import descriptor_pb2, json_format, text_format

from app import proto_validate
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from app.contract_suite import (
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    compile_contract_suite,
)
from app.contract_suite_rpc import _MODE_REQUEST, _MODE_RESPONSE, _SchemaBuilder
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fingerprint import canonical_fingerprint
from app.import_preview_manifest import (
    KNOWN_PARSER_LIMITS,
    CoverageClass,
    build_import_preview_manifest,
)
from app.jsonschema_emitter import JsonSchemaEmitter
from app.lossiness import LossinessKind
from app.proto_descriptor import (
    BUF_TOOL_KEY,
    ProtoFile,
    compile_proto_descriptor_set,
    read_file_descriptor_set,
    vendored_proto_imports,
)
from app.proto_emitter import ProtoEmitOptions, ProtoEmitter
from app.proto_normalizer import ProtoNormalizer
from app.proto_validate import (
    ONEOFS_REQUIRED_EXTRA_KEY,
    PROTOVALIDATE_EXTRA_KEY,
    PROTOVALIDATE_IMPORT,
    PROTOVALIDATE_REQUIRED_EXTRA_KEY,
    PROTOVALIDATE_UNRECOGNIZED_EXTRA_KEY,
    RULE_FAMILIES,
    UNSUPPORTED_CONSTRAINT_KIND,
    read_field_rules,
    render_field_options,
    rules_family_for_scalar,
)
from app.toolchain_packaging import probe_tool

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "proto" / "protovalidate"
_FIXTURE_PROTO = "rules.proto"
_PKG = "fixtures.protovalidate.v1"
_VENDORED = (
    Path(proto_validate.__file__).parent / "data" / "proto_vendor" / "buf" / "validate"
)


# ===========================================================================
# Helpers
# ===========================================================================


def _compiled():
    """The committed descriptor set of the fixture, with ``rules.proto`` as the target."""
    return read_file_descriptor_set(
        (_FIXTURE_DIR / "rules.binpb").read_bytes(), target_files=[_FIXTURE_PROTO]
    )


@pytest.fixture(scope="module")
def api() -> CanonicalApi:
    """The fixture normalized into the canonical model."""
    return ProtoNormalizer().normalize(_compiled(), include_raw=False)


def _field(api: CanonicalApi, message: str, name: str) -> CanonicalField:
    """One field of a fixture message."""
    type_ = api.type_by_key(f"{_PKG}.{message}")
    assert type_ is not None, message
    return next(field for field in type_.fields if field.name == name)


def _facets(field: CanonicalField) -> Dict[str, Any]:
    """A field's named constraint facets (no extras)."""
    if field.constraints is None:
        return {}
    return field.constraints.model_dump(exclude={"extras"}, exclude_none=True)


def _verbatim(field: CanonicalField) -> Optional[Dict[str, Any]]:
    """A field's verbatim Protovalidate rules."""
    return proto_validate.verbatim_rules(field.constraints)


def _options(rules: Dict[str, Any]) -> descriptor_pb2.FieldOptions:
    """Build ``FieldOptions`` carrying ``(buf.validate.field)`` from protobuf-JSON rules.

    The result is parsed by the *default* runtime, so the extension sits in its unknown fields
    exactly as it does in a compiled descriptor set.
    """
    runtime = proto_validate._runtime()
    typed = runtime.field_options()
    json_format.ParseDict(rules, typed.Extensions[runtime.field_extension])
    typed.Extensions[runtime.field_extension].SetInParent()
    return descriptor_pb2.FieldOptions.FromString(typed.SerializeToString())


def _model(*fields: CanonicalField, extras: Optional[Dict[str, Any]] = None) -> CanonicalApi:
    """A one-message canonical model, as a non-protobuf source would produce it."""
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[
            Type(key="p.M", name="M", kind=TypeKind.RECORD, fields=list(fields), extras=extras or {})
        ],
    )


def _proto_text(api: CanonicalApi, **options: Any) -> str:
    """The emitted ``.proto`` text."""
    return str(ProtoEmitter().emit(api, opts=ProtoEmitOptions(**options)).files[0].content)


# ===========================================================================
# Coverage: no rule family without a fixture
# ===========================================================================


def test_rule_families_match_the_vendored_validate_proto() -> None:
    """``RULE_FAMILIES`` is exactly the ``type`` oneof of the vendored ``FieldRules``."""
    rules = proto_validate._runtime().field_rules.DESCRIPTOR
    assert set(RULE_FAMILIES) == {member.name for member in rules.oneofs_by_name["type"].fields}
    assert len(RULE_FAMILIES) == len(set(RULE_FAMILIES))


def test_every_rule_family_has_a_fixture() -> None:
    """No family can claim support without a field in the fixture set that uses it."""
    runtime = proto_validate._runtime()
    used = set()

    def walk(message: descriptor_pb2.DescriptorProto) -> None:
        for field in message.field:
            rules = proto_validate._extension_of(
                field.options, runtime.field_options, runtime.field_extension
            )
            if rules is not None and rules.WhichOneof("type"):
                used.add(rules.WhichOneof("type"))
        for nested in message.nested_type:
            walk(nested)

    fixture = next(file for file in _compiled().proto.file if file.name == _FIXTURE_PROTO)
    for message in fixture.message_type:
        walk(message)
    assert used == set(RULE_FAMILIES)


# ===========================================================================
# Acceptance: min_len = 3 → minLength: 3, canonical and JSON Schema
# ===========================================================================


def test_min_len_imports_to_canonical_min_length(api: CanonicalApi) -> None:
    handle = _field(api, "CreateAccountRequest", "handle")
    assert handle.constraints is not None
    assert handle.constraints.min_length == 3
    assert _verbatim(handle) is None


def test_json_schema_export_carries_the_mapped_constraints(api: CanonicalApi) -> None:
    document = json.loads(JsonSchemaEmitter().emit(api).files[0].content)
    request = next(
        schema for key, schema in document["$defs"].items() if key.endswith("CreateAccountRequest")
    )
    assert request["properties"]["handle"]["minLength"] == 3
    assert request["properties"]["email"]["format"] == "email"
    assert request["properties"]["seats"]["minimum"] == 1
    assert request["properties"]["seats"]["maximum"] == 500
    assert request["required"] == ["email"]


def test_model_survives_a_jsonb_round_trip_with_a_stable_fingerprint(api: CanonicalApi) -> None:
    again = ProtoNormalizer().normalize(_compiled(), include_raw=False)
    assert CanonicalApi.model_validate(api.model_dump()) == api
    assert canonical_fingerprint(again) == canonical_fingerprint(api)


def test_a_rule_change_flips_the_fingerprint(api: CanonicalApi) -> None:
    changed = api.model_copy(deep=True)
    _field(changed, "CreateAccountRequest", "handle").constraints.min_length = 4
    assert canonical_fingerprint(changed) != canonical_fingerprint(api)


def test_a_proto_without_rules_gets_no_constraints_and_no_record() -> None:
    """A descriptor set with no ``buf.validate`` option normalizes exactly as before."""
    descriptor_set = descriptor_pb2.FileDescriptorSet()
    file_proto = descriptor_set.file.add(name="plain.proto", package="plain", syntax="proto3")
    message = file_proto.message_type.add(name="M")
    message.field.add(
        name="n",
        number=1,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    )
    plain = ProtoNormalizer().normalize(descriptor_set, include_raw=False)
    assert plain.types[0].fields[0].constraints is None
    assert PROTOVALIDATE_EXTRA_KEY not in plain.extras


# ===========================================================================
# The mapping table, one fixture field per rule
# ===========================================================================

#: (message, field) → the named canonical facets the rule maps to.
_MAPPED = [
    ("StringFixture", "min_len", {"min_length": 3}),
    ("StringFixture", "max_len", {"max_length": 64}),
    ("StringFixture", "len", {"min_length": 8, "max_length": 8}),
    ("StringFixture", "pattern", {"pattern": "^[a-z]+(-[a-z]+)*$"}),
    ("StringFixture", "const", {"enum": ["fixed"]}),
    ("StringFixture", "in", {"enum": ["red", "green", "blue"]}),
    ("StringFixture", "email", {"format": "email"}),
    ("StringFixture", "hostname", {"format": "hostname"}),
    ("StringFixture", "ipv4", {"format": "ipv4"}),
    ("StringFixture", "ipv6", {"format": "ipv6"}),
    ("StringFixture", "uri", {"format": "uri"}),
    ("StringFixture", "uri_ref", {"format": "uri-reference"}),
    ("StringFixture", "uuid", {"format": "uuid"}),
    ("NumericFixture", "float_range", {"exclusive_minimum": 0.0, "maximum": 1.0}),
    ("NumericFixture", "double_range", {"minimum": -90.0, "maximum": 90.0}),
    ("NumericFixture", "int32_range", {"minimum": 1.0, "exclusive_maximum": 100.0}),
    ("NumericFixture", "int64_range", {"exclusive_minimum": 0.0, "maximum": 1000000.0}),
    ("NumericFixture", "uint32_in", {"enum": [1, 2, 4, 8]}),
    ("NumericFixture", "uint64_gt", {"exclusive_minimum": 0.0}),
    ("NumericFixture", "sint32_const", {"enum": [-1]}),
    ("NumericFixture", "sint64_lte", {"maximum": 0.0}),
    ("NumericFixture", "fixed32_gte", {"minimum": 10.0}),
    ("NumericFixture", "fixed64_lt", {"exclusive_maximum": 4096.0}),
    ("NumericFixture", "sfixed32_gt", {"exclusive_minimum": -5.0}),
    ("NumericFixture", "sfixed64_range", {"minimum": -10.0, "maximum": 10.0}),
    ("BoolFixture", "accepted", {"enum": [True]}),
    ("RepeatedFixture", "tags", {"min_items": 1, "max_items": 10, "unique_items": True}),
]

#: (message, field) → the rules kept verbatim (no JSON-Schema analogue, or not exact).
_VERBATIM = [
    ("StringFixture", "prefix", {"string": {"prefix": "acct_"}}),
    ("StringFixture", "suffix", {"string": {"suffix": ".json"}}),
    ("StringFixture", "contains", {"string": {"contains": "@"}}),
    ("StringFixture", "not_contains", {"string": {"not_contains": " "}}),
    ("StringFixture", "not_in", {"string": {"not_in": ["root", "admin"]}}),
    ("StringFixture", "max_bytes", {"string": {"max_bytes": "256"}}),
    ("StringFixture", "ip", {"string": {"ip": True}}),
    ("NumericFixture", "not_in", {"int32": {"not_in": [0, 13]}}),
    ("NumericFixture", "finite", {"double": {"finite": True}}),
    # A reversed range means "outside 10..100"; minimum/maximum would make it unsatisfiable.
    ("NumericFixture", "outside", {"int32": {"lt": 10, "gt": 100}}),
    # 2**53 + 1 is not exactly representable as the float a canonical bound is.
    ("NumericFixture", "huge", {"int64": {"lt": "9007199254740993"}}),
    ("BytesFixture", "digest", {"bytes": {"len": "32"}}),
    ("BytesFixture", "payload", {"bytes": {"min_len": "1", "max_len": "1024"}}),
    ("EnumFixture", "defined_only", {"enum": {"defined_only": True}}),
    ("EnumFixture", "in", {"enum": {"in": [1, 2]}}),
    ("EnumFixture", "not_in", {"enum": {"not_in": [0]}}),
    ("RepeatedFixture", "codes", {"repeated": {"items": {"string": {"len": "3"}}}}),
    (
        "MapFixture",
        "quotas",
        {
            "map": {
                "min_pairs": "1",
                "max_pairs": "8",
                "keys": {"string": {"min_len": "1"}},
                "values": {"int32": {"gte": 0}},
            }
        },
    ),
    ("AnyFixture", "detail", {"any": {"in": [f"type.googleapis.com/{_PKG}.Account"]}}),
    ("DurationFixture", "timeout", {"duration": {"gte": "1s", "lte": "300s"}}),
    ("FieldMaskFixture", "update_mask", {"field_mask": {"in": ["handle", "email"]}}),
    ("TimestampFixture", "created_at", {"timestamp": {"lt_now": True}}),
    ("TimestampFixture", "expires_at", {"timestamp": {"gt_now": True, "within": "86400s"}}),
    ("TimestampFixture", "not_before", {"timestamp": {"gte": "2023-11-14T22:13:20Z"}}),
]


@pytest.mark.parametrize(("message", "name", "expected"), _MAPPED)
def test_standard_rule_maps_to_named_facets(
    api: CanonicalApi, message: str, name: str, expected: Dict[str, Any]
) -> None:
    field = _field(api, message, name)
    assert _facets(field) == expected
    assert _verbatim(field) is None  # fully mapped: nothing rides in extras


@pytest.mark.parametrize(("message", "name", "expected"), _VERBATIM)
def test_rule_without_a_json_schema_analogue_is_kept_verbatim(
    api: CanonicalApi, message: str, name: str, expected: Dict[str, Any]
) -> None:
    field = _field(api, message, name)
    assert _verbatim(field) == expected
    assert _facets(field) == {}


def test_mapped_and_verbatim_rules_split_on_one_field(api: CanonicalApi) -> None:
    slug = _field(api, "StringFixture", "slug")
    assert _facets(slug) == {"min_length": 2, "max_length": 40}
    assert _verbatim(slug) == {"string": {"prefix": "s-"}}


def test_required_is_non_nullable_with_the_write_back_flag(api: CanonicalApi) -> None:
    for name in ("name", "count", "account"):
        field = _field(api, "RequiredFixture", name)
        assert field.type.nullable is False, name
        assert field.extras[PROTOVALIDATE_REQUIRED_EXTRA_KEY] is True
    # A repeated field is flagged; its list reference is non-nullable in every syntax already.
    tags = _field(api, "RequiredFixture", "tags")
    assert tags.extras[PROTOVALIDATE_REQUIRED_EXTRA_KEY] is True
    assert tags.type.is_list()
    # Presence keeps its own spelling: the proto3 `optional` label is still recorded.
    assert _field(api, "RequiredFixture", "count").extras["proto3_optional"] is True
    # An unruled sibling stays nullable and unflagged.
    phone = _field(api, "RequiredFixture", "phone")
    assert phone.type.nullable is True
    assert PROTOVALIDATE_REQUIRED_EXTRA_KEY not in phone.extras


def test_required_oneof_is_recorded_on_the_type(api: CanonicalApi) -> None:
    type_ = api.type_by_key(f"{_PKG}.RequiredFixture")
    assert type_.extras["oneofs"] == ["contact", "nickname"]
    assert type_.extras[ONEOFS_REQUIRED_EXTRA_KEY] == ["contact"]


# ===========================================================================
# CEL: recorded as unsupported_constraint, never evaluated
# ===========================================================================


def test_cel_rules_are_kept_verbatim_on_their_field_and_message(api: CanonicalApi) -> None:
    type_ = api.type_by_key(f"{_PKG}.CelFixture")
    assert type_.extras[PROTOVALIDATE_EXTRA_KEY] == {
        "cel": [
            {
                "id": "window.order",
                "message": "start must be before end",
                "expression": "this.start < this.end",
            }
        ],
        "cel_expression": ["this.start >= 0"],
    }
    assert _verbatim(_field(api, "CelFixture", "end")) == {
        "cel": [{"id": "end.even", "message": "end must be even", "expression": "this % 2 == 0"}]
    }
    # A standard rule beside a CEL one is still mapped.
    label = _field(api, "CelFixture", "label")
    assert _facets(label) == {"max_length": 20}
    assert _verbatim(label) == {"cel_expression": ["this.size() > 0"]}


def test_every_cel_rule_is_an_unsupported_constraint_with_its_expression(
    api: CanonicalApi,
) -> None:
    limits = api.extras[PROTOVALIDATE_EXTRA_KEY]["capability_limits"]
    assert {limit["kind"] for limit in limits} == {UNSUPPORTED_CONSTRAINT_KIND}
    assert [(limit["location"], limit["path"], limit["expression"]) for limit in limits] == [
        (f"{_PKG}.CelFixture", "cel", "this.start < this.end"),
        (f"{_PKG}.CelFixture", "cel_expression", "this.start >= 0"),
        (f"{_PKG}.CelFixture.end", "cel", "this % 2 == 0"),
        (f"{_PKG}.CelFixture.label", "cel_expression", "this.size() > 0"),
    ]
    assert limits[0]["id"] == "window.order"
    assert all(limit["preserved"] for limit in limits)


def test_cel_nested_in_item_rules_is_found() -> None:
    reading = read_field_rules(
        _options({"repeated": {"items": {"cel": [{"id": "i", "expression": "this != ''"}]}}})
    )
    field = CanonicalField(
        key="p.M.f", name="f", type=TypeRef(item=TypeRef(name="string")), constraints=reading.constraints
    )
    limits = proto_validate.unsupported_constraints(_model(field).types)
    assert [(limit["path"], limit["expression"]) for limit in limits] == [
        ("repeated.items.cel", "this != ''")
    ]


def test_cel_rules_appear_in_the_import_coverage_ledger(api: CanonicalApi) -> None:
    manifest = build_import_preview_manifest(api, adapter_key="grpc", options={})
    rows = [
        row
        for row in manifest.document_coverage
        if row.source_construct.startswith("buf.validate#")
    ]
    assert len(rows) == 4
    assert {row.coverage for row in rows} == {CoverageClass.PARTIALLY_MAPPED}
    by_construct = {row.source_construct: row for row in rows}
    end = by_construct[f"buf.validate#{_PKG}.CelFixture.end:cel"]
    assert end.entity_key == f"{_PKG}.CelFixture.end"
    assert "unsupported_constraint" in end.detail
    assert "this % 2 == 0" in end.detail
    assert "end.even" in end.detail
    assert end.document_scoped is True


def test_cel_is_declared_in_the_adapter_parser_limits() -> None:
    constructs = [limit.construct for limit in KNOWN_PARSER_LIMITS["grpc"]]
    assert "Protovalidate CEL and predefined rules" in constructs


def test_json_schema_export_reports_the_rules_it_cannot_carry(api: CanonicalApi) -> None:
    losses = [
        loss for loss in JsonSchemaEmitter().emit(api).losses if loss.subject == "protovalidate-rules"
    ]
    by_pointer = {loss.pointer: loss.detail for loss in losses}
    assert "cel" in by_pointer[f"{_PKG}.CelFixture.end"]
    assert "cel, cel_expression" in by_pointer[f"{_PKG}.CelFixture"]
    assert "string.prefix" in by_pointer[f"{_PKG}.StringFixture.prefix"]
    assert "oneof contact required" in by_pointer[f"{_PKG}.RequiredFixture"]
    # A fully mapped rule is a keyword, not a loss.
    assert f"{_PKG}.StringFixture.min_len" not in by_pointer


def _predicted(report, needle: str) -> Dict[str, LossinessKind]:
    """Construct key → kind of every predicted item whose message mentions ``needle``."""
    return {item.construct_key: item.kind for item in report.items if needle in item.message}


def test_other_targets_predict_the_verbatim_rules_as_lossy(api: CanonicalApi) -> None:
    predicted = _predicted(compute_lossiness_for_emitter(api, JsonSchemaEmitter), "Protovalidate")
    assert predicted[f"{_PKG}.CelFixture.end"] is LossinessKind.APPROX
    assert predicted[f"{_PKG}.CelFixture"] is LossinessKind.APPROX  # message.cel
    assert predicted[f"{_PKG}.RequiredFixture"] is LossinessKind.APPROX  # required oneof
    assert predicted[f"{_PKG}.StringFixture.prefix"] is LossinessKind.APPROX
    assert f"{_PKG}.StringFixture.min_len" not in predicted  # a keyword, not a loss


def test_proto_target_predicts_no_loss_for_rules_it_writes_back(api: CanonicalApi) -> None:
    report = compute_lossiness_for_emitter(api, ProtoEmitter)
    assert _predicted(report, "Protovalidate") == {}
    # `required` is written back as a rule, so it is no longer "not enforced".
    assert f"{_PKG}.RequiredFixture.name" not in _predicted(report, "non-null/required")
    # ...and the same model with the option off predicts every ruled construct as a loss.
    off = compute_lossiness_for_emitter(api, ProtoEmitter, options={"protovalidate": False})
    dropped = _predicted(off, "Protovalidate")
    assert f"{_PKG}.StringFixture.min_len" in dropped
    assert f"{_PKG}.CelFixture.end" in dropped
    assert f"{_PKG}.CelFixture" in dropped
    assert f"{_PKG}.RequiredFixture.name" in dropped


# ===========================================================================
# Unrecognized rules (predefined / another validate.proto version)
# ===========================================================================


def _unrecognized_options() -> descriptor_pb2.FieldOptions:
    """``string.min_len = 3`` plus an extension-range field (1001) the reader does not know."""
    options = _options({"string": {"min_len": "3"}})
    runtime = proto_validate._runtime()
    typed = runtime.field_options.FromString(options.SerializeToString())
    string_rules = typed.Extensions[runtime.field_extension].string
    string_rules.MergeFromString(b"\xc8\x3e\x01")  # field 1001, varint 1
    return descriptor_pb2.FieldOptions.FromString(typed.SerializeToString())


def test_unrecognized_rule_is_reported_and_the_known_one_still_maps() -> None:
    reading = read_field_rules(_unrecognized_options())
    assert reading.constraints.min_length == 3
    assert reading.unrecognized == ["string.#1001"]


def test_unrecognized_rule_reaches_the_ledger_and_the_export_losses() -> None:
    reading = read_field_rules(_unrecognized_options())
    field = CanonicalField(
        key="p.M.f",
        name="f",
        type=TypeRef(name="string"),
        field_number=1,
        constraints=reading.constraints,
        extras={PROTOVALIDATE_UNRECOGNIZED_EXTRA_KEY: reading.unrecognized},
    )
    api = _model(field)
    api.extras[PROTOVALIDATE_EXTRA_KEY] = {
        "capability_limits": proto_validate.unsupported_constraints(api.types)
    }
    limit = api.extras[PROTOVALIDATE_EXTRA_KEY]["capability_limits"][0]
    assert limit["kind"] == UNSUPPORTED_CONSTRAINT_KIND
    assert limit["preserved"] is False

    manifest = build_import_preview_manifest(api, adapter_key="grpc", options={})
    row = next(
        row for row in manifest.document_coverage if row.source_construct.startswith("buf.validate#")
    )
    assert row.coverage is CoverageClass.NOT_PARSED_BY_ADAPTER
    assert row.capability_reference is not None  # every not-parsed row names its registry entry

    subjects = {loss.subject for loss in ProtoEmitter().emit(api).losses}
    assert "protovalidate-unrecognized-rule" in subjects


def test_field_without_the_option_reads_as_none() -> None:
    assert read_field_rules(descriptor_pb2.FieldOptions()) is None
    assert read_field_rules(descriptor_pb2.FieldOptions(deprecated=True)) is None


def test_ignore_always_keeps_every_rule_verbatim() -> None:
    """Rules that are switched off must not become constraints anything enforces."""
    rules = {"ignore": "IGNORE_ALWAYS", "required": True, "string": {"min_len": "3"}}
    reading = read_field_rules(_options(rules))
    assert reading.required is False
    assert reading.constraints.min_length is None
    assert proto_validate.verbatim_rules(reading.constraints) == rules
    # ...and they are written back exactly as they were.
    field = CanonicalField(
        key="p.M.f", name="f", type=TypeRef(name="string"), constraints=reading.constraints
    )
    assert render_field_options(field, "string").options == [
        "(buf.validate.field).string.min_len = 3",
        "(buf.validate.field).required = true",
        "(buf.validate.field).ignore = IGNORE_ALWAYS",
    ]


def test_ignore_if_zero_value_is_still_mapped() -> None:
    reading = read_field_rules(
        _options({"ignore": "IGNORE_IF_ZERO_VALUE", "string": {"min_len": "3"}})
    )
    assert reading.constraints.min_length == 3
    assert proto_validate.verbatim_rules(reading.constraints) == {"ignore": "IGNORE_IF_ZERO_VALUE"}


def test_explicit_required_false_is_not_required() -> None:
    reading = read_field_rules(_options({"required": False}))
    assert reading.required is False
    assert reading.constraints is None


# ===========================================================================
# Writing rules back — the symmetry rule
# ===========================================================================


def test_emitter_writes_the_rules_back_and_imports_validate_proto(api: CanonicalApi) -> None:
    text = _proto_text(api)
    assert f'import "{PROTOVALIDATE_IMPORT}";' in text
    assert "string handle = 1 [(buf.validate.field).string.min_len = 3];" in text
    assert "(buf.validate.field).required = true" in text
    assert "option (buf.validate.oneof).required = true;" in text
    assert '(buf.validate.field).string.prefix = "acct_"' in text
    assert "(buf.validate.field).repeated.unique = true" in text
    assert "(buf.validate.field).timestamp.within = { seconds: 86400 }" in text
    assert "(buf.validate.field).map.keys = { string { min_len: 1 } }" in text
    # CEL is written back verbatim, never interpreted.
    assert (
        'option (buf.validate.message).cel = { id: "window.order" '
        'message: "start must be before end" expression: "this.start < this.end" };'
    ) in text
    assert '(buf.validate.field).cel_expression = "this.size() > 0"' in text
    # A repeated rule is assigned once per element.
    assert text.count("(buf.validate.field).string.in = ") == 3


def test_emitting_the_fixture_records_no_constraint_loss(api: CanonicalApi) -> None:
    subjects = {loss.subject for loss in ProtoEmitter().emit(api).losses}
    assert not subjects & {
        "field-constraints",
        "protovalidate-rules-dropped",
        "protovalidate-unrecognized-rule",
    }


def test_several_options_are_written_one_per_line(api: CanonicalApi) -> None:
    text = _proto_text(api)
    assert (
        "  string email = 2 [\n"
        "    (buf.validate.field).string.email = true,\n"
        "    (buf.validate.field).required = true\n"
        "  ];"
    ) in text


def test_every_canonical_facet_read_is_written_for_every_fixture_field(api: CanonicalApi) -> None:
    """Symmetry, without ``buf``: rendering each field and re-reading the rules is the identity."""
    types = {type_.key: type_ for type_ in api.types}
    checked = 0
    for type_ in api.types:
        for field in type_.fields:
            required = bool(field.extras.get(PROTOVALIDATE_REQUIRED_EXTRA_KEY))
            if field.constraints is None and not required:
                continue
            leaf = field.type.item if field.type.is_list() else field.type
            scalar = leaf.name if leaf.name not in types else None
            family = rules_family_for_scalar(scalar, repeated=field.type.is_list())
            rendered = render_field_options(field, family)
            assert rendered.unwritten == [], field.key
            reread = read_field_rules(_options(_rules_json(rendered.options)))
            assert reread.required == required, field.key
            assert _dump(reread.constraints) == _dump(field.constraints), field.key
            checked += 1
    assert checked > 60


def _dump(constraints: Optional[Constraints]) -> Optional[Dict[str, Any]]:
    """Constraints as plain data (``None`` when absent)."""
    return constraints.model_dump(exclude_none=True) if constraints is not None else None


def _rules_json(assignments: List[str]) -> Dict[str, Any]:
    """Parse rendered ``(buf.validate.field).path = literal`` assignments back into rules JSON.

    Shares nothing with the writer but its output: each assignment is re-spelled as protobuf
    text format and merged, which is what the ``.proto`` compiler does with an option list.
    """
    rules = proto_validate._runtime().field_rules()
    for assignment in assignments:
        path, literal = assignment.split(" = ", 1)
        names = path[len(proto_validate.FIELD_OPTION) + 1 :].split(".")
        text = f"{names[-1]} {literal}" if literal.startswith("{") else f"{names[-1]}: {literal}"
        for name in reversed(names[:-1]):
            text = f"{name} {{ {text} }}"
        text_format.Merge(text, rules)
    return json_format.MessageToDict(rules, preserving_proto_field_name=True)


def test_constraints_from_another_format_are_written_as_rules() -> None:
    """An OpenAPI-shaped model (canonical scalar names, no rule extras) gets the same rules."""
    api = _model(
        CanonicalField(
            key="p.M.name",
            name="name",
            type=TypeRef(name="string"),
            field_number=1,
            constraints=Constraints(min_length=1, max_length=80, pattern="^[A-Z]", format="email"),
        ),
        CanonicalField(
            key="p.M.age",
            name="age",
            type=TypeRef(name="integer"),
            field_number=2,
            constraints=Constraints(minimum=0, exclusive_maximum=150, format="int32"),
        ),
        CanonicalField(
            key="p.M.ratio",
            name="ratio",
            type=TypeRef(name="double"),
            field_number=3,
            constraints=Constraints(minimum=0.5, maximum=1.5),
        ),
        CanonicalField(
            key="p.M.color",
            name="color",
            type=TypeRef(name="string"),
            field_number=4,
            constraints=Constraints(enum=["red", "green"]),
        ),
        CanonicalField(
            key="p.M.tags",
            name="tags",
            type=TypeRef(item=TypeRef(name="string")),
            field_number=5,
            constraints=Constraints(min_items=1, unique_items=True),
        ),
        CanonicalField(
            key="p.M.flag",
            name="flag",
            type=TypeRef(name="bool"),
            field_number=6,
            constraints=Constraints(enum=[True]),
        ),
    )
    text = _proto_text(api)
    for expected in (
        "(buf.validate.field).string.min_len = 1",
        "(buf.validate.field).string.max_len = 80",
        '(buf.validate.field).string.pattern = "^[A-Z]"',
        "(buf.validate.field).string.email = true",
        "(buf.validate.field).int32.lt = 150",
        "(buf.validate.field).int32.gte = 0",
        "(buf.validate.field).double.gte = 0.5",
        "(buf.validate.field).double.lte = 1.5",
        '(buf.validate.field).string.in = "red"',
        "(buf.validate.field).repeated.min_items = 1",
        "(buf.validate.field).repeated.unique = true",
        "(buf.validate.field).bool.const = true",
    ):
        assert expected in text, expected


def test_a_required_list_of_another_format_is_not_written_as_protovalidate_required() -> None:
    """Only the Protovalidate flag writes ``required``: it forbids the zero value, which an
    OpenAPI ``required`` entry does not."""
    api = _model(
        CanonicalField(
            key="p.M.n", name="n", type=TypeRef(name="int32", nullable=False), field_number=1
        )
    )
    text = _proto_text(api)
    assert "buf.validate" not in text
    assert "int32 n = 1;" in text


def test_facets_with_no_standard_rule_are_a_named_loss() -> None:
    api = _model(
        CanonicalField(
            key="p.M.n",
            name="n",
            type=TypeRef(name="int32"),
            field_number=1,
            constraints=Constraints(minimum=0, multiple_of=5, format="int32"),
        ),
        CanonicalField(
            key="p.M.when",
            name="when",
            type=TypeRef(name="string"),
            field_number=2,
            constraints=Constraints(format="date-time"),
        ),
        CanonicalField(
            key="p.M.half",
            name="half",
            type=TypeRef(name="int32"),
            field_number=3,
            constraints=Constraints(minimum=0.5),
        ),
        CanonicalField(
            key="p.M.count",
            name="count",
            type=TypeRef(name="uint32"),
            field_number=4,
            constraints=Constraints(minimum=-1),
        ),
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    assert "int32 n = 1 [(buf.validate.field).int32.gte = 0];" in text
    assert "string when = 2;" in text
    assert "int32 half = 3;" in text  # 0.5 is not an int32 bound
    assert "uint32 count = 4;" in text  # -1 is out of a uint32 rule's range
    details = {
        loss.pointer: loss.detail for loss in result.losses if loss.subject == "field-constraints"
    }
    assert "format, multiple_of" in details["p.M.n"]
    assert "format" in details["p.M.when"]
    assert "minimum" in details["p.M.half"]
    assert "minimum" in details["p.M.count"]


def test_the_stricter_bound_is_written_when_both_are_set() -> None:
    lower = CanonicalField(
        key="p.M.a",
        name="a",
        type=TypeRef(name="int32"),
        constraints=Constraints(minimum=5, exclusive_minimum=5, maximum=9, exclusive_maximum=20),
    )
    rendered = render_field_options(lower, "int32")
    assert rendered.unwritten == []
    assert sorted(rendered.options) == [
        "(buf.validate.field).int32.gt = 5",
        "(buf.validate.field).int32.lte = 9",
    ]


def test_named_facets_do_not_replace_a_verbatim_rule_of_another_family() -> None:
    """A ``FieldRules`` holds one family; the verbatim rules win and the facets are reported."""
    field = CanonicalField(
        key="p.M.a",
        name="a",
        type=TypeRef(name="string"),
        constraints=Constraints(
            min_length=2, extras={PROTOVALIDATE_EXTRA_KEY: {"bytes": {"max_len": "4"}}}
        ),
    )
    rendered = render_field_options(field, "string")
    assert rendered.options == ["(buf.validate.field).bytes.max_len = 4"]
    assert rendered.unwritten == ["min_length"]


def test_an_unreadable_verbatim_bag_is_reported_not_raised() -> None:
    field = CanonicalField(
        key="p.M.a",
        name="a",
        type=TypeRef(name="string"),
        constraints=Constraints(extras={PROTOVALIDATE_EXTRA_KEY: {"no_such_rule": 1}}),
    )
    rendered = render_field_options(field, "string")
    assert rendered.options == []
    assert rendered.unwritten == [PROTOVALIDATE_EXTRA_KEY]


def test_string_literals_are_escaped() -> None:
    field = CanonicalField(
        key="p.M.a",
        name="a",
        type=TypeRef(name="string"),
        constraints=Constraints(pattern='^"\\d+"$'),
    )
    assert render_field_options(field, "string").options == [
        '(buf.validate.field).string.pattern = "^\\"\\\\d+\\"$"'
    ]


def test_protovalidate_off_drops_rules_and_says_so(api: CanonicalApi) -> None:
    result = ProtoEmitter().emit(api, opts=ProtoEmitOptions(protovalidate=False))
    text = str(result.files[0].content)
    assert "buf.validate" not in text
    assert "buf/validate" not in text
    subjects = [loss.subject for loss in result.losses]
    assert "field-constraints" in subjects
    dropped = {
        loss.pointer for loss in result.losses if loss.subject == "protovalidate-rules-dropped"
    }
    assert f"{_PKG}.RequiredFixture.name" in dropped
    assert f"{_PKG}.RequiredFixture.contact" in dropped  # the required oneof
    assert f"{_PKG}.CelFixture" in dropped  # message rules


def test_rules_family_for_scalar() -> None:
    assert rules_family_for_scalar("string") == "string"
    assert rules_family_for_scalar("sfixed64") == "sfixed64"
    assert rules_family_for_scalar("bool") == "bool"
    assert rules_family_for_scalar("string", repeated=True) == "repeated"
    assert rules_family_for_scalar("bytes") is None  # byte lengths are not JSON string lengths
    assert rules_family_for_scalar(None) is None
    assert rules_family_for_scalar(".pkg.Message") is None


# ===========================================================================
# Contract suite (XPC-3.2 negatives, sharpened)
# ===========================================================================


def test_request_schema_is_narrowed_by_the_constraints(api: CanonicalApi) -> None:
    types = {type_.key: type_ for type_ in api.types}
    for mode in (_MODE_REQUEST, _MODE_RESPONSE):
        builder = _SchemaBuilder(types, mode)
        builder.named(f"{_PKG}.CreateAccountRequest")
        schema = builder.defs[f"{_PKG}.CreateAccountRequest"]
        assert schema["properties"]["handle"]["minLength"] == 3
        assert schema["properties"]["email"]["format"] == "email"
        # The rule's range, tightened inside int32's own.
        assert schema["properties"]["seats"]["minimum"] == 1
        assert schema["properties"]["seats"]["maximum"] == 500
        assert schema["required"] == ["email"]


def test_required_oneof_keeps_its_first_member_required_in_a_request(api: CanonicalApi) -> None:
    types = {type_.key: type_ for type_ in api.types}
    builder = _SchemaBuilder(types, _MODE_REQUEST)
    builder.named(f"{_PKG}.RequiredFixture")
    required = builder.defs[f"{_PKG}.RequiredFixture"]["required"]
    assert required == ["account", "count", "name", "phone", "tags"]


def test_enum_is_not_applied_where_a_response_accepts_two_json_types() -> None:
    field = CanonicalField(
        key="p.M.n",
        name="n",
        type=TypeRef(name="int64"),
        field_number=1,
        constraints=Constraints(enum=[1, 2], minimum=1),
    )
    types = {type_.key: type_ for type_ in _model(field).types}
    response = _SchemaBuilder(types, _MODE_RESPONSE)
    response.named("p.M")
    assert "enum" not in response.defs["p.M"]["properties"]["n"]
    assert response.defs["p.M"]["properties"]["n"]["minimum"] == 1
    request = _SchemaBuilder(types, _MODE_REQUEST)
    request.named("p.M")
    assert request.defs["p.M"]["properties"]["n"]["enum"] == [1, 2]


def test_suite_generates_valid_messages_and_a_required_field_negative(api: CanonicalApi) -> None:
    manifest = compile_contract_suite(api)
    cases = [case for case in manifest.cases if case.operation_key.endswith("CreateAccount")]
    assert cases
    negatives = [case for case in cases if case.source == CASE_SOURCE_NEGATIVE_MISSING_PARAMETER]
    assert [case.source_detail for case in negatives] == ["email"]
    assert "email" not in negatives[0].rpc.message
    for case in cases:
        if case.source.startswith("negative"):
            continue
        message = case.rpc.message
        assert "@" in message["email"]
        if "handle" in message:
            assert len(message["handle"]) >= 3
        if "seats" in message:
            assert 1 <= message["seats"] <= 500


# ===========================================================================
# Vendored validate.proto
# ===========================================================================


def test_validate_proto_is_supplied_when_imported_and_not_otherwise() -> None:
    source = ProtoFile(
        path=_FIXTURE_PROTO, content=(_FIXTURE_DIR / _FIXTURE_PROTO).read_text(encoding="utf-8")
    )
    assert [proto.path for proto in vendored_proto_imports([source])] == [PROTOVALIDATE_IMPORT]
    supplied = ProtoFile(path=PROTOVALIDATE_IMPORT, content="// caller's own copy")
    assert vendored_proto_imports([source, supplied]) == []
    plain = ProtoFile(path="plain.proto", content='syntax = "proto3";')
    assert vendored_proto_imports([plain]) == []


# ===========================================================================
# Real bundled buf (gated)
# ===========================================================================

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _BUF_AVAILABLE,
    reason="buf tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_BUF_BIN)",
)
class TestRealBuf:
    """Recompile with real ``buf``: the committed descriptor sets are current, and
    ``normalize ∘ emit`` is the identity on the whole fixture."""

    async def _compile_fixture(self):
        return await compile_proto_descriptor_set(
            [
                ProtoFile(
                    path=_FIXTURE_PROTO,
                    content=(_FIXTURE_DIR / _FIXTURE_PROTO).read_text(encoding="utf-8"),
                )
            ]
        )

    async def test_committed_fixture_descriptor_set_is_current(self, api: CanonicalApi) -> None:
        compiled = await self._compile_fixture()
        assert PROTOVALIDATE_IMPORT in {file.name for file in compiled.files if file.is_import}
        assert ProtoNormalizer().normalize(compiled, include_raw=False) == api

    async def test_committed_validate_descriptor_set_is_current(self) -> None:
        """``validate.binpb`` is the compiled twin of the vendored ``validate.proto``."""
        compiled = await compile_proto_descriptor_set(
            [
                ProtoFile(
                    path=PROTOVALIDATE_IMPORT,
                    content=(_VENDORED / "validate.proto").read_text(encoding="utf-8"),
                )
            ]
        )
        fresh = next(file for file in compiled.proto.file if file.name == PROTOVALIDATE_IMPORT)
        fresh.ClearField("source_code_info")
        committed = descriptor_pb2.FileDescriptorSet.FromString(
            (_VENDORED / "validate.binpb").read_bytes()
        )
        assert [file.name for file in committed.file] == [PROTOVALIDATE_IMPORT]
        assert committed.file[0] == fresh

    async def test_emitted_proto_compiles_and_round_trips(self, api: CanonicalApi) -> None:
        emitted = ProtoEmitter().emit(api)
        compiled = await compile_proto_descriptor_set(
            [ProtoFile(path=file.path, content=str(file.content)) for file in emitted.files]
        )
        again = ProtoNormalizer().normalize(compiled, include_raw=False)
        assert again.types == api.types
        # The XPC-4.3 file record names the emitted file, not the fixture's.
        assert {k: v for k, v in again.extras.items() if k != "protobuf_files"} == {
            k: v for k, v in api.extras.items() if k != "protobuf_files"
        }
        assert canonical_fingerprint(again) == canonical_fingerprint(api)
