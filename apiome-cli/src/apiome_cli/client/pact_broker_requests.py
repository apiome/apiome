"""Request building for the ``pact-broker``-compatible ``apiome pact`` commands — PFX-4.1 (#6938).

Every rule here is pure — reading pact files, grouping them by consumer, building the matrix query
of ``can-i-deploy``, the bodies of ``create-environment``, ``create-webhook`` and ``verify``, and
detecting the branch and build URL from the CI environment — so the commands stay thin shells and
each rule is unit-tested without HTTP.

Nothing is dropped silently: every input the server would not accept (a file that is not a pact,
a webhook method the broker refuses, ``--merge``) is a :class:`ValueError` naming the input and
the reason, raised before anything is sent.
"""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

#: Most pacts one ``POST …/contracts/publish`` accepts (the REST contract's ``maxItems``).
MAX_CONTRACTS_PER_PUBLISH = 100

#: The webhook methods the broker accepts.
WEBHOOK_METHODS = ("POST", "PUT", "PATCH")

#: The broker's webhook events, in ``pact-broker``'s order; ``create-webhook`` has a ``--<event>``
#: flag for each (underscores written as dashes).
WEBHOOK_EVENTS: tuple[str, ...] = (
    "contract_content_changed",
    "contract_published",
    "contract_requiring_verification_published",
    "provider_verification_published",
    "provider_verification_succeeded",
    "provider_verification_failed",
    "consumer_version_branch_created",
)


# ---------------------------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PactFile:
    """One pact read from disk.

    Attributes:
        path: Where it was read from.
        consumer: ``consumer.name``.
        provider: ``provider.name``.
        content: The file's bytes, sent unchanged.
    """

    path: Path
    consumer: str
    provider: str
    content: bytes


def collect_pact_paths(inputs: Sequence[Path]) -> list[Path]:
    """The pact files named by the command line: files as given, directories' ``*.json``.

    Args:
        inputs: Files and directories, in command-line order.

    Returns:
        The files, directories expanded in name order (not recursive, as ``pact-broker publish``).

    Raises:
        ValueError: when nothing was named, a path does not exist, or a directory holds no
            ``*.json`` file.
    """
    if not inputs:
        raise ValueError("name at least one pact file or directory")
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            found = sorted(p for p in item.glob("*.json") if p.is_file())
            if not found:
                raise ValueError(f"{item}: the directory holds no *.json pact file")
            paths.extend(found)
        elif item.is_file():
            paths.append(item)
        else:
            raise ValueError(f"{item}: no such file or directory")
    return paths


def _pacticipant_name(document: Mapping[str, Any], role: str, path: Path) -> str:
    """``document[role].name``, or a :class:`ValueError` naming the file."""
    party = document.get(role)
    name = party.get("name") if isinstance(party, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: not a pact — it has no {role}.name")
    return name.strip()


def read_pact_file(path: Path) -> PactFile:
    """Read one pact file and the names it carries.

    Args:
        path: The file.

    Returns:
        The pact.

    Raises:
        ValueError: when the file is not JSON, not an object, or lacks ``consumer.name`` /
            ``provider.name``.
    """
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: not a pact — it is not JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: not a pact — the document is not a JSON object")
    return PactFile(
        path=path,
        consumer=_pacticipant_name(document, "consumer", path),
        provider=_pacticipant_name(document, "provider", path),
        content=content,
    )


def build_publish_bodies(
    pacts: Sequence[PactFile],
    *,
    consumer_app_version: str,
    branch: Optional[str],
    tags: Optional[Sequence[str]],
    build_url: Optional[str],
) -> list[dict[str, Any]]:
    """The ``POST …/contracts/publish`` bodies for some pacts: one per consumer, ≤ 100 pacts each.

    ``pact-broker publish`` sends one request per consumer, since a request publishes the pacts of
    one consumer version. The same holds here; a consumer with more than 100 pacts is split.

    Args:
        pacts: The pacts, in the order read.
        consumer_app_version: The consumer version (``-a``).
        branch: Its branch.
        tags: Its tags.
        build_url: The CI build URL.

    Returns:
        The bodies, consumers in first-seen order.

    Raises:
        ValueError: when the consumer version is empty.
    """
    version = (consumer_app_version or "").strip()
    if not version:
        raise ValueError("--consumer-app-version is empty")
    by_consumer: dict[str, list[PactFile]] = {}
    for pact in pacts:
        by_consumer.setdefault(pact.consumer, []).append(pact)
    bodies: list[dict[str, Any]] = []
    for consumer, group in by_consumer.items():
        for start in range(0, len(group), MAX_CONTRACTS_PER_PUBLISH):
            body: dict[str, Any] = {
                "pacticipantName": consumer,
                "pacticipantVersionNumber": version,
                "contracts": [
                    {
                        "consumerName": pact.consumer,
                        "providerName": pact.provider,
                        "specification": "pact",
                        "contentType": "application/json",
                        "content": base64.b64encode(pact.content).decode("ascii"),
                    }
                    for pact in group[start : start + MAX_CONTRACTS_PER_PUBLISH]
                ],
            }
            if branch:
                body["branch"] = branch
            if tags:
                body["tags"] = list(tags)
            if build_url:
                body["buildUrl"] = build_url
            bodies.append(body)
    return bodies


# ---------------------------------------------------------------------------------------------
# --auto-detect-version-properties
# ---------------------------------------------------------------------------------------------

#: CI variables naming the branch, in ``pact-broker``'s order of preference.
_BRANCH_VARIABLES = (
    "GITHUB_HEAD_REF",  # GitHub Actions, pull requests
    "GITHUB_REF_NAME",  # GitHub Actions, pushes
    "CI_COMMIT_REF_NAME",  # GitLab
    "BUILDKITE_BRANCH",
    "CIRCLE_BRANCH",
    "TRAVIS_BRANCH",
    "BITBUCKET_BRANCH",
    "APPVEYOR_REPO_BRANCH",
    "CI_BRANCH",  # CodeShip
    "BUILD_SOURCEBRANCHNAME",  # Azure DevOps
    "GIT_BRANCH",  # Jenkins, Hudson
    "BRANCH_NAME",  # Jenkins multibranch
)

#: CI variables holding the build URL.
_BUILD_URL_VARIABLES = ("CI_JOB_URL", "BUILDKITE_BUILD_URL", "CIRCLE_BUILD_URL", "BUILD_URL")


def _git_branch() -> Optional[str]:
    """The checked-out branch from ``git``, or ``None`` (detached HEAD, no git, no repository)."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = completed.stdout.strip()
    return name if completed.returncode == 0 and name and name != "HEAD" else None


@dataclass(frozen=True)
class VersionProperties:
    """The branch and build URL detected for a version.

    Attributes:
        branch: The branch, or ``None`` when none could be detected.
        build_url: The build URL, or ``None``.
    """

    branch: Optional[str]
    build_url: Optional[str]


def detect_version_properties(
    environ: Mapping[str, str], *, git_branch: Callable[[], Optional[str]] = _git_branch
) -> VersionProperties:
    """Detect the branch and build URL the way ``pact-broker … --auto-detect-version-properties`` does.

    Args:
        environ: The environment.
        git_branch: Reads the branch from git when no CI variable names one (tests replace it).

    Returns:
        What was found; Jenkins' ``origin/`` prefix is removed from the branch.
    """
    branch = next((environ[name].strip() for name in _BRANCH_VARIABLES if environ.get(name, "").strip()), None)
    if branch and branch.startswith("origin/"):
        branch = branch[len("origin/") :]
    if not branch:
        branch = git_branch()
    build_url: Optional[str] = None
    if environ.get("GITHUB_RUN_ID") and environ.get("GITHUB_REPOSITORY"):
        server = environ.get("GITHUB_SERVER_URL") or "https://github.com"
        build_url = f"{server.rstrip('/')}/{environ['GITHUB_REPOSITORY']}/actions/runs/{environ['GITHUB_RUN_ID']}"
    else:
        build_url = next((environ[name] for name in _BUILD_URL_VARIABLES if environ.get(name)), None)
    return VersionProperties(branch=branch, build_url=build_url)


# ---------------------------------------------------------------------------------------------
# can-i-deploy
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CanIDeployQuery:
    """What ``can-i-deploy`` asks.

    Attributes:
        pacticipant: The pacticipant being deployed.
        version: Its version, or ``None`` with ``latest`` / ``branch`` / ``main_branch``.
        latest: Its latest version (with ``tag``: the latest with that tag).
        tag: The tag ``latest`` reads.
        branch: The latest version from this branch.
        main_branch: The latest version from its main branch.
        to_environment: Where it is deployed.
        to: The tag it is deployed to (legacy).
        ignore: Pacticipants left out of the verdict.
    """

    pacticipant: str
    version: Optional[str] = None
    latest: bool = False
    tag: Optional[str] = None
    branch: Optional[str] = None
    main_branch: bool = False
    to_environment: Optional[str] = None
    to: Optional[str] = None
    ignore: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        """Refuse a query the broker would refuse, naming the flags.

        Raises:
            ValueError: when the version is not named exactly one way, or both targets are given.
        """
        if not self.pacticipant.strip():
            raise ValueError("--pacticipant is empty")
        ways = [self.version is not None, self.latest, self.branch is not None, self.main_branch]
        if sum(ways) != 1:
            raise ValueError("name the version exactly one way: --version, --latest, --branch or --main-branch")
        if self.tag is not None and not self.latest:
            raise ValueError("--tag reads the latest version with that tag; give it with --latest")
        if self.to_environment and self.to:
            raise ValueError("give --to-environment or --to, not both")

    def matrix_params(self) -> list[tuple[str, str]]:
        """The ``GET …/matrix`` query, as ``pact-broker can-i-deploy`` sends it.

        Returns:
            ``(name, value)`` pairs, in order: the selector, ``latestby=cvp``, the target, the ignores.
        """
        params: list[tuple[str, str]] = [("q[][pacticipant]", self.pacticipant)]
        if self.version is not None:
            params.append(("q[][version]", self.version))
        if self.latest:
            params.append(("q[][latest]", "true"))
            if self.tag:
                params.append(("q[][tag]", self.tag))
        if self.branch is not None:
            params.append(("q[][branch]", self.branch))
        if self.main_branch:
            params.append(("q[][mainBranch]", "true"))
        params.append(("latestby", "cvp"))
        if self.to_environment:
            params.append(("environment", self.to_environment))
        else:
            params.append(("latest", "true"))
            if self.to:
                params.append(("tag", self.to))
        params.extend(("ignore[][pacticipant]", name) for name in self.ignore)
        return params


def deployable(document: Mapping[str, Any]) -> Optional[bool]:
    """``summary.deployable`` of a matrix document: ``True``, ``False`` or ``None`` (unknown)."""
    summary = document.get("summary")
    value = summary.get("deployable") if isinstance(summary, dict) else None
    return value if isinstance(value, bool) else None


# ---------------------------------------------------------------------------------------------
# create-environment
# ---------------------------------------------------------------------------------------------


def build_environment_body(
    *,
    name: str,
    display_name: Optional[str],
    production: bool,
    contract_required: bool,
    contact_name: Optional[str],
    contact_email_address: Optional[str],
) -> dict[str, Any]:
    """The ``POST …/environments`` body.

    Args:
        name: The name tooling uses (one word).
        display_name: The name people read.
        production: Whether it is a production environment.
        contract_required: Apiome: can-i-deploy refuses a pacticipant without a contract.
        contact_name: A contact's name.
        contact_email_address: That contact's email address.

    Returns:
        The body.

    Raises:
        ValueError: when the name is empty or has whitespace, or an email has no contact name.
    """
    text = name.strip()
    if not text or any(ch.isspace() for ch in text):
        raise ValueError("--name must be one word, with no spaces")
    body: dict[str, Any] = {"name": text, "production": production}
    if display_name:
        body["displayName"] = display_name
    if contract_required:
        body["contractRequired"] = True
    if contact_email_address and not contact_name:
        raise ValueError("--contact-email-address needs --contact-name")
    if contact_name:
        contact: dict[str, Any] = {"name": contact_name}
        if contact_email_address:
            contact["details"] = {"emailAddress": contact_email_address}
        body["contacts"] = [contact]
    return body


def embedded_environments(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``_embedded.environments`` of an environment list, or ``[]``."""
    embedded = document.get("_embedded")
    items = embedded.get("environments") if isinstance(embedded, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


# ---------------------------------------------------------------------------------------------
# create-webhook
# ---------------------------------------------------------------------------------------------


def _headers(values: Sequence[str]) -> dict[str, str]:
    """``-H "Name: value"`` options as a dict, or a :class:`ValueError` naming the bad one."""
    headers: dict[str, str] = {}
    for raw in values:
        name, sep, value = raw.partition(":")
        if not sep or not name.strip():
            raise ValueError(f"--header {raw!r}: write it as 'Name: value'")
        headers[name.strip()] = value.strip()
    return headers


def _body(data: Optional[str], *, read_file: Callable[[str], str]) -> Any:
    """``-d`` as the webhook body: ``@file`` reads a file; JSON text becomes a JSON value."""
    if data is None:
        return None
    text = read_file(data[1:]) if data.startswith("@") else data
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _read_text(path: str) -> str:
    """The text of a file named by ``-d @file``."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"--data @{path}: {exc.strerror or exc}") from exc


def build_webhook_body(
    *,
    url: str,
    method: str,
    headers: Sequence[str],
    data: Optional[str],
    user: Optional[str],
    consumer: Optional[str],
    provider: Optional[str],
    description: Optional[str],
    events: Sequence[str],
    read_file: Callable[[str], str] = _read_text,
) -> dict[str, Any]:
    """The ``POST …/webhooks`` body, from ``pact-broker create-webhook``'s options.

    Args:
        url: The URL the webhook calls.
        method: ``-X`` (``POST``, ``PUT`` or ``PATCH``).
        headers: ``-H`` values, ``Name: value``.
        data: ``-d``: a body, or ``@file``.
        user: ``-u user:password``.
        consumer: Only pacts of this consumer.
        provider: Only pacts of this provider.
        description: Free text.
        events: The broker event names chosen by the event flags.
        read_file: Reads ``@file`` (tests replace it).

    Returns:
        The body.

    Raises:
        ValueError: when the method is not one the broker accepts, no event is chosen, the URL is
            not http(s), or a header or user is malformed.
    """
    verb = method.strip().upper()
    if verb not in WEBHOOK_METHODS:
        raise ValueError(f"--request {method}: the broker sends webhooks as {', '.join(WEBHOOK_METHODS)} only")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"{url!r}: the webhook URL must be http(s)")
    if not events:
        raise ValueError(
            "choose at least one event: " + ", ".join("--" + name.replace("_", "-") for name in WEBHOOK_EVENTS)
        )
    request: dict[str, Any] = {"method": verb, "url": url}
    parsed_headers = _headers(headers)
    if parsed_headers:
        request["headers"] = parsed_headers
    body = _body(data, read_file=read_file)
    if body is not None:
        request["body"] = body
    if user is not None:
        username, sep, password = user.partition(":")
        if not sep or not username:
            raise ValueError("--user: write it as 'username:password'")
        request["username"] = username
        request["password"] = password
    document: dict[str, Any] = {"events": [{"name": name} for name in events], "request": request}
    if description:
        document["description"] = description
    if consumer:
        document["consumer"] = {"name": consumer}
    if provider:
        document["provider"] = {"name": provider}
    return document


# ---------------------------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------------------------


def parse_selectors(values: Sequence[str]) -> list[dict[str, Any]]:
    """``--consumer-version-selector`` JSON objects, as ``pact_verifier_cli`` takes them.

    Args:
        values: One JSON object per option (``{"mainBranch": true}``).

    Returns:
        The selectors.

    Raises:
        ValueError: when a value is not a JSON object.
    """
    selectors: list[dict[str, Any]] = []
    for raw in values:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--consumer-version-selector {raw!r}: not JSON ({exc.msg})") from exc
        if not isinstance(value, dict):
            raise ValueError(f"--consumer-version-selector {raw!r}: must be a JSON object")
        selectors.append(value)
    return selectors


def parse_context(values: Sequence[str]) -> dict[str, str]:
    """``--context KEY=VALUE`` options as a dict, or a :class:`ValueError` naming the bad one."""
    context: dict[str, str] = {}
    for raw in values:
        key, sep, value = raw.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--context {raw!r}: write it as KEY=VALUE")
        context[key.strip()] = value
    return context


def build_verify_body(
    *,
    target: str,
    provider_app_version: str,
    branch: Optional[str],
    build_url: Optional[str],
    selectors: Sequence[dict[str, Any]],
    include_pending: bool,
    include_wip_pacts_since: Optional[str],
    allow_mutating: bool,
    replay_without_state_setup: bool,
    publish: bool,
    context: Mapping[str, str],
) -> dict[str, Any]:
    """The ``POST …/pact-verifier/pacts/provider/{p}/verify`` body.

    Args:
        target: The verification target's slug or id.
        provider_app_version: The provider build's version.
        branch: Its branch.
        build_url: The CI build URL.
        selectors: Consumer version selectors; empty selects the broker's default.
        include_pending: Ask for pending status (a pending pact's failure does not fail the run).
        include_wip_pacts_since: Include work-in-progress pacts published since this date.
        allow_mutating: Replay ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` interactions.
        replay_without_state_setup: Replay interactions whose provider state nothing sets up.
        publish: Publish the results (``False`` is a dry run).
        context: Non-secret CI context.

    Returns:
        The body, with only what was given.
    """
    selection: dict[str, Any] = {}
    if selectors:
        selection["consumerVersionSelectors"] = list(selectors)
    if include_pending:
        selection["includePendingStatus"] = True
    if include_wip_pacts_since:
        selection["includeWipPactsSince"] = include_wip_pacts_since
    body: dict[str, Any] = {"target_ref": target, "provider_version": provider_app_version, "publish": publish}
    if branch:
        body["provider_branch"] = branch
    if build_url:
        body["build_url"] = build_url
    if selection:
        body["selection"] = selection
    verification: dict[str, Any] = {}
    if allow_mutating:
        verification["allow_mutating"] = True
    if replay_without_state_setup:
        verification["replay_without_state_setup"] = True
    if verification:
        body["verification"] = verification
    if context:
        body["context"] = dict(context)
    return body
