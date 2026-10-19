"""Suggested consumers: observed in traffic, not registered — CDG-3.5 (#5970).

The RDG-1.x usage index counts every call, but only a call a binding recognises is attributed to a
consumer. The rest are anonymous. V293 keeps, per project and day, the **client key** of each
unattributed call (``usage_unattributed_client_daily``): the product token of its scrubbed user
agent, or the HMAC its ``consumer_hint`` carried when no binding matched. Each distinct client key in
the window is a **Suggested consumer** of the project.

**Registering one is one click.** :func:`register_suggestion` creates the CTG-4.1 consumer and the
RDG-1.8 binding that recognises it — the glob ``<token>/*`` for a user agent, or a hashed binding
holding the HMAC the edge already sent (so nobody has to type the value). From the next batch on,
its calls are attributed and its runtime edges appear in the graph. It can also bind the client to
an existing consumer instead of registering a new one.

**No identity leaves the server.** A user-agent suggestion shows its token, which is what a person
would name the consumer after anyway. A hashed suggestion shows neither the value (Apiome never had
it) nor the HMAC (the RDG-1.8 rule: no response renders a bound value, not even as a hash). It is
addressed by an opaque id, a truncated SHA-256 of the HMAC, which identifies the row and nothing else.

A client key a live binding already recognises is not suggested, even though its older unattributed
rows remain until they age out of retention.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .consumer_binding import (
    BINDING_KINDS,
    KIND_USER_AGENT,
    BindingError,
    BindingRecord,
    ConsumerMatcher,
    active_key_version,
    normalize_binding,
)
from .consumer_binding_store import insert_binding, live_bindings
from .consumer_contract import ConsumerInput, ConsumerRecord, slugify_consumer_name
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_SUGGESTION_NOT_FOUND",
    "DEFAULT_WINDOW_DAYS",
    "MAX_SUGGESTIONS",
    "RegisterSuggestionInput",
    "RegisteredSuggestion",
    "SuggestedConsumer",
    "list_suggestions",
    "register_suggestion",
    "suggestion_id",
]

CODE_SUGGESTION_NOT_FOUND = "consumer-suggestion-not-found"

#: The window suggestions are drawn from (the same as the runtime edges').
DEFAULT_WINDOW_DAYS = 30

#: The most suggestions one read returns, busiest first.
MAX_SUGGESTIONS = 50

#: A suggestion id: ``ua:<token>`` or ``<kind>:<20 hex>``.
_ID = re.compile(r"^(?:ua:[a-z0-9][a-z0-9._-]{0,63}|(?:header|api_key|jwt_claim):[0-9a-f]{20})$")

#: How each hashed kind reads in a suggestion's label.
_KIND_NOUN = {"header": "header value", "api_key": "API key", "jwt_claim": "JWT claim"}


def suggestion_id(client_kind: str, client_key: str) -> str:
    """The id a suggestion is addressed by.

    Args:
        client_kind: ``user_agent`` or a hashed kind.
        client_key: The product token, or the HMAC.

    Returns:
        ``ua:<token>`` for a user agent; ``<kind>:<first 20 hex of sha256(hmac)>`` otherwise, so the
        HMAC itself never appears in a URL or a response.
    """
    if client_kind == KIND_USER_AGENT:
        return f"ua:{client_key}"
    return f"{client_kind}:{hashlib.sha256(client_key.encode('ascii')).hexdigest()[:20]}"


class SuggestedConsumer(BaseModel):
    """A client seen in the project's traffic that no binding attributes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="`ua:<token>` or `<kind>:<opaque>`; what register takes.")
    client_kind: str = Field(description="`user_agent`, `header`, `api_key` or `jwt_claim`.")
    label: str = Field(description="How the client reads: its user-agent token, or the kind of credential.")
    suggested_name: str = Field(description="A display name to register it under.")
    suggested_slug: Optional[str] = Field(default=None, description="A handle to register it under.")
    needs_binding_name: bool = Field(
        description="True for a hashed client: registering needs the header or claim name the value came in."
    )
    calls: int = Field(description="Unattributed calls in the window.")
    days_seen: int = Field(description="UTC days in the window with a call.")
    first_seen_at: str
    last_seen_at: str


class RegisterSuggestionInput(BaseModel):
    """How to register a suggestion.

    Attributes:
        name: Display name for a new consumer (defaults to the suggestion's).
        slug: Handle for a new consumer (defaults to the suggestion's).
        consumer: Bind to this existing consumer (slug or id) instead of registering a new one.
        binding_name: For a hashed client: the header, API-key header or claim name.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, max_length=128)
    consumer: Optional[str] = Field(default=None, max_length=128)
    binding_name: Optional[str] = Field(default=None, max_length=256)


class RegisteredSuggestion(BaseModel):
    """What registering did."""

    model_config = ConfigDict(extra="forbid")

    consumer: ConsumerRecord
    binding: BindingRecord
    created_consumer: bool = Field(description="False when the client was bound to an existing consumer.")


@dataclass(frozen=True)
class _Row:
    """One client key's totals over the window."""

    client_kind: str
    client_key: str
    calls: int
    days_seen: int
    first_seen_at: datetime
    last_seen_at: datetime


def _window(days: int, today: Optional[date] = None) -> date:
    """The first UTC day of a window of ``days`` days ending today."""
    end = today or datetime.now(timezone.utc).date()
    return end - timedelta(days=max(days, 1) - 1)


def _rows(db: Any, tenant_id: str, project_id: str, since: date) -> List[_Row]:
    """Every client key's unattributed totals since ``since``, busiest first."""
    rows = db.execute_query(
        """
        SELECT client_kind, client_key, sum(calls)::bigint AS calls, count(DISTINCT day) AS days_seen,
               min(first_seen_at) AS first_seen_at, max(last_seen_at) AS last_seen_at
        FROM apiome.usage_unattributed_client_daily
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND day >= %s
        GROUP BY client_kind, client_key
        HAVING sum(calls) > 0
        ORDER BY sum(calls) DESC, client_kind, client_key
        """,
        (tenant_id, project_id, since),
    )
    return [
        _Row(
            client_kind=row["client_kind"],
            client_key=row["client_key"],
            calls=int(row["calls"]),
            days_seen=int(row["days_seen"]),
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
        )
        for row in rows or []
    ]


def _bound(matcher: ConsumerMatcher, row: _Row) -> bool:
    """Whether a live binding already recognises the client key."""
    if row.client_kind == KIND_USER_AGENT:
        return matcher.match(None, None, f"{row.client_key}/") is not None or matcher.match(
            None, None, row.client_key
        ) is not None
    return matcher.match(row.client_kind, row.client_key, None) is not None


def _suggestion(row: _Row) -> SuggestedConsumer:
    """Present one row."""
    sid = suggestion_id(row.client_kind, row.client_key)
    if row.client_kind == KIND_USER_AGENT:
        label = row.client_key
        name = row.client_key
        slug: Optional[str] = slugify_consumer_name(row.client_key) or None
    else:
        noun = _KIND_NOUN.get(row.client_kind, row.client_kind)
        label = f"Unrecognised {noun} {sid.split(':', 1)[1][:6]}"
        name = label
        slug = None
    return SuggestedConsumer(
        id=sid,
        client_kind=row.client_kind,
        label=label,
        suggested_name=name,
        suggested_slug=slug,
        needs_binding_name=row.client_kind != KIND_USER_AGENT,
        calls=row.calls,
        days_seen=row.days_seen,
        first_seen_at=row.first_seen_at.isoformat(),
        last_seen_at=row.last_seen_at.isoformat(),
    )


def list_suggestions(
    db: Any, tenant_id: str, project_id: str, *, days: int = DEFAULT_WINDOW_DAYS, limit: int = MAX_SUGGESTIONS
) -> List[SuggestedConsumer]:
    """The project's suggested consumers, busiest first.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.
        days: The window in UTC days, ending today.
        limit: The most to return.

    Returns:
        The suggestions not yet recognised by a live binding.
    """
    if not is_uuid_string(tenant_id) or not is_uuid_string(project_id):
        return []
    matcher = ConsumerMatcher(live_bindings(db, tenant_id, project_id))
    out: List[SuggestedConsumer] = []
    for row in _rows(db, tenant_id, project_id, _window(days)):
        if matcher and _bound(matcher, row):
            continue
        out.append(_suggestion(row))
        if len(out) >= max(1, limit):
            break
    return out


def _find(db: Any, tenant_id: str, project_id: str, sid: str, days: int) -> Optional[_Row]:
    """The window's row a suggestion id names, if any."""
    if not _ID.match(sid):
        return None
    for row in _rows(db, tenant_id, project_id, _window(days)):
        if suggestion_id(row.client_kind, row.client_key) == sid:
            return row
    return None


def _binding_for(row: _Row, binding_name: Optional[str]) -> Tuple[str, str, Optional[str], Optional[int]]:
    """``(kind, normalized name, value_hmac, key_version)`` of the binding that recognises ``row``.

    Raises:
        BindingError: 400 when a hashed client has no ``binding_name`` or the name is malformed; 503
            when no master key is configured.
    """
    if row.client_kind == KIND_USER_AGENT:
        return KIND_USER_AGENT, normalize_binding(KIND_USER_AGENT, f"{row.client_key}/*"), None, None
    if row.client_kind not in BINDING_KINDS:
        raise BindingError("consumer-binding-invalid", "this suggestion cannot be bound")
    if not binding_name or not binding_name.strip():
        raise BindingError(
            "consumer-binding-invalid",
            "name the header or claim this client's value arrives in (binding_name)",
        )
    return row.client_kind, normalize_binding(row.client_kind, binding_name), row.client_key, active_key_version()


def register_suggestion(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    suggestion: str,
    body: RegisterSuggestionInput,
    actor: Any,
    days: int = DEFAULT_WINDOW_DAYS,
) -> RegisteredSuggestion:
    """Register a suggested consumer (or bind it to an existing one) and bind its client key.

    Everything that can be refused is checked before the consumer is created, so a refusal leaves
    nothing behind.

    Args:
        db: The database (bindings and the usage read).
        tenant_id: The tenant.
        project_id: The project.
        suggestion: The suggestion id.
        body: Name, slug, an existing consumer, and for a hashed client the binding name.
        actor: The :class:`~app.consumer_contract_store.ConsumerActor`.
        days: The window the suggestion must be in.

    Returns:
        The consumer, the binding, and whether the consumer is new.

    Raises:
        BindingError: 404 ``consumer-suggestion-not-found``; 400 / 409 / 503 from the binding.
        ConsumerValidationError: from registering or finding the consumer.
    """
    from .consumer_contract_store import create_consumer, get_consumer

    row = _find(db, tenant_id, project_id, suggestion, days)
    if row is None:
        raise BindingError(CODE_SUGGESTION_NOT_FOUND, "no such suggested consumer in this window", status=404)
    if _bound(ConsumerMatcher(live_bindings(db, tenant_id, project_id)), row):
        raise BindingError(
            "consumer-binding-exists",
            "a binding already recognises this client; its calls are attributed from the next batch",
            status=409,
        )
    kind, name, value_hmac, key_version = _binding_for(row, body.binding_name)
    presented = _suggestion(row)

    created = body.consumer is None
    if created:
        consumer = create_consumer(
            tenant_id,
            project_id,
            ConsumerInput(
                name=body.name or presented.suggested_name,
                slug=body.slug or presented.suggested_slug,
                metadata={"registered_from": "suggested_consumer", "client_kind": row.client_kind},
            ),
            actor=actor,
        )
    else:
        consumer = get_consumer(tenant_id, project_id, body.consumer or "")
    binding = insert_binding(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        consumer_id=consumer.id,
        kind=kind,
        name=name,
        value_hmac=value_hmac,
        key_version=key_version,
        user_id=actor.user_id if actor else None,
    )
    return RegisteredSuggestion(consumer=consumer, binding=binding, created_consumer=created)

