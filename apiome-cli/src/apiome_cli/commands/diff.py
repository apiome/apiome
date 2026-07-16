"""CI classified-diff gate: ``apiome diff <file> --against <project>@<ref>`` (CTG-2.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import format_api_error, format_connection_error
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.output import json_mode_from_context
from apiome_cli.output_diff import (
    INLINE_SPEC_MAX_BYTES,
    format_diff_json,
    format_diff_text,
    gate_should_fail,
    parse_against,
)

_FORMATS = ("text", "json", "md")
_FAIL_ON = ("breaking", "warn")


def _exit_operational(message: str) -> None:
    """Print an operational error and exit 2 (distinct from gate failure exit 1)."""
    typer.echo(message, err=True)
    raise typer.Exit(EXIT_USAGE)


def _read_inline_spec(path: Path) -> str:
    """Load a local OpenAPI file as UTF-8 text, enforcing the 10MB inline cap."""
    if not path.is_file():
        _exit_operational(f"Spec file not found: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _exit_operational(f"Cannot read spec file: {exc}")
    if len(raw) > INLINE_SPEC_MAX_BYTES:
        _exit_operational(
            f"Inline OpenAPI document exceeds the {INLINE_SPEC_MAX_BYTES}-byte "
            f"limit ({len(raw)} bytes)"
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _exit_operational(f"Spec file is not valid UTF-8: {exc}")


def _post_classified(
    client: Any,
    path: str,
    body: dict[str, Any],
    *,
    accept: str,
) -> httpx.Response:
    """POST classified diff; map HTTP and transport failures to exit 2."""
    try:
        response = client.post_raw(path, json=body, headers={"Accept": accept})
    except typer.Exit as exc:
        # post_raw maps connection errors to EXIT_ERROR; remap to exit 2.
        if exc.exit_code == EXIT_ERROR:
            raise typer.Exit(EXIT_USAGE) from exc
        raise
    except httpx.RequestError as exc:
        _exit_operational(format_connection_error(exc))
    if not response.is_success:
        _exit_operational(format_api_error(response))
    return response


def diff(
    ctx: typer.Context,
    file: Path = typer.Argument(
        ...,
        exists=False,
        dir_okay=False,
        help="Path to the candidate OpenAPI YAML/JSON file.",
    ),
    against: str = typer.Option(
        ...,
        "--against",
        help="Stored baseline as <project>@<version|latest> (e.g. payments@latest).",
    ),
    fail_on: str = typer.Option(
        "breaking",
        "--fail-on",
        help=(
            "Exit 1 when changes at this level or higher are present: "
            "breaking (default) or warn (non-breaking and breaking). "
            "docs-only alone never fails. Exit 2 on auth/network/parse errors."
        ),
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text (default), json, or md (CTG-1.3 markdown changelog).",
    ),
) -> None:
    """Diff a local OpenAPI file against a published project version (CI gate).

    Uploads ``file`` as an inline candidate and classifies against a stored version
    via ``POST /v1/diff/{tenant}/classified``. Exit codes: ``0`` = gate passed,
    ``1`` = threshold met, ``2`` = operational error.
    """
    fmt = (output_format or "text").strip().lower()
    if json_mode_from_context(ctx):
        fmt = "json"
    if fmt not in _FORMATS:
        raise typer.BadParameter(
            "must be one of text, json, md",
            param_hint="--format",
        )
    fail_level = (fail_on or "breaking").strip().lower()
    if fail_level not in _FAIL_ON:
        raise typer.BadParameter(
            "must be one of breaking, warn",
            param_hint="--fail-on",
        )

    try:
        project, version_ref = parse_against(against)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--against") from exc

    # Remap setup/HTTP EXIT_ERROR → 2 so gate failure (1) stays distinguishable.
    try:
        client, tenant_slug = tenant_scoped_client(ctx)
        inline = _read_inline_spec(file)
        post_path = api_paths.classified_diff(tenant_slug)
        body = {
            "base": {"project": project, "version": version_ref},
            "head": {"inline": inline},
        }

        json_response = _post_classified(
            client,
            post_path,
            body,
            accept="application/json",
        )
        try:
            payload = json_response.json()
        except ValueError as exc:
            _exit_operational(f"Invalid JSON from classified diff: {exc}")
        if not isinstance(payload, dict):
            _exit_operational("Invalid JSON from classified diff: expected object")

        if fmt == "md":
            md_response = _post_classified(
                client,
                post_path,
                body,
                accept="text/markdown",
            )
            typer.echo(md_response.text, nl=not md_response.text.endswith("\n"))
        elif fmt == "json":
            typer.echo(format_diff_json(payload))
        else:
            typer.echo(format_diff_text(payload))

        max_severity = payload.get("maxSeverity")
        if isinstance(max_severity, str):
            max_sev: str | None = max_severity
        else:
            max_sev = None
        should_fail = gate_should_fail(max_sev, fail_level)
    except typer.Exit as exc:
        if exc.exit_code == EXIT_ERROR:
            raise typer.Exit(EXIT_USAGE) from exc
        raise

    if should_fail:
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(EXIT_SUCCESS)
