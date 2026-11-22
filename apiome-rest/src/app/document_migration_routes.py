"""Run the document migration from the ops plane — COA-5.8 (#7084).

Platform-admin only, like the rest of ``/v1/ops``:

* ``POST /v1/ops/document-migration`` starts one step of :mod:`app.document_migration` (the
  ``copy`` step, or the ``purge`` step with ``purgeDbCopies``) in a background thread of this
  process and answers ``202``. A second start while a run is going answers ``409
  document-migration-running``; a purge on the ``db`` backend answers ``409
  document-migration-refused``.
* ``GET /v1/ops/document-migration`` reports whether a run is going in this process, the last
  run's report or error, the active backend and every checkpoint (which also shows runs from
  ``scripts/migrate_documents_to_store.py`` or another instance).

Only one non-dry run proceeds at a time across every instance (the job's advisory lock); a run
that finds the lock taken ends with the error ``Another document migration run is in progress.``
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .db_timeouts import long_statements
from .document_migration import (
    MAX_BATCH_SIZE,
    MAX_WORKERS,
    SOURCES,
    MigrationBusy,
    MigrationOptions,
    MigrationRefused,
    check_options,
    list_checkpoints,
    run_document_migration,
)
from .document_store import get_document_store
from .permissions import enforce_platform_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ops", tags=["ops"])

CODE_RUNNING = "document-migration-running"
CODE_REFUSED = "document-migration-refused"

SourceName = Literal["adapter_source", "import_snapshot", "frozen_schema", "export_artifact"]


class DocumentMigrationRequest(BaseModel):
    """One step of the document migration to start."""

    model_config = ConfigDict(populate_by_name=True)

    purge_db_copies: bool = Field(
        default=False,
        alias="purgeDbCopies",
        description="Run the purge step (drop database copies whose stored object verifies) instead of the copy step.",
    )
    dry_run: bool = Field(default=False, alias="dryRun", description="Report what the step would do; write nothing.")
    tenant_id: Optional[str] = Field(
        default=None, alias="tenantId", description="Only this tenant (UUID); every tenant when omitted."
    )
    sources: Optional[List[SourceName]] = Field(
        default=None, description="Only these sources; every source when omitted."
    )
    rate: float = Field(default=20.0, ge=0, description="Most rows per second; 0 for no limit.")
    batch_size: int = Field(
        default=50, ge=1, le=MAX_BATCH_SIZE, alias="batchSize", description="Rows per page and checkpoint."
    )
    workers: int = Field(default=1, ge=1, le=MAX_WORKERS, description="Rows processed in parallel.")

    def options(self) -> MigrationOptions:
        """The job options this request asks for."""
        return MigrationOptions(
            purge_db_copies=self.purge_db_copies,
            dry_run=self.dry_run,
            tenant_id=self.tenant_id,
            sources=tuple(self.sources) if self.sources else SOURCES,
            batch_size=self.batch_size,
            rate=self.rate,
            workers=self.workers,
        )


class _RunState:
    """The run this process started last: its thread, report and error."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.options: Optional[MigrationOptions] = None
        self.report: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None

    @property
    def running(self) -> bool:
        """Whether this process's run is still going."""
        return self.thread is not None and self.thread.is_alive()

    def snapshot(self) -> Dict[str, Any]:
        """JSON-ready view of the last run."""
        options = self.options
        return {
            "running": self.running,
            "startedAt": self.started_at,
            "step": options.step if options else None,
            "dryRun": options.dry_run if options else None,
            "scope": options.scope if options else None,
            "report": self.report,
            "error": self.error,
        }


_state = _RunState()


def _run(options: MigrationOptions) -> None:
    """Thread body: run the step and keep its report (or error) for the status endpoint."""
    try:
        # Copies every legacy document: the long statement ceiling applies (DBP-1.2, #7185).
        with long_statements():
            report = run_document_migration(db, get_document_store(), options)
        _state.report, _state.error = report.as_dict(), None
    except (MigrationRefused, MigrationBusy) as exc:
        _state.report, _state.error = None, str(exc)
    except Exception as exc:  # noqa: BLE001 - surface the failure in the status, never crash the server
        logger.exception("document migration run failed")
        _state.report, _state.error = None, f"The run stopped: {type(exc).__name__}."


@router.post("/document-migration", status_code=202)
def start_document_migration(
    request: DocumentMigrationRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """Start one step of the document migration in the background (COA-5.8, #7084). Platform-admin only.

    The copy step writes each database-held import source, frozen schema and export artifact to
    the document store, verifies it and links it; the purge step (``purgeDbCopies``) re-verifies
    each stored object and drops its database copy. Answers ``202`` with the run's status; follow
    it with ``GET /v1/ops/document-migration``.
    """
    enforce_platform_admin(db, auth_data)
    try:
        options = check_options(get_document_store(), request.options())
    except MigrationRefused as exc:
        raise HTTPException(status_code=409, detail={"code": CODE_REFUSED, "message": str(exc)}) from None
    with _state.lock:
        if _state.running:
            raise HTTPException(
                status_code=409,
                detail={"code": CODE_RUNNING, "message": "A document migration run is already in progress."},
            )
        _state.options, _state.report, _state.error = options, None, None
        _state.started_at = time.time()
        _state.thread = threading.Thread(target=_run, args=(options,), name="document-migration", daemon=True)
        _state.thread.start()
    return JSONResponse(status_code=202, content=_state.snapshot())


@router.get("/document-migration")
def document_migration_status(
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """The document migration's status (COA-5.8, #7084). Platform-admin only.

    Whether this instance is running a step, the last run's report or error, the active
    document store backend, and every checkpoint (per scope, step and source: the last key
    finished, running totals and when the step completed).
    """
    enforce_platform_admin(db, auth_data)
    try:
        backend = str(getattr(get_document_store(), "backend", "db"))
    except Exception:  # noqa: BLE001 - a misconfigured store is reported, not raised
        backend = None
    body = _state.snapshot()
    body["backend"] = backend
    body["checkpoints"] = list_checkpoints(db)
    return JSONResponse(content=body, headers={"Cache-Control": "no-store"})
