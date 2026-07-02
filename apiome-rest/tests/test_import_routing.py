"""Unit tests for Project-vs-Catalog import routing (MFI-23.7, #4016).

Exercise :func:`app.import_routing.decide_import_routing` directly against small stub
adapters and hand-built canonical models, covering the ticket's acceptance criteria:

* OpenAPI/Swagger/Arazzo (incl. TypeSpec-emitted OpenAPI) → publishable **Project**;
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
    requested_target: Optional[str] = None,
) -> ImportRoutingDecision:
    """Build a model + stub adapter and return the routing decision.

    ``requested_target`` forwards the user's explicit disambiguation choice (MFI-26.8) so a
    single helper exercises both the default routing and the JSON Schema "as current" opt-in.
    """
    model = _model(
        paradigm=paradigm,
        fmt=fmt,
        operations=operations,
        types=types,
        channels=channels,
    )
    adapter = _StubAdapter(key, paradigm, model)
    return decide_import_routing(adapter, model, requested_target=requested_target)


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


def test_openapi_30_swagger_and_arazzo_route_to_project() -> None:
    for fmt in ("openapi-3.0", "swagger-2.0", "arazzo"):
        decision = _decide(
            key="openapi", paradigm=ApiParadigm.REST, fmt=fmt, operations=1
        )
        assert decision.target is ImportTarget.PROJECT, fmt
        assert decision.publishable is True, fmt


def test_publishable_formats_set_is_the_project_family() -> None:
    assert PUBLISHABLE_FORMATS == {"openapi-3.0", "openapi-3.1", "swagger-2.0", "arazzo"}


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
    assert decision.publishable is False


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
# JSON Schema "import as current" → Types/Projects (MFI-26.8)
# ---------------------------------------------------------------------------


def test_json_schema_without_target_defaults_to_catalog() -> None:
    # No opt-in → the JSON Schema still stores a non-publishable, schemas-only catalog item.
    decision = _decide(
        key="json-schema", paradigm=ApiParadigm.DATA_SCHEMA, fmt="json-schema", types=3
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is True


def test_json_schema_explicit_catalog_target_stays_catalog() -> None:
    # The explicit "catalog" choice is the default branch: a non-publishable catalog item.
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema",
        types=3,
        requested_target="catalog",
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False
    assert decision.schemas_only is True


def test_json_schema_target_types_imports_as_current() -> None:
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema",
        types=3,
        requested_target="types",
    )
    assert decision.target is ImportTarget.TYPES
    # As-current never mints a publishable Project (§0.3 rule 1).
    assert decision.publishable is False
    assert decision.schemas_only is True
    assert "current type/schema" in decision.reason
    assert decision.as_dict()["target"] == "types"


def test_json_schema_target_project_imports_as_current_not_publishable() -> None:
    # "project" is an as-current choice too — it lands in the type registry, NOT a publishable
    # Project, so only OpenAPI/Arazzo ever create Projects.
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema",
        types=2,
        requested_target="project",
    )
    assert decision.target is ImportTarget.TYPES
    assert decision.publishable is False


def test_json_schema_dialect_tagged_format_honors_target() -> None:
    # A dialect-tagged emitted format (json-schema-2020-12) is still JSON Schema.
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema-2020-12",
        types=1,
        requested_target="types",
    )
    assert decision.target is ImportTarget.TYPES


def test_requested_target_is_case_and_whitespace_insensitive() -> None:
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema",
        types=1,
        requested_target="  TYPES  ",
    )
    assert decision.target is ImportTarget.TYPES


def test_requested_target_ignored_for_openapi_no_regression() -> None:
    # The guardrail: an OpenAPI import ignores a stray as-current opt-in and still routes to a
    # publishable Project. This is the "no regression to OpenAPI/Arazzo routing" criterion.
    for fmt in ("openapi-3.1", "swagger-2.0", "arazzo"):
        decision = _decide(
            key="openapi",
            paradigm=ApiParadigm.REST,
            fmt=fmt,
            operations=2,
            requested_target="types",
        )
        assert decision.target is ImportTarget.PROJECT, fmt
        assert decision.publishable is True, fmt


def test_requested_target_ignored_for_non_json_schema_formats() -> None:
    # Only JSON Schema prompts the user; other non-OpenAPI formats keep their catalog routing
    # regardless of a requested target (they should never be sent as-current).
    decision = _decide(
        key="grpc",
        paradigm=ApiParadigm.RPC,
        fmt="grpc",
        operations=3,
        types=4,
        requested_target="types",
    )
    assert decision.target is ImportTarget.CATALOG
    assert decision.publishable is False


def test_unknown_requested_target_falls_back_to_catalog() -> None:
    # A value outside {catalog, types, project} is not an as-current opt-in → default catalog.
    decision = _decide(
        key="json-schema",
        paradigm=ApiParadigm.DATA_SCHEMA,
        fmt="json-schema",
        types=2,
        requested_target="nonsense",
    )
    assert decision.target is ImportTarget.CATALOG


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


async def test_pipeline_catalog_branch_never_converts() -> None:
    # MFI-26.6 (#4101) guardrail: a catalog import stores the source verbatim and never
    # auto-converts at import time — no conversion event is emitted, the completion note
    # says the source was stored *unconverted*, and the routed artifact is non-publishable.
    model = _model(paradigm=ApiParadigm.GRAPH, fmt="graphql", operations=3, types=5)
    adapter = _StubAdapter("graphql", ApiParadigm.GRAPH, model)

    final = await run_adapter_import_job(adapter, _payload())

    assert final.state == "completed"
    assert final.summary["routing"]["target"] == "catalog"
    assert final.summary["routing"]["publishable"] is False
    # No event in the run signals a conversion to OpenAPI.
    assert not any("CONVERT" in e.code.upper() for e in final.events)
    completed = [e for e in final.events if e.code == "IMPORT_COMPLETED"]
    assert len(completed) == 1
    assert "unconverted" in completed[0].message.lower()


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


# ---------------------------------------------------------------------------
# JSON Schema "import as current" through the pipeline (MFI-26.8)
# ---------------------------------------------------------------------------


def _json_schema_model(
    *, fmt: str = "json-schema", source: Optional[dict] = None, types: int = 1
) -> CanonicalApi:
    """A DATA_SCHEMA canonical model that retains a raw JSON Schema ``source`` (include_raw)."""
    document = source if source is not None else {"$defs": {"User": {"type": "object"}}}
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format=fmt,
        identity=ApiIdentity(name="Schema"),
        types=_types(types),
        raw={"source": document},
    )


def _payload_with_options(options: dict, **overrides: Any) -> dict:
    """A worker payload carrying importer ``options`` (and optional tenant overrides)."""
    payload = _payload()
    payload["metadata"]["options"] = options
    payload.update(overrides)
    return payload


async def test_pipeline_json_schema_without_target_routes_to_catalog() -> None:
    # No opt-in → the JSON Schema still routes to a schemas-only catalog item.
    model = _json_schema_model()
    adapter = _StubAdapter("json-schema", ApiParadigm.DATA_SCHEMA, model)

    final = await run_adapter_import_job(adapter, _payload())

    assert final.state == "completed"
    assert final.summary["routing"]["target"] == "catalog"
    assert final.summary["routing"]["schemas_only"] is True


async def test_pipeline_records_types_routing_for_json_schema_as_current() -> None:
    # The opt-in routes to Types; without a tenant nothing is persisted, but the summary +
    # completion note reflect the as-current destination (DB-free).
    model = _json_schema_model()
    adapter = _StubAdapter("json-schema", ApiParadigm.DATA_SCHEMA, model)

    final = await run_adapter_import_job(
        adapter, _payload_with_options({"import_target": "types"})
    )

    assert final.state == "completed"
    assert final.summary["routing"]["target"] == "types"
    assert final.summary["routing"]["publishable"] is False
    assert final.summary["persisted"] is False
    routed = [e for e in final.events if e.code == "ROUTING_DECIDED"]
    assert routed[0].context["target"] == "types"
    completed = [e for e in final.events if e.code == "IMPORT_COMPLETED"]
    assert "current type/schema" in completed[0].message


async def test_pipeline_persists_json_schema_as_current_types(monkeypatch) -> None:
    # With a tenant, the Types branch commits the schema's $defs through the shared registry
    # importer (stubbed here) — a current type/schema, not a catalog item.
    captured: dict = {}

    def _fake_commit(definitions, *, tenant_id, tenant_slug, target_namespace, created_by, **_):
        captured.update(
            definitions=definitions,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            target_namespace=target_namespace,
            created_by=created_by,
        )
        return {
            "imported": list(definitions.keys()),
            "overwritten": [],
            "renamed": [],
            "identical": [],
            "skipped": [],
            "errors": [],
            "rewrites": {},
            "reviews": [],
        }

    import app.primitives_routes as primitives_routes

    monkeypatch.setattr(primitives_routes, "_commit_imported_definitions", _fake_commit)

    schema = {"$defs": {"User": {"type": "object"}, "Order": {"type": "object"}}}
    model = _json_schema_model(source=schema, types=2)
    adapter = _StubAdapter("json-schema", ApiParadigm.DATA_SCHEMA, model)
    payload = _payload_with_options(
        {"import_target": "project"},
        tenant_id="tenant-1",
        tenant_slug="acme",
        user_id="user-1",
    )

    final = await run_adapter_import_job(adapter, payload)

    assert final.state == "completed"
    # The commit helper received the extracted $defs under the right tenant/creator.
    assert set(captured["definitions"].keys()) == {"User", "Order"}
    assert captured["tenant_id"] == "tenant-1"
    assert captured["tenant_slug"] == "acme"
    assert captured["created_by"] == "user-1"
    # The summary reports it persisted as current types (no catalog project).
    assert final.summary["persisted"] is True
    assert final.summary["routing"]["target"] == "types"
    assert final.summary["types_import"]["imported"] == 2
    assert final.result is None
    persisted = [e for e in final.events if e.code == "PERSISTED"]
    assert len(persisted) == 1
    assert "current type/schema" in persisted[0].message


async def test_pipeline_bare_single_type_json_schema_imports_as_one_type(monkeypatch) -> None:
    # A JSON Schema with no $defs is a single (bare) type; it still imports as-current, named
    # from its title, instead of failing with "no definitions".
    captured: dict = {}

    def _fake_commit(definitions, **_):
        captured["definitions"] = definitions
        return {
            "imported": list(definitions.keys()),
            "overwritten": [],
            "renamed": [],
            "identical": [],
            "skipped": [],
            "errors": [],
        }

    import app.primitives_routes as primitives_routes

    monkeypatch.setattr(primitives_routes, "_commit_imported_definitions", _fake_commit)

    schema = {"title": "Widget", "type": "object", "properties": {"id": {"type": "string"}}}
    model = _json_schema_model(source=schema, types=1)
    adapter = _StubAdapter("json-schema", ApiParadigm.DATA_SCHEMA, model)
    payload = _payload_with_options(
        {"import_target": "types"},
        tenant_id="tenant-1",
        tenant_slug="acme",
        user_id="user-1",
    )

    final = await run_adapter_import_job(adapter, payload)

    assert final.state == "completed"
    assert list(captured["definitions"].keys()) == ["Widget"]
    assert final.summary["types_import"]["imported"] == 1
