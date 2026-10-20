"""PR-back sync rules: Apiome → repository — REPO-5.8 (#2793).

Changes used to flow one way: a repository file is imported into a project. PR-back is the way
back: render a project version's spec and open a pull request into the repository files the
project was imported from. This module holds the **pure** rules — no database, no network:

* **Settings** (:class:`PrBackSettings`, :func:`normalize_settings`) — each repository's allow/deny
  list of projects, its target branch, commit message template and reviewers (apiome-db V302).
  A repository with no settings lets no project PR back: PR-back is opt-in per repository.
* **Which file gets what** (:func:`owner_of`, :func:`slice_spec_for_source`). A project can merge
  several repository files (REPO-5.7, V301): every class and path has exactly one source file, and
  ``version_entity_sources`` records which. Each file gets back only the paths and schemas it
  defines. Content no live source file defines — edited in Apiome, or whose file was removed —
  belongs to the **primary** file (precedence 1), the same file whose project info the merge keeps.
  A single-source project is the degenerate case: its one file is primary and gets everything.
* **The file text** (:func:`spec_format_for_path`, :func:`serialize_spec`, :func:`parse_spec_text`)
  — written in the file's own format, JSON or YAML, picked from its extension. Other files (a
  ``.graphql``, a ``.proto``) are not rendered back: Apiome renders OpenAPI.
* **The words** (:func:`render_commit_message`, :func:`pull_request_title`,
  :func:`pull_request_body`) — the commit message from the repository's Mustache template, and a
  pull request description made of the project's change report (the same templates a publication
  change report uses) for each file, plus what PR-back did.

The pipeline that applies these rules against GitHub is :mod:`app.pr_back_pipeline`.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import chevron
import yaml

from .sdk_git_delivery_targets import ref_name_problem, ref_segment

__all__ = [
    "BRANCH_PREFIX",
    "DEFAULT_COMMIT_MESSAGE_TEMPLATE",
    "MAX_PROJECT_IDS",
    "MAX_REVIEWERS",
    "PR_BODY_MAX_CHARS",
    "PROJECT_POLICIES",
    "FileChangeReport",
    "PrBackSettings",
    "PrBackSettingsError",
    "SourceFile",
    "commit_message_context",
    "foreign_schema_refs",
    "normalize_settings",
    "owner_of",
    "parse_spec_text",
    "pr_back_branch_name",
    "project_allowed",
    "pull_request_body",
    "pull_request_title",
    "render_commit_message",
    "serialize_spec",
    "slice_spec_for_source",
    "spec_format_for_path",
    "split_reviewers",
]

#: Every PR-back branch starts with this, so a repository's maintainers can see at a glance which
#: branches Apiome owns (and rebuilds).
BRANCH_PREFIX = "apiome/pr-back-"

#: The commit message when a repository sets no template.
DEFAULT_COMMIT_MESSAGE_TEMPLATE = "Sync {{project}} {{version}} from Apiome"

#: ``allow`` lets only the listed projects PR back; ``deny`` lets every project except them.
PROJECT_POLICIES = ("allow", "deny")

#: Longest project list a repository's settings hold (V302's CHECK).
MAX_PROJECT_IDS = 500

#: Most reviewers a pull request is given (V302's CHECK; GitHub accepts up to 15 per request).
MAX_REVIEWERS = 15

#: Longest commit message template (V302's CHECK).
COMMIT_TEMPLATE_MAX_CHARS = 2000

#: Longest rendered commit message kept.
_COMMIT_MESSAGE_MAX_CHARS = 4000

#: GitHub refuses pull request descriptions longer than 65,536 characters; stay under it.
PR_BODY_MAX_CHARS = 60_000

#: A GitHub login: alphanumerics and single hyphens, 1–39 characters.
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

#: A GitHub team: ``org/team-slug``.
_TEAM = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")

#: Extensions PR-back renders back, and the format each is written in.
_FORMAT_BY_EXTENSION = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}

#: A plain ``{{name}}`` variable tag (not ``{{{name}}}``, a section or a comment).
_PLAIN_TAG = re.compile(r"(?<!\{)\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}(?!\})")

#: A local reference to a schema component.
_SCHEMA_REF_PREFIX = "#/components/schemas/"


class PrBackSettingsError(ValueError):
    """Settings that cannot be saved, with a stable code and a message naming the fix.

    Attributes:
        code: A stable, machine-readable reason.
        message: What is wrong and how to fix it.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PrBackSettings:
    """One repository's PR-back settings (a ``repository_pr_back_settings`` row).

    Attributes:
        project_policy: ``allow`` or ``deny``.
        project_ids: The projects the policy lists.
        target_branch: The pull requests' base branch; ``None`` for the files' import branch.
        commit_message_template: Mustache template; ``None`` for
            :data:`DEFAULT_COMMIT_MESSAGE_TEMPLATE`.
        reviewers: GitHub logins and ``org/team`` slugs to request reviews from.
    """

    project_policy: str = "allow"
    project_ids: Tuple[str, ...] = ()
    target_branch: Optional[str] = None
    commit_message_template: Optional[str] = None
    reviewers: Tuple[str, ...] = ()

    @classmethod
    def from_row(cls, row: Optional[Mapping[str, Any]]) -> Optional["PrBackSettings"]:
        """Build settings from a stored row.

        Args:
            row: A ``repository_pr_back_settings`` row, or ``None``.

        Returns:
            The settings, or ``None`` when the repository has none.
        """
        if not row:
            return None
        return cls(
            project_policy=str(row.get("project_policy") or "allow"),
            project_ids=tuple(str(p) for p in (row.get("project_ids") or [])),
            target_branch=row.get("target_branch") or None,
            commit_message_template=row.get("commit_message_template") or None,
            reviewers=tuple(str(r) for r in (row.get("reviewers") or [])),
        )


@dataclass(frozen=True)
class SourceFile:
    """One repository file a project was imported from.

    Attributes:
        source_id: The ``project_repository_sources`` row, or ``None`` for a pre-REPO-5.7 import
            read from ``tenant_repository_imports``.
        repository_id: The registered repository.
        branch: The branch the file was imported from.
        path: The repository-relative path of the file.
        precedence: The merge order (1 contributed first).
    """

    source_id: Optional[str]
    repository_id: str
    branch: str
    path: str
    precedence: int = 1


@dataclass
class FileChangeReport:
    """What PR-back writes to one file, and how it differs from the file on the base branch.

    Attributes:
        path: The repository-relative path.
        status: ``added`` (no file on the base branch), ``modified`` or ``unchanged``.
        header: The rendered change report header.
        body: The rendered change report body.
        footnote: The rendered change report footnote.
        counts: Substantive change counts (``openapi_change_report.change_report_change_counts``).
        paths: How many paths the file carries.
        schemas: How many schemas the file carries.
        foreign_refs: Schemas the file references that another source file defines.
        notes: Anything a reviewer should know (an unparseable base file, a format change).
    """

    path: str
    status: str
    header: str = ""
    body: str = ""
    footnote: str = ""
    counts: Dict[str, int] = field(default_factory=dict)
    paths: int = 0
    schemas: int = 0
    foreign_refs: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# -------------------------------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------------------------------


def split_reviewers(reviewers: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Split reviewer entries into GitHub user logins and team slugs.

    Args:
        reviewers: Entries as stored — ``octocat`` or ``acme/api-reviewers``.

    Returns:
        ``(logins, team_slugs)``; a team entry contributes only its slug, which is what GitHub's
        review-request API takes (the organization is the repository's).
    """
    logins: List[str] = []
    teams: List[str] = []
    for entry in reviewers:
        if "/" in entry:
            teams.append(entry.split("/", 1)[1])
        else:
            logins.append(entry)
    return logins, teams


def normalize_settings(
    *,
    project_policy: Optional[str],
    project_ids: Optional[Sequence[str]],
    target_branch: Optional[str],
    commit_message_template: Optional[str],
    reviewers: Optional[Sequence[str]],
) -> PrBackSettings:
    """Validate and normalize settings a caller wants to save.

    Args:
        project_policy: ``allow`` or ``deny``; ``None`` for ``allow``.
        project_ids: Project ids; duplicates are dropped, order kept.
        target_branch: A branch name; blank for the files' import branch.
        commit_message_template: A Mustache template; blank for the default.
        reviewers: GitHub logins (``octocat``) or teams (``acme/api-reviewers``); a leading ``@``
            is dropped; duplicates (ignoring case) are dropped.

    Returns:
        The normalized :class:`PrBackSettings`.

    Raises:
        PrBackSettingsError: For an unknown policy, too many projects or reviewers, an illegal
            branch name, a template that is too long or does not render, or a reviewer that is
            neither a login nor a team.
    """
    policy = (project_policy or "allow").strip().lower()
    if policy not in PROJECT_POLICIES:
        raise PrBackSettingsError(
            "pr-back-policy-invalid",
            f"Project policy must be one of {', '.join(PROJECT_POLICIES)}; got {project_policy!r}.",
        )

    ids: List[str] = []
    for raw in project_ids or []:
        value = str(raw or "").strip().lower()
        if value and value not in ids:
            ids.append(value)
    if len(ids) > MAX_PROJECT_IDS:
        raise PrBackSettingsError(
            "pr-back-projects-too-many",
            f"A repository can list at most {MAX_PROJECT_IDS} projects; got {len(ids)}.",
        )

    branch = (target_branch or "").strip() or None
    if branch is not None:
        problem = ref_name_problem(branch)
        if problem:
            raise PrBackSettingsError("pr-back-branch-invalid", f"Target branch {branch!r}: {problem}.")

    template = (commit_message_template or "").strip() or None
    if template is not None:
        if len(template) > COMMIT_TEMPLATE_MAX_CHARS:
            raise PrBackSettingsError(
                "pr-back-template-too-long",
                f"The commit message template is longer than {COMMIT_TEMPLATE_MAX_CHARS} characters.",
            )
        try:
            rendered = _render_plain(template, commit_message_context("project", "1.0.0", "o/r", "main", 1))
        except Exception as exc:  # noqa: BLE001 - chevron raises several types for a bad template
            raise PrBackSettingsError(
                "pr-back-template-invalid",
                f"The commit message template does not render ({type(exc).__name__}). Check its "
                "{{…}} tags.",
            ) from exc
        if not rendered.strip():
            raise PrBackSettingsError(
                "pr-back-template-invalid", "The commit message template renders an empty message."
            )

    people: List[str] = []
    seen: Set[str] = set()
    for raw in reviewers or []:
        value = str(raw or "").strip().lstrip("@")
        if not value:
            continue
        if not (_LOGIN.match(value) or _TEAM.match(value)):
            raise PrBackSettingsError(
                "pr-back-reviewer-invalid",
                f"Reviewer {raw!r} is neither a GitHub login (octocat) nor a team (org/team-slug).",
            )
        if value.lower() not in seen:
            seen.add(value.lower())
            people.append(value)
    if len(people) > MAX_REVIEWERS:
        raise PrBackSettingsError(
            "pr-back-reviewers-too-many",
            f"A pull request can request at most {MAX_REVIEWERS} reviewers; got {len(people)}.",
        )

    return PrBackSettings(
        project_policy=policy,
        project_ids=tuple(ids),
        target_branch=branch,
        commit_message_template=template,
        reviewers=tuple(people),
    )


def project_allowed(settings: Optional[PrBackSettings], project_id: str) -> bool:
    """Say whether a repository's settings let a project open pull requests into it.

    Args:
        settings: The repository's settings, or ``None`` when it has none.
        project_id: The project.

    Returns:
        ``False`` without settings (PR-back is opt-in); otherwise the policy's answer — ``allow``:
        listed; ``deny``: not listed.
    """
    if settings is None:
        return False
    listed = str(project_id).strip().lower() in {p.lower() for p in settings.project_ids}
    return listed if settings.project_policy == "allow" else not listed


# -------------------------------------------------------------------------------------------
# Branch and commit message
# -------------------------------------------------------------------------------------------


def pr_back_branch_name(project_slug: Optional[str], base_branch: str) -> str:
    """Name the branch PR-back pushes a project's files to.

    One branch — and so one open pull request — per project and base branch. Each new version
    refreshes the same pull request the way a dependency bot's does, instead of opening another.

    Args:
        project_slug: The project's slug.
        base_branch: The branch the pull request merges into.

    Returns:
        ``apiome/pr-back-<project>-<base>``, e.g. ``apiome/pr-back-shop-main``.
    """
    return f"{BRANCH_PREFIX}{ref_segment(project_slug, 'project')}-{ref_segment(base_branch, 'base')}"


def commit_message_context(
    project: str, version: str, repository: str, branch: str, file_count: int
) -> Dict[str, Any]:
    """The values a commit message template may use.

    Args:
        project: The project's name.
        version: The version label.
        repository: ``owner/repo``.
        branch: The base branch.
        file_count: How many files the commit writes.

    Returns:
        ``project``, ``version``, ``repository``, ``branch`` and ``fileCount``.
    """
    return {
        "project": project,
        "version": version,
        "repository": repository,
        "branch": branch,
        "fileCount": file_count,
    }


def _render_plain(template: str, context: Mapping[str, Any]) -> str:
    """Render a Mustache template without HTML escaping.

    A commit message is plain text: ``{{project}}`` for ``R&D`` must read ``R&D``, not
    ``R&amp;D``, so plain variable tags are rendered as Mustache's unescaped ``{{{…}}}``.

    Args:
        template: The template.
        context: Its values.

    Returns:
        The rendered text.
    """
    return chevron.render(_PLAIN_TAG.sub(r"{{{\1}}}", template), dict(context))


def render_commit_message(template: Optional[str], context: Mapping[str, Any]) -> str:
    """Render the commit message.

    Args:
        template: The repository's template, or ``None`` for the default.
        context: :func:`commit_message_context`.

    Returns:
        The message, trimmed and bounded. Falls back to the default template when the stored one
        renders empty (it was validated on save, so that only happens for odd values).
    """
    text = _render_plain(template or DEFAULT_COMMIT_MESSAGE_TEMPLATE, context).strip()
    if not text:
        text = _render_plain(DEFAULT_COMMIT_MESSAGE_TEMPLATE, context).strip()
    return text[:_COMMIT_MESSAGE_MAX_CHARS]


# -------------------------------------------------------------------------------------------
# Which file gets what
# -------------------------------------------------------------------------------------------


def owner_of(
    kind: str,
    key: str,
    entity_sources: Mapping[Tuple[str, str], Optional[str]],
    live_source_ids: Set[str],
    primary_source_id: Optional[str],
) -> Optional[str]:
    """Say which source file a class or path belongs to.

    Args:
        kind: ``class`` or ``path``.
        key: The class name or pathname.
        entity_sources: ``(kind, key) → source_id`` from ``version_entity_sources``.
        live_source_ids: The project's current source rows.
        primary_source_id: The precedence-1 source.

    Returns:
        The defining source when it is still live, otherwise the primary source — content no live
        file defines (edited in Apiome, or whose file was removed) belongs to the primary file.
    """
    source_id = entity_sources.get((kind, key))
    if source_id and source_id in live_source_ids:
        return source_id
    return primary_source_id


def _collect_schema_refs(value: Any, out: Set[str]) -> None:
    """Collect every ``#/components/schemas/<name>`` reference under a value."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_SCHEMA_REF_PREFIX):
            out.add(ref[len(_SCHEMA_REF_PREFIX):].replace("~1", "/").replace("~0", "~"))
        for item in value.values():
            _collect_schema_refs(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_schema_refs(item, out)


def foreign_schema_refs(document: Mapping[str, Any]) -> List[str]:
    """List the schemas a document references but does not define.

    Args:
        document: An OpenAPI document.

    Returns:
        Sorted schema names.
    """
    refs: Set[str] = set()
    _collect_schema_refs(document, refs)
    defined = set(((document.get("components") or {}).get("schemas") or {}).keys())
    return sorted(refs - defined)


def slice_spec_for_source(
    spec: Mapping[str, Any],
    *,
    source_id: Optional[str],
    owner: Callable[[str, str], Optional[str]],
) -> Dict[str, Any]:
    """Keep the part of a version's spec one source file owns.

    Everything outside ``paths`` and ``components.schemas`` — ``info``, ``servers``, security
    schemes, tags — is kept whole: it describes the API, not one file's share of it. A schema
    another file defines is **not** copied in when this file references it: two files defining the
    same class fail the next import (REPO-5.7), so the reference stays as the file wrote it and
    the change report lists it (:func:`foreign_schema_refs`).

    Args:
        spec: The rendered version spec. Not mutated.
        source_id: The file being written.
        owner: ``(kind, key) → source_id`` (:func:`owner_of` with its maps bound).

    Returns:
        A new document holding the paths whose owner is ``source_id`` and the schemas (one per
        class) whose owner is ``source_id``.
    """
    document = copy.deepcopy(dict(spec))
    paths = document.get("paths")
    if isinstance(paths, dict):
        document["paths"] = {k: v for k, v in paths.items() if owner("path", k) == source_id}
    components = document.get("components")
    if isinstance(components, dict) and isinstance(components.get("schemas"), dict):
        components["schemas"] = {
            k: v for k, v in components["schemas"].items() if owner("class", k) == source_id
        }
    return document


# -------------------------------------------------------------------------------------------
# File text
# -------------------------------------------------------------------------------------------


def spec_format_for_path(path: str) -> Optional[str]:
    """Pick the format a file is written in from its extension.

    Args:
        path: The repository-relative path.

    Returns:
        ``json`` or ``yaml``; ``None`` for a file PR-back does not render (not JSON or YAML).
    """
    lower = path.lower()
    for extension, fmt in _FORMAT_BY_EXTENSION.items():
        if lower.endswith(extension):
            return fmt
    return None


def serialize_spec(document: Mapping[str, Any], fmt: str) -> str:
    """Write a document as file text.

    Args:
        document: The OpenAPI document.
        fmt: ``json`` or ``yaml``.

    Returns:
        The text, ending with one newline. Key order is the document's (the renderer's), so the
        same version always produces the same bytes.
    """
    if fmt == "json":
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True, width=1000)


def parse_spec_text(text: Optional[str], fmt: str) -> Optional[Dict[str, Any]]:
    """Read the file currently on the base branch, for the change report.

    Args:
        text: The file's text, or ``None`` when it does not exist.
        fmt: ``json`` or ``yaml``.

    Returns:
        The document, or ``None`` when there is no file or it is not a JSON/YAML object.
    """
    if text is None:
        return None
    try:
        value = json.loads(text) if fmt == "json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError):
        return None
    return value if isinstance(value, dict) else None


# -------------------------------------------------------------------------------------------
# Pull request words
# -------------------------------------------------------------------------------------------


def pull_request_title(project_name: str, version_label: str) -> str:
    """Title the pull request.

    Args:
        project_name: The project's name.
        version_label: The version rendered.

    Returns:
        e.g. ``Apiome: sync Shop 1.4.0``.
    """
    return f"Apiome: sync {project_name} {version_label}".strip()[:250]


def _file_section(report: FileChangeReport) -> List[str]:
    """Markdown for one file's change report."""
    lines = [f"### `{report.path}` — {report.status}", ""]
    lines.append(f"{report.paths} path(s) and {report.schemas} schema(s) rendered from Apiome.")
    lines.append("")
    for part in (report.header, report.body, report.footnote):
        if part.strip():
            lines.extend([part.strip(), ""])
    if report.foreign_refs:
        names = ", ".join(f"`{name}`" for name in report.foreign_refs)
        lines.extend(
            [
                f"> References schemas another source file defines, left as references: {names}.",
                "",
            ]
        )
    for note in report.notes:
        lines.extend([f"> {note}", ""])
    return lines


def pull_request_body(
    *,
    project_name: str,
    version_label: str,
    repository_full_name: str,
    base_branch: str,
    branch_name: str,
    files: Sequence[FileChangeReport],
    skipped: Sequence[str],
    apiome_version: Optional[str],
) -> str:
    """Write the pull request description: each file's change report, then what PR-back did.

    Args:
        project_name: The project's name.
        version_label: The version rendered.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch.
        branch_name: The PR-back branch.
        files: One report per file written (``unchanged`` files included, so a reviewer sees the
            whole set).
        skipped: Sentences about files that were not rendered back, and why.
        apiome_version: The running API version, for provenance.

    Returns:
        Markdown, bounded to :data:`PR_BODY_MAX_CHARS`.
    """
    changed = [f for f in files if f.status != "unchanged"]
    lines = [
        f"## {project_name} {version_label} — rendered from Apiome",
        "",
        f"Apiome rendered version **{version_label}** of **{project_name}** and wrote "
        f"{len(changed)} of {len(files)} source file(s) back to `{repository_full_name}`.",
        "",
    ]
    for report in files:
        lines.extend(_file_section(report))
    if skipped:
        lines.extend(["### Not rendered back", ""])
        lines.extend(f"- {sentence}" for sentence in skipped)
        lines.append("")
    lines.extend(
        [
            "---",
            "",
            f"Opened by Apiome PR-back{f' ({apiome_version})' if apiome_version else ''}. "
            f"`{branch_name}` belongs to Apiome: it is rebuilt from `{base_branch}` every time this "
            "project is synced, so push review changes to the project in Apiome rather than to this "
            "branch.",
        ]
    )
    body = "\n".join(lines).rstrip() + "\n"
    if len(body) > PR_BODY_MAX_CHARS:
        marker = "\n\n_The change report was truncated to fit GitHub's limit._\n"
        body = body[: PR_BODY_MAX_CHARS - len(marker)] + marker
    return body
