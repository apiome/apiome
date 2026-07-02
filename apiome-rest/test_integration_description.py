#!/usr/bin/env python3
"""
Integration test demonstrating the OpenAPI description feature.
This shows how project descriptions flow from database through to OpenAPI spec.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from app.openapi_generator import generate_openapi_spec, generate_class_openapi_spec


def test_version_spec_with_description():
    """Simulate a full version spec generation with project description."""
    print("=" * 70)
    print("Integration Test: Version OpenAPI Spec with Project Description")
    print("=" * 70)

    # Simulate data from database
    tenant_slug = "acme-corp"
    project_slug = "customer-api"
    version_id = "2.0.0"
    project_description = "RESTful API for managing customer data across our platform"

    classes = [
        {
            "id": "class-uuid-1",
            "name": "Customer",
            "description": "Customer entity",
            "schema": '{"type": "object"}'
        },
        {
            "id": "class-uuid-2",
            "name": "Order",
            "description": "Order entity",
            "schema": '{"type": "object"}'
        }
    ]

    all_properties = {
        "class-uuid-1": [],
        "class-uuid-2": []
    }

    # Generate spec
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    # Display results
    print("\nGenerated OpenAPI Specification Info:")
    print(f"  Title: {spec['info']['title']}")
    print(f"  Version: {spec['info']['version']}")
    print(f"  Description: {spec['info']['description']}")
    print(f"  Number of schemas: {len(spec['components']['schemas'])}")

    # Verify
    assert spec['info']['title'] == "customer-api API", "Title should be project-slug API"
    assert spec['info']['version'] == "2.0.0", "Version should match version_id"
    assert spec['info']['description'] == project_description, "Description should match project description"

    print("\n✓ All assertions passed!")
    return True


def test_version_spec_without_description():
    """Simulate a version spec generation without project description."""
    print("\n" + "=" * 70)
    print("Integration Test: Version OpenAPI Spec WITHOUT Project Description")
    print("=" * 70)

    # Simulate data from database (no description)
    tenant_slug = "startup-inc"
    project_slug = "prototype-api"
    version_id = "0.1.0"
    project_description = None  # Project has no description

    classes = [
        {
            "id": "class-uuid-3",
            "name": "Widget",
            "description": None,
            "schema": '{"type": "object"}'
        }
    ]

    all_properties = {
        "class-uuid-3": []
    }

    # Generate spec
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    # Display results
    print("\nGenerated OpenAPI Specification Info:")
    print(f"  Title: {spec['info']['title']}")
    print(f"  Version: {spec['info']['version']}")
    print(f"  Description: {spec['info']['description']}")
    print(f"  Number of schemas: {len(spec['components']['schemas'])}")

    # Verify
    assert spec['info']['description'] == "No description provided", \
        "Description should default when project description is None"

    print("\n✓ All assertions passed!")
    return True


def test_class_spec():
    """Simulate a single class spec generation."""
    print("\n" + "=" * 70)
    print("Integration Test: Single Class OpenAPI Spec")
    print("=" * 70)

    tenant_slug = "tech-co"
    project_slug = "inventory-system"
    version_id = "3.2.1"

    class_data = {
        "id": "class-uuid-product",
        "name": "Product",
        "description": "Represents a product in the inventory",
        "schema": '{"type": "object"}'
    }

    properties = []

    # Generate spec (note: this function doesn't use project description)
    spec = generate_class_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        class_data,
        properties
    )

    # Display results
    print("\nGenerated OpenAPI Specification Info:")
    print(f"  Title: {spec['info']['title']}")
    print(f"  Version: {spec['info']['version']}")
    print(f"  Description: {spec['info']['description']}")
    print(f"  Schemas: {list(spec['components']['schemas'].keys())}")

    # Verify
    assert spec['info']['title'] == "Product", "Title should be class name"
    assert "Product" in spec['components']['schemas'], "Schema should contain the class"

    print("\n✓ All assertions passed!")
    return True


def main():
    """Run all integration tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 10 + "OpenAPI Description Feature - Integration Tests" + " " * 10 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    try:
        results = []
        results.append(test_version_spec_with_description())
        results.append(test_version_spec_without_description())
        results.append(test_class_spec())

        print("\n" + "=" * 70)
        print(f"Integration Test Results: {sum(results)}/{len(results)} passed")
        print("=" * 70)

        if all(results):
            print("\n✓ All integration tests passed successfully!")
            return 0
        else:
            print("\n✗ Some integration tests failed!")
            return 1

    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

