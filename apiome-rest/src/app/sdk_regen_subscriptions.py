"""Which SDKs regenerate on publish — SDK-4.3 (#4497).

SDK-4.1 publishes an SDK to a registry and SDK-4.2 delivers one as a pull request, but only when
someone asks. A **subscription** is the standing request: "every time this project publishes a
version, regenerate its npm SDK and ship it". This module owns that configuration and the moment a
publish turns it into work; :mod:`app.sdk_regen_worker` does the work.

**One subscription per project per ecosystem.** The ticket's subscription is *(project, language
target, delivery mode, options)*; the uniqueness is *(project, ecosystem)* because everything a
regen ships through is already one-per-ecosystem — the SDK-4.2 delivery target and the SDK-4.1
credential — and because two subscriptions for one ecosystem could each claim a registry version
for the same publish. The **delivery mode** says which of those a regen uses:

* ``registry`` — publish the regenerated package (SDK-4.1).
* ``git`` — open or update a pull request (SDK-4.2).
* ``registry_and_git`` — publish first, then deliver *the version that publish claimed*, so the pull
  request and the registry agree.

``deliveryMode`` has no default: publishing to a public registry is irreversible, so it is never
what a subscription does unless its author named it.

**Options are a closed vocabulary.** The job options SDK-1.1 was to carry were cancelled with it,
and SDK-3.4's settings now supply the branding every run reads, so the only per-run knob left in the
pipelines a subscription orchestrates is SDK-4.1's dry run:

* ``dryRun`` (registry modes only, default ``false``) — rehearse every release: build it, resolve
  and decrypt the credential, compute the version, and upload nothing. A ``registry_and_git``
  rehearsal still opens the pull request, carrying the version the next real publish would claim.

An unknown option is refused rather than stored, so a misspelt ``dry_run`` cannot silently publish.

**Unsubscribing stops future runs and touches nothing past.** Disabling keeps the configuration;
deleting removes it. Either way the worker cancels jobs still queued for it, and every run, job,
package and pull request already produced is kept.

**A publish never fails because of a subscription.** :func:`enqueue_regen_on_publish` runs as a
background task after the publish response, like the CTG-3.3 webhook fan-out, and never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .database import db
from .revision_deprecation import is_uuid_string
from .sdk_publish_version import PUBLISH_ECOSYSTEMS

logger = logging.getLogger(__name__)

__all__ = [
    "DELIVERY_MODES",
    "DELIVERY_MODE_GIT",
    "DELIVERY_MODE_REGISTRY",
    "DELIVERY_MODE_REGISTRY_AND_GIT",
    "OPTION_DRY_RUN",
    "REGEN_ECOSYSTEMS",
    "REGEN_SUBSCRIPTION_SCHEMA_VERSION",
    "RegenOptions",
    "RegenSubscriptionError",
    "RegenSubscriptionOut",
    "delete_subscription",
    "enqueue_regen_on_publish",
    "includes_git",
    "includes_registry",
    "list_subscriptions",
    "normalize_delivery_mode",
    "normalize_ecosystem",
    "normalize_options",
    "options_object",
    "read_options",
    "save_subscription",
    "set_subscription_active",
    "subscription_out",
]

#: The shape of a subscription as the API describes it.
REGEN_SUBSCRIPTION_SCHEMA_VERSION = "sdk.regen-subscription.v1"

#: The language targets a subscription can name: the SDK-4.1 package layouts.
REGEN_ECOSYSTEMS: Tuple[str, ...] = PUBLISH_ECOSYSTEMS

#: Publish the regenerated package to its registry (SDK-4.1).
DELIVERY_MODE_REGISTRY = "registry"

#: Open or update a pull request carrying the regenerated SDK (SDK-4.2).
DELIVERY_MODE_GIT = "git"

#: Publish first, then deliver the version that publish claimed.
DELIVERY_MODE_REGISTRY_AND_GIT = "registry_and_git"

#: Every delivery mode, matching V258's ``sdk_regen_subscriptions_delivery_mode_check``.
DELIVERY_MODES: Tuple[str, ...] = (
    DELIVERY_MODE_REGISTRY,
    DELIVERY_MODE_GIT,
    DELIVERY_MODE_REGISTRY_AND_GIT,
)

#: The one option: rehearse the registry step instead of uploading.
OPTION_DRY_RUN = "dryRun"


class RegenSubscriptionError(ValueError):
    """Raised when a subscription cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid SDK regen subscription")


@dataclass(frozen=True)
class RegenOptions:
    """A subscription's options, as a job applies them.

    Attributes:
        dry_run: Rehearse the registry step instead of uploading.
    """

    dry_run: bool = False


class RegenSubscriptionOut(BaseModel):
    """A subscription, as the API describes it.

    Attributes:
        schema_version: The projection's shape.
        ecosystem: ``npm`` or ``pypi``.
        delivery_mode: ``registry``, ``git`` or ``registry_and_git``.
        options: The normalised options (``{"dryRun": …}`` for a registry mode, ``{}`` for git).
        active: Whether publishes regenerate this SDK.
        created_at: When the subscription was first stored.
        updated_at: When it was last changed.
        updated_by: Who last changed it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=REGEN_SUBSCRIPTION_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    ecosystem: str
    delivery_mode: str = Field(serialization_alias="deliveryMode")
    options: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


# -------------------------------------------------------------------------------------------
# Vocabulary
# -------------------------------------------------------------------------------------------


def includes_registry(delivery_mode: Optional[str]) -> bool:
    """Whether a delivery mode publishes to a registry.

    Args:
        delivery_mode: A delivery mode.

    Returns:
        ``True`` for ``registry`` and ``registry_and_git``.
    """
    return delivery_mode in (DELIVERY_MODE_REGISTRY, DELIVERY_MODE_REGISTRY_AND_GIT)


def includes_git(delivery_mode: Optional[str]) -> bool:
    """Whether a delivery mode opens a pull request.

    Args:
        delivery_mode: A delivery mode.

    Returns:
        ``True`` for ``git`` and ``registry_and_git``.
    """
    return delivery_mode in (DELIVERY_MODE_GIT, DELIVERY_MODE_REGISTRY_AND_GIT)


def normalize_ecosystem(ecosystem: Optional[str]) -> str:
    """Return the ecosystem key, or refuse.

    Args:
        ecosystem: The requested ecosystem.

    Returns:
        The lower-cased key.

    Raises:
        RegenSubscriptionError: When the ecosystem has no SDK-4.1 package layout to regenerate.
    """
    key = (ecosystem or "").strip().lower()
    if key not in REGEN_ECOSYSTEMS:
        raise RegenSubscriptionError(
            f"ecosystem must be one of {', '.join(REGEN_ECOSYSTEMS)}, got {ecosystem!r}. A regen "
            "rebuilds the SDK-4.1 package layout, which exists for those ecosystems only."
        )
    return key


def normalize_delivery_mode(delivery_mode: Optional[str]) -> str:
    """Return the delivery mode key, or refuse.

    Args:
        delivery_mode: The requested mode.

    Returns:
        The lower-cased key.

    Raises:
        RegenSubscriptionError: When the mode is not one of :data:`DELIVERY_MODES`.
    """
    key = (delivery_mode or "").strip().lower()
    if key not in DELIVERY_MODES:
        raise RegenSubscriptionError(
            f"deliveryMode must be one of {', '.join(DELIVERY_MODES)}, got {delivery_mode!r}."
        )
    return key


def normalize_options(delivery_mode: str, raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate and normalise a subscription's options for its delivery mode.

    Args:
        delivery_mode: The (normalised) delivery mode the options belong to.
        raw: The options as submitted, or ``None``.

    Returns:
        ``{"dryRun": bool}`` for a registry mode (``dryRun`` defaulting to ``false``); ``{}`` for
        ``git``.

    Raises:
        RegenSubscriptionError: For an unknown option, a ``dryRun`` that is not a boolean, or a
            ``dryRun`` on a ``git`` subscription (a pull request has no dry run — it is reviewed
            before anything ships).
    """
    options = dict(raw or {})
    problems: List[str] = []
    unknown = sorted(key for key in options if key != OPTION_DRY_RUN)
    if unknown:
        problems.append(
            f"unknown option(s) {', '.join(repr(key) for key in unknown)}; the only option is "
            f"{OPTION_DRY_RUN!r}"
        )
    dry_run = options.get(OPTION_DRY_RUN, False)
    if OPTION_DRY_RUN in options:
        if not isinstance(dry_run, bool):
            problems.append(f"options.{OPTION_DRY_RUN} must be true or false")
        elif not includes_registry(delivery_mode):
            problems.append(
                f"options.{OPTION_DRY_RUN} applies to the registry step; a {delivery_mode!r} "
                "subscription publishes nothing, and a pull request is reviewed before it ships"
            )
    if problems:
        raise RegenSubscriptionError(*problems)
    if includes_registry(delivery_mode):
        return {OPTION_DRY_RUN: bool(dry_run)}
    return {}


def read_options(delivery_mode: Optional[str], stored: Any) -> RegenOptions:
    """Read stored options leniently, for a job about to run.

    A stored row was validated when it was saved, but a job must still run sensibly on a row from a
    newer build or a hand edit: anything unrecognised is ignored, and ``dryRun`` counts only when it
    is exactly ``true`` on a registry mode — a malformed value never *enables* a rehearsal that would
    silently stop real publishing, nor the reverse.

    Args:
        delivery_mode: The subscription's delivery mode.
        stored: The ``options`` column.

    Returns:
        The options to apply.
    """
    dry_run = isinstance(stored, Mapping) and stored.get(OPTION_DRY_RUN) is True
    return RegenOptions(dry_run=bool(dry_run and includes_registry(delivery_mode)))


def options_object(delivery_mode: Optional[str], stored: Any) -> Dict[str, Any]:
    """Render stored options as the object the API reports and a job records.

    Args:
        delivery_mode: The subscription's delivery mode.
        stored: The ``options`` column.

    Returns:
        ``{"dryRun": bool}`` for a registry mode, ``{}`` for ``git`` — read through
        :func:`read_options`, so what is reported is exactly what a job applies.
    """
    if not includes_registry(delivery_mode):
        return {}
    return {OPTION_DRY_RUN: read_options(delivery_mode, stored).dry_run}


# -------------------------------------------------------------------------------------------
# Store
# -------------------------------------------------------------------------------------------


def subscription_out(row: Mapping[str, Any]) -> RegenSubscriptionOut:
    """Project a stored subscription row onto its API description.

    Args:
        row: A row from ``sdk_regen_subscriptions``.

    Returns:
        The description.
    """
    mode = str(row.get("delivery_mode") or "")
    return RegenSubscriptionOut(
        ecosystem=str(row.get("ecosystem") or ""),
        delivery_mode=mode,
        options=options_object(mode, row.get("options")),
        active=bool(row.get("active")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )


def list_subscriptions(tenant_id: str, project_id: str) -> List[RegenSubscriptionOut]:
    """List a project's subscriptions.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.

    Returns:
        One entry per subscribed ecosystem. Never raises: a store failure logs and returns an empty
        list, because this is a read of configuration rather than a step in a run.
    """
    try:
        rows = db.list_sdk_regen_subscriptions(tenant_id, project_id)
    except Exception:  # noqa: BLE001 - listing configuration must not take a screen down
        logger.warning(
            "Could not list SDK regen subscriptions for project %s", project_id, exc_info=True
        )
        return []
    return [subscription_out(row) for row in rows]


def save_subscription(
    tenant_id: str,
    project_id: str,
    *,
    ecosystem: str,
    delivery_mode: Optional[str],
    options: Optional[Mapping[str, Any]] = None,
    active: bool = True,
    actor_id: Optional[str] = None,
) -> RegenSubscriptionOut:
    """Store (or replace) a project's subscription for one ecosystem.

    Every field is validated before anything is written, and every problem is reported at once.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: ``npm`` or ``pypi``.
        delivery_mode: ``registry``, ``git`` or ``registry_and_git``.
        options: The options object.
        active: Whether publishes regenerate this SDK.
        actor_id: The user configuring it.

    Returns:
        The stored subscription.

    Raises:
        RegenSubscriptionError: When a field is invalid.
        RuntimeError: When the write returned no row.
    """
    problems: List[str] = []
    key = ""
    mode = ""
    try:
        key = normalize_ecosystem(ecosystem)
    except RegenSubscriptionError as exc:
        problems.extend(exc.errors)
    try:
        mode = normalize_delivery_mode(delivery_mode)
    except RegenSubscriptionError as exc:
        problems.extend(exc.errors)
    normalised: Dict[str, Any] = {}
    if mode:
        try:
            normalised = normalize_options(mode, options)
        except RegenSubscriptionError as exc:
            problems.extend(exc.errors)
    if problems:
        raise RegenSubscriptionError(*problems)

    row = db.upsert_sdk_regen_subscription(
        tenant_id=tenant_id,
        project_id=project_id,
        ecosystem=key,
        delivery_mode=mode,
        options=normalised,
        active=bool(active),
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError("The SDK regen subscription could not be stored for this project.")
    return subscription_out(row)


def set_subscription_active(
    tenant_id: str,
    project_id: str,
    ecosystem: str,
    *,
    active: bool,
    actor_id: Optional[str] = None,
) -> Optional[RegenSubscriptionOut]:
    """Enable or disable a project's subscription for one ecosystem.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: ``npm`` or ``pypi``.
        active: The new state.
        actor_id: The user changing it.

    Returns:
        The updated subscription, or ``None`` when the project has none for that ecosystem.

    Raises:
        RegenSubscriptionError: When the ecosystem is not one a subscription can name.
    """
    key = normalize_ecosystem(ecosystem)
    row = db.set_sdk_regen_subscription_active(
        tenant_id, project_id, key, active=bool(active), actor_id=actor_id
    )
    return subscription_out(row) if row else None


def delete_subscription(tenant_id: str, project_id: str, ecosystem: str) -> bool:
    """Remove a project's subscription for one ecosystem.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        Whether a subscription existed.

    Raises:
        RegenSubscriptionError: When the ecosystem is not one a subscription can name.
    """
    key = normalize_ecosystem(ecosystem)
    return db.delete_sdk_regen_subscription(tenant_id, project_id, key) > 0


# -------------------------------------------------------------------------------------------
# The publish event
# -------------------------------------------------------------------------------------------


def enqueue_regen_on_publish(
    *,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    version_line: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> int:
    """Background-task entry point: expand a publish into one queued job per active subscription.

    Scheduled by the publish route after the version is published. The run and its jobs are written
    in one statement (:meth:`app.database.Database.enqueue_sdk_regen_run`), so a publish queues its
    whole subscription matrix or none of it, and a project with no active subscription gains no
    rows. The worker picks the jobs up on its next tick.

    Never raises: a subscription problem must not turn a completed publish into a failed one. A
    queueing failure is logged with the revision, which is enough to re-run the regen by hand
    (SDK-4.1's publish and SDK-4.2's delivery routes) while the cause is fixed.

    Args:
        tenant_id: Owning tenant.
        project_id: The project that was published.
        published_revision_id: The published revision.
        version_line: Its version label, recorded on the run.
        actor_id: The user who published.

    Returns:
        How many jobs were queued (``0`` when none, including on a failure or non-UUID ids).
    """
    if not (
        is_uuid_string(str(tenant_id or ""))
        and is_uuid_string(str(project_id or ""))
        and is_uuid_string(str(published_revision_id or ""))
    ):
        return 0
    try:
        jobs = db.enqueue_sdk_regen_run(
            tenant_id=tenant_id,
            project_id=project_id,
            version_id=published_revision_id,
            version_line=version_line,
            published_by=actor_id,
        )
    except Exception:  # noqa: BLE001 - a publish never fails because of a subscription
        logger.exception(
            "SDK regen: could not queue jobs for revision %s of project %s",
            published_revision_id,
            project_id,
        )
        return 0
    if jobs:
        logger.info(
            "SDK regen: publish of revision %s queued %d job(s) (%s)",
            published_revision_id,
            len(jobs),
            ", ".join(sorted(str(job.get("ecosystem")) for job in jobs)),
        )
    return len(jobs)
