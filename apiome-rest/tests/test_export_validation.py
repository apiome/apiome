"""Emitted-artifact validation — MFX-5.1 (#3852).

Exercises :mod:`app.export_validation`, the dispatcher that re-validates an emitted
artifact through its matching MFI import parser and is the gate the export job
(:mod:`app.export_job_engine`) fails delivery on. The acceptance criteria proven here —
"valid output passes; deliberately broken output is caught" — for every registered
emitter format, plus the honest handling of the two toolchain-backed targets:

* **openapi-3.1** / **graphql** / **avro** — pure-Python re-parse, so both the passing and
  the deliberately-broken case run in any runtime;
* **asyncapi-3** / **proto3** — validated when their toolchain is present, otherwise reported
  *skipped* (``validated`` false), never failing a possibly-valid export; the invalid path is
  proven with the toolchain mocked present;
* **sample-noop** / an unregistered format — reported *not applicable*, never a failure.
"""

from __future__ import annotations

from unittest.mock import patch

from app.avro_emitter import AvroEmitter
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitResult, EmittedFile
from app.export_validation import (
    EmittedArtifactValidation,
    validate_emitted_artifact,
)
from app.graphql_emitter import GraphQlEmitter
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.openapi_emitter import OpenApiEmitter

# ---------------------------------------------------------------------------
# Fixtures — one small valid model per paradigm
# ---------------------------------------------------------------------------


def _rest_api() -> CanonicalApi:
    """A REST model with one operation and one referenced type (emits valid OpenAPI)."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[Service(key="widgets", name="widgets", operations=[op])],
        types=[widget],
    )


_SIMPLE_SDL = """
type Query {
  ping: String!
  user: User
}

type User {
  id: ID!
  name: String
}
"""


def _graph_api() -> CanonicalApi:
    """A Graph-native model in the normalizer's normal form (emits valid GraphQL SDL)."""
    return GraphQlNormalizer().normalize(build_graphql_schema(_SIMPLE_SDL), include_raw=False)


def _data_schema_api() -> CanonicalApi:
    """A data-schema model with one RECORD type (emits a valid ``.avsc``)."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False)),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="widgets", namespace="com.example"),
        types=[widget],
    )


# ---------------------------------------------------------------------------
# OpenAPI (pure Python — always runs)
# ---------------------------------------------------------------------------


async def test_openapi_valid_artifact_passes() -> None:
    """A real OpenAPI emission re-parses cleanly: applicable, validated, valid."""
    api = _rest_api()
    emit_result = OpenApiEmitter().emit(api)
    validation = await validate_emitted_artifact("openapi-3.1", emit_result, api=api)

    assert validation.applicable
    assert validation.validated
    assert validation.valid
    assert not validation.failed
    assert validation.errors == []


async def test_openapi_schema_invalid_artifact_is_caught() -> None:
    """A 3.1 document missing the OAS-required ``info`` fails the meta-schema → job-failing."""
    broken = EmitResult.from_document({"openapi": "3.1.0", "paths": {}})
    validation = await validate_emitted_artifact("openapi-3.1", broken, api=_rest_api())

    assert validation.applicable
    assert validation.validated
    assert not validation.valid
    assert validation.failed
    assert validation.errors  # the meta-schema errors are surfaced


async def test_openapi_unparseable_artifact_is_caught() -> None:
    """A document with no ``openapi`` marker is not legal input for its own parser."""
    not_a_spec = EmitResult.from_document({"foo": "bar"})
    validation = await validate_emitted_artifact("openapi-3.1", not_a_spec, api=_rest_api())

    assert validation.failed
    assert validation.errors


# ---------------------------------------------------------------------------
# GraphQL (pure Python — always runs)
# ---------------------------------------------------------------------------


async def test_graphql_valid_artifact_passes() -> None:
    """A real GraphQL SDL emission re-parses and re-imports cleanly."""
    api = _graph_api()
    emit_result = GraphQlEmitter().emit(api)
    validation = await validate_emitted_artifact("graphql", emit_result, api=api)

    assert validation.validated
    assert validation.valid
    assert not validation.failed


async def test_graphql_broken_sdl_is_caught() -> None:
    """A syntactically invalid SDL is rejected by the MFI-10.1 parser → job-failing."""
    broken = EmitResult(files=[EmittedFile(path="schema.graphql", content="type Query { !!! }")])
    validation = await validate_emitted_artifact("graphql", broken, api=_graph_api())

    assert validation.failed
    assert validation.errors


# ---------------------------------------------------------------------------
# Avro (pure Python — always runs)
# ---------------------------------------------------------------------------


async def test_avro_valid_artifact_passes() -> None:
    """A real Avro emission validates against ``fastavro`` for every schema."""
    api = _data_schema_api()
    emit_result = AvroEmitter().emit(api)
    validation = await validate_emitted_artifact("avro", emit_result, api=api)

    assert validation.validated
    assert validation.valid
    assert not validation.failed


async def test_avro_cross_referencing_types_pass_regardless_of_file_order() -> None:
    """A record referencing another named type by name resolves against the shared registry.

    Each named type is emitted to its own file, so a record that references a sibling type by
    name cannot be validated in isolation; the validator must resolve the references across
    files, order-independently (the emitted files are path-sorted, not dependency-sorted).
    """
    referenced = Type(
        key="Suit",
        name="Suit",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Suit.HEARTS", name="HEARTS"),
            EnumValue(key="Suit.SPADES", name="SPADES"),
        ],
    )
    holder = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="User.id", name="id", type=TypeRef(name="string", nullable=False)),
            CanonicalField(key="User.suit", name="suit", type=TypeRef(name="Suit", nullable=False)),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="cards", namespace="com.example"),
        types=[holder, referenced],
    )
    emit_result = AvroEmitter().emit(api)
    # The emitted files are path-sorted, so ``User`` (which references ``Suit``) is emitted
    # before ``Suit`` — the ordering that trips a naive single-pass validator.
    validation = await validate_emitted_artifact("avro", emit_result, api=api)

    assert validation.validated
    assert validation.valid
    assert not validation.failed


async def test_avro_broken_schema_is_caught() -> None:
    """A file whose content is not a legal Avro schema is rejected, tagged by path."""
    broken = EmitResult(
        files=[EmittedFile(path="schemas/bad.avsc", content={"type": "not-a-real-avro-type"})]
    )
    validation = await validate_emitted_artifact("avro", broken, api=_data_schema_api())

    assert validation.failed
    assert any("bad.avsc" in error for error in validation.errors)


# ---------------------------------------------------------------------------
# Not applicable — no importer matches the format
# ---------------------------------------------------------------------------


async def test_sample_noop_target_is_not_applicable() -> None:
    """The internal sample no-op target has no importable artifact; never a failure."""
    emit_result = EmitResult(files=[EmittedFile(path="sample.txt", content="anything")])
    validation = await validate_emitted_artifact("sample-noop", emit_result, api=_rest_api())

    assert not validation.applicable
    assert not validation.validated
    assert not validation.failed
    assert validation.detail


async def test_unregistered_format_is_not_applicable() -> None:
    """A format with no registered validator is reported not-applicable, not failed."""
    emit_result = EmitResult(files=[EmittedFile(path="x", content="y")])
    validation = await validate_emitted_artifact("totally-unknown", emit_result, api=_rest_api())

    assert not validation.applicable
    assert not validation.failed


# ---------------------------------------------------------------------------
# AsyncAPI — toolchain-backed (skipped when absent, invalid caught when present)
# ---------------------------------------------------------------------------


async def test_asyncapi_is_skipped_when_the_parser_toolchain_is_unavailable() -> None:
    """With ``asyncapi-parser`` unavailable, the artifact is not re-validated (not failed)."""
    emit_result = EmitResult.from_document({"asyncapi": "3.0.0"})
    with patch("app.toolchain_runner.is_tool_available", return_value=False):
        validation = await validate_emitted_artifact("asyncapi-3", emit_result, api=_rest_api())

    assert validation.applicable
    assert not validation.validated
    assert not validation.failed
    assert "asyncapi-parser" in (validation.detail or "")


async def test_asyncapi_invalid_artifact_is_caught_when_the_parser_is_available() -> None:
    """With the parser present and reporting errors, the artifact fails validation."""

    class _Report:
        valid = False
        validation_errors = [{"message": "channels is required", "path": "/channels"}]
        import_error = None

    async def _fake_round_trip(*args, **kwargs):
        return _Report()

    emit_result = EmitResult.from_document({"asyncapi": "3.0.0"})
    with patch("app.toolchain_runner.is_tool_available", return_value=True), patch(
        "app.asyncapi_roundtrip.round_trip_asyncapi", _fake_round_trip
    ):
        validation = await validate_emitted_artifact("asyncapi-3", emit_result, api=_rest_api())

    assert validation.validated
    assert validation.failed
    assert any("channels is required" in error for error in validation.errors)


async def test_asyncapi_infrastructure_failure_is_skipped_not_failed() -> None:
    """A parser that raises (tool vanished / timeout) is a skip, never a false rejection."""
    from app.asyncapi_parser import AsyncApiParseError

    async def _boom(*args, **kwargs):
        raise AsyncApiParseError("the asyncapi-parser worker timed out")

    emit_result = EmitResult.from_document({"asyncapi": "3.0.0"})
    with patch("app.toolchain_runner.is_tool_available", return_value=True), patch(
        "app.asyncapi_roundtrip.round_trip_asyncapi", _boom
    ):
        validation = await validate_emitted_artifact("asyncapi-3", emit_result, api=_rest_api())

    assert not validation.validated
    assert not validation.failed


# ---------------------------------------------------------------------------
# protobuf — toolchain-backed (skipped when absent, invalid caught when present)
# ---------------------------------------------------------------------------


async def test_proto_is_skipped_when_buf_is_unavailable() -> None:
    """With ``buf`` unavailable, the emitted ``.proto`` is not compiled here (not failed)."""
    emit_result = EmitResult(
        files=[EmittedFile(path="widgets.proto", content='syntax = "proto3";\n')]
    )
    with patch("app.toolchain_runner.is_tool_available", return_value=False):
        validation = await validate_emitted_artifact("proto3", emit_result, api=_rest_api())

    assert validation.applicable
    assert not validation.validated
    assert not validation.failed
    assert "buf" in (validation.detail or "")


async def test_proto_that_does_not_compile_is_caught_when_buf_is_available() -> None:
    """With ``buf`` present and the compile failing, the artifact fails validation."""
    from app.proto_descriptor import ProtoCompileError

    async def _fail_compile(*args, **kwargs):
        raise ProtoCompileError("buf build failed", diagnostics="syntax error: unexpected token")

    emit_result = EmitResult(
        files=[EmittedFile(path="widgets.proto", content="not valid proto")]
    )
    with patch("app.toolchain_runner.is_tool_available", return_value=True), patch(
        "app.proto_descriptor.compile_proto_descriptor_set", _fail_compile
    ):
        validation = await validate_emitted_artifact("proto3", emit_result, api=_rest_api())

    assert validation.validated
    assert validation.failed
    assert any("syntax error" in error for error in validation.errors)


async def test_proto_that_compiles_passes_when_buf_is_available() -> None:
    """With ``buf`` present and the compile succeeding, the artifact passes."""

    async def _ok_compile(*args, **kwargs):
        return object()  # a CompiledDescriptorSet stand-in; the validator ignores its shape

    emit_result = EmitResult(
        files=[EmittedFile(path="widgets.proto", content='syntax = "proto3";\n')]
    )
    with patch("app.toolchain_runner.is_tool_available", return_value=True), patch(
        "app.proto_descriptor.compile_proto_descriptor_set", _ok_compile
    ):
        validation = await validate_emitted_artifact("proto3", emit_result, api=_rest_api())

    assert validation.validated
    assert validation.valid
    assert not validation.failed


# ---------------------------------------------------------------------------
# The `failed` gate
# ---------------------------------------------------------------------------


def test_failed_is_true_only_for_a_validated_invalid_artifact() -> None:
    """The gate the job fails on: applicable + validated + not valid."""
    assert EmittedArtifactValidation(
        target="openapi-3.1", applicable=True, validated=True, valid=False, errors=["e"]
    ).failed
    # Skipped / not-applicable / passing are never failures.
    assert not EmittedArtifactValidation(
        target="asyncapi-3", applicable=True, validated=False, valid=True
    ).failed
    assert not EmittedArtifactValidation(
        target="sample-noop", applicable=False, validated=False, valid=True
    ).failed
    assert not EmittedArtifactValidation(
        target="openapi-3.1", applicable=True, validated=True, valid=True
    ).failed
