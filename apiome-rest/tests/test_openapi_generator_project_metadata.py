"""project_metadata must surface in published OpenAPI info (imports store JSON on apiome.projects.metadata)."""

from app.openapi_generator import generate_openapi_spec


def test_generate_openapi_spec_merges_project_metadata_into_info():
    meta = {
        "summary": "Stock quote API",
        "termsOfService": "https://example.com/tos",
        "contact": {"name": "Support", "url": "https://example.com", "email": "hi@example.com"},
        "license": {"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0.html"},
    }
    spec = generate_openapi_spec(
        "acme",
        "quotes-api",
        "1.0.0",
        [],
        {},
        "Project column description",
        None,
        None,
        meta,
    )
    info = spec["info"]
    assert info["description"] == "Project column description"
    assert info["summary"] == "Stock quote API"
    assert info["termsOfService"] == "https://example.com/tos"
    assert info["contact"]["email"] == "hi@example.com"
    assert info["license"]["name"] == "Apache 2.0"
    assert spec["x-metadata"] == meta


def test_generate_openapi_spec_project_metadata_json_string():
    import json

    meta = {"contact": {"email": "a@b.co"}}
    spec = generate_openapi_spec(
        "t",
        "p",
        "1.0.0",
        [],
        {},
        None,
        None,
        None,
        json.dumps(meta),
    )
    assert spec["info"]["contact"]["email"] == "a@b.co"


def test_generate_openapi_spec_merges_vendor_keys_from_project_metadata_into_info():
    meta = {
        "contact": {"email": "contact@1forge.com", "name": "1Forge"},
        "x-providerName": "1forge.com",
        "x-logo": {"url": "https://example.com/logo.svg", "backgroundColor": "#24292e"},
    }
    spec = generate_openapi_spec(
        "acme",
        "forge-api",
        "1.0.0",
        [],
        {},
        "Stock and Forex Data",
        None,
        None,
        meta,
    )
    info = spec["info"]
    assert info["description"] == "Stock and Forex Data"
    assert info["contact"]["email"] == "contact@1forge.com"
    assert info["x-providerName"] == "1forge.com"
    assert info["x-logo"]["url"] == "https://example.com/logo.svg"
