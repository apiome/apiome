"""MCP catalog and governance commands.

Catalog subcommands (``register`` / ``list`` / ``show`` / ``discover`` / ``lint``)
use Tier 2 API key auth against ``/v1/mcp/{tenant_slug}/endpoints``. Governance
subcommands (``policy``, ``key capabilities``) use a tenant-admin session bearer
against ``/v1/tenants/{tenant_slug}/mcp-policy`` and ``…/mcp-keys/…`` (MTG-5.3).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import typer

from apiome_cli.cli_context import (
    import_timeout_from_context,
    insecure_from_context,
    json_mode_from_context,
    no_progress_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.mcp_discovery import (
    emit_discovery_completed,
    emit_discovery_enqueue_result,
    wait_for_discovery_job,
)
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.commands.mcp_governance import key_app, policy_app
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.import_.jobs import DEFAULT_POLL_INTERVAL
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_table,
)
from apiome_cli.output_lint import emit_lint_command_output, lint_command_should_fail

# Letter grades accepted by ``--min-grade`` (mirrors the project ``lint`` command).
_LINT_GRADES = frozenset({"A", "B", "C", "D", "F"})

# MCP conformance gate vocabulary (mirrors the REST query-param enums; validated
# locally so a typo is a usage error rather than a 422 round-trip).
_CONFORMANCE_PROFILES = ("mcp-conformance", "mcp-protocol", "mcp-agent-readiness")
_CONFORMANCE_FORMATS = ("json", "sarif", "junit")
_CONFORMANCE_FAIL_ON = ("error", "warning", "info", "none")

app = typer.Typer(
    name="mcp",
    help=(
        "MCP catalog endpoints and tenant governance "
        "(policy / key capabilities)."
    ),
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)
app.add_typer(policy_app, name="policy")
app.add_typer(key_app, name="key")

# Mirrors ``MCP_ENDPOINT_TRANSPORTS`` / ``MCP_ENDPOINT_VISIBILITIES`` in the REST
# models; the server re-validates, but rejecting locally yields a usage exit code
# and a clearer message than a round-trip 422.
_MCP_TRANSPORTS = frozenset({"streamable_http", "sse", "stdio"})
_MCP_VISIBILITIES = frozenset({"private", "public"})

# Widen the render target for the wide list table when output is piped/CI, so
# columns are not squeezed to the 80-column fallback (see ``emit_list_table``).
_MCP_LIST_MIN_WIDTH = 140


@app.callback(invoke_without_command=True)
def mcp_group(ctx: typer.Context) -> None:
    """MCP catalog command group."""
    group_callback_without_subcommand(ctx)


def _scoped_client(
    ctx: typer.Context,
    *,
    timeout: float | None = None,
) -> tuple[RestClient, str]:
    """Build an API-key REST client and resolve the configured tenant slug.

    ``timeout`` overrides the per-request HTTP read timeout (used by the discovery
    poll loop so a long-running run is not cut off at the 30s default); when omitted
    the global ``--timeout`` / default applies.
    """
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout if timeout is not None else timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    return client, tenant_slug


def _json_output(ctx: typer.Context, output: str | None) -> bool:
    """Return True when global ``--json`` or local ``--output json`` was requested."""
    if output == "json":
        return True
    if output is not None and output != "table":
        msg = "--output must be 'table' or 'json'."
        raise typer.BadParameter(msg)
    return json_mode_from_context(ctx)


def _normalize_transport(transport: str) -> str:
    """Validate ``--transport`` against the REST transport enum."""
    normalized = transport.strip().lower()
    if normalized in _MCP_TRANSPORTS:
        return normalized
    msg = "--transport must be streamable_http, sse, or stdio."
    raise typer.BadParameter(msg)


def _normalize_visibility(visibility: str) -> str:
    """Validate ``--visibility`` against the REST visibility enum."""
    normalized = visibility.strip().lower()
    if normalized in _MCP_VISIBILITIES:
        return normalized
    msg = "--visibility must be 'private' or 'public'."
    raise typer.BadParameter(msg)


def _credential_body(bearer: str | None, header: str | None) -> dict[str, Any] | None:
    """Build a credential upsert body from ``--bearer`` / ``--header``.

    ``--bearer TOKEN`` seals a bearer token; ``--header NAME:VALUE`` seals a
    custom header secret. The two are mutually exclusive. Returns ``None`` when
    neither flag was supplied (the endpoint stays anonymous).
    """
    if bearer is not None and header is not None:
        msg = "Use either --bearer or --header, not both."
        raise typer.BadParameter(msg)
    if bearer is not None:
        token = bearer.strip()
        if not token:
            msg = "--bearer must not be empty."
            raise typer.BadParameter(msg)
        return {"auth_type": "bearer", "payload": {"token": token}}
    if header is not None:
        name, sep, value = header.partition(":")
        if not sep or not name.strip() or not value.strip():
            msg = "--header must be 'Name:Value' with a non-empty name and value."
            raise typer.BadParameter(msg)
        return {
            "auth_type": "header",
            "payload": {"name": name.strip(), "value": value.strip()},
        }
    return None


def _format_optional(value: object) -> str:
    """Render an optional cell, leaving missing values blank."""
    return "" if value in (None, "") else str(value)


_MCP_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("Transport", "transport", None),
    ("Visibility", "visibility", None),
    ("URL", "endpoint_url", None),
    ("Last Discovered", "last_discovered_at", _format_optional),
)

_MCP_SHOW_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Slug", "slug", None),
    ("URL", "endpoint_url", None),
    ("Transport", "transport", None),
    ("Description", "description", _format_optional),
    ("Category", "category", _format_optional),
    ("Visibility", "visibility", None),
    ("Published", "published", None),
    ("Enabled", "enabled", None),
    ("Discovery cadence (s)", "discovery_cadence_seconds", _format_optional),
    ("Last discovered", "last_discovered_at", _format_optional),
    ("Last discovery status", "last_discovery_status", _format_optional),
    ("Consecutive failures", "consecutive_failures", None),
    ("Quarantined", "quarantined", None),
    ("Quarantine reason", "quarantine_reason", _format_optional),
    ("Current version", "current_version_id", _format_optional),
    ("Created", "created_at", _format_optional),
    ("Updated", "updated_at", _format_optional),
)


@app.command("register")
def register_endpoint(
    ctx: typer.Context,
    name: str = typer.Option(
        ...,
        "--name",
        help="Human-readable endpoint name.",
    ),
    url: str = typer.Option(
        ...,
        "--url",
        help="MCP server URL (http/https for streamable_http/sse).",
    ),
    transport: str = typer.Option(
        "streamable_http",
        "--transport",
        help="MCP transport: streamable_http (default), sse, or stdio.",
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help="Optional catalog slug; derived from --name and uniquified when omitted.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional endpoint description.",
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        help="Optional catalog category.",
    ),
    visibility: str = typer.Option(
        "private",
        "--visibility",
        help="Catalog visibility: private (default) or public.",
    ),
    bearer: str | None = typer.Option(
        None,
        "--bearer",
        help="Seal a bearer token as the endpoint's outbound credential.",
    ),
    header: str | None = typer.Option(
        None,
        "--header",
        help="Seal a custom header secret as 'Name:Value'.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Register an MCP server in the tenant catalog (POST /v1/mcp/{tenant}/endpoints)."""
    trimmed_name = name.strip()
    if not trimmed_name:
        msg = "--name must not be empty."
        raise typer.BadParameter(msg)
    trimmed_url = url.strip()
    if not trimmed_url:
        msg = "--url must not be empty."
        raise typer.BadParameter(msg)

    credential = _credential_body(bearer, header)

    body: dict[str, Any] = {
        "name": trimmed_name,
        "endpoint_url": trimmed_url,
        "transport": _normalize_transport(transport),
        "visibility": _normalize_visibility(visibility),
    }
    if slug is not None and slug.strip():
        body["slug"] = slug.strip()
    if description is not None and description.strip():
        body["description"] = description.strip()
    if category is not None and category.strip():
        body["category"] = category.strip()

    client, tenant_slug = _scoped_client(ctx)

    response = client.post(api_paths.mcp_endpoints(tenant_slug), json=body)
    payload = response.json()
    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None

    # Attach the outbound credential once the endpoint exists (PUT credentials).
    if credential is not None and isinstance(endpoint, dict):
        endpoint_id = endpoint.get("id")
        if isinstance(endpoint_id, str) and endpoint_id:
            client.put(
                api_paths.mcp_endpoint_credentials(tenant_slug, endpoint_id),
                json=credential,
            )

    if _json_output(ctx, output):
        emit_json(payload)
        return

    if isinstance(endpoint, dict):
        emit_record_table(endpoint, _MCP_SHOW_FIELDS)
        if credential is not None:
            typer.echo(f"Credential set ({credential['auth_type']}).")
    else:
        emit_json(payload)


@app.command("list")
def list_endpoints(
    ctx: typer.Context,
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """List MCP catalog endpoints (GET /v1/mcp/{tenant}/endpoints)."""
    client, tenant_slug = _scoped_client(ctx)
    response = client.get(api_paths.mcp_endpoints(tenant_slug))
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    if not isinstance(endpoints, list):
        emit_json(payload)
        return
    emit_list_table(
        endpoints,
        _MCP_LIST_COLUMNS,
        empty_message="No MCP endpoints.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


@app.command("show")
def show_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Show one MCP catalog endpoint (GET /v1/mcp/{tenant}/endpoints/{id})."""
    client, tenant_slug = _scoped_client(ctx)
    response = client.get(api_paths.mcp_endpoint(tenant_slug, endpoint_id))
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    if not isinstance(endpoint, dict):
        emit_json(payload)
        return
    emit_record_table(endpoint, _MCP_SHOW_FIELDS)


def _resolve_import_timeout(ctx: typer.Context, override: float | None) -> float:
    """Prefer an explicit ``--import-timeout`` over the context (``--timeout``/default)."""
    if override is not None and override > 0:
        return float(override)
    return import_timeout_from_context(ctx)


def _fetch_version_lint(
    client: RestClient,
    tenant_slug: str,
    endpoint_id: str,
    version_id: str,
) -> dict[str, Any] | None:
    """Best-effort read of a version snapshot's lint score/grade.

    Returns the lint report dict, or ``None`` when the version has no readable
    score — a missing score must never fail an otherwise-successful discovery, so
    HTTP errors here are swallowed (``get_raw`` does not exit on 4xx/5xx).
    """
    response = client.get_raw(
        api_paths.mcp_endpoint_version_lint(tenant_slug, endpoint_id, version_id)
    )
    if not response.is_success:
        return None
    body = response.json()
    return body if isinstance(body, dict) else None


@app.command("discover")
def discover_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll the discovery job until terminal (default: wait).",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        min=0.1,
        help="Seconds between discovery-job status polls when waiting.",
    ),
    import_timeout: float | None = typer.Option(
        None,
        "--import-timeout",
        min=1.0,
        help=(
            "Max seconds to wait for the discovery run to finish, and the per-request "
            "HTTP timeout used while waiting (default 120). Overrides --timeout."
        ),
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Trigger a discovery run and poll it to completion.

    Posts ``POST /v1/mcp/{tenant}/endpoints/{id}/discover`` to enqueue a manual
    discovery job, then (unless ``--no-wait``) polls
    ``GET …/endpoints/{id}/jobs/{job_id}`` until the run reaches a terminal state and
    prints the new version, change summary, and best-effort quality score. Exits
    non-zero on a failed run or a timeout.
    """
    json_mode = _json_output(ctx, output)
    resolved_timeout = _resolve_import_timeout(ctx, import_timeout)
    client, tenant_slug = _scoped_client(ctx, timeout=resolved_timeout)

    endpoint_str = str(endpoint_id)
    response = client.post(api_paths.mcp_endpoint_discover(tenant_slug, endpoint_str))
    payload = response.json()
    deduplicated = bool(payload.get("deduplicated")) if isinstance(payload, dict) else False

    if not wait:
        emit_discovery_enqueue_result(payload, json_mode=json_mode)
        return

    job = payload.get("job") if isinstance(payload, dict) else None
    job_id = job.get("id") if isinstance(job, dict) else None
    if not isinstance(job_id, str) or not job_id:
        typer.echo("Discovery trigger response missing job id.", err=True)
        raise typer.Exit(EXIT_ERROR)

    terminal = wait_for_discovery_job(
        client,
        tenant_slug,
        endpoint_str,
        job_id,
        poll_interval=poll_interval,
        timeout=resolved_timeout,
        no_progress=no_progress_from_context(ctx),
    )

    lint = None
    version_id = terminal.get("version_id")
    if isinstance(version_id, str) and version_id:
        lint = _fetch_version_lint(client, tenant_slug, endpoint_str, version_id)

    emit_discovery_completed(
        terminal,
        deduplicated=deduplicated,
        lint=lint,
        json_mode=json_mode,
    )


def _resolve_lint_version_id(
    client: RestClient,
    tenant_slug: str,
    endpoint_id: str,
    version: UUID | None,
) -> str:
    """Resolve which version snapshot to lint.

    Prefers an explicit ``--version`` snapshot id; when omitted, reads the endpoint's
    ``current_version_id`` (the latest discovered surface). Exits with an actionable
    message when the endpoint has never been discovered, so the caller is not handed
    an opaque 404 from the lint route.
    """
    if version is not None:
        return str(version)

    response = client.get(api_paths.mcp_endpoint(tenant_slug, endpoint_id))
    payload = response.json()
    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    current = endpoint.get("current_version_id") if isinstance(endpoint, dict) else None
    if not isinstance(current, str) or not current:
        typer.echo(
            "Endpoint has no current version yet — run 'mcp discover' first, "
            "or pass --version <id>.",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR)
    return current


@app.command("lint")
def lint_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    version: UUID | None = typer.Option(
        None,
        "--version",
        help="Version snapshot UUID to score (default: the endpoint's current version).",
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
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Score a version snapshot and list its lint findings (GET .../versions/{id}/lint).

    The MCP-catalog analogue of the project ``lint`` command: the server computes a
    deterministic 0-100 quality score, an A-F grade, and itemized findings for a
    discovered surface snapshot. ``--version`` targets a specific snapshot; omitted, the
    endpoint's current version is scored. ``--min-grade`` turns the report into a CI gate;
    ``--fail-on-policy`` also evaluates style-guide policy gates (GET .../lint/policy).
    """
    if min_grade is not None and min_grade.strip().upper() not in _LINT_GRADES:
        raise typer.BadParameter(
            "must be one of A, B, C, D, F",
            param_hint="--min-grade",
        )

    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    endpoint_str = str(endpoint_id)
    version_id = _resolve_lint_version_id(client, tenant_slug, endpoint_str, version)

    report = client.get(
        api_paths.mcp_endpoint_version_lint(tenant_slug, endpoint_str, version_id)
    ).json()

    policy = None
    if fail_on_policy:
        policy = client.get(
            api_paths.mcp_version_lint_policy(tenant_slug, endpoint_str, version_id)
        ).json()

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


def _registry_client(ctx: typer.Context) -> RestClient:
    """Build an API-key REST client for registry-level (untenanted) MCP reads."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )


def _normalize_choice(value: str, choices: tuple[str, ...], param_hint: str) -> str:
    """Validate one enum-ish option locally, raising a usage error on a bad value."""
    normalized = (value or choices[0]).strip().lower()
    if normalized not in choices:
        raise typer.BadParameter(
            f"must be one of {', '.join(choices)}",
            param_hint=param_hint,
        )
    return normalized


def _emit_conformance_human(report: dict[str, Any]) -> None:
    """Print a readable conformance summary: score, gate, findings, skipped rules."""
    profile = report.get("profile") or "?"
    spec_version = report.get("specVersion") or report.get("spec_version") or "?"
    typer.echo(f"MCP conformance profile: {profile}  (spec {spec_version})")
    typer.echo(f"Score: {report.get('score', '?')}/100  (grade {report.get('grade', '?')})")

    counts = report.get("severityCounts") or report.get("severity_counts") or {}
    typer.echo(
        "Findings — errors: {e}, warnings: {w}, info: {i}".format(
            e=counts.get("error", 0),
            w=counts.get("warning", 0),
            i=counts.get("info", 0),
        )
    )

    gate = report.get("gate") or {}
    passed = bool(gate.get("passed"))
    typer.echo(f"Gate: {'PASSED' if passed else 'FAILED'} (fail-on {gate.get('failOn', 'error')})")
    for reason in gate.get("reasons") or []:
        typer.echo(f"  - {reason}")

    for finding in report.get("findings") or []:
        severity = finding.get("severity") or "?"
        rule = finding.get("rule") or finding.get("id") or "?"
        path_hint = finding.get("path") or ""
        message = finding.get("message") or ""
        typer.echo(f"  {severity:<8} {rule}  {path_hint}  {message}")

    skipped = report.get("skippedRules") or report.get("skipped_rules") or []
    if skipped:
        typer.echo(
            "NOT EVALUATED: the following rules were skipped because no protocol "
            "transcript was captured — they are not passing, they are unverified:"
        )
        for rule_id in skipped:
            typer.echo(f"  - {rule_id}")


@app.command("conformance")
def conformance_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    version: UUID | None = typer.Option(
        None,
        "--version",
        help="Version snapshot UUID to evaluate (default: the endpoint's current version).",
    ),
    profile: str = typer.Option(
        "mcp-conformance",
        "--profile",
        help=(
            "Rule profile: mcp-conformance (default), mcp-protocol, or "
            "mcp-agent-readiness."
        ),
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Gate output format: json (default), sarif, or junit.",
    ),
    fail_on: str = typer.Option(
        "error",
        "--fail-on",
        help=(
            "Exit non-zero when findings at this severity or higher are present: "
            "error (default), warning, info, or none."
        ),
    ),
    min_score: int | None = typer.Option(
        None,
        "--min-score",
        min=0,
        max=100,
        help="Exit non-zero when the conformance score is below this floor (0-100).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Evaluate MCP protocol conformance + agent-readiness (GET .../versions/{id}/conformance).

    The server evaluates the selected rule profile against a discovered surface snapshot
    and computes the CI gate from ``--fail-on`` / ``--min-score``; this command exits
    non-zero whenever that gate fails — including under ``--format sarif|junit``, which
    echo the raw gate artifact for CI ingestion (the gate is always read from the JSON
    report, never inferred from the artifact). Rules that need a protocol transcript are
    reported as *skipped* (not passing) when no transcript was captured.
    """
    profile_id = _normalize_choice(profile, _CONFORMANCE_PROFILES, "--profile")
    fmt = _normalize_choice(output_format, _CONFORMANCE_FORMATS, "--format")
    fail_level = _normalize_choice(fail_on, _CONFORMANCE_FAIL_ON, "--fail-on")

    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    endpoint_str = str(endpoint_id)
    version_id = _resolve_lint_version_id(client, tenant_slug, endpoint_str, version)

    base_path = api_paths.mcp_endpoint_version_conformance(
        tenant_slug, endpoint_str, version_id
    )
    query: dict[str, str] = {"profile": profile_id, "failOn": fail_level}
    if min_score is not None:
        query["minScore"] = str(min_score)

    # Always read the JSON report first: it carries the server-computed gate, which must
    # decide the exit code regardless of --format (mirrors the ``compat`` command). A
    # SARIF/JUnit run that skipped this would upload an artifact and exit 0 on a failing
    # gate — a silently green CI build.
    payload = client.get(f"{base_path}?{urlencode({**query, 'format': 'json'})}").json()
    report = payload if isinstance(payload, dict) else {}

    if fmt == "json":
        if json_mode:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _emit_conformance_human(report)
    else:
        # SARIF / JUnit bodies are raw artifacts, echoed verbatim for CI ingestion.
        artifact = client.get(f"{base_path}?{urlencode({**query, 'format': fmt})}").text
        typer.echo(artifact)

    gate = report.get("gate") or {}
    if not gate.get("passed", True):
        raise typer.Exit(EXIT_ERROR)


_CONFORMANCE_RULE_COLUMNS: tuple[ListColumn, ...] = (
    ("Rule", "ruleId", None),
    ("Severity", "severity", None),
    ("Category", "category", None),
    ("Spec", "specVersion", _format_optional),
    ("Reference", "specReference", _format_optional),
    ("Transcript", "requiresTranscript", _format_optional),
)


@app.command("conformance-rules")
def conformance_rules(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        help=(
            "Only list rules in this profile: mcp-conformance, mcp-protocol, or "
            "mcp-agent-readiness (default: all)."
        ),
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """List the MCP conformance rule catalog (GET /v1/mcp/conformance/rules).

    Each rule cites the MCP specification version it was written against and a source
    reference, so a failing gate can be traced back to the spec text that motivated it.
    """
    profile_id = (
        _normalize_choice(profile, _CONFORMANCE_PROFILES, "--profile")
        if profile is not None
        else None
    )

    json_mode = _json_output(ctx, output)
    client = _registry_client(ctx)

    path = api_paths.mcp_conformance_rules()
    if profile_id is not None:
        path = f"{path}?{urlencode({'profile': profile_id})}"
    payload = client.get(path).json()

    if json_mode:
        emit_json(payload)
        return

    if not isinstance(payload, dict):
        emit_json(payload)
        return

    spec_version = payload.get("specVersion") or payload.get("spec_version") or "?"
    typer.echo(f"MCP conformance rules (spec {spec_version})")
    for entry in payload.get("profiles") or []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or entry.get("profileId") or "?"
        typer.echo(f"  profile {entry.get('profileId', '?')}: {label}")

    rules = payload.get("rules")
    if not isinstance(rules, list):
        emit_json(payload)
        return
    emit_list_table(
        rules,
        _CONFORMANCE_RULE_COLUMNS,
        empty_message="No conformance rules.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )
