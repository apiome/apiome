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

# MCP trust-posture gate vocabulary (CLX-3.2, #4856). Mirrors the REST query-param enums, so a
# typo is a local usage error rather than a 422 round-trip.
_POSTURE_PROFILES = ("mcp-trust-posture", "mcp-metadata-posture", "mcp-supply-chain")

# MCP dynamic-probe profiles (CLX-3.3, #4857). Mirrors the REST enum; 'passive' is the read-only
# default, the two active profiles are consent-gated and audited.
_PROBE_PROFILES = ("passive", "safe-active", "payload-fuzzing")
# MCP trust-drift categories (CLX-3.4, #4858). Mirrors the REST engine's DRIFT_CATEGORIES; used to
# validate --gate values locally so a typo is a usage error rather than a 400 round-trip.
_DRIFT_CATEGORIES = (
    "normal_change",
    "quality_regression",
    "security_regression",
    "coverage_loss",
)
_SOURCE_KINDS = ("git", "package", "image", "registry")
_SOURCE_PROVENANCES = (
    "operator_declared",
    "registry_published",
    "discovery_advertised",
    "attested",
)

app = typer.Typer(
    name="mcp",
    help=(
        "MCP catalog endpoints and tenant governance "
        "(policy / key capabilities)."
    ),
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

source_app = typer.Typer(
    name="source",
    help="Link and manage the source artifacts an MCP endpoint is built from (CLX-3.2).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)
app.add_typer(source_app, name="source")
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


# --- MCP source links & trust posture (CLX-3.2, #4856) ----------------------------------------

_SOURCE_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("Id", "id", None),
    ("Kind", "sourceKind", None),
    ("Locator", "locator", None),
    ("Revision", "revision", _format_optional),
    ("Pinned", "verificationState", None),
    ("Provenance", "provenance", None),
)


@source_app.command("link")
def source_link(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    kind: str = typer.Option(..., "--kind", help="Source kind: git, package, image, or registry."),
    reference: str = typer.Option(
        ...,
        "--reference",
        help="Source reference: a git URL, a purl, an OCI image ref, or a registry server id.",
    ),
    revision: str | None = typer.Option(
        None,
        "--revision",
        help="For git, the branch/tag/commit. A full 40-hex commit sha pins the source.",
    ),
    provenance: str = typer.Option(
        "operator_declared",
        "--provenance",
        help="How the link is known: operator_declared (default), registry_published, "
        "discovery_advertised, or attested.",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Link a source artifact to an MCP endpoint (POST .../endpoints/{id}/sources).

    The pin strength is derived by the server from whether the reference actually carries an
    immutable digest — a branch stays 'unverified', a commit sha becomes 'digest_pinned'.
    """
    kind_id = _normalize_choice(kind, _SOURCE_KINDS, "--kind")
    provenance_id = _normalize_choice(provenance, _SOURCE_PROVENANCES, "--provenance")

    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    body: dict[str, Any] = {
        "source_kind": kind_id,
        "reference": reference,
        "provenance": provenance_id,
    }
    if revision is not None:
        body["revision"] = revision

    payload = client.post(
        api_paths.mcp_endpoint_sources(tenant_slug, str(endpoint_id)), json=body
    ).json()

    if json_mode:
        emit_json(payload)
        return
    source = payload.get("source") if isinstance(payload, dict) else None
    if isinstance(source, dict):
        typer.echo(
            f"Linked {source.get('sourceKind')} source {source.get('id')}: "
            f"{source.get('locator')} ({source.get('verificationState')})"
        )
    else:
        emit_json(payload)


@source_app.command("list")
def source_list(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    include_retired: bool = typer.Option(
        False, "--include-retired", help="Include retired source links."
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """List an endpoint's linked sources (GET .../endpoints/{id}/sources)."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    path = api_paths.mcp_endpoint_sources(tenant_slug, str(endpoint_id))
    if include_retired:
        path = f"{path}?{urlencode({'includeRetired': 'true'})}"
    payload = client.get(path).json()

    if json_mode:
        emit_json(payload)
        return
    sources = payload.get("sources") if isinstance(payload, dict) else None
    emit_list_table(
        sources if isinstance(sources, list) else [],
        _SOURCE_LIST_COLUMNS,
        empty_message="No linked sources.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


@source_app.command("retire")
def source_retire(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    source_id: UUID = typer.Argument(..., help="Source association UUID to retire."),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Retire a linked source (DELETE .../sources/{id}). Soft delete — it stays readable."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    payload = client.delete(
        api_paths.mcp_endpoint_source(tenant_slug, str(endpoint_id), str(source_id))
    ).json()

    if json_mode:
        emit_json(payload)
        return
    typer.echo(f"Retired source {source_id}.")


def _emit_posture_human(report: dict[str, Any]) -> None:
    """Print a readable trust-posture summary: score, gate, findings, skipped rules, coverage."""
    profile = report.get("profile") or "?"
    owasp = report.get("owaspRevision") or report.get("owasp_revision") or "?"
    typer.echo(f"MCP trust posture profile: {profile}  (OWASP MCP {owasp})")
    typer.echo(f"Score: {report.get('score', '?')}/100  (grade {report.get('grade', '?')})")

    counts = report.get("severityCounts") or report.get("severity_counts") or {}
    typer.echo(
        "Findings — errors: {e}, warnings: {w}, info: {i}".format(
            e=counts.get("error", 0), w=counts.get("warning", 0), i=counts.get("info", 0)
        )
    )

    # The exploitability line is not decoration: it is the whole honesty contract of this scan.
    proven = report.get("provenCount") or report.get("proven_count") or 0
    typer.echo(
        f"Proven exploitable: {proven}  "
        f"(every other finding is a SIGNAL to review, not a demonstrated exploit)"
    )

    gate = report.get("gate") or {}
    passed = bool(gate.get("passed"))
    typer.echo(f"Gate: {'PASSED' if passed else 'FAILED'} (fail-on {gate.get('failOn', 'error')})")
    for reason in gate.get("reasons") or []:
        typer.echo(f"  - {reason}")

    for finding in report.get("findings") or []:
        severity = finding.get("severity") or "?"
        origin = finding.get("origin") or "?"
        rule = finding.get("rule") or finding.get("id") or "?"
        path_hint = finding.get("path") or ""
        owasp_ids = ",".join(finding.get("owaspIds") or finding.get("owasp_ids") or [])
        typer.echo(f"  {severity:<8} [{origin}] {rule}  {path_hint}  ({owasp_ids})")

    skipped = report.get("skippedRules") or report.get("skipped_rules") or []
    if skipped:
        typer.echo(
            "NOT EVALUATED: these rules were skipped for lack of evidence (a linked source, an "
            "SBOM, or a vulnerability lookup) — they are not passing, they are unverified:"
        )
        for rule_id in skipped:
            typer.echo(f"  - {rule_id}")


@app.command("trust-posture")
def trust_posture_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    version: UUID | None = typer.Option(
        None, "--version", help="Version snapshot UUID (default: the endpoint's current version)."
    ),
    profile: str = typer.Option(
        "mcp-trust-posture",
        "--profile",
        help="Profile: mcp-trust-posture (default), mcp-metadata-posture, or mcp-supply-chain.",
    ),
    output_format: str = typer.Option(
        "json", "--format", help="Gate output format: json (default), sarif, or junit."
    ),
    fail_on: str = typer.Option(
        "error",
        "--fail-on",
        help="Exit non-zero on findings at this severity or higher: error (default), warning, "
        "info, or none.",
    ),
    min_score: int | None = typer.Option(
        None, "--min-score", min=0, max=100, help="Exit non-zero when the score is below this floor."
    ),
    require_full_coverage: bool = typer.Option(
        False,
        "--require-full-coverage",
        help="Fail the gate when any rule was skipped for lack of evidence.",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Evaluate MCP source / supply-chain / trust posture (GET .../versions/{id}/trust-posture).

    Assesses what the server is built from — advertised metadata, linked source, dependencies —
    mapped to the OWASP MCP Top 10, and gates the result. Every finding is a SIGNAL a reviewer
    should confirm, never a demonstrated exploit: nothing is 'proven' until a dynamic probe exists
    (CLX-3.3). Rules whose evidence is absent are reported as skipped, never as passes.
    """
    profile_id = _normalize_choice(profile, _POSTURE_PROFILES, "--profile")
    fmt = _normalize_choice(output_format, _CONFORMANCE_FORMATS, "--format")
    fail_level = _normalize_choice(fail_on, _CONFORMANCE_FAIL_ON, "--fail-on")

    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    endpoint_str = str(endpoint_id)
    version_id = _resolve_lint_version_id(client, tenant_slug, endpoint_str, version)

    base_path = api_paths.mcp_endpoint_version_trust_posture(
        tenant_slug, endpoint_str, version_id
    )
    query: dict[str, str] = {"profile": profile_id, "failOn": fail_level}
    if min_score is not None:
        query["minScore"] = str(min_score)
    if require_full_coverage:
        query["requireFullCoverage"] = "true"

    # Read the JSON report first for the server-computed gate, which decides the exit code
    # regardless of --format (mirrors the conformance command). A SARIF/JUnit run that skipped this
    # would upload an artifact and exit 0 on a failing gate — a silently green build.
    payload = client.get(f"{base_path}?{urlencode({**query, 'format': 'json'})}").json()
    report = payload if isinstance(payload, dict) else {}

    if fmt == "json":
        if json_mode:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _emit_posture_human(report)
    else:
        artifact = client.get(f"{base_path}?{urlencode({**query, 'format': fmt})}").text
        typer.echo(artifact)

    gate = report.get("gate") or {}
    if not gate.get("passed", True):
        raise typer.Exit(EXIT_ERROR)


_POSTURE_RULE_COLUMNS: tuple[ListColumn, ...] = (
    ("Rule", "ruleId", None),
    ("Origin", "origin", None),
    ("Severity", "severity", None),
    ("OWASP", "owaspIds", lambda v: ",".join(v) if isinstance(v, list) else _format_optional(v)),
    ("Requires", "requires", None),
)


@app.command("trust-posture-rules")
def trust_posture_rules(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Only list rules in this profile: mcp-trust-posture, mcp-metadata-posture, or "
        "mcp-supply-chain (default: all).",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """List the MCP trust-posture rule catalog (GET /v1/mcp/trust-posture/rules).

    Each rule declares its evidence lane, the OWASP MCP risk it maps to, and what it needs to run —
    so you can see what the scan can and cannot tell you before running it.
    """
    profile_id = (
        _normalize_choice(profile, _POSTURE_PROFILES, "--profile") if profile is not None else None
    )

    json_mode = _json_output(ctx, output)
    client = _registry_client(ctx)

    path = api_paths.mcp_trust_posture_rules()
    if profile_id is not None:
        path = f"{path}?{urlencode({'profile': profile_id})}"
    payload = client.get(path).json()

    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return

    owasp = payload.get("owaspRevision") or payload.get("owasp_revision") or "?"
    typer.echo(f"MCP trust-posture rules (OWASP MCP {owasp})")
    for entry in payload.get("profiles") or []:
        if isinstance(entry, dict):
            label = entry.get("label") or entry.get("profileId") or "?"
            typer.echo(f"  profile {entry.get('profileId', '?')}: {label}")

    rules = payload.get("rules")
    if not isinstance(rules, list):
        emit_json(payload)
        return
    emit_list_table(
        rules,
        _POSTURE_RULE_COLUMNS,
        empty_message="No trust-posture rules.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


# =================================================================================================
# Dynamic probes (CLX-3.3, #4857).
# =================================================================================================

_PROBE_CATALOG_COLUMNS: tuple[ListColumn, ...] = (
    ("Probe", "probeId", None),
    ("Profile", "profile", None),
    ("Emits", "emits", None),
    ("OWASP", "owaspIds", lambda v: ",".join(v) if isinstance(v, list) else _format_optional(v)),
    ("Title", "title", None),
)

_PROBE_RUN_COLUMNS: tuple[ListColumn, ...] = (
    ("Started", "startedAt", None),
    ("Profile", "profile", None),
    ("Status", "status", None),
    ("Sent", "requestsSent", None),
    ("Observed", "observedCount", None),
    ("Exploited", "exploitedCount", None),
    ("Reason", "refusalReason", _format_optional),
)


def _emit_probe_report_human(report: dict[str, Any]) -> None:
    """Print a readable probe-run summary: profile, classification tallies, findings, audit envelope."""
    profile = report.get("profile") or "?"
    counts = report.get("classification_counts") or {}
    typer.echo(f"MCP probe profile: {profile}")
    typer.echo(
        "Findings — observed: {o}, exploited-in-test: {e}".format(
            o=counts.get("observed", 0), e=report.get("exploited_count", 0)
        )
    )
    typer.echo(f"Requests sent: {report.get('requests_sent', 0)}")
    for finding in report.get("findings") or []:
        cls = finding.get("classification") or "?"
        probe = finding.get("probe_id") or "?"
        path_hint = finding.get("path") or ""
        owasp = ",".join(finding.get("owasp_ids") or [])
        typer.echo(f"  [{cls}] {probe}  {path_hint}  ({owasp})")
        observed = finding.get("observed")
        if observed:
            typer.echo(f"      observed: {observed}")
    skipped = report.get("skipped_probes") or {}
    for probe_id, reason in skipped.items():
        typer.echo(f"  SKIPPED {probe_id}: {reason}")


@app.command("probe-catalog")
def probe_catalog(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Only list probes in this profile: passive, safe-active, or payload-fuzzing.",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """List the MCP probe catalog (GET /v1/mcp/probes/catalog).

    Shows every probe, which profile runs it, and the strongest classification tier it can reach —
    so you know, before running anything, what a probe can and cannot demonstrate.
    """
    profile_id = (
        _normalize_choice(profile, _PROBE_PROFILES, "--profile") if profile is not None else None
    )
    json_mode = _json_output(ctx, output)
    client = _registry_client(ctx)

    path = api_paths.mcp_probe_catalog()
    if profile_id is not None:
        path = f"{path}?{urlencode({'profile': profile_id})}"
    payload = client.get(path).json()

    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    probes = payload.get("probes")
    if not isinstance(probes, list):
        emit_json(payload)
        return
    emit_list_table(
        probes,
        _PROBE_CATALOG_COLUMNS,
        empty_message="No probes.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


@app.command("probe-target-add")
def probe_target_add(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID to enrol on the allowlist."),
    own: bool = typer.Option(
        False,
        "--i-own-or-am-authorized",
        help="Assert you own or are authorized to probe this target (required).",
    ),
    test_credential_id: UUID | None = typer.Option(
        None,
        "--test-credential",
        help="The dedicated (non-production) test credential a probe authenticates as.",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Enrol an endpoint on the active-probe allowlist (POST .../probe-targets).

    Active probing may only ever fire at an allowlisted target. Enrolling records, on the record, that
    you asserted ownership/authorization and (optionally) the dedicated test identity a probe uses.
    """
    if not own:
        typer.echo(
            "Refusing: pass --i-own-or-am-authorized to assert you may probe this target.", err=True
        )
        raise typer.Exit(EXIT_ERROR)
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    body: dict[str, Any] = {"ownership_declared": True}
    if test_credential_id is not None:
        body["test_credential_id"] = str(test_credential_id)
    path = api_paths.mcp_endpoint_probe_targets(tenant_slug, str(endpoint_id))
    payload = client.post(path, json=body).json()
    if json_mode:
        emit_json(payload)
    else:
        target = payload.get("target") if isinstance(payload, dict) else None
        typer.echo(f"Enrolled probe target: {(target or {}).get('id', '?')}")


@app.command("probe-target-list")
def probe_target_list(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """List an endpoint's active-probe allowlist entries (GET .../probe-targets)."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.mcp_endpoint_probe_targets(tenant_slug, str(endpoint_id))
    payload = client.get(path).json()
    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    targets = payload.get("targets")
    emit_list_table(
        targets if isinstance(targets, list) else [],
        (
            ("Id", "id", None),
            ("Transport", "transport", None),
            ("Locator", "locator", None),
            ("Owns", "ownershipDeclared", None),
            ("Test cred", "testCredentialId", _format_optional),
        ),
        empty_message="No allowlisted probe targets.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


@app.command("probe")
def probe_endpoint(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    version: UUID | None = typer.Option(
        None, "--version", help="Version snapshot UUID (default: the endpoint's current version)."
    ),
    profile: str = typer.Option(
        "passive",
        "--profile",
        help="Profile: passive (default, read-only), safe-active, or payload-fuzzing.",
    ),
    explicit_approval: bool = typer.Option(
        False,
        "--i-approve-hostile-payloads",
        help="Explicit per-run approval, required for payload-fuzzing.",
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Run a dynamic probe against a version snapshot (POST .../versions/{id}/probe).

    The default 'passive' profile is read-only: it re-reads the captured transcript, sends nothing,
    and classifies observed protocol behaviour. Active profiles require the target to be allowlisted
    (see 'probe-target-add'), the global kill switch to be on, and — for payload-fuzzing —
    --i-approve-hostile-payloads. Nothing here is 'proven' unless a probe demonstrated it against a
    live server in isolation (an exploited-in-test finding).
    """
    profile_id = _normalize_choice(profile, _PROBE_PROFILES, "--profile")
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)

    version_id = _resolve_lint_version_id(client, tenant_slug, str(endpoint_id), version)
    path = api_paths.mcp_endpoint_version_probe(tenant_slug, str(endpoint_id), version_id)
    body = {"profile": profile_id, "explicit_approval": explicit_approval}
    payload = client.post(path, json=body).json()

    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    _emit_probe_report_human(payload)


@app.command("probe-runs")
def probe_runs(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="Max audit rows to return."),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Show an endpoint's probe-run audit trail (GET .../probe-runs)."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.mcp_endpoint_probe_runs(tenant_slug, str(endpoint_id))
    payload = client.get(f"{path}?{urlencode({'limit': limit})}").json()
    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    runs = payload.get("runs")
    emit_list_table(
        runs if isinstance(runs, list) else [],
        _PROBE_RUN_COLUMNS,
        empty_message="No probe runs recorded.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )


# =================================================================================================
# Trust baselines, drift, and shadowing (CLX-3.4, #4858).
# =================================================================================================

_DRIFT_CHANGE_COLUMNS: tuple[ListColumn, ...] = (
    ("Category", "category", None),
    ("Component", "component", None),
    ("Path", "path", None),
    ("Summary", "summary", None),
)

_SHADOW_GROUP_COLUMNS: tuple[ListColumn, ...] = (
    ("Type", "item_type", None),
    ("Name", "name", None),
    ("Scope", "host_scope", None),
    ("Endpoints", "endpoint_count", None),
)


def _emit_drift_human(report: dict[str, Any]) -> None:
    """Print a readable drift summary: alert severity, gate, category tallies, and each change."""
    typer.echo(f"Alert severity: {report.get('alert_severity', '?')}")
    gate = report.get("gate") or {}
    enforced = " (enforced)" if gate.get("enforced") else " (advisory)"
    typer.echo(f"Gate: {gate.get('status', '?')}{enforced} — {gate.get('reason', '')}")
    counts = report.get("category_counts") or {}
    typer.echo(
        "Changes — security_regression: {s}, coverage_loss: {c}, quality_regression: {q}, "
        "normal_change: {n}".format(
            s=counts.get("security_regression", 0),
            c=counts.get("coverage_loss", 0),
            q=counts.get("quality_regression", 0),
            n=counts.get("normal_change", 0),
        )
    )
    for change in report.get("changes") or []:
        typer.echo(
            f"  [{change.get('category')}] {change.get('component')}:{change.get('path')}  "
            f"{change.get('summary')}"
        )


@app.command("trust-baseline-approve")
def trust_baseline_approve(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID to approve a baseline for."),
    rationale: str = typer.Option(
        ..., "--rationale", help="Why this snapshot is approved (required; recorded as a policy event)."
    ),
    version: UUID | None = typer.Option(
        None, "--version", help="Version snapshot UUID to approve (default: the current version)."
    ),
    gate: list[str] = typer.Option(
        [],
        "--gate",
        help=(
            "Drift categories that block the gate (repeatable): security_regression, coverage_loss, "
            "quality_regression, normal_change. Default: security_regression + coverage_loss."
        ),
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Approve a trust baseline for an endpoint (POST .../trust-baseline).

    Pins the trust manifest of the approved snapshot as the reference every later rediscovery/release
    is diffed against. The rationale is required and recorded as a governance policy event; approving
    a new baseline supersedes the prior one.
    """
    gating = [_normalize_choice(g, _DRIFT_CATEGORIES, "--gate") for g in gate]
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    body: dict[str, Any] = {"rationale": rationale}
    if version is not None:
        body["version_id"] = str(version)
    if gating:
        body["gating_categories"] = gating
    path = api_paths.mcp_endpoint_trust_baseline(tenant_slug, str(endpoint_id))
    payload = client.post(path, json=body).json()
    if json_mode:
        emit_json(payload)
    else:
        baseline = payload.get("baseline") if isinstance(payload, dict) else None
        typer.echo(f"Approved trust baseline: {(baseline or {}).get('id', '?')}")


@app.command("trust-baseline-show")
def trust_baseline_show(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Show an endpoint's active trust baseline and approval history (GET .../trust-baseline)."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.mcp_endpoint_trust_baseline(tenant_slug, str(endpoint_id))
    payload = client.get(path).json()
    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    baseline = payload.get("baseline")
    if not baseline:
        typer.echo("No approved trust baseline for this endpoint.")
        return
    typer.echo(f"Baseline: {baseline.get('id')}  (version {baseline.get('versionId')})")
    typer.echo(f"Fingerprint: {baseline.get('manifestFingerprint')}")
    typer.echo(f"Rationale: {baseline.get('rationale')}")
    typer.echo(f"Gating: {', '.join(baseline.get('gatingCategories') or [])}")


@app.command("trust-drift")
def trust_drift(
    ctx: typer.Context,
    endpoint_id: UUID = typer.Argument(..., help="MCP endpoint UUID."),
    notify: bool = typer.Option(
        False, "--notify", help="Fan out a push-webhook alert when a regression is found."
    ),
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """Diff an endpoint's current snapshot against its approved baseline (GET .../trust-drift).

    Every material surface/source change is classified as a normal change, a quality regression, a
    security regression, or coverage loss, and carries an old→new evidence reference. The gate
    reflects the baseline's configured risk deltas.
    """
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.mcp_endpoint_trust_drift(tenant_slug, str(endpoint_id))
    if notify:
        path = f"{path}?{urlencode({'notify': 'true'})}"
    payload = client.get(path).json()
    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    _emit_drift_human(payload.get("drift") or {})


@app.command("shadowing")
def shadowing(
    ctx: typer.Context,
    output: str | None = typer.Option(None, "--output", help="Output: table (default) or json."),
) -> None:
    """List tool/resource/prompt names shadowed across enabled endpoints (GET .../data-quality/shadowing)."""
    json_mode = _json_output(ctx, output)
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.mcp_shadowing(tenant_slug)
    payload = client.get(path).json()
    if json_mode or not isinstance(payload, dict):
        emit_json(payload)
        return
    groups = payload.get("groups")
    emit_list_table(
        groups if isinstance(groups, list) else [],
        _SHADOW_GROUP_COLUMNS,
        empty_message="No shadowed names across the enabled host scope.",
        min_width=_MCP_LIST_MIN_WIDTH,
    )
