"""Unit tests for Arazzo 1.0 local validation."""

from __future__ import annotations

import pytest

from apiome_cli.import_.arazzo import (
    ArazzoStructureError,
    validate_arazzo_structure,
)

_VALID_ARAZZO = {
    "arazzo": "1.0.0",
    "info": {"title": "Checkout Flow", "version": "1.0.0"},
    "sourceDescriptions": [
        {
            "name": "openapi",
            "url": "https://example.test/openapi.json",
            "type": "openapi",
        }
    ],
    "workflows": [
        {
            "workflowId": "checkout",
            "steps": [{"stepId": "createCart", "operationId": "createCart"}],
        }
    ],
}


def test_validate_arazzo_structure_accepts_valid_document() -> None:
    """Valid Arazzo 1.0 documents pass schema validation."""
    validate_arazzo_structure(_VALID_ARAZZO)


def test_validate_arazzo_structure_rejects_missing_info() -> None:
    """Missing required fields raise ArazzoStructureError with a pointer."""
    document = {**_VALID_ARAZZO}
    del document["info"]
    with pytest.raises(ArazzoStructureError) as exc_info:
        validate_arazzo_structure(document)
    assert "info" in exc_info.value.message.lower() or "At /" in exc_info.value.message
