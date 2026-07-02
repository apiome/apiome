"""Shared fixtures for httpx-mocked CLI integration tests."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

_API_KEY_ENV = {
    "APIOME_API_KEY": "test-integration-key",
    "APIOME_BASE_URL": "http://localhost:8000",
}

_VALID_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Integration Pet Store", "version": "1.0.0"},
    "paths": {},
}

_IMPORT_RESULT = {
    "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "version_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "project": {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "name": "Integration Pet Store",
        "slug": "integration-pet-store",
        "source": "import",
        "enabled": True,
    },
    "version": {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "version": "1.0.0",
        "slug": "1.0.0",
        "source": "import",
        "enabled": True,
    },
    "created": {
        "schemas": 0,
        "properties": 0,
        "project_properties": 0,
        "version_schemas": 0,
    },
    "warnings": [],
    "errors": [],
}

_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key; isolate from developer env."""
    for key, value in _API_KEY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("APIOME_TENANT_ID", raising=False)


def _write_openapi_spec(path: Path) -> Path:
    """Write a minimal valid OpenAPI document for import integration tests."""
    path.write_text(json.dumps(_VALID_OPENAPI_SPEC), encoding="utf-8")
    return path


@pytest.fixture
def runner() -> CliRunner:
    """CLI test runner for integration tests."""
    return CliRunner()


@pytest.fixture
def write_openapi_spec() -> Callable[[Path], Path]:
    """Factory that writes a minimal valid OpenAPI document to disk."""
    return _write_openapi_spec


@pytest.fixture
def strip_ansi() -> Callable[[str], str]:
    """Remove terminal color codes from CLI output."""
    return lambda text: _ANSI_ESCAPE.sub("", text)


@pytest.fixture
def import_result() -> dict:
    """Successful ImportResult payload returned by mocked REST."""
    return dict(_IMPORT_RESULT)


@pytest.fixture
def job_id() -> str:
    """Async import job id used in 202/poll scenarios."""
    return _JOB_ID


@pytest.fixture
def fixtures_dir() -> Path:
    """Directory of synthetic OpenAPI/Arazzo documents (no credentials or PII)."""
    return Path(__file__).resolve().parents[1] / "fixtures"
