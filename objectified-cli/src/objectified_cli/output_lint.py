"""Human-readable rendering for the ``lint`` command (quality score + findings)."""

from __future__ import annotations

from typing import Any

import typer

from objectified_cli.output import ListColumn, emit_list_table

#: Letter grades ordered best-to-worst for ``--min-grade`` comparisons.
GRADE_ORDER = ("A", "B", "C", "D", "F")


def grade_rank(grade: str) -> int:
    """Return the rank of ``grade`` (0 = best). Unknown grades rank worst."""
    grade = (grade or "").strip().upper()
    return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else len(GRADE_ORDER)


def grade_meets_minimum(grade: str, minimum: str) -> bool:
    """True when ``grade`` is at least as good as ``minimum`` (A best, F worst)."""
    return grade_rank(grade) <= grade_rank(minimum)


def _severity_sort_key(finding: dict[str, Any]) -> tuple[int, str, str]:
    order = {"error": 0, "warning": 1, "info": 2}
    severity = str(finding.get("severity", ""))
    return (order.get(severity, 3), str(finding.get("path", "")), str(finding.get("rule", "")))


def emit_lint_report(report: dict[str, Any]) -> None:
    """Render a lint report as a summary header plus a findings table."""
    score = report.get("score")
    grade = report.get("grade", "?")
    version_label = report.get("versionId", "")
    severity = report.get("severityCounts") or {}

    typer.echo(f"Quality score: {score}/100  (grade {grade})")
    if version_label:
        typer.echo(f"Version: {version_label}")
    typer.echo(
        "Findings: "
        f"{severity.get('error', 0)} error, "
        f"{severity.get('warning', 0)} warning, "
        f"{severity.get('info', 0)} info"
    )
    compatibility_overall = report.get("compatibilityOverall")
    if compatibility_overall:
        base = report.get("baseRevisionId") or ""
        typer.echo(f"Compatibility vs {base}: {compatibility_overall}")
    typer.echo("")

    findings = list(report.get("findings") or [])
    findings.sort(key=_severity_sort_key)
    columns: tuple[ListColumn, ...] = (
        ("Severity", "severity", None),
        ("Rule", "rule", None),
        ("Path", "path", None),
        ("Message", "message", None),
    )
    emit_list_table(
        findings,
        columns,
        total=len(findings),
        empty_message="No findings — clean bill of health.",
        min_width=120,
    )
