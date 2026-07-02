"""Tests for the fidelity / completeness gap analyzer — MFI-22.3 (#4004).

Covers the acceptance criteria end-to-end (emit → analyze):

* an OData-style REST model scores **high** (near-lossless);
* an AsyncAPI event model scores **low**, with its pub/sub and channel-binding
  losses enumerated;
* a gRPC model without HTTP annotations flags **inferred paths** plus inferred
  (defaulted) media types and status codes;

and pins the analyzer's contracts: every :class:`~app.fidelity.Coverage` tag is
reachable, the score/grade/tier banding, that ``n/a`` rows never penalize while
``missing``/``inferred`` rows do, that projection losses are carried through, and
that the whole report is deterministic for a fixed model.
"""

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity import (
    TIER_HIGH_MIN,
    TIER_MEDIUM_MIN,
    ChecklistItem,
    Coverage,
    FidelityAnalyzer,
    FidelityReport,
    FidelityTier,
    analyze_fidelity,
)
from app.openapi_emitter import OpenApiEmitter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMITTER = OpenApiEmitter()


def _analyze(api: CanonicalApi) -> FidelityReport:
    """Emit ``api`` and analyze the result in one step."""
    return analyze_fidelity(api, _EMITTER.emit(api))


def _item(report: FidelityReport, key: str) -> ChecklistItem:
    """Return the checklist row with ``key`` (fails loudly if absent)."""
    for item in report.items:
        if item.key == key:
            return item
    raise AssertionError(f"no checklist item {key!r} in report")


def _record(key: str, name: str, kind: TypeKind = TypeKind.RECORD) -> Type:
    """A one-field RECORD type usable as a message payload."""
    return Type(
        key=key,
        name=name,
        kind=kind,
        fields=[
            CanonicalField(
                key=f"{key}.id", name="id", type=TypeRef(name="integer", nullable=False)
            )
        ],
    )


# ---------------------------------------------------------------------------
# Acceptance fixtures
# ---------------------------------------------------------------------------


def _odata_rest() -> CanonicalApi:
    """A rich, fully-specified REST (OData-style) model — should be near-lossless."""
    product = _record("Product", "Product")
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="odata",
        identity=ApiIdentity(name="Northwind"),
        title="Northwind",
        version="4.0",
        description="OData Northwind service",
        servers=[Server(url="https://svc.example.com/odata")],
        types=[product],
        services=[
            Service(
                key="ProductsSvc",
                name="ProductsSvc",
                operations=[
                    Operation(
                        key="GET /Products",
                        name="listProducts",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/Products",
                        tags=["Products"],
                        extras={"operationId": "listProducts", "summary": "List"},
                        parameters=[
                            Parameter(
                                key="GET /Products#query.top",
                                name="$top",
                                location=ParameterLocation.QUERY,
                                type=TypeRef(name="integer"),
                            )
                        ],
                        messages=[
                            Message(
                                key="GET /Products#resp",
                                role=MessageRole.RESPONSE,
                                status_code="200",
                                content_types=["application/json"],
                                payload=TypeRef(name="Product"),
                            )
                        ],
                    ),
                    Operation(
                        key="POST /Products",
                        name="createProduct",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="POST",
                        http_path="/Products",
                        tags=["Products"],
                        extras={"operationId": "createProduct"},
                        messages=[
                            Message(
                                key="POST /Products#req",
                                role=MessageRole.REQUEST,
                                content_types=["application/json"],
                                payload=TypeRef(name="Product"),
                            ),
                            Message(
                                key="POST /Products#resp",
                                role=MessageRole.RESPONSE,
                                status_code="201",
                                content_types=["application/json"],
                                payload=TypeRef(name="Product"),
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


def _grpc_no_http() -> CanonicalApi:
    """A gRPC model with no HTTP annotations and no streaming."""
    req, resp = _record("GetReq", "GetReq"), _record("GetResp", "GetResp")
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        protocol="grpc",
        identity=ApiIdentity(name="acme.Widgets"),
        title="Widgets",
        version="1.0",
        servers=[Server(url="grpc://acme:443")],
        types=[req, resp],
        services=[
            Service(
                key="acme.Widgets",
                name="Widgets",
                operations=[
                    Operation(
                        key="acme.Widgets.Get",
                        name="Get",
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        messages=[
                            Message(
                                key="acme.Widgets.Get#req",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="GetReq"),
                            ),
                            Message(
                                key="acme.Widgets.Get#resp",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="GetResp"),
                            ),
                        ],
                    ),
                    Operation(
                        key="acme.Widgets.List",
                        name="List",
                        kind=OperationKind.REQUEST_RESPONSE,
                        messages=[
                            Message(
                                key="acme.Widgets.List#req",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="GetReq"),
                            ),
                            Message(
                                key="acme.Widgets.List#resp",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="GetResp"),
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


def _asyncapi_event() -> CanonicalApi:
    """An AsyncAPI event model: two pub/sub ops on a channel with protocol bindings."""
    payload = _record("UserSignedUp", "UserSignedUp")
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="UserEvents"),
        title="User Events",
        version="1.0",
        description="user lifecycle events",
        channels=[
            Channel(
                key="user/signedup",
                address="user/signedup",
                protocol="kafka",
                bindings={"kafka": {"topic": "user.signedup"}},
            )
        ],
        types=[payload],
        services=[
            Service(
                key="UserEvents",
                name="UserEvents",
                operations=[
                    Operation(
                        key="user/signedup#publish",
                        name="publish",
                        kind=OperationKind.PUBLISH,
                        channel_ref="user/signedup",
                        messages=[
                            Message(
                                key="user/signedup#msg",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="UserSignedUp"),
                            )
                        ],
                    ),
                    Operation(
                        key="user/signedup#subscribe",
                        name="subscribe",
                        kind=OperationKind.SUBSCRIBE,
                        channel_ref="user/signedup",
                        messages=[
                            Message(
                                key="user/signedup#msg2",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="UserSignedUp"),
                            )
                        ],
                    ),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------


def test_odata_rest_scores_high_and_near_lossless() -> None:
    report = _analyze(_odata_rest())
    assert report.tier is FidelityTier.HIGH
    assert report.grade == "A"
    assert report.score >= TIER_HIGH_MIN
    # Every load-bearing REST construct is faithful.
    for key in ("paths", "responses", "requestBody", "parameters", "components.schemas"):
        assert _item(report, key).coverage is Coverage.PRESENT
    # No projection losses on the REST identity path.
    assert report.losses == []


def test_asyncapi_event_scores_low_with_losses_enumerated() -> None:
    report = _analyze(_asyncapi_event())
    assert report.tier is FidelityTier.LOW
    assert report.score < TIER_MEDIUM_MIN
    # The pub/sub and channel-binding losses are surfaced, not dropped.
    subjects = {loss.subject for loss in report.losses}
    assert "event-pubsub-action" in subjects
    assert "event-channel-bindings" in subjects
    assert all(loss.kind is LossKind.NA for loss in report.losses)
    # Routes are synthesized; events carry no responses.
    assert _item(report, "paths").coverage is Coverage.INFERRED
    assert _item(report, "responses").coverage is Coverage.MISSING


def test_grpc_without_http_flags_inferred_paths_and_missing_media_and_status() -> None:
    report = _analyze(_grpc_no_http())
    # Inferred paths (synthesized POST /{Service}/{Method}).
    paths = _item(report, "paths")
    assert paths.coverage is Coverage.INFERRED
    assert paths.count == 2
    # Media types + status codes were inferred, not declared by the source.
    assert _item(report, "requestBody").coverage is Coverage.INFERRED
    assert _item(report, "responses").coverage is Coverage.INFERRED
    # The synthesized bindings are enumerated as inferred losses.
    assert any(
        loss.subject == "synthesized-http-binding" and loss.kind is LossKind.INFERRED
        for loss in report.losses
    )
    # Medium fidelity: emitted, but not faithful.
    assert report.tier is FidelityTier.MEDIUM


# ---------------------------------------------------------------------------
# Coverage-tag classifiers
# ---------------------------------------------------------------------------


def test_info_rows_reflect_source_presence() -> None:
    report = _analyze(_odata_rest())
    assert _item(report, "info.title").coverage is Coverage.PRESENT
    assert _item(report, "info.version").coverage is Coverage.PRESENT
    assert _item(report, "info.description").coverage is Coverage.PRESENT


def test_missing_title_version_description_are_flagged() -> None:
    # A REST model with no title/version/description on the artifact.
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Nameless"),
        services=[
            Service(
                key="S",
                name="S",
                operations=[
                    Operation(
                        key="GET /x",
                        name="x",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/x",
                    )
                ],
            )
        ],
    )
    report = _analyze(api)
    # title falls back to identity.name → inferred, not source.
    assert _item(report, "info.title").coverage is Coverage.INFERRED
    assert _item(report, "info.version").coverage is Coverage.MISSING
    assert _item(report, "info.description").coverage is Coverage.MISSING


def test_missing_servers_flagged() -> None:
    api = _odata_rest().model_copy(update={"servers": []})
    assert _item(_analyze(api), "servers").coverage is Coverage.MISSING


def test_partial_paths_when_some_routes_synthesized() -> None:
    """One REST op with a real binding + one with none → partial paths coverage."""
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Mixed"),
        title="Mixed",
        version="1.0",
        services=[
            Service(
                key="S",
                name="S",
                operations=[
                    Operation(
                        key="GET /a",
                        name="a",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/a",
                    ),
                    # No http_method/http_path → synthesized POST binding.
                    Operation(key="b.op", name="b", kind=OperationKind.REQUEST_RESPONSE),
                ],
            )
        ],
    )
    report = _analyze(api)
    assert _item(report, "paths").coverage is Coverage.PARTIAL


def test_types_only_model_has_na_paths_and_present_components() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="Schemas"),
        title="Schemas",
        version="1.0",
        types=[_record("Widget", "Widget")],
    )
    report = _analyze(api)
    paths = _item(report, "paths")
    assert paths.coverage is Coverage.NA
    assert "types only" in paths.reason
    assert _item(report, "components.schemas").coverage is Coverage.PRESENT
    # A schema library converts cleanly: high fidelity.
    assert report.tier is FidelityTier.HIGH


def test_graphql_subscription_is_na_loss_and_absent_from_paths() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="G"),
        title="G",
        version="1.0",
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.me",
                        name="me",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.me#resp",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="string"),
                            )
                        ],
                    ),
                    Operation(
                        key="Subscription.onPing",
                        name="onPing",
                        kind=OperationKind.SUBSCRIPTION,
                    ),
                ],
            )
        ],
    )
    report = _analyze(api)
    assert any(
        loss.subject == "graphql-subscription" and loss.kind is LossKind.NA
        for loss in report.losses
    )
    # Only the query reached paths (the subscription was dropped).
    assert _item(report, "paths").count == 1


def test_na_rows_present_for_constructs_the_model_cannot_carry() -> None:
    report = _analyze(_odata_rest())
    for key in ("info.contact", "info.license", "security", "examples", "externalDocs"):
        assert _item(report, key).coverage is Coverage.NA


def test_tags_and_deprecated_present_when_declared() -> None:
    report = _analyze(_odata_rest())
    assert _item(report, "tags").coverage is Coverage.PRESENT
    # No deprecation in the fixture → n/a, not missing.
    assert _item(report, "deprecated").coverage is Coverage.NA


# ---------------------------------------------------------------------------
# Score / grade / tier banding + penalty transparency
# ---------------------------------------------------------------------------


def test_na_rows_do_not_penalize_the_score() -> None:
    # The OData model's only non-present rows are all n/a → perfect score.
    report = _analyze(_odata_rest())
    assert report.score == 100
    assert report.penalty == 0
    assert all(
        item.coverage in (Coverage.PRESENT, Coverage.NA) for item in report.items
    )


def test_score_equals_hundred_minus_penalty() -> None:
    for build in (_odata_rest, _grpc_no_http, _asyncapi_event):
        report = _analyze(build())
        assert report.score == max(0, 100 - report.penalty)


def test_grade_follows_house_bands() -> None:
    assert _analyze(_odata_rest()).grade == "A"  # 100
    assert _analyze(_grpc_no_http()).grade in {"C", "D"}  # ~79
    assert _analyze(_asyncapi_event()).grade == "F"  # <60


def test_tier_bands_align_with_score() -> None:
    for build in (_odata_rest, _grpc_no_http, _asyncapi_event):
        report = _analyze(build())
        if report.score >= TIER_HIGH_MIN:
            assert report.tier is FidelityTier.HIGH
        elif report.score >= TIER_MEDIUM_MIN:
            assert report.tier is FidelityTier.MEDIUM
        else:
            assert report.tier is FidelityTier.LOW


def test_coverage_counts_tally_every_row() -> None:
    report = _analyze(_grpc_no_http())
    assert sum(report.coverage_counts.values()) == len(report.items)
    # The tally matches an independent recount.
    for tag in Coverage:
        expected = sum(1 for i in report.items if i.coverage is tag)
        assert report.coverage_counts[tag.value] == expected


# ---------------------------------------------------------------------------
# Determinism & report shape
# ---------------------------------------------------------------------------


def test_report_is_deterministic() -> None:
    api = _asyncapi_event()
    first = analyze_fidelity(api, _EMITTER.emit(api))
    second = analyze_fidelity(api, _EMITTER.emit(api))
    assert first.model_dump() == second.model_dump()


def test_examples_are_sorted_and_capped() -> None:
    report = _analyze(_grpc_no_http())
    for item in report.items:
        assert item.examples == sorted(item.examples)
        assert len(item.examples) <= 3


def test_checklist_order_is_fixed_and_complete() -> None:
    report = _analyze(_odata_rest())
    keys = [item.key for item in report.items]
    assert keys == [
        "info.title",
        "info.version",
        "info.description",
        "info.contact",
        "info.license",
        "servers",
        "paths",
        "operation.metadata",
        "parameters",
        "requestBody",
        "responses",
        "components.schemas",
        "security",
        "tags",
        "examples",
        "externalDocs",
        "deprecated",
    ]


def test_losses_carried_through_from_emit_result() -> None:
    api = _asyncapi_event()
    result = _EMITTER.emit(api)
    report = analyze_fidelity(api, result)
    assert report.losses == result.losses


def test_analyzer_instance_is_reusable() -> None:
    analyzer = FidelityAnalyzer()
    a, b = _odata_rest(), _asyncapi_event()
    # Reusing one analyzer across models must not leak state between analyses.
    ra1 = analyzer.analyze(a, _EMITTER.emit(a))
    rb = analyzer.analyze(b, _EMITTER.emit(b))
    ra2 = analyzer.analyze(a, _EMITTER.emit(a))
    assert ra1.model_dump() == ra2.model_dump()
    assert rb.tier is FidelityTier.LOW
