"""Suggested lint fixes for CI summaries — GVM-3.4 (#5872).

A reviewer reading a pull request should see, without opening a terminal, which lint failures are
mechanical. This module condenses a GVM-3.2 :class:`~app.lint_fix_plan.FixPlan` into what a CI
summary shows — per rule the number of ``ready`` fixes, the fix class and the first hunk of one
fix — and renders that as the *Suggested fixes* Markdown section of:

* the lint gate's ``format=markdown`` artifact (:func:`app.lint_gate_emit.to_gate_markdown`), and
* the API change check suite's summary (:func:`app.api_check_suite.render_summary`), which is also
  the summary of the GNC-2.2 provider check run.

Snippets are hunks of the same indented-JSON rendering the plan's ``format=diff`` uses, so they
read like the full diff a reviewer downloads. Everything here is a pure function of the plan: no
clock, no I/O, so a replayed evaluation renders byte-identical text.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Mapping, Optional

from .lint_fix import FixError, apply_fix_ops
from .lint_fix_plan import STATUS_BREAKING, STATUS_CONFLICT, STATUS_READY, FixPlan

__all__ = [
    "MAX_SNIPPET_LINES",
    "MAX_SUGGESTED_RULES",
    "fix_suggestions_markdown",
    "summarize_fix_plan",
]

#: Lines a snippet keeps before it is cut (the full change is the downloadable patch).
MAX_SNIPPET_LINES = 20
#: Rules a summary lists; the rest are counted on one closing line.
MAX_SUGGESTED_RULES = 10
#: Context lines around a snippet's change.
_CONTEXT_LINES = 2


def _pretty_lines(document: Any) -> List[str]:
    """The document as indented JSON lines — the plan's ``format=diff`` rendering."""
    return json.dumps(document, indent=2, ensure_ascii=False).splitlines()


def first_hunk(before: Any, after: Any) -> str:
    """The first hunk of the unified diff between two documents, capped at the snippet length.

    Args:
        before: The original document.
        after: The document with one fix applied.

    Returns:
        The hunk (its ``@@`` header included), or an empty string when nothing changes.
    """
    lines = list(
        difflib.unified_diff(
            _pretty_lines(before), _pretty_lines(after), n=_CONTEXT_LINES, lineterm=""
        )
    )
    hunk: List[str] = []
    for line in lines[2:]:  # skip the ---/+++ file headers
        if line.startswith("@@") and hunk:
            break
        hunk.append(line)
    if len(hunk) > MAX_SNIPPET_LINES:
        hunk = hunk[:MAX_SNIPPET_LINES] + ["…"]
    return "\n".join(hunk)


def summarize_fix_plan(plan: FixPlan) -> Dict[str, Any]:
    """Condense a plan into what a CI summary shows.

    Only ``ready`` fixes are suggested — a breaking fix is never applied and a conflicting one only
    becomes ready after the fix it conflicts with — but both are counted so a reader knows what is
    left for a person.

    Args:
        plan: A lint-fix plan.

    Returns:
        ``{"ready", "breaking", "conflict", "rules": [{"ruleId", "fixClass", "count",
        "snippet"}]}``; ``rules`` lists the rules with ready fixes in plan order, each with the
        first hunk of its first ready fix.
    """
    counts = plan.counts()
    rules: Dict[str, Dict[str, Any]] = {}
    for entry in plan.entries:
        if entry.status != STATUS_READY:
            continue
        known = rules.get(entry.rule_id)
        if known is not None:
            known["count"] += 1
            continue
        try:
            snippet = first_hunk(plan.original_document, apply_fix_ops(plan.original_document, entry.ops))
        except FixError:
            snippet = ""
        rules[entry.rule_id] = {
            "ruleId": entry.rule_id,
            "fixClass": entry.fix_class,
            "count": 1,
            "snippet": snippet,
        }
    return {
        "ready": counts[STATUS_READY],
        "breaking": counts[STATUS_BREAKING],
        "conflict": counts[STATUS_CONFLICT],
        "rules": list(rules.values()),
    }


def _fence(text: str) -> str:
    """A backtick fence longer than any backtick run inside ``text`` (never shorter than three)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def fix_suggestions_markdown(
    summary: Optional[Mapping[str, Any]],
    *,
    heading: str,
    links: Optional[Mapping[str, str]] = None,
) -> List[str]:
    """The *Suggested fixes* section of a CI summary.

    Args:
        summary: :func:`summarize_fix_plan` output, or ``None`` when no plan was made.
        heading: The section's heading line (``## Suggested fixes`` or ``**Suggested fixes**``),
            matching the document it is embedded in.
        links: Where to download the full change, by label (e.g. ``{"patch": "/v1/…?format=patch"}``).

    Returns:
        The section's lines (no trailing blank line); empty when ``summary`` is ``None`` or the plan
        has nothing ready or left over.
    """
    if not summary:
        return []
    ready = int(summary.get("ready") or 0)
    remaining = int(summary.get("breaking") or 0) + int(summary.get("conflict") or 0)
    if not ready and not remaining:
        return []
    lines = [heading, ""]
    if ready:
        lines.append(
            f"{ready} mechanical fix{'es' if ready != 1 else ''} ready to apply "
            "(`apiome lint --fix`); nothing is written until someone applies them."
        )
    else:
        lines.append("No fix is ready to apply.")
    rules = list(summary.get("rules") or [])
    for rule in rules[:MAX_SUGGESTED_RULES]:
        count = int(rule.get("count") or 0)
        lines.append("")
        lines.append(
            f"- `{rule.get('ruleId')}` — {count} fix{'es' if count != 1 else ''} "
            f"({rule.get('fixClass')})"
        )
        snippet = str(rule.get("snippet") or "")
        if snippet:
            fence = _fence(snippet)
            lines.extend(["", f"{fence}diff", snippet, fence])
    if len(rules) > MAX_SUGGESTED_RULES:
        extra = len(rules) - MAX_SUGGESTED_RULES
        lines.extend(["", f"- … and {extra} more rule{'s' if extra != 1 else ''}."])
    if remaining:
        lines.extend(
            [
                "",
                f"{summary.get('breaking') or 0} breaking and {summary.get('conflict') or 0} "
                "conflicting fixes need a person (a breaking fix is never applied).",
            ]
        )
    shown = [(label, href) for label, href in (links or {}).items() if href]
    if shown and ready:
        lines.extend(["", "Full change: " + " · ".join(f"{label} `GET {href}`" for label, href in shown)])
    return lines
