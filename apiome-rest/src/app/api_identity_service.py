"""Cross-format API identity helpers (MFI-6.4, #4410).

Pure functions for projecting related-artifact rows and ranking heuristic link suggestions.
Suggestions never auto-link — callers must confirm via the link endpoint.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from .models import IdentitySuggestionRef, RelatedArtifactRef


def _normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    lowered = value.lower().strip()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def _shared_metadata_keys(
    left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]
) -> List[str]:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    shared: List[str] = []
    for key in ("package", "subject", "namespace", "service", "registryUrl"):
        left_val = left.get(key)
        right_val = right.get(key)
        if left_val and right_val and str(left_val).strip() == str(right_val).strip():
            shared.append(key)
    return shared


def build_related_artifact_refs(rows: List[Dict[str, Any]]) -> List[RelatedArtifactRef]:
    """Project DAO rows onto :class:`RelatedArtifactRef` models."""
    refs: List[RelatedArtifactRef] = []
    for row in rows:
        refs.append(
            RelatedArtifactRef(
                project_id=str(row["project_id"]),
                name=row.get("name") or "",
                slug=row.get("slug") or "",
                publishable=bool(row.get("publishable")),
                source_format=row.get("source_format"),
                protocol=row.get("protocol"),
                link_source=row.get("link_source") or "manual",
                deleted=bool(row.get("deleted")),
            )
        )
    return refs


def rank_identity_suggestions(
    *,
    anchor: Dict[str, Any],
    anchor_ops: Set[str],
    candidates: List[Dict[str, Any]],
    candidate_ops: Dict[str, Set[str]],
    limit: int = 10,
) -> List[IdentitySuggestionRef]:
    """Rank heuristic link suggestions for ``anchor`` against ``candidates``."""
    anchor_name = _normalize_title(anchor.get("name"))
    anchor_identity = _normalize_title(anchor.get("identity_name"))
    anchor_namespace = (anchor.get("identity_namespace") or "").strip().lower()
    anchor_meta = anchor.get("format_metadata")

    scored: List[tuple[int, str, Dict[str, Any]]] = []
    for row in candidates:
        pid = str(row["project_id"])
        score = 0
        reasons: List[str] = []

        candidate_name = _normalize_title(row.get("name"))
        if anchor_name and candidate_name and anchor_name == candidate_name:
            score += 40
            reasons.append("matching title")

        identity_name = _normalize_title(row.get("identity_name"))
        if anchor_identity and identity_name and anchor_identity == identity_name:
            score += 35
            reasons.append("matching API identity name")

        candidate_namespace = (row.get("identity_namespace") or "").strip().lower()
        if anchor_namespace and candidate_namespace and anchor_namespace == candidate_namespace:
            score += 15
            reasons.append("matching namespace")

        shared_keys = _shared_metadata_keys(
            anchor_meta if isinstance(anchor_meta, dict) else None,
            row.get("format_metadata") if isinstance(row.get("format_metadata"), dict) else None,
        )
        if shared_keys:
            score += 20 * len(shared_keys)
            reasons.append(f"shared {', '.join(shared_keys)}")

        overlap = anchor_ops.intersection(candidate_ops.get(pid, set()))
        if overlap:
            score += min(30, 5 * len(overlap))
            reasons.append(f"{len(overlap)} shared operation(s)")

        if score <= 0:
            continue

        scored.append((score, "; ".join(reasons), row))

    scored.sort(key=lambda item: (-item[0], item[2].get("name") or ""))

    suggestions: List[IdentitySuggestionRef] = []
    for score, reason, row in scored[:limit]:
        suggestions.append(
            IdentitySuggestionRef(
                project_id=str(row["project_id"]),
                name=row.get("name") or "",
                slug=row.get("slug") or "",
                publishable=bool(row.get("publishable")),
                source_format=row.get("source_format"),
                protocol=row.get("protocol"),
                reason=reason,
                score=score,
            )
        )
    return suggestions
