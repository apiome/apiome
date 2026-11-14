"""Rules for ``apiome data create`` (CLI 10.3, #3255): the class address, the payload, local validation.

Nothing here talks to the network; :mod:`apiome_cli.commands.data` reads the input, calls
``GET /v1/data/{tenant}/classes`` and ``POST /v1/data/{tenant}/records``, and maps the outcome to
an exit code.

* :func:`parse_class_address` — ``--class <project>/<version>/<Class>``;
* :func:`is_class_schema_id` — ``--class`` given as a class schema id (``data list``);
* :func:`check_filter` — ``data list --filter key=value``;
* :func:`parse_field` / :func:`build_payload` — ``--field key=value`` (``key=:<json>``) on top of
  the ``--from-file`` / ``--stdin`` object, so every input mode reaches the same POST body;
* :func:`find_class` — the class in the version's frozen class schemas (exact name, then a
  unique case-insensitive match);
* :func:`validate_record` — the payload against the class's JSON Schema 2020-12, as
  ``field: message`` problems.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing.exceptions import Unresolvable

from apiome_cli.property_create import FieldError

#: The field name a problem with the whole record (not one of its fields) is reported under.
RECORD_FIELD = "(record)"

#: Prefix on a ``--field`` value that makes it parsed as JSON (``count=:3``, ``tags=:["a"]``).
JSON_VALUE_PREFIX = ":"


class DataInputError(ValueError):
    """The command line or input cannot be used (exit 2); the message says why."""


class SchemaUnusable(ValueError):
    """The class schema cannot be checked locally (an unresolvable ``$ref`` or an invalid schema)."""


@dataclass(frozen=True)
class ClassAddress:
    """Where a record goes: a class in a published version of a project."""

    project: str
    version: str
    class_name: str

    def __str__(self) -> str:
        return f"{self.project}/{self.version}/{self.class_name}"


def parse_class_address(text: str) -> ClassAddress:
    """Parse ``--class <project>/<version>/<Class>``.

    Args:
        text: The option value, e.g. ``billing/1.0.0/Charge`` (a ``v`` before the version is fine).

    Returns:
        The address.

    Raises:
        DataInputError: When it does not have exactly three non-empty segments.
    """
    parts = [part.strip() for part in text.strip().split("/")]
    if len(parts) != 3 or not all(parts):
        raise DataInputError(
            f"--class {text!r} must be <project>/<version>/<Class>, e.g. billing/1.0.0/Charge."
        )
    return ClassAddress(*parts)


def is_class_schema_id(text: str) -> bool:
    """Whether ``--class`` is a class schema id (a UUID) rather than ``<project>/<version>/<Class>``."""
    try:
        uuid.UUID(text.strip())
    except ValueError:
        return False
    return True


def check_filter(text: str) -> str:
    """Check one ``--filter key=value`` and return it as given (the server compares the value as text).

    Raises:
        DataInputError: No ``=``, or an empty key.
    """
    key, sep, _value = text.partition("=")
    if not sep or not key.strip():
        raise DataInputError(f"--filter {text!r} must be key=value, e.g. status=succeeded.")
    return text


def parse_field(text: str) -> tuple[str, Any]:
    """Parse one ``--field key=value``.

    The value is a string, unless it starts with ``:`` — then the rest is parsed as JSON
    (``amount=:19.99``, ``active=:true``, ``tags=:["a","b"]``, ``note=:null``).

    Args:
        text: The option value.

    Returns:
        ``(key, value)``.

    Raises:
        DataInputError: No ``=``, an empty key, or a ``:`` value that is not valid JSON.
    """
    key, sep, raw = text.partition("=")
    key = key.strip()
    if not sep or not key:
        raise DataInputError(f"--field {text!r} must be key=value (or key=:<json>).")
    if not raw.startswith(JSON_VALUE_PREFIX):
        return key, raw
    try:
        return key, json.loads(raw[len(JSON_VALUE_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise DataInputError(f"--field {key}: the value after ':' is not valid JSON ({exc.msg}).") from exc


def build_payload(document: Optional[Mapping[str, Any]], fields: Sequence[str]) -> dict[str, Any]:
    """The record payload: the ``--from-file`` / ``--stdin`` object, then each ``--field`` on top.

    A ``--field`` replaces the same top-level key from the document; a key given twice keeps
    the last value.

    Args:
        document: The parsed input object, or ``None`` when only ``--field`` was given.
        fields: The raw ``--field`` values, in command-line order.

    Returns:
        A new dict (the document is not modified).

    Raises:
        DataInputError: A malformed ``--field``.
    """
    payload = dict(document or {})
    for text in fields:
        key, value = parse_field(text)
        payload[key] = value
    return payload


def find_class(classes: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    """The class schema row named ``name``: an exact match, else the one case-insensitive match.

    Args:
        classes: The ``classes`` rows from ``GET /v1/data/{tenant}/classes``.
        name: The class segment of ``--class``.

    Returns:
        The matching row (``class_schema_id``, ``class_name``, ``schema``).

    Raises:
        DataInputError: No class matches (or several only differ by case); the message lists
            the version's classes.
    """
    for row in classes:
        if row.get("class_name") == name:
            return row
    folded = [row for row in classes if str(row.get("class_name") or "").lower() == name.lower()]
    if len(folded) == 1:
        return folded[0]
    names = sorted(str(row.get("class_name")) for row in classes)
    known = f" Classes: {', '.join(names)}." if names else ""
    raise DataInputError(f"No class {name!r} in this version.{known}")


def _field_name(path: Iterable[Any]) -> str:
    """``address/city`` for a JSON path; :data:`RECORD_FIELD` for the record itself."""
    parts = [str(part) for part in path]
    return "/".join(parts) if parts else RECORD_FIELD


def _problems(error: ValidationError) -> list[FieldError]:
    """One :class:`FieldError` per field a validation error is about.

    A ``required`` error sits on the parent object; it is reported on the missing field itself
    (``customer_id: is required``) so each line names the field to fix.
    """
    if error.validator == "required" and isinstance(error.instance, Mapping):
        missing = [name for name in error.validator_value or [] if name not in error.instance]
        if missing:
            return [FieldError(_field_name([*error.absolute_path, name]), "is required") for name in missing]
    return [FieldError(_field_name(error.absolute_path), error.message)]


def validate_record(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> list[FieldError]:
    """Check ``payload`` against the class's JSON Schema 2020-12 (with ``format`` assertions).

    Args:
        schema: The frozen class schema (``classes[].schema``).
        payload: The record.

    Returns:
        The field-level problems, sorted by field then message and without duplicates; empty
        when the record is valid.

    Raises:
        SchemaUnusable: The schema is not a valid JSON Schema, or it has a ``$ref`` that cannot be
            resolved offline — the record cannot be checked locally.
    """
    try:
        Draft202012Validator.check_schema(dict(schema))
        validator = Draft202012Validator(dict(schema), format_checker=FormatChecker())
        found = [problem for error in validator.iter_errors(dict(payload)) for problem in _problems(error)]
    except SchemaError as exc:
        raise SchemaUnusable(f"the class schema is not valid JSON Schema ({exc.message})") from exc
    except Unresolvable as exc:
        raise SchemaUnusable(f"the class schema has a $ref that cannot be resolved locally ({exc})") from exc
    unique = {(problem.field, problem.message): problem for problem in found}
    return [unique[key] for key in sorted(unique)]


def render_created(record_id: str, address: ClassAddress) -> str:
    """``✔ Created rc_9b3e… in billing/1.0.0/Charge.``"""
    return f"✔ Created {record_id} in {address}."


def render_valid(address: ClassAddress) -> str:
    """The ``--dry-run`` success line: nothing was sent."""
    return f"✔ Valid {address} record. Nothing was created (--dry-run)."
