"""Independent OpenAPI compatibility evidence (oasdiff) for CI gates (CLX-2.3).

With ``--mode``, ``--transitive`` or ``--category`` (XPC-4.5, #5749) the command asks the server's
native compatibility check instead (``POST …/compatibility``), which grades Avro, JSON Schema,
AsyncAPI and Protobuf revisions by that mode or category. oasdiff only reads OpenAPI and has no
notion of a mode, so passing a mode to it would imply semantics it never applied.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.project_version_resolve import resolve_version_uuid
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.compat_modes import describe_evaluated_under, mode_request_fields
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.output import json_mode_from_context

app = typer.Typer(
    name="compat",
    help="Compare two revisions: oasdiff evidence, or the native check graded by compatibility mode.",
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
    mode: str | None = typer.Option(
        None,
        "--mode",
        show_default="project policy",
        help=(
            "Use the native check graded by this compatibility mode: backward, forward, full or "
            "none (optionally with _transitive). JSON output only."
        ),
    ),
    transitive: bool | None = typer.Option(
        None,
        "--transitive/--no-transitive",
        show_default="project policy",
        help="Use the native check, also comparing against every earlier version of the base.",
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        show_default="project policy",
        help="Use the native check with this Protobuf category: wire, wire_json, package or file.",
    ),
) -> None:
    """POST .../compatibility/evidence and print normalized JSON / SARIF / JUnit.

    Exit code is non-zero when findings meet ``--fail-on`` (default: any breaking
    change). Native merge gates are unchanged; this is independent oasdiff evidence.

    With ``--mode``, ``--transitive`` or ``--category`` the native check
    (``POST .../compatibility``) runs instead, with those values; settings left off come from the
    project's style-guide policy. Its ``breaking`` findings fail ``--fail-on breaking``, ``unknown``
    (dangerous) ones fail ``--fail-on dangerous``, and any finding fails ``--fail-on info``.
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

    mode_fields = mode_request_fields(mode, transitive, category)
    if mode_fields and fmt != "json":
        raise typer.BadParameter(
            "the native check (--mode, --transitive, --category) reports JSON only",
            param_hint="--format",
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

    if mode_fields:
        _native_check(
            ctx,
            client,
            path=api_paths.version_compatibility(tenant_slug, project_id),
            body={
                "baseRevisionId": str(base_version_id),
                "headRevisionId": str(version_id),
                **mode_fields,
            },
            fail_level=fail_level,
        )
        return

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


#: ``--fail-on`` → the native finding categories that fail it.
_NATIVE_FAILING = {
    "breaking": ("breaking",),
    "dangerous": ("breaking", "unknown"),
    "info": ("breaking", "unknown", "safe"),
}


def _native_check(
    ctx: typer.Context,
    client: Any,
    *,
    path: str,
    body: dict[str, Any],
    fail_level: str,
) -> None:
    """Run the native compatibility check with a mode and print its report (XPC-4.5).

    Args:
        ctx: The Typer context (for ``--json``).
        client: The tenant-scoped API client.
        path: ``POST …/compatibility``.
        body: The revision pair plus ``mode`` / ``transitive`` / ``category``.
        fail_level: ``--fail-on``.

    Raises:
        typer.Exit: ``EXIT_ERROR`` when a finding meets ``fail_level``.
    """
    payload = client.post(path, json=body, headers={"Accept": "application/json"}).json()
    findings = [f for f in payload.get("findings") or [] if isinstance(f, dict)]
    if json_mode_from_context(ctx):
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"Compatibility overall: {payload.get('overall') or 'safe'}")
        evaluated = describe_evaluated_under(payload.get("evaluatedUnder"))
        if evaluated:
            typer.echo(evaluated)
        for finding in findings:
            rule = finding.get("ruleId") or finding.get("rule") or "?"
            against = finding.get("against")
            versus = (
                f" (against {against['versionLabel']})"
                if isinstance(against, dict) and against.get("versionLabel")
                else ""
            )
            typer.echo(
                f"  [{finding.get('category') or ''}] {rule} {finding.get('path') or ''}{versus} — "
                f"{finding.get('message') or ''}"
            )
    failing = _NATIVE_FAILING.get(fail_level, ("breaking",))
    if any(str(f.get("category") or "") in failing for f in findings):
        raise typer.Exit(EXIT_ERROR)
