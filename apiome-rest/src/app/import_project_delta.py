"""Import a new version: what the incoming spec changes on the project's latest version — IXH-3.7 (#6321).

When the Import wizard's slug resolves to an existing **publishable Project**, the commit lands
the spec as a *new version* on top of that project's latest revision. This module answers, before
anything is written, what that new version would change:

* **Target resolution** mirrors the commit (``getProjectIdBySlugTx`` /
  ``getLatestVersionUuidForProjectTx`` in ``apiome-ui/lib/db/import-helper.ts``): an explicit
  ``project_id`` wins, otherwise the slug is trimmed and lower-cased and matched against the
  tenant's live projects; the baseline is the project's most recently created revision. A slug
  that matches nothing, a **catalog item** (``publishable = false`` — the IXH-3.4 re-import delta
  in :mod:`app.import_preview_manifest` covers those), or a project with no revision yet is *not*
  a new version, and :func:`resolve_project_delta_target` returns ``None`` (the route answers
  ``204``).
* **Baseline document**: the latest revision's OpenAPI is rebuilt from the database with
  :func:`app.compatibility_engine.openapi_for_revision` — the generator Versions → Compare, the
  compatibility gate and the #6319 shared revision loader (``export_source.build_revision_source``)
  use for decomposed OpenAPI projects, which keep no captured source.
* **Classification**: :class:`app.compatibility_engine.CompatibilityCheckEngine` with default
  rules — the same safe / breaking / unknown verdict as Versions → Compare and the gate.
* **Structural list**: :func:`app.source_change_review.diff_documents` over the API surface
  (``paths``, ``webhooks``, ``components``), one row per deepest changed pointer, each graded by
  the compatibility findings that cover it and ranked breaking first.

Everything in :func:`build_project_delta` is pure (no DB, inputs never mutated), so the tests can
pin the whole table without a database.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .compatibility_engine import CompatibilityCheckEngine, openapi_for_revision
from .models import CompatibilityFindingOut
from .preservation_envelope import parse_pointer
from .source_change_review import diff_documents, scope_for_pointer

__all__ = [
    "DELTA_SECTIONS",
    "MAX_DELTA_CHANGES",
    "ProjectDeltaChange",
    "ProjectDeltaCounts",
    "ProjectDeltaRequest",
    "ProjectDeltaResponse",
    "build_project_delta",
    "change_label",
    "resolve_project_delta_target",
    "run_project_delta",
]

logger = logging.getLogger(__name__)

#: Top-level document sections the change list covers. ``info``, ``servers``, ``tags`` and the
#: like always differ between a hand-written spec and the generator's rebuild (version label,
#: default description), so listing them would bury the API changes under noise. The
#: side-by-side view still shows both documents in full.
DELTA_SECTIONS = ("paths", "webhooks", "components")

#: Upper bound on change rows returned. A larger delta is cut here and says so
#: (``truncated`` / ``counts.total``) — never silently.
MAX_DELTA_CHANGES = 5000

ChangeKind = Literal["added", "changed", "removed"]
Severity = Literal["breaking", "unknown", "safe"]

#: ``diff_documents`` kinds → the wizard's verbs.
_KIND_FOR_DIFF: Dict[str, ChangeKind] = {
    "addition": "added",
    "update": "changed",
    "deletion": "removed",
}

#: Rank order: breaking first, then unknown, then safe, then ungraded.
_SEVERITY_RANK: Dict[Optional[str], int] = {"breaking": 0, "unknown": 1, "safe": 2, None: 3}

#: Within a severity: removals first (what consumers lose), then changes, then additions.
_KIND_RANK: Dict[str, int] = {"removed": 0, "changed": 1, "added": 2}


# ===========================================================================
# Models
# ===========================================================================


class ProjectDeltaRequest(BaseModel):
    """What the wizard sends: the incoming document and the project the commit would target."""

    model_config = ConfigDict(extra="forbid")

    document: Dict[str, Any] = Field(
        ...,
        description="The incoming OpenAPI document, parsed (the wizard's analyzed document).",
    )
    project_slug: Optional[str] = Field(
        default=None,
        description="The slug the commit would use; trimmed and lower-cased like the commit.",
    )
    project_id: Optional[str] = Field(
        default=None,
        description="An explicitly targeted project id; wins over `project_slug` when both are set.",
    )
    include_documents: bool = Field(
        default=True,
        description="Return both documents for the side-by-side view (false for counts only).",
    )


class ProjectDeltaChange(BaseModel):
    """One structural change between the latest version and the incoming spec."""

    kind: ChangeKind = Field(..., description="added, changed or removed.")
    scope: str = Field(
        ..., description="document / path / operation / component / schema (source-review scope)."
    )
    entity: str = Field(..., description="Stable group key, e.g. `DELETE /refunds/{id}` or `Refund`.")
    label: str = Field(..., description="Human label, e.g. `schema Refund.amount minimum`.")
    pointer: str = Field(..., description="RFC 6901 pointer of the change in the documents.")
    before: Any = Field(
        default=None,
        description="Old value when scalar; a `{n keys}` / `[n items]` preview for containers.",
    )
    after: Any = Field(
        default=None,
        description="New value when scalar; a `{n keys}` / `[n items]` preview for containers.",
    )
    severity: Optional[Severity] = Field(
        default=None,
        description=(
            "Worst compatibility category among the findings covering this pointer; null when no "
            "compatibility rule grades it (ungraded — not implied safe)."
        ),
    )
    rules: List[str] = Field(
        default_factory=list, description="Compatibility rule ids covering this change."
    )
    message: Optional[str] = Field(
        default=None, description="The first covering finding's message, when graded."
    )


class ProjectDeltaCounts(BaseModel):
    """The summary bar's numbers."""

    added: int = 0
    changed: int = 0
    removed: int = 0
    breaking: int = Field(
        default=0,
        description="Breaking compatibility findings (the Versions → Compare / gate count).",
    )
    total: int = Field(default=0, description="Every structural change, before any truncation.")


class ProjectDeltaResponse(BaseModel):
    """The Changes step's payload."""

    project_id: str
    project_slug: str
    project_name: str
    base_revision_id: str = Field(..., description="The latest revision (`versions.id`) compared against.")
    base_version_label: str = Field(..., description="Its version label, e.g. `2.4.0`.")
    existing_version_labels: List[str] = Field(
        default_factory=list,
        description="Every live version label of the project, oldest first (#590). The wizard checks "
        "whether the import's version is already taken and, if so, offers a free sub-version "
        "(`1.0.0b`, `1.0.0c` …).",
    )
    overall: Severity = Field(..., description="The compatibility engine's overall verdict.")
    counts: ProjectDeltaCounts
    changes: List[ProjectDeltaChange] = Field(
        default_factory=list, description="Ranked: breaking first, then unknown, safe, ungraded."
    )
    truncated: bool = Field(
        default=False, description=f"True when more than {MAX_DELTA_CHANGES} changes were cut."
    )
    findings: List[CompatibilityFindingOut] = Field(
        default_factory=list, description="The compatibility engine's findings, as Compare reports them."
    )
    base_document: Optional[Dict[str, Any]] = Field(
        default=None, description="The latest version's OpenAPI (left side of the diff)."
    )
    incoming_document: Optional[Dict[str, Any]] = Field(
        default=None, description="The incoming spec (right side of the diff)."
    )


# ===========================================================================
# Pure builder
# ===========================================================================


def _preview(value: Any) -> Any:
    """A scalar as-is; a container as a short ``{n keys}`` / ``[n items]`` preview.

    Args:
        value: A JSON value from either document.

    Returns:
        The value itself for scalars (and ``None``), otherwise a preview string — whole subtrees
        belong in the side-by-side view, not in every row of the list.
    """
    if isinstance(value, dict):
        return f"{{{len(value)} {'key' if len(value) == 1 else 'keys'}}}"
    if isinstance(value, list):
        return f"[{len(value)} {'item' if len(value) == 1 else 'items'}]"
    return value


def change_label(pointer: str) -> str:
    """A reader-facing label for a change pointer.

    The entity comes first in the form the wizard's list uses — ``DELETE /refunds/{id}``,
    ``path /refunds``, ``schema Refund`` — and the remaining segments follow, with schema
    ``properties/<name>`` hops folded into ``.name``.

    Args:
        pointer: RFC 6901 pointer into an OpenAPI document.

    Returns:
        For example ``schema Refund.amount minimum`` for
        ``/components/schemas/Refund/properties/amount/minimum``.
    """
    scope, group = scope_for_pointer(pointer)
    segments = parse_pointer(pointer)
    if scope == "operation":
        head, rest = group, segments[3:]
    elif scope == "path":
        head, rest = f"path {group}", segments[2:]
    elif scope == "schema":
        head, rest = f"schema {group}", segments[3:]
    elif scope == "component":
        head, rest = f"component {group}", segments[3:]
    else:
        return "/".join(segments) or "document"

    words: List[str] = [head]
    index = 0
    while index < len(rest):
        if rest[index] == "properties" and index + 1 < len(rest):
            words[-1] = f"{words[-1]}.{rest[index + 1]}"
            index += 2
            continue
        words.append(rest[index])
        index += 1
    return " ".join(words)


def _covering_findings(dotted: str, findings: List[CompatibilityFindingOut]) -> List[CompatibilityFindingOut]:
    """Findings that grade a change at ``dotted``.

    A finding covers a change when it sits at the same location, at an ancestor of it (a
    constraint change under a property the engine flagged), or under it (an added or removed
    subtree whose members the engine graded one by one).

    Args:
        dotted: The change pointer in the compatibility engine's dotted form.
        findings: Every finding of the run.

    Returns:
        The covering findings, in the engine's deterministic order.
    """
    return [
        f
        for f in findings
        if f.path == dotted or dotted.startswith(f.path + ".") or f.path.startswith(dotted + ".")
    ]


def _worst(findings: List[CompatibilityFindingOut]) -> Optional[Severity]:
    """The worst category among ``findings`` (breaking > unknown > safe), or ``None`` for none."""
    best: Optional[Severity] = None
    for f in findings:
        category = f.category if f.category in ("breaking", "unknown", "safe") else "unknown"
        if _SEVERITY_RANK[category] < _SEVERITY_RANK[best]:
            best = category  # type: ignore[assignment]
    return best


def build_project_delta(
    base_document: Dict[str, Any],
    incoming_document: Dict[str, Any],
    *,
    max_changes: int = MAX_DELTA_CHANGES,
) -> Dict[str, Any]:
    """Diff and classify ``incoming_document`` against ``base_document``.

    Args:
        base_document: The latest version's OpenAPI (rebuilt from the database).
        incoming_document: The spec being imported.
        max_changes: Cap on returned change rows; the counts always cover every change.

    Returns:
        A dict with ``overall``, ``counts`` (:class:`ProjectDeltaCounts`), ``changes`` (ranked
        :class:`ProjectDeltaChange` rows), ``truncated`` and ``findings``
        (:class:`~app.models.CompatibilityFindingOut`) — the fields of
        :class:`ProjectDeltaResponse` that do not depend on the target project.
    """
    result = CompatibilityCheckEngine.run(base_document, incoming_document)
    findings = [CompatibilityFindingOut(**f) for f in result.finding_dicts]

    base_surface = {k: base_document.get(k) for k in DELTA_SECTIONS if k in base_document}
    incoming_surface = {k: incoming_document.get(k) for k in DELTA_SECTIONS if k in incoming_document}

    rows: List[ProjectDeltaChange] = []
    counts = ProjectDeltaCounts(
        breaking=sum(1 for f in findings if f.category == "breaking"),
    )
    for delta in diff_documents(base_surface, incoming_surface):
        kind = _KIND_FOR_DIFF[delta["kind"]]
        pointer = delta["pointer"]
        scope, group = scope_for_pointer(pointer)
        covering = _covering_findings(".".join(parse_pointer(pointer)), findings)
        setattr(counts, kind, getattr(counts, kind) + 1)
        rows.append(
            ProjectDeltaChange(
                kind=kind,
                scope=scope,
                entity=group,
                label=change_label(pointer),
                pointer=pointer,
                before=_preview(delta["before"]),
                after=_preview(delta["after"]),
                severity=_worst(covering),
                rules=sorted({f.rule for f in covering}),
                message=covering[0].message if covering else None,
            )
        )
    counts.total = len(rows)

    # Stable sort: within one (severity, kind) bucket the diff's own deterministic order holds.
    rows.sort(key=lambda r: (_SEVERITY_RANK[r.severity], _KIND_RANK[r.kind]))
    return {
        "overall": result.overall,
        "counts": counts,
        "changes": rows[:max_changes],
        "truncated": len(rows) > max_changes,
        "findings": findings,
    }


# ===========================================================================
# Target resolution + orchestration (DB)
# ===========================================================================


def resolve_project_delta_target(
    db: Any, tenant_id: str, *, project_slug: Optional[str], project_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """The project and latest revision an import would land on as a new version.

    Mirrors the commit's resolution (``getProjectIdBySlugTx`` / ``getLatestVersionUuidForProjectTx``):
    an explicit ``project_id`` first, otherwise the slug trimmed and lower-cased.

    Args:
        db: The database facade (``app.database.db``).
        tenant_id: The acting tenant; every read is scoped to it.
        project_slug: The slug the commit would use.
        project_id: An explicitly targeted project, if any.

    Returns:
        ``{"project": row, "version": row}``, or ``None`` when the import is not a new version of
        an existing Project — no match, a catalog item (``publishable = false``), or a project
        with no revision yet.
    """
    project: Optional[Dict[str, Any]] = None
    if project_id and project_id.strip():
        project = db.get_project_by_id(project_id.strip(), tenant_id)
    else:
        slug = (project_slug or "").strip().lower()
        if slug:
            project = db.get_project_by_slug(slug, tenant_id)
    if not project or project.get("publishable") is False:
        return None
    latest_id = db.get_latest_revision_id_for_project(str(project["id"]), tenant_id)
    if not latest_id:
        return None
    version = db.get_version_by_id(latest_id, tenant_id)
    if not version:
        return None
    return {"project": project, "version": version}


def run_project_delta(
    db: Any,
    request: ProjectDeltaRequest,
    *,
    tenant_id: str,
    tenant_slug: str,
) -> Optional[ProjectDeltaResponse]:
    """Resolve the target, rebuild its latest version, and diff the incoming spec against it.

    Args:
        db: The database facade.
        request: The wizard's request.
        tenant_id: The acting tenant.
        tenant_slug: Its slug (the generator stamps it into per-class descriptions).

    Returns:
        The delta, or ``None`` when the import is not a new version of an existing Project.

    Raises:
        HTTPException: From :func:`openapi_for_revision` when the revision's project vanished.
        Exception: Anything the generator or the engines raise; the route maps it to a 500 the
            wizard shows as a retryable error that never blocks the import.
    """
    target = resolve_project_delta_target(
        db, tenant_id, project_slug=request.project_slug, project_id=request.project_id
    )
    if target is None:
        return None
    project, version = target["project"], target["version"]
    base_document = openapi_for_revision(version, tenant_slug, tenant_id)
    delta = build_project_delta(base_document, request.document)
    return ProjectDeltaResponse(
        project_id=str(project["id"]),
        project_slug=str(project.get("slug") or ""),
        project_name=str(project.get("name") or project.get("slug") or ""),
        base_revision_id=str(version["id"]),
        base_version_label=str(version.get("version_id") or ""),
        existing_version_labels=db.list_version_labels_for_project(str(project["id"]), tenant_id),
        base_document=base_document if request.include_documents else None,
        incoming_document=request.document if request.include_documents else None,
        **delta,
    )
