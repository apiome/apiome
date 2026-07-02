"""Structured JSON logging for apiome-rest (RC1-3.2, #3617).

Mirrors the apiome-mcp logging setup (``apiome_mcp.logging_config``) so the spine emits a
single, consistent log shape across services: one JSON object per line on stderr carrying a
``timestamp``, ``level``, ``event``, ``logger`` and — crucially for diagnosability — the
``request_id`` bound for the in-flight HTTP request. The observability middleware
(``app.observability``) binds ``request_id``/``method``/``path``/``status_code`` into structlog's
contextvars for the duration of each request, so every log line a handler emits while serving that
request is automatically correlated to it. That is what makes "a failing request is diagnosable from
logs alone" true: grep the ``request_id`` and you get the full story.

Library loggers (uvicorn, fastapi, psycopg2, …) that log via the stdlib are routed through the same
formatter via ``ProcessorFormatter`` so their records come out as JSON too — no second, unstructured
log format leaking onto the same stream.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Final, MutableMapping

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.typing import Processor

# Guard so repeated imports / app reloads (uvicorn --reload, the test suite re-importing the app)
# do not stack duplicate handlers on the root logger and double every log line.
_CONFIGURED: bool = False


def reset_logging_state_for_tests() -> None:
    """Undo :func:`configure_logging` so a test can assert a clean configuration (pytest only)."""
    global _CONFIGURED
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.WARNING)
    clear_contextvars()
    _CONFIGURED = False


def _ensure_observability_keys(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Guarantee every line carries a ``request_id`` key, even outside a request (value ``None``).

    A stable key set keeps downstream log processors (jq filters, log-store schemas) simple: they
    can always select on ``request_id`` without worrying about whether the field is present.
    """
    event_dict.setdefault("request_id", None)
    return event_dict


def _timestamper() -> Processor:
    return structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")


def _shared_processors() -> list[Processor]:
    """Processors applied to both structlog-native and stdlib ("foreign") log records."""
    return [
        structlog.contextvars.merge_contextvars,
        _ensure_observability_keys,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _timestamper(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def _structlog_processor_chain() -> list[Processor]:
    chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _ensure_observability_keys,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        _timestamper(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # Hand off to the stdlib ProcessorFormatter, which renders the final line (JSON or console)
        # so structlog-native and foreign records share one renderer.
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]
    return chain


def configure_logging(*, log_level: int, json_output: bool = True, force: bool = False) -> None:
    """Configure structured logging for the REST service.

    Args:
        log_level: stdlib logging level integer (e.g. ``logging.INFO``).
        json_output: emit one JSON object per line (production). When False, a colorized
            console renderer is used instead — friendlier for local development.
        force: reconfigure even if already configured (used by tests).
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    clear_contextvars()

    structlog.configure(
        processors=_structlog_processor_chain(),
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    final_renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=final_renderer,
        foreign_pre_chain=_shared_processors(),
    )

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(log_level)

    # Let uvicorn's access/error loggers propagate to root so they share the JSON formatter rather
    # than emitting their own plaintext lines on the same stream.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lib_logger = logging.getLogger(noisy)
        lib_logger.handlers.clear()
        lib_logger.propagate = True

    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger bound to ``name`` (defaults to the caller's module-style logger)."""
    return structlog.get_logger(name) if name else structlog.get_logger()


# Re-exported for callers that bind/clear request context (the observability middleware).
__all__: Final = [
    "configure_logging",
    "get_logger",
    "reset_logging_state_for_tests",
    "bind_contextvars",
    "clear_contextvars",
]
