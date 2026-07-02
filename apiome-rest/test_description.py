#!/usr/bin/env python3
"""
Test script to verify that OpenAPI description is correctly using project description.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from app.openapi_generator import generate_openapi_spec


def test_description_with_project_description():
    """Test that project description is used when provided."""
    print("Test 1: With project description provided...")

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = []
    all_properties = {}
    project_description = "This is my custom project description"

    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    expected_description = "This is my custom project description"
    actual_description = spec["info"]["description"]

    if actual_description == expected_description:
        print(f"✓ PASS: Description correctly set to: '{actual_description}'")
        return True
    else:
        print(f"✗ FAIL: Expected '{expected_description}' but got '{actual_description}'")
        return False


def test_description_without_project_description():
    """Test that default description is used when project description is None."""
    print("\nTest 2: With project description as None...")

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = []
    all_properties = {}
    project_description = None

    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    expected_description = "No description provided"
    actual_description = spec["info"]["description"]

    if actual_description == expected_description:
        print(f"✓ PASS: Description correctly defaulted to: '{actual_description}'")
        return True
    else:
        print(f"✗ FAIL: Expected '{expected_description}' but got '{actual_description}'")
        return False


def test_description_with_empty_string():
    """Test that default description is used when project description is empty string."""
    print("\nTest 3: With project description as empty string...")

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = []
    all_properties = {}
    project_description = ""

    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    expected_description = "No description provided"
    actual_description = spec["info"]["description"]

    if actual_description == expected_description:
        print(f"✓ PASS: Description correctly defaulted to: '{actual_description}'")
        return True
    else:
        print(f"✗ FAIL: Expected '{expected_description}' but got '{actual_description}'")
        return False


def test_description_with_whitespace():
    """Test that default description is used when project description is only whitespace."""
    print("\nTest 4: With project description as whitespace...")

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = []
    all_properties = {}
    project_description = "   "

    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties,
        project_description,
        version_db_id=None  # not needed for this test
    )

    expected_description = "No description provided"
    actual_description = spec["info"]["description"]

    if actual_description == expected_description:
        print(f"✓ PASS: Description correctly defaulted to: '{actual_description}'")
        return True
    else:
        print(f"✗ FAIL: Expected '{expected_description}' but got '{actual_description}'")
        return False


def test_description_omitted():
    """Test that default description is used when project description parameter is omitted."""
    print("\nTest 5: With project description parameter omitted...")

    tenant_slug = "test-tenant"
    project_slug = "test-project"
    version_id = "1.0.0"
    classes = []
    all_properties = {}

    # Call without project_description parameter
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_id,
        classes,
        all_properties
    )

    expected_description = "No description provided"
    actual_description = spec["info"]["description"]

    if actual_description == expected_description:
        print(f"✓ PASS: Description correctly defaulted to: '{actual_description}'")
        return True
    else:
        print(f"✗ FAIL: Expected '{expected_description}' but got '{actual_description}'")
        return False


def main():
    """Run all tests."""
    print("Testing OpenAPI description generation...\n")
    print("=" * 60)

    results = []
    results.append(test_description_with_project_description())
    results.append(test_description_without_project_description())
    results.append(test_description_with_empty_string())
    results.append(test_description_with_whitespace())
    results.append(test_description_omitted())

    print("\n" + "=" * 60)
    print(f"\nTest Results: {sum(results)}/{len(results)} passed")

    if all(results):
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())

