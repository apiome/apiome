"""Contributing repositories and per-entity provenance of a project — REPO-5.7 (#2792).

A project can source from several repository files (one per service). Each import of a repository
file into the project produces a version holding the union of the contributing files; the import
(apiome-ui ``lib/db/repository-merge.ts``) records

* the project's contributing files in ``apiome.project_repository_sources`` (apiome-db V301), one
  row per repository / branch / path with a ``precedence`` (1 contributed first), and
* which file defined each class and path of a version in ``apiome.version_entity_sources``.

This module is the read side: :func:`read_project_repository_sources` answers ``GET
/v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources`` with the contributing files
and the provenance of every class and path of one version. A class or path without a provenance row
is reported with ``source: null`` — it was not defined by a repository (edited in Apiome, or
imported before REPO-5.7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import comment_store
from .database import db

__all__ = [
    "EntityProvenance",
    "ProjectRepositorySource",
    "ProjectRepositorySourcesResponse",
    "ProvenanceCounts",
    "ProvenanceSource",
    "ProvenanceVersion",
    "read_project_repository_sources",
]

EntityKind = Literal["class", "path"]


class ProjectRepositorySource(BaseModel):
    """One repository file contributing to the project's merged API surface."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The source row id.")
    repository_id: str = Field(description="The registered tenant repository.")
    repository_full_name: Optional[str] = Field(
        default=None, description="`owner/name` of the repository."
    )
    provider: Optional[str] = Field(default=None, description="`github`, `gitlab`, or `bitbucket`.")
    branch: str = Field(description="Branch the file is imported from.")
    path: str = Field(description="Repository-relative path of the file.")
    precedence: int = Field(
        description=(
            "Merge order: 1 contributed first. Orders the merged surface and keeps the first "
            "source's project info; it never resolves a conflict — two files defining the same "
            "class or path fail the import."
        )
    )
    first_version_id: Optional[str] = Field(
        default=None, description="The version this file first contributed to."
    )
    last_version_id: Optional[str] = Field(
        default=None, description="The version this file was last imported into."
    )
    last_version_label: Optional[str] = Field(
        default=None, description="That version's label, e.g. `1.2.0`."
    )
    last_blob_sha: Optional[str] = Field(default=None, description="Blob of the last import.")
    class_count: int = Field(
        default=0, description="Classes of the reported version this file defines."
    )
    path_count: int = Field(default=0, description="Paths of the reported version this file defines.")
    created_at: datetime
    updated_at: datetime


class ProvenanceSource(BaseModel):
    """The repository file a class or path came from (snapshotted at import time)."""

    model_config = ConfigDict(extra="forbid")

    source_id: Optional[str] = Field(
        default=None,
        description="The contributing source row; null once that source was removed.",
    )
    repository_id: Optional[str] = None
    repository_full_name: str
    branch: str
    path: str
    blob_sha: Optional[str] = None
    carried_from_version_id: Optional[str] = Field(
        default=None,
        description=(
            "The version this entity was carried forward from by a merge; null when this "
            "version's import wrote it."
        ),
    )


class EntityProvenance(BaseModel):
    """A class or path of the version and where it came from."""

    model_config = ConfigDict(extra="forbid")

    kind: EntityKind = Field(description="`class` or `path`.")
    key: str = Field(description="The class name or the pathname.")
    source: Optional[ProvenanceSource] = Field(
        default=None, description="Null when no repository defined it."
    )


class ProvenanceCounts(BaseModel):
    """How much of the version is attributed to a repository."""

    model_config = ConfigDict(extra="forbid")

    classes: int
    paths: int
    attributed: int
    unattributed: int


class ProvenanceVersion(BaseModel):
    """The version the provenance describes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The revision id (`versions.id`).")
    version_label: Optional[str] = Field(default=None, description="e.g. `1.2.0`.")


class ProjectRepositorySourcesResponse(BaseModel):
    """A project's contributing repository files and one version's provenance."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    sources: List[ProjectRepositorySource] = Field(
        default_factory=list, description="Contributing files in precedence order."
    )
    version: Optional[ProvenanceVersion] = Field(
        default=None, description="The version described; null when the project has none."
    )
    entities: List[EntityProvenance] = Field(
        default_factory=list,
        description="Every live class (first) and path of the version, each ordered by key.",
    )
    counts: ProvenanceCounts


_SOURCES_SQL = """
    SELECT prs.id, prs.repository_id, tr.repository_full_name, tr.provider, prs.branch, prs.path,
           prs.precedence, prs.first_version_id, prs.last_version_id, lv.version_id AS last_version_label,
           prs.last_blob_sha, prs.created_at, prs.updated_at
      FROM apiome.project_repository_sources prs
      LEFT JOIN apiome.tenant_repositories tr ON tr.id = prs.repository_id
      LEFT JOIN apiome.versions lv ON lv.id = prs.last_version_id
     WHERE prs.project_id = %s AND prs.tenant_id = %s
     ORDER BY prs.precedence, prs.created_at, prs.id
"""

_LATEST_VERSION_SQL = """
    SELECT id FROM apiome.versions
     WHERE project_id = %s AND deleted_at IS NULL
     ORDER BY created_at DESC NULLS LAST, id DESC
     LIMIT 1
"""

_ENTITIES_SQL = """
    WITH ents AS (
      SELECT 'class'::text AS kind, c.name::text AS key
        FROM apiome.classes c
       WHERE c.version_id = %s AND c.deleted_at IS NULL
      UNION
      SELECT 'path'::text, vp.pathname::text
        FROM apiome.version_path vp
       WHERE vp.version_id = %s
    )
    SELECT e.kind, e.key, ves.id AS provenance_id, ves.source_id, ves.repository_id,
           ves.repository_full_name, ves.branch, ves.path, ves.blob_sha, ves.carried_from_version_id
      FROM ents e
      LEFT JOIN apiome.version_entity_sources ves
        ON ves.version_id = %s AND ves.entity_kind = e.kind AND ves.entity_key = e.key
     ORDER BY e.kind, e.key
"""


def _str_or_none(value: Any) -> Optional[str]:
    """Stringify a UUID-ish column, keeping NULL as None."""
    return None if value is None else str(value)


def _entity(row: Dict[str, Any]) -> EntityProvenance:
    """Build one entity from a provenance query row."""
    source = None
    if row.get("provenance_id") is not None:
        source = ProvenanceSource(
            source_id=_str_or_none(row.get("source_id")),
            repository_id=_str_or_none(row.get("repository_id")),
            repository_full_name=str(row["repository_full_name"]),
            branch=str(row["branch"]),
            path=str(row["path"]),
            blob_sha=row.get("blob_sha"),
            carried_from_version_id=_str_or_none(row.get("carried_from_version_id")),
        )
    return EntityProvenance(kind=row["kind"], key=str(row["key"]), source=source)


def read_project_repository_sources(
    tenant_id: str, project_ref: str, version_ref: Optional[str] = None
) -> ProjectRepositorySourcesResponse:
    """Read a project's contributing repository files and one version's provenance.

    Args:
        tenant_id: The caller's tenant (scopes every read).
        project_ref: Project slug or id.
        version_ref: Revision id or version label; the project's newest version when omitted.

    Returns:
        The sources in precedence order (each with how many of the version's classes and paths it
        defines), the version, every class and path of it with its source, and the counts.

    Raises:
        CommentValidationError: when the project or the version is not found in the tenant.
    """
    project = comment_store.resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])

    if version_ref and version_ref.strip():
        version_row: Optional[Dict[str, Any]] = comment_store.resolve_version(
            tenant_id, project_id, version_ref
        )
    else:
        latest = db.execute_query(_LATEST_VERSION_SQL, (project_id,))
        version_row = (
            comment_store.resolve_version(tenant_id, project_id, str(latest[0]["id"]))
            if latest
            else None
        )

    entities: List[EntityProvenance] = []
    version: Optional[ProvenanceVersion] = None
    if version_row is not None:
        version_id = str(version_row["id"])
        version = ProvenanceVersion(id=version_id, version_label=version_row.get("version_id"))
        rows = db.execute_query(_ENTITIES_SQL, (version_id, version_id, version_id))
        entities = [_entity(r) for r in rows]

    per_source: Dict[str, Dict[str, int]] = {}
    for entity in entities:
        if entity.source and entity.source.source_id:
            bucket = per_source.setdefault(entity.source.source_id, {"class": 0, "path": 0})
            bucket[entity.kind] += 1

    sources = []
    for row in db.execute_query(_SOURCES_SQL, (project_id, tenant_id)):
        counts = per_source.get(str(row["id"]), {"class": 0, "path": 0})
        sources.append(
            ProjectRepositorySource(
                id=str(row["id"]),
                repository_id=str(row["repository_id"]),
                repository_full_name=row.get("repository_full_name"),
                provider=row.get("provider"),
                branch=str(row["branch"]),
                path=str(row["path"]),
                precedence=int(row["precedence"]),
                first_version_id=_str_or_none(row.get("first_version_id")),
                last_version_id=_str_or_none(row.get("last_version_id")),
                last_version_label=row.get("last_version_label"),
                last_blob_sha=row.get("last_blob_sha"),
                class_count=counts["class"],
                path_count=counts["path"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )

    attributed = sum(1 for e in entities if e.source is not None)
    return ProjectRepositorySourcesResponse(
        project_id=project_id,
        sources=sources,
        version=version,
        entities=entities,
        counts=ProvenanceCounts(
            classes=sum(1 for e in entities if e.kind == "class"),
            paths=sum(1 for e in entities if e.kind == "path"),
            attributed=attributed,
            unattributed=len(entities) - attributed,
        ),
    )
