"""Suggested lint fixes for a spec file in a pull request (GVM-3.4, #5872).

``apiome lint suggest <file>`` plans the file's deterministic lint fixes
(``POST /v1/lint/fixes/plan``, the GVM-3.2 file-mode plan) and turns the plan into what a CI
comment shows. Each ready fix's operations are applied **alone** to the file's original text with
the GVM-3.3 round-trip rewriter (:func:`apiome_cli.lint_fix_file.rewrite_document_text`), so every
hunk is a hunk of the real file — real paths and real line numbers, not the reconstructed JSON a
stored revision's plan diffs:

* per rule, the number of ready fixes, the fix class and the first hunk as a ``diff`` snippet; and
* for each fix whose change is **one** region of the file, the line range it replaces and the
  replacement lines — what diff-action turns into a GitHub ``suggestion`` block when the range
  lies inside the pull request's diff.

Everything here is pure (no HTTP), so it is tested without a server. Nothing is ever written to the
spec file.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from apiome_cli.lint_fix_file import FixApplyError, rewrite_document_text
from apiome_cli.lint_fix_output import plan_entries, status_counts

#: Lines a snippet keeps before it is cut (the full change is the downloadable patch).
MAX_SNIPPET_LINES = 20
#: Rules the Markdown section lists; the rest are counted on one closing line.
MAX_SUGGESTED_RULES = 10
#: Context lines around a snippet's change.
CONTEXT_LINES = 2
#: Renderings ``apiome lint suggest --format`` accepts.
SUGGEST_FORMATS = ("markdown", "json", "patch", "overlay", "diff")


def _entry_ops(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The entry's RFC 6902 operations, or none when the plan carries none."""
    ops = entry.get("ops")
    return [op for op in ops if isinstance(op, dict)] if isinstance(ops, list) else []


def first_hunk(before: str, after: str) -> str:
    """The first hunk of the unified diff between two texts, capped in length.

    Args:
        before: The original text.
        after: The text with one fix applied.

    Returns:
        The hunk with its ``@@`` header, or an empty string when nothing changes.
    """
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            n=CONTEXT_LINES,
            lineterm="",
        )
    )
    hunk: list[str] = []
    for line in lines[2:]:  # skip the ---/+++ file headers
        if line.startswith("@@") and hunk:
            break
        hunk.append(line)
    if len(hunk) > MAX_SNIPPET_LINES:
        hunk = hunk[:MAX_SNIPPET_LINES] + ["…"]
    return "\n".join(hunk)


def single_region(before: str, after: str) -> dict[str, Any] | None:
    """The one region of ``before`` that ``after`` changes, as a line-range replacement.

    A GitHub suggestion replaces whole lines of the file, so a pure insertion is anchored to the
    line before it (or after it, at the top of the file) and that line is repeated in the
    replacement.

    Args:
        before: The original text.
        after: The text with one fix applied.

    Returns:
        ``{"startLine", "endLine", "replacement"}`` (1-based, inclusive; ``replacement`` is the
        new text of those lines, newline-terminated) when exactly one region changes; ``None`` when
        nothing changes, several regions do, or the file is empty.
    """
    old = before.splitlines()
    new = after.splitlines()
    if not old:
        return None
    changed = [
        op
        for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if len(changed) != 1:
        return None
    _tag, i1, i2, j1, j2 = changed[0]
    replacement = new[j1:j2]
    if i1 == i2:  # an insertion: anchor it to a neighbouring line
        if i1 > 0:
            i1 -= 1
            replacement = [old[i1], *replacement]
        else:
            i2 = 1
            replacement = [*replacement, old[0]]
    return {
        "startLine": i1 + 1,
        "endLine": i2,
        "replacement": "".join(f"{line}\n" for line in replacement),
    }


def build_suggestions(text: str, plan: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Condense a file-mode plan into the suggestions a CI comment shows.

    Only ``ready`` fixes are suggested; breaking and conflicting ones are counted so a reader knows
    what is left for a person. A fix the rewriter cannot apply to the text is counted but has no
    snippet or region.

    Args:
        text: The spec file's original text.
        plan: The ``format=json`` plan of that text.
        path: The file's repository-relative path, as the pull request names it.

    Returns:
        ``{"path", "ready", "breaking", "conflict", "rules": [{"ruleId", "fixClass", "count",
        "snippet"}], "suggestions": [{"fixId", "ruleId", "fixClass", "message", "startLine",
        "endLine", "replacement"}]}`` — rules in plan order; ``suggestions`` holds the ready fixes
        whose change is a single region of the file.
    """
    counts = status_counts(plan)
    rules: dict[str, dict[str, Any]] = {}
    suggestions: list[dict[str, Any]] = []
    for entry in plan_entries(plan):
        if entry.get("status") != "ready":
            continue
        rule_id = str(entry.get("ruleId"))
        try:
            after = rewrite_document_text(text, _entry_ops(entry))
        except FixApplyError:
            after = text
        rule = rules.get(rule_id)
        if rule is None:
            rule = rules[rule_id] = {
                "ruleId": rule_id,
                "fixClass": entry.get("fixClass"),
                "count": 0,
                "snippet": first_hunk(text, after),
            }
        rule["count"] += 1
        region = single_region(text, after)
        if region is not None:
            suggestions.append(
                {
                    "fixId": entry.get("fixId"),
                    "ruleId": rule_id,
                    "fixClass": entry.get("fixClass"),
                    "message": entry.get("message"),
                    **region,
                }
            )
    return {
        "path": path,
        "ready": counts["ready"],
        "breaking": counts["breaking"],
        "conflict": counts["conflict"],
        "rules": list(rules.values()),
        "suggestions": suggestions,
    }


def fence_for(text: str) -> str:
    """A backtick fence longer than any backtick run inside ``text`` (never shorter than three)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def format_suggestions_markdown(
    summary: dict[str, Any],
    *,
    heading: str = "### Suggested fixes",
    artifact_url: str | None = None,
) -> str:
    """The *Suggested fixes* Markdown section for a pull-request comment.

    Laid out like the server's section in ``apiome lint gate --format markdown`` and
    ``apiome checks run --format md``: a count, then per rule the count, the fix class and a
    fenced snippet of the first hunk.

    Args:
        summary: :func:`build_suggestions` output.
        heading: The section's heading line.
        artifact_url: Where the full patch and overlay can be downloaded (a workflow run's
            artefacts), or ``None``.

    Returns:
        The section, newline-terminated. A plan with nothing to suggest says so in one line.
    """
    ready = int(summary.get("ready") or 0)
    breaking = int(summary.get("breaking") or 0)
    conflict = int(summary.get("conflict") or 0)
    lines = [heading, ""]
    if not ready and not breaking and not conflict:
        lines.append(f"No mechanical lint fixes for `{summary.get('path')}`.")
        return "\n".join(lines) + "\n"
    if ready:
        lines.append(
            f"{ready} mechanical fix{'es' if ready != 1 else ''} ready for "
            f"`{summary.get('path')}`; nothing is pushed to the branch."
        )
    else:
        lines.append(f"No fix is ready to apply to `{summary.get('path')}`.")
    rules = list(summary.get("rules") or [])
    for rule in rules[:MAX_SUGGESTED_RULES]:
        count = int(rule.get("count") or 0)
        lines.extend(
            ["", f"- `{rule.get('ruleId')}` — {count} fix{'es' if count != 1 else ''} ({rule.get('fixClass')})"]
        )
        snippet = str(rule.get("snippet") or "")
        if snippet:
            fence = fence_for(snippet)
            lines.extend(["", f"{fence}diff", snippet, fence])
    if len(rules) > MAX_SUGGESTED_RULES:
        extra = len(rules) - MAX_SUGGESTED_RULES
        lines.extend(["", f"- … and {extra} more rule{'s' if extra != 1 else ''}."])
    if breaking or conflict:
        lines.extend(
            [
                "",
                f"{breaking} breaking and {conflict} conflicting fixes need a person "
                "(a breaking fix is never applied).",
            ]
        )
    if ready and artifact_url:
        lines.extend(["", f"Download the full patch and overlay: [workflow artefacts]({artifact_url})."])
    return "\n".join(lines) + "\n"
