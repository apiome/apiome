"""JSON Type Definition (RFC 8927) output mode of the JSON Schema emitter — MFX-21.3 (#4128).

Covers, in order:

* ``mode="jtd"`` on a typed source: one ``<Item>.jtd.json`` with ``definitions`` and a root ``ref``,
  records as ``properties`` / ``optionalProperties``, enums, maps, lists and JTD scalar types — checked
  against RFC 8927 and, when Node and ajv are installed, compiled by ajv's JTD validator with instance
  documents;
* the options JTD takes no part in (``draft``, ``packaging``, ``id_base``) rejected beside it;
* each expressiveness loss recorded with its JSON Pointer, and filed by the fidelity report on its type
  or field (``DROP`` / ``APPROX``) — the report matching the export's losses;
* :func:`app.jsonschema_jtd.jtd_from_bundle` on keywords the canonical projection does not write;
* :func:`app.jsonschema_jtd.check_jtd_schema` rejecting schemas RFC 8927 rejects.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.emitter import LossKind, LossTracker
from app.jsonschema_emitter import JsonSchemaEmitOptions, JsonSchemaEmitter, validate_jsonschema_document
from app.jsonschema_jtd import check_jtd_schema, jtd_from_bundle
from app.lossiness import LossinessKind, LossinessSeverity
from tests.test_jsonschema_emitter import _EXAMPLES, _json_schema_item, _only, _orders_api

_REPO = Path(__file__).resolve().parents[2]


def _emit_jtd(api, **opts):
    return JsonSchemaEmitter().emit(api, opts=JsonSchemaEmitOptions(mode="jtd", **opts))


def _report(api, **options):
    from app.fidelity_engine import compute_lossiness_for_emitter

    return compute_lossiness_for_emitter(api, JsonSchemaEmitter, options={"mode": "jtd", **options})


def _rewrite(schema: Dict[str, Any]):
    """``schema`` as the only ``$defs`` entry of a bundle, rewritten as JTD: (JTD schema, losses)."""
    losses = LossTracker()
    out = jtd_from_bundle({"$ref": "#/$defs/T", "$defs": {"T": schema}}, losses)
    check_jtd_schema(out)
    return out["definitions"]["T"], [(loss.subject, loss.pointer) for loss in losses.records()]


def _ajv(schema: Dict[str, Any], instances: List[Any]) -> List[bool]:
    """Compile ``schema`` with ajv's JTD validator (strict mode) and validate each instance."""
    script = (
        "const A=require('ajv/dist/jtd');const [s,xs]=JSON.parse(process.argv[1]);"
        "const v=new (A.default||A)().compile(s);console.log(JSON.stringify(xs.map(x=>v(x))))"
    )
    run = subprocess.run(
        ["node", "-e", script, json.dumps([schema, instances])],
        cwd=_REPO, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


_HAS_AJV = shutil.which("node") is not None and (_REPO / "node_modules" / "ajv" / "dist" / "jtd.js").exists()


# ===========================================================================
# The JTD document
# ===========================================================================


def test_jtd_mode_writes_one_valid_jtd_document() -> None:
    result = _emit_jtd(_orders_api())
    assert [f.path for f in result.files] == ["Order.jtd.json"]
    document = _only(result)
    check_jtd_schema(document)
    validate_jsonschema_document(result.files[0].content)
    assert "$schema" not in document and "$defs" not in document
    assert document["ref"] == "Order"
    assert list(document["definitions"]) == ["Order", "Line", "Status", "Card", "Cash", "Payment", "Tags"]


def test_records_enums_maps_lists_and_scalars() -> None:
    defs = _only(_emit_jtd(_orders_api()))["definitions"]
    order = defs["Order"]
    assert list(order["properties"]) == ["id", "sku", "quantity", "status", "lines"]
    assert list(order["optionalProperties"]) == ["note", "payment", "tags"]
    assert order["properties"]["quantity"] == {"type": "int32"}
    assert order["properties"]["id"] == {"type": "float64"}
    assert order["properties"]["status"] == {"ref": "Status"}
    assert order["properties"]["lines"] == {"elements": {"ref": "Line"}}
    assert defs["Status"] == {"enum": ["OPEN", "SHIPPED"]}
    assert defs["Tags"] == {"values": {"type": "string"}}
    assert defs["Payment"] == {}
    assert "additionalProperties" not in order


@pytest.mark.skipif(not _HAS_AJV, reason="Node and ajv are not installed")
def test_ajv_compiles_the_document_and_checks_instances() -> None:
    document = _only(_emit_jtd(_orders_api()))
    good = {"id": 1, "sku": "ABC-1", "quantity": 2, "status": "OPEN", "lines": [{"price": 9.5}],
            "tags": {"a": "b"}, "payment": {"number": "4111"}}
    wrong_quantity = {**good, "quantity": 2.5}
    wrong_status = {**good, "status": "LOST"}
    extra = {**good, "unknown": True}
    assert _ajv(document, [good, wrong_quantity, wrong_status, extra]) == [True, False, False, False]


@pytest.mark.parametrize("name", sorted(p.name for p in (_EXAMPLES / "json-schema").glob("*.json")))
def test_every_json_schema_example_exports_to_valid_jtd(name: str) -> None:
    api = _json_schema_item(name)
    result = _emit_jtd(api)
    (emitted,) = result.files
    assert emitted.path.endswith(".jtd.json")
    check_jtd_schema(json.loads(emitted.content))
    assert not any(loss.subject == "rebuilt-from-canonical" for loss in result.losses)


def test_a_model_without_types_is_the_empty_form() -> None:
    from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi

    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="avro", identity=ApiIdentity(name="Empty"),
                       description="Nothing yet")
    document = _only(_emit_jtd(api))
    assert document == {"metadata": {"description": "Nothing yet"}}
    check_jtd_schema(document)


@pytest.mark.parametrize("option", [{"draft": "draft-07"}, {"packaging": "per-type"},
                                    {"id_base": "https://example.com/schemas"}])
def test_jtd_takes_no_draft_packaging_or_id_base(option: Dict[str, str]) -> None:
    with pytest.raises(ValueError, match="mode 'jtd'"):
        JsonSchemaEmitOptions(mode="jtd", **option)


def test_the_default_mode_is_json_schema() -> None:
    assert JsonSchemaEmitOptions().mode == "json-schema"
    assert JsonSchemaEmitter().emit(_orders_api()).files[0].path == "Order.schema.json"


# ===========================================================================
# Expressiveness losses
# ===========================================================================


def test_each_loss_is_recorded_with_its_pointer() -> None:
    losses = {(loss.subject, loss.pointer) for loss in _emit_jtd(_orders_api()).losses}
    assert losses == {
        ("jtd-closed-records", "#"),
        ("jtd-integer-as-float", "#/$defs/Order/properties/id"),
        ("jtd-keyword-dropped", "#/$defs/Order/properties/sku"),
        ("jtd-keyword-dropped", "#/$defs/Order/properties/quantity"),
        ("jtd-annotation-dropped", "#/$defs/Order/properties/status"),
        ("jtd-widened", "#/$defs/Payment"),
    }


def _filed(report) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for item in report.items:
        if (item.target_mapping or "").startswith("jtd-"):
            out.setdefault(item.construct_key, []).append(item.target_mapping)
    return {key: sorted(value) for key, value in out.items()}


def test_the_report_files_each_loss_on_its_construct() -> None:
    report = _report(_orders_api())
    assert _filed(report) == {
        "": ["jtd-closed-records"],
        "shop.Order.id": ["jtd-integer-as-float"],
        "shop.Order.sku": ["jtd-keyword-dropped", "jtd-keyword-dropped"],
        "shop.Order.quantity": ["jtd-keyword-dropped", "jtd-keyword-dropped"],
        "shop.Order.status": ["jtd-annotation-dropped"],
        "shop.Payment": ["jtd-widened"],
    }
    by_mapping = {item.target_mapping: item for item in report.items}
    assert (by_mapping["jtd-keyword-dropped"].kind, by_mapping["jtd-keyword-dropped"].severity) == (
        LossinessKind.DROP, LossinessSeverity.WARN,
    )
    assert (by_mapping["jtd-widened"].kind, by_mapping["jtd-widened"].severity) == (
        LossinessKind.APPROX, LossinessSeverity.WARN,
    )
    assert (by_mapping["jtd-closed-records"].kind, by_mapping["jtd-closed-records"].severity) == (
        LossinessKind.APPROX, LossinessSeverity.INFO,
    )
    assert by_mapping["jtd-annotation-dropped"].severity is LossinessSeverity.INFO


def test_the_report_names_jtd_and_definitions_instead_of_json_schema() -> None:
    report = _report(_orders_api())
    by_key = {item.construct_key: item for item in report.items if item.construct_key in ("", "shop.Order")
              and not (item.target_mapping or "").startswith("jtd-")}
    assert by_key[""].target_mapping == "document → JSON Type Definition"
    assert by_key["shop.Order"].target_mapping == "shop.Order → definitions/Order"
    assert not [i for i in report.items if (i.target_mapping or "").startswith("format ")]


def test_a_json_schema_source_is_reported_as_rewritten_for_jtd() -> None:
    report = _report(_json_schema_item("03-multiple-defs.json"))
    assert any(i.target_mapping == "document → JSON Type Definition" for i in report.items)


def test_the_report_matches_the_export_losses() -> None:
    emitted = {loss.detail for loss in _emit_jtd(_orders_api()).losses if loss.subject.startswith("jtd-")}
    reported = {i.message for i in _report(_orders_api()).items if (i.target_mapping or "").startswith("jtd-")}
    assert emitted == reported and len(reported) == 8


def test_json_schema_mode_reports_no_jtd_loss() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter

    report = compute_lossiness_for_emitter(_orders_api(), JsonSchemaEmitter)
    assert _filed(report) == {}


# ===========================================================================
# Rewrite rules the canonical projection does not exercise
# ===========================================================================


@pytest.mark.parametrize(
    ("schema", "expected", "subjects"),
    [
        ({"type": "string", "format": "date-time"}, {"type": "timestamp"}, []),
        ({"type": "number", "format": "float"}, {"type": "float32"}, []),
        ({"type": "boolean", "description": "Flag"}, {"type": "boolean", "metadata": {"description": "Flag"}}, []),
        ({"type": ["string", "null"]}, {"type": "string", "nullable": True}, []),
        ({"type": "string", "const": "on"}, {"enum": ["on"]}, []),
        ({"type": "string", "enum": ["a", "b", "a", None]}, {"enum": ["a", "b"], "nullable": True}, []),
        ({"type": "string", "format": "uuid"}, {"type": "string"}, ["jtd-keyword-dropped"]),
        ({"type": "string", "contentEncoding": "base64"}, {"type": "string"}, ["jtd-keyword-dropped"]),
        ({"type": "string", "default": "x"}, {"type": "string"}, ["jtd-annotation-dropped"]),
        ({"type": "integer", "enum": [1, 2]}, {"type": "float64"}, ["jtd-enum-as-type"]),
        ({"type": "null"}, {}, ["jtd-widened"]),
        ({"type": ["string", "integer"]}, {}, ["jtd-widened"]),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, {}, ["jtd-widened"]),
        ({"type": "array", "items": {"type": "integer"}, "uniqueItems": True},
         {"elements": {"type": "float64"}}, ["jtd-integer-as-float", "jtd-keyword-dropped"]),
        ({"type": "object", "properties": {}}, {"properties": {}}, []),
        ({"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": True},
         {"optionalProperties": {"a": {"type": "string"}}, "additionalProperties": True}, []),
        ({"type": "object", "properties": {}, "additionalProperties": {"type": "string"}},
         {"properties": {}, "additionalProperties": True}, ["jtd-widened"]),
        ({"type": "object"}, {"values": {}}, []),
    ],
)
def test_rewrite_rules(schema: Dict[str, Any], expected: Dict[str, Any], subjects: List[str]) -> None:
    out, losses = _rewrite(schema)
    assert out == expected
    assert sorted(subject for subject, _ in losses if subject != "jtd-closed-records") == subjects


def test_a_property_named_like_a_keyword_is_kept() -> None:
    out, losses = _rewrite({"type": "object", "properties": {"default": {"type": "string"}},
                            "required": ["default"]})
    assert out == {"properties": {"default": {"type": "string"}}}
    assert [s for s, _ in losses if s != "jtd-closed-records"] == []


# ===========================================================================
# RFC 8927 schema rules
# ===========================================================================


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "JSON object"),
        ({"type": "int64"}, "not a JTD type"),
        ({"ref": "Missing"}, "names no definition"),
        ({"definitions": {"A": {"definitions": {}}}}, "not allowed"),
        ({"type": "string", "enum": ["a"]}, "not allowed"),
        ({"enum": []}, "non-empty array of strings"),
        ({"enum": ["a", "a"]}, "unique"),
        ({"enum": [1]}, "non-empty array of strings"),
        ({"properties": {"a": {}}, "optionalProperties": {"a": {}}}, "both"),
        ({"properties": {}, "additionalProperties": {}}, "boolean"),
        ({"nullable": "yes"}, "boolean"),
        ({"metadata": []}, "object"),
        ({"elements": {"type": "nope"}}, "/elements"),
        ({"discriminator": "kind", "mapping": {"a": {"type": "string"}}}, "properties form"),
        ({"discriminator": "kind", "mapping": {"a": {"properties": {"kind": {"type": "string"}}}}},
         "discriminator"),
        ({"discriminator": "kind", "mapping": {"a": {"properties": {}, "nullable": True}}}, "nullable"),
    ],
)
def test_check_rejects_what_rfc_8927_rejects(document: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_jtd_schema(document)


def test_check_accepts_every_form() -> None:
    check_jtd_schema({
        "definitions": {
            "A": {"properties": {"x": {"type": "uint8"}}, "additionalProperties": True},
            "U": {"discriminator": "kind", "mapping": {"a": {"optionalProperties": {"y": {"enum": ["p"]}}}}},
        },
        "values": {"elements": {"ref": "A", "nullable": True, "metadata": {"description": "d"}}},
    })


def test_validate_rejects_an_invalid_jtd_document() -> None:
    with pytest.raises(ValueError, match="names no definition"):
        validate_jsonschema_document(json.dumps({"ref": "Nope", "metadata": {"description": "x"}}))


def test_losses_are_typed() -> None:
    kinds = {loss.subject: loss.kind for loss in _emit_jtd(_orders_api()).losses}
    assert kinds["jtd-keyword-dropped"] is LossKind.NA
    assert kinds["jtd-widened"] is LossKind.INFERRED
