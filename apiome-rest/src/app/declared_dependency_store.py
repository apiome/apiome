"""Declared dependencies — the database side (CDG-3.2, #5967).

Each function runs one transaction over :func:`app.declared_dependencies.replace_declared`:

* :func:`put_dependencies` — the REST ``PUT`` (source ``manual``), audited as
  ``graph.dependencies.update``;
* :func:`read_dependencies` — every declared edge an entity has, from any source, and its
  unresolved references;
* :func:`record_spec_dependencies` — an import's ``x-apiome-depends-on`` (source ``spec``);
* :func:`record_backstage_dependencies` — a repository scan's ``catalog-info`` files
  (sources ``backstage:<path>``).

The import and scan writers are best-effort: they log and return on any fault, because the import
or scan itself already succeeded.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .catalog_graph import MAX_READ_LIMIT, list_edges
from .consumer_contract_store import ConsumerActor
from .database import db
from .declared_dependencies import (
    BACKSTAGE_PREFIX,
    MAX_DECLARED,
    SOURCE_MANUAL,
    SOURCE_SPEC,
    DeclaredReference,
    DependencyValidationError,
    backstage_entities,
    references_from_document,
    replace_declared,
    resolve_target,
)
from .entity_owners import KINDS

__all__ = [
    "put_dependencies",
    "read_dependencies",
    "record_backstage_dependencies",
    "record_spec_dependencies",
    "resolve_entity",
]

_logger = logging.getLogger(__name__)


def resolve_entity(cursor: Any, tenant_id: str, kind: str, entity: str) -> Tuple[str, str]:
    """The live declaring entity a URL names: ``(node kind, id)``.

    Args:
        cursor: An open cursor.
        tenant_id: The tenant.
        kind: A kind from :data:`app.entity_owners.KINDS`.
        entity: Its id, or — for a project or catalog item — its slug.

    Raises:
        DependencyValidationError: ``graph-invalid`` for an unknown kind;
            ``graph-entity-not-found`` when no live entity matches.
    """
    if kind not in KINDS:
        raise DependencyValidationError("graph-invalid", f"unknown entity kind '{kind}'; use one of {', '.join(KINDS)}")
    from .revision_deprecation import is_uuid_string

    if is_uuid_string(entity or ""):
        ref = DeclaredReference(reference=entity, kind=kind, entity_id=entity)
    elif kind in ("project", "catalog_item"):
        ref = DeclaredReference(reference=entity, slug=str(entity or "").lower())
    else:
        ref = None
    found = resolve_target(cursor, tenant_id, ref) if ref else None
    if found is None:
        raise DependencyValidationError("graph-entity-not-found", f"no {kind} '{entity}' in this tenant")
    return found


def _unresolved_rows(cursor: Any, tenant_id: str, entity_id: str) -> List[Dict[str, Any]]:
    """An entity's unresolved references, every source, in a stable order."""
    cursor.execute(
        """
        SELECT source_ref, reference, pointer, edge_kind, reason, note, created_at
        FROM apiome.catalog_unresolved_dependencies
        WHERE tenant_id = %s::uuid AND from_id = %s::uuid
        ORDER BY source_ref, reference, pointer NULLS FIRST
        """,
        (tenant_id, entity_id),
    )
    rows = []
    for row in cursor.fetchall():
        item = dict(row)
        created = item.get("created_at")
        item["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
        rows.append(item)
    return rows


def read_dependencies(tenant_id: str, kind: str, entity: str) -> Dict[str, Any]:
    """Everything an entity declares it depends on.

    Args:
        tenant_id: The tenant.
        kind: The entity's kind.
        entity: Its id (or a project/catalog-item slug).

    Returns:
        ``{kind, entity_id, declared: [edge], unresolved: [row], truncated}`` — declared edges are
        the entity's outgoing ``declared`` edges from every source, at most 500.

    Raises:
        DependencyValidationError: see :func:`resolve_entity`.
    """

    def work(cursor: Any) -> Dict[str, Any]:
        found_kind, entity_id = resolve_entity(cursor, tenant_id, kind, entity)
        unresolved = _unresolved_rows(cursor, tenant_id, entity_id)
        return {"kind": found_kind, "entity_id": entity_id, "unresolved": unresolved}

    result = db._guarded_tx(work)
    page = list_edges(
        db, tenant_id, result["kind"], result["entity_id"], provenances=("declared",), limit=MAX_READ_LIMIT
    )
    return {**result, "declared": page.edges, "truncated": page.truncated}


def _manual_reference(item: Mapping[str, Any]) -> DeclaredReference:
    """One ``PUT`` entry ``{to: {kind, id | slug}, pointer?, note?}`` as a reference.

    Raises:
        DependencyValidationError: ``graph-invalid`` for a malformed entry.
    """
    to = item.get("to") if isinstance(item.get("to"), Mapping) else {}
    kind = str(to.get("kind") or "").strip() or None
    target_id = str(to.get("id") or "").strip() or None
    slug = str(to.get("slug") or "").strip().lower() or None
    pointer = str(item.get("pointer") or "").strip() or None
    note = str(item.get("note") or "").strip() or None
    if bool(target_id) == bool(slug):
        raise DependencyValidationError(
            "graph-invalid", "each dependency names its target by exactly one of id or slug"
        )
    if target_id and kind not in KINDS:
        raise DependencyValidationError("graph-invalid", f"a target by id needs a kind: one of {', '.join(KINDS)}")
    if slug and kind not in (None, "project", "catalog_item"):
        raise DependencyValidationError("graph-invalid", "only a project or catalog item can be named by slug")
    if pointer and not pointer.startswith("/"):
        raise DependencyValidationError(
            "graph-invalid", f"pointer '{pointer}' must be a JSON pointer starting with '/'"
        )
    if note and len(note) > 500:
        raise DependencyValidationError("graph-invalid", "a note is at most 500 characters")
    reference = slug or f"{kind}:{target_id}"
    if pointer:
        reference = f"{reference}#{pointer}"
    return DeclaredReference(
        reference=reference, kind=kind, entity_id=target_id, slug=slug, pointer=pointer, note=note
    )


def put_dependencies(
    tenant_id: str, kind: str, entity: str, items: Sequence[Mapping[str, Any]], *, actor: Optional[ConsumerActor]
) -> Dict[str, Any]:
    """Replace an entity's ``manual`` dependencies with ``items`` (an empty list clears them).

    Spec and Backstage declarations are left alone. Audited as ``graph.dependencies.update`` in the
    same transaction.

    Args:
        tenant_id: The tenant.
        kind: The declaring entity's kind.
        entity: Its id (or a project/catalog-item slug).
        items: ``[{to: {kind?, id | slug}, pointer?, note?}]``, at most :data:`MAX_DECLARED`.
        actor: Who changed them.

    Returns:
        :func:`read_dependencies` after the change.

    Raises:
        DependencyValidationError: ``graph-invalid`` or ``graph-entity-not-found``.
    """
    if len(items) > MAX_DECLARED:
        raise DependencyValidationError("graph-invalid", f"at most {MAX_DECLARED} dependencies")
    references = [_manual_reference(item) for item in items]

    def work(cursor: Any) -> Tuple[str, str]:
        found_kind, entity_id = resolve_entity(cursor, tenant_id, kind, entity)
        counts = replace_declared(cursor, tenant_id, found_kind, entity_id, SOURCE_MANUAL, references)
        db._append_access_audit(
            cursor,
            tenant_id=tenant_id,
            action="graph.dependencies.update",
            actor_id=actor.user_id if actor else None,
            actor_label=actor.label if actor else None,
            target=f"{found_kind}:{entity_id}",
            source="api_key" if actor and actor.kind == "api_key" else "web",
            detail={"kind": found_kind, "entity_id": entity_id, **counts},
        )
        return found_kind, entity_id

    found_kind, entity_id = db._guarded_tx(work)
    return read_dependencies(tenant_id, found_kind, entity_id)


def record_spec_dependencies(tenant_id: str, kind: str, project_id: str, document: Any) -> Optional[Dict[str, int]]:
    """Store an import's ``x-apiome-depends-on`` as the entity's ``spec`` declarations, never raising.

    A document without the extension clears what the previous import declared.

    Args:
        tenant_id: The importing tenant.
        kind: ``project`` or ``catalog_item``.
        project_id: The row the import wrote.
        document: The parsed source (``model.raw``) or the raw document.

    Returns:
        The counts, or ``None`` when it failed (logged).
    """
    try:
        references = references_from_document(document)
        return db._guarded_tx(
            lambda cursor: replace_declared(cursor, tenant_id, kind, project_id, SOURCE_SPEC, references)
        )
    except Exception as exc:  # noqa: BLE001 - declarations must not fail a finished import
        _logger.warning(
            "declared dependencies from the document failed project_id=%s error=%s",
            project_id,
            f"{type(exc).__name__}: {exc}"[:300],
        )
        return None


def _repository_projects(cursor: Any, tenant_id: str, repository_id: str, branch: str) -> List[Dict[str, Any]]:
    """The live projects and catalog items imported from a repository branch."""
    cursor.execute(
        """
        SELECT DISTINCT p.id::text AS id, lower(p.slug) AS slug, p.publishable
        FROM apiome.repository_import_spec s
        JOIN apiome.projects p ON p.id = s.project_id AND p.deleted_at IS NULL
        WHERE s.tenant_id = %s::uuid AND s.repository_id = %s::uuid AND s.branch = %s
        ORDER BY 1
        """,
        (tenant_id, repository_id, branch),
    )
    return [dict(row) for row in cursor.fetchall()]


def record_backstage_dependencies(
    tenant_id: str, repository_id: str, branch: str, files: Mapping[str, str]
) -> Optional[Dict[str, int]]:
    """Store a repository branch's Backstage declarations on the APIs imported from it, never raising.

    For each ``catalog-info`` file (``{path: text}``) and each entity in it, the declaring APIs are
    the repository's projects whose slug the entity's ``providesApis`` names — or, when it names
    none of them, every project imported from the branch. ``consumesApis`` become ``consumes`` and
    ``dependsOn`` ``depends_on`` declarations with source ``backstage:<path>``. Declarations from a
    ``catalog-info`` file that is no longer in ``files`` are removed.

    Args:
        tenant_id: The repository's tenant.
        repository_id: The repository.
        branch: The scanned branch.
        files: Every Backstage file on the branch, with its text.

    Returns:
        ``{"entities": declaring APIs written, "declared": edges, "unresolved": rows}``, or ``None``
        when it failed (logged).
    """

    def work(cursor: Any) -> Dict[str, int]:
        projects = _repository_projects(cursor, tenant_id, repository_id, branch)
        totals = {"entities": 0, "declared": 0, "unresolved": 0}
        if not projects:
            return totals
        by_slug = {row["slug"]: row for row in projects}
        sources = {f"{BACKSTAGE_PREFIX}{path}" for path in files}
        for row in projects:
            kind = "project" if row["publishable"] else "catalog_item"
            for path, text in sorted(files.items()):
                references: List[DeclaredReference] = []
                for entity in backstage_entities(text):
                    provided = [name for name in entity.provides if name in by_slug]
                    if provided and row["slug"] not in provided:
                        continue
                    references.extend(entity.references)
                counts = replace_declared(cursor, tenant_id, kind, row["id"], f"{BACKSTAGE_PREFIX}{path}", references)
                if references:
                    totals["entities"] += 1
                totals["declared"] += counts["declared"]
                totals["unresolved"] += counts["unresolved"]
            # Declarations from Backstage files that are gone.
            cursor.execute(
                """
                DELETE FROM apiome.catalog_edges
                 WHERE tenant_id = %s::uuid AND from_id = %s::uuid AND provenance = 'declared'
                   AND source_ref LIKE 'backstage:%%' AND NOT (source_ref = ANY(%s::text[]))
                """,
                (tenant_id, row["id"], sorted(sources)),
            )
            cursor.execute(
                """
                DELETE FROM apiome.catalog_unresolved_dependencies
                 WHERE tenant_id = %s::uuid AND from_id = %s::uuid
                   AND source_ref LIKE 'backstage:%%' AND NOT (source_ref = ANY(%s::text[]))
                """,
                (tenant_id, row["id"], sorted(sources)),
            )
        return totals

    try:
        return db._guarded_tx(work)
    except Exception as exc:  # noqa: BLE001 - declarations must not fail a finished scan
        _logger.warning(
            "Backstage declarations skipped repository_id=%s branch=%s error=%s",
            repository_id,
            branch,
            f"{type(exc).__name__}: {exc}"[:300],
        )
        return None
