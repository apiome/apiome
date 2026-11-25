"""The provider's schemas, as the cross-contract comparison reads them — PFX-2.2 (#6926).

:mod:`app.pact_oas_compare` asks one question of a provider contract many times: *does this
value satisfy the schema at this place in the OpenAPI document?* This module answers it through
the IXH-5.1 validator (:func:`app.schema_instance_validation.validate_json_instance`) and keeps
everything about the document's dialect in one place.

Two views of one document
-------------------------
The comparison is not symmetric, so the document is read two ways:

* **request** — what the provider *accepts*. The consumer's request must satisfy the schema as
  written: a missing ``required`` property or an undeclared property under
  ``additionalProperties: false`` is the consumer's mistake.
* **response** — what the provider *returns*. A consumer rarely reads every field, so
  ``required`` is not held against its example. A field the consumer expects that the provider
  never declares is the failure worth finding, so every object is closed
  (``unevaluatedProperties: false``) unless the provider opened it itself. With ``required``
  gone a ``oneOf`` can no longer tell its branches apart, so it is read as ``anyOf``.

Both views are JSON Schema **2020-12**. An OpenAPI 3.0 document is brought there first:
``nullable: true`` becomes a ``"null"`` type and the boolean ``exclusiveMinimum`` /
``exclusiveMaximum`` become their numeric forms. No rewrite moves a node, so every JSON Pointer
means the same thing in a view as in the document the provider published.

Pure: no I/O, no clock, no network. A ``$ref`` that leaves the document is never fetched; the
schema that needs it is reported as unusable instead of being read as "accepts anything".
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote, unquote

from referencing import Registry

from .change_taxonomy_enum import json_pointer_escape
from .consumer_surface import SpecIndex
from .schema_instance_validation import (
    MAX_FINDINGS_CEILING,
    InstanceFinding,
    build_reference_registry,
    validate_json_instance,
)

__all__ = [
    "COMPOSITION_KEYWORDS",
    "MAX_SITE_FINDINGS",
    "REQUEST",
    "RESPONSE",
    "RESPONSE_PROBE",
    "ProviderSchemas",
    "pointer_tokens",
]

#: The view a request is checked in: the provider's schemas as written.
REQUEST = "request"

#: The view a response is checked in: ``required`` lifted, undeclared properties refused.
RESPONSE = "response"

#: The response view with every ``oneOf`` emptied, so that it fails wherever it is applied —
#: used only to learn whether a ``oneOf`` describes any part of one body.
RESPONSE_PROBE = "response-probe"

#: How many validator findings one schema site may contribute.
MAX_SITE_FINDINGS = 20

#: Keywords that make a schema a combination of others rather than one plain description.
COMPOSITION_KEYWORDS = ("allOf", "anyOf", "oneOf", "not", "if")

#: The JSON Schema dialect both views are validated under.
_DIALECT = "2020-12"

#: Keywords whose value is a map of name to schema.
_SCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")

#: Keywords whose value is a list of schemas.
_SCHEMA_LIST_KEYS = ("allOf", "anyOf", "oneOf", "prefixItems")

#: Keywords whose value is one schema.
_SCHEMA_CHILD_KEYS = (
    "items",
    "additionalProperties",
    "contains",
    "propertyNames",
    "then",
    "else",
    "not",
    "if",
)

#: Child keywords under which ``required`` keeps its meaning even in the response view: lifting
#: it inside a negation or a condition would invert what the provider wrote.
_NEVER_RELAXED = ("not", "if")

#: Child keywords that hold the schema of a *value* (as opposed to a branch of the same value).
_VALUE_CHILD_KEYS = ("items", "additionalProperties", "contains")

#: OpenAPI keys whose value is a map of *names* — the keys are data, not OpenAPI keywords.
_NAME_MAPS = (
    "callbacks",
    "content",
    "encoding",
    "headers",
    "links",
    "parameters",
    "pathItems",
    "paths",
    "requestBodies",
    "responses",
    "securitySchemes",
    "webhooks",
)

#: OpenAPI keys that hold example data, which must never be read as schemas.
_DATA_KEYS = ("example", "examples", "default")

#: Characters a JSON Pointer may carry unescaped inside a URI fragment.
_FRAGMENT_SAFE = "/~!$&'()*+,;=:@"


def pointer_tokens(pointer: str) -> List[str]:
    """Split a JSON Pointer into its unescaped reference tokens.

    Args:
        pointer: An RFC 6901 pointer (``""`` or one starting with ``/``).

    Returns:
        The tokens, in order; empty for the root pointer.
    """
    if not pointer:
        return []
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer.split("/")[1:]]


def _transform_schema(
    node: Any, *, oas30: bool, relax: bool, value_position: bool, probe_one_of: bool = False
) -> None:
    """Rewrite one schema, and every schema under it, in place for a view.

    Args:
        node: The schema node (anything that is not a mapping is left alone).
        oas30: Whether the document is OpenAPI 3.0 and needs its dialect brought to 2020-12.
        relax: Whether this is the response view (lift ``required``, close objects).
        value_position: Whether the node describes a whole value (a body, a property, an array
            item) rather than one branch of a combination. Only whole values are closed: a
            branch closed on its own would refuse its siblings' properties.
        probe_one_of: Empty every ``oneOf`` instead of reading it as ``anyOf``, so that the
            validator reports it wherever it applies to the instance.
    """
    if not isinstance(node, dict):
        return
    if oas30:
        if node.get("nullable") is True and isinstance(node.get("type"), str):
            node["type"] = [node["type"], "null"]
        node.pop("nullable", None)
        for bound, exclusive in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
            flag = node.get(exclusive)
            if isinstance(flag, bool):
                del node[exclusive]
                if flag and bound in node:
                    node[exclusive] = node.pop(bound)
    if relax:
        if isinstance(node.get("required"), list):
            del node["required"]
        if probe_one_of and isinstance(node.get("oneOf"), list):
            node["oneOf"] = []
        elif "oneOf" in node and "anyOf" not in node:
            node["anyOf"] = node.pop("oneOf")
        if value_position and "unevaluatedProperties" not in node:
            node["unevaluatedProperties"] = False

    for key in _SCHEMA_MAP_KEYS:
        children = node.get(key)
        if isinstance(children, dict):
            is_value = key in ("properties", "patternProperties")
            for child in children.values():
                _transform_schema(
                    child,
                    oas30=oas30,
                    relax=relax,
                    value_position=is_value,
                    probe_one_of=probe_one_of,
                )
    for key in _SCHEMA_LIST_KEYS:
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                _transform_schema(
                    child,
                    oas30=oas30,
                    relax=relax,
                    value_position=key == "prefixItems",
                    probe_one_of=probe_one_of,
                )
    for key in _SCHEMA_CHILD_KEYS:
        if key in node:
            _transform_schema(
                node[key],
                oas30=oas30,
                relax=relax and key not in _NEVER_RELAXED,
                value_position=key in _VALUE_CHILD_KEYS,
                probe_one_of=probe_one_of,
            )


def _transform_document(
    node: Any, *, oas30: bool, relax: bool, probe_one_of: bool = False
) -> None:
    """Rewrite every schema an OpenAPI document holds, in place.

    Args:
        node: A node of the document outside any schema.
        oas30: Whether the document is OpenAPI 3.0.
        relax: Whether to build the response view.
        probe_one_of: Build the probe view (see :data:`RESPONSE_PROBE`).
    """
    if isinstance(node, list):
        for item in node:
            _transform_document(item, oas30=oas30, relax=relax, probe_one_of=probe_one_of)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in _DATA_KEYS or key.startswith("x-"):
            continue
        if key == "schema":
            _transform_schema(
                value, oas30=oas30, relax=relax, value_position=True, probe_one_of=probe_one_of
            )
        elif key == "schemas" and isinstance(value, dict):
            for schema in value.values():
                _transform_schema(
                    schema,
                    oas30=oas30,
                    relax=relax,
                    value_position=False,
                    probe_one_of=probe_one_of,
                )
        elif key in _NAME_MAPS and isinstance(value, dict):
            for named in value.values():
                _transform_document(named, oas30=oas30, relax=relax, probe_one_of=probe_one_of)
        else:
            _transform_document(value, oas30=oas30, relax=relax, probe_one_of=probe_one_of)


class ProviderSchemas:
    """One provider OpenAPI document, ready to validate values and to be asked about its shape.

    Built once per comparison. The published document is never mutated: each view is a copy.
    """

    def __init__(self, document: Dict[str, Any]) -> None:
        """Prepare both views of a document.

        Args:
            document: The provider's OpenAPI 3.x document.
        """
        self.index = SpecIndex(document)
        self.oas30 = str(document.get("openapi", "")).strip().startswith("3.0")
        self._document = document
        self._views: Dict[str, Dict[str, Any]] = {}
        self._registries: Dict[str, Registry] = {}
        self._request_index = SpecIndex(self._view(REQUEST))
        self._one_of_cache: Dict[str, bool] = {}
        self._descend_cache: Dict[Tuple[str, Tuple[Any, ...]], Tuple[Optional[str], Optional[str]]] = {}

    # -----------------------------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------------------------

    def _view(self, side: str) -> Dict[str, Any]:
        """One view of the document, built on first use.

        Args:
            side: :data:`REQUEST`, :data:`RESPONSE` or :data:`RESPONSE_PROBE`.

        Returns:
            The rewritten copy of the document for that view.
        """
        if side not in self._views:
            view = copy.deepcopy(self._document)
            _transform_document(
                view,
                oas30=self.oas30,
                relax=side != REQUEST,
                probe_one_of=side == RESPONSE_PROBE,
            )
            self._views[side] = view
        return self._views[side]

    def _uri(self, side: str) -> str:
        """The in-memory URI a view is registered under.

        Args:
            side: :data:`REQUEST` or :data:`RESPONSE`.

        Returns:
            The URN; nothing is ever fetched from it.
        """
        return f"urn:apiome:pact-oas:{side}"

    def _registry(self, side: str) -> Registry:
        """The reference registry for a view, built on first use.

        Args:
            side: :data:`REQUEST` or :data:`RESPONSE`.

        Returns:
            A closed registry holding that view and nothing else.
        """
        if side not in self._registries:
            uri = self._uri(side)
            view = self._view(side)

            def retrieve(target: str) -> Optional[Dict[str, Any]]:
                """Serve the one view under comparison, and nothing else."""
                return view if target == uri else None

            self._registries[side], _ = build_reference_registry(
                {"$ref": f"{uri}#"}, retrieve=retrieve
            )
        return self._registries[side]

    def validate(
        self, side: str, pointer: str, instance: Any
    ) -> Optional[Tuple[List[InstanceFinding], int]]:
        """Validate a value against the schema at a pointer of the document.

        Args:
            side: :data:`REQUEST` or :data:`RESPONSE` — which view the schema is read in.
            pointer: JSON Pointer of the schema node in the document.
            instance: The parsed JSON value.

        Returns:
            ``(findings, total)`` — the ordered findings (at most :data:`MAX_SITE_FINDINGS`,
            branch detail of a failed ``anyOf`` / ``oneOf`` / ``not`` folded into its
            headline) and how many the validator produced. ``None`` when the schema could not
            be used at all (it does not compile, or needs a ``$ref`` outside the document):
            the value was **not** checked, which the caller must report, never assume a pass.
        """
        wrapper = {"$ref": f"{self._uri(side)}#{quote(pointer, safe=_FRAGMENT_SAFE)}"}
        try:
            result = validate_json_instance(
                wrapper,
                instance,
                dialect=_DIALECT,
                registry=self._registry(side),
                max_findings=MAX_SITE_FINDINGS * 4,
            )
        except Exception:  # noqa: BLE001 — a malformed target schema raises from deep inside
            # the keyword implementations (see app.example_conformance); a provider contract
            # that cannot be evaluated must degrade to "not compared", never crash the run.
            return None
        if not result.validated:
            return None
        headlines = [
            finding
            for finding in result.findings
            if finding.keyword in ("anyOf", "oneOf", "not")
        ]
        kept = [
            finding
            for finding in result.findings
            if not any(
                finding.schema_pointer.startswith(f"{headline.schema_pointer}/")
                and finding.pointer.startswith(headline.pointer)
                for headline in headlines
            )
        ]
        return kept[:MAX_SITE_FINDINGS], len(kept)

    # -----------------------------------------------------------------------------------------
    # Shape questions (all asked of the published document, in its own pointers)
    # -----------------------------------------------------------------------------------------

    def node(self, pointer: str, *, normalized: bool = False) -> Any:
        """Read a node of the document.

        Args:
            pointer: JSON Pointer of the node.
            normalized: Read it from the request view (2020-12 keywords) instead of the
                document as published.

        Returns:
            The node, or ``None`` when the pointer names nothing.
        """
        return (self._request_index if normalized else self.index).node_at(pointer)

    def follow(self, pointer: str) -> str:
        """Follow the local ``$ref`` chain starting at a schema node.

        Args:
            pointer: JSON Pointer of a node that may be a ``$ref``.

        Returns:
            The pointer of the node the chain ends at (the input when it is not a reference,
            or when the reference leaves the document or loops).
        """
        current = pointer
        seen: Set[str] = {pointer}
        while True:
            node = self.index.node_at(current)
            ref = node.get("$ref") if isinstance(node, dict) else None
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return current
            target = unquote(ref[1:])
            if target in seen or self.index.node_at(target) is None:
                return current
            seen.add(target)
            current = target

    def locate(self, site: str, schema_path: Sequence[str]) -> str:
        """Find where a validator schema path actually lives in the document.

        The validator reports a failing keyword by the path it walked from the schema site,
        which crosses ``$ref``\\ s without naming them. This walks the same path through the
        published document, hopping each reference it meets.

        Args:
            site: JSON Pointer of the schema the validation started at.
            schema_path: The validator's path from there, as unescaped tokens.

        Returns:
            The pointer of the deepest node of the path that exists in the document — the
            keyword itself when the provider wrote it, its schema when the view added it.
        """
        current = site
        for token in schema_path:
            node = self.index.node_at(current)
            if isinstance(node, dict) and token not in node:
                current = self.follow(current)
                node = self.index.node_at(current)
            key = token
            if isinstance(node, dict):
                if key not in node and key == "anyOf" and "oneOf" in node:
                    key = "oneOf"
                if key not in node:
                    return current
            elif isinstance(node, list):
                if not key.isdigit() or int(key) >= len(node):
                    return current
            else:
                return current
            current = f"{current}/{json_pointer_escape(key)}"
        return current

    def declared_properties(self, pointer: str) -> Optional[Set[str]]:
        """The property names an object schema declares, through references and combinations.

        Args:
            pointer: JSON Pointer of the object's schema.

        Returns:
            The names, or ``None`` when the schema is open (``additionalProperties`` or
            ``patternProperties``) so that no finite list exists.
        """
        names: Set[str] = set()
        seen: Set[str] = set()
        stack = [pointer]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node = self.index.node_at(current)
            if not isinstance(node, dict):
                continue
            if node.get("additionalProperties") not in (None, False) or node.get(
                "patternProperties"
            ):
                return None
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(str(name) for name in properties)
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                stack.append(unquote(ref[1:]))
            for key in ("allOf", "anyOf", "oneOf"):
                branches = node.get(key)
                if isinstance(branches, list):
                    stack.extend(f"{current}/{key}/{i}" for i in range(len(branches)))
        return names

    def one_of_applies(self, pointer: str, instance: Any) -> bool:
        """Whether any part of a response body is described by a ``oneOf``.

        The response view reads ``oneOf`` as ``anyOf`` (see the module docstring). That is a
        weaker check, and the caller has to say so — but only for a body the ``oneOf``
        actually describes, not for every response whose schema mentions one somewhere.

        Args:
            pointer: JSON Pointer of the response body's schema.
            instance: The expected body.

        Returns:
            True when the validator applies a ``oneOf`` of the schema to some part of the
            body. False when the schema reaches no ``oneOf``, or the body never gets there.
        """
        if not self.uses_one_of(pointer):
            return False
        wrapper = {"$ref": f"{self._uri(RESPONSE_PROBE)}#{quote(pointer, safe=_FRAGMENT_SAFE)}"}
        try:
            result = validate_json_instance(
                wrapper,
                instance,
                dialect=_DIALECT,
                registry=self._registry(RESPONSE_PROBE),
                max_findings=MAX_FINDINGS_CEILING,
            )
        except Exception:  # noqa: BLE001 — same reasoning as in validate()
            return False
        return any(finding.keyword == "oneOf" for finding in result.findings)

    def uses_one_of(self, pointer: str) -> bool:
        """Whether a schema reaches a ``oneOf`` anywhere, through references.

        Args:
            pointer: JSON Pointer of the schema.

        Returns:
            True when the response view had to read a ``oneOf`` as ``anyOf`` to check it.
        """
        if pointer in self._one_of_cache:
            return self._one_of_cache[pointer]
        found = False
        seen: Set[str] = set()
        stack = [pointer]
        while stack and not found:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            pending: List[Tuple[str, Any]] = [(current, self.index.node_at(current))]
            while pending and not found:
                where, node = pending.pop()
                if isinstance(node, list):
                    pending.extend((f"{where}/{i}", item) for i, item in enumerate(node))
                    continue
                if not isinstance(node, dict):
                    continue
                if isinstance(node.get("oneOf"), list):
                    found = True
                    break
                ref = node.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/"):
                    stack.append(unquote(ref[1:]))
                for key, value in node.items():
                    if key in _DATA_KEYS or key == "enum" or key == "const":
                        continue
                    pending.append((f"{where}/{json_pointer_escape(str(key))}", value))
        self._one_of_cache[pointer] = found
        return found

    def descend(self, pointer: str, steps: Sequence[Any]) -> Tuple[Optional[str], Optional[str]]:
        """Walk from a schema to the schema of a value inside it.

        Args:
            pointer: JSON Pointer of the starting schema.
            steps: The way down: a ``str`` names an object property, an ``int`` or ``None``
                an array element (``None`` for "any element").

        Returns:
            ``(pointer, None)`` with the pointer of the plain schema describing that value
            (references followed), or ``(None, reason)`` — ``"composition"`` when the way
            crosses an ``anyOf`` / ``oneOf`` / ``not`` / ``if`` or ends on a combined schema,
            ``"path-not-declared"`` when the provider declares nothing there.
        """
        # Every element of an array is described by the same ``items``, so the index is not
        # part of the question — and a thousand-element array asks it once.
        key = (pointer, tuple(None if isinstance(step, int) else step for step in steps))
        if key not in self._descend_cache:
            self._descend_cache[key] = self._descend(pointer, steps)
        return self._descend_cache[key]

    def _descend(self, pointer: str, steps: Sequence[Any]) -> Tuple[Optional[str], Optional[str]]:
        """Compute :meth:`descend` for one starting schema and one way down.

        Args:
            pointer: JSON Pointer of the starting schema.
            steps: The way down.

        Returns:
            What :meth:`descend` returns.
        """
        current = pointer
        for step in steps:
            found = self._descend_one(self.follow(current), step, depth=0)
            if found is None:
                return None, "path-not-declared"
            if found == "":
                return None, "composition"
            current = found
        final = self.follow(current)
        node = self.index.node_at(final)
        if not isinstance(node, dict):
            return None, "path-not-declared"
        if any(key in node for key in COMPOSITION_KEYWORDS):
            return None, "composition"
        return final, None

    def _descend_one(self, pointer: str, step: Any, *, depth: int) -> Optional[str]:
        """Take one step down from a schema whose references are already followed.

        Args:
            pointer: JSON Pointer of the schema.
            step: A property name (``str``) or an array element (``int`` / ``None``).
            depth: How many ``allOf`` levels deep the search already is.

        Returns:
            The child schema's pointer, ``""`` when a combination blocks the way, or ``None``
            when the schema declares nothing for the step.
        """
        node = self.index.node_at(pointer)
        if not isinstance(node, dict):
            return None
        if isinstance(step, str):
            properties = node.get("properties")
            if isinstance(properties, dict) and step in properties:
                return f"{pointer}/properties/{json_pointer_escape(step)}"
        else:
            items = node.get("items")
            if isinstance(items, dict):
                return f"{pointer}/items"
        branches = node.get("allOf")
        if isinstance(branches, list) and depth < 8:
            for position in range(len(branches)):
                found = self._descend_one(
                    self.follow(f"{pointer}/allOf/{position}"), step, depth=depth + 1
                )
                if found:
                    return found
        if any(key in node for key in COMPOSITION_KEYWORDS if key != "allOf"):
            return ""
        if isinstance(step, str) and isinstance(node.get("additionalProperties"), dict):
            return f"{pointer}/additionalProperties"
        return None
