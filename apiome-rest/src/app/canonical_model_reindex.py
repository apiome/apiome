"""Re-index existing catalog items into the canonical model tables (MFI-6.2, #3754).

The cross-protocol search (:mod:`app.model_search`) reads the MFI-2.2 canonical tables. Imports
persist their canonical model there now, but before MFI-6.2 only AsyncAPI, Arazzo and
agent-descriptor imports did, so most existing catalog items (gRPC, GraphQL, Avro, OData, …) have
no rows to find. This one-off backfill fills them in.

The canonical model is not stored anywhere else, so it is rebuilt the way the import built it:
:func:`app.catalog_conversion.build_conversion_source` resolves the item's adapter, parses the
source the revision captured (``format_metadata.sourceContent``) and normalizes it. The result is
written with :meth:`app.database.Database.persist_canonical_api`, the same call the import makes.

Run it from ``apiome-rest`` with ``scripts/backfill_canonical_models.py``. It is safe to re-run:
candidates are catalog items whose latest revision has no live canonical artifact, so an indexed
item is never re-parsed. An item without a captured source (it was withheld, or imported before
sources were kept) cannot be rebuilt and is reported as skipped each run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .catalog_conversion import build_conversion_source
from .conversion_job import ConversionError

logger = logging.getLogger(__name__)

__all__ = ["reindex_catalog_canonical_models"]


def reindex_catalog_canonical_models(
    db: Any, *, limit: Optional[int] = None
) -> Dict[str, Any]:
    """Rebuild and persist the canonical model of every catalog item that lacks one.

    Each item is independent: a failure is recorded and the run moves on to the next one.

    Args:
        db: The database handle (:data:`app.database.db` in production).
        limit: Optional cap on the number of items processed in this run.

    Returns:
        A summary: ``processed``, ``indexed``, ``skipped`` (no source to rebuild from) and
        ``failed`` counts, plus ``skips`` and ``failures`` lists of
        ``{projectId, versionId, reason}``.
    """
    summary: Dict[str, Any] = {
        "processed": 0,
        "indexed": 0,
        "skipped": 0,
        "failed": 0,
        "skips": [],
        "failures": [],
    }
    for row in db.list_catalog_versions_needing_canonical_reindex(limit=limit):
        tenant_id = str(row["tenant_id"])
        project_id = str(row["project_id"])
        version_id = str(row["version_id"])
        summary["processed"] += 1
        entry = {"projectId": project_id, "versionId": version_id}
        try:
            item = db.get_catalog_item_by_id(project_id, tenant_id)
            if not item:
                raise ConversionError("catalog item not found", status_code=404)
            source = build_conversion_source(item, source_version_id=version_id)
        except ConversionError as exc:
            # 422 = nothing to rebuild from (no captured or a withheld source): not a failure.
            bucket = "skips" if exc.status_code == 422 else "failures"
            summary["skipped" if bucket == "skips" else "failed"] += 1
            summary[bucket].append({**entry, "reason": str(exc)})
            continue
        except Exception as exc:  # an adapter bug must not stop the run
            logger.warning("canonical re-index: rebuilding %s failed: %s", project_id, exc)
            summary["failed"] += 1
            summary["failures"].append({**entry, "reason": str(exc)})
            continue
        try:
            db.persist_canonical_api(
                tenant_id=tenant_id,
                creator_id=str(row["creator_id"]),
                version_id=version_id,
                model=source.api,
            )
        except Exception as exc:
            logger.warning("canonical re-index: persisting %s failed: %s", project_id, exc)
            summary["failed"] += 1
            summary["failures"].append({**entry, "reason": str(exc)})
            continue
        summary["indexed"] += 1
    return summary
