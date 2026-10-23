"""Project activity timeline correlated with schema revisions — #2594.

A project's history is written to two append-only ledgers:

* ``apiome.workflow_audit`` (V080) — version workflow actions: publish, merge, rollback, push,
  pull, tag create/update/delete, gate decisions; ``version_id`` is the revision the event
  concerns;
* ``apiome.version_protection_audit`` (V074) — protection policy changes (branch and tag
  protection, revision locks), admin overrides and denied attempts; ``resource_type`` /
  ``resource_id`` name the branch, tag or revision.

The timeline reads both as one newest-first stream (``Database.list_project_timeline``). This
module holds the rules that do not need the database:

* :func:`classify` — the **kind** of an event (``publish``, ``merge``, ``tag``, ``protection`` or
  ``other``), so a client can filter and colour the stream;
* :func:`kind_filter` — the SQL-side filter for a set of kinds;
* :func:`visible_outcomes` — role-based visibility: failures and denied attempts are shown to
  tenant administrators only;
* :func:`to_event` — one ledger row as a :class:`TimelineEvent`, with the revision it concerns, the
  revision it merged from and the routes that open that revision in the revision DAG (#2593).

Retention: neither ledger is pruned today; see the *Retention* section of the docs page
``apiome-docs/docs/build/project-timeline.md`` for the hooks a retention job uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple
from uuid import UUID

__all__ = [
    "ALL_KINDS",
    "DEFAULT_TIMELINE_LIMIT",
    "KIND_MERGE",
    "KIND_OTHER",
    "KIND_PROTECTION",
    "KIND_PUBLISH",
    "KIND_TAG",
    "MAX_TIMELINE_LIMIT",
    "PUBLIC_OUTCOMES",
    "SOURCE_PROTECTION",
    "SOURCE_WORKFLOW",
    "TimelineEvent",
    "classify",
    "kind_filter",
    "parse_kinds",
    "publish_audit_detail",
    "revision_links",
    "tag_audit_detail",
    "to_event",
    "to_events",
    "visible_outcomes",
]

#: Events a timeline page returns when the caller does not say.
DEFAULT_TIMELINE_LIMIT = 50
#: The most events one page may return.
MAX_TIMELINE_LIMIT = 200

#: Row came from ``apiome.workflow_audit``.
SOURCE_WORKFLOW = "workflow"
#: Row came from ``apiome.version_protection_audit``.
SOURCE_PROTECTION = "protection"

KIND_PUBLISH = "publish"
KIND_MERGE = "merge"
KIND_TAG = "tag"
KIND_PROTECTION = "protection"
KIND_OTHER = "other"

#: Every kind, in display order.
ALL_KINDS: Tuple[str, ...] = (KIND_PUBLISH, KIND_MERGE, KIND_TAG, KIND_PROTECTION, KIND_OTHER)

#: Workflow-ledger actions per kind. Every protection-ledger row is ``protection``; a workflow
#: action not listed here is ``other`` (pushes, pulls, gate assessments, changelog runs …).
WORKFLOW_ACTION_KINDS: Mapping[str, str] = {
    "version.publish": KIND_PUBLISH,
    "version.merge": KIND_MERGE,
    "version.rollback": KIND_MERGE,
    "tag.create": KIND_TAG,
    "tag.update": KIND_TAG,
    "tag.delete": KIND_TAG,
    "version.publish_checks_override": KIND_PROTECTION,
    "version.compat_gate_override": KIND_PROTECTION,
    "version.immutability_override": KIND_PROTECTION,
    "version.default_branch_promoted": KIND_PROTECTION,
}

#: Outcomes every caller with ``versions:view`` sees. Anything else — ``failure`` on the workflow
#: ledger, ``denied`` on the protection ledger — is an attempt that did not happen and is shown to
#: tenant administrators only.
PUBLIC_OUTCOMES: Tuple[str, ...] = ("success", "allowed", "policy_change")


def classify(source: str, action: str) -> str:
    """The kind of one ledger row.

    Args:
        source: :data:`SOURCE_WORKFLOW` or :data:`SOURCE_PROTECTION`.
        action: The row's ``action`` (e.g. ``version.publish``).

    Returns:
        One of :data:`ALL_KINDS`.
    """
    if source == SOURCE_PROTECTION:
        return KIND_PROTECTION
    return WORKFLOW_ACTION_KINDS.get(action, KIND_OTHER)


def parse_kinds(raw: Optional[Iterable[str]]) -> Optional[FrozenSet[str]]:
    """Normalise a ``?kind=`` filter.

    Accepts repeated values and comma-separated lists, ignores blanks and case.

    Args:
        raw: The query values, or ``None``.

    Returns:
        The set of kinds, or ``None`` when no filter was given (or it names every kind).

    Raises:
        ValueError: A value is not one of :data:`ALL_KINDS`.
    """
    if not raw:
        return None
    kinds = set()
    for value in raw:
        for part in str(value or "").split(","):
            kind = part.strip().lower()
            if not kind:
                continue
            if kind not in ALL_KINDS:
                raise ValueError(f"Unknown kind {kind!r}; expected one of {', '.join(ALL_KINDS)}")
            kinds.add(kind)
    if not kinds or kinds == set(ALL_KINDS):
        return None
    return frozenset(kinds)


def kind_filter(kinds: Optional[FrozenSet[str]]) -> Optional[Dict[str, Any]]:
    """The SQL-side shape of a kind filter.

    Args:
        kinds: From :func:`parse_kinds`; ``None`` means no filter.

    Returns:
        ``None`` for no filter, else a dict with:

        * ``workflow_actions`` — workflow-ledger actions to include (listed kinds);
        * ``workflow_other`` — also include workflow actions outside :data:`WORKFLOW_ACTION_KINDS`;
        * ``excluded_actions`` — the mapped actions, which ``workflow_other`` must leave out;
        * ``protection_ledger`` — include every protection-ledger row.
    """
    if kinds is None:
        return None
    return {
        "workflow_actions": sorted(a for a, k in WORKFLOW_ACTION_KINDS.items() if k in kinds),
        "workflow_other": KIND_OTHER in kinds,
        "excluded_actions": sorted(WORKFLOW_ACTION_KINDS),
        "protection_ledger": KIND_PROTECTION in kinds,
    }


def visible_outcomes(is_tenant_admin: bool) -> Optional[Tuple[str, ...]]:
    """The outcomes a caller may see.

    Args:
        is_tenant_admin: Whether the caller administers the tenant.

    Returns:
        ``None`` (every outcome) for an administrator, else :data:`PUBLIC_OUTCOMES`.
    """
    return None if is_tenant_admin else PUBLIC_OUTCOMES


def revision_links(tenant_slug: str, project_id: str, revision_id: str) -> Dict[str, str]:
    """The routes that open one revision from the timeline, and come back to it.

    Args:
        tenant_slug: The tenant in the request path.
        project_id: The project.
        revision_id: The revision (``versions.id``).

    Returns:
        ``revision`` (the revision itself), ``ancestors`` (its place in the DAG, #2593) and
        ``timeline`` (this timeline narrowed to the revision).
    """
    base = f"/v1/versions/{tenant_slug}/{project_id}"
    return {
        "revision": f"{base}/{revision_id}",
        "ancestors": f"{base}/{revision_id}/ancestors",
        "timeline": f"{base}/timeline?revisionId={revision_id}",
    }


def _uuid_or_none(value: Any) -> Optional[str]:
    """``value`` as a canonical UUID string, or ``None`` when it is not one."""
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _str_or_none(value: Any) -> Optional[str]:
    """A non-blank string, or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class TimelineEvent:
    """One event on a project timeline.

    Attributes:
        id: The ledger row id.
        source: :data:`SOURCE_WORKFLOW` or :data:`SOURCE_PROTECTION`.
        kind: One of :data:`ALL_KINDS`.
        action: The ledger action (``version.publish``, ``tag.update``, ``branch.protection_policy`` …).
        outcome: ``success`` / ``failure`` (workflow) or ``allowed`` / ``denied`` / ``policy_change``.
        actor_id: Who acted; ``None`` for system work or a deleted user.
        occurred_at: When the row was written.
        revision_id: The revision the event concerns, when there is one.
        version_label: That revision's version string.
        merge_from_revision_id: For a merge (or the publish of a merge revision), the revision merged in.
        merge_from_branch: The branch merged from, when the ledger recorded it.
        branch_name: The branch the event touched (merge target, protected branch).
        tag_name: The tag the event touched.
        resource_type: Protection ledger only: ``version``, ``version_branch`` or ``version_tag``.
        resource_id: Protection ledger only: the id of that resource.
        detail: The ledger's structured detail, unchanged.
        links: From :func:`revision_links` when ``revision_id`` is set.
    """

    id: str
    source: str
    kind: str
    action: str
    outcome: str
    actor_id: Optional[str]
    occurred_at: Any
    revision_id: Optional[str] = None
    version_label: Optional[str] = None
    merge_from_revision_id: Optional[str] = None
    merge_from_branch: Optional[str] = None
    branch_name: Optional[str] = None
    tag_name: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    links: Dict[str, str] = field(default_factory=dict)


def to_event(row: Mapping[str, Any], *, tenant_slug: str, project_id: str) -> TimelineEvent:
    """One ``Database.list_project_timeline`` row as a :class:`TimelineEvent`.

    The merge-from revision is read from the detail the ledgers already write: ``sourceTipRevisionId``
    on ``version.merge``, ``mergeParentRevisionId`` on ``version.publish``.

    Args:
        row: Keys ``id``, ``source``, ``action``, ``outcome``, ``actor_id``, ``revision_id``,
            ``version_label``, ``resource_type``, ``resource_id``, ``detail``, ``created_at``.
        tenant_slug: The tenant in the request path (for links).
        project_id: The project (for links).

    Returns:
        The event.
    """
    source = str(row.get("source") or SOURCE_WORKFLOW)
    action = str(row.get("action") or "")
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else None
    d: Mapping[str, Any] = detail or {}
    revision_id = _uuid_or_none(row.get("revision_id"))
    merge_from = _uuid_or_none(d.get("sourceTipRevisionId") or d.get("mergeParentRevisionId"))
    branch = _str_or_none(d.get("targetBranch") or d.get("branchName"))
    return TimelineEvent(
        id=str(row.get("id")),
        source=source,
        kind=classify(source, action),
        action=action,
        outcome=str(row.get("outcome") or ""),
        actor_id=_uuid_or_none(row.get("actor_id")),
        occurred_at=row.get("created_at"),
        revision_id=revision_id,
        version_label=_str_or_none(row.get("version_label")),
        merge_from_revision_id=merge_from,
        merge_from_branch=_str_or_none(d.get("sourceBranch")),
        branch_name=branch,
        tag_name=_str_or_none(d.get("tagName")),
        resource_type=_str_or_none(row.get("resource_type")),
        resource_id=_uuid_or_none(row.get("resource_id")),
        detail=detail,
        links=revision_links(tenant_slug, project_id, revision_id) if revision_id else {},
    )


def to_events(rows: Iterable[Mapping[str, Any]], *, tenant_slug: str, project_id: str) -> List[TimelineEvent]:
    """:func:`to_event` over many rows, in order."""
    return [to_event(r, tenant_slug=tenant_slug, project_id=project_id) for r in rows]


def _compact(values: Mapping[str, Any]) -> Dict[str, Any]:
    """``values`` without its ``None`` entries."""
    return {k: v for k, v in values.items() if v is not None}


def publish_audit_detail(revision: Mapping[str, Any], visibility: Optional[str]) -> Dict[str, Any]:
    """The ``workflow_audit.detail`` of a ``version.publish`` row.

    Args:
        revision: The ``versions`` row as it was read before publishing.
        visibility: The visibility the publish set.

    Returns:
        ``visibility``, ``versionLine`` and the revision's DAG parents (``parentRevisionId``,
        ``mergeParentRevisionId``) — the latter is the timeline's ``mergeFromRevisionId``.
    """
    return _compact(
        {
            "visibility": visibility,
            "versionLine": _str_or_none(revision.get("version_id")),
            "parentRevisionId": _uuid_or_none(revision.get("parent_version_id")),
            "mergeParentRevisionId": _uuid_or_none(revision.get("merge_parent_version_id")),
        }
    )


def tag_audit_detail(
    tag: Mapping[str, Any],
    *,
    from_revision_id: Any = None,
    changes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """The ``workflow_audit.detail`` of a ``tag.create`` / ``tag.update`` / ``tag.delete`` row.

    Args:
        tag: The ``version_tags`` row (after the change; before it for a delete).
        from_revision_id: For a move, the revision the tag pointed at before.
        changes: For an update, which fields changed (``revision``, ``immutable``, ``protected``,
            ``message``).

    Returns:
        ``tagId``, ``tagName``, ``revisionId`` (where the tag points), ``fromRevisionId`` when it
        moved, the ``immutable`` / ``protected`` flags, and ``changes``.
    """
    to_rev = _uuid_or_none(tag.get("version_id"))
    from_rev = _uuid_or_none(from_revision_id)
    return _compact(
        {
            "tagId": _uuid_or_none(tag.get("id")),
            "tagName": _str_or_none(tag.get("name")),
            "revisionId": to_rev,
            "fromRevisionId": from_rev if from_rev and from_rev != to_rev else None,
            "immutable": bool(tag.get("immutable")) if "immutable" in tag else None,
            "protected": bool(tag.get("protected")) if "protected" in tag else None,
            "changes": list(changes) if changes else None,
        }
    )
