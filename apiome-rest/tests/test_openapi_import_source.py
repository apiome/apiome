"""End-to-end tests for the OpenAPI/Swagger import source (MFI-1.1, #3733).

Exercises the reference adapter through the full SPI: detect → parse → normalize →
fingerprint/diff/lint, including the YAML intake, the Swagger 2.0 detection-but-no-
normalizer boundary, and lint delegation to the existing OpenAPI linter.
"""

from __future__ import annotations

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    InputKind,
    LintReport,
)
from app.openapi_import_source import OpenApiImportSource


def _petstore() -> dict:
    """A small but representative OpenAPI 3.1 document."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.4.0", "description": "Pets."},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/pets/{id}": {
                "get": {
                    "tags": ["pets"],
                    "summary": "Get a pet",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "description": "A pet.",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["id", "name"],
                }
            }
        },
    }


_YAML_SPEC = """
openapi: 3.0.3
info:
  title: YAML API
  version: 0.1.0
paths: {}
"""


@pytest.fixture()
def adapter() -> OpenApiImportSource:
    return OpenApiImportSource()


# ===========================================================================
# Descriptor
# ===========================================================================


def test_descriptor_metadata(adapter: OpenApiImportSource) -> None:
    d = adapter.descriptor()
    assert d.key == "openapi"
    assert d.paradigm is ApiParadigm.REST
    assert InputKind.FILE in d.input_kinds
    assert "openapi-3.2" in d.formats
    assert "swagger-2.0" in d.formats
    assert d.supports_live_discovery is False


# ===========================================================================
# Detection
# ===========================================================================


def test_detect_openapi_32(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(
        DetectionInput(document={"openapi": "3.2.0", "info": {"title": "T"}, "paths": {}})
    )
    assert result.format == "openapi-3.2"
    assert result.confidence > 0.9


def test_detect_openapi_31(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(DetectionInput(document=_petstore()))
    assert result.format == "openapi-3.1"
    assert result.confidence > 0.9


def test_detect_openapi_30_from_yaml_text(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(DetectionInput(text=_YAML_SPEC))
    assert result.format == "openapi-3.0"


def test_detect_swagger_2(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(DetectionInput(document={"swagger": "2.0", "info": {}}))
    assert result.format == "swagger-2.0"
    assert result.matched


def test_detect_non_spec_is_no_match(adapter: OpenApiImportSource) -> None:
    assert adapter.detect(DetectionInput(document={"hello": "world"})).matched is False
    # Malformed text must not raise, just fail to match.
    assert adapter.detect(DetectionInput(text="{not json or yaml: [")).matched is False


# ===========================================================================
# Parse
# ===========================================================================


def test_parse_json_and_yaml(adapter: OpenApiImportSource) -> None:
    parsed = adapter.parse(_YAML_SPEC)
    assert parsed["openapi"] == "3.0.3"
    assert parsed["info"]["title"] == "YAML API"


def test_parse_invalid_raises_import_source_error(adapter: OpenApiImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse("")


# ===========================================================================
# Normalize
# ===========================================================================


def test_normalize_produces_canonical_model(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_petstore())
    assert isinstance(model, CanonicalApi)
    assert model.paradigm is ApiParadigm.REST
    assert model.format == "openapi-3.1"
    assert model.identity.name == "Pet Store"
    assert model.version == "1.4.0"
    assert any(op.key == "GET /pets/{id}" for op in model.operations())
    assert model.type_by_key("Pet") is not None


def test_normalize_is_deterministic(adapter: OpenApiImportSource) -> None:
    a = adapter.normalize(_petstore())
    b = adapter.normalize(_petstore())
    assert adapter.fingerprint(a) == adapter.fingerprint(b)


def test_normalize_swagger_produces_canonical_model(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(
        {
            "swagger": "2.0",
            "info": {"title": "x", "version": "1"},
            "paths": {},
        }
    )
    assert model.format == "swagger-2.0"
    assert model.identity.name == "x"


def test_normalize_non_dict_raises(adapter: OpenApiImportSource) -> None:
    with pytest.raises(ImportSourceError, match="parsed mapping"):
        adapter.normalize("not a dict")


def test_normalize_non_spec_raises(adapter: OpenApiImportSource) -> None:
    with pytest.raises(ImportSourceError, match="version marker"):
        adapter.normalize({"hello": "world"})


def test_normalize_without_raw_omits_fidelity_bag(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_petstore(), include_raw=False)
    assert model.raw is None


# ===========================================================================
# Lint delegation
# ===========================================================================


def test_lint_delegates_to_openapi_linter(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_petstore())  # raw preserved by default
    report = adapter.lint(model)
    assert isinstance(report, LintReport)
    assert report.score is not None
    assert report.grade is not None
    # MFI-4.2: the schema linter's stable fingerprint is carried through on the report.
    assert report.report_fingerprint


def test_lint_without_raw_falls_back_to_canonical_engine(
    adapter: OpenApiImportSource,
) -> None:
    # MFI-4.2: with no native OpenAPI document to lint, the adapter falls back to the
    # canonical-model engine (the SPI default) so the revision is still rolled up to a
    # deterministic score/grade/fingerprint rather than left unscored.
    model = adapter.normalize(_petstore(), include_raw=False)
    report = adapter.lint(model)
    assert isinstance(report.score, int)
    assert 0 <= report.score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}
    assert report.report_fingerprint
