"""Plan summaries and outcomes for ``apiome lint --fix`` (GVM-3.3, #5871).

Pure helpers over the GVM-3.2 lint-fix plan (``GET …/lint/fixes``) and apply response
(``POST …/lint/fixes/apply``): which fixes are ready, which remain for a person, the human
summary lines, and the exit code. Kept apart from the command so they are tested without HTTP.
"""

from __future__ import annotations

from typing import Any

from apiome_cli.exit_codes import EXIT_FIXES_REMAIN, EXIT_SUCCESS

#: Plan statuses, in the order the summary counts them.
PLAN_STATUSES = ("ready", "conflict", "breaking", "excluded")

#: Statuses of fixes that are not applied and that a person must resolve: a ``breaking`` fix is
#: never applied, and a ``conflict`` fix only becomes ready after the fix it conflicts with.
REMAINING_STATUSES = ("breaking", "conflict")

#: Renderings ``--fix-format`` accepts (the plan endpoint's ``format`` values besides ``json``).
FIX_FORMATS = ("diff", "patch", "overlay")


def plan_entries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's entries, or an empty list when the plan has none.

    Args:
        plan: A ``format=json`` lint-fix plan.

    Returns:
        Every entry dict of the plan, in plan order.
    """
    entries = plan.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def ready_fix_ids(plan: dict[str, Any]) -> list[str]:
    """The ids of the plan's ``ready`` fixes, in the order they are applied.

    Args:
        plan: A ``format=json`` lint-fix plan.

    Returns:
        ``appliedOrder`` when the plan carries it, else the ready entries' ids in plan order.
    """
    order = plan.get("appliedOrder")
    if isinstance(order, list):
        return [str(fix_id) for fix_id in order]
    return [str(e.get("fixId")) for e in plan_entries(plan) if e.get("status") == "ready"]


def remaining_entries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The entries an apply leaves for a person (``breaking`` and ``conflict``).

    Args:
        plan: A ``format=json`` lint-fix plan.

    Returns:
        The breaking and conflicting entries, in plan order.
    """
    return [e for e in plan_entries(plan) if e.get("status") in REMAINING_STATUSES]


def status_counts(plan: dict[str, Any]) -> dict[str, int]:
    """How many entries the plan has per status.

    Args:
        plan: A ``format=json`` lint-fix plan.

    Returns:
        A count for each of :data:`PLAN_STATUSES` (zero when absent).
    """
    counts = {status: 0 for status in PLAN_STATUSES}
    for entry in plan_entries(plan):
        status = str(entry.get("status"))
        if status in counts:
            counts[status] += 1
    return counts


def fix_exit_code(plan: dict[str, Any], *, dry_run: bool) -> int:
    """The exit code of ``apiome lint --fix`` for ``plan``.

    Args:
        plan: The plan the run was based on.
        dry_run: Whether nothing was applied (``--dry-run``), which never exits 3.

    Returns:
        :data:`EXIT_FIXES_REMAIN` when breaking or conflicting fixes remain (and this is not a
        dry run), else :data:`EXIT_SUCCESS`.
    """
    if not dry_run and remaining_entries(plan):
        return EXIT_FIXES_REMAIN
    return EXIT_SUCCESS


def _entry_line(entry: dict[str, Any]) -> str:
    """One indented line naming an entry: status, rule, location, and why it is not ready."""
    status = str(entry.get("status") or "")
    line = f"  {status:<9} {entry.get('ruleId')}  {entry.get('path') or entry.get('pointer')}"
    if status == "excluded" and entry.get("reason"):
        line += f"  ({entry['reason']})"
    elif status == "conflict" and entry.get("conflictsWith"):
        line += f"  (conflicts with {entry['conflictsWith']})"
    elif status == "breaking":
        line += "  (the change is breaking; never applied)"
    return line


def format_fix_plan(plan: dict[str, Any]) -> list[str]:
    """Human summary of a plan: the counts, then one line per entry that is not excluded.

    Excluded entries are only counted: they were not selected, by the flags or the style guide.

    Args:
        plan: A ``format=json`` lint-fix plan.

    Returns:
        The lines to print, without trailing newlines.
    """
    counts = status_counts(plan)
    if not plan_entries(plan):
        return ["Nothing to fix: no finding has a fix."]
    lines = ["Fix plan: " + ", ".join(f"{counts[s]} {s}" for s in PLAN_STATUSES)]
    lines.extend(_entry_line(e) for e in plan_entries(plan) if e.get("status") != "excluded")
    if counts["excluded"]:
        lines.append(
            f"  {counts['excluded']} excluded (not selected): name a rule with --only, or "
            "add --allow-renames for rename fixes."
        )
    return lines


def format_fix_applied(result: dict[str, Any]) -> list[str]:
    """Human lines for an apply response: the new revision, its score, anything skipped.

    Args:
        result: The ``POST …/lint/fixes/apply`` response.

    Returns:
        The lines to print, without trailing newlines.
    """
    applied = result.get("appliedFixIds") or []
    lines = [
        f"Applied {len(applied)} fix{'es' if len(applied) != 1 else ''} as new revision "
        f"{result.get('versionLabel')} ({result.get('versionRecordId')})."
    ]
    if result.get("grade") is not None or result.get("score") is not None:
        lines.append(f"  Score {result.get('score')}  grade {result.get('grade')}")
    for skipped in result.get("skipped") or []:
        lines.append(
            f"  skipped {skipped.get('ruleId')} {skipped.get('fixId')} ({skipped.get('status')})"
        )
    return lines


def format_remaining(plan: dict[str, Any]) -> list[str]:
    """The closing lines when fixes remain for a person after an apply.

    Args:
        plan: The plan the apply was based on.

    Returns:
        No lines when nothing remains, else a count with what to do next.
    """
    remaining = remaining_entries(plan)
    if not remaining:
        return []
    counts = status_counts(plan)
    lines = [f"{len(remaining)} fix{'es' if len(remaining) != 1 else ''} need a person:"]
    if counts["breaking"]:
        lines.append(f"  {counts['breaking']} breaking: never applied; change the API by hand.")
    if counts["conflict"]:
        lines.append(f"  {counts['conflict']} conflict: run --fix again on the new revision.")
    return lines
