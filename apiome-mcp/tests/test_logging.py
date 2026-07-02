from __future__ import annotations

import json
import logging

import pytest
import structlog

from apiome_mcp.logging_config import configure_logging, reset_logging_state_for_tests
from apiome_mcp.settings import Settings


def _minimal_settings(**overrides: object) -> Settings:
    data = {
        "database_url": "postgresql://localhost/db",
        "internal_secret": "x" * 16,
        "log_level": "INFO",
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_json_log_line_contains_required_fields(capsys: pytest.CaptureFixture[str]) -> None:
    reset_logging_state_for_tests()
    configure_logging(_minimal_settings(), force=True)
    log = structlog.get_logger("test.logger")
    log.info("hello_world", extra_field=42)
    err = capsys.readouterr().err.strip()
    payload = json.loads(err)
    assert payload["event"] == "hello_world"
    assert payload["level"] == "info"
    assert "timestamp" in payload
    assert "request_id" in payload
    assert "tool_name" in payload
    assert payload["extra_field"] == 42


def test_bound_contextvars_override_request_and_tool(capsys: pytest.CaptureFixture[str]) -> None:
    reset_logging_state_for_tests()
    configure_logging(_minimal_settings(), force=True)
    from structlog.contextvars import bound_contextvars

    log = structlog.get_logger("ctx.test")
    with bound_contextvars(request_id="rpc-99", tool_name="spec.list"):
        log.warning("inside_tool")
    err = capsys.readouterr().err.strip()
    payload = json.loads(err)
    assert payload["request_id"] == "rpc-99"
    assert payload["tool_name"] == "spec.list"
    assert payload["event"] == "inside_tool"
    assert payload["level"] == "warning"


def test_stdlib_logging_foreign_chain_is_json(capsys: pytest.CaptureFixture[str]) -> None:
    reset_logging_state_for_tests()
    configure_logging(_minimal_settings(log_level="DEBUG"), force=True)
    logging.getLogger("foreign.lib").info("stdlib_message")
    err = capsys.readouterr().err.strip()
    payload = json.loads(err)
    assert payload["level"] == "info"
    assert "timestamp" in payload
    assert "request_id" in payload
    assert "tool_name" in payload
    assert "stdlib_message" in payload["event"]


def test_log_level_respects_settings(capsys: pytest.CaptureFixture[str]) -> None:
    reset_logging_state_for_tests()
    configure_logging(_minimal_settings(log_level="WARNING"), force=True)
    log = structlog.get_logger("lvl.test")
    log.info("should_not_appear")
    assert capsys.readouterr().err.strip() == ""
    log.error("should_appear")
    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["event"] == "should_appear"
    assert payload["level"] == "error"


def test_configure_logging_is_idempotent_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    reset_logging_state_for_tests()
    s = _minimal_settings(log_level="WARNING")
    configure_logging(s, force=True)
    configure_logging(_minimal_settings(log_level="DEBUG"))
    log = structlog.get_logger("idempotent")
    log.info("still_filtered")
    assert capsys.readouterr().err.strip() == ""
