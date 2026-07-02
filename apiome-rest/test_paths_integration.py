#!/usr/bin/env python3
"""
Test script to verify paths integration in OpenAPI generation.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from app.openapi_generator import generate_openapi_spec


def test_paths_integration():
    """Test that OpenAPI spec includes empty paths when version_db_id is None."""
    print("Test: Paths integration with version_db_id=None")
    print("=" * 60)

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = [
        {
            "id": "class-1",
            "name": "User",
            "description": "User model",
            "schema": '{"type": "object"}'
        }
    ]
    all_properties = {
        "class-1": []
    }
    project_description = "Test API"

    # Generate spec with version_db_id=None (no database connection in test)
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None
    )

    # Verify structure
    assert "openapi" in spec, "Missing 'openapi' field"
    assert spec["openapi"] == "3.1.0", "Wrong OpenAPI version"

    assert "info" in spec, "Missing 'info' field"
    assert spec["info"]["title"] == "test-project API", "Wrong title"
    assert spec["info"]["version"] == "1.0.0", "Wrong version"
    assert spec["info"]["description"] == "Test API", "Wrong description"

    assert "paths" in spec, "Missing 'paths' field"
    assert isinstance(spec["paths"], dict), "'paths' should be a dictionary"
    assert len(spec["paths"]) == 0, "Paths should be empty when version_db_id is None"

    assert "components" in spec, "Missing 'components' field"
    assert "schemas" in spec["components"], "Missing 'schemas' in components"
    assert "User" in spec["components"]["schemas"], "Missing User schema"

    print("\n✓ OpenAPI structure is correct")
    print(f"✓ OpenAPI version: {spec['openapi']}")
    print(f"✓ Title: {spec['info']['title']}")
    print(f"✓ Version: {spec['info']['version']}")
    print(f"✓ Description: {spec['info']['description']}")
    print(f"✓ Paths count: {len(spec['paths'])}")
    print(f"✓ Schemas count: {len(spec['components']['schemas'])}")

    print("\n✓ PASS: All assertions passed!")
    return True


def test_paths_structure():
    """Test that the paths field has the correct structure."""
    print("\n" + "=" * 60)
    print("Test: Paths field structure")
    print("=" * 60)

    tenant_slug = "test"
    project_slug = "api"
    version_id = "1.0.0"
    classes = []
    all_properties = {}

    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties
    )

    # Verify paths is a dict (not null or undefined)
    assert "paths" in spec, "paths field should exist"
    assert spec["paths"] is not None, "paths should not be None"
    assert isinstance(spec["paths"], dict), "paths should be a dictionary"

    print("\n✓ Paths field structure is correct")
    print(f"✓ Paths type: {type(spec['paths']).__name__}")
    print(f"✓ Paths value: {spec['paths']}")

    print("\n✓ PASS: Paths structure is valid!")
    return True


def main():
    """Run all tests."""
    print("\n" + "╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "OpenAPI Paths Integration Tests" + " " * 16 + "║")
    print("╚" + "=" * 58 + "╝\n")

    results = []
    results.append(test_paths_integration())
    results.append(test_paths_structure())

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)

    if all(results):
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
