"""Frozen OpenAPI snapshots of published versions (#3214, CLI 4.7 ``apiome versions freeze``).

``GET /v1/schema/{tenant}/{project}/{version}`` normally builds the OpenAPI document from the
version's live classes, properties and paths. Freezing stores the exact response bytes in
``apiome.version_spec_snapshots`` (V279); while frozen, the route serves those bytes verbatim, so
later class edits never change what consumers download.

* :func:`build_live_spec` — the document ``/v1/schema`` generates, plus what it holds;
* :func:`render_spec_bytes` — the bytes the route sends (Starlette ``JSONResponse`` form), so a
  snapshot taken now is byte-identical to the live response at that moment;
* :func:`summarize` — SHA-256, size and counts for the CLI and the API response;
* :func:`unfreeze_refusal` — whether an unfreeze is allowed (downloads, ``force``, admin).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .openapi_generator import generate_openapi_spec

#: ``detail.code`` values the freeze routes return.
CODE_NOT_PUBLISHED = "version_not_published"
CODE_ALREADY_FROZEN = "already_frozen"
CODE_NOT_FROZEN = "not_frozen"
CODE_DOWNLOADED = "snapshot_downloaded"
CODE_FORCE_REQUIRES_ADMIN = "force_unfreeze_requires_admin"


@dataclass(frozen=True)
class SpecCounts:
    """What a version's OpenAPI document holds."""

    classes: int
    properties: int
    paths: int


def build_live_spec(
    db: Any,
    version: Mapping[str, Any],
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
) -> Tuple[Dict[str, Any], SpecCounts]:
    """Generate the OpenAPI 3.1 document ``/v1/schema`` serves for an unfrozen version.

    Args:
        db: Database handle (``get_classes_for_version``, ``get_properties_for_class``).
        version: The version row from ``get_version_by_slugs`` (needs ``id``, ``metadata``,
            ``project_description``, ``project_metadata``).
        tenant_slug: Tenant slug used in the document's URLs.
        project_slug: Project slug.
        version_slug: Version slug as requested (e.g. ``2.1.0``).

    Returns:
        The document and its :class:`SpecCounts`.
    """
    classes = db.get_classes_for_version(version["id"])
    all_properties: Dict[Any, Any] = {}
    for class_data in classes:
        all_properties[class_data["id"]] = db.get_properties_for_class(class_data["id"])
    spec = generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_slug,
        classes,
        all_properties,
        version.get("project_description"),
        version_db_id=version["id"],
        revision_metadata=version.get("metadata"),
        project_metadata=version.get("project_metadata"),
    )
    counts = SpecCounts(
        classes=len(classes),
        properties=sum(len(props or []) for props in all_properties.values()),
        paths=len(spec.get("paths") or {}),
    )
    return spec, counts


def render_spec_bytes(spec: Any) -> bytes:
    """The response body ``JSONResponse(content=spec)`` sends — compact UTF-8 JSON."""
    return json.dumps(
        spec, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")


def sha256_hex(content: bytes) -> str:
    """Lower-case hex SHA-256 of ``content``."""
    return hashlib.sha256(content).hexdigest()


def snapshot_url(tenant_slug: str, project_slug: str, version_label: str) -> str:
    """Where the frozen document is served."""
    return f"/v1/schema/{tenant_slug}/{project_slug}/{version_label}"


def summarize(
    *,
    content: bytes,
    counts: SpecCounts,
    url: str,
    frozen: bool,
    dry_run: bool = False,
    snapshot_row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The freeze response body (``FreezeSchemaResponse`` fields, snake_case).

    Args:
        content: The snapshot bytes (stored, or the ones a dry run would store).
        counts: What the document holds.
        url: :func:`snapshot_url`.
        frozen: Whether a snapshot is stored after this call.
        dry_run: Whether nothing was written.
        snapshot_row: The stored row, for ``frozen_at`` / ``frozen_by`` / ``download_count``.

    Returns:
        A dict for ``FreezeSchemaResponse``.
    """
    row = snapshot_row or {}
    return {
        "frozen": frozen,
        "dry_run": dry_run,
        "sha256": sha256_hex(content),
        "size_bytes": len(content),
        "snapshot_url": url,
        "class_count": counts.classes,
        "property_count": counts.properties,
        "path_count": counts.paths,
        "frozen_at": row.get("frozen_at"),
        "frozen_by": str(row["frozen_by"]) if row.get("frozen_by") else None,
        "download_count": int(row.get("download_count") or 0),
    }


def row_summary(row: Mapping[str, Any], url: str, *, frozen: bool) -> Dict[str, Any]:
    """The freeze response body for a stored snapshot row (status, unfreeze, already frozen)."""
    return {
        "frozen": frozen,
        "dry_run": False,
        "sha256": str(row["sha256"]).strip(),
        "size_bytes": int(row["size_bytes"]),
        "snapshot_url": url,
        "class_count": int(row.get("class_count") or 0),
        "property_count": int(row.get("property_count") or 0),
        "path_count": int(row.get("path_count") or 0),
        "frozen_at": row.get("frozen_at"),
        "frozen_by": str(row["frozen_by"]) if row.get("frozen_by") else None,
        "download_count": int(row.get("download_count") or 0),
    }


def unfreeze_refusal(
    download_count: int, *, force: bool, is_admin: bool, is_owner: bool
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Why an unfreeze is refused, as ``(status, detail)``; ``None`` when it may go ahead.

    * Only the version's creator or a tenant administrator may unfreeze (403).
    * ``force`` is for tenant administrators only (403 ``force_unfreeze_requires_admin``).
    * Once the snapshot has been downloaded, unfreezing needs ``force`` (409
      ``snapshot_downloaded``) — a consumer may already depend on those bytes.
    """
    if not (is_owner or is_admin):
        return 403, {
            "code": "forbidden",
            "message": "Only the version creator or a tenant administrator can unfreeze this version.",
        }
    if force and not is_admin:
        return 403, {
            "code": CODE_FORCE_REQUIRES_ADMIN,
            "message": "Only a tenant administrator can force an unfreeze.",
        }
    if download_count > 0 and not force:
        return 409, {
            "code": CODE_DOWNLOADED,
            "message": (
                f"The snapshot has been downloaded {download_count} time(s); a consumer may depend on "
                "it. A tenant administrator can unfreeze it anyway with force=true."
            ),
            "download_count": download_count,
        }
    return None
