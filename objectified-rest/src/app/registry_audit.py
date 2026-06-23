"""
Registry audit log — shared verbs and the write helper (#3481, 7.4).

The type registry records each governed primitive action (create / update / delete / import)
as an append-only row in ``odb.registry_audit`` with the acting user and a timestamp. This
module centralises the action vocabulary and the single best-effort write helper so every
mutating primitives route audits consistently; the read side lives in
``registry_audit_routes.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .auth import get_authenticated_user_id

_logger = logging.getLogger(__name__)

# Registry action verbs (stored verbatim in registry_audit.action).
ACTION_CREATE = "primitive.create"
ACTION_UPDATE = "primitive.update"
ACTION_DELETE = "primitive.delete"
ACTION_IMPORT = "primitive.import"

#: Every action this service writes — used by the list endpoint's documentation/tests.
REGISTRY_AUDIT_ACTIONS = (
    ACTION_CREATE,
    ACTION_UPDATE,
    ACTION_DELETE,
    ACTION_IMPORT,
)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"


def record_registry_audit(
    db: Any,
    auth_data: Dict[str, Any],
    action: str,
    outcome: str = OUTCOME_SUCCESS,
    *,
    primitive_id: Optional[str] = None,
    schema_id: Optional[str] = None,
    namespace: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one registry audit row for a governed action.

    Resolves the acting user from ``auth_data`` (None for unattributable API-key calls) and
    delegates to ``db.insert_registry_audit``. The whole call is best-effort: any error
    (including resolving the actor) is logged and swallowed here so audit writes can never fail
    the governed action they record — even though they run inside the route's success path.

    Args:
        db: The database accessor (passed in so the caller's patched/test db is used).
        auth_data: The request's resolved auth context (carries ``tenant_id`` + actor).
        action: One of the ``ACTION_*`` verbs.
        outcome: ``success`` or ``failure`` (defaults to success).
        primitive_id: Affected primitive id, when one exists.
        schema_id: Derived ``$id`` of the affected type, for traceability.
        namespace: Registry namespace path of the affected type, when applicable.
        detail: Structured JSON context (changed fields, import counts, error info).
    """
    try:
        db.insert_registry_audit(
            auth_data.get("tenant_id"),
            action,
            outcome,
            primitive_id=primitive_id,
            schema_id=schema_id,
            namespace=namespace,
            actor_id=get_authenticated_user_id(auth_data),
            detail=detail,
        )
    except Exception as e:
        # Defensive: the db layer already swallows its own errors, but this guard guarantees
        # best-effort even if actor resolution or the accessor itself raises.
        _logger.warning("record_registry_audit(%s) failed: %s", action, e)
