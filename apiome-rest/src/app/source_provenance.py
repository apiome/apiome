"""Source provenance of a revision's elements — DCW-2.4 (private-suite#2365).

Pure (no DB, no network). Given the revision's canonical document now, the canonical document its
import produced (``apiome.version_import_snapshots``), and the pointers source applies changed since
(``apiome.version_source_edits``), :func:`classify_elements` says for every path, operation and
component whether it is:

* ``imported`` — present at import and unchanged since;
* ``source-edited`` — changed through a DCW-2.3 source apply (at the element or inside it) since
  the import, including an element a source apply created;
* ``local`` — otherwise: changed or created in Apiome's editors, or imported before snapshots
  existed (with no snapshot in its lineage, every element reads ``local`` except those a source
  apply changed, which are still ``source-edited``).

"Unchanged" compares canonical JSON produced by the same generator at both moments, so an import
normalizer's rewrites never read as edits.

:func:`locate_pointer` finds where a JSON Pointer's value sits in the original source text (YAML or
JSON — JSON parses as YAML), so a provenance read can quote a bounded excerpt of the import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

import yaml

__all__ = [
    "ElementProvenance",
    "ElementStatus",
    "EXCERPT_MAX_LINES",
    "classify_elements",
    "element_pointers",
    "escape_token",
    "excerpt",
    "locate_pointer",
    "resolve_pointer",
]

ElementStatus = Literal["imported", "local", "source-edited"]
ElementKind = Literal["path", "operation", "component"]

HTTP_METHODS: Tuple[str, ...] = ("get", "put", "post", "delete", "options", "head", "patch", "trace", "query")

#: The longest excerpt a provenance read quotes; a longer value is cut and says so.
EXCERPT_MAX_LINES = 40

_MISSING = object()


def escape_token(token: str) -> str:
    """Escape one RFC 6901 reference token (``~`` → ``~0``, ``/`` → ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _tokens(pointer: str) -> List[str]:
    return [_unescape(t) for t in pointer.split("/")[1:]] if pointer else []


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Return the value a pointer addresses, or the module's missing sentinel.

    Args:
        document: A parsed JSON value.
        pointer: RFC 6901 pointer (``''`` is the document).

    Returns:
        The value, or ``_MISSING`` when any token does not resolve.
    """
    value = document
    for token in _tokens(pointer):
        if isinstance(value, Mapping) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            return _MISSING
    return value


def element_pointers(document: Any) -> List[Tuple[str, ElementKind]]:
    """List the elements provenance is reported for: every path, operation and component.

    Args:
        document: A canonical OpenAPI document.

    Returns:
        ``(pointer, kind)`` pairs, paths each followed by their operations, then components by
        group and name.
    """
    out: List[Tuple[str, ElementKind]] = []
    paths = document.get("paths") if isinstance(document, Mapping) else None
    if isinstance(paths, Mapping):
        for path in sorted(paths):
            path_pointer = f"/paths/{escape_token(path)}"
            out.append((path_pointer, "path"))
            item = paths[path]
            if isinstance(item, Mapping):
                for method in HTTP_METHODS:
                    if isinstance(item.get(method), Mapping):
                        out.append((f"{path_pointer}/{method}", "operation"))
    components = document.get("components") if isinstance(document, Mapping) else None
    if isinstance(components, Mapping):
        for group in sorted(components):
            members = components[group]
            if isinstance(members, Mapping):
                for name in sorted(members):
                    out.append((f"/components/{escape_token(group)}/{escape_token(name)}", "component"))
    return out


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _touches(element: str, edited: str) -> bool:
    """Whether a source edit at ``edited`` changed ``element`` (it, inside it, or around it)."""
    return edited == element or edited.startswith(element + "/") or element.startswith(edited + "/") or edited == ""


@dataclass(frozen=True)
class ElementProvenance:
    """One element's provenance.

    Attributes:
        pointer: The element's pointer in the canonical document.
        kind: ``path``, ``operation`` or ``component``.
        status: ``imported``, ``local`` or ``source-edited``.
        in_import: Whether the element existed in the import snapshot.
    """

    pointer: str
    kind: ElementKind
    status: ElementStatus
    in_import: bool


def classify_elements(
    current: Mapping[str, Any],
    imported: Optional[Mapping[str, Any]],
    edited_pointers: Iterable[str],
) -> List[ElementProvenance]:
    """Classify every element of the current document — see the module docstring.

    Args:
        current: The revision's canonical document now.
        imported: The canonical document at import, or ``None`` when the lineage has no snapshot.
        edited_pointers: Pointers DCW-2.3 source applies changed since the import.

    Returns:
        One :class:`ElementProvenance` per element of ``current``, in :func:`element_pointers` order.
    """
    edits = list(edited_pointers)
    out: List[ElementProvenance] = []
    for pointer, kind in element_pointers(current):
        source_edited = any(_touches(pointer, e) for e in edits)
        before = resolve_pointer(imported, pointer) if imported is not None else _MISSING
        in_import = before is not _MISSING
        if in_import and _canonical(before) == _canonical(resolve_pointer(current, pointer)):
            status: ElementStatus = "imported"
        elif source_edited:
            status = "source-edited"
        else:
            status = "local"
        out.append(ElementProvenance(pointer=pointer, kind=kind, status=status, in_import=in_import))
    return out


def _node_at(root: yaml.Node, tokens: Sequence[str]) -> Optional[yaml.Node]:
    node: Optional[yaml.Node] = root
    for token in tokens:
        if isinstance(node, yaml.MappingNode):
            node = next((v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == token), None)
        elif isinstance(node, yaml.SequenceNode) and token.isdigit() and int(token) < len(node.value):
            node = node.value[int(token)]
        else:
            return None
        if node is None:
            return None
    return node


def _key_line(root: yaml.Node, tokens: Sequence[str]) -> Optional[int]:
    """The 0-based line of the mapping key that introduces the last token, if any."""
    if not tokens:
        return None
    parent = _node_at(root, tokens[:-1])
    if isinstance(parent, yaml.MappingNode):
        for key, _ in parent.value:
            if isinstance(key, yaml.ScalarNode) and key.value == tokens[-1]:
                return key.start_mark.line
    return None


def _last_line(node: yaml.Node) -> int:
    """The 0-based last line a node's content occupies.

    A block collection's end mark points at the *next* token (often the following sibling key), so
    its last line is its last child's; a flow collection (JSON's braces) ends at its closing mark;
    a block scalar's end mark sits at column 0 of the line after it.
    """
    if isinstance(node, yaml.ScalarNode):
        end = node.end_mark
        return end.line - 1 if end.column == 0 and end.line > node.start_mark.line else end.line
    if getattr(node, "flow_style", False) or not node.value:
        return node.end_mark.line if node.value else node.start_mark.line
    last = node.value[-1]
    return _last_line(last[1] if isinstance(node, yaml.MappingNode) else last)


def locate_pointer(text: str, pointer: str) -> Optional[Tuple[int, int]]:
    """Find the 1-based, inclusive line span of a pointer's value in source text.

    The span starts at the key that introduces the value (so an excerpt reads as the author wrote
    it) and ends at the value's last line.

    Args:
        text: YAML or JSON source.
        pointer: RFC 6901 pointer.

    Returns:
        ``(start_line, end_line)``, or ``None`` when the text does not parse or the pointer does not
        resolve in it.
    """
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    if root is None:
        return None
    tokens = _tokens(pointer)
    node = _node_at(root, tokens)
    if node is None:
        return None
    start = _key_line(root, tokens)
    start_line = (start if start is not None else node.start_mark.line) + 1
    return start_line, max(start_line, _last_line(node) + 1)


def excerpt(text: str, pointer: str, max_lines: int = EXCERPT_MAX_LINES) -> Optional[Dict[str, Any]]:
    """Quote the source lines behind a pointer.

    Args:
        text: The source text.
        pointer: RFC 6901 pointer.
        max_lines: The most lines to quote.

    Returns:
        ``{"startLine", "endLine", "text", "truncated"}`` (1-based lines), or ``None`` when the pointer
        cannot be located.
    """
    span = locate_pointer(text, pointer)
    if span is None:
        return None
    start, end = span
    lines = text.splitlines()
    last = min(end, start + max_lines - 1, len(lines))
    return {
        "startLine": start,
        "endLine": last,
        "text": "\n".join(lines[start - 1 : last]),
        "truncated": last < end,
    }
