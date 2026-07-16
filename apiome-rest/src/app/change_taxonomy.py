"""CTG-1.1 OpenAPI change taxonomy & classifier (#4467).

Grades every change between two OpenAPI documents as **breaking**, **non-breaking**,
or **docs-only**. Raw changes come from :mod:`app.change_taxonomy_enum`; each is
matched against the extensible rule registry in :mod:`app.change_taxonomy_rules`.
Unknown kinds fail safe to **breaking** with ``unclassified=True``.

This module is pure (no DB, no network). The REST endpoint that exposes it is CTG-1.2.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from .change_taxonomy_enum import RawChange, enumerate_openapi_changes
from .change_taxonomy_rules import (
    UNCLASSIFIED_RULE_ID,
    Severity,
    TaxonomyRule,
    clear_severity_overrides,
    effective_severity,
    get_rule,
    list_rules,
    override_severity,
    register_rule,
    register_rules,
    rule_for_kind,
    unregister_rule,
)

__all__ = [
    "Severity",
    "ClassifiedChange",
    "ClassifiedDiff",
    "classify_openapi_changes",
    "classify_raw_changes",
    "RawChange",
    "enumerate_openapi_changes",
    "TaxonomyRule",
    "register_rule",
    "register_rules",
    "override_severity",
    "clear_severity_overrides",
    "unregister_rule",
    "get_rule",
    "list_rules",
    "UNCLASSIFIED_RULE_ID",
]


_SEVERITY_RANK: Dict[Severity, int] = {
    "docs-only": 0,
    "non-breaking": 1,
    "breaking": 2,
}


class ClassifiedChange(BaseModel):
    """One classified change from an OpenAPI document pair.

    Attributes:
        rule_id: Stable taxonomy rule that fired (or ``ctg.unclassified``).
        severity: ``breaking`` / ``non-breaking`` / ``docs-only``.
        pointer: JSON Pointer to the changed node.
        before: Value in the base document (``None`` if added).
        after: Value in the head document (``None`` if removed).
        unclassified: ``True`` when no registry rule matched (fail-safe).
        change_kind: Raw enumerator kind that produced this change.
    """

    rule_id: str = Field(description="Stable taxonomy rule id (e.g. ctg.path_removed).")
    severity: Severity = Field(description="breaking | non-breaking | docs-only.")
    pointer: str = Field(description="JSON Pointer to the changed node.")
    before: Any = Field(default=None, description="Base value (None if added).")
    after: Any = Field(default=None, description="Head value (None if removed).")
    unclassified: bool = Field(
        default=False,
        description="True when no rule matched; severity is fail-safe breaking.",
    )
    change_kind: str = Field(default="", description="Raw enumerator change kind.")


class ClassifiedDiff(BaseModel):
    """Full classification of an OpenAPI base→head pair.

    Attributes:
        changes: Classified changes in stable order (pointer, then kind).
        counts: Tallies for breaking / non-breaking / docs-only / unclassified / total.
        max_severity: Worst severity across changes; ``None`` when empty.
    """

    changes: List[ClassifiedChange] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
    max_severity: Optional[Severity] = Field(
        default=None,
        description="Worst severity; None when there are no changes.",
    )


def _worst(severities: Sequence[Severity]) -> Optional[Severity]:
    if not severities:
        return None
    worst: Severity = "docs-only"
    for severity in severities:
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity
    return worst


def _tally(changes: Sequence[ClassifiedChange]) -> Dict[str, int]:
    counts = {
        "breaking": 0,
        "non-breaking": 0,
        "docs-only": 0,
        "unclassified": 0,
        "total": len(changes),
    }
    for change in changes:
        counts[change.severity] = counts.get(change.severity, 0) + 1
        if change.unclassified:
            counts["unclassified"] += 1
    return counts


def classify_raw_changes(
    raw_changes: Sequence[RawChange],
    *,
    overrides: Optional[Mapping[str, Severity]] = None,
) -> ClassifiedDiff:
    """Classify an already-enumerated raw change list.

    Unknown kinds map to ``ctg.unclassified`` at **breaking** severity with
    ``unclassified=True`` (fail-safe).

    Args:
        raw_changes: Output of :func:`enumerate_openapi_changes` (or synthetic).
        overrides: Optional per-call severity overrides keyed by rule_id.

    Returns:
        A :class:`ClassifiedDiff` with summary counts and max severity.
    """
    override_map: Optional[Dict[str, Severity]] = dict(overrides) if overrides else None
    classified: List[ClassifiedChange] = []

    for raw in raw_changes:
        rule = rule_for_kind(raw.kind)
        if rule is None:
            classified.append(
                ClassifiedChange(
                    rule_id=UNCLASSIFIED_RULE_ID,
                    severity="breaking",
                    pointer=raw.pointer,
                    before=raw.before,
                    after=raw.after,
                    unclassified=True,
                    change_kind=raw.kind,
                )
            )
            continue

        severity = effective_severity(rule, override_map)
        classified.append(
            ClassifiedChange(
                rule_id=rule.rule_id,
                severity=severity,
                pointer=raw.pointer,
                before=raw.before,
                after=raw.after,
                unclassified=False,
                change_kind=raw.kind,
            )
        )

    return ClassifiedDiff(
        changes=classified,
        counts=_tally(classified),
        max_severity=_worst([c.severity for c in classified]),
    )


def classify_openapi_changes(
    base: Dict[str, Any],
    head: Dict[str, Any],
    *,
    overrides: Optional[Mapping[str, Severity]] = None,
) -> ClassifiedDiff:
    """Classify all changes between two OpenAPI documents.

    Args:
        base: Older / baseline OpenAPI document.
        head: Newer / candidate OpenAPI document.
        overrides: Optional per-call severity overrides keyed by rule_id
            (GOV style-guide hook; also see :func:`override_severity`).

    Returns:
        A :class:`ClassifiedDiff` ready for CTG-1.2 / changelog / CI gates.
    """
    return classify_raw_changes(enumerate_openapi_changes(base, head), overrides=overrides)
