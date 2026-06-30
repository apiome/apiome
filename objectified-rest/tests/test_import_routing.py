"""Unit tests for Project-vs-Catalog import routing (MFI-23.7, #4016).

Exercise :func:`app.import_routing.decide_import_routing` directly against small stub
adapters and hand-built canonical models, covering the ticket's acceptance criteria:

* OpenAPI/Swagger (incl. TypeSpec-emitted OpenAPI) → publishable **Project**;
* a non-OpenAPI OpenAPI-worthy source (gRPC/GraphQL/AsyncAPI/OData/…) → non-publishable
  **catalog item**;
* a pure data-schema source (Avro/Protobuf-schema/JSON-Schema/XSD) → catalog item flagged
  ``schemas_only``;
* the decision + reason is stored (round-trips through :meth:`as_dict`).

A second block runs the routing through the in-process pipeline
(:func:`app.import_source_pipeline.run_adapter_import_job`) to prove the decision is
recorded on the completed-job summary and a ``ROUTING_DECIDED`` event is emitted.
"""

from __future__ import annotations

import base64
from typing import Any, List, Optional

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Channel,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
)
from app.import_routing import (
    PUBLISHABLE_FORMATS,
    ImportRoutingDecision,
    ImportTarget,
    decide_import_routing,
)
from app.import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    InputKind,
)
from app.import_source_pipeline import run_adapter_import_job
from app.models import SpecImportJobStatus

# ---------------------------------------------------------------------------
# Stub adapters + canonical-model builders
# ---------------------------------------------------------------------------


class _StubAdapter(ImportSource):
    """A minimal adapter that returns a fixed canonical model from :meth:`normalize`.

    Not registered (no ``register=True``) so it never pollutes the global registry; it
    just carries a ``key`` and serves a pre-built model for the routing/pipeline tests.
    """

    input_kinds = (InputKind.PASTE,)

    def __init__(self, key: str, paradigm: ApiParadigm, model: CanonicalApi) -> None:
        self._key = key
        self._paradigm = paradigm
        self._model = model

    @property
    def key(self) -> str:  # type: ignore[override]
        return self._key

    @property
    def paradigm(self) -> ApiParadigm:  # type: ignore[override]
        return self._paradigm

    def detect(self, payload: DetectionInput) -> DetectionResult:
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        return {"text": raw}

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        return self._model


def _service_with_ops(count: int) -> Service:
    """A service carrying ``count`` request/response operations."""
    return Service(
        key="svc",
        name="svc",
        operations=[
            Operation(key=f"op{i}", name=f"op{i}", kind=OperationKind.REQUEST_RESPONSE)
            for i in range(count)
        ],
    )


def _types(count: int) -> List[Type]:
    """``count`` scalar data types."""
    return [Type(key=f"T{i}", name=f"T{i}", kind=TypeKind.SCALAR) for i in range(count)]


def _model(
    *,
    paradigm: ApiParadigm,
    fmt: str,
    operations: int = 0,
    types: int = 0,
    channels: int = 0,
) -> CanonicalApi:
    """Build a canonical model with the requested surface counts."""
    return CanonicalApi(
        paradigm=paradigm,
        format=fmt,
        identity=ApiIdentity(name="API"),
        services=[_service_with_ops(operations)] if operations else [],
        types=_types(types),
        channels=[
            Channel(key=f"ch{i}", address=f"topic/{i}") for i in range(channels)
        ],
    )


def _decide(
    *,
    key: str,
    paradigm: ApiParadigm,
    fmt: str,
    operations: int = 0,
    types: int = 0,
    channels: int = 0,
) -> ImportRoutingDecision:
    """Build a model + stub adapter and return the routing decision."""
    model = _model(
        paradigm=paradigm,
        fmt=fmt,
        operations=operations,
        types=types,
        channels=channels,
    )
    adapter = _StubAdapter(key, paradigm, model)
    return decide_import_routing(adapter, model)


# ---------------------------------------------------------------------------
# OpenAPI/Swagger → publishable Project
# ---------------------------------------------------------------------------


def test_openapi_31_routes_to_project() -> None:
    decision = _decide(
        key="openapi", paradigm=ApiParadigm.REST, fmt="openapi-3.1", operations=4, types=6
    )
    assert decision.target is ImportTarget.PROJECT
    assert decision.publishable is True
    assert decision.schemas_only is False
    assert "publishable Project" in decision.reason


def test_openapi_30_and_swagger_route_to_project() -> None:
    for fmt in ("openapi-3.0", "swagger-2.0"):
        decision = _decide(
            key="openapi", paradigm=ApiParadigm.REST, fmt=fmt, operations=1
        )
        assert decision.target is ImportTarget.PROJECT, fmt
        assert decision.publishable is True, fmt


def test_publishable_formats_set_is_the_openapi_family() -> None:
    assert PUBLISHABLE_FORMATS == {"openapi-3.0", "openapi-3.1", "swagger-2.0"}


def test_typespec_emitting_openapi_routes_to_project() -> None:
    # A TypeSpec adapter (key != openapi) that normalizes to an openapi-3.x format
    # routes to a Project, because the branch is on the emitted format, not the tool.
    decision = _decide(
        key="typespec", paradigm=ApiParadigm.REST, fmt="openapi-3.0", operations=2, types=3
    )
    assert decision.target is ImportTarget.PROJECT
    assert decision.publishable is True
    assert decision.source == "typespec"


def test_format_match_is_case_insensitive() -> None:
    decision = _decide(
        key="openapi", paradigm=ApiParadigm.REST, fmt="OpenAPI-3.1", operations=1
    )
    assert decision.target is ImportTarget.PROJECT
    # The reason/format preserve the original (un-lowercased) format string.
    assert decision.format == "OpenAPI-3.1"


# ---------------------------------------------------------------------------
# Non-OpenAPI OpenAPI-worthy → catalog item
# ---------------------------------------------------------------------------


def test_grpc_routes_to_catalog() -> None:
    decision = _decide(
        key="grpc", paradigm=ApiParadigm.RPC, fmt="grpc", operations=5, types=8
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is False
    assert "OpenAPI-worthy but not OpenAPI" in decision.reason
    assert "5 operation(s)" in decision.reason


def test_graphql_routes_to_catalog() -> None:
    decision = _decide(
        key="graphql", paradigm=ApiParadigm.GRAPH, fmt="graphql", operations=3, types=10
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is False


def test_asyncapi_with_channels_routes_to_catalog_not_schemas_only() -> None:
    # An event API exposes channels (a callable surface) → OpenAPI-worthy, not schemas-only.
    decision = _decide(
        key="asyncapi", paradigm=ApiParadigm.EVENT, fmt="asyncapi-3", channels=2, types=4
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is False
    assert "2 channel(s)" in decision.reason


def test_odata_routes_to_catalog() -> None:
    decision = _decide(
        key="odata", paradigm=ApiParadigm.REST, fmt="odata-4", operations=7, types=12
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False


# ---------------------------------------------------------------------------
# Pure data-schema → catalog item flagged schemas_only
# ---------------------------------------------------------------------------


def test_avro_schema_only_flagged() -> None:
    decision = _decide(
        key="avro", paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro", types=5
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is True
    assert "schemas-only catalog item" in decision.reason
    assert "5 type(s)" in decision.reason


def test_json_schema_only_flagged() -> None:
    decision = _decide(
        key="json-schema", paradigm=ApiParadigm.DATA_SCHEMA, fmt="json-schema", types=3
    )
    assert decision.schemas_only is True
    assert decision.target is ImportTarget.CATALOG


def test_types_without_operations_flagged_schemas_only_even_if_paradigm_mislabeled() -> None:
    # A model that carries only types but declares a non-data-schema paradigm is still
    # flagged schemas_only on the structural signal (no operations, no channels).
    decision = _decide(
        key="weird", paradigm=ApiParadigm.RPC, fmt="weird", types=2
    )
    assert decision.schemas_only is True
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_non_openapi_import_routes_to_catalog_without_schemas_only() -> None:
    # No operations, no types, no channels, not OpenAPI → catalog item, not schemas-only,
    # with a reason that says nothing publishable was detected.
    decision = _decide(key="grpc", paradigm=ApiParadigm.RPC, fmt="grpc")
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is False
    assert "nothing publishable detected" in decision.reason


def test_decision_as_dict_round_trips() -> None:
    decision = _decide(
        key="grpc", paradigm=ApiParadigm.RPC, fmt="grpc", operations=2, types=3, channels=0
    )
    payload = decision.as_dict()
    assert payload == {
        "target": "catalog",
        "publishable": False,
        "schemas_only": False,
        "reason": decision.reason,
        "source": "grpc",
        "paradigm": "rpc",
        "format": "grpc",
        "counts": {"operations": 2, "types": 3, "channels": 0},
    }


def test_decision_is_frozen() -> None:
    decision = _decide(key="openapi", paradigm=ApiParadigm.REST, fmt="openapi-3.1")
    try:
        decision.publishable = True  # type: ignore[misc]
    except Exception as exc:  # dataclass(frozen=True) raises FrozenInstanceError
        assert "cannot assign" in str(exc).lower() or "frozen" in str(exc).lower()
    else:  # pragma: no cover - the assignment must fail
        raise AssertionError("ImportRoutingDecision should be immutable (frozen)")


def test_counts_reflect_the_model() -> None:
    decision = _decide(
        key="grpc", paradigm=ApiParadigm.RPC, fmt="grpc", operations=3, types=7, channels=1
    )
    assert decision.operation_count == 3
    assert decision.type_count == 7
    assert decision.channel_count == 1


# ---------------------------------------------------------------------------
# Routing recorded on the import-job summary (pipeline integration)
# ---------------------------------------------------------------------------


def _payload(text: str = "x") -> dict:
    """Build a worker-style payload for the in-process pipeline."""
    return {
        "rest_job_id": "job-routing",
        "metadata": {"source_kind": "stub", "options": {}},
        "document_base64": base64.standard_b64encode(text.encode("utf-8")).decode("ascii"),
        "filename": "doc.txt",
    }


async def test_pipeline_records_catalog_routing_on_summary() -> None:
    model = _model(paradigm=ApiParadigm.RPC, fmt="grpc", operations=2, types=3)
    adapter = _StubAdapter("grpc", ApiParadigm.RPC, model)

    snaps: List[SpecImportJobStatus] = []

    async def _on(status: SpecImportJobStatus) -> None:
        snaps.append(status)

    final = await run_adapter_import_job(adapter, _payload(), on_snapshot=_on)

    assert final.state == "completed"
    routing = final.summary["routing"]
    assert routing["target"] == "catalog"
    assert routing["publishable"] is False
    assert routing["schemas_only"] is False
    assert routing["source"] == "grpc"
    # A ROUTING_DECIDED event is emitted carrying the decision context.
    routed = [e for e in final.events if e.code == "ROUTING_DECIDED"]
    assert len(routed) == 1
    assert routed[0].context["target"] == "catalog"


async def test_pipeline_records_project_routing_for_openapi_format() -> None:
    model = _model(paradigm=ApiParadigm.REST, fmt="openapi-3.1", operations=4, types=6)
    adapter = _StubAdapter("openapi", ApiParadigm.REST, model)

    final = await run_adapter_import_job(adapter, _payload())

    assert final.state == "completed"
    assert final.summary["routing"]["target"] == "project"
    assert final.summary["routing"]["publishable"] is True


async def test_pipeline_records_schemas_only_routing_for_data_schema() -> None:
    model = _model(paradigm=ApiParadigm.DATA_SCHEMA, fmt="avro", types=4)
    adapter = _StubAdapter("avro", ApiParadigm.DATA_SCHEMA, model)

    final = await run_adapter_import_job(adapter, _payload())

    assert final.summary["routing"]["target"] == "catalog"
    assert final.summary["routing"]["schemas_only"] is True
