"""Refresh URL-sourced imports — capture, sweep and fetch (RAR-6.1, #3538).

* :func:`record_url_import` — called (through ``POST …/url-imports``) after a URL import
  succeeds. It records the lineage: the stored import spec, and the validators and checksum of
  the document, which REST fetches once itself so the anchors are what *this* server sees. An
  import fetched with credentials is recorded as ``authenticated`` and never refreshed.
* :func:`process_url_import_refresh_sweep` — one sweep tick (wired in :mod:`app.main` on the
  repository refresh floor). For each due lineage it either follows the import a previous tick
  started, or checks the URL:

  1. **Conditional GET** with ``If-None-Match`` / ``If-Modified-Since`` through the SSRF-guarded
     client (:func:`fetch_conditional`). 304 → up to date.
  2. **Freshness gate** (:func:`app.url_import_refresh.decide_check`): the same document, or a
     ``Last-Modified`` older than the import, → up to date.
  3. **Divergence gate** (RAR-4.4): when the version the last import produced was edited in Apiome
     since, the refresh is held (``diverged``) and nothing is overwritten.
  4. **Spec-faithful re-import** (RAR-4.1): the stored spec is replayed onto the project through the
     spec-import engine as a new date/time-labelled version. The fetched validators become the
     anchors once that import completes; a failed import keeps the old anchors, so the next check
     tries again.

  A failure (network, HTTP error, SSRF refusal, failed import) is recorded with its error class
  and backs the lineage off exponentially. The tick honours the global auto-refresh kill switch
  (``APIOME_REFRESH_ENABLED``, RAR-3.3) and the per-lineage opt-out, and an advisory lock keeps
  replicas from checking the same lineages at once. Nothing here raises out of the tick.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple

import httpx

from . import url_import_store as store
from .refresh_source import ERROR_CLASS_UNEXPECTED, RefreshSourceError
from .url_import_refresh import (
    REASON_BASELINE,
    STATUS_UP_TO_DATE,
    build_refresh_request,
    checksum_bytes,
    conditional_headers,
    decide_check,
    divergence_for,
    normalize_url,
    version_content_checksum,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "FetchResult",
    "MAX_DOCUMENT_BYTES",
    "SWEEP_LOCK_KEY",
    "current_version_checksum",
    "fetch_conditional",
    "process_url_import_refresh_sweep",
    "record_url_import",
]

#: Session advisory-lock key that keeps the sweep single-flight across replicas.
SWEEP_LOCK_KEY = "apiome.url_import_refresh_sweep"
#: Most lineages one tick looks at; the rest stay due for the next tick.
MAX_PER_TICK = 100
#: Largest document a check reads (the import wizard's own default cap).
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
#: One check's network budget.
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
_USER_AGENT = "Apiome-UrlImportRefresh/1.0"
#: Import job states that are still running.
_PENDING_STATES = ("queued", "running", "committing", "pending-approval")


@dataclass(frozen=True)
class FetchResult:
    """One conditional GET.

    Attributes:
        status_code: ``304``, or the 2xx the server answered with.
        body: The document on a 2xx; empty on a 304.
        etag: The response's ``ETag``.
        last_modified: The response's ``Last-Modified``.
        content_type: The response's ``Content-Type``.
    """

    status_code: int
    body: bytes = b""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_type: Optional[str] = None


def fetch_conditional(
    url: str,
    *,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> FetchResult:
    """GET ``url`` with the stored validators, through the SSRF guard on every redirect hop.

    Args:
        url: The stored URL.
        etag: Sent as ``If-None-Match`` when given.
        last_modified: Sent as ``If-Modified-Since`` when given.
        client: An HTTP client (tests pass a mock transport); a guarded one by default.

    Returns:
        The :class:`FetchResult` for a 304 or a 2xx.

    Raises:
        RefreshSourceError: Any other status (with it), a refused address, an oversized document, or
            no answer at all.
    """
    from .ssrf_guard import SSRFError, build_guarded_client, validate_url

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, application/yaml, text/yaml, text/plain, */*",
        **conditional_headers(etag, last_modified),
    }
    try:
        validate_url(url)
        owned = client is None
        http = client or build_guarded_client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
        try:
            with http.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 304:
                    return FetchResult(status_code=304)
                if not 200 <= resp.status_code < 300:
                    raise RefreshSourceError(
                        f"The URL answered HTTP {resp.status_code}.", http_status=resp.status_code
                    )
                chunks, total = [], 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_DOCUMENT_BYTES:
                        raise RefreshSourceError(
                            f"The document is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.",
                            error_class=ERROR_CLASS_UNEXPECTED,
                        )
                    chunks.append(chunk)
                return FetchResult(
                    status_code=resp.status_code,
                    body=b"".join(chunks),
                    etag=resp.headers.get("etag"),
                    last_modified=resp.headers.get("last-modified"),
                    content_type=resp.headers.get("content-type"),
                )
        finally:
            if owned:
                http.close()
    except SSRFError as exc:
        raise RefreshSourceError(
            f"The URL points at an address Apiome does not fetch: {exc}", error_class="blocked"
        ) from exc
    except httpx.HTTPError as exc:
        raise RefreshSourceError(f"The URL could not be reached ({type(exc).__name__}).") from exc


def current_version_checksum(db: Any, tenant_id: str, version_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Whether a version still exists, and its content checksum (RAR-4.4).

    Returns:
        ``(False, None)`` when there is no version or it was deleted, else ``(True, checksum)``.
    """
    from .revision_deprecation import is_uuid_string
    from .spec_snapshot import build_live_spec

    if not version_id or not is_uuid_string(str(version_id)):
        return False, None
    row = store.get_version_for_checksum(db, tenant_id, str(version_id))
    if row is None:
        return False, None
    spec, _counts = build_live_spec(db, row, "_", "_", str(row.get("version_id") or "_"))
    return True, version_content_checksum(spec)


# ---------------------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------------------


def record_url_import(
    db: Any,
    *,
    tenant_id: str,
    user_id: Optional[str],
    project_id: str,
    url: str,
    source_kind: str,
    format_override: Optional[str],
    content_type: Optional[str],
    options: Mapping[str, Any],
    authenticated: bool,
    version_id: Optional[str],
    fetch: Callable[..., FetchResult] = fetch_conditional,
) -> Dict[str, Any]:
    """Record the lineage of a URL import that just succeeded.

    Args:
        db: Database handle.
        tenant_id: The importing tenant (the project is already checked to be its).
        user_id: Who imported; refreshes are imported as them.
        project_id: The project the import landed in.
        url: The URL imported from.
        source_kind: The importer kind (``openapi``, ``arazzo``).
        format_override: The resolved format, when the importer recorded one.
        content_type: The type the document was parsed as.
        options: The import options, verbatim (the wizard's camelCase blob).
        authenticated: The import was fetched with credentials: recorded, never refreshed.
        version_id: The version the import produced (``versions.id``); its checksum is the
            divergence baseline.
        fetch: The fetcher (tests inject one).

    Returns:
        The stored row.

    Raises:
        UrlImportError: The URL is not an http/https URL without credentials.
    """
    normalized = normalize_url(url)
    etag = last_modified = checksum = error = None
    if not authenticated:
        try:
            result = fetch(normalized)
            etag, last_modified, checksum = result.etag, result.last_modified, checksum_bytes(result.body)
        except RefreshSourceError as exc:
            # Recorded anyway; the first check anchors on what is served then (``baseline``).
            error = str(exc)
    exists, post_import = current_version_checksum(db, tenant_id, version_id)
    clean_options = {key: value for key, value in dict(options or {}).items() if key != "dryRun"}
    return store.upsert_spec(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        url=normalized,
        source_kind=source_kind or "openapi",
        format_override=format_override,
        content_type=content_type,
        options=clean_options,
        created_by=user_id,
        authenticated=bool(authenticated),
        etag=etag,
        last_modified=last_modified,
        content_checksum=checksum,
        last_version_id=str(version_id) if exists else None,
        post_import_checksum=post_import,
        last_error=error,
    )


# ---------------------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------------------

ScheduleFn = Callable[[str, str, str, Any], Awaitable[Any]]
StatusFn = Callable[[str, str], Awaitable[Any]]


async def process_url_import_refresh_sweep(
    db: Any,
    *,
    fetch: Callable[..., FetchResult] = fetch_conditional,
    schedule: Optional[ScheduleFn] = None,
    job_status: Optional[StatusFn] = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Run one tick over every due URL lineage. Never raises.

    Args:
        db: Database handle for this tick; blocking queries run in worker threads.
        fetch: The conditional fetcher (tests inject one).
        schedule: Starts a spec import (defaults to :func:`app.spec_import_engine.schedule_spec_import`).
        job_status: Reads a spec-import job (defaults to
            :func:`app.spec_import_engine.get_spec_import_status`).
        now: The tick's time (labels new versions; tests pin it).

    Returns:
        Counts per outcome (``up-to-date``, ``refreshing``, ``refreshed``, ``diverged``, ``failed``),
        empty when the kill switch is off or another replica holds the tick.
    """
    from .config import settings

    if not settings.refresh_enabled:
        return {}
    if schedule is None or job_status is None:
        from .spec_import_engine import get_spec_import_status, schedule_spec_import

        schedule = schedule or schedule_spec_import
        job_status = job_status or get_spec_import_status
    try:
        locked = await asyncio.to_thread(_try_lock, db)
    except Exception:  # noqa: BLE001 - a tick never raises
        _logger.warning("url import refresh: could not take the sweep lock", exc_info=True)
        return {}
    if not locked:
        return {}
    counts: Dict[str, int] = {}
    try:
        rows = await asyncio.to_thread(
            store.list_due,
            db,
            default_interval_seconds=int(settings.refresh_default_interval_seconds),
            min_interval_seconds=int(settings.refresh_min_interval_seconds),
            limit=MAX_PER_TICK,
        )
        for row in rows:
            if row.get("pending_job_id"):
                outcome = await _follow(db, row, job_status)
            else:
                outcome = await _check(db, row, fetch, schedule, now or datetime.now(timezone.utc))
            if outcome:
                counts[outcome] = counts.get(outcome, 0) + 1
    except Exception:  # noqa: BLE001 - a tick never raises
        _logger.warning("url import refresh sweep failed", exc_info=True)
    finally:
        try:
            await asyncio.to_thread(_unlock, db)
        except Exception:  # noqa: BLE001
            _logger.warning("url import refresh: could not release the sweep lock", exc_info=True)
    return counts


def _try_lock(db: Any) -> bool:
    rows = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (SWEEP_LOCK_KEY,))
    return bool(rows and rows[0].get("locked"))


def _unlock(db: Any) -> None:
    db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (SWEEP_LOCK_KEY,))


async def _fail(db: Any, row: Mapping[str, Any], reason: str, error: str) -> str:
    """Record a failure (with backoff) and return the ``failed`` outcome."""
    from .config import settings

    _logger.info("url import refresh failed spec=%s reason=%s", row.get("id"), reason)
    await asyncio.to_thread(
        store.record_failure,
        db,
        str(row["id"]),
        reason=reason,
        error=error,
        default_interval_seconds=int(settings.refresh_default_interval_seconds),
    )
    return "failed"


async def _check(
    db: Any, row: Mapping[str, Any], fetch: Callable[..., FetchResult], schedule: ScheduleFn, now: datetime
) -> Optional[str]:
    """Check one lineage's URL and, when it changed, start its re-import."""
    from .versioning import format_version_tag

    spec_id = str(row["id"])
    try:
        try:
            result = await asyncio.to_thread(
                fetch, str(row["url"]), etag=row.get("etag"), last_modified=row.get("last_modified")
            )
        except RefreshSourceError as exc:
            return await _fail(db, row, exc.error_class, str(exc))
        decision = decide_check(
            status_code=result.status_code,
            body=result.body,
            response_last_modified=result.last_modified,
            stored_last_modified=row.get("last_modified"),
            stored_checksum=row.get("content_checksum"),
        )
        if decision.record_anchors:
            await asyncio.to_thread(
                store.record_anchors,
                db,
                spec_id,
                etag=result.etag,
                last_modified=result.last_modified,
                checksum=decision.checksum,
                reason=REASON_BASELINE,
            )
            return STATUS_UP_TO_DATE
        if not decision.refresh:
            await asyncio.to_thread(store.record_check, db, spec_id, status=STATUS_UP_TO_DATE, reason=decision.reason)
            return STATUS_UP_TO_DATE

        tenant_id = str(row["tenant_id"])
        exists, current = await asyncio.to_thread(current_version_checksum, db, tenant_id, row.get("last_version_id"))
        if exists:
            guard = divergence_for(row.get("post_import_checksum"), current)
            if guard.should_hold:
                await asyncio.to_thread(store.record_diverged, db, spec_id, reason=guard.reason.value)
                return "diverged"

        slug = await asyncio.to_thread(store.tenant_slug, db, tenant_id)
        if not slug or not row.get("created_by"):
            return await _fail(db, row, "no-importer", "The person who imported this URL is no longer known.")
        request = build_refresh_request(
            row, content=result.body, version_label=format_version_tag(now), content_type=result.content_type
        )
        accepted = await schedule(slug, tenant_id, str(row["created_by"]), request)
        await asyncio.to_thread(
            store.record_started,
            db,
            spec_id,
            job_id=str(accepted.job_id),
            etag=result.etag,
            last_modified=result.last_modified,
            checksum=decision.checksum,
            reason=decision.reason,
        )
        return "refreshing"
    except Exception as exc:  # noqa: BLE001 - one lineage never stops the tick
        _logger.warning("url import refresh check failed spec=%s", spec_id, exc_info=True)
        return await _fail(db, row, ERROR_CLASS_UNEXPECTED, f"The refresh could not start ({type(exc).__name__}).")


async def _follow(db: Any, row: Mapping[str, Any], job_status: StatusFn) -> Optional[str]:
    """Follow the import a previous tick started; on success its validators become the anchors."""
    spec_id = str(row["id"])
    tenant_id = str(row["tenant_id"])
    try:
        slug = await asyncio.to_thread(store.tenant_slug, db, tenant_id)
        try:
            status = await job_status(slug or "", str(row["pending_job_id"]))
        except Exception:  # noqa: BLE001 - a job no instance knows any more
            return await _fail(db, row, "import-lost", "The refresh import could not be found.")
        state = str(getattr(status, "state", "") or "")
        if state in _PENDING_STATES:
            return None
        if state == "completed":
            result = getattr(status, "result", None)
            version_id = getattr(result, "version_record_id", None) if result is not None else None
            _exists, checksum = await asyncio.to_thread(current_version_checksum, db, tenant_id, version_id)
            await asyncio.to_thread(
                store.record_finished, db, spec_id, version_id=version_id, post_import_checksum=checksum
            )
            return "refreshed"
        error = getattr(status, "error", None)
        message = getattr(error, "message", None) or f"The refresh import ended {state or 'without a result'}."
        return await _fail(db, row, "import-failed", str(message))
    except Exception as exc:  # noqa: BLE001 - one lineage never stops the tick
        _logger.warning("url import refresh follow failed spec=%s", spec_id, exc_info=True)
        message = f"The refresh import could not be read ({type(exc).__name__})."
        return await _fail(db, row, ERROR_CLASS_UNEXPECTED, message)
