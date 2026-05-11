"""
Async spec-import jobs: schedule work and run the objectified-ui tsx worker (#3329).

The worker uses incremental import mode so the open transaction is not held across
HTTP requests; commit/rollback endpoints are idempotent or return 409 when N/A.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from fastapi import HTTPException

from .config import settings
from .models import (
    SpecImportCommitResponse,
    SpecImportJobAccepted,
    SpecImportJobListItem,
    SpecImportJobListResponse,
    SpecImportJobStatus,
    SpecImportRollbackResponse,
    SpecImportStartJsonRequest,
    SpecImportStartMetadata,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# Path segments relative to the ``objectified-ui`` package (yarn workspace cwd).
_WORKER_SCRIPT_UI_REL = Path("scripts") / "rest-spec-import-worker.ts"

# Override with JSON argv, e.g. ["yarn","workspace","objectified-ui","exec","tsx","scripts/rest-spec-import-worker.ts"]
_WORKER_ARGV_ENV_KEYS = ("SPEC_IMPORT_WORKER_ARGV", "OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV")

# asyncio subprocess StreamReader default limit is 64KiB; ``readline()`` raises
# ``ValueError: Separator is found, but chunk is longer than limit`` when one NDJSON
# line from the worker exceeds that. Large status payloads need a higher ceiling.
_DEFAULT_WORKER_STREAM_LIMIT = 256 * 1024 * 1024
_ENV_WORKER_STREAM_LIMIT_KEYS = (
    "SPEC_IMPORT_WORKER_STREAM_LIMIT",
    "OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT",
)

# Test hook: monkeypatch ``_worker_runner`` to an async callable(payload) -> dict (worker JSON).
_worker_runner: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None


def _resolve_worker_subprocess_stream_limit() -> int:
    """Max bytes per line (excluding newline) for stdout/stderr StreamReaders."""
    for key in _ENV_WORKER_STREAM_LIMIT_KEYS:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            n = int(raw, 10)
        except ValueError:
            logger.warning("Ignoring invalid %s=%r (expected integer bytes)", key, raw)
            continue
        if n < 65536:
            logger.warning(
                "Ignoring %s=%s (below minimum 65536); using default stream limit",
                key,
                raw,
            )
            continue
        return n
    return _DEFAULT_WORKER_STREAM_LIMIT


def _parse_worker_argv_env(raw: str) -> List[str]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("must be a non-empty JSON array")
    if not all(isinstance(x, str) and x for x in parsed):
        raise ValueError("must be a JSON array of non-empty strings")
    return list(parsed)


def resolve_spec_import_worker_invocation() -> tuple[List[str], Path]:
    """Argv and working directory for the UI ``tsx`` worker subprocess.

    ``FileNotFoundError`` / errno 2 from asyncio subprocess almost always means the *executable*
    (first argv element) is missing from ``PATH`` — not the uploaded spec path.

    Resolution order:

    1. ``SPEC_IMPORT_WORKER_ARGV`` or ``OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV`` — JSON array;
       cwd is always the monorepo root (``_REPO_ROOT``).
    2. ``yarn workspace objectified-ui exec tsx …`` from repo root if ``yarn`` is on ``PATH``.
    3. ``corepack yarn workspace …`` from repo root if ``corepack`` is on ``PATH``.
    4. ``npm exec --workspace=objectified-ui -- tsx …`` from repo root if ``npm`` is on ``PATH``.
    5. ``objectified-ui/node_modules/.bin/tsx`` if present (after ``yarn install``).
    6. Global ``tsx`` on ``PATH``, cwd ``objectified-ui/``.
    7. ``npx --yes tsx …``, cwd ``objectified-ui/``.

    If nothing matches, raises ``RuntimeError`` with remediation hints (no silent fallback to a
    missing ``yarn`` binary).
    """
    repo = _REPO_ROOT
    ui_root = repo / "objectified-ui"
    worker_rel = _WORKER_SCRIPT_UI_REL

    for key in _WORKER_ARGV_ENV_KEYS:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return _parse_worker_argv_env(raw), repo

    tail_yarn = ["workspace", "objectified-ui", "exec", "tsx", str(worker_rel)]
    candidates_repo_cwd: Sequence[List[str]] = (
        ["yarn", *tail_yarn],
        ["corepack", "yarn", *tail_yarn],
        ["npm", "exec", "--workspace=objectified-ui", "--", "tsx", str(worker_rel)],
    )
    for argv in candidates_repo_cwd:
        if shutil.which(argv[0]):
            return list(argv), repo

    local_tsx = ui_root / "node_modules" / ".bin" / "tsx"
    if local_tsx.is_file():
        return [str(local_tsx), str(worker_rel)], ui_root

    tsx_global = shutil.which("tsx")
    if tsx_global:
        return [tsx_global, str(worker_rel)], ui_root

    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "tsx", str(worker_rel)], ui_root

    wr = worker_rel.as_posix()
    raise RuntimeError(
        "Cannot run the specification import worker: no usable Node runner found. "
        "Checked PATH for yarn, corepack, npm, tsx, and npx, and looked for "
        f"{local_tsx} (run `yarn install` at the monorepo root if this file is missing). "
        "Install Node.js + Yarn or npm on the API host, install workspace dependencies, "
        "or set SPEC_IMPORT_WORKER_ARGV (or OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV) to a JSON argv "
        "array whose first element is an absolute path to an executable, e.g. "
        f'["/usr/bin/yarn","workspace","objectified-ui","exec","tsx","{wr}"].'
    )


def resolve_spec_import_worker_argv() -> List[str]:
    """Argv only (cwd is ``_REPO_ROOT`` for env overrides and yarn/npm; else see invocation)."""
    argv, _cwd = resolve_spec_import_worker_invocation()
    return argv


def _format_worker_spawn_errno2_message(argv: List[str], cwd: Path, exc: OSError) -> str:
    exe = argv[0] if argv else "(empty argv)"
    return (
        f"{exc}; failed to execute {exe!r} while spawning spec import worker (cwd={cwd}). "
        "Errno 2 means the program was not found on PATH or is not executable — "
        "not your uploaded spec path. Install Node tooling on the API host, run `yarn install` "
        "at the monorepo root so objectified-ui/node_modules/.bin/tsx exists, or set "
        "SPEC_IMPORT_WORKER_ARGV to a JSON argv array whose first token is an absolute path "
        '(example: ["/usr/bin/yarn","workspace","objectified-ui","exec","tsx",'
        f'"{_WORKER_SCRIPT_UI_REL.as_posix()}"].)'
    )


@dataclass
class _JobRecord:
    tenant_slug: str
    job_id: str
    state: str
    status: SpecImportJobStatus
    proc: Optional[asyncio.subprocess.Process] = None
    cancel_requested: bool = False
    commit_response: Optional[SpecImportCommitResponse] = None
    rollback_response: Optional[SpecImportRollbackResponse] = None


_jobs: Dict[str, _JobRecord] = {}
_jobs_lock = asyncio.Lock()


def _build_worker_payload(
    *,
    rest_job_id: str,
    tenant_id: str,
    user_id: str,
    body: SpecImportStartJsonRequest,
) -> Dict[str, Any]:
    meta = body.metadata
    return {
        "rest_job_id": rest_job_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "metadata": json.loads(meta.model_dump_json()),
        "document_base64": body.document_base64,
        "filename": body.filename,
        "content_type": body.content_type,
    }


def _default_result_status(
    job_id: str, message: str, code: str = "WORKER_ERROR"
) -> SpecImportJobStatus:
    return SpecImportJobStatus(
        job_id=job_id,
        state="failed",
        percent=0,
        events=[
            {
                "id": "rest-1",
                "ts": 0,
                "level": "error",
                "code": code,
                "message": message,
                "context": None,
            }
        ],
    )


def _maybe_build_commit_response(
    job_id: str, status: SpecImportJobStatus
) -> Optional[SpecImportCommitResponse]:
    if status.state != "completed":
        return None
    r = status.result
    if r is None:
        return None
    if not r.project_id or not r.project_slug or not r.version_id or not r.version_record_id:
        return None
    return SpecImportCommitResponse(
        job_id=job_id,
        state="completed",
        project_id=r.project_id,
        project_slug=r.project_slug,
        version_id=r.version_id,
        version_record_id=r.version_record_id,
    )


async def _apply_streaming_spec_import_status(job_id: str, status_raw: Dict[str, Any]) -> None:
    """Merge a worker-emitted partial status snapshot into the in-memory job record."""
    try:
        status = SpecImportJobStatus.model_validate(status_raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("Ignoring invalid partial import status job=%s: %s", job_id, e)
        return
    if status.job_id != job_id:
        logger.debug("Partial import status job_id mismatch (expected %s)", job_id)
        return
    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None or rec.cancel_requested:
            return
        rec.state = status.state
        rec.status = status


async def _run_subprocess_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    env = {**os.environ}
    db_url = os.environ.get("DATABASE_URL") or settings.effective_database_url
    env["DATABASE_URL"] = db_url

    argv, worker_cwd = resolve_spec_import_worker_invocation()
    logger.info("spec import worker spawn argv=%s cwd=%s", argv, worker_cwd)
    job_id = str(payload.get("rest_job_id", ""))
    data = json.dumps(payload).encode("utf-8")
    stderr_chunks: List[bytes] = []

    stream_limit = _resolve_worker_subprocess_stream_limit()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(worker_cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=stream_limit,
        )
    except OSError as exc:
        errno = getattr(exc, "errno", None)
        if isinstance(exc, FileNotFoundError) or errno == 2:
            raise FileNotFoundError(_format_worker_spawn_errno2_message(argv, worker_cwd, exc)) from exc
        raise

    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is not None:
            rec.proc = proc

    last: Dict[str, Any] = {}
    parse_error: Optional[str] = None

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(65536)
            if not chunk:
                break
            stderr_chunks.append(chunk)

    stderr_task = asyncio.create_task(drain_stderr())

    try:
        assert proc.stdin is not None
        proc.stdin.write(data)
        await proc.stdin.drain()
        proc.stdin.close()

        assert proc.stdout is not None
        while True:
            line_b = await proc.stdout.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                parsed_line: Dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                parse_error = line[:200]
                break

            if parsed_line.get("partial"):
                status_raw = parsed_line.get("status")
                if isinstance(status_raw, dict):
                    await _apply_streaming_spec_import_status(job_id, status_raw)
                continue

            last = parsed_line
    finally:
        if proc.returncode is None:
            await proc.wait()
        await stderr_task
        async with _jobs_lock:
            r2 = _jobs.get(job_id)
            if r2 is not None:
                r2.proc = None

    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
    if stderr_text:
        logger.warning("spec import worker stderr job=%s: %s", job_id, stderr_text[:4000])

    if parse_error is not None:
        return {
            "ok": False,
            "error": f"Worker stdout is not JSON (exit {proc.returncode}): {parse_error}",
        }

    if not last:
        return {"ok": False, "error": "Worker produced no stdout"}

    if proc.returncode != 0 and not last.get("ok"):
        return last

    if proc.returncode != 0:
        return {"ok": False, "error": last.get("error") or f"Worker exited {proc.returncode}"}

    return last


async def _invoke_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _worker_runner is not None:
        return await _worker_runner(payload)
    return await _run_subprocess_worker(payload)


async def _drive_job(job_id: str, payload: Dict[str, Any]) -> None:
    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return
        if rec.cancel_requested:
            rec.state = "canceled"
            rec.status = SpecImportJobStatus(job_id=job_id, state="canceled", percent=0)
            return
        rec.state = "running"
        rec.status = SpecImportJobStatus(job_id=job_id, state="running", percent=0)

    try:
        raw = await _invoke_worker(payload)
    except Exception as e:  # noqa: BLE001
        logger.exception("spec import worker crashed job=%s", job_id)
        async with _jobs_lock:
            rec = _jobs.get(job_id)
            if rec is None:
                return
            rec.state = "failed"
            rec.status = _default_result_status(job_id, str(e), code="WORKER_EXCEPTION")
        return

    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return
        if rec.cancel_requested:
            rec.state = "canceled"
            rec.status = SpecImportJobStatus(job_id=job_id, state="canceled", percent=0)
            return

    if not raw.get("ok"):
        msg = str(raw.get("error") or "Import worker failed")
        async with _jobs_lock:
            rec = _jobs.get(job_id)
            if rec is None:
                return
            rec.state = "failed"
            rec.status = _default_result_status(job_id, msg, code="WORKER_FAILED")
        return

    status_raw = raw.get("status")
    if not isinstance(status_raw, dict):
        async with _jobs_lock:
            rec = _jobs.get(job_id)
            if rec is None:
                return
            rec.state = "failed"
            rec.status = _default_result_status(
                job_id, "Worker returned ok but no status object", code="BAD_WORKER_PAYLOAD"
            )
        return

    try:
        status = SpecImportJobStatus.model_validate(status_raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("Invalid worker status for job=%s: %s", job_id, e)
        async with _jobs_lock:
            rec = _jobs.get(job_id)
            if rec is None:
                return
            rec.state = "failed"
            rec.status = _default_result_status(
                job_id, f"Invalid job status from worker: {e}", code="INVALID_STATUS"
            )
        return

    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return
        rec.state = status.state
        rec.status = status
        rec.commit_response = _maybe_build_commit_response(job_id, status)


def _get_record(tenant_slug: str, job_id: str) -> _JobRecord:
    rec = _jobs.get(job_id)
    if rec is None or rec.tenant_slug != tenant_slug:
        raise HTTPException(status_code=404, detail="Import job not found")
    return rec


async def schedule_spec_import(
    tenant_slug: str,
    tenant_id: str,
    user_id: str,
    body: SpecImportStartJsonRequest,
) -> SpecImportJobAccepted:
    job_id = str(uuid.uuid4())
    payload = _build_worker_payload(
        rest_job_id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        body=body,
    )
    initial = SpecImportJobStatus(job_id=job_id, state="queued", percent=0)
    async with _jobs_lock:
        _jobs[job_id] = _JobRecord(
            tenant_slug=tenant_slug,
            job_id=job_id,
            state="queued",
            status=initial,
        )
    asyncio.create_task(_drive_job(job_id, payload))
    return SpecImportJobAccepted(
        job_id=job_id,
        status_path=f"/v1/tenants/{tenant_slug}/imports/{job_id}",
    )


async def schedule_spec_import_multipart(
    tenant_slug: str,
    tenant_id: str,
    user_id: str,
    metadata: SpecImportStartMetadata,
    file_bytes: bytes,
    filename: Optional[str],
    content_type: Optional[str],
) -> SpecImportJobAccepted:
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    body = SpecImportStartJsonRequest(
        metadata=metadata,
        document_base64=b64,
        filename=filename,
        content_type=content_type,
    )
    return await schedule_spec_import(tenant_slug, tenant_id, user_id, body)


def get_spec_import_status(tenant_slug: str, job_id: str) -> SpecImportJobStatus:
    rec = _get_record(tenant_slug, job_id)
    return rec.status


async def list_spec_import_jobs(tenant_slug: str) -> SpecImportJobListResponse:
    async with _jobs_lock:
        items: list[SpecImportJobListItem] = []
        for rec in _jobs.values():
            if rec.tenant_slug != tenant_slug:
                continue
            st = rec.status
            items.append(
                SpecImportJobListItem(
                    job_id=st.job_id,
                    state=st.state,
                    percent=st.percent,
                    status_path=f"/v1/tenants/{tenant_slug}/imports/{st.job_id}",
                    progress=st.progress,
                    result=st.result,
                )
            )
    return SpecImportJobListResponse(jobs=items)


async def cancel_spec_import_job(tenant_slug: str, job_id: str) -> None:
    async with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None or rec.tenant_slug != tenant_slug:
            raise HTTPException(status_code=404, detail="Import job not found")
        if rec.state in ("completed", "failed", "canceled", "rolled-back"):
            return
        rec.cancel_requested = True
        proc = rec.proc
    if proc is not None and proc.returncode is None:
        proc.kill()


def commit_spec_import_job(tenant_slug: str, job_id: str) -> SpecImportCommitResponse:
    rec = _get_record(tenant_slug, job_id)
    if rec.commit_response is not None:
        return rec.commit_response
    if rec.status.state == "pending-approval":
        raise HTTPException(
            status_code=501,
            detail=(
                "Two-phase commit for preview imports is not available through REST yet; "
                "this server runs incremental imports that finalize without a separate commit."
            ),
        )
    raise HTTPException(
        status_code=409,
        detail=f"No commit available for import job in state {rec.status.state}",
    )


def rollback_spec_import_job(tenant_slug: str, job_id: str) -> SpecImportRollbackResponse:
    rec = _get_record(tenant_slug, job_id)
    if rec.rollback_response is not None:
        return rec.rollback_response
    if rec.status.state == "rolled-back":
        return SpecImportRollbackResponse(job_id=job_id, state="rolled-back")
    if rec.status.state == "pending-approval":
        raise HTTPException(
            status_code=501,
            detail=(
                "Rollback for preview imports is not wired through REST yet; "
                "incremental imports do not use a held-open preview transaction."
            ),
        )
    raise HTTPException(
        status_code=409,
        detail=f"Cannot rollback import job in state {rec.status.state}",
    )
