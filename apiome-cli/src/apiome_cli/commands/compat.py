"""Independent OpenAPI compatibility evidence (oasdiff) for CI gates (CLX-2.3)."""

from __future__ import annotations

import json
from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.project_version_resolve import resolve_version_uuid
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.output import json_mode_from_context

app = typer.Typer(
    name="compat",
    help="Compare two OpenAPI revisions via independent oasdiff compatibility evidence.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_FORMATS = ("json", "sarif", "junit")
_FAIL_ON = ("breaking", "dangerous", "info")


def _has_change_class(findings: list[dict[str, Any]], *classes: str) -> bool:
    wanted = {c.lower() for c in classes}
    for finding in findings:
        cc = str(finding.get("changeClass") or finding.get("change_class") or "").lower()
        if cc in wanted:
            return True
        if not cc and finding.get("severity") == "error" and "breaking" in wanted:
            return True
    return False


@app.callback(invoke_without_command=True)
def compat(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(
        ..., "--version", help="Head / candidate version (UUID, slug, or label)."
    ),
    base_version: str = typer.Option(
        ...,
        "--base-version",
        help="Baseline version (UUID, slug, or label) to compare against.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Gate output format: json (default), sarif, or junit.",
    ),
    fail_on: str = typer.Option(
        "breaking",
        "--fail-on",
        help=(
            "Exit non-zero when findings at this level or higher are present: "
            "breaking (default), dangerous, or info."
        ),
    ),
) -> None:
    """POST .../compatibility/evidence and print normalized JSON / SARIF / JUnit.

    Exit code is non-zero when findings meet ``--fail-on`` (default: any breaking
    change). Native merge gates are unchanged; this is independent oasdiff evidence.
    """
    fmt = (output_format or "json").strip().lower()
    if fmt not in _FORMATS:
        raise typer.BadParameter(
            "must be one of json, sarif, junit",
            param_hint="--format",
        )
    fail_level = (fail_on or "breaking").strip().lower()
    if fail_level not in _FAIL_ON:
        raise typer.BadParameter(
            "must be one of breaking, dangerous, info",
            param_hint="--fail-on",
        )

    client, tenant_slug, project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )
    base_version_id = resolve_version_uuid(
        client,
        tenant_slug=tenant_slug,
        project_id=project_id,
        version_ref=base_version,
    )

    post_path = api_paths.version_compatibility_evidence(tenant_slug, project_id)
    payload = client.post(
        post_path,
        json={
            "baseRevisionId": str(base_version_id),
            "headRevisionId": str(version_id),
        },
        headers={"Accept": "application/json"},
    ).json()
    findings = list(payload.get("findings") or [])

    json_mode = json_mode_from_context(ctx)
    if fmt == "json":
        if json_mode:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            overall = payload.get("overall") or "safe"
            counts = payload.get("counts") or {}
            typer.echo(f"Compatibility evidence overall: {overall}")
            typer.echo(
                "Counts — breaking: {b}, dangerous: {d}, informational: {i}".format(
                    b=counts.get("breaking", 0),
                    d=counts.get("dangerous", 0),
                    i=counts.get("informational", 0),
                )
            )
            for finding in findings:
                rule = finding.get("ruleId") or finding.get("rule_id") or "?"
                cls = finding.get("changeClass") or finding.get("change_class") or ""
                msg = finding.get("message") or ""
                loc = finding.get("location") or {}
                path_hint = loc.get("path") or ""
                typer.echo(f"  [{cls}] {rule} {path_hint} — {msg}")
            if payload.get("changelogMarkdown"):
                typer.echo("--- changelog (markdown) ---")
                typer.echo(payload["changelogMarkdown"])
    else:
        get_path = (
            f"{api_paths.version_compatibility_evidence_list(tenant_slug, project_id, version_id)}"
            f"?format={fmt}"
        )
        gate_text = client.get(get_path).text
        typer.echo(gate_text)

    should_fail = False
    if fail_level == "breaking":
        should_fail = _has_change_class(findings, "breaking")
    elif fail_level == "dangerous":
        should_fail = _has_change_class(findings, "breaking", "dangerous")
    else:
        should_fail = bool(findings)

    if should_fail:
        raise typer.Exit(EXIT_ERROR)
