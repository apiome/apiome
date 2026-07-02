"""Schema-valid mock data generation for the Mock Server (#3615, RC1-2.2).

Given a JSON Schema (a fragment of the frozen OpenAPI document, possibly carrying ``$ref`` pointers
into ``components/schemas``), produce an example value that satisfies the schema's constraints. The
goal is *plausible and valid*, not exhaustive fuzzing:

* Explicit author intent wins — ``example`` / ``examples`` / ``default`` / ``const`` / first ``enum``
  are used verbatim when present.
* Otherwise a value is synthesised from ``type`` plus ``format`` and the property name (a small
  Faker-style heuristic table covering the common fields: email, name, id, timestamps, ...).
* Numeric / string / array bounds (``minimum``/``maximum``, ``minLength``/``maxLength``,
  ``minItems``/``maxItems``) are respected so the output validates.

Generation is **deterministic**: the same ``(schema, seed, field name)`` always yields the same
value. This keeps mock responses stable across requests (and reproducible in tests) without any
external state. ``$ref`` resolution and ``allOf``/``anyOf``/``oneOf`` composition are supported with
a recursion-depth guard so self-referential schemas terminate.

The companion :func:`validate_value` runs the generated value back through ``jsonschema`` so callers
(and the test-suite) can assert the contract "responses validate against the schema" directly.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional, Tuple

import jsonschema

# Cap nested generation so recursive/self-referential schemas (a Tree whose child is a Tree, an
# object that $refs itself) cannot recurse without bound. Past this depth optional structure is
# dropped (null / empty), which still validates because the offending branch is not "required".
_MAX_DEPTH = 6

# Heuristic mapping of common property-name substrings to a generator key. Checked in order, so more
# specific names ("first_name") are matched before generic ones ("name"). Purely cosmetic — it only
# affects which realistic value is produced, never schema validity.
_NAME_HINTS: Tuple[Tuple[str, str], ...] = (
    ("email", "email"),
    ("first_name", "first_name"),
    ("firstname", "first_name"),
    ("last_name", "last_name"),
    ("lastname", "last_name"),
    ("full_name", "full_name"),
    ("username", "username"),
    ("user_name", "username"),
    ("name", "full_name"),
    ("phone", "phone"),
    ("city", "city"),
    ("country", "country"),
    ("street", "street"),
    ("address", "street"),
    ("zip", "zipcode"),
    ("postal", "zipcode"),
    ("company", "company"),
    ("title", "title"),
    ("description", "sentence"),
    ("summary", "sentence"),
    ("url", "url"),
    ("uri", "url"),
    ("website", "url"),
    ("avatar", "url"),
    ("image", "url"),
    ("price", "price"),
    ("amount", "price"),
    ("cost", "price"),
    ("quantity", "small_int"),
    ("count", "small_int"),
    ("age", "small_int"),
    ("status", "status"),
    ("state", "status"),
    ("color", "color"),
    ("colour", "color"),
    ("uuid", "uuid"),
    ("guid", "uuid"),
    ("id", "id"),
)

_FIRST_NAMES = ("Ada", "Bjarne", "Grace", "Linus", "Margaret", "Dennis", "Barbara", "Ken")
_LAST_NAMES = ("Lovelace", "Stroustrup", "Hopper", "Torvalds", "Hamilton", "Ritchie", "Liskov")
_CITIES = ("Springfield", "Riverton", "Fairview", "Greenville", "Madison", "Georgetown")
_COUNTRIES = ("United States", "Canada", "United Kingdom", "Germany", "Japan", "Australia")
_COMPANIES = ("Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries")
_STATUSES = ("active", "pending", "inactive", "archived")
_COLORS = ("red", "green", "blue", "amber", "violet", "teal")
_WORDS = ("lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit")


def _seeded_rng(seed: int, *parts: str) -> random.Random:
    """A deterministic RNG bound to ``seed`` plus a stable hash of ``parts``.

    Mixing the field path into the seed means sibling fields get different (but reproducible) values
    rather than all collapsing onto the same draw.
    """
    digest = hashlib.sha256(("\x00".join(parts)).encode("utf-8")).hexdigest()
    return random.Random(seed ^ int(digest[:16], 16))


def _resolve_ref(ref: str, root: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a local ``#/...`` JSON pointer against ``root``; non-local refs yield ``{}``."""
    if not ref.startswith("#/"):
        return {}
    node: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _merge_all_of(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-merge ``allOf`` subschemas into a single object schema."""
    merged: Dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
    props: Dict[str, Any] = dict(merged.get("properties", {}))
    required: List[str] = list(merged.get("required", []))
    for sub in schema.get("allOf", []):
        sub = _deref(sub, root)
        if sub.get("type") and "type" not in merged:
            merged["type"] = sub["type"]
        props.update(sub.get("properties", {}))
        required.extend(sub.get("required", []))
    if props:
        merged["properties"] = props
        merged.setdefault("type", "object")
    if required:
        merged["required"] = sorted(set(required))
    return merged


def _deref(schema: Any, root: Dict[str, Any]) -> Dict[str, Any]:
    """Follow a single ``$ref`` if present; otherwise return the schema unchanged."""
    if isinstance(schema, dict) and "$ref" in schema:
        return _resolve_ref(schema["$ref"], root)
    return schema if isinstance(schema, dict) else {}


def _schema_type(schema: Dict[str, Any]) -> Optional[str]:
    """Best-effort single JSON-Schema type for ``schema`` (first of a list, inferred if absent)."""
    t = schema.get("type")
    if isinstance(t, list):
        # Prefer a concrete, generatable type over "null".
        for candidate in t:
            if candidate != "null":
                return candidate
        return t[0] if t else None
    if t:
        return t
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    if "enum" in schema and schema["enum"]:
        return None  # enum handled directly regardless of type
    return None


def _string_for_name(field: str, rng: random.Random) -> str:
    """Produce a realistic string for ``field`` using the name-hint table."""
    lowered = field.lower()
    key = "word"
    for needle, hint in _NAME_HINTS:
        if needle in lowered:
            key = hint
            break
    if key == "email":
        return f"{rng.choice(_FIRST_NAMES).lower()}.{rng.choice(_LAST_NAMES).lower()}@example.com"
    if key == "first_name":
        return rng.choice(_FIRST_NAMES)
    if key == "last_name":
        return rng.choice(_LAST_NAMES)
    if key == "full_name":
        return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
    if key == "username":
        return f"{rng.choice(_FIRST_NAMES).lower()}{rng.randint(1, 999)}"
    if key == "phone":
        return f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
    if key == "city":
        return rng.choice(_CITIES)
    if key == "country":
        return rng.choice(_COUNTRIES)
    if key == "street":
        return f"{rng.randint(1, 9999)} {rng.choice(_LAST_NAMES)} St"
    if key == "zipcode":
        return f"{rng.randint(10000, 99999)}"
    if key == "company":
        return rng.choice(_COMPANIES)
    if key == "title":
        return " ".join(rng.choice(_WORDS).capitalize() for _ in range(3))
    if key == "sentence":
        return " ".join(rng.choice(_WORDS) for _ in range(8)).capitalize() + "."
    if key == "url":
        return f"https://example.com/{rng.choice(_WORDS)}/{rng.randint(1, 999)}"
    if key == "status":
        return rng.choice(_STATUSES)
    if key == "color":
        return rng.choice(_COLORS)
    if key == "uuid":
        return _uuid_like(rng)
    if key == "id":
        return f"{rng.choice(_WORDS)}-{rng.randint(1000, 9999)}"
    return rng.choice(_WORDS)


def _uuid_like(rng: random.Random) -> str:
    """A syntactically valid UUIDv4-shaped string from a seeded RNG."""
    hexd = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    return f"{hexd[:8]}-{hexd[8:12]}-4{hexd[13:16]}-8{hexd[17:20]}-{hexd[20:32]}"


def _string_for_format(fmt: str, field: str, rng: random.Random) -> Optional[str]:
    """Generate a string matching a JSON-Schema ``format``; ``None`` if the format is unknown."""
    if fmt == "email":
        return f"{rng.choice(_FIRST_NAMES).lower()}@example.com"
    if fmt in ("uri", "url", "uri-reference"):
        return f"https://example.com/{rng.choice(_WORDS)}"
    if fmt == "uuid":
        return _uuid_like(rng)
    if fmt == "date":
        return f"20{rng.randint(20, 29)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if fmt in ("date-time", "datetime"):
        return (
            f"20{rng.randint(20, 29)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
        )
    if fmt == "time":
        return f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
    if fmt in ("ipv4", "ip"):
        return ".".join(str(rng.randint(1, 254)) for _ in range(4))
    if fmt == "ipv6":
        return ":".join("".join(rng.choice("0123456789abcdef") for _ in range(4)) for _ in range(8))
    if fmt == "hostname":
        return f"{rng.choice(_WORDS)}.example.com"
    return None


def _clamp_string(value: str, schema: Dict[str, Any]) -> str:
    """Pad/truncate ``value`` to satisfy ``minLength``/``maxLength`` if present."""
    min_len = schema.get("minLength")
    max_len = schema.get("maxLength")
    if isinstance(min_len, int) and len(value) < min_len:
        value = (value + ("x" * min_len))[:min_len] if value else "x" * min_len
    if isinstance(max_len, int) and len(value) > max_len:
        value = value[:max_len]
    return value


def _gen_number(schema: Dict[str, Any], rng: random.Random, integer: bool) -> Any:
    """Generate a number within ``minimum``/``maximum``/``multipleOf`` bounds."""
    minimum = schema.get("minimum", schema.get("exclusiveMinimum"))
    maximum = schema.get("maximum", schema.get("exclusiveMaximum"))
    lo = float(minimum) if isinstance(minimum, (int, float)) else 0.0
    hi = float(maximum) if isinstance(maximum, (int, float)) else lo + 1000.0
    if hi < lo:
        hi = lo
    if "exclusiveMinimum" in schema and isinstance(schema["exclusiveMinimum"], (int, float)):
        lo += 1 if integer else 0.01
    if "exclusiveMaximum" in schema and isinstance(schema["exclusiveMaximum"], (int, float)):
        hi -= 1 if integer else 0.01
    if hi < lo:
        hi = lo
    if integer:
        value: Any = rng.randint(int(lo), int(hi)) if int(hi) >= int(lo) else int(lo)
    else:
        value = round(rng.uniform(lo, hi), 2)
    multiple_of = schema.get("multipleOf")
    if isinstance(multiple_of, (int, float)) and multiple_of > 0:
        steps = round(value / multiple_of)
        value = steps * multiple_of
        if integer:
            value = int(value)
        if isinstance(minimum, (int, float)) and value < minimum:
            value += multiple_of
    return value


def generate_example(
    schema: Any,
    root: Optional[Dict[str, Any]] = None,
    *,
    seed: int = 0,
    field: str = "root",
    _depth: int = 0,
) -> Any:
    """Generate a schema-valid example value.

    Args:
        schema: A JSON-Schema fragment (may contain ``$ref`` into ``root``).
        root: The full document used to resolve ``$ref`` pointers (defaults to ``schema``).
        seed: Deterministic seed; identical inputs always yield identical output.
        field: Property name used for realistic-value heuristics and RNG mixing.
        _depth: Internal recursion guard.

    Returns:
        A Python value (dict/list/str/number/bool/None) that validates against ``schema``.
    """
    if root is None:
        root = schema if isinstance(schema, dict) else {}
    schema = _deref(schema, root)
    if not isinstance(schema, dict) or not schema:
        return None

    rng = _seeded_rng(seed, field, str(_depth))

    # 1. Explicit author intent always wins.
    if "const" in schema:
        return schema["const"]
    if "example" in schema:
        return schema["example"]
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and "value" in first:
            return first["value"]
        return first
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    if "allOf" in schema:
        schema = _merge_all_of(schema, root)
    for combinator in ("oneOf", "anyOf"):
        options = schema.get(combinator)
        if isinstance(options, list) and options:
            return generate_example(
                options[0], root, seed=seed, field=field, _depth=_depth + 1
            )

    jtype = _schema_type(schema)

    if jtype == "object" or "properties" in schema:
        return _gen_object(schema, root, seed, field, _depth, rng)
    if jtype == "array":
        return _gen_array(schema, root, seed, field, _depth, rng)
    if jtype == "boolean":
        return rng.choice((True, False))
    if jtype == "integer":
        return _gen_number(schema, rng, integer=True)
    if jtype == "number":
        return _gen_number(schema, rng, integer=False)
    if jtype == "null":
        return None
    if jtype == "string":
        fmt = schema.get("format")
        if isinstance(fmt, str):
            by_format = _string_for_format(fmt, field, rng)
            if by_format is not None:
                return _clamp_string(by_format, schema)
        return _clamp_string(_string_for_name(field, rng), schema)

    # Untyped schema with no signal: a short string is the safest broadly-valid value.
    return _clamp_string(_string_for_name(field, rng), schema)


def _gen_object(
    schema: Dict[str, Any],
    root: Dict[str, Any],
    seed: int,
    field: str,
    depth: int,
    rng: random.Random,
) -> Dict[str, Any]:
    """Generate an object, always populating ``required`` and (until depth cap) optional props."""
    result: Dict[str, Any] = {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    if depth >= _MAX_DEPTH:
        # Past the cap, emit only required scalars so the object still validates without recursing.
        properties = {k: v for k, v in properties.items() if k in required}
    for prop_name, prop_schema in properties.items():
        result[prop_name] = generate_example(
            prop_schema, root, seed=seed, field=prop_name, _depth=depth + 1
        )
    # Honour additionalProperties only when there are no declared props and it carries a schema.
    if not properties and isinstance(schema.get("additionalProperties"), dict):
        result["key"] = generate_example(
            schema["additionalProperties"], root, seed=seed, field="value", _depth=depth + 1
        )
    return result


def _gen_array(
    schema: Dict[str, Any],
    root: Dict[str, Any],
    seed: int,
    field: str,
    depth: int,
    rng: random.Random,
) -> List[Any]:
    """Generate an array honouring ``minItems``/``maxItems`` (default 2 items)."""
    items_schema = schema.get("items", {})
    min_items = schema.get("minItems", 0)
    max_items = schema.get("maxItems")
    count = 2
    if isinstance(min_items, int):
        count = max(count, min_items)
    if isinstance(max_items, int):
        count = min(count, max_items)
    if depth >= _MAX_DEPTH:
        count = min_items if isinstance(min_items, int) else 0
    result = [
        generate_example(items_schema, root, seed=seed, field=f"{field}[{i}]", _depth=depth + 1)
        for i in range(count)
    ]
    if schema.get("uniqueItems") and len(result) > 1:
        # De-dupe by JSON identity while preserving validity (drop duplicates rather than mutate).
        seen: List[str] = []
        unique: List[Any] = []
        for item in result:
            key = repr(item)
            if key not in seen:
                seen.append(key)
                unique.append(item)
        result = unique
    return result


def validate_value(value: Any, schema: Any, root: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Validate ``value`` against ``schema`` (with ``root`` for ``$ref``).

    Returns ``None`` when valid, or a human-readable error message describing the first failure. The
    schema is wrapped so its ``$ref`` pointers resolve against the full ``root`` document.
    """
    if not isinstance(schema, dict) or not schema:
        return None
    try:
        if root and root is not schema:
            wrapper = dict(schema)
            wrapper.setdefault("$defs", {})
            # Expose the document's components so any "#/components/..." $ref resolves.
            check_schema: Dict[str, Any] = {**root, **wrapper}
        else:
            check_schema = schema
        jsonschema.validate(instance=value, schema=check_schema)
        return None
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        return f"{location}: {exc.message}"
    except jsonschema.SchemaError as exc:  # pragma: no cover - malformed stored spec
        return f"invalid schema: {exc.message}"
