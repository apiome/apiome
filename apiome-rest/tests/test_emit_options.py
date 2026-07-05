"""Per-target emit options — MFX-1.4 (#3837).

Covers options schema + defaults on the registry target list, validation/coercion,
and the acceptance criterion that defaults produce schema-valid artifacts.
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
from app.emitter import (
    EmitOptionsError,
    coerce_emit_options,
    describe_emit_targets,
    load_builtin_emitters,
)
from app.export_service import ExportError, emit_canonical, resolve_emit_options
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_validator import validate_openapi_document
from app.sample_emitter import SampleEmitOptions, SampleEmitter


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


def test_describe_emit_targets_includes_options_schema_and_defaults() -> None:
    load_builtin_emitters()
    openapi = next(t for t in describe_emit_targets() if t.descriptor.key == "openapi")
    assert openapi.options_schema["title"] == "OpenApiEmitOptions"
    assert openapi.default_options == {
        "openapi_version": "3.1",
        "include_paths": True,
        "include_components": True,
        "include_projection_extensions": True,
    }

    sample = next(t for t in describe_emit_targets() if t.descriptor.key == "sample")
    assert sample.options_schema["title"] == "SampleEmitOptions"
    assert sample.default_options == {"content": ""}


def test_openapi_default_options_match_model() -> None:
    defaults = OpenApiEmitter.default_options()
    assert isinstance(defaults, OpenApiEmitOptions)
    assert defaults.model_dump() == OpenApiEmitOptions().model_dump()


def test_coerce_emit_options_rejects_unknown_fields() -> None:
    with pytest.raises(EmitOptionsError, match="extra"):
        coerce_emit_options(OpenApiEmitter, {"include_paths": True, "bogus": True})


def test_coerce_emit_options_rejects_invalid_types() -> None:
    with pytest.raises(EmitOptionsError):
        coerce_emit_options(OpenApiEmitter, {"include_paths": []})


def test_resolve_emit_options_via_export_service() -> None:
    opts = resolve_emit_options("openapi", {"include_components": False})
    assert isinstance(opts, OpenApiEmitOptions)
    assert opts.include_components is False
    assert opts.include_paths is True


def test_emit_canonical_defaults_produce_schema_valid_openapi() -> None:
    result = emit_canonical(_minimal_rest_api(), "openapi")
    assert validate_openapi_document(result.document) == []


def test_emit_canonical_with_default_options_dict_matches_bare_emit() -> None:
    api = _minimal_rest_api()
    bare = emit_canonical(api, "openapi")
    explicit = emit_canonical(api, "openapi", opts={})
    assert explicit.model_dump() == bare.model_dump()


def test_emit_canonical_components_only_option_still_valid() -> None:
    result = emit_canonical(
        _minimal_rest_api(),
        "openapi",
        opts={"include_paths": False, "include_components": True},
    )
    assert result.document["paths"] == {}
    assert "components" in result.document
    assert validate_openapi_document(result.document) == []


def test_emit_canonical_invalid_options_raises_export_error() -> None:
    with pytest.raises(ExportError) as exc:
        emit_canonical(_minimal_rest_api(), "openapi", opts={"include_paths": "nope"})
    assert exc.value.status_code == 422


def test_sample_emitter_options_change_artifact_content() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="sample-noop",
        identity=ApiIdentity(name="Sample"),
    )
    result = SampleEmitter().emit(api, opts=SampleEmitOptions(content="hello"))
    assert result.files[0].content == "hello"


def test_sample_default_options_produce_valid_artifact() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="sample-noop",
        identity=ApiIdentity(name="Sample"),
    )
    result = emit_canonical(api, "sample")
    assert result.files[0].content == ""
    assert result.media_type == "text/plain"
