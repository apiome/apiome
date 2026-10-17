"""The rules of ``apiome properties update`` (CLI 6.4, #3226).

A property is changed with ``PUT /v1/properties/{tenant}/{project}/{id}``, which takes any of
``name``, ``description``, ``data`` and ``enabled``, plus ``expectedUpdatedAt`` (a precondition:
409 ``update_conflict`` when the property changed since it was read) and ``requiredEverywhere``
(set ``required`` on every class attribute using it in an unpublished version). Properties have no
tags and keep a **copy** of their primitive's schema, so:

* ``--primitive`` re-copies the new primitive's schema into ``data``, keeping the property's
  ``examples`` and ``required``; classes keep their own copies, so nothing cascades. It is
  refused (exit 6) while any class uses the property as required, unless ``--allow-breaking``;
* ``--add-example`` / ``--remove-example`` edit ``data.examples``, and the resulting examples are
  checked against the schema locally (exit 7, one line per field);
* ``--from-file`` applies an edited ``properties show --json`` dump (JSON or YAML) whose
  ``updated_at`` is the precondition.

Pure functions — no HTTP, no Typer — so each decision is tested on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from apiome_cli.property_create import (
    FieldError,
    PropertyInvalid,
    check_examples,
    check_name,
    parse_example,
    property_schema,
)

#: The fields an update may change. Everything else in a ``properties show --json`` dump — ids,
#: timestamps, usage — is read-only and ignored by ``--from-file``.
EDITABLE_FIELDS: tuple[str, ...] = ("name", "description", "enabled", "data")

#: Keys of the property's ``data`` that ``--primitive`` keeps when it re-copies the schema.
KEPT_ON_PRIMITIVE_CHANGE: tuple[str, ...] = ("examples", "required")


class PropertyUpdateError(ValueError):
    """A flag or file the command refuses, with a message for stderr (exit 2)."""


class BreakingChange(ValueError):
    """A primitive change while classes use the property as required (exit 6).

    Attributes:
        uses: The ``Class.attribute`` names that require it (empty when the server does not say).
    """

    def __init__(self, message: str, uses: Sequence[str]) -> None:
        super().__init__(message)
        self.uses = list(uses)


@dataclass(frozen=True)
class FieldChange:
    """One changed value, as the diff shows it."""

    #: The field, or ``data.<key>`` for one key of the schema.
    field: str
    #: Its value now (``None`` when absent).
    before: Any
    #: Its value after the update (``None`` when removed).
    after: Any


def _data(prop: Mapping[str, Any]) -> dict[str, Any]:
    data = prop.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _examples(data: Mapping[str, Any]) -> list[Any]:
    examples = data.get("examples")
    return list(examples) if isinstance(examples, list) else []


def data_with_primitive(prop: Mapping[str, Any], primitive: Mapping[str, Any]) -> dict[str, Any]:
    """The property's ``data`` re-copied from ``primitive``, keeping its ``examples`` and ``required``."""
    current = _data(prop)
    data = property_schema(primitive, [])
    data.pop("examples", None)
    for key in KEPT_ON_PRIMITIVE_CHANGE:
        if key in current:
            data[key] = current[key]
    return data


def edit_examples(data: Mapping[str, Any], add: Sequence[str], remove: Sequence[str]) -> dict[str, Any]:
    """``data`` with ``--remove-example`` values taken out, then ``--add-example`` values appended.

    Values are read by :func:`~apiome_cli.property_create.parse_example` (``19.99`` is a number). An
    added value already present is not repeated; with no examples left, ``examples`` is dropped.

    Raises:
        PropertyInvalid: ``examples: …`` for each removed value the property does not have.
    """
    examples = _examples(data)
    errors = []
    for raw in remove:
        value = parse_example(raw)
        if value in examples:
            examples = [e for e in examples if e != value]
        else:
            errors.append(FieldError("examples", f"{json.dumps(value)} is not one of the property's examples"))
    if errors:
        raise PropertyInvalid(errors)
    for raw in add:
        value = parse_example(raw)
        if value not in examples:
            examples.append(value)
    out = dict(data)
    if examples:
        out["examples"] = examples
    else:
        out.pop("examples", None)
    return out


def changes_from_flags(
    prop: Mapping[str, Any],
    *,
    name: Optional[str],
    description: Optional[str],
    primitive: Optional[Mapping[str, Any]],
    add_examples: Sequence[str],
    remove_examples: Sequence[str],
) -> dict[str, Any]:
    """The fields the flags change (unchanged values are dropped).

    Args:
        prop: The property as read (``properties show --json``).
        name: ``--name`` (rename).
        description: ``--description``; an empty string clears it.
        primitive: The resolved ``--primitive`` row, or ``None``.
        add_examples: ``--add-example`` values.
        remove_examples: ``--remove-example`` values.

    Raises:
        PropertyInvalid: When an example to remove is not there.
    """
    wanted: dict[str, Any] = {}
    if name is not None:
        wanted["name"] = name.strip()
    if description is not None:
        wanted["description"] = description.strip() or None
    data = data_with_primitive(prop, primitive) if primitive is not None else _data(prop)
    if add_examples or remove_examples:
        data = edit_examples(data, add_examples, remove_examples)
    if primitive is not None or add_examples or remove_examples:
        wanted["data"] = data
    return {field: value for field, value in wanted.items() if prop.get(field) != value}


def changes_from_file(prop: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    """The editable fields an edited ``properties show --json`` dump changes.

    Only :data:`EDITABLE_FIELDS` are read; a field the file leaves out is left alone. The file
    must describe the same property (its ``id``).

    Raises:
        PropertyUpdateError: When the file is for another property, has ``tags``, or a value is
            the wrong shape.
    """
    if str(document.get("id", "")) != str(prop.get("id")):
        raise PropertyUpdateError(f"The file describes property {document.get('id')!r}, not {prop.get('id')!r}.")
    if "tags" in document:
        raise PropertyUpdateError("The file has tags, but properties have no tags; remove the key.")
    wanted: dict[str, Any] = {}
    for field in EDITABLE_FIELDS:
        if field not in document:
            continue
        value = document[field]
        if field == "name" and (not isinstance(value, str) or not value.strip()):
            raise PropertyUpdateError("The file's name cannot be empty.")
        if field == "name":
            value = value.strip()
        if field == "enabled" and not isinstance(value, bool):
            raise PropertyUpdateError("The file's enabled must be true or false.")
        if field == "data" and not isinstance(value, Mapping):
            raise PropertyUpdateError("The file's data must be an object (the property's JSON Schema).")
        if field == "description" and value is not None:
            value = str(value).strip() or None
        wanted[field] = dict(value) if field == "data" else value
    return {field: value for field, value in wanted.items() if prop.get(field) != value}


def expected_updated_at(document: Mapping[str, Any]) -> str:
    """The ``updated_at`` an edited dump was taken at — the ``--from-file`` precondition.

    Raises:
        PropertyUpdateError: When the file has none (it was not a ``properties show --json`` dump).
    """
    value = document.get("updated_at")
    if not isinstance(value, str) or not value.strip():
        raise PropertyUpdateError(
            "The file has no updated_at; create it with `apiome properties show <project> <property> --json`."
        )
    return value


def check_changes(prop: Mapping[str, Any], changes: Mapping[str, Any], others: Sequence[str]) -> list[FieldError]:
    """Field-level problems with ``changes``: a taken name, examples the schema rejects.

    Args:
        prop: The property as read.
        changes: What the update sets.
        others: The names of the project's other properties.
    """
    errors: list[FieldError] = []
    if "name" in changes:
        errors += check_name(changes["name"], others)
    if "data" in changes:
        data = changes["data"]
        example_errors, _warnings = check_examples(data, _examples(data))
        errors += example_errors
    return errors


def breaking_uses(usage: Optional[Sequence[Mapping[str, Any]]]) -> list[str]:
    """The ``Class.attribute`` names that use the property as required, in usage order.

    Raises:
        BreakingChange: When ``usage`` is ``None`` — the server does not report it, so a primitive
            change cannot be shown to be safe.
    """
    if usage is None:
        raise BreakingChange(
            "This server does not report which classes use the property (apiome-rest 1.354.0 or later "
            "does), so a primitive change cannot be checked.",
            [],
        )
    return [f"{u.get('class_name')}.{u.get('attribute_name')}" for u in usage if u.get("required")]


def check_primitive_change(usage: Optional[Sequence[Mapping[str, Any]]], *, allow_breaking: bool) -> None:
    """Refuse a primitive change while a class requires the property, unless ``allow_breaking``.

    Raises:
        BreakingChange: Listing the class attributes that require it.
    """
    if allow_breaking:
        return
    uses = breaking_uses(usage)
    if uses:
        raise BreakingChange("Changing the primitive could break classes that require this property.", uses)


def field_changes(prop: Mapping[str, Any], changes: Mapping[str, Any]) -> list[FieldChange]:
    """Expand ``changes`` into the diff's rows, in :data:`EDITABLE_FIELDS` order.

    ``data`` is shown key by key (``data.examples``), so a one-key edit is not drawn as the whole
    schema changing.
    """
    rows: list[FieldChange] = []
    for field in EDITABLE_FIELDS:
        if field not in changes:
            continue
        if field == "data":
            before, after = _data(prop), dict(changes["data"])
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    rows.append(FieldChange(f"data.{key}", before.get(key), after.get(key)))
        else:
            rows.append(FieldChange(field, prop.get(field), changes[field]))
    return rows


def _show(value: Any) -> str:
    """A value as the diff prints it: JSON, with an absent value spelled ``(none)``."""
    if value is None:
        return "(none)"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def required_everywhere_line(prop: Mapping[str, Any], required: bool) -> str:
    """The diff line for ``--required-everywhere`` / ``--optional-everywhere``."""
    usage = prop.get("usage")
    word = "required" if required else "optional"
    if usage is None:
        return f"~ every class attribute using it (unpublished versions): {word}"
    targets = [
        f"{u.get('class_name')}.{u.get('attribute_name')}" for u in usage if bool(u.get("required")) != required
    ]
    if not targets:
        return f"~ every class attribute using it is already {word}"
    return f"~ {word} (unpublished versions only): {', '.join(targets)}"


def render_diff(prop: Mapping[str, Any], changes: Mapping[str, Any], required: Optional[bool] = None) -> str:
    """The diff: one ``-``/``+`` pair per changed value, and a ``~`` line for the class attributes.

    Example::

        Property amount (5f0c…)
        - description: "Amount."
        + description: "Monetary amount in the smallest unit."
        - data.examples: [19.99]
        + data.examples: [19.99, 1234.56]

    Returns:
        The diff text, or "No changes." under the header when nothing differs.
    """
    header = f"Property {prop.get('name')} ({prop.get('id')})"
    rows = field_changes(prop, changes)
    if not rows and required is None:
        return f"{header}\nNo changes."
    lines = [header]
    for row in rows:
        lines.append(f"- {row.field}: {_show(row.before)}")
        lines.append(f"+ {row.field}: {_show(row.after)}")
    if required is not None:
        lines.append(required_everywhere_line(prop, required))
    return "\n".join(lines)


def request_body(changes: Mapping[str, Any], updated_at: Optional[str], required: Optional[bool] = None) -> dict[str, Any]:
    """The ``PUT`` body: the changed fields, the precondition, and ``requiredEverywhere`` when set.

    ``description: None`` is sent as ``""`` — the REST API skips a null field but clears the
    description on an empty string.
    """
    body: dict[str, Any] = {}
    for field, value in changes.items():
        body[field] = "" if field == "description" and value is None else value
    if updated_at:
        body["expectedUpdatedAt"] = updated_at
    if required is not None:
        body["requiredEverywhere"] = required
    return body


def summary(prop: Mapping[str, Any], changes: Mapping[str, Any], result: Optional[Mapping[str, Any]]) -> str:
    """The success line(s): which fields changed, and what ``requiredEverywhere`` did."""
    fields = ", ".join(row.field for row in field_changes(prop, changes))
    lines = [f"✔ Updated property '{changes.get('name', prop.get('name'))}'" + (f": {fields}." if fields else ".")]
    if isinstance(result, Mapping):
        lines.append(
            f"  Class attributes: {result.get('changed', 0)} changed, {result.get('unchanged', 0)} already set, "
            f"{result.get('skipped_published', 0)} in published versions left alone."
        )
    return "\n".join(lines)
