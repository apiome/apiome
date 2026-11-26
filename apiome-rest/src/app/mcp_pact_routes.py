"""The Pact Broker for the MCP server — PFX-4.5 (#6942).

``apiome-mcp`` serves four pact tools — ``pact.list``, ``pact.matrix``, ``pact.can_i_deploy`` and
``pact.record_deployment`` — over the same broker the ``pact-broker`` CLI talks to. The matrix, the
can-i-deploy verdict and the deployment record live here, so the MCP server calls these internal routes
after it has authenticated the caller's MCP API key and checked its scope:

* ``POST /v1/internal/mcp/pacts/list`` — the latest pact of every integration (consumer → provider) of the
  tenant, newest consumer version per pair, with its latest verification result. Cursor-paginated by
  provider then consumer handle. No pact content: a row says which pact it is, not what it holds.
* ``POST /v1/internal/mcp/pacts/matrix`` — the matrix query of ``GET …/pact-broker/matrix``, from
  structured selectors instead of a ``q[][…]`` query string. The selectors are turned into that query
  string and read by the broker's own parser, so validation and semantics are identical.
* ``POST /v1/internal/mcp/pacts/can-i-deploy`` — ``GET …/pact-broker/can-i-deploy``: one pacticipant version
  to an environment or a tag.
* ``POST /v1/internal/mcp/pacts/record-deployment`` — ``pact-broker record-deployment``: the environment is
  named, not addressed by uuid.

**Bounded output.** The verdict is reached from every row the query reads, then at most ``maxRows`` rows
(default :data:`DEFAULT_MAX_ROWS`, at most :data:`MAX_ROWS`) and :data:`MAX_NOTICES` notices are returned,
with ``rowsTotal`` / ``rowsTruncated`` and ``noticesTruncated`` saying what was left out — nothing is cut
silently. Rows are compact: names, handles, version numbers, the verification and its reason; no HAL links.

**RBAC as the key's owner.** An MCP API key is minted by a person (``mcp_api_keys.created_by``). Every route
checks the ``pacts`` permission of that person in the key's tenant — ``pacts:view`` to read,
``pacts:create`` to record a deployment — through :func:`app.permissions.enforce_permission`, exactly as the
broker routes do. A key whose owner is gone (``created_by`` is null) is refused with
``mcp-pact-key-has-no-owner``: there is nobody whose role to apply, and no fallback is assumed.

All routes are **internal**: they trust the ``tenantId`` and ``keyId`` the MCP server sends, so they require
the shared ``X-Internal-Service-Token`` (``INTERNAL_SERVICE_TOKEN``) and are fail-closed without it. The key
is still re-read here (same tenant, not revoked, not expired) before its owner's role is applied.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth_provider_resolved_routes import require_internal_service
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import record_pact_write
from .pact_broker_routes import _http_error
from .pact_environment import DeployedVersionRecord, parse_application_instance
from .pact_environment_store import list_environments, record_deployment
from .pact_matrix import (
    LATEST_BY,
    RETRY_AFTER_SECONDS,
    MatrixRow,
    deployment_verdict,
    parse_can_i_deploy_query,
    parse_matrix_query,
    row_reason,
)
from .pact_matrix_store import query_matrix
from .pact_publication import PactPublicationError
from .pacticipant import PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string

__all__ = ["router"]

router = APIRouter(
    prefix="/v1/internal/mcp/pacts",
    tags=["internal-mcp-pacts"],
    dependencies=[Depends(require_internal_service)],
)

#: Matrix rows returned by default, and at most, per answer (the verdict always reads every row).
DEFAULT_MAX_ROWS = 50
MAX_ROWS = 100
#: Notices returned at most per answer.
MAX_NOTICES = 50
#: Pacts per ``list`` page by default, and at most.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100

CODE_KEY_UNKNOWN = "mcp-pact-key-unknown"
CODE_KEY_NO_OWNER = "mcp-pact-key-has-no-owner"
CODE_INVALID = "mcp-pact-invalid"
CODE_ENVIRONMENT_NOT_FOUND = "pact-environment-not-found"

_REFUSALS = (PactPublicationError, PacticipantValidationError)


# ---------------------------------------------------------------------------------------------
# Requests and answers
# ---------------------------------------------------------------------------------------------


class _McpPactRequest(BaseModel):
    """What every pact route receives: the authenticated key and its tenant."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tenant_id: str = Field(alias="tenantId", description="The MCP key's tenant (trusted: internal route).")
    key_id: str = Field(alias="keyId", description="The MCP key; its owner's `pacts` role is applied.")


class McpPactListRequest(_McpPactRequest):
    """``pact.list``: optional filters and a page."""

    provider: Optional[str] = Field(default=None, description="Only pacts for this provider (handle, id or name).")
    consumer: Optional[str] = Field(default=None, description="Only pacts of this consumer (handle, id or name).")
    limit: int = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Pacts per page.")
    cursor: Optional[str] = Field(default=None, description="`nextCursor` of the previous page.")


class McpPactSelector(BaseModel):
    """One matrix selector: a pacticipant and which of its versions."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    pacticipant: str = Field(description="The pacticipant's name, handle or id.")
    version: Optional[str] = Field(default=None, description="Exactly this version.")
    latest: Optional[bool] = Field(default=None, description="Only the latest of the versions described.")
    tag: Optional[str] = Field(default=None, description="Versions with this tag.")
    branch: Optional[str] = Field(default=None, description="Versions recorded on this branch.")
    environment: Optional[str] = Field(default=None, description="Versions currently in this environment.")
    main_branch: Optional[bool] = Field(
        default=None, alias="mainBranch", description="Versions on the pacticipant's main branch."
    )


class McpPactIgnore(BaseModel):
    """A pacticipant (or one of its versions) whose rows do not count."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    pacticipant: str = Field(description="The pacticipant to ignore.")
    version: Optional[str] = Field(default=None, description="Only this version of it.")


class McpPactMatrixRequest(_McpPactRequest):
    """``pact.matrix``: the selectors and options of a broker matrix query."""

    selectors: List[McpPactSelector] = Field(description="The versions in question (1 or more).")
    latestby: Optional[Literal["cvp", "cvpv", "cp"]] = Field(default=None, description="How rows collapse.")
    to_environment: Optional[str] = Field(
        default=None, alias="toEnvironment", description="Destination: everything in this environment."
    )
    to_tag: Optional[str] = Field(
        default=None, alias="toTag", description="Destination: the latest version with this tag."
    )
    latest: Optional[bool] = Field(default=None, description="Destination: each other pacticipant's latest.")
    main_branch: Optional[bool] = Field(
        default=None, alias="mainBranch", description="Destination: each other pacticipant's main branch."
    )
    ignore: List[McpPactIgnore] = Field(default_factory=list, description="Rows that do not count.")
    limit: Optional[int] = Field(default=None, ge=1, le=1000, description="The most rows the query reads.")
    max_rows: int = Field(
        default=DEFAULT_MAX_ROWS,
        alias="maxRows",
        ge=1,
        le=MAX_ROWS,
        description="The most rows returned (the verdict reads them all).",
    )


class McpPactCanIDeployRequest(_McpPactRequest):
    """``pact.can_i_deploy``: one version to an environment or a tag."""

    pacticipant: str = Field(description="What is being deployed.")
    version: str = Field(description="Its version number, exactly as recorded.")
    to_environment: Optional[str] = Field(default=None, alias="toEnvironment", description="Where it goes.")
    to_tag: Optional[str] = Field(default=None, alias="toTag", description="Or: the tag it is checked against.")
    ignore: List[McpPactIgnore] = Field(default_factory=list, description="Rows that do not count.")
    max_rows: int = Field(
        default=DEFAULT_MAX_ROWS,
        alias="maxRows",
        ge=1,
        le=MAX_ROWS,
        description="The most rows returned (the verdict reads them all).",
    )


class McpPactRecordDeploymentRequest(_McpPactRequest):
    """``pact.record_deployment``: a version is now deployed to a named environment."""

    pacticipant: str = Field(description="The deployed pacticipant.")
    version: str = Field(description="The deployed version number, exactly as recorded.")
    environment: str = Field(description="The environment's name (as `pact-broker record-deployment --environment`).")
    application_instance: Optional[str] = Field(
        default=None, alias="applicationInstance", description="The instance deployed to; omit for the only one."
    )


class McpPactListResponse(BaseModel):
    """One page of pacts."""

    model_config = ConfigDict(populate_by_name=True)

    items: List[Dict[str, Any]]
    has_more: bool = Field(serialization_alias="hasMore")
    next_cursor: Optional[str] = Field(default=None, serialization_alias="nextCursor")


class McpPactMatrixResponse(BaseModel):
    """The verdict and a bounded set of the rows it was reached from."""

    model_config = ConfigDict(populate_by_name=True)

    summary: Dict[str, Any]
    notices: List[Dict[str, Any]]
    notices_truncated: bool = Field(serialization_alias="noticesTruncated")
    rows: List[Dict[str, Any]]
    rows_total: int = Field(serialization_alias="rowsTotal")
    rows_truncated: bool = Field(serialization_alias="rowsTruncated")
    retry_after_seconds: Optional[int] = Field(default=None, serialization_alias="retryAfterSeconds")


class McpPactDeploymentResponse(BaseModel):
    """The recorded deployment."""

    model_config = ConfigDict(populate_by_name=True)

    created: bool = Field(description="False when this version already was the current deployment there.")
    deployment: Dict[str, Any]


# ---------------------------------------------------------------------------------------------
# The key and its owner
# ---------------------------------------------------------------------------------------------


def _refuse(status: int, code: str, message: str) -> HTTPException:
    """An ``HTTPException`` with Apiome's ``{"code", "message"}`` detail."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def key_auth_data(tenant_id: str, key_id: str) -> Dict[str, Any]:
    """The auth context of an MCP key: its tenant, acting as the person who minted it.

    Args:
        tenant_id: The tenant the MCP server authenticated the key for.
        key_id: The key's id.

    Returns:
        ``{"tenant_id", "user_id", "auth_method": "api_key", "user_name"}`` — what
        :func:`app.permissions.enforce_permission` and :func:`app.consumer_contract_store.actor_from_auth`
        read.

    Raises:
        HTTPException: 403 ``mcp-pact-key-unknown`` for a key that is not the tenant's, revoked or expired;
            403 ``mcp-pact-key-has-no-owner`` when the person who minted it is gone.
    """
    if not is_uuid_string(tenant_id) or not is_uuid_string(key_id):
        raise _refuse(403, CODE_KEY_UNKNOWN, "The MCP API key is not one of this workspace's keys.")
    rows = db.execute_query(
        """
        SELECT created_by::text AS created_by, label
        FROM apiome.mcp_api_keys
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        """,
        (key_id, tenant_id),
    )
    if not rows:
        raise _refuse(403, CODE_KEY_UNKNOWN, "The MCP API key is not one of this workspace's live keys.")
    row = dict(rows[0])
    if not row.get("created_by"):
        raise _refuse(
            403,
            CODE_KEY_NO_OWNER,
            "This MCP API key has no owner (the person who created it was removed), so no role applies to it. "
            "Create a new MCP API key to use the pact tools.",
        )
    return {
        "tenant_id": tenant_id,
        "user_id": row["created_by"],
        "auth_method": "api_key",
        "user_name": f"MCP key {row.get('label') or key_id}",
    }


# ---------------------------------------------------------------------------------------------
# pact.list
# ---------------------------------------------------------------------------------------------

#: The latest publication of every (consumer, provider) pair, with that pact's latest verification.
_LIST_SQL = """
    WITH latest AS (
        SELECT DISTINCT ON (p.consumer_id, p.provider_id)
               p.consumer_id, p.provider_id, p.pact_version_id, p.revision, p.created_at, p.updated_at,
               v.number AS consumer_version
        FROM apiome.pact_publication p
        JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
        JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
        WHERE pv.tenant_id = %(tenant)s::uuid AND v.deleted_at IS NULL
          AND (%(provider)s::uuid IS NULL OR p.provider_id = %(provider)s::uuid)
          AND (%(consumer)s::uuid IS NULL OR p.consumer_id = %(consumer)s::uuid)
        ORDER BY p.consumer_id, p.provider_id, v.seq DESC
    )
    SELECT c.slug AS consumer_slug, c.name AS consumer_name,
           pr.slug AS provider_slug, pr.name AS provider_name,
           l.consumer_version, pv.sha, pv.specification_version, pv.interaction_count,
           l.revision, l.created_at, l.updated_at,
           vr.success AS verification_success, vr.created_at AS verified_at, vr.kind AS verification_kind,
           prv.number AS verified_provider_version
    FROM latest l
    JOIN apiome.pact_version pv ON pv.id = l.pact_version_id
    JOIN apiome.pacticipant c ON c.id = l.consumer_id
    JOIN apiome.pacticipant pr ON pr.id = l.provider_id
    LEFT JOIN LATERAL (
        SELECT r.success, r.created_at, r.kind, r.provider_version_id
        FROM apiome.verification_result r
        WHERE r.pact_version_id = l.pact_version_id AND r.consumer_id = l.consumer_id
          AND r.provider_id = l.provider_id
        ORDER BY r.seq DESC
        LIMIT 1
    ) vr ON TRUE
    LEFT JOIN apiome.pacticipant_version prv ON prv.id = vr.provider_version_id
    WHERE c.deleted_at IS NULL AND pr.deleted_at IS NULL
      AND (%(after_provider)s::text IS NULL OR (pr.slug, c.slug) > (%(after_provider)s::text, %(after_consumer)s::text))
    ORDER BY pr.slug, c.slug
    LIMIT %(limit)s
"""


def encode_list_cursor(provider_slug: str, consumer_slug: str) -> str:
    """The opaque cursor after one pact row (its provider and consumer handles)."""
    raw = json.dumps({"p": provider_slug, "c": consumer_slug}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_list_cursor(cursor: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Read a ``pact.list`` cursor.

    Args:
        cursor: ``nextCursor`` of a previous page, or ``None`` for the first page.

    Returns:
        The provider and consumer handles of the last row of that page, or ``(None, None)``.

    Raises:
        HTTPException: 400 ``mcp-pact-invalid`` for a cursor this route did not issue.
    """
    if not cursor:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        provider, consumer = data["p"], data["c"]
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise _refuse(400, CODE_INVALID, "The cursor is not one this tool issued; start again without it.") from exc
    if not isinstance(provider, str) or not isinstance(consumer, str):
        raise _refuse(400, CODE_INVALID, "The cursor is not one this tool issued; start again without it.")
    return provider, consumer


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text, or ``None``."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _pact_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """One ``pact.list`` row: which pact, and how its latest verification went."""
    verification = None
    if row.get("verification_success") is not None:
        verification = {
            "success": bool(row["verification_success"]),
            "verifiedAt": _iso(row.get("verified_at")),
            "providerVersion": row.get("verified_provider_version"),
            "kind": row.get("verification_kind") or "native",
        }
    return {
        "consumer": {"name": row["consumer_name"], "slug": row["consumer_slug"]},
        "provider": {"name": row["provider_name"], "slug": row["provider_slug"]},
        "consumerVersion": row["consumer_version"],
        "sha": row["sha"],
        "specificationVersion": row.get("specification_version"),
        "interactionCount": row.get("interaction_count"),
        "revision": row.get("revision"),
        "publishedAt": _iso(row.get("created_at")),
        "updatedAt": _iso(row.get("updated_at")),
        "latestVerification": verification,
    }


def list_latest_pacts(body: McpPactListRequest) -> McpPactListResponse:
    """The latest pact of every integration of the tenant, one page.

    Args:
        body: The key, filters and page.

    Returns:
        The page, with ``nextCursor`` while more follow.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 ``pacticipant-not-found`` for an unknown filter;
            400 for a bad cursor.
    """
    auth_data = key_auth_data(body.tenant_id, body.key_id)
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    after_provider, after_consumer = decode_list_cursor(body.cursor)
    try:
        provider_id = get_pacticipant(db, body.tenant_id, body.provider).id if body.provider else None
        consumer_id = get_pacticipant(db, body.tenant_id, body.consumer).id if body.consumer else None
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    rows = (
        db.execute_query(
            _LIST_SQL,
            {
                "tenant": body.tenant_id,
                "provider": provider_id,
                "consumer": consumer_id,
                "after_provider": after_provider,
                "after_consumer": after_consumer,
                "limit": body.limit + 1,
            },
        )
        or []
    )
    rows = [dict(row) for row in rows]
    has_more = len(rows) > body.limit
    page = rows[: body.limit]
    cursor = encode_list_cursor(page[-1]["provider_slug"], page[-1]["consumer_slug"]) if has_more and page else None
    return McpPactListResponse(items=[_pact_item(row) for row in page], has_more=has_more, next_cursor=cursor)


# ---------------------------------------------------------------------------------------------
# pact.matrix / pact.can_i_deploy
# ---------------------------------------------------------------------------------------------


def _flag(value: Optional[bool]) -> Optional[str]:
    """A boolean query value as the broker spells it, or ``None`` to leave it out."""
    return None if value is None else ("true" if value else "false")


def matrix_query_string(body: McpPactMatrixRequest) -> str:
    """The ``GET …/matrix`` query string the structured request stands for.

    Args:
        body: The selectors and options.

    Returns:
        The percent-encoded ``q[][…]`` query, for :func:`app.pact_matrix.parse_matrix_query`.
    """
    pairs: List[Tuple[str, str]] = []
    for selector in body.selectors:
        pairs.append(("q[][pacticipant]", selector.pacticipant))
        for key, value in (
            ("version", selector.version),
            ("latest", _flag(selector.latest)),
            ("tag", selector.tag),
            ("branch", selector.branch),
            ("environment", selector.environment),
            ("mainBranch", _flag(selector.main_branch)),
        ):
            if value is not None:
                pairs.append((f"q[][{key}]", value))
    for key, value in (
        ("latestby", body.latestby),
        ("environment", body.to_environment),
        ("tag", body.to_tag),
        ("latest", _flag(body.latest)),
        ("mainBranch", _flag(body.main_branch)),
        ("limit", str(body.limit) if body.limit is not None else None),
    ):
        if value is not None:
            pairs.append((key, value))
    pairs += _ignore_pairs(body.ignore)
    return urlencode(pairs)


def _ignore_pairs(ignore: Sequence[McpPactIgnore]) -> List[Tuple[str, str]]:
    """``ignore[][pacticipant]`` (and ``ignore[][version]``) pairs."""
    pairs: List[Tuple[str, str]] = []
    for entry in ignore:
        pairs.append(("ignore[][pacticipant]", entry.pacticipant))
        if entry.version is not None:
            pairs.append(("ignore[][version]", entry.version))
    return pairs


def can_i_deploy_query_string(body: McpPactCanIDeployRequest) -> str:
    """The ``GET …/can-i-deploy`` query string the structured request stands for."""
    pairs: List[Tuple[str, str]] = [("pacticipant", body.pacticipant), ("version", body.version)]
    if body.to_environment is not None:
        pairs.append(("toEnvironment", body.to_environment))
    if body.to_tag is not None:
        pairs.append(("to", body.to_tag))
    pairs += _ignore_pairs(body.ignore)
    return urlencode(pairs)


def compact_row(row: MatrixRow, ignored: bool) -> Dict[str, Any]:
    """One matrix row, compact: who, which versions, the verification and why it counts as it does.

    Args:
        row: The row.
        ignored: Whether an ``ignore`` covered it.

    Returns:
        ``consumer`` / ``provider`` (name, slug, version), ``pact`` (sha, createdAt), ``verification``
        (``null`` without a result), ``reason`` and ``ignored``.
    """
    verification = None
    if row.success is not None:
        verification = {
            "success": row.success,
            "verifiedAt": row.verified_at,
            "number": row.verification_number,
            "kind": row.verification_kind or "native",
        }
        if row.pact_pending is not None:
            verification["pending"] = row.pact_pending
        if row.wip:
            verification["wip"] = True
    return {
        "consumer": {"name": row.consumer_name, "slug": row.consumer_slug, "version": row.consumer_version_number},
        "provider": {"name": row.provider_name, "slug": row.provider_slug, "version": row.provider_version_number},
        "pact": {"sha": row.pact_sha, "createdAt": row.pact_created_at},
        "verification": verification,
        "reason": row_reason(row),
        "ignored": ignored,
    }


def answer_matrix(
    tenant_id: str, auth_data: Dict[str, Any], query: str, parse: Any, max_rows: int
) -> McpPactMatrixResponse:
    """Run one matrix query and bound its answer; shared by ``matrix`` and ``can-i-deploy``.

    Args:
        tenant_id: The key's tenant.
        auth_data: The key's auth context (:func:`key_auth_data`).
        query: The broker query string.
        parse: :func:`parse_matrix_query` or :func:`parse_can_i_deploy_query`.
        max_rows: The most rows to return.

    Returns:
        The verdict, the notices (at most :data:`MAX_NOTICES`) and at most ``max_rows`` rows (considered
        rows first, then ignored ones), with what was left out counted.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 ``pact-matrix-invalid``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        selectors, options = parse(query)
        result = query_matrix(db, tenant_id, selectors, options)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    verdict = deployment_verdict(result)
    rows = [compact_row(row, False) for row in result.considered_rows]
    rows += [compact_row(row, True) for row in result.ignored_rows]
    notices = [{"type": r.type, "code": r.code, "text": r.text} for r in verdict.reasons]
    return McpPactMatrixResponse(
        summary={"deployable": verdict.deployable, "reason": verdict.reason, **verdict.counts},
        notices=notices[:MAX_NOTICES],
        notices_truncated=len(notices) > MAX_NOTICES,
        rows=rows[:max_rows],
        rows_total=len(rows),
        rows_truncated=len(rows) > max_rows,
        retry_after_seconds=RETRY_AFTER_SECONDS if verdict.unknown else None,
    )


# ---------------------------------------------------------------------------------------------
# pact.record_deployment
# ---------------------------------------------------------------------------------------------


def deployment_document(deployed: DeployedVersionRecord) -> Dict[str, Any]:
    """A recorded deployment, compact."""
    environment = deployed.environment
    return {
        "uuid": deployed.id,
        "pacticipant": {"name": deployed.pacticipant_name, "slug": deployed.pacticipant_slug},
        "version": deployed.version_number,
        "environment": {
            "uuid": environment.id,
            "name": environment.name,
            "displayName": environment.display_name,
            "production": environment.production,
        },
        "applicationInstance": deployed.application_instance,
        "currentlyDeployed": deployed.currently_deployed,
        "createdAt": deployed.created_at,
    }


def record_mcp_deployment(body: McpPactRecordDeploymentRequest) -> McpPactDeploymentResponse:
    """Record that a version is now deployed to a named environment.

    Args:
        body: The key, the version and the environment's name.

    Returns:
        The deployment, and whether this call created it.

    Raises:
        HTTPException: 403 without ``pacts:create``; 404 for an unknown pacticipant, version or environment;
            422 ``pact-deployment-invalid`` for a malformed application instance.
    """
    auth_data = key_auth_data(body.tenant_id, body.key_id)
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=body.pacticipant)
    name = (body.environment or "").strip()
    if not name:
        raise _refuse(400, CODE_INVALID, "Name the environment to record the deployment in.")
    environments = [e for e in list_environments(db, body.tenant_id, name=name) if e.name == name]
    if not environments:
        raise _refuse(
            404,
            CODE_ENVIRONMENT_NOT_FOUND,
            f"No environment named '{name}'. Create it first (`apiome pact create-environment`).",
        )
    try:
        instance = parse_application_instance(
            json.dumps({"applicationInstance": body.application_instance}).encode()
            if body.application_instance is not None
            else b""
        )
        deployed, created = record_deployment(
            db,
            body.tenant_id,
            body.pacticipant,
            body.version,
            environments[0].id,
            instance,
            actor=actor_from_auth(auth_data, user_id),
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    record_pact_write(
        db,
        auth_data,
        "pacts.deployment.record",
        f"pacticipant/{body.pacticipant}/version/{body.version}/environment/{environments[0].id}",
        {"route": "record_mcp_deployment", "via": "mcp", "created": created},
    )
    return McpPactDeploymentResponse(created=created, deployment=deployment_document(deployed))


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------

_ERRORS: Dict[Any, Any] = {
    400: {"description": "`pact-matrix-invalid` or `mcp-pact-invalid`: the request cannot be answered as sent."},
    403: {"description": "`mcp-pact-key-unknown`, `mcp-pact-key-has-no-owner`, or the key's owner lacks `pacts`."},
    404: {"description": "`pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`."},
}


@router.post(
    "/list",
    response_model=McpPactListResponse,
    response_model_by_alias=True,
    summary="Latest pacts for the MCP `pact.list` tool",
    description="Internal (`X-Internal-Service-Token`). The latest pact of every consumer → provider integration of "
    "the tenant, with its latest verification result; optional `provider` / `consumer` filters; cursor-paginated. "
    "Requires the key owner's `pacts:view`.",
    responses=_ERRORS,
)
async def mcp_pact_list(body: McpPactListRequest) -> McpPactListResponse:
    """List the latest pacts.

    Args:
        body: The key, filters and page.

    Returns:
        One page of pacts.
    """
    return await asyncio.to_thread(list_latest_pacts, body)


@router.post(
    "/matrix",
    response_model=McpPactMatrixResponse,
    response_model_by_alias=True,
    summary="Matrix query for the MCP `pact.matrix` tool",
    description="Internal (`X-Internal-Service-Token`). `GET …/pact-broker/matrix` from structured selectors: the "
    "verdict (`summary.deployable` true / false / null), its notices and at most `maxRows` compact rows, with "
    f"`rowsTotal` and `rowsTruncated`. `latestby` is one of {', '.join(LATEST_BY)}. Requires the key owner's "
    "`pacts:view`.",
    responses=_ERRORS,
)
async def mcp_pact_matrix(body: McpPactMatrixRequest) -> McpPactMatrixResponse:
    """Answer a matrix query.

    Args:
        body: The key, selectors and options.

    Returns:
        The verdict and a bounded set of rows.
    """

    def run() -> McpPactMatrixResponse:
        auth_data = key_auth_data(body.tenant_id, body.key_id)
        return answer_matrix(body.tenant_id, auth_data, matrix_query_string(body), parse_matrix_query, body.max_rows)

    return await asyncio.to_thread(run)


@router.post(
    "/can-i-deploy",
    response_model=McpPactMatrixResponse,
    response_model_by_alias=True,
    summary="Can I deploy? for the MCP `pact.can_i_deploy` tool",
    description="Internal (`X-Internal-Service-Token`). `GET …/pact-broker/can-i-deploy`: one pacticipant version to "
    "`toEnvironment` or `toTag` (exactly one). The same bounded answer as the matrix route; `retryAfterSeconds` is "
    "set while the verdict is unknown. Requires the key owner's `pacts:view`.",
    responses=_ERRORS,
)
async def mcp_pact_can_i_deploy(body: McpPactCanIDeployRequest) -> McpPactMatrixResponse:
    """Answer "can this version be deployed there?".

    Args:
        body: The key, the version and the destination.

    Returns:
        The verdict and a bounded set of rows.
    """

    def run() -> McpPactMatrixResponse:
        auth_data = key_auth_data(body.tenant_id, body.key_id)
        return answer_matrix(
            body.tenant_id, auth_data, can_i_deploy_query_string(body), parse_can_i_deploy_query, body.max_rows
        )

    return await asyncio.to_thread(run)


@router.post(
    "/record-deployment",
    response_model=McpPactDeploymentResponse,
    response_model_by_alias=True,
    summary="Record a deployment for the MCP `pact.record_deployment` tool",
    description="Internal (`X-Internal-Service-Token`). `pact-broker record-deployment`: the version is now deployed "
    "to the named environment (and application instance); the previous deployment there is marked undeployed. "
    "`created: false` when it already was the current deployment. Requires the key owner's `pacts:create`.",
    responses={**_ERRORS, 422: {"description": "`pact-deployment-invalid`: a malformed application instance."}},
)
async def mcp_pact_record_deployment(body: McpPactRecordDeploymentRequest) -> McpPactDeploymentResponse:
    """Record a deployment.

    Args:
        body: The key, the version and the environment.

    Returns:
        The deployment.
    """
    return await asyncio.to_thread(record_mcp_deployment, body)
