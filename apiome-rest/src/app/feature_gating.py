"""Feature-entitlement gating dependencies for the Primitives type registry (#3478).

The advanced Type Registry surface — relative-``$ref`` resolver, namespaces, registry
settings, coverage stats, and the import pipeline — can optionally be gated behind a
per-tenant ``primitives-registry`` entitlement. Baseline primitives CRUD and ``/health``
are never gated.

The gate is itself controlled by an operator switch
(``settings.primitives_registry_gating_enabled``, default ``False``):

* **Gating disabled (default):** these dependencies are pure pass-throughs that return the
  authenticated ``auth_data`` unchanged — current behavior, every authenticated tenant
  reaches the advanced routes.
* **Gating enabled:** the calling tenant/user must hold the ``primitives-registry`` feature
  flag (per-user override > per-tenant override > license default, see
  ``Database.tenant_has_feature_flag``). Non-entitled callers receive ``403``.

Each gated route swaps its ``Depends(validate_authentication)`` for
``Depends(require_primitives_registry)``. Because the gate depends on
``validate_authentication`` and returns the same ``auth_data`` dict, route handlers are
otherwise unchanged, and tests that override ``validate_authentication`` keep working (the
override resolves the sub-dependency).
"""

from typing import Any, Callable, Dict

from fastapi import Depends, HTTPException

from .auth import validate_authentication
from .config import settings
from .database import db

# Canonical feature-flag slug for the Primitives type registry (matches the seed in
# apiome-db migration 20260623-130000.sql and the admin Feature-Flag panel).
PRIMITIVES_REGISTRY_FLAG = "primitives-registry"


def require_feature_flag(
    flag_name: str,
    *,
    gating_enabled: Callable[[], bool],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Build a FastAPI dependency that gates a route behind a named feature flag.

    Args:
        flag_name: The feature-flag slug the caller must hold when gating is on.
        gating_enabled: Zero-arg predicate read at request time deciding whether the gate
            is active. Read lazily (not captured as a bool) so the operator switch can be
            toggled — and patched in tests — without rebuilding the dependency.

    Returns:
        A dependency callable that returns the authenticated ``auth_data`` when the caller
        is allowed, or raises ``HTTPException(403)`` when gating is on and the caller is not
        entitled.
    """

    def _dependency(
        auth_data: Dict[str, Any] = Depends(validate_authentication),
    ) -> Dict[str, Any]:
        if not gating_enabled():
            return auth_data

        if db.tenant_has_feature_flag(
            auth_data.get("tenant_id"), auth_data.get("user_id"), flag_name
        ):
            return auth_data

        raise HTTPException(
            status_code=403,
            detail=(
                f"This tenant is not entitled to the '{flag_name}' feature. "
                "Ask an administrator to grant it to continue."
            ),
        )

    return _dependency


# Gate for the advanced Primitives type-registry routes (resolver, namespaces, settings,
# stats, import). Pass-through unless ``primitives_registry_gating_enabled`` is set.
require_primitives_registry = require_feature_flag(
    PRIMITIVES_REGISTRY_FLAG,
    gating_enabled=lambda: settings.primitives_registry_gating_enabled,
)
