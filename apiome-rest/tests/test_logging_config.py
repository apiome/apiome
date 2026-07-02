"""Tests for structured JSON logging (RC1-3.2, #3617)."""

import json
import logging

import pytest

from app.logging_config import (
    bind_contextvars,
    clear_contextvars,
    configure_logging,
    get_logger,
    reset_logging_state_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_logging():
    """Each test gets a clean logging configuration and restores defaults afterwards."""
    reset_logging_state_for_tests()
    yield
    reset_logging_state_for_tests()


def _capture_json_lines(capsys) -> list[dict]:
    """Read structured log lines written to stderr and parse them as JSON."""
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip().startswith("{")]
    return [json.loads(line) for line in lines]


def test_emits_json_with_observability_keys(capsys):
    configure_logging(log_level=logging.INFO, json_output=True, force=True)
    get_logger("test.logger").info("hello_event", foo="bar")

    records = _capture_json_lines(capsys)
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "hello_event"
    assert record["foo"] == "bar"
    assert record["level"] == "info"
    assert record["logger"] == "test.logger"
    assert "timestamp" in record
    # request_id is always present even outside a request (None default).
    assert record["request_id"] is None


def test_bound_request_id_is_included(capsys):
    configure_logging(log_level=logging.INFO, json_output=True, force=True)
    bind_contextvars(request_id="abc123", method="GET", path="/v1/thing")
    try:
        get_logger("test.req").info("served")
    finally:
        clear_contextvars()

    record = _capture_json_lines(capsys)[0]
    assert record["request_id"] == "abc123"
    assert record["method"] == "GET"
    assert record["path"] == "/v1/thing"


def test_level_filtering(capsys):
    configure_logging(log_level=logging.WARNING, json_output=True, force=True)
    log = get_logger("test.level")
    log.info("suppressed")
    log.warning("kept")

    records = _capture_json_lines(capsys)
    events = [r["event"] for r in records]
    assert "suppressed" not in events
    assert "kept" in events


def test_console_output_is_not_json(capsys):
    configure_logging(log_level=logging.INFO, json_output=False, force=True)
    get_logger("test.console").info("console_event")
    captured = capsys.readouterr()
    # Console renderer is human-friendly, not a JSON object per line.
    assert "console_event" in captured.err
    assert not captured.err.strip().startswith("{")


def test_configure_is_idempotent_without_force():
    reset_logging_state_for_tests()
    configure_logging(log_level=logging.INFO, json_output=True)
    handler_count = len(logging.getLogger().handlers)
    # A second call without force must not stack another handler (would double every line).
    configure_logging(log_level=logging.INFO, json_output=True)
    assert len(logging.getLogger().handlers) == handler_count
