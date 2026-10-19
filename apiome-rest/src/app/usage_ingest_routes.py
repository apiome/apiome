"""``POST /v1/tenants/{tenant_slug}/usage/ingest`` — RDG-1.2 (#5760).

The usage index's one door. A traffic source — an OpenTelemetry Collector, a log shipper, the CLI
uploading a HAR file — posts batches of ``apiome.usage.event/v1`` events here, and
:mod:`app.usage_ingest` turns them into counters (tier cap → head sampling → scrubbing → template
matching → ledger).

**Authentication** is an ordinary workspace API key carrying the ``usage:ingest`` scope (V291) —
no new key kind, no new identity. The scope admits this route and nothing else
(:data:`app.auth._API_KEY_SCOPE_ALLOWLIST`); a full-access (``*``) key is accepted too. A browser
session is refused (``usage-ingest-key-required``): the door is for machines. An agent key
(``kind = 'agent'``) is never a REST credential, so it cannot reach the route at all.

**The request** is read raw, not through a Pydantic body, because it may be gzip-compressed and its
size is bounded before it is parsed: at most 2 MiB (compressed and decompressed) and 5,000 events.
The source is named by the ``X-Apiome-Usage-Source`` header or ``source_id`` in the body.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .usage_ingest import (
    CODE_BATCH_INVALID,
    CODE_KEY_REQUIRED,
    CODE_SOURCE_REQUIRED,
    MAX_BATCH_BYTES,
    MAX_EVENTS_PER_BATCH,
    MAX_REJECTION_DETAILS,
    REJECTION_REASONS,
    UsageIngestError,
    batch_digest,
    decode_body,
    parse_batch,
)
from .usage_ingest_store import ingest_batch

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["usage"])

#: The header a source may name itself by (instead of ``source_id`` in the body).
SOURCE_HEADER = "X-Apiome-Usage-Source"


class UsageIngestRejection(BaseModel):
    """One rejected event — its index and why, never its content."""

    index: int = Field(description="The event's position in the batch (0-based).")
    reason: str = Field(description="Why it was rejected: " + ", ".join(f"`{r}`" for r in REJECTION_REASONS) + ".")


class UsageIngestSamples(BaseModel):
    """What happened to the opt-in body samples of the batch."""

    stored: int = Field(description="Samples reduced, re-scanned clean and stored as `usage_sample` rows.")
    dropped: int = Field(
        description="Chosen samples refused because the credential re-scan flagged them or they exceeded 16 KiB."
    )


class UsageIngestResponse(BaseModel):
    """The ledger row of an admitted batch, echoed back."""

    model_config = ConfigDict(populate_by_name=True)

    batch_id: str = Field(alias="batchId", description="The `usage_ingest_batch` ledger row.")
    source_id: str = Field(alias="sourceId", description="The source the batch was filed under.")
    received_at: datetime = Field(alias="receivedAt", description="When the batch was ledgered.")
    received: int = Field(description="Events in the batch.")
    accepted: int = Field(description="Kept by sampling and matched to an operation of a published revision.")
    sampled_out: int = Field(alias="sampledOut", description="Dropped by head sampling.")
    unmatched: int = Field(
        description="Kept, but no published revision declares the operation; counted by inferred template."
    )
    rejected: int = Field(description="Refused; see `rejections`.")
    scrub_findings: int = Field(
        alias="scrubFindings",
        description="Strings the edge scrub rewrote or dropped (a count, never what was found).",
    )
    basis: str = Field(
        description="`complete` at sampling rate 1; `sampled` when counts were scaled by the inverse rate."
    )
    sampling_rate: float = Field(alias="samplingRate", description="The source's head-sampling rate.")
    samples: UsageIngestSamples
    rejections: List[UsageIngestRejection] = Field(
        description=f"Per-event rejections, at most {MAX_REJECTION_DETAILS} (the counts cover every event)."
    )
    rejections_truncated: bool = Field(alias="rejectionsTruncated", description="Whether `rejections` was cut short.")


#: The request body as OpenAPI describes it. The route reads the body raw (gzip, size limits), so
#: FastAPI cannot derive this from a model.
_REQUEST_BODY: Dict[str, Any] = {
    "required": True,
    "description": (
        f"A batch of at most {MAX_EVENTS_PER_BATCH} `apiome.usage.event/v1` events, at most "
        f"{MAX_BATCH_BYTES} bytes (send `Content-Encoding: gzip` to compress it; the limit applies "
        "before and after decompression)."
    ),
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["events"],
                "properties": {
                    "source_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": f"The usage source (or send the `{SOURCE_HEADER}` header).",
                    },
                    "events": {
                        "type": "array",
                        "maxItems": MAX_EVENTS_PER_BATCH,
                        "items": {
                            "type": "object",
                            "description": (
                                "One `apiome.usage.event/v1` event. `schema`, `source_id` and "
                                "`environment` may be omitted (the source's are used). `path` may "
                                "carry a query string: its parameter names are kept and its values "
                                "discarded before the event is built. Unknown keys reject the event."
                            ),
                            "required": ["observed_at", "method", "path", "status", "latency_ms"],
                            "properties": {
                                "observed_at": {"type": "string", "format": "date-time"},
                                "method": {"type": "string", "example": "GET"},
                                "path": {"type": "string", "example": "/pets/42?limit=10"},
                                "status": {"type": "integer", "minimum": 100, "maximum": 599},
                                "latency_ms": {"type": "integer", "minimum": 0},
                                "environment": {"type": "string", "example": "prod"},
                                "request_bytes": {"type": "integer", "minimum": 0},
                                "response_bytes": {"type": "integer", "minimum": 0},
                                "scheme": {"type": "string", "enum": ["http", "https"]},
                                "host": {"type": "string"},
                                "auth_present": {"type": "string", "enum": ["true", "false", "unknown"]},
                                "version_hint": {"type": "object"},
                                "user_agent": {"type": "string", "maxLength": 256},
                                "consumer_hint": {"type": "object"},
                                "spec_revision_id": {"type": "string", "format": "uuid"},
                                "agent_key_id": {"type": "string", "format": "uuid"},
                                "fields": {
                                    "type": "object",
                                    "properties": {
                                        "request": {"type": "array", "items": {"type": "string"}},
                                        "response": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                                "sample": {
                                    "type": "object",
                                    "description": (
                                        "Opt-in exchange (`request` / `response`, each with `headers`, "
                                        "`body`, `mediaType`). Refused with `422 usage-body-not-accepted` "
                                        "unless the source's body window is open."
                                    ),
                                },
                            },
                        },
                    },
                },
            }
        }
    },
}


def _error(exc: UsageIngestError) -> HTTPException:
    """Translate a pipeline refusal into the HTTP error a source sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` carrying ``{"code", "message"}`` (plus ``retryAt`` and ``batchId``
        for a quota refusal, with a ``Retry-After`` header in seconds).
    """
    headers: Optional[Dict[str, str]] = None
    if exc.retry_at is not None:
        seconds = max(1, int((exc.retry_at - datetime.now(timezone.utc)).total_seconds()))
        headers = {"Retry-After": str(seconds)}
    return HTTPException(status_code=exc.status, detail=exc.detail(), headers=headers)


@router.post(
    "/{tenant_slug}/usage/ingest",
    response_model=UsageIngestResponse,
    response_model_by_alias=True,
    summary="Ingest a batch of usage events",
    description=(
        "The usage index's one door (RDG-1.2). Each event runs through the pipeline in order and "
        "stops at its first refusal:\n\n"
        "1. **Tier cap** — `usage_events_per_day` of the workspace's license. Over it, the whole "
        "batch is answered `429 usage-quota-exceeded` with `retryAt` and ledgered as rejected.\n"
        "2. **Head sampling** — a deterministic hash of `(source, observed_at, path, status)` "
        "against the source's `sampling_rate`; counts are scaled by the inverse rate "
        "(`basis: sampled`).\n"
        "3. **Scrubbing** — path segments that look like a credential, an email or a UUID become "
        "`{param}`; query values are discarded and names kept; the user agent is scrubbed and "
        "truncated.\n"
        "4. **Template matching** against the project's **published** revisions — `/pets/42` "
        "lands on `GET /pets/{petId}`. Unmatched traffic is counted by inferred template.\n"
        "5. **Ledger** — one row per batch; this response echoes it.\n\n"
        "Requires a workspace API key with the `usage:ingest` scope (or full access). A batch "
        "carrying a `sample` is refused with `422 usage-body-not-accepted` unless the source's "
        "body window is open."
    ),
    openapi_extra={
        "requestBody": _REQUEST_BODY,
        "parameters": [
            {
                "name": SOURCE_HEADER,
                "in": "header",
                "required": False,
                "schema": {"type": "string", "format": "uuid"},
                "description": "The usage source, when the body has no `source_id`.",
            }
        ],
    },
    responses={
        400: {"description": "Malformed batch, unknown encoding, or no source named."},
        403: {"description": "Not a workspace API key, or the source is disabled."},
        404: {"description": "Unknown source."},
        413: {"description": "Over 2 MiB or 5,000 events."},
        422: {"description": "`usage-body-not-accepted`: a sample was sent while the body window is closed."},
        429: {"description": "`usage-quota-exceeded`: over today's cap; `retryAt` says when it resets."},
    },
)
async def ingest_usage(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    content_encoding: Optional[str] = Header(None, alias="Content-Encoding", include_in_schema=False),
    source_header: Optional[str] = Header(None, alias=SOURCE_HEADER, include_in_schema=False),
) -> UsageIngestResponse:
    """Ingest one batch of usage events.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request (its body is read raw).
        auth_data: The authenticated principal — must be an API key.
        content_encoding: ``gzip`` or absent.
        source_header: The source id, when the body has none.

    Returns:
        The batch's ledger counts.

    Raises:
        HTTPException: See the route's documented responses.
    """
    if auth_data.get("auth_method") != "api_key":
        raise HTTPException(
            status_code=403,
            detail={
                "code": CODE_KEY_REQUIRED,
                "message": "usage ingest takes a workspace API key with the usage:ingest scope, not a session",
            },
        )
    tenant_id = str(auth_data.get("tenant_id") or "")
    now = datetime.now(timezone.utc)
    try:
        data = decode_body(await request.body(), content_encoding)
        body_source, raw_events = parse_batch(data)
        header_source = (source_header or "").strip() or None
        if header_source and body_source and header_source != body_source:
            raise UsageIngestError(
                400, CODE_BATCH_INVALID, f"the {SOURCE_HEADER} header and source_id name different sources"
            )
        source_ref = header_source or body_source
        if not source_ref:
            raise UsageIngestError(
                400, CODE_SOURCE_REQUIRED, f"name the usage source with the {SOURCE_HEADER} header or source_id"
            )
        outcome = ingest_batch(
            db,
            tenant_id=tenant_id,
            source_ref=source_ref,
            raw_events=raw_events,
            digest=batch_digest(data),
            api_key_id=str(auth_data.get("id") or "") or None,
            now=now,
        )
    except UsageIngestError as exc:
        raise _error(exc) from exc

    plan = outcome.plan
    return UsageIngestResponse(
        batch_id=outcome.batch_id,
        source_id=source_ref,
        received_at=outcome.received_at,
        received=plan.received,
        accepted=plan.accepted,
        sampled_out=plan.sampled_out,
        unmatched=plan.unmatched,
        rejected=plan.rejected,
        scrub_findings=plan.scrub_findings,
        basis=plan.basis,
        sampling_rate=plan.sampling_rate,
        samples=UsageIngestSamples(stored=len(plan.samples), dropped=plan.samples_dropped),
        rejections=[
            UsageIngestRejection(index=index, reason=reason)
            for index, reason in plan.rejections[:MAX_REJECTION_DETAILS]
        ],
        rejections_truncated=len(plan.rejections) > MAX_REJECTION_DETAILS,
    )
