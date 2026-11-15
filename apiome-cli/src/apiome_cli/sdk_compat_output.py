"""Rendering the generator compatibility manifest — SGD-2.1 (#4735).

``apiome sdk compatibility`` prints the ``apiome.sdk.compat-manifest/v1`` document the dashboard's
**Export studio → SDK compatibility** tab renders, from the same REST route. This module is the pure
half: it turns the manifest into lines (findings first — each with its action — then one row per
artifact, then semver and digests) and decides the exit status for ``--fail-on``. The command module
only fetches and prints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Severities in rank order, lowest first.
SEVERITIES: Sequence[str] = ("info", "warning", "error")


def all_findings(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every finding of every artifact, most severe first, then by artifact and subject.

    Args:
        manifest: The manifest as served.

    Returns:
        The findings.
    """
    rank = {name: index for index, name in enumerate(SEVERITIES)}
    findings = [dict(f) for artifact in manifest.get("artifacts") or [] for f in artifact.get("findings") or []]
    return sorted(findings, key=lambda f: (-rank.get(str(f.get("severity")), 0), str(f.get("artifact")), str(f.get("subject"))))


def fails_threshold(manifest: Mapping[str, Any], fail_on: Optional[str]) -> bool:
    """Whether any finding is at or above ``fail_on``.

    Args:
        manifest: The manifest.
        fail_on: ``error``, ``warning``, ``info``, or ``None`` (never fails).

    Returns:
        True when the threshold is met.
    """
    if not fail_on:
        return False
    floor = SEVERITIES.index(fail_on)
    return any(SEVERITIES.index(str(f.get("severity"))) >= floor for f in all_findings(manifest) if f.get("severity") in SEVERITIES)


def _coverage(artifact: Mapping[str, Any]) -> str:
    coverage = artifact.get("coverage") or {}
    return f"{coverage.get('operations', 0)}/{coverage.get('of', 0)}"


def render_manifest(manifest: Mapping[str, Any]) -> List[str]:
    """Human-readable lines for a manifest.

    Args:
        manifest: The manifest as served.

    Returns:
        Lines to print, without trailing newlines.
    """
    api = manifest.get("api") or {}
    source = manifest.get("source") or {}
    lines = [
        f"SDK compatibility — {api.get('title') or 'API'} {source.get('version_label') or api.get('version') or ''}".rstrip(),
        f"Revision {source.get('version_record_id')} · {manifest.get('findings_count', 0)} finding(s)",
        "",
    ]

    findings = all_findings(manifest)
    if findings:
        lines.append("Findings")
        for finding in findings:
            lines.append(
                f"  [{finding.get('severity')}] {finding.get('artifact')} · {finding.get('code')} · {finding.get('subject')}"
            )
            lines.append(f"      why:  {finding.get('reason')}")
            lines.append(f"      do:   {finding.get('action')}")
        lines.append("")
    else:
        lines += ["No findings: every artifact represents every construct.", ""]

    lines.append("Artifacts")
    width = max((len(str(a.get("id"))) for a in manifest.get("artifacts") or []), default=10)
    for artifact in manifest.get("artifacts") or []:
        runtime = artifact.get("runtime") or {}
        auth = artifact.get("auth")
        pagination = artifact.get("pagination")
        status = "generated" if artifact.get("included") else "not generated"
        parts = [f"{_coverage(artifact)} operations", status]
        if runtime.get("language_version"):
            parts.append(str(runtime["language_version"]))
        if runtime.get("dependencies"):
            parts.append("deps: " + ", ".join(runtime["dependencies"]))
        if auth is not None and auth.get("unsupported"):
            parts.append("auth unsupported: " + ", ".join(auth["unsupported"]))
        if pagination is not None and pagination.get("mode") == "manual":
            parts.append("pagination: manual (" + ", ".join(pagination.get("parameters") or []) + ")")
        lines.append(f"  {str(artifact.get('id')).ljust(width)}  " + " · ".join(parts))
    lines.append("")

    semver = manifest.get("semver") or {}
    if semver.get("classification") == "unknown":
        lines.append("Semver: unknown (no classified changelog for this revision)")
    else:
        verdict = "consistent" if semver.get("consistent") else "INCONSISTENT" if semver.get("consistent") is False else "not comparable"
        lines.append(
            f"Semver: {semver.get('classification')} since {semver.get('baseline_version')} — requires "
            f"{semver.get('required_bump')}, labels declare {semver.get('declared_bump')} ({verdict})"
        )
    options = manifest.get("options") or {}
    lines += [
        f"Digests: source {source.get('digest')}",
        f"         options {options.get('digest')}",
    ]
    return lines
