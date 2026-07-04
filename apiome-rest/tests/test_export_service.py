"""Regression tests for export behind the Emitter SPI — MFX-1.3 (#3836).

Guards the acceptance criterion that existing OpenAPI export still works, now
routed through the emitter registry rather than a direct :class:`OpenApiEmitter`
import. Catalog conversion (:mod:`app.conversion_job`) is the live caller today.
"""

from __future__ import annotations

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.conversion_job import ConversionError, ConversionSource, preview_conversion
from app.export_service import ExportError, emit_canonical, resolve_emit_format
from app.openapi_emitter import OpenApiEmitter
from app.openapi_validator import validate_openapi_document


def _minimal_rest_api() -> CanonicalApi:
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="id", name="id", type=TypeRef(name="string"))],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="demo.Widgets"),
        title="Demo",
        version="1.0.0",
        servers=[Server(url="https://api.example.com")],
        types=[widget],
        services=[
            Service(
                key="WidgetsSvc",
                name="WidgetsSvc",
                operations=[
                    Operation(
                        key="GET /widgets",
                        name="listWidgets",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/widgets",
                        messages=[
                            Message(
                                key="GET /widgets#resp",
                                role=MessageRole.RESPONSE,
                                status_code="200",
                                content_types=["application/json"],
                                payload=TypeRef(name="Widget"),
                            )
                        ],
                    )
                ],
            )
        ],
    )


@pytest.mark.parametrize("target", ["openapi", "openapi-3.1"])
def test_resolve_emit_format_accepts_key_and_format(target: str) -> None:
    assert resolve_emit_format(target) == "openapi-3.1"


def test_emit_canonical_matches_direct_openapi_emitter() -> None:
    api = _minimal_rest_api()
    direct = OpenApiEmitter().emit(api)
    via_registry = emit_canonical(api, "openapi")
    assert via_registry.model_dump() == direct.model_dump()


def test_emit_canonical_produces_schema_valid_openapi() -> None:
    result = emit_canonical(_minimal_rest_api(), "openapi-3.1")
    assert validate_openapi_document(result.document) == []
    assert result.document["openapi"] == "3.1.0"
    assert result.files[0].path == "openapi.json"


def test_emit_canonical_unknown_target_raises() -> None:
    with pytest.raises(ExportError) as exc:
        emit_canonical(_minimal_rest_api(), "graphql")
    assert exc.value.status_code == 400
    assert "graphql" in str(exc.value)


def test_preview_conversion_routes_through_emitter_registry() -> None:
    source = ConversionSource(
        api=_minimal_rest_api(),
        source_project_id="proj-1",
        source_format="graphql",
        source_protocol="GraphQL",
    )
    preview = preview_conversion(source, target_format="openapi")
    assert preview.target_format == "openapi-3.1"
    assert validate_openapi_document(preview.document) == []


def test_preview_conversion_rejects_unknown_target() -> None:
    source = ConversionSource(
        api=_minimal_rest_api(),
        source_project_id="proj-1",
        source_format="graphql",
    )
    with pytest.raises(ConversionError) as exc:
        preview_conversion(source, target_format="graphql")
    assert exc.value.status_code == 400
