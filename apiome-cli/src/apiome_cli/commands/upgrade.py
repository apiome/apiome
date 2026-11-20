"""Upgrade an OpenAPI / Swagger document to a newer OpenAPI version (COA-2.6, #7049).

``apiome upgrade FILE --to 3.2`` plans the upgrade of a local document and prints every change
(``--output`` writes the upgraded document). ``apiome upgrade --project P [--version V] --to 3.2``
plans the upgrade of a project or catalog item version; add ``--apply`` to store the upgraded
document as a new version (``--version-label`` names it). Thin client over
``POST /v1/openapi-upgrade/{tenant}/plan`` and ``…/apply``: the apply sends the plan's digest, so a
version that changed between the two calls is refused rather than upgraded unseen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.spec_output import write_document_bytes
from apiome_cli.upgrade_output import format_upgrade_applied, format_upgrade_plan

#: The target families the REST route accepts.
UPGRADE_TARGETS = ("3.0", "3.1", "3.2")


def _usage(message: str) -> typer.Exit:
    """Print a usage error and return the exit to raise."""
    typer.echo(message, err=True)
    return typer.Exit(EXIT_USAGE)


def _read_source(path: str) -> str:
    """Read the document text from ``path`` (``-`` for stdin)."""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise _usage(f"Cannot read {path}: {exc}") from exc


def serialize_document(document: Any, output: str) -> bytes:
    """The upgraded document as bytes: YAML for a ``.yaml`` / ``.yml`` output, else JSON."""
    if output != "-" and Path(output).suffix.lower() in (".yaml", ".yml"):
        from yaml12 import format_yaml  # imported here: only the YAML path needs it

        return format_yaml(document).encode("utf-8")
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def upgrade(
    ctx: typer.Context,
    file: str | None = typer.Argument(
        None, help="OpenAPI / Swagger document to upgrade ('-' for stdin)."
    ),
    to: str = typer.Option(
        ..., "--to", help="Target OpenAPI version: 3.0, 3.1 or 3.2."
    ),
    project: str | None = typer.Option(
        None, "--project", help="Project or catalog item (id or slug) to upgrade."
    ),
    version: str | None = typer.Option(
        None, "--version", help="Version to upgrade (id or label; default: latest)."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Store the upgraded document as a new version (--project only).",
    ),
    version_label: str | None = typer.Option(
        None,
        "--version-label",
        help="Label of the new version (with --apply; default: a date/time label).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the upgraded document here ('-' for stdout; .yaml writes YAML).",
    ),
    summary: bool = typer.Option(
        False, "--summary", help="Print the count per rule, not every change."
    ),
) -> None:
    """Plan (and optionally apply) an upgrade to OpenAPI 3.0, 3.1 or 3.2, listing every change."""
    target = to.strip()
    if target not in UPGRADE_TARGETS:
        raise _usage(f"--to must be one of {', '.join(UPGRADE_TARGETS)} (got {to!r}).")
    if bool(file) == bool(project):
        raise _usage("Give a FILE or --project, not both and not neither.")
    if file and (apply or version or version_label):
        raise _usage(
            "--apply, --version and --version-label work with --project, not a FILE."
        )
    if version_label and not apply:
        raise _usage("--version-label names the version --apply creates; add --apply.")

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)

    body: dict[str, Any] = {"target": target, "include_document": output is not None}
    if file:
        body["document_text"] = _read_source(file)
    else:
        body["project_id"] = str(
            resolve_project_uuid(client, tenant_slug, project or "")
        )
        if version:
            body["version"] = version
    plan = client.post(api_paths.openapi_upgrade_plan(tenant_slug), json=body).json()

    if output is not None and not plan.get("already_current"):
        write_document_bytes(serialize_document(plan.get("document"), output), output)

    result: dict[str, Any] | None = None
    if apply and not plan.get("already_current"):
        apply_body: dict[str, Any] = {
            "target": target,
            "project_id": body["project_id"],
            "plan_digest": plan["plan_digest"],
        }
        if version:
            apply_body["version"] = version
        if version_label:
            apply_body["version_label"] = version_label
        result = client.post(
            api_paths.openapi_upgrade_apply(tenant_slug), json=apply_body
        ).json()

    if json_mode_from_context(ctx):
        plan.pop("document", None)
        emit_json({"plan": plan, "applied": result} if apply else plan)
        return
    # The plan goes to stderr when the document itself is written to stdout.
    err = output == "-"
    for line in format_upgrade_plan(plan, summary_only=summary):
        typer.echo(line, err=err)
    if result is not None:
        typer.echo("", err=err)
        for line in format_upgrade_applied(result):
            typer.echo(line, err=err)
    elif project and not plan.get("already_current"):
        typer.echo("", err=err)
        typer.echo(
            "Nothing was written. Run again with --apply to create the upgraded version.",
            err=err,
        )
