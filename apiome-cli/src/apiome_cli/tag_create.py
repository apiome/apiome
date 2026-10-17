"""The rules of ``apiome tags create`` (CLI 11.5, #3264).

A version tag is a named pointer to one of a project's versions, created with
``POST /v1/version-tags/{tenant}/{project}`` (``{version_id, name, message, channel, immutable,
protected}``). These functions hold the command's decisions, without HTTP:

* :func:`normalize_tag_name` — lower-cased, ``^[a-z][a-z0-9-]{1,40}$`` (stricter than the server,
  which accepts any ``[A-Za-z0-9._-/]`` name, so CLI-made tags stay easy to type in scripts).
  Conventional names such as ``latest``, ``stable`` and ``next`` are not reserved;
* :func:`merge_request` — ``--from-file`` (a JSON tag object, e.g. an edited ``tags show --json``)
  under the command-line flags;
* :func:`needs_confirmation` — only an **immutable** tag is confirmed, since it can never be moved
  or deleted afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

TAG_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class TagCreateError(ValueError):
    """An argument or file the command refuses (exit 2)."""


def normalize_tag_name(raw: Any) -> str:
    """``" Stable "`` → ``"stable"``; refuse anything outside ``^[a-z][a-z0-9-]{1,40}$``.

    Raises:
        TagCreateError: When the lower-cased name does not match.
    """
    name = str(raw or "").strip().lower()
    if not TAG_NAME_RE.match(name):
        raise TagCreateError(
            f"Invalid tag name {str(raw or '')!r}: use 2–41 characters — a letter, then lower-case "
            "letters, digits or hyphens (e.g. stable, prod-eu)."
        )
    return name


@dataclass(frozen=True)
class TagRequest:
    """What ``tags create`` sends, before the version is resolved to its record id."""

    name: str
    version_ref: str
    message: Optional[str]
    channel: Optional[str]
    immutable: bool
    protected: bool


def _text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def merge_request(
    *,
    name: Optional[str],
    version: Optional[str],
    description: Optional[str],
    document: Optional[Mapping[str, Any]] = None,
) -> TagRequest:
    """Combine ``--from-file`` with the flags; a flag wins over the file.

    The file is a JSON tag object. It may use the ``tags show --json`` keys (``name``,
    ``target_version_string`` or ``version_id``, ``message``, ``channel``, ``immutable``,
    ``protected``) or the friendlier ``version`` and ``description``.

    Raises:
        TagCreateError: When no name or no version is given, or the name is invalid.
    """
    doc = dict(document or {})
    raw_name = name if name is not None else doc.get("name")
    if raw_name is None:
        raise TagCreateError("Name the tag: apiome tags create <project> <tag> --version <version>.")
    version_ref = _text(version) or _text(doc.get("version")) or _text(doc.get("target_version_string")) or _text(
        doc.get("version_id")
    )
    if not version_ref:
        raise TagCreateError("--version is required: the version the tag points to (e.g. 2.1.0).")
    message = _text(description) if description is not None else _text(doc.get("description") or doc.get("message"))
    return TagRequest(
        name=normalize_tag_name(raw_name),
        version_ref=version_ref,
        message=message,
        channel=_text(doc.get("channel")),
        immutable=bool(doc.get("immutable")),
        protected=bool(doc.get("protected")),
    )


def needs_confirmation(request: TagRequest) -> bool:
    """Only an immutable tag is confirmed: it can never be moved or deleted."""
    return request.immutable


def request_body(request: TagRequest, version_record_id: str) -> dict[str, Any]:
    """The ``POST /v1/version-tags/…`` body."""
    return {
        "version_id": version_record_id,
        "name": request.name,
        "message": request.message,
        "channel": request.channel,
        "immutable": request.immutable,
        "protected": request.protected,
    }
