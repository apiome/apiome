"""``/v1/tenants/{tenant_slug}/pact-migration`` — importing a Pact Broker / PactFlow workspace, PFX-6.7 (#6959).

The HTTP face of :mod:`app.pact_migration_store`, which ``apiome pact migrate`` calls with what it
read from the source broker. Outside ``…/pact-broker``, because no Pact Broker client knows it:

* ``POST …/pact-migration/import`` — write a batch of up to 100 records (pacticipants, versions,
  pacts, verification results, environments, deployments, releases, webhooks), each in its own
  transaction, keeping the source's timestamps; importing a record again changes nothing;
* ``POST …/pact-migration/check`` — the dry run: read the batch the same way and say, per record,
  whether it already exists or would be created; nothing is written.

Every record is answered (``created``, ``updated``, ``unchanged``, ``refused`` — or ``exists`` /
``would-create`` for a check); a refused one carries a code and the reason, so nothing is dropped
silently. Only a malformed envelope refuses the request (``422 pact-migration-invalid``).

**Permissions.** An import needs ``pacts:create`` and ``pacts:edit`` (it adds labels and fills in a
repository or main branch); it appends one ``access_audit`` row (``pacts.migration.import``) per
request. A check needs ``pacts:view``. Every write and lookup is scoped to the authenticated tenant.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .config import settings
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _body_reader
from .pact_migration import (
    KINDS,
    MAX_RECORDS,
    MigrationReport,
    count_outcomes,
    parse_import_request,
)
from .pact_migration_store import check_records, import_records
from .pact_publication import PactPublicationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_BASE = "/{tenant_slug}/pact-migration"

#: A batch may carry several pacts, so it is read up to twice the single-pact limit.
_read_batch = _body_reader(2)

_RECORD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "created_at": {
            "type": "string",
            "format": "date-time",
            "description": "When the source recorded it; kept on the rows the import creates.",
        },
    },
    "additionalProperties": True,
    "description": (
        "`pacticipant` (`name`, `repository_url`, `main_branch`, `labels`), `version` (`pacticipant`, "
        "`number`, `build_url`, `branches`, `tags` — strings or `{name, created_at}`), `pact` (`consumer`, "
        "`provider`, `consumer_version`, `content` — the Pact), `verification` (`consumer`, `provider`, "
        "`consumer_version`, `number`, `result` — the Pact Broker verification body), `environment` "
        "(`name`, `display_name`, `production`, `contacts`), `deployment` (`pacticipant`, `version`, "
        "`environment`, `application_instance`), `release` (`pacticipant`, `version`, `environment`), "
        "`webhook` (`uuid`, `webhook` — the Pact Broker webhook body)."
    ),
}

_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["records"],
                "properties": {
                    "source": {"type": "string", "maxLength": 2048, "description": "The source broker's URL."},
                    "records": {"type": "array", "minItems": 1, "maxItems": MAX_RECORDS, "items": _RECORD_SCHEMA},
                },
            },
            "example": {
                "source": "https://broker.example.com",
                "records": [
                    {
                        "kind": "pacticipant",
                        "name": "Billing Service",
                        "main_branch": "main",
                        "labels": ["team-billing"],
                        "created_at": "2025-03-01T09:30:00Z",
                    },
                    {
                        "kind": "version",
                        "pacticipant": "Billing Service",
                        "number": "4f2a9c1",
                        "branches": ["main"],
                        "tags": [{"name": "prod", "created_at": "2025-03-02T10:00:00Z"}],
                        "created_at": "2025-03-01T09:31:00Z",
                    },
                ],
            },
        }
    },
}

_INVALID = {
    422: {
        "description": (
            '`pact-migration-invalid`: the body is not `{"records": [...]}` or holds more than '
            f"{MAX_RECORDS} records. A malformed *record* is answered `refused` instead."
        )
    },
    413: {"description": "`pact-too-large`: the batch is over twice the pact size limit; send fewer records."},
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _parse(raw: bytes) -> Any:
    """Read the batch, or a 422 naming the problem with the envelope."""
    try:
        return parse_import_request(raw, max_pact_bytes=settings.pact_max_bytes)
    except PactPublicationError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc), "pointer": exc.pointer or ""}
        ) from exc


@router.post(
    _BASE + "/import",
    response_model=MigrationReport,
    summary="Import records from a Pact Broker or PactFlow",
    description=(
        "Write a batch of records read from another Pact Broker (PFX-6.7, what `apiome pact migrate` "
        f"sends): up to {MAX_RECORDS} pacticipants, versions, pacts, verification results, environments, "
        "deployments, releases and webhooks. Each record is written in its own transaction with the "
        "source's `created_at`; importing it again changes nothing (`unchanged`), and what it adds to an "
        "existing row — a label, a tag, a branch — is `updated`. Each record is answered in order; a "
        "refused one carries `code` and `message` (`pact-migration-reference-missing` for a result whose "
        "pact or a deployment whose environment is not there yet, `pact-migration-conflict` for a pact "
        "or deployment Apiome already records differently, or the Pact rule it breaks). An import fires "
        "no webhooks, commit statuses or notifications. Requires `pacts:create` and `pacts:edit`."
    ),
    openapi_extra={"requestBody": _BODY},
    responses=_INVALID,
)
@audited_write("pacts.migration.import", "pact-migration")
def post_migration_import(
    tenant_slug: str,
    raw: bytes = Depends(_read_batch),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> MigrationReport:
    """Import a batch.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every write).
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        One outcome per record and the counts.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target="pact-migration")
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-migration")
    _ = tenant_slug
    request = _parse(raw)
    results = import_records(db, _tenant_id(auth_data), request, actor=actor_from_auth(auth_data, user_id))
    return MigrationReport(dry_run=False, results=results, counts=count_outcomes(results))


@router.post(
    _BASE + "/check",
    response_model=MigrationReport,
    summary="Check records from a Pact Broker or PactFlow (dry run)",
    description=(
        "Read a batch exactly as the import does and answer, per record, `exists`, `would-create` or "
        "`refused` (with the reason) — the dry run of `apiome pact migrate`. Nothing is written. "
        "References between records (the pact a result verifies, the environment a deployment names) "
        "are not checked, since an earlier batch of the same migration may create them. Requires "
        "`pacts:view`."
    ),
    openapi_extra={"requestBody": _BODY},
    responses=_INVALID,
)
def post_migration_check(
    tenant_slug: str,
    raw: bytes = Depends(_read_batch),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> MigrationReport:
    """Check a batch without writing it.

    Args:
        tenant_slug: The tenant in the URL.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        One outcome per record and the counts.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-migration")
    _ = tenant_slug
    results = check_records(db, _tenant_id(auth_data), _parse(raw))
    return MigrationReport(dry_run=True, results=results, counts=count_outcomes(results))
