"""The rules of ``apiome versions unpublish`` (CLI 4.6, #3213).

Unpublishing returns a published revision to draft — ``POST /v1/versions/{tenant}/{project}/
{id}/unpublish``. The command asks the server for a dry run first (``{"dryRun": true}``), so the
preview shows exactly what the server will do: which version tags move back to the previous
published version, which stay, and how many webhook subscribers are notified. These functions
hold the command's decisions without HTTP:

* :func:`parse_positionals` — ``unpublish <project> <version>``, or the older
  ``unpublish <version> --project <project>``;
* :func:`check_reason` — ``--reason`` is required unless ``--silent``;
* :func:`render_plan` / :func:`render_result` — the human preview and summary.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

#: The public spec endpoints an unpublished version disappears from.
SPEC_ENDPOINTS = "/v1/schema, /v1/swagger, /v1/arazzo, /v1/json"

#: Why the server leaves a tag on the unpublished version (``tagsKept[].reason``).
_KEPT_REASONS = {
    "keep-tags": "--keep-tags",
    "immutable": "immutable",
    "protected": "protected; only a tenant administrator can move it",
    "no-published-version": "no other published version to move it to",
}


class UnpublishError(ValueError):
    """An argument the command refuses, with a message for stderr (exit 2)."""


def parse_positionals(
    first: str, second: Optional[str], project_option: Optional[str]
) -> tuple[str, str]:
    """Return ``(project_ref, version_ref)`` from the command's arguments.

    Args:
        first: The first positional — the project, or the version when ``second`` is absent.
        second: The second positional — the version.
        project_option: ``--project``, kept so ``unpublish <version> --project <p>`` still works.

    Returns:
        The project and version references.

    Raises:
        UnpublishError: When no project is given, or ``--project`` contradicts the positional one.
    """
    if second is not None:
        if project_option is not None and project_option != first:
            raise UnpublishError(
                f"--project {project_option!r} contradicts the project argument {first!r}; pass one."
            )
        return first, second
    if project_option is None:
        raise UnpublishError("Name the project: apiome versions unpublish <project> <version>.")
    return project_option, first


def check_reason(reason: Optional[str], *, silent: bool) -> Optional[str]:
    """``--reason`` stripped; required unless ``--silent``.

    Raises:
        UnpublishError: When the reason is missing or blank and ``--silent`` was not passed.
    """
    text = (reason or "").strip() or None
    if text is None and not silent:
        raise UnpublishError(
            "--reason is required: it is recorded for audit and sent to webhook subscribers."
        )
    return text


def _kept_reason(code: Any) -> str:
    return _KEPT_REASONS.get(str(code), str(code))


def render_plan(plan: Mapping[str, Any], *, reason: Optional[str]) -> str:
    """The preview printed before the typed confirmation, from the server's dry run.

    Args:
        plan: The dry-run response (the version plus ``tagsMoved``, ``tagsKept``, ``notify``,
            ``webhookSubscribers``).
        reason: The ``--reason`` that will be recorded.

    Returns:
        The indented "Unpublishing will:" block.
    """
    label = plan.get("version_id")
    previous = plan.get("previousPublishedVersionLabel")
    lines = ["Unpublishing will:", f"  • Hide {label} from {SPEC_ENDPOINTS}"]
    for move in plan.get("tagsMoved") or []:
        lines.append(
            f"  • Move the '{move.get('name')}' tag back to {move.get('toVersionLabel') or previous} "
            "(next-most-recent published)"
        )
    for kept in plan.get("tagsKept") or []:
        lines.append(f"  • Leave the '{kept.get('name')}' tag on {label} ({_kept_reason(kept.get('reason'))})")
    if plan.get("notify", True):
        count = plan.get("webhookSubscribers")
        active = "count unavailable" if count is None else f"{count} active"
        lines.append(f"  • Notify webhook subscribers ({active})")
    else:
        lines.append("  • Not notify webhook subscribers (--silent)")
    if reason:
        lines.append(f"  • Record the reason: {reason}")
    if not plan.get("publishedVersionsRemaining"):
        lines.append("  • Leave the project with no published version")
    return "\n".join(lines)


def render_result(result: Mapping[str, Any]) -> str:
    """The summary printed after a successful unpublish."""
    label = result.get("version_id")
    lines = [f"✔ Unpublished {label}."]
    moved = result.get("tagsMoved") or []
    if moved:
        names = ", ".join(f"{m.get('name')} → {m.get('toVersionLabel')}" for m in moved)
        lines.append(f"  Tags moved: {names}")
    if not result.get("notify", True):
        lines.append("  Webhook subscribers were not notified (--silent).")
    return "\n".join(lines)
