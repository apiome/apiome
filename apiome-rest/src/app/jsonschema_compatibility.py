"""JSON Schema compatibility check: open vs closed content models — XPC-4.2 (#5746).

Whether a JSON Schema change is compatible depends on which side reads and which side writes, and
on the schema's **content model**: *open* when ``additionalProperties`` is absent or ``true`` (any
undeclared property is allowed), *closed* when it is ``false`` (or ``unevaluatedProperties`` is
``false``), *partially open* when it is a schema. This module compares two versions of one schema
the way Confluent Schema Registry and Apicurio do, and reports each difference with the
**direction** it breaks:

* ``backward`` — the **new** schema rejects data the **old** one accepted, so a new reader cannot
  read what old writers wrote (breaks ``BACKWARD`` and ``FULL``).
* ``forward`` — the **old** schema rejects data the **new** one accepts, so an old reader cannot
  read what new writers write (breaks ``FORWARD`` and ``FULL``).
* ``review`` — a keyword this check does not model moved (``not``, ``if``/``then``/``else``,
  ``patternProperties``, …), or a ``$ref`` that points outside the document changed; neither
  direction can be proven, so the change is flagged for review.

The rules (``rule`` is the stable slug; ``rule_id`` prefixes it with ``jsonschema.<direction>.``):

=====================================  ===========  ==============================================
Change                                 Direction    Rule
=====================================  ===========  ==============================================
Property added to a closed model       forward      ``closed-property-added``
Property removed from a closed model   backward     ``closed-property-removed``
Property added to an open model        backward     ``open-property-added``
Property removed from an open model    forward      ``open-property-removed``
``additionalProperties`` open→closed   backward     ``additional-properties-closed``
``additionalProperties`` closed→open   forward      ``additional-properties-opened``
``required`` entry added / removed     back / fwd   ``required-added`` / ``required-removed``
``enum`` / ``const`` lost / gained     back / fwd   ``enum-narrowed`` / ``enum-widened``
``type`` narrowed / widened / swapped  b / f / both ``type-narrowed`` / ``type-widened`` / ``type-changed``
``oneOf`` / ``anyOf`` branch removed   backward     ``one-of-branch-removed`` / ``any-of-branch-removed``
``oneOf`` / ``anyOf`` branch added     forward      ``one-of-branch-added`` / ``any-of-branch-added``
Bound tightened / loosened             back / fwd   ``<keyword>-tightened`` / ``<keyword>-loosened``
``pattern`` / ``format`` / …  changed  both         ``<keyword>-changed``
=====================================  ===========  ==============================================

``integer`` → ``number`` is a widening (every integer is a number): new readers accept old data, so
it breaks ``FORWARD`` only. A property added to a *partially open* model is compared against the
old ``additionalProperties`` schema (the old schema already constrained it), and a property removed
from one against the new.

``$ref`` targets are resolved inside each version's own document before comparing. Two references
that name the same top-level definition (``#/$defs/X``, ``#/definitions/X`` or the root ``#``) are
not followed: that definition is compared on its own, so its differences are reported once, where
they live. A reference whose target moved is followed on both sides; a reference cycle stops on
its second visit.

Annotations (``title``, ``description``, ``default``, ``examples``, ``deprecated``, ``readOnly``,
``writeOnly``, ``$comment``, vendor ``x-*`` keys) never change which data is valid and are ignored.

The module is pure: no I/O, deterministic for equal inputs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple
from urllib.parse import unquote

__all__ = [
    "BACKWARD",
    "FORWARD",
    "REVIEW",
    "COMPATIBILITY_MODES",
    "SchemaFinding",
    "compare_schemas",
    "content_model",
    "is_compatible",
    "mode_directions",
]

#: Finding directions (see the module docstring).
BACKWARD = "backward"
FORWARD = "forward"
REVIEW = "review"

#: Confluent compatibility mode → the directions a finding breaks under it. For one pair of
#: versions a ``*_TRANSITIVE`` mode checks the same directions as its plain form.
COMPATIBILITY_MODES: Dict[str, FrozenSet[str]] = {
    "BACKWARD": frozenset({BACKWARD}),
    "BACKWARD_TRANSITIVE": frozenset({BACKWARD}),
    "FORWARD": frozenset({FORWARD}),
    "FORWARD_TRANSITIVE": frozenset({FORWARD}),
    "FULL": frozenset({BACKWARD, FORWARD}),
    "FULL_TRANSITIVE": frozenset({BACKWARD, FORWARD}),
}

#: Upper bounds: lowering (or adding) one tightens the schema.
_UPPER_BOUNDS: Dict[str, str] = {
    "maximum": "maximum",
    "exclusiveMaximum": "exclusive-maximum",
    "maxLength": "max-length",
    "maxItems": "max-items",
    "maxProperties": "max-properties",
}

#: Lower bounds: raising (or adding) one tightens the schema.
_LOWER_BOUNDS: Dict[str, str] = {
    "minimum": "minimum",
    "exclusiveMinimum": "exclusive-minimum",
    "minLength": "min-length",
    "minItems": "min-items",
    "minProperties": "min-properties",
}

#: Constraints whose values cannot be ordered: adding one tightens, removing one loosens, and
#: replacing one may do either.
_EXACT_CONSTRAINTS: Dict[str, str] = {
    "pattern": "pattern",
    "multipleOf": "multiple-of",
    "format": "format",
}

#: Assertion keywords this check does not model. A change to one is reported as ``review``.
_UNMODELED = (
    "not",
    "if",
    "then",
    "else",
    "patternProperties",
    "propertyNames",
    "dependentRequired",
    "dependentSchemas",
    "dependencies",
    "contains",
    "minContains",
    "maxContains",
    "prefixItems",
    "additionalItems",
    "unevaluatedItems",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
)

#: A reference to a top-level definition (or the root), compared on its own rather than followed.
_NAMED_REF = re.compile(r"^#(/(\$defs|definitions)/[^/]+)?$")

#: Recursion ceiling: a backstop for pathological nesting (cycles are caught by the seen-set).
_MAX_DEPTH = 64


@dataclass(frozen=True)
class SchemaFinding:
    """One compatibility difference between two versions of a schema.

    Attributes:
        direction: :data:`BACKWARD`, :data:`FORWARD` or :data:`REVIEW` (see the module docstring).
        rule: The stable rule slug, e.g. ``closed-property-added``.
        path: Where in the schema the difference is, as JSON Pointer segments relative to the
            compared schema (``("properties", "address", "properties", "zip")``).
        message: One-line human explanation; property rules name the content model.
    """

    direction: str
    rule: str
    path: Tuple[str, ...]
    message: str

    @property
    def rule_id(self) -> str:
        """The stable rule id, e.g. ``jsonschema.forward.closed-property-added``."""
        return f"jsonschema.{self.direction}.{self.rule}"

    @property
    def property_name(self) -> Optional[str]:
        """The top-level property the finding sits under, or ``None`` for the schema itself."""
        if len(self.path) >= 2 and self.path[0] == "properties":
            return self.path[1]
        return None


def mode_directions(mode: str) -> FrozenSet[str]:
    """Return the directions a compatibility ``mode`` checks.

    Args:
        mode: A Confluent mode name (``BACKWARD``, ``FORWARD``, ``FULL``, optionally
            ``_TRANSITIVE``); case-insensitive.

    Returns:
        The set of directions (:data:`BACKWARD` / :data:`FORWARD`) that mode rejects.

    Raises:
        ValueError: If ``mode`` is not one of :data:`COMPATIBILITY_MODES`.
    """
    key = (mode or "").strip().upper()
    if key not in COMPATIBILITY_MODES:
        raise ValueError(f"unknown compatibility mode {mode!r}; expected one of {sorted(COMPATIBILITY_MODES)}")
    return COMPATIBILITY_MODES[key]


def is_compatible(findings: List[SchemaFinding], mode: str) -> bool:
    """Whether a pair of versions passes ``mode``, given their findings.

    ``review`` findings are not proven breaks, so they do not fail a mode; callers surface them
    separately.

    Args:
        findings: The output of :func:`compare_schemas`.
        mode: A Confluent mode name (see :func:`mode_directions`).

    Returns:
        ``True`` when no finding breaks a direction the mode checks.
    """
    directions = mode_directions(mode)
    return not any(f.direction in directions for f in findings)


def content_model(schema: Any) -> str:
    """Name a schema's content model: ``closed``, ``open`` or ``partially open``.

    Args:
        schema: A JSON Schema (mapping or boolean).

    Returns:
        ``closed`` when undeclared properties are rejected, ``partially open`` when they must
        match an ``additionalProperties`` schema, else ``open``.
    """
    extra = _additional(schema)
    if extra is False:
        return "closed"
    return "partially open" if extra else "open"


def compare_schemas(
    old: Any,
    new: Any,
    *,
    old_document: Optional[Mapping[str, Any]] = None,
    new_document: Optional[Mapping[str, Any]] = None,
) -> List[SchemaFinding]:
    """Compare two versions of a schema and list every compatibility difference.

    Args:
        old: The old version's schema (a mapping or a boolean schema).
        new: The new version's schema.
        old_document: The document ``old``'s local ``$ref``s resolve against; defaults to
            ``old`` itself.
        new_document: The document ``new``'s local ``$ref``s resolve against; defaults to
            ``new`` itself.

    Returns:
        The findings, in a stable order (schema walk order). Empty when the versions are
        compatible both ways.
    """
    walk = _Walk(
        old_document=old_document if old_document is not None else (old if isinstance(old, Mapping) else {}),
        new_document=new_document if new_document is not None else (new if isinstance(new, Mapping) else {}),
    )
    walk.compare(old, new, ())
    return walk.findings


# ===========================================================================
# Helpers
# ===========================================================================


def _canonical(value: Any) -> str:
    """A hashable, order-independent spelling of a JSON value (for set and equality checks)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _as_schema(schema: Any) -> Any:
    """Read the boolean schema ``true`` as ``{}``; leave ``false`` and mappings as they are."""
    if schema is True or schema is None:
        return {}
    return schema


def _trivial(schema: Any) -> bool:
    """Whether a schema accepts every value (``true`` or one without assertions)."""
    schema = _as_schema(schema)
    if not isinstance(schema, Mapping):
        return False
    return not any(k for k in schema if k not in _ANNOTATIONS and not str(k).startswith("x-"))


_ANNOTATIONS = frozenset(
    {
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "$comment",
        "$id",
        "$schema",
        "$anchor",
        "$dynamicAnchor",
        "$vocabulary",
        "$defs",
        "definitions",
    }
)


def _additional(schema: Any) -> Any:
    """Return the schema undeclared properties must match: ``False`` (closed) or a mapping.

    ``{}`` means fully open. ``unevaluatedProperties: false`` closes the model too.
    """
    if not isinstance(schema, Mapping):
        return False if schema is False else {}
    if schema.get("additionalProperties") is False or schema.get("unevaluatedProperties") is False:
        return False
    extra = schema.get("additionalProperties")
    return _as_schema(extra) if isinstance(extra, (Mapping, bool)) else {}


def _types(schema: Mapping[str, Any]) -> Optional[Set[str]]:
    """The JSON types a schema's ``type`` allows (``number`` implies ``integer``), or ``None`` for any."""
    declared = schema.get("type")
    if isinstance(declared, str):
        types = {declared}
    elif isinstance(declared, list):
        types = {t for t in declared if isinstance(t, str)}
    else:
        return None
    if "number" in types:
        types.add("integer")
    return types


def _enum(schema: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The values ``enum`` / ``const`` allow, keyed by canonical spelling, or ``None`` for any."""
    if "const" in schema:
        return {_canonical(schema["const"]): schema["const"]}
    values = schema.get("enum")
    if isinstance(values, list):
        return {_canonical(v): v for v in values}
    return None


def _decode_pointer(ref: str) -> List[str]:
    """Split a local ``$ref`` (``#/$defs/A~1B``) into unescaped JSON Pointer segments."""
    pointer = unquote(ref[1:])
    if not pointer:
        return []
    return [seg.replace("~1", "/").replace("~0", "~") for seg in pointer.lstrip("/").split("/")]


def _resolve_pointer(document: Mapping[str, Any], ref: str) -> Any:
    """Return what a local ``$ref`` points at in ``document``, or ``None`` when it does not resolve."""
    if not ref.startswith("#") or (len(ref) > 1 and not ref.startswith("#/")):
        return None  # an external URI or a plain-name anchor
    node: Any = document
    for segment in _decode_pointer(ref):
        if isinstance(node, Mapping) and segment in node:
            node = node[segment]
        elif isinstance(node, list) and segment.isdigit() and int(segment) < len(node):
            node = node[int(segment)]
        else:
            return None
    return node


def _show(value: Any) -> str:
    """A short display spelling of a JSON value for a finding's message."""
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def _where(path: Tuple[str, ...]) -> str:
    """A readable location for a path (``/properties/zip``, or ``the schema root``)."""
    return "/" + "/".join(path) if path else "the schema root"


# ===========================================================================
# The walk
# ===========================================================================


@dataclass
class _Walk:
    """State of one comparison: the two documents, the findings so far, and the cycle guard."""

    old_document: Mapping[str, Any]
    new_document: Mapping[str, Any]
    findings: List[SchemaFinding] = field(default_factory=list)
    #: Pairs being compared further up the walk (alive on the stack, so their ids are stable).
    _active: Set[Tuple[int, int]] = field(default_factory=set)

    def add(self, direction: str, rule: str, path: Tuple[str, ...], message: str) -> None:
        """Record one finding."""
        self.findings.append(SchemaFinding(direction=direction, rule=rule, path=path, message=message))

    def _deref(self, schema: Any, document: Mapping[str, Any]) -> Tuple[Any, Optional[str]]:
        """Follow ``schema``'s local ``$ref`` chain; return ``(schema, unresolved ref or None)``.

        Sibling keywords of a ``$ref`` are kept on top of its target (2020-12 applies both).
        """
        hops = 0
        while isinstance(schema, Mapping) and isinstance(schema.get("$ref"), str) and hops < 32:
            ref = schema["$ref"]
            target = _resolve_pointer(document, ref)
            if target is None:
                return schema, ref
            siblings = {k: v for k, v in schema.items() if k != "$ref"}
            target = _as_schema(target)
            schema = {**target, **siblings} if isinstance(target, Mapping) and siblings else target
            hops += 1
        return schema, None

    def compare(self, old: Any, new: Any, path: Tuple[str, ...], depth: int = 0) -> None:
        """Compare ``old`` against ``new`` at ``path`` and record their differences."""
        if depth > _MAX_DEPTH:
            return
        old, new = _as_schema(old), _as_schema(new)

        old_ref = old.get("$ref") if isinstance(old, Mapping) else None
        new_ref = new.get("$ref") if isinstance(new, Mapping) else None
        if isinstance(old_ref, str) and old_ref == new_ref and _NAMED_REF.match(old_ref):
            # Both name the same definition: it is compared on its own. Compare the siblings only.
            old = {k: v for k, v in old.items() if k != "$ref"}
            new = {k: v for k, v in new.items() if k != "$ref"}
        else:
            old, old_unresolved = self._deref(old, self.old_document)
            new, new_unresolved = self._deref(new, self.new_document)
            if (old_unresolved or new_unresolved) and old_unresolved != new_unresolved:
                self.add(
                    REVIEW,
                    "ref-changed",
                    path,
                    f"$ref at {_where(path)} changed from {_show(old_unresolved)} to {_show(new_unresolved)} "
                    "and points outside the document, so it cannot be compared",
                )
                return
        old, new = _as_schema(old), _as_schema(new)

        if old is False or new is False:
            self._compare_false(old, new, path)
            return
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            return
        if _canonical(old) == _canonical(new):
            return
        guard = (id(old), id(new))
        if guard in self._active:
            return  # a reference cycle: this pair is already being compared further up
        self._active.add(guard)
        try:
            self._compare_keywords(old, new, path, depth)
        finally:
            self._active.discard(guard)

    def _compare_keywords(
        self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...], depth: int
    ) -> None:
        """Apply every rule to two dereferenced, unequal schemas."""
        self._compare_types(old, new, path)
        self._compare_enum(old, new, path)
        self._compare_bounds(old, new, path)
        self._compare_exact(old, new, path)
        self._compare_unique_items(old, new, path)
        self._compare_object(old, new, path, depth)
        self._compare_items(old, new, path, depth)
        for keyword, slug in (("oneOf", "one-of"), ("anyOf", "any-of")):
            self._compare_branches(old, new, keyword, slug, path, depth)
        self._compare_all_of(old, new, path, depth)
        self._compare_unmodeled(old, new, path)

    # -- leaf rules ---------------------------------------------------------

    def _compare_false(self, old: Any, new: Any, path: Tuple[str, ...]) -> None:
        """A ``false`` schema accepts nothing: becoming one narrows, ceasing to be one widens."""
        if old is False and new is False:
            return
        if new is False:
            self.add(
                BACKWARD,
                "schema-rejects-all",
                path,
                f"the schema at {_where(path)} became `false` and rejects every value",
            )
        else:
            self.add(
                FORWARD,
                "schema-accepts-values",
                path,
                f"the schema at {_where(path)} was `false` and now accepts values",
            )

    def _compare_types(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """``type``: losing a type is a backward break, gaining one (``integer`` → ``number``) forward."""
        old_types, new_types = _types(old), _types(new)
        if old_types == new_types:
            return
        if old_types is None:
            lost, gained = {"*"}, set()  # any type -> some types
        elif new_types is None:
            lost, gained = set(), {"*"}  # some types -> any type
        else:
            lost, gained = old_types - new_types, new_types - old_types
        before, after = _show(old.get("type", "any")), _show(new.get("type", "any"))
        if lost and gained:
            message = f"type at {_where(path)} changed from {before} to {after}"
            self.add(BACKWARD, "type-changed", path, message)
            self.add(FORWARD, "type-changed", path, message)
        elif lost:
            self.add(BACKWARD, "type-narrowed", path, f"type at {_where(path)} narrowed from {before} to {after}")
        elif gained:
            self.add(
                FORWARD,
                "type-widened",
                path,
                f"type at {_where(path)} widened from {before} to {after}; only new readers accept the wider values",
            )

    def _compare_enum(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """``enum`` / ``const``: losing a value is a backward break, gaining one forward."""
        old_values, new_values = _enum(old), _enum(new)
        if old_values == new_values:
            return
        if new_values is not None:
            lost = [old_values[k] for k in old_values if k not in new_values] if old_values is not None else None
            if lost is None:
                self.add(
                    BACKWARD,
                    "enum-narrowed",
                    path,
                    f"an enum was added at {_where(path)}; other values are now rejected",
                )
            elif lost:
                self.add(BACKWARD, "enum-narrowed", path, f"enum at {_where(path)} no longer allows {_show(lost)}")
        if old_values is not None:
            gained = [new_values[k] for k in new_values if k not in old_values] if new_values is not None else None
            if gained is None:
                self.add(
                    FORWARD, "enum-widened", path, f"the enum at {_where(path)} was removed; any value is now accepted"
                )
            elif gained:
                self.add(FORWARD, "enum-widened", path, f"enum at {_where(path)} now also allows {_show(gained)}")

    def _compare_bounds(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """Ordered bounds (``maximum``, ``maxLength``, ``minimum``, …): tightened back, loosened fwd."""
        for keywords, upper in ((_UPPER_BOUNDS, True), (_LOWER_BOUNDS, False)):
            for keyword, slug in keywords.items():
                before, after = old.get(keyword), new.get(keyword)
                if isinstance(before, bool) or isinstance(after, bool):
                    self._compare_exact_keyword(keyword, slug, before, after, path)  # draft-4 boolean form
                    continue
                before = before if _is_number(before) else None
                after = after if _is_number(after) else None
                if before == after:
                    continue
                if after is None:
                    tightened = False
                elif before is None:
                    tightened = True
                else:
                    tightened = after < before if upper else after > before
                if tightened:
                    self.add(
                        BACKWARD,
                        f"{slug}-tightened",
                        path,
                        f"{keyword} at {_where(path)} tightened from {_show(before)} to {_show(after)}",
                    )
                else:
                    self.add(
                        FORWARD,
                        f"{slug}-loosened",
                        path,
                        f"{keyword} at {_where(path)} loosened from {_show(before)} to {_show(after)}",
                    )

    def _compare_exact(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """Unordered constraints (``pattern``, ``multipleOf``, ``format``)."""
        for keyword, slug in _EXACT_CONSTRAINTS.items():
            self._compare_exact_keyword(keyword, slug, old.get(keyword), new.get(keyword), path)

    def _compare_exact_keyword(self, keyword: str, slug: str, before: Any, after: Any, path: Tuple[str, ...]) -> None:
        """Added → tightened (backward), removed → loosened (forward), replaced → changed (both)."""
        if before in (None, False) and after in (None, False):
            return
        if _canonical(before) == _canonical(after):
            return
        if before in (None, False):
            self.add(BACKWARD, f"{slug}-tightened", path, f"{keyword} {_show(after)} was added at {_where(path)}")
        elif after in (None, False):
            self.add(FORWARD, f"{slug}-loosened", path, f"{keyword} {_show(before)} was removed at {_where(path)}")
        else:
            message = f"{keyword} at {_where(path)} changed from {_show(before)} to {_show(after)}"
            self.add(BACKWARD, f"{slug}-changed", path, message)
            self.add(FORWARD, f"{slug}-changed", path, message)

    def _compare_unique_items(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """``uniqueItems``: turning it on tightens, turning it off loosens."""
        before, after = old.get("uniqueItems") is True, new.get("uniqueItems") is True
        if before and not after:
            self.add(FORWARD, "unique-items-loosened", path, f"uniqueItems was turned off at {_where(path)}")
        elif after and not before:
            self.add(BACKWARD, "unique-items-tightened", path, f"uniqueItems was turned on at {_where(path)}")

    def _compare_unmodeled(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...]) -> None:
        """A keyword this check does not model moved: flag it for review."""
        keywords = list(_UNMODELED)
        if isinstance(old.get("items"), list) or isinstance(new.get("items"), list):
            keywords.append("items")  # draft-4 tuple form
        if isinstance(old.get("unevaluatedProperties"), Mapping) or isinstance(
            new.get("unevaluatedProperties"), Mapping
        ):
            keywords.append("unevaluatedProperties")  # only its `false` form is the content model
        for keyword in keywords:
            if _canonical(old.get(keyword)) != _canonical(new.get(keyword)):
                self.add(
                    REVIEW,
                    "unmodeled-keyword-changed",
                    path,
                    f"`{keyword}` changed at {_where(path)}; the JSON Schema check does not model it",
                )

    # -- structure rules ------------------------------------------------------

    def _compare_object(
        self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...], depth: int
    ) -> None:
        """Properties, ``required`` and ``additionalProperties`` under the open/closed content model."""
        object_keys = ("properties", "additionalProperties", "unevaluatedProperties", "required")
        if not any(k in old or k in new for k in object_keys):
            return
        old_extra, new_extra = _additional(old), _additional(new)
        old_props = old.get("properties") if isinstance(old.get("properties"), Mapping) else {}
        new_props = new.get("properties") if isinstance(new.get("properties"), Mapping) else {}

        if old_extra is not False and new_extra is False:
            self.add(
                BACKWARD,
                "additional-properties-closed",
                path,
                f"the content model at {_where(path)} went from {content_model(old)} to closed "
                "(additionalProperties: false); old data with undeclared properties is rejected",
            )
        elif old_extra is False and new_extra is not False:
            self.add(
                FORWARD,
                "additional-properties-opened",
                path,
                f"the content model at {_where(path)} went from closed to {content_model(new)}; "
                "new data may carry properties old readers reject",
            )
        elif old_extra is not False and new_extra is not False:
            self.compare(old_extra, new_extra, path + ("additionalProperties",), depth + 1)

        for name in new_props:
            if name in old_props:
                self.compare(old_props[name], new_props[name], path + ("properties", name), depth + 1)
            else:
                self._property_added(name, old, old_extra, new_props[name], path, depth)
        for name in old_props:
            if name not in new_props:
                self._property_removed(name, new, new_extra, old_props[name], path, depth)

        old_required = set(r for r in old.get("required") or () if isinstance(r, str))
        new_required = set(r for r in new.get("required") or () if isinstance(r, str))
        for name in sorted(new_required - old_required):
            self.add(
                BACKWARD,
                "required-added",
                path + ("properties", name),
                f"property `{name}` became required at {_where(path)}; old data may omit it",
            )
        for name in sorted(old_required - new_required):
            self.add(
                FORWARD,
                "required-removed",
                path + ("properties", name),
                f"property `{name}` is no longer required at {_where(path)}; old readers expect it",
            )

    def _property_added(
        self, name: str, old: Mapping[str, Any], old_extra: Any, schema: Any, path: Tuple[str, ...], depth: int
    ) -> None:
        """Grade a property the new version declares and the old did not."""
        at = path + ("properties", name)
        if old_extra is False:
            self.add(
                FORWARD,
                "closed-property-added",
                at,
                f"property `{name}` was added to a closed content model (additionalProperties: false) at "
                f"{_where(path)}; old readers reject data that carries it",
            )
        elif old_extra == {}:
            if not _trivial(schema):
                self.add(
                    BACKWARD,
                    "open-property-added",
                    at,
                    f"property `{name}` was added to an open content model at {_where(path)}; old data may "
                    "already carry it with a value the new schema rejects",
                )
        else:
            # Partially open: the old ``additionalProperties`` schema already constrained the name.
            self.compare(old_extra, schema, at, depth + 1)

    def _property_removed(
        self, name: str, new: Mapping[str, Any], new_extra: Any, schema: Any, path: Tuple[str, ...], depth: int
    ) -> None:
        """Grade a property the old version declared and the new does not."""
        at = path + ("properties", name)
        if new_extra is False:
            self.add(
                BACKWARD,
                "closed-property-removed",
                at,
                f"property `{name}` was removed from a closed content model (additionalProperties: false) at "
                f"{_where(path)}; old data that carries it is rejected",
            )
        elif new_extra == {}:
            if not _trivial(schema):
                self.add(
                    FORWARD,
                    "open-property-removed",
                    at,
                    f"property `{name}` was removed from an open content model at {_where(path)}; new data may "
                    "carry it with a value old readers reject",
                )
        else:
            self.compare(schema, new_extra, at, depth + 1)

    def _compare_items(self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...], depth: int) -> None:
        """Array ``items`` (single-schema form)."""
        old_items, new_items = old.get("items"), new.get("items")
        if isinstance(old_items, list) or isinstance(new_items, list):
            return  # draft-4 tuple form: reported as unmodeled
        if old_items is None and new_items is None:
            return
        self.compare(old_items, new_items, path + ("items",), depth + 1)

    def _compare_branches(
        self, old: Mapping[str, Any], new: Mapping[str, Any], keyword: str, slug: str, path: Tuple[str, ...], depth: int
    ) -> None:
        """``oneOf`` / ``anyOf``: a removed branch is a backward break, an added one forward.

        Branches are matched by equal content (so a ``$ref`` branch matches the same ``$ref``). The
        unmatched branches left on each side are paired by position and compared when both sides
        have the same number; otherwise they are reported as removed and added.
        """
        old_branches = old.get(keyword) if isinstance(old.get(keyword), list) else []
        new_branches = new.get(keyword) if isinstance(new.get(keyword), list) else []
        if not old_branches and not new_branches:
            return
        new_left = [(i, b) for i, b in enumerate(new_branches)]
        old_left: List[Tuple[int, Any]] = []
        for index, branch in enumerate(old_branches):
            match = next((pos for pos, (_, b) in enumerate(new_left) if _canonical(b) == _canonical(branch)), None)
            if match is None:
                old_left.append((index, branch))
            else:
                new_left.pop(match)
        if old_left and len(old_left) == len(new_left):
            for (_, before), (index, after) in zip(old_left, new_left):
                self.compare(before, after, path + (keyword, str(index)), depth + 1)
            return
        for index, branch in old_left:
            self.add(
                BACKWARD,
                f"{slug}-branch-removed",
                path + (keyword, str(index)),
                f"{keyword} branch {_show(branch)} was removed at {_where(path)}",
            )
        for index, branch in new_left:
            self.add(
                FORWARD,
                f"{slug}-branch-added",
                path + (keyword, str(index)),
                f"{keyword} branch {_show(branch)} was added at {_where(path)}",
            )

    def _compare_all_of(
        self, old: Mapping[str, Any], new: Mapping[str, Any], path: Tuple[str, ...], depth: int
    ) -> None:
        """``allOf``: compared part by part when both sides have the same number of parts."""
        old_parts = old.get("allOf") if isinstance(old.get("allOf"), list) else []
        new_parts = new.get("allOf") if isinstance(new.get("allOf"), list) else []
        if _canonical(old_parts) == _canonical(new_parts):
            return
        if len(old_parts) != len(new_parts):
            self.add(
                REVIEW,
                "unmodeled-keyword-changed",
                path,
                f"`allOf` gained or lost parts at {_where(path)}; the JSON Schema check does not model it",
            )
            return
        for index, (before, after) in enumerate(zip(old_parts, new_parts)):
            self.compare(before, after, path + ("allOf", str(index)), depth + 1)


def _is_number(value: Any) -> bool:
    """Whether ``value`` is a JSON number (``bool`` is not)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
