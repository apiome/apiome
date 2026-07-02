"""Render catalog → OpenAPI conversion results for the ``convert`` command (MFI-22.6).

Pure, stream-agnostic formatting helpers (no HTTP, no ``typer``) so the fidelity summary + warning
the ``convert`` command prints are unit-testable in isolation. The authoritative fidelity report is
computed server-side by apiome-rest (MFI-22.3); this module only *presents* the report the API
returns — it never recomputes a score, a grade, or a tier.

Two response shapes are rendered, both carrying the same ``report``:

* a **dry-run** (``convert --dry-run``) returns ``{report, openapi, sourceFormat, target}`` — the
  fidelity report and the would-be OpenAPI document, with no Project created;
* a **commit** returns ``{projectId, versionId, report, ...}`` — the created Project/version ids.

The mandatory warning sentence mirrors the preview screen (MFI-22.4) so every surface says the same
thing, and the ``low`` fidelity tier is what the command turns into its non-zero exit hint.
"""

from __future__ import annotations

from typing import Any, Mapping

# Mirrors apiome-ui's CONVERSION_WARNING_SENTENCE (MFI-22.4) so every surface warns identically.
CONVERSION_WARNING_SENTENCE = (
    "The fidelity of the original API may not be complete enough to create a fully defined "
    "OpenAPI Specification — review the gaps below before converting."
)

# Coverage tags that mean a construct did NOT reach the converted spec faithfully (mirrors the
# preview's MISSING_COVERAGES): these are the checklist rows worth calling out as gaps.
_GAP_COVERAGES = frozenset({"missing", "partial", "n/a"})


def report_tier(report: Mapping[str, Any]) -> str:
    """Return the report's coarse fidelity tier (``high`` / ``medium`` / ``low``), lower-cased."""
    return str(report.get("tier", "")).strip().lower()


def is_low_tier(report: Mapping[str, Any]) -> bool:
    """True when the conversion is low fidelity — the signal the command turns into a non-zero hint."""
    return report_tier(report) == "low"


def _gap_items(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the checklist rows for constructs OpenAPI favors but this conversion lacks."""
    items = report.get("items")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, Mapping) and str(item.get("coverage")) in _GAP_COVERAGES
    ]


def format_conversion_summary(
    response: Mapping[str, Any],
    *,
    committed: bool,
) -> list[str]:
    """Build the human-readable summary lines for a conversion response.

    Args:
        response: The parsed convert response (dry-run or commit); both carry a ``report``.
        committed: True when this was a commit (a Project was created), False for a dry-run.

    Returns:
        A list of output lines: the fidelity headline, the mandatory warning, up to a few gap rows,
        and — for a commit — the created Project/version ids.
    """
    report = response.get("report")
    if not isinstance(report, Mapping):
        return ["Conversion completed, but no fidelity report was returned."]

    tier = report_tier(report) or "unknown"
    score = report.get("score")
    grade = report.get("grade")
    target = response.get("target", "openapi")

    lines: list[str] = []
    headline = f"Conversion to {target}: fidelity {grade} ({score}/100), tier {tier}."
    lines.append(headline)
    lines.append(CONVERSION_WARNING_SENTENCE)

    gaps = _gap_items(report)
    if gaps:
        lines.append("Gaps OpenAPI favors but this conversion lacks:")
        for item in gaps[:8]:
            title = item.get("title") or item.get("key") or "construct"
            coverage = item.get("coverage")
            reason = item.get("reason")
            detail = f"  - {title} [{coverage}]"
            if reason:
                detail += f": {reason}"
            lines.append(detail)
        if len(gaps) > 8:
            lines.append(f"  … and {len(gaps) - 8} more (use --json for the full report).")

    losses = report.get("losses")
    if isinstance(losses, list) and losses:
        lines.append(f"Projection losses: {len(losses)} (constructs with no faithful OpenAPI form).")

    if committed:
        project_id = response.get("projectId")
        version_id = response.get("versionId")
        reconverted = response.get("reconverted")
        verb = "Re-converted" if reconverted else "Converted"
        lines.append(f"{verb} into project {project_id} version {version_id}.")

    if is_low_tier(report):
        lines.append(
            "Low fidelity — the converted spec will be substantially incomplete. "
            "Re-run with --force to accept, or supply --title/--api-version/--server to close gaps."
        )

    return lines
