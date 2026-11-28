"""Human output of ``apiome pact setup`` — PFX-8.20 (#7317).

The six sections are printed as the **Set up contracts** page shows them — Done, Next, To do, each
with its one-line summary — followed by what the command did, one line per thing: created, already
there, opened, written, or skipped with the reason. ``table`` prints plain lines; ``markdown`` prints
a GitHub list (for a job summary); ``json`` is handled by the command.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = [
    "STATE_LABELS",
    "action_lines",
    "section_lines",
    "setup_lines",
    "workflow_lines",
]

#: What each section state is called.
STATE_LABELS = {"done": "Done", "next": "Next", "todo": "To do"}


def _bullet(fmt: str) -> str:
    """The list marker for ``fmt``."""
    return "- " if fmt == "markdown" else "  "


def section_lines(state: Mapping[str, Any], fmt: str) -> list[str]:
    """The six sections with their state and summary.

    Args:
        state: The ``GET …/pact-setup`` document.
        fmt: ``table`` or ``markdown``.

    Returns:
        A heading line and one line per section.
    """
    sections = [
        section
        for section in state.get("sections") or []
        if isinstance(section, Mapping)
    ]
    done = sum(1 for section in sections if section.get("state") == "done")
    heading = f"Contracts set-up: {done} of {len(sections)} done"
    lines = [f"**{heading}**" if fmt == "markdown" else heading]
    for number, section in enumerate(sections, start=1):
        label = STATE_LABELS.get(str(section.get("state")), "To do")
        title, summary = (
            str(section.get("title") or section.get("id")),
            str(section.get("summary") or ""),
        )
        lines.append(
            f"{_bullet(fmt)}{number}. [{label}] {title}"
            + (f" — {summary}" if summary else "")
        )
    return lines


def action_lines(actions: Sequence[Mapping[str, Any]], fmt: str) -> list[str]:
    """What the command did, one line per thing.

    Args:
        actions: ``{kind, name, outcome, detail?}`` in the order they happened. ``outcome`` is
            ``created``, ``exists``, ``written``, ``opened``, ``would``, ``skipped`` or ``failed``.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines; empty when nothing was asked for.
    """
    words = {
        "created": "created",
        "exists": "already there",
        "written": "written",
        "opened": "opened",
        "would": "would be done (dry run)",
        "skipped": "skipped",
        "failed": "FAILED",
    }
    lines: list[str] = []
    for action in actions:
        outcome = words.get(str(action.get("outcome")), str(action.get("outcome")))
        detail = str(action.get("detail") or "")
        lines.append(
            f"{_bullet(fmt)}{action.get('kind')} {action.get('name')}: {outcome}"
            + (f" — {detail}" if detail else "")
        )
    return lines


def workflow_lines(results: Sequence[Mapping[str, Any]], fmt: str) -> list[str]:
    """The workflow of every repository no pull request was opened in, to add by hand.

    Args:
        results: The ``…/pact-setup/github/pull-requests`` results.
        fmt: ``table`` or ``markdown``.

    Returns:
        For each ``preview`` or ``skipped`` result with content: where the file goes and its text.
    """
    lines: list[str] = []
    for result in results:
        content = str(result.get("content") or "")
        if result.get("status") not in ("preview", "skipped") or not content:
            continue
        name = str(result.get("full_name") or result.get("repository_id"))
        lines.append("")
        lines.append(f"Add this to {name} as {result.get('path')}:")
        if fmt == "markdown":
            lines += ["```yaml", content.rstrip("\n"), "```"]
        else:
            lines += content.rstrip("\n").split("\n")
    return lines


def setup_lines(
    state: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    pull_requests: Sequence[Mapping[str, Any]],
    fmt: str,
) -> list[str]:
    """Everything ``apiome pact setup`` prints.

    Args:
        state: The set-up after the command's changes.
        actions: What the command did.
        pull_requests: The pull-request results, for the workflows to add by hand.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines.
    """
    lines = section_lines(state, fmt)
    done = action_lines(actions, fmt)
    if done:
        lines += [
            "",
            "**What this run did**" if fmt == "markdown" else "What this run did",
        ] + done
    return lines + workflow_lines(pull_requests, fmt)
