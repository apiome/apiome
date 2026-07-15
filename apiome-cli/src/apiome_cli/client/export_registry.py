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
    options: Mapping[str, Any] | None = None,
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
    options:
        Per-target emit options; ``None`` applies the target defaults. Folded into the
        snapshot hash server-side, so different options are a different snapshot.

    Returns
    -------
    dict
        The parsed ``ExportPreviewResponse`` (its ``fidelity`` envelope carries the tier,
        per-construct report, and advisory).
    """
    body: dict[str, Any] = {"artifact": artifact, "target": target}
    if version is not None:
        body["version"] = version
    if options:
        body["options"] = dict(options)
    return client.post(api_paths.export_preview(tenant_slug), json=body).json()


def projection_snapshot_hash(preview: Mapping[str, Any]) -> str | None:
    """Return ``fidelity.projection.manifest_hash`` from a preview response, when present."""
    fidelity = preview.get("fidelity")
    if not isinstance(fidelity, Mapping):
        return None
    projection = fidelity.get("projection")
    if not isinstance(projection, Mapping):
        return None
    manifest_hash = projection.get("manifest_hash")
    return manifest_hash if isinstance(manifest_hash, str) and manifest_hash.strip() else None


def preview_fidelity(preview: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the ``fidelity`` envelope from a preview response, or ``None`` when absent."""
    fidelity = preview.get("fidelity")
    return fidelity if isinstance(fidelity, dict) else None


def fetch_projection_evidence(
    client: RestClient,
    tenant_slug: str,
    *,
    artifact: str,
    version: str | None,
    target: str,
    options: Mapping[str, Any] | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    redact_source: bool = False,
) -> dict[str, Any]:
    """Fetch one bounded page of projection evidence for a configured export (EFP-2.1).

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
    options:
        Per-target emit options; ``None`` applies the target defaults. Folded into the
        snapshot hash server-side, so different options are a different snapshot.
    cursor:
        Opaque cursor from a previous page, or ``None`` to start at the beginning.
    limit:
        Maximum evidence rows per page (server clamps to its hard cap); ``None`` applies
        the server default.
    redact_source:
        When true, source-native evidence values are withheld (redaction placeholder).

    Returns
    -------
    dict
        The parsed ``ExportProjectionEvidenceResponse`` (``summary`` snapshot + ``page``
        of edges/nodes with the ``next_cursor``).
    """
    body: dict[str, Any] = {"artifact": artifact, "target": target}
    if version is not None:
        body["version"] = version
    if options is not None:
        body["options"] = dict(options)
    if cursor is not None:
        body["cursor"] = cursor
    if limit is not None:
        body["limit"] = limit
    if redact_source:
        body["redact_source"] = True
    return client.post(api_paths.export_projection_evidence(tenant_slug), json=body).json()


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
