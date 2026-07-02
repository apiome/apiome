"""Extract project and version metadata from OpenAPI info objects.

This module maps the ``info`` block of a parsed OpenAPI document onto the
``projects`` and ``project_versions`` database columns defined in migrations
V13 and V14:

* ``info.title``   → ``projects.name``   (override: ``project_name`` arg)
* ``info.version`` → ``project_versions.version`` (override: ``version`` arg)
* All remaining ``info`` keys (including ``x-*`` extensions) → ``data`` JSONB.

Slugs are derived automatically via :mod:`apiome_cli.extract.slug` and
validated against the DB ``CHECK`` constraints.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from apiome_cli.extract.slug import slugify_project_name, slugify_version

X_APIOME_PROJECT_SLUG = "x-apiome-project-slug"
X_APIOME_VERSION_SLUG = "x-apiome-version-slug"
X_APIOME_PROJECT_NAME_FIELD = "x-apiome-project-name-field"

DEFAULT_PROJECT_NAME_FIELD = "info.title"
X_PROVIDER_NAME = "x-providerName"
X_SERVICE_NAME = "x-serviceName"
_INFO_STRIP_KEYS = frozenset(
    {
        "title",
        "version",
        X_APIOME_PROJECT_SLUG,
        X_APIOME_VERSION_SLUG,
        X_APIOME_PROJECT_NAME_FIELD,
    },
)
_MAX_PROJECT_NAME_FIELD_LENGTH = 255
_MAX_PROJECT_NAME_FIELD_SEGMENTS = 64
_PROJECT_NAME_FIELD_RE = re.compile(r"^[#]?[/a-zA-Z0-9._~-]+$")


@dataclasses.dataclass(frozen=True)
class InfoMetadata:
    """Extracted and normalised metadata from an OpenAPI ``info`` block.

    Attributes:
        name:         Human-readable project name derived from ``info.title``
                      (or overridden by the caller).
        version:      Version display string derived from ``info.version``
                      (or overridden by the caller).
        project_slug: URL-safe slug for the ``projects`` table.  Matches the
                      DB constraint ``^[a-z0-9]([a-z0-9-]*[a-z0-9])?$``.
        version_slug: URL-safe slug for the ``project_versions`` table.
                      Matches ``^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$``.
        data:         Remaining ``info`` fields (``description``, ``contact``,
                      ``x-*`` extensions, etc.) with ``title`` and ``version``
                      stripped.  Empty dict when no extra fields are present.
    """

    name: str
    version: str
    project_slug: str
    version_slug: str
    data: dict[str, Any]


def _resolve_json_pointer(document: Any, pointer: str) -> Any | None:
    trimmed = pointer.strip()
    if trimmed.startswith("#/"):
        path = trimmed[1:]
    elif trimmed.startswith("/"):
        path = trimmed
    else:
        return None
    if not path.startswith("/"):
        return None

    current: Any = document
    for raw_token in path[1:].split("/"):
        if raw_token == "":
            return None
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return None
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                index = int(token)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _resolve_dot_path(document: Any, path: str) -> Any | None:
    current: Any = document
    for segment in path.split("."):
        if not segment:
            return None
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def validate_project_name_field(field_path: str) -> str:
    trimmed = field_path.strip()
    if not trimmed:
        raise ValueError("Project name field path cannot be empty.")
    if len(trimmed) > _MAX_PROJECT_NAME_FIELD_LENGTH:
        raise ValueError(
            "Project name field path exceeds maximum length of "
            f"{_MAX_PROJECT_NAME_FIELD_LENGTH} characters."
        )
    if not _PROJECT_NAME_FIELD_RE.fullmatch(trimmed):
        raise ValueError(
            f"Project name field path {trimmed!r} contains unsupported characters."
        )
    segment_source = trimmed[2:] if trimmed.startswith("#/") else trimmed.lstrip("/")
    segments = [segment for segment in re.split(r"[./]", segment_source) if segment]
    if len(segments) > _MAX_PROJECT_NAME_FIELD_SEGMENTS:
        raise ValueError(
            "Project name field path exceeds maximum depth of "
            f"{_MAX_PROJECT_NAME_FIELD_SEGMENTS} segments."
        )
    return trimmed


def resolve_spec_field_path(document: Any, field_path: str) -> Any | None:
    validated = validate_project_name_field(field_path)
    if validated.startswith("#/") or validated.startswith("/"):
        pointer = validated if validated.startswith("#") else f"#{validated}"
        return _resolve_json_pointer(document, pointer)
    return _resolve_dot_path(document, validated)


def _project_name_field_from_info(info: dict[str, Any]) -> str | None:
    raw = info.get(X_APIOME_PROJECT_NAME_FIELD)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("Project name field override must be a string.")
    return validate_project_name_field(raw)


def _optional_non_empty_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _fallback_project_name_from_info(info: dict[str, Any]) -> str | None:
    provider = _optional_non_empty_string(info.get(X_PROVIDER_NAME))
    service = _optional_non_empty_string(info.get(X_SERVICE_NAME))
    if provider and service:
        return f"{service} ({provider})"
    if provider:
        return provider
    if service:
        return service
    return None


def _resolve_project_name(
    doc: dict[str, Any],
    *,
    info: dict[str, Any],
    project_name: str | None,
    project_name_field: str | None,
) -> str:
    if project_name is not None:
        if not project_name.strip():
            raise ValueError(
                "Cannot resolve project name: --project-name override was empty."
            )
        return project_name.strip()

    field_path = (
        validate_project_name_field(project_name_field)
        if project_name_field is not None
        else _project_name_field_from_info(info) or DEFAULT_PROJECT_NAME_FIELD
    )
    resolved = resolve_spec_field_path(doc, field_path)
    if isinstance(resolved, str) and resolved.strip():
        return resolved.strip()
    fallback = _fallback_project_name_from_info(info)
    if fallback is not None:
        return fallback
    raise ValueError(
        "Cannot resolve project name from "
        f"{field_path!r}: value is absent, empty, or not a string."
    )


def extract_info_metadata(
    doc: dict[str, Any],
    *,
    project_name: str | None = None,
    version: str | None = None,
    project_name_field: str | None = None,
) -> InfoMetadata:
    """Extract project and version metadata from a parsed OpenAPI document.

    Reads the ``info`` block of *doc* and maps fields onto the columns used by
    the ``projects`` (V13) and ``project_versions`` (V14) database tables:

    * ``info.title``   → :attr:`InfoMetadata.name`    (override: *project_name*)
    * ``info.version`` → :attr:`InfoMetadata.version` (override: *version*)
    * Remaining info fields → :attr:`InfoMetadata.data`

    Slugs are generated automatically via :func:`slugify_project_name` and
    :func:`slugify_version`.

    Args:
        doc:          Parsed OpenAPI document (top-level dict from
                      ``load_openapi_file``).
        project_name: Optional CLI override for the project name.  When
                      provided, overrides ``info.title``.
        version:      Optional CLI override for the version string.  When
                      provided, overrides ``info.version``.
        project_name_field: Optional field path override for the project name.

    Returns:
        :class:`InfoMetadata` with ``name``, ``version``, ``project_slug``,
        ``version_slug``, and ``data`` populated.

    Raises:
        ValueError: If ``info`` is missing or not a mapping, if ``title`` or
                    ``version`` cannot be resolved, or if a slug cannot be
                    derived from the resolved name or version.
    """
    info = doc.get("info")
    if not isinstance(info, dict):
        raise ValueError(
            "OpenAPI document is missing a valid 'info' block "
            f"(got {type(info).__name__})."
        )

    resolved_name = _resolve_project_name(
        doc,
        info=info,
        project_name=project_name,
        project_name_field=project_name_field,
    )
    resolved_version = version if version is not None else info.get("version", "")

    if not isinstance(resolved_version, str) or not resolved_version.strip():
        raise ValueError(
            "Cannot resolve version: 'info.version' is absent or empty "
            "and no --version override was supplied."
        )

    resolved_version = resolved_version.strip()

    project_slug_override = info.get(X_APIOME_PROJECT_SLUG)
    if project_slug_override is not None and not isinstance(project_slug_override, str):
        raise ValueError("Project slug override must be a string.")

    project_slug = (
        project_slug_override.strip()
        if isinstance(project_slug_override, str) and project_slug_override.strip()
        else slugify_project_name(resolved_name)
    )
    version_slug_override = info.get(X_APIOME_VERSION_SLUG)
    if version_slug_override is not None and not isinstance(version_slug_override, str):
        raise ValueError("Version slug override must be a string.")
    version_slug = (
        version_slug_override.strip()
        if isinstance(version_slug_override, str) and version_slug_override.strip()
        else slugify_version(resolved_version)
    )

    data: dict[str, Any] = {
        key: value
        for key, value in info.items()
        if key not in _INFO_STRIP_KEYS
    }

    return InfoMetadata(
        name=resolved_name,
        version=resolved_version,
        project_slug=project_slug,
        version_slug=version_slug,
        data=data,
    )
