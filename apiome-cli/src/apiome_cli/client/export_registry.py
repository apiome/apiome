"""Emitter-registry export client: targets discovery and dry-run fidelity preview (MFX-9.4).

Thin HTTP helpers over the export surface apiome-rest exposes for the multi-format emitter registry:

* ``GET /v1/export/{tenant}/targets`` — the emitter descriptors + per-source fidelity badges an
  ``export targets`` listing renders (the inverse of ``import --list``);
* ``POST /v1/export/{tenant}/preview`` — the full fidelity envelope (tier + per-construct report +
  advisory) the ``export openapi`` command surfaces alongside the written document.

Neither endpoint emits an artifact; the document bytes come from the browse reconstruction
(:mod:`apiome_cli.client.spec_download`). These helpers only fetch JSON and hand back the parsed
mappings — all presentation lives in :mod:`apiome_cli.export_output`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient


def fetch_export_targets(
    client: RestClient,
    tenant_slug: str,
    *,
    artifact: str,
    version: str | None,
) -> dict[str, Any]:
    """Fetch the emitter registry targets + fidelity badges for one artifact revision.

    Parameters
    ----------
    client:
        Authenticated REST client (API key + tenant scope).
    tenant_slug:
        The tenant URL slug.
    artifact:
        The artifact (project) id to describe targets for.
    version:
        Revision UUID / version label, or ``None`` for the latest revision.

    Returns
    -------
    dict
        The parsed ``ExportTargetsResponse`` (``artifact``, ``version``, ``targets`` list).
    """
    params = {"artifact": artifact}
    if version is not None:
        params["version"] = version
    query = "&".join(f"{key}={value}" for key, value in params.items())
    path = f"{api_paths.export_targets(tenant_slug)}?{query}"
    return client.get(path).json()


def fetch_export_preview(
    client: RestClient,
    tenant_slug: str,
    *,
    artifact: str,
    version: str | None,
    target: str,
) -> dict[str, Any]:
    """Fetch the dry-run fidelity preview for one (artifact, target) export.

    Parameters
    ----------
    client:
        Authenticated REST client (API key + tenant scope).
    tenant_slug:
        The tenant URL slug.
    artifact:
        The artifact (project) id being exported.
    version:
        Revision UUID / version label, or ``None`` for the latest revision.
    target:
        Target emitter key (``openapi``) or format key (``openapi-3.1``).

    Returns
    -------
    dict
        The parsed ``ExportPreviewResponse`` (its ``fidelity`` envelope carries the tier,
        per-construct report, and advisory).
    """
    body: dict[str, Any] = {"artifact": artifact, "target": target}
    if version is not None:
        body["version"] = version
    return client.post(api_paths.export_preview(tenant_slug), json=body).json()


def preview_fidelity(preview: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the ``fidelity`` envelope from a preview response, or ``None`` when absent."""
    fidelity = preview.get("fidelity")
    return fidelity if isinstance(fidelity, dict) else None


# User-facing target aliases that differ from the emitter registry key.
_EXPORT_TARGET_ALIASES: dict[str, str] = {
    "grpc": "protobuf",
}


def resolve_export_target(format_ref: str, targets: Sequence[Any]) -> str:
    """Resolve a user-supplied format name to a registered emitter key.

    Raises
    ------
    ValueError
        When no registered target matches ``format_ref``.
    """
    normalized = format_ref.strip().lower()
    if not normalized:
        raise ValueError("format cannot be empty")
    alias = _EXPORT_TARGET_ALIASES.get(normalized, normalized)

    keys: list[str] = []
    for entry in targets:
        if not isinstance(entry, Mapping):
            continue
        descriptor = entry.get("descriptor")
        if not isinstance(descriptor, Mapping):
            continue
        key = descriptor.get("key")
        fmt = descriptor.get("format")
        if isinstance(key, str) and key.strip():
            keys.append(key.strip().lower())
            if alias == key.strip().lower():
                return key.strip()
        if isinstance(fmt, str) and fmt.strip():
            if alias == fmt.strip().lower():
                return key.strip() if isinstance(key, str) and key.strip() else fmt.strip()

    raise ValueError(normalized)


def unknown_export_target_message(format_ref: str, targets: Sequence[Any]) -> str:
    """Build an actionable error when ``format_ref`` is not in the registry."""
    available: list[str] = []
    for entry in targets:
        if not isinstance(entry, Mapping):
            continue
        descriptor = entry.get("descriptor")
        if not isinstance(descriptor, Mapping):
            continue
        key = descriptor.get("key")
        if isinstance(key, str) and key.strip():
            available.append(key.strip())
    joined = ", ".join(sorted(set(available))) if available else "(none)"
    return f"Unknown export format {format_ref!r}. Available targets: {joined}."
