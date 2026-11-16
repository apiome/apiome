"""Storage for a revision's overlay chain — GVM-4.3 (#5878), apiome-db V385.

Rules this module keeps (the HTTP surface is :mod:`app.version_overlay_routes`):

* **Write-once rows.** V385 refuses UPDATE on ``version_overlays``. :func:`replace_overlay` is a
  DELETE + INSERT at the same position in one transaction, with one ``version.overlay_replaced``
  audit row in that transaction.
* **Dense positions.** Append takes the next position. An insert at a position shifts later rows
  up, and a delete compacts them down. Positions are moved by delete + re-insert, because rows
  cannot be updated; the UNIQUE constraint is deferred for the duration of the transaction.
* **Audit in the same transaction.** Every write appends its ``apiome.workflow_audit`` row before
  the commit, so a chain change and its audit event commit or roll back together.
* **Tenant scope.** Every query filters on ``tenant_id``.

The published-revision guard (``409 overlay-version-published``) is the route's, because it needs
the version row the route already loads.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .database import db
from .export_overlay import ExportOverlay, ExportOverlayError, ExportOverlayReport
from .export_source import ExportSource, ExportSourceError, load_export_source
from .version_overlay_chain import (
    ChainRender,
    StoredOverlay,
    document_fingerprint,
    render_for_publish,
    resolve_chain,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "delete_overlay",
    "get_render",
    "insert_overlay",
    "list_overlays",
    "record_render",
    "render_chain_on_publish",
    "replace_overlay",
    "resolve_for_export",
]

_COLUMNS = "id, position, name, source, document, content_fingerprint, created_by, created_at"


def _row_to_overlay(row: Mapping[str, Any]) -> StoredOverlay:
    """Build a :class:`StoredOverlay` from a ``version_overlays`` row (dict cursor)."""
    document = row["document"]
    if isinstance(document, str):
        document = json.loads(document)
    return StoredOverlay(
        id=str(row["id"]),
        position=int(row["position"]),
        name=str(row["name"]),
        source=str(row["source"]),
        document=dict(document or {}),
        content_fingerprint=str(row["content_fingerprint"]),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        created_at=row.get("created_at"),
    )


def _audit(
    cursor: Any,
    *,
    tenant_id: str,
    project_id: Optional[str],
    version_record_id: str,
    action: str,
    actor_id: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Append a ``workflow_audit`` row inside the caller's transaction."""
    cursor.execute(
        """
        INSERT INTO apiome.workflow_audit
          (tenant_id, project_id, version_id, action, outcome, actor_id, detail)
        VALUES (%s, %s, %s, %s, 'success', %s, %s::jsonb)
        """,
        (tenant_id, project_id, version_record_id, action, actor_id, json.dumps(detail, default=str)),
    )


def _select_chain(cursor: Any, tenant_id: str, version_record_id: str, *, lock: bool = False) -> List[StoredOverlay]:
    """Read the chain in position order, optionally locking its rows for a write."""
    cursor.execute(
        f"""
        SELECT {_COLUMNS}
        FROM apiome.version_overlays
        WHERE tenant_id = %s AND version_record_id = %s
        ORDER BY position
        {"FOR UPDATE" if lock else ""}
        """,
        (tenant_id, version_record_id),
    )
    return [_row_to_overlay(row) for row in cursor.fetchall() or []]


def _insert_row(
    cursor: Any,
    *,
    tenant_id: str,
    version_record_id: str,
    position: int,
    name: str,
    source: str,
    document: Mapping[str, Any],
    created_by: Optional[str],
    overlay_id: Optional[str] = None,
    created_at: Any = None,
) -> StoredOverlay:
    """Insert one chain row and return it. ``overlay_id`` / ``created_at`` keep a moved row's identity."""
    cursor.execute(
        f"""
        INSERT INTO apiome.version_overlays
          (id, tenant_id, version_record_id, position, name, source, document,
           content_fingerprint, created_by, created_at)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                COALESCE(%s::timestamptz, CURRENT_TIMESTAMP))
        RETURNING {_COLUMNS}
        """,
        (
            overlay_id or str(uuid.uuid4()),
            tenant_id,
            version_record_id,
            position,
            name,
            source,
            json.dumps(document),
            document_fingerprint(document),
            created_by,
            created_at,
        ),
    )
    return _row_to_overlay(cursor.fetchone())


def _move(cursor: Any, tenant_id: str, row: StoredOverlay, version_record_id: str, position: int) -> None:
    """Move a write-once row to ``position`` (delete + re-insert with the same id and timestamps)."""
    cursor.execute(
        "DELETE FROM apiome.version_overlays WHERE tenant_id = %s AND id = %s",
        (tenant_id, row.id),
    )
    _insert_row(
        cursor,
        tenant_id=tenant_id,
        version_record_id=version_record_id,
        position=position,
        name=row.name,
        source=row.source,
        document=row.document,
        created_by=row.created_by,
        overlay_id=row.id,
        created_at=row.created_at,
    )


def list_overlays(tenant_id: str, version_record_id: str) -> List[StoredOverlay]:
    """Return a revision's stored chain in application order.

    Args:
        tenant_id: The caller's tenant.
        version_record_id: The revision (``versions.id``).

    Returns:
        The chain rows, ``position`` ascending; empty when the revision has none.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _select_chain(cursor, tenant_id, version_record_id)


def resolve_for_export(
    tenant_id: str,
    source: ExportSource,
    inline: Optional[Sequence[ExportOverlay]] = None,
    *,
    apply_stored: bool = True,
) -> Tuple[ExportSource, Optional[ExportOverlayReport]]:
    """Apply a revision's stored chain (unless opted out), then ``inline``, to an export source.

    The one entry point for the export job, verify and the chain preview, so they all render the
    same document.

    Args:
        tenant_id: The caller's tenant.
        source: The loaded export source; its ``version_record_id`` selects the chain.
        inline: The request's inline overlays, applied after the stored chain.
        apply_stored: ``False`` skips the stored chain (``apply_stored_overlays: false``).

    Returns:
        ``(source, report)`` from :func:`app.version_overlay_chain.resolve_chain`.

    Raises:
        ExportOverlayError: When the chain cannot be applied.
    """
    stored = list_overlays(tenant_id, source.version_record_id) if apply_stored else []
    return resolve_chain(source, stored, inline)


def insert_overlay(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    name: str,
    source: str,
    document: Mapping[str, Any],
    actor_id: Optional[str],
    position: Optional[int] = None,
) -> StoredOverlay:
    """Add an overlay to the chain, at the end or at ``position``.

    Args:
        tenant_id: The caller's tenant.
        project_id: The revision's project (for the audit row).
        version_record_id: The revision.
        name: The overlay's label (already validated).
        source: One of :data:`app.version_overlay_chain.OVERLAY_SOURCES`.
        document: The validated Overlay document.
        actor_id: The user storing it.
        position: Where to insert it. ``None``, or a position past the end, appends; a position
            inside the chain shifts that row and the rows after it up by one.

    Returns:
        The stored row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS apiome.version_overlays_position_uq DEFERRED")
            chain = _select_chain(cursor, tenant_id, version_record_id, lock=True)
            at = len(chain) if position is None or position >= len(chain) else max(0, position)
            for row in reversed(chain[at:]):
                _move(cursor, tenant_id, row, version_record_id, row.position + 1)
            stored = _insert_row(
                cursor,
                tenant_id=tenant_id,
                version_record_id=version_record_id,
                position=at,
                name=name,
                source=source,
                document=document,
                created_by=actor_id,
            )
            _audit(
                cursor,
                tenant_id=tenant_id,
                project_id=project_id,
                version_record_id=version_record_id,
                action="version.overlay_added",
                actor_id=actor_id,
                detail={
                    "overlayId": stored.id,
                    "name": stored.name,
                    "source": stored.source,
                    "position": stored.position,
                    "contentFingerprint": stored.content_fingerprint,
                },
            )
        conn.commit()
        return stored
    except Exception:
        conn.rollback()
        raise


def replace_overlay(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    overlay_id: str,
    name: str,
    source: str,
    document: Mapping[str, Any],
    actor_id: Optional[str],
) -> Optional[StoredOverlay]:
    """Replace one overlay in place: delete + insert at the same position, one audit event.

    Args:
        tenant_id: The caller's tenant.
        project_id: The revision's project (for the audit row).
        version_record_id: The revision.
        overlay_id: The row being replaced.
        name: The new label.
        source: The new source.
        document: The new validated Overlay document.
        actor_id: The user replacing it.

    Returns:
        The new row (it has a new id: rows are write-once), or ``None`` when ``overlay_id`` is not in
        this revision's chain.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            chain = _select_chain(cursor, tenant_id, version_record_id, lock=True)
            old = next((row for row in chain if row.id == overlay_id), None)
            if old is None:
                conn.rollback()
                return None
            cursor.execute(
                "DELETE FROM apiome.version_overlays WHERE tenant_id = %s AND id = %s",
                (tenant_id, old.id),
            )
            stored = _insert_row(
                cursor,
                tenant_id=tenant_id,
                version_record_id=version_record_id,
                position=old.position,
                name=name,
                source=source,
                document=document,
                created_by=actor_id,
            )
            _audit(
                cursor,
                tenant_id=tenant_id,
                project_id=project_id,
                version_record_id=version_record_id,
                action="version.overlay_replaced",
                actor_id=actor_id,
                detail={
                    "replacedOverlayId": old.id,
                    "replacedFingerprint": old.content_fingerprint,
                    "overlayId": stored.id,
                    "name": stored.name,
                    "source": stored.source,
                    "position": stored.position,
                    "contentFingerprint": stored.content_fingerprint,
                },
            )
        conn.commit()
        return stored
    except Exception:
        conn.rollback()
        raise


def delete_overlay(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    overlay_id: str,
    actor_id: Optional[str],
) -> bool:
    """Remove one overlay and compact the positions after it.

    Args:
        tenant_id: The caller's tenant.
        project_id: The revision's project (for the audit row).
        version_record_id: The revision.
        overlay_id: The row to remove.
        actor_id: The user removing it.

    Returns:
        ``True`` when the row was removed, ``False`` when it is not in this revision's chain.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS apiome.version_overlays_position_uq DEFERRED")
            chain = _select_chain(cursor, tenant_id, version_record_id, lock=True)
            old = next((row for row in chain if row.id == overlay_id), None)
            if old is None:
                conn.rollback()
                return False
            cursor.execute(
                "DELETE FROM apiome.version_overlays WHERE tenant_id = %s AND id = %s",
                (tenant_id, old.id),
            )
            for row in chain:
                if row.position > old.position:
                    _move(cursor, tenant_id, row, version_record_id, row.position - 1)
            _audit(
                cursor,
                tenant_id=tenant_id,
                project_id=project_id,
                version_record_id=version_record_id,
                action="version.overlay_removed",
                actor_id=actor_id,
                detail={
                    "overlayId": old.id,
                    "name": old.name,
                    "source": old.source,
                    "position": old.position,
                    "contentFingerprint": old.content_fingerprint,
                },
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def record_render(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    render: ChainRender,
    actor_id: Optional[str],
) -> None:
    """Store the publish render of a chain and audit it (``version.overlay_rendered``).

    Args:
        tenant_id: The caller's tenant.
        project_id: The revision's project (for the audit row).
        version_record_id: The published revision.
        render: What :func:`app.version_overlay_chain.render_for_publish` produced.
        actor_id: The user who published.
    """
    findings = [finding.model_dump() for finding in (render.report.findings if render.report else [])]
    changes = render.report.changes if render.report else 0
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.version_overlay_renders
                  (version_record_id, tenant_id, source_fingerprint, resolved_fingerprint,
                   overlay_fingerprints, findings, changes, rendered_by, rendered_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (version_record_id) DO UPDATE SET
                  source_fingerprint = EXCLUDED.source_fingerprint,
                  resolved_fingerprint = EXCLUDED.resolved_fingerprint,
                  overlay_fingerprints = EXCLUDED.overlay_fingerprints,
                  findings = EXCLUDED.findings,
                  changes = EXCLUDED.changes,
                  rendered_by = EXCLUDED.rendered_by,
                  rendered_at = EXCLUDED.rendered_at
                """,
                (
                    version_record_id,
                    tenant_id,
                    render.source_fingerprint,
                    render.resolved_fingerprint,
                    json.dumps(render.overlay_fingerprints),
                    json.dumps(findings),
                    changes,
                    actor_id,
                ),
            )
            _audit(
                cursor,
                tenant_id=tenant_id,
                project_id=project_id,
                version_record_id=version_record_id,
                action="version.overlay_rendered",
                actor_id=actor_id,
                detail={
                    "sourceFingerprint": render.source_fingerprint,
                    "resolvedFingerprint": render.resolved_fingerprint,
                    "overlays": render.overlay_fingerprints,
                    "changes": changes,
                    "findings": findings,
                },
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def render_chain_on_publish(
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    actor_id: Optional[str],
) -> Optional[ChainRender]:
    """Publish render: apply the revision's stored chain and record both fingerprints.

    It runs after a successful publish and is best-effort: a chain that cannot be rendered is audited
    as a failed ``version.overlay_rendered`` and never fails or reverts the publish. A revision
    without a chain records nothing.

    Args:
        tenant_id: The caller's tenant.
        project_id: The published revision's project.
        version_record_id: The published revision.
        actor_id: The user who published.

    Returns:
        The recorded :class:`ChainRender`, or ``None`` when there was no chain or it failed.
    """
    try:
        stored = list_overlays(tenant_id, version_record_id)
        if not stored:
            return None
        source = load_export_source(tenant_id, project_id, version_record_id)
        render = render_for_publish(source, stored)
        if render is None:
            return None
        record_render(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=version_record_id,
            render=render,
            actor_id=actor_id,
        )
        return render
    except (ExportOverlayError, ExportSourceError) as exc:
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            version_record_id,
            "version.overlay_rendered",
            "failure",
            actor_id,
            {"code": getattr(exc, "code", None), "message": str(exc)},
        )
    except Exception:  # noqa: BLE001 - the publish has already happened; never fail it
        _logger.warning("Overlay chain publish render failed for %s", version_record_id, exc_info=True)
    return None


def get_render(tenant_id: str, version_record_id: str) -> Optional[Dict[str, Any]]:
    """Return the stored publish render of a revision's chain, or ``None`` when it has none.

    Args:
        tenant_id: The caller's tenant.
        version_record_id: The revision.

    Returns:
        ``{source_fingerprint, resolved_fingerprint, overlays, findings, changes, rendered_by,
        rendered_at}`` or ``None``.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_fingerprint, resolved_fingerprint, overlay_fingerprints, findings, changes,
                   rendered_by, rendered_at
            FROM apiome.version_overlay_renders
            WHERE tenant_id = %s AND version_record_id = %s
            """,
            (tenant_id, version_record_id),
        )
        row = cursor.fetchone()
    if not row:
        return None

    def _json(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    return {
        "source_fingerprint": row["source_fingerprint"],
        "resolved_fingerprint": row["resolved_fingerprint"],
        "overlays": _json(row["overlay_fingerprints"]) or [],
        "findings": _json(row["findings"]) or [],
        "changes": int(row["changes"] or 0),
        "rendered_by": str(row["rendered_by"]) if row.get("rendered_by") else None,
        "rendered_at": row["rendered_at"],
    }
