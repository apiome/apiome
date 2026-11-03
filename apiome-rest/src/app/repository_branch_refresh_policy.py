"""Per-branch repository refresh policy (RAR-6.4, #3541).

A repository can carry branch rules, each naming a branch exactly (``main``) or with a glob
(``release/*``) and setting, for the branches it matches:

* whether they refresh on the schedule and on push (``refresh_enabled``);
* how often (``refresh_interval_seconds``; ``None`` inherits the repository's cadence);
* which version line a refresh lands in (``target_version_line``; ``None`` keeps the default
  naming).

This module is pure (no I/O): it resolves which rule governs a branch, the branch's effective
settings, whether the branch is due, and the label and parent of a version-line refresh. The
sweep (:mod:`app.repository_refresh_sweep`), the push refresh
(:mod:`app.repository_webhook_refresh`) and the manual refresh call it, and the executor
(:mod:`app.repository_refresh_executor`) names the refreshed version from the job's line.

**Matching.** ``*`` matches any characters except ``/``, ``**`` matches any characters
including ``/``, and ``?`` matches one character except ``/`` — so ``release/*`` matches
``release/2.0`` but not ``release/2.0/hotfix``. When several rules match, the most specific
wins: an exact name beats any glob, then the glob with the most literal characters, then the
pattern that sorts first (so the choice never depends on storage order).

**Fallback.** A branch no rule matches keeps the repository-wide settings, so a repository with
no rules refreshes exactly as before. The repository's ``auto_refresh_enabled`` stays the
master switch: when it is off, no branch refreshes on the schedule, whatever its rule says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from .repository_refresh_cadence import is_repository_due, resolve_refresh_interval
from .versioning import format_version_tag

__all__ = [
    "BranchRefreshRule",
    "EffectiveBranchRefresh",
    "VERSION_LINE_PATTERN",
    "effective_branch_refresh",
    "is_branch_due",
    "is_glob",
    "pattern_matches",
    "resolve_branch_rule",
    "rule_from_row",
    "select_version_line_parent",
    "validate_branch_pattern",
    "validate_version_line",
    "version_line_label",
]

#: A version line: letters, digits, ``.``, ``_`` and ``-``, starting with a letter or digit
#: (``latest``, ``2.x``, ``release-2``). Mirrors the V350 CHECK constraint.
VERSION_LINE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: The longest version line the column holds (V350 ``VARCHAR(64)``).
MAX_VERSION_LINE_LENGTH = 64

_GLOB_CHARS = frozenset("*?")


@dataclass(frozen=True)
class BranchRefreshRule:
    """One branch rule of a repository.

    Attributes:
        branch_pattern: An exact branch name or a glob.
        refresh_enabled: Whether matching branches refresh on the schedule and on push.
        refresh_interval_seconds: Cadence for matching branches; ``None`` inherits the
            repository's.
        target_version_line: The version line a refresh of a matching branch lands in;
            ``None`` keeps the default naming.
    """

    branch_pattern: str
    refresh_enabled: bool = True
    refresh_interval_seconds: Optional[int] = None
    target_version_line: Optional[str] = None


@dataclass(frozen=True)
class EffectiveBranchRefresh:
    """The settings that govern one branch's refresh after resolving its rule.

    Attributes:
        branch: The branch.
        enabled: Whether the branch refreshes on the schedule and on push.
        interval_seconds: The branch's cadence, clamped to the floor.
        target_version_line: The version line its refreshes land in, or ``None``.
        rule_pattern: The pattern of the rule that matched, or ``None`` when the branch
            follows the repository-wide settings.
    """

    branch: str
    enabled: bool
    interval_seconds: int
    target_version_line: Optional[str]
    rule_pattern: Optional[str]


def is_glob(pattern: str) -> bool:
    """Return whether ``pattern`` is a glob (contains ``*`` or ``?``) rather than a branch name."""
    return any(ch in _GLOB_CHARS for ch in pattern)


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a branch glob into an anchored regular expression.

    Args:
        pattern: The glob (``release/*``, ``feature/**``).

    Returns:
        The compiled expression: ``**`` → any characters, ``*`` → any characters but ``/``,
        ``?`` → one character but ``/``; everything else literal.
    """
    out: List[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*" and pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def pattern_matches(pattern: str, branch: str) -> bool:
    """Return whether the rule pattern ``pattern`` matches ``branch``.

    Args:
        pattern: An exact branch name or a glob.
        branch: The branch to test.

    Returns:
        True for an equal name, or a glob that matches the whole branch name.
    """
    if not is_glob(pattern):
        return pattern == branch
    return bool(_glob_regex(pattern).match(branch))


def _specificity(pattern: str) -> tuple:
    """Sort key: exact names first, then globs with more literal characters, then by pattern."""
    literal = sum(1 for ch in pattern if ch not in _GLOB_CHARS)
    return (0 if not is_glob(pattern) else 1, -literal, pattern)


def resolve_branch_rule(
    rules: Iterable[BranchRefreshRule], branch: str
) -> Optional[BranchRefreshRule]:
    """Return the most specific rule that matches ``branch``, or ``None``.

    Args:
        rules: The repository's rules, in any order.
        branch: The branch being refreshed.

    Returns:
        The governing rule, or ``None`` when no rule matches (the branch follows the
        repository-wide settings).
    """
    matching = [rule for rule in rules if pattern_matches(rule.branch_pattern, branch)]
    if not matching:
        return None
    return min(matching, key=lambda rule: _specificity(rule.branch_pattern))


def effective_branch_refresh(
    rules: Sequence[BranchRefreshRule],
    branch: str,
    *,
    repository_enabled: bool,
    repository_interval_seconds: Optional[int],
    floor_seconds: int,
) -> EffectiveBranchRefresh:
    """Resolve the settings that govern ``branch``'s refresh.

    Args:
        rules: The repository's branch rules.
        branch: The branch.
        repository_enabled: The repository's ``auto_refresh_enabled`` (the master switch).
        repository_interval_seconds: The repository's ``refresh_interval_seconds``.
        floor_seconds: The global minimum interval; a shorter cadence is raised to it.

    Returns:
        The branch's :class:`EffectiveBranchRefresh`.
    """
    rule = resolve_branch_rule(rules, branch)
    interval = repository_interval_seconds
    if rule is not None and rule.refresh_interval_seconds is not None:
        interval = rule.refresh_interval_seconds
    return EffectiveBranchRefresh(
        branch=branch,
        enabled=bool(repository_enabled) and (rule is None or rule.refresh_enabled),
        interval_seconds=resolve_refresh_interval(interval, floor_seconds=floor_seconds),
        target_version_line=rule.target_version_line if rule is not None else None,
        rule_pattern=rule.branch_pattern if rule is not None else None,
    )


def is_branch_due(
    last_refreshed_at: Optional[datetime], interval_seconds: int, now: Optional[datetime] = None
) -> bool:
    """Return whether a branch last refreshed at ``last_refreshed_at`` is due again.

    Args:
        last_refreshed_at: When the sweep last refreshed the branch, or ``None`` (never).
        interval_seconds: The branch's effective cadence.
        now: The current time (defaults to now, UTC).

    Returns:
        True when the branch was never refreshed or its interval has elapsed.
    """
    return is_repository_due(last_refreshed_at=last_refreshed_at, interval_seconds=interval_seconds, now=now)


def validate_branch_pattern(pattern: str) -> str:
    """Return ``pattern`` stripped, or raise when it cannot name a branch.

    Args:
        pattern: The requested branch name or glob.

    Returns:
        The stripped pattern.

    Raises:
        ValueError: When the pattern is empty, has whitespace, or starts or ends with ``/``.
    """
    text = (pattern or "").strip()
    if not text:
        raise ValueError("branch pattern is required")
    if any(ch.isspace() for ch in text):
        raise ValueError(f"branch pattern {text!r} must not contain whitespace")
    if text.startswith("/") or text.endswith("/"):
        raise ValueError(f"branch pattern {text!r} must not start or end with '/'")
    return text


def validate_version_line(line: Optional[str]) -> Optional[str]:
    """Return a version line stripped (``None`` for blank), or raise when it is not valid.

    Args:
        line: The requested version line.

    Returns:
        The stripped line, or ``None``.

    Raises:
        ValueError: When the line is too long or has characters a version label cannot use.
    """
    text = (line or "").strip()
    if not text:
        return None
    if len(text) > MAX_VERSION_LINE_LENGTH:
        raise ValueError(f"version line must be at most {MAX_VERSION_LINE_LENGTH} characters")
    if not VERSION_LINE_PATTERN.match(text):
        raise ValueError(
            f"version line {text!r} may use letters, digits, '.', '_' and '-', starting with a letter or digit"
        )
    return text


def version_line_label(line: str, when: datetime) -> str:
    """Return the label of a refreshed version in ``line``: ``<line>-<UTC timestamp>``.

    Args:
        line: The version line (``2.x``).
        when: When the refresh runs.

    Returns:
        For example ``2.x-2026-11-03T21:00Z``.
    """
    return f"{line}-{format_version_tag(when)}"


def _label_in_line(label: str, line: str) -> bool:
    """Whether a version label belongs to ``line`` (the line itself, or ``<line>-…``)."""
    return label == line or label.startswith(f"{line}-")


def select_version_line_parent(
    versions: Iterable[Mapping[str, Any]], line: str
) -> Optional[Mapping[str, Any]]:
    """Return the latest version of ``line`` among ``versions``, the parent of the next refresh.

    Args:
        versions: Version rows with ``version_id`` (the label) and ``created_at``.
        line: The version line.

    Returns:
        The newest version whose label is ``line`` or starts with ``<line>-``, or ``None``
        when the line has no version yet.
    """
    in_line = [v for v in versions if _label_in_line(str(v.get("version_id") or ""), line)]
    if not in_line:
        return None
    return max(in_line, key=lambda v: (v.get("created_at") is not None, v.get("created_at") or 0))


def rule_from_row(row: Mapping[str, Any]) -> BranchRefreshRule:
    """Build a :class:`BranchRefreshRule` from a ``repository_branch_refresh_rule`` row."""
    interval = row.get("refresh_interval_seconds")
    return BranchRefreshRule(
        branch_pattern=str(row.get("branch_pattern") or ""),
        refresh_enabled=bool(row.get("refresh_enabled", True)),
        refresh_interval_seconds=int(interval) if interval is not None else None,
        target_version_line=(row.get("target_version_line") or None),
    )
