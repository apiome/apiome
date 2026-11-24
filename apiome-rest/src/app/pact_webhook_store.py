"""Persistence for contract webhooks and their firings — PFX-1.9 (#6922).

:mod:`app.pact_webhook` says what a webhook *is*; this module is the only place one is read or
written (apiome-db V436).

**Secrets are sealed on the way in and opened in one place.** :func:`create_webhook` and
:func:`replace_webhook` seal the password, the secret headers and the signing secret
(:mod:`app.pact_webhook_secrets`) and store only the ciphertext and the *names* of what is sealed.
Every read returns a :class:`~app.pact_webhook.WebhookRecord`, which has no field a secret could
be in. The only function that opens them is :func:`load_for_delivery`, for the sender.

**A firing is a queued delivery.** :func:`enqueue_triggered_webhook` writes a
``push_webhook_delivery_events`` row (the queue every outbound webhook uses, so retries and
dead-lettering are shared) and a ``pact_triggered_webhook`` row saying what caused it. The payload
of the queued row holds the template parameters — names, version numbers and URLs — and never a
secret.

**Everything starts from the caller's tenant.** A webhook, a firing and a log are read by
``tenant_id``; an id from another tenant reads as not found.

Every function takes the :class:`~app.database.Database` (or the open cursor) it runs on, so the
live-database tests can pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from psycopg2.extras import Json
from pydantic import BaseModel, ConfigDict, Field

from .config import WEBHOOK_MAX_DELIVERY_ATTEMPTS
from .consumer_contract_store import ConsumerActor
from .pact_publication import PactPublicationError
from .pact_webhook import (
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_LIMIT,
    CODE_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_SECRETS_UNAVAILABLE,
    MAX_WEBHOOKS_PER_TENANT,
    REDACTED,
    SECRET_PASSWORD,
    SECRET_SIGNING,
    WebhookInput,
    WebhookRecord,
    header_secret_field,
    request_description,
)
from .pact_webhook_secrets import (
    KEYS_SETTING,
    WebhookSecretError,
    seal_webhook_secrets,
    unseal_webhook_secrets,
)
from .pacticipant import PacticipantRecord, PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .revision_deprecation import is_uuid_string

__all__ = [
    "ANY_SCOPE",
    "DeliveryWebhook",
    "TriggeredWebhookLogs",
    "TriggeredWebhookRecord",
    "create_webhook",
    "delete_webhook",
    "enqueue_triggered_webhook",
    "find_webhooks_to_trigger",
    "get_triggered_webhook_logs",
    "get_webhook",
    "list_triggered_webhooks",
    "list_webhooks",
    "load_for_delivery",
    "replace_webhook",
    "triggered_status",
]

#: "Every webhook of the workspace" — distinct from ``(None, None)``, the webhooks for all pacts.
ANY_SCOPE: Any = object()

#: The prefix of a contract webhook's event type in the delivery queue (``pact.contract_published``).
EVENT_TYPE_PREFIX = "pact."

_WEBHOOK_SELECT = """
    SELECT w.id::text AS id, w.description, w.enabled, w.events, w.target_kind, w.target_config,
           w.request_method, w.request_url, w.request_headers, w.request_body, w.request_username,
           w.secret_fields, w.secret_ciphertext, w.key_version, w.created_at, w.updated_at,
           c.name AS consumer_name, c.slug AS consumer_slug,
           pr.name AS provider_name, pr.slug AS provider_slug
    FROM apiome.pact_webhook w
    LEFT JOIN apiome.pacticipant c ON c.id = w.consumer_id AND c.tenant_id = w.tenant_id
    LEFT JOIN apiome.pacticipant pr ON pr.id = w.provider_id AND pr.tenant_id = w.tenant_id
    WHERE w.tenant_id = %s::uuid
"""

_TRIGGERED_SELECT = """
    SELECT t.id::text AS id, t.webhook_id::text AS webhook_id, t.event_name, t.trigger_type,
           t.consumer_version_number, t.pact_version_sha, t.verification_number, t.created_at,
           w.request_method, w.request_url,
           e.id::text AS delivery_event_id, e.status::text AS delivery_status, e.attempt_count,
           c.name AS consumer_name, c.slug AS consumer_slug,
           pr.name AS provider_name, pr.slug AS provider_slug
    FROM apiome.pact_triggered_webhook t
    JOIN apiome.pact_webhook w ON w.id = t.webhook_id AND w.tenant_id = t.tenant_id
    JOIN apiome.push_webhook_delivery_events e ON e.id = t.delivery_event_id
    JOIN apiome.pacticipant c ON c.id = t.consumer_id AND c.tenant_id = t.tenant_id
    JOIN apiome.pacticipant pr ON pr.id = t.provider_id AND pr.tenant_id = t.tenant_id
    WHERE t.tenant_id = %s::uuid
"""


class DeliveryWebhook(BaseModel):
    """A webhook as the sender needs it: the record and its opened secrets.

    Attributes:
        record: The stored webhook.
        secrets: ``{"password", "signingSecret", "headers"}``; ``{}`` when the webhook has none;
            ``None`` when it has some and they cannot be opened.
    """

    model_config = ConfigDict(extra="forbid")

    record: WebhookRecord
    secrets: Optional[Dict[str, Any]] = None


class TriggeredWebhookRecord(BaseModel):
    """One firing of a webhook, with the state of its delivery.

    Attributes:
        id: The firing's ``uuid``.
        webhook_id: The webhook that fired.
        name: The request, as ``POST host``.
        status: ``not_run``, ``retrying``, ``success`` or ``failure``.
        attempts_made: How many requests were sent.
        attempts_remaining: How many more will be, before it is dead-lettered.
        trigger_type: ``resource_creation`` or ``user``.
        event_name: The event that fired it.
        consumer_name: The pact's consumer.
        consumer_slug: Its handle.
        provider_name: The pact's provider.
        provider_slug: Its handle.
        consumer_version_number: The consumer version of the pact.
        sha: The pact version.
        verification_number: The verification result that caused it, if any.
        triggered_at: When it fired.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    webhook_id: str
    name: str
    status: str
    attempts_made: int = 0
    attempts_remaining: int = 0
    trigger_type: str = "resource_creation"
    event_name: str
    consumer_name: str
    consumer_slug: str
    provider_name: str
    provider_slug: str
    consumer_version_number: Optional[str] = None
    sha: Optional[str] = None
    verification_number: Optional[int] = None
    triggered_at: Optional[str] = None


class TriggeredWebhookLogs(BaseModel):
    """The execution log of one firing: one entry per attempt.

    Attributes:
        triggered: The firing.
        executions: ``[{"success", "logs", "createdAt", "attempt", "status"}]``, oldest first.
    """

    model_config = ConfigDict(extra="forbid")

    triggered: TriggeredWebhookRecord
    executions: List[Dict[str, Any]] = Field(default_factory=list)


def triggered_status(delivery_status: str, attempt_count: int) -> str:
    """Translate a delivery's queue state into the Pact Broker's triggered-webhook status.

    Args:
        delivery_status: ``pending``, ``processing``, ``retrying``, ``delivered`` or ``dead_letter``.
        attempt_count: Attempts made so far.

    Returns:
        ``success``, ``failure`` (dead-lettered), ``retrying`` (failed at least once, will be
        sent again) or ``not_run``.
    """
    if delivery_status == "delivered":
        return "success"
    if delivery_status == "dead_letter":
        return "failure"
    if delivery_status == "retrying" or attempt_count > 0:
        return "retrying"
    return "not_run"


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else (str(value) if value is not None else None)


def _record(row: Mapping[str, Any]) -> WebhookRecord:
    """Adapt a :data:`_WEBHOOK_SELECT` row into its record (the sealed columns are left behind)."""
    return WebhookRecord(
        id=str(row["id"]),
        description=row.get("description"),
        consumer_name=row.get("consumer_name"),
        consumer_slug=row.get("consumer_slug"),
        provider_name=row.get("provider_name"),
        provider_slug=row.get("provider_slug"),
        enabled=bool(row.get("enabled")),
        events=list(row.get("events") or []),
        target_kind=str(row.get("target_kind") or "http"),
        target_config=row.get("target_config"),
        method=str(row.get("request_method") or "POST"),
        url=str(row.get("request_url") or ""),
        headers=dict(row.get("request_headers") or {}),
        body=row.get("request_body"),
        username=row.get("request_username"),
        secret_fields=list(row.get("secret_fields") or []),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _triggered(row: Mapping[str, Any]) -> TriggeredWebhookRecord:
    """Adapt a :data:`_TRIGGERED_SELECT` row into its record."""
    attempts = int(row.get("attempt_count") or 0)
    status = triggered_status(str(row.get("delivery_status") or ""), attempts)
    finished = status in ("success", "failure")
    return TriggeredWebhookRecord(
        id=str(row["id"]),
        webhook_id=str(row["webhook_id"]),
        name=request_description(str(row.get("request_method") or ""), str(row.get("request_url") or "")),
        status=status,
        attempts_made=attempts,
        attempts_remaining=0 if finished else max(0, WEBHOOK_MAX_DELIVERY_ATTEMPTS - attempts),
        trigger_type=str(row.get("trigger_type") or "resource_creation"),
        event_name=str(row.get("event_name") or ""),
        consumer_name=str(row.get("consumer_name") or ""),
        consumer_slug=str(row.get("consumer_slug") or ""),
        provider_name=str(row.get("provider_name") or ""),
        provider_slug=str(row.get("provider_slug") or ""),
        consumer_version_number=row.get("consumer_version_number"),
        sha=(row.get("pact_version_sha") or "").strip() or None,
        verification_number=row.get("verification_number"),
        triggered_at=_iso(row.get("created_at")),
    )


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _missing(webhook_id: str) -> PactPublicationError:
    """The 404 for a webhook the workspace does not have."""
    return PactPublicationError(CODE_WEBHOOK_NOT_FOUND, f"no webhook '{webhook_id}' in this workspace")


def _scope_pacticipant(db: Any, tenant_id: str, name: Optional[str], role: str) -> Optional[PacticipantRecord]:
    """Resolve the consumer or provider a webhook body names.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` pointing at the name when the workspace has
            no such pacticipant.
    """
    if name is None:
        return None
    try:
        return get_pacticipant(db, tenant_id, name)
    except PacticipantValidationError as exc:
        pointer = f"/{role}/name"
        raise PactPublicationError(
            CODE_WEBHOOK_INVALID, f"{pointer}: no pacticipant '{name}' in this workspace", pointer=pointer
        ) from exc


def _secrets_to_seal(webhook: WebhookInput, stored: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Work out the secrets to seal, keeping a stored value wherever the body sent ``**********``.

    Args:
        webhook: The checked body.
        stored: The opened secrets of the webhook being replaced; ``None`` for a new webhook or
            when they cannot be opened.

    Returns:
        ``{"password", "signingSecret", "headers"}`` with only the values that are set.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` when ``**********`` is sent for a value
            that is not stored; ``pact-webhook-secrets-unavailable`` when it is stored but cannot
            be opened.
    """

    def keep(value: Optional[str], kept: Any, pointer: str) -> Optional[str]:
        if value != REDACTED:
            return value
        if stored is None:
            raise PactPublicationError(
                CODE_WEBHOOK_SECRETS_UNAVAILABLE,
                f"{pointer}: the stored value cannot be opened (check {KEYS_SETTING}); send the value itself",
                pointer=pointer,
            )
        if not isinstance(kept, str) or not kept:
            raise PactPublicationError(
                CODE_WEBHOOK_INVALID,
                f"{pointer}: {REDACTED} keeps a stored value, and none is stored; send the value itself",
                pointer=pointer,
            )
        return kept

    stored_headers = {str(k).lower(): v for k, v in ((stored or {}).get("headers") or {}).items()}
    header_pointer = "/target/token" if webhook.target_config is not None else "/request/headers/{name}"
    headers = {
        name: keep(value, stored_headers.get(name.lower()), header_pointer.format(name=name))
        for name, value in webhook.secret_headers.items()
    }
    secrets: Dict[str, Any] = {}
    password = keep(webhook.password, (stored or {}).get("password"), "/request/password")
    if password:
        secrets["password"] = password
    signing = keep(webhook.signing_secret, (stored or {}).get("signingSecret"), "/signingSecret")
    if signing:
        secrets["signingSecret"] = signing
    if headers:
        secrets["headers"] = headers
    return secrets


def _sealed_columns(secrets: Mapping[str, Any]) -> Tuple[Optional[bytes], Optional[int], List[str]]:
    """Seal ``secrets`` and name what was sealed.

    Returns:
        ``(ciphertext, key_version, secret_fields)``; all empty for a webhook without secrets.

    Raises:
        PactPublicationError: ``pact-webhook-secrets-unavailable`` when no key is configured.
    """
    if not secrets:
        return None, None, []
    try:
        ciphertext, key_version = seal_webhook_secrets(secrets)
    except WebhookSecretError as exc:
        raise PactPublicationError(
            CODE_WEBHOOK_SECRETS_UNAVAILABLE,
            f"this webhook carries a secret and the server cannot seal it: set {KEYS_SETTING}",
        ) from exc
    named = ((SECRET_PASSWORD, "password"), (SECRET_SIGNING, "signingSecret"))
    fields = [name for name, key in named if key in secrets]
    fields.extend(header_secret_field(name) for name in sorted(secrets.get("headers") or {}))
    return ciphertext, key_version, fields


def _write_values(
    db: Any, tenant_id: str, webhook: WebhookInput, stored: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    """The column values of a webhook write: scope resolved, secrets sealed."""
    consumer = _scope_pacticipant(db, tenant_id, webhook.consumer_name, "consumer")
    provider = _scope_pacticipant(db, tenant_id, webhook.provider_name, "provider")
    ciphertext, key_version, fields = _sealed_columns(_secrets_to_seal(webhook, stored))
    return {
        "description": webhook.description,
        "consumer_id": consumer.id if consumer else None,
        "provider_id": provider.id if provider else None,
        "enabled": webhook.enabled,
        "events": list(webhook.events),
        "target_kind": webhook.target_kind,
        "target_config": Json(webhook.target_config) if webhook.target_config is not None else None,
        "request_method": webhook.method,
        "request_url": webhook.url,
        "request_headers": Json(webhook.headers),
        "request_body": Json(webhook.body) if webhook.body is not None else None,
        "request_username": webhook.username,
        "secret_ciphertext": ciphertext,
        "key_version": key_version,
        "secret_fields": fields,
    }


# ---------------------------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------------------------


def list_webhooks(db: Any, tenant_id: str, *, scope: Any = ANY_SCOPE) -> List[WebhookRecord]:
    """List the workspace's webhooks, oldest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        scope: :data:`ANY_SCOPE` for every webhook, or ``(consumer, provider)`` — each a
            :class:`~app.pacticipant.PacticipantRecord` or ``None`` — for the webhooks defined for
            exactly that consumer and provider (``None`` matches webhooks that name none).

    Returns:
        The webhooks.
    """
    where = ""
    params: List[Any] = [tenant_id]
    if scope is not ANY_SCOPE:
        consumer, provider = scope
        where = " AND w.consumer_id IS NOT DISTINCT FROM %s::uuid AND w.provider_id IS NOT DISTINCT FROM %s::uuid"
        params += [consumer.id if consumer else None, provider.id if provider else None]
    rows = db.execute_query(_WEBHOOK_SELECT + where + " ORDER BY w.created_at, w.id", tuple(params)) or []
    return [_record(dict(row)) for row in rows]


def _read_row(db: Any, tenant_id: str, webhook_id: str) -> Optional[Dict[str, Any]]:
    """Read one webhook row, sealed columns included; ``None`` when the tenant has none."""
    if not is_uuid_string(str(webhook_id or "")):
        return None
    rows = db.execute_query(_WEBHOOK_SELECT + " AND w.id = %s::uuid", (tenant_id, webhook_id))
    return dict(rows[0]) if rows else None


def get_webhook(db: Any, tenant_id: str, webhook_id: str) -> WebhookRecord:
    """Read one webhook.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        webhook_id: The webhook's ``uuid``.

    Returns:
        The webhook.

    Raises:
        PactPublicationError: ``pact-webhook-not-found``.
    """
    row = _read_row(db, tenant_id, webhook_id)
    if row is None:
        raise _missing(webhook_id)
    return _record(row)


def create_webhook(
    db: Any,
    tenant_id: str,
    webhook: WebhookInput,
    *,
    actor: ConsumerActor,
    webhook_id: Optional[str] = None,
) -> WebhookRecord:
    """Create a webhook.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        webhook: The checked body.
        actor: Who is creating it.
        webhook_id: The ``uuid`` the client chose (``PUT …/webhooks/{uuid}``); generated when omitted.

    Returns:
        The stored webhook.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` for an unknown consumer or provider or a
            ``**********`` secret; ``pact-webhook-secrets-unavailable`` when a secret cannot be
            sealed; ``pact-webhook-limit-reached`` at :data:`MAX_WEBHOOKS_PER_TENANT` webhooks;
            ``pact-webhook-not-found`` when ``webhook_id`` belongs to another workspace.
    """
    values = _write_values(db, tenant_id, webhook, {})
    user_id = _user_id(actor)
    columns = list(values)

    def work(cursor: Any) -> Optional[str]:
        cursor.execute("SELECT count(*) AS n FROM apiome.pact_webhook WHERE tenant_id = %s::uuid", (tenant_id,))
        if int(cursor.fetchone()["n"]) >= MAX_WEBHOOKS_PER_TENANT:
            raise PactPublicationError(
                CODE_WEBHOOK_LIMIT,
                f"this workspace already has {MAX_WEBHOOKS_PER_TENANT} webhooks; delete one before adding another",
            )
        cursor.execute(
            f"""
            INSERT INTO apiome.pact_webhook (id, tenant_id, created_by, updated_by, {", ".join(columns)})
            VALUES (COALESCE(%s::uuid, apiome.uuid_generate_v4()), %s::uuid, %s::uuid, %s::uuid,
                    {", ".join(["%s"] * len(columns))})
            ON CONFLICT (id) DO NOTHING
            RETURNING id::text AS id
            """,
            (webhook_id, tenant_id, user_id, user_id, *[values[column] for column in columns]),
        )
        row = cursor.fetchone()
        return row["id"] if row else ""

    created_id = db._guarded_tx(work)
    if not created_id:
        # The id exists in another workspace: it names nothing the caller can see or replace.
        raise _missing(str(webhook_id))
    return get_webhook(db, tenant_id, created_id)


def replace_webhook(
    db: Any, tenant_id: str, webhook_id: str, webhook: WebhookInput, *, actor: ConsumerActor
) -> WebhookRecord:
    """Replace a webhook with a new definition.

    A secret sent as ``**********`` keeps the stored value; a secret left out is removed.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        webhook_id: The webhook's ``uuid``.
        webhook: The checked body.
        actor: Who is changing it.

    Returns:
        The stored webhook.

    Raises:
        PactPublicationError: ``pact-webhook-not-found``; otherwise as :func:`create_webhook`.
    """
    row = _read_row(db, tenant_id, webhook_id)
    if row is None:
        raise _missing(webhook_id)
    stored = unseal_webhook_secrets(row.get("secret_ciphertext"), row.get("key_version"))
    values = _write_values(db, tenant_id, webhook, stored)
    columns = list(values)

    def work(cursor: Any) -> Optional[bool]:
        cursor.execute(
            f"""
            UPDATE apiome.pact_webhook
            SET {", ".join(f"{column} = %s" for column in columns)},
                updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND id = %s::uuid
            """,
            (*[values[column] for column in columns], _user_id(actor), tenant_id, webhook_id),
        )
        return cursor.rowcount > 0

    if not db._guarded_tx(work):
        raise _missing(webhook_id)
    return get_webhook(db, tenant_id, webhook_id)


def delete_webhook(db: Any, tenant_id: str, webhook_id: str) -> WebhookRecord:
    """Delete a webhook, its queued deliveries, its firings and their logs.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        webhook_id: The webhook's ``uuid``.

    Returns:
        The webhook as it was.

    Raises:
        PactPublicationError: ``pact-webhook-not-found``.
    """
    record = get_webhook(db, tenant_id, webhook_id)

    def work(cursor: Any) -> bool:
        cursor.execute(
            "DELETE FROM apiome.pact_webhook WHERE tenant_id = %s::uuid AND id = %s::uuid", (tenant_id, webhook_id)
        )
        return True

    db._guarded_tx(work)
    return record


def load_for_delivery(db: Any, webhook_id: str, tenant_id: str) -> Optional[DeliveryWebhook]:
    """Read a webhook and open its secrets, for the sender.

    Args:
        db: The database.
        webhook_id: The webhook's ``uuid``.
        tenant_id: The tenant of the queued delivery.

    Returns:
        The webhook and its secrets (``secrets`` is ``None`` when they cannot be opened), or
        ``None`` when the webhook no longer exists.
    """
    row = _read_row(db, tenant_id, webhook_id)
    if row is None:
        return None
    return DeliveryWebhook(
        record=_record(row),
        secrets=unseal_webhook_secrets(row.get("secret_ciphertext"), row.get("key_version")),
    )


# ---------------------------------------------------------------------------------------------
# Firings
# ---------------------------------------------------------------------------------------------


def find_webhooks_to_trigger(
    cursor: Any, tenant_id: str, consumer_id: str, provider_id: str, event_name: str
) -> List[str]:
    """The enabled webhooks an event of a pact fires.

    Args:
        cursor: An open cursor.
        tenant_id: The pact's tenant.
        consumer_id: The pact's consumer.
        provider_id: The pact's provider.
        event_name: The event.

    Returns:
        The ids of the webhooks that list the event and are for this consumer (or any) and this
        provider (or any), oldest first.
    """
    cursor.execute(
        """
        SELECT id::text AS id FROM apiome.pact_webhook
        WHERE tenant_id = %s::uuid AND enabled AND %s = ANY(events)
          AND (consumer_id IS NULL OR consumer_id = %s::uuid)
          AND (provider_id IS NULL OR provider_id = %s::uuid)
        ORDER BY created_at, id
        """,
        (tenant_id, event_name, consumer_id, provider_id),
    )
    return [row["id"] for row in cursor.fetchall() or []]


def enqueue_triggered_webhook(
    cursor: Any,
    *,
    tenant_id: str,
    webhook_id: str,
    consumer_id: str,
    provider_id: str,
    event_name: str,
    parameters: Mapping[str, str],
    consumer_version_number: Optional[str] = None,
    sha: Optional[str] = None,
    verification_number: Optional[int] = None,
    trigger_type: str = "resource_creation",
) -> str:
    """Queue one firing of a webhook, on the caller's cursor.

    Args:
        cursor: The open transaction's cursor.
        tenant_id: The pact's tenant.
        webhook_id: The webhook to fire.
        consumer_id: The pact's consumer.
        provider_id: The pact's provider.
        event_name: The event.
        parameters: The template parameters of this firing (no secret among them).
        consumer_version_number: The consumer version of the pact.
        sha: The pact version.
        verification_number: The verification result that caused it, for a verification event.
        trigger_type: ``resource_creation`` or ``user``.

    Returns:
        The firing's ``uuid``.
    """
    cursor.execute(
        """
        INSERT INTO apiome.push_webhook_delivery_events
          (tenant_id, subscription_id, target_url, pact_webhook_id, event_type, payload, status,
           attempt_count, next_retry_at)
        SELECT %s::uuid, NULL, w.request_url, w.id, %s, %s::jsonb, 'pending', 0, CURRENT_TIMESTAMP
        FROM apiome.pact_webhook w
        WHERE w.id = %s::uuid AND w.tenant_id = %s::uuid
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            EVENT_TYPE_PREFIX + event_name,
            Json({"eventName": event_name, "parameters": dict(parameters)}),
            webhook_id,
            tenant_id,
        ),
    )
    delivery_event_id = cursor.fetchone()["id"]
    cursor.execute(
        """
        INSERT INTO apiome.pact_triggered_webhook
          (tenant_id, webhook_id, delivery_event_id, consumer_id, provider_id, event_name, trigger_type,
           consumer_version_number, pact_version_sha, verification_number)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            webhook_id,
            delivery_event_id,
            consumer_id,
            provider_id,
            event_name,
            trigger_type,
            consumer_version_number,
            sha,
            verification_number,
        ),
    )
    return cursor.fetchone()["id"]


def list_triggered_webhooks(
    db: Any,
    tenant_id: str,
    consumer: PacticipantRecord,
    provider: PacticipantRecord,
    *,
    consumer_version_number: Optional[str] = None,
    verification: Optional[Tuple[str, int]] = None,
    latest_only: bool = False,
    limit: int = 200,
) -> List[TriggeredWebhookRecord]:
    """List the firings for the pacts of one consumer and provider, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        consumer: The consumer.
        provider: The provider.
        consumer_version_number: Only firings caused by this consumer version's publication.
        verification: ``(sha, number)`` — only firings caused by that verification result.
        latest_only: Only the latest firing of each webhook and event (the pact's webhook status).
        limit: The most firings returned.

    Returns:
        The firings.
    """
    where = " AND t.provider_id = %s::uuid AND t.consumer_id = %s::uuid"
    params: List[Any] = [tenant_id, provider.id, consumer.id]
    if consumer_version_number is not None:
        where += " AND t.consumer_version_number = %s AND t.verification_number IS NULL"
        params.append(consumer_version_number)
    if verification is not None:
        where += " AND t.pact_version_sha = %s AND t.verification_number = %s"
        params += [verification[0], verification[1]]
    query = _TRIGGERED_SELECT + where
    if latest_only:
        query = (
            "SELECT * FROM ("
            + query.replace("SELECT t.id::text", "SELECT DISTINCT ON (t.webhook_id, t.event_name) t.id::text", 1)
            + " ORDER BY t.webhook_id, t.event_name, t.created_at DESC, t.id DESC) latest"
            " ORDER BY created_at DESC, id DESC LIMIT %s"
        )
    else:
        query += " ORDER BY t.created_at DESC, t.id DESC LIMIT %s"
    params.append(max(1, int(limit)))
    return [_triggered(dict(row)) for row in db.execute_query(query, tuple(params)) or []]


def get_triggered_webhook_logs(db: Any, tenant_id: str, triggered_id: str) -> TriggeredWebhookLogs:
    """Read one firing and the log of each of its attempts.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        triggered_id: The firing's ``uuid``.

    Returns:
        The firing and its executions, oldest first.

    Raises:
        PactPublicationError: ``pact-triggered-webhook-not-found``.
    """
    rows = (
        db.execute_query(_TRIGGERED_SELECT + " AND t.id = %s::uuid", (tenant_id, triggered_id))
        if is_uuid_string(str(triggered_id or ""))
        else None
    )
    if not rows:
        raise PactPublicationError(
            CODE_TRIGGERED_WEBHOOK_NOT_FOUND, f"no triggered webhook '{triggered_id}' in this workspace"
        )
    row = dict(rows[0])
    attempts = (
        db.execute_query(
            """
            SELECT attempt_number, http_status, error_message, execution_log, attempted_at
            FROM apiome.push_webhook_delivery_attempts
            WHERE delivery_event_id = %s::uuid
            ORDER BY attempt_number
            """,
            (row["delivery_event_id"],),
        )
        or []
    )
    executions = [
        {
            "attempt": int(attempt["attempt_number"]),
            "success": attempt.get("http_status") is not None and 200 <= int(attempt["http_status"]) < 300,
            "status": attempt.get("http_status"),
            "logs": attempt.get("execution_log") or attempt.get("error_message") or "",
            "createdAt": _iso(attempt.get("attempted_at")),
        }
        for attempt in attempts
    ]
    return TriggeredWebhookLogs(triggered=_triggered(row), executions=executions)
