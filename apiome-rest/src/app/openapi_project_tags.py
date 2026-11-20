"""A project's OpenAPI tag list, with the OpenAPI 3.2 hierarchy (COA-2.5, #7048).

An OpenAPI import keeps the document's Tag Objects on the project's metadata under
``x-apiome-tag-taxonomy`` (OA5, #3502): ``{"version": 1, "tags": [{name, summary, description,
parent, kind, externalDocs}, …]}``. This module is the one place that reads, checks and writes that
list, and turns it into the generated document's top-level ``tags``:

* :func:`read_stored_tags` reads the list from project metadata;
* :func:`validate_tags` checks a list before it is stored (unique names, a ``parent`` that names
  another listed tag, no ``parent`` cycles);
* :func:`stored_taxonomy` is the form written back to project metadata;
* :func:`build_document_tags` writes the Tag Objects for a target version — ``summary``,
  ``parent`` and ``kind`` only for OpenAPI 3.2, which is the version that has them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Project-metadata key the tag list is kept under (shared with apiome-ui's import, OA5).
TAG_TAXONOMY_METADATA_KEY = "x-apiome-tag-taxonomy"

#: Version of the stored ``{"version", "tags"}`` shape.
TAG_TAXONOMY_FORMAT_VERSION = 1

#: The Tag Object fields a stored tag may carry.
TAG_FIELDS = ("name", "summary", "description", "parent", "kind", "externalDocs")


def _text(value: Any) -> Optional[str]:
    """A trimmed non-empty string, or ``None``."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_tag(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep a tag's Tag Object fields, trimmed, dropping empty ones.

    Args:
        raw: A tag as sent or stored.

    Returns:
        The tag with only ``name`` / ``summary`` / ``description`` / ``parent`` / ``kind`` /
        ``externalDocs`` (``{url, description?}``); ``name`` may be missing when it was blank.
    """
    tag: Dict[str, Any] = {}
    for key in ("name", "summary", "description", "parent", "kind"):
        value = _text(raw.get(key))
        if value is not None:
            tag[key] = value
    docs = raw.get("externalDocs")
    if isinstance(docs, Mapping) and _text(docs.get("url")):
        tag["externalDocs"] = {"url": _text(docs.get("url"))}
        if _text(docs.get("description")):
            tag["externalDocs"]["description"] = _text(docs.get("description"))
    return tag


def read_stored_tags(project_metadata: Any) -> List[Dict[str, Any]]:
    """Read the stored tag list.

    Args:
        project_metadata: ``apiome.projects.metadata`` (a dict; anything else reads as empty).

    Returns:
        The stored tags with a name, in stored order.
    """
    if not isinstance(project_metadata, Mapping):
        return []
    taxonomy = project_metadata.get(TAG_TAXONOMY_METADATA_KEY)
    if not isinstance(taxonomy, Mapping) or not isinstance(taxonomy.get("tags"), list):
        return []
    tags = [normalize_tag(t) for t in taxonomy["tags"] if isinstance(t, Mapping)]
    return [t for t in tags if t.get("name")]


def validate_tags(tags: Sequence[Mapping[str, Any]]) -> List[str]:
    """Check a tag list before it is stored.

    Args:
        tags: The tags, already normalized by :func:`normalize_tag`.

    Returns:
        One message per problem — a missing or repeated name, a ``parent`` that is the tag itself
        or names no listed tag, a ``parent`` cycle — empty when the list is valid.
    """
    errors: List[str] = []
    names: List[str] = []
    for index, tag in enumerate(tags):
        name = tag.get("name")
        if not name:
            errors.append(f"tags[{index}]: name is required")
            continue
        if name in names:
            errors.append(f"tags[{index}]: the tag {name!r} is listed more than once")
        names.append(name)
    known = set(names)
    # A repeated name is already reported; its first declaration is the one checked.
    parents: Dict[str, Optional[str]] = {}
    for tag in tags:
        if tag.get("name") and tag["name"] not in parents:
            parents[tag["name"]] = tag.get("parent")
    for name, parent in parents.items():
        if parent is None:
            continue
        if parent == name:
            errors.append(f"tag {name!r}: parent cannot be the tag itself")
        elif parent not in known:
            errors.append(f"tag {name!r}: parent {parent!r} is not a listed tag")
    errors.extend(_parent_cycle_errors(parents))
    return errors


def _parent_cycle_errors(parents: Mapping[str, Optional[str]]) -> List[str]:
    """One message per ``parent`` cycle of two or more tags (a self-parent is reported apart).

    Args:
        parents: Tag name → its ``parent`` (or ``None``).

    Returns:
        ``tags a → b → a form a parent cycle`` for each distinct cycle, in first-found order.
    """
    errors: List[str] = []
    reported: set = set()
    for start in parents:
        path: List[str] = []
        current: Optional[str] = start
        while current is not None and current in parents and current not in path:
            path.append(current)
            current = parents[current]
        if current is None or current not in path:
            continue
        cycle = path[path.index(current):]
        key = frozenset(cycle)
        if len(cycle) < 2 or key in reported:
            continue
        reported.add(key)
        errors.append("tags " + " → ".join(cycle + [current]) + " form a parent cycle")
    return errors


def stored_taxonomy(tags: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The value written to project metadata under :data:`TAG_TAXONOMY_METADATA_KEY`.

    Args:
        tags: Valid, normalized tags.

    Returns:
        ``{"version": 1, "tags": [...]}``.
    """
    return {"version": TAG_TAXONOMY_FORMAT_VERSION, "tags": [dict(t) for t in tags]}


def build_document_tags(tags: Sequence[Mapping[str, Any]], is32: bool) -> List[Dict[str, Any]]:
    """The document's top-level ``tags`` for a target version.

    OpenAPI 3.2 writes ``summary``, ``parent`` and ``kind``; any other version writes only
    ``name``, ``description`` and ``externalDocs``. A ``parent`` naming no listed tag is not written.

    Args:
        tags: The stored tags.
        is32: Whether the target is OpenAPI 3.2.

    Returns:
        The Tag Objects, in stored order.
    """
    names = {t.get("name") for t in tags}
    out: List[Dict[str, Any]] = []
    for tag in tags:
        obj: Dict[str, Any] = {"name": tag["name"]}
        if is32 and tag.get("summary"):
            obj["summary"] = tag["summary"]
        if tag.get("description"):
            obj["description"] = tag["description"]
        parent = tag.get("parent")
        if is32 and parent and parent != tag["name"] and parent in names:
            obj["parent"] = parent
        if is32 and tag.get("kind"):
            obj["kind"] = tag["kind"]
        if tag.get("externalDocs"):
            obj["externalDocs"] = dict(tag["externalDocs"])
        out.append(obj)
    return out
