"""The blast-radius line on each breaking change of a diff gate — CDG-3.6 (#5971).

``POST /v1/diff/{tenant}/classified`` with ``blastRadius: true`` (``apiome diff --blast-radius``, the
``diff-action`` PR comment) runs the CDG-3.3 blast radius (:mod:`app.blast_radius`) for every
breaking change against the **base** project and version, and states the answer in one line::

    affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated

* **N consumers**: the distinct consumers among the direct and transitive dependents of the change.
* **M teams**: the distinct owner teams of those consumers, named (a consumer without an owner
  counts toward N, not M).
* **K verification runs**: the latest verification runs that exercised an affected operation and
  are invalidated by the change.

A change is asked about once per pointer, and at most :data:`MAX_ANNOTATED_POINTERS` distinct
pointers are asked about per diff, so one huge diff cannot run thousands of traversals; changes past
the bound carry no line and the response says how many were skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .blast_radius import BlastRadiusRequest, blast_radius
from .declared_dependencies import DependencyValidationError

__all__ = [
    "MAX_ANNOTATED_POINTERS",
    "BlastRadiusAnnotations",
    "BlastRadiusDiffMeta",
    "BlastRadiusSummary",
    "BlastRadiusTeam",
    "annotate_breaking_changes",
    "summarize_blast_radius",
    "summary_line",
]

#: The most distinct breaking-change pointers one diff asks the blast radius about.
MAX_ANNOTATED_POINTERS = 50

#: The severity whose changes are annotated.
_BREAKING = "breaking"


class BlastRadiusTeam(BaseModel):
    """An owner team named in the line."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: Optional[str] = None


class BlastRadiusSummary(BaseModel):
    """What one breaking change affects, counted from its blast radius.

    Attributes:
        consumers: Distinct consumers among the change's direct and transitive dependents.
        teams: The distinct owner teams of those consumers, sorted by slug.
        verification_runs: Verification runs the change invalidates.
        truncated: True when the traversal hit its bound, so the counts are lower bounds.
        line: The sentence the diff gate prints.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    consumers: int = Field(description="Distinct consumers the change affects, directly or transitively.")
    teams: List[BlastRadiusTeam] = Field(
        default_factory=list, description="Owner teams of those consumers, sorted by slug."
    )
    verification_runs: int = Field(
        serialization_alias="verificationRuns", description="Verification runs the change invalidates."
    )
    truncated: bool = Field(default=False, description="True when the counts are lower bounds.")
    line: str = Field(
        description="e.g. `affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated`."
    )


def _plural(count: int, word: str) -> str:
    """``1 team`` / ``2 teams``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def summary_line(consumers: int, teams: Iterable[BlastRadiusTeam], verification_runs: int, *, truncated: bool) -> str:
    """The one-line statement of a summary.

    Args:
        consumers: N.
        teams: The owner teams (M is their count; their slugs are named).
        verification_runs: K.
        truncated: Prefix the counts with "at least".

    Returns:
        ``affects N consumers across M teams (a, b); K verification runs invalidated``. With no
        owned consumer the team part is left out; with no consumer at all it reads ``affects no
        registered consumers``.
    """
    team_list = list(teams)
    floor = "at least " if truncated else ""
    if consumers == 0:
        reach = "affects no registered consumers"
    else:
        reach = f"affects {floor}{_plural(consumers, 'consumer')}"
        if team_list:
            named = ", ".join(team.slug for team in team_list)
            reach += f" across {_plural(len(team_list), 'team')} ({named})"
    runs = (
        "no verification runs invalidated"
        if verification_runs == 0
        else (f"{floor}{_plural(verification_runs, 'verification run')} invalidated")
    )
    return f"{reach}; {runs}"


def summarize_blast_radius(answer: Mapping[str, Any]) -> BlastRadiusSummary:
    """Count a blast-radius answer into a summary.

    Args:
        answer: What :func:`app.blast_radius.blast_radius` returned.

    Returns:
        The summary, with its line.
    """
    consumers: Dict[str, Dict[str, Any]] = {}
    for entity in list(answer.get("direct") or []) + list(answer.get("transitive") or []):
        if entity.get("kind") == "consumer" and entity.get("id"):
            consumers.setdefault(str(entity["id"]), entity)
    teams: Dict[str, BlastRadiusTeam] = {}
    for entity in consumers.values():
        owner = entity.get("owner") or {}
        if owner.get("slug"):
            teams.setdefault(owner["slug"], BlastRadiusTeam(slug=owner["slug"], name=owner.get("name")))
    ordered = [teams[slug] for slug in sorted(teams)]
    runs = len((answer.get("invalidated_evidence") or {}).get("verification_runs") or [])
    truncated = bool(answer.get("truncated"))
    return BlastRadiusSummary(
        consumers=len(consumers),
        teams=ordered,
        verification_runs=runs,
        truncated=truncated,
        line=summary_line(len(consumers), ordered, runs, truncated=truncated),
    )


class BlastRadiusDiffMeta(BaseModel):
    """How the diff's breaking changes were annotated."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    annotated: int = Field(description="Breaking-change pointers that carry a `blastRadius`.")
    skipped: int = Field(description="Breaking-change pointers past the per-diff bound, left unannotated.")
    failed: int = Field(description="Pointers whose blast radius could not be computed.")
    limit: int = Field(description="The most distinct pointers one diff annotates.")


@dataclass
class BlastRadiusAnnotations:
    """The summaries for one diff.

    Attributes:
        by_pointer: Summary per annotated breaking-change pointer.
        skipped: Breaking-change pointers past :data:`MAX_ANNOTATED_POINTERS`, left unannotated.
        failed: Pointers whose blast radius could not be computed (left unannotated).
    """

    by_pointer: Dict[str, BlastRadiusSummary] = field(default_factory=dict)
    skipped: int = 0
    failed: int = 0

    def meta(self, limit: int = MAX_ANNOTATED_POINTERS) -> BlastRadiusDiffMeta:
        """The response-level counts."""
        return BlastRadiusDiffMeta(
            annotated=len(self.by_pointer), skipped=self.skipped, failed=self.failed, limit=limit
        )

    def lines(self) -> Dict[str, str]:
        """``{pointer: line}`` for the markdown renderer."""
        return {pointer: summary.line for pointer, summary in self.by_pointer.items()}


def annotate_breaking_changes(
    db: Any,
    tenant_id: str,
    project_id: str,
    version_id: Optional[str],
    changes: Iterable[Any],
    *,
    limit: int = MAX_ANNOTATED_POINTERS,
) -> BlastRadiusAnnotations:
    """Run the blast radius for each breaking change of a diff.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        project_id: The base project — the published contract its dependents declared against.
        version_id: The base revision (evidence is read for it); ``None`` uses the latest published.
        changes: Classified changes with ``severity`` and ``pointer``.
        limit: The most distinct pointers to ask about.

    Returns:
        The summaries. A pointer whose blast radius fails (for example a pointer the graph cannot
        read) is counted in ``failed`` and left unannotated rather than failing the diff.
    """
    pointers: List[str] = []
    for change in changes:
        pointer = str(getattr(change, "pointer", "") or "")
        if getattr(change, "severity", None) == _BREAKING and pointer.startswith("/") and pointer not in pointers:
            pointers.append(pointer)
    result = BlastRadiusAnnotations(skipped=max(0, len(pointers) - int(limit)))
    for pointer in pointers[: int(limit)]:
        try:
            answer = blast_radius(
                db,
                tenant_id,
                BlastRadiusRequest(kind="project", entity=project_id, pointers=(pointer,), version=version_id),
            )
        except DependencyValidationError:
            result.failed += 1
            continue
        result.by_pointer[pointer] = summarize_blast_radius(answer)
    return result
