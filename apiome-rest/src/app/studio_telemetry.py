"""Privacy-safe Export studio usage telemetry — MFX-46.5 (#4383).

Counters and structured log lines for how Export studio (and the Export dialog) is used. Like the
projection telemetry (EFP-3.2, :mod:`app.projection_telemetry`) every field is a **controlled
vocabulary** — an event kind, which surface, a registered export format, a verdict, a test-drive tool
or a visualization — never an artifact name, a source, a file, an option value or free text.

Kinds tracked:

* ``target_chosen`` — a target was chosen (``target``: the canonical export format; ``mode``:
  ``single`` or ``multi``)
* ``verify_verdict`` — a verification finished (``verdict``: ``clean`` / ``lossy`` / ``severe`` /
  ``invalid``, or ``error`` when it could not run)
* ``lossy_prompt_shown`` / ``lossy_acknowledged`` — the lossy acknowledgement was asked for / given
  (``verdict``: ``lossy`` or ``severe``); together they give the acknowledge-lossy rate
  (:meth:`StudioTelemetry.acknowledge_lossy_rate`)
* ``test_drive_used`` — a test-drive tool was opened or run (``tool``; ``action``: ``open`` / ``run``)
* ``viz_used`` — a visualization was shown (``view``)
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .export_service import ExportError, resolve_emit_format
from .logging_config import get_logger

_log = get_logger("app.studio_telemetry")

StudioMetricKind = Literal[
    "target_chosen", "verify_verdict", "lossy_prompt_shown", "lossy_acknowledged", "test_drive_used", "viz_used",
]
StudioSurface = Literal["studio", "dialog"]
StudioVerdict = Literal["clean", "lossy", "severe", "invalid", "error"]
StudioTestTool = Literal["swagger-ui", "redoc", "graphiql", "asyncapi-render", "mock-server", "toolchain"]
StudioViz = Literal[
    "erd", "proto-imports", "service-map", "channel-topology", "fidelity-overlay", "fidelity-treemap",
]

#: The verdicts that ask for an acknowledgement.
LOSSY_VERDICTS = frozenset({"lossy", "severe"})

#: Which field each kind requires (``None``: none beyond the kind).
_REQUIRED: Dict[str, Optional[str]] = {
    "target_chosen": "target",
    "verify_verdict": "verdict",
    "lossy_prompt_shown": "verdict",
    "lossy_acknowledged": "verdict",
    "test_drive_used": "tool",
    "viz_used": "view",
}


class StudioMetricRequest(BaseModel):
    """One Export studio usage event: ``POST /v1/export/{tenant}/studio-metrics``.

    Unknown fields are refused, every value is a controlled vocabulary, and each kind names the one
    field it needs (``target`` / ``verdict`` / ``tool`` / ``view``).
    """

    model_config = ConfigDict(extra="forbid")

    kind: StudioMetricKind = Field(description="What happened (whitelist).")
    surface: StudioSurface = Field(default="studio", description="Export studio or the Export dialog.")
    target: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9._+-]*$",
        description="`target_chosen`: the chosen export target (a registered format or key).")
    mode: Optional[Literal["single", "multi"]] = Field(
        default=None, description="`target_chosen`: one target, or one of several.")
    verdict: Optional[StudioVerdict] = Field(
        default=None, description="`verify_verdict` / `lossy_*`: the verification's verdict.")
    tool: Optional[StudioTestTool] = Field(default=None, description="`test_drive_used`: the test-drive tool.")
    action: Optional[Literal["open", "run"]] = Field(
        default=None, description="`test_drive_used`: the tool was opened, or run.")
    view: Optional[StudioViz] = Field(default=None, description="`viz_used`: the visualization shown.")


class StudioMetricResponse(BaseModel):
    """Acknowledgement that a usage event was recorded."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool = True
    kind: str


def normalize_event(request: StudioMetricRequest) -> Dict[str, Any]:
    """The fields one event records, checked against its kind.

    Args:
        request: The validated request.

    Returns:
        ``{kind, surface, …}`` with only the fields the kind uses; ``target`` is the canonical export
        format (``openapi`` → ``openapi-3.1``).

    Raises:
        ValueError: When the kind's field is missing, the target is not a registered export target, or
            a lossy event names a verdict that asks for no acknowledgement.
    """
    required = _REQUIRED[request.kind]
    if required and getattr(request, required) is None:
        raise ValueError(f"{request.kind} needs {required!r}")
    event: Dict[str, Any] = {"kind": request.kind, "surface": request.surface}
    if request.kind == "target_chosen":
        try:
            event["target"] = resolve_emit_format(str(request.target))
        except ExportError as exc:
            raise ValueError(f"unknown export target {request.target!r}") from exc
        event["mode"] = request.mode or "single"
    elif request.kind == "verify_verdict":
        event["verdict"] = request.verdict
    elif request.kind in ("lossy_prompt_shown", "lossy_acknowledged"):
        if request.verdict not in LOSSY_VERDICTS:
            raise ValueError(f"{request.kind} is only for a lossy or severe verdict")
        event["verdict"] = request.verdict
    elif request.kind == "test_drive_used":
        event["tool"] = request.tool
        event["action"] = request.action or "open"
    elif request.kind == "viz_used":
        event["view"] = request.view
    return event


class StudioTelemetry:
    """Thread-safe in-process counters + structured log emitter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        """Clear all counters (unit tests)."""
        with self._lock:
            self._counts.clear()

    def snapshot(self) -> Dict[str, int]:
        """Every counter key → count: ``kind``, ``kind:surface`` and ``kind:<value>`` (e.g.
        ``verify_verdict:lossy``, ``test_drive_used:graphiql:run``)."""
        with self._lock:
            return dict(self._counts)

    def record(self, event: Dict[str, Any]) -> None:
        """Count one event from :func:`normalize_event` and log it as ``export.studio``.

        Args:
            event: The normalized event.
        """
        kind = event["kind"]
        detail = [str(event[key]) for key in ("target", "verdict", "tool", "view") if event.get(key)]
        if event.get("action"):
            detail.append(str(event["action"]))
        with self._lock:
            self._counts[kind] += 1
            self._counts[f"{kind}:{event['surface']}"] += 1
            if detail:
                self._counts[":".join([kind, *detail])] += 1
        _log.info("export.studio", **event)

    def acknowledge_lossy_rate(self) -> Optional[float]:
        """Share of lossy acknowledgement prompts that were acknowledged (0–1), or ``None`` before any."""
        with self._lock:
            shown = self._counts.get("lossy_prompt_shown", 0)
            acknowledged = self._counts.get("lossy_acknowledged", 0)
        return round(acknowledged / shown, 4) if shown else None


#: Process-wide telemetry registry for Export studio usage.
studio_telemetry = StudioTelemetry()
