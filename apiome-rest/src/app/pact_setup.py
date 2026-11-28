"""Contracts guided set-up: sections, detection and the pipeline file — PFX-8.20 (#7317).

The **Set up contracts** page (``/ade/dashboard/pacts/setup``) and ``apiome pact setup`` take a
workspace from nothing to a yes-or-no before every deploy in six sections, in the order they depend
on each other:

1. ``pacticipants`` — who talks to whom;
2. ``environments`` — where things run;
3. ``pipelines`` — a key and two variables for CI;
4. ``first-pact`` — the first consumer pact;
5. ``provider`` — the provider's side (the spec as the contract, a verification, or both);
6. ``gates`` — can-i-deploy in CI, commit statuses, notifications.

This module is the part with no I/O:

* :func:`derive_sections` — each section's state (``done`` / ``next`` / ``todo``) from what the
  workspace **has** (:class:`PactSetupFacts`) and what an admin **marked** (:class:`PactSetupSaved`). A
  section whose thing exists is done whoever made it, so nothing is set up twice on a resume, and a
  workspace that migrated from a broker arrives with the first two sections done.
* :func:`detect_candidates` — pacticipants proposed from projects (providers) and from linked
  repositories no project is read from (consumers), with main branch and owner, each saying whether
  it already exists.
* :func:`workflow_text` — the GitHub Actions workflow a pull request adds: can-i-deploy on every
  pull request and push, and record-deployment after a push to the default branch.

Storage is :mod:`app.pact_setup_store`; GitHub is :mod:`app.pact_setup_github`; the routes are
:mod:`app.pact_setup_routes`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .pacticipant import slugify_pacticipant_name

__all__ = [
    "FIRST_PACT_PATHS",
    "SECRET_NAMES",
    "SECTION_IDS",
    "SECTION_TITLES",
    "SETUP_BRANCH",
    "WORKFLOW_PATH",
    "PactSetupGithubRepository",
    "PactSetupGithub",
    "PactSetupPullRequestRepository",
    "PactSetupPullRequestResult",
    "PactSetupPullRequestsRequest",
    "PactSetupPullRequestsResponse",
    "PactSetupSecretsRequest",
    "PactSetupSecretsResponse",
    "PactSetupSecretsResult",
    "PactSetupCandidate",
    "PactSetupCiKey",
    "PactSetupFacts",
    "PactSetupSave",
    "PactSetupSaved",
    "PactSetupSection",
    "PactSetupState",
    "check_broker_base_url",
    "derive_sections",
    "detect_candidates",
    "workflow_text",
]

#: The six sections, in the order they depend on each other.
SECTION_IDS = ("pacticipants", "environments", "pipelines", "first-pact", "provider", "gates")

#: What each section is called on the page and in ``apiome pact setup``.
SECTION_TITLES: Dict[str, str] = {
    "pacticipants": "Who talks to whom",
    "environments": "Where things run",
    "pipelines": "Connect your pipelines",
    "first-pact": "The first consumer pact",
    "provider": "The provider's side",
    "gates": "Gate deploys and tell people",
}

#: The ways to the first pact the page offers: publish the files Pact tests write, or derive one
#: from the provider's spec.
FIRST_PACT_PATHS = ("tests", "spec")

#: The two Actions secrets every Pact tool reads.
SECRET_NAMES = ("PACT_BROKER_BASE_URL", "PACT_BROKER_TOKEN")

#: Where the workflow goes in a repository, and the branch its pull request comes from.
WORKFLOW_PATH = ".github/workflows/apiome-contracts.yml"
SETUP_BRANCH = "apiome/contracts-setup"

SectionId = Literal["pacticipants", "environments", "pipelines", "first-pact", "provider", "gates"]
SectionState = Literal["done", "next", "todo"]

_NAME_SAFE = re.compile(r"^[^\x00-\x1f\x7f]{1,255}$")


class PactSetupCiKey(BaseModel):
    """The API key the page created for CI. Never its secret."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The key's id.", examples=["7b1f0c1e-6f4e-4f0a-9d53-3d0e3f5a2a11"])
    prefix: str = Field(description="The key's visible prefix.", min_length=1, max_length=64, examples=["apk_9f2c…"])


class PactSetupFacts(BaseModel):
    """What the workspace has, as far as the set-up's sections care."""

    model_config = ConfigDict(extra="forbid")

    pacticipants: int = Field(default=0, description="Live pacticipants.")
    environments: List[str] = Field(default_factory=list, description="Environment names.")
    production_environment: bool = Field(default=False, description="Whether one is marked production.")
    pacts: int = Field(default=0, description="Published pacts (consumer × provider × version).")
    contract_sources: int = Field(
        default=0, description="Providers whose published project versions become their provider contract."
    )
    verification_results: int = Field(default=0, description="Verification results recorded, of any kind.")
    webhooks: int = Field(default=0, description="Webhooks, enabled or not.")
    migrated: bool = Field(default=False, description="Whether a migration from another broker completed here.")


class PactSetupSaved(BaseModel):
    """What the workspace marked and did on the page (``pact_setup_progress``)."""

    model_config = ConfigDict(extra="forbid")

    marked: List[SectionId] = Field(default_factory=list, description="Sections marked done by hand.")
    first_pact_path: Optional[Literal["tests", "spec"]] = Field(
        default=None, description="The chosen way to the first pact."
    )
    ci_key: Optional[PactSetupCiKey] = Field(
        default=None, description="The key the page created for CI, while it is still live."
    )


class PactSetupSection(BaseModel):
    """One section of the set-up."""

    model_config = ConfigDict(extra="forbid")

    id: SectionId
    title: str
    state: SectionState = Field(description="`done`, `next` (the one to do now) or `todo`.")
    summary: str = Field(description="One line: what is there, or what the section sets up.")
    marked: bool = Field(default=False, description="Whether an admin marked it done by hand.")


class PactSetupCandidate(BaseModel):
    """A pacticipant the set-up proposes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The proposed pacticipant name.", examples=["Billing API"])
    slug: str = Field(description="The handle it would get.", examples=["billing-api"])
    source: Literal["project", "repository"]
    source_label: str = Field(description="Where it was found.", examples=["Project · Billing API"])
    role: Literal["provider", "consumer"] = Field(
        description="A project describes an API, so it is proposed as a provider; a repository no project is "
        "read from is proposed as a consumer. A pacticipant can be both: the role only orders the page."
    )
    project: Optional[str] = Field(default=None, description="The project's slug, for a provider.")
    repository_id: Optional[str] = Field(default=None, description="The linked repository, when one is known.")
    repository_url: Optional[str] = None
    main_branch: Optional[str] = None
    owner: Optional[str] = Field(default=None, description="The confirmed owner team's name, or null for none.")
    pacticipant: Optional[str] = Field(
        default=None, description="The handle of the pacticipant that already exists for it, or null."
    )
    pacticipant_name: Optional[str] = Field(default=None, description="That pacticipant's name, as pacts use it.")
    contract_source: bool = Field(
        default=False,
        description="Whether that pacticipant already publishes each published version of its project as its "
        "provider contract.",
    )


class PactSetupGithubRepository(BaseModel):
    """A registered GitHub repository and what the set-up did to it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    full_name: str
    default_branch: Optional[str] = None
    linked: bool = Field(description="Whether it was registered with a linked GitHub account that can be written with.")
    pacticipant: Optional[str] = Field(
        default=None, description="The handle of the pacticipant whose repository URL names it, or null."
    )
    pacticipant_name: Optional[str] = Field(
        default=None, description="That pacticipant's name — what the workflow passes to can-i-deploy."
    )
    secrets_written_at: Optional[str] = Field(
        default=None, description="When the two Actions secrets were last written by the set-up."
    )
    pull_request_url: Optional[str] = Field(default=None, description="The pull request the set-up opened.")


class PactSetupGithub(BaseModel):
    """Whether the secret and pull-request actions can run, and on what."""

    model_config = ConfigDict(extra="forbid")

    linked: bool = Field(description="Whether at least one repository can be written with a linked account.")
    reason: Optional[str] = Field(
        default=None, description="Why not, when `linked` is false: the page then shows copyable snippets."
    )
    repositories: List[PactSetupGithubRepository] = Field(default_factory=list)


class PactSetupState(BaseModel):
    """``GET …/pact-setup``: the six sections and everything the page draws them from."""

    model_config = ConfigDict(extra="forbid")

    sections: List[PactSetupSection]
    done: int = Field(description="How many sections are done.")
    total: int = Field(description="How many there are (6).")
    complete: bool = Field(description="Whether all are done.")
    facts: PactSetupFacts
    saved: PactSetupSaved
    candidates: List[PactSetupCandidate] = Field(default_factory=list)
    candidates_omitted: int = Field(
        default=0, description="Candidates left out of `candidates` because the list is capped."
    )
    github: PactSetupGithub
    workflow_path: str = Field(description="Where the pull request puts the workflow.")
    can_edit: bool = Field(description="Whether the caller may act on the page (`pacts:delete`).")
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class PactSetupSave(BaseModel):
    """``PUT …/pact-setup``: only what is sent changes."""

    model_config = ConfigDict(extra="forbid")

    mark: Optional[Dict[SectionId, bool]] = Field(
        default=None,
        description="Sections to mark done (`true`) or unmark (`false`); the others keep their mark.",
        examples=[{"pipelines": True}],
    )
    first_pact_path: Optional[Literal["tests", "spec"]] = Field(default=None, description="The chosen first-pact path.")
    ci_key: Optional[PactSetupCiKey] = Field(default=None, description="The key just created for CI.")
    forget_ci_key: bool = Field(default=False, description="Forget the recorded CI key (it is not revoked).")


class PactSetupSecretsRequest(BaseModel):
    """``POST …/pact-setup/github/secrets``."""

    model_config = ConfigDict(extra="forbid")

    repository_ids: List[str] = Field(min_length=1, max_length=50, description="Registered repositories to write to.")
    broker_base_url: str = Field(
        description="What `PACT_BROKER_BASE_URL` is set to.",
        examples=["https://api.apiome.dev/v1/tenants/acme/pact-broker"],
    )
    token: str = Field(
        min_length=8,
        max_length=512,
        description="What `PACT_BROKER_TOKEN` is set to: an Apiome API key. Sent on to GitHub sealed; never stored.",
    )


class PactSetupSecretsResult(BaseModel):
    """What happened in one repository."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str
    full_name: Optional[str] = None
    status: Literal["written", "skipped"]
    reason: Optional[str] = Field(default=None, description="Why it was skipped, in words a person can act on.")
    names: List[str] = Field(default_factory=list, description="The secrets written.")


class PactSetupSecretsResponse(BaseModel):
    """Every repository asked for, written or skipped with the reason."""

    model_config = ConfigDict(extra="forbid")

    results: List[PactSetupSecretsResult]


class PactSetupPullRequestRepository(BaseModel):
    """One repository and the pacticipant its pipeline asks about."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str
    pacticipant: str = Field(description="The pacticipant name the workflow passes to can-i-deploy.")


class PactSetupPullRequestsRequest(BaseModel):
    """``POST …/pact-setup/github/pull-requests``."""

    model_config = ConfigDict(extra="forbid")

    repositories: List[PactSetupPullRequestRepository] = Field(min_length=1, max_length=50)
    environment: str = Field(description="The environment can-i-deploy asks about.", examples=["production"])
    can_i_deploy: bool = Field(default=True, description="Add the can-i-deploy step.")
    record_deployment: bool = Field(default=True, description="Add the record-deployment step.")
    preview: bool = Field(
        default=False, description="Only answer with the file each pull request would add; GitHub is not called."
    )


class PactSetupPullRequestResult(BaseModel):
    """What happened in one repository."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str
    full_name: Optional[str] = None
    status: Literal["opened", "exists", "preview", "skipped"]
    reason: Optional[str] = Field(default=None, description="Why it was skipped, or what `exists` found.")
    url: Optional[str] = Field(default=None, description="The pull request.")
    number: Optional[int] = None
    path: str = Field(description="Where the workflow goes.")
    content: str = Field(description="The workflow, so it can be added by hand when no pull request was opened.")


class PactSetupPullRequestsResponse(BaseModel):
    """Every repository asked for."""

    model_config = ConfigDict(extra="forbid")

    results: List[PactSetupPullRequestResult]


def _plural(count: int, word: str) -> str:
    """``3 pacticipants`` / ``1 pacticipant``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _join(names: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``; past three, the count of the rest."""
    shown = list(names[:3])
    rest = len(names) - len(shown)
    if rest > 0:
        return f"{', '.join(shown)} and {rest} more"
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def _done_and_summary(section: str, facts: PactSetupFacts, saved: PactSetupSaved) -> tuple[bool, str]:
    """Whether a section is done, and its one-line summary."""
    marked = section in saved.marked
    if section == "pacticipants":
        if facts.pacticipants:
            return True, f"{_plural(facts.pacticipants, 'pacticipant')}"
        if facts.migrated:
            return True, "Copied from your broker"
        return False, "Pacticipants from your projects and repositories"
    if section == "environments":
        if facts.environments:
            return True, _join(facts.environments)
        if facts.migrated:
            return True, "Copied from your broker"
        return False, "production, staging, or your own"
    if section == "pipelines":
        if saved.ci_key is not None:
            return True, f"Key {saved.ci_key.prefix}"
        return marked, "Connected outside this page" if marked else "A key and two variables"
    if section == "first-pact":
        if facts.pacts:
            return True, f"{_plural(facts.pacts, 'pact')} published"
        return False, "Publish one or derive one from the spec"
    if section == "provider":
        parts = []
        if facts.contract_sources:
            parts.append(f"spec as the contract for {_plural(facts.contract_sources, 'provider')}")
        if facts.verification_results:
            parts.append(f"{_plural(facts.verification_results, 'verification result')}")
        if parts:
            summary = " · ".join(parts)
            return True, summary[0].upper() + summary[1:]
        return marked, "Handled outside this page" if marked else "Spec as the contract, a live verification, or both"
    return marked, "Finished" if marked else "can-i-deploy in CI, commit statuses, notifications"


def derive_sections(facts: PactSetupFacts, saved: PactSetupSaved) -> List[PactSetupSection]:
    """Each section's state from what exists and what was marked.

    A section is ``done`` when its thing exists — whoever made it, here or elsewhere — or, for the
    sections nothing in the workspace proves (pipelines, the provider's side, gates), when an admin
    marked it. The first section not done is ``next``; the rest are ``todo``.

    Args:
        facts: What the workspace has.
        saved: What it marked and did on the page.

    Returns:
        The six sections, in order.
    """
    sections: List[PactSetupSection] = []
    next_given = False
    for section in SECTION_IDS:
        done, summary = _done_and_summary(section, facts, saved)
        state: SectionState = "done"
        if not done:
            state = "todo" if next_given else "next"
            next_given = True
        sections.append(
            PactSetupSection(
                id=section,  # type: ignore[arg-type]
                title=SECTION_TITLES[section],
                state=state,
                summary=summary,
                marked=section in saved.marked,
            )
        )
    return sections


def _repository_key(url: Optional[str]) -> Optional[str]:
    """``host/owner/repo`` of a repository URL, lowercased, without ``.git``; ``None`` when unreadable."""
    text = str(url or "").strip()
    if not text:
        return None
    if text.startswith("git@") and ":" in text:
        host, _, path = text[4:].partition(":")
    else:
        parts = urlsplit(text if "://" in text else f"https://{text}")
        host, path = parts.hostname or "", parts.path
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    if not host or not path:
        return None
    return f"{host}/{path}".lower()


def _repository_web_url(row: Mapping[str, Any]) -> Optional[str]:
    """The http(s) page of a registered repository, or ``None``."""
    full_name = str(row.get("repository_full_name") or "").strip()
    if str(row.get("provider") or "").lower() == "github" and full_name:
        return f"https://github.com/{full_name}"
    clone = str(row.get("clone_url") or "").strip()
    if clone.lower().startswith(("http://", "https://")):
        return clone[:-4] if clone.lower().endswith(".git") else clone
    return None


def _repository_name(row: Mapping[str, Any]) -> str:
    """What a repository is called: its last path segment."""
    full_name = str(row.get("repository_full_name") or "").strip()
    if full_name:
        return full_name.rsplit("/", 1)[-1]
    key = _repository_key(row.get("clone_url"))
    return key.rsplit("/", 1)[-1] if key else ""


def detect_candidates(
    projects: Iterable[Mapping[str, Any]],
    repositories: Iterable[Mapping[str, Any]],
    pacticipants: Iterable[Mapping[str, Any]],
) -> List[PactSetupCandidate]:
    """Propose pacticipants from projects and linked repositories.

    * Every project is proposed as a **provider** named after it. When the project is read from a
      registered repository (``project_repository_sources``), the candidate carries that
      repository's URL and branch.
    * Every registered repository no project is read from is proposed as a **consumer** named
      after the repository.

    A candidate ``pacticipant`` names the pacticipant that already exists for it: one bound to the
    project, one whose repository URL is the repository's, or one with the same handle or name.

    Args:
        projects: ``{id, slug, name, owner, repository_id, repository_branch}`` rows.
        repositories: ``tenant_repositories`` rows (``id``, ``provider``, ``repository_full_name``,
            ``clone_url``, ``default_branch``, ``owner``).
        pacticipants: ``{slug, name, project_id, repository_url, contract_source}`` rows of the live
            pacticipants.

    Returns:
        The candidates: providers by name, then consumers by name. A project or repository whose
        name cannot be a pacticipant name is left out by the caller's count, never renamed here.
    """
    existing = [dict(row) for row in pacticipants]
    by_project = {str(row["project_id"]): str(row["slug"]) for row in existing if row.get("project_id")}
    by_repository = {
        key: str(row["slug"]) for row in existing if (key := _repository_key(row.get("repository_url"))) is not None
    }
    by_slug = {str(row["slug"]).lower(): str(row["slug"]) for row in existing}
    by_name = {str(row.get("name") or "").strip().lower(): str(row["slug"]) for row in existing}
    repository_rows = {str(row["id"]): dict(row) for row in repositories}
    rows_by_slug = {str(row["slug"]): row for row in existing}

    def matched(slug: Optional[str]) -> Dict[str, Any]:
        """The fields a candidate copies from the pacticipant that already stands for it."""
        row = rows_by_slug.get(slug or "")
        if row is None:
            return {"pacticipant": None}
        return {
            "pacticipant": slug,
            "pacticipant_name": str(row.get("name") or "") or None,
            "contract_source": bool(row.get("contract_source")),
        }

    def known(name: str, slug: str, repository_url: Optional[str], project_id: Optional[str] = None) -> Optional[str]:
        """The handle of the pacticipant that already stands for a candidate."""
        if project_id and project_id in by_project:
            return by_project[project_id]
        key = _repository_key(repository_url)
        if key and key in by_repository:
            return by_repository[key]
        return by_slug.get(slug.lower()) or by_name.get(name.strip().lower())

    providers: List[PactSetupCandidate] = []
    used_repositories: set[str] = set()
    for project in projects:
        name = str(project.get("name") or "").strip()
        if not _NAME_SAFE.match(name):
            continue
        slug = slugify_pacticipant_name(name)
        repository = repository_rows.get(str(project.get("repository_id") or ""))
        if repository is not None:
            used_repositories.add(str(repository["id"]))
        repository_url = _repository_web_url(repository) if repository else None
        providers.append(
            PactSetupCandidate(
                name=name,
                slug=slug,
                source="project",
                source_label=f"Project · {name}",
                role="provider",
                project=str(project.get("slug") or "") or None,
                repository_id=str(repository["id"]) if repository else None,
                repository_url=repository_url,
                main_branch=(
                    str(project.get("repository_branch") or (repository or {}).get("default_branch") or "") or None
                ),
                owner=str(project.get("owner") or "") or None,
                **matched(known(name, slug, repository_url, str(project.get("id") or "") or None)),
            )
        )
    consumers: List[PactSetupCandidate] = []
    for repository_id, repository in repository_rows.items():
        if repository_id in used_repositories:
            continue
        name = _repository_name(repository)
        if not _NAME_SAFE.match(name):
            continue
        slug = slugify_pacticipant_name(name)
        repository_url = _repository_web_url(repository)
        label = str(repository.get("repository_full_name") or "").strip() or name
        consumers.append(
            PactSetupCandidate(
                name=name,
                slug=slug,
                source="repository",
                source_label=f"Repository · {label}",
                role="consumer",
                repository_id=repository_id,
                repository_url=repository_url,
                main_branch=str(repository.get("default_branch") or "") or None,
                owner=str(repository.get("owner") or "") or None,
                **matched(known(name, slug, repository_url)),
            )
        )
    providers.sort(key=lambda item: item.name.lower())
    consumers.sort(key=lambda item: item.name.lower())
    return providers + consumers


def check_broker_base_url(url: str) -> str:
    """Return a broker base URL fit to be stored as a secret, or refuse it.

    Args:
        url: The address as sent.

    Returns:
        The address without a trailing slash.

    Raises:
        ValueError: For anything but an http(s) URL with a host, no credentials, no query and no
            whitespace, of at most 512 characters.
    """
    text = str(url or "").strip()
    if not text or len(text) > 512 or any(ch.isspace() for ch in text):
        raise ValueError("broker_base_url must be an http(s) URL of at most 512 characters, without spaces")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("broker_base_url must be an http(s) URL")
    if parts.username or parts.password:
        raise ValueError("broker_base_url must not carry credentials; the key goes in PACT_BROKER_TOKEN")
    if parts.query or parts.fragment:
        raise ValueError("broker_base_url must not carry a query or a fragment")
    return text.rstrip("/")


def _yaml_string(value: str) -> str:
    """A YAML double-quoted scalar (JSON's string syntax is a subset of YAML's)."""
    return json.dumps(value, ensure_ascii=False)


def workflow_text(
    *,
    pacticipant: str,
    environment: str,
    default_branch: str = "main",
    can_i_deploy: bool = True,
    record_deployment: bool = True,
) -> str:
    """The GitHub Actions workflow the set-up's pull request adds.

    It reads ``PACT_BROKER_BASE_URL`` and ``PACT_BROKER_TOKEN`` from the repository's secrets and
    runs the Apiome Pact action: can-i-deploy on every pull request and push to the default branch,
    record-deployment after a push to the default branch.

    Args:
        pacticipant: The pacticipant the pipeline asks about, as pacts name it.
        environment: The environment asked about and recorded.
        default_branch: The repository's default branch.
        can_i_deploy: Add the can-i-deploy step.
        record_deployment: Add the record-deployment step.

    Returns:
        The workflow file's text.

    Raises:
        ValueError: When neither step is asked for, or a value has a line break or control character.
    """
    if not can_i_deploy and not record_deployment:
        raise ValueError("choose at least one of can-i-deploy and record-deployment")
    for what, value in (("pacticipant", pacticipant), ("environment", environment), ("branch", default_branch)):
        if not _NAME_SAFE.match(str(value or "")):
            raise ValueError(f"the {what} must be 1 to 255 characters without line breaks")
    name = _yaml_string(pacticipant)
    target = _yaml_string(environment)
    lines = [
        "# Added by Apiome's Contracts set-up.",
        "# Reads PACT_BROKER_BASE_URL and PACT_BROKER_TOKEN from this repository's Actions secrets.",
        "name: apiome-contracts",
        "on:",
        "  pull_request:",
        "  push:",
        f"    branches: [{_yaml_string(default_branch)}]",
        "permissions:",
        "  contents: read",
        "  pull-requests: write",
        "jobs:",
        "  contracts:",
        "    runs-on: ubuntu-latest",
        "    env:",
        "      PACT_BROKER_BASE_URL: ${{ secrets.PACT_BROKER_BASE_URL }}",
        "      PACT_BROKER_TOKEN: ${{ secrets.PACT_BROKER_TOKEN }}",
        "    steps:",
        "      - uses: actions/checkout@v4",
    ]
    if can_i_deploy:
        lines += [
            "      # Fails the job when this version is not safe to deploy.",
            "      - uses: apiome/apiome/pact-action@main",
            "        with:",
            "          command: can-i-deploy",
            f"          pacticipant: {name}",
            f"          environment: {target}",
            '          retry-while-unknown: "12"',
        ]
    if record_deployment:
        lines += [
            "      # Deploy before this step: it tells Apiome this version is now running.",
            "      - if: github.event_name == 'push'",
            "        uses: apiome/apiome/pact-action@main",
            "        with:",
            "          command: record-deployment",
            f"          pacticipant: {name}",
            f"          environment: {target}",
        ]
    return "\n".join(lines) + "\n"
