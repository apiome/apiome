"""How ``apiome migrations list`` / ``counts`` / ``show`` present migration plans (CLI 11.1–11.3).

A migration plan holds the rules that move data from one version of a project to another, one
plan per ``(from version, to version)`` pair. ``GET /v1/migration-plans/{tenant}/projects/{project}``
returns each plan with its version **ids** and every rule; these functions turn that into rows that
name the versions by label, filter by version, and render the table — without HTTP. ``show`` renders one plan from
``GET /v1/migration-plans/{tenant}/{plan_id}``, which also names the project and the versions.

The server records no status, breaking flag, author or notes for a plan, so none is shown.
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


def count_project_plans(project: Mapping[str, Any], plans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One ``migrations counts`` row: how many plans, classes and rules ``project`` has (CLI 11.2, #3261).

    Args:
        project: The project record (``id``, ``slug``, ``name``); ``slug`` names the row, falling back
            to ``name`` and then ``id``.
        plans: The project's raw plans (``GET /v1/migration-plans/{tenant}/projects/{project}``).

    Returns:
        ``{project_id, project, plans, classes, rules}`` — ``classes`` counts the distinct class names
        mapped across every plan, ``rules`` every rule.
    """
    summaries = [summarize_plan(plan, {}) for plan in plans if isinstance(plan, Mapping)]
    classes = {name for summary in summaries for name in summary["classes"]}
    project_id = str(project.get("id") or "")
    return {
        "project_id": project_id,
        "project": str(project.get("slug") or project.get("name") or project_id),
        "plans": len(summaries),
        "classes": len(classes),
        "rules": sum(summary["rule_count"] for summary in summaries),
    }


def sort_counts(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Projects with the most plans first; ties by project name, so output is stable."""
    return sorted(rows, key=lambda row: (-int(row.get("plans") or 0), str(row.get("project") or "")))


def render_plan_counts(rows: Sequence[Mapping[str, Any]]) -> str:
    """The ``migrations counts`` table: PROJECT, PLANS, CLASSES, RULES.

    Args:
        rows: ``count_project_plans`` rows, already sorted.

    Returns:
        The table, or ``"No projects."`` when the tenant has none.
    """
    if not rows:
        return "No projects."
    header = ("PROJECT", "PLANS", "CLASSES", "RULES")
    cells = [
        (str(r.get("project") or ""), str(r.get("plans") or 0), str(r.get("classes") or 0), str(r.get("rules") or 0))
        for r in rows
    ]
    widths = [max(len(header[i]), *(len(c[i]) for c in cells)) for i in range(len(header))]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in (header, *cells))


#: ``migrations show --scope`` values: ``all`` prints the summary and the mappings, ``mappings``
#: only the mappings. (Plans store no notes, so there is no ``notes`` scope.)
SHOW_SCOPES = ("all", "mappings")


def _rule_side(class_name: str, names: Sequence[Any]) -> str:
    """``Charge.status`` (or ``Charge.a + Charge.b``) for the property names one side of a rule lists."""
    return " + ".join(f"{class_name}.{name}" if class_name else str(name) for name in names)


def mapping_lines(rules: Sequence[Mapping[str, Any]]) -> list[str]:
    """One line per rule: ``Charge.legacy_status → Charge.status  (simple · rename)``.

    Args:
        rules: The plan's rules (``{class_name, source_property, rule: {name, inputProperties,
            outputProperties, ruleType, ruleContent}}``), already in display order.

    Returns:
        The lines, arrows and rule types aligned. The source is the rule's input properties (the stored
        ``source_property`` when it lists none); a rule with no output reads ``(removed)``. The
        parenthesis names the rule type (``simple`` when unset) and the rule's name, if it has one.
    """
    rows: list[tuple[str, str, str]] = []
    for entry in rules:
        if not isinstance(entry, Mapping):
            continue
        class_name = str(entry.get("class_name") or "")
        rule = entry.get("rule") if isinstance(entry.get("rule"), Mapping) else {}
        inputs = [name for name in rule.get("inputProperties") or [] if name] or [entry.get("source_property") or "?"]
        outputs = [name for name in rule.get("outputProperties") or [] if name]
        kind = " · ".join(str(part) for part in (rule.get("ruleType") or "simple", rule.get("name")) if part)
        rows.append((_rule_side(class_name, inputs), _rule_side(class_name, outputs) or "(removed)", kind))
    source_width = max((len(source) for source, _, _ in rows), default=0)
    target_width = max((len(target) for _, target, _ in rows), default=0)
    return [f"{source.ljust(source_width)} → {target.ljust(target_width)}  ({kind})" for source, target, kind in rows]


def _version_label(plan: Mapping[str, Any], side: str) -> str:
    """The ``from`` / ``to`` version label of ``plan``, or its revision id when the version is gone."""
    return str(plan.get(f"{side}_version") or plan.get(f"{side}_version_id") or "—")


def render_plan_show(plan: Mapping[str, Any], *, scope: str = "all") -> str:
    """The ``migrations show`` record (CLI 11.3, #3262).

    Args:
        plan: The plan body (``GET /v1/migration-plans/{tenant}/{plan_id}``).
        scope: One of :data:`SHOW_SCOPES` — ``all`` (summary and mappings) or ``mappings``.

    Returns:
        The rendered plan: a title, a rule, the ``Project`` / ``From`` / ``To`` / ``Rules`` /
        ``Created`` / ``Updated`` summary, then the indented ``Mappings:`` section (``(none)`` for
        a plan without rules).

    Raises:
        ValueError: ``scope`` is not one of :data:`SHOW_SCOPES`.
    """
    if scope not in SHOW_SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {', '.join(SHOW_SCOPES)}")
    rules = [rule for rule in plan.get("rules") or [] if isinstance(rule, Mapping)]
    mappings = ["Mappings:", *(f"  {line}" for line in mapping_lines(rules) or ["(none)"])]
    if scope == "mappings":
        return "\n".join(mappings)
    title = f"Migration plan {plan.get('id') or ''}"
    classes = {str(rule.get("class_name")) for rule in rules if rule.get("class_name")}
    rows = [
        ("Project:", str(plan.get("project_slug") or plan.get("project_name") or plan.get("project_id") or "—")),
        ("From:", _version_label(plan, "from")),
        ("To:", _version_label(plan, "to")),
        ("Rules:", f"{len(rules)} across {len(classes)} {'class' if len(classes) == 1 else 'classes'}"),
        ("Created:", format_when(plan.get("created_at"), with_time=True) or "—"),
        ("Updated:", format_when(plan.get("updated_at"), with_time=True) or "—"),
    ]
    width = max(len(label) for label, _ in rows)
    summary = [f"{label.ljust(width)}  {value}" for label, value in rows]
    return "\n".join([title, "─" * len(title), *summary, "", *mappings])
