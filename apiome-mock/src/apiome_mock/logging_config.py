"""Structured logging for the mock server."""

from __future__ import annotations

import logging

import structlog

from apiome_mock.settings import Settings

_configured = False


def reset_logging_state_for_tests() -> None:
    global _configured
    _configured = False
    structlog.reset_defaults()


def configure_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True
