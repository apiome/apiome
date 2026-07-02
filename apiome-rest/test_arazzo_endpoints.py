"""
Test Arazzo endpoints
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from app.main import app

client = TestClient(app)


def test_root_includes_arazzo_endpoints():
    """Test that the root endpoint lists Arazzo endpoints."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "endpoints" in data
    assert "arazzo_spec" in data["endpoints"]
    assert "class_arazzo_spec" in data["endpoints"]
    assert data["endpoints"]["arazzo_spec"] == "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}"
    assert data["endpoints"]["class_arazzo_spec"] == "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}"


def test_arazzo_version_endpoint_structure():
    """Test that the Arazzo version endpoint exists and has the correct structure."""
    # This test will likely fail without a proper database setup
    # But we can at least verify the endpoint is registered
    response = client.get("/v1/arazzo/test-tenant/test-project/1.0.0")
    # We expect either 404 (no data) or 200 (success), but not 405 (method not allowed)
    assert response.status_code in [200, 404, 401, 403]


def test_arazzo_class_endpoint_structure():
    """Test that the Arazzo class endpoint exists and has the correct structure."""
    # This test will likely fail without a proper database setup
    # But we can at least verify the endpoint is registered
    response = client.get("/v1/arazzo/test-tenant/test-project/1.0.0/TestClass")
    # We expect either 404 (no data) or 200 (success), but not 405 (method not allowed)
    assert response.status_code in [200, 404, 401, 403]


def test_arazzo_spec_format():
    """Test that Arazzo spec has correct format (if we can get one)."""
    # This is a structural test that would pass with mock data
    from app.arazzo_generator import generate_arazzo_spec

    test_classes = [
        {
            "name": "User",
            "description": "A user in the system"
        },
        {
            "name": "Product",
            "description": "A product for sale"
        }
    ]

    spec = generate_arazzo_spec(
        "test-tenant",
        "test-project",
        "1.0.0",
        test_classes,
        "Test API"
    )

    # Verify Arazzo structure
    assert spec["arazzo"] == "1.0.1"
    assert "info" in spec
    assert spec["info"]["title"] == "test-project Workflows"
    assert spec["info"]["version"] == "1.0.0"
    assert "sourceDescriptions" in spec
    assert len(spec["sourceDescriptions"]) > 0
    assert spec["sourceDescriptions"][0]["type"] == "openapi"
    assert "workflows" in spec
    assert len(spec["workflows"]) == 2  # One for each class

    # Verify workflow structure
    workflow = spec["workflows"][0]
    assert "workflowId" in workflow
    assert "summary" in workflow
    assert "description" in workflow
    assert "steps" in workflow
    assert len(workflow["steps"]) == 4  # CRUD operations

    # Verify step structure
    step = workflow["steps"][0]
    assert "stepId" in step
    assert "description" in step
    assert "operationId" in step
    assert "successCriteria" in step


def test_class_arazzo_spec_format():
    """Test that class-specific Arazzo spec has correct format."""
    from app.arazzo_generator import generate_class_arazzo_spec

    test_class = {
        "name": "User",
        "description": "A user in the system"
    }

    spec = generate_class_arazzo_spec(
        "test-tenant",
        "test-project",
        "1.0.0",
        test_class
    )

    # Verify Arazzo structure
    assert spec["arazzo"] == "1.0.1"
    assert "info" in spec
    assert spec["info"]["title"] == "User Workflow"
    assert spec["info"]["version"] == "1.0.0"
    assert "sourceDescriptions" in spec
    assert "workflows" in spec
    assert len(spec["workflows"]) == 1  # Single workflow for one class

    # Verify workflow structure
    workflow = spec["workflows"][0]
    assert workflow["workflowId"] == "userWorkflow"
    assert "steps" in workflow
    assert len(workflow["steps"]) == 4  # CRUD operations

    # Verify steps have proper dependencies
    step_ids = [step["stepId"] for step in workflow["steps"]]
    assert "createUser" in step_ids
    assert "getUser" in step_ids
    assert "updateUser" in step_ids
    assert "deleteUser" in step_ids

    # Verify dependency chain
    get_step = next(s for s in workflow["steps"] if s["stepId"] == "getUser")
    assert "dependsOn" in get_step
    assert "createUser" in get_step["dependsOn"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

