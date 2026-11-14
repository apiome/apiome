"""How ``apiome migrations list`` presents a project's migration plans (CLI 11.1, #3260).

A migration plan holds the rules that move data from one version of a project to another, one
plan per ``(from version, to version)`` pair. ``GET /v1/migration-plans/{tenant}/projects/{project}``
returns each plan with its version **ids** and every rule; these functions turn that into rows that
name the versions by label, filter by version, and render the table — without HTTP.

The server records no status, breaking flag or author for a plan, so none is shown.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from apiome_cli.tag_view import format_when


def version_labels(versions: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Map each version revision id to its label (``2.1.0``).

    Args:
        versions: The project's versions (``GET /v1/versions/{tenant}/{project}``).

    Returns:
        ``{revision id: label}``; a version without a label maps to its id.
    """
    return {str(v.get("id")): str(v.get("version_id") or v.get("id")) for v in versions if v.get("id")}


def summarize_plan(plan: Mapping[str, Any], labels: Mapping[str, str]) -> dict[str, Any]:
    """One list row for ``plan``: its ids, version labels and rule counts, without the rule bodies.

    Args:
        plan: A plan from the project list route (``id``, ``from_version_id``, ``to_version_id``,
            ``created_at``, ``updated_at``, ``rules: [{class_name, source_property, rule}]``).
        labels: ``version_labels`` of the project; an unknown id is shown as the id itself.

    Returns:
        ``{id, from_version_id, from_version, to_version_id, to_version, classes, rule_count,
        created_at, updated_at}`` — ``classes`` lists the distinct class names, in order.
    """
    from_id = str(plan.get("from_version_id") or "")
    to_id = str(plan.get("to_version_id") or "")
    rules = [rule for rule in plan.get("rules") or [] if isinstance(rule, Mapping)]
    classes = sorted({str(rule.get("class_name")) for rule in rules if rule.get("class_name")})
    return {
        "id": str(plan.get("id") or ""),
        "from_version_id": from_id,
        "from_version": labels.get(from_id, from_id),
        "to_version_id": to_id,
        "to_version": labels.get(to_id, to_id),
        "classes": classes,
        "rule_count": len(rules),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
    }


def filter_plans(
    plans: Sequence[Mapping[str, Any]],
    *,
    from_version_id: Optional[str] = None,
    to_version_id: Optional[str] = None,
) -> list[Mapping[str, Any]]:
    """The plans that start at ``from_version_id`` and/or end at ``to_version_id`` (``None`` = any).

    Args:
        plans: Plan summaries (``summarize_plan``) or raw plans — only the version ids are read.
        from_version_id: Source version revision id to keep, or ``None``.
        to_version_id: Target version revision id to keep, or ``None``.
    """
    return [
        plan
        for plan in plans
        if (from_version_id is None or str(plan.get("from_version_id")) == from_version_id)
        and (to_version_id is None or str(plan.get("to_version_id")) == to_version_id)
    ]


def sort_plans(plans: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Plans most recently updated first; ties (and plans without a date) by id, so output is stable."""
    by_id = sorted(plans, key=lambda p: str(p.get("id") or ""))
    return sorted(by_id, key=lambda p: str(p.get("updated_at") or p.get("created_at") or ""), reverse=True)


def render_plan_list(plans: Sequence[Mapping[str, Any]], *, total: Optional[int] = None) -> str:
    """The ``migrations list`` table: PLAN ID, FROM, TO, CLASSES, RULES, UPDATED.

    Args:
        plans: Plan summaries (``summarize_plan``) to show, already filtered and limited.
        total: How many plans matched, when more exist than are shown.

    Returns:
        The table, a "Showing N of M" footer when limited, or ``"No migration plans."``.
    """
    if not plans:
        return "No migration plans."
    header = ("PLAN ID", "FROM", "TO", "CLASSES", "RULES", "UPDATED")
    rows = [
        (
            str(p.get("id") or ""),
            str(p.get("from_version") or ""),
            str(p.get("to_version") or ""),
            str(len(p.get("classes") or [])),
            str(p.get("rule_count") or 0),
            format_when(p.get("updated_at") or p.get("created_at")),
        )
        for p in plans
    ]
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in (header, *rows)]
    if total is not None and total > len(plans):
        lines.append(f"Showing {len(plans)} of {total} plans; pass --all for every plan or --limit N.")
    return "\n".join(lines)
