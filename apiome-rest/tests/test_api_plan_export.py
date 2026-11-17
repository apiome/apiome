"""API plans on export — APX-1.2 (#6099).

A revision that an API product includes carries the product's plans on its canonical model
(``extras["apiome_plans"]``, put there by :func:`app.export_source.attach_plans`). These tests pin
what each export does with them:

* the OpenAPI emitter writes them as the root ``x-apiome-plans`` extension in every dialect (3.1,
  3.0 and Swagger 2.0, whose downgrade rebuilds the root), and the document stays valid;
* the fidelity report says so — an ``ok`` root item for OpenAPI, an ``info`` ``drop`` for a target
  with no equivalent (Proto3, GraphQL);
* a model without plans exports and reports exactly as before;
* a failure to read the plans never fails the export.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app import api_plan_store, export_source
from app.api_plans import PLANS_EXTENSION_KEY, PLANS_EXTRAS_KEY
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Operation, OperationKind, Service
from app.emitter import get_emitter
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_validator import validate_openapi_document

_PLANS: List[Dict[str, Any]] = [
    {
        "product": "payments",
        "product_name": "Payments",
        "plan": "standard",
        "name": "Standard",
        "state": "published",
        "auth": {"strategy": "key_auth", "header_name": "X-API-Key"},
        "limits": [{"window": "minute", "requests": 100}, {"window": "day", "requests": 50000}],
        "approval": "manual",
        "declared_only": True,
        "environments": ["kong-prod-cp"],
    }
]


def _model(plans: List[Dict[str, Any]] | None = None) -> CanonicalApi:
    """A one-operation REST model, with ``plans`` on its extras when given."""
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Payments API"),
        version="1.4.0",
        title="Payments API",
        services=[
            Service(
                key="payments",
                name="payments",
                operations=[
                    Operation(
                        key="GET /payments",
                        name="listPayments",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/payments",
                    )
                ],
            )
        ],
    )
    if plans is not None:
        api.extras[PLANS_EXTRAS_KEY] = plans
    return api


@pytest.mark.parametrize("dialect", ["3.1", "3.0", "2.0"])
def test_openapi_writes_the_plans_in_every_dialect(dialect: str) -> None:
    result = OpenApiEmitter().emit(_model(_PLANS), opts=OpenApiEmitOptions(openapi_version=dialect))
    document = result.document
    assert document[PLANS_EXTENSION_KEY] == _PLANS
    if dialect == "3.1":
        assert validate_openapi_document(document) == []


def test_openapi_without_plans_has_no_extension() -> None:
    assert PLANS_EXTENSION_KEY not in OpenApiEmitter().emit(_model()).document


def test_the_openapi_fidelity_report_keeps_the_plans() -> None:
    report = compute_lossiness_for_emitter(_model(_PLANS), OpenApiEmitter)
    root = [item for item in report.items if item.construct_key == "" and "plan" in item.message]
    assert len(root) == 1
    assert root[0].kind is LossinessKind.OK and root[0].target_mapping == f"root {PLANS_EXTENSION_KEY}"


@pytest.mark.parametrize("target", ["proto3", "graphql"])
def test_a_target_without_an_equivalent_drops_the_plans(target: str) -> None:
    report = compute_lossiness_for_emitter(_model(_PLANS), get_emitter(target))
    dropped = [item for item in report.items if item.construct_key == "" and PLANS_EXTENSION_KEY in item.message]
    assert len(dropped) == 1
    assert dropped[0].kind is LossinessKind.DROP and dropped[0].severity is LossinessSeverity.INFO
    assert "1 API product plan (x-apiome-plans) dropped" in dropped[0].message


@pytest.mark.parametrize("target", ["openapi", "proto3"])
def test_a_model_without_plans_reports_as_before(target: str) -> None:
    emitter = OpenApiEmitter if target == "openapi" else get_emitter(target)
    report = compute_lossiness_for_emitter(_model(), emitter)
    assert not [item for item in report.items if "x-apiome-plans" in item.message]


def test_attach_plans_puts_the_entries_on_the_model(monkeypatch) -> None:
    monkeypatch.setattr(api_plan_store, "plans_for_revision", lambda t, a, r: _PLANS)
    api = _model()
    export_source.attach_plans(api, "t", "a", "r")
    assert api.extras[PLANS_EXTRAS_KEY] == _PLANS


def test_attach_plans_leaves_a_model_without_plans_untouched(monkeypatch) -> None:
    monkeypatch.setattr(api_plan_store, "plans_for_revision", lambda t, a, r: [])
    api = _model()
    export_source.attach_plans(api, "t", "a", "r")
    assert PLANS_EXTRAS_KEY not in api.extras


def test_a_plan_read_failure_never_fails_the_export(monkeypatch) -> None:
    def boom(*args: Any) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(api_plan_store, "plans_for_revision", boom)
    api = _model()
    export_source.attach_plans(api, "t", "a", "r")
    assert PLANS_EXTRAS_KEY not in api.extras
