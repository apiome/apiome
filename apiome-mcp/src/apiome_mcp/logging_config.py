"""Structured JSON logging via structlog (stdlib bridge for library loggers)."""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Any, Final, MutableMapping

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.typing import Processor

from apiome_mcp.settings import Settings

_CONFIGURED: bool = False


def reset_logging_state_for_tests() -> None:
    """Undo `configure_logging` (pytest only)."""
    global _CONFIGURED
    structlog.reset_defaults()
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    root.setLevel(logging.WARNING)
    clear_contextvars()
    _CONFIGURED = False


def _ensure_observability_keys(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict.setdefault("request_id", None)
    event_dict.setdefault("tool_name", None)
    return event_dict


def _timestamper() -> Processor:
    return structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")


def _structlog_processor_chain(*, wrap_for_formatter: bool) -> list[Processor]:
    chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _ensure_observability_keys,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        _timestamper(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if wrap_for_formatter:
        chain.append(structlog.stdlib.ProcessorFormatter.wrap_for_formatter)
    return chain


def _foreign_pre_chain() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        _ensure_observability_keys,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _timestamper(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def configure_logging(settings: Settings, *, force: bool = False) -> None:
    """Emit JSON lines to stderr with timestamp, level, event, request_id, tool_name."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level: Final[int] = getattr(logging, settings.log_level)

    clear_contextvars()
    bind_contextvars(request_id=f"process-{uuid.uuid4()}", tool_name=None)

    structlog.configure(
        processors=_structlog_processor_chain(wrap_for_formatter=True),
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=_foreign_pre_chain(),
    )

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True
