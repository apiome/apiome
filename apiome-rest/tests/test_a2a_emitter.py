"""A2A Agent Card emitter — MFX-32.2 (#4296).

Covers :mod:`app.a2a_emitter`, against the issue's acceptance criteria:

* **a valid agent card is emitted for an agent-paradigm source (lossless tier)** — every A2A corpus
  card exports to a card that passes the vendored AgentCard schema and imports back through the
  MFI-18.1 adapter to the same agent descriptor and servers (the stress card differs only by what
  its losses report), and its fidelity report says ``OK`` for every skill;
* **REST/RPC sources emit with documented skill reframing (APPROX)** — an OpenAPI or Protobuf source
  becomes one agent whose skills are its operations (or its tags), each ``APPROX`` in the report and
  an ``a2a-skill-reframed`` loss; the root carries the reframing advisory.

Plus auth (schemes and per-skill requirements), endpoints, placeholders, event / deprecated
operations, multi-agent sources, refusals and the options.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.a2a_agent_card_lint import lint_a2a_agent_card
from app.a2a_agent_card_parser import is_a2a_agent_card
from app.a2a_emitter import (
    AGENT_CARD_FILE,
    LOSS_EVENT_NOT_A_SKILL,
    LOSS_PROVIDER_INCOMPLETE,
    LOSS_REQUIRED_SYNTHESIZED,
    LOSS_SCHEME_INVALID,
    LOSS_SIGNATURES,
    LOSS_SKILL_GROUPED,
    LOSS_SKILL_ID_SYNTHESIZED,
    LOSS_SKILL_REFRAMED,
    LOSS_URL_PLACEHOLDER,
    PLACEHOLDER_URL,
    A2aEmitOptions,
    A2aEmitter,
    agent_card_schema_violations,
)
from app.canonical_model import (
    AgentDescriptor,
    AgentProvider,
    AgentSkill,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, Provenance, coerce_emit_options, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_A2A_CARDS = sorted(path.name for path in (_EXAMPLES / "a2a").glob("*.json"))


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _corpus(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _petstore() -> CanonicalApi:
    return _corpus("openapi/30-openapi-3.0-petstore.yaml", "openapi")


def _emit(api: CanonicalApi, **options: Any) -> Any:
    return A2aEmitter().emit(api, opts=coerce_emit_options(A2aEmitter, options))


def _card(api: CanonicalApi, **options: Any) -> Dict[str, Any]:
    return json.loads(_emit(api, **options).files[0].content)


def _reimport(content: str) -> CanonicalApi:
    source = get_import_source("a2a")
    return source.normalize(source.parse(content))


def _subjects(result: Any) -> set[str]:
    return {loss.subject for loss in result.losses}


def _op(key: str, name: str, *, method: str = "GET", path: str = "/x", tags: list[str] | None = None,
        kind: OperationKind = OperationKind.REQUEST_RESPONSE, deprecated: bool = False,
        description: str | None = None, extras: Dict[str, Any] | None = None,
        streaming: StreamingMode = StreamingMode.NONE, request_types: list[str] | None = None) -> Operation:
    messages = [Message(key=f"{key}#response.200", role=MessageRole.RESPONSE, status_code="200",
                        content_types=["application/json"])]
    if request_types:
        messages.append(Message(key=f"{key}#request", role=MessageRole.REQUEST, content_types=request_types))
    return Operation(key=key, name=name, kind=kind, http_method=method, http_path=path, tags=tags or [],
                     deprecated=deprecated, description=description, extras=extras or {},
                     streaming=streaming, messages=messages)


def _api(*ops: Operation, servers: list[Server] | None = None, extras: Dict[str, Any] | None = None,
         **fields: Any) -> CanonicalApi:
    values: Dict[str, Any] = {"title": "Shop API", "version": "2.0.0", "description": "Sells things."}
    values.update(fields)
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Shop API"),
                        servers=servers if servers is not None else [Server(url="https://shop.example.com/v2")],
                        extras=extras or {},
                        services=[Service(key="shop", name="shop", operations=list(ops))], **values)


# ===========================================================================
# Agent source → lossless card
# ===========================================================================


@pytest.mark.parametrize("name", _A2A_CARDS)
def test_every_a2a_corpus_card_exports_to_a_valid_card(name: str) -> None:
    result = _emit(_corpus(f"a2a/{name}", "a2a"))
    assert [f.path for f in result.files] == [AGENT_CARD_FILE]
    content = result.files[0].content
    assert agent_card_schema_violations(json.loads(content)) == []
    assert is_a2a_agent_card(content)


@pytest.mark.parametrize("name", [n for n in _A2A_CARDS if not n.startswith("04-")])
def test_an_a2a_card_round_trips_losslessly_through_the_importer(name: str) -> None:
    api = _corpus(f"a2a/{name}", "a2a")
    result = _emit(api)
    back = _reimport(result.files[0].content)
    assert back.agents[0].model_dump() == api.agents[0].model_dump()
    assert [s.model_dump() for s in back.servers] == [s.model_dump() for s in api.servers]
    assert [op.model_dump() for op in back.operations()] == [op.model_dump() for op in api.operations()]
    for key in ("preferred_transport", "documentation_url", "icon_url", "protocol_version",
                "supports_authenticated_extended_card", "provider"):
        assert back.extras.get(key) == api.extras.get(key), key
    assert not _subjects(result) - {LOSS_SIGNATURES}


def test_an_a2a_card_is_ok_in_the_fidelity_report() -> None:
    api = _corpus("a2a/02-typical-travel-concierge.json", "a2a")
    report = compute_lossiness_for_emitter(api, A2aEmitter)
    skills = [item for item in report.items if item.construct_key.startswith("Travel Concierge.")]
    assert skills and all(item.kind is LossinessKind.OK for item in skills)
    assert not [item for item in report.items if item.kind is not LossinessKind.OK]


def test_the_stress_card_reports_exactly_what_it_cannot_carry() -> None:
    api = _corpus("a2a/04-stress-edge-cases.json", "a2a")
    result = _emit(api)
    card = json.loads(result.files[0].content)
    assert "kerberos" not in card["securitySchemes"]  # type `negotiate` is not an A2A scheme type
    assert "signatures" not in card
    assert _subjects(result) == {LOSS_SCHEME_INVALID, LOSS_SIGNATURES, LOSS_REQUIRED_SYNTHESIZED}
    back = _reimport(result.files[0].content).agents[0]
    original = api.agents[0]
    kept = [s.name for s in original.security_schemes if s.name != "kerberos"]
    assert [s.name for s in back.security_schemes] == kept
    assert [s.id for s in back.skills] == [s.id for s in original.skills]  # duplicates kept as declared
    report = compute_lossiness_for_emitter(api, A2aEmitter)
    kinds = {item.kind for item in report.items if item.construct_key == ""}
    assert {LossinessKind.DROP, LossinessKind.SYNTH} <= kinds


def _agent_api(**descriptor: Any) -> CanonicalApi:
    values: Dict[str, Any] = {
        "key": "Helper", "name": "Helper", "protocol": "a2a", "skills": [
            AgentSkill(key="Helper.do", id="do", name="Do", description="Does it.", operation_ref="Helper.do")
        ],
    }
    values.update(descriptor)
    op = Operation(key="Helper.do", name="Do", kind=OperationKind.REQUEST_RESPONSE)
    return CanonicalApi(paradigm=ApiParadigm.AGENT, format="a2a", identity=ApiIdentity(name="Helper"),
                        services=[Service(key="Helper", name="Helper", operations=[op])],
                        agents=[AgentDescriptor(**values)])


def test_missing_required_fields_are_synthesized_and_reported() -> None:
    result = _emit(_agent_api())
    card = json.loads(result.files[0].content)
    assert card["description"] == "The Helper agent."
    assert card["url"] == PLACEHOLDER_URL
    assert card["version"] == "0.0.0"
    assert card["protocolVersion"] == "0.3.0"
    assert agent_card_schema_violations(card) == []
    assert {LOSS_REQUIRED_SYNTHESIZED, LOSS_URL_PLACEHOLDER} <= _subjects(result)
    inferred = {r.pointer for r in result.provenance if r.provenance is Provenance.INFERRED}
    assert {"/agent-card.json/url", "/agent-card.json/description", "/agent-card.json/version"} <= inferred


def test_the_url_option_fills_a_missing_endpoint_but_never_overrides_the_source() -> None:
    assert _card(_agent_api(), url="https://helper.example.com/a2a")["url"] == "https://helper.example.com/a2a"
    own = _agent_api(url="https://own.example.com")
    assert _card(own, url="https://other.example.com")["url"] == "https://own.example.com"


def test_a_provider_without_a_url_is_dropped_and_reported() -> None:
    result = _emit(_agent_api(provider=AgentProvider(organization="Acme")))
    assert "provider" not in json.loads(result.files[0].content)
    assert LOSS_PROVIDER_INCOMPLETE in _subjects(result)


def test_an_acp_agent_is_written_as_a2a_and_reported_approx() -> None:
    api = _corpus("acp/02-typical-research-agent.json", "acp")
    result = _emit(api)
    for file in result.files:
        card = json.loads(file.content)
        assert agent_card_schema_violations(card) == []
        assert card["protocolVersion"] == "0.3.0"
    report = compute_lossiness_for_emitter(api, A2aEmitter)
    skills = [item for item in report.items if (item.target_mapping or "").startswith("agent skill → A2A skill")]
    assert skills and all(item.kind is LossinessKind.APPROX for item in skills)


def test_several_agents_write_one_card_each() -> None:
    api = _agent_api()
    second = api.agents[0].model_copy(update={"key": "Other", "name": "Other Agent"})
    api = api.model_copy(update={"agents": [api.agents[0], second]})
    result = _emit(api)
    assert [f.path for f in result.files] == ["helper.agent-card.json", "other-agent.agent-card.json"]


# ===========================================================================
# REST / RPC source → reframed card
# ===========================================================================


def test_a_rest_source_is_reframed_as_one_agent_with_a_skill_per_operation() -> None:
    result = _emit(_petstore())
    card = json.loads(result.files[0].content)
    assert agent_card_schema_violations(card) == []
    assert card["name"] == "Sample Pet Store API (OpenAPI 3.0)"
    assert card["url"] == "https://api.example.com/v1"
    assert card["preferredTransport"] == "HTTP+JSON"
    assert card["protocolVersion"] == "0.3.0"
    skills = {skill["id"]: skill for skill in card["skills"]}
    assert set(skills) == {"listPets", "createPet", "getPetById", "updatePet", "deletePet"}
    assert skills["listPets"]["name"] == "List pets"
    assert skills["createPet"]["inputModes"] == ["application/json", "application/x-www-form-urlencoded"]
    assert all(skill["tags"] for skill in card["skills"])
    reframed = [loss for loss in result.losses if loss.subject == LOSS_SKILL_REFRAMED]
    assert len(reframed) == 5


def test_the_reframed_card_imports_back_with_one_skill_per_operation() -> None:
    api = _petstore()
    content = _emit(api).files[0].content
    back = _reimport(content)
    assert back.paradigm is ApiParadigm.AGENT
    assert sorted(skill.id for skill in back.agents[0].skills) == sorted(op.name for op in api.operations())
    lint = lint_a2a_agent_card(content)
    assert not lint.severity_counts.get("error")


def test_reframed_operations_are_approx_in_the_fidelity_report() -> None:
    api = _petstore()
    report = compute_lossiness_for_emitter(api, A2aEmitter)
    by_key = {item.construct_key: item for item in report.items}
    for operation in api.operations():
        assert by_key[operation.key].kind is LossinessKind.APPROX
        assert by_key[operation.key].target_mapping.startswith("operation → skill")
    root = [item for item in report.items if item.construct_key == ""]
    assert any(item.kind is LossinessKind.APPROX and "reframed as one agent" in item.message for item in root)
    assert all(by_key[type_.key].kind is LossinessKind.DROP for type_ in api.types)


def test_an_rpc_source_is_reframed_too() -> None:
    api = _corpus("protobuf/02-grpc-service.proto", "protobuf")
    card = _card(api)
    assert agent_card_schema_violations(card) == []
    assert len(card["skills"]) == len([op for op in api.operations()])


def test_skills_from_tags_groups_operations() -> None:
    api = _api(_op("a", "listOrders", tags=["orders"]), _op("b", "createOrder", tags=["orders", "write"]),
               _op("c", "listUsers", tags=["users"]), _op("d", "ping"))
    result = _emit(api, skills_from="tags")
    card = json.loads(result.files[0].content)
    assert [(s["id"], s["name"]) for s in card["skills"]] == [
        ("orders", "orders"), ("users", "users"), ("shop", "shop"),
    ]
    assert "listOrders, createOrder" in card["skills"][0]["description"]
    assert len([loss for loss in result.losses if loss.subject == LOSS_SKILL_GROUPED]) == 4
    report = compute_lossiness_for_emitter(api, A2aEmitter, options={"skills_from": "tags"})
    grouped = [item for item in report.items if item.construct_key in {"a", "b", "c", "d"}]
    assert len(grouped) == 4
    assert all(item.kind is LossinessKind.APPROX and "grouped into the tag skill" in item.message for item in grouped)


def test_duplicate_operation_names_get_unique_skill_ids() -> None:
    result = _emit(_api(_op("a", "list"), _op("b", "list")))
    assert [s["id"] for s in json.loads(result.files[0].content)["skills"]] == ["list", "list_2"]
    assert LOSS_SKILL_ID_SYNTHESIZED in _subjects(result)


def test_auth_becomes_security_schemes_and_skill_requirements() -> None:
    api = _api(_op("a", "secret", extras={"security": ["bearer"]}), _op("b", "open"),
               extras={"security_schemes": {"bearer": {"type": "http", "scheme": "bearer"}}})
    card = _card(api)
    assert card["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    skills = {s["id"]: s for s in card["skills"]}
    assert skills["secret"]["security"] == [{"bearer": []}]
    assert "security" not in skills["open"]
    assert agent_card_schema_violations(card) == []


def test_a_scheme_without_a_recorded_stub_gets_one() -> None:
    card = _card(_api(_op("a", "secret", extras={"security": ["apiKey"]})))
    assert card["securitySchemes"]["apiKey"]["type"] == "apiKey"
    assert agent_card_schema_violations(card) == []


def test_extra_servers_become_additional_interfaces() -> None:
    api = _api(_op("a", "list"), servers=[Server(url="https://a.example.com"), Server(url="https://b.example.com")])
    card = _card(api)
    assert card["url"] == "https://a.example.com"
    assert card["additionalInterfaces"] == [
        {"url": "https://a.example.com", "transport": "HTTP+JSON"},
        {"url": "https://b.example.com", "transport": "HTTP+JSON"},
    ]


def test_a_rest_source_without_servers_gets_the_placeholder_or_the_option() -> None:
    api = _api(_op("a", "list"), servers=[])
    result = _emit(api)
    assert json.loads(result.files[0].content)["url"] == PLACEHOLDER_URL
    assert LOSS_URL_PLACEHOLDER in _subjects(result)
    assert _card(api, url="https://agent.shop.example.com")["url"] == "https://agent.shop.example.com"


def test_streaming_sets_the_capability_and_events_are_dropped() -> None:
    api = _api(_op("a", "watch", streaming=StreamingMode.SERVER),
               _op("b", "orderPlaced", kind=OperationKind.PUBLISH))
    result = _emit(api)
    card = json.loads(result.files[0].content)
    assert card["capabilities"]["streaming"] is True
    assert [s["id"] for s in card["skills"]] == ["watch"]
    assert LOSS_EVENT_NOT_A_SKILL in _subjects(result)
    report = compute_lossiness_for_emitter(api, A2aEmitter)
    assert next(item for item in report.items if item.construct_key == "b").kind is LossinessKind.DROP


def test_deprecated_operations_need_include_deprecated() -> None:
    api = _api(_op("a", "current"), _op("b", "legacy", deprecated=True))
    assert [s["id"] for s in _card(api)["skills"]] == ["current"]
    assert [s["id"] for s in _card(api, include_deprecated=True)["skills"]] == ["current", "legacy"]


def test_a_description_is_synthesized_from_the_method_and_path() -> None:
    card = _card(_api(_op("a", "list", method="get", path="/orders"), description=None))
    assert card["skills"][0]["description"] == "Calls GET /orders."
    assert card["description"] == "An agent interface to the Shop API API."


def test_output_is_deterministic() -> None:
    assert _emit(_petstore()).files[0].content == _emit(_petstore()).files[0].content


# ===========================================================================
# Refusals, the schema check and the target card
# ===========================================================================


def test_a_schema_only_source_is_offered_greyed_out_and_refused() -> None:
    api = _corpus("json-schema/03-multiple-defs.json", "json-schema")
    card = next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == "a2a")
    assert card.descriptor.available is False
    assert "agent or at least one operation" in (card.descriptor.unavailable_reason or "")
    with pytest.raises(EmitPreconditionError, match="no operation to make a skill of"):
        _emit(api)


def test_the_schema_check_rejects_an_invalid_card() -> None:
    assert agent_card_schema_violations({"name": "x", "skills": []})
    bad_skill = {"protocolVersion": "0.3.0", "name": "x", "description": "d", "url": "u", "version": "1",
                 "capabilities": {}, "defaultInputModes": [], "defaultOutputModes": [],
                 "skills": [{"id": "s", "name": "S"}]}
    assert any("description" in p for p in agent_card_schema_violations(bad_skill))
    bad_skill["skills"] = [{"id": "s", "name": "S", "description": "d", "tags": []}]
    assert agent_card_schema_violations(bad_skill) == []
    bad_skill["securitySchemes"] = {"k": {"type": "apiKey"}}
    assert agent_card_schema_violations(bad_skill)


@pytest.mark.parametrize("options", [{"skills_from": "paths"}, {"include_deprecated": "maybe"}])
def test_invalid_options_are_rejected(options: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        A2aEmitOptions(**options)
    with pytest.raises(Exception):
        coerce_emit_options(A2aEmitter, options)


def test_the_card_offers_the_target_for_rest_and_agent_sources() -> None:
    for api in (_petstore(), _corpus("a2a/01-minimal-echo-agent.json", "a2a")):
        card = next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == "a2a")
        assert card.descriptor.available is True
        assert card.descriptor.paradigm == "agent"
    assert set(card.options_schema["properties"]) == {"skills_from", "url", "include_deprecated"}
