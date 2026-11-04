"""Agent-interface fidelity packs — MFX-32.4 (#4298).

Covers :mod:`app.agent_interface_fidelity` and the rules it adds to the MCP (MFX-32.1) and A2A
(MFX-32.2) fidelity packs, against the issue's acceptance criteria:

* **REST → MCP enumerates APPROX / DROP / SYNTH items with reasons** — the HTTP binding is written
  into the tool description (APPROX), auth schemes beyond bearer / OAuth 2 are APPROX or DROP,
  event and streaming operations and channels are DROP (with the SSE note for a server stream),
  constraint keywords survive (OK), and names and grouping decisions are SYNTH;
* **a 500-operation source triggers the grouping guard advisory** — a critical item, so the MFX-3.3
  transcoding guard classifies the export ``severe`` and requires confirmation; splitting the
  surface (per-service grouping, tag skills) clears it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.a2a_emitter import A2aEmitter
from app.agent_interface_fidelity import (
    GROUPING_GUARD_MAPPING,
    MAX_AGENT_SURFACE,
    NEAR_EMPTY_MAPPING,
    auth_scheme_verdicts,
    classify_auth_scheme,
    constraints_verdict,
    declared_auth_schemes,
    grouping_guard_verdicts,
    http_binding_note,
    streaming_drop_reason,
)
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import coerce_emit_options, load_builtin_emitters
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity, LossItem
from app.mcp_emitter import McpEmitter
from app.transcoding_guards import TranscodeGuardError, TranscodeVerdict, classify_transcode, enforce_transcode_guard


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


# ===========================================================================
# Fixtures
# ===========================================================================

#: The auth schemes of the REST fixture, as an OpenAPI document declares them.
_SCHEMES: Dict[str, Dict[str, Any]] = {
    "bearerAuth": {"type": "http", "scheme": "bearer"},
    "oauth": {"type": "oauth2", "flows": {"authorizationCode": {"authorizationUrl": "https://a", "tokenUrl": "https://t"}}},
    "legacyOauth": {"type": "oauth2", "flows": {"implicit": {"authorizationUrl": "https://a"}}},
    "oidc": {"type": "openIdConnect", "openIdConnectUrl": "https://id/.well-known/openid-configuration"},
    "key": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    "basicAuth": {"type": "http", "scheme": "basic"},
    "session": {"type": "apiKey", "in": "cookie", "name": "sid"},
    "mtls": {"type": "mutualTLS"},
}


def _op(key: str, name: str, **fields: Any) -> Operation:
    """A REST request/response operation with a 200 response unless ``messages`` is given."""
    method, _, path = key.partition(" ")
    fields.setdefault("messages", [Message(key=f"{key}#response.200", role=MessageRole.RESPONSE, status_code="200")])
    fields.setdefault("kind", OperationKind.REQUEST_RESPONSE)
    return Operation(key=key, name=name, http_method=method, http_path=path, **fields)


def _rest_api() -> CanonicalApi:
    """A REST API that exercises every MFX-32.4 rule once."""
    pets = Service(key="pets", name="pets", operations=[
        _op("GET /pets/{id}", "getPet", extras={"operationId": "getPet"}, messages=[
            Message(key="GET /pets/{id}#response.200", role=MessageRole.RESPONSE, status_code="200",
                    headers=[CanonicalField(key="h.rate", name="X-Rate-Limit", type=TypeRef(name="string"))]),
            Message(key="GET /pets/{id}#response.404", role=MessageRole.ERROR, status_code="404"),
        ]),
        _op("GET /pets/feed", "petFeed", extras={"operationId": "petFeed"}, streaming=StreamingMode.SERVER),
        _op("POST /pets/upload", "uploadPets", extras={"operationId": "uploadPets"}, streaming=StreamingMode.CLIENT),
        _op("DELETE /pets", "purgePets", extras={"operationId": "purgePets"}, deprecated=True),
    ])
    events = Service(key="events", name="events", operations=[
        Operation(key="petAdopted.publish", name="petAdopted", kind=OperationKind.PUBLISH, channel_ref="pet/adopted"),
    ])
    misc = Service(key="misc", name="misc", operations=[_op("GET /health", "get health")])
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pet Store"),
        title="Pet Store",
        version="1.0.0",
        servers=[Server(url="https://api.example.com")],
        services=[pets, events, misc],
        channels=[Channel(key="pet/adopted", address="pet/adopted")],
        types=[
            Type(key="Pet", name="Pet", kind=TypeKind.RECORD, fields=[
                CanonicalField(key="Pet.age", name="age", type=TypeRef(name="integer"),
                               constraints=Constraints(minimum=0, maximum=40)),
                CanonicalField(key="Pet.name", name="name", type=TypeRef(name="string")),
            ]),
            Type(key="Tag", name="Tag", kind=TypeKind.SCALAR, constraints=Constraints(pattern="^[a-z]+$")),
        ],
        raw={"openapi": "3.1.0", "components": {"securitySchemes": _SCHEMES}},
    )


def _big_api(operations: int = 500, *, services: int = 1, tags: int = 0) -> CanonicalApi:
    """A REST API of ``operations`` GETs spread over ``services`` services (and ``tags`` tags)."""
    groups: List[Service] = []
    for s in range(services):
        ops = [
            _op(f"GET /s{s}/r{i}", f"getS{s}R{i}", extras={"operationId": f"getS{s}R{i}"},
                tags=[f"t{i % tags}"] if tags else [])
            for i in range(operations // services)
        ]
        groups.append(Service(key=f"svc{s}", name=f"svc{s}", operations=ops))
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="big"),
                        title="Big", version="1.0.0", services=groups)


def _items(report: LossinessReport, **match: Any) -> List[LossItem]:
    """The report items whose attributes equal every ``match`` value."""
    return [item for item in report.items if all(getattr(item, k) == v for k, v in match.items())]


def _one(report: LossinessReport, key: str, needle: str) -> LossItem:
    """The single item under ``key`` whose message contains ``needle``."""
    found = [item for item in report.items if item.construct_key == key and needle in item.message]
    assert len(found) == 1, (key, needle, [i.message for i in report.items if i.construct_key == key])
    return found[0]


# ===========================================================================
# HTTP semantics → description text
# ===========================================================================


def test_the_http_binding_note_names_the_verb_path_statuses_and_response_headers() -> None:
    api = _rest_api()
    get_pet = api.operations()[0]
    assert http_binding_note(get_pet) == (
        "HTTP: GET /pets/{id} — returns 200; errors 404; response headers X-Rate-Limit."
    )


def test_an_operation_without_an_http_binding_has_no_note() -> None:
    rpc = Operation(key="acme.Pets.Get", name="Get", kind=OperationKind.REQUEST_RESPONSE)
    assert http_binding_note(rpc) is None
    bare = Operation(key="GET /x", name="x", kind=OperationKind.REQUEST_RESPONSE, http_method="get", http_path="/x")
    assert http_binding_note(bare) == "HTTP: GET /x."


def test_the_emitted_tool_description_ends_with_the_http_binding() -> None:
    descriptor = json.loads(McpEmitter().emit(_rest_api()).files[0].content)
    tools = {tool["name"]: tool for tool in descriptor["tools"]}
    assert tools["getPet"]["description"].endswith(
        "HTTP: GET /pets/{id} — returns 200; errors 404; response headers X-Rate-Limit."
    )
    assert list(tools["getPet"])[:3] == ["name", "description", "inputSchema"]


def test_a_tool_without_documentation_is_described_by_its_binding_alone() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="x"),
                       services=[Service(key="s", name="s", operations=[
                           Operation(key="GET /x", name="getX", kind=OperationKind.REQUEST_RESPONSE,
                                     http_method="GET", http_path="/x", extras={"operationId": "getX"})])])
    descriptor = json.loads(McpEmitter().emit(api).files[0].content)
    assert descriptor["tools"][0]["description"] == "HTTP: GET /x."


# ===========================================================================
# REST → MCP enumerates APPROX / DROP / SYNTH with reasons
# ===========================================================================


@pytest.fixture(scope="module")
def rest_report() -> LossinessReport:
    return compute_lossiness_for_emitter(_rest_api(), McpEmitter)


def test_rest_to_mcp_reports_every_kind_with_a_reason(rest_report: LossinessReport) -> None:
    for kind in (LossinessKind.APPROX, LossinessKind.DROP, LossinessKind.SYNTH):
        items = _items(rest_report, kind=kind)
        assert items, f"no {kind.value} item"
        assert all(item.message.strip() for item in items)


def test_the_http_binding_is_approx_as_description_text(rest_report: LossinessReport) -> None:
    item = _one(rest_report, "GET /pets/{id}", "HTTP fields")
    assert item.kind is LossinessKind.APPROX
    assert item.target_mapping == "HTTP binding → tool description text"
    assert "GET /pets/{id} — returns 200; errors 404; response headers X-Rate-Limit" in item.message
    # A dropped operation has no tool, so no binding note.
    binding = "HTTP binding → tool description text"
    assert not _items(rest_report, construct_key="GET /pets/feed", target_mapping=binding)


@pytest.mark.parametrize("name, kind, needle", [
    ("bearerAuth", LossinessKind.OK, "bearer token"),
    ("oauth", LossinessKind.OK, "OAuth 2.1"),
    ("legacyOauth", LossinessKind.APPROX, "implicit"),
    ("oidc", LossinessKind.APPROX, "OpenID Connect"),
    ("key", LossinessKind.APPROX, "API key"),
    ("basicAuth", LossinessKind.APPROX, "basic credentials"),
    ("session", LossinessKind.DROP, "cookie"),
    ("mtls", LossinessKind.DROP, "client certificate"),
])
def test_each_auth_scheme_is_classified_against_mcp_authorization(
    rest_report: LossinessReport, name: str, kind: LossinessKind, needle: str
) -> None:
    item = _one(rest_report, "", f"auth scheme {name!r}")
    assert item.kind is kind
    assert needle in item.message


def test_streaming_and_event_operations_are_dropped_with_their_reason(rest_report: LossinessReport) -> None:
    feed = _one(rest_report, "GET /pets/feed", "dropped")
    assert feed.kind is LossinessKind.DROP and "SSE" in feed.message
    upload = _one(rest_report, "POST /pets/upload", "dropped")
    assert upload.kind is LossinessKind.DROP and "client-streaming" in upload.message
    event = _one(rest_report, "petAdopted.publish", "dropped")
    assert event.kind is LossinessKind.DROP and "event flow" in event.message
    channel = _one(rest_report, "pet/adopted", "dropped")
    assert channel.kind is LossinessKind.DROP


def test_a_deprecated_operation_is_dropped_unless_included() -> None:
    report = compute_lossiness_for_emitter(_rest_api(), McpEmitter)
    assert _one(report, "DELETE /pets", "include_deprecated").kind is LossinessKind.DROP
    included = compute_lossiness_for_emitter(_rest_api(), McpEmitter, options={"include_deprecated": True})
    assert not _items(included, construct_key="DELETE /pets", kind=LossinessKind.DROP)


def test_constraint_keywords_survive_as_json_schema(rest_report: LossinessReport) -> None:
    field = _one(rest_report, "Pet.age", "constraint keyword")
    assert field.kind is LossinessKind.OK and "maximum, minimum" in field.message
    scalar = _one(rest_report, "Tag", "constraint keyword")
    assert scalar.kind is LossinessKind.OK and "pattern" in scalar.message
    assert not _items(rest_report, construct_key="Pet.name", target_mapping="constraints → JSON Schema keywords")


def test_names_and_grouping_decisions_are_synth(rest_report: LossinessReport) -> None:
    server = _one(rest_report, "", "server name")
    assert server.kind is LossinessKind.SYNTH and "'pet-store'" in server.message
    grouping = _one(rest_report, "", "grouping=single")
    assert grouping.kind is LossinessKind.SYNTH
    assert _one(rest_report, "GET /health", "synthesized").kind is LossinessKind.SYNTH


def test_per_service_grouping_reports_each_descriptor_as_synth() -> None:
    report = compute_lossiness_for_emitter(_rest_api(), McpEmitter, options={"grouping": "per-service"})
    mappings = {item.target_mapping for item in _items(report, construct_key="", kind=LossinessKind.SYNTH)}
    assert "service → descriptor pet-store-pets" in mappings
    assert "service → descriptor pet-store-misc" in mappings
    assert not _items(report, construct_key="", target_mapping="services → descriptor pet-store")


def test_the_servers_are_still_dropped(rest_report: LossinessReport) -> None:
    assert _items(rest_report, construct_key="", target_mapping="servers → dropped")


# ===========================================================================
# The grouping guard
# ===========================================================================


def test_a_500_operation_source_triggers_the_mcp_grouping_guard() -> None:
    api = _big_api(500)
    report = compute_lossiness_for_emitter(api, McpEmitter)
    [advisory] = _items(report, target_mapping=GROUPING_GUARD_MAPPING)
    assert advisory.kind is LossinessKind.APPROX
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert "500 tools" in advisory.message and str(MAX_AGENT_SURFACE) in advisory.message

    guard = classify_transcode(api, McpEmitter, report=report)
    assert guard.verdict is TranscodeVerdict.SEVERE
    assert guard.requires_confirmation
    assert advisory.message in guard.reasons  # a root item is listed without a "<key>:" prefix
    with pytest.raises(TranscodeGuardError):
        enforce_transcode_guard(guard, confirmed=False)
    assert enforce_transcode_guard(guard, confirmed=True) is guard


def test_a_500_operation_source_triggers_the_a2a_grouping_guard() -> None:
    report = compute_lossiness_for_emitter(_big_api(500), A2aEmitter)
    [advisory] = _items(report, target_mapping=GROUPING_GUARD_MAPPING)
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert "500 skills" in advisory.message and "skills_from=tags" in advisory.message


def test_splitting_the_surface_clears_the_guard() -> None:
    api = _big_api(500, services=5, tags=10)
    single = compute_lossiness_for_emitter(api, McpEmitter)
    assert "grouping=per-service" in _items(single, target_mapping=GROUPING_GUARD_MAPPING)[0].message
    per_service = compute_lossiness_for_emitter(api, McpEmitter, options={"grouping": "per-service"})
    assert not _items(per_service, target_mapping=GROUPING_GUARD_MAPPING)
    tags = compute_lossiness_for_emitter(api, A2aEmitter, options={"skills_from": "tags"})
    assert not _items(tags, target_mapping=GROUPING_GUARD_MAPPING)
    assert not _items(tags, target_mapping=NEAR_EMPTY_MAPPING)  # 10 skills cover all 500 operations


def test_a_single_service_api_is_told_to_curate_rather_than_group() -> None:
    report = compute_lossiness_for_emitter(_big_api(500), McpEmitter)
    assert "grouping=per-service" not in _items(report, target_mapping=GROUPING_GUARD_MAPPING)[0].message


def test_the_guard_threshold_is_inclusive() -> None:
    at = compute_lossiness_for_emitter(_big_api(MAX_AGENT_SURFACE), McpEmitter)
    assert not _items(at, target_mapping=GROUPING_GUARD_MAPPING)
    over = compute_lossiness_for_emitter(_big_api(MAX_AGENT_SURFACE + 1), McpEmitter)
    assert _items(over, target_mapping=GROUPING_GUARD_MAPPING)


def test_a_mostly_event_source_is_flagged_near_empty() -> None:
    events = [Operation(key=f"e{i}.publish", name=f"e{i}", kind=OperationKind.PUBLISH) for i in range(9)]
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="x"),
                       services=[Service(key="s", name="s", operations=[
                           _op("GET /x", "getX", extras={"operationId": "getX"}), *events])])
    report = compute_lossiness_for_emitter(api, McpEmitter)
    [advisory] = _items(report, target_mapping=NEAR_EMPTY_MAPPING)
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.WARN
    assert "only 1 of the source's 10" in advisory.message


def test_grouping_guard_verdicts_directly() -> None:
    api = _big_api(10)
    assert grouping_guard_verdicts(api, {"a": 10}, covered=10, target_label="T", unit="tool", split_hint="h") == []
    assert grouping_guard_verdicts(api, {}, covered=0, target_label="T", unit="tool", split_hint="h") == []
    [near] = grouping_guard_verdicts(api, {"a": 1}, covered=1, target_label="T", unit="tool", split_hint="h")
    assert near.target_mapping == NEAR_EMPTY_MAPPING


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.mark.parametrize("definition, outcome", [
    ({"type": "http", "scheme": "Bearer"}, "ok"),
    ({"type": "oauth2", "flows": {}}, "ok"),
    ({"type": "oauth2", "flows": {"password": {}}}, "approx"),
    ({"type": "openIdConnect"}, "approx"),
    ({"type": "apiKey", "in": "query"}, "approx"),
    ({"type": "httpApiKey", "in": "header"}, "approx"),
    ({"type": "http", "scheme": "digest"}, "approx"),
    ({"type": "basic"}, "approx"),
    ({"type": "http", "scheme": "hoba"}, "approx"),
    ({"type": "apiKey", "in": "cookie"}, "drop"),
    ({"type": "X509"}, "drop"),
    ({"type": "userPassword"}, "drop"),
    ({}, "drop"),
])
def test_classify_auth_scheme(definition: Dict[str, Any], outcome: str) -> None:
    assert classify_auth_scheme(definition)[0] == outcome


def test_declared_auth_schemes_reads_every_place_a_model_records_auth() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.REST, format="swagger-2.0", identity=ApiIdentity(name="x"),
        raw={"securityDefinitions": {"basic": {"type": "basic"}}},
        extras={"security_schemes": {"stub": {"type": "http", "scheme": "bearer"}},
                "inferred_auth_schemes": ["apiKey"]},
        services=[Service(key="s", name="s", operations=[
            Operation(key="GET /x", name="x", kind=OperationKind.REQUEST_RESPONSE, extras={"security": ["oauth2"]})])],
    )
    schemes = dict(declared_auth_schemes(api))
    assert sorted(schemes) == ["apiKey", "basic", "oauth2", "stub"]
    assert schemes["stub"]["scheme"] == "bearer"
    assert schemes["oauth2"]["type"] == "oauth2"
    # Swagger 2 `type: basic` is HTTP basic auth: approximated, like an OpenAPI 3 basic scheme.
    assert classify_auth_scheme(schemes["basic"])[0] == "approx"
    assert {v.kind for v in auth_scheme_verdicts(api, target_label="T")} == {LossinessKind.OK, LossinessKind.APPROX}


def test_a_model_without_auth_reports_none() -> None:
    assert auth_scheme_verdicts(_big_api(1), target_label="T") == []


def test_streaming_drop_reason() -> None:
    plain = Operation(key="k", name="k", kind=OperationKind.REQUEST_RESPONSE)
    assert streaming_drop_reason(plain) is None
    bidi = Operation(key="k", name="k", kind=OperationKind.REQUEST_RESPONSE, streaming=StreamingMode.BIDIRECTIONAL)
    assert "bidirectional-streaming" in (streaming_drop_reason(bidi) or "")
    sub = Operation(key="k", name="k", kind=OperationKind.SUBSCRIPTION)
    assert "event flow" in (streaming_drop_reason(sub) or "")


def test_constraints_verdict() -> None:
    assert constraints_verdict(None, target_label="T") is None
    assert constraints_verdict(Constraints(), target_label="T") is None
    verdict: Optional[Any] = constraints_verdict(Constraints(min_length=1, format="email"), target_label="T")
    assert verdict is not None and verdict.kind is LossinessKind.OK
    assert "format, min_length" in verdict.message


def test_the_emitted_descriptor_still_validates_with_notes() -> None:
    from app.mcp_emitter import mcp_tool_schema_violations

    result = McpEmitter().emit(_rest_api(), opts=coerce_emit_options(McpEmitter, {"grouping": "per-service"}))
    for file in result.files:
        for tool in json.loads(file.content)["tools"]:
            assert mcp_tool_schema_violations(tool, "2025-06-18") == []
