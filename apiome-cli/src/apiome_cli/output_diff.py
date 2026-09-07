"""Helpers for ``apiome diff`` CI gate formatting and threshold logic (CTG-2.1).

Also renders the CTG-4.2 per-consumer verdicts (#4480) the server attaches when
``apiome diff --consumers`` is used, so a CI log says *whose* build this breaks.
"""

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
        consumers = change.get("consumers")
        touches = f" — breaks {', '.join(consumers)}" if consumers else ""
        lines.append(f"  [{sev}] {rule} {pointer}{touches}")
    impact = payload.get("consumers")
    if isinstance(impact, dict):
        lines.extend(format_consumer_impact_text(impact))
    return "\n".join(lines)


def format_diff_json(payload: dict[str, Any]) -> str:
    """Serialize classified diff JSON with stable key ordering.

    Args:
        payload: Parsed ClassifiedDiffResponse mapping.

    Returns:
        Pretty-printed JSON string.
    """
    return json.dumps(payload, indent=2, sort_keys=True)


def _impact_target(impact: dict[str, Any]) -> str:
    """Human phrase for what one attributed change touches.

    Args:
        impact: One entry from a verdict's ``impacts`` list.

    Returns:
        ``document-wide``, ``GET /pets``, or ``GET /pets — 200 response `name```.
    """
    if impact.get("match") == "document":
        return "document-wide"
    method = str(impact.get("method") or "").upper()
    operation = f"{method} {impact.get('path') or ''}".strip()
    field_path = impact.get("fieldPath")
    if impact.get("match") != "field" or not field_path:
        return operation
    where = str(impact.get("fieldLocation") or "field")
    status = impact.get("fieldStatus")
    if status:
        where = f"{status} {where}"
    return f"{operation} — {where} `{field_path}`"


def format_consumer_impact_text(impact: dict[str, Any]) -> list[str]:
    """Render the consumer-impact block of the text report.

    A breaking verdict is spelled ``breaks <handle>`` so the line a CI log is grepped for says
    who to talk to, not only that something is wrong.

    Args:
        impact: The ``consumers`` block of a ClassifiedDiffResponse.

    Returns:
        Lines to append to the text report (empty when there is nothing to say).
    """
    if not isinstance(impact, dict):
        return []
    lines = ["", f"Consumer impact: {impact.get('summary') or 'not analysed'}"]
    for verdict in impact.get("consumers") or []:
        if not isinstance(verdict, dict):
            continue
        slug = verdict.get("consumerSlug") or "?"
        outcome = verdict.get("verdict") or "?"
        if outcome == "breaking":
            lines.append(f"  breaks {slug}")
        elif outcome == "undeclared":
            lines.append(f"  {slug}: no declared surface")
        else:
            lines.append(f"  {slug}: {outcome}")
        for row in verdict.get("impacts") or []:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"    [{row.get('severity') or ''}] {_impact_target(row)} "
                f"({row.get('ruleId') or '?'})"
            )
        if verdict.get("truncated"):
            lines.append("    …list truncated.")
    unattributed = (impact.get("counts") or {}).get("changes_unattributed", 0)
    if unattributed:
        lines.append(f"  {unattributed} change(s) affect no registered consumer")
    return lines
