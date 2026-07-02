"""Tests for OpenAPI structural validation (openapi-spec-validator).

Covers:
- Valid OpenAPI 3.0.x, 3.1.x, and 3.2.x documents pass validation
- Swagger 2.0 detection and validation
- Version detection metadata (keyword, raw version, family)
- Invalid specs raise OpenApiStructureError with validator message
- OpenApiStructureError uses EXIT_USAGE (2) for CLI mapping
- load_and_validate_openapi_file integrates parse + validate
- Unsupported or missing version fields
"""

from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.openapi import (
    OpenApiStructureError,
    OpenApiVersionInfo,
    detect_openapi_version,
    load_and_validate_openapi_file,
    validate_openapi_structure,
)

# ---------------------------------------------------------------------------
# Helpers — minimal valid specs per OpenAPI minor version
# ---------------------------------------------------------------------------


def _openapi_doc(openapi_version: str) -> dict:
    return {
        "openapi": openapi_version,
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }


def _swagger_doc() -> dict:
    return {
        "swagger": "2.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }


_INVALID_MISSING_INFO_VERSION = {
    "openapi": "3.1.0",
    "info": {"title": "Test API"},
    "paths": {},
}


# ---------------------------------------------------------------------------
# Valid specs — 3.0.x / 3.1.x / 3.2.x
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "openapi_version,family",
    [
        ("3.0.0", "3.0.x"),
        ("3.0.3", "3.0.x"),
        ("3.1.0", "3.1.x"),
        ("3.2.0", "3.2.x"),
    ],
)
def test_validate_openapi_structure_accepts_supported_versions(
    openapi_version: str,
    family: str,
) -> None:
    """Supported OpenAPI 3.x minor versions pass structural validation."""
    spec = _openapi_doc(openapi_version)

    version_info = validate_openapi_structure(spec)

    assert version_info == OpenApiVersionInfo(
        keyword="openapi",
        version=openapi_version,
        family=family,
    )


def test_validate_swagger_2_0() -> None:
    """Swagger 2.0 documents validate with the 2.0 schema."""
    spec = _swagger_doc()

    version_info = validate_openapi_structure(spec)

    assert version_info == OpenApiVersionInfo(
        keyword="swagger",
        version="2.0",
        family="2.0",
    )


def test_validate_openapi_structure_normalizes_swagger_file_response_schema() -> None:
    """Swagger response schemas with ``type: file`` validate after normalization."""
    spec = {
        "swagger": "2.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {
            "/policy": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "Policy payload",
                            "schema": {"type": "file"},
                        }
                    }
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["paths"]["/policy"]["get"]["responses"]["200"]["schema"]
    assert schema == {"type": "string", "format": "binary"}
    assert len(warnings) == 1
    assert warnings[0].code == "swagger_legacy_type_normalized"


@pytest.mark.skipif(
    not Path(
        "/home/kenji/Development/openapi-directory/APIs/azure.com/"
        "apimanagement-apimapis/2016-10-10/swagger.yaml"
    ).is_file(),
    reason="Azure APIM fixture not available locally",
)
def test_validate_openapi_structure_accepts_azure_apim_swagger_fixture() -> None:
    """Azure APIM Swagger 2.0 specs with file responses pass local validation."""
    from apiome_cli.import_.openapi import load_openapi_file

    spec = load_openapi_file(
        "/home/kenji/Development/openapi-directory/APIs/azure.com/"
        "apimanagement-apimapis/2016-10-10/swagger.yaml"
    )
    validate_openapi_structure(spec)


def test_detect_openapi_version_returns_metadata() -> None:
    """detect_openapi_version returns keyword, raw version, and family."""
    spec = _openapi_doc("3.1.0")

    version_info = detect_openapi_version(spec)

    assert version_info.keyword == "openapi"
    assert version_info.version == "3.1.0"
    assert version_info.family == "3.1.x"


# ---------------------------------------------------------------------------
# Invalid specs — validator message and exit code
# ---------------------------------------------------------------------------


def test_invalid_spec_raises_structure_error_with_validator_message() -> None:
    """Invalid specs raise OpenApiStructureError including validator detail."""
    with pytest.raises(OpenApiStructureError, match="version.*required") as exc_info:
        validate_openapi_structure(_INVALID_MISSING_INFO_VERSION)

    assert "'version' is a required property" in exc_info.value.message


def test_structure_error_exit_code_is_usage() -> None:
    """OpenApiStructureError maps to EXIT_USAGE (2) for CLI commands."""
    with pytest.raises(OpenApiStructureError) as exc_info:
        validate_openapi_structure(_INVALID_MISSING_INFO_VERSION)

    assert exc_info.value.exit_code == EXIT_USAGE


def test_missing_version_field_raises_structure_error() -> None:
    """Documents without openapi/swagger raise OpenApiStructureError."""
    spec = {"info": {"title": "T", "version": "1"}, "paths": {}}

    with pytest.raises(OpenApiStructureError, match="version field"):
        detect_openapi_version(spec)


def test_unsupported_openapi_version_raises_structure_error() -> None:
    """Unsupported openapi version strings are rejected before validation."""
    spec = _openapi_doc("3.3.0")

    with pytest.raises(OpenApiStructureError, match="Unsupported openapi version"):
        detect_openapi_version(spec)


def test_swagger_invalid_missing_paths_raises_structure_error() -> None:
    """Incomplete Swagger 2.0 documents fail validation with a clear message."""
    spec = {
        "swagger": "2.0",
        "info": {"title": "T", "version": "1"},
    }

    with pytest.raises(OpenApiStructureError, match="paths.*required"):
        validate_openapi_structure(spec)


def test_validate_openapi_structure_coerces_integer_default_from_string() -> None:
    """String integer defaults are coerced before openapi-spec-validator runs."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "parameters": {
                "limit": {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": "100"},
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["components"]["parameters"]["limit"]["schema"]
    assert schema["default"] == 100
    assert len(warnings) == 1
    assert warnings[0].code == "schema_default_type_coercion"


def test_validate_openapi_structure_normalizes_null_default_on_date_time() -> None:
    """Null defaults on non-nullable schemas are normalized before validation."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                "UpdatedAt": {
                    "type": "string",
                    "format": "dateTime",
                    "default": None,
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["components"]["schemas"]["UpdatedAt"]
    assert schema["nullable"] is True
    assert schema["default"] is None
    assert len(warnings) == 1
    assert warnings[0].code == "schema_null_default_normalization"


def test_validate_openapi_structure_coerces_array_default_from_scalar_string() -> None:
    """Scalar defaults on array-typed schemas are wrapped before validation."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "parameters": {
                "sort": {
                    "name": "sort",
                    "in": "query",
                    "schema": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["created_at"],
                        },
                        "default": "created_at",
                    },
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["components"]["parameters"]["sort"]["schema"]
    assert schema["default"] == ["created_at"]
    assert len(warnings) == 1
    assert warnings[0].code == "schema_default_type_coercion"


def test_validate_openapi_structure_coerces_array_default_from_comma_separated_string() -> None:
    """Comma-separated defaults on array-typed schemas are split before validation."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "parameters": {
                "sort": {
                    "name": "sort",
                    "in": "query",
                    "schema": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "created_at",
                                "first_name",
                                "last_name",
                                "updated_at",
                            ],
                        },
                        "default": "last_name,first_name",
                    },
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["components"]["parameters"]["sort"]["schema"]
    assert schema["default"] == ["last_name", "first_name"]
    assert len(warnings) == 1
    assert warnings[0].code == "schema_default_type_coercion"


def test_validate_openapi_structure_coerces_array_example_from_scalar_string() -> None:
    """Scalar examples on array-typed schemas are wrapped before validation."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                "Tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "example": "news",
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["components"]["schemas"]["Tags"]
    assert schema["example"] == ["news"]
    assert len(warnings) == 1
    assert warnings[0].code == "schema_example_type_coercion"


def test_validate_openapi_structure_coerces_parameter_example_for_array_schema() -> None:
    """Parameter-level examples are wrapped when the schema type is array."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {
            "/items": {
                "get": {
                    "responses": {"200": {"description": "OK"}},
                    "parameters": [
                        {
                            "name": "tags",
                            "in": "query",
                            "schema": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "example": "news",
                        }
                    ],
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    parameter = spec["paths"]["/items"]["get"]["parameters"][0]
    assert parameter["example"] == ["news"]
    assert len(warnings) == 1
    assert warnings[0].code == "schema_example_type_coercion"


def test_validate_openapi_structure_preserves_yaml_parameter_name_on() -> None:
    from apiome_cli.import_.openapi import validate_openapi_structure

    spec = {
        "openapi": "3.0.1",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {
            "/items/microsoft.graph.filterByCurrentUser(on='{on}')": {
                "get": {
                    "parameters": [
                        {
                            "name": "on",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    validate_openapi_structure(spec)
    parameter = spec["paths"]["/items/microsoft.graph.filterByCurrentUser(on='{on}')"]["get"][
        "parameters"
    ][0]
    assert parameter["name"] == "on"


def test_validate_openapi_structure_accepts_microsoft_graph_beta_fixture() -> None:
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/microsoft.com/"
        "graph-beta/1.0.1/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Microsoft Graph beta fixture spec not available")

    spec = load_openapi_file(str(path))
    path_key = (
        "/identityGovernance/accessReviews/decisions/"
        "microsoft.graph.filterByCurrentUser(on='{on}')"
    )
    parameter = spec["paths"][path_key]["get"]["parameters"][0]
    assert parameter["name"] == "on"
    validate_openapi_structure(spec)


def test_validate_openapi_structure_accepts_mastercard_swagger_fixture() -> None:
    """Mastercard Swagger 2.0 schemas use Draft 4 boolean exclusiveMinimum."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/mastercard.com/"
        "open-banking-connect-pis/1.16.0/swagger.yaml"
    )
    if not path.is_file():
        pytest.skip("Mastercard fixture spec not available")

    spec = load_openapi_file(str(path))
    validate_openapi_structure(spec)

    amount = spec["definitions"][
        "postPaymentsDomesticCreditTransfersConsentsParamsBodyPaymentsInstructedAmount"
    ]["properties"]["amount"]
    assert amount["exclusiveMinimum"] is True
    assert amount["minimum"] == 0


def test_validate_openapi_structure_accepts_nba_swagger_fixture() -> None:
    """NBA Swagger 2.0 responses may use YAML integer status code keys."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/nba.com/version/swagger.yaml"
    )
    if not path.is_file():
        pytest.skip("NBA fixture spec not available")

    spec = load_openapi_file(str(path))
    validate_openapi_structure(spec)

    responses = spec["paths"]["/allstarballotpredictor"]["get"]["responses"]
    assert "200" in responses
    assert "400" in responses
    assert "404" in responses


def test_validate_openapi_structure_coerces_nbg_string_parameter_required() -> None:
    """NBG parameters may declare required as the string 'true'."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/nbg.gr/v3.1.5/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NBG fixture spec not available")

    spec = load_openapi_file(str(path))
    spec["paths"]["/account-access-consents"]["post"]["parameters"][4][
        "required"
    ] = "true"
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    parameter = spec["paths"]["/account-access-consents"]["post"]["parameters"][4]
    assert parameter["required"] is True
    assert any(warning.code == "openapi_boolean_field_coerced" for warning in warnings)


def test_validate_openapi_structure_coerces_ndhm_string_request_body_required() -> None:
    """NDHM request bodies may declare required as the string 'true'."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ndhm.gov.in/"
        "ndhm-cm/0.5/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NDHM fixture spec not available")

    spec = load_openapi_file(str(path))
    spec["paths"]["/v0.5/care-contexts/on-discover"]["post"]["requestBody"][
        "required"
    ] = "true"
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    request_body = spec["paths"]["/v0.5/care-contexts/on-discover"]["post"]["requestBody"]
    assert request_body["required"] is True
    assert any(warning.code == "openapi_boolean_field_coerced" for warning in warnings)


def test_validate_openapi_structure_accepts_ndhm_gateway_fixture() -> None:
    """NDHM gateway openid-configuration response validates after import prep."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ndhm.gov.in/"
        "ndhm-gateway/0.5/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NDHM gateway fixture spec not available")

    spec = load_openapi_file(str(path))
    validate_openapi_structure(spec)
    response = spec["paths"]["/v0.5/.well-known/openid-configuration"]["get"]["responses"][
        "200"
    ]
    assert response["description"] == "OK"


def test_validate_openapi_structure_coerces_ndhm_gateway_missing_response_description() -> None:
    """Responses with content but no description are coerced before validation."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ndhm.gov.in/"
        "ndhm-gateway/0.5/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NDHM gateway fixture spec not available")

    spec = load_openapi_file(str(path))
    response = spec["paths"]["/v0.5/.well-known/openid-configuration"]["get"]["responses"][
        "200"
    ]
    spec["paths"]["/v0.5/.well-known/openid-configuration"]["get"]["responses"]["200"] = {
        "content": response["content"]
    }
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)
    assert spec["paths"]["/v0.5/.well-known/openid-configuration"]["get"]["responses"]["200"][
        "description"
    ] == "200"
    assert any(
        warning.code == "empty_response_description_coercion" for warning in warnings
    )


def test_validate_openapi_structure_accepts_ndhm_healthid_fixture() -> None:
    """NDHM healthid validates after import prep."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ndhm.gov.in/"
        "ndhm-healthid/1.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NDHM healthid fixture spec not available")

    spec = load_openapi_file(str(path))
    validate_openapi_structure(spec)


def test_validate_openapi_structure_coerces_ndhm_healthid_string_parameter_required() -> None:
    """NDHM healthid parameters may declare required as the string 'true'."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ndhm.gov.in/"
        "ndhm-healthid/1.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("NDHM healthid fixture spec not available")

    spec = load_openapi_file(str(path))
    spec["paths"]["/v1/account/aadhaar/generateOTP"]["post"]["parameters"][1][
        "required"
    ] = "true"
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    parameter = spec["paths"]["/v1/account/aadhaar/generateOTP"]["post"]["parameters"][1]
    assert parameter["required"] is True
    assert any(warning.code == "openapi_boolean_field_coerced" for warning in warnings)


def test_validate_openapi_structure_accepts_openai_fixture() -> None:
    """OpenAI schemas remove non-integer ``inf`` defaults before validation."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/openai.com/1.2.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("OpenAI fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    max_tokens = spec["components"]["schemas"]["CreateChatCompletionRequest"][
        "properties"
    ]["max_tokens"]
    assert "default" not in max_tokens
    assert any(warning.code == "schema_default_removed" for warning in warnings)


def test_validate_openapi_structure_normalizes_openapi_generator_file_schema() -> None:
    """OpenAPI Generator vendor response schemas may use legacy ``type: file``."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/openapi-generator.tech/"
        "6.5.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("OpenAPI Generator fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    schema = spec["paths"]["/api/gen/download/{fileId}"]["get"]["x-responsesObject"][
        "200"
    ]["schema"]
    assert schema == {"type": "string", "format": "binary"}
    assert any(warning.code == "swagger_legacy_type_normalized" for warning in warnings)


def test_validate_openapi_structure_accepts_optimade_empty_email_default() -> None:
    """OPTIMADE query params may declare ``format: email`` with ``default: \"\"``."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/optimade.local/"
        "1.1.0~develop/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("OPTIMADE fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    params = spec["paths"]["/structures"]["get"]["parameters"]
    email_param = next(p for p in params if p.get("name") == "email_address")
    assert "default" not in email_param["schema"]
    assert any(
        warning.code == "schema_format_default_removed" for warning in warnings
    )


def test_validate_openapi_structure_accepts_godaddy_empty_object_default() -> None:
    """GoDaddy domain notifications may use ``default: \"\"`` on ``type: object``."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/ote-godaddy.com/domains/"
        "1.0.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("GoDaddy fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    metadata = spec["components"]["schemas"]["DomainNotification"]["properties"][
        "metadata"
    ]
    assert "default" not in metadata
    assert any(warning.code == "schema_default_removed" for warning in warnings)


def test_validate_openapi_structure_accepts_image_charts_swagger() -> None:
    """Image-Charts Swagger 2.0 query parameters use empty defaults with strict patterns."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/image-charts.com/6.1.19/swagger.yaml"
    )
    if not path.is_file():
        pytest.skip("Image-Charts fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    chtt = spec["paths"]["/chart"]["get"]["parameters"][13]
    assert chtt["name"] == "chtt"
    assert "default" not in chtt
    assert chtt["pattern"].startswith("^[a-z0-9sW")
    assert any(
        warning.code == "schema_pattern_default_removed" for warning in warnings
    )


def test_validate_openapi_structure_accepts_oxford_string_boolean_enum() -> None:
    """Oxford Dictionaries may declare boolean enums with string literals."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/oxforddictionaries.com/"
        "1.11.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Oxford Dictionaries fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    prefix_schema = next(
        param["schema"]
        for path_item in spec["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict)
        for param in operation.get("parameters", [])
        if param.get("name") == "prefix"
    )
    assert prefix_schema["enum"] == [False, True]
    assert prefix_schema["default"] is False
    assert any(
        warning.code == "schema_boolean_literal_normalized" for warning in warnings
    )


def test_validate_openapi_structure_accepts_bhagavadgita_string_enum_defaults() -> None:
    """Bhagavad Gita declares string path params with integer enum/default values."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/bhagavadgita.io/1.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Bhagavad Gita fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    verse_schema = next(
        param["schema"]
        for path_item in spec["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict)
        for param in operation.get("parameters", [])
        if param.get("name") == "verse_number"
    )
    assert verse_schema["enum"] == ["1", "2", "3"]
    assert verse_schema["default"] == "1"
    assert any(warning.code == "schema_enum_type_coercion" for warning in warnings)


def test_validate_openapi_structure_accepts_biapi_python_function_date_time_defaults() -> None:
    """Biapi exports Flask-style ``datetime.now`` reprs as date-time defaults."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/biapi.pro/2.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Biapi fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    created = spec["components"]["schemas"]["Connection"]["properties"]["created"]
    assert "default" not in created
    assert any(
        warning.code == "schema_format_default_removed" for warning in warnings
    )


def test_validate_openapi_structure_accepts_brainbi_empty_parameter_names() -> None:
    """Brainbi Postman export uses empty query parameter names as placeholders."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/brainbi.net/1.0.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Brainbi fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    customers = spec["paths"]["/api/customers"]["get"]
    assert customers["parameters"] == []
    assert any(
        warning.code == "empty_parameter_name_removed" for warning in warnings
    )


def test_validate_openapi_structure_accepts_icons8_embedded_query_path() -> None:
    from pathlib import Path

    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/icons8.com/1.0.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Icons8 fixture spec not available")

    preparation_warnings: list = []
    spec = load_openapi_file(str(path))
    validate_openapi_structure(spec, preparation_warnings=preparation_warnings)

    latest = spec["paths"]["/api/iconsets/v3/latest"]["get"]
    assert latest["parameters"][-1]["name"] == "term"
    assert latest["parameters"][-1]["in"] == "query"
    assert any(
        warning.code == "embedded_query_path_normalized" for warning in preparation_warnings
    )


def test_validate_openapi_structure_accepts_contract_p_invalid_enum_default() -> None:
    """Contract-p.fit removes invalid enum defaults before openapi-spec-validator runs."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/contract-p.fit/1.0/openapi.yaml"
    )
    if not path.is_file():
        pytest.skip("Contract-p.fit fixture spec not available")

    spec = load_openapi_file(str(path))
    warnings: list = []
    validate_openapi_structure(spec, preparation_warnings=warnings)

    how_schema = spec["paths"]["/documents/{document_id}"]["delete"]["parameters"][0][
        "schema"
    ]
    assert "default" not in how_schema
    assert any(warning.code == "schema_enum_default_removed" for warning in warnings)


def test_validate_openapi_structure_resolves_sibling_file_refs(tmp_path: Path) -> None:
    """Relative file $ref values resolve from the spec path during validation."""
    from apiome_cli.import_.openapi import load_openapi_file

    sibling = tmp_path / "routeFilter.json"
    sibling.write_text(
        json.dumps(
            {
                "definitions": {
                    "RouteFilter": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    spec_path = tmp_path / "swagger.yaml"
    spec_path.write_text(
        textwrap.dedent(
            """\
            swagger: "2.0"
            info:
              title: External Ref Test
              version: "1.0.0"
            paths: {}
            definitions:
              ExpressRouteCrossConnection:
                type: object
                properties:
                  routeFilter:
                    $ref: './routeFilter.json#/definitions/RouteFilter'
            """
        ),
        encoding="utf-8",
    )

    spec = load_openapi_file(str(spec_path))
    validate_openapi_structure(spec, source=str(spec_path))


def test_validate_openapi_structure_warns_on_missing_external_file_ref() -> None:
    """Missing external file refs become warnings during import prep, not crashes."""
    from apiome_cli.import_.openapi import load_openapi_file

    path = Path(
        "/home/kenji/Development/openapi-directory/APIs/azure.com/"
        "network-expressRouteCrossConnection/2018-02-01/swagger.yaml"
    )
    if not path.is_file():
        pytest.skip("Azure expressRouteCrossConnection fixture not available locally")

    spec = load_openapi_file(str(path))
    warnings: list = []
    version_info = validate_openapi_structure(
        spec,
        source=str(path),
        preparation_warnings=warnings,
    )

    assert version_info.keyword == "swagger"
    assert any(warning.code == "external_ref_not_followed" for warning in warnings)


def test_validate_openapi_structure_missing_external_ref_raises_without_warnings(
    tmp_path: Path,
) -> None:
    """Direct validation without preparation_warnings still fails on missing external refs."""
    spec_path = tmp_path / "swagger.yaml"
    spec_path.write_text(
        textwrap.dedent(
            """\
            swagger: "2.0"
            info:
              title: External Ref Test
              version: "1.0.0"
            paths:
              /items:
                get:
                  responses:
                    "200":
                      schema:
                        $ref: './routeFilter.json#/definitions/RouteFilter'
            """
        ),
        encoding="utf-8",
    )
    from apiome_cli.import_.openapi import load_openapi_file

    spec = load_openapi_file(str(spec_path))
    with pytest.raises(OpenApiStructureError, match=r"routeFilter\.json"):
        validate_openapi_structure(spec, source=str(spec_path))


# ---------------------------------------------------------------------------
# load_and_validate_openapi_file
# ---------------------------------------------------------------------------


def test_load_and_validate_json_file(tmp_path: Path) -> None:
    """load_and_validate_openapi_file parses and validates a JSON spec."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(_openapi_doc("3.1.0")),
        encoding="utf-8",
    )

    spec, version_info = load_and_validate_openapi_file(str(spec_path))

    assert spec["openapi"] == "3.1.0"
    assert version_info.family == "3.1.x"


def test_load_and_validate_yaml_file(tmp_path: Path) -> None:
    """load_and_validate_openapi_file works for YAML files."""
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        textwrap.dedent(
            """\
            openapi: "3.2.0"
            info:
              title: Test API
              version: "1.0.0"
            paths: {}
            """
        ),
        encoding="utf-8",
    )

    _spec, version_info = load_and_validate_openapi_file(str(spec_path))

    assert version_info.version == "3.2.0"
    assert version_info.family == "3.2.x"


def test_load_and_validate_invalid_file_raises_structure_error(
    tmp_path: Path,
) -> None:
    """Invalid on-disk specs raise OpenApiStructureError after parsing."""
    spec_path = tmp_path / "bad.json"
    spec_path.write_text(json.dumps(_INVALID_MISSING_INFO_VERSION), encoding="utf-8")

    with pytest.raises(OpenApiStructureError, match="required"):
        load_and_validate_openapi_file(str(spec_path))


def test_load_and_validate_stdin() -> None:
    """stdin specs are parsed and validated when path is '-'."""
    content = json.dumps(_openapi_doc("3.0.0"))
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(content)):
        _spec, version_info = load_and_validate_openapi_file("-")

    assert version_info.family == "3.0.x"


def test_validate_drops_nonconforming_enum_default_and_warns() -> None:
    """A default that violates its schema's enum is dropped (not fatal), with a warning.

    Regression: third-party specs (e.g. adyen.com PayoutService) carry placeholder
    defaults like ['<all available types>'] that fail items.enum; the import must
    succeed by dropping only the offending value.
    """
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                "DeviceRenderOptions": {
                    "type": "object",
                    "properties": {
                        "sdkUiType": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "multiSelect",
                                    "otherHtml",
                                    "outOfBand",
                                    "singleSelect",
                                    "text",
                                ],
                            },
                            "default": ["<all available types>"],
                        },
                    },
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    sdk = spec["components"]["schemas"]["DeviceRenderOptions"]["properties"]["sdkUiType"]
    assert "default" not in sdk
    codes = [w.code for w in warnings]
    assert "schema.value.nonconforming_dropped" in codes


def test_validate_keeps_conforming_default_untouched() -> None:
    """A default that satisfies its schema's enum is preserved, with no drop warning."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                "Mode": {
                    "type": "string",
                    "enum": ["text", "html"],
                    "default": "text",
                }
            }
        },
    }
    warnings: list = []

    validate_openapi_structure(spec, preparation_warnings=warnings)

    assert spec["components"]["schemas"]["Mode"]["default"] == "text"
    assert not any(w.code == "schema.value.nonconforming_dropped" for w in warnings)


def test_validate_still_raises_on_structural_error_after_value_drop() -> None:
    """Dropping advisory values does not mask genuine structural errors."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Demo"},  # missing required 'version' -> structural
        "paths": {},
        "components": {
            "schemas": {
                "X": {
                    "type": "string",
                    "enum": ["a"],
                    "default": "not-in-enum",
                }
            }
        },
    }

    with pytest.raises(OpenApiStructureError):
        validate_openapi_structure(spec)
