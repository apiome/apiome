"""Unit tests for the fidelity computation engine — MFX-2.2 (#3839).

Pins the ticket's acceptance criteria and the engine's contract:

* **rich source → Protobuf** reports unions (``DROP``), constraints (``APPROX``),
  nullability (``APPROX``), and field numbers (``SYNTH``) correctly;
* a **clean REST → OpenAPI** export reports mostly ``OK`` (lossless);
* the engine is **pure and deterministic** — same inputs yield an equal, and
  byte-identically serialized, report, and it never mutates the source model;
* per-construct verdicts key off the target's :class:`CapabilityProfile`:
  operations vs event operations, channels, unions, per-field nullability /
  constraints / field identity, and scalar constraints.
"""

from copy import deepcopy

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import CapabilityProfile
from app.fidelity_engine import compute_lossiness, compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity
from app.openapi_emitter import OpenApiEmitter

# ---------------------------------------------------------------------------
# Capability profiles under test
# ---------------------------------------------------------------------------

# OpenAPI 3.1: carries operations, events, unions, nullability, and constraints;
# no stable field numbers. Mirrors ``OpenApiEmitter.capability_profile()``.
OPENAPI_PROFILE = CapabilityProfile(
    operations=True,
    events=True,
    unions=True,
    nullability=True,
    constraints=True,
    field_identity=False,
)

# Protobuf messages: the lossiest data-schema target. No operations, no events, no
# discriminated unions, no explicit nullability, no validation constraints — but it
# *requires* stable field numbers (which a REST source lacks, so they are
# synthesized).
PROTOBUF_PROFILE = CapabilityProfile(
    operations=False,
    events=False,
    unions=False,
    nullability=False,
    constraints=False,
    field_identity=True,
)


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------


def _user_type() -> Type:
    """A record with a required plain field, a constrained field, and a required one."""
    return Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            # Required (non-null), no constraints, no field number.
            CanonicalField(
                key="User.id",
                name="id",
                type=TypeRef(name="string", nullable=False),
            ),
            # Nullable, constrained (numeric range).
            CanonicalField(
                key="User.age",
                name="age",
                type=TypeRef(name="integer", nullable=True),
                constraints=Constraints(minimum=0, maximum=120),
            ),
            # Required (non-null) and constrained (pattern) — two losses at once.
            CanonicalField(
                key="User.email",
                name="email",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(pattern=r".+@.+"),
            ),
        ],
    )


def _rich_api() -> CanonicalApi:
    """A REST source exercising every construct class the engine reports on.

    An operation, an event channel, a record with lossy fields, a discriminated
    union, an enum, and a scalar carrying a constraint — enough to distinguish a
    faithful target (OpenAPI) from a lossy one (Protobuf).
    """
    get_user = Operation(
        key="GET /users/{id}",
        name="getUser",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/users/{id}",
    )
    service = Service(key="Users", name="Users", operations=[get_user])
    channel = Channel(key="user/signedup", address="user/signedup", protocol="kafka")
    union = Type(
        key="Contact",
        name="Contact",
        kind=TypeKind.UNION,
        union_members=["User", "Org"],
    )
    status = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.ACTIVE", name="ACTIVE"),
            EnumValue(key="Status.CLOSED", name="CLOSED"),
        ],
    )
    money = Type(
        key="Money",
        name="Money",
        kind=TypeKind.SCALAR,
        constraints=Constraints(pattern=r"^\d+\.\d{2}$"),
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Users API"),
        services=[service],
        channels=[channel],
        types=[_user_type(), union, status, money],
    )


def _items_for(report: LossinessReport, construct: str) -> list:
    """Return the items in ``report`` for a given construct key."""
    return [item for item in report.items if item.construct_key == construct]


# ---------------------------------------------------------------------------
# Acceptance: clean REST → OpenAPI is (mostly) OK
# ---------------------------------------------------------------------------


def test_rest_to_openapi_is_lossless():
    """A REST source exported to OpenAPI carries every construct: all OK, lossless."""
    report = compute_lossiness(_rich_api(), OPENAPI_PROFILE, target_label="OpenAPI 3.1")

    assert report.is_lossless
    assert report.worst_severity is None
    assert all(item.kind is LossinessKind.OK for item in report.items)
    # Every top-level construct is accounted for (operation, channel, 4 types).
    assert report.kind_counts["ok"] == report.total
    for key in ("GET /users/{id}", "user/signedup", "User", "Contact", "Status", "Money"):
        assert _items_for(report, key), f"missing OK item for {key}"


def test_openapi_emitter_profile_matches_helper():
    """The engine's convenience wrapper reads the emitter's real capability profile."""
    api = _rich_api()
    via_emitter = compute_lossiness_for_emitter(api, OpenApiEmitter)
    via_profile = compute_lossiness(
        api, OpenApiEmitter.capability_profile(), target_label=OpenApiEmitter.label
    )
    assert via_emitter.model_dump() == via_profile.model_dump()
    assert via_emitter.is_lossless


# ---------------------------------------------------------------------------
# Acceptance: rich source → Protobuf reports unions/constraints/nullability/fields
# ---------------------------------------------------------------------------


def test_rich_source_to_protobuf_reports_all_losses():
    """Rich REST source → Protobuf: unions DROP, constraints/nullability APPROX, fields SYNTH."""
    report = compute_lossiness(_rich_api(), PROTOBUF_PROFILE, target_label="Protobuf")

    assert not report.is_lossless
    assert report.worst_severity is LossinessSeverity.CRITICAL

    # Union → DROP (critical): the discriminated alternatives are unrepresentable.
    union_items = _items_for(report, "Contact")
    assert len(union_items) == 1
    assert union_items[0].kind is LossinessKind.DROP
    assert union_items[0].severity is LossinessSeverity.CRITICAL

    # Operation and channel → DROP (critical): a types-only target carries neither.
    assert _items_for(report, "GET /users/{id}")[0].kind is LossinessKind.DROP
    assert _items_for(report, "user/signedup")[0].kind is LossinessKind.DROP

    # A required, unconstrained field with no source field number: non-null lost
    # (APPROX) + a field number synthesized (SYNTH).
    id_kinds = {item.kind for item in _items_for(report, "User.id")}
    assert id_kinds == {LossinessKind.APPROX, LossinessKind.SYNTH}

    # A nullable, constrained field: constraints demoted (APPROX) + SYNTH field
    # number; no nullability loss (it was already nullable).
    age_items = _items_for(report, "User.age")
    age_kinds = {item.kind for item in age_items}
    assert age_kinds == {LossinessKind.APPROX, LossinessKind.SYNTH}
    approx = next(i for i in age_items if i.kind is LossinessKind.APPROX)
    assert "constraint" in (approx.target_mapping or "").lower()

    # A required *and* constrained field: two APPROX (nullability + constraints) and
    # one SYNTH — three independent losses on one construct.
    email_kinds = sorted(i.kind.value for i in _items_for(report, "User.email"))
    assert email_kinds == ["approx", "approx", "synth"]

    # The scalar's constraint is demoted (APPROX); the enum still carries (OK).
    assert _items_for(report, "Money")[0].kind is LossinessKind.APPROX
    assert _items_for(report, "Status")[0].kind is LossinessKind.OK


def test_synthesized_field_number_is_synth_kind():
    """A target that requires field numbers synthesizes them (SYNTH) for a source lacking them."""
    report = compute_lossiness(_rich_api(), PROTOBUF_PROFILE)
    synths = report.items_of_kind(LossinessKind.SYNTH)
    assert {i.construct_key for i in synths} == {"User.id", "User.age", "User.email"}
    assert all("field number" in (i.target_mapping or "") for i in synths)


# ---------------------------------------------------------------------------
# Per-capability behaviour
# ---------------------------------------------------------------------------


def test_operations_dropped_for_types_only_target():
    """Every operation is a critical DROP when the target cannot carry operations."""
    api = _rich_api()
    profile = OPENAPI_PROFILE.model_copy(update={"operations": False})
    report = compute_lossiness(api, profile)
    op_item = _items_for(report, "GET /users/{id}")[0]
    assert op_item.kind is LossinessKind.DROP
    assert op_item.severity is LossinessSeverity.CRITICAL


def test_publish_operation_needs_event_capability_not_operation_capability():
    """A publish/subscribe operation is governed by ``events``, not ``operations``."""
    publish = Operation(
        key="publish user/signedup",
        name="onSignup",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="Events"),
        services=[Service(key="S", name="S", operations=[publish])],
    )
    # operations=True but events=False → the publish operation still drops.
    profile = CapabilityProfile(operations=True, events=False)
    report = compute_lossiness(api, profile)
    assert _items_for(report, "publish user/signedup")[0].kind is LossinessKind.DROP

    # events=True (operations irrelevant) → it carries.
    profile_ok = CapabilityProfile(operations=False, events=True)
    report_ok = compute_lossiness(api, profile_ok)
    assert _items_for(report_ok, "publish user/signedup")[0].kind is LossinessKind.OK


def test_channel_dropped_without_events_capability():
    """An event channel is a critical DROP on a target that cannot carry events."""
    report = compute_lossiness(_rich_api(), PROTOBUF_PROFILE)
    channel_item = _items_for(report, "user/signedup")[0]
    assert channel_item.kind is LossinessKind.DROP
    assert channel_item.severity is LossinessSeverity.CRITICAL


def test_source_field_number_dropped_when_target_lacks_identity():
    """A source field number is an info DROP when the target has no field identity."""
    typed = Type(
        key="Msg",
        name="Msg",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="Msg.a",
                name="a",
                type=TypeRef(name="string"),
                field_number=1,
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        identity=ApiIdentity(name="Svc"),
        types=[typed],
    )
    # OpenAPI has field_identity=False → the number is dropped (info).
    report = compute_lossiness(api, OPENAPI_PROFILE)
    item = next(i for i in _items_for(report, "Msg.a"))
    assert item.kind is LossinessKind.DROP
    assert item.severity is LossinessSeverity.INFO


def test_present_field_number_is_not_synthesized():
    """A field that already has a number is not re-synthesized on a field-identity target."""
    typed = Type(
        key="Msg",
        name="Msg",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="Msg.a",
                name="a",
                type=TypeRef(name="string", nullable=True),
                field_number=7,
            )
        ],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        identity=ApiIdentity(name="Svc"),
        types=[typed],
    )
    report = compute_lossiness(api, PROTOBUF_PROFILE)
    # Nullable, unconstrained, already-numbered field → no field-level loss at all.
    assert _items_for(report, "Msg.a") == []


def test_enum_map_alias_types_carry_ok():
    """Enum, map, and alias types are representable everywhere → OK, even on Protobuf."""
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="Data"),
        types=[
            Type(key="E", name="E", kind=TypeKind.ENUM,
                 enum_values=[EnumValue(key="E.X", name="X")]),
            Type(key="M", name="M", kind=TypeKind.MAP,
                 value_type=TypeRef(name="string")),
            Type(key="A", name="A", kind=TypeKind.ALIAS,
                 aliased=TypeRef(name="string")),
        ],
    )
    report = compute_lossiness(api, PROTOBUF_PROFILE)
    assert report.is_lossless
    for key in ("E", "M", "A"):
        assert _items_for(report, key)[0].kind is LossinessKind.OK


def test_scalar_without_constraints_is_ok_on_lossy_target():
    """An unconstrained scalar carries cleanly even where constraints are unsupported."""
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="Data"),
        types=[Type(key="Id", name="Id", kind=TypeKind.SCALAR)],
    )
    report = compute_lossiness(api, PROTOBUF_PROFILE)
    assert _items_for(report, "Id")[0].kind is LossinessKind.OK


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


def test_empty_api_is_lossless():
    """An API with no constructs produces an empty, lossless report."""
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Empty"),
    )
    report = compute_lossiness(api, PROTOBUF_PROFILE)
    assert report.total == 0
    assert report.is_lossless
    # Counts are still zero-filled for every enum member.
    assert report.kind_counts == {"drop": 0, "approx": 0, "synth": 0, "ok": 0}


def test_deterministic_and_serializes_identically():
    """Two computations over the same inputs are equal and serialize byte-identically."""
    api = _rich_api()
    a = compute_lossiness(api, PROTOBUF_PROFILE, target_label="Protobuf")
    b = compute_lossiness(api, PROTOBUF_PROFILE, target_label="Protobuf")
    assert a.model_dump() == b.model_dump()
    assert a.model_dump_json() == b.model_dump_json()
    # The report round-trips through JSON unchanged.
    assert LossinessReport.model_validate_json(a.model_dump_json()).model_dump() == a.model_dump()


def test_engine_does_not_mutate_source_model():
    """Computing a report leaves the source model untouched (pure function)."""
    api = _rich_api()
    before = deepcopy(api).model_dump()
    compute_lossiness(api, PROTOBUF_PROFILE)
    assert api.model_dump() == before


def test_target_label_appears_in_messages_but_not_verdicts():
    """The label is cosmetic: it changes messages, never kinds/severities."""
    api = _rich_api()
    labelled = compute_lossiness(api, PROTOBUF_PROFILE, target_label="Protobuf")
    default = compute_lossiness(api, PROTOBUF_PROFILE)
    # Same verdicts regardless of label.
    assert [(i.construct_key, i.kind, i.severity) for i in labelled.items] == \
        [(i.construct_key, i.kind, i.severity) for i in default.items]
    # But the label is woven into the human message.
    assert any("Protobuf" in i.message for i in labelled.items)
