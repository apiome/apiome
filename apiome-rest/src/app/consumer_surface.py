"""Resolve a declared consumer surface against a stored specification — CTG-4.1 (#4479).

A consumer says "I call ``GET /pets`` and I read ``items.name``". A registry that stored those
words would be a wish list. This module turns them into **JSON Pointers into the project's actual
specification**, written in exactly the vocabulary :mod:`app.change_taxonomy_enum` emits, so that
CTG-4.2 can intersect a classified change with a declared surface by comparing pointers rather
than by re-deriving what a change touched.

Three jobs, one index
---------------------
:class:`SpecIndex` wraps one OpenAPI document and answers all three:

* **What can be declared?** :meth:`SpecIndex.available_surface` enumerates every operation and
  every addressable field — the UI picker's catalogue.
* **Which operation is this?** :meth:`SpecIndex.match_operation` maps a method plus a *concrete*
  path (``/pets/42``, which is what a Pact interaction records) onto the specification's path
  template (``/pets/{petId}``), including through a server base path.
* **Where does this field live?** :meth:`SpecIndex.resolve_field` walks a dotted data path into
  a request or response schema and returns the two pointers a contract stores.

Why two pointers per field
--------------------------
The classifier reports an inline schema change under ``/paths/…/responses/200/content/…/schema``
and a component change under ``/components/schemas/Pet``. Which one it emits depends on how the
author wrote the document, not on what the consumer uses. So every resolved field carries the
**operation-anchored** pointer (its identity inside the contract) and the **resolved** pointer
(where the node actually lives). Storing one without the other would make half of the relevant
changes invisible to the intersection.

Bounded by construction
-----------------------
Specifications contain recursive schemas and 40-level object graphs. Enumeration stops at
:data:`MAX_FIELD_DEPTH` levels and :data:`MAX_FIELDS_PER_OPERATION` fields per operation, and
every ``$ref`` walk carries the set of pointers it has already visited, so a self-referential
schema terminates instead of exhausting the stack. Resolution of an *explicitly named* path is
bounded the same way but by the path's own length, so a consumer can always name a field the
enumeration truncated away.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from .change_taxonomy_enum import json_pointer_escape, json_pointer_join
from .consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractSurface,
    SurfaceSelection,
    UnresolvedInteraction,
    is_http_method,
    normalize_method,
    sort_operations,
)

__all__ = [
    "MAX_FIELDS_PER_OPERATION",
    "MAX_FIELD_DEPTH",
    "AvailableField",
    "AvailableOperation",
    "AvailableSurface",
    "SpecIndex",
    "operation_pointer",
    "resolve_selection",
]

#: How deep the field enumeration walks before it stops describing a schema.
MAX_FIELD_DEPTH = 5

#: How many fields one operation may contribute to the picker's catalogue.
MAX_FIELDS_PER_OPERATION = 300

#: Media types whose bodies this module walks as JSON. A body offered only as XML or as an
#: opaque binary has no addressable fields here, and says so rather than pretending otherwise.
_JSON_MEDIA_HINTS = ("json",)

#: Schema composition keywords whose branches are walked as if their members were inline.
_COMPOSITION_KEYWORDS = ("allOf", "oneOf", "anyOf")


def operation_pointer(path: str, method: str) -> str:
    """The classifier's own pointer for an operation.

    Args:
        path: The specification's path template.
        method: Lowercase HTTP method.

    Returns:
        ``/paths/<escaped path>/<method>`` — byte-identical to what
        :mod:`app.change_taxonomy_enum` emits for the same operation.
    """
    return f"{json_pointer_join('paths', path)}/{json_pointer_escape(method)}"


@dataclass(frozen=True)
class AvailableField:
    """One field a consumer *could* declare, as the picker offers it.

    Attributes:
        pointer: Operation-anchored JSON Pointer.
        schema_pointer: Where the node actually lives (a ``$ref`` target, or the same pointer).
        location: ``response``, ``request``, or ``parameter``.
        status: Response status code, for a response field.
        media_type: Media type, for a body field.
        path: Dotted data path, or the parameter name.
        type_name: The schema's declared ``type``, when it has one — shown beside the checkbox.
        required: Whether the specification marks the field required at its own level.
    """

    pointer: str
    schema_pointer: str
    location: str
    path: str
    status: Optional[str] = None
    media_type: Optional[str] = None
    type_name: Optional[str] = None
    required: bool = False


@dataclass(frozen=True)
class AvailableOperation:
    """One operation a consumer could declare, with its addressable fields.

    Attributes:
        method: Lowercase HTTP method.
        path: The specification's path template.
        pointer: ``/paths/<escaped path>/<method>``.
        operation_id: Declared ``operationId``, when present.
        summary: Declared summary, when present.
        tags: Declared tags, for grouping in the picker.
        fields: Addressable fields, possibly truncated (see :attr:`truncated`).
        truncated: True when the walk stopped at a limit and the operation has more fields than
            are listed. A picker that showed a short list without saying so would read as
            "this operation has four fields".
    """

    method: str
    path: str
    pointer: str
    operation_id: Optional[str] = None
    summary: Optional[str] = None
    tags: Tuple[str, ...] = ()
    fields: Tuple[AvailableField, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class AvailableSurface:
    """Everything a consumer could declare against one specification.

    Attributes:
        operations: Every operation, ordered by path then method.
        truncated: True when any operation's field walk hit a limit.
    """

    operations: Tuple[AvailableOperation, ...] = ()
    truncated: bool = False


@dataclass
class _OperationEntry:
    """One operation as the index holds it.

    Attributes:
        method: Lowercase HTTP method.
        path: The specification's path template.
        pointer: The operation pointer.
        operation: The raw operation object.
        parameters: Merged path-item and operation parameters, ``$ref``\\ s resolved.
    """

    method: str
    path: str
    pointer: str
    operation: Dict[str, Any]
    parameters: List[Dict[str, Any]] = dataclass_field(default_factory=list)


def _as_dict(value: Any) -> Dict[str, Any]:
    """Coerce a document node to a dict.

    Args:
        value: Any node.

    Returns:
        The dict, or an empty one for anything else.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    """Coerce a document node to a list.

    Args:
        value: Any node.

    Returns:
        The list, or an empty one for anything else.
    """
    return value if isinstance(value, list) else []


def _is_json_media_type(media_type: str) -> bool:
    """Whether a media type carries a JSON body this module can walk.

    Args:
        media_type: The media type as the document spells it.

    Returns:
        True for ``application/json``, ``application/hal+json``, ``*/*+json``, and friends.
    """
    return any(hint in media_type.lower() for hint in _JSON_MEDIA_HINTS)


class SpecIndex:
    """One OpenAPI document, indexed for the three questions the registry asks of it.

    The index is built once per request and thrown away; it holds no state beyond the document
    it was handed and never mutates it.
    """

    def __init__(self, document: Mapping[str, Any]) -> None:
        """Index a document.

        Args:
            document: The OpenAPI document. Anything that is not a mapping indexes as empty,
                so a caller that could not load a specification still gets a usable (empty)
                index rather than an exception at an awkward moment.
        """
        self._document: Dict[str, Any] = _as_dict(document)
        self._entries: Dict[Tuple[str, str], _OperationEntry] = {}
        self._server_prefixes: Tuple[str, ...] = self._collect_server_prefixes()
        self._index_operations()

    # -----------------------------------------------------------------------------------------
    # Indexing
    # -----------------------------------------------------------------------------------------

    def _collect_server_prefixes(self) -> Tuple[str, ...]:
        """Path prefixes the document's servers declare, longest first.

        A Pact interaction records the path the client actually sent, which includes whatever
        base path the server URL carries (``/v1/pets`` for a server of
        ``https://api.example.com/v1``). Matching has to be able to take that off.

        Returns:
            The distinct non-empty prefixes, longest first so the most specific is tried first.
        """
        prefixes: Set[str] = set()
        for server in _as_list(self._document.get("servers")):
            url = _as_dict(server).get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            candidate = url.strip()
            path = urlsplit(candidate).path if "//" in candidate else candidate
            path = (path or "").rstrip("/")
            if path and path != "/" and "{" not in path:
                prefixes.add(path if path.startswith("/") else f"/{path}")
        return tuple(sorted(prefixes, key=len, reverse=True))

    def _index_operations(self) -> None:
        """Walk ``paths`` and record one entry per declared operation."""
        paths = _as_dict(self._document.get("paths"))
        for path, path_item_raw in paths.items():
            path_item = _as_dict(path_item_raw)
            shared = [
                _as_dict(self._resolve_node(p)[0])
                for p in _as_list(path_item.get("parameters"))
            ]
            for method, operation_raw in path_item.items():
                method_key = normalize_method(str(method))
                if not is_http_method(method_key):
                    continue
                operation = _as_dict(operation_raw)
                own = [
                    _as_dict(self._resolve_node(p)[0])
                    for p in _as_list(operation.get("parameters"))
                ]
                self._entries[(method_key, str(path))] = _OperationEntry(
                    method=method_key,
                    path=str(path),
                    pointer=operation_pointer(str(path), method_key),
                    operation=operation,
                    parameters=_merge_parameters(shared, own),
                )

    # -----------------------------------------------------------------------------------------
    # $ref resolution
    # -----------------------------------------------------------------------------------------

    def _resolve_node(
        self, node: Any, *, seen: Optional[Set[str]] = None
    ) -> Tuple[Any, Optional[str]]:
        """Follow local ``$ref``\\ s to the node they name.

        Only in-document references (``#/...``) are followed. A reference to another file is
        left as it is: the stored document is self-contained by the time it reaches here, and
        silently resolving an external reference to nothing would invent a field that is not
        there.

        Args:
            node: The node, which may be a ``{"$ref": "#/..."}`` wrapper.
            seen: Pointers already visited on this walk, for cycle protection.

        Returns:
            ``(resolved_node, resolved_pointer)`` — the pointer is ``None`` when nothing was
            followed, and the document pointer of the final target otherwise.
        """
        visited = seen if seen is not None else set()
        current = node
        pointer: Optional[str] = None
        while isinstance(current, dict) and isinstance(current.get("$ref"), str):
            ref = current["$ref"]
            if not ref.startswith("#/"):
                return current, pointer
            target_pointer = ref[1:]
            if target_pointer in visited:
                return {}, pointer
            visited.add(target_pointer)
            target = _dereference(self._document, target_pointer)
            if target is None:
                return {}, pointer
            current = target
            pointer = target_pointer
        return current, pointer

    # -----------------------------------------------------------------------------------------
    # Operation lookup
    # -----------------------------------------------------------------------------------------

    def operations(self) -> List[_OperationEntry]:
        """Every indexed operation, ordered by path then method.

        Returns:
            The entries in stable order.
        """
        return [self._entries[key] for key in sorted(self._entries, key=lambda k: (k[1], k[0]))]

    def get_operation(self, method: str, path: str) -> Optional[_OperationEntry]:
        """One operation by its exact template path.

        Args:
            method: HTTP method, any case.
            path: The specification's path template.

        Returns:
            The entry, or ``None``.
        """
        return self._entries.get((normalize_method(method), path))

    def declares_path(self, path: str) -> bool:
        """Whether any method is declared on a path template.

        Args:
            path: The specification's path template.

        Returns:
            True when the document declares at least one operation on it.
        """
        return any(entry_path == path for _, entry_path in self._entries)

    def match_operation(self, method: str, path: str) -> Optional[_OperationEntry]:
        """Resolve a method plus a possibly-concrete path onto a declared operation.

        The match is tried in the order that keeps it predictable: the path exactly as given,
        then with each declared server base path removed, and within each attempt an exact
        template match before a templated one. When several templates match a concrete path,
        the one with the **fewest** template segments wins — ``/pets/mine`` is a better answer
        than ``/pets/{petId}`` when both are declared — and ties break lexicographically so the
        same document always resolves the same way.

        Args:
            method: HTTP method, any case.
            path: A path template or a concrete path as a client sent it.

        Returns:
            The matched entry, or ``None`` when nothing matches.
        """
        method_key = normalize_method(method)
        for candidate in self._path_candidates(path):
            direct = self._entries.get((method_key, candidate))
            if direct is not None:
                return direct
            template = self._match_template(candidate)
            if template is not None:
                matched = self._entries.get((method_key, template))
                if matched is not None:
                    return matched
        return None

    def matches_any_method(self, path: str) -> bool:
        """Whether *some* method is declared on a path a lookup failed to match.

        This is what separates "you called an operation we do not declare" from "you called a
        path we declare, with a method we do not" — two different unresolved reasons, and a
        consumer can act on the second one.

        Args:
            path: A path template or concrete path.

        Returns:
            True when any operation matches the path, regardless of method.
        """
        for candidate in self._path_candidates(path):
            if self.declares_path(candidate):
                return True
            if self._match_template(candidate) is not None:
                return True
        return False

    def _path_candidates(self, path: str) -> List[str]:
        """The path spellings to try, most literal first.

        Args:
            path: The path as the source named it.

        Returns:
            The original path, then the same path with each declared server prefix removed.
        """
        raw = (path or "").split("?", 1)[0].strip()
        if not raw:
            return []
        normalized = raw if raw.startswith("/") else f"/{raw}"
        candidates = [normalized]
        for prefix in self._server_prefixes:
            if normalized.startswith(prefix):
                trimmed = normalized[len(prefix):] or "/"
                if trimmed not in candidates:
                    candidates.append(trimmed)
        return candidates

    def _match_template(self, concrete: str) -> Optional[str]:
        """Find the declared path template a concrete path belongs to.

        Args:
            concrete: A concrete path (``/pets/42``).

        Returns:
            The winning template, or ``None``.
        """
        wanted = [segment for segment in concrete.split("/") if segment != ""]
        best: Optional[Tuple[int, str]] = None
        for _, template in self._entries:
            segments = [segment for segment in template.split("/") if segment != ""]
            if len(segments) != len(wanted):
                continue
            variables = 0
            for declared, actual in zip(segments, wanted):
                if declared.startswith("{") and declared.endswith("}"):
                    variables += 1
                    continue
                if declared != actual:
                    break
            else:
                key = (variables, template)
                if best is None or key < best:
                    best = key
        return best[1] if best else None

    # -----------------------------------------------------------------------------------------
    # Defaults a caller may omit
    # -----------------------------------------------------------------------------------------

    def default_status(self, entry: _OperationEntry) -> Optional[str]:
        """The response status a field selection means when it names none.

        Args:
            entry: The operation.

        Returns:
            The lowest declared 2xx code, else ``default``, else the lowest declared code,
            else ``None`` when the operation declares no responses at all.
        """
        responses = _as_dict(entry.operation.get("responses"))
        if not responses:
            return None
        codes = [str(code) for code in responses]
        successes = sorted(code for code in codes if code[:1] == "2")
        if successes:
            return successes[0]
        if "default" in codes:
            return "default"
        return sorted(codes)[0]

    def _body_content(
        self, entry: _OperationEntry, location: str, status: Optional[str]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """The ``content`` map for a request or response body, and its owning pointer.

        Args:
            entry: The operation.
            location: ``request`` or ``response``.
            status: The response status, for a response.

        Returns:
            ``(content_map, content_pointer)``; an empty map with ``None`` when the body is not
            declared.
        """
        if location == "request":
            body, _ = self._resolve_node(entry.operation.get("requestBody"))
            body_dict = _as_dict(body)
            if not body_dict:
                return {}, None
            return _as_dict(body_dict.get("content")), f"{entry.pointer}/requestBody/content"

        responses = _as_dict(entry.operation.get("responses"))
        code = status or self.default_status(entry)
        if code is None or str(code) not in responses:
            return {}, None
        response, _ = self._resolve_node(responses[str(code)])
        response_dict = _as_dict(response)
        pointer = (
            f"{entry.pointer}/responses/{json_pointer_escape(str(code))}/content"
        )
        return _as_dict(response_dict.get("content")), pointer

    def default_media_type(
        self, entry: _OperationEntry, location: str, status: Optional[str]
    ) -> Optional[str]:
        """The media type a field selection means when it names none.

        Args:
            entry: The operation.
            location: ``request`` or ``response``.
            status: The response status, for a response.

        Returns:
            The first declared JSON media type (sorted, so the choice is stable), else the
            first declared media type, else ``None``.
        """
        content, _ = self._body_content(entry, location, status)
        if not content:
            return None
        media_types = sorted(str(mt) for mt in content)
        for media_type in media_types:
            if _is_json_media_type(media_type):
                return media_type
        return media_types[0]

    # -----------------------------------------------------------------------------------------
    # Field resolution
    # -----------------------------------------------------------------------------------------

    def resolve_field(
        self,
        entry: _OperationEntry,
        *,
        location: str,
        path: str,
        status: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> Tuple[Optional[ConsumerContractField], Optional[str]]:
        """Resolve one named field against the specification.

        Args:
            entry: The operation the field belongs to.
            location: ``response``, ``request``, or ``parameter``.
            path: Dotted data path into the body, or the parameter name.
            status: Response status code; defaults to the operation's first 2xx.
            media_type: Media type; defaults to the first declared JSON media type.

        Returns:
            ``(field, None)`` when it resolved, or ``(None, reason)`` with one of
            :data:`~app.consumer_contract.UNRESOLVED_REASONS` when it did not.
        """
        if location == "parameter":
            return self._resolve_parameter(entry, path)

        code = status or (self.default_status(entry) if location == "response" else None)
        content, content_pointer = self._body_content(entry, location, code)
        if not content or content_pointer is None:
            reason = "status-not-declared" if location == "response" else "media-type-not-declared"
            return None, reason

        chosen = media_type or self.default_media_type(entry, location, code)
        if chosen is None or str(chosen) not in content:
            return None, "media-type-not-declared"

        media_pointer = f"{content_pointer}/{json_pointer_escape(str(chosen))}/schema"
        schema_node = _as_dict(content[str(chosen)]).get("schema")

        anchor = media_pointer
        resolved_node, resolved_target = self._resolve_node(schema_node)
        resolved = resolved_target or media_pointer

        segments = [segment for segment in (path or "").split(".") if segment]
        current: Any = resolved_node
        for segment in segments:
            step = self._descend(current, anchor, resolved, segment)
            if step is None:
                return None, "field-not-found"
            current, anchor, resolved = step

        return (
            ConsumerContractField(
                pointer=anchor,
                schema_pointer=resolved,
                location=location,
                status=str(code) if location == "response" and code is not None else None,
                media_type=str(chosen),
                path=path or "",
            ),
            None,
        )

    def _resolve_parameter(
        self, entry: _OperationEntry, name: str
    ) -> Tuple[Optional[ConsumerContractField], Optional[str]]:
        """Resolve a parameter by name.

        The pointer uses the classifier's own parameter identity (``<in>:<name>``), so a
        ``required_param_added`` change lands on the same pointer a contract stored.

        Args:
            entry: The operation.
            name: The parameter name.

        Returns:
            ``(field, None)`` or ``(None, "parameter-not-declared")``.
        """
        wanted = (name or "").strip()
        for parameter in entry.parameters:
            if str(parameter.get("name", "")) != wanted:
                continue
            identity = f"{parameter.get('in', '')}:{parameter.get('name', '')}"
            pointer = f"{entry.pointer}/parameters/{json_pointer_escape(identity)}"
            return (
                ConsumerContractField(
                    pointer=pointer,
                    schema_pointer=pointer,
                    location="parameter",
                    status=None,
                    media_type=None,
                    path=wanted,
                ),
                None,
            )
        return None, "parameter-not-declared"

    def _descend(
        self, schema: Any, anchor: str, resolved: str, segment: str
    ) -> Optional[Tuple[Any, str, str]]:
        """Take one data-path step into a schema.

        Array levels are transparent: ``items.id`` names ``id`` inside every element of
        ``items``, which is how a consumer talks about it and how a Pact body is shaped.
        Composition branches are searched in document order, and an object that permits
        additional properties resolves an unknown key onto its ``additionalProperties`` schema
        rather than refusing — a map-typed body has real fields whose names are data.

        Args:
            schema: The schema node to descend from.
            anchor: The operation-anchored pointer of that node.
            resolved: The document pointer of that node.
            segment: The property name to step into.

        Returns:
            ``(schema, anchor, resolved)`` for the step, or ``None`` when the name is not there.
        """
        node, anchor, resolved = self._unwrap_arrays(schema, anchor, resolved)
        node_dict = _as_dict(node)

        properties = _as_dict(node_dict.get("properties"))
        if segment in properties:
            child_anchor = f"{anchor}/properties/{json_pointer_escape(segment)}"
            child_resolved = f"{resolved}/properties/{json_pointer_escape(segment)}"
            child, target = self._resolve_node(properties[segment])
            return child, child_anchor, target or child_resolved

        for keyword in _COMPOSITION_KEYWORDS:
            branches = _as_list(node_dict.get(keyword))
            for position, branch in enumerate(branches):
                branch_anchor = f"{anchor}/{keyword}/{position}"
                branch_resolved = f"{resolved}/{keyword}/{position}"
                branch_node, target = self._resolve_node(branch)
                step = self._descend(
                    branch_node, branch_anchor, target or branch_resolved, segment
                )
                if step is not None:
                    return step

        additional = node_dict.get("additionalProperties")
        if isinstance(additional, dict):
            child_anchor = f"{anchor}/additionalProperties"
            child_resolved = f"{resolved}/additionalProperties"
            child, target = self._resolve_node(additional)
            return child, child_anchor, target or child_resolved
        if additional is True:
            return {}, f"{anchor}/additionalProperties", f"{resolved}/additionalProperties"

        return None

    def _unwrap_arrays(
        self, schema: Any, anchor: str, resolved: str
    ) -> Tuple[Any, str, str]:
        """Descend through any number of array levels without consuming a path segment.

        Args:
            schema: The schema node.
            anchor: Its operation-anchored pointer.
            resolved: Its document pointer.

        Returns:
            The first non-array node reached, with its two pointers.
        """
        node = schema
        for _ in range(MAX_FIELD_DEPTH):
            node_dict = _as_dict(node)
            items = node_dict.get("items")
            if items is None:
                return node, anchor, resolved
            anchor = f"{anchor}/items"
            child_resolved = f"{resolved}/items"
            node, target = self._resolve_node(items)
            resolved = target or child_resolved
        return node, anchor, resolved

    # -----------------------------------------------------------------------------------------
    # Enumeration (the picker's catalogue)
    # -----------------------------------------------------------------------------------------

    def available_surface(self) -> AvailableSurface:
        """Every operation and addressable field in the document.

        Returns:
            The catalogue, with ``truncated`` set when any operation's walk hit a limit.
        """
        operations: List[AvailableOperation] = []
        any_truncated = False
        for entry in self.operations():
            fields, truncated = self._available_fields(entry)
            any_truncated = any_truncated or truncated
            tags = tuple(
                str(tag) for tag in _as_list(entry.operation.get("tags")) if isinstance(tag, str)
            )
            summary = entry.operation.get("summary")
            operations.append(
                AvailableOperation(
                    method=entry.method,
                    path=entry.path,
                    pointer=entry.pointer,
                    operation_id=(
                        str(entry.operation["operationId"])
                        if isinstance(entry.operation.get("operationId"), str)
                        else None
                    ),
                    summary=str(summary) if isinstance(summary, str) else None,
                    tags=tags,
                    fields=tuple(fields),
                    truncated=truncated,
                )
            )
        return AvailableSurface(operations=tuple(operations), truncated=any_truncated)

    def _available_fields(self, entry: _OperationEntry) -> Tuple[List[AvailableField], bool]:
        """Enumerate one operation's addressable fields.

        Order is parameters, then request body, then each declared response in code order — the
        order a person reads an operation in, and a stable one.

        Args:
            entry: The operation.

        Returns:
            ``(fields, truncated)``.
        """
        fields: List[AvailableField] = []
        truncated = False

        for parameter in entry.parameters:
            if len(fields) >= MAX_FIELDS_PER_OPERATION:
                return fields, True
            identity = f"{parameter.get('in', '')}:{parameter.get('name', '')}"
            pointer = f"{entry.pointer}/parameters/{json_pointer_escape(identity)}"
            schema = _as_dict(self._resolve_node(parameter.get("schema"))[0])
            fields.append(
                AvailableField(
                    pointer=pointer,
                    schema_pointer=pointer,
                    location="parameter",
                    path=str(parameter.get("name", "")),
                    type_name=_type_name(schema),
                    required=parameter.get("required") is True,
                )
            )

        request_fields, request_truncated = self._walk_body(entry, "request", None, len(fields))
        fields.extend(request_fields)
        truncated = truncated or request_truncated

        responses = _as_dict(entry.operation.get("responses"))
        for code in sorted(str(key) for key in responses):
            body_fields, body_truncated = self._walk_body(entry, "response", code, len(fields))
            fields.extend(body_fields)
            truncated = truncated or body_truncated

        return fields, truncated

    def _walk_body(
        self, entry: _OperationEntry, location: str, status: Optional[str], used: int
    ) -> Tuple[List[AvailableField], bool]:
        """Enumerate the fields of one body.

        Args:
            entry: The operation.
            location: ``request`` or ``response``.
            status: The response status, for a response.
            used: How many fields the operation has already contributed, so the per-operation
                cap covers the operation rather than each body separately.

        Returns:
            ``(fields, truncated)``.
        """
        content, content_pointer = self._body_content(entry, location, status)
        if not content or content_pointer is None:
            return [], False

        media_type = self.default_media_type(entry, location, status)
        if media_type is None or not _is_json_media_type(str(media_type)):
            return [], False

        anchor = f"{content_pointer}/{json_pointer_escape(str(media_type))}/schema"
        node, target = self._resolve_node(_as_dict(content[str(media_type)]).get("schema"))
        collected: List[AvailableField] = []
        truncated = self._walk_schema(
            node,
            anchor=anchor,
            resolved=target or anchor,
            data_path="",
            depth=0,
            location=location,
            status=status,
            media_type=str(media_type),
            out=collected,
            budget=MAX_FIELDS_PER_OPERATION - used,
            seen=set(),
        )
        return collected, truncated

    def _walk_schema(
        self,
        schema: Any,
        *,
        anchor: str,
        resolved: str,
        data_path: str,
        depth: int,
        location: str,
        status: Optional[str],
        media_type: str,
        out: List[AvailableField],
        budget: int,
        seen: Set[str],
    ) -> bool:
        """Collect every named field under a schema.

        Args:
            schema: The schema node.
            anchor: Its operation-anchored pointer.
            resolved: Its document pointer.
            data_path: The dotted data path that reaches it.
            depth: How many object levels deep the walk already is.
            location: ``request`` or ``response``.
            status: The response status, for a response.
            media_type: The media type the body was declared under.
            out: Accumulator, appended in place.
            budget: How many more fields may be collected.
            seen: Document pointers already walked, for cycle protection.

        Returns:
            True when the walk stopped early at a depth, budget, or cycle limit.
        """
        if depth > MAX_FIELD_DEPTH:
            return True
        if len(out) >= budget:
            return True

        node, anchor, resolved = self._unwrap_arrays(schema, anchor, resolved)
        node_dict = _as_dict(node)
        if not node_dict:
            return False
        if resolved in seen:
            return True
        seen = seen | {resolved}

        truncated = False
        required_names = {
            str(name) for name in _as_list(node_dict.get("required")) if isinstance(name, str)
        }

        for name in sorted(_as_dict(node_dict.get("properties"))):
            if len(out) >= budget:
                return True
            raw_child = _as_dict(node_dict.get("properties"))[name]
            child_anchor = f"{anchor}/properties/{json_pointer_escape(str(name))}"
            child_resolved = f"{resolved}/properties/{json_pointer_escape(str(name))}"
            child, target = self._resolve_node(raw_child)
            child_resolved = target or child_resolved
            child_path = f"{data_path}.{name}" if data_path else str(name)
            out.append(
                AvailableField(
                    pointer=child_anchor,
                    schema_pointer=child_resolved,
                    location=location,
                    path=child_path,
                    status=str(status) if location == "response" and status is not None else None,
                    media_type=media_type,
                    type_name=_type_name(_as_dict(child)),
                    required=str(name) in required_names,
                )
            )
            truncated = (
                self._walk_schema(
                    child,
                    anchor=child_anchor,
                    resolved=child_resolved,
                    data_path=child_path,
                    depth=depth + 1,
                    location=location,
                    status=status,
                    media_type=media_type,
                    out=out,
                    budget=budget,
                    seen=seen,
                )
                or truncated
            )

        for keyword in _COMPOSITION_KEYWORDS:
            for position, branch in enumerate(_as_list(node_dict.get(keyword))):
                if len(out) >= budget:
                    return True
                branch_anchor = f"{anchor}/{keyword}/{position}"
                branch_resolved = f"{resolved}/{keyword}/{position}"
                branch_node, target = self._resolve_node(branch)
                truncated = (
                    self._walk_schema(
                        branch_node,
                        anchor=branch_anchor,
                        resolved=target or branch_resolved,
                        data_path=data_path,
                        depth=depth,
                        location=location,
                        status=status,
                        media_type=media_type,
                        out=out,
                        budget=budget,
                        seen=seen,
                    )
                    or truncated
                )

        return truncated


def _type_name(schema: Mapping[str, Any]) -> Optional[str]:
    """The schema's declared type, as a picker label.

    Args:
        schema: A schema node.

    Returns:
        The ``type`` when it is a string, the first entry when it is a list (OpenAPI 3.1 spells
        a nullable string as ``["string", "null"]``), else ``None``.
    """
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        for entry in declared:
            if isinstance(entry, str) and entry != "null":
                return entry
    return None


def _merge_parameters(
    shared: Sequence[Mapping[str, Any]], own: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge path-item parameters with an operation's own, operation wins.

    OpenAPI says an operation's parameter overrides a path-item parameter of the same
    ``name``/``in`` pair. Applying that here means a contract's parameter pointer is the one the
    classifier will report against.

    Args:
        shared: Path-item level parameters, ``$ref``\\ s already resolved.
        own: Operation level parameters, ``$ref``\\ s already resolved.

    Returns:
        The merged list, ordered by ``in`` then ``name`` so enumeration is stable.
    """
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for parameter in list(shared) + list(own):
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name", ""))
        location = str(parameter.get("in", ""))
        if not name:
            continue
        merged[(location, name)] = dict(parameter)
    return [merged[key] for key in sorted(merged)]


def _dereference(document: Mapping[str, Any], pointer: str) -> Optional[Any]:
    """Read a node out of a document by JSON Pointer.

    Args:
        document: The document.
        pointer: An RFC 6901 pointer beginning with ``/``.

    Returns:
        The node, or ``None`` when any segment is missing.
    """
    current: Any = document
    for token in pointer.split("/"):
        if token == "":
            continue
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return None
    return current


def resolve_selection(
    selection: SurfaceSelection, index: SpecIndex
) -> Tuple[ConsumerContractSurface, List[UnresolvedInteraction]]:
    """Resolve a picked surface against a specification.

    The picker sends what a person meant; this turns it into pointers, and reports every part it
    could not place instead of dropping it. An operation that does not resolve contributes an
    unresolved entry and no operation; a field that does not resolve contributes an unresolved
    entry and leaves its operation in place, because "you call this operation but that field is
    gone" is a more useful answer than discarding the call.

    Args:
        selection: The picked operations and fields.
        index: The specification index to resolve against.

    Returns:
        ``(surface, unresolved)``.
    """
    operations: List[ConsumerContractOperation] = []
    unresolved: List[UnresolvedInteraction] = []

    for picked in selection.operations:
        entry = index.match_operation(picked.method, picked.path)
        if entry is None:
            unresolved.append(
                UnresolvedInteraction(
                    reason=(
                        "method-not-declared"
                        if index.matches_any_method(picked.path)
                        else "operation-not-found"
                    ),
                    message=(
                        f"the specification declares no {picked.method.upper()} "
                        f"{picked.path} operation"
                    ),
                    method=picked.method,
                    path=picked.path,
                )
            )
            continue

        fields: List[ConsumerContractField] = []
        for picked_field in picked.fields:
            field, reason = index.resolve_field(
                entry,
                location=picked_field.location,
                path=picked_field.path,
                status=picked_field.status,
                media_type=picked_field.media_type,
            )
            if field is None:
                unresolved.append(
                    UnresolvedInteraction(
                        reason=reason or "field-not-found",
                        message=(
                            f"{entry.method.upper()} {entry.path} does not declare "
                            f"{picked_field.location} field '{picked_field.path or '(body)'}'"
                        ),
                        method=entry.method,
                        path=entry.path,
                        status=picked_field.status,
                        field_path=picked_field.path,
                    )
                )
                continue
            fields.append(field)

        summary = entry.operation.get("summary")
        operations.append(
            ConsumerContractOperation(
                method=entry.method,
                path=entry.path,
                pointer=entry.pointer,
                operation_id=(
                    str(entry.operation["operationId"])
                    if isinstance(entry.operation.get("operationId"), str)
                    else None
                ),
                summary=str(summary) if isinstance(summary, str) else None,
                fields=fields,
            )
        )

    return ConsumerContractSurface(operations=sort_operations(operations)), unresolved
