"""GraphQL Federation subgraph output mode — MFX-13.6 (#4344).

Covers :mod:`app.graphql_federation_subgraph` and the GraphQL emitter's ``federation`` option:

* entity keys — a source ``@key`` is kept; otherwise the declared primary key, the ``id`` field or
  the one ``ID`` field is synthesized, and a type with none stays a value type;
* the subgraph SDL — ``extend schema @link`` header with exactly the Federation directives used,
  no Federation / ``join`` machinery, re-builds through the GraphQL parser;
* composition — the emitted subgraph composes with a second hand-written subgraph on the fixtures
  (pure checks always; the bundled ``rover`` when it is installed);
* reporting — each synthesized ``@key`` is an ``inferred`` emit loss, an inferred provenance note and
  a ``SYNTH`` verdict in the fidelity preview;
* the ``rover supergraph compose`` toolchain check stages a ``supergraph.yaml`` for the export.

Fixtures live in ``tests/fixtures/graphql_federation_subgraph/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from graphql import parse

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind, Provenance
from app.export_tool_checks import ToolCheckStatus, run_tool_check, tool_check_command
from app.fidelity_rulepack import FidelityVerdict
from app.graphql_emitter import GraphQlEmitOptions, GraphQlEmitter, GraphQlFidelityRulePack
from app.graphql_federation import (
    SubgraphRef,
    check_composition,
    compose_subgraphs_sync,
    document_federation_role,
)
from app.graphql_federation_subgraph import (
    FEDERATION_LINK_URL,
    KeyBasis,
    entity_key_for,
    entity_keys,
    to_subgraph_sdl,
    with_federation_definitions,
)
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.lossiness import LossinessKind
from app.openapi_normalizer import OpenApiNormalizer
from app.toolchain_runner import ToolRunResult, is_tool_available

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "graphql_federation_subgraph"

_SUPERGRAPH_SDL = '''
schema @link(url: "https://specs.apollo.dev/link/v1.0")
  @link(url: "https://specs.apollo.dev/join/v0.3", for: EXECUTION) {
  query: Query
}

directive @join__field(graph: join__Graph, requires: join__FieldSet, provides: join__FieldSet,
  type: String, external: Boolean, override: String, usedOverridden: Boolean
) repeatable on FIELD_DEFINITION | INPUT_FIELD_DEFINITION

directive @join__graph(name: String!, url: String!) on ENUM_VALUE

directive @join__type(graph: join__Graph!, key: join__FieldSet, extension: Boolean! = false,
  resolvable: Boolean! = true, isInterfaceObject: Boolean! = false
) repeatable on OBJECT | INTERFACE | UNION | ENUM | INPUT_OBJECT | SCALAR

directive @link(url: String, as: String, for: link__Purpose, import: [link__Import]) repeatable on SCHEMA

scalar join__FieldSet

scalar link__Import

enum link__Purpose {
  SECURITY
  EXECUTION
}

enum join__Graph {
  PRODUCTS @join__graph(name: "products", url: "http://products.local/graphql")
}

type Query @join__type(graph: PRODUCTS) {
  topProducts: [Product] @join__field(graph: PRODUCTS)
}

type Product @join__type(graph: PRODUCTS, key: "id") {
  id: ID!
  name: String! @join__field(graph: PRODUCTS)
}
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _inventory_api() -> CanonicalApi:
    """The OpenAPI inventory fixture as a canonical model (Product has an ``id``; Warehouse none)."""
    return OpenApiNormalizer().normalize(json.loads(_fixture("inventory.openapi.json")), include_raw=False)


def _graphql_api(sdl: str) -> CanonicalApi:
    return GraphQlNormalizer().normalize(build_graphql_schema(sdl), include_raw=False)


def _emit(api: CanonicalApi, *, federation: bool = True):
    return GraphQlEmitter().emit(api, opts=GraphQlEmitOptions(federation=federation))


def _sdl(api: CanonicalApi, *, federation: bool = True) -> str:
    return _emit(api, federation=federation).files[0].content


def _record(name: str, *fields: CanonicalField, extras: Optional[Dict[str, Any]] = None) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields), extras=extras or {})


def _field(owner: str, name: str, type_name: Optional[str] = "String", *, nullable: bool = True,
           item: Optional[TypeRef] = None) -> CanonicalField:
    ref = TypeRef(item=item, nullable=nullable) if item is not None else TypeRef(name=type_name, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref)


def _api(*types: Type) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="test",
        identity=ApiIdentity(name="Test"),
        types=list(types),
    )


def _served(*types: Type) -> CanonicalApi:
    """A graph model whose ``Query.items`` field returns the first type (so it is printed)."""
    query = Service(
        key="Query",
        name="Query",
        operations=[
            Operation(
                key="Query.items",
                name="items",
                kind=OperationKind.QUERY,
                messages=[
                    Message(key="Query.items#response", role=MessageRole.RESPONSE,
                            payload=TypeRef(name=types[0].key)),
                ],
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Served"),
        services=[query],
        types=list(types),
    )


def _key_of(type_: Type, *others: Type):
    by_key = {t.key: t for t in (type_, *others)}
    return entity_key_for(type_, by_key)


# ---------------------------------------------------------------------------
# Entity keys
# ---------------------------------------------------------------------------


class TestEntityKeys:
    def test_id_field_is_synthesized(self) -> None:
        key = _key_of(_record("Pet", _field("Pet", "id"), _field("Pet", "name")))
        assert key is not None and key.basis is KeyBasis.ID_FIELD
        assert key.fields == ("id",) and key.synthesized

    def test_id_field_match_ignores_case(self) -> None:
        key = _key_of(_record("Pet", _field("Pet", "ID", "Int")))
        assert key is not None and key.fields == ("ID",)

    def test_declared_primary_key_wins_over_id(self) -> None:
        record = _record(
            "OrderLine",
            _field("OrderLine", "id"),
            _field("OrderLine", "order_id", "Int", nullable=False),
            _field("OrderLine", "line_no", "Int", nullable=False),
            extras={"sql_key": {"primary_key": {"columns": ["order_id", "line_no"]}}},
        )
        key = _key_of(record)
        assert key is not None and key.basis is KeyBasis.DECLARED
        assert key.fields == ("order_id", "line_no")
        assert key.describe() == "its declared primary key (order_id, line_no)"

    def test_declared_key_naming_a_missing_field_falls_back(self) -> None:
        record = _record("T", _field("T", "id"), extras={"sql_key": {"primary_key": {"columns": ["gone"]}}})
        key = _key_of(record)
        assert key is not None and key.basis is KeyBasis.ID_FIELD

    def test_single_id_scalar_field_is_synthesized(self) -> None:
        key = _key_of(_record("Sku", _field("Sku", "code", "ID", nullable=False), _field("Sku", "label")))
        assert key is not None and key.basis is KeyBasis.ID_TYPE and key.fields == ("code",)

    def test_two_id_scalar_fields_are_ambiguous(self) -> None:
        record = _record("Edge", _field("Edge", "from", "ID"), _field("Edge", "to", "ID"))
        assert _key_of(record) is None

    def test_type_without_identity_stays_a_value_type(self) -> None:
        assert _key_of(_record("Money", _field("Money", "amount", "Float"))) is None

    def test_list_and_object_fields_cannot_key(self) -> None:
        other = _record("Other", _field("Other", "x"))
        listed = _record("L", _field("L", "id", item=TypeRef(name="String")))
        objected = _record("O", _field("O", "id", "Other"))
        assert _key_of(listed) is None
        assert _key_of(objected, other) is None

    def test_enum_and_alias_to_scalar_can_key(self) -> None:
        status = Type(key="Code", name="Code", kind=TypeKind.ENUM)
        alias = Type(key="Uuid", name="Uuid", kind=TypeKind.ALIAS, aliased=TypeRef(name="String"))
        assert _key_of(_record("A", _field("A", "id", "Code")), status) is not None
        assert _key_of(_record("B", _field("B", "id", "Uuid")), alias) is not None

    def test_source_key_is_kept_not_synthesized(self) -> None:
        record = _record("User", _field("User", "id"), extras={"directives": ['@key(fields: "email")']})
        key = _key_of(record)
        assert key is not None and key.basis is KeyBasis.SOURCE and not key.synthesized

    def test_inputs_interfaces_roots_and_machinery_are_never_entities(self) -> None:
        for record in (
            _record("PetInput", _field("PetInput", "id"), extras={"graphql_type": "input"}),
            _record("Node", _field("Node", "id"), extras={"graphql_type": "interface"}),
            _record("Query", _field("Query", "id")),
            _record("join__Thing", _field("join__Thing", "id")),
        ):
            assert _key_of(record) is None, record.name

    def test_entity_keys_are_in_type_key_order(self) -> None:
        api = _api(_record("Zed", _field("Zed", "id")), _record("Alpha", _field("Alpha", "id")))
        assert [key.type_key for key in entity_keys(api)] == ["Alpha", "Zed"]


# ---------------------------------------------------------------------------
# Subgraph SDL
# ---------------------------------------------------------------------------


class TestSubgraphSdl:
    def test_rest_source_becomes_subgraph_sdl(self) -> None:
        sdl = _sdl(_inventory_api())
        assert sdl.startswith(f'extend schema @link(url: "{FEDERATION_LINK_URL}", import: ["@key"])')
        assert 'type Product @key(fields: "id")' in sdl
        assert "type Warehouse {" in sdl  # no identity field: a value type
        assert "directive @" not in sdl and "federation__" not in sdl and "link__" not in sdl
        assert document_federation_role(parse(sdl)) == "subgraph"
        build_graphql_schema(sdl)

    def test_option_off_writes_plain_sdl(self) -> None:
        sdl = _sdl(_inventory_api(), federation=False)
        assert "@link" not in sdl and "@key" not in sdl

    def test_emission_is_deterministic(self) -> None:
        api = _inventory_api()
        assert _sdl(api) == _sdl(api)

    def test_source_subgraph_keeps_its_keys_and_imports(self) -> None:
        sdl = _sdl(_graphql_api(_fixture("accounts.graphql")))
        assert 'type User @key(fields: "email")' in sdl
        assert "displayName: String @shareable" in sdl
        assert 'type Team @key(fields: "id")' in sdl  # synthesized beside the source key
        assert 'import: ["@key", "@shareable"]' in sdl
        assert sdl.count("@link(") == 1 and FEDERATION_LINK_URL in sdl
        assert "directive @key" not in sdl and "scalar federation__FieldSet" not in sdl
        build_graphql_schema(sdl)

    def test_supergraph_source_drops_join_machinery(self) -> None:
        sdl = _sdl(_graphql_api(_SUPERGRAPH_SDL))
        assert "join__" not in sdl and "link/v1.0" not in sdl
        assert 'type Product @key(fields: "id")' in sdl
        build_graphql_schema(sdl)

    def test_no_entities_still_links_federation_and_says_so(self) -> None:
        result = _emit(_graphql_api("type Query { hello: String }"))
        sdl = result.files[0].content
        assert sdl.startswith(f'extend schema @link(url: "{FEDERATION_LINK_URL}")')
        assert any(loss.subject == "federation-no-entities" and loss.kind is LossKind.NA for loss in result.losses)

    def test_renamed_key_field_uses_the_emitted_name(self) -> None:
        odd = _record(
            "Odd",
            _field("Odd", "order-id", "Int", nullable=False),
            extras={"sql_key": {"primary_key": {"columns": ["order-id"]}}},
        )
        sdl = _sdl(_served(odd))
        assert 'type Odd @key(fields: "order_id")' in sdl
        build_graphql_schema(sdl)

    def test_unreachable_types_get_no_key_and_no_report(self) -> None:
        result = _emit(_api(_record("Lonely", _field("Lonely", "id"))))
        assert "Lonely" not in result.files[0].content
        assert not [loss for loss in result.losses if loss.subject == "federation-key-synthesized"]
        assert any(loss.subject == "federation-no-entities" for loss in result.losses)

    def test_to_subgraph_sdl_keeps_an_existing_key(self) -> None:
        sdl = with_federation_definitions('type Query { a: A }\ntype A @key(fields: "b") { b: ID c: ID }')
        out = to_subgraph_sdl(sdl, {"A": ["c"], "Missing": ["x"]})
        assert '@key(fields: "b")' in out.sdl and '@key(fields: "c")' not in out.sdl
        assert out.imports == ("key",) and out.keyed == () and out.entities == ("A",)

    def test_with_federation_definitions_adds_only_what_is_missing(self) -> None:
        sdl = with_federation_definitions("directive @key(fields: String!) on OBJECT\ntype Query { a: Int }")
        assert sdl.count("directive @key") == 1 and "directive @shareable" in sdl


# ---------------------------------------------------------------------------
# Composition on the fixtures
# ---------------------------------------------------------------------------


class TestComposition:
    def test_rest_subgraph_composes_with_a_second_subgraph(self) -> None:
        subgraphs = {"inventory": _sdl(_inventory_api()), "reviews": _fixture("reviews.graphql")}
        assert check_composition(subgraphs) == []

    def test_re_emitted_source_subgraph_composes(self) -> None:
        subgraphs = {"accounts": _sdl(_graphql_api(_fixture("accounts.graphql")))}
        assert check_composition(subgraphs) == []

    @pytest.mark.skipif(not is_tool_available("rover"), reason="rover is not installed")
    def test_rover_composes_the_fixtures(self) -> None:
        subgraphs = {
            "inventory": _sdl(_inventory_api()),
            "reviews": _fixture("reviews.graphql"),
            "accounts": _sdl(_graphql_api(_fixture("accounts.graphql"))),
        }
        findings = compose_subgraphs_sync([SubgraphRef(name=name) for name in subgraphs], subgraphs)
        if findings is None:
            pytest.skip("rover gave no verdict (its composition plugin is unavailable offline)")
        assert findings == []


# ---------------------------------------------------------------------------
# Reporting: losses, provenance, SYNTH verdicts
# ---------------------------------------------------------------------------


def _pack(options: Dict[str, Any]) -> GraphQlFidelityRulePack:
    pack = GraphQlFidelityRulePack(GraphQlEmitter.capability_profile(), "GraphQL SDL")
    pack.apply_options(options)
    return pack


def _synth_items(report) -> List[Any]:
    return [item for item in report.items if item.kind is LossinessKind.SYNTH]


class TestReporting:
    def test_synthesized_key_is_an_inferred_loss_and_provenance(self) -> None:
        result = _emit(_inventory_api())
        losses = [loss for loss in result.losses if loss.subject == "federation-key-synthesized"]
        assert [(loss.kind, loss.pointer) for loss in losses] == [(LossKind.INFERRED, "Product")]
        assert "its `id` field" in losses[0].detail and '@key(fields: "id")' in losses[0].detail
        notes = [r for r in result.provenance if r.pointer == "/types/Product/@key"]
        assert notes and notes[0].provenance is Provenance.INFERRED

    def test_source_keys_are_not_reported_as_synthesized(self) -> None:
        result = _emit(_graphql_api(_fixture("accounts.graphql")))
        subjects = [(loss.subject, loss.pointer) for loss in result.losses]
        assert ("federation-key-synthesized", "Team") in subjects
        assert ("federation-key-synthesized", "User") not in subjects

    def test_preview_reports_synthesized_keys_as_synth(self) -> None:
        report = _pack({"federation": True}).evaluate(_inventory_api())
        items = _synth_items(report)
        assert [item.construct_key for item in items] == ["Product"]
        assert items[0].target_mapping == 'identity → @key(fields: "id")'

    def test_preview_without_federation_has_no_key_synth(self) -> None:
        assert _synth_items(_pack({}).evaluate(_inventory_api())) == []

    def test_preview_matches_the_emit(self) -> None:
        api = _graphql_api(_fixture("accounts.graphql"))
        predicted = sorted(item.construct_key for item in _synth_items(_pack({"federation": True}).evaluate(api)))
        emitted = sorted(
            loss.pointer for loss in _emit(api).losses if loss.subject == "federation-key-synthesized"
        )
        assert predicted == emitted == ["Team"]

    def test_invalid_options_fall_back_to_the_defaults(self) -> None:
        assert _synth_items(_pack({"federation": "not-a-bool"}).evaluate(_inventory_api())) == []

    def test_synth_helper_is_the_verdict_kind(self) -> None:
        assert FidelityVerdict.synth(message="x").kind is LossinessKind.SYNTH


# ---------------------------------------------------------------------------
# rover supergraph compose toolchain check
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Records the staged files and argv, then exits 0."""

    def __init__(self) -> None:
        self.staged: Dict[str, str] = {}
        self.calls: List[Dict[str, Any]] = []

    async def run_spec(self, spec, args, *, timeout=None, cwd=None, extra_env=None, on_output=None):
        scratch = Path(cwd)
        self.staged = {str(p.relative_to(scratch)): p.read_text() for p in scratch.rglob("*") if p.is_file()}
        self.calls.append({"spec": spec, "args": list(args), "extra_env": extra_env})
        return ToolRunResult(key=spec.key, argv=[spec.executable, *args], exit_code=0, stdout="", stderr="",
                             duration_ms=5)


class TestRoverCheck:
    def test_graphql_target_declares_the_check(self) -> None:
        tools = GraphQlEmitter.descriptor().test_tools
        rover = [tool for tool in tools if tool.params.get("tool") == "rover"]
        assert [(tool.params["check"], tool.label) for tool in rover] == [("compose", "rover supergraph compose")]

    @pytest.mark.asyncio
    async def test_check_stages_a_supergraph_config(self) -> None:
        runner = _FakeRunner()
        files = {"schema.graphql": _sdl(_inventory_api())}
        result = await run_tool_check(tool_check_command("rover", "compose"), files,
                                      label="rover supergraph compose", on_event=lambda _e: None, runner=runner)
        assert result.status is ToolCheckStatus.PASSED
        call = runner.calls[0]
        assert call["args"] == ["supergraph", "compose", "--config", "supergraph.yaml", "--elv2-license", "accept"]
        assert call["extra_env"]["APOLLO_TELEMETRY_DISABLED"] == "1"
        config = runner.staged["supergraph.yaml"]
        assert "federation_version: =2.9.3" in config
        assert "  schema:\n" in config and "      file: ./schema.graphql" in config

    @pytest.mark.asyncio
    async def test_an_artifact_supergraph_config_is_kept(self) -> None:
        runner = _FakeRunner()
        own = "federation_version: =2.9.3\nsubgraphs: {}\n"
        files = {"schema.graphql": "type Query { a: Int }\n", "supergraph.yaml": own}
        await run_tool_check(tool_check_command("rover", "compose"), files,
                             label="rover supergraph compose", on_event=lambda _e: None, runner=runner)
        assert runner.staged["supergraph.yaml"] == own
