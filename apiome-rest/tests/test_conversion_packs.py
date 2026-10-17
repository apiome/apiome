"""Per-format conversion packs (MFI-22.8, #4009).

Each pack is held to its acceptance criterion: its golden fixture converts to a **valid OpenAPI
3.1 document** at the pack's **expected fidelity tier**. The outcome of each golden conversion —
tier, score, grade, the emitted operations, the pack's refinements and the loss subjects — is
pinned under ``tests/golden/conversion_packs/`` so a projection change shows up as a reviewable
diff. Regenerate with::

    UPDATE_CONVERSION_PACK_GOLDENS=1 .venv/bin/python -m pytest tests/test_conversion_packs.py

The suite also covers the pieces each pack is built from: the source-text readers
(``google.api.http`` / Smithy ``@http``), the component-key repair, the tier ceiling, the
source-only losses, the external-converter hook (with a fake runner, since no converter ships in
the runtime image), the vendored googleapis protos, and the dry-run response's ``conversionPack``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.conversion_job import preview_conversion
from app.conversion_pack_sources import (
    proto_http_bindings,
    smithy_http_bindings,
    smithy_unconverted_traits,
)
from app.conversion_packs import (
    ConversionPack,
    apply_source_losses,
    apply_tier_ceiling,
    conversion_packs,
    resolve_conversion_pack,
    run_external_converter,
    valid_component_keys,
)
from app.emitter import Loss, LossKind
from app.fidelity import FidelityReport, FidelityTier
from app.openapi_validator import validate_openapi_document
from app.proto_descriptor import ProtoFile, vendored_proto_imports
from app.toolchain_runner import ToolExecutionError

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "apiome-ui" / "examples"
LOCAL_FIXTURES = Path(__file__).parent / "fixtures" / "conversion_packs"
GOLDEN_DIR = Path(__file__).parent / "golden" / "conversion_packs"
UPDATE_GOLDENS = os.environ.get("UPDATE_CONVERSION_PACK_GOLDENS") == "1"

#: One golden conversion per pack (and the unannotated-gRPC case the ceiling exists for):
#: ``(golden name, catalog source_format, fixture path, expected pack, expected tier)``.
#: The two annotated fixtures live with this suite — the examples corpus has no
#: ``google.api.http`` or Smithy ``@http`` source.
PACK_GOLDENS = [
    ("odata", "odata", EXAMPLES / "odata/01-northwind.edmx", "odata", FidelityTier.HIGH),
    ("smithy", "smithy", LOCAL_FIXTURES / "orders-http.smithy", "smithy", FidelityTier.MEDIUM),
    ("grpc", "grpc", LOCAL_FIXTURES / "orders-http.proto", "grpc", FidelityTier.MEDIUM),
    (
        "grpc-unannotated",
        "grpc",
        EXAMPLES / "protobuf/02-grpc-service.proto",
        "grpc",
        FidelityTier.LOW,
    ),
    (
        "graphql",
        "graphql",
        EXAMPLES / "graphql/10-comprehensive-ecommerce.graphql",
        "graphql",
        FidelityTier.MEDIUM,
    ),
    (
        "asyncapi",
        "asyncapi",
        EXAMPLES / "asyncapi/02-order-events-3.0.yaml",
        "asyncapi",
        FidelityTier.LOW,
    ),
    (
        "cloudevents",
        "cloudevents",
        EXAMPLES / "cloudevents/01-order-created.json",
        "cloudevents",
        FidelityTier.LOW,
    ),
    ("wsdl", "wsdl", EXAMPLES / "wsdl/02-order-service.wsdl", "wsdl", FidelityTier.MEDIUM),
    ("avro", "avro", EXAMPLES / "avro/05-stress-mixed-types.avsc", "avro", FidelityTier.HIGH),
    ("raml", "raml", EXAMPLES / "raml/03-orders-service.raml", "raml", FidelityTier.HIGH),
    (
        "apiblueprint",
        "apiblueprint",
        EXAMPLES / "api-blueprint/03-bookstore-service.apib",
        "apiblueprint",
        FidelityTier.HIGH,
    ),
    ("wadl", "wadl", EXAMPLES / "wadl/06-task-tracker.wadl", "wadl", FidelityTier.MEDIUM),
]


def _catalog_item(source_format: str, fixture: Path) -> Dict[str, Any]:
    """The catalog row a conversion of ``fixture`` rebuilds from (as the route loads it)."""
    return {
        "id": f"pack-{fixture.stem}",
        "source_format": source_format,
        "protocol": None,
        "tool_versions": {},
        "format_metadata": {
            "sourceContent": fixture.read_text(encoding="utf-8"),
            "sourceLabel": fixture.name,
        },
    }


def _golden_summary(name: str, fixture: Path, preview) -> Dict[str, Any]:
    """The pinned outcome of one golden conversion."""
    operations: List[str] = sorted(
        f"{method.upper()} {path}"
        for path, item in (preview.document.get("paths") or {}).items()
        for method in item
        if method in {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
    )
    return {
        "pack": preview.pack.key,
        "fixture": str(fixture.relative_to(REPO_ROOT)),
        "tier": preview.fidelity.tier.value,
        "score": preview.fidelity.score,
        "grade": preview.fidelity.grade,
        "operations": operations,
        "schemas": sorted((preview.document.get("components") or {}).get("schemas") or {}),
        "refinements": preview.pack.refinements,
        "losses": sorted({loss.subject for loss in preview.fidelity.losses}),
    }


# ---------------------------------------------------------------------------
# The acceptance criterion — each pack's golden fixture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,source_format,fixture,pack_key,expected_tier",
    PACK_GOLDENS,
    ids=[golden[0] for golden in PACK_GOLDENS],
)
def test_pack_converts_its_golden_fixture_to_valid_openapi_at_its_tier(
    name: str,
    source_format: str,
    fixture: Path,
    pack_key: str,
    expected_tier: FidelityTier,
) -> None:
    preview = preview_conversion(build_conversion_source(_catalog_item(source_format, fixture)))

    assert preview.pack is not None and preview.pack.key == pack_key
    assert preview.pack.strategy == "native"
    assert validate_openapi_document(preview.document) == []
    assert preview.fidelity.tier is expected_tier
    # The fixture's tier is one the pack itself declares — the docs table reads these.
    pack = resolve_conversion_pack(source_format, None)
    assert expected_tier in pack.expected_tiers or name == "grpc-unannotated"

    summary = _golden_summary(name, fixture, preview)
    golden_path = GOLDEN_DIR / f"{name}.json"
    if UPDATE_GOLDENS:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", "utf-8")
    assert golden_path.exists(), f"missing golden {golden_path.name}; regenerate (see module doc)"
    assert summary == json.loads(golden_path.read_text("utf-8"))


def test_every_registered_pack_has_a_golden_fixture() -> None:
    covered = {golden[3] for golden in PACK_GOLDENS}
    assert {pack.key for pack in conversion_packs()} == covered


def test_annotated_grpc_keeps_its_declared_rest_surface() -> None:
    preview = preview_conversion(
        build_conversion_source(_catalog_item("grpc", LOCAL_FIXTURES / "orders-http.proto"))
    )
    paths = preview.document["paths"]
    assert set(paths["/v1/orders/{id}"]) >= {"get", "delete"}
    assert set(paths["/v1/orders"]) >= {"get", "post"}
    assert "post" in paths["/v1/orders/{id}:cancel"]
    # No synthesized POST /{Service}/{Method} survives once every method is annotated.
    assert not any(path.startswith("/shop.orders.v1.OrderService/") for path in paths)
    assert "synthesized-http-binding" not in {loss.subject for loss in preview.fidelity.losses}
    # The vendored googleapis messages are imports, never emitted schemas.
    assert not any("HttpRule" in name for name in preview.document["components"]["schemas"])


def test_unannotated_grpc_is_capped_at_low_and_says_why() -> None:
    preview = preview_conversion(
        build_conversion_source(
            _catalog_item("grpc", EXAMPLES / "protobuf/02-grpc-service.proto")
        )
    )
    assert preview.fidelity.tier is FidelityTier.LOW
    assert preview.fidelity.score < 60
    subjects = {loss.subject for loss in preview.fidelity.losses}
    assert "grpc-no-http-annotations" in subjects


def test_event_packs_warn_that_only_schemas_convert() -> None:
    for fmt, path in (
        ("asyncapi", "asyncapi/02-order-events-3.0.yaml"),
        ("cloudevents", "cloudevents/01-order-created.json"),
    ):
        preview = preview_conversion(build_conversion_source(_catalog_item(fmt, EXAMPLES / path)))
        assert preview.fidelity.tier is FidelityTier.LOW
        assert preview.fidelity.grade == "F"
        loss = next(l for l in preview.fidelity.losses if l.subject == "event-schemas-only")
        assert "publish/subscribe" in loss.detail


def test_smithy_reports_its_unconverted_traits_as_losses() -> None:
    preview = preview_conversion(
        build_conversion_source(_catalog_item("smithy", LOCAL_FIXTURES / "orders-http.smithy"))
    )
    subjects = {loss.subject for loss in preview.fidelity.losses}
    assert {"smithy-endpoint-trait", "smithy-hostLabel-trait"} <= subjects
    assert "/orders/{id}" in preview.document["paths"]


def test_a_format_without_a_pack_converts_as_before() -> None:
    fixture = EXAMPLES / "json-schema/01-simple-person.json"
    preview = preview_conversion(build_conversion_source(_catalog_item("jsonschema", fixture)))
    assert preview.pack is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_packs_resolve_by_adapter_key_or_model_format() -> None:
    assert resolve_conversion_pack("grpc", "protobuf").key == "grpc"
    assert resolve_conversion_pack(None, "protobuf").key == "grpc"
    assert resolve_conversion_pack("AsyncAPI", None).key == "asyncapi"
    assert resolve_conversion_pack(None, "asyncapi-3").key == "asyncapi"
    assert resolve_conversion_pack("api-blueprint", None).key == "apiblueprint"
    assert resolve_conversion_pack("openapi-3.1", "openapi-3.1") is None
    assert resolve_conversion_pack(None, None) is None


def test_every_pack_declares_what_the_docs_table_reads() -> None:
    for pack in conversion_packs():
        assert pack.key and pack.label and pack.formats and pack.expected_tiers
        assert pack.documented_losses, pack.key


def test_a_pack_missing_its_declaration_is_refused() -> None:
    with pytest.raises(TypeError):

        class _Incomplete(ConversionPack, register=True):  # noqa: F841 - registration is the test
            key = "incomplete"


def test_a_duplicate_pack_key_is_refused() -> None:
    with pytest.raises(ValueError):

        class _Duplicate(ConversionPack, register=True):  # noqa: F841
            key = "odata"
            formats = frozenset({"odata-dup"})
            expected_tiers = (FidelityTier.HIGH,)


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------

_PROTO = """
syntax = "proto3";
package demo.v1;
import "google/api/annotations.proto";
// service Commented { rpc Ghost(A) returns (B) { option (google.api.http) = { get: "/ghost" }; } }
service Things {
  rpc GetThing(GetReq) returns (Thing) {
    option (google.api.http) = { get: "/v1/{name=things/*}" };
  }
  rpc PatchThing(PatchReq) returns (Thing) {
    option (google.api.http) = {
      patch: "/v1/things/{thing.id}"
      body: "thing"
      additional_bindings { patch: "/v2/things/{thing.id}" body: "thing" }
      additional_bindings: { put: "/v1/things/{thing.id}" }
    };
  }
  rpc Purge(PurgeReq) returns (PurgeResp) {
    option (google.api.http) = { custom: { kind: "PURGE" path: "/v1/things" } };
  }
  rpc Plain(A) returns (B);
  rpc NoHttp(A) returns (B) { option deprecated = true; }
}
service Other {
  rpc GetThing(A) returns (B) { option (google.api.http).get = "/unsupported/shorthand"; }
}
"""


def test_proto_reader_finds_each_annotated_rpc_by_service() -> None:
    bindings = proto_http_bindings(_PROTO)
    assert set(bindings) == {("Things", "GetThing"), ("Things", "PatchThing"), ("Things", "Purge")}
    get = bindings[("Things", "GetThing")]
    assert (get.method, get.path, get.body) == ("get", "/v1/{name=things/*}", None)
    patch = bindings[("Things", "PatchThing")]
    assert (patch.method, patch.path, patch.body, patch.extra_bindings) == (
        "patch",
        "/v1/things/{thing.id}",
        "thing",
        2,
    )
    purge = bindings[("Things", "Purge")]
    assert (purge.method, purge.path) == ("purge", "/v1/things")
    assert purge.as_extras() == {"method": "purge", "path": "/v1/things"}


def test_proto_reader_tolerates_no_text() -> None:
    assert proto_http_bindings(None) == {}
    assert proto_http_bindings("") == {}


_SMITHY = """
$version: "2"
namespace demo

/// Docs mention @http(method: "PUT", uri: "/nope") but are comments.
@readonly
@http(method: "GET", uri: "/things/{id}", code: 200)
operation GetThing {
    input: GetThingInput
}

operation Unbound {
    input: GetThingInput
}

@endpoint(hostPrefix: "{region}.")
@http(method: "post", uri: "/things")
operation CreateThing {
    input: CreateThingInput
}

structure CreateThingInput {
    @required
    @hostLabel
    region: String
}
"""


def test_smithy_reader_binds_only_the_trait_on_each_operation() -> None:
    bindings = smithy_http_bindings(_SMITHY)
    assert set(bindings) == {"GetThing", "CreateThing"}
    assert (bindings["GetThing"].method, bindings["GetThing"].path) == ("get", "/things/{id}")
    assert (bindings["CreateThing"].method, bindings["CreateThing"].path) == ("post", "/things")
    assert smithy_unconverted_traits(_SMITHY) == ["endpoint", "hostLabel"]
    assert smithy_unconverted_traits(None) == []
    assert smithy_http_bindings(None) == {}


# ---------------------------------------------------------------------------
# Component keys
# ---------------------------------------------------------------------------


def _model_with_types(*keys: str) -> CanonicalApi:
    from app.canonical_model import CanonicalField
    from app.canonical_model import Type, TypeKind, TypeRef

    types = [
        Type(
            key=key,
            name=key,
            kind=TypeKind.RECORD,
            fields=[CanonicalField(key=f"{key}#next", name="next", type=TypeRef(name=keys[0]))],
        )
        for key in keys
    ]
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="wsdl",
        identity=ApiIdentity(name="Demo"),
        types=types,
    )


def test_invalid_component_keys_are_renamed_with_every_reference() -> None:
    api = _model_with_types("http://example.com/orders.Order", "orders.Order", "Map_['a', 'b']")
    renamed, renames = valid_component_keys(api)
    assert renames == {
        # The local part collides with a valid key that already exists, so it is suffixed.
        "http://example.com/orders.Order": "orders.Order_2",
        "Map_['a', 'b']": "Map_a_b",
    }
    keys = sorted(t.key for t in renamed.types)
    assert keys == ["Map_a_b", "orders.Order", "orders.Order_2"]
    # Every field referencing the first type now names its new key.
    assert {f.type.name for t in renamed.types for f in t.fields} == {"orders.Order_2"}
    # The source model is left alone.
    assert api.types[0].key == "http://example.com/orders.Order"


def test_valid_component_keys_leave_a_valid_model_untouched() -> None:
    api = _model_with_types("demo.Order")
    renamed, renames = valid_component_keys(api)
    assert renamed is api and renames == {}


# ---------------------------------------------------------------------------
# Report adjustments
# ---------------------------------------------------------------------------


def _report(score: int, tier: FidelityTier, grade: str = "B") -> FidelityReport:
    return FidelityReport(
        score=score, grade=grade, tier=tier, items=[], losses=[], coverage_counts={}, penalty=100 - score
    )


class _CeilingPack(ConversionPack):
    key = "ceiling-test"
    label = "Ceiling"
    formats = frozenset({"ceiling-test"})
    expected_tiers = (FidelityTier.LOW,)

    def tier_ceiling(self, api):
        return FidelityTier.LOW, Loss(kind=LossKind.NA, subject="cap", detail="why")

    def source_losses(self, source_text):
        return [Loss(kind=LossKind.NA, subject="trait", detail="lost")]


def test_tier_ceiling_lowers_score_grade_and_tier_together() -> None:
    capped = apply_tier_ceiling(_report(80, FidelityTier.MEDIUM), _CeilingPack(), None)
    assert (capped.score, capped.grade, capped.tier) == (59, "F", FidelityTier.LOW)
    assert [loss.subject for loss in capped.losses] == ["cap"]
    assert capped.penalty == 41
    # Already under the ceiling: the score stands, the explanation is still stated.
    low = apply_tier_ceiling(_report(40, FidelityTier.LOW, "F"), _CeilingPack(), None)
    assert (low.score, low.tier) == (40, FidelityTier.LOW)
    assert [loss.subject for loss in low.losses] == ["cap"]


def test_no_pack_means_no_adjustment() -> None:
    report = _report(80, FidelityTier.MEDIUM)
    assert apply_tier_ceiling(report, None, None) is report
    assert apply_source_losses(report, None, "text") is report


def test_source_losses_are_charged_like_projection_losses() -> None:
    charged = apply_source_losses(_report(87, FidelityTier.HIGH), _CeilingPack(), "text")
    # An n/a loss costs 5 points, and the tier is re-banded from the new score.
    assert (charged.score, charged.grade, charged.tier) == (82, "B", FidelityTier.MEDIUM)
    assert [loss.subject for loss in charged.losses] == ["trait"]


# ---------------------------------------------------------------------------
# External converter hook
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Stands in for the toolchain runner: records the call, returns canned stdout."""

    def __init__(self, stdout: str = "", error: Optional[Exception] = None) -> None:
        self.stdout = stdout
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def run(self, key, args=(), *, stdin=None, timeout=None, **_kwargs):
        self.calls.append({"key": key, "stdin": stdin})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(stdout=self.stdout)


_EXTERNAL_DOC = {"openapi": "3.1.0", "info": {"title": "From the tool", "version": "1"}, "paths": {}}


def test_external_converter_unavailable_falls_back_natively() -> None:
    pack = resolve_conversion_pack("odata", None)
    document, info = run_external_converter(pack, "<edmx/>", available=lambda _tool: False)
    assert document is None
    assert info.tool == "odata-openapi" and info.available is False and info.used is False
    assert "not installed" in info.fallback_reason


def test_external_converter_used_when_installed() -> None:
    runner = _FakeRunner(stdout=json.dumps(_EXTERNAL_DOC))
    pack = resolve_conversion_pack("odata", None)
    document, info = run_external_converter(
        pack, "<edmx/>", runner=runner, available=lambda _tool: True
    )
    assert document == _EXTERNAL_DOC
    assert info.used is True and info.fallback_reason is None
    assert runner.calls == [{"key": "odata-openapi", "stdin": "<edmx/>"}]


@pytest.mark.parametrize(
    "runner,reason",
    [
        (_FakeRunner(error=ToolExecutionError("graphql-tool", 1, "", "bad")), "failed"),
        (_FakeRunner(stdout="not json"), "not JSON"),
        (_FakeRunner(stdout=json.dumps({"swagger": "2.0"})), "OpenAPI 3.x"),
    ],
    ids=["exit-code", "not-json", "not-openapi"],
)
def test_external_converter_failures_fall_back_with_the_reason(runner, reason) -> None:
    pack = resolve_conversion_pack("graphql", None)
    document, info = run_external_converter(
        pack, "type Query { a: Int }", runner=runner, available=lambda _tool: True
    )
    assert document is None and info.used is False and info.available is True
    assert reason in info.fallback_reason


def test_external_converter_needs_text() -> None:
    pack = resolve_conversion_pack("graphql", None)
    document, info = run_external_converter(pack, None, available=lambda _tool: True)
    assert document is None and "not text" in info.fallback_reason


def test_a_pack_without_a_converter_reports_none() -> None:
    assert run_external_converter(resolve_conversion_pack("raml", None), "x") == (None, None)
    assert run_external_converter(None, "x") == (None, None)


def test_preview_uses_an_installed_converter_and_keeps_the_native_report(monkeypatch) -> None:
    runner = _FakeRunner(stdout=json.dumps(_EXTERNAL_DOC))
    monkeypatch.setattr("app.conversion_packs.is_tool_available", lambda _tool: True)
    monkeypatch.setattr("app.conversion_packs.default_runner", runner)
    item = _catalog_item("odata", EXAMPLES / "odata/01-northwind.edmx")
    preview = preview_conversion(build_conversion_source(item))
    assert preview.document["info"]["title"] == "From the tool"
    assert preview.pack.strategy == "external"
    assert preview.pack.external_converter.used is True
    # The report still describes what the source carries (the native analysis).
    assert preview.fidelity.tier is FidelityTier.HIGH


# ---------------------------------------------------------------------------
# Vendored googleapis protos
# ---------------------------------------------------------------------------


def test_vendored_googleapis_are_added_only_when_imported_and_not_supplied() -> None:
    annotated = ProtoFile(path="a.proto", content='import "google/api/annotations.proto";')
    added = [proto.path for proto in vendored_proto_imports([annotated])]
    assert added == ["google/api/http.proto", "google/api/annotations.proto"]
    assert "HttpRule http = 72295728" in vendored_proto_imports([annotated])[1].content

    only_http = ProtoFile(path="b.proto", content='import public "google/api/http.proto";')
    assert [p.path for p in vendored_proto_imports([only_http])] == ["google/api/http.proto"]

    supplied = ProtoFile(path="google/api/http.proto", content="syntax = \"proto3\";")
    assert [p.path for p in vendored_proto_imports([annotated, supplied])] == [
        "google/api/annotations.proto"
    ]

    plain = ProtoFile(path="c.proto", content='import "google/protobuf/timestamp.proto";')
    assert vendored_proto_imports([plain]) == []
