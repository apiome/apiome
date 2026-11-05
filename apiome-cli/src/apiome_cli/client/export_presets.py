"""REST helpers for export presets (MFX-39.3).

A preset saves an export's targets, each target's emit options and an optional delivery profile once per
workspace, by name. These helpers wrap ``/v1/export/{tenant}/presets`` (which takes a preset's id or its
name wherever it names one) and turn command-line flags into a preset's ``targets`` list.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE


def _json_object(response: Any, what: str) -> dict[str, Any]:
    """The response body as a JSON object, or exit naming what was expected."""
    payload = response.json()
    if not isinstance(payload, dict):
        typer.echo(f"{what} response was not a JSON object.", err=True)
        raise typer.Exit(EXIT_ERROR)
    return payload


def list_presets(client: RestClient, tenant_slug: str) -> list[dict[str, Any]]:
    """``GET …/presets`` — the workspace's presets, by name."""
    presets = _json_object(client.get(api_paths.export_presets(tenant_slug)), "Preset list").get("presets")
    return [p for p in presets if isinstance(p, dict)] if isinstance(presets, list) else []


def get_preset(client: RestClient, tenant_slug: str, preset: str) -> dict[str, Any]:
    """``GET …/presets/{id or name}``."""
    return _json_object(client.get(api_paths.export_preset(tenant_slug, preset)), "Preset")


def create_preset(client: RestClient, tenant_slug: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST …/presets``."""
    return _json_object(client.post(api_paths.export_presets(tenant_slug), json=dict(body)), "Preset")


def update_preset(client: RestClient, tenant_slug: str, preset: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """``PATCH …/presets/{id or name}`` (exits on an HTTP error)."""
    response = client.patch_raw(api_paths.export_preset(tenant_slug, preset), json=dict(body))
    exit_on_api_error(response)
    return _json_object(response, "Preset")


def delete_preset(client: RestClient, tenant_slug: str, preset: str) -> None:
    """``DELETE …/presets/{id or name}``."""
    client.delete(api_paths.export_preset(tenant_slug, preset))


def _option_value(raw: str) -> Any:
    """An option value: JSON when it parses (``3``, ``true``, ``["a"]``), else the string itself."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def build_targets(targets: Sequence[str], options: Sequence[str]) -> list[dict[str, Any]]:
    """A preset's ``targets`` list from ``--target`` and ``--option TARGET:KEY=VALUE`` flags.

    Args:
        targets: ``--target`` values, in order (repeats dropped).
        options: ``--option`` values, each ``TARGET:KEY=VALUE`` naming one of ``targets``; the value is
            parsed as JSON when it parses.

    Returns:
        ``[{target, options}]``.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` for no target, a malformed ``--option`` or one naming a target
            that is not in ``targets``.
    """
    names: list[str] = []
    for raw in targets:
        name = raw.strip()
        if name and name not in names:
            names.append(name)
    if not names:
        typer.echo("Name at least one --target.", err=True)
        raise typer.Exit(EXIT_USAGE)
    per_target: dict[str, dict[str, Any]] = {name: {} for name in names}
    for raw in options:
        target, sep, assignment = raw.partition(":")
        key, eq, value = assignment.partition("=")
        if not sep or not eq or not target.strip() or not key.strip():
            typer.echo(f"--option {raw!r} must be TARGET:KEY=VALUE (for example openapi:openapi_version=3.0).",
                       err=True)
            raise typer.Exit(EXIT_USAGE)
        if target.strip() not in per_target:
            typer.echo(f"--option {raw!r} names {target.strip()!r}, which is not one of the --target values.",
                       err=True)
            raise typer.Exit(EXIT_USAGE)
        per_target[target.strip()][key.strip()] = _option_value(value)
    return [{"target": name, "options": per_target[name]} for name in names]


def targets_summary(targets: Any) -> str:
    """One line for a preset's targets: ``openapi (openapi_version=3.0), protobuf``."""
    if not isinstance(targets, list):
        return ""
    parts = []
    for entry in targets:
        if not isinstance(entry, dict):
            continue
        options = entry.get("options") or {}
        detail = ", ".join(f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in options.items())
        parts.append(f"{entry.get('target')}" + (f" ({detail})" if detail else ""))
    return ", ".join(parts)
