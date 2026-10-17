"""The rules of ``apiome classes create`` (CLI 7.3, #3231).

A class is created in a **draft** version with ``POST /v1/classes/{tenant}`` (``{version_id, name,
description, schema}``), then each property is attached with ``POST /v1/classes/{tenant}/{id}/properties``
(a copy of the library property's ``data`` with ``required`` set, linked by ``property_id``), then
each tag is attached with ``POST /v1/project-tags/{tenant}/classes/{id}`` — creating the project tag
first when it does not exist. The prompts, the flags and ``--from-file`` fill one
:class:`ClassDraft`. These functions hold the decisions, without HTTP.

The ``--from-file`` document (JSON or YAML) is the **class spec**::

    name: Refund
    description: Reversal of a charge.
    tags: [financial]
    properties:
      - amount:required           # "name" or "name:required" …
      - {name: reason, required: false}   # … or an object
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from apiome_cli.property_create import FieldError, PropertyInvalid

#: The longest class name accepted (``classes.name`` is ``VARCHAR(255)``).
NAME_MAX = 255

#: The longest tag name accepted (``tags.name`` is ``VARCHAR(100)``).
TAG_MAX = 100

#: Keys a class spec may hold.
SPEC_KEYS = ("name", "description", "tags", "properties")


class VersionLocked(ValueError):
    """The version is published or frozen, so no class can be added (exit 6)."""


@dataclass(frozen=True)
class PropertyRef:
    """One property to attach: a library property's name, and whether the class requires it."""

    name: str
    required: bool = False


@dataclass(frozen=True)
class ClassDraft:
    """What the user asked for."""

    name: Optional[str]
    description: Optional[str]
    tags: list[str] = field(default_factory=list)
    properties: list[PropertyRef] = field(default_factory=list)


def parse_property(raw: Any, *, where: str) -> PropertyRef:
    """``"amount"``, ``"amount:required"``, ``"amount:optional"`` or ``{name, required}``.

    Raises:
        PropertyInvalid: ``<where>: …`` for anything else.
    """
    if isinstance(raw, Mapping):
        name = str(raw.get("name") or "").strip()
        required = raw.get("required", False)
        if not name or not isinstance(required, bool):
            raise PropertyInvalid([FieldError(where, "an object needs a name and required: true|false")])
        return PropertyRef(name, required)
    text = str(raw or "").strip()
    name, _, flag = text.partition(":")
    flag = flag.strip().lower()
    if not name.strip() or flag not in ("", "required", "optional"):
        raise PropertyInvalid([FieldError(where, f"{text!r}: use name or name:required")])
    return PropertyRef(name.strip(), flag == "required")


def normalize_tags(raw: Any) -> list[str]:
    """Tag names: trimmed, lower-cased, repeats dropped (``"Financial, core"`` → ``["financial", "core"]``)."""
    values = raw if isinstance(raw, list) else str(raw or "").split(",")
    tags: list[str] = []
    for value in values:
        tag = str(value).strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def merge_draft(
    *,
    name: Optional[str],
    description: Optional[str],
    tags: Sequence[str],
    properties: Sequence[str],
    document: Optional[Mapping[str, Any]] = None,
) -> ClassDraft:
    """Combine ``--from-file`` with the flags; a flag (or any ``--tag`` / ``--property``) wins.

    Raises:
        PropertyInvalid: Unknown keys in the file, or a property entry that cannot be read.
    """
    doc = dict(document or {})
    errors = [
        FieldError(key, f"unknown key (use {', '.join(SPEC_KEYS)})") for key in doc if key not in SPEC_KEYS
    ]
    raw_props: Sequence[Any] = properties
    if not properties:
        file_props = doc.get("properties") or []
        raw_props = file_props if isinstance(file_props, list) else [file_props]
    refs: list[PropertyRef] = []
    for index, raw in enumerate(raw_props):
        try:
            refs.append(parse_property(raw, where=f"properties[{index}]" if not properties else "--property"))
        except PropertyInvalid as exc:
            errors += exc.errors
    if errors:
        raise PropertyInvalid(errors)
    return ClassDraft(
        name=_text(name if name is not None else doc.get("name")),
        description=_text(description if description is not None else doc.get("description")),
        tags=normalize_tags(list(tags) if tags else doc.get("tags") or []),
        properties=refs,
    )


def check_version(version: Mapping[str, Any], *, frozen: bool) -> None:
    """Refuse a published or frozen version.

    Raises:
        VersionLocked: Saying which, and that a draft is needed.
    """
    label = version.get("version_id") or version.get("id")
    if version.get("published"):
        raise VersionLocked(f"Version {label} is published; classes can only be added to a draft version.")
    if frozen:
        raise VersionLocked(f"Version {label} is frozen; classes can only be added to a draft version.")


def check_draft(
    draft: ClassDraft, *, existing_classes: Sequence[str], library: Sequence[str], allow_missing: bool = False
) -> list[FieldError]:
    """Field problems: name missing, too long or taken; tags too long; properties repeated or unknown.

    Args:
        draft: The class to create.
        existing_classes: Live class names in the version.
        library: The project's property names.
        allow_missing: Unknown properties are allowed (they will be created with ``--create-missing``).
    """
    errors: list[FieldError] = []
    if not draft.name:
        errors.append(FieldError("name", "required"))
    elif len(draft.name) > NAME_MAX:
        errors.append(FieldError("name", f"at most {NAME_MAX} characters (got {len(draft.name)})"))
    elif draft.name in existing_classes:
        errors.append(FieldError("name", f"the version already has a class '{draft.name}'"))
    errors += [FieldError("tags", f"{t!r} is longer than {TAG_MAX} characters") for t in draft.tags if len(t) > TAG_MAX]
    seen: set[str] = set()
    for ref in draft.properties:
        if ref.name in seen:
            errors.append(FieldError("properties", f"{ref.name!r} is listed twice"))
        seen.add(ref.name)
    if not allow_missing:
        errors += [FieldError("properties", f"no property {name!r} in this project") for name in missing_properties(draft, library)]
    return errors


def missing_properties(draft: ClassDraft, library: Sequence[str]) -> list[str]:
    """The draft's property names the project does not have, in order."""
    known = set(library)
    return [ref.name for ref in draft.properties if ref.name not in known]


def class_body(draft: ClassDraft, version_id: str) -> dict[str, Any]:
    """``POST /v1/classes/{tenant}``."""
    return {"version_id": version_id, "name": draft.name, "description": draft.description, "schema": {}}


def class_property_body(prop: Mapping[str, Any], required: bool) -> dict[str, Any]:
    """``POST …/{class_id}/properties``: the library property's ``data`` with ``required`` set, linked by id."""
    data = dict(prop.get("data") or {}) if isinstance(prop.get("data"), Mapping) else {}
    data["required"] = required
    return {
        "property_id": str(prop.get("id")),
        "name": str(prop.get("name")),
        "description": prop.get("description"),
        "data": data,
    }


def tags_to_create(draft: ClassDraft, project_tags: Sequence[Mapping[str, Any]]) -> list[str]:
    """The draft's tags the project does not have yet (matched by name, any case)."""
    known = {str(t.get("name") or "").lower() for t in project_tags}
    return [t for t in draft.tags if t not in known]


def render_created(name: str, properties: int, created_tags: Sequence[str]) -> str:
    """``✔ Created class 'Refund' with 5 properties.`` (+ the tags created on the way)."""
    noun = "property" if properties == 1 else "properties"
    line = f"✔ Created class '{name}' with {properties} {noun}."
    if created_tags:
        line += f"\n  New project tags: {', '.join(created_tags)}"
    return line
