"""API Blueprint fidelity pack — MFX-18.2 (#3906).

:class:`app.apiblueprint_emitter.ApiblueprintFidelityRulePack` predicts, before an emit, the three
loss classes the epic names for API Blueprint:

* **non-REST** — operations with no HTTP binding, event operations and channels are a ``DROP``;
* **MSON type limits** — what MSON writes differently (wider scalars as ``number`` / ``string``,
  aliases, named scalars and maps as named types) is an ``APPROX``; unions are a ``DROP``;
* **constraints** — a ``DROP`` wherever they sit (field, parameter, named scalar, alias, record),
  recorded beside the construct's ``APPROX`` rather than folded into it.

Also covered: the base pack's list hooks (:meth:`~app.fidelity_rulepack.FidelityRulePack.operation_verdicts`,
:meth:`~app.fidelity_rulepack.FidelityRulePack.type_verdicts`) default to the single verdict, and the
prediction agrees with what the writer reports.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from app.apiblueprint_emitter import ApiblueprintEmitter, ApiblueprintFidelityRulePack
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_rulepack import CapabilityRulePack
from app.lossiness import LossinessKind, LossinessSeverity

_RULES = Constraints(pattern="^[A-Z]+$", max_length=8)


def _api(*, operations=(), types=(), channels=(), paradigm=ApiParadigm.REST) -> CanonicalApi:
    return CanonicalApi(
        paradigm=paradigm,
        format="openapi-3.1",
        identity=ApiIdentity(name="Shop"),
        title="Shop",
        services=[Service(key="svc", name="svc", operations=list(operations))],
        types=list(types),
        channels=list(channels),
    )


def _op(key: str = "GET /items", *, method: str | None = "GET", path: str | None = "/items", **kw) -> Operation:
    return Operation(key=key, name=key, kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE), http_method=method,
                     http_path=path, **kw)


def _items(api: CanonicalApi) -> Dict[str, List]:
    """Construct key → its report items, in the report's order."""
    out: Dict[str, List] = {}
    for item in compute_lossiness_for_emitter(api, ApiblueprintEmitter()).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _kinds(api: CanonicalApi, key: str) -> set:
    """The kinds reported for ``key`` (empty when nothing is reported, as for a field that loses nothing)."""
    return {item.kind for item in _items(api).get(key, [])}


# ===========================================================================
# Non-REST
# ===========================================================================


@pytest.mark.parametrize(
    "operation",
    [
        _op("Query.items", method=None, path=None),  # GraphQL
        _op("svc.GetItem", method=None, path=None, kind=OperationKind.REQUEST_RESPONSE),  # gRPC
        _op("POST /events", method="POST", path="/events", kind=OperationKind.PUBLISH),  # event
    ],
    ids=["graphql", "grpc", "event"],
)
def test_non_rest_operations_are_dropped(operation: Operation) -> None:
    api = _api(operations=[operation], types=[Type(key="Item", name="Item", kind=TypeKind.RECORD)])
    assert _kinds(api, operation.key) == {LossinessKind.DROP}


def test_channels_are_dropped() -> None:
    api = _api(types=[Type(key="Item", name="Item", kind=TypeKind.RECORD)],
               channels=[Channel(key="orders", name="orders", address="orders")])
    assert _kinds(api, "orders") == {LossinessKind.DROP}


def test_an_http_operation_is_ok_when_nothing_is_lost() -> None:
    api = _api(operations=[_op()])
    assert _kinds(api, "GET /items") == {LossinessKind.OK}


# ===========================================================================
# MSON type limits
# ===========================================================================


@pytest.mark.parametrize(("scalar", "kinds"), [("i64", {LossinessKind.APPROX}), ("date-time", {LossinessKind.APPROX}),
                                                 ("double", set()), ("string", set())])
def test_scalars_mson_writes_differently_are_approx(scalar: str, kinds: set) -> None:
    record = Type(key="Row", name="Row", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Row.v", name="v", type=TypeRef(name=scalar, nullable=False), field_number=1),
    ])
    assert _kinds(_api(types=[record]), "Row.v") == kinds


@pytest.mark.parametrize(
    ("type_", "kind"),
    [
        (Type(key="T", name="T", kind=TypeKind.ALIAS, aliased=TypeRef(name="string")), LossinessKind.APPROX),
        (Type(key="T", name="T", kind=TypeKind.SCALAR), LossinessKind.APPROX),
        (Type(key="T", name="T", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
              value_type=TypeRef(name="string")), LossinessKind.APPROX),
        (Type(key="T", name="T", kind=TypeKind.UNION, union_members=["string", "double"]), LossinessKind.DROP),
        (Type(key="T", name="T", kind=TypeKind.RECORD), LossinessKind.OK),
    ],
    ids=["alias", "scalar", "map", "union", "record"],
)
def test_named_types_by_kind(type_: Type, kind: LossinessKind) -> None:
    assert _kinds(_api(types=[type_]), "T") == {kind}


def test_a_named_scalar_is_no_longer_said_to_be_demoted_to_documentation() -> None:
    scalar = Type(key="Code", name="Code", kind=TypeKind.SCALAR, constraints=_RULES)
    messages = [item.message for item in _items(_api(types=[scalar]))["Code"]]
    assert not any("documentation" in message for message in messages)


# ===========================================================================
# Constraints: DROP wherever they sit
# ===========================================================================


def _constraint_drop(api: CanonicalApi, key: str):
    drops = [item for item in _items(api)[key] if item.kind is LossinessKind.DROP]
    assert len(drops) == 1, _items(api)[key]
    return drops[0]


def test_field_constraints_are_dropped() -> None:
    record = Type(key="Row", name="Row", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Row.code", name="code", type=TypeRef(name="string"), field_number=1, constraints=_RULES),
    ])
    drop = _constraint_drop(_api(types=[record]), "Row.code")
    assert "max_length, pattern of the field" in drop.message
    assert drop.severity is LossinessSeverity.WARN


@pytest.mark.parametrize("kind", [TypeKind.SCALAR, TypeKind.ALIAS, TypeKind.RECORD])
def test_type_constraints_are_dropped_beside_how_the_type_is_written(kind: TypeKind) -> None:
    type_ = Type(key="Code", name="Code", kind=kind, constraints=_RULES,
                 aliased=TypeRef(name="string") if kind is TypeKind.ALIAS else None)
    api = _api(types=[type_])
    drop = _constraint_drop(api, "Code")
    assert "max_length, pattern of the type" in drop.message
    if kind is not TypeKind.RECORD:  # the APPROX for being written as a named type stays
        assert LossinessKind.APPROX in _kinds(api, "Code")


def test_parameter_constraints_are_dropped_beside_the_operation_approx() -> None:
    operation = _op(parameters=[
        Parameter(key="GET /items#query.q", name="q", location=ParameterLocation.QUERY, type=TypeRef(name="string"),
                  constraints=Constraints(min_length=2)),
        Parameter(key="GET /items#cookie.s", name="s", location=ParameterLocation.COOKIE, type=TypeRef(name="string")),
    ])
    api = _api(operations=[operation])
    assert _kinds(api, "GET /items") == {LossinessKind.APPROX, LossinessKind.DROP}
    assert "min_length of the parameter 'q'" in _constraint_drop(api, "GET /items").message


def test_the_single_verdict_is_the_most_severe() -> None:
    pack = ApiblueprintFidelityRulePack(ApiblueprintEmitter.capability_profile(), "API Blueprint")
    scalar = Type(key="Code", name="Code", kind=TypeKind.SCALAR, constraints=_RULES)
    pack.evaluate(_api(types=[scalar]))
    assert pack.type_verdict(scalar).kind is LossinessKind.DROP
    assert [v.kind for v in pack.type_verdicts(scalar)] == [LossinessKind.APPROX, LossinessKind.DROP]


# ===========================================================================
# The prediction agrees with the export
# ===========================================================================


def test_every_constraint_drop_is_also_a_writer_loss() -> None:
    operation = _op(parameters=[Parameter(key="GET /items#query.q", name="q", location=ParameterLocation.QUERY,
                                          type=TypeRef(name="string"), constraints=Constraints(min_length=2))])
    types = [
        Type(key="Code", name="Code", kind=TypeKind.SCALAR, constraints=_RULES),
        Type(key="Row", name="Row", kind=TypeKind.RECORD, constraints=Constraints(min_items=1), fields=[
            CanonicalField(key="Row.code", name="code", type=TypeRef(name="Code"), field_number=1, constraints=_RULES),
        ]),
    ]
    api = _api(operations=[operation], types=types)
    predicted = {key for key, items in _items(api).items()
                 if any("validation facets" in item.message for item in items)}
    written = {loss.pointer for loss in ApiblueprintEmitter().emit(api).losses
               if loss.subject == "constraints-dropped" and loss.kind is LossKind.NA}
    assert predicted == written == {"GET /items", "Code", "Row", "Row.code"}


# ===========================================================================
# Base pack hooks
# ===========================================================================


class _OnePack(CapabilityRulePack):
    target_label = "One"


def test_the_list_hooks_default_to_the_single_verdict() -> None:
    pack = _OnePack(ApiblueprintEmitter.capability_profile(), "One")
    operation, type_ = _op(), Type(key="T", name="T", kind=TypeKind.RECORD)
    assert pack.operation_verdicts(operation) == [pack.operation_verdict(operation)]
    assert pack.type_verdicts(type_) == [pack.type_verdict(type_)]
