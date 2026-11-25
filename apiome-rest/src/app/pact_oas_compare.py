"""Compare a consumer pact with a provider's OpenAPI document — PFX-2.2 (#6926).

Bi-directional contract testing answers "can this consumer talk to this provider?" without
running either: the consumer publishes a pact (PFX-1.2), the provider publishes its OpenAPI
document (PFX-2.1), and this module decides whether the document satisfies every interaction
of the pact. It is the pure core — two parsed documents in, one :class:`ComparisonResult` out.
No I/O, no clock, no network; equal inputs produce byte-equal output.

What is compared, per interaction
---------------------------------
1. **Operation** — the request's method and concrete path are resolved onto a declared
   operation with :meth:`app.consumer_surface.SpecIndex.match_operation` (the path templating
   CTG-4.1 already uses, server base paths included).
2. **Request** — path, query and header parameters and the body are validated against the
   provider's schemas *as written*: the consumer must send what the provider accepts.
3. **Response** — the status must be declared; headers and the body are validated against the
   response's schemas with ``required`` lifted and undeclared properties refused: the consumer
   may read less than the provider returns, never more (see :mod:`app.pact_oas_schema`).
4. **Matching rules** — each rule of Pact 2, 3 and 4 is mapped onto a JSON Schema constraint
   and checked against the provider's schema where that is lossless
   (:mod:`app.pact_matching_rules`).

Three lists, and what each means
--------------------------------
* **failures** — the provider's document contradicts the pact. Every failure has a stable code
  (:data:`FAILURE_CLASSES`), a JSON Pointer into the pact, and two into the OpenAPI document in
  the CTG-1.1 vocabulary: ``oasPointer`` anchored at the operation (the identity
  :mod:`app.change_taxonomy_enum` gives the same node) and ``resolvedPointer`` where the node
  actually lives once ``$ref``\\ s are followed.
* **warnings** — worth a look, never a reason to fail (:data:`WARNING_CLASSES`).
* **fidelity** — what was *not* compared, or compared more weakly than the pact asks: an
  unmapped or unproven matching rule, a non-JSON body, a message interaction
  (:data:`FIDELITY_CLASSES`). Nothing is dropped silently; PFX-2.5 surfaces this list.

The verdict is ``fail`` when any interaction has a failure, ``partial`` when none has but the
fidelity list is not empty, and ``pass`` only when everything in the pact was compared in full.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .change_taxonomy_enum import json_pointer_escape
from .pact_contract_import import (
    interaction_is_http,
    pact_consumer_name,
    pact_provider_name,
    pact_specification_version,
)
from .pact_interaction_reader import PactBody as _Body
from .pact_interaction_reader import as_dict as _as_dict
from .pact_interaction_reader import is_json_media_type as _is_json
from .pact_interaction_reader import media_type_of as _media
from .pact_interaction_reader import read_body as _read_body
from .pact_interaction_reader import read_headers as _headers
from .pact_interaction_reader import read_query as _query
from .pact_matching_rules import (
    MAX_COMPARISON_RULE_LOCATIONS,
    evaluate_rule,
    parse_matching_rules,
    parse_path,
    schema_types,
)
from .pact_oas_result import (
    FAILURE_CLASSES,
    FIDELITY_CLASSES,
    MAX_INTERACTION_FINDINGS,
    VERDICT_FAIL,
    VERDICT_PARTIAL,
    VERDICT_PASS,
    WARNING_CLASSES,
    ComparisonResult,
    FidelityNote,
    Finding,
    InteractionResult,
    PactOasCompareError,
)
from .pact_oas_schema import (
    REQUEST,
    RESPONSE,
    ProviderSchemas,
    pointer_tokens,
)

__all__ = [
    "FAILURE_CLASSES",
    "FIDELITY_CLASSES",
    "MAX_INTERACTION_FINDINGS",
    "VERDICT_FAIL",
    "VERDICT_PARTIAL",
    "VERDICT_PASS",
    "WARNING_CLASSES",
    "ComparisonResult",
    "Finding",
    "FidelityNote",
    "InteractionResult",
    "PactOasCompareError",
    "compare_pact_to_oas",
]

#: Request headers every HTTP client sends, which providers do not declare as parameters.
#: (``Accept``, ``Content-Type`` and ``Authorization`` are never parameters in OpenAPI at all.)
_UNDECLARED_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-charset",
        "accept-encoding",
        "accept-language",
        "authorization",
        "cache-control",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "origin",
        "pragma",
        "referer",
        "user-agent",
    }
)

#: Parameter styles whose serialization the engine does not parse.
_UNPARSED_STYLES = ("deepObject", "pipeDelimited", "spaceDelimited", "matrix", "label")

_INTEGER = re.compile(r"^-?(0|[1-9]\d*)$")
_NUMBER = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$")


# =============================================================================================
# Small readers
# =============================================================================================


def _range_matches(declared: str, wanted: str) -> bool:
    """Whether a declared media type or range covers a concrete media type.

    Args:
        declared: A media type or range (``application/json``, ``application/*``, ``*/*``).
        wanted: A concrete media type, or a range from an ``Accept`` header.

    Returns:
        True when one covers the other.
    """
    left, right = (_media(declared) or ""), (_media(wanted) or "")
    if left == right or "*/*" in (left, right):
        return True
    left_type, _, left_sub = left.partition("/")
    right_type, _, right_sub = right.partition("/")
    return left_type == right_type and "*" in (left_sub, right_sub)


def _pick_media(content: Mapping[str, Any], wanted: Optional[str]) -> Optional[str]:
    """Choose the declared media type a body is compared against.

    Args:
        content: An OpenAPI ``content`` map.
        wanted: The body's media type, or ``None`` when the pact does not say.

    Returns:
        The key of ``content`` to use — the exact type, else a covering range, and for an
        unstated type the first JSON type (sorted, so the choice is stable) — or ``None``.
    """
    keys = sorted(str(key) for key in content)
    if wanted is None:
        for key in keys:
            if _is_json(_media(key)):
                return key
        return keys[0] if keys else None
    for key in keys:
        if _media(key) == wanted:
            return key
    for key in keys:
        if "*" in key and _range_matches(key, wanted):
            return key
    return None


def _value_at(instance: Any, tokens: Sequence[str]) -> Any:
    """Read a value out of a parsed JSON instance by pointer tokens.

    Args:
        instance: The instance.
        tokens: Unescaped JSON Pointer tokens.

    Returns:
        The value, or ``None`` when a token leads nowhere.
    """
    current = instance
    for token in tokens:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return None
    return current


def _candidates(raw: str, types: Optional[Set[str]]) -> List[Any]:
    """The JSON values a parameter's text may stand for.

    A parameter travels as text; ``10`` is the integer ten to a schema of ``type: integer``
    and the string ``"10"`` to one of ``type: string``.

    Args:
        raw: The value as the pact recorded it.
        types: The types the parameter's schema admits, or ``None`` when it does not say.

    Returns:
        The readings to try, most specific first. The parameter is valid when any is.
    """
    found: List[Any] = []
    # Longer digit strings are not numbers any API means, and int() refuses them outright.
    numeric = len(raw) <= 64 and (types is None or bool(types & {"integer", "number"}))
    if numeric and _INTEGER.match(raw):
        found.append(int(raw))
    elif numeric and _NUMBER.match(raw):
        found.append(float(raw))
    if (types is None or "boolean" in types) and raw in ("true", "false"):
        found.append(raw == "true")
    if types is None or "string" in types or not found:
        found.append(raw)
    return found


@dataclass
class _Parameter:
    """A declared parameter or response header.

    Attributes:
        name: Its name as declared.
        location: ``path``, ``query``, ``header`` or ``cookie``.
        node: The parameter or header object, ``$ref`` resolved.
        pointer: JSON Pointer of where that object actually lives.
        anchor: Its operation-anchored pointer in the CTG-1.1 vocabulary.
    """

    name: str
    location: str
    node: Dict[str, Any]
    pointer: str
    anchor: str


# =============================================================================================
# The comparison
# =============================================================================================


class _Comparison:
    """State shared by every interaction of one comparison."""

    def __init__(self, pact: Mapping[str, Any], oas: Dict[str, Any]) -> None:
        """Prepare the provider's schemas once.

        Args:
            pact: The parsed pact document.
            oas: The parsed OpenAPI document.
        """
        self.schemas = ProviderSchemas(oas)
        self.index = self.schemas.index
        version = pact_specification_version(pact) or ""
        self.v4 = version.startswith("4")
        self._parameters: Dict[str, List[_Parameter]] = {}
        self.rule_cache: Dict[Tuple[str, str, str], Optional[str]] = {}
        self.rule_budget = [MAX_COMPARISON_RULE_LOCATIONS]

    def parameters(self, entry: Any) -> List[_Parameter]:
        """An operation's parameters, path-level ones included, with where each one lives.

        Args:
            entry: The operation entry from the index.

        Returns:
            The parameters; one declared on the operation replaces a path-level one of the
            same name and location. Cached per operation.
        """
        if entry.pointer in self._parameters:
            return self._parameters[entry.pointer]
        path_pointer = f"/paths/{json_pointer_escape(entry.path)}"
        merged: Dict[Tuple[str, str], _Parameter] = {}
        sources = (
            (path_pointer, _as_dict(self.index.node_at(path_pointer)).get("parameters")),
            (entry.pointer, entry.operation.get("parameters")),
        )
        for base, declared in sources:
            for position, raw in enumerate(declared if isinstance(declared, list) else []):
                node, target = self.index.resolve_reference(raw)
                node = _as_dict(node)
                name, location = str(node.get("name", "")), str(node.get("in", ""))
                if not name:
                    continue
                key = (location, name.lower() if location == "header" else name)
                merged[key] = _Parameter(
                    name=name,
                    location=location,
                    node=node,
                    pointer=target or f"{base}/parameters/{position}",
                    anchor=(
                        f"{entry.pointer}/parameters/"
                        f"{json_pointer_escape(f'{location}:{name}')}"
                    ),
                )
        self._parameters[entry.pointer] = [merged[key] for key in sorted(merged)]
        return self._parameters[entry.pointer]


class _InteractionRun:
    """The comparison of one interaction: the checks, in order, and what each one found."""

    def __init__(
        self, shared: _Comparison, index: int, interaction: Mapping[str, Any], pointer: str
    ) -> None:
        """Bind an interaction to the shared comparison state.

        Args:
            shared: The comparison's shared state.
            index: Position of the interaction in the pact.
            interaction: The interaction object.
            pointer: JSON Pointer of the interaction in the pact document.
        """
        self.shared = shared
        self.schemas = shared.schemas
        self.index = shared.index
        self.interaction = interaction
        description = interaction.get("description")
        self.result = InteractionResult(
            index=index,
            description=description if isinstance(description, str) else None,
            pointer=pointer,
        )
        self.pointer = pointer
        self.dropped = 0
        #: Where each part of the message is described and what its example is:
        #: ``(side, category, lowercase name) → (schema site or None, example value)``.
        self.sites: Dict[Tuple[str, str, str], Tuple[Optional[str], Any]] = {}

    # -----------------------------------------------------------------------------------------
    # Recording
    # -----------------------------------------------------------------------------------------

    def fail(self, code: str, message: str, pact_pointer: str, **extra: Any) -> None:
        """Record a failure, up to :data:`MAX_INTERACTION_FINDINGS` per interaction.

        Args:
            code: A key of :data:`FAILURE_CLASSES`.
            message: The sentence to show.
            pact_pointer: JSON Pointer into the pact.
            **extra: Further :class:`Finding` fields.
        """
        if len(self.result.failures) >= MAX_INTERACTION_FINDINGS:
            self.dropped += 1
            return
        self.result.failures.append(Finding(code, message, pact_pointer, **extra))

    def warn(self, code: str, message: str, pact_pointer: str, **extra: Any) -> None:
        """Record a warning.

        Args:
            code: A key of :data:`WARNING_CLASSES`.
            message: The sentence to show.
            pact_pointer: JSON Pointer into the pact.
            **extra: Further :class:`Finding` fields.
        """
        self.result.warnings.append(Finding(code, message, pact_pointer, **extra))

    def note(self, code: str, message: str, pact_pointer: str, **extra: Any) -> None:
        """Record a fidelity note.

        Args:
            code: A key of :data:`FIDELITY_CLASSES`.
            message: The sentence to show.
            pact_pointer: JSON Pointer into the pact.
            **extra: Further :class:`FidelityNote` fields.
        """
        self.result.fidelity.append(FidelityNote(code, message, pact_pointer, **extra))

    # -----------------------------------------------------------------------------------------
    # Entry point
    # -----------------------------------------------------------------------------------------

    def run(self) -> InteractionResult:
        """Compare the interaction.

        Returns:
            Its :class:`InteractionResult`.
        """
        interaction = self.interaction
        if not interaction_is_http(interaction):
            self.note(
                "interaction-not-http",
                f"interaction type '{interaction.get('type')}' carries no HTTP exchange, so "
                "there is nothing to compare with an OpenAPI document",
                self.pointer,
            )
            return self.result

        request = _as_dict(interaction.get("request"))
        response = _as_dict(interaction.get("response"))
        request_pointer = f"{self.pointer}/request"
        response_pointer = f"{self.pointer}/response"
        method = str(request.get("method", "")).strip().lower()
        path = request.get("path")

        entry = None
        if not method or not isinstance(path, str) or not path.strip():
            self.fail(
                "interaction.malformed",
                "the interaction's request declares no method and path",
                request_pointer,
            )
        else:
            entry = self._resolve_operation(method, path, request_pointer)

        if entry is not None and isinstance(path, str):
            self._check_request(entry, request, request_pointer, path)
            self._check_response(entry, request, response, request_pointer, response_pointer)

        self._check_rules(REQUEST, request, request_pointer)
        self._check_rules(RESPONSE, response, response_pointer)
        self._note_generators(request, request_pointer)
        self._note_generators(response, response_pointer)
        if self.dropped:
            self.note(
                "findings-truncated",
                f"{self.dropped} more failure(s) in this interaction are not listed",
                self.pointer,
            )
        return self.result

    # -----------------------------------------------------------------------------------------
    # Operation
    # -----------------------------------------------------------------------------------------

    def _resolve_operation(self, method: str, path: str, request_pointer: str) -> Any:
        """Resolve the request onto a declared operation, or record why it does not resolve.

        Args:
            method: The request's method, lowercase.
            path: The request's concrete path.
            request_pointer: JSON Pointer of the pact request.

        Returns:
            The operation entry, or ``None``.
        """
        self.result.checks.append("request.operation")
        entry = self.index.match_operation(method, path)
        if entry is not None:
            operation_id = entry.operation.get("operationId")
            self.result.operation = {
                "method": entry.method,
                "path": entry.path,
                "pointer": entry.pointer,
                "operationId": operation_id if isinstance(operation_id, str) else None,
            }
            return entry
        template = self.index.match_path(path)
        if template is not None:
            pointer = f"/paths/{json_pointer_escape(template)}"
            self.fail(
                "request.method.undeclared",
                f"the provider declares {template} but not with {method.upper()}",
                f"{request_pointer}/method",
                oas_pointer=pointer,
                resolved_pointer=pointer,
            )
        else:
            self.fail(
                "request.operation.unknown",
                f"the provider declares no operation for {method.upper()} {path}",
                f"{request_pointer}/path",
                oas_pointer="/paths",
                resolved_pointer="/paths",
            )
        return None

    # -----------------------------------------------------------------------------------------
    # Schema failures
    # -----------------------------------------------------------------------------------------

    def _validate_value(
        self, side: str, site: str, anchor: str, instance: Any, pact_pointer: str
    ) -> Optional[List[Tuple[Any, str, str]]]:
        """Validate a value and place each finding in the document.

        Args:
            side: ``request`` or ``response``.
            site: JSON Pointer of the schema, where it actually lives.
            anchor: The operation-anchored pointer of the same schema.
            instance: The value.
            pact_pointer: JSON Pointer of the value in the pact, for the not-usable note.

        Returns:
            ``(finding, oas pointer, resolved pointer)`` triples, or ``None`` when the schema
            could not be used (a fidelity note has then been recorded).
        """
        outcome = self.schemas.validate(side, site, instance)
        if outcome is None:
            self.note(
                "schema-not-usable",
                "the provider's schema could not be evaluated, so this value was not compared",
                pact_pointer,
                oas_pointer=anchor,
            )
            return None
        findings, total = outcome
        self.dropped += total - len(findings)
        placed = []
        for finding in findings:
            schema_path = pointer_tokens(finding.schema_pointer)
            placed.append(
                (
                    finding,
                    anchor + "".join(f"/{json_pointer_escape(token)}" for token in schema_path),
                    self.schemas.locate(site, schema_path),
                )
            )
        return placed

    def _check_body_schema(
        self, side: str, site: str, anchor: str, body: _Body
    ) -> None:
        """Validate a JSON body and name each way it breaks the provider's schema.

        Args:
            side: ``request`` or ``response``.
            site: JSON Pointer of the body's schema, where it actually lives.
            anchor: The operation-anchored pointer of the same schema.
            body: The body.
        """
        placed = self._validate_value(side, site, anchor, body.value, body.pointer)
        if placed is None:
            return
        seen: Set[Tuple[str, str, str]] = set()
        pointers = [finding.pointer for finding, _, _ in placed]
        for finding, oas_pointer, resolved in placed:
            identity = (finding.keyword, finding.pointer, finding.schema_pointer)
            if identity in seen:
                continue
            seen.add(identity)
            where = f" at {finding.pointer}" if finding.pointer else ""
            pact_pointer = f"{body.pointer}{finding.pointer}"
            tokens = pointer_tokens(finding.pointer)
            value = _value_at(body.value, tokens)
            common = {
                "oas_pointer": oas_pointer,
                "resolved_pointer": resolved,
                "keyword": finding.keyword,
                "detail": finding.message,
            }
            if finding.keyword == "required":
                declared = self.schemas.node(resolved)
                missing = [
                    str(name)
                    for name in (declared if isinstance(declared, list) else [])
                    if not isinstance(value, dict) or name not in value
                ]
                names = ", ".join(f"'{name}'" for name in missing) or "a required property"
                self.fail(
                    f"{side}.body.required-mismatch",
                    f"the {side} body{where} leaves out {names}, which the provider requires",
                    pact_pointer,
                    **common,
                )
            elif finding.keyword == "type" and value is None:
                self.fail(
                    f"{side}.body.nullable-mismatch",
                    f"the {side} body{where} is null, but the provider does not declare it "
                    "nullable",
                    pact_pointer,
                    **common,
                )
            elif finding.keyword in ("additionalProperties", "unevaluatedProperties"):
                below = any(other.startswith(f"{finding.pointer}/") for other in pointers)
                self._unknown_properties(
                    side, site, finding, value, where, pact_pointer, common, below
                )
            else:
                self.fail(
                    f"{side}.body.schema-mismatch",
                    f"the {side} body{where} does not satisfy the provider's schema "
                    f"({finding.keyword})",
                    pact_pointer,
                    **common,
                )

    def _unknown_properties(
        self,
        side: str,
        site: str,
        finding: Any,
        value: Any,
        where: str,
        pact_pointer: str,
        common: Dict[str, Any],
        failing_below: bool,
    ) -> None:
        """Record one failure per property the provider's schema does not declare.

        A closed object also "has unevaluated properties" when one of its declared properties
        simply fails its own schema. That failure is already reported where it happens, so an
        object whose every property is declared adds nothing here.

        Args:
            side: ``request`` or ``response``.
            site: JSON Pointer of the body's schema.
            finding: The validator finding for the closed object.
            value: The object in the example.
            where: `` at <pointer>`` for the message, or ``""`` at the body root.
            pact_pointer: JSON Pointer of the object in the pact.
            common: The pointer and keyword fields every failure of this finding shares.
            failing_below: Whether another finding lies inside the object.
        """
        verb = "sends" if side == REQUEST else "expects"
        owner = self.schemas.locate(site, pointer_tokens(finding.schema_pointer)[:-1])
        declared = self.schemas.declared_properties(owner)
        unknown = (
            sorted(str(name) for name in value if name not in declared)
            if isinstance(value, dict) and declared is not None
            else []
        )
        if not unknown and failing_below:
            return
        if not unknown:
            self.fail(
                f"{side}.body.unknown-property",
                f"the {side} body{where} {verb} properties the provider's schema does not accept",
                pact_pointer,
                **common,
            )
            return
        for name in unknown:
            self.fail(
                f"{side}.body.unknown-property",
                f"the {side} body{where} {verb} property '{name}', which the provider does "
                "not declare",
                f"{pact_pointer}/{json_pointer_escape(name)}",
                **common,
            )

    def _check_parameter(
        self,
        side: str,
        parameter: _Parameter,
        raws: Sequence[str],
        code: str,
        label: str,
        pact_pointer: str,
    ) -> None:
        """Validate a parameter's or header's text against its schema.

        Args:
            side: ``request`` or ``response``.
            parameter: The declared parameter or header.
            raws: The value or values the pact records.
            code: The failure code to use.
            label: How to name it in a message (``query parameter 'limit'``).
            pact_pointer: JSON Pointer of the value in the pact.
        """
        key = (side, "header" if parameter.location == "header" else parameter.location)
        example: Any = raws[0] if len(raws) == 1 else list(raws)
        if not isinstance(parameter.node.get("schema"), dict):
            self.sites[(*key, parameter.name.lower())] = (None, example)
            self.note(
                "parameter-not-compared",
                f"{label} declares no schema, so its value was not compared",
                pact_pointer,
                reason="no-schema",
                oas_pointer=parameter.anchor,
            )
            return
        site = f"{parameter.pointer}/schema"
        self.sites[(*key, parameter.name.lower())] = (site, example)
        resolved = self.schemas.node(self.schemas.follow(site), normalized=True)
        types = schema_types(resolved)
        style = parameter.node.get("style")
        if (types and "object" in types) or style in _UNPARSED_STYLES:
            self.note(
                "parameter-not-compared",
                f"{label} is an object or uses style '{style}', which is not parsed",
                pact_pointer,
                reason="style",
                oas_pointer=parameter.anchor,
            )
            return

        if types and "array" in types:
            explode = parameter.node.get("explode", parameter.location in ("query", "cookie"))
            parts = (
                list(raws)
                if explode and parameter.location == "query"
                else [part.strip() for raw in raws for part in raw.split(",")]
            )
            items = _as_dict(resolved).get("items")
            item_types = (
                schema_types(self.schemas.node(self.schemas.follow(f"{site}/items"), normalized=True))
                if isinstance(items, dict)
                else None
            )
            readings: List[List[Any]] = [[[_candidates(part, item_types)[0] for part in parts]]]
        else:
            readings = [_candidates(raw, types) for raw in raws]

        for candidates in readings:
            best: Optional[List[Tuple[Any, str, str]]] = None
            for candidate in candidates:
                placed = self._validate_value(side, site, parameter.anchor, candidate, pact_pointer)
                if placed is None:
                    return
                if best is None or len(placed) < len(best):
                    best = placed
                if not placed:
                    break
            for finding, _, resolved_pointer in (best or [])[:1]:
                self.fail(
                    code,
                    f"{label} does not satisfy the provider's schema ({finding.keyword})",
                    pact_pointer,
                    oas_pointer=parameter.anchor,
                    resolved_pointer=resolved_pointer,
                    keyword=finding.keyword,
                    detail=finding.message,
                )

    # -----------------------------------------------------------------------------------------
    # Request
    # -----------------------------------------------------------------------------------------

    def _check_request(
        self, entry: Any, request: Mapping[str, Any], pointer: str, path: str
    ) -> None:
        """Check the request's parameters, headers and body.

        Args:
            entry: The matched operation.
            request: The pact request.
            pointer: JSON Pointer of the pact request.
            path: The request's concrete path.
        """
        parameters = self.shared.parameters(entry)
        checks = self.result.checks

        checks.append("request.path-parameters")
        path_values = self.index.path_parameters(entry, path)
        for parameter in parameters:
            if parameter.location == "path" and parameter.name in path_values:
                self._check_parameter(
                    REQUEST,
                    parameter,
                    [path_values[parameter.name]],
                    "request.path-parameter.invalid",
                    f"path parameter '{parameter.name}'",
                    f"{pointer}/path",
                )

        checks.append("request.query")
        query = _query(request)
        declared_query = {p.name: p for p in parameters if p.location == "query"}
        for name in sorted(declared_query):
            parameter = declared_query[name]
            if name in query:
                self._check_parameter(
                    REQUEST,
                    parameter,
                    query[name],
                    "request.query.invalid",
                    f"query parameter '{name}'",
                    f"{pointer}/query"
                    + (
                        ""
                        if isinstance(request.get("query"), str)
                        else f"/{json_pointer_escape(name)}"
                    ),
                )
            elif parameter.node.get("required") is True:
                self.fail(
                    "request.query.required-missing",
                    f"the request leaves out query parameter '{name}', which the provider "
                    "requires",
                    f"{pointer}/query",
                    oas_pointer=parameter.anchor,
                    resolved_pointer=parameter.pointer,
                )
        for name in sorted(set(query) - set(declared_query)):
            self.sites[(REQUEST, "query", name.lower())] = (None, query[name][0] if query[name] else "")
            self.warn(
                "request.query.undeclared",
                f"the request sends query parameter '{name}', which the provider does not "
                "declare",
                f"{pointer}/query",
                oas_pointer=f"{entry.pointer}/parameters",
            )

        checks.append("request.headers")
        headers = _headers(request)
        declared_headers = {
            p.name.lower(): p
            for p in parameters
            if p.location == "header" and p.name.lower() not in ("accept", "content-type", "authorization")
        }
        for lowered in sorted(declared_headers):
            parameter = declared_headers[lowered]
            if lowered in headers:
                written, value = headers[lowered]
                self._check_parameter(
                    REQUEST,
                    parameter,
                    [value],
                    "request.header.invalid",
                    f"request header '{parameter.name}'",
                    f"{pointer}/headers/{json_pointer_escape(written)}",
                )
            elif parameter.node.get("required") is True:
                self.fail(
                    "request.header.required-missing",
                    f"the request leaves out header '{parameter.name}', which the provider "
                    "requires",
                    f"{pointer}/headers",
                    oas_pointer=parameter.anchor,
                    resolved_pointer=parameter.pointer,
                )
        for lowered in sorted(set(headers) - set(declared_headers)):
            written, value = headers[lowered]
            self.sites.setdefault((REQUEST, "header", lowered), (None, value))
            if lowered not in _UNDECLARED_REQUEST_HEADERS:
                self.warn(
                    "request.header.undeclared",
                    f"the request sends header '{written}', which the provider does not declare",
                    f"{pointer}/headers/{json_pointer_escape(written)}",
                    oas_pointer=f"{entry.pointer}/parameters",
                )

        checks.append("request.body")
        self._check_request_body(entry, request, pointer, headers)

    def _check_request_body(
        self,
        entry: Any,
        request: Mapping[str, Any],
        pointer: str,
        headers: Mapping[str, Tuple[str, str]],
    ) -> None:
        """Check the request body against the operation's ``requestBody``.

        Args:
            entry: The matched operation.
            request: The pact request.
            pointer: JSON Pointer of the pact request.
            headers: The request's headers, by lowercase name.
        """
        body = _read_body(request, pointer, self.shared.v4)
        declared, target = self.index.resolve_reference(entry.operation.get("requestBody"))
        declared = _as_dict(declared)
        anchor = f"{entry.pointer}/requestBody"
        real = target or anchor
        if not body.present:
            if declared.get("required") is True:
                self.fail(
                    "request.body.required-missing",
                    "the request has no body, but the provider requires one",
                    pointer,
                    oas_pointer=f"{anchor}/required",
                    resolved_pointer=f"{real}/required",
                )
            return
        if not declared:
            self.fail(
                "request.body.undeclared",
                "the request sends a body, but the operation declares no request body",
                body.pointer,
                oas_pointer=entry.pointer,
                resolved_pointer=entry.pointer,
            )
            return
        stated = _media(headers.get("content-type", ("", ""))[1]) or body.media_type
        self._check_body(REQUEST, body, stated, _as_dict(declared.get("content")), anchor, real)

    def _check_body(
        self,
        side: str,
        body: _Body,
        stated: Optional[str],
        content: Mapping[str, Any],
        anchor: str,
        real: str,
    ) -> None:
        """Pick the media type a body is described by and validate the body against it.

        Args:
            side: ``request`` or ``response``.
            body: The body.
            stated: The media type the pact states for it, if any.
            content: The OpenAPI ``content`` map it is compared against.
            anchor: Operation-anchored pointer of the object owning ``content``.
            real: Where that object actually lives.
        """
        if body.embedded:
            self.note(
                "embedded-matcher-not-mapped",
                f"the {side} body embeds matchers in its example; the values were compared, "
                "the matchers were not",
                body.pointer,
            )
        if not content:
            if side == RESPONSE:
                self.fail(
                    "response.body.undeclared",
                    "the consumer expects a response body, but the provider declares no "
                    "content for this response",
                    body.pointer,
                    oas_pointer=anchor,
                    resolved_pointer=real,
                )
            else:
                self.note(
                    "body-not-compared",
                    "the operation's request body declares no content, so the body was not "
                    "compared",
                    body.pointer,
                    reason="no-schema",
                    oas_pointer=anchor,
                )
            return
        media_type = _pick_media(content, stated)
        if media_type is None:
            self.fail(
                f"{side}.content-type.undeclared",
                f"the {side} content type '{stated}' is not one the provider declares "
                f"({', '.join(sorted(str(key) for key in content))})",
                body.pointer,
                oas_pointer=f"{anchor}/content",
                resolved_pointer=f"{real}/content",
            )
            return
        escaped = json_pointer_escape(media_type)
        schema_anchor = f"{anchor}/content/{escaped}/schema"
        site = f"{real}/content/{escaped}/schema"
        effective = stated or _media(media_type)
        if body.problem is not None:
            self.note(
                "body-not-compared",
                f"the {side} body was not compared: {body.problem}",
                body.pointer,
                reason="not-decodable",
                oas_pointer=schema_anchor,
            )
            return
        if not _is_json(effective) and not (stated is None and isinstance(body.value, (dict, list))):
            self.note(
                "body-not-compared",
                f"the {side} body is '{effective}', which is not JSON, so it was not validated "
                "against a schema",
                body.pointer,
                reason="content-type",
                oas_pointer=schema_anchor,
            )
            return
        if not isinstance(_as_dict(content.get(media_type)).get("schema"), dict):
            self.note(
                "body-not-compared",
                f"the provider declares no schema for '{media_type}', so the {side} body was "
                "not compared",
                body.pointer,
                reason="no-schema",
                oas_pointer=f"{anchor}/content/{escaped}",
            )
            return
        self.sites[(side, "body", "")] = (site, body.value)
        if side == RESPONSE and self.schemas.one_of_applies(site, body.value):
            self.note(
                "oneof-relaxed",
                "part of the expected body is described by a oneOf; with required properties "
                "lifted its branches cannot be told apart, so it was compared as anyOf",
                body.pointer,
                oas_pointer=schema_anchor,
            )
        self._check_body_schema(side, site, schema_anchor, body)

    # -----------------------------------------------------------------------------------------
    # Response
    # -----------------------------------------------------------------------------------------

    def _check_response(
        self,
        entry: Any,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        request_pointer: str,
        pointer: str,
    ) -> None:
        """Check the expected status, headers and body against the declared response.

        Args:
            entry: The matched operation.
            request: The pact request (for its ``Accept`` header).
            response: The pact response.
            request_pointer: JSON Pointer of the pact request.
            pointer: JSON Pointer of the pact response.
        """
        checks = self.result.checks
        checks.append("response.status")
        responses = _as_dict(entry.operation.get("responses"))
        keys = {str(key).upper(): str(key) for key in responses}
        status = response.get("status")
        wanted = str(status) if status is not None else (self.index.default_status(entry) or "")
        key = keys.get(wanted.upper()) or keys.get(f"{wanted[:1]}XX") or keys.get("DEFAULT")
        if key is None:
            self.fail(
                "response.status.undeclared",
                f"the consumer expects status {wanted or '(none)'}, which "
                f"{entry.method.upper()} {entry.path} does not declare",
                f"{pointer}/status",
                oas_pointer=f"{entry.pointer}/responses",
                resolved_pointer=f"{entry.pointer}/responses",
            )
            return
        anchor = f"{entry.pointer}/responses/{json_pointer_escape(key)}"
        if key.lower() == "default":
            self.warn(
                "response.status.default",
                f"status {wanted} is covered only by the operation's default response",
                f"{pointer}/status",
                oas_pointer=anchor,
            )
        declared, target = self.index.resolve_reference(responses[key])
        declared = _as_dict(declared)
        real = target or anchor
        content = _as_dict(declared.get("content"))

        accept = _headers(request).get("accept")
        if accept and content:
            ranges = [part for part in (_media(item) for item in accept[1].split(",")) if part]
            if ranges and not any(_range_matches(key_, item) for key_ in content for item in ranges):
                self.fail(
                    "request.accept.unsatisfiable",
                    f"the request accepts '{accept[1]}', but the response declares only "
                    f"{', '.join(sorted(str(k) for k in content))}",
                    f"{request_pointer}/headers/{json_pointer_escape(accept[0])}",
                    oas_pointer=f"{anchor}/content",
                    resolved_pointer=f"{real}/content",
                )

        checks.append("response.headers")
        headers = _headers(response)
        declared_headers: Dict[str, _Parameter] = {}
        for name, raw in _as_dict(declared.get("headers")).items():
            node, header_target = self.index.resolve_reference(raw)
            escaped = json_pointer_escape(str(name))
            declared_headers[str(name).lower()] = _Parameter(
                name=str(name),
                location="header",
                node=_as_dict(node),
                pointer=header_target or f"{real}/headers/{escaped}",
                anchor=f"{anchor}/headers/{escaped}",
            )
        for lowered in sorted(headers):
            written, value = headers[lowered]
            if lowered == "content-type":
                continue
            header_pointer = f"{pointer}/headers/{json_pointer_escape(written)}"
            if lowered not in declared_headers:
                self.sites[(RESPONSE, "header", lowered)] = (None, value)
                self.fail(
                    "response.header.undeclared",
                    f"the consumer expects response header '{written}', which the provider "
                    "does not declare",
                    header_pointer,
                    oas_pointer=f"{anchor}/headers",
                    resolved_pointer=f"{real}/headers",
                )
                continue
            self._check_parameter(
                RESPONSE,
                declared_headers[lowered],
                [value],
                "response.header.invalid",
                f"response header '{written}'",
                header_pointer,
            )

        checks.append("response.body")
        body = _read_body(response, pointer, self.shared.v4)
        stated = _media(headers.get("content-type", ("", ""))[1]) or body.media_type
        if body.present:
            self._check_body(RESPONSE, body, stated, content, anchor, real)
        elif stated and content and _pick_media(content, stated) is None:
            self.fail(
                "response.content-type.undeclared",
                f"the response content type '{stated}' is not one the provider declares "
                f"({', '.join(sorted(str(k) for k in content))})",
                f"{pointer}/headers",
                oas_pointer=f"{anchor}/content",
                resolved_pointer=f"{real}/content",
            )

    # -----------------------------------------------------------------------------------------
    # Matching rules and generators
    # -----------------------------------------------------------------------------------------

    def _check_rules(self, side: str, section: Mapping[str, Any], pointer: str) -> None:
        """Evaluate every matching rule of a request or a response.

        Args:
            side: ``request`` or ``response``.
            section: The pact ``request`` or ``response`` object.
            pointer: JSON Pointer of that object.
        """
        rules = parse_matching_rules(section.get("matchingRules"), f"{pointer}/matchingRules")
        if not rules:
            return
        self.result.checks.append(f"{side}.matching-rules")
        body_paths = {
            rule.path: parse_path(rule.path) for rule in rules if rule.category == "body"
        }
        counts = self.result.matching_rules
        for rule in rules:
            counts["total"] += 1
            site, example = self.sites.get(
                (side, rule.category, "" if rule.category == "body" else rule.path.lower()),
                (None, None),
            )
            if rule.category == "path":
                example = str(section.get("path", ""))
            outcome = evaluate_rule(
                rule,
                direction=side,
                schemas=self.schemas,
                site=site,
                example=example,
                other_paths=[
                    steps
                    for path, steps in body_paths.items()
                    if steps is not None and path != rule.path
                ],
                cache=self.shared.rule_cache,
                budget=self.shared.rule_budget,
            )
            where = f" at {rule.path}" if rule.path else ""
            subject = f"the {side} {rule.category} matching rule '{rule.kind}'{where}"
            if outcome.status == "verified":
                counts["verified"] += 1
            elif outcome.status == "unverified":
                counts["unverified"] += 1
                self.note(
                    "matching-rule-unverified",
                    f"{subject} is not proven by the provider's schema ({outcome.reason})",
                    rule.pointer,
                    reason=outcome.reason,
                    oas_pointer=outcome.oas_pointer,
                    matcher=rule.kind,
                    constraint=outcome.constraint,
                )
            else:
                counts["notMapped"] += 1
                self.note(
                    "matching-rule-not-mapped",
                    f"{subject} has no lossless JSON Schema mapping ({outcome.reason}); only "
                    "its example was compared",
                    rule.pointer,
                    reason=outcome.reason,
                    matcher=rule.kind,
                )

    def _note_generators(self, section: Mapping[str, Any], pointer: str) -> None:
        """Record every generator of a request or a response in the fidelity list.

        Args:
            section: The pact ``request`` or ``response`` object.
            pointer: JSON Pointer of that object.
        """
        generators = section.get("generators")
        if not isinstance(generators, dict):
            return
        for category in sorted(str(key) for key in generators):
            value = generators[category]
            where = f"{pointer}/generators/{json_pointer_escape(category)}"
            entries: List[Tuple[str, Any]] = (
                [(where, value)]
                if not isinstance(value, dict) or "type" in value
                else [
                    (f"{where}/{json_pointer_escape(str(path))}", value[path])
                    for path in sorted(value, key=str)
                ]
            )
            for entry_pointer, generator in entries:
                kind = _as_dict(generator).get("type")
                self.note(
                    "generator-not-applied",
                    f"the {category} generator '{kind}' replaces the example when the pact is "
                    "verified; only the example was compared",
                    entry_pointer,
                    matcher=str(kind) if kind is not None else None,
                )


def _run_bounded(run: _InteractionRun) -> InteractionResult:
    """Compare one interaction, turning runaway nesting into a recorded gap.

    A pact is tenant input. A body nested hundreds of levels deep must cost that one
    interaction its comparison, not take the whole run down with a ``RecursionError``.

    Args:
        run: The prepared interaction run.

    Returns:
        The interaction's result; when it nests too deeply, whatever was found before the
        limit plus a ``body-not-compared`` note saying so.
    """
    try:
        return run.run()
    except RecursionError:
        run.note(
            "body-not-compared",
            "the interaction nests too deeply to be compared",
            run.pointer,
            reason="too-deep",
        )
        return run.result


def compare_pact_to_oas(pact: Any, oas: Any) -> ComparisonResult:
    """Decide whether a provider's OpenAPI document satisfies every interaction of a pact.

    Args:
        pact: The parsed pact document (Pact specification 1 to 4). A Pact 3 message pact
            (``messages`` instead of ``interactions``) is accepted; its messages are listed as
            not comparable.
        oas: The parsed provider contract: an OpenAPI 3.0, 3.1 or 3.2 document.

    Returns:
        The :class:`ComparisonResult`. Neither input is modified.

    Raises:
        PactOasCompareError: When ``pact`` is not a JSON object, or ``oas`` is not an
            OpenAPI 3.x document.
    """
    if not isinstance(pact, dict):
        raise PactOasCompareError("the pact is not a JSON object")
    if not isinstance(oas, dict):
        raise PactOasCompareError("the provider contract is not a JSON object")
    version = oas.get("openapi")
    if not isinstance(version, str) or not version.strip().startswith("3."):
        raise PactOasCompareError("the provider contract is not an OpenAPI 3.x document")

    try:
        shared = _Comparison(pact, oas)
    except RecursionError as exc:
        raise PactOasCompareError("the provider contract nests too deeply to be read") from exc
    result = ComparisonResult(
        consumer=pact_consumer_name(pact),
        provider=pact_provider_name(pact),
        pact_specification=pact_specification_version(pact),
        oas_version=version.strip(),
    )
    interactions = pact.get("interactions")
    for position, raw in enumerate(interactions if isinstance(interactions, list) else []):
        run = _InteractionRun(shared, position, _as_dict(raw), f"/interactions/{position}")
        result.interactions.append(_run_bounded(run))
    messages = pact.get("messages")
    offset = len(result.interactions)
    for position, raw in enumerate(messages if isinstance(messages, list) else []):
        message = dict(_as_dict(raw))
        message.setdefault("type", "Asynchronous/Messages")
        run = _InteractionRun(shared, offset + position, message, f"/messages/{position}")
        result.interactions.append(_run_bounded(run))
    return result
