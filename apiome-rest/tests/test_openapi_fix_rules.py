"""The first fixable OpenAPI rules and their fix fixtures — GVM-3.1 (#5869).

Every fixable rule has a one-defect fixture under ``tests/fixtures/scanner_evaluation/fix/<rule id>/`` (GVM-3.5 gates them in CI too)
holding the document, the expected plan and the expected post-fix document. The gates run over
each fixture:

1. the fixture triggers exactly its rule, and the plan is the expected one;
2. after the fix the rule is clean;
3. no other finding changes (default lint and on-demand rules alike);
4. planning and applying twice is byte-stable;
5. a rule flagged fixable without a fixture fails :func:`test_every_fixable_rule_has_a_fixture`.

The rest of the file covers what a one-defect fixture cannot: the cases where a fix must
decline, and the guarantee that the default lint does not change.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.lint_fix import FIX_SCOPE_DOCUMENT, FIX_SCOPE_FINDING, FixOptions, apply_fix_ops
from app.lint_rule_registry import builtin_rule_descriptors
from app.openapi_fix_rules import (
    lint_openapi_fixable,
    openapi_fix_rule,
    openapi_fix_rules,
    plan_openapi_fix,
    render_operation_id,
)
from app.schema_lint import OPENAPI_RULES, LintFinding, lint_openapi_spec

FIXTURES = Path(__file__).parent / "fixtures" / "scanner_evaluation" / "fix"
OPENAPI_FAMILY = Path(__file__).parent / "fixtures" / "openapi_family"


def _fixture_ids() -> List[str]:
    return sorted(path.parent.name for path in FIXTURES.glob("*/fixture.json"))


def _load(rule_id: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / rule_id / "fixture.json").read_text(encoding="utf-8"))


def _options(fixture: Dict[str, Any]) -> FixOptions:
    raw = fixture.get("options") or {}
    return FixOptions(
        operation_id_template=raw.get("operationIdTemplate", FixOptions().operation_id_template),
        opt_in=frozenset(raw.get("optIn", [])),
    )


def _all_findings(document: Dict[str, Any]) -> Set[Tuple[str, str, str]]:
    """Every finding of the default lint and the on-demand rules, as ``(rule, path, message)``."""
    findings = list(lint_openapi_spec(document).findings) + lint_openapi_fixable(document)
    return {(f.rule, f.path, f.message) for f in findings}


def _one(document: Dict[str, Any], rule_id: str) -> LintFinding:
    findings = [f for f in lint_openapi_fixable(document) if f.rule == rule_id]
    assert len(findings) == 1, findings
    return findings[0]


def _doc(**overrides: Any) -> Dict[str, Any]:
    """A clean OpenAPI 3.1 document: no on-demand rule fires on it."""
    document: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Pet API", "version": "1.0.0"},
        "tags": [{"name": "pets"}],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "tags": ["pets"],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
                        }
                    },
                }
            }
        },
        "components": {"schemas": {"Pet": {"type": "object", "properties": {"name": {"type": "string"}}}}},
    }
    document.update(overrides)
    return document


def _plan(document: Dict[str, Any], rule_id: str, *opt_in: str) -> List[Dict[str, Any]]:
    ops = plan_openapi_fix(document, _one(document, rule_id), FixOptions(opt_in=frozenset(opt_in)))
    return [op.as_dict() for op in ops]


# ===========================================================================
# The fixture gates
# ===========================================================================


def test_every_fixable_rule_has_a_fixture():
    """Gate 5: a rule flagged fixable without a fixture fails the build."""
    fixable = {d.rule_id for d in builtin_rule_descriptors() if d.fixable}
    assert fixable == set(_fixture_ids()), (
        f"fixable without a fixture: {sorted(fixable - set(_fixture_ids()))}; "
        f"fixture without a fixable rule: {sorted(set(_fixture_ids()) - fixable)}"
    )


@pytest.mark.parametrize("rule_id", _fixture_ids())
def test_fixture_triggers_exactly_its_rule_and_the_expected_plan(rule_id: str):
    fixture = _load(rule_id)
    assert fixture["rule"] == rule_id
    findings = lint_openapi_fixable(fixture["before"])
    assert [f.rule for f in findings] == [rule_id], "a fix fixture carries one defect"
    assert {"path": findings[0].path, "message": findings[0].message} == fixture["finding"]
    ops = plan_openapi_fix(fixture["before"], findings[0], _options(fixture))
    assert [op.as_dict() for op in ops] == fixture["plan"]


@pytest.mark.parametrize("rule_id", _fixture_ids())
def test_after_the_fix_the_rule_is_clean_and_nothing_else_changed(rule_id: str):
    fixture = _load(rule_id)
    before = fixture["before"]
    finding = _one(before, rule_id)
    after = apply_fix_ops(before, plan_openapi_fix(before, finding, _options(fixture)))
    # Key order is part of the expected document: a fix must not reshuffle what it leaves alone.
    assert json.dumps(after) == json.dumps(fixture["after"])

    assert all(f.rule != rule_id for f in lint_openapi_fixable(after))
    others_before = {f for f in _all_findings(before) if f[0] != rule_id}
    others_after = {f for f in _all_findings(after) if f[0] != rule_id}
    assert others_after == others_before


@pytest.mark.parametrize("rule_id", _fixture_ids())
def test_planning_and_applying_twice_is_byte_stable(rule_id: str):
    fixture = _load(rule_id)
    options = _options(fixture)

    def fix_all(document: Dict[str, Any]) -> Dict[str, Any]:
        for finding in lint_openapi_fixable(document):
            if finding.rule == rule_id:
                document = apply_fix_ops(document, plan_openapi_fix(document, finding, options))
        return document

    once = fix_all(fixture["before"])
    twice = fix_all(once)
    assert json.dumps(twice) == json.dumps(once) == json.dumps(fixture["after"])


@pytest.mark.parametrize("rule_id", _fixture_ids())
def test_planning_does_not_mutate_the_fixture(rule_id: str):
    fixture = _load(rule_id)
    before = copy.deepcopy(fixture["before"])
    plan_openapi_fix(before, _one(before, rule_id), _options(fixture))
    assert before == fixture["before"]


# ===========================================================================
# The rule set
# ===========================================================================


def test_at_least_twelve_rules_are_fixable():
    """Acceptance: ``GET /v1/lint/rules`` lists at least twelve ``fixable: true`` rules."""
    assert len([d for d in builtin_rule_descriptors() if d.fixable]) >= 12


def test_only_the_schema_rename_leaves_the_finding_subtree():
    scopes = {rule.rule_id: rule.fix_scope for rule in openapi_fix_rules()}
    assert scopes.pop("naming.schema-pascal-case") == FIX_SCOPE_DOCUMENT
    assert set(scopes.values()) == {FIX_SCOPE_FINDING}


def test_only_the_schema_rename_is_wire_visible_and_it_is_never_applied_by_default():
    wire_visible = [rule.rule_id for rule in openapi_fix_rules() if rule.wire_visible]
    assert wire_visible == ["naming.schema-pascal-case"]
    off_by_default = {rule.rule_id for rule in openapi_fix_rules() if not rule.fix_default}
    assert off_by_default == {"naming.schema-pascal-case", "structure.operation-missing-tags"}


def test_fix_classes_match_the_issue():
    classes = {rule.rule_id: rule.fix_class for rule in openapi_fix_rules()}
    assert classes == {
        "structure.nullable-keyword": "structural",
        "structure.schema-example-keyword": "structural",
        "structure.boolean-exclusive-bound": "structural",
        "structure.server-url-trailing-slash": "structural",
        "structure.server-url-scheme-case": "structural",
        "structure.unused-component": "removal",
        "structure.empty-required": "removal",
        "structure.duplicate-tag": "removal",
        "structure.operation-missing-operation-id": "fill-in",
        "structure.operation-missing-tags": "fill-in",
        "naming.operation-id-camel-case": "rename",
        "naming.tag-case-mismatch": "rename",
        "naming.schema-pascal-case": "rename",
    }


def test_no_fixable_rule_is_an_error_rule():
    # An error rule would need a CLX-4.3 blocking entry; these are hygiene rules.
    assert {rule.severity for rule in openapi_fix_rules()} <= {"warning", "info"}


def test_the_pascal_case_fix_reports_the_default_lints_own_finding():
    document = _doc()
    document["components"]["schemas"]["pet_record"] = document["components"]["schemas"].pop("Pet")
    document["paths"]["/pets"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] = "#/components/schemas/pet_record"
    default = [f for f in lint_openapi_spec(document).findings if f.rule == "naming.schema-pascal-case"]
    assert [_one(document, "naming.schema-pascal-case")] == default
    rule = openapi_fix_rule("naming.schema-pascal-case")
    assert (rule.category, rule.severity, rule.description) == OPENAPI_RULES["naming.schema-pascal-case"]


# ===========================================================================
# No behaviour change until a fix is requested
# ===========================================================================


def test_the_default_lint_never_emits_an_on_demand_rule():
    """Acceptance: the on-demand rules add nothing to a lint report, score or fingerprint."""
    on_demand = {rule.rule_id for rule in openapi_fix_rules()} - set(OPENAPI_RULES)
    assert len(on_demand) == 12
    for rule_id in _fixture_ids():
        result = lint_openapi_spec(_load(rule_id)["before"])
        assert not {f.rule for f in result.findings} & on_demand


def test_the_on_demand_rules_self_gate_on_anything_but_openapi_3():
    assert lint_openapi_fixable({"swagger": "2.0", "paths": {"/p": {"get": {}}}}) == []
    assert lint_openapi_fixable({"asyncapi": "3.0.0"}) == []
    assert lint_openapi_fixable({}) == []
    assert lint_openapi_fixable([]) == []  # type: ignore[arg-type]


def test_the_rules_run_over_a_canonical_artifacts_retained_document():
    fixture = _load("structure.empty-required")
    api = CanonicalApi(
        identity=ApiIdentity(name="pets"), format="openapi", paradigm=ApiParadigm.REST, raw=fixture["before"]
    )
    rule = openapi_fix_rule("structure.empty-required")
    assert [(f.path, f.message) for f in rule.run(api)] == [
        (fixture["finding"]["path"], fixture["finding"]["message"])
    ]
    bare = CanonicalApi(identity=ApiIdentity(name="pets"), format="openapi", paradigm=ApiParadigm.REST)
    assert rule.run(bare) == []


def test_a_finding_of_a_rule_without_a_fix_plans_nothing():
    finding = LintFinding(
        path="info", category="documentation", rule="documentation.info-missing-description",
        severity="info", message="API info block is missing a description.",
    )
    assert plan_openapi_fix(_doc(), finding) == ()


# ===========================================================================
# 3.0 → 3.1 syntax moves
# ===========================================================================


def test_syntax_moves_fire_only_from_openapi_3_1():
    schema = {"type": "integer", "nullable": True, "example": 1, "minimum": 0, "exclusiveMinimum": True}
    for marker, expected in (("3.0.3", set()), ("3.1.0", {"n", "e", "b"}), ("3.2.0", {"n", "e", "b"})):
        document = _doc(openapi=marker)
        document["components"]["schemas"]["Pet"]["properties"]["age"] = dict(schema)
        fired = {f.rule for f in lint_openapi_fixable(document)}
        assert ("structure.nullable-keyword" in fired) == ("n" in expected)
        assert ("structure.schema-example-keyword" in fired) == ("e" in expected)
        assert ("structure.boolean-exclusive-bound" in fired) == ("b" in expected)


def test_a_property_named_like_a_keyword_is_data_not_a_keyword():
    document = _doc()
    document["components"]["schemas"]["Pet"]["properties"].update(
        {"nullable": {"type": "boolean"}, "example": {"type": "string"}, "required": {"type": "array", "items": {}}}
    )
    assert lint_openapi_fixable(document) == []


def _with_name_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    document = _doc()
    document["components"]["schemas"]["Pet"]["properties"]["name"] = schema
    return document


NAME = "/components/schemas/Pet/properties/name"


@pytest.mark.parametrize(
    "schema, plan",
    [
        (
            {"type": ["string", "integer"], "nullable": True},
            [
                {"op": "replace", "path": f"{NAME}/type", "value": ["string", "integer", "null"]},
                {"op": "remove", "path": f"{NAME}/nullable"},
            ],
        ),
        ({"type": ["string", "null"], "nullable": True}, [{"op": "remove", "path": f"{NAME}/nullable"}]),
        (
            {"type": "string", "enum": ["a", "b"], "nullable": True},
            [
                {"op": "replace", "path": f"{NAME}/type", "value": ["string", "null"]},
                {"op": "replace", "path": f"{NAME}/enum", "value": ["a", "b", None]},
                {"op": "remove", "path": f"{NAME}/nullable"},
            ],
        ),
        ({"type": "string", "nullable": False}, [{"op": "remove", "path": f"{NAME}/nullable"}]),
        # No type to extend, a $ref beside it, or a value that is not a boolean: left to a person.
        ({"nullable": True}, []),
        ({"$ref": "#/components/schemas/Pet", "nullable": True}, []),
        ({"type": "string", "nullable": "yes"}, []),
    ],
)
def test_nullable_fix(schema: Dict[str, Any], plan: List[Dict[str, Any]]):
    assert _plan(_with_name_schema(schema), "structure.nullable-keyword") == plan


def test_example_is_not_moved_over_existing_examples():
    document = _with_name_schema({"type": "string", "example": "a", "examples": ["b"]})
    assert _plan(document, "structure.schema-example-keyword") == []


def test_a_media_type_example_is_not_a_schema_example():
    document = _doc()
    document["paths"]["/pets"]["get"]["responses"]["200"]["content"]["application/json"]["example"] = {"name": "Rex"}
    assert lint_openapi_fixable(document) == []


@pytest.mark.parametrize(
    "schema, plan",
    [
        (
            {"type": "number", "maximum": 9.5, "exclusiveMaximum": True},
            [
                {"op": "replace", "path": f"{NAME}/exclusiveMaximum", "value": 9.5},
                {"op": "remove", "path": f"{NAME}/maximum"},
            ],
        ),
        (
            {"type": "number", "minimum": 1, "exclusiveMinimum": False},
            [{"op": "remove", "path": f"{NAME}/exclusiveMinimum"}],
        ),
        ({"type": "number", "exclusiveMinimum": True}, [{"op": "remove", "path": f"{NAME}/exclusiveMinimum"}]),
        (
            {"type": "number", "minimum": 0, "exclusiveMinimum": True, "maximum": 5, "exclusiveMaximum": False},
            [
                {"op": "replace", "path": f"{NAME}/exclusiveMinimum", "value": 0},
                {"op": "remove", "path": f"{NAME}/minimum"},
                {"op": "remove", "path": f"{NAME}/exclusiveMaximum"},
            ],
        ),
    ],
)
def test_boolean_exclusive_bound_fix(schema: Dict[str, Any], plan: List[Dict[str, Any]]):
    assert _plan(_with_name_schema(schema), "structure.boolean-exclusive-bound") == plan


def test_a_numeric_exclusive_bound_is_already_3_1():
    assert lint_openapi_fixable(_with_name_schema({"type": "number", "exclusiveMinimum": 0})) == []


# ===========================================================================
# Server URLs
# ===========================================================================


@pytest.mark.parametrize("url", ["/", "https://api.example.com", "{scheme}://api.example.com", "/v1", ""])
def test_server_urls_that_are_left_alone(url: str):
    assert lint_openapi_fixable(_doc(servers=[{"url": url}])) == []


def test_operation_level_servers_are_checked_too():
    document = _doc()
    document["paths"]["/pets"]["get"]["servers"] = [{"url": "Https://files.example.com//"}]
    findings = lint_openapi_fixable(document)
    assert {f.rule for f in findings} == {
        "structure.server-url-trailing-slash",
        "structure.server-url-scheme-case",
    }
    assert {f.path for f in findings} == {"paths./pets.get.servers.0"}
    assert _plan(document, "structure.server-url-trailing-slash") == [
        {"op": "replace", "path": "/paths/~1pets/get/servers/0/url", "value": "Https://files.example.com"}
    ]
    assert _plan(document, "structure.server-url-scheme-case") == [
        {"op": "replace", "path": "/paths/~1pets/get/servers/0/url", "value": "https://files.example.com//"}
    ]


# ===========================================================================
# Unused components
# ===========================================================================


def test_a_component_used_only_by_an_unused_component_is_unused_too():
    document = _doc()
    document["components"]["schemas"].update(
        {"Orphan": {"properties": {"leaf": {"$ref": "#/components/schemas/Leaf"}}}, "Leaf": {"type": "string"}}
    )
    unused = {f.path for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"}
    assert unused == {"components.schemas.Orphan", "components.schemas.Leaf"}


def test_transitive_and_self_references_keep_a_component():
    document = _doc()
    schemas = document["components"]["schemas"]
    schemas["Pet"]["properties"]["owner"] = {"$ref": "#/components/schemas/Owner"}
    schemas["Owner"] = {"properties": {"pets": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}}}
    schemas["Loop"] = {"properties": {"next": {"$ref": "#/components/schemas/Loop"}}}
    unused = {f.path for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"}
    assert unused == {"components.schemas.Loop"}  # only itself refers to it


def test_discriminator_mappings_and_deep_references_count_as_use():
    document = _doc()
    schemas = document["components"]["schemas"]
    schemas["Pet"]["discriminator"] = {
        "propertyName": "kind",
        "mapping": {"cat": "Cat", "dog": "#/components/schemas/Dog"},
    }
    schemas["Pet"]["properties"]["tag"] = {"$ref": "#/components/schemas/Shared/properties/tag"}
    schemas.update({"Cat": {}, "Dog": {}, "Shared": {"properties": {"tag": {"type": "string"}}}})
    assert [f for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"] == []


def test_other_component_sections_are_checked_and_security_schemes_are_not():
    document = _doc()
    document["components"].update(
        {
            "parameters": {"Limit": {"name": "limit", "in": "query"}},
            "responses": {"NotFound": {"description": "Not found."}},
            "securitySchemes": {"key": {"type": "apiKey", "name": "k", "in": "header"}},
        }
    )
    document["paths"]["/pets"]["get"]["parameters"] = [{"$ref": "#/components/parameters/Limit"}]
    unused = {f.path for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"}
    assert unused == {"components.responses.NotFound"}


def test_a_component_library_without_paths_reports_nothing_unused():
    document = _doc()
    del document["paths"]
    assert [f for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"] == []


def test_a_webhook_reference_keeps_a_component():
    document = _doc(webhooks={"petAdded": {"post": {"requestBody": {"$ref": "#/components/requestBodies/Added"}}}})
    document["components"]["requestBodies"] = {"Added": {"content": {}}}
    assert [f for f in lint_openapi_fixable(document) if f.rule == "structure.unused-component"] == []


def test_a_component_name_that_needs_pointer_escaping_resolves():
    document = _doc()
    document["components"]["schemas"]["v1/Old.Thing"] = {"type": "string"}
    assert _plan(document, "structure.unused-component") == [
        {"op": "remove", "path": "/components/schemas/v1~1Old.Thing"}
    ]


# ===========================================================================
# Tags
# ===========================================================================


def test_a_duplicate_tag_with_its_own_text_is_left_to_a_person():
    document = _doc(tags=[{"name": "pets", "description": "First."}, {"name": "pets", "description": "Second."}])
    assert _plan(document, "structure.duplicate-tag") == []


def test_an_identical_duplicate_tag_is_removed():
    document = _doc(tags=[{"name": "pets", "description": "Same."}, {"name": "pets", "description": "Same."}])
    assert _plan(document, "structure.duplicate-tag") == [{"op": "remove", "path": "/tags/1"}]


def test_tag_case_is_ambiguous_when_both_casings_are_declared():
    document = _doc(tags=[{"name": "pets"}, {"name": "Pets"}])
    document["paths"]["/pets"]["get"]["tags"] = ["PETS"]
    assert [f for f in lint_openapi_fixable(document) if f.rule == "naming.tag-case-mismatch"] == []


def test_an_undeclared_tag_is_not_a_case_mismatch():
    document = _doc()
    document["paths"]["/pets"]["get"]["tags"] = ["store"]
    assert lint_openapi_fixable(document) == []


def test_missing_tags_are_not_filled_in_by_default_or_from_a_path_parameter():
    document = _doc()
    del document["paths"]["/pets"]["get"]["tags"]
    assert _plan(document, "structure.operation-missing-tags") == []

    document["paths"] = {"/{tenant}/pets": {"get": {"operationId": "listPets", "tags": [], "responses": {}}}}
    del document["components"]
    assert _plan(document, "structure.operation-missing-tags", "structure.operation-missing-tags") == []


# ===========================================================================
# operationId
# ===========================================================================


@pytest.mark.parametrize(
    "template, method, path, expected",
    [
        ("{method}{Path}", "get", "/pets/{petId}", "getPetsPetId"),
        ("{method}{Path}", "POST", "/pet-store/v1.orders", "postPetStoreV1Orders"),
        ("{method}{Path}", "get", "/", "getRoot"),
        ("{path}_{method}", "delete", "/pets/{petId}", "petsPetId_delete"),
        ("{Method}{Path}", "patch", "/API/users", "PatchApiUsers"),
    ],
)
def test_render_operation_id(template: str, method: str, path: str, expected: str):
    assert render_operation_id(template, method, path) == expected


def _two_operations() -> Dict[str, Any]:
    document = _doc()
    document["paths"] = {
        "/pets": {"get": {"tags": ["pets"], "responses": {}}, "post": {"operationId": "getPetsId", "tags": ["pets"]}},
        "/pets/{id}": {"get": {"tags": ["pets"], "responses": {}}},
        "/pets/id": {"get": {"tags": ["pets"], "responses": {}}},
    }
    del document["components"]
    return document


def test_generated_operation_ids_are_unique_across_the_document():
    document = _two_operations()
    generated = {}
    for finding in lint_openapi_fixable(document):
        if finding.rule == "structure.operation-missing-operation-id":
            (op,) = plan_openapi_fix(document, finding)
            generated[finding.path] = op.value
    # "getPetsId" is taken by POST /pets, and the two /pets/… paths render alike.
    assert generated == {
        "paths./pets.get": "getPets",
        "paths./pets/{id}.get": "getPetsId2",
        "paths./pets/id.get": "getPetsId3",
    }


def test_the_operation_id_template_is_the_callers():
    document = _two_operations()
    finding = next(f for f in lint_openapi_fixable(document) if f.path == "paths./pets.get")
    (op,) = plan_openapi_fix(document, finding, FixOptions(operation_id_template="{path}_{method}"))
    assert op.as_dict() == {"op": "add", "path": "/paths/~1pets/get/operationId", "value": "pets_get"}


def test_a_template_that_renders_no_identifier_plans_nothing():
    document = _two_operations()
    finding = next(f for f in lint_openapi_fixable(document) if f.path == "paths./pets.get")
    assert plan_openapi_fix(document, finding, FixOptions(operation_id_template="{path}-{method}")) == ()


@pytest.mark.parametrize(
    "operation_id, expected",
    [("List_pets", "listPets"), ("ListPets", "listPets"), ("list-pets", "listPets"), ("LIST_PETS", "listPets")],
)
def test_operation_id_recasing(operation_id: str, expected: str):
    document = _doc()
    document["paths"]["/pets"]["get"]["operationId"] = operation_id
    assert _plan(document, "naming.operation-id-camel-case") == [
        {"op": "replace", "path": "/paths/~1pets/get/operationId", "value": expected}
    ]


def test_operation_id_is_not_recased_into_a_collision_or_under_a_link():
    document = _doc()
    document["paths"]["/pets"]["get"]["operationId"] = "List_pets"
    document["paths"]["/pets"]["post"] = {"operationId": "listPets", "tags": ["pets"]}
    assert _plan(document, "naming.operation-id-camel-case") == []

    document["paths"]["/pets"]["post"]["operationId"] = "createPet"
    document["paths"]["/pets"]["post"]["responses"] = {
        "201": {"description": "Created", "links": {"list": {"operationId": "List_pets"}}}
    }
    assert _plan(document, "naming.operation-id-camel-case") == []


def test_an_operation_id_that_cannot_be_camel_cased_plans_nothing():
    document = _doc()
    document["paths"]["/pets"]["get"]["operationId"] = "1-list"
    assert _plan(document, "naming.operation-id-camel-case") == []


# ===========================================================================
# Schema rename
# ===========================================================================


def _snake_schema_document() -> Dict[str, Any]:
    document = _doc()
    schemas = document["components"]["schemas"]
    schemas["pet_record"] = schemas.pop("Pet")
    schemas["pet_record"]["properties"]["parent"] = {"$ref": "#/components/schemas/pet_record"}
    schemas["pet_record"]["properties"]["tag"] = {"$ref": "#/components/schemas/pet_record/properties/name"}
    schemas["Animal"] = {
        "oneOf": [{"$ref": "#/components/schemas/pet_record"}],
        "discriminator": {
            "propertyName": "kind",
            "mapping": {"a": "pet_record", "b": "#/components/schemas/pet_record"},
        },
    }
    get = document["paths"]["/pets"]["get"]
    get["responses"]["200"]["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/Animal"}
    return document


def test_the_schema_rename_is_never_planned_without_an_opt_in():
    assert _plan(_snake_schema_document(), "naming.schema-pascal-case") == []


def test_the_schema_rename_rewrites_every_reference_then_moves_the_schema():
    document = _snake_schema_document()
    plan = _plan(document, "naming.schema-pascal-case", "naming.schema-pascal-case")
    assert plan[-1] == {
        "op": "move",
        "path": "/components/schemas/PetRecord",
        "from": "/components/schemas/pet_record",
    }
    assert {(op["path"], op["value"]) for op in plan[:-1]} == {
        ("/components/schemas/pet_record/properties/parent/$ref", "#/components/schemas/PetRecord"),
        ("/components/schemas/pet_record/properties/tag/$ref", "#/components/schemas/PetRecord/properties/name"),
        ("/components/schemas/Animal/oneOf/0/$ref", "#/components/schemas/PetRecord"),
        ("/components/schemas/Animal/discriminator/mapping/a", "PetRecord"),
        ("/components/schemas/Animal/discriminator/mapping/b", "#/components/schemas/PetRecord"),
    }
    finding = _one(document, "naming.schema-pascal-case")
    after = apply_fix_ops(
        document, plan_openapi_fix(document, finding, FixOptions(opt_in=frozenset({finding.rule})))
    )
    assert "pet_record" not in json.dumps(after)
    assert lint_openapi_fixable(after) == []


def test_the_schema_rename_declines_a_taken_or_impossible_name():
    document = _snake_schema_document()
    document["components"]["schemas"]["PetRecord"] = {"type": "string"}
    document["paths"]["/pets"]["get"]["parameters"] = [
        {"name": "p", "in": "query", "schema": {"$ref": "#/components/schemas/PetRecord"}}
    ]
    assert _plan(document, "naming.schema-pascal-case", "naming.schema-pascal-case") == []

    document = _doc()
    document["components"]["schemas"]["1st"] = document["components"]["schemas"].pop("Pet")
    document["paths"]["/pets"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] = "#/components/schemas/1st"
    assert _plan(document, "naming.schema-pascal-case", "naming.schema-pascal-case") == []


# ===========================================================================
# The shipped OpenAPI fixtures stay fixable end to end
# ===========================================================================


@pytest.mark.parametrize("name", ["openapi-3.0-inventory.yaml", "openapi-3.1-petstore.yaml", "openapi-3.2-search.yaml"])
def test_every_planned_fix_applies_and_removes_its_finding(name: str):
    """Fix every on-demand finding of a real document, one at a time, until none is fixable."""
    import yaml

    document = yaml.safe_load((OPENAPI_FAMILY / name).read_text(encoding="utf-8"))
    options = FixOptions(opt_in=frozenset(rule.rule_id for rule in openapi_fix_rules()))
    for _round in range(500):
        planned = None
        for finding in lint_openapi_fixable(document):
            ops = plan_openapi_fix(document, finding, options)
            if ops:
                planned = (finding, ops)
                break
        if planned is None:
            break
        finding, ops = planned
        document = apply_fix_ops(document, ops)
        assert finding.id not in {f.id for f in lint_openapi_fixable(document)}
    else:  # pragma: no cover - a fix that never converges
        pytest.fail("fixes did not converge")
    assert all(not plan_openapi_fix(document, f, options) for f in lint_openapi_fixable(document))
