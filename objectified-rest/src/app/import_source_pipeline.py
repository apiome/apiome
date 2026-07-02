"""In-process import-source job pipeline — MFI-1.2 (#3734).

The spec-import job engine (:mod:`app.spec_import_engine`) was OpenAPI-shaped: every
job ran the ``objectified-ui`` ``tsx`` worker, which only knows how to import an
OpenAPI/Swagger document. MFI-1.1 (#3733) introduced the :class:`ImportSource` SPI so
a *format* is added by registering an adapter; this module is the generalized engine
step that **drives any such adapter through the existing job lifecycle** —
parse → normalize → version → lint — emitting the same
:class:`~app.models.SpecImportJobStatus` contract the worker already produces.

The four phases map onto the SPI:

* **parse** — :meth:`ImportSource.parse` turns the raw document text into the
  format's native AST;
* **normalize** — :meth:`ImportSource.normalize` maps that AST onto the canonical
  model (:class:`~app.canonical_model.CanonicalApi`);
* **version** — :meth:`ImportSource.fingerprint` computes the stable content
  fingerprint that *identifies* this revision (the unit ``skip_duplicate_versions``
  and incremental imports key off);
* **lint** — :meth:`ImportSource.lint` scores the normalized model.

The OpenAPI/Swagger path keeps running on the ``tsx`` worker (it persists a full
catalog project/version and has its own benchmark instrumentation). This path handles
every *other* format and now **persists** its result via the canonical→catalog hook
(:func:`persist_adapter_import`): a non-dry-run import writes its routed artifact and
keeps the **original source verbatim** in the revision's ``format_metadata`` so it can
be converted to OpenAPI later (MFI-EPIC-22) — nothing is converted at import time. A
``dry_run`` still previews without writing. The completed job's ``summary`` carries the
fingerprint, paradigm/format, entity counts, lint score, the Project-vs-Catalog
**routing decision** (MFI-23.7, :mod:`app.import_routing`), and a ``persisted`` flag;
its ``result`` carries the produced project/version ids.

Between normalize and version the pipeline records a routing decision — OpenAPI/Swagger
imports route to a publishable **Project**, everything else to a non-publishable
**catalog item** — onto the summary (and a ``ROUTING_DECIDED`` event) so the UI can
explain where an import landed and why; the persistence hook then creates that artifact
with ``db.create_project(publishable=routing.publishable)``.

The driver is intentionally transport-agnostic: it takes a resolved adapter and the
worker payload dict, calls an optional ``on_snapshot`` coroutine after every phase so
the engine can publish poll-visible progress, and checks an optional ``is_canceled``
predicate between phases. This mirrors the MCP discovery-job driver: a small async
state machine over a registry-resolved adapter.

The adapter's parse/normalize/fingerprint/lint calls run inline (not on a worker
thread): these adapters handle bounded new-format documents, and the one heavy path —
OpenAPI/Swagger — stays on the subprocess worker. Keeping the work inline means a job
runs to a terminal state within a single event-loop turn, the same way the worker's
final-status callback resolves, which the job engine and its tests rely on. A future
format with genuinely CPU-bound parsing can move its own step to a thread/subprocess.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .canonical_model import CanonicalApi
from .import_routing import ImportRoutingDecision, decide_import_routing
from .import_source import ImportSource, ImportSourceError, LintReport
from .models import (
    SpecImportEvent,
    SpecImportJobResult,
    SpecImportJobStatus,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ADAPTER_PHASE_EVENT_CODES",
    "capture_canonical_quality_score",
    "run_adapter_import_job",
]

# Event codes the in-process adapter pipeline emits for each phase. Surfaced at INFO
# by the engine's event logger (mirrors the worker's PHASE_TIMING/BENCHMARK codes) so
# an adapter import's progress is readable in the REST logs as it runs.
ADAPTER_PHASE_EVENT_CODES = frozenset(
    {
        "ADAPTER_INIT",
        "PARSE_OK",
        "NORMALIZE_OK",
        "ROUTING_DECIDED",
        "VERSION_FINGERPRINT",
        "INCREMENTAL_MODE",
        "DRY_RUN",
        "LINT_COMPLETED",
        "QUALITY_CAPTURED",
        "IMPORT_COMPLETED",
    }
)

# Percent milestones for each phase, so a poller sees monotonic progress even though
# an in-process adapter run is fast. Values are coarse on purpose — the contract only
# promises a 0–100 percent, not a per-phase breakdown.
_PCT_INIT = 5
_PCT_PARSED = 25
_PCT_NORMALIZED = 55
_PCT_VERSIONED = 75
_PCT_LINTED = 90
_PCT_DONE = 100


class _AdapterRunState:
    """Accumulates events/percent for one adapter import and builds status snapshots.

    A tiny mutable helper so each phase can append an event and emit a
    :class:`SpecImportJobStatus` carrying the *full* accumulated event log (the same
    shape the worker's streamed snapshots use), without threading a growing list
    through every call.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._events: List[SpecImportEvent] = []
        self._seq = 0

    def event(
        self,
        code: str,
        message: str,
        *,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append one structured event to the run's log."""
        self._seq += 1
        self._events.append(
            SpecImportEvent(
                id=f"adapter-{self._seq}",
                ts=int(time.time() * 1000),
                level=level,  # type: ignore[arg-type]
                code=code,
                message=message,
                context=context,
            )
        )

    def snapshot(
        self,
        *,
        state: str,
        percent: int,
        summary: Optional[Dict[str, Any]] = None,
        result: Optional[SpecImportJobResult] = None,
    ) -> SpecImportJobStatus:
        """Build a status snapshot carrying the accumulated event log."""
        return SpecImportJobStatus(
            job_id=self.job_id,
            state=state,  # type: ignore[arg-type]
            percent=percent,
            events=list(self._events),
            summary=summary,
            result=result,
        )


def _decode_document(payload: Dict[str, Any]) -> str:
    """Decode the base64 worker payload into source text.

    Raises:
        ImportSourceError: If ``document_base64`` is missing or not valid base64.
    """
    b64 = payload.get("document_base64")
    if not isinstance(b64, str) or not b64:
        raise ImportSourceError("Import payload is missing document_base64 content")
    try:
        raw_bytes = base64.standard_b64decode(b64)
    except (binascii.Error, ValueError) as exc:
        raise ImportSourceError(f"document_base64 is not valid base64: {exc}") from exc
    # Decode permissively: a per-format adapter's parse() is responsible for rejecting
    # genuinely malformed text; we should not fail the whole job on a stray byte.
    return raw_bytes.decode("utf-8", errors="replace")


def capture_canonical_quality_score(
    version_record_id: str, tenant_id: str, report: LintReport
) -> None:
    """Best-effort: persist an import's rolled-up lint score onto the revision (MFI-4.2).

    The canonical-model analogue of
    :func:`app.spec_import_engine._capture_version_quality_score` (specs) and
    :func:`app.mcp_discovery_engine._capture_mcp_version_score` (MCP). Given the already-computed
    :class:`~app.import_source.LintReport` for a freshly committed revision — the same roll-up
    surfaced in the import summary — this writes its weighted 0–100 ``score``, A–F ``grade``, and
    stable ``report_fingerprint`` onto the revision's ``quality_*`` columns (V124), the
    artifact-version row the canonical model is tied to (one ``api_artifacts`` row per
    ``versions`` row, MFI-2.2), so no new table/migration is needed. Persisting the report the
    adapter already produced (rather than re-linting) keeps the stored score identical to the
    surfaced one.

    Strictly **best-effort**: the revision is already committed, so any failure here just leaves
    the score for an on-demand re-lint (MFI-4.4) to fill and never affects the import outcome. An
    unscored report (no ``score``/``grade``) is skipped — there is nothing to persist. The DB
    import is lazy to keep that layer off the hot import path.

    Args:
        version_record_id: The just-committed ``versions`` row to score.
        tenant_id: Owning tenant; scopes the write so a caller cannot score another tenant's row.
        report: The rolled-up lint report for the revision (from the adapter's ``lint``).
    """
    if report.score is None or report.grade is None:
        return
    try:
        from .database import db

        db.set_version_quality_score(
            version_record_id,
            tenant_id,
            report.score,
            report.grade,
            report.report_fingerprint,
        )
    except Exception:  # noqa: BLE001 - capture is strictly best-effort
        logger.warning(
            "Failed to capture canonical quality score for revision %s",
            version_record_id,
            exc_info=True,
        )


def persist_adapter_import(
    payload: Dict[str, Any],
    model: CanonicalApi,
    raw_text: str,
    routing: ImportRoutingDecision,
) -> Optional[SpecImportJobResult]:
    """Persist a non-dry-run adapter import as its routed artifact (canonical→catalog hook, MFI-23.7).

    This is the persistence hook the pipeline docstring calls out as "pending": it creates the
    routed artifact — a **non-publishable catalog item** for every non-OpenAPI format
    (``routing.publishable is False``) — and stores the *original source verbatim* on the created
    revision's ``format_metadata`` (under ``sourceContent``) alongside its ``source_format`` and
    ``protocol``.

    Crucially, **nothing is converted here.** The raw bytes the user uploaded sit in the catalog
    untouched until they explicitly run the convert-to-OpenAPI flow (MFI-EPIC-22), which re-parses
    exactly these stored bytes via :mod:`app.catalog_conversion`. So a gRPC / Protobuf / Thrift
    import lands in the catalog in its native form and is converted only when the user is ready.

    Blocking DB work (the psycopg driver is synchronous) — call via ``asyncio.to_thread``.

    Args:
        payload: The worker payload (``tenant_id`` / ``user_id`` / ``metadata`` / ``filename``).
        model: The normalized canonical model (its ``format`` / ``paradigm`` label the revision).
        raw_text: The decoded original source, stored verbatim for later conversion.
        routing: The Project-vs-Catalog decision; ``routing.publishable`` sets the created row.

    Returns:
        The produced identifiers, or ``None`` when there is no tenant to write under.
    """
    from .database import db

    tenant_id = str(payload.get("tenant_id") or "")
    if not tenant_id:
        return None
    creator_id = str(payload.get("user_id") or "") or None
    metadata = payload.get("metadata") or {}
    project_meta = metadata.get("project") or {}
    version_meta = metadata.get("version") or {}
    options = metadata.get("options") or {}
    existing_project_id = metadata.get("existing_project_id")
    source_label = payload.get("filename")

    version_id = str(version_meta.get("version_id") or "1.0.0").strip() or "1.0.0"
    version_description = version_meta.get("description")

    if existing_project_id:
        existing = db.get_project_by_id(str(existing_project_id), tenant_id)
        project_id = str(existing_project_id)
        project_slug = (existing or {}).get("slug")
    else:
        name = str(project_meta.get("name") or source_label or "Imported source").strip()
        slug = str(project_meta.get("slug") or "").strip()
        description = project_meta.get("description")
        project = db.create_project(
            tenant_id,
            creator_id,
            name,
            slug,
            description,
            None,
            routing.publishable,
        )
        project_id = str(project["id"])
        project_slug = project.get("slug")

    version = db.create_version(project_id, creator_id, version_id, version_description)
    version_record_id = str(version["id"])

    # Store the original source verbatim so the convert flow can re-parse it later. The input kind
    # (file/url/paste) is recorded for the catalog's source-material badge when the client sends it
    # (MFI-26.2); for a URL intake the label is also recorded as the source URI so the detail panel
    # can link/redirect back to it.
    input_kind = options.get("input_kind") if isinstance(options, dict) else None
    format_metadata: Dict[str, Any] = {
        "sourceContent": raw_text,
        "sourceLabel": source_label,
        "inputKind": input_kind or "file",
    }
    if input_kind == "url" and source_label:
        format_metadata["sourceUri"] = source_label
    db.set_version_source_format(
        version_record_id,
        tenant_id,
        source_format=model.format,
        protocol=model.paradigm.value,
        format_metadata=format_metadata,
    )

    return SpecImportJobResult(
        project_id=project_id,
        project_slug=project_slug,
        version_id=version_id,
        version_record_id=version_record_id,
    )


def _build_summary(
    *,
    adapter: ImportSource,
    model: CanonicalApi,
    fingerprint: str,
    lint: LintReport,
    routing: ImportRoutingDecision,
    options: Dict[str, Any],
    persisted: bool = False,
) -> Dict[str, Any]:
    """Assemble the completed-job summary for an adapter import.

    Carries the version fingerprint, what was produced (paradigm/format + entity
    counts), the rolled-up lint outcome (score / grade / fingerprint / severity tally),
    the **Project-vs-Catalog routing decision** (MFI-23.7) so the UI can explain where
    the import landed and why, the dry-run/incremental flags the request asked for, and
    whether the import was **persisted** — a non-dry-run import now stores its routed
    artifact (a catalog item for non-OpenAPI formats), keeping the original source verbatim.
    """
    return {
        "source": adapter.key,
        "paradigm": model.paradigm.value,
        "format": model.format,
        "fingerprint": fingerprint,
        "counts": {
            "services": len(model.services),
            "operations": sum(len(s.operations) for s in model.services),
            "types": len(model.types),
            "channels": len(model.channels),
        },
        "lint": {
            "score": lint.score,
            "grade": lint.grade,
            "report_fingerprint": lint.report_fingerprint,
            "findings": len(lint.findings),
            "severity_counts": dict(lint.severity_counts),
        },
        "routing": routing.as_dict(),
        "dry_run": bool(options.get("dry_run")),
        "incremental_mode": bool(options.get("incremental_mode")),
        "persisted": persisted,
    }


async def run_adapter_import_job(
    adapter: ImportSource,
    payload: Dict[str, Any],
    *,
    on_snapshot: Optional[Callable[[SpecImportJobStatus], Awaitable[None]]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> SpecImportJobStatus:
    """Drive one import-source adapter through the job lifecycle, in-process.

    Runs parse → normalize → version(fingerprint) → lint and returns the terminal
    :class:`SpecImportJobStatus`. After each phase the optional ``on_snapshot``
    coroutine is awaited with the current snapshot (so the engine can publish
    poll-visible progress), and the optional ``is_canceled`` predicate is checked (so
    a delete request between phases stops the run).

    The adapter's parse/normalize/fingerprint/lint calls run inline (see the module
    docstring). A :class:`ImportSourceError` from parse or normalize is a clean,
    user-facing failure (bad document / unsupported format), so it is turned into a
    ``failed`` status rather than propagated.

    Args:
        adapter: The resolved :class:`ImportSource` for the request's source kind.
        payload: The worker payload dict (``document_base64`` + ``metadata`` etc.).
        on_snapshot: Optional coroutine called with each intermediate snapshot.
        is_canceled: Optional predicate; when it returns ``True`` between phases the
            run stops and a ``canceled`` status is returned.

    Returns:
        The terminal :class:`SpecImportJobStatus` (``completed``/``failed``/``canceled``).
    """
    job_id = str(payload.get("rest_job_id") or "")
    metadata = payload.get("metadata") or {}
    options = metadata.get("options") or {}
    source_label = payload.get("filename")
    state = _AdapterRunState(job_id)

    async def publish(status: SpecImportJobStatus) -> None:
        if on_snapshot is not None:
            await on_snapshot(status)

    def canceled() -> bool:
        return is_canceled is not None and is_canceled()

    # --- init -----------------------------------------------------------------
    state.event("ADAPTER_INIT", f"Importing via the {adapter.label!r} source ({adapter.key})")
    if options.get("incremental_mode"):
        state.event(
            "INCREMENTAL_MODE",
            "Incremental mode requested; the in-process adapter path holds no transaction.",
        )
    await publish(state.snapshot(state="running", percent=_PCT_INIT))
    if canceled():
        return state.snapshot(state="canceled", percent=_PCT_INIT)

    # --- parse ----------------------------------------------------------------
    try:
        raw_text = _decode_document(payload)
        native_ast = adapter.parse(raw_text, source_label=source_label)
    except ImportSourceError as exc:
        state.event("PARSE_ERROR", str(exc), level="error")
        return state.snapshot(state="failed", percent=_PCT_INIT)
    state.event("PARSE_OK", "Parsed source into the format's native representation.")
    await publish(state.snapshot(state="running", percent=_PCT_PARSED))
    if canceled():
        return state.snapshot(state="canceled", percent=_PCT_PARSED)

    # --- normalize ------------------------------------------------------------
    try:
        model = adapter.normalize(native_ast, include_raw=True)
    except ImportSourceError as exc:
        state.event("NORMALIZE_ERROR", str(exc), level="error")
        return state.snapshot(state="failed", percent=_PCT_PARSED)
    state.event(
        "NORMALIZE_OK",
        f"Normalized into the canonical model ({model.paradigm.value}/{model.format}).",
    )
    await publish(state.snapshot(state="running", percent=_PCT_NORMALIZED))
    if canceled():
        return state.snapshot(state="canceled", percent=_PCT_NORMALIZED)

    # --- route (Project vs Catalog) — MFI-23.7 --------------------------------
    # Decide whether this import becomes a publishable Project (OpenAPI/Swagger) or a
    # non-publishable catalog item (everything else). The decision + its reason are
    # recorded on the summary so the UI can explain the routing; the persistence hook
    # (a later format epic) reads ``routing.publishable`` to create the right artifact.
    routing = decide_import_routing(adapter, model)
    state.event(
        "ROUTING_DECIDED",
        f"Routing → {routing.target.value}: {routing.reason}",
        context=routing.as_dict(),
    )

    # --- version (fingerprint) ------------------------------------------------
    fingerprint = adapter.fingerprint(model)
    state.event(
        "VERSION_FINGERPRINT",
        f"Computed revision fingerprint {fingerprint}.",
        context={"fingerprint": fingerprint},
    )
    await publish(state.snapshot(state="running", percent=_PCT_VERSIONED))
    if canceled():
        return state.snapshot(state="canceled", percent=_PCT_VERSIONED)

    # --- lint -----------------------------------------------------------------
    lint = adapter.lint(model)
    state.event(
        "LINT_COMPLETED",
        f"Lint produced {len(lint.findings)} finding(s)"
        + (f", score {lint.score}" if lint.score is not None else "")
        + ".",
    )
    await publish(state.snapshot(state="running", percent=_PCT_LINTED))

    # --- persist (canonical→catalog hook, MFI-23.7) ---------------------------
    # A non-dry-run import stores its routed artifact: a non-publishable **catalog item** for every
    # non-OpenAPI format, keeping the *original source verbatim* in the revision's format_metadata so
    # the user can convert it to OpenAPI later (MFI-EPIC-22) — nothing is converted at import time.
    # The DB driver is blocking, so the write runs off-thread. A persistence failure fails the job
    # (unlike the best-effort quality capture) since without it the import produced nothing.
    result: Optional[SpecImportJobResult] = None
    tenant_id = str(payload.get("tenant_id") or "")
    if not options.get("dry_run") and not adapter.preview_only:
        try:
            result = await asyncio.to_thread(
                persist_adapter_import, payload, model, raw_text, routing
            )
        except Exception as exc:  # noqa: BLE001 - surface a persistence fault as a failed job
            logger.exception("adapter import persistence failed job=%s", job_id)
            state.event("PERSIST_ERROR", f"Failed to store the import: {exc}", level="error")
            return state.snapshot(state="failed", percent=_PCT_LINTED)

    if result is not None:
        state.event(
            "PERSISTED",
            f"Stored {routing.target.value} item {result.project_id} "
            f"(revision {result.version_record_id}); the original source was kept verbatim "
            "for later conversion.",
            context={
                "project_id": result.project_id,
                "version_record_id": result.version_record_id,
                "publishable": routing.publishable,
            },
        )
        # Capture the rolled-up quality score onto the freshly created revision (MFI-4.2).
        if result.version_record_id and tenant_id:
            await asyncio.to_thread(
                capture_canonical_quality_score, result.version_record_id, tenant_id, lint
            )
            state.event(
                "QUALITY_CAPTURED",
                f"Captured quality score onto revision {result.version_record_id}.",
            )

    # --- finalize -------------------------------------------------------------
    summary = _build_summary(
        adapter=adapter,
        model=model,
        fingerprint=fingerprint,
        lint=lint,
        routing=routing,
        options=options,
        persisted=result is not None,
    )
    if options.get("dry_run"):
        state.event("DRY_RUN", "Dry run: the normalized model was not persisted.")
        state.event("IMPORT_COMPLETED", "Import-source pipeline completed (dry run; no catalog write).")
    else:
        state.event(
            "IMPORT_COMPLETED",
            "Import-source pipeline completed; the source was stored in the catalog unconverted.",
        )
    return state.snapshot(state="completed", percent=_PCT_DONE, summary=summary, result=result)
