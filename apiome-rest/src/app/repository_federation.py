"""Multi-repository federation: toggle and merge history — V2-REPO-8.2 (#2806).

REPO-5.7 (#2792) built the merge itself: every repository file imported into a project is merged
with the other contributing files into one API surface, with deterministic precedence and
per-entity provenance (apiome-db V301). The merge runs in apiome-ui's import
(``lib/repository-merge.ts``). Federation adds, on top of it (apiome-db V303):

* **The switch** — ``projects.repository_federation``. On (the default) keeps REPO-5.7's merge.
  Off makes each import replace the project's surface with the importing file alone.
* **The merge history** — ``project_federation_merges``: one row per repository-file import that
  federation acted on. ``merged`` (a multi-file merge wrote a version), ``conflicted`` (two files
  define the same class or path — the import failed and wrote nothing) or ``replaced`` (federation
  off, and the import dropped other files' content).
* **Per-source diffs.** A conflicted row keeps, for each colliding class or path, every source's
  definition of it — the importing file's (sent by the import) and the contributing file's (read
  here from the parent version's rendered spec) — so the history can show them side by side.

This module is pure: the request and response models, how a definition is found in a spec and
bounded, and which audit action each status writes. The writes are :mod:`app.repository_federation_store`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AUDIT_BY_STATUS",
    "AUDIT_TOGGLED",
    "DEFINITION_MAX_BYTES",
    "MAX_CONFLICTS",
    "FederationConflict",
    "FederationConflictSource",
    "FederationMerge",
    "FederationMergeCreate",
    "FederationMergeList",
    "FederationSetting",
    "FederationSettingUpdate",
    "FederationSourceRef",
    "bound_definition",
    "definition_in_spec",
    "with_existing_definitions",
]

MergeStatus = Literal["merged", "conflicted", "replaced"]
EntityKind = Literal["class", "path"]

#: Audit action written with each history row, by status.
AUDIT_BY_STATUS: Dict[str, str] = {
    "merged": "repository.federation_merged",
    "conflicted": "repository.federation_conflicted",
    "replaced": "repository.federation_replaced",
}

#: Audit action for switching a project's federation on or off.
AUDIT_TOGGLED = "repository.federation_toggled"

#: Most conflicts a history row keeps (the import's own message names the rest).
MAX_CONFLICTS = 50

#: A definition larger than this is stored as a marker instead of the value.
DEFINITION_MAX_BYTES = 20_000


class FederationSourceRef(BaseModel):
    """A repository file, as the history shows it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_full_name: str = Field(alias="repositoryFullName", min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    precedence: Optional[int] = Field(default=None, description="Merge order (1 contributed first).")


class FederationConflictSource(BaseModel):
    """One source's side of a conflict."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role: Literal["existing", "incoming"] = Field(
        description="`existing`: the contributing file that already defines it. `incoming`: the file imported."
    )
    repository_full_name: str = Field(alias="repositoryFullName", min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    definition: Any = Field(
        default=None,
        description=(
            "That source's definition of the class (its schema) or path (its path item); null when "
            "it could not be read. A definition over 20 KB is `{\"$truncated\": true, \"bytes\": n}`."
        ),
    )


class FederationConflict(BaseModel):
    """A class or path two contributing files both define."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: EntityKind
    key: str = Field(min_length=1, max_length=2048, description="The class name or pathname.")
    sources: List[FederationConflictSource] = Field(min_length=2, max_length=2)


class FederationMergeCreate(BaseModel):
    """What an import reports after federation acted on it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: MergeStatus
    version_id: Optional[str] = Field(default=None, alias="versionId", max_length=64)
    parent_version_id: Optional[str] = Field(default=None, alias="parentVersionId", max_length=64)
    repository_id: Optional[str] = Field(default=None, alias="repositoryId", max_length=64)
    repository_full_name: str = Field(alias="repositoryFullName", min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    source_count: int = Field(default=1, alias="sourceCount", ge=0, le=10_000)
    classes_carried: int = Field(default=0, alias="classesCarried", ge=0)
    paths_carried: int = Field(default=0, alias="pathsCarried", ge=0)
    removed_count: int = Field(default=0, alias="removedCount", ge=0)
    sources: List[FederationSourceRef] = Field(default_factory=list, max_length=500)
    conflicts: List[FederationConflict] = Field(default_factory=list, max_length=MAX_CONFLICTS)
    conflict_count: Optional[int] = Field(
        default=None,
        alias="conflictCount",
        ge=0,
        description="How many conflicts there were in all, when more than `conflicts` lists.",
    )


class FederationMerge(BaseModel):
    """One row of a project's merge history."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    project_name: Optional[str] = Field(default=None, alias="projectName")
    status: MergeStatus
    version_id: Optional[str] = Field(default=None, alias="versionId")
    version_label: Optional[str] = Field(default=None, alias="versionLabel")
    parent_version_id: Optional[str] = Field(default=None, alias="parentVersionId")
    repository_id: Optional[str] = Field(default=None, alias="repositoryId")
    repository_full_name: str = Field(alias="repositoryFullName")
    branch: str
    path: str
    source_count: int = Field(alias="sourceCount")
    classes_carried: int = Field(alias="classesCarried")
    paths_carried: int = Field(alias="pathsCarried")
    removed_count: int = Field(alias="removedCount")
    conflict_count: int = Field(alias="conflictCount")
    sources: List[FederationSourceRef] = Field(default_factory=list)
    conflicts: List[FederationConflict] = Field(default_factory=list)
    actor_id: Optional[str] = Field(default=None, alias="actorId")
    created_at: datetime = Field(alias="createdAt")


class FederationMergeList(BaseModel):
    """A page of merge history, newest first."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    merges: List[FederationMerge] = Field(default_factory=list)


class FederationSetting(BaseModel):
    """A project's federation switch."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(alias="projectId")
    enabled: bool = Field(
        description=(
            "True: each imported repository file is merged with the other contributing files. "
            "False: each import replaces the project's surface with the importing file alone."
        )
    )


class FederationSettingUpdate(BaseModel):
    """Body for switching federation on or off."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool


def definition_in_spec(spec: Optional[Mapping[str, Any]], kind: str, key: str) -> Any:
    """Find a class's schema or a path's path item in a rendered OpenAPI document.

    Args:
        spec: The document, or ``None``.
        kind: ``class`` or ``path``.
        key: The class name (a ``components.schemas`` key) or the pathname.

    Returns:
        The definition, or ``None`` when the document does not hold it.
    """
    if not isinstance(spec, Mapping):
        return None
    if kind == "path":
        paths = spec.get("paths")
        return paths.get(key) if isinstance(paths, Mapping) else None
    schemas = (spec.get("components") or {}).get("schemas") if isinstance(spec.get("components"), Mapping) else None
    return schemas.get(key) if isinstance(schemas, Mapping) else None


def bound_definition(value: Any, max_bytes: int = DEFINITION_MAX_BYTES) -> Any:
    """Keep a definition small enough to store on a history row.

    Args:
        value: The definition.
        max_bytes: The largest serialized size kept.

    Returns:
        The value, or ``{"$truncated": true, "bytes": n}`` when it serializes larger than
        ``max_bytes`` (or cannot be serialized at all).
    """
    if value is None:
        return None
    try:
        size = len(json.dumps(value, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return {"$truncated": True, "bytes": 0}
    if size > max_bytes:
        return {"$truncated": True, "bytes": size}
    return value


def with_existing_definitions(
    conflicts: List[FederationConflict], parent_spec: Optional[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Fill each conflict's ``existing`` side from the parent version, and bound every definition.

    The import knows the importing file's definitions; the contributing file's definition is what
    the parent version holds, read from its rendered spec here.

    Args:
        conflicts: The reported conflicts.
        parent_spec: The parent version's rendered OpenAPI document, or ``None``.

    Returns:
        The conflicts as stored (camelCase JSON), existing side first.
    """
    out: List[Dict[str, Any]] = []
    for conflict in conflicts:
        sides = []
        for source in sorted(conflict.sources, key=lambda s: 0 if s.role == "existing" else 1):
            definition = source.definition
            if source.role == "existing" and definition is None:
                definition = definition_in_spec(parent_spec, conflict.kind, conflict.key)
            side = source.model_dump(by_alias=True)
            side["definition"] = bound_definition(definition)
            sides.append(side)
        out.append({"kind": conflict.kind, "key": conflict.key, "sources": sides})
    return out
