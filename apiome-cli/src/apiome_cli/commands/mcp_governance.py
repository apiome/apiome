"""Tenant MCP policy and per-key capability CLI (session / tenant-admin auth).

Thin client over:

* ``GET`` / ``PUT /v1/tenants/{tenant_slug}/mcp-policy`` (MTG-3.1)
* ``GET /v1/tenants/{tenant_slug}/mcp-keys/{key_id}`` (capability read)
* ``PUT …/mcp-keys/{key_id}/capabilities`` (MTG-3.3)

Mutations require a signed-in tenant-admin session; API keys cannot escalate into
governance writes. Commands accept a JSON document (``--file`` / stdin ``-``)
and/or field flags; flags merge onto the file body or onto a live GET when no
file is supplied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_session_token
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_table,
)

_DEFAULT_MODES = frozenset({"all", "inherit_registry", "explicit"})
_CAPABILITY_MODES = frozenset({"inherit", "explicit"})
_POLICY_PUT_KEYS = frozenset({"default_mode", "allow_anonymous_mcp", "tools"})
_POLICY_TOOL_KEYS = frozenset(
    {"tool_id", "in_ceiling", "default_enabled", "anonymous_enabled"}
)
_CAPABILITIES_PUT_KEYS = frozenset({"mode", "enabled_tools"})

policy_app = typer.Typer(
    name="policy",
    help="Inspect and replace tenant MCP governance policy (session / tenant admin).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

key_app = typer.Typer(
    name="key",
    help="Manage per-key MCP capability grants (session / tenant admin).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

capabilities_app = typer.Typer(
    name="capabilities",
    help="Get and set MCP API key capability grants.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)
key_app.add_typer(capabilities_app, name="capabilities")


@policy_app.callback(invoke_without_command=True)
def policy_group(ctx: typer.Context) -> None:
    """Tenant MCP policy command group."""
    group_callback_without_subcommand(ctx)


@key_app.callback(invoke_without_command=True)
def key_group(ctx: typer.Context) -> None:
    """MCP key governance command group."""
    group_callback_without_subcommand(ctx)


@capabilities_app.callback(invoke_without_command=True)
def capabilities_group(ctx: typer.Context) -> None:
    """Per-key capability command group."""
    group_callback_without_subcommand(ctx)


def _session_scoped_client(ctx: typer.Context) -> tuple[RestClient, str]:
    """Build a session-bearer REST client and resolve the configured tenant slug.

    Returns:
        ``(client, tenant_slug)`` ready for ``/v1/tenants/{slug}/…`` governance routes.
    """
    settings = settings_from_context(ctx)
    require_session_token(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
        session=True,
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


def _parse_bool_flag(value: str, *, option_name: str) -> bool:
    """Parse a required ``true``/``false`` CLI flag value."""
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    msg = f"{option_name} must be 'true' or 'false'."
    raise typer.BadParameter(msg)


def _load_json_document(file_path: str) -> dict[str, Any]:
    """Load a JSON object from ``PATH`` or stdin when ``file_path`` is ``-``.

    Args:
        file_path: Filesystem path, or ``-`` to read stdin.

    Returns:
        Parsed JSON object.

    Raises:
        typer.Exit: On read/parse failure or a non-object root.
    """
    try:
        if file_path == "-":
            text = sys.stdin.read()
        else:
            text = Path(file_path).expanduser().read_text(encoding="utf-8")
        payload = json.loads(text)
    except OSError as exc:
        typer.echo(f"Cannot read policy file: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"Invalid JSON: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    if not isinstance(payload, dict):
        typer.echo("Governance JSON root must be an object.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return payload


def _strip_policy_write_body(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop response-only fields so a ``policy get`` payload can be PUT back."""
    return {key: value for key, value in raw.items() if key in _POLICY_PUT_KEYS}


def _validate_policy_put_body(body: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a tenant MCP policy PUT body.

    Args:
        body: Candidate write body (already stripped of response metadata).

    Returns:
        Normalized body ready for ``PUT …/mcp-policy``.

    Raises:
        typer.BadParameter: When shape, enums, or per-tool rules fail.
    """
    unknown = set(body) - _POLICY_PUT_KEYS
    if unknown:
        keys = ", ".join(sorted(unknown))
        msg = f"Unknown policy fields: {keys}."
        raise typer.BadParameter(msg)

    default_mode = body.get("default_mode")
    if not isinstance(default_mode, str) or default_mode not in _DEFAULT_MODES:
        msg = "--default-mode / default_mode must be all, inherit_registry, or explicit."
        raise typer.BadParameter(msg)

    allow_anonymous = body.get("allow_anonymous_mcp", True)
    if not isinstance(allow_anonymous, bool):
        msg = "allow_anonymous_mcp must be a boolean."
        raise typer.BadParameter(msg)

    tools_raw = body.get("tools", [])
    if tools_raw is None:
        tools_raw = []
    if not isinstance(tools_raw, list):
        msg = "tools must be an array."
        raise typer.BadParameter(msg)

    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(tools_raw):
        if not isinstance(item, dict):
            msg = f"tools[{index}] must be an object."
            raise typer.BadParameter(msg)
        unknown_tool = set(item) - _POLICY_TOOL_KEYS
        if unknown_tool:
            keys = ", ".join(sorted(unknown_tool))
            msg = f"tools[{index}] has unknown fields: {keys}."
            raise typer.BadParameter(msg)
        tool_id = item.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id.strip():
            msg = f"tools[{index}].tool_id must be a non-empty string."
            raise typer.BadParameter(msg)
        tool_id = tool_id.strip()
        if tool_id in seen:
            msg = f"Duplicate tool_id in tools: {tool_id}."
            raise typer.BadParameter(msg)
        seen.add(tool_id)

        in_ceiling = item.get("in_ceiling")
        default_enabled = item.get("default_enabled")
        anonymous_enabled = item.get("anonymous_enabled", True)
        if not isinstance(in_ceiling, bool):
            msg = f"tools[{index}].in_ceiling must be a boolean."
            raise typer.BadParameter(msg)
        if not isinstance(default_enabled, bool):
            msg = f"tools[{index}].default_enabled must be a boolean."
            raise typer.BadParameter(msg)
        if not isinstance(anonymous_enabled, bool):
            msg = f"tools[{index}].anonymous_enabled must be a boolean."
            raise typer.BadParameter(msg)
        if default_enabled and not in_ceiling:
            msg = f"default_enabled requires in_ceiling for tool_id: {tool_id}."
            raise typer.BadParameter(msg)

        tools.append(
            {
                "tool_id": tool_id,
                "in_ceiling": in_ceiling,
                "default_enabled": default_enabled,
                "anonymous_enabled": anonymous_enabled,
            }
        )

    return {
        "default_mode": default_mode,
        "allow_anonymous_mcp": allow_anonymous,
        "tools": tools,
    }


def _merge_policy_flags(
    base: dict[str, Any],
    *,
    default_mode: str | None,
    allow_anonymous_mcp: bool | None,
) -> dict[str, Any]:
    """Overlay CLI policy flags onto a base policy document."""
    merged = dict(base)
    if default_mode is not None:
        merged["default_mode"] = default_mode
    if allow_anonymous_mcp is not None:
        merged["allow_anonymous_mcp"] = allow_anonymous_mcp
    if "tools" not in merged:
        merged["tools"] = []
    if "allow_anonymous_mcp" not in merged:
        merged["allow_anonymous_mcp"] = True
    return merged


def _validate_capabilities_put_body(body: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a per-key capabilities PUT body.

    Args:
        body: Candidate write body with ``mode`` / ``enabled_tools``.

    Returns:
        Normalized body ready for ``PUT …/capabilities``.

    Raises:
        typer.BadParameter: When shape or enums fail.
    """
    unknown = set(body) - _CAPABILITIES_PUT_KEYS
    if unknown:
        keys = ", ".join(sorted(unknown))
        msg = f"Unknown capability fields: {keys}."
        raise typer.BadParameter(msg)

    mode = body.get("mode")
    if not isinstance(mode, str) or mode not in _CAPABILITY_MODES:
        msg = "--mode / mode must be 'inherit' or 'explicit'."
        raise typer.BadParameter(msg)

    enabled_tools = body.get("enabled_tools")
    if mode == "inherit":
        return {"mode": "inherit", "enabled_tools": None}

    if enabled_tools is None:
        enabled_tools = []
    if not isinstance(enabled_tools, list):
        msg = "enabled_tools must be an array of tool ids."
        raise typer.BadParameter(msg)

    tools: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(enabled_tools):
        if not isinstance(item, str) or not item.strip():
            msg = f"enabled_tools[{index}] must be a non-empty string."
            raise typer.BadParameter(msg)
        tool_id = item.strip()
        if tool_id in seen:
            continue
        seen.add(tool_id)
        tools.append(tool_id)

    return {"mode": "explicit", "enabled_tools": tools}


def _merge_capabilities_flags(
    base: dict[str, Any],
    *,
    mode: str | None,
    tools: list[str] | None,
) -> dict[str, Any]:
    """Overlay CLI capability flags onto a base capabilities document."""
    merged = dict(base)
    if mode is not None:
        merged["mode"] = mode
    if tools is not None:
        merged["enabled_tools"] = list(tools)
    return merged


def _capabilities_from_key_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project a MCP key GET payload onto the capabilities write/read shape.

    Args:
        record: ``GET …/mcp-keys/{id}`` JSON object.

    Returns:
        ``{"mode": …, "enabled_tools": …}`` matching the capabilities API.
    """
    mode = record.get("capability_mode") or record.get("mode") or "inherit"
    enabled = record.get("enabled_tools")
    if not isinstance(enabled, list):
        enabled = []
    return {
        "mode": mode if isinstance(mode, str) else "inherit",
        "enabled_tools": [str(item) for item in enabled],
    }


_POLICY_SUMMARY_FIELDS: tuple[RecordField, ...] = (
    ("Default mode", "default_mode", None),
    ("Allow anonymous MCP", "allow_anonymous_mcp", None),
    ("Updated at", "updated_at", lambda v: "" if v in (None, "") else str(v)),
    ("Updated by", "updated_by", lambda v: "" if v in (None, "") else str(v)),
)

_POLICY_TOOL_COLUMNS: tuple[ListColumn, ...] = (
    ("Tool", "tool_id", None),
    ("Ceiling", "in_ceiling", None),
    ("Default", "default_enabled", None),
    ("Anonymous", "anonymous_enabled", None),
)

_CAPABILITIES_FIELDS: tuple[RecordField, ...] = (
    ("Mode", "mode", None),
    (
        "Enabled tools",
        "enabled_tools",
        lambda v: ", ".join(str(x) for x in v) if isinstance(v, list) else "",
    ),
)


def _emit_policy_human(policy: dict[str, Any]) -> None:
    """Render tenant MCP policy as a summary record plus tools table."""
    emit_record_table(policy, _POLICY_SUMMARY_FIELDS)
    tools = policy.get("tools")
    if isinstance(tools, list) and tools:
        typer.echo("")
        emit_list_table(tools, _POLICY_TOOL_COLUMNS, empty_message="No tool rows.")
    else:
        typer.echo("Tools: (none)")


def _emit_capabilities_human(caps: dict[str, Any]) -> None:
    """Render per-key capability grants as a field/value table."""
    emit_record_table(caps, _CAPABILITIES_FIELDS)


@policy_app.command("get")
def get_policy(
    ctx: typer.Context,
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Print the tenant MCP policy (GET /v1/tenants/{slug}/mcp-policy)."""
    client, tenant_slug = _session_scoped_client(ctx)
    response = client.get(api_paths.tenant_mcp_policy(tenant_slug))
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    if not isinstance(payload, dict):
        emit_json(payload)
        return
    _emit_policy_human(payload)


@policy_app.command("set")
def set_policy(
    ctx: typer.Context,
    file_path: str | None = typer.Option(
        None,
        "--file",
        help="Policy JSON file, or '-' for stdin (TenantMcpPolicyPutRequest shape).",
    ),
    default_mode: str | None = typer.Option(
        None,
        "--default-mode",
        help="default_mode: all, inherit_registry, or explicit.",
    ),
    allow_anonymous: str | None = typer.Option(
        None,
        "--allow-anonymous",
        help="allow_anonymous_mcp kill switch: true or false.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Replace the tenant MCP policy (PUT /v1/tenants/{slug}/mcp-policy).

    Supply ``--file`` / stdin and/or ``--default-mode`` / ``--allow-anonymous``.
    With only flags, the current policy is fetched and merged before PUT.
    """
    if default_mode is not None and default_mode.strip() not in _DEFAULT_MODES:
        msg = "--default-mode must be all, inherit_registry, or explicit."
        raise typer.BadParameter(msg)
    allow_anon_flag = (
        _parse_bool_flag(allow_anonymous, option_name="--allow-anonymous")
        if allow_anonymous is not None
        else None
    )
    if file_path is None and default_mode is None and allow_anon_flag is None:
        msg = "Provide --file and/or --default-mode / --allow-anonymous."
        raise typer.BadParameter(msg)

    client, tenant_slug = _session_scoped_client(ctx)
    path = api_paths.tenant_mcp_policy(tenant_slug)

    if file_path is not None:
        base = _strip_policy_write_body(_load_json_document(file_path))
    else:
        current = client.get(path).json()
        if not isinstance(current, dict):
            typer.echo("Unexpected response from GET mcp-policy.", err=True)
            raise typer.Exit(EXIT_USAGE)
        base = _strip_policy_write_body(current)

    merged = _merge_policy_flags(
        base,
        default_mode=default_mode.strip() if default_mode is not None else None,
        allow_anonymous_mcp=allow_anon_flag,
    )
    body = _validate_policy_put_body(merged)

    response = client.put(path, json=body)
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    if isinstance(payload, dict):
        typer.echo(
            "Tenant MCP policy updated: "
            f"default_mode={payload.get('default_mode')} "
            f"allow_anonymous_mcp={payload.get('allow_anonymous_mcp')} "
            f"tools={len(payload.get('tools') or [])}"
        )
        return
    emit_json(payload)


@capabilities_app.command("get")
def get_key_capabilities(
    ctx: typer.Context,
    key_id: UUID = typer.Argument(..., help="MCP API key UUID."),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Print capability grants for one MCP key (projects GET …/mcp-keys/{id})."""
    client, tenant_slug = _session_scoped_client(ctx)
    response = client.get(api_paths.tenant_mcp_key(tenant_slug, key_id))
    record = response.json()
    if not isinstance(record, dict):
        emit_json(record)
        return

    caps = _capabilities_from_key_record(record)
    if _json_output(ctx, output):
        emit_json(caps)
        return
    _emit_capabilities_human(caps)


@capabilities_app.command("set")
def set_key_capabilities(
    ctx: typer.Context,
    key_id: UUID = typer.Argument(..., help="MCP API key UUID."),
    file_path: str | None = typer.Option(
        None,
        "--file",
        help="Capabilities JSON file, or '-' for stdin ({mode, enabled_tools}).",
    ),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help="Capability mode: inherit or explicit.",
    ),
    tool: list[str] | None = typer.Option(
        None,
        "--tool",
        help="Enabled tool id when mode=explicit (repeatable).",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Replace per-key capability grants (PUT …/mcp-keys/{id}/capabilities).

    Supply ``--file`` / stdin and/or ``--mode`` / ``--tool``. With only flags, the
    current grants are loaded from the key GET and merged before PUT.
    """
    if mode is not None and mode.strip() not in _CAPABILITY_MODES:
        msg = "--mode must be 'inherit' or 'explicit'."
        raise typer.BadParameter(msg)

    tools_flag: list[str] | None = None
    if tool:
        tools_flag = [item.strip() for item in tool if item.strip()]

    if file_path is None and mode is None and tools_flag is None:
        msg = "Provide --file and/or --mode / --tool."
        raise typer.BadParameter(msg)

    client, tenant_slug = _session_scoped_client(ctx)
    key_path = api_paths.tenant_mcp_key(tenant_slug, key_id)
    caps_path = api_paths.tenant_mcp_key_capabilities(tenant_slug, key_id)

    if file_path is not None:
        base = _load_json_document(file_path)
        if "capability_mode" in base and "mode" not in base:
            base = {
                "mode": base.get("capability_mode"),
                "enabled_tools": base.get("enabled_tools"),
            }
        base = {k: v for k, v in base.items() if k in _CAPABILITIES_PUT_KEYS}
    else:
        record = client.get(key_path).json()
        if not isinstance(record, dict):
            typer.echo("Unexpected response from GET mcp-keys/{id}.", err=True)
            raise typer.Exit(EXIT_USAGE)
        base = _capabilities_from_key_record(record)

    merged = _merge_capabilities_flags(
        base,
        mode=mode.strip() if mode is not None else None,
        tools=tools_flag,
    )
    body = _validate_capabilities_put_body(merged)

    response = client.put(caps_path, json=body)
    payload = response.json()

    if _json_output(ctx, output):
        emit_json(payload)
        return

    if isinstance(payload, dict):
        mode_value = payload.get("mode")
        tools_value = payload.get("enabled_tools") or []
        count = len(tools_value) if isinstance(tools_value, list) else 0
        typer.echo(f"MCP key capabilities updated: mode={mode_value} tools={count}")
        return
    emit_json(payload)
