"""The rules of ``apiome versions delete`` (CLI 4.9, #3216).

``DELETE /v1/versions/{tenant}/{project}/{id}`` removes a version from every list and spec URL (a
soft delete: only a database administrator can bring it back). Drafts are the normal case — a typo
in a version number, an abandoned spike. A **published** or **frozen** version is refused unless
``--force``, which first goes through the safe paths: unpublish it (4.6 — reason recorded, webhook
subscribers notified, tags moved back) and unfreeze it (4.7 — the server's download rule applies).
Version tags pointing at the version are listed and the delete stops unless ``--detach-tags`` (or
``--force``) removes them first, since a deleted version's tags would otherwise keep their names
taken in the project.

These functions hold the command's decisions, without HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


class DeleteRefused(ValueError):
    """The delete stops before anything changes (exit 6), with the reason for stderr."""


class DeleteUsageError(ValueError):
    """An argument the command refuses (exit 2)."""


def state_of(version: Mapping[str, Any], *, frozen: bool) -> str:
    """``draft``, ``published``, ``frozen`` or ``published, frozen``."""
    parts = []
    if version.get("published"):
        parts.append("published")
    if frozen:
        parts.append("frozen")
    return ", ".join(parts) or "draft"


@dataclass(frozen=True)
class DeletePlan:
    """What the delete will do, in order."""

    label: str
    state: str
    unpublish: bool
    unfreeze: bool
    #: Names of the version tags removed before the delete.
    detach: list[str]


def plan_delete(
    version: Mapping[str, Any],
    *,
    frozen: bool,
    tags: Sequence[Mapping[str, Any]],
    force: bool,
    detach_tags: bool,
    reason: Optional[str],
) -> DeletePlan:
    """Decide whether the delete may go ahead, and what has to happen first.

    Args:
        version: The version (``published``, ``version_id``).
        frozen: Whether it has a frozen snapshot (``GET …/freeze-schema``).
        tags: The version tags pointing at it.
        force: ``--force``.
        detach_tags: ``--detach-tags``.
        reason: ``--reason`` — the unpublish reason, required when ``--force`` unpublishes.

    Returns:
        The :class:`DeletePlan`.

    Raises:
        DeleteRefused: A published / frozen version without ``--force``, or tags without
            ``--detach-tags`` / ``--force``.
        DeleteUsageError: ``--force`` on a published version without ``--reason``.
    """
    label = str(version.get("version_id"))
    published = bool(version.get("published"))
    state = state_of(version, frozen=frozen)
    if (published or frozen) and not force:
        steps = " and ".join(
            step for step, needed in (("unpublish", published), ("unfreeze", frozen)) if needed
        )
        raise DeleteRefused(
            f"{label} is {state}; consumers may depend on it. Pass --force to {steps} it and then "
            f"delete it (or run `apiome versions unpublish` / `versions freeze --unfreeze` yourself)."
        )
    names = sorted(str(t.get("name")) for t in tags)
    if names and not (detach_tags or force):
        raise DeleteRefused(
            f"{label} is pointed to by version tag(s): {', '.join(names)}. Pass --detach-tags to "
            "remove them first."
        )
    clean_reason = (reason or "").strip()
    if published and not clean_reason:
        raise DeleteUsageError(
            "--reason is required with --force on a published version: it is recorded when the "
            "version is unpublished and sent to webhook subscribers."
        )
    return DeletePlan(label=label, state=state, unpublish=published, unfreeze=frozen, detach=names)


def render_plan(
    plan: DeletePlan, *, classes: int, paths: int, downloads: int = 0, reason: Optional[str] = None
) -> str:
    """The summary shown before the typed confirmation."""
    lines = [
        "This will delete:",
        f"  • Version:  {plan.label}  (state: {plan.state})",
        f"  • Classes:  {classes:,}",
        f"  • Paths:    {paths:,}",
    ]
    if plan.detach:
        lines.append(f"  • Tags:     {', '.join(plan.detach)} (removed first)")
    if plan.unpublish:
        lines.append(
            f"  First it is unpublished (reason: {reason}): webhook subscribers are notified and "
            "its tags move back to the previous published version."
        )
    if plan.unfreeze:
        note = f" — downloaded {downloads:,} time(s), so only a tenant administrator can" if downloads else ""
        lines.append(f"  Its frozen snapshot is removed{note}.")
    if not (plan.unpublish or plan.unfreeze):
        lines.append("No published artifacts will be affected.")
    lines.append("The version disappears from every list and spec URL; only a database administrator can restore it.")
    return "\n".join(lines)


def json_result(
    *,
    label: str,
    version_record_id: str,
    removed_tags: Sequence[str],
    moved_tags: Sequence[Mapping[str, Any]],
    unpublished: bool,
    unfrozen: bool,
) -> dict[str, Any]:
    """The ``--json`` shape: ``{deleted: true, version, removed_tags, …}``."""
    return {
        "deleted": True,
        "version": label,
        "version_record_id": version_record_id,
        "removed_tags": list(removed_tags),
        "moved_tags": [
            {"name": m.get("name"), "to_version": m.get("toVersionLabel")} for m in moved_tags
        ],
        "unpublished": unpublished,
        "unfrozen": unfrozen,
    }
