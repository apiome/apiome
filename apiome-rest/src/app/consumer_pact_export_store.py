"""Who an exported pact names — PFX-2.6 (#6930).

A pact names its consumer and provider by **pacticipant name**, and a publish registers or finds
pacticipants by that name. An Apiome consumer or project may already be bound to a pacticipant
(PFX-1.1: ``pacticipant.consumer_id`` / ``pacticipant.project_id``); when it is, the exported pact
must use that pacticipant's name, or publishing it would create a second, unbound application.

Every read is scoped by the caller's tenant id, so a binding in another workspace is never seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .consumer_contract import ConsumerRecord, ConsumerValidationError

__all__ = [
    "CODE_PROVIDER_AMBIGUOUS",
    "PactNames",
    "resolve_pact_names",
]

#: Several pacticipants are bound to the project and no ``provider`` was named.
CODE_PROVIDER_AMBIGUOUS = "consumer-pact-export-provider-ambiguous"

#: The live pacticipant bound to one consumer. %s: tenant id, consumer id.
_BOUND_TO_CONSUMER = """
    SELECT slug, name FROM apiome.pacticipant
    WHERE tenant_id = %s::uuid AND consumer_id = %s::uuid AND deleted_at IS NULL
    ORDER BY slug
    LIMIT 1
"""

#: The live pacticipants bound to one project. %s: tenant id, project id.
_BOUND_TO_PROJECT = """
    SELECT slug, name FROM apiome.pacticipant
    WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND deleted_at IS NULL
    ORDER BY slug
"""


@dataclass(frozen=True)
class PactNames:
    """The names an exported pact carries.

    Attributes:
        consumer: ``consumer.name`` — the bound pacticipant's name, else the consumer's handle.
        provider: ``provider.name`` — the caller's choice, else the project's one bound
            pacticipant, else the project's handle.
        consumer_bound: Whether the consumer name came from a bound pacticipant.
        provider_bound: Whether the provider name came from a bound pacticipant.
    """

    consumer: str
    provider: str
    consumer_bound: bool
    provider_bound: bool


def resolve_pact_names(
    db: Any,
    tenant_id: str,
    project: Dict[str, Any],
    consumer: ConsumerRecord,
    provider: Optional[str] = None,
) -> PactNames:
    """Choose the consumer and provider names of an exported pact.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project: The resolved project row (``id``, ``slug``).
        consumer: The consumer being exported.
        provider: A provider pacticipant name the caller chose, when it did.

    Returns:
        The names.

    Raises:
        ConsumerValidationError: ``consumer-pact-export-provider-ambiguous`` when no provider was
            named and more than one pacticipant is bound to the project.
    """
    consumer_rows: List[Dict[str, Any]] = db.execute_query(_BOUND_TO_CONSUMER, (tenant_id, consumer.id)) or []
    consumer_name = str(consumer_rows[0]["name"]) if consumer_rows else consumer.slug

    chosen = (provider or "").strip()
    if chosen:
        return PactNames(consumer_name, chosen, bool(consumer_rows), False)

    project_rows: List[Dict[str, Any]] = db.execute_query(_BOUND_TO_PROJECT, (tenant_id, str(project["id"]))) or []
    if len(project_rows) > 1:
        names = ", ".join(str(row["slug"]) for row in project_rows)
        raise ConsumerValidationError(
            CODE_PROVIDER_AMBIGUOUS,
            f"several pacticipants are bound to this project ({names}); name the provider to export for",
        )
    if project_rows:
        return PactNames(consumer_name, str(project_rows[0]["name"]), bool(consumer_rows), True)
    return PactNames(consumer_name, str(project.get("slug") or project["id"]), bool(consumer_rows), False)
