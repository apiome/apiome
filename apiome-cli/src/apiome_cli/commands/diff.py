"""CI classified-diff gate: ``apiome diff <file> --against <project>@<ref>`` (CTG-2.1).

``--blast-radius`` (CDG-3.6, #5971) adds what each breaking change affects in the dependency graph.

``--mode`` / ``--transitive`` / ``--category`` (XPC-4.5, #5749) choose the compatibility mode the
server grades by; left off, the baseline project's style-guide policy applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import format_api_error, format_connection_error
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.compat_modes import mode_request_fields
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
    """Load a local candidate file as UTF-8 text, enforcing the 10MB inline cap."""
    if not path.is_file():
        _exit_operational(f"Spec file not found: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _exit_operational(f"Cannot read spec file: {exc}")
    if len(raw) > INLINE_SPEC_MAX_BYTES:
        _exit_operational(
            f"Inline document exceeds the {INLINE_SPEC_MAX_BYTES}-byte "
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
        help=(
            "Path to the candidate file: OpenAPI YAML/JSON, or the baseline's own format "
            "(an Avro .avsc, a JSON Schema, an AsyncAPI document, a .proto)."
        ),
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
    consumers: bool = typer.Option(
        False,
        "--consumers",
        help=(
            "Add the CTG-4.2 per-consumer analysis: which registered consumers of the baseline "
            "project this change breaks. Needs consumer_contracts:view."
        ),
    ),
    blast_radius: bool = typer.Option(
        False,
        "--blast-radius",
        help=(
            "Add the CDG-3.3 blast radius to each breaking change: \"affects N consumers across M "
            "teams (…); K verification runs invalidated\". Needs projects:view."
        ),
    ),
    mode: str | None = typer.Option(
        None,
        "--mode",
        show_default="project policy",
        help=(
            "Compatibility mode: backward, forward, full or none (optionally with _transitive, "
            "e.g. full_transitive). Applies to Avro, JSON Schema and AsyncAPI baselines. "
            "Default: the project's style-guide policy."
        ),
    ),
    transitive: bool | None = typer.Option(
        None,
        "--transitive/--no-transitive",
        show_default="project policy",
        help=(
            "Also compare against every earlier version of the baseline, not only the baseline. "
            "Default: the project's style-guide policy."
        ),
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        show_default="project policy",
        help=(
            "Protobuf buf breaking category: wire, wire_json, package or file. "
            "Default: the project's style-guide policy."
        ),
    ),
) -> None:
    """Diff a local OpenAPI file against a published project version (CI gate).

    Uploads ``file`` as an inline candidate and classifies against a stored version
    via ``POST /v1/diff/{tenant}/classified``. Exit codes: ``0`` = gate passed,
    ``1`` = threshold met, ``2`` = operational error.

    With ``--consumers`` the report also names *whose* build each change breaks
    ("breaks billing-service") in all three formats. The threshold is unchanged: it still
    grades the whole specification, so a passing gate never depends on who has registered.

    With ``--blast-radius`` each breaking change also says what it affects in the dependency
    graph — consumers reached directly or transitively, their owner teams, and the verification
    runs it invalidates — in all three formats. The threshold is unchanged here too.

    ``--mode``, ``--transitive`` and ``--category`` pick the compatibility mode the server grades
    by. Left off, the server uses the baseline project's policy, and the report says what it was
    graded under. For an Avro, JSON Schema, AsyncAPI or Protobuf baseline, ``file`` is read as the
    baseline's format; for any other format it must be OpenAPI.
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
    mode_fields = mode_request_fields(mode, transitive, category)

    # Remap setup/HTTP EXIT_ERROR → 2 so gate failure (1) stays distinguishable.
    try:
        client, tenant_slug = tenant_scoped_client(ctx)
        inline = _read_inline_spec(file)
        post_path = api_paths.classified_diff(tenant_slug)
        body: dict[str, Any] = {
            "base": {"project": project, "version": version_ref},
            "head": {"inline": inline},
        }
        if consumers:
            body["consumers"] = True
        if blast_radius:
            body["blastRadius"] = True
        body.update(mode_fields)

        # Markdown is fetched separately below; the JSON call then only needs the severity, so it
        # skips the per-change graph traversals.
        json_body = {k: v for k, v in body.items() if k != "blastRadius"} if fmt == "md" else body
        json_response = _post_classified(
            client,
            post_path,
            json_body,
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
