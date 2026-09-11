"""The words a git delivery writes — SDK-4.2 (#4496).

A delivery's commit message and pull request are what an SDK owner actually reads, so they carry
what the ticket asks for — **the spec version, the generator version, a changed-files overview and
the provenance** — in a form a reviewer can check at a glance and a machine can trace back.

Two properties are load-bearing:

**Deterministic.** Nothing here reads a clock or a run id. The same inputs render the same title
and body, which is what lets a re-run tell "the open pull request already says this" apart from
"the description needs refreshing" by comparing text — so re-running an unchanged delivery writes
nothing at all.

**Bounded.** GitHub refuses a pull request body over 65,536 characters. The changed-files table is
the only part that grows with the API, so it is the part that is shortened — the counts above it
stay exact — until the body fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .sdk_git_delivery_changes import CHANGE_ADDED, CHANGE_DELETED, CHANGE_MODIFIED

__all__ = [
    "PULL_REQUEST_BODY_MAX_CHARS",
    "PULL_REQUEST_FILE_ROWS",
    "PULL_REQUEST_MARKER",
    "DeliverySummary",
    "commit_message",
    "pull_request_body",
    "pull_request_title",
]

#: The first line of every body, so a pull request Apiome opened can be recognised by tooling
#: without parsing prose.
PULL_REQUEST_MARKER = "<!-- apiome:sdk-git-delivery v1 -->"

#: Largest body rendered. GitHub's limit is 65,536; the margin absorbs multi-byte characters
#: counted differently on either side.
PULL_REQUEST_BODY_MAX_CHARS = 60_000

#: How many changed files the body lists before summarising the rest.
PULL_REQUEST_FILE_ROWS = 100

#: Provenance keys already shown in the summary table, so the provenance table does not repeat them.
_SUMMARISED_KEYS = frozenset({"schemaVersion"})

#: Longest title rendered. GitHub accepts 256.
_TITLE_MAX_CHARS = 240


@dataclass(frozen=True)
class DeliverySummary:
    """Everything the commit message and pull request describe.

    Attributes:
        project_slug: The project the SDK was generated from.
        api_title: The API's own title, when it declares one.
        version_line: The API version the SDK was generated from.
        version_record_id: The exact revision — a version line can be re-published, a revision
            cannot.
        ecosystem: ``npm`` or ``pypi``.
        package_name: The committed package's name.
        package_version: The committed package's version.
        repository_full_name: ``owner/repo``.
        base_branch: The branch the pull request targets.
        branch_name: The delivery branch.
        target_path: The directory the SDK is committed under.
        apiome_version: The Apiome API version that generated it.
        renderer: The generator that wrote the SDK's contents.
        changes: The change overview (:meth:`app.sdk_git_delivery_changes.ChangeSet.overview`).
        provenance: The provenance embedded in the package's own metadata.
    """

    project_slug: str
    api_title: Optional[str]
    version_line: Optional[str]
    version_record_id: str
    ecosystem: str
    package_name: str
    package_version: str
    repository_full_name: str
    base_branch: str
    branch_name: str
    target_path: str
    apiome_version: Optional[str]
    renderer: Optional[str]
    changes: Mapping[str, Any]
    provenance: Mapping[str, Any]


def _code(value: Any) -> str:
    """Render a value as inline code that is safe inside a Markdown table cell.

    Args:
        value: Anything printable.

    Returns:
        The value in backticks, with backticks and pipes neutralised so a hostile or unusual label
        cannot break out of its cell.
    """
    text = str(value).replace("`", "'").replace("|", "\\|").replace("\n", " ").strip()
    return f"`{text}`" if text else "—"


def pull_request_title(summary: DeliverySummary) -> str:
    """The pull request's title.

    Args:
        summary: What was delivered.

    Returns:
        ``Apiome SDK: @acme/widgets-sdk 1.4.0 (widgets 1.4.2)``.
    """
    version = summary.version_line or summary.version_record_id
    title = (
        f"Apiome SDK: {summary.package_name} {summary.package_version} "
        f"({summary.project_slug} {version})"
    )
    return " ".join(title.split())[:_TITLE_MAX_CHARS]


def commit_message(summary: DeliverySummary) -> str:
    """The commit's message, with provenance as git trailers.

    Trailers (``Apiome-Revision: …``) survive squash merges and rebases and are queryable with
    ``git log --format=%(trailers)``, so the provenance reaches the repository's history, not just
    the pull request.

    Args:
        summary: What was delivered.

    Returns:
        A subject line, a blank line, a short body and the trailers.
    """
    version = summary.version_line or summary.version_record_id
    subject = (
        f"Regenerate {summary.package_name} {summary.package_version} "
        f"from {summary.project_slug} {version}"
    )
    lines = [
        " ".join(subject.split())[:_TITLE_MAX_CHARS],
        "",
        f"Generated by Apiome from revision {summary.version_record_id} of "
        f"{summary.project_slug} ({summary.ecosystem}).",
        "",
        f"Apiome-Revision: {summary.version_record_id}",
    ]
    if summary.version_line:
        lines.append(f"Apiome-Version-Line: {summary.version_line}")
    lines.append(f"Apiome-Package: {summary.ecosystem} {summary.package_name}@{summary.package_version}")
    if summary.apiome_version:
        lines.append(f"Apiome-Generator: apiome {summary.apiome_version}")
    return "\n".join(lines) + "\n"


def _change_counts(changes: Mapping[str, Any]) -> str:
    """The one-line change tally."""
    return (
        f"**{int(changes.get(CHANGE_ADDED) or 0)} added · "
        f"{int(changes.get(CHANGE_MODIFIED) or 0)} modified · "
        f"{int(changes.get(CHANGE_DELETED) or 0)} removed** · "
        f"{int(changes.get('unchanged') or 0)} unchanged"
    )


def _render(summary: DeliverySummary, file_rows: int) -> str:
    """Render the body listing at most ``file_rows`` changed files.

    Args:
        summary: What was delivered.
        file_rows: How many changed files to list individually.

    Returns:
        The Markdown body.
    """
    changes = summary.changes
    files: List[Dict[str, Any]] = list(changes.get("files") or [])
    total_changed = sum(
        int(changes.get(key) or 0) for key in (CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_DELETED)
    )
    version = summary.version_line or summary.version_record_id
    # The API title is author-controlled prose rendered outside a code span, so it is kept to one
    # line — a title carrying newlines must not be able to start headings or tables of its own.
    subject = " ".join(str(summary.api_title or summary.project_slug).split()).replace("*", "\\*")
    target = summary.target_path or "(repository root)"

    lines: List[str] = [
        PULL_REQUEST_MARKER,
        f"## Regenerated SDK: {_code(summary.package_name)} {summary.package_version}",
        "",
        f"Apiome regenerated the **{summary.ecosystem}** SDK for **{subject}** from API version "
        f"{_code(version)}.",
        "",
        "| | |",
        "| --- | --- |",
        f"| Spec version | {_code(version)} (revision {_code(summary.version_record_id)}) |",
        f"| Package | {_code(f'{summary.package_name}@{summary.package_version}')} "
        f"({summary.ecosystem}) |",
        f"| Generator | Apiome {_code(summary.apiome_version or 'unknown')}"
        + (f" · {_code(summary.renderer)}" if summary.renderer else "")
        + " |",
        f"| Target | {_code(target)} in {_code(summary.repository_full_name)}, "
        f"into {_code(summary.base_branch)} |",
        "",
        "### Changed files",
        "",
        _change_counts(changes),
        "",
    ]

    shown = files[: max(0, file_rows)]
    if shown:
        lines.extend(["| Change | File |", "| --- | --- |"])
        lines.extend(f"| {entry.get('change')} | {_code(entry.get('path'))} |" for entry in shown)
        lines.append("")
    hidden = total_changed - len(shown)
    if hidden > 0:
        lines.extend([f"_…and {hidden:,} more changed file{'s' if hidden != 1 else ''}._", ""])

    lines.extend(["### Provenance", "", "| Field | Value |", "| --- | --- |"])
    for key, value in summary.provenance.items():
        if value is None or key in _SUMMARISED_KEYS:
            continue
        lines.append(f"| {_code(key)} | {_code(value)} |")
    lines.extend(
        [
            "",
            "The package's own metadata carries the same provenance, and the commit carries it as "
            "`Apiome-*` trailers.",
            "",
            "---",
            "",
            f"This branch ({_code(summary.branch_name)}) is managed by Apiome. Delivering this "
            f"version again rebuilds it on the latest {_code(summary.base_branch)} and "
            "force-updates it, so commits pushed to it by hand are replaced — change the API or its "
            "SDK settings instead. Files under the target directory that Apiome did not generate "
            "are never modified.",
        ]
    )
    return "\n".join(lines) + "\n"


def pull_request_body(
    summary: DeliverySummary, *, max_chars: int = PULL_REQUEST_BODY_MAX_CHARS
) -> str:
    """The pull request's description.

    Args:
        summary: What was delivered.
        max_chars: The longest body to return.

    Returns:
        Markdown carrying the spec version, the generator version, the changed-files overview and
        the provenance. When it would exceed ``max_chars`` the file table is shortened (the counts
        stay exact); as a last resort the text is cut.
    """
    rows = PULL_REQUEST_FILE_ROWS
    body = _render(summary, rows)
    while len(body) > max_chars and rows > 0:
        rows //= 2
        body = _render(summary, rows)
    if len(body) > max_chars:
        body = body[: max_chars - 2].rstrip() + "…\n"
    return body
