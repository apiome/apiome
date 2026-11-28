"""Human output of ``apiome pact retention show|set|preview`` — PFX-8.14 (#7311).

The rules are printed as the sentences the Contracts **Settings → Clean-up** tab shows, so the CLI
and the screen read the same. ``table`` prints plain lines and a table of what would go;
``markdown`` prints a list and a GitHub table (for a job summary); ``json`` is handled by the
command (the server's document as it is).
"""

from __future__ import annotations

from typing import Any, Mapping

from apiome_cli.pact_broker_output import table

__all__ = ["policy_lines", "preview_lines", "rule_sentences"]

#: Deletions listed per pacticipant in the preview (the server lists at most 100; counts are complete).
_LISTED = 20


def _plural(count: int, word: str) -> str:
    """``1 version`` / ``5 versions``."""
    return f"{count:,} {word}" + ("" if count == 1 else "s")


def rule_sentences(policy: Mapping[str, Any]) -> list[str]:
    """The keep rules as sentences, deployed / released first (it is always on).

    Args:
        policy: A policy or rules document (``keep_*`` fields).

    Returns:
        One sentence per rule in force.
    """
    sentences = ["Every version deployed or released anywhere (always)"]
    main = policy.get("keep_main_branch_latest")
    if main:
        sentences.append(f"The latest {_plural(int(main), 'version')} on each pacticipant's main branch")
    other = policy.get("keep_other_branch_latest")
    if other:
        days = policy.get("keep_other_branch_days")
        sentence = f"The latest {_plural(int(other), 'version')} on every other branch"
        sentences.append(sentence + (f", for {_plural(int(days), 'day')}" if days else ""))
    tags = [str(tag) for tag in policy.get("keep_tags") or []]
    if tags:
        sentences.append("Anything tagged " + ", ".join(tags))
    return sentences


def _bullet(fmt: str) -> str:
    """The list marker for ``fmt``."""
    return "- " if fmt == "markdown" else "  "


def policy_lines(policy: Mapping[str, Any], fmt: str, *, saved: bool = False) -> list[str]:
    """``show`` / ``set``: what is kept, whether clean-up runs, the restore window, the last run.

    Args:
        policy: The ``GET …/pact-retention/policy`` document.
        fmt: ``table`` or ``markdown``.
        saved: Lead with "Clean-up rules saved." (``set``).

    Returns:
        The lines to print.
    """
    lines = ["Clean-up rules saved."] if saved else []
    if not policy.get("configured") and not saved:
        lines.append("No clean-up rules saved yet; these are the defaults.")
    lines.append("What to keep (everything else is removed by the nightly clean-up):")
    lines += [_bullet(fmt) + sentence for sentence in rule_sentences(policy)]
    if policy.get("nightly_enabled"):
        upcoming = policy.get("next_run_at")
        lines.append("Clean-up runs nightly" + (f"; next run {upcoming}." if upcoming else "."))
    else:
        lines.append("Clean-up is off: nothing is removed. Turn it on with: apiome pact retention set --nightly")
    lines.append(f"Deleted items stay restorable for {_plural(int(policy.get('restore_window_days') or 0), 'day')}.")
    last = policy.get("last_run") or {}
    if last.get("error"):
        lines.append(f"Last run {last.get('at')}: removed nothing — {last['error']}")
    elif last.get("at"):
        lines.append(f"Last run {last.get('at')}: removed {_plural(int(last.get('deleted') or 0), 'version')}.")
    if not policy.get("can_edit"):
        lines.append("You can read these rules; changing them needs the Contracts admin permission (pacts:delete).")
    return lines


def preview_lines(preview: Mapping[str, Any], fmt: str) -> list[str]:
    """``preview``: how much would go if the clean-up ran now, and the list.

    Args:
        preview: The ``POST …/pact-retention/policy/preview`` document.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines to print.
    """
    plan = preview.get("plan") or {}
    deleted, evaluated = int(plan.get("deleted") or 0), int(plan.get("evaluated") or 0)
    lines = []
    if preview.get("draft"):
        lines.append("Previewing rules that are not saved.")
    if not preview.get("nightly_enabled"):
        lines.append("Nothing is removed while clean-up is off. If it were on, it would remove:")
    lines.append(
        f"If it ran now: {deleted:,} of {_plural(evaluated, 'version')} would go, with "
        f"{_plural(int(plan.get('pacts') or 0), 'pact')} and {_plural(int(plan.get('results') or 0), 'result')}."
    )
    remaining = int(plan.get("remaining") or 0)
    if remaining:
        lines.append(f"{remaining:,} more are past one run's cap and would go on a later night.")
    rows = []
    for row in plan.get("pacticipants") or []:
        listed = row.get("deletions") or []
        for deletion in listed[:_LISTED]:
            rows.append(
                (
                    row.get("name"),
                    deletion.get("number"),
                    ", ".join(str(b) for b in deletion.get("branches") or []),
                    deletion.get("pacts", 0),
                    deletion.get("results", 0),
                    deletion.get("created_at"),
                )
            )
        more = int(row.get("deleted") or 0) - min(len(listed), _LISTED)
        if more > 0:
            rows.append((row.get("name"), f"… and {more:,} more", "", "", "", ""))
    if rows:
        lines += table(("PACTICIPANT", "VERSION", "BRANCHES", "PACTS", "RESULTS", "RECORDED"), rows, fmt)
    else:
        lines.append("Nothing would go.")
    return lines
