"""Declared dependencies — CDG-3.2 (#5967).

A service can say what it depends on, in three places, each a **declaring source** with its own
``source_ref``:

==============================  =====================  ==================================================
Where                           ``source_ref``         Edge
==============================  =====================  ==================================================
``PUT …/dependencies``          ``manual``             ``depends_on`` (each entry)
``x-apiome-depends-on`` in the  ``spec``               ``depends_on``
spec it was imported from
A Backstage ``catalog-info``    ``backstage:<path>``   ``consumesApis`` → ``consumes``, ``dependsOn`` →
file in its repository                                 ``depends_on``; ``providesApis`` picks which of the
                                                       repository's APIs the component is
==============================  =====================  ==================================================

A reference that resolves to an entity becomes a ``declared`` edge in ``apiome.catalog_edges``
(apiome-db V288); one that resolves to nothing is kept in ``apiome.catalog_unresolved_dependencies``
(V289) on the declaring entity and shown by ``GET …/dependencies``, never dropped.

**Each source replaces its own rows.** :func:`replace_declared` upserts the source's edges, deletes
the source's edges it no longer names, and rewrites the source's unresolved rows, all in the caller's
transaction — so a re-import or a repeated PUT never duplicates anything, and removing a reference
removes it. Sources never touch each other's rows, nor the ``derived`` edges of
:mod:`app.catalog_graph`.

**The ``x-apiome-depends-on`` grammar.** A list (or one string, or a comma-separated string) of
``<slug>[#<pointer>]``, where ``<slug>`` names a project or catalog item in the tenant and the
optional ``<pointer>`` is a JSON pointer into it (``customers#/components/schemas/Customer``):

* OpenAPI, AsyncAPI, Avro ``.avsc`` and JSON Schema — a property at the document root;
* GraphQL — a line ``x-apiome-depends-on: payments, customers#/…`` in a description (usually the
  ``schema`` block's), since SDL has no root object to extend.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml

from .entity_owners import KINDS
from .revision_deprecation import is_uuid_string

__all__ = [
    "BACKSTAGE_FILENAMES",
    "BACKSTAGE_PREFIX",
    "EXTENSION_KEY",
    "MAX_DECLARED",
    "SOURCE_MANUAL",
    "SOURCE_SPEC",
    "BackstageEntity",
    "DeclaredReference",
    "DependencyValidationError",
    "backstage_entities",
    "backstage_name",
    "is_backstage_path",
    "parse_reference",
    "references_from_document",
    "replace_declared",
    "resolve_target",
]

#: The root extension a spec declares its dependencies with.
EXTENSION_KEY = "x-apiome-depends-on"

#: ``source_ref`` of dependencies written through the REST ``PUT``.
SOURCE_MANUAL = "manual"

#: ``source_ref`` of dependencies read from an imported spec.
SOURCE_SPEC = "spec"

#: ``source_ref`` prefix of dependencies read from a Backstage file (``backstage:<path>``).
BACKSTAGE_PREFIX = "backstage:"

#: The Backstage descriptor file names the repository scan recognizes.
BACKSTAGE_FILENAMES = ("catalog-info.yaml", "catalog-info.yml")

#: At most this many references per declaring source; the rest are ignored.
MAX_DECLARED = 200

#: Longest reference and note kept.
_MAX_REFERENCE = 512
_MAX_NOTE = 500

#: Kinds whose rows live in ``apiome.projects`` and resolve by slug.
_PROJECT_KINDS = ("project", "catalog_item")

#: A GraphQL description line declaring dependencies. The schema printer folds a one-line
#: description onto its quotes (``"""x-apiome-depends-on: a"""``), so the quotes are optional.
_SDL_LINE = re.compile(
    r'^\s*(?:"{1,3})?\s*x-apiome-depends-on\s*:\s*(.+?)\s*(?:"{1,3})?\s*$', re.IGNORECASE | re.MULTILINE
)


class DependencyValidationError(ValueError):
    """A malformed declaration, with a stable code (``graph-invalid`` or ``graph-entity-not-found``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeclaredReference:
    """One reference a source declares.

    Attributes:
        reference: The reference as written, for display (``payments``, ``api:default/payments``).
        edge_kind: ``depends_on`` or ``consumes``.
        slug: The project or catalog-item slug it names, when it names one by slug.
        kind: The target's node kind, when it names one by id.
        entity_id: The target's id, when it names one by id.
        pointer: A JSON pointer into the target, or ``None``.
        note: Free text from the declarer, or ``None``.
    """

    reference: str
    edge_kind: str = "depends_on"
    slug: Optional[str] = None
    kind: Optional[str] = None
    entity_id: Optional[str] = None
    pointer: Optional[str] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Reading declarations
# ---------------------------------------------------------------------------------------------


def parse_reference(text: str, *, edge_kind: str = "depends_on") -> Optional[DeclaredReference]:
    """Parse ``<slug>[#<pointer>]``.

    Args:
        text: The reference.
        edge_kind: The edge it would become.

    Returns:
        The reference, or ``None`` for an empty one.
    """
    raw = str(text or "").strip()[:_MAX_REFERENCE]
    if not raw:
        return None
    name, _, fragment = raw.partition("#")
    pointer = fragment.strip() or None
    if pointer is not None and not pointer.startswith("/"):
        pointer = "/" + pointer
    return DeclaredReference(reference=raw, edge_kind=edge_kind, slug=name.strip().lower() or None, pointer=pointer)


def _split(value: Any) -> List[str]:
    """A declaration value as a list of strings: a list, one string, or a comma-separated string."""
    if isinstance(value, str):
        return [part for part in (piece.strip() for piece in value.split(",")) if part]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if isinstance(item, (str, int)) and str(item).strip()]
    return []


def _root(document: Any) -> Any:
    """Unwrap the import pipeline's per-format ``model.raw`` to the document a user wrote.

    JSON Schema arrives as ``{"source": <doc>}``, Avro as ``{"avro": <text>}`` (re-parsed when it
    is ``.avsc`` JSON; Avro IDL has no root and yields ``None``), GraphQL as ``{"sdl": <text>}``
    (returned as the SDL string). Anything else is returned as is.
    """
    if isinstance(document, Mapping):
        if set(document) == {"source"} and isinstance(document.get("source"), Mapping):
            return document["source"]
        avro = document.get("avro")
        if isinstance(avro, str) and EXTENSION_KEY not in document:
            try:
                parsed = json.loads(avro)
            except ValueError:
                return None
            return parsed if isinstance(parsed, Mapping) else None
        sdl = document.get("sdl")
        if isinstance(sdl, str) and EXTENSION_KEY not in document:
            return sdl
    return document


def references_from_document(document: Any) -> List[DeclaredReference]:
    """The ``x-apiome-depends-on`` references an imported document declares (module docstring).

    Args:
        document: The parsed source (``model.raw``), a raw document dict, or GraphQL SDL text.

    Returns:
        The distinct references, in the order written, at most :data:`MAX_DECLARED`.
    """
    root = _root(document)
    values: List[str] = []
    if isinstance(root, Mapping):
        values = _split(root.get(EXTENSION_KEY))
    elif isinstance(root, str):
        for match in _SDL_LINE.finditer(root):
            values.extend(_split(match.group(1).strip().strip('"')))
    return _distinct(parse_reference(value) for value in values)


def _distinct(references: Iterable[Optional[DeclaredReference]]) -> List[DeclaredReference]:
    """Drop empties and repeats (same target, pointer and edge kind), keeping the first."""
    seen = set()
    kept: List[DeclaredReference] = []
    for ref in references:
        if ref is None:
            continue
        key = (ref.slug, ref.kind, ref.entity_id, ref.pointer, ref.edge_kind)
        if key in seen:
            continue
        seen.add(key)
        kept.append(ref)
        if len(kept) >= MAX_DECLARED:
            break
    return kept


# ---------------------------------------------------------------------------------------------
# Backstage
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BackstageEntity:
    """The relations one ``catalog-info`` entity declares.

    Attributes:
        name: ``metadata.name``.
        provides: ``spec.providesApis`` names (the APIs this component is).
        references: ``spec.consumesApis`` (as ``consumes``) and ``spec.dependsOn`` (as ``depends_on``).
    """

    name: Optional[str]
    provides: Tuple[str, ...]
    references: Tuple[DeclaredReference, ...]


def is_backstage_path(path: str) -> bool:
    """Whether a repository path is a Backstage descriptor (``catalog-info.yaml`` at any depth)."""
    return str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower() in BACKSTAGE_FILENAMES


def backstage_name(entity_ref: str) -> Optional[str]:
    """The name in a Backstage entity reference ``[<kind>:][<namespace>/]<name>``, lowercased."""
    raw = str(entity_ref or "").strip()
    if not raw:
        return None
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    name = raw.rsplit("/", 1)[-1].strip().lower()
    return name or None


def backstage_entities(text: str) -> List[BackstageEntity]:
    """Parse a ``catalog-info.yaml`` (one or more YAML documents) into its entities' relations.

    Args:
        text: The file's text.

    Returns:
        One :class:`BackstageEntity` per document with a ``spec`` mapping; malformed YAML yields
        an empty list.
    """
    try:
        documents = list(yaml.safe_load_all(text or ""))
    except yaml.YAMLError:
        return []
    entities: List[BackstageEntity] = []
    for doc in documents:
        if not isinstance(doc, Mapping) or not isinstance(doc.get("spec"), Mapping):
            continue
        spec = doc["spec"]
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), Mapping) else {}
        references: List[Optional[DeclaredReference]] = []
        for key, edge_kind in (("consumesApis", "consumes"), ("dependsOn", "depends_on")):
            for value in _split(spec.get(key)):
                name = backstage_name(value)
                references.append(
                    DeclaredReference(reference=value[:_MAX_REFERENCE], edge_kind=edge_kind, slug=name)
                    if name
                    else None
                )
        provides = tuple(name for name in (backstage_name(v) for v in _split(spec.get("providesApis"))) if name)
        entities.append(
            BackstageEntity(
                name=backstage_name(str(metadata.get("name") or "")),
                provides=provides,
                references=tuple(_distinct(references)),
            )
        )
    return entities


# ---------------------------------------------------------------------------------------------
# Resolving and writing
# ---------------------------------------------------------------------------------------------


def resolve_target(cursor: Any, tenant_id: str, ref: DeclaredReference) -> Optional[Tuple[str, str]]:
    """The live entity a reference names, as ``(node kind, id)``, or ``None``.

    A slug names a project or catalog item (its kind follows ``publishable``). An id names an
    entity of ``ref.kind``; for a projects row the actual kind is returned whichever was asked.

    Args:
        cursor: An open cursor.
        tenant_id: The tenant.
        ref: The reference.

    Returns:
        ``(kind, id)`` or ``None``.
    """
    if ref.entity_id:
        spec = KINDS.get(ref.kind or "")
        if spec is None or not is_uuid_string(ref.entity_id):
            return None
        if ref.kind in _PROJECT_KINDS:
            cursor.execute(
                "SELECT id::text AS id, publishable FROM apiome.projects "
                "WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL",
                (ref.entity_id, tenant_id),
            )
        else:
            cursor.execute(
                f"SELECT e.id::text AS id FROM {spec.table} e "
                f"WHERE e.id = %s::uuid AND e.tenant_id = %s::uuid AND {spec.where}",
                (ref.entity_id, tenant_id),
            )
    elif ref.slug:
        cursor.execute(
            "SELECT id::text AS id, publishable FROM apiome.projects "
            "WHERE lower(slug) = %s AND tenant_id = %s::uuid AND deleted_at IS NULL",
            (ref.slug.lower(), tenant_id),
        )
    else:
        return None
    row = cursor.fetchone()
    if not row:
        return None
    if "publishable" in row:
        return ("project" if row["publishable"] else "catalog_item", str(row["id"]))
    return (str(ref.kind), str(row["id"]))


def replace_declared(
    cursor: Any,
    tenant_id: str,
    from_kind: str,
    from_id: str,
    source_ref: str,
    references: Sequence[DeclaredReference],
) -> Dict[str, int]:
    """Make one declaring source's rows for one entity exactly ``references`` (module docstring).

    Runs on the caller's transaction and commits nothing.

    Args:
        cursor: An open cursor.
        tenant_id: The tenant.
        from_kind: The declaring entity's node kind.
        from_id: The declaring entity.
        source_ref: The declaring source (``manual``, ``spec``, ``backstage:<path>``).
        references: What the source declares now.

    Returns:
        ``{"declared": edges kept, "removed": edges deleted, "unresolved": unresolved rows}``.
    """
    kept_ids: List[str] = []
    unresolved: List[Tuple[DeclaredReference, str]] = []
    for ref in references[:MAX_DECLARED]:
        target = resolve_target(cursor, tenant_id, ref)
        if target is None:
            unresolved.append((ref, "not-found"))
            continue
        if target[1] == str(from_id):
            unresolved.append((ref, "self"))
            continue
        evidence = {"reference": ref.reference}
        if ref.note:
            evidence["note"] = ref.note[:_MAX_NOTE]
        cursor.execute(
            """
            INSERT INTO apiome.catalog_edges
                (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance,
                 source_ref, evidence)
            VALUES (%s::uuid, %s, %s::uuid, %s, %s::uuid, %s, %s, 'declared', %s, %s::jsonb)
            ON CONFLICT ON CONSTRAINT catalog_edges_identity_key DO UPDATE
               SET last_seen_at = CURRENT_TIMESTAMP, stale_since = NULL, evidence = EXCLUDED.evidence
            RETURNING id::text AS id
            """,
            (tenant_id, from_kind, from_id, target[0], target[1], ref.edge_kind, ref.pointer, source_ref,
             json.dumps(evidence)),
        )
        kept_ids.append(str(cursor.fetchone()["id"]))
    # The source's edges it no longer names. Matched on the declaring id alone, so a catalog item
    # converted into a project (same row, new kind) still replaces its own declarations.
    cursor.execute(
        """
        DELETE FROM apiome.catalog_edges
         WHERE tenant_id = %s::uuid AND from_id = %s::uuid AND provenance = 'declared'
           AND source_ref = %s AND NOT (id = ANY(%s::uuid[]))
        """,
        (tenant_id, from_id, source_ref, kept_ids),
    )
    removed = int(cursor.rowcount or 0)
    cursor.execute(
        "DELETE FROM apiome.catalog_unresolved_dependencies "
        "WHERE tenant_id = %s::uuid AND from_id = %s::uuid AND source_ref = %s",
        (tenant_id, from_id, source_ref),
    )
    for ref, reason in unresolved:
        cursor.execute(
            """
            INSERT INTO apiome.catalog_unresolved_dependencies
                (tenant_id, from_kind, from_id, source_ref, reference, pointer, edge_kind, reason, note)
            VALUES (%s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT catalog_unresolved_dependencies_identity_key DO NOTHING
            """,
            (tenant_id, from_kind, from_id, source_ref, ref.reference, ref.pointer, ref.edge_kind, reason,
             ref.note[:_MAX_NOTE] if ref.note else None),
        )
    return {"declared": len(kept_ids), "removed": removed, "unresolved": len(unresolved)}
