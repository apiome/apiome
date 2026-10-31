"""Overlays on export — GVM-4.2 (#5877).

Overlays (:mod:`app.openapi_overlay`) are accepted on the way in, but the common use — "publish the
same API with partner-specific servers, descriptions or ``x-`` extensions without forking the
source" — is an export concern. This module applies an ordered chain of inline Overlay documents to
an export source **before** anything downstream runs:

1. the source's OpenAPI document (the parsed document the revision's canonical model was built
   from, ``CanonicalApi.raw``) is the base;
2. :func:`app.openapi_overlay.apply_overlays` applies the overlays in the order given;
3. the resolved document is re-normalized through the **same import adapter** that built the
   source, so the post-overlay canonical model replaces the source's.

Everything after that — the fidelity envelope and its snapshot hash, the transcoding guard, the
emitter, the emitted-artifact validation and the delivery gate (whose lint grade is the IXH-2.3
export quality policy's input, recorded in ``quality_rank_observations`` with scope ``export``) —
sees the post-overlay model, because that is what leaves the building.

What the overlays did is reported on :class:`ExportOverlayReport`: one ledger row per changed leaf
(the same per-pointer provenance the import ledger renders, IXH-7.7) plus a declared-truncation row
at the :data:`~app.openapi_overlay.MAX_PROVENANCE_RECORDS` cap, and one finding per action that
could not be applied — an action whose target matches nothing is an ``overlay.unmatched-target``
finding and leaves the document untouched, never a silent no-op.

Overlays modify OpenAPI documents, so a source that was not built from one (a GraphQL schema, a
Protobuf file, …) is refused with :data:`OVERLAY_SOURCE_UNSUPPORTED` rather than rendered through a
lossy OpenAPI round trip.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog_conversion import ConversionError, resolve_conversion_adapter
from .export_source import ExportSource
from .import_source import ImportSourceError
from .openapi_overlay import (
    OVERLAY_EXTRA_KEY,
    OverlayApplication,
    OverlayedOpenApiDocument,
    apply_overlays,
    is_overlay_document,
    overlay_lint_findings,
)

__all__ = [
    "ExportOverlay",
    "ExportOverlayError",
    "ExportOverlayFinding",
    "ExportOverlayLedgerRow",
    "ExportOverlayReport",
    "MAX_EXPORT_OVERLAYS",
    "MAX_EXPORT_OVERLAY_BYTES",
    "OVERLAY_INVALID",
    "OVERLAY_SOURCE_UNSUPPORTED",
    "apply_export_overlays",
    "overlay_events",
    "overlay_source_document",
]

#: Most overlays one export may apply. A chain is a curation tool, not a build system; ten is far
#: beyond any real layering (base → environment → partner) and bounds the work per request.
MAX_EXPORT_OVERLAYS = 10

#: Largest serialized overlay document accepted inline (1 MiB), so a request cannot smuggle an
#: unbounded document into the export path.
MAX_EXPORT_OVERLAY_BYTES = 1024 * 1024

#: Error code: an overlay is not an Overlay document, declares a revision Apiome does not read, or
#: has no usable ``actions`` (HTTP 422).
OVERLAY_INVALID = "OVERLAY_INVALID"

#: Error code: the export source was not built from an OpenAPI document, so there is nothing for an
#: overlay to modify (HTTP 422).
OVERLAY_SOURCE_UNSUPPORTED = "OVERLAY_SOURCE_UNSUPPORTED"

#: Human verbs for provenance kinds — the wording the import ledger uses (IXH-7.7).
_KIND_VERBS = {
    "set": "was added",
    "replaced": "was replaced",
    "appended": "was appended",
    "removed": "was removed",
}


class ExportOverlay(BaseModel):
    """One inline overlay of an export request: a label and the parsed Overlay document."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=200,
        description="The overlay's label — usually its file name. Ledger rows and findings name it.",
    )
    document: Dict[str, Any] = Field(
        description="The parsed Overlay 1.0 / 1.1 / 1.2 document (`overlay`, `info`, `actions`), at "
        "most 1 MiB serialized.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """Trim the label and refuse a blank one."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("An overlay needs a non-blank 'name'.")
        return stripped

    @field_validator("document")
    @classmethod
    def _bounded_overlay(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Refuse a document that is not an Overlay or exceeds :data:`MAX_EXPORT_OVERLAY_BYTES`."""
        if not is_overlay_document(value):
            raise ValueError("'document' is not an Overlay document (it has no `overlay: 1.x` marker).")
        size = len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
        if size > MAX_EXPORT_OVERLAY_BYTES:
            raise ValueError(
                f"An overlay document may be at most {MAX_EXPORT_OVERLAY_BYTES} bytes serialized; "
                f"this one is {size}."
            )
        return value


class ExportOverlayLedgerRow(BaseModel):
    """One fidelity-ledger row for an overlay: a changed leaf, or the declared truncation."""

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(
        description="JSON Pointer (RFC 6901) of the changed value in the source document; "
        "`(truncated)` on the declared-truncation row.",
    )
    kind: str = Field(
        description="`set`, `replaced`, `appended` or `removed`; `truncated` on the truncation row.",
    )
    overlay: Optional[str] = Field(
        default=None, description="The overlay that made the change; null on the truncation row."
    )
    action_index: Optional[int] = Field(
        default=None, description="0-based index of the action in that overlay's `actions`."
    )
    target: Optional[str] = Field(default=None, description="The action's JSONPath `target`, verbatim.")
    detail: str = Field(description="One readable sentence: what happened to the value and why.")


class ExportOverlayFinding(BaseModel):
    """One overlay action that could not be applied, as an ``overlay`` pack finding."""

    model_config = ConfigDict(extra="forbid")

    rule: str = Field(description="The `overlay` pack rule id (e.g. `overlay.unmatched-target`).")
    severity: str = Field(description="The rule's default severity (`warning` / `error`).")
    overlay: str = Field(description="The overlay the action came from.")
    action_index: int = Field(
        description="0-based index of the action; -1 for a finding about the overlay document itself."
    )
    target: str = Field(default="", description="The action's `target` expression (empty when it had none).")
    message: str = Field(description="What was wrong.")


class ExportOverlayReport(BaseModel):
    """What the overlays of one export did: applied chain, per-leaf ledger rows, findings."""

    model_config = ConfigDict(extra="forbid")

    applied: List[str] = Field(description="Overlay names, in the order they were applied.")
    ledger: List[ExportOverlayLedgerRow] = Field(
        default_factory=list,
        description="One row per changed leaf (capped at 500), plus a declared-truncation row when "
        "the cap was reached.",
    )
    findings: List[ExportOverlayFinding] = Field(
        default_factory=list,
        description="Actions that could not be applied — never silently skipped.",
    )
    changes: int = Field(description="Total values the overlays changed, including any beyond the cap.")
    truncated: bool = Field(description="True when `ledger` itemizes only the first 500 changes.")


class ExportOverlayError(Exception):
    """An export's overlays could not be applied; carries an HTTP status and a stable ``code``."""

    def __init__(self, message: str, *, code: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def http_detail(self) -> Dict[str, Any]:
        """The structured HTTP error ``detail`` (``{code, message}``)."""
        return {"code": self.code, "message": str(self)}


def overlay_source_document(source: ExportSource) -> Optional[Dict[str, Any]]:
    """The OpenAPI document an overlay applies to for ``source``, or ``None`` when it has none.

    Args:
        source: The loaded export source.

    Returns:
        The parsed OpenAPI / Swagger document the source's canonical model was normalized from
        (``CanonicalApi.raw``), or ``None`` when the source was not built from one.
    """
    raw = source.api.raw
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("openapi"), str) or isinstance(raw.get("swagger"), str):
        return raw
    return None


def _ledger_rows(application: OverlayApplication) -> List[ExportOverlayLedgerRow]:
    """Render the application's provenance as ledger rows, plus the declared-truncation row."""
    rows: List[ExportOverlayLedgerRow] = []
    for record in application.provenance:
        verb = _KIND_VERBS.get(record.kind, f"was {record.kind or 'changed'}")
        rows.append(
            ExportOverlayLedgerRow(
                pointer=record.pointer,
                kind=record.kind,
                overlay=record.overlay,
                action_index=record.action_index,
                target=record.target,
                detail=(
                    f"The value at {record.pointer or 'the document root'} {verb} by overlay "
                    f"{record.overlay!r} (action #{record.action_index}, target {record.target!r})."
                ),
            )
        )
    if application.provenance_truncated:
        rows.append(
            ExportOverlayLedgerRow(
                pointer="(truncated)",
                kind="truncated",
                detail=(
                    f"The overlays changed {application.provenance_total} value(s) in total; only "
                    f"the first {len(application.provenance)} carry itemized rows here."
                ),
            )
        )
    return rows


def _findings(application: OverlayApplication) -> List[ExportOverlayFinding]:
    """Adapt the application's findings into ``overlay`` pack findings, keeping their origin."""
    raw_findings = [finding.as_dict() for finding in application.findings]
    lint = overlay_lint_findings({"findings": raw_findings})
    return [
        ExportOverlayFinding(
            rule=finding.rule,
            severity=finding.severity,
            overlay=str(raw["overlay"]),
            action_index=int(raw["action_index"]),
            target=str(raw.get("target") or ""),
            message=finding.message,
        )
        for raw, finding in zip(raw_findings, lint)
    ]


def _resolved_document(raw: Dict[str, Any], application: OverlayApplication) -> Dict[str, Any]:
    """The resolved document, carrying the base's adapter attributes (import overlay report, …).

    A base built by the adapter can be a ``dict`` subclass with attributes the adapter publishes on
    the model's extras (an import-time overlay report, Swagger 1.2 provenance). The resolved copy
    keeps them, so the post-overlay model states the same provenance the source did.
    """
    attributes = getattr(raw, "__dict__", None)
    if not attributes:
        return application.document
    resolved = OverlayedOpenApiDocument(application.document)
    for name, value in attributes.items():
        setattr(resolved, name, value)
    return resolved


def apply_export_overlays(
    source: ExportSource, overlays: Optional[Sequence[ExportOverlay]]
) -> Tuple[ExportSource, Optional[ExportOverlayReport]]:
    """Apply ``overlays`` to an export source, in order, and rebuild its canonical model.

    Args:
        source: The loaded export source.
        overlays: The request's overlays; ``None`` or empty leaves the source as it is.

    Returns:
        ``(source, report)`` — the post-overlay source (a copy with the rebuilt canonical model;
        coordinates, captured text and format unchanged) and the overlay report. With no overlays,
        the source unchanged and ``None``.

    Raises:
        ExportOverlayError: :data:`OVERLAY_SOURCE_UNSUPPORTED` when the source was not built from an
            OpenAPI document; :data:`OVERLAY_INVALID` when an overlay declares a revision Apiome does
            not read or has no ``actions``, or the resolved document no longer normalizes.
    """
    if not overlays:
        return source, None
    base = overlay_source_document(source)
    if base is None:
        fmt = source.source_format or source.api.format or "this format"
        raise ExportOverlayError(
            f"Overlays modify OpenAPI documents, and this version's source is {fmt}. Export it "
            "without overlays, or export a version imported from OpenAPI.",
            code=OVERLAY_SOURCE_UNSUPPORTED,
        )
    try:
        application = apply_overlays(base, [(overlay.name, overlay.document) for overlay in overlays])
    except ImportSourceError as exc:
        raise ExportOverlayError(str(exc), code=OVERLAY_INVALID) from exc

    try:
        adapter = resolve_conversion_adapter(source.source_format or source.api.format, source.source_text or "")
        api = adapter.normalize(_resolved_document(base, application))
    except (ConversionError, ImportSourceError) as exc:
        raise ExportOverlayError(
            f"The overlaid document is no longer a valid source for export: {exc}",
            code=OVERLAY_INVALID,
        ) from exc
    # The import-time overlay report (if the source itself was an overlay import) is the source's
    # provenance; the export's own overlays are reported on the result, never folded into extras.
    imported = source.api.extras.get(OVERLAY_EXTRA_KEY) if isinstance(source.api.extras, dict) else None
    if isinstance(api.extras, dict):
        if isinstance(imported, Mapping):
            api.extras[OVERLAY_EXTRA_KEY] = imported
        else:
            api.extras.pop(OVERLAY_EXTRA_KEY, None)

    report = ExportOverlayReport(
        applied=list(application.applied),
        ledger=_ledger_rows(application),
        findings=_findings(application),
        changes=application.provenance_total,
        truncated=application.provenance_truncated,
    )
    return source.model_copy(update={"api": api}), report


def overlay_events(report: Optional[ExportOverlayReport]) -> List[Tuple[str, str, str, Optional[Dict[str, Any]]]]:
    """The job events an overlay report produces: one summary, then one warning per finding.

    Args:
        report: The overlay report, or ``None`` when the export had no overlays.

    Returns:
        ``(level, code, message, context)`` tuples in publication order; empty without a report.
    """
    if report is None:
        return []
    events: List[Tuple[str, str, str, Optional[Dict[str, Any]]]] = [
        (
            "info",
            "OVERLAYS_APPLIED",
            f"Applied {len(report.applied)} overlay(s): {report.changes} value(s) changed",
            {"applied": list(report.applied), "changes": report.changes, "truncated": report.truncated},
        )
    ]
    for finding in report.findings:
        events.append(
            (
                "warn",
                "OVERLAY_FINDING",
                f"{finding.rule} in overlay {finding.overlay!r}: {finding.message}",
                {"rule": finding.rule, "overlay": finding.overlay,
                 "action_index": finding.action_index, "target": finding.target},
            )
        )
    return events
