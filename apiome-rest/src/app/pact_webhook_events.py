"""Which webhooks an event fires — PFX-1.9 (#6922).

Two things happen on the broker surface that CI wants to hear about, and each is turned into
events here, after the write that caused it has committed:

**A pact was published** (:func:`fire_publish_events`). For every pact a publish request stored or
replaced — a request that changed nothing fires nothing:

* ``contract_published`` — always;
* ``contract_content_changed`` — when the content differs from the pact of the previous consumer
  version on the same branch or with the same tag (or of the previous version at all, for a
  version with neither), or there is no such previous pact;
* ``contract_requiring_verification_published`` — **once per provider version that has not
  verified this pact content yet**, taken from the head of the provider's main branch and the
  provider versions currently deployed or released. Each firing carries that provider version, its
  branch and why it is on the list (``latest from main branch``, ``deployed in production``), so a
  CI job knows which commit to check out;
* ``consumer_version_branch_created`` (Apiome) — when the publication recorded the consumer
  version on a branch the consumer did not have before.

**A verification result was published** (:func:`fire_verification_events`):
``provider_verification_published``, then ``provider_verification_succeeded`` or
``provider_verification_failed``.

For each event the enabled webhooks that list it and are for this consumer and provider (or any)
get one queued delivery each (:func:`app.pact_webhook_store.enqueue_triggered_webhook`), with the
template parameters of that firing.

**Neither function raises.** A webhook problem must never turn a completed publish into a failed
one: any error is logged and the function returns what it managed to queue.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .pact_publication import PublishedPact
from .pact_publication_store import PublishOutcome
from .pact_selectors import encode_metadata
from .pact_webhook import (
    EVENT_BRANCH_CREATED,
    EVENT_CONTENT_CHANGED,
    EVENT_PUBLISHED,
    EVENT_REQUIRING_VERIFICATION,
    EVENT_VERIFICATION_FAILED,
    EVENT_VERIFICATION_PUBLISHED,
    EVENT_VERIFICATION_SUCCEEDED,
    template_parameters,
)
from .pact_webhook_store import enqueue_triggered_webhook, find_webhooks_to_trigger
from .verification_result import VerificationResultRecord

logger = logging.getLogger(__name__)

__all__ = [
    "RequiredVerification",
    "content_changed",
    "fire_publish_events",
    "fire_verification_events",
    "pact_url",
    "required_verifications",
    "verification_result_url",
]

_PREVIOUS_SHA = """
    SELECT pv.sha
    FROM apiome.pact_publication p
    JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
    JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
    WHERE p.consumer_id = %s::uuid AND p.provider_id = %s::uuid AND v.seq < %s AND v.deleted_at IS NULL
"""
_WITH_TAG = (
    " AND EXISTS (SELECT 1 FROM apiome.pacticipant_version_tag t"
    " WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id AND t.name = %s)"
)
_ON_BRANCH = (
    " AND EXISTS (SELECT 1 FROM apiome.pacticipant_branch_version bv"
    " JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id"
    " WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id AND b.name = %s)"
)

#: Provider versions that should verify a pact: main-branch head, deployed, released.
_REQUIRED = """
    SELECT v.id::text AS version_id, v.number, v.seq, 'latest from main branch' AS description, b.name AS branch
    FROM apiome.pacticipant pr
    JOIN apiome.pacticipant_branch b ON b.pacticipant_id = pr.id AND b.name = pr.main_branch
    JOIN apiome.pacticipant_version v ON v.id = b.head_version_id AND v.pacticipant_id = pr.id
    WHERE pr.id = %(provider)s::uuid AND v.deleted_at IS NULL
    UNION ALL
    SELECT v.id::text, v.number, v.seq, 'deployed in ' || e.name, NULL
    FROM apiome.deployed_version d
    JOIN apiome.pacticipant_version v ON v.id = d.version_id AND v.pacticipant_id = d.pacticipant_id
    JOIN apiome.pact_environment e ON e.id = d.environment_id AND e.tenant_id = d.tenant_id
    WHERE d.pacticipant_id = %(provider)s::uuid AND d.currently_deployed AND v.deleted_at IS NULL
    UNION ALL
    SELECT v.id::text, v.number, v.seq, 'released in ' || e.name, NULL
    FROM apiome.released_version r
    JOIN apiome.pacticipant_version v ON v.id = r.version_id AND v.pacticipant_id = r.pacticipant_id
    JOIN apiome.pact_environment e ON e.id = r.environment_id AND e.tenant_id = r.tenant_id
    WHERE r.pacticipant_id = %(provider)s::uuid AND r.currently_supported AND v.deleted_at IS NULL
"""

#: A version's branches, most recently recorded last, and its tags.
_VERSION_LABELS = """
    SELECT
      COALESCE((SELECT array_agg(b.name ORDER BY bv.created_at, b.name)
                FROM apiome.pacticipant_branch_version bv
                JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id), ARRAY[]::text[]) AS branches,
      COALESCE((SELECT array_agg(t.name ORDER BY t.name)
                FROM apiome.pacticipant_version_tag t
                WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id), ARRAY[]::text[]) AS tags,
      v.id::text AS id, v.seq, v.build_url
    FROM apiome.pacticipant_version v
    WHERE v.pacticipant_id = %s::uuid AND v.number = %s AND v.deleted_at IS NULL
"""


class RequiredVerification:
    """A provider version that has not verified a pact yet and should.

    Attributes:
        number: The provider version.
        branch: The branch to check out: the main branch when that is why it is listed, else the
            branch the version was recorded on last.
        descriptions: Why it is listed, without repeats.
    """

    def __init__(self, number: str, branch: Optional[str], descriptions: List[str]) -> None:
        """Hold the version.

        Args:
            number: The provider version.
            branch: Its branch.
            descriptions: Why it is listed.
        """
        self.number = number
        self.branch = branch
        self.descriptions = descriptions


def pact_url(base: str, provider_slug: str, consumer_slug: str, sha: str, consumer_version: str) -> str:
    """The value of ``${pactbroker.pactUrl}``: the pact by content, naming the consumer version.

    The Pact Broker's form — the pact version URL with the consumer version in its metadata
    segment — so a verifier that fetches it publishes its result for that consumer version.

    Args:
        base: The broker base URL.
        provider_slug: The provider's handle.
        consumer_slug: The consumer's handle.
        sha: The pact version.
        consumer_version: The consumer version that published it.

    Returns:
        The URL.
    """
    pair = f"{base}/pacts/provider/{quote(provider_slug, safe='')}/consumer/{quote(consumer_slug, safe='')}"
    return f"{pair}/pact-version/{sha}/metadata/{encode_metadata({'cvn': consumer_version})}"


def verification_result_url(base: str, provider_slug: str, consumer_slug: str, sha: str, number: int) -> str:
    """The value of ``${pactbroker.verificationResultUrl}``.

    Args:
        base: The broker base URL.
        provider_slug: The provider's handle.
        consumer_slug: The consumer's handle.
        sha: The verified pact version.
        number: The result's number.

    Returns:
        The URL of the verification result.
    """
    pair = f"{base}/pacts/provider/{quote(provider_slug, safe='')}/consumer/{quote(consumer_slug, safe='')}"
    return f"{pair}/pact-version/{sha}/verification-results/{number}"


def _one(cursor: Any, query: str, params: Any) -> Optional[Dict[str, Any]]:
    """Run a query and return its first row as a dict, or ``None``."""
    cursor.execute(query, params)
    row = cursor.fetchone()
    return dict(row) if row else None


def _pacticipant_id(cursor: Any, tenant_id: str, slug: str) -> Optional[str]:
    """The id of the tenant's pacticipant with this handle."""
    row = _one(
        cursor,
        "SELECT id::text AS id FROM apiome.pacticipant"
        " WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
        (tenant_id, slug),
    )
    return row["id"] if row else None


def _pacticipant_labels(cursor: Any, pacticipant_id: str) -> List[str]:
    """A pacticipant's labels, by name (PFX-1.11), for ``${pactbroker.consumerLabels}`` and the like."""
    cursor.execute(
        "SELECT name FROM apiome.pacticipant_label WHERE pacticipant_id = %s::uuid ORDER BY name",
        (pacticipant_id,),
    )
    return [row["name"] for row in cursor.fetchall() or []]


def _version_labels(cursor: Any, pacticipant_id: str, number: str) -> Dict[str, Any]:
    """A version's id, order, build URL, branches (latest last) and tags; empty when unknown."""
    row = _one(cursor, _VERSION_LABELS, (pacticipant_id, number))
    return row or {"id": None, "seq": None, "build_url": None, "branches": [], "tags": []}


def content_changed(
    cursor: Any,
    consumer_id: str,
    provider_id: str,
    version_seq: int,
    sha: str,
    *,
    branches: Sequence[str],
    tags: Sequence[str],
) -> bool:
    """Whether a newly published pact differs from what came before it.

    The pact is compared with the pact of the latest earlier consumer version on each of its
    branches and with each of its tags; a version with neither is compared with the latest earlier
    version of any kind. It has changed when any comparison finds different content, or nothing
    to compare with (the first pact on a new branch is a change: nobody has verified it there).

    Args:
        cursor: An open cursor.
        consumer_id: The consumer.
        provider_id: The provider.
        version_seq: The publishing version's order of recording.
        sha: The published content.
        branches: The publishing version's branches.
        tags: The publishing version's tags.

    Returns:
        True when the content is new in at least one of those lines.
    """
    comparisons: List[Tuple[str, Tuple[Any, ...]]] = [(_ON_BRANCH, (branch,)) for branch in branches]
    comparisons += [(_WITH_TAG, (tag,)) for tag in tags]
    if not comparisons:
        comparisons = [("", ())]
    for extra, params in comparisons:
        previous = _one(
            cursor,
            _PREVIOUS_SHA + extra + " ORDER BY v.seq DESC LIMIT 1",
            (consumer_id, provider_id, version_seq, *params),
        )
        if previous is None or str(previous["sha"]).strip() != sha:
            return True
    return False


def required_verifications(
    cursor: Any, consumer_id: str, provider_id: str, sha: str
) -> List[RequiredVerification]:
    """The provider versions that should verify a pact and have not.

    The head of the provider's main branch and every provider version currently deployed or
    released, each listed once however many reasons name it, without those that already have a
    verification result for this pact content.

    Args:
        cursor: An open cursor.
        consumer_id: The consumer.
        provider_id: The provider.
        sha: The pact version.

    Returns:
        The versions, in the order they were recorded.
    """
    cursor.execute(
        f"""
        WITH candidates AS ({_REQUIRED})
        SELECT c.version_id, c.number, c.seq, c.description, c.branch,
               (SELECT b.name FROM apiome.pacticipant_branch_version bv
                JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                WHERE bv.version_id = c.version_id::uuid AND bv.pacticipant_id = %(provider)s::uuid
                ORDER BY bv.created_at DESC, b.name LIMIT 1) AS recorded_branch
        FROM candidates c
        WHERE NOT EXISTS (
            SELECT 1 FROM apiome.verification_result r
            JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
            WHERE pv.consumer_id = %(consumer)s::uuid AND pv.provider_id = %(provider)s::uuid
              AND pv.sha = %(sha)s AND r.provider_version_id = c.version_id::uuid
        )
        ORDER BY c.seq, c.description
        """,
        {"provider": provider_id, "consumer": consumer_id, "sha": sha},
    )
    by_version: Dict[str, RequiredVerification] = {}
    for row in cursor.fetchall() or []:
        required = by_version.setdefault(
            row["version_id"], RequiredVerification(row["number"], row.get("recorded_branch"), [])
        )
        if row.get("branch"):
            required.branch = row["branch"]  # The main branch wins: it is the reason, not a guess.
        if row["description"] not in required.descriptions:
            required.descriptions.append(row["description"])
    return list(by_version.values())


def _latest_main_verification(cursor: Any, consumer_id: str, provider_id: str, sha: str) -> Optional[Dict[str, Any]]:
    """The latest result for this pact content from the provider's main branch, if any."""
    return _one(
        cursor,
        """
        SELECT r.number, r.success, v.number AS provider_version, r.provider_branch
        FROM apiome.verification_result r
        JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
        JOIN apiome.pacticipant pr ON pr.id = r.provider_id
        JOIN apiome.pacticipant_version v ON v.id = r.provider_version_id
        WHERE pv.consumer_id = %s::uuid AND pv.provider_id = %s::uuid AND pv.sha = %s
          AND r.provider_branch IS NOT NULL AND r.provider_branch = pr.main_branch
          AND v.deleted_at IS NULL
        ORDER BY r.seq DESC LIMIT 1
        """,
        (consumer_id, provider_id, sha),
    )


def _fire(
    cursor: Any,
    tenant_id: str,
    event_name: str,
    consumer_id: str,
    provider_id: str,
    parameters: Dict[str, str],
    *,
    consumer_version_number: Optional[str],
    sha: str,
    verification_number: Optional[int] = None,
) -> List[str]:
    """Queue one delivery of ``event_name`` per webhook that listens for it."""
    return [
        enqueue_triggered_webhook(
            cursor,
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            consumer_id=consumer_id,
            provider_id=provider_id,
            event_name=event_name,
            parameters=parameters,
            consumer_version_number=consumer_version_number,
            sha=sha,
            verification_number=verification_number,
        )
        for webhook_id in find_webhooks_to_trigger(cursor, tenant_id, consumer_id, provider_id, event_name)
    ]


def _publish_events_for_pact(
    cursor: Any, tenant_id: str, base: str, outcome: PublishOutcome, published: PublishedPact
) -> List[str]:
    """Queue the events of one stored or replaced pact."""
    pact = published.pact
    consumer_id = outcome.consumer.id
    provider_id = _pacticipant_id(cursor, tenant_id, pact.provider_slug)
    if provider_id is None:
        return []
    version = outcome.version.version
    # The record lists branches by name; the branch of this build is the one recorded last.
    recorded = _version_labels(cursor, consumer_id, pact.consumer_version)["branches"]
    main = _latest_main_verification(cursor, consumer_id, provider_id, pact.sha)
    consumer_labels = _pacticipant_labels(cursor, consumer_id)
    provider_labels = _pacticipant_labels(cursor, provider_id)

    def parameters(event_name: str, **extra: Any) -> Dict[str, str]:
        values: Dict[str, Any] = {
            "event_name": event_name,
            "consumer_name": pact.consumer_name,
            "provider_name": pact.provider_name,
            "consumer_labels": consumer_labels,
            "provider_labels": provider_labels,
            "consumer_version_number": pact.consumer_version,
            "consumer_version_tags": version.tags,
            "consumer_version_branch": recorded[-1] if recorded else None,
            "pact_url": pact_url(base, pact.provider_slug, pact.consumer_slug, pact.sha, pact.consumer_version),
            "build_url": version.build_url,
        }
        if main is not None:
            values.update(
                provider_version_number=main["provider_version"],
                provider_version_branch=main.get("provider_branch"),
                verification_success=bool(main["success"]),
                verification_result_url=verification_result_url(
                    base, pact.provider_slug, pact.consumer_slug, pact.sha, int(main["number"])
                ),
            )
        values.update(extra)
        return template_parameters(**values)

    def fire(event_name: str, **extra: Any) -> List[str]:
        return _fire(
            cursor,
            tenant_id,
            event_name,
            consumer_id,
            provider_id,
            parameters(event_name, **extra),
            consumer_version_number=pact.consumer_version,
            sha=pact.sha,
        )

    queued = fire(EVENT_PUBLISHED)
    if published.replaced or content_changed(
        cursor, consumer_id, provider_id, version.seq, pact.sha, branches=version.branches, tags=version.tags
    ):
        queued += fire(EVENT_CONTENT_CHANGED)
    for required in required_verifications(cursor, consumer_id, provider_id, pact.sha):
        queued += fire(
            EVENT_REQUIRING_VERIFICATION,
            provider_version_number=required.number,
            provider_version_branch=required.branch,
            provider_version_descriptions=required.descriptions,
            # Not verified by this provider version yet, whatever the main branch said earlier.
            verification_success=None,
            verification_result_url="",
        )
    if outcome.version.branch_created:
        queued += fire(EVENT_BRANCH_CREATED)
    return queued


def fire_publish_events(db: Any, tenant_id: str, base: str, outcome: PublishOutcome) -> List[str]:
    """Queue the webhooks of a publish request that has committed.

    Args:
        db: The database.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used; the links in the parameters start with it.
        outcome: What the request stored.

    Returns:
        The ids of the queued firings. Empty when nothing changed, no webhook listens, or queueing
        failed (which is logged, never raised).
    """
    changed = [published for published in outcome.pacts if published.created or published.replaced]
    if not changed:
        return []

    def work(cursor: Any) -> List[str]:
        queued: List[str] = []
        for published in changed:
            queued += _publish_events_for_pact(cursor, tenant_id, base, outcome, published)
        return queued

    try:
        return list(db._guarded_tx(work) or [])
    except Exception:  # noqa: BLE001 - a webhook problem never fails the publish
        logger.exception("contract webhooks: failed to queue publish events for tenant %s", tenant_id)
        return []


def fire_verification_events(db: Any, tenant_id: str, base: str, result: VerificationResultRecord) -> List[str]:
    """Queue the webhooks of a verification result that has committed.

    Args:
        db: The database.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used.
        result: The stored result.

    Returns:
        The ids of the queued firings; empty when no webhook listens or queueing failed (logged).
    """

    def work(cursor: Any) -> List[str]:
        consumer_id = _pacticipant_id(cursor, tenant_id, result.consumer_slug)
        provider_id = _pacticipant_id(cursor, tenant_id, result.provider_slug)
        if consumer_id is None or provider_id is None:
            return []
        consumer_version = result.consumer_version or ""
        consumer_labels = _version_labels(cursor, consumer_id, consumer_version)
        provider_labels = _version_labels(cursor, provider_id, result.provider_version)
        consumer_pacticipant_labels = _pacticipant_labels(cursor, consumer_id)
        provider_pacticipant_labels = _pacticipant_labels(cursor, provider_id)
        queued: List[str] = []
        outcome_event = EVENT_VERIFICATION_SUCCEEDED if result.success else EVENT_VERIFICATION_FAILED
        for event_name in (EVENT_VERIFICATION_PUBLISHED, outcome_event):
            parameters = template_parameters(
                event_name=event_name,
                consumer_name=result.consumer_name,
                provider_name=result.provider_name,
                consumer_labels=consumer_pacticipant_labels,
                provider_labels=provider_pacticipant_labels,
                consumer_version_number=consumer_version,
                consumer_version_tags=consumer_labels["tags"],
                consumer_version_branch=(consumer_labels["branches"] or [None])[-1],
                pact_url=pact_url(base, result.provider_slug, result.consumer_slug, result.sha, consumer_version),
                provider_version_number=result.provider_version,
                provider_version_tags=provider_labels["tags"],
                provider_version_branch=result.provider_branch or (provider_labels["branches"] or [None])[-1],
                verification_result_url=verification_result_url(
                    base, result.provider_slug, result.consumer_slug, result.sha, result.number
                ),
                verification_success=result.success,
                build_url=result.build_url,
            )
            queued += _fire(
                cursor,
                tenant_id,
                event_name,
                consumer_id,
                provider_id,
                parameters,
                consumer_version_number=consumer_version or None,
                sha=result.sha,
                verification_number=result.number,
            )
        return queued

    try:
        return list(db._guarded_tx(work) or [])
    except Exception:  # noqa: BLE001 - a webhook problem never fails the verification
        logger.exception("contract webhooks: failed to queue verification events for tenant %s", tenant_id)
        return []
