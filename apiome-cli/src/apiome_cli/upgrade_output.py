"""Human output for ``apiome upgrade`` (COA-2.6, #7049).

Renders the plan the REST ``…/openapi-upgrade/{tenant}/plan`` route returns: a headline, a
count per rule, and (unless ``--summary``) every change with its pointer. Pure: takes the
response mappings, returns lines.
"""

from __future__ import annotations

from typing import Any


def _family_name(family: str) -> str:
    """``Swagger 2.0`` for 2.0, ``OpenAPI 3.x`` otherwise."""
    return "Swagger 2.0" if family == "2.0" else f"OpenAPI {family}"


def format_upgrade_plan(
    plan: dict[str, Any], *, summary_only: bool = False
) -> list[str]:
    """Lines describing an upgrade plan.

    Args:
        plan: The plan response (``source_version``, ``target_version``, ``hops``, ``rules``,
            ``changes``, ``change_count``, ``review_count``, ``already_current``).
        summary_only: Print the per-rule counts but not each change.

    Returns:
        Output lines, without trailing newlines.
    """
    source = plan.get("source_version") or "?"
    family = str(plan.get("source_family") or "")
    target = plan.get("target_version") or plan.get("target") or "?"
    if plan.get("already_current"):
        return [
            f"{_family_name(family)} ({source}) is already at {plan.get('target')}; nothing to upgrade."
        ]
    changes = plan.get("changes") or []
    review = int(plan.get("review_count") or 0)
    hops = plan.get("hops") or []
    headline = (
        f"Upgrade {_family_name(family)} ({source}) → OpenAPI {target}: "
        f"{plan.get('change_count', len(changes))} change(s), {review} to review, "
        f"{len(hops)} hop(s) ({', '.join(hops)})"
    )
    lines = [
        headline,
        "",
        "Changes by rule:",
    ]
    rules = plan.get("rules") or []
    width = max((len(str(row.get("rule", ""))) for row in rules), default=0)
    for row in rules:
        lines.append(
            f"  {str(row.get('rule', '')).ljust(width)}  {int(row.get('count', 0)):>4}  {row.get('title', '')}"
        )
    if not summary_only and changes:
        lines += ["", "Every change:"]
        for change in changes:
            mark = "  [review]" if change.get("review") else ""
            pointer = change.get("pointer") or "/"
            lines.append(
                f"  {change.get('hop')}  {change.get('rule')}  {pointer}{mark}"
            )
            lines.append(f"      {change.get('summary')}")
    return lines


def format_upgrade_applied(result: dict[str, Any]) -> list[str]:
    """Lines confirming an applied upgrade (the ``…/apply`` response)."""
    created = (
        f"Created version {result.get('version_label')} (OpenAPI {result.get('target_version')}, "
        f"{result.get('change_count')} change(s)) from version {result.get('source_version_record_id')}."
    )
    return [created, f"Version id: {result.get('version_record_id')}"]
