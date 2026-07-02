"""Import-time publish visibility normalization for the REST API."""

from __future__ import annotations

PUBLISH_FLAG_HELP = (
    "Publish the imported project version immediately as ``public`` or "
    "``private`` (tenant-protected). Omit to leave the version as ``draft``."
)

VISIBILITY_FLAG_HELP = "Alias for ``--publish`` (accepts ``public`` or ``private``)."

TYPE_PUBLISH_FLAG_HELP = (
    "Publish imported types to the system-wide library as ``public``, or import "
    "``private`` to the caller's tenant only. Omit to default to tenant scope."
)


def normalize_cli_import_visibility(value: str) -> str:
    """Normalize a CLI publish flag to the REST ``visibility`` enum.

    User-facing ``private`` maps to API ``protected``.
    """
    normalized = value.strip().lower()
    if normalized == "private":
        return "protected"
    if normalized in {"public", "protected"}:
        return normalized
    msg = "--publish must be 'public' or 'private'."
    raise ValueError(msg)


def resolve_publish_visibility(
    *,
    publish: str | None,
    visibility: str | None,
) -> str | None:
    """Return the REST ``visibility`` value from ``--publish`` or ``--visibility``."""
    if publish is not None and visibility is not None:
        msg = "Use only one of --publish and --visibility."
        raise ValueError(msg)
    raw = publish if publish is not None else visibility
    if raw is None:
        return None
    return normalize_cli_import_visibility(raw)


def resolve_type_publish_system(
    *,
    publish: str | None,
    visibility: str | None,
) -> bool | None:
    """Return the REST ``system`` flag from ``--publish`` or ``--visibility``.

    ``public`` imports into the system-wide type library (master tenant only).
    ``private`` imports into the caller's tenant. When both flags are omitted,
    returns ``None`` so the request body omits ``system`` and REST defaults to
    tenant scope.
    """
    if publish is not None and visibility is not None:
        msg = "Use only one of --publish and --visibility."
        raise ValueError(msg)
    raw = publish if publish is not None else visibility
    if raw is None:
        return None
    normalized = normalize_cli_import_visibility(raw)
    return normalized == "public"
