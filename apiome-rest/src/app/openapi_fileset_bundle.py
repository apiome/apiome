"""Bundle a split OpenAPI fileset into one document by hoisting components — FMT-7.1 (#5455).

Teams often keep an API definition's schemas and parameters in a sibling file and reach them by
relative ``$ref`` (``./components.yaml#/components/schemas/Shipment``). The AsyncAPI bundler
(:mod:`app.asyncapi_fileset`) *inlines* every cross-file reference, which breaks here: the inlined
``Shipment`` schema still says ``$ref: '#/components/schemas/Money'``, and in the root document that
pointer leads nowhere.

So this bundler **hoists** instead. A cross-file reference to ``#/components/<section>/<name>``
copies that component into the root's own ``components`` (under the same section and name) and
becomes the internal reference ``#/components/<section>/<name>``. References inside a hoisted
component are processed against the file it came from, so its own ``#/components/...`` references
are hoisted too, transitively. A reference to anything that is not a component (a whole file, or
some other pointer) is inlined, as the AsyncAPI bundler does.

A root that **registers** a whole file as one of its entries — ``components/schemas/Pet:
{$ref: components/schemas/Pet.json}``, a path item ``/pets: {$ref: paths/pets.json}`` or a Swagger
2.0 ``definitions`` entry, the layout a split export writes (COA-2.4, #7047) — gets that file's
content in place, and every other reference to the file (``../components/schemas/Pet.json``,
``Pet.json#/properties/id``, a ``discriminator.mapping`` value, a Link's ``operationRef``) becomes
the internal reference to the entry (``#/components/schemas/Pet``), so a split document bundles
back to the document it was split from. A reference with a URI scheme (``https://…``) is left as
written.

Only fileset members are read — never the network or the filesystem. A reference to a missing
member or pointer is ``INPUT_REFERENCE_UNRESOLVED``; two different definitions hoisted under one
component name are ``INPUT_SEMANTIC_INVALID`` rather than one silently winning.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional, Set, Tuple

from .asyncapi_fileset import _json_pointer_get, _resolve_member_path, _split_ref
from .fileset import IntakeFileset
from .import_ingestion import IngestionError, parse_document
from .import_source import ImportSourceError

__all__ = ["bundle_openapi_fileset", "references_fileset_members"]

_COMPONENT_PREFIX = "#/components/"


def _conflict(section: str, name: str, where: str) -> ImportSourceError:
    return ImportSourceError(
        f"Component {section}/{name} is defined differently in {where!r} and elsewhere in the "
        "fileset; rename one of them.",
        code="INPUT_SEMANTIC_INVALID",
    )


class _Bundler:
    """One bundling run: the parsed members, the root, and what has been hoisted so far."""

    def __init__(self, fileset: IntakeFileset) -> None:
        self.members = fileset.members
        self.root_path = fileset.root
        self.parsed: Dict[str, Any] = {}
        self.root = copy.deepcopy(self.load(self.root_path))
        if not isinstance(self.root, dict):
            raise ImportSourceError("The fileset's root document must be a mapping.", code="INPUT_MALFORMED")
        self.hoisted: Dict[Tuple[str, str], str] = {}
        self.inlining: Set[Tuple[str, str]] = set()
        # Hoisted components, kept apart from the root until the walk ends (the walk iterates
        # the root's own components while hoisting).
        self.extra: Dict[str, Dict[str, Any]] = {}
        # COA-2.4: members the root registers as one of its entries, mapped to that entry's
        # internal pointer (``#/components/schemas/Pet``).
        self.registered: Dict[str, str] = _registered_members(self.root, self.root_path)

    def load(self, path: str) -> Any:
        """Parse one member (cached)."""
        if path not in self.parsed:
            if path not in self.members:
                raise ImportSourceError(
                    f"The fileset has no member {path!r}, which a cross-file $ref needs.",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            try:
                self.parsed[path] = parse_document(self.members[path], source_label=path)
            except IngestionError as exc:
                raise ImportSourceError(
                    f"Fileset member {path!r} is not valid JSON/YAML: {exc}", code="INPUT_MALFORMED"
                ) from exc
        return self.parsed[path]

    def target(self, member: str, fragment: str, ref: str) -> Any:
        """The value ``fragment`` points at in ``member``."""
        try:
            return _json_pointer_get(self.load(member), fragment or "#")
        except ImportSourceError as exc:
            raise ImportSourceError(f"Unresolved $ref {ref!r}: {exc}", code="INPUT_REFERENCE_UNRESOLVED") from exc

    def hoist(self, member: str, fragment: str, ref: str) -> str:
        """Copy the component at ``member#fragment`` into the root and return its internal ref."""
        parts = fragment[len(_COMPONENT_PREFIX):].split("/")
        if len(parts) != 2 or not all(parts):
            return ""
        section, name = (p.replace("~1", "/").replace("~0", "~") for p in parts)
        internal = f"{_COMPONENT_PREFIX}{parts[0]}/{parts[1]}"
        key = (member, fragment)
        if key in self.hoisted:
            return self.hoisted[key]
        self.hoisted[key] = internal  # registered first, so a recursive component terminates
        value = self.process(copy.deepcopy(self.target(member, fragment, ref)), member)
        bucket = self.extra.setdefault(section, {})
        if name in bucket and bucket[name] != value:
            raise _conflict(section, name, member)
        bucket[name] = value
        return internal

    def process(self, value: Any, base: str) -> Any:
        """Rewrite every reference in ``value`` (which lives in member ``base``)."""
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and _has_scheme(ref):
                return {k: (v if k == "$ref" else self.process(v, base)) for k, v in value.items()}
            if isinstance(ref, str) and ref:
                registered = self.registered_pointer(ref, base)
                if registered is not None:
                    return {**value, "$ref": registered}
                file_part, fragment = _split_ref(ref)
                if file_part or base != self.root_path:
                    member = _resolve_member_path(base, file_part) if file_part else base
                    if member == self.root_path and fragment.startswith(_COMPONENT_PREFIX):
                        return {**value, "$ref": fragment}
                    if fragment.startswith(_COMPONENT_PREFIX):
                        internal = self.hoist(member, fragment, ref)
                        if internal:
                            return {**value, "$ref": internal}
                    key = (member, fragment)
                    if key in self.inlining:
                        raise ImportSourceError(f"Circular cross-file $ref at {ref!r}.", code="INPUT_SEMANTIC_INVALID")
                    self.inlining.add(key)
                    try:
                        return self.process(copy.deepcopy(self.target(member, fragment, ref)), member)
                    finally:
                        self.inlining.discard(key)
            return {k: self._process_member(k, v, base) for k, v in value.items()}
        if isinstance(value, list):
            return [self.process(v, base) for v in value]
        return value


    def _process_member(self, key: str, value: Any, base: str) -> Any:
        """Process one member of a mapping; reference *strings* (mapping, operationRef) are mapped too."""
        if key == "operationRef" and isinstance(value, str):
            return self.registered_pointer(value, base) or value
        if key == "mapping" and isinstance(value, dict):
            return {
                name: (self.registered_pointer(target, base) or target) if isinstance(target, str) else target
                for name, target in value.items()
            }
        return self.process(value, base)

    def registered_pointer(self, ref: str, base: str) -> Optional[str]:
        """The internal pointer for ``ref`` when it reaches a member the root registers, else ``None``.

        ``ref`` is written in member ``base``. A reference back into the root becomes its internal
        pointer too. An internal reference (``#/…``) is never rewritten (it already is one).
        """
        file_part, fragment = _split_ref(ref)
        if not file_part or _has_scheme(ref):
            return None
        try:
            member = _resolve_member_path(base, file_part)
        except ImportSourceError:
            return None
        if member == self.root_path:
            # A pointer back into the root (``../openapi.json#/components/securitySchemes/key``).
            return fragment if fragment.startswith("#/") else None
        pointer = self.registered.get(member)
        if pointer is None:
            return None
        if fragment and fragment != "#":
            if not fragment.startswith("#/"):
                return None
            return pointer + fragment[1:]
        return pointer

    def inline_registered(self) -> None:
        """Put each registered member's content where the root registers it."""
        for member, pointer in self.registered.items():
            tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[2:].split("/")]
            container = self.root
            for token in tokens[:-1]:
                container = container[token]
            entry = container[tokens[-1]]
            siblings = {k: v for k, v in entry.items() if k != "$ref"}
            content = self.process(copy.deepcopy(self.load(member)), member)
            if siblings and isinstance(content, dict):
                content = {**content, **siblings}
            container[tokens[-1]] = content


def _has_scheme(ref: str) -> bool:
    """Whether ``ref`` is an absolute URI (``https://…``, ``urn:…``) rather than a fileset path."""
    return "://" in ref or ref.startswith("urn:")


def _registered_members(root: Dict[str, Any], root_path: str) -> Dict[str, str]:
    """Members the root registers as a whole entry, mapped to the entry's internal pointer.

    An entry registers a member when it is a Reference Object to a whole file (no fragment):
    ``components/<section>/<name>``, ``paths/<path>`` and Swagger 2.0 ``definitions/<name>``. A
    member registered twice keeps its first entry.
    """
    def esc(token: str) -> str:
        return token.replace("~", "~0").replace("/", "~1")

    places = []
    components = root.get("components")
    if isinstance(components, dict):
        for section, entries in components.items():
            if isinstance(entries, dict):
                places.extend((f"#/components/{esc(section)}/{esc(name)}", entry) for name, entry in entries.items())
    for section in ("paths", "definitions"):
        entries = root.get(section)
        if isinstance(entries, dict):
            places.extend((f"#/{section}/{esc(name)}", entry) for name, entry in entries.items())

    registered: Dict[str, str] = {}
    for pointer, entry in places:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("$ref")
        if not isinstance(ref, str) or _has_scheme(ref):
            continue
        file_part, fragment = _split_ref(ref)
        if not file_part or fragment not in ("", "#"):
            continue
        member = _resolve_member_path(root_path, file_part)
        if member != root_path:
            registered.setdefault(member, pointer)
    return registered


def references_fileset_members(document: Any, path: str, fileset: IntakeFileset) -> bool:
    """Whether ``document`` (member ``path``) has a relative ``$ref`` to another member of ``fileset``.

    Args:
        document: The parsed member.
        path: The member's path in the fileset.
        fileset: The fileset it belongs to.

    Returns:
        ``True`` when at least one ``$ref`` names another member (so bundling has work to do).
    """
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and not _has_scheme(ref):
                file_part, _ = _split_ref(ref)
                if file_part:
                    try:
                        member = _resolve_member_path(path, file_part)
                    except ImportSourceError:
                        member = None
                    if member and member != path and member in fileset.members:
                        return True
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


def bundle_openapi_fileset(fileset: IntakeFileset, *, root: Optional[str] = None) -> Dict[str, Any]:
    """Bundle a split OpenAPI fileset into one self-contained document.

    Args:
        fileset: The root document plus the sibling members it references.
        root: Override for the root member path (defaults to ``fileset.root``).

    Returns:
        The root document with every cross-file component hoisted into its ``components`` and
        every other cross-file reference inlined.

    Raises:
        ImportSourceError: ``INPUT_MALFORMED`` for an unparseable member,
            ``INPUT_REFERENCE_UNRESOLVED`` for a missing member or pointer, and
            ``INPUT_SEMANTIC_INVALID`` for conflicting components or a circular inline.
    """
    if root is not None and root != fileset.root:
        fileset = IntakeFileset.from_members(dict(fileset.members), root=root)
    bundler = _Bundler(fileset)
    bundler.inline_registered()
    bundled = bundler.process(bundler.root, bundler.root_path)
    for section, entries in bundler.extra.items():
        components = bundled.setdefault("components", {})
        if not isinstance(components, dict):
            raise ImportSourceError("The root document's `components` is not a mapping.", code="INPUT_MALFORMED")
        bucket = components.setdefault(section, {})
        for name, value in entries.items():
            if name in bucket and bucket[name] != value:
                raise _conflict(section, name, "a sibling file")
            bucket[name] = value
    return bundled
