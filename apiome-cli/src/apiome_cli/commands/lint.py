"""Quality-scoring / lint commands for a project version.

``apiome lint`` (the bare group) fetches the server-computed quality report; with ``--fix``
(GVM-3.3) it plans the deterministic lint fixes of the version and applies them as a new
revision (``--dry-run`` prints the diff and writes nothing). The CLX-4.2 subcommands add the
CI-facing surfaces:

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
from urllib.parse import urlencode

import typer

from apiome_cli.attestation import attestation_statement, verify_attestation_envelope
from apiome_cli.client import api_paths
from apiome_cli.client.project_version_resolve import resolve_version_uuid
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.lint_fix_output import (
    FIX_FORMATS,
    fix_exit_code,
    format_fix_applied,
    format_fix_plan,
    format_remaining,
    ready_fix_ids,
)
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.output_lint import (
    emit_gate_output,
    emit_lint_command_output,
    gate_should_fail,
    lint_command_should_fail,
    maturity_gate_line,
)
from apiome_cli.spec_output import write_document_bytes

app = typer.Typer(
    name="lint",
    help="Score schema quality, list lint findings, and run the CI lint gate.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: Artifact formats the gate endpoint can emit besides the default JSON payload.
GATE_FORMATS = ("json", "sarif", "junit", "markdown", "attestation")

#: The audited reason an ``apiome lint --fix`` apply records on the new revision.
FIX_APPLY_REASON = "Applied with apiome lint --fix"


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
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Apply the version's deterministic lint fixes as a new revision.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="With --fix: print the change (a unified diff by default) and write nothing.",
    ),
    only: str | None = typer.Option(
        None,
        "--only",
        help="With --fix: fix only these rule ids (comma-separated); an unknown id is refused.",
    ),
    allow_renames: bool = typer.Option(
        False,
        "--allow-renames",
        help="With --fix: include rename fixes. A breaking fix is never applied.",
    ),
    fix_format: str = typer.Option(
        "diff",
        "--fix-format",
        help="With --fix: how the change is printed or written: diff | patch | overlay.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="With --fix: write the change (--fix-format) to this file.",
    ),
) -> None:
    """Fetch the server-computed quality score and findings (GET .../lint).

    The score and A-F grade are computed by the REST service from the generated
    OpenAPI/JSON-Schema — deterministic for a fixed input. ``--base-version`` folds
    breaking-change risk into the report; ``--min-grade`` turns the report into a CI gate;
    ``--fail-on-policy`` also evaluates style-guide policy gates (GET .../lint/policy).

    ``--fix`` plans the version's deterministic lint fixes (GET .../lint/fixes) and applies the
    ready ones as a new revision (POST .../lint/fixes/apply), printing its id. ``--dry-run``
    prints the change instead and writes nothing. Exit codes: 0 when nothing is left to fix or
    every ready fix was applied, 3 when breaking or conflicting fixes remain for a person
    (never with ``--dry-run``), 2 for a refused request such as an unknown ``--only`` rule.
    """
    if ctx.invoked_subcommand:
        return

    _check_fix_options(
        fix=fix,
        dry_run=dry_run,
        only=only,
        allow_renames=allow_renames,
        fix_format=fix_format,
        output=output,
        other_options=bool(base_version or min_grade or fail_on_policy),
    )
    fix_rules = _parse_only(only)

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

    if fix:
        _run_fix(
            ctx,
            client,
            fixes_path=api_paths.version_lint_fixes(tenant_slug, project_id, version_id),
            apply_path=api_paths.version_lint_fixes_apply(tenant_slug, project_id, version_id),
            dry_run=dry_run,
            rules=fix_rules,
            allow_renames=allow_renames,
            fix_format=fix_format.strip().lower(),
            output=output,
        )
        return

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


def _parse_only(only: str | None) -> list[str] | None:
    """The distinct rule ids of ``--only``, in the order given, or ``None`` when not given.

    Raises:
        typer.BadParameter: ``--only`` was given but names no rule.
    """
    if only is None:
        return None
    rules = list(dict.fromkeys(part.strip() for part in only.split(",") if part.strip()))
    if not rules:
        raise typer.BadParameter("name at least one rule id", param_hint="--only")
    return rules


def _check_fix_options(
    *,
    fix: bool,
    dry_run: bool,
    only: str | None,
    allow_renames: bool,
    fix_format: str,
    output: Path | None,
    other_options: bool,
) -> None:
    """Refuse fix options without ``--fix``, and report options together with ``--fix``.

    Args:
        fix: ``--fix``.
        dry_run, only, allow_renames, fix_format, output: The options that only mean
            something with ``--fix``.
        other_options: Whether a report-only option (``--base-version``, ``--min-grade``,
            ``--fail-on-policy``) was given.

    Raises:
        typer.BadParameter: An invalid combination.
    """
    if not fix:
        given = [
            name
            for name, used in (
                ("--dry-run", dry_run),
                ("--only", only is not None),
                ("--allow-renames", allow_renames),
                ("--fix-format", fix_format != "diff"),
                ("--output", output is not None),
            )
            if used
        ]
        if given:
            raise typer.BadParameter(
                f"{', '.join(given)} only work with --fix", param_hint="--fix"
            )
        return
    if other_options:
        raise typer.BadParameter(
            "--fix cannot be combined with --base-version, --min-grade or --fail-on-policy",
            param_hint="--fix",
        )
    if fix_format.strip().lower() not in FIX_FORMATS:
        raise typer.BadParameter(
            f"must be one of {', '.join(FIX_FORMATS)}", param_hint="--fix-format"
        )


def _run_fix(
    ctx: typer.Context,
    client: RestClient,
    *,
    fixes_path: str,
    apply_path: str,
    dry_run: bool,
    rules: list[str] | None,
    allow_renames: bool,
    fix_format: str,
    output: Path | None,
) -> None:
    """Plan a version's lint fixes, then print the change (dry run) or apply the ready fixes.

    Only ``ready`` fixes are ever applied — by their ids, or, with ``--only``, by their rules
    (the server re-plans with the same rules, so both name the same set). A ``breaking`` fix is
    never ready, whatever the flags, so it is never written.

    Args:
        ctx: The Typer context (``--json``).
        client: The authenticated REST client.
        fixes_path: ``GET …/lint/fixes`` of the version.
        apply_path: ``POST …/lint/fixes/apply`` of the version.
        dry_run: Print the change and write nothing.
        rules: ``--only`` rule ids, or ``None`` for every rule.
        allow_renames: ``--allow-renames``.
        fix_format: ``diff``, ``patch`` or ``overlay``.
        output: ``--output`` file, or ``None``.

    Raises:
        typer.Exit: With the exit code of :func:`apiome_cli.lint_fix_output.fix_exit_code`.
    """
    params: dict[str, str] = {}
    if rules:
        params["rules"] = ",".join(rules)
    if allow_renames:
        params["includeRenames"] = "true"
    plan = client.get(f"{fixes_path}?{urlencode({**params, 'format': 'json'})}").json()
    ready = ready_fix_ids(plan)
    json_mode = json_mode_from_context(ctx)

    # The change goes to --output, or to stdout on a human dry run (the summary then moves to
    # stderr so the diff can be piped). It is fetched from the planned revision, before an apply.
    rendering_to_stdout = dry_run and output is None and not json_mode
    if ready and (output is not None or rendering_to_stdout):
        query = urlencode({**params, "format": fix_format})
        body = client.get(f"{fixes_path}?{query}").content
        write_document_bytes(body, str(output) if output is not None else "-")

    result = None
    if ready and not dry_run:
        apply_body: dict[str, object] = {
            "reason": FIX_APPLY_REASON,
            "includeRenames": allow_renames,
        }
        if rules:
            apply_body["rules"] = rules
        else:
            apply_body["fixIds"] = ready
        result = client.post(apply_path, json=apply_body).json()

    if json_mode:
        emit_json(plan if dry_run else {"plan": plan, "applied": result})
    else:
        err = rendering_to_stdout and bool(ready)
        for line in format_fix_plan(plan):
            typer.echo(line, err=err)
        if result is not None:
            for line in format_fix_applied(result):
                typer.echo(line, err=err)
        elif dry_run and ready:
            typer.echo("Dry run: nothing was written.", err=err)
        if not dry_run:
            for line in format_remaining(plan):
                typer.echo(line, err=err)

    code = fix_exit_code(plan, dry_run=dry_run)
    if code:
        raise typer.Exit(code)


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
    exit 0. The maturity level line (GVM-1.3) is always printed when the guide has a ladder;
    it changes the exit code only when the pack's ``failOnMaturityLevel`` toggle is on. The verdict is always fetched as JSON; a non-json ``--format`` additionally
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
        maturity_line = maturity_gate_line(gate_payload)
        if maturity_line:
            typer.echo(maturity_line, err=True)
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
