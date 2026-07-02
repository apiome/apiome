"""Quality-scoring / lint command for a project version (read-only)."""

from __future__ import annotations

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.project_version_resolve import resolve_version_uuid
from apiome_cli.client.version_scope import resolve_version_scope
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.output_lint import emit_lint_report, grade_meets_minimum

app = typer.Typer(
    name="lint",
    help="Score schema quality and list lint findings for a project version.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def lint(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
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
) -> None:
    """Fetch the server-computed quality score and findings (GET .../lint).

    The score and A-F grade are computed by the REST service from the generated
    OpenAPI/JSON-Schema — deterministic for a fixed input. ``--base-version`` folds
    breaking-change risk into the report; ``--min-grade`` turns the report into a CI gate.
    """
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

    if json_mode_from_context(ctx):
        emit_json(report)
    else:
        emit_lint_report(report)

    if min_grade is not None and not grade_meets_minimum(str(report.get("grade", "")), min_grade):
        raise typer.Exit(EXIT_ERROR)
