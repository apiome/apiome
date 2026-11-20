"""JSON Schema dialect handling per OpenAPI document — COA-2.3 (#7046).

Covers reading the declared dialect, keeping it through import, reporting it on the JSON
Schema projection, recording every 3.0 ⇄ 2020-12 schema rewrite, the ``$dynamicRef`` /
``$anchor`` cases, and the acceptance criterion: 3.0 → 3.1 → 3.2 → 3.0 round-trips on the
construct corpus with every change recorded.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.canonical_json_schema import build_type_json_schema
from app.emitter import LossKind, LossTracker, Provenance, ProvenanceTracker
from app.openapi_construct_audit import load_corpus
from app.openapi_downgrade import downgrade_to_openapi_30
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_import_source import OpenApiImportSource
from app.openapi_schema_dialect import (
    OPENAPI_30_SCHEMA_DIALECT,
    OPENAPI_31_DEFAULT_DIALECT,
    OPENAPI_32_DEFAULT_DIALECT,
    changed_objects,
    default_dialect,
    document_dialect,
    is_default_dialect,
    record_schema_rewrites,
    schema_dialect,
)
from app.openapi_source_preservation import OPENAPI_SOURCE_EXTRA, upgrade_schema_30_to_31

CORPUS = Path(__file__).parent / "fixtures" / "openapi_construct_corpus"
DRAFT_07 = "http://json-schema.org/draft-07/schema#"
REWRITE = "schema rewritten"


def _import(document: Dict[str, Any]):
    source = OpenApiImportSource()
    return source.normalize(source.parse(json.dumps(document)), include_raw=False)


def _emit(document: Dict[str, Any], version: str):
    return OpenApiEmitter().emit(_import(document), opts=OpenApiEmitOptions(openapi_version=version))


def _doc_30() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "nick": {"type": "string", "nullable": True},
                        "weight": {"type": "number", "maximum": 100, "exclusiveMaximum": True},
                    },
                },
                "MaybePet": {"allOf": [{"$ref": "#/components/schemas/Pet"}], "nullable": True},
            }
        },
    }


# ---------------------------------------------------------------------------
# Reading the dialect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("3.0.3", OPENAPI_30_SCHEMA_DIALECT),
        ("3.1.0", OPENAPI_31_DEFAULT_DIALECT),
        ("3.1.2", OPENAPI_31_DEFAULT_DIALECT),
        ("3.2.0", OPENAPI_32_DEFAULT_DIALECT),
        ("2.0", None),
        ("4.0.0", None),
    ],
)
def test_default_dialect_per_version(version: str, expected: Any) -> None:
    assert default_dialect(version) == expected


def test_declared_dialect_wins_over_the_default() -> None:
    info = document_dialect({"openapi": "3.1.0", "jsonSchemaDialect": DRAFT_07})
    assert info == {"dialect": DRAFT_07, "declared": True}
    assert not is_default_dialect(DRAFT_07)


def test_undeclared_dialect_is_the_version_default() -> None:
    assert document_dialect({"openapi": "3.2.0"}) == {
        "dialect": OPENAPI_32_DEFAULT_DIALECT,
        "declared": False,
    }
    assert is_default_dialect(OPENAPI_32_DEFAULT_DIALECT)


def test_a_30_document_has_no_declared_dialect() -> None:
    # jsonSchemaDialect is not a 3.0 field, so it does not change a 3.0 document's dialect.
    info = document_dialect({"openapi": "3.0.3", "jsonSchemaDialect": DRAFT_07})
    assert info == {"dialect": OPENAPI_30_SCHEMA_DIALECT, "declared": False}
    assert document_dialect([]) == {"dialect": None, "declared": False}


def test_schema_dollar_schema_overrides_only_from_31() -> None:
    schema = {"$schema": DRAFT_07, "type": "string"}
    assert schema_dialect(schema, OPENAPI_31_DEFAULT_DIALECT, "3.1.0") == DRAFT_07
    assert schema_dialect(schema, OPENAPI_30_SCHEMA_DIALECT, "3.0.3") == OPENAPI_30_SCHEMA_DIALECT
    assert schema_dialect({"type": "string"}, OPENAPI_31_DEFAULT_DIALECT, "3.1.0") == (
        OPENAPI_31_DEFAULT_DIALECT
    )


# ---------------------------------------------------------------------------
# Keeping it through import, reporting it on the projection
# ---------------------------------------------------------------------------


def test_import_keeps_the_declared_dialect() -> None:
    document = {
        "openapi": "3.1.0",
        "jsonSchemaDialect": DRAFT_07,
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {"schemas": {"A": {"type": "string"}}},
    }
    bag = _import(document).extras[OPENAPI_SOURCE_EXTRA]
    assert bag["schemaDialect"] == {"dialect": DRAFT_07, "declared": True}


def test_projection_reports_the_source_dialect() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "A": {"type": "string"},
                "B": {"$schema": DRAFT_07, "type": "integer"},
            }
        },
    }
    api = _import(document)
    projected_a = build_type_json_schema(api, "A")
    assert projected_a.source_dialect == OPENAPI_31_DEFAULT_DIALECT
    assert projected_a.document["$schema"].startswith("https://json-schema.org/draft/2020-12")
    assert build_type_json_schema(api, "B").source_dialect == DRAFT_07


def test_projection_of_a_30_type_names_the_30_subset() -> None:
    assert build_type_json_schema(_import(_doc_30()), "Pet").source_dialect == (
        OPENAPI_30_SCHEMA_DIALECT
    )


# ---------------------------------------------------------------------------
# Recording rewrites
# ---------------------------------------------------------------------------


def test_changed_objects_attributes_keyword_changes_to_their_object() -> None:
    before = {"a": {"b": {"type": "string", "nullable": True}, "c": [1, 2]}, "d": 1}
    after = {"a": {"b": {"type": ["string", "null"]}, "c": [1, 2, 3]}, "d": 1}
    assert changed_objects(before, after) == ["/a/b", "/a"]


def test_record_schema_rewrites_skips_what_a_loss_already_names() -> None:
    before = {"x": {"type": "string", "nullable": True}, "y": {"const": 1}}
    after = {"x": {"type": ["string", "null"]}, "y": {"enum": [1]}}
    losses = LossTracker()
    losses.record(LossKind.INFERRED, "openapi-30-const", "const folded", pointer="#/y")
    tracker = ProvenanceTracker()
    recorded = record_schema_rewrites(before, after, tracker, losses.records(), "rewrite")
    assert recorded == ["/x"]
    assert [(r.pointer, r.provenance) for r in tracker.records()] == [("/x", Provenance.INFERRED)]


def test_upgrade_records_nullable_next_to_ref_as_a_loss() -> None:
    schema = {"$ref": "#/components/schemas/A", "nullable": True}
    losses = LossTracker()
    upgrade_schema_30_to_31(schema, losses, "/components/schemas/B")
    assert schema == {"anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "null"}]}
    [loss] = losses.records()
    assert (loss.subject, loss.kind, loss.pointer) == (
        "openapi-30-nullable-ref",
        LossKind.INFERRED,
        "#/components/schemas/B",
    )


def test_faithful_upgrade_records_no_loss() -> None:
    losses = LossTracker()
    upgrade_schema_30_to_31({"type": "string", "nullable": True}, losses, "/x")
    assert losses.records() == []


def _rewrite_records(result) -> List[str]:
    return [
        record.pointer
        for record in result.provenance
        if record.provenance == Provenance.INFERRED and REWRITE in (record.detail or "")
    ]


def test_30_source_emitted_as_31_records_each_rewritten_schema() -> None:
    result = _emit(_doc_30(), "3.1")
    schemas = result.document["components"]["schemas"]
    assert schemas["Pet"]["properties"]["nick"]["type"] == ["string", "null"]
    assert schemas["Pet"]["properties"]["weight"] == {"type": "number", "exclusiveMaximum": 100}
    assert schemas["MaybePet"] == {
        "anyOf": [{"allOf": [{"$ref": "#/components/schemas/Pet"}]}, {"type": "null"}]
    }
    rewritten = set(_rewrite_records(result))
    assert {
        "/components/schemas/Pet/properties/nick",
        "/components/schemas/Pet/properties/weight",
        "/components/schemas/MaybePet",
    } <= rewritten
    # The faithful upgrade is not a loss.
    assert not [loss for loss in result.losses if loss.subject.startswith("openapi-30")]


def test_30_source_emitted_as_30_is_verbatim_and_records_no_rewrite() -> None:
    result = _emit(_doc_30(), "3.0")
    assert result.document["components"] == _doc_30()["components"]
    assert _rewrite_records(result) == []


def test_downgrade_folds_the_upgraded_nullable_any_of_back() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "A": {"type": "object"},
                "Wrapped": {"anyOf": [{"allOf": [{"$ref": "#/components/schemas/A"}]}, {"type": "null"}]},
                "Bare": {"anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "null"}]},
                "Typed": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
                "Three": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
            }
        },
    }
    losses = LossTracker()
    schemas = downgrade_to_openapi_30(document, losses)["components"]["schemas"]
    assert schemas["Wrapped"] == {"allOf": [{"$ref": "#/components/schemas/A"}], "nullable": True}
    assert schemas["Bare"] == {"allOf": [{"$ref": "#/components/schemas/A"}], "nullable": True}
    assert schemas["Typed"] == {"type": "string", "minLength": 1, "nullable": True}
    # More than one non-null member is not the upgrade's pattern: it is rewritten member by member.
    assert schemas["Three"]["anyOf"][2] == {"nullable": True}
    assert [loss.pointer for loss in losses.records()] == ["#/components/schemas/Three/anyOf/2"]


def test_declared_non_default_dialect_at_30_is_a_named_loss() -> None:
    document = {
        "openapi": "3.1.0",
        "jsonSchemaDialect": DRAFT_07,
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {"schemas": {"A": {"type": "string"}}},
    }
    result = _emit(document, "3.0")
    assert "jsonSchemaDialect" not in result.document
    subjects = {loss.subject: loss for loss in result.losses}
    assert "openapi-3.1-only" in subjects
    assert DRAFT_07 in subjects["openapi-30-schema-dialect"].detail
    # At 3.1 and 3.2 the declared dialect is kept.
    assert _emit(document, "3.1").document["jsonSchemaDialect"] == DRAFT_07
    assert _emit(document, "3.2").document["jsonSchemaDialect"] == DRAFT_07


def test_default_dialect_at_30_records_no_dialect_loss() -> None:
    document = {
        "openapi": "3.1.0",
        "jsonSchemaDialect": OPENAPI_31_DEFAULT_DIALECT,
        "info": {"title": "T", "version": "1"},
        "paths": {},
    }
    subjects = [loss.subject for loss in _emit(document, "3.0").losses]
    assert "openapi-30-schema-dialect" not in subjects


# ---------------------------------------------------------------------------
# $dynamicRef / $anchor
# ---------------------------------------------------------------------------


def _dynamic_doc(version: str) -> Dict[str, Any]:
    return {
        "openapi": version,
        "info": {"title": "Tree", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Tree": {
                    "$id": "https://example.com/tree",
                    "$dynamicAnchor": "node",
                    "type": "object",
                    "properties": {
                        "children": {"type": "array", "items": {"$dynamicRef": "#node"}}
                    },
                },
                "Named": {
                    "$anchor": "named",
                    "type": "object",
                    "properties": {"self": {"$ref": "#named"}},
                },
            }
        },
    }


@pytest.mark.parametrize("source,target", [("3.1.0", "3.1"), ("3.1.0", "3.2"), ("3.2.0", "3.1"), ("3.2.0", "3.2")])
def test_dynamic_ref_and_anchor_survive_31_and_32(source: str, target: str) -> None:
    document = _dynamic_doc(source)
    result = _emit(document, target)
    assert result.document["components"]["schemas"] == document["components"]["schemas"]
    pointers = [loss.pointer or "" for loss in result.losses]
    assert not [p for p in pointers if "Tree" in p or "Named" in p]


def test_dynamic_ref_and_anchor_at_30_are_recorded_losses() -> None:
    result = _emit(_dynamic_doc("3.1.0"), "3.0")
    tree = result.document["components"]["schemas"]["Tree"]
    named = result.document["components"]["schemas"]["Named"]
    assert "$dynamicAnchor" not in tree and "$id" not in tree
    assert "$dynamicRef" not in tree["properties"]["children"]["items"]
    assert "$anchor" not in named
    dropped = {loss.pointer for loss in result.losses if loss.subject == "downgrade-unsupported-keyword"}
    assert {
        "#/components/schemas/Tree/$dynamicAnchor",
        "#/components/schemas/Tree/$id",
        "#/components/schemas/Tree/properties/children/items/$dynamicRef",
        "#/components/schemas/Named/$anchor",
    } <= dropped


def test_dynamic_ref_target_is_kept_as_referenced() -> None:
    # A schema only a $dynamicRef reaches is still written (not dropped as unreferenced).
    document = _dynamic_doc("3.1.0")
    document["components"]["schemas"]["Leaf"] = {"$dynamicAnchor": "leaf", "type": "string"}
    document["components"]["schemas"]["Tree"]["properties"]["leaf"] = {
        "$dynamicRef": "#/components/schemas/Leaf"
    }
    assert "Leaf" in _emit(document, "3.2").document["components"]["schemas"]


# ---------------------------------------------------------------------------
# Acceptance: 3.0 → 3.1 → 3.2 → 3.0 on the corpus, every change recorded
# ---------------------------------------------------------------------------


def _unescape(pointer: str) -> str:
    return pointer.lstrip("#").replace("~1", "/").replace("~0", "~")


def _covered(pointer: str, records: List[str]) -> bool:
    plain = _unescape(pointer)
    return any(
        plain == target or plain.startswith(target + "/") or target.startswith(plain + "/")
        for target in map(_unescape, records)
    )


def _hop(document: Dict[str, Any], version: str) -> Tuple[Dict[str, Any], List[str]]:
    """Emit ``document`` at ``version``; return the output and every recorded change pointer."""
    result = _emit(document, version)
    records = [loss.pointer for loss in result.losses if loss.pointer]
    records += _rewrite_records(result)
    return result.document, records


CORPUS_30 = [(name, doc) for name, doc in load_corpus(CORPUS) if doc["openapi"].startswith("3.0")]


def test_corpus_has_30_documents() -> None:
    assert len(CORPUS_30) >= 3


@pytest.mark.parametrize("name,document", CORPUS_30, ids=[name for name, _ in CORPUS_30])
def test_30_31_32_30_round_trip_records_every_change(name: str, document: Dict[str, Any]) -> None:
    current = copy.deepcopy(document)
    all_records: List[str] = []
    for version in ("3.1", "3.2", "3.0"):
        emitted, records = _hop(current, version)
        all_records += records
        # The version string changes on every hop by design; everything else must be recorded.
        unrecorded = [
            pointer
            for pointer in changed_objects({**current, "openapi": emitted["openapi"]}, emitted)
            if not _covered(pointer, records)
        ]
        assert unrecorded == [], f"{name}: unrecorded changes on the {version} hop"
        current = emitted
    # Back at 3.0 the document is the source again, except where a hop recorded a change it
    # cannot undo (a default ``exclusiveMinimum: false`` the 2020-12 form has no spelling for).
    current["openapi"] = document["openapi"]
    residue = changed_objects(document, current)
    assert [pointer for pointer in residue if not _covered(pointer, all_records)] == []


def test_the_constructs_fixture_round_trips_to_its_source_but_for_a_default_flag() -> None:
    [(_, document)] = [(n, d) for n, d in CORPUS_30 if n == "apiome/oas-3.0-constructs.yaml"]
    current = copy.deepcopy(document)
    for version in ("3.1", "3.2", "3.0"):
        current, _ = _hop(current, version)
    current["openapi"] = document["openapi"]
    assert changed_objects(document, current) == [
        "/paths/~1pets~1{petId}~1photo/put/parameters/0/schema"
    ]
    schema = document["paths"]["/pets/{petId}/photo"]["put"]["parameters"][0]["schema"]
    assert schema["exclusiveMinimum"] is False
    assert {k: v for k, v in schema.items() if k != "exclusiveMinimum"} == (
        current["paths"]["/pets/{petId}/photo"]["put"]["parameters"][0]["schema"]
    )
