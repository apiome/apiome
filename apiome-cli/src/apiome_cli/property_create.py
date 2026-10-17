"""The rules of ``apiome properties create`` (CLI 6.3, #3225).

A library property is created with ``POST /v1/properties/{tenant}/{project}`` and a body of
``{name, description, data}``, where ``data`` is the property's JSON Schema. Properties are not
bound to primitives and carry no tags, so the command **copies** the chosen primitive's schema into
``data`` and adds the examples; there is no tags field. The interactive prompts, the flags and
``--from-file`` all fill one :class:`PropertyDraft`, so they send identical bodies. These functions
hold the decisions, without HTTP:

* :func:`merge_draft` — ``--from-file`` (JSON or YAML) under the flags; a flag wins;
* :func:`find_primitive` — name (exact, then any case), UUID or ``$id``; a miss suggests names;
* :func:`check_examples` — each example against the primitive's schema, locally;
* :func:`request_body` — the POST body.

Every content problem is a :class:`FieldError` (``field: message``); the command prints them all
and exits 7.
"""

from __future__ import annotations

import copy
import difflib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import extend

#: The longest name the database accepts (``properties.name`` is ``VARCHAR(255)``).
NAME_MAX = 255

#: Keys a ``--from-file`` document may hold.
FILE_KEYS = ("name", "primitive", "description", "examples")

#: Schema keywords that name the primitive itself and are not copied into the property.
IDENTITY_KEYWORDS = ("$id", "$schema")

#: How many names a primitive miss, or a search while typing, suggests.
SUGGESTIONS = 5


@dataclass(frozen=True)
class FieldError:
    """One problem with one field of the new property."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class PropertyInvalid(ValueError):
    """The new property has field-level problems (exit 7); nothing was created."""

    def __init__(self, errors: Sequence[FieldError]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(str(e) for e in self.errors))


@dataclass(frozen=True)
class PropertyDraft:
    """What the user asked for, before the primitive is looked up."""

    name: Optional[str]
    primitive: Optional[str]
    description: Optional[str]
    examples: list[Any] = field(default_factory=list)


def parse_example(text: str) -> Any:
    """An example as typed: JSON when it parses (``19.99`` → a number, ``true``), else the text."""
    raw = text.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def split_examples(text: str) -> list[Any]:
    """The interactive **Examples** answer: comma-separated, each read by :func:`parse_example`."""
    return [parse_example(part) for part in text.split(",") if part.strip()]


def _text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def merge_draft(
    *,
    name: Optional[str],
    primitive: Optional[str],
    description: Optional[str],
    examples: Sequence[str],
    document: Optional[Mapping[str, Any]] = None,
) -> PropertyDraft:
    """Combine ``--from-file`` with the flags; a flag (or any ``--example``) wins over the file.

    The file holds ``name``, ``primitive``, ``description`` and ``examples`` (a list, or one value);
    its examples keep their JSON/YAML types, while ``--example`` text is read by
    :func:`parse_example`.

    Raises:
        PropertyInvalid: When the file has other keys (``tags`` among them — properties have none).
    """
    doc = dict(document or {})
    errors = [
        FieldError(key, "properties have no tags" if key == "tags" else f"unknown key (use {', '.join(FILE_KEYS)})")
        for key in doc
        if key not in FILE_KEYS
    ]
    if errors:
        raise PropertyInvalid(errors)
    if examples:
        merged_examples = [parse_example(e) for e in examples]
    else:
        file_examples = doc.get("examples", [])
        merged_examples = list(file_examples) if isinstance(file_examples, list) else [file_examples]
    return PropertyDraft(
        name=_text(name if name is not None else doc.get("name")),
        primitive=_text(primitive if primitive is not None else doc.get("primitive")),
        description=_text(description if description is not None else doc.get("description")),
        examples=merged_examples,
    )


def check_name(name: Optional[str], existing: Sequence[str]) -> list[FieldError]:
    """``name`` is given, at most :data:`NAME_MAX` characters, and new in the project."""
    if not name:
        return [FieldError("name", "required")]
    if len(name) > NAME_MAX:
        return [FieldError("name", f"at most {NAME_MAX} characters (got {len(name)})")]
    if name in existing:
        return [FieldError("name", f"the project already has a property '{name}'")]
    return []


def search_primitives(primitives: Sequence[Mapping[str, Any]], text: str, *, limit: int = SUGGESTIONS) -> list[str]:
    """Primitive names containing ``text`` (any case), names starting with it first."""
    needle = text.strip().lower()
    names = sorted({str(p.get("name")) for p in primitives if p.get("name")}, key=str.lower)
    hits = [n for n in names if needle in n.lower()]
    hits.sort(key=lambda n: (not n.lower().startswith(needle), n.lower()))
    return hits[:limit]


def find_primitive(primitives: Sequence[Mapping[str, Any]], ref: Optional[str]) -> Mapping[str, Any]:
    """The primitive ``ref`` names: exact name, name in any case, UUID, or schema ``$id``.

    Raises:
        PropertyInvalid: ``primitive: …`` when ``ref`` is empty, matches nothing (with up to
            :data:`SUGGESTIONS` close names), or matches several names only ignoring case.
    """
    if not ref:
        raise PropertyInvalid([FieldError("primitive", "required")])
    wanted = ref.strip()
    exact = [p for p in primitives if str(p.get("name")) == wanted]
    folded = exact or [p for p in primitives if str(p.get("name") or "").lower() == wanted.lower()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        ids = ", ".join(str(p.get("id")) for p in folded)
        raise PropertyInvalid([FieldError("primitive", f"{ref!r} names more than one primitive; use its id ({ids})")])
    for row in primitives:
        if str(row.get("schema_id") or "") == wanted:
            return row
    try:
        UUID(wanted)
    except ValueError:
        pass
    else:
        for row in primitives:
            if str(row.get("id")).lower() == wanted.lower():
                return row
    names = [str(p.get("name")) for p in primitives if p.get("name")]
    close = difflib.get_close_matches(wanted, names, n=SUGGESTIONS, cutoff=0.6) or search_primitives(primitives, wanted)
    hint = f" Did you mean: {', '.join(close)}?" if close else ""
    raise PropertyInvalid([FieldError("primitive", f"no primitive {ref!r} in this tenant.{hint}")])


def property_schema(primitive: Mapping[str, Any], examples: Sequence[Any]) -> dict[str, Any]:
    """The property's ``data``: a copy of the primitive's schema with ``examples`` set.

    ``$id`` and ``$schema`` are left out (the property is not the primitive); with no examples, the
    primitive's own ``examples`` are kept.
    """
    source = primitive.get("schema") if isinstance(primitive.get("schema"), Mapping) else {}
    data = {k: copy.deepcopy(v) for k, v in source.items() if k not in IDENTITY_KEYWORDS}
    if examples:
        data["examples"] = list(examples)
    return data


def _multiple_of(validator: Any, divisor: Any, instance: Any, schema: Any):
    """``multipleOf`` in decimal, so ``19.99`` is a multiple of ``0.01`` (binary floats say no)."""
    if not validator.is_type(instance, "number"):
        return
    try:
        remainder = Decimal(str(instance)) % Decimal(str(divisor))
    except (InvalidOperation, ArithmeticError):
        return
    if remainder != 0:
        yield ValidationError(f"{instance!r} is not a multiple of {divisor}")


#: Draft 2020-12 with :func:`_multiple_of` in place of the float check.
ExampleValidator = extend(Draft202012Validator, {"multipleOf": _multiple_of})


def check_examples(schema: Mapping[str, Any], examples: Sequence[Any]) -> tuple[list[FieldError], list[str]]:
    """Validate each example against ``schema`` (JSON Schema 2020-12, formats checked).

    Returns:
        ``(errors, warnings)``: one :class:`FieldError` per rejected example (``examples[1]: …``),
        and a warning when the schema cannot be checked here (an invalid schema, or a ``$ref`` to
        another document), in which case the server is left to judge.
    """
    # ``"required": true`` is Apiome's property-level flag, not the JSON Schema keyword (an array).
    body = {k: v for k, v in schema.items() if k != "examples" and not (k == "required" and isinstance(v, bool))}
    try:
        Draft202012Validator.check_schema(body)
    except SchemaError as exc:
        return [], [f"The primitive's schema is not valid JSON Schema ({exc.message}); examples were not checked."]
    validator = ExampleValidator(body, format_checker=FormatChecker())
    errors: list[FieldError] = []
    for index, example in enumerate(examples):
        try:
            problem = next(iter(validator.iter_errors(example)), None)
        except Exception:  # noqa: BLE001 - an unresolvable $ref must not stop the command
            return errors, ["The primitive's schema refers to other documents; examples were not fully checked."]
        if problem is not None:
            errors.append(FieldError(f"examples[{index}]", f"{json.dumps(example)} — {problem.message}"))
    return errors, []


def request_body(draft: PropertyDraft, primitive: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /v1/properties/{tenant}/{project}``: ``{name, description, data}``."""
    return {
        "name": draft.name,
        "description": draft.description,
        "data": property_schema(primitive, draft.examples),
    }
