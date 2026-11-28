"""The Contracts set-up's two GitHub actions — PFX-8.20 (#7317).

**Connect your pipelines** can write ``PACT_BROKER_BASE_URL`` and ``PACT_BROKER_TOKEN`` into a
registered repository as Actions secrets, and **Gate deploys** can open a pull request adding the
workflow of :func:`app.pact_setup.workflow_text`. Both use the token of the GitHub account the
repository was registered with (:func:`app.repository_webhook_rotation.resolve_linked_account_token`)
through :class:`app.sdk_git_delivery_github.GitHubGitClient`, so requests only ever go to
``api.github.com`` and no token reaches a command line or a working copy.

**Nothing fails as a whole and nothing is dropped.** Each repository asked for ends as one result:
``written`` / ``opened`` / ``exists``, or ``skipped`` with a reason a person can act on (not this
workspace's repository, not GitHub, no linked account, the token was refused, a branch rule). A
skipped pull request still answers with the workflow's text, so it can be added by hand.

**Nothing is done twice.** A repository whose default branch already holds the same workflow is
skipped as already set up; an open pull request from :data:`app.pact_setup.SETUP_BRANCH` is
answered as ``exists``; writing a secret again replaces its value, which is what a re-run means.

**Secrets.** GitHub takes a secret sealed to the repository's public key (a libsodium sealed box).
The key value passes through memory only: it is not stored, logged or audited, and every message
is redacted of both tokens before it leaves this module.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import httpx

from .pact_setup import (
    SECRET_NAMES,
    SETUP_BRANCH,
    WORKFLOW_PATH,
    PactSetupPullRequestResult,
    PactSetupPullRequestsRequest,
    PactSetupSecretsResult,
    workflow_text,
)
from .pact_setup_store import get_repository, is_writable
from .repository_webhook_rotation import resolve_linked_account_token
from .sdk_git_delivery_changes import FILE_MODE
from .sdk_git_delivery_github import ClientFactory, GitHubGitClient, GitProviderError, _github_message
from .sdk_registry_credentials import redact_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "PULL_REQUEST_TITLE",
    "SetupGitHubClient",
    "open_pull_requests",
    "seal_secret",
    "write_secrets",
]

#: The pull request's title and its commit's message.
PULL_REQUEST_TITLE = "Add Apiome contract checks"

_NOT_FOUND = "This repository is not registered in this workspace."
_NOT_GITHUB = "Only github.com repositories can be written to; add this one by hand."
_NOT_LINKED = (
    "This repository was registered without a linked GitHub account, so Apiome has no token to write "
    "with. Add it by hand, or register the repository again with a linked account."
)
_NO_TOKEN = (
    "The GitHub account this repository was registered with no longer holds a token. Re-link the "
    "account, then try again — or add it by hand."
)

#: How a sealing function is obtained; tests inject one so they need no key pair.
Sealer = Callable[[str, str], str]


def seal_secret(public_key_b64: str, value: str) -> str:
    """Seal a secret to a repository's Actions public key.

    Args:
        public_key_b64: The key GitHub answered with, base64.
        value: The secret's value.

    Returns:
        The sealed box, base64 — what ``PUT …/actions/secrets/{name}`` takes as ``encrypted_value``.

    Raises:
        RuntimeError: When PyNaCl is not installed, or the key is not a Curve25519 public key.
    """
    try:
        from nacl import encoding, public
    except ImportError as exc:  # pragma: no cover - the dependency is declared
        raise RuntimeError("PyNaCl is not installed, so a secret cannot be sealed for GitHub") from exc
    try:
        box = public.SealedBox(public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder))
    except Exception as exc:
        raise RuntimeError("GitHub's public key for this repository could not be read") from exc
    return base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")


class SetupGitHubClient(GitHubGitClient):
    """:class:`GitHubGitClient` plus Actions secrets, with refusals worded for the set-up page.

    Args:
        token: The repository's linked-account token.
        full_name: ``owner/repo``.
        client_factory: How to obtain the HTTP client.
        also_redact: Other secrets (the key being stored) to scrub from every message.
    """

    def __init__(
        self,
        token: str,
        full_name: str,
        *,
        client_factory: Optional[ClientFactory] = None,
        also_redact: Tuple[str, ...] = (),
    ) -> None:
        super().__init__(token, full_name, client_factory=client_factory)
        self._also_redact = tuple(value for value in also_redact if value)

    def _redact(self, text: str) -> str:
        """Scrub the linked-account token and the key being stored."""
        return redact_secrets(super()._redact(text), list(self._also_redact), marker="[secret-redacted]")

    def _error(self, response: httpx.Response, *, what: str, kind: str) -> GitProviderError:
        """Translate a refusal into a reason worded for the set-up (no "deliver again")."""
        status = response.status_code
        detail = _github_message(response)
        repo = self._full_name
        rate_limited = response.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in detail.lower()
        if status == 429 or (status == 403 and rate_limited):
            message = f"GitHub's rate limit for the linked account was reached while {what}. Try again later."
            code, retryable = "pact-setup-github-rate-limited", True
        elif status == 401:
            message = (
                f"GitHub rejected the linked account's token while {what}. Re-link the GitHub account that "
                f"registered {repo}, then try again."
            )
            code, retryable = "pact-setup-github-token-rejected", False
        elif status in (403, 404):
            message = (
                f"The linked account may not do this in {repo} (HTTP {status} while {what}: {detail}). It needs "
                "admin access for secrets and write access for a pull request; a fine-grained token also needs "
                "the Secrets, Contents, Workflows and Pull requests permissions."
            )
            code, retryable = "pact-setup-github-not-allowed", False
        elif status >= 500:
            message = f"GitHub failed while {what} (HTTP {status}). Try again."
            code, retryable = "pact-setup-github-unavailable", True
        else:
            message = f"GitHub refused the request while {what} (HTTP {status}: {detail})."
            code, retryable = "pact-setup-github-refused", False
        return GitProviderError(code, self._redact(message), http_status=status, retryable=retryable)

    def get_actions_public_key(self) -> Tuple[str, str]:
        """Read the key Actions secrets are sealed to.

        Returns:
            ``(key_id, key)`` — the key base64.

        Raises:
            GitProviderError: When the token may not manage the repository's secrets.
        """
        response = self._request(
            "GET", "/actions/secrets/public-key", what="reading the repository's secrets key", kind="write"
        )
        payload = response.json() or {}
        key_id, key = str(payload.get("key_id") or ""), str(payload.get("key") or "")
        if not key_id or not key:
            raise GitProviderError("pact-setup-github-refused", "GitHub answered without a secrets key.")
        return key_id, key

    def put_actions_secret(self, name: str, encrypted_value: str, key_id: str) -> None:
        """Create or replace one Actions secret.

        Args:
            name: The secret's name.
            encrypted_value: The value sealed to the repository's key, base64.
            key_id: The id of that key.

        Raises:
            GitProviderError: When GitHub refuses it.
        """
        self._request(
            "PUT",
            f"/actions/secrets/{name}",
            what=f"writing the secret {name}",
            kind="write",
            ok=(201, 204),
            json={"encrypted_value": encrypted_value, "key_id": key_id},
        )


def _now() -> str:
    """The current UTC time, ISO-8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target(
    db: Any, tenant_id: str, repository_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Resolve a repository to ``(row, token, reason)``; ``reason`` says why it cannot be written."""
    repository = get_repository(db.execute_query, tenant_id, repository_id)
    if repository is None:
        return None, None, _NOT_FOUND
    if str(repository.get("provider") or "").lower() != "github" or not repository.get("repository_full_name"):
        return repository, None, _NOT_GITHUB
    if not is_writable(repository):
        return repository, None, _NOT_LINKED
    token = resolve_linked_account_token(db, repository)
    if not token:
        return repository, None, _NO_TOKEN
    return repository, token, None


def write_secrets(
    db: Any,
    tenant_id: str,
    repository_ids: List[str],
    *,
    broker_base_url: str,
    token: str,
    client_factory: Optional[ClientFactory] = None,
    sealer: Sealer = seal_secret,
) -> Tuple[List[PactSetupSecretsResult], Dict[str, Dict[str, Any]]]:
    """Write the two broker secrets into each repository.

    Args:
        db: The database.
        tenant_id: The caller's tenant; a repository of another tenant is skipped as not found.
        repository_ids: The registered repositories, each handled once.
        broker_base_url: The value of ``PACT_BROKER_BASE_URL`` (already checked).
        token: The value of ``PACT_BROKER_TOKEN``. Never stored or logged.
        client_factory: How to obtain the HTTP client (tests).
        sealer: How a value is sealed to a public key (tests).

    Returns:
        One result per distinct repository id, in the order given, and the progress updates
        (``{repository_id: {"secrets_at": …}}``) for the ones written.
    """
    values = dict(zip(SECRET_NAMES, (broker_base_url, token)))
    results: List[PactSetupSecretsResult] = []
    updates: Dict[str, Dict[str, Any]] = {}
    for repository_id in dict.fromkeys(str(item) for item in repository_ids):
        repository, github_token, reason = _target(db, tenant_id, repository_id)
        full_name = str((repository or {}).get("repository_full_name") or "") or None
        if reason or not github_token or not full_name:
            results.append(
                PactSetupSecretsResult(
                    repository_id=repository_id, full_name=full_name, status="skipped", reason=reason
                )
            )
            continue
        written: List[str] = []
        try:
            with SetupGitHubClient(
                github_token, full_name, client_factory=client_factory, also_redact=(token,)
            ) as github:
                key_id, key = github.get_actions_public_key()
                for name in SECRET_NAMES:
                    github.put_actions_secret(name, sealer(key, values[name]), key_id)
                    written.append(name)
        except (GitProviderError, RuntimeError) as exc:
            message = redact_secrets(str(exc), [token, github_token], marker="[secret-redacted]")
            if written:
                message = f"{message} Written before that: {', '.join(written)}."
            logger.info("pact set-up secrets skipped repository_id=%s", repository_id)
            results.append(
                PactSetupSecretsResult(
                    repository_id=repository_id, full_name=full_name, status="skipped", reason=message, names=written
                )
            )
            continue
        updates[repository_id] = {"secrets_at": _now()}
        results.append(
            PactSetupSecretsResult(
                repository_id=repository_id, full_name=full_name, status="written", names=list(SECRET_NAMES)
            )
        )
    return results, updates


def _pull_request_body(pacticipant: str, environment: str, body: PactSetupPullRequestsRequest) -> str:
    """The pull request's description."""
    steps = []
    if body.can_i_deploy:
        steps.append(
            f"- asks Apiome **can-i-deploy** for `{pacticipant}` to `{environment}` on every pull request and push"
        )
    if body.record_deployment:
        steps.append(
            f"- **records the deployment** of `{pacticipant}` to `{environment}` after a push to the default branch"
        )
    return "\n".join(
        [
            f"Adds `{WORKFLOW_PATH}`, which:",
            "",
            *steps,
            "",
            "It reads `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN` from this repository's Actions secrets.",
            "Put your deploy step before the record-deployment step, or move that step into your deploy workflow.",
            "",
            "Opened from Apiome's Contracts set-up.",
        ]
    )


def _open_one(
    github: SetupGitHubClient, content: str, description: str
) -> Tuple[str, Optional[str], Optional[str], Optional[int]]:
    """Open the pull request in one repository: ``(status, reason, url, number)``."""
    info = github.get_repository()
    if info.archived:
        return "skipped", f"{info.full_name} is archived, so nothing can be added to it.", None, None
    if not info.can_push:
        return "skipped", f"The linked account cannot push to {info.full_name}. Add the workflow by hand.", None, None
    base = info.default_branch
    base_sha = github.get_branch_sha(base)
    if not base_sha:
        return (
            "skipped",
            f"{info.full_name} has no commits on {base} yet. Push a first commit, then try again.",
            None,
            None,
        )
    root = github.get_commit_tree_sha(base_sha)
    present = github.find_file(root, WORKFLOW_PATH, ref_label=base)
    if present is not None and github.get_blob_text(present.sha) == content:
        return "skipped", f"{WORKFLOW_PATH} is already on {base} with this content: nothing to add.", None, None
    open_pull = github.find_open_pull(info.owner, SETUP_BRANCH)
    tree = github.create_tree(root, [{"path": WORKFLOW_PATH, "mode": FILE_MODE, "type": "blob", "content": content}])
    commit = github.create_commit(PULL_REQUEST_TITLE, tree, [base_sha])
    if not github.create_branch(SETUP_BRANCH, commit):
        # The branch is ours (an earlier run): rebuild it on the current base with the current file.
        github.update_branch(SETUP_BRANCH, commit, force=True)
    if open_pull is not None:
        return (
            "exists",
            "A pull request from the set-up is already open; its branch now has this workflow.",
            open_pull.url,
            open_pull.number,
        )
    pull = github.create_pull(title=PULL_REQUEST_TITLE, body=description, head=SETUP_BRANCH, base=base)
    if pull is None:
        found = github.find_open_pull(info.owner, SETUP_BRANCH)
        return (
            "exists",
            "A pull request from the set-up is already open.",
            (found.url if found else None),
            (found.number if found else None),
        )
    return "opened", None, pull.url, pull.number


def open_pull_requests(
    db: Any,
    tenant_id: str,
    body: PactSetupPullRequestsRequest,
    *,
    client_factory: Optional[ClientFactory] = None,
) -> Tuple[List[PactSetupPullRequestResult], Dict[str, Dict[str, Any]]]:
    """Open (or preview) the workflow pull request in each repository.

    Args:
        db: The database.
        tenant_id: The caller's tenant; a repository of another tenant is skipped as not found.
        body: The repositories with their pacticipants, the environment, the steps, and ``preview``.
        client_factory: How to obtain the HTTP client (tests).

    Returns:
        One result per distinct repository, in the order given — each with the workflow's text —
        and the progress updates (``{repository_id: {"pull_request_url": …, "pull_request_number": …}}``)
        for the pull requests opened or found.

    Raises:
        ValueError: When no step is chosen, or a pacticipant or the environment cannot be written
            into a workflow (a line break). Nothing is sent to GitHub in that case.
    """
    chosen: Dict[str, str] = {}
    for item in body.repositories:
        chosen.setdefault(str(item.repository_id), item.pacticipant)
    # Check every workflow before the first GitHub call, so a bad name stops the whole request.
    for pacticipant in chosen.values():
        workflow_text(
            pacticipant=pacticipant,
            environment=body.environment,
            can_i_deploy=body.can_i_deploy,
            record_deployment=body.record_deployment,
        )
    results: List[PactSetupPullRequestResult] = []
    updates: Dict[str, Dict[str, Any]] = {}
    for repository_id, pacticipant in chosen.items():
        repository: Optional[Mapping[str, Any]] = get_repository(db.execute_query, tenant_id, repository_id)
        full_name = str((repository or {}).get("repository_full_name") or "") or None
        content = workflow_text(
            pacticipant=pacticipant,
            environment=body.environment,
            default_branch=str((repository or {}).get("default_branch") or "main"),
            can_i_deploy=body.can_i_deploy,
            record_deployment=body.record_deployment,
        )

        def result(
            status: str, reason: Optional[str] = None, url: Optional[str] = None, number: Optional[int] = None
        ) -> PactSetupPullRequestResult:
            """One repository's result, always with the workflow."""
            return PactSetupPullRequestResult(
                repository_id=repository_id,
                full_name=full_name,
                status=status,  # type: ignore[arg-type]
                reason=reason,
                url=url,
                number=number,
                path=WORKFLOW_PATH,
                content=content,
            )

        if repository is None:
            results.append(result("skipped", _NOT_FOUND))
            continue
        if body.preview:
            results.append(result("preview"))
            continue
        _, github_token, reason = _target(db, tenant_id, repository_id)
        if reason or not github_token or not full_name:
            results.append(result("skipped", reason))
            continue
        try:
            with SetupGitHubClient(github_token, full_name, client_factory=client_factory) as github:
                status, why, url, number = _open_one(
                    github, content, _pull_request_body(pacticipant, body.environment, body)
                )
        except GitProviderError as exc:
            logger.info("pact set-up pull request skipped repository_id=%s code=%s", repository_id, exc.code)
            results.append(result("skipped", exc.message))
            continue
        if status in ("opened", "exists") and url:
            updates[repository_id] = {"pull_request_url": url, "pull_request_number": number}
        results.append(result(status, why, url, number))
    return results, updates
