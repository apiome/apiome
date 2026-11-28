"""The audit trail of every Pact Broker write — PFX-6.1 (#6953).

Every call that changes Pact data (a pacticipant, a version, a pact, a verification result, an
environment, a deployment, a webhook, a provider state…) appends one hash-chained
``apiome.access_audit`` row naming the action, the actor, the target and the route.

Two mechanisms write those rows:

* **In the transaction** — deleting, restoring and labelling pacticipants and versions, and the
  retention run, append their row inside the transaction that makes the change
  (:func:`app.pact_cleanup_store.audit_tx`), so the change and its row commit together.
* **After the change** — every other write is wrapped in :func:`audited_write`, which appends the row
  once the route has succeeded. Like every other ``write_access_audit`` caller, auditing is
  best-effort here: a failed audit insert is logged and never fails the change it describes.

``docs/pacts-permission-matrix.json`` tables every write, its permission and its audit action;
``tests/test_pacts_permission_matrix.py`` checks that each mounted write route appears there and
writes the row it names.

The row never carries a request body: webhook bodies hold credentials and pact bodies can be large.
It carries the route, the path parameters, the response status (when the route returns a ``Response``)
and, when the return value names one, the id of what was created.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import sys
from typing import Any, Callable, Dict, Mapping, Optional, TypeVar

from starlette.responses import Response

from .auth import get_authenticated_user_id
from .database import db as _default_db
from .pact_cleanup_store import AUDIT_ACTIONS as TRANSACTIONAL_AUDIT_ACTIONS
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ACTIONS",
    "AUDITED_ENDPOINTS",
    "TRANSACTIONAL_AUDIT_ACTIONS",
    "audited_write",
    "record_pact_write",
]

#: The ``access_audit`` actions :func:`audited_write` writes, one per kind of change.
AUDIT_ACTIONS = (
    "pacts.pacticipant.create",
    "pacts.pacticipant.update",
    "pacts.version.record",
    "pacts.tag.add",
    "pacts.publication.create",
    "pacts.verification.publish",
    "pacts.verification.run",
    # PFX-8.9 (#7306): stopping a live verification run.
    "pacts.verification.stop",
    "pacts.environment.create",
    "pacts.environment.update",
    "pacts.environment.delete",
    "pacts.deployment.record",
    "pacts.deployment.update",
    "pacts.release.record",
    "pacts.release.update",
    "pacts.webhook.create",
    "pacts.webhook.update",
    "pacts.webhook.delete",
    "pacts.webhook.execute",
    "pacts.webhook.redeliver",
    "pacts.provider_state.create",
    "pacts.provider_state.update",
    "pacts.provider_state.delete",
    "pacts.commit_status.retry",
    "pacts.verification_settings.update",
    "pacts.verification_override.save",
    "pacts.verification_override.delete",
    "pacts.republish_request.acknowledge",
    "pacts.secret.create",
    "pacts.secret.update",
    "pacts.secret.delete",
    "pacts.migration.import",
    # PFX-8.16 (#7313): the Migration wizard — a source broker reached from the server, and a
    # migration run started, stopped, resumed.
    "pacts.migration.source.test",
    "pacts.migration.run.start",
    "pacts.migration.run.stop",
    "pacts.migration.run.resume",
    # PFX-8.7 (#7304): a provider's standing contract sources, and each publish they make.
    "pacts.contract_source.update",
    "pacts.contract.auto_publish",
    # PFX-8.15 (#7312): an MCP agent action the workspace's Agents switches refused.
    "pacts.agent.refused",
)

#: Every endpoint :func:`audited_write` wraps, by qualified name, with the action it writes. The
#: permission-matrix suite reads it to prove that no write route is left unaudited.
AUDITED_ENDPOINTS: Dict[str, str] = {}

_F = TypeVar("_F", bound=Callable[..., Any])


def _source(auth_data: Mapping[str, Any]) -> str:
    """``api_key`` for a CI runner's key, ``web`` for a signed-in session.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The ``access_audit.source`` value.
    """
    return "api_key" if auth_data.get("auth_method") == "api_key" else "web"


def _actor_id(auth_data: Mapping[str, Any]) -> Optional[str]:
    """The acting user's id when it is a storable UUID, else ``None``.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The user id ``access_audit.actor_id`` can hold, or ``None`` (an unattributable key).
    """
    try:
        user_id = get_authenticated_user_id(dict(auth_data))
    except Exception:  # noqa: BLE001 - attributing the row never fails the audit
        user_id = None
    return str(user_id) if user_id and is_uuid_string(str(user_id)) else None


def record_pact_write(
    db: Any,
    auth_data: Mapping[str, Any],
    action: str,
    target: str,
    detail: Optional[Dict[str, Any]] = None,
) -> bool:
    """Append one ``access_audit`` row for a Pact write that has happened (best-effort).

    Args:
        db: The database handle (its ``write_access_audit`` appends the hash-chained row).
        auth_data: Who acted: the resolved auth context of the call.
        action: One of :data:`AUDIT_ACTIONS`.
        target: What was changed, e.g. ``pacticipant/billing-service``.
        detail: Structured context (route, path parameters, status). Never a request body.

    Returns:
        ``True`` when the row was written; ``False`` when there was no tenant to audit under or the
        insert failed (logged as a warning — the change it describes has already happened).

    Raises:
        ValueError: For an action outside :data:`AUDIT_ACTIONS` — a programming error, raised so a
            typo cannot write rows nobody filters for.
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown pact audit action {action!r}")
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        logger.warning("Pact write %s on %s has no tenant to audit under", action, target)
        return False
    try:
        db.write_access_audit(
            tenant_id=str(tenant_id),
            action=action,
            actor_id=_actor_id(auth_data),
            actor_label=auth_data.get("user_email") or auth_data.get("user_name") or auth_data.get("email"),
            target=target,
            source=_source(auth_data),
            detail=detail or {},
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s on %s for tenant %s", action, target, tenant_id, exc_info=True)
        return False
    return True


def _status_of(result: Any) -> Optional[int]:
    """The HTTP status a route's return value answers with, when the value carries one.

    Args:
        result: What the endpoint returned (a ``Response`` or a model / dict FastAPI serialises).

    Returns:
        The response's status code, or ``None`` for a value FastAPI serialises (its status is the
        route's declared ``status_code``, which the endpoint itself cannot see — always a success).
    """
    return int(result.status_code) if isinstance(result, Response) else None


def _created_id(result: Any) -> Optional[str]:
    """The id of what the call created or changed, when its return value names one.

    Args:
        result: What the endpoint returned.

    Returns:
        ``result.id`` / ``result["id"]`` / ``result["uuid"]`` as text, else ``None`` (a ``Response``,
        whose body is already serialised, never names one).
    """
    if isinstance(result, Response):
        return None
    for key in ("id", "uuid"):
        value = result.get(key) if isinstance(result, Mapping) else getattr(result, key, None)
        if value:
            return str(value)
    return None


def _target(template: str, params: Mapping[str, Any]) -> str:
    """Fill a target template from the route's path parameters.

    Args:
        template: e.g. ``pacticipant/{pacticipant_ref}``.
        params: The endpoint's keyword arguments.

    Returns:
        The filled target; the template itself when a placeholder is missing (never an error).
    """
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def _db_of(func: Callable[..., Any]) -> Any:
    """The database handle the endpoint's own module uses (so a test's patch of it applies).

    Args:
        func: The endpoint.

    Returns:
        The module's ``db``, or the application's database.
    """
    return getattr(sys.modules.get(func.__module__), "db", _default_db)


def audited_write(action: str, target: str) -> Callable[[_F], _F]:
    """Decorate a Pact write route so a successful call appends its ``access_audit`` row.

    The endpoint must take ``auth_data`` as a keyword argument (every Pact route does). The row is
    written after the endpoint returns a success (a value, or a ``Response`` below 400); a call that
    raises or answers 4xx/5xx changed nothing and writes no row. The decorated function keeps the
    endpoint's signature, so FastAPI sees the same parameters.

    Args:
        action: One of :data:`AUDIT_ACTIONS`.
        target: A template over the path parameters, e.g. ``pact-environment/{uuid}``.

    Returns:
        The decorator.

    Raises:
        ValueError: At import time, for an action outside :data:`AUDIT_ACTIONS`.
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown pact audit action {action!r}")

    def decorate(func: _F) -> _F:
        """Wrap ``func`` (sync or async) and register it in :data:`AUDITED_ENDPOINTS`."""
        route = getattr(func, "__qualname__", func.__name__)

        def after(kwargs: Dict[str, Any], result: Any) -> None:
            """Write the row for a call that returned ``result``."""
            status = _status_of(result)
            if status is not None and status >= 400:
                return
            auth_data = kwargs.get("auth_data") or {}
            params = {
                key: value
                for key, value in kwargs.items()
                if key != "auth_data" and isinstance(value, (str, int, bool)) and value is not None
            }
            detail: Dict[str, Any] = {"route": route, "params": params}
            if status is not None:
                detail["status"] = status
            created = _created_id(result)
            if created:
                detail["id"] = created
            record_pact_write(_db_of(func), auth_data, action, _target(target, kwargs), detail)

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = await func(*args, **kwargs)
                await asyncio.to_thread(after, kwargs, result)
                return result

            wrapper: Any = async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = func(*args, **kwargs)
                after(kwargs, result)
                return result

            wrapper = sync_wrapper

        # FastAPI reads the parameters from the signature and resolves string annotations (this
        # package uses ``from __future__ import annotations``) in the *wrapper's* globals — this
        # module's, where the endpoint's models are not defined. Pin the endpoint's signature with
        # its annotations already evaluated, so the request body is still read as the body.
        signature = inspect.signature(func, eval_str=True)
        if "auth_data" not in signature.parameters:
            raise TypeError(f"{route} has no auth_data parameter to audit the actor from")
        wrapper.__signature__ = signature
        AUDITED_ENDPOINTS[f"{func.__module__}.{route}"] = action
        return wrapper  # type: ignore[return-value]

    return decorate
