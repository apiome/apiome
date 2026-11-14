"""Tests for ``google.api.http`` annotations on the protobuf emitter — MFX-12.6 (#4343).

Pins the acceptance criteria:

* a REST-sourced export carries ``option (google.api.http)`` on each ``rpc`` when
  ``http_annotations`` is on (verb + route, ``body: "*"`` for a POST/PUT/PATCH with a request
  body, ``custom`` for a verb the rule has no field for), and imports
  ``google/api/annotations.proto``; off (the default), nothing is written and the binding is a loss;
* the fidelity pack reflects the mapping: ``DROP`` with the option off, ``OK`` when every route
  variable and query parameter is a request field, ``APPROX`` naming the inputs it cannot bind;
* the Connect target inherits the option and the ``buf`` toolchain checks;
* the toolchain ``buf`` checks stage the vendored googleapis protos an annotated bundle imports.

The gated test compiles an annotated bundle with the real ``buf`` (when it is resolvable).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.connectrpc_emitter import ConnectRpcEmitOptions, ConnectRpcEmitter
from app.export_tool_checks import _BUF_YAML, run_tool_check, tool_check_command
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.proto_descriptor import BUF_TOOL_KEY
from app.proto_emitter import ProtoEmitOptions, ProtoEmitter, compile_emitted_descriptor_set
from app.proto_http_annotations import (
    HttpAnnotation,
    http_annotation_for,
    render_http_option,
    request_field_names,
    unbound_parameters,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import ToolRunResult

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))

_ON = ProtoEmitOptions(http_annotations=True)


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------
def _field(owner: str, name: str, number: int) -> CanonicalField:
    """A string field ``name`` on type ``owner``."""
    return CanonicalField(
        key=f"{owner}.{name}", name=name, type=TypeRef(name="string"), field_number=number
    )


def _message(key: str, role: MessageRole, payload: Optional[str]) -> Message:
    """A request/response message naming ``payload``."""
    return Message(key=key, role=role, payload=TypeRef(name=payload) if payload else None)


def _operation(
    name: str,
    method: str,
    path: str,
    *,
    request: Optional[str] = None,
    response: Optional[str] = "acme.pets.Pet",
    parameters: Optional[List[Parameter]] = None,
) -> Operation:
    """A REST operation ``METHOD path`` with optional request/response payloads."""
    key = f"{method} {path}"
    messages = []
    if request:
        messages.append(_message(f"{key}#request", MessageRole.REQUEST, request))
    if response:
        messages.append(_message(f"{key}#response.200", MessageRole.RESPONSE, response))
    return Operation(
        key=key,
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=messages,
    )


def _param(op_key: str, name: str, location: ParameterLocation) -> Parameter:
    """A string parameter ``name`` carried in ``location``."""
    return Parameter(
        key=f"{op_key}#{location.value}.{name}",
        name=name,
        location=location,
        type=TypeRef(name="string"),
    )


def _rest_api() -> CanonicalApi:
    """A REST pets API: a bound GET, a POST with a body, a GET with unbound inputs, a HEAD."""
    pet = Type(
        key="acme.pets.Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        fields=[_field("acme.pets.Pet", "id", 1), _field("acme.pets.Pet", "name", 2)],
    )
    get_request = Type(
        key="acme.pets.GetPetRequest",
        name="GetPetRequest",
        kind=TypeKind.RECORD,
        fields=[_field("acme.pets.GetPetRequest", "pet_id", 1)],
    )
    operations = [
        _operation("GetPet", "GET", "/pets/{pet-id}", request="acme.pets.GetPetRequest"),
        _operation("CreatePet", "POST", "/pets", request="acme.pets.Pet"),
        _operation(
            "ListPets",
            "GET",
            "/owners/{owner}/pets",
            parameters=[
                _param("GET /owners/{owner}/pets", "owner", ParameterLocation.PATH),
                _param("GET /owners/{owner}/pets", "limit", ParameterLocation.QUERY),
                _param("GET /owners/{owner}/pets", "X-Trace", ParameterLocation.HEADER),
            ],
        ),
        _operation("PetExists", "HEAD", "/pets/{id}", request="acme.pets.Pet", response=None),
    ]
    return CanonicalApi(
        identity=ApiIdentity(name="Pets", namespace="acme.pets"),
        paradigm=ApiParadigm.REST,
        format="openapi",
        types=[pet, get_request],
        services=[Service(key="acme.pets.PetService", name="PetService", operations=operations)],
    )


def _ops(api: CanonicalApi) -> Dict[str, Operation]:
    """The model's operations by name."""
    return {op.name: op for op in api.operations()}


def _text(result) -> str:
    """The emitted ``.proto`` text (the pets API is one package, so one file)."""
    assert len(result.files) == 1
    return str(result.files[0].content)


# ---------------------------------------------------------------------------
# The rule helper
# ---------------------------------------------------------------------------
class TestHttpAnnotationFor:
    """Deriving a ``google.api.http`` rule from an operation's binding."""

    def test_rest_binding_is_used_and_variables_become_field_paths(self) -> None:
        annotation = http_annotation_for(_ops(_rest_api())["GetPet"])
        assert annotation == HttpAnnotation(verb="get", path="/pets/{pet_id}", body=None)
        assert annotation.label == "GET /pets/{pet_id}"
        assert annotation.variables() == ["pet_id"]

    def test_post_with_a_request_body_binds_the_whole_message(self) -> None:
        assert http_annotation_for(_ops(_rest_api())["CreatePet"]).body == "*"

    def test_get_never_carries_a_body(self) -> None:
        op = _operation("Search", "GET", "/search", request="acme.pets.Pet")
        assert http_annotation_for(op).body is None

    def test_extras_binding_keeps_its_recorded_body(self) -> None:
        op = Operation(
            key="acme.pets.PetService.UpdatePet",
            name="UpdatePet",
            kind=OperationKind.REQUEST_RESPONSE,
            extras={"http": {"method": "patch", "path": "/v1/{pet.id}", "body": "pet"}},
        )
        assert http_annotation_for(op) == HttpAnnotation(verb="patch", path="/v1/{pet.id}", body="pet")

    def test_google_style_extras_binding(self) -> None:
        op = Operation(
            key="k", name="Get", kind=OperationKind.REQUEST_RESPONSE, extras={"http": {"get": "v1/{name=shelves/*}"}}
        )
        assert http_annotation_for(op) == HttpAnnotation(verb="get", path="/v1/{name=shelves/*}", body=None)

    def test_an_operation_without_a_binding_has_no_rule(self) -> None:
        op = Operation(key="k", name="Do", kind=OperationKind.REQUEST_RESPONSE)
        assert http_annotation_for(op) is None

    def test_unbound_inputs_are_named(self) -> None:
        api = _rest_api()
        types = {t.key: t for t in api.types}
        ops = _ops(api)
        get_pet = ops["GetPet"]
        assert unbound_parameters(get_pet, http_annotation_for(get_pet), request_field_names(get_pet, types)) == []
        list_pets = ops["ListPets"]
        assert request_field_names(list_pets, types) is None
        assert unbound_parameters(list_pets, http_annotation_for(list_pets), None) == [
            "header X-Trace",
            "path owner",
            "query limit",
        ]

    def test_query_parameters_are_not_checked_when_the_body_is_the_whole_message(self) -> None:
        op = _operation(
            "CreatePet",
            "POST",
            "/pets",
            request="acme.pets.Pet",
            parameters=[_param("POST /pets", "dry_run", ParameterLocation.QUERY)],
        )
        assert unbound_parameters(op, http_annotation_for(op), ["id", "name"]) == []

    def test_render_standard_and_custom_verbs(self) -> None:
        assert render_http_option(HttpAnnotation("post", "/pets", "*"), "    ", "  ") == [
            "    option (google.api.http) = {",
            '      post: "/pets"',
            '      body: "*"',
            "    };",
        ]
        assert render_http_option(HttpAnnotation("head", '/a"b', None), "", "  ") == [
            "option (google.api.http) = {",
            '  custom: { kind: "HEAD" path: "/a\\"b" }',
            "};",
        ]


# ---------------------------------------------------------------------------
# The emitter
# ---------------------------------------------------------------------------
class TestEmitter:
    """``ProtoEmitter`` with and without ``http_annotations``."""

    def test_option_defaults_off(self) -> None:
        assert ProtoEmitOptions().http_annotations is False

    def test_off_writes_no_annotation_and_records_each_dropped_binding(self) -> None:
        result = ProtoEmitter().emit(_rest_api())
        text = _text(result)
        assert "google.api.http" not in text
        assert "google/api/annotations.proto" not in text
        dropped = [loss for loss in result.losses if loss.subject == "http-binding"]
        assert len(dropped) == 4
        assert any("GET /pets/{pet_id}" in loss.detail for loss in dropped)

    def test_on_annotates_every_rest_rpc(self) -> None:
        result = ProtoEmitter().emit(_rest_api(), opts=_ON)
        text = _text(result)
        assert 'import "google/api/annotations.proto";' in text
        assert (
            "  rpc GetPet (.acme.pets.GetPetRequest) returns (.acme.pets.Pet) {\n"
            "    option (google.api.http) = {\n"
            '      get: "/pets/{pet_id}"\n'
            "    };\n"
            "  }\n"
        ) in text
        assert '      post: "/pets"\n      body: "*"\n' in text
        assert '      custom: { kind: "HEAD" path: "/pets/{id}" }\n' in text
        assert not [loss for loss in result.losses if loss.subject == "http-binding"]

    def test_on_records_inputs_the_rule_cannot_bind(self) -> None:
        result = ProtoEmitter().emit(_rest_api(), opts=_ON)
        unbound = {loss.pointer: loss.detail for loss in result.losses if loss.subject == "http-annotation-unbound"}
        assert set(unbound) == {"GET /owners/{owner}/pets"}
        assert "header X-Trace, path owner, query limit" in unbound["GET /owners/{owner}/pets"]

    def test_annotation_precedes_other_method_options(self) -> None:
        api = _rest_api()
        _ops(api)["GetPet"].deprecated = True
        text = _text(ProtoEmitter().emit(api, opts=_ON))
        assert '      get: "/pets/{pet_id}"\n    };\n    option deprecated = true;\n' in text

    def test_provenance_marks_the_annotation_as_source(self) -> None:
        result = ProtoEmitter().emit(_rest_api(), opts=_ON)
        pointers = {record.pointer for record in result.provenance}
        assert any(p.endswith("/methods/GetPet/options/google.api.http") for p in pointers)

    def test_emission_is_deterministic(self) -> None:
        assert _text(ProtoEmitter().emit(_rest_api(), opts=_ON)) == _text(
            ProtoEmitter().emit(_rest_api(), opts=_ON)
        )

    def test_rpc_source_without_bindings_is_unchanged(self) -> None:
        api = _rest_api()
        for op in api.operations():
            op.http_method = None
            op.http_path = None
        assert _text(ProtoEmitter().emit(api, opts=_ON)) == _text(ProtoEmitter().emit(api))

    def test_connect_target_inherits_the_option_and_buf_checks(self) -> None:
        result = ConnectRpcEmitter().emit(_rest_api(), opts=ConnectRpcEmitOptions(http_annotations=True))
        text = str(result.files[0].content)
        assert text.startswith("// Connect-RPC service contract")
        assert 'get: "/pets/{pet_id}"' in text
        assert ConnectRpcEmitter.test_tools == ProtoEmitter.test_tools


# ---------------------------------------------------------------------------
# The fidelity pack
# ---------------------------------------------------------------------------
def _binding_items(options: Optional[dict]) -> Dict[str, List]:
    """The REST-binding verdicts the protobuf pack predicts, by operation key."""
    report = compute_lossiness_for_emitter(_rest_api(), ProtoEmitter, options=options)
    items: Dict[str, List] = {}
    for item in report.items:
        if "google.api.http" in item.message or "HTTP binding" in item.message:
            items.setdefault(item.construct_key, []).append(item)
    return items


class TestFidelityPack:
    """``ProtoFidelityRulePack`` reflects the ``http_annotations`` choice."""

    def test_off_drops_every_binding(self) -> None:
        items = _binding_items(None)
        assert len(items) == 4
        assert all(item.kind is LossinessKind.DROP for group in items.values() for item in group)

    def test_on_carries_bound_operations_ok(self) -> None:
        items = _binding_items({"http_annotations": True})
        get_pet = items["GET /pets/{pet-id}"][0]
        assert get_pet.kind is LossinessKind.OK
        assert get_pet.target_mapping == "GET /pets/{pet_id} → option (google.api.http)"
        assert items["POST /pets"][0].kind is LossinessKind.OK

    def test_on_approximates_unbound_inputs(self) -> None:
        item = _binding_items({"http_annotations": True})["GET /owners/{owner}/pets"][0]
        assert item.kind is LossinessKind.APPROX
        assert "header X-Trace, path owner, query limit" in item.message

    def test_invalid_options_fall_back_to_the_default(self) -> None:
        items = _binding_items({"http_annotations": "not-a-bool"})
        assert all(item.kind is LossinessKind.DROP for group in items.values() for item in group)

    def test_pack_and_emitter_agree(self) -> None:
        """Each emit-time ``http-annotation-unbound`` loss has a predicted ``APPROX``."""
        result = ProtoEmitter().emit(_rest_api(), opts=_ON)
        emitted = {loss.pointer for loss in result.losses if loss.subject == "http-annotation-unbound"}
        predicted = {
            key
            for key, group in _binding_items({"http_annotations": True}).items()
            if any(item.kind is LossinessKind.APPROX for item in group)
        }
        assert emitted == predicted


# ---------------------------------------------------------------------------
# The toolchain checks
# ---------------------------------------------------------------------------
class _StagingRunner:
    """Captures the staged scratch directory and returns a clean run."""

    def __init__(self) -> None:
        self.staged: Dict[str, str] = {}

    async def run_spec(self, spec, args, *, timeout=None, cwd=None, extra_env=None, on_output=None):
        scratch = Path(cwd)
        self.staged = {p.relative_to(scratch).as_posix(): p.read_text() for p in scratch.rglob("*") if p.is_file()}
        return ToolRunResult(key=spec.key, argv=[spec.executable, *args], exit_code=0, stdout="", stderr="",
                             duration_ms=1)


async def _stage(check: str, files: Dict[str, str]) -> Dict[str, str]:
    """Run ``buf <check>`` on ``files`` with a capturing runner and return what was staged."""
    runner = _StagingRunner()
    await run_tool_check(tool_check_command("buf", check), files, label=f"buf {check}",
                         on_event=lambda _event: None, runner=runner)
    return runner.staged


class TestToolchainStaging:
    """``buf lint`` / ``buf build`` get the googleapis protos an annotated bundle imports."""

    @pytest.mark.parametrize("check", ["lint", "build"])
    async def test_annotated_bundle_gets_vendored_googleapis(self, check: str) -> None:
        result = ProtoEmitter().emit(_rest_api(), opts=_ON)
        staged = await _stage(check, {f.path: str(f.content) for f in result.files})
        assert "google/api/annotations.proto" in staged and "google/api/http.proto" in staged
        assert "- google/api/annotations.proto" in staged["buf.yaml"]
        assert "- google/api/http.proto" in staged["buf.yaml"]

    async def test_plain_bundle_stages_nothing_extra(self) -> None:
        result = ProtoEmitter().emit(_rest_api())
        staged = await _stage("lint", {f.path: str(f.content) for f in result.files})
        assert not any(path.startswith("google/") for path in staged)
        assert staged["buf.yaml"] == _BUF_YAML

    async def test_a_bundled_googleapis_tree_and_config_are_kept(self) -> None:
        files = {
            "a.proto": 'syntax = "proto3";\nimport "google/api/annotations.proto";\n',
            "google/api/annotations.proto": "// mine\n",
            "buf.yaml": "version: v2\n",
        }
        staged = await _stage("build", files)
        assert staged["google/api/annotations.proto"] == "// mine\n"
        assert "google/api/http.proto" in staged  # its own import is still supplied
        assert staged["buf.yaml"] == "version: v2\n"


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="buf toolchain not available")
class TestRealBuf:
    """An annotated bundle compiles through the real ``buf build``."""

    async def test_annotated_bundle_compiles(self) -> None:
        compiled = await compile_emitted_descriptor_set(_rest_api(), opts=_ON)
        assert "acme/pets.proto" in {f.name for f in compiled.files}
