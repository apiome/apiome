"""The server stub plan — SDK-2.5 (#4490).

Pure-function tests for :mod:`app.server_stub_plan`, the language-neutral middle both server stub
generators render from: how a canonical type becomes a shape, how an operation becomes a route,
which names are allocated out of which namespace, and the two rules that keep the FastAPI and the
Express projects describing one contract rather than two — one shared class name per schema, and
one shared set of enforceable constraints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.server_stub_plan import (
    DEFAULT_MAX_OPERATIONS,
    Names,
    ValueShape,
    build_server_stub_plan,
    camel_case,
    constraint_facts,
    pascal_case,
    python_identifier,
    screaming_snake_case,
    shape_constraints,
    snake_case,
    typescript_identifier,
    words,
    wrap_text,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _member(name: str, type_name: str, *, required: bool = False, item: Optional[str] = None) -> CanonicalField:
    """One record member. ``required`` is the canonical ``nullable=False`` spelling."""
    ref = (
        TypeRef(name="list", item=TypeRef(name=item), nullable=not required)
        if item is not None
        else TypeRef(name=type_name, nullable=not required)
    )
    return CanonicalField(key=f"X.{name}", name=name, type=ref)


def _op(
    key: str,
    name: str,
    *,
    method: Optional[str] = "get",
    path: Optional[str] = "/widgets",
    parameters: Optional[List[Parameter]] = None,
    messages: Optional[List[Message]] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Operation:
    """One operation, HTTP-bound unless ``method``/``path`` are cleared."""
    return Operation(
        key=key,
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=messages or [],
        extras={"operationId": name, **(extras or {})},
    )


def _api(
    *,
    types: Optional[List[Type]] = None,
    operations: Optional[List[Operation]] = None,
    services: Optional[List[Service]] = None,
    servers: Optional[List[Server]] = None,
) -> CanonicalApi:
    """A REST model with the pieces a test cares about substituted in."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Widgets API",
        version="1.0.0",
        identity=ApiIdentity(name="widgets"),
        servers=servers if servers is not None else [Server(url="https://api.example.dev/v2")],
        types=types or [],
        services=services
        if services is not None
        else [Service(key="svc", name="widgets", operations=operations or [])],
    )


# ===========================================================================
# Identifiers
# ===========================================================================


def test_words_splits_separators_and_camel_seams_alike() -> None:
    assert words("pet_id") == words("pet-id") == words("petId") == ["pet", "id"]
    assert words(None) == []


def test_the_case_helpers_agree_on_one_word_split() -> None:
    assert pascal_case("pet_id") == "PetId"
    assert camel_case("pet_id") == "petId"
    assert snake_case("petId") == "pet_id"
    assert screaming_snake_case("petId") == "PET_ID"


def test_an_identifier_that_would_start_with_a_digit_is_prefixed() -> None:
    """No language this generator targets accepts a leading digit."""
    assert pascal_case("2fa") == "N2fa"
    assert camel_case("2fa") == "n2fa"
    assert snake_case("2fa") == "n_2fa"


def test_a_python_keyword_is_suffixed_not_dropped() -> None:
    assert python_identifier("from") == "from_"
    assert python_identifier("class") == "class_"
    assert python_identifier("limit") == "limit"


def test_a_pydantic_reserved_prefix_is_moved_out_of_the_way() -> None:
    """A field called ``model_config`` would replace the model's own configuration."""
    assert python_identifier("model_config") == "field_model_config"


def test_a_typescript_class_member_name_is_guarded_only_where_it_has_to_be() -> None:
    assert typescript_identifier("constructor") == "constructor_"
    assert typescript_identifier("class") == "class"


def test_the_allocator_suffixes_rather_than_colliding() -> None:
    names = Names({"Pet"})
    assert names.take("Pet") == "Pet2"
    assert names.take("Pet") == "Pet3"
    assert names.take("Dog") == "Dog"
    assert names.taken("Dog") is True


# ===========================================================================
# Schemas
# ===========================================================================


def test_a_record_becomes_a_schema_with_its_members_resolved() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[
                Type(
                    key="Widget",
                    name="Widget",
                    kind=TypeKind.RECORD,
                    fields=[_member("id", "i64", required=True), _member("tags", "", item="string")],
                )
            ]
        )
    )
    schema = plan.schemas[0]
    assert (schema.class_name, schema.kind) == ("Widget", "record")
    assert [(m.wire_name, m.required, m.shape.kind) for m in schema.fields] == [
        ("id", True, "integer"),
        ("tags", False, "array"),
    ]


def test_a_member_keeps_its_wire_name_in_typescript_and_is_snake_cased_in_python() -> None:
    """The two languages disagree about naming; neither may disagree with the JSON."""
    plan = build_server_stub_plan(
        _api(types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=[_member("pageSize", "i32")])])
    )
    member = plan.schemas[0].fields[0]
    assert (member.wire_name, member.ts_name, member.py_name) == ("pageSize", "pageSize", "page_size")


def test_a_python_keyword_member_is_escaped_without_losing_its_wire_name() -> None:
    plan = build_server_stub_plan(
        _api(types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=[_member("from", "string")])])
    )
    member = plan.schemas[0].fields[0]
    assert (member.wire_name, member.py_name, member.ts_name) == ("from", "from_", "from")


def test_an_enum_takes_its_declared_wire_values_over_its_member_names() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[
                Type(
                    key="Status",
                    name="Status",
                    kind=TypeKind.ENUM,
                    enum_values=[
                        EnumValue(key="a", name="available", value="AVAILABLE"),
                        EnumValue(key="b", name="sold", value="SOLD"),
                        EnumValue(key="c", name="dup", value="SOLD"),
                    ],
                )
            ]
        )
    )
    schema = plan.schemas[0]
    assert schema.enum_value_kind == "string"
    assert schema.enum_members == (("available", "AVAILABLE"), ("sold", "SOLD"))


def test_a_heterogeneous_enum_is_reported_as_mixed_rather_than_guessed_at() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[
                Type(
                    key="Odd",
                    name="Odd",
                    kind=TypeKind.ENUM,
                    enum_values=[
                        EnumValue(key="a", name="one", value="one"),
                        EnumValue(key="b", name="two", value=2),
                    ],
                )
            ]
        )
    )
    assert plan.schemas[0].enum_value_kind == "mixed"


def test_a_reference_resolves_by_key_first_and_by_unique_name_second() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[
                Type(key="pkg.Widget", name="Widget", kind=TypeKind.RECORD, fields=[]),
                Type(
                    key="Holder",
                    name="Holder",
                    kind=TypeKind.RECORD,
                    fields=[_member("byName", "Widget"), _member("byKey", "pkg.Widget")],
                ),
            ]
        )
    )
    holder = plan.schema_by_key("Holder")
    assert holder is not None
    assert [member.shape.ref for member in holder.fields] == ["pkg.Widget", "pkg.Widget"]


def test_an_unknown_scalar_resolves_to_any_rather_than_to_a_wrong_type() -> None:
    plan = build_server_stub_plan(
        _api(types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=[_member("blob", "SomeVendorScalar")])])
    )
    assert plan.schemas[0].fields[0].shape.kind == "any"


def test_a_schema_gets_one_class_name_shared_by_both_languages() -> None:
    """"The Pet model" being called Pet in both stubs is the property this protects."""
    plan = build_server_stub_plan(
        _api(types=[Type(key="pet-record", name="pet record", kind=TypeKind.RECORD, fields=[])])
    )
    assert plan.schemas[0].class_name == "PetRecord"


def test_a_schema_cannot_claim_a_name_the_generated_modules_import() -> None:
    plan = build_server_stub_plan(
        _api(types=[Type(key="Field", name="Field", kind=TypeKind.RECORD, fields=[])])
    )
    assert plan.schemas[0].class_name == "Field2"


def test_a_schema_named_after_a_handler_interface_does_not_redeclare_it() -> None:
    """Both end up imported into one module, so they compete for one namespace."""
    plan = build_server_stub_plan(
        _api(
            types=[Type(key="WidgetsHandlers", name="WidgetsHandlers", kind=TypeKind.RECORD, fields=[])],
            operations=[_op("GET /widgets", "listWidgets")],
        )
    )
    assert plan.schemas[0].class_name == "WidgetsHandlers"
    assert plan.groups[0].handler_class == "WidgetsHandlers2"


# ===========================================================================
# Operations
# ===========================================================================


def test_an_operation_becomes_a_route_in_both_path_spellings() -> None:
    plan = build_server_stub_plan(_api(operations=[_op("GET /widgets/{id}", "getWidget", path="/widgets/{id}")]))
    operation = plan.operations[0]
    assert operation.path_template == "/widgets/{id}"
    assert operation.express_path == "/widgets/:id"
    assert (operation.py_name, operation.ts_name) == ("get_widget", "getWidget")


def test_a_path_without_a_leading_slash_is_rooted() -> None:
    plan = build_server_stub_plan(_api(operations=[_op("GET widgets", "listWidgets", path="widgets")]))
    assert plan.operations[0].path_template == "/widgets"


def test_an_empty_path_token_is_dropped_rather_than_registered_nameless() -> None:
    """Express refuses a nameless parameter at registration time — the server would not boot."""
    plan = build_server_stub_plan(_api(operations=[_op("GET /a/{}/b", "odd", path="/a/{}/b")]))
    assert plan.operations[0].express_path == "/a//b"
    assert plan.operations[0].path_params == ()


def test_a_path_parameter_is_required_whatever_the_contract_claims() -> None:
    """The route pattern cannot match without a value in that position."""
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "GET /widgets/{id}",
                    "getWidget",
                    path="/widgets/{id}",
                    parameters=[
                        Parameter(
                            key="p",
                            name="id",
                            location=ParameterLocation.PATH,
                            type=TypeRef(name="i64"),
                            required=False,
                        )
                    ],
                )
            ]
        )
    )
    assert plan.operations[0].path_params[0].required is True


def test_a_path_token_the_contract_never_declared_still_becomes_a_string_parameter() -> None:
    plan = build_server_stub_plan(_api(operations=[_op("GET /w/{id}", "getWidget", path="/w/{id}")]))
    parameter = plan.operations[0].path_params[0]
    assert (parameter.wire_name, parameter.shape.kind, parameter.required) == ("id", "string", True)


def test_a_repeated_path_token_becomes_one_parameter() -> None:
    plan = build_server_stub_plan(_api(operations=[_op("GET /a/{id}/b/{id}", "odd", path="/a/{id}/b/{id}")]))
    assert [param.wire_name for param in plan.operations[0].path_params] == ["id"]


def test_parameters_are_split_by_location_in_declaration_order() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    parameters=[
                        Parameter(key="q", name="limit", location=ParameterLocation.QUERY, type=TypeRef(name="i32")),
                        Parameter(
                            key="h",
                            name="X-Request-Id",
                            location=ParameterLocation.HEADER,
                            type=TypeRef(name="string"),
                        ),
                        Parameter(
                            key="c", name="session", location=ParameterLocation.COOKIE, type=TypeRef(name="string")
                        ),
                    ],
                )
            ]
        )
    )
    operation = plan.operations[0]
    assert [param.wire_name for param in operation.query_params] == ["limit"]
    assert [param.wire_name for param in operation.header_params] == ["X-Request-Id"]
    assert [param.wire_name for param in operation.cookie_params] == ["session"]
    assert operation.header_params[0].ts_name == "xRequestId"


def test_a_parameter_called_body_does_not_take_the_request_body_s_name() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    parameters=[
                        Parameter(key="q", name="body", location=ParameterLocation.QUERY, type=TypeRef(name="string"))
                    ],
                )
            ]
        )
    )
    assert plan.operations[0].query_params[0].ts_name == "body2"


def test_an_inline_enum_on_a_parameter_lands_on_its_shape() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    parameters=[
                        Parameter(
                            key="q",
                            name="status",
                            location=ParameterLocation.QUERY,
                            type=TypeRef(name="string"),
                            constraints=Constraints(enum=["new", "used"]),
                        )
                    ],
                )
            ]
        )
    )
    assert plan.operations[0].query_params[0].shape.enum == ("new", "used")


def test_a_json_request_body_is_typed_from_its_payload() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[])],
            operations=[
                _op(
                    "POST /widgets",
                    "createWidget",
                    method="post",
                    messages=[
                        Message(
                            key="req",
                            role=MessageRole.REQUEST,
                            payload=TypeRef(name="Widget"),
                            content_types=["application/json"],
                            required=True,
                        )
                    ],
                )
            ],
        )
    )
    body = plan.operations[0].body
    assert body is not None
    assert (body.is_json, body.required, body.shape.ref) == (True, True, "Widget")


def test_a_non_json_body_is_marked_for_pass_through_not_validation() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "POST /widgets",
                    "upload",
                    method="post",
                    messages=[
                        Message(
                            key="req",
                            role=MessageRole.REQUEST,
                            payload=TypeRef(name="bytes"),
                            content_types=["application/octet-stream"],
                        )
                    ],
                )
            ]
        )
    )
    body = plan.operations[0].body
    assert body is not None and body.is_json is False


def test_the_declared_success_status_wins_over_the_verb_default() -> None:
    plan = build_server_stub_plan(
        _api(
            types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[])],
            operations=[
                _op(
                    "POST /widgets",
                    "createWidget",
                    method="post",
                    messages=[
                        Message(key="r", role=MessageRole.RESPONSE, status_code="202", payload=TypeRef(name="Widget"))
                    ],
                )
            ],
        )
    )
    assert plan.operations[0].success.status == 202


def test_an_operation_with_no_response_payload_answers_204_or_201() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op("DELETE /widgets/{id}", "deleteWidget", method="delete", path="/widgets/{id}"),
                _op("POST /widgets", "createWidget", method="post"),
            ]
        )
    )
    assert [operation.success.status for operation in plan.operations] == [204, 201]
    assert all(operation.success.shape is None for operation in plan.operations)


def test_error_responses_are_collected_by_ascending_status() -> None:
    plan = build_server_stub_plan(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    messages=[
                        Message(key="e2", role=MessageRole.ERROR, status_code="500"),
                        Message(key="e1", role=MessageRole.ERROR, status_code="404"),
                        Message(key="range", role=MessageRole.ERROR, status_code="4XX"),
                    ],
                )
            ]
        )
    )
    assert [response.status for response in plan.operations[0].errors] == [404, 500]


def test_only_an_operation_scoped_security_requirement_is_carried() -> None:
    """A model-scoped *inferred* scheme is an observation, not a requirement (canonical_security)."""
    api = _api(operations=[_op("GET /widgets", "listWidgets", extras={"security": ["bearer", "bearer"]})])
    api.extras["inferred_auth_schemes"] = ["apiKey"]
    plan = build_server_stub_plan(api)
    assert plan.operations[0].security_schemes == ("bearer",)
    assert plan.security_schemes == ("bearer",)


# ===========================================================================
# Grouping, skipping, capping
# ===========================================================================


def test_operations_are_grouped_by_service_in_declaration_order() -> None:
    plan = build_server_stub_plan(
        _api(
            services=[
                Service(key="a", name="widgets", operations=[_op("GET /widgets", "listWidgets")]),
                Service(key="b", name="admin", operations=[_op("GET /admin", "listAdmin", path="/admin")]),
            ]
        )
    )
    assert [group.name for group in plan.groups] == ["widgets", "admin"]
    assert [group.module for group in plan.groups] == ["widgets", "admin"]
    assert [group.handler_class for group in plan.groups] == ["WidgetsHandlers", "AdminHandlers"]
    assert [group.stub_class for group in plan.groups] == [
        "NotImplementedWidgetsHandlers",
        "NotImplementedAdminHandlers",
    ]


def test_a_group_whose_operations_are_all_unroutable_is_not_emitted_empty() -> None:
    plan = build_server_stub_plan(
        _api(
            services=[
                Service(key="a", name="widgets", operations=[_op("GET /widgets", "listWidgets")]),
                Service(key="b", name="events", operations=[_op("Sub.events", "events", method=None, path=None)]),
            ]
        )
    )
    assert [group.name for group in plan.groups] == ["widgets"]


def test_an_operation_with_no_http_binding_is_skipped_with_a_reason() -> None:
    plan = build_server_stub_plan(
        _api(operations=[_op("GET /widgets", "listWidgets"), _op("Query.things", "things", method=None, path=None)])
    )
    assert len(plan.operations) == 1
    assert plan.skipped[0].operation_id == "things"
    assert "no HTTP binding" in plan.skipped[0].reason


def test_the_cap_reports_what_it_left_out_and_counts_only_routable_operations() -> None:
    operations = [_op("Query.things", "things", method=None, path=None)]
    operations += [_op(f"GET /w/{index}", f"op{index}", path=f"/w/{index}") for index in range(4)]
    plan = build_server_stub_plan(_api(operations=operations), max_operations=2)
    assert [operation.operation_id for operation in plan.operations] == ["op0", "op1"]
    assert plan.truncated is True
    assert plan.total_operation_count == 5
    assert [item.operation_id for item in plan.skipped] == ["things", "op2", "op3"]
    assert "beyond that limit" in plan.skipped[-1].reason


def test_a_module_name_that_is_a_python_keyword_is_escaped() -> None:
    plan = build_server_stub_plan(
        _api(services=[Service(key="a", name="import", operations=[_op("GET /w", "listW", path="/w")])])
    )
    assert plan.groups[0].module == "import_"


# ===========================================================================
# Model-level facts
# ===========================================================================


def test_the_base_path_comes_from_the_declared_server_and_keeps_only_its_path() -> None:
    plan = build_server_stub_plan(_api(servers=[Server(url="https://api.example.dev/v2/")]))
    assert plan.base_path == "/v2"


def test_a_server_with_no_path_yields_no_prefix() -> None:
    assert build_server_stub_plan(_api(servers=[Server(url="https://api.example.dev")])).base_path == ""
    assert build_server_stub_plan(_api(servers=[])).base_path == ""


def test_only_constraints_both_stubs_can_enforce_survive() -> None:
    """A rule one stub applied and the other did not would make them two contracts."""
    facts = constraint_facts(
        Constraints(minimum=1, maximum=10, pattern="^a", unique_items=True, format="date-time")
    )
    assert facts == {"minimum": 1, "maximum": 10, "pattern": "^a"}
    assert constraint_facts(None) == {}


def test_a_constraint_only_applies_to_the_shape_family_it_means_something_for() -> None:
    """``min_length`` means characters on a string and items on an array; the two are not the same."""
    bounds = Constraints(minimum=1, maximum=10, min_length=2, max_length=8, min_items=3, pattern="^a")
    assert shape_constraints(ValueShape(kind="string", constraints=bounds)) == {
        "min_length": 2,
        "max_length": 8,
        "pattern": "^a",
    }
    assert shape_constraints(ValueShape(kind="integer", constraints=bounds)) == {
        "minimum": 1,
        "maximum": 10,
    }
    assert shape_constraints(ValueShape(kind="array", constraints=bounds)) == {"min_items": 3}
    assert shape_constraints(ValueShape(kind="boolean", constraints=bounds)) == {}


def test_a_whole_number_bound_keeps_an_integer_spelling() -> None:
    """`Constraints` stores every bound as a float; `le=100.0` on an int reads as a float bound."""
    bounds = Constraints(minimum=1, maximum=100)
    assert shape_constraints(ValueShape(kind="integer", constraints=bounds)) == {
        "minimum": 1,
        "maximum": 100,
    }
    # A genuinely fractional bound on a number keeps its float.
    assert shape_constraints(ValueShape(kind="number", constraints=Constraints(maximum=1.5))) == {
        "maximum": 1.5
    }


def test_wrapping_never_breaks_a_word() -> None:
    assert wrap_text("one two three four", 9) == ["one two", "three", "four"]
    assert wrap_text("indivisible", 4) == ["indivisible"]


def test_the_default_cap_matches_the_go_clients_so_one_kit_cannot_disagree_with_itself() -> None:
    from app.go_client_generator import DEFAULT_MAX_OPERATIONS as GO_CAP

    assert DEFAULT_MAX_OPERATIONS == GO_CAP


def test_planning_twice_produces_an_equal_plan() -> None:
    api = _api(
        types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[_member("id", "i64", required=True)])],
        operations=[_op("GET /widgets/{id}", "getWidget", path="/widgets/{id}")],
    )
    assert build_server_stub_plan(api) == build_server_stub_plan(api)
