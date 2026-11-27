"""One consumer model — a published pact refreshes the consumer's declared surface (PFX-7.1, #6961).

The Pact Broker surface (:mod:`app.pact_publication_store`) knows *pacticipants*; the registry's
consumer-driven contracts (:mod:`app.consumer_contract_store`) know *consumers* of a project and the
revisions of the surface each declares. They are one model: a consumer pacticipant **is** a
consumer of the provider's project, and publishing its pact is declaring its surface.

:func:`refresh_consumer_contracts` runs after a publish has committed, once per published pact:

1. The pact's **provider pacticipant** must be bound to a project (``pacticipant.project_id``). An
   unbound provider has no specification to resolve against, so the pact is reported as
   ``skipped`` with the reason — never silently ignored.
2. The **consumer** is registered in that project under the consumer pacticipant's handle when it
   is not there yet (a first publication from CI succeeds on its first run), and the consumer
   pacticipant is bound to it when it carries no binding yet.
3. The pact is resolved against the project's latest specification revision by
   :func:`app.pact_contract_import.import_pact` and stored as the consumer's **next contract
   revision** (revision N+1, CTG-4.1 rule 2). Interactions that cannot be placed stay on the
   revision with their reason codes.

**Idempotent.** A publish whose pact content and specification revision match the consumer's
current revision stores nothing (``unchanged``), so a re-run CI job does not grow the history.

**A publish never fails because of this.** The publish has committed when this runs; a fault while
refreshing is logged and reported as ``error``, and the next publish retries.

**Tenancy.** The provider and consumer are resolved in the caller's tenant; the project comes from
the provider's own row, and every contract write is tenant-scoped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .compatibility_engine import openapi_for_revision
from .consumer_contract import SOURCE_PACT, ConsumerRecord, ConsumerValidationError
from .consumer_contract_store import (
    ConsumerActor,
    current_contract,
    ensure_consumer,
    record_contract,
    resolve_version,
)
from .consumer_surface import SpecIndex
from .pact_contract_import import import_pact
from .pact_publication import PublishedPact
from .pact_publication_store import PublishOutcome
from .pacticipant import PacticipantPatch, PacticipantRecord
from .pacticipant_store import get_pacticipant, update_pacticipant

__all__ = [
    "REASON_NO_SPECIFICATION",
    "REASON_PROVIDER_NOT_BOUND",
    "STATUS_ERROR",
    "STATUS_REFRESHED",
    "STATUS_SKIPPED",
    "STATUS_UNCHANGED",
    "ConsumerRefresh",
    "ConsumerRefreshRun",
    "refresh_consumer_contracts",
    "refresh_notices",
]

logger = logging.getLogger(__name__)

#: A new contract revision was stored.
STATUS_REFRESHED = "refreshed"
#: The consumer's current revision already came from this pact and specification revision.
STATUS_UNCHANGED = "unchanged"
#: The pact could not be resolved against a project; ``reason_code`` says why.
STATUS_SKIPPED = "skipped"
#: The refresh failed; the publish itself stands.
STATUS_ERROR = "error"

#: The provider pacticipant is not bound to a project, so there is no specification to resolve to.
REASON_PROVIDER_NOT_BOUND = "provider-not-bound-to-project"
#: The bound project has no version, or its latest version cannot be rendered as OpenAPI.
REASON_NO_SPECIFICATION = "project-specification-unavailable"


@dataclass
class ConsumerRefresh:
    """What one published pact did to the consumer model.

    Attributes:
        consumer: The consumer pacticipant's handle.
        provider: The provider pacticipant's handle.
        status: One of the ``STATUS_*`` constants.
        reason_code: Stable code for ``skipped`` / ``error`` entries, else ``None``.
        reason: Human-readable explanation for ``skipped`` / ``error`` entries.
        project_id: The project the surface was declared in, when one was found.
        consumer_id: The registry consumer, when one was found or registered.
        revision: The contract revision stored (or the current one for ``unchanged``).
        resolved_count: Interactions placed on an operation.
        unresolved_count: Interactions or fields recorded as unresolved, each with a reason code.
    """

    consumer: str
    provider: str
    status: str
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    project_id: Optional[str] = None
    consumer_id: Optional[str] = None
    revision: Optional[int] = None
    resolved_count: int = 0
    unresolved_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Render the entry as the camelCase object the publish response carries."""
        body: Dict[str, Any] = {
            "consumer": self.consumer,
            "provider": self.provider,
            "status": self.status,
        }
        optional = {
            "reasonCode": self.reason_code,
            "reason": self.reason,
            "projectId": self.project_id,
            "consumerId": self.consumer_id,
            "revision": self.revision,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        if self.status in (STATUS_REFRESHED, STATUS_UNCHANGED):
            body["resolvedCount"] = self.resolved_count
            body["unresolvedCount"] = self.unresolved_count
        return body


@dataclass
class ConsumerRefreshRun:
    """The refreshes one publish request made, in pact order.

    Attributes:
        entries: One entry per pact whose consumer model was considered.
    """

    entries: List[ConsumerRefresh]

    def to_dict(self) -> List[Dict[str, Any]]:
        """Render every entry for the publish response."""
        return [entry.to_dict() for entry in self.entries]


def _should_refresh(published: PublishedPact) -> bool:
    """Whether a pact's publication can change the consumer's surface.

    A repeat publish of the same pact for the same consumer version changes nothing, so it is not
    a refresh; a new pact, a new consumer version of known content, or a replaced pact is.
    """
    return published.created or published.replaced or published.new_content


def _spec_index_for(tenant_id: str, tenant_slug: str, version_row: Dict[str, Any]) -> SpecIndex:
    """Render a version as OpenAPI and index it.

    Raises:
        Exception: Whatever the renderer raises; the caller reports it as a skipped refresh.
    """
    return SpecIndex(openapi_for_revision(version_row, tenant_slug, tenant_id))


def _consumer_for(
    db: Any,
    tenant_id: str,
    project_id: str,
    pacticipant: PacticipantRecord,
    actor: ConsumerActor,
) -> ConsumerRecord:
    """Find or register the project's consumer for a consumer pacticipant.

    The registry consumer shares the pacticipant's handle, and the pacticipant is bound to it the
    first time, so the two stay one model from then on.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project_id: The provider's project.
        pacticipant: The consumer pacticipant.
        actor: Who published.

    Returns:
        The consumer.
    """
    consumer = ensure_consumer(
        tenant_id,
        project_id,
        slug=pacticipant.slug,
        name=pacticipant.name,
        actor=actor,
        metadata={"source": "pact", "pacticipant": pacticipant.slug},
    )
    if not pacticipant.consumer_id:
        update_pacticipant(
            db, tenant_id, pacticipant.id, PacticipantPatch(consumer_id=consumer.id), actor=actor
        )
    return consumer


def _refresh_one(
    db: Any,
    tenant_id: str,
    tenant_slug: str,
    consumer_pacticipant: PacticipantRecord,
    published: PublishedPact,
    actor: ConsumerActor,
) -> ConsumerRefresh:
    """Refresh the consumer model for one published pact.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug the document renderer needs.
        consumer_pacticipant: The consumer pacticipant.
        published: The publication.
        actor: Who published.

    Returns:
        The report entry; never raises for a data problem.
    """
    pact = published.pact
    entry = ConsumerRefresh(consumer=consumer_pacticipant.slug, provider=pact.provider_slug, status=STATUS_SKIPPED)

    provider = get_pacticipant(db, tenant_id, pact.provider_slug)
    if not provider.project_id:
        entry.reason_code = REASON_PROVIDER_NOT_BOUND
        entry.reason = (
            f"provider {provider.name} is not bound to a project, so there is no specification to "
            f"resolve the pact against; bind it with PATCH …/pacticipants/{provider.slug} (project)"
        )
        return entry
    entry.project_id = provider.project_id

    try:
        version_row = resolve_version(tenant_id, provider.project_id, "latest")
        index = _spec_index_for(tenant_id, tenant_slug, version_row)
    except Exception as exc:  # noqa: BLE001 - any version or render fault is the same answer
        entry.reason_code = REASON_NO_SPECIFICATION
        entry.reason = f"the latest version of the provider's project cannot be resolved against: {exc}"
        return entry

    consumer = _consumer_for(db, tenant_id, provider.project_id, consumer_pacticipant, actor)
    entry.consumer_id = consumer.id
    digest = f"sha256:{pact.sha}"

    try:
        current = current_contract(tenant_id, consumer.id)
    except ConsumerValidationError:
        current = None
    if (
        current is not None
        and current.source == SOURCE_PACT
        and current.source_digest == digest
        and current.version_id == str(version_row["id"])
    ):
        entry.status = STATUS_UNCHANGED
        entry.revision = current.revision
        entry.resolved_count = int(current.source_metadata.get("resolved_count", 0) or 0)
        entry.unresolved_count = current.unresolved_count
        return entry

    result = import_pact(pact.content, index)
    stored = record_contract(
        tenant_id,
        provider.project_id,
        consumer,
        result.surface,
        actor=actor,
        unresolved=result.unresolved,
        source=SOURCE_PACT,
        version_id=str(version_row["id"]),
        version_label=str(version_row.get("version_id") or ""),
        source_metadata={
            **result.metadata,
            "resolved_count": result.resolved_count,
            "consumer_version": pact.consumer_version,
            "pact_sha": pact.sha,
        },
        source_digest=digest,
        note=f"Published by {consumer_pacticipant.name} version {pact.consumer_version}",
    )
    entry.status = STATUS_REFRESHED
    entry.revision = stored.revision
    entry.resolved_count = result.resolved_count
    entry.unresolved_count = len(result.unresolved)
    return entry


def refresh_consumer_contracts(
    db: Any,
    tenant_id: str,
    tenant_slug: str,
    outcome: PublishOutcome,
    *,
    actor: ConsumerActor,
) -> ConsumerRefreshRun:
    """Refresh the consumer's declared surface from the pacts a publish stored.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug the document renderer needs.
        outcome: What the publish stored (it has committed).
        actor: Who published.

    Returns:
        One entry per pact that could change the consumer's surface; pacts re-published unchanged
        are left out. A fault is reported as ``error`` and logged, never raised.
    """
    entries: List[ConsumerRefresh] = []
    for published in outcome.pacts:
        if not _should_refresh(published):
            continue
        try:
            entries.append(_refresh_one(db, tenant_id, tenant_slug, outcome.consumer, published, actor))
        except Exception as exc:  # noqa: BLE001 - never fail a committed publish
            logger.exception(
                "consumer model refresh failed for %s -> %s", outcome.consumer.slug, published.pact.provider_slug
            )
            entries.append(
                ConsumerRefresh(
                    consumer=outcome.consumer.slug,
                    provider=published.pact.provider_slug,
                    status=STATUS_ERROR,
                    reason_code="refresh-failed",
                    reason=(
                        f"the consumer contract could not be refreshed ({type(exc).__name__}); "
                        "publish again to retry"
                    ),
                )
            )
    return ConsumerRefreshRun(entries)


def refresh_notices(run: ConsumerRefreshRun) -> List[Dict[str, str]]:
    """Pact Broker ``notices`` for a run, in the shape ``pact-broker publish`` prints.

    Args:
        run: The run.

    Returns:
        One notice per entry. ``unchanged`` entries stay quiet.
    """
    notices: List[Dict[str, str]] = []
    for entry in run.entries:
        pair = f"{entry.consumer} -> {entry.provider}"
        if entry.status == STATUS_REFRESHED:
            kind = "warning" if entry.unresolved_count else "success"
            text = (
                f"Consumer contract of {pair} is now revision {entry.revision}: "
                f"{entry.resolved_count} interaction(s) resolved"
            )
            text += f", {entry.unresolved_count} unresolved." if entry.unresolved_count else "."
            notices.append({"type": kind, "text": text})
        elif entry.status == STATUS_SKIPPED:
            text = f"Consumer contract of {pair} not refreshed: {entry.reason}"
            notices.append({"type": "warning", "text": text})
        elif entry.status == STATUS_ERROR:
            notices.append({"type": "error", "text": f"Consumer contract of {pair}: {entry.reason}"})
    return notices
