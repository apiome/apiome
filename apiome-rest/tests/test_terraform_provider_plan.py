"""Tests for the Terraform provider plan — SDK-4.4 (#4498).

The plan decides which operations form a resource. Most cases run against the corpus fixture
``openapi/38-terraform-crud-conventions.yaml`` (selected by tag, not path); the edge cases each
build the smallest OpenAPI document that exercises them.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pytest
import yaml
from corpus_loader import load_corpus

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
)
from app.openapi_normalizer import OpenApiNormalizer
from app.terraform_provider_plan import (
    ATTRIBUTE_COMPUTED,
    ATTRIBUTE_OPTIONAL_COMPUTED,
    ATTRIBUTE_REQUIRED,
    TerraformProviderPlan,
    TerraformResource,
    build_terraform_provider_plan,
    terraform_provider_name,
)


def _fixture_document() -> Dict[str, Any]:
    """The corpus fixture that follows the CRUD conventions."""
    [entry] = load_corpus(format="openapi", feature="terraform-crud")
    return yaml.safe_load(entry.read_text())


def _plan(document: Optional[Dict[str, Any]] = None) -> TerraformProviderPlan:
    """Normalize ``document`` (default: the fixture) and plan its provider."""
    api = OpenApiNormalizer().normalize(document if document is not None else _fixture_document())
    return build_terraform_provider_plan(api)


def _resource(plan: TerraformProviderPlan, name: str) -> TerraformResource:
    """The planned resource called ``name``."""
    [resource] = [candidate for candidate in plan.resources if candidate.name == name]
    return resource


def _attributes(resource: TerraformResource) -> Dict[str, Any]:
    """``name → attribute`` for a resource."""
    return {attribute.name: attribute for attribute in resource.attributes}


def _codes(plan: TerraformProviderPlan) -> List[str]:
    """Every warning code, in order."""
    return [warning.code for warning in plan.warnings]


def _crud_document(**overrides: Any) -> Dict[str, Any]:
    """The smallest conventional CRUD document: one ``Thing`` collection."""
    thing = {
        "type": "object",
        "required": ["name"],
        "properties": {"id": {"type": "string", "readOnly": True}, "name": {"type": "string"}},
    }
    ref = {"$ref": "#/components/schemas/Thing"}
    body = {"required": True, "content": {"application/json": {"schema": ref}}}
    answer = {"content": {"application/json": {"schema": ref}}}
    item = {"name": "thingId", "in": "path", "required": True, "schema": {"type": "string"}}
    document: Dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Things", "version": "1"},
        "servers": [{"url": "https://things.example.com"}],
        "paths": {
            "/things": {
                "post": {
                    "operationId": "createThing",
                    "requestBody": body,
                    "responses": {"201": {"description": "c", **answer}},
                },
            },
            "/things/{thingId}": {
                "parameters": [item],
                "get": {"operationId": "getThing", "responses": {"200": {"description": "r", **answer}}},
                "put": {
                    "operationId": "putThing",
                    "requestBody": body,
                    "responses": {"200": {"description": "u", **answer}},
                },
                "delete": {"operationId": "deleteThing", "responses": {"204": {"description": "d"}}},
            },
        },
        "components": {"schemas": {"Thing": thing}},
    }
    for key, value in overrides.items():
        document[key] = value
    return copy.deepcopy(document)


# ===========================================================================
# The corpus fixture
# ===========================================================================


def test_a_conventional_collection_becomes_a_resource() -> None:
    widget = _resource(_plan(), "widget")
    assert widget.collection_path == "/widgets"
    assert widget.item_path == "/widgets/{widgetId}"
    assert widget.id_param == "widgetId"
    assert widget.id_attr == "id"
    assert [(role, ref.operation_id) for role, ref in widget.operations] == [
        ("create", "createWidget"),
        ("read", "getWidget"),
        ("update", "replaceWidget"),
        ("delete", "deleteWidget"),
    ]
    assert widget.import_parts == ("id",)


def test_attribute_modes_follow_the_create_body_and_read_only_members() -> None:
    attributes = _attributes(_resource(_plan(), "widget"))
    assert attributes["id"].mode == ATTRIBUTE_COMPUTED  # readOnly, and the identifier
    assert attributes["id"].is_id and not attributes["id"].create
    assert attributes["created_at"].mode == ATTRIBUTE_COMPUTED  # readOnly
    assert attributes["name"].mode == ATTRIBUTE_REQUIRED
    assert attributes["size"].mode == ATTRIBUTE_OPTIONAL_COMPUTED
    assert attributes["name"].create and attributes["name"].update
    assert attributes["id"].field.kind == "int"
    assert attributes["tags"].field.kind == "list" and attributes["tags"].field.elem.kind == "string"
    assert attributes["settings"].field.kind == "object"
    assert [member.attr for member in attributes["settings"].field.fields] == ["color", "retries"]


def test_schema_hints_drop_members_and_force_replacement() -> None:
    attributes = _attributes(_resource(_plan(), "widget"))
    assert "etag" not in attributes  # x-terraform: ignore
    assert attributes["region"].force_new  # x-terraform: forceNew
    assert not attributes["name"].force_new
    assert attributes["region"].field.enum == ("us-east", "eu-west")


def test_a_nested_collection_requires_its_parent_and_replaces_on_a_new_parent() -> None:
    project = _resource(_plan(), "project")
    attributes = _attributes(project)
    org = attributes["org_id"]
    assert org.mode == ATTRIBUTE_REQUIRED and org.path_param == "orgId" and org.force_new
    assert not org.create and not org.update
    assert project.import_parts == ("org_id", "id")
    # PATCH is the update when there is no PUT; the create body is a distinct input schema.
    assert project.operation("update").method == "PATCH"
    assert attributes["name"].mode == ATTRIBUTE_REQUIRED
    assert attributes["id"].mode == ATTRIBUTE_COMPUTED


def test_operation_hints_assemble_a_resource_the_paths_do_not() -> None:
    gadget = _resource(_plan(), "gadget")
    assert gadget.operation("create").operation_id == "orderGadget"
    assert gadget.collection_path == "/gadget-orders"
    assert gadget.item_path == "/gadgets/{serial}"
    assert gadget.id_attr == "serial"  # x-terraform: id
    assert gadget.operation("update") is None
    assert gadget.import_parts == ()  # x-terraform: import false
    attributes = _attributes(gadget)
    # Without an update every configurable attribute replaces the resource.
    assert attributes["model"].force_new
    assert attributes["options"].field.kind == "json"  # a oneOf


def test_a_read_only_collection_is_a_data_source_and_is_reported() -> None:
    plan = _plan()
    assert "region" not in [resource.name for resource in plan.resources]
    assert "region" in [source.name for source in plan.item_data_sources]
    [incomplete] = [warning for warning in plan.warnings if warning.code == "terraform.incomplete-resource"]
    assert "`region`" in incomplete.message and "create or delete" in incomplete.message


def test_item_data_sources_look_up_by_the_identifier() -> None:
    [widget] = [source for source in _plan().item_data_sources if source.name == "widget"]
    lookup = [attribute for attribute in widget.attributes if attribute.path_param]
    assert [(attribute.name, attribute.path_param, attribute.mode) for attribute in lookup] == [
        ("id", "widgetId", ATTRIBUTE_REQUIRED)
    ]
    assert all(attribute.mode == ATTRIBUTE_COMPUTED for attribute in widget.attributes if not attribute.path_param)
    assert "etag" not in [attribute.name for attribute in widget.attributes]


def test_list_operations_become_list_data_sources() -> None:
    lists = {source.name: source for source in _plan().list_data_sources}
    assert set(lists) == {"widget_list", "project_list", "region_list"}
    assert lists["widget_list"].list_member == "items"  # the {"items": [...]} envelope
    assert lists["region_list"].list_member == ""  # a bare array
    assert [parent.name for parent in lists["project_list"].parents] == ["org_id"]
    assert "etag" not in [member.attr for member in lists["widget_list"].item.fields]


def test_operations_that_are_not_crud_shaped_are_reported_not_guessed() -> None:
    plan = _plan()
    reported = {warning.operation_id for warning in plan.warnings if warning.code == "terraform.not-crud-shaped"}
    assert {"restartWidget", "search"} <= reported
    [ignored] = [warning for warning in plan.warnings if warning.code == "terraform.operation-ignored"]
    assert ignored.operation_id == "getHealth" and ignored.severity == "info"


def test_loosely_typed_members_are_reported_as_json() -> None:
    messages = [warning.message for warning in _plan().warnings if warning.code == "terraform.json-attribute"]
    assert any("gadget.options" in message for message in messages)


def test_security_schemes_become_provider_settings() -> None:
    auth = {setting.scheme: setting for setting in _plan().auth}
    assert auth["bearerAuth"].kind == "bearer" and auth["bearerAuth"].attributes == ("token",)
    key = auth["apiKeyAuth"]
    assert (key.kind, key.location, key.parameter, key.attributes) == (
        "api_key",
        "header",
        "X-Platform-Key",
        ("api_key",),
    )


def test_the_plan_is_deterministic() -> None:
    assert _plan() == _plan()


def test_the_provider_name_comes_from_the_title() -> None:
    plan = _plan()
    assert plan.provider_name == "widgetplatformapi"
    assert plan.base_url == "https://api.example.com/v1"


# ===========================================================================
# Edge cases
# ===========================================================================


def test_the_smallest_crud_document_is_one_clean_resource() -> None:
    plan = _plan(_crud_document())
    assert [resource.name for resource in plan.resources] == ["thing"]
    assert plan.warnings == ()


def test_a_missing_identifier_is_reported() -> None:
    document = _crud_document()
    del document["components"]["schemas"]["Thing"]["properties"]["id"]
    plan = _plan(document)
    assert plan.resources == ()
    assert "terraform.no-id-attribute" in _codes(plan)


def test_a_member_named_like_the_placeholder_is_the_identifier() -> None:
    document = _crud_document()
    properties = document["components"]["schemas"]["Thing"]["properties"]
    properties["thingId"] = properties.pop("id")
    [thing] = _plan(document).resources
    assert thing.id_attr == "thing_id"


def test_a_create_that_answers_with_no_body_is_not_a_resource() -> None:
    document = _crud_document()
    document["paths"]["/things"]["post"]["responses"] = {"204": {"description": "nothing"}}
    plan = _plan(document)
    assert plan.resources == ()
    assert "terraform.create-returns-no-id" in _codes(plan)


def test_a_required_query_parameter_disqualifies_the_resource() -> None:
    document = _crud_document()
    document["paths"]["/things"]["post"]["parameters"] = [
        {"name": "dryRun", "in": "query", "required": True, "schema": {"type": "boolean"}}
    ]
    plan = _plan(document)
    assert plan.resources == ()
    [warning] = [w for w in plan.warnings if w.code == "terraform.unsupplied-parameter"]
    assert "query parameter `dryRun`" in warning.message


def test_a_required_header_is_left_to_the_provider_headers_setting() -> None:
    document = _crud_document()
    document["paths"]["/things"]["post"]["parameters"] = [
        {"name": "X-Tenant", "in": "header", "required": True, "schema": {"type": "string"}}
    ]
    plan = _plan(document)
    assert [resource.name for resource in plan.resources] == ["thing"]
    [warning] = [w for w in plan.warnings if w.code == "terraform.required-header"]
    assert warning.severity == "info" and "`X-Tenant`" in warning.message


def test_without_an_update_every_configurable_attribute_replaces() -> None:
    document = _crud_document()
    del document["paths"]["/things/{thingId}"]["put"]
    attributes = _attributes(_plan(document).resources[0])
    assert attributes["name"].force_new
    assert not attributes["id"].force_new  # computed: nothing to replace on


def test_put_wins_over_patch_and_the_patch_is_reported() -> None:
    document = _crud_document()
    item = document["paths"]["/things/{thingId}"]
    item["patch"] = {**item["put"], "operationId": "patchThing"}
    plan = _plan(document)
    assert plan.resources[0].operation("update").operation_id == "putThing"
    assert "patchThing" in {w.operation_id for w in plan.warnings if w.code == "terraform.not-crud-shaped"}


def test_an_operation_hint_can_replace_a_conventional_operation() -> None:
    document = _crud_document()
    document["paths"]["/things:bulk"] = {
        "post": {
            **document["paths"]["/things"]["post"],
            "operationId": "createThingV2",
            "x-terraform": {"resource": "thing", "operation": "create"},
        }
    }
    plan = _plan(document)
    assert plan.resources[0].operation("create").operation_id == "createThingV2"
    assert "createThing" in {w.operation_id for w in plan.warnings if w.code == "terraform.not-crud-shaped"}


def test_an_operation_hint_can_exclude_an_operation() -> None:
    document = _crud_document()
    document["paths"]["/things/{thingId}"]["delete"]["x-terraform"] = {"ignore": True}
    plan = _plan(document)
    assert plan.resources == ()
    assert "terraform.operation-ignored" in _codes(plan)
    assert "terraform.incomplete-resource" in _codes(plan)


@pytest.mark.parametrize(
    "hint",
    [{"resource": "thing", "operation": "upsert"}, {"operation": "create"}, "yes"],
)
def test_an_invalid_operation_hint_is_reported_and_ignored(hint: Any) -> None:
    document = _crud_document()
    document["paths"]["/things"]["post"]["x-terraform"] = hint
    plan = _plan(document)
    assert "terraform.invalid-hint" in _codes(plan)
    assert [resource.name for resource in plan.resources] == ["thing"]  # the convention still applies


def test_a_schema_hint_naming_an_unknown_member_is_reported() -> None:
    document = _crud_document()
    document["components"]["schemas"]["Thing"]["x-terraform"] = {"forceNew": ["colour"]}
    plan = _plan(document)
    [warning] = [w for w in plan.warnings if w.code == "terraform.invalid-hint"]
    assert "`colour`" in warning.message


def test_a_schema_hint_can_rename_and_disable_the_resource() -> None:
    document = _crud_document()
    document["components"]["schemas"]["Thing"]["x-terraform"] = {"resource": "Gizmo"}
    assert [resource.name for resource in _plan(document).resources] == ["gizmo"]
    document["components"]["schemas"]["Thing"]["x-terraform"] = {"resource": False}
    plan = _plan(document)
    assert plan.resources == ()
    assert [source.name for source in plan.item_data_sources] == ["thing"]
    assert "terraform.resource-disabled" in _codes(plan)


def test_a_schema_hint_can_disable_the_data_sources() -> None:
    document = _crud_document()
    document["components"]["schemas"]["Thing"]["x-terraform"] = {"dataSource": False}
    plan = _plan(document)
    assert [resource.name for resource in plan.resources] == ["thing"]
    assert plan.item_data_sources == ()


def test_reserved_meta_argument_names_are_renamed() -> None:
    document = _crud_document()
    document["components"]["schemas"]["Thing"]["properties"]["count"] = {"type": "integer"}
    attributes = _attributes(_plan(document).resources[0])
    assert "count" not in attributes
    assert attributes["count_value"].field.wire == "count"


def test_a_recursive_schema_is_held_as_json_rather_than_expanded_forever() -> None:
    document = _crud_document()
    document["components"]["schemas"]["Thing"]["properties"]["parent"] = {"$ref": "#/components/schemas/Thing"}
    parent = _attributes(_plan(document).resources[0])["parent"]
    assert parent.field.kind == "object"
    inner = {member.attr: member for member in parent.field.fields}
    assert inner["parent"].kind == "json"


def test_unsupported_auth_is_reported_and_left_to_headers() -> None:
    document = _crud_document()
    document["components"]["securitySchemes"] = {"mtls": {"type": "mutualTLS"}}
    plan = _plan(document)
    assert plan.auth == ()
    assert "terraform.unsupported-auth" in _codes(plan)


def test_basic_auth_becomes_a_username_and_password() -> None:
    document = _crud_document()
    document["components"]["securitySchemes"] = {"basicAuth": {"type": "http", "scheme": "basic"}}
    [setting] = _plan(document).auth
    assert (setting.kind, setting.attributes) == ("basic", ("username", "password"))


def test_a_model_with_no_source_document_falls_back_to_canonical_schemes() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="har",
        title="Inferred",
        identity=ApiIdentity(name="inferred"),
        extras={"inferred_auth_schemes": ["bearer"]},
        services=[
            Service(
                key="s",
                name="s",
                operations=[
                    Operation(
                        key="GET /ping",
                        name="ping",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="get",
                        http_path="/ping",
                    )
                ],
            )
        ],
    )
    plan = build_terraform_provider_plan(api)
    assert [(setting.kind, setting.attributes) for setting in plan.auth] == [("bearer", ("token",))]
    assert plan.resources == ()


def test_operations_without_an_http_binding_are_reported() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        title="Graph",
        identity=ApiIdentity(name="graph"),
        services=[
            Service(
                key="q",
                name="Query",
                operations=[Operation(key="Query.things", name="things", kind=OperationKind.QUERY)],
            )
        ],
    )
    plan = build_terraform_provider_plan(api)
    [warning] = plan.warnings
    assert (warning.code, warning.key) == ("terraform.no-http-binding", "Query.things")


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("acme-widgets",), "acmewidgets"),
        ((None, "Widget Platform API"), "widgetplatformapi"),
        (("42 things",), "api42things"),
        ((None, "", "!!"), "api"),
    ],
)
def test_provider_names_are_lower_case_alphanumerics(candidates: Any, expected: str) -> None:
    assert terraform_provider_name(*candidates) == expected


def test_operations_beyond_the_cap_are_reported_as_truncated() -> None:
    api = OpenApiNormalizer().normalize(_crud_document())
    plan = build_terraform_provider_plan(api, max_operations=2)
    truncated = [warning for warning in plan.warnings if warning.code == "terraform.truncated"]
    assert len(truncated) == 2
    assert "terraform.no-http-binding" not in _codes(plan)


def test_a_named_map_schema_is_a_map_of_its_value_type() -> None:
    """The stub plan records a named map's *value* shape as its target; the map must survive that."""
    document = _crud_document()
    document["components"]["schemas"]["Counts"] = {"type": "object", "additionalProperties": {"type": "integer"}}
    document["components"]["schemas"]["Thing"]["properties"]["counts"] = {"$ref": "#/components/schemas/Counts"}
    counts = _attributes(_plan(document).resources[0])["counts"].field
    assert counts.kind == "map"
    assert counts.elem is not None and counts.elem.kind == "int"
