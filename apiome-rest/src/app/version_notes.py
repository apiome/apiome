"""Revision note + changelog validation (git-like commit / annotated tag analog).

Policy defaults come from :class:`VersionNotesLimits` and ``Settings``; per-project
overrides live in ``projects.metadata.commitPolicy`` (JSON).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel

from .config import settings


class CommitPolicyViolation(Exception):
    """Pre-commit policy rejection; use ``code`` + ``message`` for REST error bodies."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def commit_policy_http_exception(exc: CommitPolicyViolation) -> HTTPException:
    """Convert a :class:`CommitPolicyViolation` to a 400 :class:`HTTPException` with a machine-readable body."""
    return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})


@dataclass(frozen=True)
class VersionNotesLimits:
    max_short_message_chars: int
    max_changelog_chars: int
    require_short_message: bool
    max_commit_payload_bytes: int


_DEFAULT_MAX_COMMIT_PAYLOAD_BYTES = 5_242_880  # 5 MiB; kept in sync with Settings default

DEFAULT_VERSION_NOTES_LIMITS = VersionNotesLimits(
    max_short_message_chars=2000,
    max_changelog_chars=65535,
    require_short_message=True,
    max_commit_payload_bytes=_DEFAULT_MAX_COMMIT_PAYLOAD_BYTES,
)


def _coerce_metadata_dict(metadata: Any) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _int_from_policy(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def effective_commit_policy(
    _tenant_id: str,
    project_metadata: Optional[Any] = None,
) -> VersionNotesLimits:
    """
    Effective limits for a tenant + optional project ``metadata`` (DB JSON).

    Reads ``metadata.commitPolicy`` (or ``commit_policy``) with optional keys:
    ``requireShortMessage``, ``maxShortMessageChars``, ``maxChangelogChars``,
    ``maxCommitPayloadBytes`` (camelCase or snake_case).
    """
    base = DEFAULT_VERSION_NOTES_LIMITS
    max_payload = int(
        getattr(settings, "commit_policy_max_payload_bytes_default", _DEFAULT_MAX_COMMIT_PAYLOAD_BYTES)
    )
    lim = replace(base, max_commit_payload_bytes=max_payload)

    md = _coerce_metadata_dict(project_metadata)
    policy = md.get("commitPolicy") or md.get("commit_policy")
    if not isinstance(policy, dict):
        return lim

    updates: Dict[str, Any] = {}
    if "requireShortMessage" in policy:
        updates["require_short_message"] = bool(policy["requireShortMessage"])
    elif "require_short_message" in policy:
        updates["require_short_message"] = bool(policy["require_short_message"])

    m = _int_from_policy(policy.get("maxShortMessageChars") or policy.get("max_short_message_chars"))
    if m is not None and m > 0:
        updates["max_short_message_chars"] = m

    m = _int_from_policy(policy.get("maxChangelogChars") or policy.get("max_changelog_chars"))
    if m is not None and m > 0:
        updates["max_changelog_chars"] = m

    m = _int_from_policy(policy.get("maxCommitPayloadBytes") or policy.get("max_commit_payload_bytes"))
    if m is not None and m > 0:
        updates["max_commit_payload_bytes"] = m

    if not updates:
        return lim
    return replace(lim, **updates)


def limits_for_tenant(tenant_id: str) -> VersionNotesLimits:
    """Backward-compatible: defaults only (no project metadata). Prefer :func:`effective_commit_policy`."""
    return effective_commit_policy(tenant_id, None)


def commit_request_json_byte_length(model: BaseModel) -> int:
    """UTF-8 size of the JSON representation (alias keys, excluding unset fields), for payload policy."""
    return len(model.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8"))


def enforce_max_commit_payload(model: BaseModel, limits: VersionNotesLimits) -> None:
    """Reject when serialized request JSON exceeds ``limits.max_commit_payload_bytes``."""
    n = commit_request_json_byte_length(model)
    if n > limits.max_commit_payload_bytes:
        raise CommitPolicyViolation(
            "PAYLOAD_TOO_LARGE",
            f"Commit request payload exceeds maximum size ({limits.max_commit_payload_bytes} bytes).",
        )


def validate_version_notes(
    short_message: Optional[str],
    changelog: Optional[str],
    limits: VersionNotesLimits,
    *,
    require_short_message: Optional[bool] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Strip and validate revision note + changelog.

    Returns (short_message, changelog) with None for empty optional strings.
    Raises CommitPolicyViolation on violation.
    """
    req = limits.require_short_message if require_short_message is None else require_short_message
    sm = short_message.strip() if short_message else None
    cl = changelog.strip() if changelog else None
    if req and not sm:
        raise CommitPolicyViolation(
            "POLICY_VIOLATION",
            "Revision note (shortMessage) is required",
        )
    if sm and len(sm) > limits.max_short_message_chars:
        raise CommitPolicyViolation(
            "POLICY_VIOLATION",
            f"Revision note exceeds maximum length ({limits.max_short_message_chars} characters)",
        )
    if cl and len(cl) > limits.max_changelog_chars:
        raise CommitPolicyViolation(
            "POLICY_VIOLATION",
            f"Changelog exceeds maximum length ({limits.max_changelog_chars} characters)",
        )
    return sm, cl


def extract_breaking_hints_from_changelog(changelog: Optional[str]) -> list[str]:
    """
    Lines in markdown changelog that look like breaking-change bullets, for downstream
    docs (#746 / migration guides). Best-effort; does not parse full Markdown.
    """
    if not changelog:
        return []
    out: list[str] = []
    for raw in changelog.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower().lstrip("-*•").strip()
        if lower.startswith("breaking:") or lower.startswith("breaking "):
            out.append(raw.strip())
    return out
