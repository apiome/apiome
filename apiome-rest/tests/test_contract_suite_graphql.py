"""The GraphQL protocol adapter of the contract-suite compiler — XPC-1.2 (#5730).

Every test compiles real SDL through the real parser and normalizer, so what is pinned here is
what a published GraphQL version actually produces. The strongest check is
:func:`test_every_compiled_document_behaves_as_its_expectation_says`: each compiled document is
executed by graphql-core against the same schema, so a positive case that a conforming server
would reject — or a negative case it would accept — fails here rather than against a customer.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from graphql import graphql_sync

from app.canonical_model import ApiParadigm, TypeRef
from app.contract_protocols import PROTOCOL_GRAPHQL, PROTOCOL_HTTP
from app.contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    CASE_SOURCE_GENERATED_FULL,
    CASE_SOURCE_GENERATED_MINIMAL,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    CODE_FIELD_ARGUMENTS_REQUIRED,
    CODE_NO_NEGATIVE_CASES,
    CODE_SELECTION_DEPTH_LIMITED,
    CODE_UNMAPPED_SCALAR,
    CODE_UNSUPPORTED_STREAMING,
    CONTRACT_SUITE_SCHEMA_VERSION,
    NEGATIVE_CASE_SOURCES,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    SUITE_FINDING_CODES,
    ContractCase,
    ContractSuiteManifest,
    ContractSuiteOptions,
    canonical_manifest_bytes,
    compile_contract_suite,
    protocol_adapter_for,
)
from app.contract_suite_graphql import (
    GRAPHQL_REQUEST_PATH,
    GRAPHQL_SCHEMA_PREFIX,
    UNKNOWN_FIELD_NAME,
    graphql_type_text,
)
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.openapi_normalizer import OpenApiNormalizer
from app.schema_instance_validation import validate_json_instance

#: A small schema exercising every shape the adapter handles: a declared example, required and
#: optional arguments, an input object (recursive), an enum, a union, a nested field with a
#: required argument, a custom scalar, a mutation, and a subscription.
SDL = '''
directive @example(value: String) on ARGUMENT_DEFINITION

scalar DateTime

type Query {
  pet(id: ID! @example(value: "pet-1")): Pet
  pets(limit: Int = 10, status: Status, filter: PetFilter): [Pet!]!
  hello: String!
  search(term: String!): SearchResult
}

type Mutation {
  addPet(input: PetInput!): Pet!
}

type Subscription {
  petAdded: Pet
}

enum Status { AVAILABLE SOLD }

input PetInput { name: String! tag: String }
input PetFilter { status: Status and: PetFilter }

union SearchResult = Pet | Owner

type Pet {
  id: ID!
  name: String!
  tag: String
  status: Status
  bornAt: DateTime
  owner: Owner
  friends(first: Int): [Pet]
  photo(size: Int!): String
}

type Owner { name: String pets: [Pet] }
'''

#: The value every resolver hands back, so documents can be executed end to end.
ROOT: Dict[str, Any] = {
    "pet": {"id": "1", "name": "Rex", "tag": None, "status": "SOLD", "bornAt": None,
            "owner": {"name": "Ann", "pets": []}, "friends": []},
    "pets": [],
    "hello": "hi",
    "search": None,
    "addPet": {"id": "2", "name": "Tom", "tag": None, "status": None, "bornAt": None,
               "owner": None, "friends": None},
}


def _api():
    """The canonical model of :data:`SDL`."""
    return GraphQlNormalizer().normalize(build_graphql_schema(SDL))


def _compile(**options: Any) -> ContractSuiteManifest:
    """Compile :data:`SDL` with the given options."""
    return compile_contract_suite(_api(), options=ContractSuiteOptions(**options))


def _cases(manifest: ContractSuiteManifest, key: str) -> List[ContractCase]:
    """The cases compiled for one root field."""
    return [case for case in manifest.cases if case.operation_key == key]


def _sources(manifest: ContractSuiteManifest, key: str) -> List[str]:
    """The sources of one root field's cases, in emission order."""
    return [case.source for case in _cases(manifest, key)]


def _codes(manifest: ContractSuiteManifest, key: str | None = None) -> List[str]:
    """Finding codes, optionally for one operation."""
    return [
        finding.code
        for finding in manifest.findings
        if key is None or finding.operation_key == key
    ]


def _resolve(obj: Any, info: Any, **_: Any) -> Any:
    """Field resolver reading plain dicts, so :data:`ROOT` serves every query."""
    return obj.get(info.field_name) if isinstance(obj, dict) else None


@pytest.fixture(scope="module")
def manifest() -> ContractSuiteManifest:
    """The default-options suite, compiled once."""
    return _compile()


# ---------------------------------------------------------------------------
# The adapter seam
# ---------------------------------------------------------------------------


def test_the_graph_paradigm_has_its_own_adapter() -> None:
    """``graph`` compiles through the GraphQL adapter; ``rest`` through the HTTP one."""
    assert protocol_adapter_for(ApiParadigm.GRAPH).protocol == PROTOCOL_GRAPHQL
    assert protocol_adapter_for(ApiParadigm.REST).protocol == PROTOCOL_HTTP
    # A paradigm with no adapter of its own falls through to HTTP, which reports it.
    assert protocol_adapter_for(ApiParadigm.EVENT).protocol == PROTOCOL_HTTP


def test_the_manifest_and_every_case_carry_the_graphql_protocol(manifest) -> None:
    assert manifest.protocol == PROTOCOL_GRAPHQL
    assert manifest.schema_version == CONTRACT_SUITE_SCHEMA_VERSION
    assert manifest.cases
    for case in manifest.cases:
        assert case.protocol == PROTOCOL_GRAPHQL
        assert case.graphql is not None
        assert case.request.method == "POST"
        assert case.request.path == GRAPHQL_REQUEST_PATH
        # The body is exactly the GraphQL-over-HTTP document the runner posts.
        assert case.request.body == {
            "query": case.graphql.query,
            "variables": case.graphql.variables,
            "operationName": case.graphql.operationName,
        }


def test_every_new_finding_code_is_registered() -> None:
    for code in (CODE_SELECTION_DEPTH_LIMITED, CODE_FIELD_ARGUMENTS_REQUIRED):
        assert code in SUITE_FINDING_CODES
    assert CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD in NEGATIVE_CASE_SOURCES


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_seed_compiles_byte_identical_manifests() -> None:
    first, second = _compile(seed=7), _compile(seed=7)
    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")


def test_a_different_seed_samples_different_arguments() -> None:
    assert _compile(seed=1).digest != _compile(seed=2).digest


# ---------------------------------------------------------------------------
# One set of cases per root field
# ---------------------------------------------------------------------------


def test_one_operation_per_query_and_mutation_root_field(manifest) -> None:
    assert [operation.key for operation in manifest.operations] == [
        "Mutation.addPet",
        "Query.hello",
        "Query.pet",
        "Query.pets",
        "Query.search",
    ]
    for operation in manifest.operations:
        assert operation.http_method == "POST"
        assert operation.case_count == len(_cases(manifest, operation.key))


def test_cases_follow_the_preference_order(manifest) -> None:
    """Declared example first, then generated values, then negatives — as REST cases do."""
    assert _sources(manifest, "Query.pet") == [
        CASE_SOURCE_DECLARED_EXAMPLE,
        CASE_SOURCE_GENERATED_MINIMAL,
        CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
        CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
        CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    ]
    assert _sources(manifest, "Query.pets") == [
        CASE_SOURCE_GENERATED_MINIMAL,
        CASE_SOURCE_GENERATED_FULL,
        CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
        CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    ]


def test_a_declared_example_is_the_only_unsynthetic_case(manifest) -> None:
    declared = _cases(manifest, "Query.pet")[0]
    assert declared.source == CASE_SOURCE_DECLARED_EXAMPLE
    assert declared.synthetic is False
    assert declared.source_detail == "id"
    assert declared.graphql.variables == {"id": "pet-1"}
    others = [case for case in manifest.cases if case is not declared]
    assert all(case.synthetic for case in others)


def test_documents_are_named_operations_with_typed_variables(manifest) -> None:
    case = _cases(manifest, "Query.pet")[0]
    assert case.graphql.operationName == "Query_pet"
    assert case.graphql.operation_type == "query"
    assert case.graphql.field == "pet"
    assert case.graphql.query.startswith("query Query_pet($id: ID!) { pet(id: $id) { ")
    mutation = _cases(manifest, "Mutation.addPet")[0]
    assert mutation.graphql.operation_type == "mutation"
    assert mutation.graphql.query.startswith("mutation Mutation_addPet($input: PetInput!) ")


def test_a_field_with_no_arguments_still_gets_its_call(manifest) -> None:
    cases = _cases(manifest, "Query.hello")
    assert [case.source for case in cases] == [CASE_SOURCE_GENERATED_MINIMAL]
    assert cases[0].graphql.query == "query Query_hello { hello }"
    assert cases[0].graphql.variables == {}
    # A scalar root with no arguments has nothing a request can break — and the suite says so.
    assert CODE_NO_NEGATIVE_CASES in _codes(manifest, "Query.hello")


def test_generated_int_arguments_stay_within_32_bits(manifest) -> None:
    full = next(
        case for case in _cases(manifest, "Query.pets") if case.source == CASE_SOURCE_GENERATED_FULL
    )
    limit = full.graphql.variables["limit"]
    assert isinstance(limit, int)
    assert -(2**31) <= limit <= 2**31 - 1


# ---------------------------------------------------------------------------
# Negative cases are attributed
# ---------------------------------------------------------------------------


def test_negatives_name_the_fault_they_carry(manifest) -> None:
    by_source = {case.source: case for case in _cases(manifest, "Query.pet")}

    missing = by_source[CASE_SOURCE_NEGATIVE_MISSING_PARAMETER]
    assert missing.source_detail == "id"
    assert "$id" not in missing.graphql.query and "id:" not in missing.graphql.query.split("{")[1]

    typed = by_source[CASE_SOURCE_NEGATIVE_PARAMETER_TYPE]
    assert typed.source_detail == "id"
    assert typed.graphql.variables == {"id": True}

    unknown = by_source[CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD]
    assert unknown.source_detail == UNKNOWN_FIELD_NAME
    assert f"{{ {UNKNOWN_FIELD_NAME} " in unknown.graphql.query

    for case in (missing, typed, unknown):
        assert case.expect.outcome == OUTCOME_CLIENT_ERROR
        assert case.expect.status_codes == ["2XX", "4XX"]
        assert case.expect.response_schema_id is None


def test_a_boolean_argument_is_broken_with_a_string() -> None:
    sdl = "type Query { flag(on: Boolean!): String }"
    manifest = compile_contract_suite(GraphQlNormalizer().normalize(build_graphql_schema(sdl)))
    typed = next(
        case for case in manifest.cases if case.source == CASE_SOURCE_NEGATIVE_PARAMETER_TYPE
    )
    assert isinstance(typed.graphql.variables["on"], str)


def test_the_negative_budget_is_honoured() -> None:
    manifest = _compile(max_negative_cases_per_operation=1)
    for operation in manifest.operations:
        negatives = [
            case
            for case in _cases(manifest, operation.key)
            if case.source in NEGATIVE_CASE_SOURCES
        ]
        assert len(negatives) <= 1


def test_negatives_can_be_switched_off() -> None:
    manifest = _compile(include_negative=False)
    assert not [case for case in manifest.cases if case.source in NEGATIVE_CASE_SOURCES]


# ---------------------------------------------------------------------------
# Subscriptions and unsupported shapes are never silently omitted
# ---------------------------------------------------------------------------


def test_subscriptions_are_listed_under_unsupported_with_a_reason(manifest) -> None:
    assert [item.operation_key for item in manifest.unsupported] == ["Subscription.petAdded"]
    item = manifest.unsupported[0]
    assert item.code == CODE_UNSUPPORTED_STREAMING
    assert "subscription" in item.reason
    assert not _cases(manifest, "Subscription.petAdded")
    assert CODE_UNSUPPORTED_STREAMING in _codes(manifest, "Subscription.petAdded")
    assert manifest.counts["operations_skipped"] == 1


def test_a_nested_field_with_a_required_argument_is_left_out_and_reported(manifest) -> None:
    query = _cases(manifest, "Query.pet")[0].graphql.query
    assert "photo" not in query
    # ``friends`` takes an *optional* argument, so it is selected without one.
    assert "friends {" in query
    assert CODE_FIELD_ARGUMENTS_REQUIRED in _codes(manifest, "Query.pet")


def test_a_custom_scalar_is_selected_but_reported_unchecked(manifest) -> None:
    assert "bornAt" in _cases(manifest, "Query.pet")[0].graphql.query
    assert CODE_UNMAPPED_SCALAR in _codes(manifest, "Query.pet")


def test_a_union_selects_its_typename(manifest) -> None:
    case = _cases(manifest, "Query.search")[0]
    assert case.graphql.query.endswith("search(term: $term) { __typename } }")
    schema = manifest.schemas[GRAPHQL_SCHEMA_PREFIX + "Query.search"]
    assert schema["properties"]["search"]["properties"]["__typename"] == {
        "enum": ["Owner", "Pet"]
    }


def test_the_selection_depth_is_bounded_and_reported() -> None:
    manifest = _compile(max_selection_depth=1)
    query = _cases(manifest, "Query.pet")[0].graphql.query
    # Depth 1: only the leaf fields of Pet, no nested objects.
    assert "owner" not in query and "friends" not in query
    assert "id" in query and "name" in query
    assert CODE_SELECTION_DEPTH_LIMITED in _codes(manifest, "Query.pet")


def test_the_operations_filter_takes_graphql_coordinates() -> None:
    manifest = _compile(operations=["Query.hello"])
    assert [operation.key for operation in manifest.operations] == ["Query.hello"]


# ---------------------------------------------------------------------------
# The response contract
# ---------------------------------------------------------------------------


def test_the_data_schema_follows_the_selection_and_graphql_nullability(manifest) -> None:
    case = _cases(manifest, "Query.pet")[0]
    assert case.expect.outcome == OUTCOME_SUCCESS
    assert case.expect.status_codes == ["2XX"]
    assert case.expect.status_declared is False
    schema = manifest.schemas[case.expect.response_schema_id]
    assert case.expect.response_schema_id == GRAPHQL_SCHEMA_PREFIX + "Query.pet"
    assert schema["required"] == ["pet"]
    pet = schema["properties"]["pet"]
    assert pet["type"] == ["object", "null"]  # `pet: Pet` is nullable
    assert pet["additionalProperties"] is False
    assert pet["properties"]["id"] == {"type": "string"}  # `ID!`
    assert pet["properties"]["tag"] == {"type": ["string", "null"]}  # `String`
    assert pet["properties"]["status"] == {"enum": ["AVAILABLE", "SOLD", None]}
    assert set(pet["required"]) == set(pet["properties"])
    pets = manifest.schemas[GRAPHQL_SCHEMA_PREFIX + "Query.pets"]["properties"]["pets"]
    assert pets["type"] == "array"  # `[Pet!]!`
    assert pets["items"]["type"] == "object"


def test_response_schemas_can_be_left_out() -> None:
    manifest = _compile(include_response_schemas=False)
    assert manifest.schemas == {}
    assert all(case.expect.response_schema_id is None for case in manifest.cases)


def test_every_compiled_document_behaves_as_its_expectation_says(manifest) -> None:
    """Execute each case with graphql-core: positives succeed and conform, negatives error."""
    schema = build_graphql_schema(SDL)
    for case in manifest.cases:
        result = graphql_sync(
            schema,
            case.graphql.query,
            root_value=ROOT,
            variable_values=case.graphql.variables,
            operation_name=case.graphql.operationName,
            field_resolver=_resolve,
        )
        if case.expect.outcome == OUTCOME_SUCCESS:
            assert not result.errors, (case.title, result.errors)
            verdict = validate_json_instance(
                manifest.schemas[case.expect.response_schema_id], result.data
            )
            assert verdict.valid is True, (case.title, verdict.findings)
        else:
            assert result.errors, f"{case.operation_key} {case.title} was accepted"


# ---------------------------------------------------------------------------
# REST is unchanged in meaning, and now says what it is
# ---------------------------------------------------------------------------


def test_rest_manifests_declare_the_http_protocol() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    manifest = compile_contract_suite(OpenApiNormalizer().normalize(document))
    assert manifest.protocol == PROTOCOL_HTTP
    assert manifest.unsupported == []
    assert manifest.cases and all(case.protocol == PROTOCOL_HTTP for case in manifest.cases)
    assert all(case.graphql is None for case in manifest.cases)


@pytest.mark.parametrize(
    "ref,text",
    [
        (TypeRef(name="ID", nullable=False), "ID!"),
        (TypeRef(name="String"), "String"),
        (TypeRef(item=TypeRef(name="Pet", nullable=False), nullable=False), "[Pet!]!"),
        (TypeRef(item=TypeRef(item=TypeRef(name="Int"))), "[[Int]]"),
    ],
)
def test_graphql_type_text_reproduces_every_wrapper(ref: TypeRef, text: str) -> None:
    assert graphql_type_text(ref) == text
