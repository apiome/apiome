"""The rules of ``apiome versions fork`` (CLI 4.4, #3211).

A fork copies one revision of a project **into another project** — the REST
``POST /v1/versions/{tenant}/{target}/fork`` — recording where it came from, so the target can
later merge back. Within one project the product calls that a branch, and the server refuses a
same-project fork. These functions hold every decision the command makes, without HTTP:

* :func:`find_source_version` — the source by UUID, version label (``2.1.0`` or ``v2.1.0``) or
  version tag;
* :func:`parse_release` / :func:`check_new_version` — the new label must be a plain
  ``MAJOR.MINOR.PATCH`` (what the server accepts) and, unless ``--allow-lesser``, strictly
  greater than the source's;
* :func:`copy_counts` — what will be copied (classes and their properties; paths are not
  copied by the server);
* :func:`render_summary` — the human summary for a fork or a ``--dry-run``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence
from uuid import UUID

_RELEASE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class ForkError(ValueError):
    """An argument the fork refuses, with a message for stderr (exit 2)."""


def parse_release(label: Any) -> Optional[tuple[int, int, int]]:
    """``"v2.1.0"`` / ``"2.1.0"`` → ``(2, 1, 0)``; anything else → ``None``."""
    text = str(label or "").strip()
    if text[:1] in ("v", "V") and text[1:2].isdigit():
        text = text[1:]
    match = _RELEASE_RE.match(text)
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def check_new_version(
    new_label: str, source_label: Any, *, allow_lesser: bool
) -> str:
    """Validate ``--to`` and return it as the server expects it (no ``v`` prefix).

    Args:
        new_label: ``--to``.
        source_label: The source version's label.
        allow_lesser: ``--allow-lesser`` — skip the strictly-greater rule.

    Returns:
        ``MAJOR.MINOR.PATCH``.

    Raises:
        ForkError: When ``--to`` is not a plain release version, or is not strictly greater than
            the source (and ``--allow-lesser`` was not passed).
    """
    new = parse_release(new_label)
    if new is None:
        raise ForkError(
            f"--to must be a release version like 3.0.0 (got {new_label!r}); pre-release and "
            "build suffixes such as -rc.1 are not supported by the server."
        )
    normalized = ".".join(str(part) for part in new)
    source = parse_release(source_label)
    if source is not None and not allow_lesser and new <= source:
        raise ForkError(
            f"--to {normalized} must be greater than the source version {source_label}; "
            "pass --allow-lesser to fork to a lower or equal version."
        )
    return normalized


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class SourceMatch:
    """The source revision and how the reference matched it."""

    version: dict[str, Any]
    #: ``id``, ``label`` or ``tag``.
    matched_by: str


def find_source_version(
    versions: Sequence[dict[str, Any]],
    version_tags: Sequence[dict[str, Any]],
    ref: str,
) -> SourceMatch:
    """Find the source revision by UUID, version label, or version tag — in that order.

    A label matches with or without a leading ``v``; a tag matches its exact name.

    Raises:
        ForkError: When nothing matches.
    """
    wanted = ref.strip()
    if _is_uuid(wanted):
        for version in versions:
            if str(version.get("id")) == wanted:
                return SourceMatch(version, "id")
    else:
        release = parse_release(wanted)
        for version in versions:
            label = version.get("version_id")
            if str(label) == wanted or (release is not None and parse_release(label) == release):
                return SourceMatch(version, "label")
        for tag in version_tags:
            if tag.get("name") == wanted:
                for version in versions:
                    if str(version.get("id")) == str(tag.get("version_id")):
                        return SourceMatch(version, "tag")
    raise ForkError(f"No version or version tag {ref!r} in the source project.")


def label_exists(versions: Sequence[dict[str, Any]], label: str) -> bool:
    """Whether a project already has the version ``label``."""
    release = parse_release(label)
    return any(
        str(v.get("version_id")) == label
        or (release is not None and parse_release(v.get("version_id")) == release)
        for v in versions
    )


def copy_counts(classes: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """``(classes, properties)`` the fork copies, from ``…/with-properties-tags``."""
    return len(classes), sum(len(c.get("properties") or []) for c in classes)


def tags_to_copy(
    version_tags: Sequence[dict[str, Any]], source_version_id: str
) -> list[dict[str, Any]]:
    """The source project's version tags that point at the source revision, by name."""
    return sorted(
        (t for t in version_tags if str(t.get("version_id")) == source_version_id),
        key=lambda t: str(t.get("name")),
    )


def render_summary(
    *,
    dry_run: bool,
    source: str,
    target: str,
    classes: int,
    properties: int,
    source_paths: int,
    new_id: Optional[str] = None,
    tags_copied: Sequence[str] = (),
    tags_skipped: Sequence[str] = (),
    include_tags: bool = False,
) -> str:
    """The human summary of a fork (or of what a ``--dry-run`` would do)."""
    if dry_run:
        head = f"Would fork {source} → {target} (dry run; nothing was created)"
        verb = "to copy"
    else:
        head = f"✔ Forked {source} → {target}" + (f" ({new_id})" if new_id else "")
        verb = "copied"
    rows = [
        (f"Classes {verb}:", f"{classes:,}"),
        (f"Properties {verb}:", f"{properties:,}"),
        ("Paths:", f"not copied ({source_paths:,} in the source)" if source_paths else "none in the source"),
    ]
    if include_tags:
        value = ", ".join(tags_copied) if tags_copied else "none"
        if tags_skipped:
            value += f" (skipped, name taken: {', '.join(tags_skipped)})"
        rows.append((f"Tags {verb}:", value))
    rows.append(("State:", "draft"))
    width = max(len(label) for label, _ in rows)
    return "\n".join([head, *(f"  {label.ljust(width)} {value}" for label, value in rows)])
