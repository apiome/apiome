"""OpenAPI spec upgrade assistant — COA-2.6 (#7049).

Covers the plan (every hop, every rule, every change listed), the acceptance criterion — a
downgrade of the upgraded document matches the original on the corpus — and the guards
(unknown target, older target, non-OpenAPI input, determinism, no input mutation).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.openapi_construct_audit import load_corpus
from app.openapi_schema_dialect import changed_objects
from app.openapi_upgrade import (
    TARGET_VERSIONS,
    UpgradeError,
    document_family,
    downgrade_to_family,
    plan_upgrade,
    unlisted_changes,
)
from app.openapi_upgrade_rules import HOP_20_30, HOP_30_31, HOP_31_32, UPGRADE_RULES, ChangeLog
from app.openapi_validator import validate_openapi_document

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "openapi_construct_corpus"
LIBRARY = FIXTURES / "openapi_upgrade" / "swagger-2.0-library.yaml"
PETSTORE_20 = FIXTURES / "openapi_family" / "swagger-2.0-petstore.yaml"
DOCS_PAGE = Path(__file__).resolve().parents[2] / "apiome-docs" / "docs" / "build" / "upgrade-a-spec.mdx"

CORPUS_30 = [(name, doc) for name, doc in load_corpus(CORPUS) if str(doc["openapi"]).startswith("3.0")]
CORPUS_31 = [(name, doc) for name, doc in load_corpus(CORPUS) if str(doc["openapi"]).startswith("3.1")]

# Rewrites that drop a keyword with no effect: the 2020-12 form has no spelling for them, so a
# downgrade cannot bring them back. Each one is listed in the plan (exclusive-flag-removed,
# nullable-false-removed); the round trip compares documents without them.
_NO_OP_KEYWORDS = {"exclusiveMinimum": False, "exclusiveMaximum": False, "nullable": False}


def _load(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rules(plan) -> List[str]:
    return [change.rule for change in plan.changes]


def _doc_30() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "nullable": True, "example": "Rex"},
                        "owner": {"$ref": "#/components/schemas/Owner", "nullable": True},
                        "tag": {"nullable": True, "description": "no type"},
                        "kind": {"type": "string", "enum": ["cat", "dog"], "nullable": True},
                        "age": {"type": "integer", "minimum": 0, "exclusiveMinimum": True},
                        "weight": {"type": "number", "maximum": 50, "exclusiveMaximum": False},
                        "legs": {"type": "integer", "nullable": False},
                    },
                },
                "Owner": {"type": "object"},
            }
        },
    }


# ---------------------------------------------------------------------------------------
# Rule catalog
# ---------------------------------------------------------------------------------------


def test_every_rule_names_a_known_hop() -> None:
    assert {rule.hop for rule in UPGRADE_RULES.values()} <= {"*", HOP_20_30, HOP_30_31, HOP_31_32}


def test_change_log_refuses_an_unknown_rule() -> None:
    with pytest.raises(KeyError):
        ChangeLog(HOP_30_31).record("made-up", "/x", "nope")


def test_docs_page_lists_every_rule() -> None:
    text = DOCS_PAGE.read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|", text, flags=re.MULTILINE))
    assert listed == set(UPGRADE_RULES), "build/upgrade-a-spec.mdx must list exactly the UPGRADE_RULES ids"


# ---------------------------------------------------------------------------------------
# Version families and guards
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "document,expected",
    [
        ({"swagger": "2.0"}, ("2.0", "2.0")),
        ({"openapi": "3.0.3"}, ("3.0.3", "3.0")),
        ({"openapi": "3.1.0"}, ("3.1.0", "3.1")),
        ({"openapi": "3.2.0"}, ("3.2.0", "3.2")),
    ],
)
def test_document_family(document, expected) -> None:
    assert document_family(document) == expected


@pytest.mark.parametrize(
    "document,code",
    [
        ({"asyncapi": "2.6.0"}, "not-openapi"),
        ([], "not-openapi"),
        ({"swagger": "1.2"}, "unsupported-version"),
        ({"openapi": "4.0.0"}, "unsupported-version"),
    ],
)
def test_document_family_refuses(document, code) -> None:
    with pytest.raises(UpgradeError) as caught:
        document_family(document)
    assert caught.value.code == code


def test_unknown_target_is_refused() -> None:
    with pytest.raises(UpgradeError) as caught:
        plan_upgrade(_doc_30(), "4.0")
    assert caught.value.code == "unknown-target"


def test_older_target_is_refused() -> None:
    with pytest.raises(UpgradeError) as caught:
        plan_upgrade({"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}, "3.0")
    assert caught.value.code == "target-older"


def test_same_family_is_already_current() -> None:
    document = {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}
    plan = plan_upgrade(document, "3.1")
    assert plan.already_current
    assert plan.changes == []
    assert plan.document == document
    assert plan.target_version == "3.1.0"


def test_plan_is_deterministic_and_does_not_mutate_input() -> None:
    document = _load(LIBRARY)
    original = copy.deepcopy(document)
    first = plan_upgrade(document, "3.2")
    second = plan_upgrade(document, "3.2")
    assert document == original
    assert first.plan_digest == second.plan_digest
    assert first.as_dict() == second.as_dict()


def test_plan_digest_changes_with_target_and_source() -> None:
    document = _doc_30()
    assert plan_upgrade(document, "3.1").plan_digest != plan_upgrade(document, "3.2").plan_digest
    edited = _doc_30()
    edited["info"]["title"] = "Other"
    assert plan_upgrade(document, "3.1").plan_digest != plan_upgrade(edited, "3.1").plan_digest


# ---------------------------------------------------------------------------------------
# 3.0 → 3.1 → 3.2
# ---------------------------------------------------------------------------------------


def test_30_to_31_rewrites_and_lists_each_schema_rule() -> None:
    plan = plan_upgrade(_doc_30(), "3.1")
    props = plan.document["components"]["schemas"]["Pet"]["properties"]
    assert plan.document["openapi"] == TARGET_VERSIONS["3.1"]
    assert props["name"] == {"type": ["string", "null"], "examples": ["Rex"]}
    assert props["owner"] == {"anyOf": [{"$ref": "#/components/schemas/Owner"}, {"type": "null"}]}
    assert props["tag"] == {"anyOf": [{"description": "no type"}, {"type": "null"}]}
    assert props["kind"] == {"type": ["string", "null"], "enum": ["cat", "dog", None]}
    assert props["age"] == {"type": "integer", "exclusiveMinimum": 0}
    assert props["weight"] == {"type": "number", "maximum": 50}
    assert props["legs"] == {"type": "integer"}
    by_pointer = {(c.rule, c.pointer) for c in plan.changes}
    base = "/components/schemas/Pet/properties/"
    assert {
        ("openapi-version", "/openapi"),
        ("example-to-examples", base + "name"),
        ("nullable-to-type-array", base + "name"),
        ("nullable-ref", base + "owner"),
        ("nullable-to-any-of", base + "tag"),
        ("nullable-to-type-array", base + "kind"),
        ("exclusive-bound-numeric", base + "age"),
        ("exclusive-flag-removed", base + "weight"),
        ("nullable-false-removed", base + "legs"),
    } == by_pointer
    assert [c.rule for c in plan.changes if c.review] == ["nullable-ref"]
    assert unlisted_changes(plan) == []
    assert _schema_errors(plan.document) == []


def test_31_to_32_changes_only_the_version() -> None:
    document = {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}
    plan = plan_upgrade(document, "3.2")
    assert plan.hops == [HOP_31_32]
    assert _rules(plan) == ["openapi-version"]
    assert plan.document == {**document, "openapi": "3.2.0"}


def test_plan_summary_counts_rules() -> None:
    plan = plan_upgrade(_doc_30(), "3.2")
    counts = {row["rule"]: row["count"] for row in plan.rule_counts()}
    assert counts["openapi-version"] == 2
    assert counts["nullable-to-type-array"] == 2
    payload = plan.as_dict(include_document=False)
    assert "document" not in payload
    assert payload["change_count"] == len(plan.changes)
    assert payload["review_count"] == 1
    assert payload["changes"][0]["title"] == UPGRADE_RULES[payload["changes"][0]["rule"]].title


@pytest.mark.parametrize("target", ["3.1", "3.2"])
@pytest.mark.parametrize("name,document", CORPUS_30, ids=[name for name, _ in CORPUS_30])
def test_corpus_30_plan_lists_every_change(name: str, document: Dict[str, Any], target: str) -> None:
    plan = plan_upgrade(document, target)
    assert unlisted_changes(plan) == [], name
    assert _schema_errors(plan.document) == [], name


@pytest.mark.parametrize("name,document", CORPUS_31, ids=[name for name, _ in CORPUS_31])
def test_corpus_31_plan_lists_every_change(name: str, document: Dict[str, Any]) -> None:
    plan = plan_upgrade(document, "3.2")
    assert unlisted_changes(plan) == [], name
    assert _rules(plan) == ["openapi-version"]


# ---------------------------------------------------------------------------------------
# Acceptance: a downgrade of the result matches the original on the corpus
# ---------------------------------------------------------------------------------------


def _without_no_ops(node: Any) -> Any:
    """``node`` with every no-op keyword the upgrade removes (and lists) taken out."""
    if isinstance(node, dict):
        return {
            key: _without_no_ops(value)
            for key, value in node.items()
            if not (key in _NO_OP_KEYWORDS and value is _NO_OP_KEYWORDS[key])
        }
    if isinstance(node, list):
        return [_without_no_ops(item) for item in node]
    return node


@pytest.mark.parametrize("target", ["3.1", "3.2"])
@pytest.mark.parametrize("name,document", CORPUS_30, ids=[name for name, _ in CORPUS_30])
def test_corpus_30_upgrade_then_downgrade_matches_the_original(
    name: str, document: Dict[str, Any], target: str
) -> None:
    plan = plan_upgrade(document, target)
    back, _ = downgrade_to_family(plan.document, "3.0")
    back["openapi"] = document["openapi"]
    assert changed_objects(_without_no_ops(document), back) == [], name


def test_the_no_op_residue_is_listed_in_the_plan() -> None:
    [(_, document)] = [(n, d) for n, d in CORPUS_30 if n == "apiome/oas-3.0-constructs.yaml"]
    plan = plan_upgrade(document, "3.2")
    back, _ = downgrade_to_family(plan.document, "3.0")
    back["openapi"] = document["openapi"]
    residue = changed_objects(document, back)
    assert residue
    listed = {c.pointer for c in plan.changes if c.rule == "exclusive-flag-removed"}
    assert set(residue) <= listed


@pytest.mark.parametrize("name,document", CORPUS_31, ids=[name for name, _ in CORPUS_31])
def test_corpus_31_upgrade_then_downgrade_matches_the_original(name: str, document: Dict[str, Any]) -> None:
    plan = plan_upgrade(document, "3.2")
    back, _ = downgrade_to_family(plan.document, "3.1")
    back["openapi"] = document["openapi"]
    assert back == document, name


def _media_per_operation(document: Dict[str, Any]) -> Dict[str, Any]:
    """A Swagger document with document-level consumes / produces pushed onto each operation.

    ``consumes`` only means something for an operation with a body or form parameters, so it is
    pushed onto those alone (the downgrade writes it nowhere else).
    """
    out = copy.deepcopy(document)
    defaults = {key: out.pop(key) for key in ("consumes", "produces") if key in out}
    for item in (out.get("paths") or {}).values():
        for method, operation in item.items():
            if not isinstance(operation, dict) or method == "parameters":
                continue
            has_body = any(
                isinstance(p, dict) and p.get("in") in ("body", "formData") for p in operation.get("parameters") or []
            )
            for key, value in defaults.items():
                if key == "produces" or has_body:
                    operation.setdefault(key, value)
            if not has_body:
                operation.pop("consumes", None)
    return out


# The vendored 3.1 / 3.2 meta-schemas reject ``x-`` keys in a Callback Object, which the OAI tests
# accept (the open COA-2.1 follow-up). Those errors are the meta-schema's, not the upgrade's.
def _schema_errors(document: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        error
        for error in validate_openapi_document(document)
        if not ("/callbacks/" in error.get("path", "") and "/x-" in error.get("path", ""))
    ]


@pytest.mark.parametrize("target", ["3.0", "3.1", "3.2"])
def test_swagger_20_upgrade_then_downgrade_matches_the_original(target: str) -> None:
    document = _load(PETSTORE_20)
    plan = plan_upgrade(document, target)
    upgraded = plan.document
    if target == "3.0":
        upgraded = plan_upgrade({**upgraded, "openapi": "3.0.4"}, "3.1").document
    back, _ = downgrade_to_family(upgraded, "2.0")
    assert changed_objects(_media_per_operation(document), _media_per_operation(back)) == []


# ---------------------------------------------------------------------------------------
# Swagger 2.0 → 3.0
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["3.0", "3.1", "3.2"])
def test_swagger_library_upgrades_to_a_valid_document(target: str) -> None:
    plan = plan_upgrade(_load(LIBRARY), target)
    assert plan.document["openapi"] == TARGET_VERSIONS[target]
    assert _schema_errors(plan.document) == []
    assert unlisted_changes(plan) == []


def test_swagger_library_hits_every_20_rule() -> None:
    plan = plan_upgrade(_load(LIBRARY), "3.0")
    rules_20 = {rule for rule, spec in UPGRADE_RULES.items() if spec.hop == HOP_20_30}
    assert rules_20 <= set(_rules(plan))
    assert plan.hops == [HOP_20_30]


def test_swagger_library_structure() -> None:
    doc = plan_upgrade(_load(LIBRARY), "3.0").document
    assert doc["x-owner"] == "platform-team"
    assert doc["info"]["x-audience"] == "internal"
    assert doc["servers"] == [{"url": "https://library.example.com/api"}, {"url": "http://library.example.com/api"}]
    for gone in (
        "swagger",
        "host",
        "basePath",
        "schemes",
        "consumes",
        "produces",
        "definitions",
        "securityDefinitions",
    ):
        assert gone not in doc
    components = doc["components"]
    assert set(components["schemas"]) == {"Book", "Ebook", "Error"}
    assert set(components["parameters"]) == {"PageSize"}
    assert components["parameters"]["PageSize"]["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 20,
    }
    assert components["securitySchemes"]["basicAuth"] == {"type": "http", "scheme": "basic"}
    assert "authorizationCode" in components["securitySchemes"]["oauth"]["flows"]
    book = components["schemas"]["Book"]
    assert book["discriminator"] == {"propertyName": "kind"}
    assert book["properties"]["title"] == {"type": "string", "nullable": True}
    assert components["schemas"]["Ebook"]["allOf"][0] == {"$ref": "#/components/schemas/Book"}
    assert components["responses"]["NotFound"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Error"
    }

    books = doc["paths"]["/books"]
    listing = books["get"]
    assert listing["x-rate-limit"] == 100
    assert listing["parameters"][0] == {"$ref": "#/components/parameters/PageSize"}
    assert listing["parameters"][1]["style"] == "form" and listing["parameters"][1]["explode"] is False
    assert listing["parameters"][2]["style"] == "form" and listing["parameters"][2]["explode"] is True
    ok = listing["responses"]["200"]
    assert ok["headers"]["X-Total"] == {"description": "Total count.", "schema": {"type": "integer"}}
    assert ok["content"]["application/json"]["example"] == [{"id": "b1", "title": "Dune"}]
    assert ok["content"]["application/json"]["schema"]["items"] == {"$ref": "#/components/schemas/Book"}

    create = books["post"]
    assert create["requestBody"] == {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Book"}}},
        "required": True,
    }
    assert "parameters" not in create

    item = doc["paths"]["/books/{id}"]
    assert item["parameters"][0]["schema"] == {"type": "string"}
    assert item["get"]["servers"] == [{"url": "https://library.example.com/api"}]
    assert item["get"]["responses"]["404"] == {"$ref": "#/components/responses/NotFound"}

    cover = doc["paths"]["/books/{id}/cover"]["put"]
    form = cover["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert form["properties"]["file"] == {"type": "string", "format": "binary"}
    assert form["required"] == ["file"]
    assert [p["name"] for p in cover["parameters"]] == ["id"]


def test_swagger_without_schemes_assumes_https_and_flags_it() -> None:
    document = {"swagger": "2.0", "info": {"title": "x", "version": "1"}, "host": "a.example", "paths": {}}
    plan = plan_upgrade(document, "3.0")
    assert plan.document["servers"] == [{"url": "https://a.example"}]
    [server] = [c for c in plan.changes if c.rule == "servers-from-host"]
    assert server.review


def test_swagger_base_path_only_becomes_a_relative_server() -> None:
    document = {"swagger": "2.0", "info": {"title": "x", "version": "1"}, "basePath": "v2", "paths": {}}
    assert plan_upgrade(document, "3.0").document["servers"] == [{"url": "/v2"}]


@pytest.mark.parametrize(
    "location,fmt,expected,review",
    [
        ("query", "tsv", {"x-collectionFormat": "tsv"}, True),
        ("query", "pipes", {"style": "pipeDelimited", "explode": False}, False),
        ("query", "ssv", {"style": "spaceDelimited", "explode": False}, False),
        ("path", "csv", {"style": "simple", "explode": False}, False),
        ("header", "pipes", {"x-collectionFormat": "pipes"}, True),
    ],
)
def test_collection_formats(location: str, fmt: str, expected: Dict[str, Any], review: bool) -> None:
    param = {"name": "p", "in": location, "type": "array", "items": {"type": "string"}, "collectionFormat": fmt}
    if location == "path":
        param["required"] = True
    document = {
        "swagger": "2.0",
        "info": {"title": "x", "version": "1"},
        "paths": {"/a/{p}": {"get": {"parameters": [param], "responses": {"200": {"description": "ok"}}}}},
    }
    plan = plan_upgrade(document, "3.0")
    converted = plan.document["paths"]["/a/{p}"]["get"]["parameters"][0]
    for key, value in expected.items():
        assert converted[key] == value
    assert "collectionFormat" not in converted
    [change] = [c for c in plan.changes if c.rule == "collection-format-to-style"]
    assert change.review is review


def test_reusable_form_data_parameter_is_inlined() -> None:
    document = {
        "swagger": "2.0",
        "info": {"title": "x", "version": "1"},
        "parameters": {"Note": {"name": "note", "in": "formData", "type": "string", "required": True}},
        "paths": {
            "/n": {"post": {"parameters": [{"$ref": "#/parameters/Note"}], "responses": {"200": {"description": "ok"}}}}
        },
    }
    plan = plan_upgrade(document, "3.0")
    body = plan.document["paths"]["/n"]["post"]["requestBody"]
    assert body["content"]["application/x-www-form-urlencoded"]["schema"]["required"] == ["note"]
    assert "components" not in plan.document
    assert "body-parameter-inlined" in _rules(plan)
