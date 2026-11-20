"""Export an OpenAPI document bundled, dereferenced or split into files — COA-2.4 (#7047).

The OpenAPI emitter writes one self-contained document whose shared objects live under
``components`` and are reached by internal ``$ref`` (``#/components/schemas/Pet``). That is the
**bundle** shape, and the default. Two more shapes are an export option (``refs``):

* **dereference** — every internal ``$ref`` is replaced by a copy of what it points at, so a reader
  never has to follow a reference. ``components`` is kept (its entries dereferenced too), so a
  ``discriminator.mapping`` or a security requirement that names a component still resolves. A
  **circular** reference (a ``Tree`` whose ``children`` are ``Tree``) cannot be expanded: it is
  never expanded forever. With the ``keep-ref`` cycle policy the reference that closes the loop
  stays a ``$ref`` and each one is reported as a loss; with ``error`` the export is refused
  (:class:`~app.emitter.EmitPreconditionError`, HTTP 422) and the message names the cycles.
* **split** — the root document keeps ``info``, ``servers``, ``tags`` and so on, and each path item
  and each component moves into its own file (``paths/pets_petId.json``,
  ``components/schemas/Pet.json``; Swagger 2.0: ``definitions/Pet.json``). The root and the files
  reach each other by relative ``$ref``, the conventional multi-file layout. Importing the files
  again (:func:`app.openapi_fileset_bundle.bundle_openapi_fileset`) rebuilds the bundled document.

Only ``$ref`` keys (plus ``discriminator.mapping`` values and a Link's ``operationRef`` when
splitting) are treated as references. Literal data — ``example``, ``default``, ``const``, ``enum``,
an Example's ``value`` and a schema's ``examples`` list — is copied as is, even when it holds a key
named ``$ref``. A reference that is not an internal JSON Pointer (``https://…``, ``#anchor``) is
left as written; when splitting, a relative file reference is re-based onto the file it moves to.
"""

from __future__ import annotations

import copy
import posixpath
import re
from typing import Any, Dict, List, Optional, Tuple

from .emitter import EmitPreconditionError, EmittedFile, LossKind, LossTracker

__all__ = [
    "CYCLE_POLICIES",
    "MAX_DEREFERENCED_NODES",
    "REF_MODES",
    "apply_ref_mode",
    "dereference_document",
    "split_document",
]

#: The ``refs`` option values: the default bundled document, fully dereferenced, or split into files.
REF_MODES: Tuple[str, ...] = ("bundle", "dereference", "split")
#: The ``ref_cycles`` option values: keep the closing ``$ref`` (and report it), or refuse the export.
CYCLE_POLICIES: Tuple[str, ...] = ("keep-ref", "error")

#: The most JSON nodes a dereferenced document may hold. A document whose shared schemas are reused
#: many times over can grow far beyond its bundled size when every reference is copied in; past
#: this bound the export is refused (export it bundled or split instead) rather than exhausting
#: the server's memory.
MAX_DEREFERENCED_NODES = 2_000_000

#: Loss subject for a circular reference a dereferenced document keeps as ``$ref``.
CYCLE_LOSS_SUBJECT = "openapi-dereference-cycle"

#: Keys whose value is literal data, never a reference (a ``$ref`` key inside is just data).
_LITERAL_KEYS = frozenset({"example", "default", "const", "enum", "value", "externalValue"})

#: The ``components`` sections an OpenAPI 3.x split moves into files: every section whose entries
#: may be a Reference Object. ``securitySchemes`` stay in the root — security requirements name
#: them, so they are never reached by ``$ref`` in practice.
_SPLIT_SECTIONS_3X: Tuple[str, ...] = (
    "schemas",
    "responses",
    "parameters",
    "examples",
    "requestBodies",
    "headers",
    "links",
    "callbacks",
    "pathItems",
    "mediaTypes",
)
#: Swagger 2.0: only ``definitions`` take a ``$ref`` entry (``parameters`` / ``responses`` do not).
_SPLIT_SECTIONS_20: Tuple[str, ...] = ("definitions",)

#: Characters kept in a split file name; every other run becomes ``_``.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


# ===========================================================================
# JSON Pointer helpers
# ===========================================================================


def _escape(token: str) -> str:
    """Escape one JSON Pointer reference token (RFC 6901: ``~`` → ``~0``, ``/`` → ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    """Undo :func:`_escape` for one reference token."""
    return token.replace("~1", "/").replace("~0", "~")


def _resolve_pointer(document: Any, ref: str) -> Tuple[bool, Any]:
    """Follow the internal reference ``ref`` (``#/a/b``) into ``document``.

    Args:
        document: The document the reference lives in.
        ref: An internal JSON Pointer reference starting with ``#/``.

    Returns:
        ``(True, value)`` when the pointer resolves, ``(False, None)`` when it does not.
    """
    current = document
    for raw in ref[2:].split("/"):
        token = _unescape(raw)
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return False, None
    return True, current


def _is_internal_pointer(ref: Any) -> bool:
    """Whether ``ref`` is an internal JSON Pointer reference (``#/…``)."""
    return isinstance(ref, str) and ref.startswith("#/")


def _is_literal(key: str, value: Any, parent_key: Optional[str]) -> bool:
    """Whether ``value`` under ``key`` is literal data the walk must not treat as references.

    A schema's ``examples`` is a list of literal instances; a media type's ``examples`` is a map of
    Example Objects (or references to them), which the walk does enter. A schema's ``default`` is
    literal, but the ``default`` entry of a Responses Object is a Response (or a reference to one).

    Args:
        key: The member's key.
        value: The member's value.
        parent_key: The key of the mapping that holds the member (``None`` at the root).
    """
    if key == "default" and parent_key == "responses":
        return False
    return key in _LITERAL_KEYS or (key == "examples" and isinstance(value, list))


def _node_count(value: Any) -> int:
    """The number of JSON nodes in ``value`` (each dict, list and scalar counts as one)."""
    if isinstance(value, dict):
        return 1 + sum(_node_count(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_node_count(item) for item in value)
    return 1


# ===========================================================================
# Dereference
# ===========================================================================


def _component_entry_pointers(document: Dict[str, Any]) -> List[str]:
    """The references of every reusable entry (``#/components/schemas/Pet``, ``#/definitions/Pet``).

    Each entry is dereferenced with its own reference already on the expansion stack, so a
    self-recursive component keeps its self reference instead of being expanded one level.
    """
    pointers: List[str] = []
    components = document.get("components")
    if isinstance(components, dict):
        for section, entries in components.items():
            if isinstance(entries, dict):
                pointers.extend(
                    f"#/components/{_escape(section)}/{_escape(name)}" for name in entries
                )
    for section in ("definitions", "parameters", "responses"):
        entries = document.get(section) if "swagger" in document else None
        if isinstance(entries, dict):
            pointers.extend(f"#/{section}/{_escape(name)}" for name in entries)
    return pointers


class _Dereferencer:
    """One dereference run over a document: the cycles found and the expansions cached so far."""

    def __init__(self, document: Dict[str, Any]) -> None:
        self.document = document
        #: ``(pointer in the output, reference kept)`` for every circular reference left as ``$ref``.
        self.cycles: List[Tuple[str, str]] = []
        #: Cycle-free expansions by reference, with their node counts (an expansion that met a
        #: cycle depends on the expansion stack, so it is never cached).
        self.cache: Dict[str, Tuple[Any, int]] = {}
        self.nodes = 0

    def _grow(self, count: int) -> None:
        """Count ``count`` more output nodes, refusing a document past :data:`MAX_DEREFERENCED_NODES`."""
        self.nodes += count
        if self.nodes > MAX_DEREFERENCED_NODES:
            raise EmitPreconditionError(
                "Dereferencing this document would copy shared objects into more than "
                f"{MAX_DEREFERENCED_NODES:,} JSON values. Export it bundled or split instead."
            )

    def expand(self, value: Any, at: str, stack: Tuple[str, ...], key: Optional[str] = None) -> Any:
        """Return ``value`` with every internal ``$ref`` replaced by its expanded target.

        Args:
            value: The JSON value to dereference (not modified).
            at: The JSON Pointer of ``value`` in the output document (for cycle reports).
            stack: The references being expanded around ``value``, outermost first.
            key: The key ``value`` sits under (``None`` for a list item or the root), which decides
                whether its members are literal data (:func:`_is_literal`).

        Returns:
            The dereferenced copy.
        """
        if isinstance(value, list):
            self._grow(1)
            return [self.expand(item, f"{at}/{index}", stack) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            self._grow(1)
            return value
        ref = value.get("$ref")
        if _is_internal_pointer(ref):
            return self._expand_reference(value, ref, at, stack, key)
        self._grow(1)
        return {
            name: copy.deepcopy(item)
            if _is_literal(name, item, key)
            else self.expand(item, f"{at}/{_escape(name)}", stack, name)
            for name, item in value.items()
        }

    def _expand_reference(
        self, value: Dict[str, Any], ref: str, at: str, stack: Tuple[str, ...], key: Optional[str]
    ) -> Any:
        """Expand the Reference Object ``value`` (its ``$ref`` is ``ref``); see :meth:`expand`."""
        if ref in stack:
            self.cycles.append((at, ref))
            self._grow(_node_count(value))
            return copy.deepcopy(value)
        found, target = _resolve_pointer(self.document, ref)
        if not found:
            # A dangling reference is not this option's to fix: it stays as written.
            self._grow(_node_count(value))
            return copy.deepcopy(value)
        cached = self.cache.get(ref)
        if cached is not None:
            expanded, count = cached
            self._grow(count)
            expanded = copy.deepcopy(expanded)
        else:
            cycles_before, nodes_before = len(self.cycles), self.nodes
            expanded = self.expand(target, at, (*stack, ref))
            if len(self.cycles) == cycles_before:
                self.cache[ref] = (copy.deepcopy(expanded), self.nodes - nodes_before)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        if not siblings:
            return expanded
        siblings = self.expand(siblings, at, stack, key)
        return _merge_siblings(expanded, siblings)


def _merge_siblings(expanded: Any, siblings: Dict[str, Any]) -> Any:
    """Combine a dereferenced target with the keys written beside its ``$ref``.

    ``summary`` / ``description`` override the target's (the OpenAPI Reference Object rule). A
    ``summary`` only applies to an object that has one (an Example, a Path Item); on any other
    target it "has no effect" (OpenAPI 3.1 §4.8.23) and is dropped, so a Parameter never gains a
    field it may not carry. Any other sibling (a 3.1 schema's ``$ref`` next to ``maxLength``) is
    merged in when the target does not define it; when it does, the target is kept whole under
    ``allOf`` and the siblings sit beside it, so neither side's constraint is lost.
    """
    if not isinstance(expanded, dict):
        return expanded
    if "summary" in siblings and not _takes_summary(expanded):
        siblings = {key: item for key, item in siblings.items() if key != "summary"}
    overridable = {"summary", "description"}
    conflict = any(key in expanded and key not in overridable for key in siblings)
    if conflict:
        return {"allOf": [expanded], **siblings}
    return {**expanded, **siblings}


#: Keys that mark an Example Object (which, like a Path Item, has a ``summary`` field).
_EXAMPLE_KEYS = frozenset({"value", "externalValue", "dataValue", "serializedValue"})
#: Path Item operation keys (a Path Item has a ``summary`` field).
_PATH_ITEM_KEYS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "query", "additionalOperations"}
)


def _takes_summary(target: Dict[str, Any]) -> bool:
    """Whether ``target`` is an object with a ``summary`` field (an Example or a Path Item)."""
    return "summary" in target or bool(set(target) & (_EXAMPLE_KEYS | _PATH_ITEM_KEYS))


def dereference_document(
    document: Dict[str, Any],
    *,
    cycle_policy: str = "keep-ref",
    losses: Optional[LossTracker] = None,
) -> Dict[str, Any]:
    """Return ``document`` with every internal ``$ref`` replaced by what it points at.

    Args:
        document: A bundled OpenAPI (or Swagger 2.0) document. Not modified.
        cycle_policy: ``keep-ref`` keeps each reference that closes a cycle as ``$ref`` and reports
            it; ``error`` refuses a document that has a cycle.
        losses: Where each kept cyclic reference is recorded (``openapi-dereference-cycle``, one
            loss per distinct reference, pointing at its first occurrence).

    Returns:
        The dereferenced copy.

    Raises:
        EmitPreconditionError: When ``cycle_policy`` is ``error`` and the document has a circular
            reference, or when the output would exceed :data:`MAX_DEREFERENCED_NODES`.
        ValueError: When ``cycle_policy`` is not one of :data:`CYCLE_POLICIES`.
    """
    if cycle_policy not in CYCLE_POLICIES:
        raise ValueError(f"Unknown cycle policy {cycle_policy!r}; expected one of {CYCLE_POLICIES}.")
    run = _Dereferencer(document)
    entries = set(_component_entry_pointers(document))
    result = _expand_with_entries(run, document, "", entries)

    if run.cycles and cycle_policy == "error":
        refs = sorted({ref for _, ref in run.cycles})
        named = ", ".join(refs[:5]) + (f" and {len(refs) - 5} more" if len(refs) > 5 else "")
        raise EmitPreconditionError(
            f"The document has {len(refs)} circular $ref(s) ({named}); a fully dereferenced copy "
            "would never end. Export it bundled or split, or keep cyclic references as $ref "
            "(ref_cycles: keep-ref)."
        )
    if losses is not None:
        first: Dict[str, Tuple[str, int]] = {}
        for at, ref in run.cycles:
            pointer, count = first.get(ref, (at, 0))
            first[ref] = (pointer, count + 1)
        for ref, (pointer, count) in sorted(first.items()):
            places = "once" if count == 1 else f"{count} times"
            losses.record(
                LossKind.INFERRED,
                CYCLE_LOSS_SUBJECT,
                f"{ref} refers back to itself, so the dereferenced document keeps it as a $ref "
                f"({places}) instead of expanding it forever.",
                pointer=pointer or "/",
            )
    return result


def _expand_with_entries(run: _Dereferencer, value: Any, at: str, entries: set) -> Any:
    """Dereference the document tree, putting each component entry's own reference on its stack."""
    if not isinstance(value, dict):
        return run.expand(value, at, ())
    out: Dict[str, Any] = {}
    for key, item in value.items():
        pointer = f"{at}/{_escape(key)}"
        if f"#{pointer}" in entries:
            out[key] = run.expand(item, pointer, (f"#{pointer}",), key)
        elif isinstance(item, dict) and any(entry.startswith(f"#{pointer}/") for entry in entries):
            out[key] = _expand_with_entries(run, item, pointer, entries)
        else:
            out[key] = run.expand(item, pointer, (), key)
    return out


# ===========================================================================
# Split
# ===========================================================================


def _file_stem(name: str) -> str:
    """A file-name-safe stem for a component name or a path (``/pets/{petId}`` → ``pets_petId``)."""
    stem = _UNSAFE_NAME.sub("_", name.strip("/")).strip("._")
    return stem or "root"


def _split_units(document: Dict[str, Any]) -> Dict[str, str]:
    """Choose the file of every split unit, keyed by the unit's JSON Pointer (``/paths/~1pets``).

    A unit that is already a bare ``$ref`` (a path item or component that only refers elsewhere)
    stays in the root. File names are unique within their folder, ignoring case.
    """
    units: Dict[str, str] = {}
    taken: set = set()

    def add(pointer: str, folder: str, name: str) -> None:
        stem = _file_stem(name)
        candidate, suffix = f"{folder}/{stem}.json", 2
        while candidate.lower() in taken:
            candidate, suffix = f"{folder}/{stem}-{suffix}.json", suffix + 1
        taken.add(candidate.lower())
        units[pointer] = candidate

    def bare_ref(value: Any) -> bool:
        return isinstance(value, dict) and set(value) == {"$ref"}

    paths = document.get("paths")
    if isinstance(paths, dict):
        for key, item in paths.items():
            if isinstance(item, dict) and not bare_ref(item):
                add(f"/paths/{_escape(key)}", "paths", key)
    if "swagger" in document:
        sections = [(f"/{section}", section, document.get(section)) for section in _SPLIT_SECTIONS_20]
    else:
        components = document.get("components")
        components = components if isinstance(components, dict) else {}
        sections = [
            (f"/components/{section}", f"components/{section}", components.get(section))
            for section in _SPLIT_SECTIONS_3X
        ]
    for prefix, folder, entries in sections:
        if isinstance(entries, dict):
            for name, item in entries.items():
                if isinstance(item, dict) and not bare_ref(item):
                    add(f"{prefix}/{_escape(name)}", folder, name)
    return units


def _relative(target: str, from_file: str) -> str:
    """The relative reference from ``from_file`` to ``target`` (both bundle-relative paths)."""
    start = posixpath.dirname(from_file) or "."
    return posixpath.relpath(target, start)


class _Splitter:
    """One split run: the units, the root file, and the reference rewrite they imply."""

    def __init__(self, units: Dict[str, str], root_path: str) -> None:
        self.units = units
        self.root_path = root_path
        # Longest prefix first, so a reference resolves to the innermost unit that contains it.
        self.prefixes = sorted(units, key=len, reverse=True)

    def rewrite_ref(self, ref: str, in_file: str) -> str:
        """Rewrite one reference written in the bundled document so it resolves from ``in_file``."""
        if _is_internal_pointer(ref):
            pointer = ref[1:]
            for prefix in self.prefixes:
                if pointer == prefix or pointer.startswith(prefix + "/"):
                    target = _relative(self.units[prefix], in_file)
                    rest = pointer[len(prefix):]
                    return f"{target}#{rest}" if rest else target
            if in_file == self.root_path:
                return ref
            return f"{_relative(self.root_path, in_file)}{ref}"
        if not isinstance(ref, str) or ref.startswith("#") or "://" in ref or ref.startswith("urn:"):
            return ref
        # A relative file reference was written relative to the root: re-base it onto ``in_file``.
        file_part, hash_sign, fragment = ref.partition("#")
        if not file_part or posixpath.isabs(file_part):
            return ref
        moved = posixpath.normpath(posixpath.join(posixpath.dirname(self.root_path), file_part))
        return _relative(moved, in_file) + (hash_sign + fragment if hash_sign else "")

    def rewrite(self, value: Any, in_file: str, parent_key: Optional[str] = None) -> Any:
        """Return a copy of ``value`` with every reference rewritten for ``in_file``.

        Args:
            value: The JSON value (not modified).
            in_file: The bundle path of the file ``value`` is written to.
            parent_key: The key ``value`` sits under, for :func:`_is_literal`.
        """
        if isinstance(value, list):
            return [self.rewrite(item, in_file) for item in value]
        if not isinstance(value, dict):
            return value
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                out[key] = self.rewrite_ref(item, in_file)
            elif key == "operationRef" and _is_internal_pointer(item):
                out[key] = self.rewrite_ref(item, in_file)
            elif key == "mapping" and isinstance(item, dict):
                # A mapping value is a reference or a bare schema name (``Foo``); only the
                # internal pointers move with the split.
                out[key] = {
                    name: self.rewrite_ref(target, in_file) if _is_internal_pointer(target) else target
                    for name, target in item.items()
                }
            elif _is_literal(key, item, parent_key):
                out[key] = copy.deepcopy(item)
            else:
                out[key] = self.rewrite(item, in_file, key)
        return out


def _set_pointer(document: Dict[str, Any], pointer: str, value: Any) -> None:
    """Replace the value at the (existing) JSON Pointer ``pointer`` in ``document``."""
    tokens = [_unescape(raw) for raw in pointer[1:].split("/")]
    current = document
    for token in tokens[:-1]:
        current = current[token]
    current[tokens[-1]] = value


def split_document(
    document: Dict[str, Any],
    *,
    root_path: str,
    media_type: str,
) -> List[EmittedFile]:
    """Split a bundled document into a root file plus one file per path item and component.

    Args:
        document: A bundled OpenAPI (or Swagger 2.0) document. Not modified.
        root_path: The root file's bundle path (``openapi.json`` / ``swagger.json``).
        media_type: The root file's media type; the other files are ``application/json``.

    Returns:
        The root file first, then the unit files sorted by path. A document with nothing to split
        (no path items, no components) is the root alone.
    """
    units = _split_units(document)
    splitter = _Splitter(units, root_path)
    root = splitter.rewrite(document, root_path)
    files: List[EmittedFile] = []
    for pointer, path in units.items():
        _, value = _resolve_pointer(document, f"#{pointer}")
        files.append(
            EmittedFile(path=path, content=splitter.rewrite(value, path), media_type="application/json")
        )
        _set_pointer(root, pointer, {"$ref": _relative(path, root_path)})
    files.sort(key=lambda file: file.path)
    return [EmittedFile(path=root_path, content=root, media_type=media_type), *files]


# ===========================================================================
# Entry point
# ===========================================================================


def apply_ref_mode(
    document: Dict[str, Any],
    *,
    mode: str,
    cycle_policy: str,
    root_path: str,
    media_type: str,
    losses: LossTracker,
) -> List[EmittedFile]:
    """Shape the emitted document per the ``refs`` export option.

    Args:
        document: The emitter's bundled document.
        mode: One of :data:`REF_MODES`.
        cycle_policy: One of :data:`CYCLE_POLICIES` (used by ``dereference``).
        root_path: The primary file's bundle path.
        media_type: The primary file's media type.
        losses: The emit's loss tracker (dereference cycles are recorded here).

    Returns:
        The emitted files, primary first: one for ``bundle`` and ``dereference``, several for ``split``.

    Raises:
        ValueError: When ``mode`` is not one of :data:`REF_MODES`.
        EmitPreconditionError: See :func:`dereference_document`.
    """
    if mode == "bundle":
        return [EmittedFile(path=root_path, content=document, media_type=media_type)]
    if mode == "dereference":
        dereferenced = dereference_document(document, cycle_policy=cycle_policy, losses=losses)
        return [EmittedFile(path=root_path, content=dereferenced, media_type=media_type)]
    if mode == "split":
        return split_document(document, root_path=root_path, media_type=media_type)
    raise ValueError(f"Unknown refs mode {mode!r}; expected one of {REF_MODES}.")

