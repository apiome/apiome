"""The stored overlay chain's render path — GVM-4.3 (#5878).

A revision can carry an ordered chain of Overlay 1.x documents (apiome-db V385,
``apiome.version_overlays``; storage in :mod:`app.version_overlay_store`). The chain is the curation
form for edits that must not touch the source: accepted enrichment descriptions, Export Studio
tweaks, lint fixes a team keeps out of the repository.

It is applied at **export and publish render only**. The stored canonical model and the Studio
editing surface never see it, so every lint, diff and SDK path is unchanged. Every consumer of the
chain goes through :func:`resolve_chain`:

* the export job and ``POST /v1/export/{t}/verify`` (stored chain first, then the request's inline
  overlays, unless the request opts out with ``applyStoredOverlays: false``);
* ``GET /v1/versions/{t}/{p}/{v}/overlays/preview``;
* the publish render (:func:`render_for_publish`), which records the source and resolved
  fingerprints side by side.

Because preview and export share this function, the preview is exactly what the export renders.

A stored overlay whose target no longer matches (for example after a Studio edit removed the path
it updated) is an ``overlay.unmatched-target`` finding on the next render, never a silent no-op —
:func:`app.export_overlay.apply_export_overlays` reports every action it could not apply.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .export_overlay import (
    MAX_EXPORT_OVERLAYS,
    OVERLAY_INVALID,
    ExportOverlay,
    ExportOverlayError,
    ExportOverlayReport,
    apply_export_overlays,
    overlay_source_document,
)
from .export_source import ExportSource

__all__ = [
    "MAX_STORED_OVERLAYS",
    "OVERLAY_SOURCES",
    "STORED_OVERLAY_PREFIX",
    "ChainRender",
    "StoredOverlay",
    "document_fingerprint",
    "render_for_publish",
    "resolve_chain",
    "stored_export_overlays",
]

#: Sources a stored overlay may declare. Must match V385's ``version_overlays.source`` CHECK.
OVERLAY_SOURCES = ("manual", "lint-fix", "export-studio", "enrichment-export")

#: Longest stored chain. It shares :data:`~app.export_overlay.MAX_EXPORT_OVERLAYS` so a full stored
#: chain still renders. A request's inline overlays count towards the same cap.
MAX_STORED_OVERLAYS = MAX_EXPORT_OVERLAYS

#: Label prefix for stored overlays in ledger rows and findings. It tells a stored overlay apart
#: from an inline overlay that has the same name.
STORED_OVERLAY_PREFIX = "stored:"


@dataclass(frozen=True)
class StoredOverlay:
    """One row of a revision's overlay chain.

    Attributes:
        id: The row id (``version_overlays.id``).
        position: Order in the chain; 0 applies first.
        name: The overlay's label.
        source: One of :data:`OVERLAY_SOURCES`.
        document: The parsed Overlay document.
        content_fingerprint: ``sha256:`` of :func:`document_fingerprint` over ``document``.
        created_by: The user who stored it, if known.
        created_at: When it was stored (ISO-8601 or a datetime, whatever the row carried).
    """

    id: str
    position: int
    name: str
    source: str
    document: Dict[str, Any]
    content_fingerprint: str
    created_by: Optional[str] = None
    created_at: Any = None


@dataclass
class ChainRender:
    """The result of a publish render.

    Attributes:
        source_fingerprint: Fingerprint of the source OpenAPI document (before the chain).
        resolved_fingerprint: Fingerprint of the resolved (post-chain) document.
        overlay_fingerprints: ``[{id, name, position, contentFingerprint}]`` of the chain, in order.
        report: What the chain did — ledger rows and ``overlay.*`` findings.
    """

    source_fingerprint: str
    resolved_fingerprint: str
    overlay_fingerprints: List[Dict[str, Any]] = field(default_factory=list)
    report: Optional[ExportOverlayReport] = None


def document_fingerprint(document: Mapping[str, Any]) -> str:
    """Return a stable ``sha256:`` fingerprint of a JSON document.

    The canonical serialization (sorted keys, compact separators) is the same one
    :func:`app.version_quality_capture.openapi_source_fingerprint` uses, so source, resolved and
    overlay fingerprints are comparable.

    Args:
        document: Any JSON-compatible mapping.

    Returns:
        ``"sha256:<hex>"``.
    """
    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def stored_export_overlays(stored: Sequence[StoredOverlay]) -> List[ExportOverlay]:
    """Turn stored chain rows into export overlays, in chain order.

    Args:
        stored: The chain rows (any order; sorted by ``position`` here).

    Returns:
        One :class:`~app.export_overlay.ExportOverlay` per row, labelled
        ``stored:<name>``.

    Raises:
        ExportOverlayError: ``OVERLAY_INVALID`` when a stored document no longer validates (it
            cannot happen through the API, which validates on write; it guards hand-edited rows).
    """
    overlays: List[ExportOverlay] = []
    for row in sorted(stored, key=lambda r: r.position):
        try:
            overlays.append(ExportOverlay(name=f"{STORED_OVERLAY_PREFIX}{row.name}", document=row.document))
        except ValueError as exc:
            raise ExportOverlayError(
                f"Stored overlay {row.name!r} (position {row.position}) is not a valid Overlay "
                f"document: {exc}",
                code=OVERLAY_INVALID,
            ) from exc
    return overlays


def resolve_chain(
    source: ExportSource,
    stored: Sequence[StoredOverlay],
    inline: Optional[Sequence[ExportOverlay]] = None,
) -> Tuple[ExportSource, Optional[ExportOverlayReport]]:
    """Apply a revision's stored chain, then any inline overlays, to an export source.

    This is the single render path for export, verify, preview and publish.

    Args:
        source: The loaded export source (:func:`app.export_source.load_export_source`).
        stored: The revision's stored chain; empty for none (or when the caller opted out).
        inline: The request's inline overlays, applied after the stored chain.

    Returns:
        ``(source, report)`` as :func:`app.export_overlay.apply_export_overlays` returns them:
        the post-overlay source and what the overlays did, or the source unchanged and ``None``
        when there is nothing to apply.

    Raises:
        ExportOverlayError: ``OVERLAY_INVALID`` when stored plus inline overlays exceed
            :data:`MAX_EXPORT_OVERLAYS`, or when an overlay cannot be applied;
            ``OVERLAY_SOURCE_UNSUPPORTED`` when the source was not built from OpenAPI.
    """
    chain = stored_export_overlays(stored) + list(inline or [])
    if len(chain) > MAX_EXPORT_OVERLAYS:
        raise ExportOverlayError(
            f"An export may apply at most {MAX_EXPORT_OVERLAYS} overlays; this revision's stored "
            f"chain has {len(stored)} and the request adds {len(inline or [])}. Remove inline "
            "overlays, or export with applyStoredOverlays set to false.",
            code=OVERLAY_INVALID,
        )
    return apply_export_overlays(source, chain)


def render_for_publish(source: ExportSource, stored: Sequence[StoredOverlay]) -> Optional[ChainRender]:
    """Render a revision's stored chain for publish and fingerprint both documents.

    Args:
        source: The revision's loaded export source.
        stored: Its stored chain.

    Returns:
        The :class:`ChainRender`, or ``None`` when the chain is empty (nothing to record).

    Raises:
        ExportOverlayError: When the chain cannot be applied (the caller records and audits it;
            a publish never fails because of it).
    """
    if not stored:
        return None
    base = overlay_source_document(source)
    resolved_source, report = resolve_chain(source, stored)
    resolved = resolved_source.api.raw if isinstance(resolved_source.api.raw, Mapping) else {}
    return ChainRender(
        source_fingerprint=document_fingerprint(base or {}),
        resolved_fingerprint=document_fingerprint(resolved),
        overlay_fingerprints=[
            {
                "id": row.id,
                "name": row.name,
                "position": row.position,
                "contentFingerprint": row.content_fingerprint,
            }
            for row in sorted(stored, key=lambda r: r.position)
        ],
        report=report,
    )
