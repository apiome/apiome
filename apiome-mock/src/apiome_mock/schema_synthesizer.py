"""Schema-driven mock data synthesis for the mock data plane (SIM-1.3).

Given a JSON Schema fragment from a frozen OpenAPI document, produce an example value that
validates against the schema. Explicit author intent (``example``, ``default``, ``const``,
``enum``) wins; otherwise values are synthesised from ``type``, ``format``, ``pattern``,
bounds, and property-name heuristics. Generation is deterministic for a given
``(schema, seed, field)`` tuple.
"""

from __future__ import annotations

import hashlib
import random
import re
import sre_parse
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

import jsonschema

_MAX_DEPTH = 6
_MAX_ARRAY_ITEMS = 5
_MAX_FIXUP_ROUNDS = 24

_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("created_at", "timestamp"),
    ("updated_at", "timestamp"),
    ("createdat", "timestamp"),
    ("updatedat", "timestamp"),
    ("email", "email"),
    ("first_name", "first_name"),
    ("firstname", "first_name"),
    ("last_name", "last_name"),
    ("lastname", "last_name"),
    ("full_name", "full_name"),
    ("username", "username"),
    ("user_name", "username"),
    ("phone", "phone_e164"),
    ("phonenumber", "phone_e164"),
    ("country", "country_code"),
    ("currency", "currency_code"),
    ("cvv", "cvv"),
    ("swift", "swift"),
    ("swiftcode", "swift"),
    ("zipcode", "zip_us"),
    ("postal", "zip_us"),
    ("tracking", "tracking"),
    ("microchip", "digits_15"),
    ("cardlast4", "digits_4"),
    ("name", "full_name"),
    ("city", "city"),
    ("street", "street"),
    ("address", "street"),
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
    ("state", "state_code"),
    ("color", "color"),
    ("colour", "color"),
    ("uuid", "uuid"),
    ("guid", "uuid"),
    ("twitter", "twitter"),
    ("id", "id"),
)

_FIRST_NAMES = ("Ada", "Bjarne", "Grace", "Linus", "Margaret", "Dennis", "Barbara", "Ken")
_LAST_NAMES = ("Lovelace", "Stroustrup", "Hopper", "Torvalds", "Hamilton", "Ritchie", "Liskov")
_CITIES = ("Springfield", "Riverton", "Fairview", "Greenville", "Madison", "Georgetown")
_COUNTRY_CODES = ("US", "CA", "GB", "DE", "JP", "AU", "FR", "IT", "ES", "NL")
_CURRENCY_CODES = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SEK")
_STATE_CODES = ("CA", "NY", "TX", "FL", "WA", "IL", "CO", "MA")
_COMPANIES = ("Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries")
_STATUSES = ("active", "pending", "inactive", "archived")
_COLORS = ("red", "green", "blue", "amber", "violet", "teal")
_WORDS = ("lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit")


def parse_mock_seed(raw: str | None) -> int:
    """Parse ``__seed`` query values into a stable integer seed."""
    if raw is None or not str(raw).strip():
        return 0
    text = str(raw).strip()
    try:
        return int(text)
    except ValueError:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)


def _seeded_rng(seed: int, *parts: str) -> random.Random:
    digest = hashlib.sha256(("\x00".join(parts)).encode("utf-8")).hexdigest()
    return random.Random(seed ^ int(digest[:16], 16))


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
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


def _deref(schema: Any, root: dict[str, Any]) -> dict[str, Any]:
    if isinstance(schema, dict) and "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], root)
        if resolved:
            return resolved
    return schema if isinstance(schema, dict) else {}


def _merge_all_of(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
    props: dict[str, Any] = dict(merged.get("properties", {}))
    required: list[str] = list(merged.get("required", []))
    for sub in schema.get("allOf", []):
        sub = _deref(sub, root)
        if "allOf" in sub:
            sub = _merge_all_of(sub, root)
        if sub.get("type") and "type" not in merged:
            merged["type"] = sub["type"]
        props.update(sub.get("properties", {}))
        required.extend(sub.get("required", []))
        for key in ("if", "then", "else", "dependentSchemas", "patternProperties"):
            if key in sub and key not in merged:
                merged[key] = sub[key]
    if props:
        merged["properties"] = props
        merged.setdefault("type", "object")
    if required:
        merged["required"] = sorted(set(required))
    return merged


def _schema_type(schema: dict[str, Any]) -> str | None:
    t = schema.get("type")
    if isinstance(t, list):
        for candidate in t:
            if candidate != "null":
                return str(candidate)
        return str(t[0]) if t else None
    if t:
        return str(t)
    if "properties" in schema:
        return "object"
    if "items" in schema or "prefixItems" in schema:
        return "array"
    return None


def _uuid_like(rng: random.Random) -> str:
    hexd = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    return f"{hexd[:8]}-{hexd[8:12]}-4{hexd[13:16]}-8{hexd[17:20]}-{hexd[20:32]}"


def _iso_timestamp(rng: random.Random) -> str:
    return (
        f"20{rng.randint(20, 29)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
    )


def _digits(rng: random.Random, count: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(count))


def _phone_e164(rng: random.Random) -> str:
    return f"+1{rng.randint(2, 9)}{rng.randint(100000000, 999999999)}"


def _string_for_hint(key: str, rng: random.Random) -> str:
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
    if key == "phone_e164":
        return _phone_e164(rng)
    if key == "country_code":
        return rng.choice(_COUNTRY_CODES)
    if key == "currency_code":
        return rng.choice(_CURRENCY_CODES)
    if key == "state_code":
        return rng.choice(_STATE_CODES)
    if key == "cvv":
        return _digits(rng, rng.choice((3, 4)))
    if key == "swift":
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        alnum = letters + "0123456789"
        return "".join(rng.choice(letters) for _ in range(6)) + "".join(rng.choice(alnum) for _ in range(2)) + "XXX"
    if key == "zip_us":
        return f"{rng.randint(10000, 99999)}"
    if key == "tracking":
        return "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(12))
    if key == "digits_15":
        return _digits(rng, 15)
    if key == "digits_4":
        return _digits(rng, 4)
    if key == "timestamp":
        return _iso_timestamp(rng)
    if key == "city":
        return rng.choice(_CITIES)
    if key == "street":
        return f"{rng.randint(1, 9999)} {rng.choice(_LAST_NAMES)} St"
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
    if key == "twitter":
        handle = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789_") for _ in range(8))
        return f"@{handle}"
    if key == "id":
        return f"{rng.choice(_WORDS)}-{rng.randint(1000, 9999)}"
    if key == "price":
        return str(round(rng.uniform(1, 999), 2))
    if key == "small_int":
        return str(rng.randint(1, 20))
    return rng.choice(_WORDS)


def _hint_key(field: str) -> str:
    lowered = field.lower().replace("-", "").replace("_", "")
    for needle, hint in _NAME_HINTS:
        if needle.replace("_", "") in lowered:
            return hint
    return "word"


def _string_for_name(field: str, rng: random.Random) -> str:
    return _string_for_hint(_hint_key(field), rng)


def _string_for_format(fmt: str, field: str, rng: random.Random) -> str | None:
    if fmt == "email":
        return _string_for_hint("email", rng)
    if fmt in ("uri", "url", "uri-reference"):
        return _string_for_hint("url", rng)
    if fmt == "uuid":
        return _uuid_like(rng)
    if fmt == "date":
        return f"20{rng.randint(20, 29)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if fmt in ("date-time", "datetime"):
        return _iso_timestamp(rng)
    if fmt == "time":
        return f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
    if fmt in ("ipv4", "ip"):
        return ".".join(str(rng.randint(1, 254)) for _ in range(4))
    if fmt == "ipv6":
        return ":".join("".join(rng.choice("0123456789abcdef") for _ in range(4)) for _ in range(8))
    if fmt == "hostname":
        return f"{rng.choice(_WORDS)}.example.com"
    return None


def _char_from_in_category(category: list[tuple[Any, ...]], rng: random.Random) -> str:
    if not category:
        return "x"
    start = 0
    if category[0][0] == sre_parse.NEGATE:
        start = 1
    chars: list[str] = []
    for op, arg in category[start:]:
        if op == sre_parse.LITERAL:
            chars.append(chr(arg))
        elif op == sre_parse.RANGE:
            lo, hi = arg
            chars.extend(chr(codepoint) for codepoint in range(lo, hi + 1))
    if start == 1:
        pool = [c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if c not in chars]
        return rng.choice(pool) if pool else "x"
    return rng.choice(chars) if chars else "x"


def _build_from_regex_tokens(tokens: Any, rng: random.Random) -> str:
    parts: list[str] = []
    for op, arg in tokens:
        if op == sre_parse.LITERAL:
            parts.append(chr(arg))
        elif op == sre_parse.IN:
            parts.append(_char_from_in_category(arg, rng))
        elif op in (sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT):
            if len(arg) == 4:
                _, min_count, max_count, sub = arg
            else:
                min_count, max_count, sub = arg
            repeat = min_count if min_count == max_count else rng.randint(min_count, min(max_count, min_count + 4))
            parts.append(_build_from_regex_tokens(sub, rng) * repeat)
        elif op == sre_parse.SUBPATTERN:
            _, _, _, sub = arg
            parts.append(_build_from_regex_tokens(sub, rng))
        elif op == sre_parse.BRANCH:
            _, branches = arg
            if branches:
                parts.append(_build_from_regex_tokens(branches[0][1], rng))
    return "".join(parts)


def _string_for_pattern(pattern: str, field: str, rng: random.Random) -> str:
    try:
        tokens = sre_parse.parse(pattern)
        candidate = _build_from_regex_tokens(tokens, rng)
        if re.fullmatch(pattern, candidate):
            return candidate
    except re.error:
        pass
    for _ in range(32):
        candidate = _string_for_name(field, rng)
        if re.fullmatch(pattern, candidate):
            return candidate
    return _string_for_name(field, rng)


def _clamp_string(value: str, schema: dict[str, Any]) -> str:
    min_len = schema.get("minLength")
    max_len = schema.get("maxLength")
    if isinstance(min_len, int) and len(value) < min_len:
        value = (value + ("x" * min_len))[:min_len] if value else "x" * min_len
    if isinstance(max_len, int) and len(value) > max_len:
        value = value[:max_len]
    return value


def _jsonschema_number(value: Decimal) -> int | float:
    """Convert a ``Decimal`` to a float/jsonschema-safe number."""
    if value == value.to_integral_value():
        return int(value)
    return float(format(value, "f"))


def _snap_number(value: Any, schema: dict[str, Any]) -> Any:
    multiple_of = schema.get("multipleOf")
    if not isinstance(multiple_of, (int, float)) or multiple_of <= 0:
        return value
    step = Decimal(str(multiple_of))
    snapped = (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_HALF_UP) * step
    if schema.get("type") == "integer" or isinstance(value, int):
        return int(snapped)
    return _jsonschema_number(snapped)


def _gen_number(schema: dict[str, Any], rng: random.Random, *, integer: bool) -> Any:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    exclusive_minimum = schema.get("exclusiveMinimum")
    exclusive_maximum = schema.get("exclusiveMaximum")
    lo: Decimal | None = Decimal(str(minimum)) if isinstance(minimum, (int, float)) else None
    hi: Decimal | None = Decimal(str(maximum)) if isinstance(maximum, (int, float)) else None
    if exclusive_minimum is True and lo is not None:
        lo += Decimal(1) if integer else Decimal("0.01")
    elif isinstance(exclusive_minimum, (int, float)):
        lo = Decimal(str(exclusive_minimum)) + (Decimal(1) if integer else Decimal("0.01"))
    if exclusive_maximum is True and hi is not None:
        hi -= Decimal(1) if integer else Decimal("0.01")
    elif isinstance(exclusive_maximum, (int, float)):
        hi = Decimal(str(exclusive_maximum)) - (Decimal(1) if integer else Decimal("0.01"))
    if lo is None:
        lo = Decimal(0)
    if hi is None:
        hi = lo + Decimal(1000)
    if hi < lo:
        hi = lo
    multiple_of = schema.get("multipleOf")
    step = Decimal(str(multiple_of)) if isinstance(multiple_of, (int, float)) and multiple_of > 0 else None
    if step is not None:
        start = lo if lo % step == 0 else lo + (step - (lo % step))
        if start > hi:
            start = lo
        span = int(((hi - start) / step).to_integral_value(rounding=ROUND_HALF_UP))
        offset = rng.randint(0, max(span, 0))
        value = start + step * offset
    elif integer:
        value = Decimal(rng.randint(int(lo), int(hi)))
    else:
        value = lo + (hi - lo) * Decimal(rng.random())
        value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if integer:
        return int(value)
    return _jsonschema_number(value)


def _normalize_openapi_schema(schema: Any) -> Any:
    """Normalize OpenAPI 3.0 boolean exclusive bounds for ``jsonschema`` validation."""
    if isinstance(schema, list):
        return [_normalize_openapi_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "exclusiveMinimum" and value is True:
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)):
                normalized["exclusiveMinimum"] = minimum
            continue
        if key == "exclusiveMaximum" and value is True:
            maximum = schema.get("maximum")
            if isinstance(maximum, (int, float)):
                normalized["exclusiveMaximum"] = maximum
            continue
        if key == "minimum" and schema.get("exclusiveMinimum") is True:
            continue
        if key == "maximum" and schema.get("exclusiveMaximum") is True:
            continue
        normalized[key] = _normalize_openapi_schema(value)
    return normalized


def _validation_schema(schema: dict[str, Any], root: dict[str, Any] | None) -> dict[str, Any]:
    base: dict[str, Any] = {**root, **schema} if root and root is not schema else schema
    return cast(dict[str, Any], _normalize_openapi_schema(base))


def _instance_satisfies(instance: Any, subschema: dict[str, Any], root: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(instance=instance, schema=_validation_schema(subschema, root))
        return True
    except jsonschema.ValidationError:
        return False


def _pick_combinator_branch(schema: dict[str, Any], root: dict[str, Any], combinator: str) -> dict[str, Any] | None:
    options = schema.get(combinator)
    if not isinstance(options, list) or not options:
        return None
    discriminator = schema.get("discriminator")
    if isinstance(discriminator, dict):
        prop = discriminator.get("propertyName")
        mapping = discriminator.get("mapping", {})
        if isinstance(prop, str) and isinstance(mapping, dict) and mapping:
            for ref in mapping.values():
                branch = _deref({"$ref": ref}, root) if isinstance(ref, str) else {}
                if branch:
                    return branch
    merged = _merge_all_of(schema, root) if combinator == "allOf" else schema
    if combinator == "allOf":
        return merged
    for option in options:
        branch = _deref(option, root)
        if branch.get("required") and "properties" in schema:
            probe: dict[str, Any] = {}
            for req in branch["required"]:
                if req in schema["properties"]:
                    probe[req] = generate_example(schema["properties"][req], root, seed=0, field=req, _depth=0)
            if _instance_satisfies(probe, {"allOf": [schema, branch]}, root):
                return branch
        if not branch.get("required"):
            return branch
    return _deref(options[0], root)


def generate_example(
    schema: Any,
    root: dict[str, Any] | None = None,
    *,
    seed: int = 0,
    field: str = "root",
    _depth: int = 0,
) -> Any:
    """Generate a schema-valid example value."""
    if root is None:
        root = schema if isinstance(schema, dict) else {}
    schema = _deref(schema, root)
    if not isinstance(schema, dict) or not schema:
        return None

    rng = _seeded_rng(seed, field, str(_depth))

    if "const" in schema:
        return schema["const"]
    if "example" in schema:
        value = schema["example"]
        if _schema_type(schema) in ("number", "integer"):
            value = _snap_number(value, schema)
            if validate_value(value, schema, root) is None:
                return value
        else:
            return value
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        value = examples[0]
        if _schema_type(schema) in ("number", "integer"):
            value = _snap_number(value, schema)
            if validate_value(value, schema, root) is None:
                return value
        else:
            return value
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

    if "oneOf" in schema and isinstance(schema.get("discriminator"), dict):
        mapping = schema["discriminator"].get("mapping")
        if isinstance(mapping, dict) and mapping:
            first_ref = next(iter(mapping.values()))
            if isinstance(first_ref, str):
                branch = _deref({"$ref": first_ref}, root)
                if branch:
                    return generate_example(branch, root, seed=seed, field=field, _depth=_depth + 1)

    for combinator in ("oneOf", "anyOf"):
        picked = _pick_combinator_branch(schema, root, combinator)
        if picked is not None:
            merged = dict(schema)
            merged.pop(combinator, None)
            merged.setdefault("properties", {})
            merged["properties"] = {**merged.get("properties", {}), **picked.get("properties", {})}
            merged["required"] = sorted(set(merged.get("required", [])) | set(picked.get("required", [])))
            schema = merged

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
        return _gen_string(schema, field, rng)

    return _clamp_string(_string_for_name(field, rng), schema)


def _gen_string(schema: dict[str, Any], field: str, rng: random.Random) -> str:
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        value = _string_for_pattern(pattern, field, rng)
        return _clamp_string(value, schema)
    fmt = schema.get("format")
    if isinstance(fmt, str):
        by_format = _string_for_format(fmt, field, rng)
        if by_format is not None:
            return _clamp_string(by_format, schema)
    return _clamp_string(_string_for_name(field, rng), schema)


def _property_names_key(schema: dict[str, Any], rng: random.Random, index: int) -> str:
    names_schema = schema.get("propertyNames")
    if isinstance(names_schema, dict):
        if names_schema.get("format") == "email":
            return f"user{index}@example.com"
        if names_schema.get("format") == "uuid":
            return _uuid_like(rng)
        pattern = names_schema.get("pattern")
        if isinstance(pattern, str):
            return _string_for_pattern(pattern, f"key{index}", rng)
    return f"prop_{index}"


def _gen_object(
    schema: dict[str, Any],
    root: dict[str, Any],
    seed: int,
    field: str,
    depth: int,
    rng: random.Random,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    properties = dict(schema.get("properties", {}))
    required = set(schema.get("required", []))
    if depth >= _MAX_DEPTH:
        properties = {k: v for k, v in properties.items() if k in required}

    for prop_name, prop_schema in properties.items():
        if prop_name not in required and depth >= _MAX_DEPTH:
            continue
        result[prop_name] = generate_example(prop_schema, root, seed=seed, field=prop_name, _depth=depth + 1)

    pattern_props = schema.get("patternProperties")
    if isinstance(pattern_props, dict):
        min_props = schema.get("minProperties", 0)
        needed = max(0, int(min_props) - len(result)) if isinstance(min_props, int) else 0
        needed = min(needed, 3)
        for index in range(needed):
            key = _property_names_key(schema, rng, index)
            for pattern, subschema in pattern_props.items():
                if re.fullmatch(pattern, key):
                    result[key] = generate_example(subschema, root, seed=seed, field=key, _depth=depth + 1)
                    break
            else:
                first_pattern, first_schema = next(iter(pattern_props.items()))
                key = _string_for_pattern(first_pattern, f"key{index}", rng)
                names_schema = schema.get("propertyNames")
                if isinstance(names_schema, dict) and not _instance_satisfies(key, names_schema, root):
                    key = _property_names_key(schema, rng, index)
                result[key] = generate_example(first_schema, root, seed=seed, field=key, _depth=depth + 1)

    if not properties and isinstance(schema.get("additionalProperties"), dict):
        result["key"] = generate_example(
            schema["additionalProperties"], root, seed=seed, field="value", _depth=depth + 1
        )

    _apply_applicators(result, schema, root, seed, depth)
    return _fixup_object(result, schema, root, seed, field, depth)


def _apply_applicators(
    result: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    seed: int,
    depth: int,
) -> None:
    if_block = schema.get("if")
    if isinstance(if_block, dict):
        if _instance_satisfies(result, if_block, root):
            then = schema.get("then")
            if isinstance(then, dict):
                _merge_generated_properties(result, then, root, seed, depth)
        else:
            otherwise = schema.get("else")
            if isinstance(otherwise, dict):
                _merge_generated_properties(result, otherwise, root, seed, depth)

    dependent = schema.get("dependentSchemas")
    if isinstance(dependent, dict):
        for trigger, dep_schema in dependent.items():
            if trigger not in result:
                continue
            if isinstance(dep_schema, dict):
                if_part = dep_schema.get("if")
                if if_part is None or _instance_satisfies(result, if_part, root):
                    then = dep_schema.get("then", dep_schema)
                    if isinstance(then, dict):
                        _merge_generated_properties(result, then, root, seed, depth)


def _merge_generated_properties(
    result: dict[str, Any],
    fragment: dict[str, Any],
    root: dict[str, Any],
    seed: int,
    depth: int,
) -> None:
    props = fragment.get("properties", {})
    if isinstance(props, dict):
        for name, subschema in props.items():
            if name not in result:
                result[name] = generate_example(subschema, root, seed=seed, field=name, _depth=depth + 1)
    for req in fragment.get("required", []):
        if req not in result and req in props:
            result[req] = generate_example(props[req], root, seed=seed, field=req, _depth=depth + 1)


def _fixup_object(
    result: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    seed: int,
    field: str,
    depth: int,
) -> dict[str, Any]:
    for _ in range(_MAX_FIXUP_ROUNDS):
        error = validate_value(result, schema, root)
        if error is None:
            return result
        missing = re.search(r"'([^']+)' is a required property", error)
        if missing:
            prop = missing.group(1)
            props = schema.get("properties", {})
            if isinstance(props, dict) and prop in props:
                result[prop] = generate_example(props[prop], root, seed=seed, field=prop, _depth=depth + 1)
                continue
        any_of = schema.get("anyOf")
        if isinstance(any_of, list):
            for branch in any_of:
                branch = _deref(branch, root)
                for req in branch.get("required", []):
                    if req not in result and req in schema.get("properties", {}):
                        result[req] = generate_example(
                            schema["properties"][req], root, seed=seed, field=req, _depth=depth + 1
                        )
                        break
                else:
                    continue
                break
        break
    return result


def _gen_array(
    schema: dict[str, Any],
    root: dict[str, Any],
    seed: int,
    field: str,
    depth: int,
    rng: random.Random,
) -> list[Any]:
    prefix = schema.get("prefixItems")
    if isinstance(prefix, list):
        result = [
            generate_example(item_schema, root, seed=seed, field=f"{field}[{i}]", _depth=depth + 1)
            for i, item_schema in enumerate(prefix)
        ]
        min_items = schema.get("minItems", len(result))
        if isinstance(min_items, int) and len(result) < min_items:
            item_schema = schema.get("items", schema.get("unevaluatedItems", {}))
            while len(result) < min_items:
                result.append(
                    generate_example(item_schema, root, seed=seed, field=f"{field}[{len(result)}]", _depth=depth + 1)
                )
        return result

    items_schema = schema.get("items", {})
    min_items = schema.get("minItems", 0)
    max_items = schema.get("maxItems")
    count = min(2, _MAX_ARRAY_ITEMS)
    if isinstance(min_items, int):
        count = max(count, min_items)
    if isinstance(max_items, int):
        count = min(count, max_items)
    if depth >= _MAX_DEPTH:
        count = min_items if isinstance(min_items, int) else 0
    result = [
        generate_example(items_schema, root, seed=seed, field=f"{field}[{i}]", _depth=depth + 1) for i in range(count)
    ]
    if schema.get("uniqueItems") and len(result) > 1:
        seen: list[str] = []
        unique: list[Any] = []
        for item in result:
            key = repr(item)
            if key not in seen:
                seen.append(key)
                unique.append(item)
        result = unique
    return result


def validate_value(value: Any, schema: Any, root: dict[str, Any] | None = None) -> str | None:
    """Validate ``value`` against ``schema``; return an error message or ``None``."""
    if not isinstance(schema, dict) or not schema:
        return None
    try:
        jsonschema.validate(instance=value, schema=_validation_schema(schema, root))
        return None
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        return f"{location}: {exc.message}"
    except jsonschema.SchemaError as exc:  # pragma: no cover
        return f"invalid schema: {exc.message}"
