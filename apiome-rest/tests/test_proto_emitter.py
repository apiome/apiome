"""Tests for the Protocol Buffers (proto3) emitter — MFX-12.1 (#3879).

Exercises the acceptance criteria: a typed **RPC** source emits compilable proto3 ``.proto`` with
**streaming preserved** — every :class:`~app.canonical_model.StreamingMode` restores the right
``stream`` keyword on the request/response — and the type system (messages, nested messages,
enums, ``map<K,V>``, ``oneof``, ``repeated``, proto3 ``optional``, ``reserved``, field numbers)
inverts :mod:`app.proto_normalizer` construct-for-construct. Constructs proto3 cannot carry (a
field's ``Constraints``, a proto2 ``default``, a ``UNION`` type, a source field with no number)
are recorded as :class:`~app.emitter.Loss`\\es. Emission is deterministic and provenance-tagged.

The structural tests assert the emitted text and run everywhere (no toolchain). The gated
``TestRealBuf`` class compiles the emitted document through the real bundled ``buf`` and normalizes
it back, proving the ``.proto`` is legal and that a proto source is a fixed point of
``normalize ∘ emit`` — but only when ``buf`` is resolvable (bundled in the image / ``APIOME_BUF_BIN``).
"""

from __future__ import annotations

import pytest

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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import Provenance, get_emitter
from app.proto_descriptor import BUF_TOOL_KEY
from app.proto_emitter import ProtoEmitOptions, ProtoEmitter, compile_emitted_descriptor_set
from app.proto_normalizer import ProtoNormalizer
from app.toolchain_packaging import probe_tool

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------
def _rpc_api() -> CanonicalApi:
    """A self-contained single-package RPC model exercising the full proto surface.

    One package (``acme.user``), a nested message, an enum, a ``map`` field, a ``oneof``, a
    ``repeated`` field, a proto3 ``optional`` field, ``reserved`` ranges/names, a well-known-type
    reference (``Timestamp``), and two rpcs (unary + bidi-streaming).
    """
    address = Type(
        key="acme.user.Address",
        name="Address",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="acme.user.Address.street",
                name="street",
                type=TypeRef(name="string"),
                field_number=1,
            )
        ],
    )
    role = Type(
        key="acme.user.Role",
        name="Role",
        kind=TypeKind.ENUM,
        description="Access role.",
        enum_values=[
            EnumValue(key="acme.user.Role.ROLE_UNSPECIFIED", name="ROLE_UNSPECIFIED", value=0),
            EnumValue(key="acme.user.Role.ROLE_MEMBER", name="ROLE_MEMBER", value=1),
            EnumValue(key="acme.user.Role.ROLE_ADMIN", name="ROLE_ADMIN", value=2),
        ],
    )
    labels_entry = Type(
        key="acme.user.User.LabelsEntry",
        name="LabelsEntry",
        kind=TypeKind.MAP,
        key_type=TypeRef(name="string"),
        value_type=TypeRef(name="int32"),
    )
    meta = Type(
        key="acme.user.User.Meta",
        name="Meta",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="acme.user.User.Meta.note",
                name="note",
                type=TypeRef(name="string"),
                field_number=1,
            )
        ],
    )
    user = Type(
        key="acme.user.User",
        name="User",
        kind=TypeKind.RECORD,
        description="A registered user.",
        fields=[
            CanonicalField(
                key="acme.user.User.id", name="id", type=TypeRef(name="string"), field_number=1
            ),
            CanonicalField(
                key="acme.user.User.address",
                name="address",
                type=TypeRef(name="acme.user.Address"),
                field_number=3,
            ),
            CanonicalField(
                key="acme.user.User.created_at",
                name="created_at",
                type=TypeRef(name="google.protobuf.Timestamp"),
                field_number=4,
            ),
            CanonicalField(
                key="acme.user.User.role",
                name="role",
                type=TypeRef(name="acme.user.Role"),
                field_number=5,
            ),
            CanonicalField(
                key="acme.user.User.tags",
                name="tags",
                type=TypeRef(item=TypeRef(name="string", nullable=False), nullable=False),
                field_number=6,
                extras={"label": "repeated"},
            ),
            CanonicalField(
                key="acme.user.User.labels",
                name="labels",
                type=TypeRef(name="acme.user.User.LabelsEntry", nullable=False),
                field_number=7,
            ),
            CanonicalField(
                key="acme.user.User.nick",
                name="nick",
                type=TypeRef(name="string"),
                field_number=8,
                extras={"proto3_optional": True},
            ),
            CanonicalField(
                key="acme.user.User.email",
                name="email",
                type=TypeRef(name="string"),
                field_number=9,
                extras={"oneof": "contact"},
            ),
            CanonicalField(
                key="acme.user.User.phone",
                name="phone",
                type=TypeRef(name="string"),
                field_number=10,
                extras={"oneof": "contact"},
            ),
            CanonicalField(
                key="acme.user.User.meta",
                name="meta",
                type=TypeRef(name="acme.user.User.Meta"),
                field_number=11,
            ),
        ],
        extras={
            "oneofs": ["contact"],
            "reserved_ranges": [[2, 3]],
            "reserved_names": ["old_name"],
        },
    )
    get_req = Type(
        key="acme.user.GetUserRequest",
        name="GetUserRequest",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="acme.user.GetUserRequest.id",
                name="id",
                type=TypeRef(name="string"),
                field_number=1,
            )
        ],
    )
    service = Service(
        key="acme.user.UserService",
        name="UserService",
        operations=[
            Operation(
                key="acme.user.UserService.GetUser",
                name="GetUser",
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.NONE,
                messages=[
                    Message(
                        key="acme.user.UserService.GetUser#request",
                        role=MessageRole.REQUEST,
                        payload=TypeRef(name="acme.user.GetUserRequest"),
                    ),
                    Message(
                        key="acme.user.UserService.GetUser#response",
                        role=MessageRole.RESPONSE,
                        payload=TypeRef(name="acme.user.User"),
                    ),
                ],
            ),
            Operation(
                key="acme.user.UserService.Chat",
                name="Chat",
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.BIDIRECTIONAL,
                extras={"idempotency_level": "no_side_effects"},
                messages=[
                    Message(
                        key="acme.user.UserService.Chat#request",
                        role=MessageRole.REQUEST,
                        payload=TypeRef(name="acme.user.GetUserRequest"),
                    ),
                    Message(
                        key="acme.user.UserService.Chat#response",
                        role=MessageRole.RESPONSE,
                        payload=TypeRef(name="acme.user.User"),
                    ),
                ],
            ),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        protocol="grpc",
        identity=ApiIdentity(name="acme.user", namespace="acme.user"),
        services=[service],
        types=[address, role, labels_entry, meta, user, get_req],
    )


def _emit(api: CanonicalApi, opts: ProtoEmitOptions | None = None) -> str:
    """Emit ``api`` and return the primary ``.proto`` text."""
    return str(ProtoEmitter().emit(api, opts=opts).files[0].content)


# ---------------------------------------------------------------------------
# Registration + descriptor
# ---------------------------------------------------------------------------
def test_registers_under_proto3_format() -> None:
    assert get_emitter("proto3") is ProtoEmitter


def test_descriptor_and_capability_profile() -> None:
    descriptor = ProtoEmitter.descriptor()
    assert descriptor.key == "protobuf"
    assert descriptor.format == "proto3"
    assert descriptor.paradigm == ApiParadigm.RPC
    # Emit needs no toolchain (pure text); buf is only for the optional compile/validate.
    assert descriptor.needs_toolchain is False

    profile = ProtoEmitter.capability_profile()
    assert profile.operations is True
    assert profile.field_identity is True  # field numbers are protobuf's strength
    assert profile.unions is False  # no first-class union type
    assert profile.constraints is False  # no native validation facets


# ---------------------------------------------------------------------------
# Header / package / imports
# ---------------------------------------------------------------------------
def test_header_syntax_package_and_wkt_import() -> None:
    text = _emit(_rpc_api())
    assert text.startswith('syntax = "proto3";')
    assert "package acme.user;" in text
    # The Timestamp reference pulls in exactly its well-known-type import.
    assert 'import "google/protobuf/timestamp.proto";' in text


def test_package_option_overrides_identity_namespace() -> None:
    text = _emit(_rpc_api(), ProtoEmitOptions(package="other.pkg"))
    assert "package other.pkg;" in text


# ---------------------------------------------------------------------------
# Services / streaming (the acceptance criterion)
# ---------------------------------------------------------------------------
def test_service_and_rpc_unary_and_bidi_streaming() -> None:
    text = _emit(_rpc_api())
    assert "service UserService {" in text
    # Unary: no stream keyword either side.
    assert "rpc GetUser (.acme.user.GetUserRequest) returns (.acme.user.User);" in text
    # Bidi: stream on both request and response.
    assert "rpc Chat (stream .acme.user.GetUserRequest) returns (stream .acme.user.User)" in text
    # Method option restored from extras.
    assert "option idempotency_level = NO_SIDE_EFFECTS;" in text


@pytest.mark.parametrize(
    "mode, expected",
    [
        (StreamingMode.NONE, "rpc M (.p.Req) returns (.p.Resp);"),
        (StreamingMode.CLIENT, "rpc M (stream .p.Req) returns (.p.Resp);"),
        (StreamingMode.SERVER, "rpc M (.p.Req) returns (stream .p.Resp);"),
        (StreamingMode.BIDIRECTIONAL, "rpc M (stream .p.Req) returns (stream .p.Resp);"),
    ],
)
def test_all_four_streaming_modes_render(mode: StreamingMode, expected: str) -> None:
    """Each of the four streaming modes restores the exact ``stream`` placement."""
    req = Type(key="p.Req", name="Req", kind=TypeKind.RECORD)
    resp = Type(key="p.Resp", name="Resp", kind=TypeKind.RECORD)
    service = Service(
        key="p.S",
        name="S",
        operations=[
            Operation(
                key="p.S.M",
                name="M",
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=mode,
                messages=[
                    Message(key="p.S.M#request", role=MessageRole.REQUEST, payload=TypeRef(name="p.Req")),
                    Message(key="p.S.M#response", role=MessageRole.RESPONSE, payload=TypeRef(name="p.Resp")),
                ],
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        services=[service],
        types=[req, resp],
    )
    assert expected in _emit(api)


def test_emit_services_disabled_omits_services_and_records_loss() -> None:
    result = ProtoEmitter().emit(_rpc_api(), opts=ProtoEmitOptions(emit_services=False))
    text = str(result.files[0].content)
    assert "service UserService" not in text
    assert "message User" in text  # types still emitted
    assert any(loss.subject == "emit-services-disabled" for loss in result.losses)


# ---------------------------------------------------------------------------
# Messages / fields / maps / oneof / nesting / reserved
# ---------------------------------------------------------------------------
def test_message_fields_numbers_and_type_references() -> None:
    text = _emit(_rpc_api())
    assert "message User {" in text
    assert "string id = 1;" in text
    # A message reference is emitted fully-qualified with a leading dot (unambiguous resolution).
    assert ".acme.user.Address address = 3;" in text
    assert ".google.protobuf.Timestamp created_at = 4;" in text
    assert ".acme.user.Role role = 5;" in text


def test_repeated_map_and_optional_fields() -> None:
    text = _emit(_rpc_api())
    assert "repeated string tags = 6;" in text
    # The MAP type is inlined as map<K,V>, never emitted as a standalone LabelsEntry message.
    assert "map<string, int32> labels = 7;" in text
    assert "message LabelsEntry" not in text
    assert "optional string nick = 8;" in text


def test_oneof_block_groups_members() -> None:
    text = _emit(_rpc_api())
    assert "oneof contact {" in text
    assert "string email = 9;" in text
    assert "string phone = 10;" in text


def test_nested_message_is_reconstructed_from_dotted_key() -> None:
    text = _emit(_rpc_api())
    # Meta is keyed acme.user.User.Meta → nested inside User, referenced by its full path.
    user_block = text.split("message User {", 1)[1]
    assert "message Meta {" in user_block
    assert ".acme.user.User.Meta meta = 11;" in text


def test_reserved_ranges_and_names() -> None:
    text = _emit(_rpc_api())
    # Message reserved range [2, 3) (half-open) → the single inclusive number 2.
    assert "reserved 2;" in text
    assert 'reserved "old_name";' in text


def test_reserved_range_inclusive_conversion_and_max() -> None:
    """A multi-number half-open message range renders inclusive; an open-ended one renders ``to max``."""
    record = Type(
        key="p.R",
        name="R",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="p.R.a", name="a", type=TypeRef(name="string"), field_number=1)],
        extras={"reserved_ranges": [[9, 12], [100, 536870912]]},
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[record],
    )
    text = _emit(api)
    assert "reserved 9 to 11, 100 to max;" in text


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
def test_enum_values_preserve_numbers_and_zero_first() -> None:
    text = _emit(_rpc_api())
    assert "enum Role {" in text
    assert "ROLE_UNSPECIFIED = 0;" in text
    assert "ROLE_MEMBER = 1;" in text
    assert "ROLE_ADMIN = 2;" in text


def test_enum_allow_alias_option() -> None:
    enum = Type(
        key="p.E",
        name="E",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="p.E.A", name="A", value=0),
            EnumValue(key="p.E.B", name="B", value=1),
            EnumValue(key="p.E.C", name="C", value=1),
        ],
        extras={"allow_alias": True},
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[enum],
    )
    assert "option allow_alias = true;" in _emit(api)


def test_enum_non_zero_first_is_reordered_zero_first() -> None:
    """proto3 requires the first enum value to be 0; a non-zero-first source is reordered."""
    enum = Type(
        key="p.E",
        name="E",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="p.E.A", name="A", value=1),
            EnumValue(key="p.E.Z", name="Z", value=0),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[enum],
    )
    text = _emit(api)
    zero_pos = text.index("Z = 0;")
    one_pos = text.index("A = 1;")
    assert zero_pos < one_pos


def test_enum_without_zero_synthesizes_unspecified() -> None:
    enum = Type(
        key="p.Color",
        name="Color",
        kind=TypeKind.ENUM,
        enum_values=[EnumValue(key="p.Color.RED", name="RED", value=1)],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[enum],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    assert "COLOR_UNSPECIFIED = 0;" in text
    assert any(loss.subject == "synthesized-enum-zero" for loss in result.losses)


def test_enum_without_numbers_assigns_zero_based_indices() -> None:
    enum = Type(
        key="p.Color",
        name="Color",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="p.Color.RED", name="RED"),
            EnumValue(key="p.Color.GREEN", name="GREEN"),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[enum],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    assert "RED = 0;" in text
    assert "GREEN = 1;" in text
    assert any(loss.subject == "synthesized-enum-number" for loss in result.losses)


# ---------------------------------------------------------------------------
# Determinism + provenance
# ---------------------------------------------------------------------------
def test_emission_is_deterministic() -> None:
    api = _rpc_api()
    assert _emit(api) == _emit(api)


def test_provenance_records_source_and_defaults() -> None:
    result = ProtoEmitter().emit(_rpc_api())
    by_pointer = {record.pointer: record for record in result.provenance}
    assert by_pointer["/syntax"].provenance == Provenance.DEFAULT
    assert by_pointer["/package"].provenance == Provenance.SOURCE
    assert by_pointer["/messages/acme.user.User"].provenance == Provenance.SOURCE


# ---------------------------------------------------------------------------
# Losses for constructs proto3 cannot carry
# ---------------------------------------------------------------------------
def test_field_constraints_and_default_are_losses() -> None:
    record = Type(
        key="p.M",
        name="M",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="p.M.n",
                name="n",
                type=TypeRef(name="int32"),
                field_number=1,
                constraints=Constraints(minimum=0, maximum=10),
                default=5,
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[record],
    )
    subjects = {loss.subject for loss in ProtoEmitter().emit(api).losses}
    assert "field-constraints" in subjects
    assert "proto3-default" in subjects


def test_missing_field_number_is_synthesized_with_loss() -> None:
    record = Type(
        key="p.M",
        name="M",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.M.a", name="a", type=TypeRef(name="string")),
            CanonicalField(key="p.M.b", name="b", type=TypeRef(name="string"), field_number=5),
            CanonicalField(key="p.M.c", name="c", type=TypeRef(name="string")),
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[record],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    # Source number 5 is honoured; the numberless a/c fill the first free numbers (1, 2).
    assert "string a = 1;" in text
    assert "string b = 5;" in text
    assert "string c = 2;" in text
    assert any(loss.subject == "synthesized-field-number" for loss in result.losses)


def test_union_type_is_approximated_as_message_oneof() -> None:
    member_a = Type(key="p.A", name="A", kind=TypeKind.RECORD)
    member_b = Type(key="p.B", name="B", kind=TypeKind.RECORD)
    union = Type(
        key="p.Shape",
        name="Shape",
        kind=TypeKind.UNION,
        union_members=["p.A", "p.B"],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[member_a, member_b, union],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    assert "message Shape {" in text
    assert "oneof value {" in text
    assert ".p.A a = 1;" in text
    assert ".p.B b = 2;" in text
    assert any(loss.subject == "union-as-oneof" for loss in result.losses)


def test_out_of_package_type_records_loss() -> None:
    """A type outside the emitted package cannot be declared in a single-file proto → a loss."""
    local = Type(key="a.b.Local", name="Local", kind=TypeKind.RECORD)
    foreign = Type(key="x.y.Foreign", name="Foreign", kind=TypeKind.RECORD)
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="a.b", namespace="a.b"),
        types=[local, foreign],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    assert "message Local {" in text
    assert "message Foreign" not in text  # not in this package
    assert any(loss.subject == "out-of-package-type" for loss in result.losses)


def test_event_operation_without_response_uses_empty_and_records_losses() -> None:
    event_type = Type(key="p.Ping", name="Ping", kind=TypeKind.RECORD)
    service = Service(
        key="p.Pinger",
        name="Pinger",
        operations=[
            Operation(
                key="p.Pinger.OnPing",
                name="OnPing",
                kind=OperationKind.PUBLISH,
                messages=[
                    Message(key="p.Pinger.OnPing#e", role=MessageRole.EVENT, payload=TypeRef(name="p.Ping"))
                ],
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="p", namespace="p"),
        services=[service],
        types=[event_type],
    )
    result = ProtoEmitter().emit(api)
    text = str(result.files[0].content)
    # The event payload becomes the request; the missing response falls back to Empty.
    assert "rpc OnPing (.p.Ping) returns (.google.protobuf.Empty);" in text
    assert 'import "google/protobuf/empty.proto";' in text
    subjects = {loss.subject for loss in result.losses}
    assert "event-operation" in subjects
    assert "synthesized-response" in subjects


# ---------------------------------------------------------------------------
# Real buf: compile + round-trip (gated)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _BUF_AVAILABLE,
    reason="buf tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_BUF_BIN)",
)
class TestRealBuf:
    """Compile the emitted ``.proto`` with the real ``buf`` and normalize it back (fixed point)."""

    async def test_emitted_proto_compiles(self) -> None:
        """The acceptance criterion: the emitted document compiles via ``buf build``."""
        compiled = await compile_emitted_descriptor_set(_rpc_api())
        names = {f.name for f in compiled.files}
        assert "user.proto" in names
        # The well-known Timestamp import resolved into the descriptor set.
        assert "google/protobuf/timestamp.proto" in names

    async def test_round_trip_preserves_streaming_and_field_numbers(self) -> None:
        """Emit → compile → normalize reproduces the streaming modes and field numbers."""
        source = _rpc_api()
        compiled = await compile_emitted_descriptor_set(source)
        reimported = ProtoNormalizer().normalize(compiled)

        # Streaming preserved construct-for-construct (the MFX-12.1 acceptance criterion).
        ops = {op.key.rsplit(".", 1)[-1]: op for op in reimported.operations()}
        assert ops["GetUser"].streaming == StreamingMode.NONE
        assert ops["Chat"].streaming == StreamingMode.BIDIRECTIONAL

        # Field numbers survived the round trip.
        user = reimported.type_by_key("acme.user.User")
        assert user is not None
        numbers = {f.name: f.field_number for f in user.fields}
        assert numbers["id"] == 1
        assert numbers["role"] == 5
