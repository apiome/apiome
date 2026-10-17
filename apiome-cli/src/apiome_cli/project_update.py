"""The rules of ``apiome projects update`` (CLI 3.4, #3205).

Pure functions — no HTTP, no Typer — so every decision the command makes can be tested on its
own:

* which fields a set of flags (``--name``, ``--rename``, ``--description``, ``--domain``) or an
  edited ``projects get --json`` dump (``--from-file``) actually **changes** — only those are
  sent, so an update never rewrites a field it did not mean to;
* how ``--domain`` edits ``metadata`` — REST replaces ``metadata`` wholesale, so the change is
  made on the project's current metadata, keeping every other key;
* what a new slug may look like (the database's own constraint, checked before a request);
* how the ``--dry-run`` diff reads (:func:`render_diff`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

#: The domain ids ``--domain`` accepts — the REST allow-list
#: (``apiome-rest/src/app/projects_routes.py`` ``PROJECT_DOMAIN_CATEGORY_IDS``) plus ``none``.
PROJECT_DOMAIN_CHOICES: tuple[str, ...] = (
    "iot",
    "social",
    "gaming",
    "travel",
    "media",
    "ecommerce",
    "healthcare",
    "finance",
    "saas",
    "education",
    "realestate",
    "logistics",
)

#: The ``--domain`` value that clears the domain (the Projects pickers' spelling).
PROJECT_DOMAIN_NONE = "none"

#: The fields an update may change. Everything else in a ``projects get --json`` dump —
#: ids, timestamps, counts, the creator — is read-only and ignored by ``--from-file``.
EDITABLE_FIELDS: tuple[str, ...] = ("name", "slug", "description", "enabled", "metadata")

#: The database's slug constraint (``projects_slug_check``): lower-case letters, digits and
#: inner hyphens, 2–50 characters.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_SLUG_MIN, _SLUG_MAX = 2, 50


class ProjectUpdateError(ValueError):
    """A flag or file the command refuses, with a message for stderr (exit 2)."""


@dataclass(frozen=True)
class FieldChange:
    """One changed value, as the diff shows it."""

    #: The field, or ``metadata.<key>`` for one metadata key.
    field: str
    #: Its value now (``None`` when absent).
    before: Any
    #: Its value after the update (``None`` when removed).
    after: Any


def validate_slug(slug: str) -> str:
    """Return ``slug`` lower-cased and trimmed, or refuse it.

    Raises:
        ProjectUpdateError: When it does not match the database's slug constraint.
    """
    value = slug.strip().lower()
    if not (_SLUG_MIN <= len(value) <= _SLUG_MAX) or not _SLUG_RE.match(value):
        raise ProjectUpdateError(
            f"Invalid slug {slug!r}: use {_SLUG_MIN}-{_SLUG_MAX} lower-case letters, digits "
            "and hyphens, starting and ending with a letter or digit."
        )
    return value


def validate_domain(domain: str) -> str:
    """Return the domain id (``none`` included), or refuse it.

    Raises:
        ProjectUpdateError: When it is not one of :data:`PROJECT_DOMAIN_CHOICES` or ``none``.
    """
    value = domain.strip().lower()
    if value != PROJECT_DOMAIN_NONE and value not in PROJECT_DOMAIN_CHOICES:
        choices = ", ".join((*PROJECT_DOMAIN_CHOICES, PROJECT_DOMAIN_NONE))
        raise ProjectUpdateError(f"Unknown domain {domain!r}; choose one of: {choices}.")
    return value


def _metadata(project: Mapping[str, Any]) -> dict[str, Any]:
    value = project.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def metadata_with_domain(project: Mapping[str, Any], domain: str) -> dict[str, Any]:
    """The project's metadata with its domain set to ``domain`` (``none`` clears it).

    Every other key is kept, because REST replaces ``metadata`` as a whole. A legacy free-text
    ``metadata.domain`` is removed: it would otherwise keep overriding the domain just chosen
    (the same rule the catalog's Categorize write applies).
    """
    metadata = _metadata(project)
    metadata.pop("domain", None)
    metadata["domainCategory"] = domain
    return metadata


def changes_from_flags(
    project: Mapping[str, Any],
    *,
    name: Optional[str] = None,
    rename: Optional[str] = None,
    description: Optional[str] = None,
    domain: Optional[str] = None,
) -> dict[str, Any]:
    """The fields the flags change, with their new values — unchanged values are left out.

    Args:
        project: The project as ``GET /v1/projects/{tenant}/{id}`` returns it.
        name: ``--name``.
        rename: ``--rename`` (the new slug).
        description: ``--description`` (an empty string clears it).
        domain: ``--domain`` (``none`` clears it).

    Returns:
        ``{field: new_value}`` for each field that differs from ``project``.

    Raises:
        ProjectUpdateError: On an empty name, an invalid slug or an unknown domain.
    """
    wanted: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise ProjectUpdateError("--name cannot be empty.")
        wanted["name"] = name.strip()
    if rename is not None:
        wanted["slug"] = validate_slug(rename)
    if description is not None:
        wanted["description"] = description.strip() or None
    if domain is not None:
        wanted["metadata"] = metadata_with_domain(project, validate_domain(domain))
    return {field: value for field, value in wanted.items() if project.get(field) != value}


def changes_from_file(
    project: Mapping[str, Any], document: Mapping[str, Any]
) -> dict[str, Any]:
    """The editable fields an edited ``projects get --json`` dump changes.

    Only :data:`EDITABLE_FIELDS` are read; a field the file leaves out is left alone. The
    file must describe the same project (its ``id``).

    Raises:
        ProjectUpdateError: When the file is for another project, or a value is invalid.
    """
    if str(document.get("id", "")) != str(project.get("id")):
        raise ProjectUpdateError(
            f"The file describes project {document.get('id')!r}, not {project.get('id')!r}."
        )
    wanted: dict[str, Any] = {}
    for field in EDITABLE_FIELDS:
        if field not in document:
            continue
        value = document[field]
        if field == "name" and (not isinstance(value, str) or not value.strip()):
            raise ProjectUpdateError("The file's name cannot be empty.")
        if field == "slug":
            value = validate_slug(str(value))
        if field == "enabled" and not isinstance(value, bool):
            raise ProjectUpdateError("The file's enabled must be true or false.")
        if field == "metadata" and value is not None and not isinstance(value, Mapping):
            raise ProjectUpdateError("The file's metadata must be an object.")
        if field == "description" and isinstance(value, str):
            value = value.strip() or None
        wanted[field] = value
    return {field: value for field, value in wanted.items() if project.get(field) != value}


def expected_updated_at(document: Mapping[str, Any]) -> str:
    """The ``updated_at`` an edited dump was taken at — the ``--from-file`` precondition.

    Raises:
        ProjectUpdateError: When the file has none (it was not a ``projects get --json`` dump).
    """
    value = document.get("updated_at")
    if not isinstance(value, str) or not value.strip():
        raise ProjectUpdateError(
            "The file has no updated_at; create it with `apiome projects get <id> --json`."
        )
    return value


def field_changes(project: Mapping[str, Any], changes: Mapping[str, Any]) -> list[FieldChange]:
    """Expand ``changes`` into the diff's rows, in :data:`EDITABLE_FIELDS` order.

    ``metadata`` is shown key by key (``metadata.domainCategory``), so a one-key edit is not
    drawn as the whole object changing.
    """
    rows: list[FieldChange] = []
    for field in EDITABLE_FIELDS:
        if field not in changes:
            continue
        if field == "metadata":
            before = _metadata(project)
            after = dict(changes[field] or {})
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    rows.append(FieldChange(f"metadata.{key}", before.get(key), after.get(key)))
        else:
            rows.append(FieldChange(field, project.get(field), changes[field]))
    return rows


def _show(value: Any) -> str:
    """A value as the diff prints it: JSON, with an absent value spelled ``(none)``."""
    if value is None:
        return "(none)"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_diff(project: Mapping[str, Any], changes: Mapping[str, Any]) -> str:
    """The ``--dry-run`` diff: one ``-``/``+`` pair per changed value, under a header.

    Example::

        Project payments-api (3f2a…)
        - name: "Payments"
        + name: "Payments v2"
        - metadata.domainCategory: (none)
        + metadata.domainCategory: "finance"

    Returns:
        The diff text, or a one-line "no changes" message when nothing differs.
    """
    header = f"Project {project.get('slug')} ({project.get('id')})"
    rows = field_changes(project, changes)
    if not rows:
        return f"{header}\nNo changes."
    lines = [header]
    for row in rows:
        lines.append(f"- {row.field}: {_show(row.before)}")
        lines.append(f"+ {row.field}: {_show(row.after)}")
    return "\n".join(lines)


def request_body(changes: Mapping[str, Any], updated_at: Optional[str]) -> dict[str, Any]:
    """The ``PUT`` body: the changed fields, plus the optimistic-concurrency precondition.

    ``description: None`` is sent as ``""`` — the REST API skips a null field but clears the
    description on an empty string.
    """
    body: dict[str, Any] = {}
    for field, value in changes.items():
        body[field] = "" if field == "description" and value is None else value
    if updated_at:
        body["expectedUpdatedAt"] = updated_at
    return body
