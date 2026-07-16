"""Helpers for ``apiome diff`` CI gate formatting and threshold logic (CTG-2.1)."""

from __future__ import annotations

import json
from typing import Any

#: Inline OpenAPI upload cap (matches apiome-rest INLINE_SPEC_MAX_BYTES).
INLINE_SPEC_MAX_BYTES = 10 * 1024 * 1024

#: Severity rank for --fail-on thresholds (higher = worse).
_SEVERITY_RANK: dict[str, int] = {
    "docs-only": 0,
    "non-breaking": 1,
    "breaking": 2,
}

#: Minimum severity rank that trips each --fail-on level.
_FAIL_ON_RANK: dict[str, int] = {
    "breaking": 2,
    "warn": 1,
}


def parse_against(value: str) -> tuple[str, str]:
    """Parse ``project@version|latest`` into ``(project, version_ref)``.

    Args:
        value: Against specifier, e.g. ``payments@latest`` or ``pets@1.0.0``.

    Returns:
        Tuple of project slug/UUID and version label/UUID/``latest``.

    Raises:
        ValueError: When the value is empty or missing a non-empty project and ref.
    """
    text = (value or "").strip()
    if not text or "@" not in text:
        raise ValueError(
            "must be <project>@<version|latest> (e.g. payments@latest)"
        )
    project, _, version = text.rpartition("@")
    project = project.strip()
    version = version.strip()
    if not project or not version:
        raise ValueError(
            "must be <project>@<version|latest> (e.g. payments@latest)"
        )
    return project, version


def gate_should_fail(max_severity: str | None, fail_on: str) -> bool:
    """Return True when ``max_severity`` meets or exceeds the ``fail_on`` threshold.

    Args:
        max_severity: Worst severity from the classified diff (``breaking``,
            ``non-breaking``, ``docs-only``), or ``None`` when there are no changes.
        fail_on: ``breaking`` (default) or ``warn`` (non-breaking and above).

    Returns:
        Whether the CI gate should exit 1.
    """
    if max_severity is None:
        return False
    rank = _SEVERITY_RANK.get(str(max_severity).strip().lower())
    if rank is None:
        # Unknown severities fail safe as breaking.
        rank = _SEVERITY_RANK["breaking"]
    threshold = _FAIL_ON_RANK.get(fail_on.strip().lower(), _FAIL_ON_RANK["breaking"])
    return rank >= threshold


def format_diff_text(payload: dict[str, Any]) -> str:
    """Render a human-readable text report from a ClassifiedDiffResponse.

    Args:
        payload: Parsed JSON body from ``POST …/diff/…/classified``.

    Returns:
        Multi-line text for stdout.
    """
    counts = payload.get("counts") or {}
    max_sev = payload.get("maxSeverity")
    lines = [
        f"Classified diff maxSeverity: {max_sev or 'none'}",
        (
            "Counts — breaking: {b}, non-breaking: {n}, docs-only: {d}, "
            "unclassified: {u}, total: {t}"
        ).format(
            b=counts.get("breaking", 0),
            n=counts.get("non-breaking", 0),
            d=counts.get("docs-only", 0),
            u=counts.get("unclassified", 0),
            t=counts.get("total", 0),
        ),
    ]
    for change in payload.get("changes") or []:
        if not isinstance(change, dict):
            continue
        rule = change.get("ruleId") or change.get("rule_id") or "?"
        sev = change.get("severity") or ""
        pointer = change.get("pointer") or ""
        lines.append(f"  [{sev}] {rule} {pointer}")
    return "\n".join(lines)


def format_diff_json(payload: dict[str, Any]) -> str:
    """Serialize classified diff JSON with stable key ordering.

    Args:
        payload: Parsed ClassifiedDiffResponse mapping.

    Returns:
        Pretty-printed JSON string.
    """
    return json.dumps(payload, indent=2, sort_keys=True)
