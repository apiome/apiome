"""The rules of ``apiome versions create`` (CLI 4.3, #3210; ported to the Python CLI by #3177).

``versions create`` cuts a new **draft** version of a project — the REST
``POST /v1/versions/{tenant}/{project}`` — for CI flows such as "on tag push, cut the next
version". A push is optimistically locked: the request names the head revision the client
expects (``baseRevisionId``), so the command looks the head up itself. These functions hold
every decision the command makes, without HTTP:

* :func:`check_label` — ``--version`` must be a plain ``MAJOR.MINOR.PATCH`` (what the server
  accepts) and not already a version of the project;
* :func:`read_notes` / :func:`load_body` — ``--notes`` / ``--notes-file`` and ``--from-file``;
* :func:`expected_head` — the head the push must name: the branch tip, or the newest revision of
  a project without branches;
* :func:`default_base` — the version the new draft copies its classes from when ``--base`` is not
  given: the latest **published** version;
* :func:`build_body` — the request body.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from apiome_cli.version_compat import newest_first
from apiome_cli.version_fork import label_exists, parse_release


class CreateError(ValueError):
    """An argument the command refuses, with a message for stderr (exit 2)."""


class VersionExists(CreateError):
    """``--version`` is already a version of the project (exit 6)."""


def check_label(label: str, versions: Sequence[Mapping[str, Any]]) -> str:
    """Validate ``--version`` and return it as the server expects it (no ``v`` prefix).

    Args:
        label: ``--version`` (``1.2.0`` or ``v1.2.0``).
        versions: The project's versions.

    Returns:
        ``MAJOR.MINOR.PATCH``.

    Raises:
        CreateError: When it is not a plain release version.
        VersionExists: When the project already has it.
    """
    release = parse_release(label)
    if release is None:
        raise CreateError(
            f"--version must be a release version like 1.2.0 (got {label!r}); pre-release and build "
            "suffixes such as -rc.1 are not accepted by the server."
        )
    normalized = ".".join(str(part) for part in release)
    if label_exists(versions, normalized):
        raise VersionExists(
            f"Version {normalized} already exists in this project; pick another --version "
            "(apiome versions list shows the taken labels)."
        )
    return normalized


def read_notes(notes: str | None, notes_file: Path | None) -> tuple[str | None, str | None]:
    """``(short message, changelog)`` from ``--notes`` / ``--notes-file``.

    ``--notes`` is the revision's short note; ``--notes-file`` is read as UTF-8 markdown and
    becomes its changelog. They are mutually exclusive.

    Raises:
        CreateError: When both are given, or the file cannot be read as UTF-8.
    """
    if notes is not None and notes_file is not None:
        raise CreateError("Pass --notes or --notes-file, not both.")
    if notes_file is None:
        return (notes.strip() or None) if notes is not None else None, None
    try:
        text = notes_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CreateError(f"{notes_file} is not UTF-8 text.") from exc
    except OSError as exc:
        raise CreateError(f"Cannot read {notes_file}: {exc.strerror or exc}.") from exc
    return None, text


def load_body(path: Path | None) -> dict[str, Any]:
    """The request body ``--from-file`` names (a JSON object), or ``{}``.

    Raises:
        CreateError: When the file cannot be read or is not a JSON object.
    """
    if path is None:
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CreateError(f"Cannot read {path}: {exc.strerror or exc}.") from exc
    except ValueError as exc:
        raise CreateError(f"{path} is not valid JSON: {exc}.") from exc
    if not isinstance(body, dict):
        raise CreateError(f"{path} must hold a JSON object (the version request body).")
    return body


def expected_head(
    versions: Sequence[Mapping[str, Any]],
    branches: Sequence[Mapping[str, Any]],
    branch: str | None,
) -> str | None:
    """The revision the push must name as ``baseRevisionId`` (the server's rule, #2566).

    Args:
        versions: The project's versions.
        branches: Its version branches (``…/version-branches``).
        branch: ``--branch``, when given.

    Returns:
        The branch tip (the named branch, or the only one), the newest revision when the project has
        no branches, or ``None`` when it has no versions at all.

    Raises:
        CreateError: When ``--branch`` names no branch, or the project has several and none was named.
    """
    if branch:
        for row in branches:
            if row.get("name") == branch:
                return str(row.get("tip_version_id") or row.get("tipVersionId") or "") or None
        names = ", ".join(sorted(str(b.get("name")) for b in branches)) or "none"
        raise CreateError(f"No branch {branch!r} in this project (branches: {names}).")
    if len(branches) == 1:
        tip = branches[0].get("tip_version_id") or branches[0].get("tipVersionId")
        return str(tip) if tip else None
    if len(branches) > 1:
        names = ", ".join(sorted(str(b.get("name")) for b in branches))
        raise CreateError(f"The project has several branches ({names}); pass --branch.")
    ordered = newest_first(versions)
    return str(ordered[0]["id"]) if ordered else None


def default_base(versions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The version a new draft copies from by default: the latest published one (``None`` if none)."""
    return next((v for v in newest_first(versions) if v.get("published")), None)


def build_body(
    *,
    from_file: Mapping[str, Any],
    label: str,
    head: str | None,
    short_message: str | None,
    changelog: str | None,
    source_id: str | None,
    copy_paths: bool,
    branch: str | None,
) -> dict[str, Any]:
    """The ``POST /v1/versions/{tenant}/{project}`` body.

    ``--from-file`` supplies a full body; the flags win over it for the fields they set, and the
    command always names the head it looked up.
    """
    body: dict[str, Any] = dict(from_file)
    body["version_id"] = label
    body["baseRevisionId"] = head or ""
    if short_message:
        body["shortMessage"] = short_message
    if changelog:
        body["changelog"] = changelog
    if source_id:
        body["source_version_id"] = source_id
        if copy_paths:
            body["copyPaths"] = True
    if branch:
        body["branchName"] = branch
    return body


def stale_head_message(detail: Mapping[str, Any]) -> str:
    """The hint for a ``409 STALE_HEAD``: someone pushed between the head lookup and the create."""
    head = detail.get("currentHead") or {}
    moved_to = head.get("versionId") or detail.get("currentHeadRevisionId") or "another revision"
    return (
        f"The project's head moved to {moved_to} while the version was being created; re-run the "
        "command to create it on top of the new head."
    )
