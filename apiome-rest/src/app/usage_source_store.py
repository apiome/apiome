"""Find or create the HAR usage source of a project — RDG-1.4 (#5762).

``apiome usage upload file.har --project pets --environment staging`` needs a ``usage_source`` to
post its events to. Rather than make the developer ask an operator for one, the CLI asks the server
for **the project's HAR source in that environment**, and the server finds it or creates it:

* **Named source.** When the caller names a source id, it must exist in the tenant (404), be
  enabled (403), belong to the named project (409 ``usage-source-project-mismatch``) and be of kind
  ``har`` (409 ``usage-source-kind-mismatch``) — a key cannot pour a HAR into an OTLP source.
* **Found source.** Otherwise the oldest ``har`` source of the project in that environment is
  answered. A disabled one is refused (403) rather than replaced: ``enabled`` is the tenant's off
  switch, and creating a fresh source next to it would route around it.
* **Created source.** When there is none, one is created with ``field_capture`` on (field presence
  is the point of a HAR upload), sampling rate 1 and no body window.

Only ``har`` sources are ever created here; every other kind stays an operator's decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .sdk_beacon_store import CODE_SOURCE_KIND_MISMATCH
from .usage_events import ENVIRONMENT_PATTERN, MOCK_ENVIRONMENT
from .usage_ingest import CODE_BATCH_INVALID, CODE_SOURCE_DISABLED, SourceConfig, UsageIngestError
from .usage_ingest_store import load_source

__all__ = [
    "CODE_SOURCE_PROJECT_MISMATCH",
    "HAR_SOURCE_KIND",
    "ResolvedSource",
    "resolve_har_source",
]

#: The source kind a HAR upload files its events under.
HAR_SOURCE_KIND = "har"

#: The named source belongs to another project.
CODE_SOURCE_PROJECT_MISMATCH = "usage-source-project-mismatch"

_ENVIRONMENT = re.compile(ENVIRONMENT_PATTERN)

_COLUMNS = """
    id::text AS id, tenant_id::text AS tenant_id, project_id::text AS project_id, kind,
    environment, sampling_rate, field_capture, body_sample_rate, body_sample_until, enabled
"""


@dataclass(frozen=True)
class ResolvedSource:
    """The source a HAR upload posts to.

    Attributes:
        source: The source's configuration.
        created: Whether this call created it.
    """

    source: SourceConfig
    created: bool


def _config(row: Dict[str, Any]) -> SourceConfig:
    """Build a :class:`SourceConfig` from a ``usage_source`` row selected with ``_COLUMNS``."""
    return SourceConfig(
        id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        kind=row["kind"],
        environment=row["environment"],
        sampling_rate=float(row["sampling_rate"]),
        field_capture=bool(row["field_capture"]),
        body_sample_rate=float(row["body_sample_rate"]),
        body_sample_until=row["body_sample_until"],
        enabled=bool(row["enabled"]),
    )


def _check_environment(environment: str) -> str:
    """Validate an environment name for a HAR source.

    Args:
        environment: The requested environment.

    Returns:
        The environment, unchanged.

    Raises:
        UsageIngestError: 400 ``usage-batch-invalid`` when it is not a valid name or is the reserved
            ``mock`` environment.
    """
    if not _ENVIRONMENT.match(environment or ""):
        raise UsageIngestError(
            400,
            CODE_BATCH_INVALID,
            "environment must be lower-case letters, digits, '_' or '-', start with a letter and be at most 32 "
            "characters",
        )
    if environment == MOCK_ENVIRONMENT:
        raise UsageIngestError(400, CODE_BATCH_INVALID, "the mock environment is reserved for the mock runtime")
    return environment


def resolve_har_source(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    environment: str,
    source_ref: Optional[str] = None,
) -> ResolvedSource:
    """Find, check or create the HAR source a project's upload posts to.

    Args:
        db: The database.
        tenant_id: The authenticated tenant.
        project_id: The project (already resolved to a UUID within the tenant).
        environment: The environment the upload reports (``prod``, ``staging``, ...).
        source_ref: A source id the caller named, or ``None`` to find or create one.

    Returns:
        The source and whether it was created.

    Raises:
        UsageIngestError: 400 for a bad environment; 404 / 403 for an unknown or disabled source;
            409 when a named source belongs to another project or is not a ``har`` source.
    """
    environment = _check_environment(environment)
    if source_ref:
        source = load_source(db, tenant_id, source_ref)
        if source.project_id != project_id:
            raise UsageIngestError(409, CODE_SOURCE_PROJECT_MISMATCH, "this usage source belongs to another project")
        if source.kind != HAR_SOURCE_KIND:
            raise UsageIngestError(
                409, CODE_SOURCE_KIND_MISMATCH, f"this usage source is a '{source.kind}' source, not a 'har' one"
            )
        return ResolvedSource(source=source, created=False)

    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}
        FROM apiome.usage_source
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND kind = %s AND environment = %s
        ORDER BY created_at, id
        LIMIT 1
        """,
        (tenant_id, project_id, HAR_SOURCE_KIND, environment),
    )
    if rows:
        found = _config(rows[0])
        if not found.enabled:
            raise UsageIngestError(403, CODE_SOURCE_DISABLED, "this project's HAR usage source is disabled")
        return ResolvedSource(source=found, created=False)

    created = db.execute_query(
        f"""
        INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment, field_capture)
        VALUES (%s::uuid, %s::uuid, %s, %s, true)
        RETURNING {_COLUMNS}
        """,
        (tenant_id, project_id, HAR_SOURCE_KIND, environment),
    )
    return ResolvedSource(source=_config(created[0]), created=True)

