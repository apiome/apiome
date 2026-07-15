"""Quality-scoring / lint commands for a project version (read-only).

``apiome lint`` (the bare group) fetches the server-computed quality report; the CLX-4.2
subcommands add the CI-facing surfaces:

* ``apiome lint gate`` — evaluate the policy gate, optionally against a baseline, emit a
  machine-readable artifact (JSON / SARIF / JUnit / Markdown / attestation), and exit
  non-zero ONLY when a configured policy gate failed.
* ``apiome lint evidence`` — list the immutable evidence runs behind a revision's findings.
* ``apiome lint verify-attestation`` — verify a gate attestation offline with the shared
  HMAC secret (no server round-trip).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from apiome_cli.attestation import attestation_statement, verify_attestation_envelope
from apiome_cli.client import api_paths
from apiome_cli.client.project_version_resolve import resolve_version_uuid
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.output_lint import (
    emit_gate_output,
    emit_lint_command_output,
    gate_should_fail,
    lint_command_should_fail,
)

app = typer.Typer(
    name="lint",
    help="Score schema quality, list lint findings, and run the CI lint gate.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: Artifact formats the gate endpoint can emit besides the default JSON payload.
GATE_FORMATS = ("json", "sarif", "junit", "markdown", "attestation")


@app.callback(invoke_without_command=True)
def lint(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project", help="Project UUID or slug."),
    version: str | None = typer.Option(
        None, "--version", help="Version UUID, slug, or label."
    ),
    base_version: str | None = typer.Option(
        None,
        "--base-version",
        help="Optional base version (UUID, slug, or label) to flag breaking changes against.",
    ),
    min_grade: str | None = typer.Option(
        None,
        "--min-grade",
        help="Exit non-zero when the grade is worse than this (A best, F worst).",
    ),
    fail_on_policy: bool = typer.Option(
        False,
        "--fail-on-policy",
        help="Fetch lint policy evaluation and exit non-zero when policy gates fail.",
    ),
) -> None:
    """Fetch the server-computed quality score and findings (GET .../lint).

    The score and A-F grade are computed by the REST service from the generated
    OpenAPI/JSON-Schema — deterministic for a fixed input. ``--base-version`` folds
    breaking-change risk into the report; ``--min-grade`` turns the report into a CI gate;
    ``--fail-on-policy`` also evaluates style-guide policy gates (GET .../lint/policy).
    """
    if ctx.invoked_subcommand:
        return

    if project is None:
        raise typer.BadParameter("Missing option '--project'.", param_hint="--project")
    if version is None:
        raise typer.BadParameter("Missing option '--version'.", param_hint="--version")
    if min_grade is not None and min_grade.strip().upper() not in {"A", "B", "C", "D", "F"}:
        raise typer.BadParameter(
            "must be one of A, B, C, D, F",
            param_hint="--min-grade",
        )

    client, tenant_slug, project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )

    path = api_paths.version_lint(tenant_slug, project_id, version_id)
    if base_version:
        base_version_id = resolve_version_uuid(
            client,
            tenant_slug=tenant_slug,
            project_id=project_id,
            version_ref=base_version,
        )
        path = f"{path}?baseRevisionId={base_version_id}"

    report = client.get(path).json()

    policy = None
    if fail_on_policy:
        policy_path = api_paths.version_lint_policy(tenant_slug, project_id, version_id)
        if base_version:
            policy_path = f"{policy_path}?baseRevisionId={base_version_id}"
        policy = client.get(policy_path).json()

    json_mode = json_mode_from_context(ctx)
    emit_lint_command_output(
        json_mode=json_mode,
        report=report,
        policy=policy,
        fail_on_policy=fail_on_policy,
    )

    if lint_command_should_fail(
        report,
        min_grade=min_grade,
        policy=policy,
        fail_on_policy=fail_on_policy,
    ):
        raise typer.Exit(EXIT_ERROR)


@app.command("gate")
def gate(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    base_version: str | None = typer.Option(
        None,
        "--base-version",
        help=(
            "Optional baseline version (UUID, slug, or label) to diff regressions against; "
            "without it, each scanner's latest run is compared to its own previous run."
        ),
    ),
    policy_version: str | None = typer.Option(
        None,
        "--policy-version",
        help="Optional historical policy pack id (defaults to the latest for the assigned guide).",
    ),
    new_only: bool = typer.Option(
        False,
        "--new-only",
        help=(
            "Gate only newly introduced violations: pre-existing unwaived errors do not fail; "
            "coverage and axis gates still evaluate the full revision."
        ),
    ),
    format: str = typer.Option(
        "json",
        "--format",
        help="Artifact format: json | sarif | junit | markdown | attestation.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the artifact to this file (non-json formats print to stdout otherwise).",
    ),
) -> None:
    """Run the lint CI gate for a version (GET .../lint/gate) and emit an artifact.

    Exits non-zero ONLY when a configured policy gate failed (``gate.passed`` false in the
    verdict) — findings without policy failures, or failures of gates the pack disabled,
    exit 0. The verdict is always fetched as JSON; a non-json ``--format`` additionally
    fetches that artifact and writes it to ``--output`` (or stdout, with the human summary
    moved to stderr so the artifact stays clean).
    """
    fmt = format.strip().lower()
    if fmt not in GATE_FORMATS:
        raise typer.BadParameter(
            f"must be one of {', '.join(GATE_FORMATS)}", param_hint="--format"
        )

    client, tenant_slug, project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )

    params: list[str] = []
    if base_version:
        base_version_id = resolve_version_uuid(
            client,
            tenant_slug=tenant_slug,
            project_id=project_id,
            version_ref=base_version,
        )
        params.append(f"baselineRevisionId={base_version_id}")
    if policy_version:
        params.append(f"policyVersionId={policy_version}")
    if new_only:
        params.append("newOnly=true")

    base_path = api_paths.version_lint_gate(tenant_slug, project_id, version_id)

    def _gate_url(artifact_format: str) -> str:
        return f"{base_path}?{'&'.join([f'format={artifact_format}', *params])}"

    gate_payload = client.get(_gate_url("json")).json()

    artifact_to_stdout = False
    if fmt != "json":
        artifact = client.get(_gate_url(fmt)).text
        if output is not None:
            output.write_text(artifact, encoding="utf-8")
        else:
            typer.echo(artifact)
            artifact_to_stdout = True
    elif output is not None:
        output.write_text(
            json.dumps(gate_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    json_mode = json_mode_from_context(ctx)
    if artifact_to_stdout:
        # The artifact owns stdout; route the human verdict to stderr for CI logs.
        verdict = gate_payload.get("gate") or {}
        status = "PASSED" if verdict.get("passed") is True else "FAILED"
        typer.echo(f"Lint gate: {status}", err=True)
    else:
        emit_gate_output(json_mode=json_mode, gate=gate_payload)
        if output is not None:
            typer.echo(f"Artifact written: {output}")

    if gate_should_fail(gate_payload):
        raise typer.Exit(EXIT_ERROR)


@app.command("evidence")
def evidence(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
) -> None:
    """List the immutable lint evidence runs for a version (GET .../lint/evidence).

    Emits the full JSON evidence payload: one run per scanner execution with provenance
    fingerprints, outcome, coverage, and normalized findings.
    """
    client, tenant_slug, project_id, version_id = resolve_version_scope(
        ctx,
        project=project,
        version=version,
    )
    payload = client.get(
        api_paths.version_lint_evidence(tenant_slug, project_id, version_id)
    ).json()
    emit_json(payload)


@app.command("verify-attestation")
def verify_attestation(
    file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        help="Path to the attestation envelope JSON (from --format attestation).",
    ),
    secret: str = typer.Option(
        ...,
        "--secret",
        "-s",
        envvar="APIOME_LINT_ATTESTATION_SECRET",
        help="Shared HMAC secret (server: APIOME_LINT_ATTESTATION_SIGNING_SECRET).",
    ),
) -> None:
    """Verify a lint gate attestation offline (no server round-trip).

    Recomputes the DSSE PAEv1 HMAC-SHA256 signature with the shared secret and compares it
    against the envelope's signatures. Exits 0 when verified, non-zero otherwise.
    """
    try:
        envelope = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        typer.echo(f"Cannot read attestation file: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    if not verify_attestation_envelope(envelope, secret):
        typer.echo("Attestation verification FAILED.", err=True)
        raise typer.Exit(EXIT_ERROR)

    typer.echo("Attestation verified.")
    statement = attestation_statement(envelope)
    if statement:
        predicate = statement.get("predicate") or {}
        gate_block = predicate.get("gate") or {}
        typer.echo(f"Subject: {predicate.get('subjectId')} ({predicate.get('subjectType')})")
        typer.echo(f"Gate passed: {gate_block.get('passed')}")
