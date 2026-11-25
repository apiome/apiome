"""Pact matching rules as JSON Schema constraints — PFX-2.2 (#6926).

A Pact example says "the consumer saw this value". A matching rule widens that to "any value
like this one": any string, anything matching a regular expression, an array of at least two.
Comparing only the example against the provider's OpenAPI document would ignore that widening
and report a green verdict stronger than the evidence.

This module reads the rules of Pact specification 2, 3 and 4 into one shape
(:func:`parse_matching_rules`), maps each onto the JSON Schema constraint that says exactly the
same thing (:func:`rule_constraint`, and the table :data:`MATCHER_MAPPINGS`), and asks whether
the provider's schema *proves* the constraint (:func:`evaluate_rule`):

* in a **request** the consumer may send any value the rule allows, so the provider's schema
  must accept all of them — it may not be narrower than the rule;
* in a **response** the consumer accepts only what the rule allows, so the provider's schema
  must promise nothing else — it may not be broader than the rule.

Three outcomes, never a silent one
----------------------------------
``verified`` — the schema proves the constraint. ``unverified`` — the rule was mapped but the
schema does not prove it (a regular expression the provider does not declare, a nullable field
under a type rule), with the reason. ``not-mapped`` — no JSON Schema constraint says the same
thing without loss (``date``, ``eachKey``, a rule combined with ``OR``). The last two are not
failures: the example was still validated. They are what the comparison could not vouch for,
and the caller records every one of them in the fidelity list.

Pure and deterministic: no I/O, and equal inputs produce equal outcomes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .change_taxonomy_enum import json_pointer_escape
from .pact_oas_schema import REQUEST, ProviderSchemas

__all__ = [
    "MATCHER_MAPPINGS",
    "MAX_COMPARISON_RULE_LOCATIONS",
    "MAX_RULE_LOCATIONS",
    "UNVERIFIED_REASONS",
    "MatcherMapping",
    "MatchingRule",
    "RuleOutcome",
    "evaluate_rule",
    "json_type",
    "parse_matching_rules",
    "rule_constraint",
    "schema_types",
    "select_path",
]

#: How many example values one rule is checked at (a rule on ``$.items[*]`` over a thousand
#: items describes one schema a thousand times).
MAX_RULE_LOCATIONS = 200

#: How many locations all the rules of one comparison are checked at together. A pact is tenant
#: input: without a ceiling, a file made of nothing but cascading rules would buy unbounded
#: work. Rules past the ceiling are reported as ``budget-exhausted``, not skipped.
MAX_COMPARISON_RULE_LOCATIONS = 100_000


@dataclass(frozen=True)
class MatcherMapping:
    """How one Pact matcher is read.

    Attributes:
        matcher: The ``match`` value, lowercase.
        versions: The Pact specification versions that define it.
        constraint: The JSON Schema constraint it maps to, as shown in the documentation, or
            ``None`` when it has no lossless mapping.
        note: Why, or what the mapping depends on.
    """

    matcher: str
    versions: str
    constraint: Optional[str]
    note: str


#: Every matcher the engine knows, in documentation order. This table **is** the published
#: mapping: :func:`rule_constraint` implements it and the tests hold the two together.
MATCHER_MAPPINGS: Tuple[MatcherMapping, ...] = (
    MatcherMapping(
        "type",
        "2, 3, 4",
        '{"type": <type of the example>}',
        "Cascades to every value below it that has no rule of its own. A number example "
        "allows any number in a response and an integer in a request. With `min` / `max` on "
        "an array it adds `minItems` / `maxItems`.",
    ),
    MatcherMapping("equality", "2, 3, 4", '{"const": <the example>}', "Stops a `type` cascade."),
    MatcherMapping(
        "regex", "2, 3, 4", '{"type": "string", "pattern": <regex>}', "The expression as written."
    ),
    MatcherMapping(
        "include",
        "3, 4",
        '{"type": "string", "pattern": <escaped value>}',
        "The substring, escaped so that it is matched literally.",
    ),
    MatcherMapping("integer", "3, 4", '{"type": "integer"}', ""),
    MatcherMapping("number", "3, 4", '{"type": "number"}', ""),
    MatcherMapping("boolean", "4", '{"type": "boolean"}', ""),
    MatcherMapping("null", "3, 4", '{"type": "null"}', ""),
    MatcherMapping(
        "notEmpty",
        "4",
        '{"minLength": 1}, {"minItems": 1} or {"minProperties": 1}',
        "By the type of the example, together with that type.",
    ),
    MatcherMapping(
        "decimal",
        "3, 4",
        None,
        "JSON Schema cannot require a number to have a fractional part.",
    ),
    MatcherMapping(
        "date / time / timestamp / datetime",
        "3, 4",
        None,
        "The format is a Java date pattern, which JSON Schema `format` cannot express.",
    ),
    MatcherMapping("semver", "4", None, "No JSON Schema keyword describes a semantic version."),
    MatcherMapping(
        "values / eachKey / eachValue",
        "3, 4",
        None,
        "The rule nests further rules for keys and values.",
    ),
    MatcherMapping("arrayContains", "4", None, "Each variant carries its own nested rules."),
    MatcherMapping("contentType", "3, 4", None, "Compares bytes by sniffed media type."),
    MatcherMapping(
        "statusCode", "4", None, "Applies to the response status, which is compared by example."
    ),
)

#: Why a mapped rule could not be proven, by reason code. Published with the mapping table.
UNVERIFIED_REASONS: Dict[str, str] = {
    "no-provider-schema": (
        "The provider declares no schema where the rule applies: the body was not compared, "
        "or the header, query or path parameter is not declared."
    ),
    "path-not-in-example": "The rule's path selects nothing in the example.",
    "path-not-declared": "The provider's schema declares nothing at the rule's path.",
    "composition": (
        "The provider's schema at the rule's path is combined with `allOf`, `anyOf`, `oneOf`, "
        "`not` or `if`; the engine does not reason across combinations."
    ),
    "provider-narrower": (
        "Request: the provider's schema refuses some values the rule lets the consumer send "
        "(an `enum`, a `pattern`, a length or range limit, another type)."
    ),
    "provider-nullable": "Response: the provider may return `null` where the rule expects a value.",
    "provider-broader": "Response: the provider may return a type the rule does not accept.",
    "provider-type-undeclared": "Response: the provider's schema declares no `type` here.",
    "pattern-not-guaranteed": (
        "Response: the provider's schema does not declare the rule's expression as its "
        "`pattern`."
    ),
    "value-not-guaranteed": "Response: the provider's schema does not fix the value with `const`.",
    "bounds-not-guaranteed": (
        "Response: the provider's schema does not promise the length the rule requires."
    ),
    "budget-exhausted": (
        "The pact's rules apply at more than 100,000 locations; the rules past that were not "
        "checked."
    ),
}

#: Why a rule has no mapping at all, by reason code.
NOT_MAPPED_REASONS: Dict[str, str] = {
    "no-lossless-mapping": "No JSON Schema constraint says what the matcher says.",
    "combined-with-or": "Several matchers are combined with `OR`.",
    "path-not-understood": "The rule's path is not a JSONPath the engine reads.",
    "unknown-location": "The rule is filed under a part of the message the engine does not know.",
}

#: Schema keywords that make a provider refuse values a request-side rule allows.
_NARROWING = (
    "enum",
    "const",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "contains",
)

#: Lower bounds a rule can itself guarantee.
_LOWER_BOUNDS = ("minLength", "minItems", "minProperties")

#: One step of a Pact rule path after the leading ``$``.
_PATH_STEP = re.compile(
    r"""\.\*|\[\*\]|\.([^.\[\]]+)|\[(\d+)\]|\['((?:[^'\\]|\\.)*)'\]|\["((?:[^"\\]|\\.)*)"\]"""
)

#: Marks "any child" in a parsed rule path.
_ANY = None


@dataclass(frozen=True)
class MatchingRule:
    """One matcher from a Pact interaction, wherever its specification version filed it.

    Attributes:
        category: ``body``, ``header``, ``query``, ``path``, ``status`` or ``unknown``.
        path: The JSONPath for a body rule (``$.items[*].id``), the header or query name, or
            ``""`` for a path or status rule.
        kind: The matcher, lowercase (``type``, ``regex`` …).
        matcher: The matcher object as the pact wrote it.
        pointer: JSON Pointer of the rule in the pact document.
        combine: ``AND`` or ``OR`` — how it combines with its siblings on the same path.
        siblings: How many matchers share its path.
    """

    category: str
    path: str
    kind: str
    matcher: Mapping[str, Any]
    pointer: str
    combine: str = "AND"
    siblings: int = 1


@dataclass(frozen=True)
class RuleOutcome:
    """What the comparison could say about one rule.

    Attributes:
        status: ``verified``, ``unverified`` or ``not-mapped``.
        reason: Reason code for the last two (:data:`UNVERIFIED_REASONS` /
            :data:`NOT_MAPPED_REASONS`), else ``None``.
        constraint: The JSON Schema constraint the rule mapped to, when it mapped.
        oas_pointer: JSON Pointer of the provider schema that failed to prove it, when known.
        locations: How many example values the rule could not be proven at.
    """

    status: str
    reason: Optional[str] = None
    constraint: Optional[Dict[str, Any]] = None
    oas_pointer: Optional[str] = None
    locations: int = 0


# =============================================================================================
# Reading rules
# =============================================================================================


def _matcher_kind(matcher: Mapping[str, Any]) -> str:
    """Name the matcher an object describes.

    Pact 2 writers leave ``match`` out when another key implies it.

    Args:
        matcher: One matcher object.

    Returns:
        The lowercase matcher name, or ``unknown``.
    """
    declared = matcher.get("match")
    if isinstance(declared, str) and declared.strip():
        kind = declared.strip().lower()
        return "type" if kind in ("min", "max", "minmax", "min-type", "max-type") else kind
    if "regex" in matcher:
        return "regex"
    if "min" in matcher or "max" in matcher:
        return "type"
    return "unknown"


def _rules_at(
    category: str, path: str, value: Any, pointer: str
) -> List[MatchingRule]:
    """Read the matcher or matchers filed at one path.

    Args:
        category: The rule category.
        path: The rule's path or name.
        value: A matcher object (Pact 2) or ``{"matchers": [...], "combine": ...}`` (3, 4).
        pointer: JSON Pointer of ``value`` in the pact document.

    Returns:
        One rule per matcher; a value that is no matcher at all yields one ``unknown`` rule so
        that it is still accounted for.
    """
    if not isinstance(value, dict):
        return [MatchingRule(category, path, "unknown", {}, pointer)]
    matchers = value.get("matchers")
    if isinstance(matchers, list):
        combine = str(value.get("combine", "AND")).upper()
        usable = [(n, m) for n, m in enumerate(matchers) if isinstance(m, dict)]
        return [
            MatchingRule(
                category,
                path,
                _matcher_kind(matcher),
                matcher,
                f"{pointer}/matchers/{position}",
                combine,
                len(usable),
            )
            for position, matcher in usable
        ]
    return [MatchingRule(category, path, _matcher_kind(value), value, pointer)]


def _pact2_location(key: str) -> Tuple[str, str]:
    """File a Pact 2 rule key (``$.body.id``, ``$.headers.Accept``) under its category.

    Args:
        key: The rule key.

    Returns:
        ``(category, path)``.
    """
    for prefix, category in (
        ("$.body", "body"),
        ("$.headers", "header"),
        ("$.header", "header"),
        ("$.query", "query"),
        ("$.path", "path"),
    ):
        if key == prefix or key.startswith((f"{prefix}.", f"{prefix}[")):
            rest = key[len(prefix):]
            if category == "body":
                return category, f"${rest}"
            if category == "path":
                return category, ""
            steps = parse_path(f"${rest}")
            name = steps[0] if steps and isinstance(steps[0], str) else rest.lstrip(".")
            return category, str(name)
    return "unknown", key


def parse_matching_rules(section: Any, pointer: str) -> List[MatchingRule]:
    """Read a request's or response's ``matchingRules`` in any specification version.

    Args:
        section: The ``matchingRules`` value.
        pointer: JSON Pointer of that value in the pact document.

    Returns:
        Every matcher, in a stable order (category, then path, then position).
    """
    if not isinstance(section, dict) or not section:
        return []
    rules: List[MatchingRule] = []
    if any(str(key).startswith("$") for key in section):
        for key in sorted(str(k) for k in section):
            category, path = _pact2_location(key)
            rules.extend(
                _rules_at(category, path, section[key], f"{pointer}/{json_pointer_escape(key)}")
            )
        return rules
    aliases = {"headers": "header", "body": "body", "header": "header", "query": "query"}
    for key in sorted(str(k) for k in section):
        value = section[key]
        where = f"{pointer}/{json_pointer_escape(key)}"
        if key in ("path", "status"):
            rules.extend(_rules_at(key, "", value, where))
        elif key in aliases and isinstance(value, dict):
            for path in sorted(str(p) for p in value):
                rules.extend(
                    _rules_at(
                        aliases[key], path, value[path], f"{where}/{json_pointer_escape(path)}"
                    )
                )
        else:
            rules.extend(_rules_at("unknown", key, value, where))
    return rules


def parse_path(expression: str) -> Optional[List[Any]]:
    """Parse a Pact rule path.

    Args:
        expression: A path such as ``$``, ``$.items[*].id`` or ``$['a b'][0]``.

    Returns:
        The steps — a ``str`` for a property, an ``int`` for an index, ``None`` for "any
        child" — or ``None`` when the expression is not one this engine reads.
    """
    text = (expression or "").strip()
    if not text.startswith("$"):
        return None
    steps: List[Any] = []
    position = 1
    while position < len(text):
        match = _PATH_STEP.match(text, position)
        if match is None:
            return None
        name, index, single, double = match.groups()
        if name is not None:
            steps.append(name)
        elif index is not None:
            steps.append(int(index))
        elif single is not None or double is not None:
            steps.append(re.sub(r"\\(.)", r"\1", single if single is not None else double))
        else:
            steps.append(_ANY)
        position = match.end()
    return steps


def select_path(value: Any, steps: Sequence[Any]) -> List[Tuple[Tuple[Any, ...], Any]]:
    """Find the example values a rule path selects.

    Args:
        value: The example (a parsed JSON value).
        steps: The parsed rule path.

    Returns:
        ``(tokens, value)`` pairs in document order, at most :data:`MAX_RULE_LOCATIONS`; the
        tokens are the concrete property names and indexes that lead to the value.
    """
    found: List[Tuple[Tuple[Any, ...], Any]] = [((), value)]
    for step in steps:
        advanced: List[Tuple[Tuple[Any, ...], Any]] = []
        for tokens, current in found:
            if step is _ANY:
                if isinstance(current, dict):
                    advanced.extend((tokens + (str(k),), current[k]) for k in sorted(current))
                elif isinstance(current, list):
                    advanced.extend((tokens + (n,), item) for n, item in enumerate(current))
            elif isinstance(step, int):
                if isinstance(current, list) and step < len(current):
                    advanced.append((tokens + (step,), current[step]))
            elif isinstance(current, dict) and step in current:
                advanced.append((tokens + (step,), current[step]))
            if len(advanced) >= MAX_RULE_LOCATIONS:
                break
        found = advanced[:MAX_RULE_LOCATIONS]
    return found


def _path_covers(steps: Sequence[Any], tokens: Sequence[Any]) -> bool:
    """Whether a rule path names exactly one concrete location.

    Args:
        steps: A parsed rule path.
        tokens: Concrete tokens of a location.

    Returns:
        True when each step matches the token at its position.
    """
    if len(steps) != len(tokens):
        return False
    return all(step is _ANY or step == token for step, token in zip(steps, tokens))


# =============================================================================================
# Mapping
# =============================================================================================


def json_type(value: Any) -> str:
    """The JSON Schema type name of a parsed JSON value.

    Args:
        value: The value.

    Returns:
        ``null``, ``boolean``, ``integer``, ``number``, ``string``, ``array`` or ``object``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _example_type(value: Any, direction: str) -> str:
    """The type a ``type`` rule stands for, given its example.

    Pact has one number type: ``like(5)`` accepts ``5.5``. In a response that is what the
    consumer accepts. In a request the consumer sends what its example shows, so an integer
    example is read as an integer.

    Args:
        value: The example value.
        direction: ``request`` or ``response``.

    Returns:
        The JSON Schema type name.
    """
    name = json_type(value)
    return "number" if name == "integer" and direction != REQUEST else name


def rule_constraint(
    kind: str, matcher: Mapping[str, Any], example: Any, direction: str
) -> Optional[Dict[str, Any]]:
    """Map one matcher onto the JSON Schema constraint that says the same thing.

    Args:
        kind: The matcher name, lowercase.
        matcher: The matcher object.
        example: The example value the rule applies to.
        direction: ``request`` or ``response``.

    Returns:
        The constraint, or ``None`` when :data:`MATCHER_MAPPINGS` lists no lossless mapping.
    """
    if kind == "type":
        constraint: Dict[str, Any] = {"type": _example_type(example, direction)}
        if isinstance(example, list):
            for bound, keyword in (("min", "minItems"), ("max", "maxItems")):
                limit = matcher.get(bound)
                if isinstance(limit, int) and not isinstance(limit, bool):
                    constraint[keyword] = limit
        return constraint
    if kind == "equality":
        return {"const": example}
    if kind == "regex":
        pattern = matcher.get("regex")
        return {"type": "string", "pattern": pattern} if isinstance(pattern, str) else None
    if kind == "include":
        value = matcher.get("value")
        return {"type": "string", "pattern": re.escape(value)} if isinstance(value, str) else None
    if kind in ("integer", "number", "boolean", "null"):
        return {"type": kind}
    if kind == "notempty":
        name = json_type(example)
        bounds = {"string": "minLength", "array": "minItems", "object": "minProperties"}
        return {"type": name, bounds[name]: 1} if name in bounds else {"type": name}
    return None


def schema_types(schema: Any) -> Optional[Set[str]]:
    """The JSON types a plain schema admits.

    Args:
        schema: A schema node in 2020-12 form.

    Returns:
        The type names, or ``None`` when the schema does not say.
    """
    if not isinstance(schema, dict):
        return None
    declared = schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {str(name) for name in declared}
    if "const" in schema:
        return {json_type(schema["const"])}
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return {json_type(value) for value in schema["enum"]}
    return None


def _fixed_values(schema: Mapping[str, Any]) -> Optional[List[Any]]:
    """The finite list of values a schema allows, when it declares one.

    Args:
        schema: A schema node.

    Returns:
        The values of ``const`` or ``enum``, or ``None``.
    """
    if "const" in schema:
        return [schema["const"]]
    values = schema.get("enum")
    return list(values) if isinstance(values, list) and values else None


def _accepts(schema: Mapping[str, Any], constraint: Mapping[str, Any]) -> Optional[str]:
    """Whether a provider schema accepts **every** value a request-side constraint allows.

    The example itself has already been validated, so this only looks for ways the schema is
    narrower than the rule.

    Args:
        schema: The provider's plain schema, 2020-12 form.
        constraint: The rule's constraint.

    Returns:
        ``None`` when proven, else the reason code.
    """
    if "const" in constraint:
        return None
    wanted = constraint.get("type")
    types = schema_types(schema)
    if types is not None and wanted is not None:
        if wanted not in types and not (wanted == "integer" and "number" in types):
            return "provider-narrower"
    if wanted == "object":
        return None
    for keyword in _NARROWING:
        if keyword not in schema:
            continue
        declared = schema[keyword]
        if keyword == "pattern" and constraint.get("pattern") == declared:
            continue
        if keyword == "uniqueItems" and declared is False:
            continue
        if keyword in _LOWER_BOUNDS:
            promised = constraint.get(keyword, 0)
            if isinstance(declared, int) and declared <= promised:
                continue
        if keyword == "maxItems" and isinstance(constraint.get("maxItems"), int):
            if isinstance(declared, int) and declared >= constraint["maxItems"]:
                continue
        return "provider-narrower"
    return None


def _guarantees(schema: Mapping[str, Any], constraint: Mapping[str, Any]) -> Optional[str]:
    """Whether a provider schema promises **only** values a response-side constraint accepts.

    Args:
        schema: The provider's plain schema, 2020-12 form.
        constraint: The rule's constraint.

    Returns:
        ``None`` when proven, else the reason code.
    """
    for keyword in sorted(constraint):
        wanted = constraint[keyword]
        if keyword == "type":
            types = schema_types(schema)
            if types is None:
                return "provider-type-undeclared"
            extra = {
                name
                for name in types
                if name != wanted and not (wanted == "number" and name == "integer")
            }
            if extra == {"null"}:
                return "provider-nullable"
            if extra:
                return "provider-broader"
        elif keyword == "pattern":
            # Only the same expression is proof. Running the pact's expression over the
            # provider's enum would prove more, but both are tenant input and a hostile
            # expression must never be evaluated here.
            if schema.get("pattern") != wanted:
                return "pattern-not-guaranteed"
        elif keyword == "const":
            fixed = _fixed_values(schema)
            if fixed != [wanted] or json_type(fixed[0]) != json_type(wanted):
                return "value-not-guaranteed"
        elif keyword in _LOWER_BOUNDS:
            declared = schema.get(keyword)
            if not isinstance(declared, int) or declared < wanted:
                return "bounds-not-guaranteed"
        elif keyword == "maxItems":
            declared = schema.get(keyword)
            if not isinstance(declared, int) or declared > wanted:
                return "bounds-not-guaranteed"
    return None


# =============================================================================================
# Evaluation
# =============================================================================================


def _leaves(
    tokens: Tuple[Any, ...], value: Any, budget: List[int]
) -> List[Tuple[Tuple[Any, ...], Any]]:
    """Every value strictly below a location, containers included.

    Args:
        tokens: Tokens of the starting location.
        value: The value there.
        budget: One-element list holding how many more locations may be listed.

    Returns:
        ``(tokens, value)`` for each descendant, in document order.
    """
    found: List[Tuple[Tuple[Any, ...], Any]] = []
    children: List[Tuple[Any, Any]] = []
    if isinstance(value, dict):
        children = [(str(key), value[key]) for key in sorted(value, key=str)]
    elif isinstance(value, list):
        children = list(enumerate(value))
    for token, child in children:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        found.append((tokens + (token,), child))
        found.extend(_leaves(tokens + (token,), child, budget))
    return found


def evaluate_rule(
    rule: MatchingRule,
    *,
    direction: str,
    schemas: ProviderSchemas,
    site: Optional[str],
    example: Any,
    other_paths: Sequence[Sequence[Any]] = (),
    cache: Optional[Dict[Tuple[str, str, str], Optional[str]]] = None,
    budget: Optional[List[int]] = None,
) -> RuleOutcome:
    """Decide what the provider's schema proves about one matching rule.

    Args:
        rule: The rule.
        direction: ``request`` or ``response`` (see the module docstring).
        schemas: The provider's schemas.
        site: JSON Pointer of the schema the rule's part of the message is described by — the
            body schema for a body rule, the parameter's or header's schema otherwise — or
            ``None`` when the provider declares none.
        example: The example the rule's path is read against: the body for a body rule, the
            header / query / path value otherwise.
        other_paths: The parsed paths of the other body rules of the same message, used to
            stop a ``type`` cascade where a more specific rule takes over.
        cache: Shared memo of ``(direction, schema pointer, constraint) → reason``, so one
            schema is not re-examined for every element of a long array.
        budget: One-element list holding how many more locations this comparison may check
            (see :data:`MAX_COMPARISON_RULE_LOCATIONS`); decremented here. ``None`` means no
            ceiling.

    Returns:
        The :class:`RuleOutcome`.
    """
    if rule.category in ("status", "unknown"):
        reason = "unknown-location" if rule.category == "unknown" else "no-lossless-mapping"
        return RuleOutcome("not-mapped", reason)
    if rule.combine == "OR" and rule.siblings > 1:
        return RuleOutcome("not-mapped", "combined-with-or")

    steps: Optional[List[Any]] = parse_path(rule.path) if rule.category == "body" else []
    if steps is None:
        return RuleOutcome("not-mapped", "path-not-understood")
    selected = select_path(example, steps) if site is not None or not steps else []
    probe = selected[0][1] if selected else None
    first_constraint = rule_constraint(rule.kind, rule.matcher, probe, direction)
    if first_constraint is None:
        return RuleOutcome("not-mapped", "no-lossless-mapping")
    if site is None:
        return RuleOutcome(
            "unverified", "no-provider-schema", first_constraint if selected else None
        )
    if not selected:
        return RuleOutcome("unverified", "path-not-in-example")
    if budget is not None and budget[0] <= 0:
        return RuleOutcome("unverified", "budget-exhausted", first_constraint)

    memo = cache if cache is not None else {}
    unproven: List[Tuple[str, Optional[str]]] = []

    def check(tokens: Tuple[Any, ...], constraint: Dict[str, Any]) -> None:
        """Check one constraint at one location and record what is not proven."""
        if budget is not None:
            budget[0] -= 1
        pointer, reason = schemas.descend(site, tokens)
        if pointer is not None:
            key = (direction, pointer, json.dumps(constraint, sort_keys=True, default=str))
            if key not in memo:
                node = schemas.node(pointer, normalized=True) or {}
                memo[key] = (
                    _accepts(node, constraint)
                    if direction == REQUEST
                    else _guarantees(node, constraint)
                )
            reason = memo[key]
        elif direction == REQUEST and reason == "path-not-declared":
            # The provider says nothing about this value, so it accepts whatever the rule
            # lets the consumer send. (Were the object closed, validating the example would
            # already have failed.)
            reason = None
        if reason is not None:
            unproven.append((reason, pointer))

    leaf_budget = [MAX_RULE_LOCATIONS]
    for tokens, value in selected:
        constraint = rule_constraint(rule.kind, rule.matcher, value, direction)
        if constraint is None:
            return RuleOutcome("not-mapped", "no-lossless-mapping")
        check(tokens, constraint)
        if rule.kind != "type":
            continue
        # A type rule cascades: every value below it is matched by type too, until a more
        # specific rule takes over.
        deeper = [path for path in other_paths if len(path) > len(steps)]
        for leaf_tokens, leaf in _leaves(tokens, value, leaf_budget):
            if any(
                _path_covers(path, leaf_tokens[: len(path)])
                for path in deeper
                if len(path) <= len(leaf_tokens)
            ):
                continue
            check(leaf_tokens, {"type": _example_type(leaf, direction)})

    if not unproven:
        return RuleOutcome("verified", None, first_constraint)
    reason, pointer = unproven[0]
    return RuleOutcome("unverified", reason, first_constraint, pointer, len(unproven))
