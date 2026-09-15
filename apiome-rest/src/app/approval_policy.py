"""Approval policy vocabulary — COL-2.3 (#4519).

Deliberately dependency-free, for the same reason
:mod:`app.breaking_publish_policy` is: the style-guide editor
(:mod:`app.style_guide_routes` / :mod:`app.style_guide_revisions`) and the publish gate
(:mod:`app.approval_publish_gate`) both normalize the same two stored values, and the guide
surfaces must not drag the review store into their import graph to do it.

The policy is two settings on the governing style guide (apiome-db **V262**):

``required_approvals``
    How many approvals the version's current review round must carry before it may be
    published. ``0`` (the default) switches the gate off, which is the behaviour every tenant
    had before COL-2.3.

``required_reviewer_role``
    An optional RBAC role slug (``roles.slug``) that at least one of those approvals must come
    from. ``None`` means any approver counts. It only qualifies the count — a role on its own
    never gates a publish, because "0 approvals, one of them from a release manager" is not a
    policy anyone can satisfy.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "DEFAULT_REQUIRED_APPROVALS",
    "MAX_REQUIRED_APPROVALS",
    "MAX_REVIEWER_ROLE_LENGTH",
    "normalize_required_approvals",
    "normalize_required_reviewer_role",
]

#: What a guide gets without configuring anything: no approval gate at all.
DEFAULT_REQUIRED_APPROVALS = 0

#: The cap, mirroring :data:`app.reviews.MAX_REVIEWERS` and the V262 check constraint. A round
#: can never collect more approvals than it has reviewers, so a larger requirement would be
#: permanently unsatisfiable rather than merely strict.
MAX_REQUIRED_APPROVALS = 20

#: The longest role slug, mirroring ``roles.slug VARCHAR(64)`` (V118).
MAX_REVIEWER_ROLE_LENGTH = 64


def normalize_required_approvals(raw: Any) -> int:
    """Coerce a stored or submitted approval count into the supported range.

    Args:
        raw: Any candidate value — a DB column, a request field, ``None``.

    Returns:
        An ``int`` in ``0..``:data:`MAX_REQUIRED_APPROVALS`. Anything unparseable or negative
        falls back to :data:`DEFAULT_REQUIRED_APPROVALS`, so a bad value can never silently
        arm the gate; a value above the cap is clamped to it rather than dropped, because a
        tenant asking for "everyone" meant more, not less.
    """
    if isinstance(raw, bool):  # bool is an int subclass; True is not "1 approval".
        return DEFAULT_REQUIRED_APPROVALS
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_REQUIRED_APPROVALS
    if value < 0:
        return DEFAULT_REQUIRED_APPROVALS
    return min(value, MAX_REQUIRED_APPROVALS)


def normalize_required_reviewer_role(raw: Any) -> Optional[str]:
    """Coerce a stored or submitted reviewer-role slug into its canonical spelling.

    Args:
        raw: Any candidate value — a DB column, a request field, ``None``.

    Returns:
        The trimmed, lower-cased slug, or ``None`` when there is no usable one. Role slugs are
        compared, never joined, so the canonical spelling is what makes
        ``" Release-Manager "`` and ``"release-manager"`` the same requirement. Over-long
        values yield ``None`` rather than a truncated slug that would match nothing.
    """
    if isinstance(raw, bool) or not isinstance(raw, (str, bytes)):
        return None
    text = (raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw).strip().lower()
    if not text or len(text) > MAX_REVIEWER_ROLE_LENGTH:
        return None
    return text
