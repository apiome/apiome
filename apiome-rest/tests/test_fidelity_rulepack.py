"""Unit tests for the fidelity rule-pack SPI — MFX-2.3 (#3840).

Pins the ticket's acceptance criteria and the SPI's contract:

* the **SPI drives the walk** — a :class:`FidelityRulePack` visits every construct,
  keys each verdict by the construct's canonical key, and assembles a sorted report;
* the **reference default** (:class:`CapabilityRulePack`) derives every verdict from
  the target's :class:`CapabilityProfile` (the six axes: operations, events, unions,
  nullability, constraints, field identity);
* the **engine consumes packs** — an emitter's declared pack
  (:meth:`Emitter.fidelity_rule_pack`) is honoured, and a custom pack refines a
  verdict the profile alone could not express;
* the **reference OpenAPI pack** upgrades a source field number from ``DROP`` to a
  lossless ``APPROX`` (preserved as an ``x-field-number`` extension);
* a pack is **pure and deterministic** — same inputs yield an equal, byte-identically
  serialized report, and evaluation never mutates the source model.
"""

from copy import deepcopy
from typing import List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import CapabilityProfile, Emitter
from app.fidelity_engine import compute_lossiness, compute_lossiness_for_emitter
from app.fidelity_rulepack import (
    CapabilityRulePack,
    FidelityRulePack,
    FidelityVerdict,
)
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity
from app.openapi_emitter import X_FIELD_NUMBER, OpenApiEmitter, OpenApiFidelityRulePack
from app.sample_emitter import SampleEmitter

# ---------------------------------------------------------------------------
# Profiles + model helpers (mirror the engine tests so behaviour lines up)
# ---------------------------------------------------------------------------

OPENAPI_PROFILE = CapabilityProfile(
    operations=True,
    events=True,
    unions=True,
    nullability=True,
    constraints=True,
    field_identity=False,
)

PROTOBUF_PROFILE = CapabilityProfile(
    operations=False,
    events=False,
    unions=False,
    nullability=False,
    constraints=False,
    field_identity=True,
)


def _rich_api() -> CanonicalApi:
    """A REST source touching every construct class the SPI reports on."""
    get_user = Operation(
        key="GET /users/{id}",
        name="getUser",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/users/{id}",
    )
    service = Service(key="Users", name="Users", operations=[get_user])
    channel = Channel(key="user/signedup", address="user/signedup", protocol="kafka")
    user = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="User.id", name="id", type=TypeRef(name="string", nullable=False)
            ),
            CanonicalField(
                key="User.age",
                name="age",
                type=TypeRef(name="integer", nullable=True),
                constraints=Constraints(minimum=0, maximum=120),
            ),
        ],
    )
    contact = Type(
        key="Contact", name="Contact", kind=TypeKind.UNION, union_members=["User", "Org"]
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
        types=[user, contact, money],
    )


def _numbered_api() -> CanonicalApi:
    """A model whose one record field carries a source field number."""
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
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        identity=ApiIdentity(name="Svc"),
        types=[typed],
    )


def _items_for(report: LossinessReport, construct: str) -> list:
    return [item for item in report.items if item.construct_key == construct]


# ---------------------------------------------------------------------------
# FidelityVerdict value type
# ---------------------------------------------------------------------------


def test_verdict_constructors_name_the_four_outcomes():
    """The four classmethods set the expected kind and default severity."""
    ok = FidelityVerdict.ok("carried")
    assert ok.kind is LossinessKind.OK and ok.severity is LossinessSeverity.INFO

    drop = FidelityVerdict.drop("gone")
    assert drop.kind is LossinessKind.DROP
    assert drop.severity is LossinessSeverity.CRITICAL  # default for a drop

    approx = FidelityVerdict.approx("demoted")
    assert approx.kind is LossinessKind.APPROX
    assert approx.severity is LossinessSeverity.WARN  # default for approx

    synth = FidelityVerdict.synth("invented")
    assert synth.kind is LossinessKind.SYNTH
    assert synth.severity is LossinessSeverity.WARN  # default for synth


def test_verdict_severity_and_mapping_overridable():
    """A caller can override the default severity and attach a target mapping."""
    v = FidelityVerdict.drop(
        "cosmetic", severity=LossinessSeverity.INFO, target_mapping="x → y"
    )
    assert v.severity is LossinessSeverity.INFO
    assert v.target_mapping == "x → y"


def test_verdict_is_frozen():
    """Verdicts are immutable so a shared instance cannot be mutated in place."""
    v = FidelityVerdict.ok("carried")
    with pytest.raises(Exception):
        v.message = "changed"


# ---------------------------------------------------------------------------
# The SPI drive loop keys verdicts by construct
# ---------------------------------------------------------------------------


class _StubPack(FidelityRulePack):
    """A minimal pack whose verdicts are fixed, to exercise the drive loop alone."""

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        return FidelityVerdict.drop("op dropped")

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        return FidelityVerdict.ok("channel kept")

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        return FidelityVerdict.ok("type kept")

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        # Two independent losses on every field, to prove lists are supported.
        return [
            FidelityVerdict.approx("aspect one"),
            FidelityVerdict.synth("aspect two"),
        ]


def test_drive_loop_keys_each_verdict_by_construct():
    """`evaluate` records one item per verdict, keyed by the construct's canonical key."""
    report = _StubPack(PROTOBUF_PROFILE).evaluate(_rich_api())

    # Operation, channel, and each named type each produced their single verdict.
    assert _items_for(report, "GET /users/{id}")[0].kind is LossinessKind.DROP
    assert _items_for(report, "user/signedup")[0].kind is LossinessKind.OK
    assert _items_for(report, "Contact")[0].kind is LossinessKind.OK
    # Each of the RECORD's two fields produced two verdicts, keyed by the field key.
    for field_key in ("User.id", "User.age"):
        kinds = sorted(i.kind.value for i in _items_for(report, field_key))
        assert kinds == ["approx", "synth"]
    # A non-record type (union/scalar) has no fields walked.
    assert len(_items_for(report, "Money")) == 1


def test_abstract_pack_cannot_be_instantiated():
    """`FidelityRulePack` is abstract — a concrete pack must implement the hooks."""
    with pytest.raises(TypeError):
        FidelityRulePack(PROTOBUF_PROFILE)  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# CapabilityRulePack: the profile-derived default
# ---------------------------------------------------------------------------


def test_capability_pack_openapi_is_lossless():
    """The rich REST source is carried cleanly by the OpenAPI profile."""
    report = CapabilityRulePack(OPENAPI_PROFILE, "OpenAPI 3.1").evaluate(_rich_api())
    assert report.is_lossless
    assert all(item.kind is LossinessKind.OK for item in report.items)


def test_capability_pack_protobuf_reports_all_losses():
    """The lossy Protobuf profile drops operations/channel/union and degrades fields."""
    report = CapabilityRulePack(PROTOBUF_PROFILE, "Protobuf").evaluate(_rich_api())

    assert _items_for(report, "GET /users/{id}")[0].kind is LossinessKind.DROP
    assert _items_for(report, "user/signedup")[0].kind is LossinessKind.DROP
    assert _items_for(report, "Contact")[0].kind is LossinessKind.DROP
    # Scalar constraint demoted.
    assert _items_for(report, "Money")[0].kind is LossinessKind.APPROX
    # Required, unnumbered field: non-null lost (APPROX) + field number synthesized.
    id_kinds = {i.kind for i in _items_for(report, "User.id")}
    assert id_kinds == {LossinessKind.APPROX, LossinessKind.SYNTH}


def test_capability_pack_matches_engine_entrypoint():
    """`compute_lossiness` with no explicit pack builds exactly a CapabilityRulePack."""
    api = _rich_api()
    via_engine = compute_lossiness(api, PROTOBUF_PROFILE, target_label="Protobuf")
    via_pack = CapabilityRulePack(PROTOBUF_PROFILE, "Protobuf").evaluate(api)
    assert via_engine.model_dump() == via_pack.model_dump()


# ---------------------------------------------------------------------------
# Emitter wiring: an emitter declares (or omits) a pack
# ---------------------------------------------------------------------------


def test_base_and_sample_emitters_declare_no_pack():
    """A target with no special rules declares no pack; the engine uses the default."""
    assert Emitter.fidelity_rule_pack() is None
    assert SampleEmitter.fidelity_rule_pack() is None


def test_openapi_emitter_declares_reference_pack():
    """The OpenAPI emitter ships its reference pack alongside itself."""
    assert OpenApiEmitter.fidelity_rule_pack() is OpenApiFidelityRulePack
    assert issubclass(OpenApiFidelityRulePack, CapabilityRulePack)


# ---------------------------------------------------------------------------
# Reference OpenAPI pack refines the field-number verdict
# ---------------------------------------------------------------------------


def test_openapi_pack_preserves_field_number_as_extension():
    """A source field number is an APPROX (info), not a DROP, on the OpenAPI target."""
    report = compute_lossiness_for_emitter(_numbered_api(), OpenApiEmitter)
    item = _items_for(report, "Msg.a")[0]
    assert item.kind is LossinessKind.APPROX
    assert item.severity is LossinessSeverity.INFO
    assert X_FIELD_NUMBER in (item.target_mapping or "")


def test_default_pack_drops_field_number_that_openapi_pack_keeps():
    """The refinement is the pack's: the raw profile default still DROPs the number."""
    api = _numbered_api()
    # Raw profile path → CapabilityRulePack → DROP (info).
    default = compute_lossiness(api, OPENAPI_PROFILE)
    assert _items_for(default, "Msg.a")[0].kind is LossinessKind.DROP
    # Emitter path → OpenApiFidelityRulePack → APPROX. The engine consumed the pack.
    via_pack = compute_lossiness_for_emitter(api, OpenApiEmitter)
    assert _items_for(via_pack, "Msg.a")[0].kind is LossinessKind.APPROX


def test_openapi_pack_leaves_other_verdicts_unchanged():
    """Only the field-number verdict is refined; the rest defers to the default."""
    api = _rich_api()  # no field numbers → refinement never triggers
    via_pack = compute_lossiness_for_emitter(api, OpenApiEmitter)
    via_default = compute_lossiness(
        api, OpenApiEmitter.capability_profile(), target_label=OpenApiEmitter.label
    )
    assert via_pack.model_dump() == via_default.model_dump()
    assert via_pack.is_lossless


# ---------------------------------------------------------------------------
# The engine consumes a caller-supplied pack
# ---------------------------------------------------------------------------


def test_compute_lossiness_honours_explicit_rule_pack():
    """An explicit `rule_pack` overrides the profile-derived default in the engine."""

    class _AllOkPack(CapabilityRulePack):
        def type_verdict(self, type_: Type) -> FidelityVerdict:
            return FidelityVerdict.ok("forced ok")

    api = _rich_api()
    pack = _AllOkPack(PROTOBUF_PROFILE, "Protobuf")
    report = compute_lossiness(api, PROTOBUF_PROFILE, rule_pack=pack)
    # Every named type is OK despite the lossy profile, because the pack said so.
    for key in ("User", "Contact", "Money"):
        assert _items_for(report, key)[0].kind is LossinessKind.OK


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


def test_pack_is_deterministic_and_serializes_identically():
    """Two evaluations over the same inputs are equal and serialize byte-identically."""
    api = _rich_api()
    pack = CapabilityRulePack(PROTOBUF_PROFILE, "Protobuf")
    a = pack.evaluate(api)
    b = CapabilityRulePack(PROTOBUF_PROFILE, "Protobuf").evaluate(api)
    assert a.model_dump_json() == b.model_dump_json()


def test_pack_does_not_mutate_source_model():
    """Evaluating a pack leaves the source model untouched (pure)."""
    api = _rich_api()
    before = deepcopy(api).model_dump()
    CapabilityRulePack(PROTOBUF_PROFILE, "Protobuf").evaluate(api)
    assert api.model_dump() == before
