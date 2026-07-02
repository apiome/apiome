"""Tests for OpenAPI path template validation (#2644)."""

import pytest

from app.path_template_validation import validate_openapi_path_template


def test_valid_templates():
    validate_openapi_path_template("/users")
    validate_openapi_path_template("/users/{id}")
    validate_openapi_path_template("/v1/users/{userId}/posts/{postId}")


def test_empty_and_leading_slash():
    with pytest.raises(ValueError, match="empty"):
        validate_openapi_path_template("")
    with pytest.raises(ValueError, match="start with"):
        validate_openapi_path_template("users")


def test_unbalanced_braces():
    with pytest.raises(ValueError, match="balanced"):
        validate_openapi_path_template("/users/{id")


def test_duplicate_parameter_names():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_openapi_path_template("/users/{id}/posts/{id}")


def test_empty_brace_segment():
    with pytest.raises(ValueError, match="empty"):
        validate_openapi_path_template("/users/{}/x")
