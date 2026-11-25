"""Generate a Pact v4 file from a declared consumer surface — PFX-2.6 (#6930).

A consumer registered through the UI picker (CTG-4.1) has said *which* operations and fields it
uses, but it has no Pact file: nothing a Pact Broker, a verifier or a bi-directional comparison
can read. This module writes one. Each declared operation becomes one ``Synchronous/HTTP``
interaction per response status the consumer reads, carrying only the fields it declared, with
the specification's own **examples** as the sample values.

Where the sample values come from
---------------------------------
For a body, the first of these that exists wins, at every level of the body:

1. the media type's ``example``, or the first of its ``examples`` (the whole-body example an
   author wrote);
2. the schema's ``example``, the first of its ``examples`` (OpenAPI 3.1), ``default``, ``const``
   or first ``enum`` value — read from the field's own schema, then from a parent object's;
3. a **placeholder** of the declared type (``"string"``, ``0``, ``true``, a format-shaped string
   for ``date-time`` / ``uuid`` / ``email`` / ``uri``), reported as a finding.

A parameter reads its own ``example`` / ``examples``, then its schema the same way.

What the file promises
----------------------
* **Only declared fields.** A response body carries the fields the consumer reads and the
  objects that hold them, nothing else; a request body carries the fields it sends. A field
  declared as a whole object (no children declared) carries the object's example in full.
* **Response values are matched by type.** The sample values are documentation, not the
  provider's real data, so every response body carries one cascading ``type`` matcher at ``$``:
  the provider must return the same shape, not the same values. Request bodies carry none —
  they are what this consumer sends.
* **Deterministic.** The same contract revision against the same specification always produces
  the same document, so publishing it twice is one pact version (:func:`app.pact_publication.
  pact_content_sha`).

Nothing is dropped silently
---------------------------
Every place the generator had to invent or leave something out is an :class:`ExportFinding`:
``placeholder`` when a value was invented (the interaction is still written), ``omitted`` when a
field, a response or an operation could not be written at all — with a stable reason code from
:data:`EXPORT_REASONS`. Interactions the stored contract itself could not resolve are carried
over as ``omitted`` / ``contract-unresolved``.

Pure: no database, no network, no clock. The specification arrives as a
:class:`~app.consumer_surface.SpecIndex`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractRecord,
)
from .consumer_surface import SpecIndex

__all__ = [
    "EXPORT_OUTCOMES",
    "EXPORT_REASONS",
    "OUTCOME_OMITTED",
    "OUTCOME_PLACEHOLDER",
    "PACT_SPECIFICATION_VERSION",
    "ExportFinding",
    "PactExport",
    "build_consumer_pact",
]

#: The Pact specification version every exported file declares.
PACT_SPECIFICATION_VERSION = "4.0"

#: A value was invented (the interaction is still written).
OUTCOME_PLACEHOLDER = "placeholder"
#: Something could not be written at all.
OUTCOME_OMITTED = "omitted"
EXPORT_OUTCOMES = (OUTCOME_PLACEHOLDER, OUTCOME_OMITTED)

#: Why a finding was raised. Stable codes — a client branches on them, never on the message.
EXPORT_REASONS = (
    # placeholder
    "no-example",
    "status-range",
    "complex-parameter-value",
    # omitted
    "contract-unresolved",
    "operation-not-found",
    "field-not-found",
    "parameter-not-declared",
    "status-default",
    "status-not-numeric",
    "no-response-declared",
    "media-type-not-json",
    "media-type-conflict",
)

#: How deep a generated value may nest before it is cut off with a placeholder. Guards a
#: self-referencing ``items`` chain, which no declared path bounds.
_MAX_VALUE_DEPTH = 32

#: A response status range key (``2XX``).
_STATUS_RANGE = re.compile(r"^([1-5])XX$", re.IGNORECASE)

#: Format-shaped placeholders, so an invented string still satisfies the declared format.
_FORMAT_PLACEHOLDERS: Dict[str, str] = {
    "date-time": "2026-01-01T00:00:00Z",
    "date": "2026-01-01",
    "time": "00:00:00Z",
    "uuid": "00000000-0000-4000-8000-000000000000",
    "email": "user@example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
}

#: Composition keywords searched (in this order) for an example the outer schema lacks.
_COMPOSITION_KEYWORDS = ("allOf", "oneOf", "anyOf")

#: Marks "no example here" — distinct from an example whose value is ``null``.
_MISSING: Any = object()


class ExportFinding(BaseModel):
    """One place the generated pact is weaker than, or different from, the declared surface.

    Attributes:
        outcome: ``placeholder`` (a value was invented) or ``omitted`` (nothing was written).
        reason: One of :data:`EXPORT_REASONS`.
        message: What happened, for a person.
        method: The operation's method, upper case, when the finding is about one.
        path: The operation's path template.
        status: The response status involved, when there is one.
        location: ``response``, ``request`` or ``parameter``, for a field-level finding.
        field: The field's dotted data path or parameter name.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(description="placeholder | omitted.")
    reason: str = Field(description=f"One of: {', '.join(EXPORT_REASONS)}.")
    message: str = Field(description="What happened.")
    method: Optional[str] = Field(default=None, description="Operation method, upper case.")
    path: Optional[str] = Field(default=None, description="Operation path template.")
    status: Optional[str] = Field(default=None, description="Response status involved.")
    location: Optional[str] = Field(default=None, description="response | request | parameter.")
    field: Optional[str] = Field(default=None, description="Field data path or parameter name.")


@dataclass
class PactExport:
    """A generated pact and the report that goes with it.

    Attributes:
        document: The Pact v4 document.
        interaction_count: How many interactions it carries.
        findings: Every placeholder and omission, in operation order.
    """

    document: Dict[str, Any]
    interaction_count: int
    findings: List[ExportFinding] = dataclass_field(default_factory=list)


# =============================================================================================
# Small helpers
# =============================================================================================


def _as_dict(value: Any) -> Dict[str, Any]:
    """The value when it is a mapping, else an empty dict."""
    return dict(value) if isinstance(value, Mapping) else {}


def _is_json_media_type(media_type: Optional[str]) -> bool:
    """Whether a media type carries a JSON body (``application/json``, ``*/*+json``)."""
    lowered = (media_type or "").split(";", 1)[0].strip().lower()
    return lowered == "application/json" or lowered.endswith("+json") or lowered.endswith("/json")


def _schema_types(schema: Mapping[str, Any]) -> List[str]:
    """The declared JSON types of a schema, ``null`` last (3.1 allows a list)."""
    declared = schema.get("type")
    if isinstance(declared, str):
        return [declared]
    if isinstance(declared, list):
        names = [str(t) for t in declared if isinstance(t, str)]
        return [t for t in names if t != "null"] + [t for t in names if t == "null"]
    return []


def _is_array_schema(schema: Mapping[str, Any]) -> bool:
    """Whether a schema describes an array."""
    types = _schema_types(schema)
    return (bool(types) and types[0] == "array") or (not types and "items" in schema)


def _placeholder(schema: Mapping[str, Any]) -> Any:
    """A value of the schema's declared type, for a field no example covers.

    Args:
        schema: The (resolved) field schema.

    Returns:
        A format-shaped string, the declared ``minimum`` (or 0) for a number, ``True``, ``{}``,
        ``[]``, ``None`` for a ``null``-only schema, else ``"string"``.
    """
    types = _schema_types(schema)
    kind = types[0] if types else ("object" if "properties" in schema else "string")
    if kind == "string":
        return _FORMAT_PLACEHOLDERS.get(str(schema.get("format", "")).lower(), "string")
    if kind in ("integer", "number"):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and minimum > 0:
            return int(minimum) if kind == "integer" else minimum
        return 0
    if kind == "boolean":
        return True
    if kind == "object":
        return {}
    if kind == "array":
        return []
    if kind == "null":
        return None
    return "string"


def _parameter_text(value: Any) -> Tuple[List[str], bool]:
    """Render a parameter example the way it travels on the wire.

    Args:
        value: The example value.

    Returns:
        ``(values, complex)`` — one string per value (an array example is several values of a
        repeated query parameter), and whether an object had to be serialized as JSON text.
    """
    if isinstance(value, bool):
        return ["true" if value else "false"], False
    if isinstance(value, list):
        rendered: List[str] = []
        complex_value = False
        for item in value:
            part, nested = _parameter_text(item)
            rendered.extend(part)
            complex_value = complex_value or nested
        return rendered, complex_value
    if isinstance(value, dict):
        return [json.dumps(value, sort_keys=True, separators=(",", ":"))], True
    if value is None:
        return [""], False
    return [str(value)], False


# =============================================================================================
# The generator
# =============================================================================================


class _Generator:
    """Builds one pact from one contract revision. Holds the findings while it works."""

    def __init__(self, index: SpecIndex) -> None:
        """Start a generator.

        Args:
            index: The specification the contract was declared against.
        """
        self.index = index
        self.findings: List[ExportFinding] = []

    # -----------------------------------------------------------------------------------------
    # Findings
    # -----------------------------------------------------------------------------------------

    def _report(
        self,
        outcome: str,
        reason: str,
        message: str,
        operation: Optional[ConsumerContractOperation] = None,
        *,
        status: Optional[str] = None,
        location: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        """Record one finding."""
        self.findings.append(
            ExportFinding(
                outcome=outcome,
                reason=reason,
                message=message,
                method=operation.method.upper() if operation else None,
                path=operation.path if operation else None,
                status=status,
                location=location,
                field=field,
            )
        )

    # -----------------------------------------------------------------------------------------
    # Examples
    # -----------------------------------------------------------------------------------------

    def _resolve(self, node: Any) -> Dict[str, Any]:
        """Follow a node's local ``$ref`` chain and return it as a dict."""
        resolved, _ = self.index.resolve_reference(node)
        return _as_dict(resolved)

    def _first_example_value(self, examples: Any) -> Any:
        """The ``value`` of the first Example Object in an ``examples`` map, or ``_MISSING``."""
        for _name, example in _as_dict(examples).items():
            resolved = self._resolve(example)
            if "value" in resolved:
                return resolved["value"]
        return _MISSING

    def _schema_example(self, schema: Any, depth: int = 0) -> Any:
        """The example a schema declares for itself, or ``_MISSING``.

        Args:
            schema: A schema node, possibly a ``$ref``.
            depth: Composition nesting so far (cycle guard).

        Returns:
            ``example``, the first of ``examples`` (3.1), ``default``, ``const`` or the first
            ``enum`` value — else the same search in each ``allOf`` / ``oneOf`` / ``anyOf``
            branch — else ``_MISSING``.
        """
        node = self._resolve(schema)
        if "example" in node:
            return node["example"]
        examples = node.get("examples")
        if isinstance(examples, list) and examples:
            return examples[0]
        for keyword in ("default", "const"):
            if keyword in node:
                return node[keyword]
        enum = node.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
        if depth < _MAX_VALUE_DEPTH:
            for keyword in _COMPOSITION_KEYWORDS:
                branches = node.get(keyword)
                for branch in branches if isinstance(branches, list) else []:
                    found = self._schema_example(branch, depth + 1)
                    if found is not _MISSING:
                        return found
        return _MISSING

    # -----------------------------------------------------------------------------------------
    # Bodies
    # -----------------------------------------------------------------------------------------

    def _field_schema(
        self, entry: Any, location: str, path: str, status: Optional[str], media_type: str
    ) -> Optional[Dict[str, Any]]:
        """The schema node of one body data path, or ``None`` when it no longer resolves."""
        resolved, _reason = self.index.resolve_field(
            entry, location=location, path=path, status=status, media_type=media_type
        )
        if resolved is None:
            return None
        return self._resolve(self.index.node_at(resolved.schema_pointer))

    def _media_example(self, root: ConsumerContractField) -> Any:
        """The whole-body example the media type declares, or ``_MISSING``.

        Args:
            root: The body root as :meth:`SpecIndex.resolve_field` returns it for path ``""``;
                its ``pointer`` ends in ``/<media type>/schema``.
        """
        media_pointer = root.pointer[: -len("/schema")] if root.pointer.endswith("/schema") else root.pointer
        media = _as_dict(self.index.node_at(media_pointer))
        if "example" in media:
            return media["example"]
        return self._first_example_value(media.get("examples"))

    def build_body(
        self,
        operation: ConsumerContractOperation,
        entry: Any,
        *,
        location: str,
        status: Optional[str],
        media_type: str,
        paths: Sequence[str],
    ) -> Any:
        """Build a request or response body carrying exactly the declared fields.

        Args:
            operation: The declared operation (for findings).
            entry: Its indexed operation.
            location: ``request`` or ``response``.
            status: The response status, for a response.
            media_type: The body's media type.
            paths: The declared dotted data paths.

        Returns:
            The body value, or ``_MISSING`` when not even the body root resolves (every declared
            field is then reported as omitted).
        """
        root, _reason = self.index.resolve_field(
            entry, location=location, path="", status=status, media_type=media_type
        )
        if root is None:
            for path in paths:
                self._report(
                    OUTCOME_OMITTED,
                    "field-not-found",
                    f"the {location} body under {media_type} is no longer declared",
                    operation,
                    status=status,
                    location=location,
                    field=path,
                )
            return _MISSING

        children: Dict[str, List[str]] = {}
        for path in sorted(set(paths)):
            if not path:
                continue
            if self._field_schema(entry, location, path, status, media_type) is None:
                self._report(
                    OUTCOME_OMITTED,
                    "field-not-found",
                    f"the {location} field '{path}' is no longer in the specification",
                    operation,
                    status=status,
                    location=location,
                    field=path,
                )
                continue
            segments = path.split(".")
            for depth in range(len(segments)):
                parent = ".".join(segments[:depth])
                child = segments[depth]
                siblings = children.setdefault(parent, [])
                if child not in siblings:
                    siblings.append(child)

        context = _BodyContext(operation, entry, location, status, media_type, children)
        root_schema = self._resolve(self.index.node_at(root.schema_pointer))
        return self._value(context, "", root_schema, self._media_example(root), 0)

    def _value(self, context: "_BodyContext", prefix: str, schema: Dict[str, Any], example: Any, depth: int) -> Any:
        """The value of one body node: an example, a built object or array, or a placeholder.

        Args:
            context: The body being built.
            prefix: The node's dotted data path (``""`` for the root).
            schema: The node's resolved schema.
            example: The example handed down from the parent, or ``_MISSING``.
            depth: Nesting so far.

        Returns:
            The value.
        """
        if example is _MISSING:
            example = self._schema_example(schema)
        if depth >= _MAX_VALUE_DEPTH:
            return self._leaf(context, prefix, schema, example)
        if _is_array_schema(schema):
            element = example[0] if isinstance(example, list) and example else _MISSING
            if not context.children.get(prefix) and isinstance(example, list):
                return example
            return [self._value(context, prefix, self._resolve(schema.get("items")), element, depth + 1)]
        names = context.children.get(prefix, [])
        if not names:
            return self._leaf(context, prefix, schema, example)
        built: Dict[str, Any] = {}
        for name in names:
            path = f"{prefix}.{name}" if prefix else name
            child_schema = (
                self._field_schema(context.entry, context.location, path, context.status, context.media_type) or {}
            )
            child_example = example.get(name, _MISSING) if isinstance(example, dict) else _MISSING
            built[name] = self._value(context, path, child_schema, child_example, depth + 1)
        return built

    def _leaf(self, context: "_BodyContext", prefix: str, schema: Dict[str, Any], example: Any) -> Any:
        """A declared field with no declared children: its example, or a reported placeholder."""
        if example is not _MISSING:
            return example
        value = _placeholder(schema)
        self._report(
            OUTCOME_PLACEHOLDER,
            "no-example",
            f"the specification has no example for the {context.location} field "
            f"'{prefix or '(body)'}'; wrote {json.dumps(value)}",
            context.operation,
            status=context.status,
            location=context.location,
            field=prefix or None,
        )
        return value

    # -----------------------------------------------------------------------------------------
    # Parameters and the path
    # -----------------------------------------------------------------------------------------

    def _parameter_example(self, parameter: Mapping[str, Any]) -> Any:
        """A parameter's ``example``, its first ``examples`` value, or its schema's example."""
        if "example" in parameter:
            return parameter["example"]
        found = self._first_example_value(parameter.get("examples"))
        if found is not _MISSING:
            return found
        return self._schema_example(parameter.get("schema"))

    def parameter_values(self, operation: ConsumerContractOperation, parameter: Mapping[str, Any]) -> List[str]:
        """The wire values of one parameter, reporting any value that had to be invented."""
        name = str(parameter.get("name", ""))
        example = self._parameter_example(parameter)
        if example is _MISSING:
            example = _placeholder(self._resolve(parameter.get("schema")))
            self._report(
                OUTCOME_PLACEHOLDER,
                "no-example",
                f"the specification has no example for the {parameter.get('in')} parameter "
                f"'{name}'; wrote {json.dumps(example)}",
                operation,
                location="parameter",
                field=name,
            )
        values, complex_value = _parameter_text(example)
        if complex_value:
            self._report(
                OUTCOME_PLACEHOLDER,
                "complex-parameter-value",
                f"the example of parameter '{name}' is an object; it was written as JSON text, "
                f"which may not be how the provider serializes it",
                operation,
                location="parameter",
                field=name,
            )
        return values or [""]

    def _server_base_path(self) -> str:
        """The path of the first declared server URL (``/v1`` of ``https://api.example.com/v1``).

        A Pact interaction records the path the client actually sends, base path included. A
        server URL with variables is not used — there is no single value to substitute.
        """
        servers = self.index.node_at("/servers")
        first = servers[0] if isinstance(servers, list) and servers else None
        url = _as_dict(first).get("url")
        if not isinstance(url, str) or "{" in url:
            return ""
        path = urlsplit(url).path if "//" in url else url
        path = (path or "").rstrip("/")
        if not path or path == "/":
            return ""
        return path if path.startswith("/") else f"/{path}"

    def concrete_path(self, operation: ConsumerContractOperation, entry: Any) -> str:
        """The path template with every variable replaced by its example, server base path first."""
        by_name = {str(p.get("name")): p for p in entry.parameters if str(p.get("in")) == "path"}

        def substitute(match: "re.Match[str]") -> str:
            name = match.group(1)
            parameter = by_name.get(name, {"name": name, "in": "path", "schema": {"type": "string"}})
            return quote(self.parameter_values(operation, parameter)[0], safe="")

        return self._server_base_path() + re.sub(r"\{([^}/]+)\}", substitute, operation.path)

    # -----------------------------------------------------------------------------------------
    # Operations
    # -----------------------------------------------------------------------------------------

    def _status_code(self, operation: ConsumerContractOperation, status: str) -> Optional[int]:
        """The numeric status a declared response key becomes, reporting any approximation."""
        if status.isdigit():
            return int(status)
        ranged = _STATUS_RANGE.match(status)
        if ranged:
            code = int(ranged.group(1)) * 100
            self._report(
                OUTCOME_PLACEHOLDER,
                "status-range",
                f"the response is declared as the range {status}; the interaction expects {code}",
                operation,
                status=status,
            )
            return code
        reason = "status-default" if status == "default" else "status-not-numeric"
        self._report(
            OUTCOME_OMITTED,
            reason,
            f"the response '{status}' names no single HTTP status, so no interaction can expect "
            f"it; declare the fields under a numeric status to export them",
            operation,
            status=status,
        )
        return None

    def _request(
        self,
        operation: ConsumerContractOperation,
        entry: Any,
        request_fields: List[ConsumerContractField],
        parameter_fields: List[ConsumerContractField],
    ) -> Dict[str, Any]:
        """The interaction request: method, concrete path, declared parameters, declared body."""
        request: Dict[str, Any] = {
            "method": operation.method.upper(),
            "path": self.concrete_path(operation, entry),
        }
        query: Dict[str, List[str]] = {}
        headers: Dict[str, List[str]] = {}
        cookies: List[str] = []
        by_name = {str(p.get("name")): p for p in entry.parameters}
        for declared in parameter_fields:
            parameter = by_name.get(declared.path)
            if parameter is None:
                self._report(
                    OUTCOME_OMITTED,
                    "parameter-not-declared",
                    f"the parameter '{declared.path}' is no longer in the specification",
                    operation,
                    location="parameter",
                    field=declared.path,
                )
                continue
            where = str(parameter.get("in"))
            if where == "path":
                continue  # already in the concrete path
            values = self.parameter_values(operation, parameter)
            if where == "query":
                query[declared.path] = values
            elif where == "header":
                headers[declared.path] = values
            elif where == "cookie":
                cookies.extend(f"{declared.path}={value}" for value in values)
        if cookies:
            headers["Cookie"] = ["; ".join(cookies)]

        body = self._body_section(operation, entry, "request", None, request_fields)
        if body is not None:
            headers["Content-Type"] = [body["contentType"]]
            request["body"] = body
        if query:
            request["query"] = dict(sorted(query.items()))
        if headers:
            request["headers"] = dict(sorted(headers.items()))
        return request

    def _body_section(
        self,
        operation: ConsumerContractOperation,
        entry: Any,
        location: str,
        status: Optional[str],
        fields: List[ConsumerContractField],
    ) -> Optional[Dict[str, Any]]:
        """A v4 body object for the declared fields of one request or response, or ``None``."""
        if not fields:
            return None
        media_types = sorted({f.media_type or "" for f in fields})
        media_type = next((m for m in media_types if _is_json_media_type(m)), media_types[0])
        if not _is_json_media_type(media_type):
            for declared in fields:
                self._report(
                    OUTCOME_OMITTED,
                    "media-type-not-json",
                    f"the {location} field '{declared.path}' is declared under {media_type or 'no media type'}; "
                    f"only JSON bodies can be generated",
                    operation,
                    status=status,
                    location=location,
                    field=declared.path,
                )
            return None
        for declared in fields:
            if declared.media_type != media_type:
                self._report(
                    OUTCOME_OMITTED,
                    "media-type-conflict",
                    f"the {location} field '{declared.path}' is declared under {declared.media_type}; "
                    f"one interaction carries one body, and it is written as {media_type}",
                    operation,
                    status=status,
                    location=location,
                    field=declared.path,
                )
        content = self.build_body(
            operation,
            entry,
            location=location,
            status=status,
            media_type=media_type,
            paths=[f.path for f in fields if f.media_type == media_type],
        )
        if content is _MISSING:
            return None
        return {"contentType": media_type, "encoded": False, "content": content}

    def interactions(self, operation: ConsumerContractOperation) -> List[Dict[str, Any]]:
        """Every interaction one declared operation becomes — one per response status it reads."""
        entry = self.index.get_operation(operation.method, operation.path)
        if entry is None:
            self._report(
                OUTCOME_OMITTED,
                "operation-not-found",
                f"the specification no longer declares {operation.method.upper()} {operation.path}",
                operation,
            )
            return []

        request_fields = [f for f in operation.fields if f.location == "request"]
        parameter_fields = [f for f in operation.fields if f.location == "parameter"]
        by_status: Dict[str, List[ConsumerContractField]] = {}
        for declared in operation.fields:
            if declared.location == "response":
                by_status.setdefault(str(declared.status or self.index.default_status(entry) or ""), []).append(
                    declared
                )
        if not by_status:
            default = self.index.default_status(entry)
            if default is None:
                self._report(
                    OUTCOME_OMITTED,
                    "no-response-declared",
                    "the operation declares no responses, so no interaction can expect one",
                    operation,
                )
                return []
            by_status[default] = []

        request = self._request(operation, entry, request_fields, parameter_fields)
        label = operation.operation_id or f"{operation.method.upper()} {operation.path}"
        written: List[Dict[str, Any]] = []
        for status in sorted(by_status):
            code = self._status_code(operation, status)
            if code is None:
                continue
            response: Dict[str, Any] = {"status": code}
            body = self._body_section(operation, entry, "response", status, by_status[status])
            if body is not None:
                response["headers"] = {"Content-Type": [body["contentType"]]}
                response["body"] = body
                response["matchingRules"] = {"body": {"$": {"combine": "AND", "matchers": [{"match": "type"}]}}}
            written.append(
                {
                    "type": "Synchronous/HTTP",
                    "description": f"{label} returns {code}",
                    "pending": False,
                    "request": json.loads(json.dumps(request)),
                    "response": response,
                }
            )
        if not written:
            self._report(
                OUTCOME_OMITTED,
                "no-response-declared",
                "no declared response of this operation has a single HTTP status, so it was not exported",
                operation,
            )
        return written


@dataclass
class _BodyContext:
    """What every node of one body being built shares."""

    operation: ConsumerContractOperation
    entry: Any
    location: str
    status: Optional[str]
    media_type: str
    children: Dict[str, List[str]]


def build_consumer_pact(
    contract: ConsumerContractRecord,
    index: SpecIndex,
    *,
    consumer_name: str,
    provider_name: str,
    consumer_slug: Optional[str] = None,
) -> PactExport:
    """Generate the Pact v4 document of one declared contract revision.

    Args:
        contract: The stored contract revision (the picker's surface).
        index: The specification it was declared against.
        consumer_name: The ``consumer.name`` to write (the pacticipant the pact is published as).
        provider_name: The ``provider.name`` to write.
        consumer_slug: The Apiome consumer handle, recorded in ``metadata.apiome``.

    Returns:
        The document, its interaction count and every finding. The document may hold zero
        interactions; the caller decides whether that is publishable.
    """
    generator = _Generator(index)
    for unresolved in contract.unresolved:
        generator.findings.append(
            ExportFinding(
                outcome=OUTCOME_OMITTED,
                reason="contract-unresolved",
                message=f"the stored contract could not resolve this ({unresolved.reason}): {unresolved.message}",
                method=unresolved.method.upper() if unresolved.method else None,
                path=unresolved.path,
                status=unresolved.status,
                field=unresolved.field_path,
            )
        )

    interactions: List[Dict[str, Any]] = []
    for operation in contract.surface.operations:
        interactions.extend(generator.interactions(operation))

    apiome: Dict[str, Any] = {
        "generatedFrom": "consumer-contract",
        "contractRevision": contract.revision,
        "versionRecordId": contract.version_id,
        "versionLabel": contract.version_label,
        "consumer": consumer_slug,
    }
    document: Dict[str, Any] = {
        "consumer": {"name": consumer_name},
        "provider": {"name": provider_name},
        "interactions": interactions,
        "metadata": {
            "pactSpecification": {"version": PACT_SPECIFICATION_VERSION},
            "apiome": {key: value for key, value in apiome.items() if value is not None},
        },
    }
    return PactExport(document=document, interaction_count=len(interactions), findings=generator.findings)
