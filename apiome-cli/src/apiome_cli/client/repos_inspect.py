"""Helpers for ``apiome repos inspect`` sniff and deep-verdict output."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import typer

from apiome_cli.client.repos_closure import (
    RepositoryFileClosureResponse,
    emit_repository_file_closure_result,
)
from apiome_cli.client.repos_files import format_detected_kind, format_importable_verdict
from apiome_cli.output import emit_json


def format_detected_version(value: object) -> str:
    """Format ``detected_version`` for human-readable output."""
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def format_sniff_confidence(value: object) -> str:
    """Format ``detected_confidence`` for human-readable output."""
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def format_sniff_reasons(value: object) -> list[str]:
    """Normalize REST ``reasons`` into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    reasons: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                reasons.append(text)
    return reasons


def emit_repository_file_sniff_result(
    payload: dict[str, Any],
    *,
    json_mode: bool,
    closure: RepositoryFileClosureResponse | None = None,
) -> None:
    """Print the sniff verdict and optional ``$ref`` closure."""
    if json_mode:
        output = dict(payload)
        if closure is not None:
            output["closure"] = closure
        emit_json(output)
        return

    typer.echo("Content sniff completed.")
    file_id = payload.get("file_id")
    if isinstance(file_id, str) and file_id:
        typer.echo(f"  File: {file_id}")

    typer.echo(f"  Kind: {format_detected_kind(payload.get('detected_kind'))}")
    typer.echo(f"  Version: {format_detected_version(payload.get('detected_version'))}")
    typer.echo(
        "  Importable: "
        + format_importable_verdict(
            payload.get("importable"),
            blocked_reason=payload.get("import_blocked_reason"),
        )
    )
    typer.echo(f"  Confidence: {format_sniff_confidence(payload.get('detected_confidence'))}")

    reasons = format_sniff_reasons(payload.get("reasons"))
    if reasons:
        typer.echo("  Reasons:")
        for reason in reasons:
            typer.echo(f"    - {reason}")

    if closure is not None:
        emit_repository_file_closure_result(closure, json_mode=False)


def format_deep_verdict_finding(finding: dict[str, Any]) -> str:
    """Format one deep-verdict finding for human-readable output."""
    severity = finding.get("severity")
    severity_label = str(severity).strip() if severity is not None else "finding"
    code = finding.get("code")
    code_label = f" ({code})" if isinstance(code, str) and code.strip() else ""
    path = finding.get("path")
    path_label = f" at {path}" if isinstance(path, str) and path.strip() else ""
    message = finding.get("message")
    message_label = str(message).strip() if isinstance(message, str) else "Finding reported."
    return f"[{severity_label}]{code_label}{path_label}: {message_label}"


def format_deep_verdict_findings(value: object) -> list[str]:
    """Normalize deep-verdict finding arrays into formatted lines."""
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            lines.append(format_deep_verdict_finding(item))
    return lines


def format_fidelity_status(value: object) -> str:
    """Format ``fidelity`` for human-readable output."""
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def format_bundle_member(member: dict[str, Any]) -> str:
    """Format one bundled closure member for human-readable output."""
    path = member.get("path")
    path_label = str(path).strip() if isinstance(path, str) and path.strip() else "—"
    blob_sha = member.get("blob_sha")
    blob_label = (
        str(blob_sha)[:7]
        if isinstance(blob_sha, str) and blob_sha.strip()
        else "—"
    )
    return f"{path_label} ({blob_label})"


def format_bundle_members(value: object) -> list[str]:
    """Normalize ``bundle_members`` into formatted lines."""
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            lines.append(format_bundle_member(item))
    return lines


def _emit_deep_verdict_findings_section(title: str, findings: Sequence[str]) -> None:
    """Print a titled findings section or a ``(none)`` placeholder."""
    typer.echo(f"  {title}:")
    if findings:
        for finding in findings:
            typer.echo(f"    - {finding}")
    else:
        typer.echo("    (none)")


def emit_repository_file_deep_verdict_result(
    payload: dict[str, Any],
    *,
    json_mode: bool,
) -> bool:
    """
    Print the deep pre-import verdict from ``POST …/verify``.

    Returns ``True`` when ``blocking`` findings prevent import.
    """
    blocking = payload.get("blocking") is True
    if json_mode:
        emit_json(payload)
        return blocking

    typer.echo("Deep pre-import verdict completed.")
    file_id = payload.get("file_id")
    if isinstance(file_id, str) and file_id:
        typer.echo(f"  File: {file_id}")

    typer.echo(f"  Kind: {format_detected_kind(payload.get('detected_kind'))}")
    validation_status = payload.get("validation_status")
    validation_label = (
        str(validation_status).strip()
        if validation_status is not None and str(validation_status).strip()
        else "—"
    )
    typer.echo(f"  Validation: {validation_label}")
    typer.echo(f"  Fidelity: {format_fidelity_status(payload.get('fidelity'))}")

    fidelity_nodes = payload.get("fidelity_nodes")
    if isinstance(fidelity_nodes, list) and fidelity_nodes:
        typer.echo("  Fidelity nodes:")
        for node in fidelity_nodes:
            if isinstance(node, str) and node.strip():
                typer.echo(f"    - {node.strip()}")

    typer.echo(f"  Blocking: {'yes' if blocking else 'no'}")
    blocking_reasons = payload.get("blocking_reasons")
    if blocking and isinstance(blocking_reasons, list) and blocking_reasons:
        typer.echo("  Blocking reasons:")
        for reason in blocking_reasons:
            if isinstance(reason, str) and reason.strip():
                typer.echo(f"    - {reason.strip()}")

    _emit_deep_verdict_findings_section(
        "Validation errors",
        format_deep_verdict_findings(payload.get("validation_errors")),
    )
    _emit_deep_verdict_findings_section(
        "Lint findings",
        format_deep_verdict_findings(payload.get("lint_findings")),
    )
    _emit_deep_verdict_findings_section(
        "Secrets findings",
        format_deep_verdict_findings(payload.get("secrets_findings")),
    )
    _emit_deep_verdict_findings_section(
        "Bundle members",
        format_bundle_members(payload.get("bundle_members")),
    )

    return blocking
