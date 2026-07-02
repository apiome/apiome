"""Verify CI provides a reachable Postgres (GitHub Actions service container)."""

from __future__ import annotations

import os

import psycopg
import pytest


def test_ci_postgres_service_accepts_connections() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        pytest.skip("Requires GitHub Actions Postgres service")
    url = os.environ.get("APIOME_MCP_DATABASE_URL")
    assert url, "APIOME_MCP_DATABASE_URL must be set when running in CI"
    with psycopg.connect(url) as conn:
        conn.execute("SELECT 1")
