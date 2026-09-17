"""Publishing a normalized check to a git provider — GNC-2.2 (#4738).

The one place a repository token leaves this process on the check path. Everything above this
module thinks in the four words :mod:`app.provider_checks` defines; this module turns one of them
into the single REST call the named provider actually wants, and turns every refusal into a
:class:`StatusPublishError` carrying a stable code.

**One interface, three providers.** :class:`StatusAdapter` is the whole contract — a
``publish(request) -> PublishedStatus``. The ticket asks for GitHub first and GitLab and Bitbucket
"through the same interface", and the reason that is more than tidiness is that the three APIs
disagree about almost everything:

===========  ===========================================================================
``github``   ``POST /repos/{owner}/{repo}/check-runs``, or ``PATCH .../check-runs/{id}``
             once the provider has given us an id. A status is split into ``status`` and
             ``conclusion``, and the human text lives in a nested ``output`` object.
``gitlab``   ``POST /projects/{id}/statuses/{sha}``, everything in the query-shaped body,
             the project addressed by its URL-encoded path.
``bitbucket````POST /repositories/{workspace}/{repo}/commit/{sha}/statuses/build``, with a
             caller-chosen ``key`` that makes the call an upsert.
===========  ===========================================================================

Three shapes, one caller-visible behaviour: "put this verdict on this commit". A check recorded
before an adapter existed reads back identically after one does, and a fourth provider is a class
here and nothing anywhere else.

**The host is fixed per provider.** Requests only ever go to the provider's documented API host,
never to a URL a tenant configured, so there is no server-side request forgery surface to guard —
the same reasoning :mod:`app.sdk_git_delivery_github` gives.

**Nothing here reads the database, and nothing here holds a token beyond the call.** The token
arrives as an argument, resolved server-side by :mod:`app.provider_check_store` from the
registration the binding was authorized through, and every message raised passes through
:func:`app.sdk_registry_credentials.redact_secrets` first, because a provider's error body is
outside our control and a check delivery row is read straight into an API response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import quote

import httpx

from .provider_checks import (
    CODE_PROVIDER_FORBIDDEN,
    CODE_PROVIDER_REFUSED,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_PROVIDER_UNSUPPORTED,
    bitbucket_state,
    github_conclusion,
    github_status,
    gitlab_state,
    request_fingerprint,
)
from .sdk_registry_credentials import redact_secrets

logger = logging.getLogger(__name__)

__all__ = [
    "BITBUCKET_API_URL",
    "BitbucketStatusAdapter",
    "ClientFactory",
    "GITHUB_API_URL",
    "GITLAB_API_URL",
    "GitHubCheckRunAdapter",
    "GitLabStatusAdapter",
    "PublishRequest",
    "PublishedStatus",
    "REQUEST_TIMEOUT_SECONDS",
    "STATUS_TOKEN_REDACTION_MARKER",
    "StatusAdapter",
    "StatusPublishError",
    "adapter_for",
    "supported_providers",
]

#: The only hosts a check publish talks to, one per provider.
GITHUB_API_URL = "https://api.github.com"
GITLAB_API_URL = "https://gitlab.com/api/v4"
BITBUCKET_API_URL = "https://api.bitbucket.org/2.0"

#: Per-request timeout. A publish is one small call, and it happens on the webhook ingestion path,
#: where a provider is already counting the seconds before it decides the delivery failed. Shorter
#: than the SDK delivery's 30s for exactly that reason.
REQUEST_TIMEOUT_SECONDS = 10.0

#: What a repository token becomes if a provider quotes it back at us.
STATUS_TOKEN_REDACTION_MARKER = "[repository-token-redacted]"

#: How much of a provider's error message is kept.
_MESSAGE_MAX_CHARS = 400

#: The GitHub REST API version every request pins.
_GITHUB_API_VERSION = "2022-11-28"

#: Identifies the caller in each provider's audit log.
_USER_AGENT = "apiome-provider-checks"

#: How an :class:`httpx.Client` is obtained. Injected so tests drive the whole protocol without a
#: network, exactly as SDK-4.2 does.
ClientFactory = Callable[[], httpx.Client]


class StatusPublishError(RuntimeError):
    """A publish the provider did not accept.

    Attributes:
        code: A stable reason (one of :mod:`app.provider_checks`'s ``CODE_PROVIDER_*``).
        message: What happened, already redacted.
        http_status: The provider's status code, when there was a response.
        retryable: Whether trying again unchanged could plausibly succeed.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        """Create the failure.

        Args:
            code: The stable reason code.
            message: The redacted explanation.
            http_status: The provider's status code, when there was a response.
            retryable: Whether an unchanged retry could succeed.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


@dataclass(frozen=True)
class PublishRequest:
    """One verdict, ready to be put on a commit.

    Attributes:
        repo_full_name: Lowercased ``owner/name`` (Bitbucket's ``workspace/repo``).
        commit_sha: The commit the verdict is about.
        name: The check's stable name; every provider uses it as the upsert key.
        state: The normalized state — ``pending``, ``pass``, ``fail`` or ``skipped``.
        title: The one-line title a reviewer sees.
        summary: The longer explanation.
        details_url: Where the check points a reviewer.
        external_id: The provider's own id for the check, when a previous publish returned one.
    """

    repo_full_name: str
    commit_sha: str
    name: str
    state: str
    title: str = ""
    summary: str = ""
    details_url: str = ""
    external_id: Optional[str] = None


@dataclass(frozen=True)
class PublishedStatus:
    """What the provider did with a verdict.

    Attributes:
        provider: The provider key the call went to.
        status_code: The provider's HTTP status.
        external_id: The provider's id for the check, when it returned one.
        fingerprint: :func:`app.provider_checks.request_fingerprint` of the call that was made —
            the key V265 collides on so an identical publish is never sent twice.
        url: The provider's URL for the published check, when it returned one.
    """

    provider: str
    status_code: int
    fingerprint: str
    external_id: Optional[str] = None
    url: Optional[str] = None


def _default_client_factory() -> httpx.Client:
    """Build the client every publish goes through.

    Returns:
        A client with a bounded timeout that follows the provider's own redirects (a renamed
        repository answers with one).
    """
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)


def _split_full_name(repo_full_name: str) -> Tuple[str, str]:
    """Split ``owner/name`` into its two halves.

    Args:
        repo_full_name: The repository's full name.

    Returns:
        ``(owner, name)``.

    Raises:
        StatusPublishError: ``check-provider-refused`` when the name is not ``owner/name``. A
            malformed name is refused rather than guessed at, because guessing would mean putting
            a verdict on somebody else's repository.
    """
    parts = [part for part in str(repo_full_name or "").strip().strip("/").split("/") if part]
    if len(parts) < 2:
        raise StatusPublishError(
            CODE_PROVIDER_REFUSED,
            f"{repo_full_name!r} is not a repository full name of the form owner/name.",
        )
    # A GitLab project path may be nested (group/subgroup/project); the last segment is the
    # project and everything before it is the namespace.
    return "/".join(parts[:-1]), parts[-1]


def _provider_message(response: httpx.Response, token: Optional[str]) -> str:
    """Extract a provider's own explanation from an error response, redacted.

    Every provider nests its message somewhere different, and a body that is not JSON at all is
    entirely possible (a proxy's HTML error page), so this reads the shapes it knows and falls
    back to the raw text. Whatever it finds is bounded, whitespace-collapsed, and passed through
    the redactor before any caller sees it.

    Args:
        response: The failed response.
        token: The token in play, so it can be redacted if the provider quoted it.

    Returns:
        A short, redacted explanation; ``"no detail"`` when the body carried none.
    """
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None

    text = ""
    if isinstance(payload, Mapping):
        # GitHub: {"message": ...}; GitLab: {"message": ...} or {"error": ...};
        # Bitbucket: {"error": {"message": ...}}.
        candidate = payload.get("message") or payload.get("error") or payload.get("error_description")
        if isinstance(candidate, Mapping):
            candidate = candidate.get("message")
        if isinstance(candidate, (list, tuple)):
            candidate = "; ".join(str(item) for item in candidate)
        text = str(candidate or "").strip()
    if not text:
        text = (response.text or "").strip()

    text = " ".join(text.split())[:_MESSAGE_MAX_CHARS]
    redacted = redact_secrets(
        text, [token] if token else [], marker=STATUS_TOKEN_REDACTION_MARKER
    )
    return redacted or "no detail"


def _raise_for_response(
    response: httpx.Response, *, provider: str, token: Optional[str]
) -> None:
    """Turn a non-2xx provider response into the failure that names what to do about it.

    The mapping is the same for all three providers because their status codes mean the same
    things: 401 is a credential that is no longer good, 403/404 is a credential without the right
    to write a status here (a private repository answers 404 rather than admit it exists), 429 and
    5xx are worth retrying, and anything else is a refusal of this particular request.

    Args:
        response: The provider's response.
        provider: The provider key, for the message.
        token: The token in play, so a quoted credential is redacted.

    Raises:
        StatusPublishError: Always, when the response is not a success.
    """
    if response.is_success:
        return
    status = response.status_code
    detail = _provider_message(response, token)
    if status in (401, 403, 404):
        raise StatusPublishError(
            CODE_PROVIDER_FORBIDDEN,
            (
                f"{provider} refused the check publish ({status}): {detail}. Re-link the account "
                "or widen its token so it may write commit statuses on this repository."
            ),
            http_status=status,
        )
    if status == 429 or status >= 500:
        raise StatusPublishError(
            CODE_PROVIDER_UNAVAILABLE,
            f"{provider} could not accept the check publish ({status}): {detail}.",
            http_status=status,
            retryable=True,
        )
    raise StatusPublishError(
        CODE_PROVIDER_REFUSED,
        f"{provider} rejected the check publish ({status}): {detail}.",
        http_status=status,
    )


class StatusAdapter:
    """Publish one normalized verdict to one provider.

    Subclasses implement :meth:`build_call` — what URL, what method, what body — and inherit the
    transport, the error mapping and the fingerprinting, so a new provider is a table of spellings
    and a URL template rather than another HTTP client.

    Args:
        token: The repository token, resolved server-side. ``None`` is allowed so a caller can ask
            an adapter to *describe* a call it cannot make; :meth:`publish` refuses without one.
        client_factory: How to obtain an :class:`httpx.Client`; injected in tests.
    """

    #: The provider key this adapter covers.
    provider = ""

    #: The API host every call goes to.
    api_url = ""

    def __init__(
        self, token: Optional[str], *, client_factory: Optional[ClientFactory] = None
    ) -> None:
        """Create the adapter.

        Args:
            token: The repository token, or ``None``.
            client_factory: How to obtain an HTTP client.
        """
        self._token = token
        self._client_factory = client_factory or _default_client_factory

    # -- to implement --------------------------------------------------------------------------

    def build_call(self, request: PublishRequest) -> Tuple[str, str, Dict[str, Any]]:
        """Describe the single call that publishes ``request``.

        Args:
            request: The verdict to publish.

        Returns:
            ``(method, url, body)``.

        Raises:
            NotImplementedError: In the base class.
        """
        raise NotImplementedError

    def headers(self) -> Dict[str, str]:
        """Return the headers the provider expects, including the credential.

        Returns:
            The request headers.
        """
        return {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    def read_external_id(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Extract the provider's own id for the check from a success body.

        Args:
            payload: The decoded response body.

        Returns:
            The id, or ``None`` when this provider addresses a status by name instead.
        """
        _ = payload
        return None

    def read_url(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Extract the provider's web URL for the published check, when it returns one.

        Args:
            payload: The decoded response body.

        Returns:
            The URL, or ``None``.
        """
        _ = payload
        return None

    # -- shared --------------------------------------------------------------------------------

    def fingerprint(self, request: PublishRequest) -> str:
        """Fingerprint the *verdict* ``request`` carries, without publishing it.

        This is what the store writes to the delivery ledger, and what makes a redelivery free at
        the provider as well as here.

        It deliberately fingerprints the verdict and not the HTTP call. The two differ in exactly
        one place, and it is the place that matters: once a provider has given us an id for the
        check, the *same* verdict is published with a different method and a different URL —
        GitHub's ``PATCH .../check-runs/99`` instead of its ``POST .../check-runs``. Fingerprinting
        the call would make a webhook redelivery look like new work every time, which is the
        opposite of what the ledger is for. ``external_id`` names the provider's record; it does
        not change what is being said about the commit.

        Args:
            request: The verdict.

        Returns:
            ``"sha256:<hex>"``.
        """
        return request_fingerprint(
            {
                "provider": self.provider,
                "repo": request.repo_full_name,
                "commit": request.commit_sha,
                "name": request.name,
                "state": request.state,
                "title": request.title,
                "summary": request.summary,
                "details_url": request.details_url,
            }
        )

    def publish(self, request: PublishRequest) -> PublishedStatus:
        """Put the verdict on the commit.

        Args:
            request: The verdict to publish.

        Returns:
            What the provider did with it.

        Raises:
            StatusPublishError: With ``check-provider-forbidden`` when no credential is held or the
                provider refuses the write, ``check-provider-unavailable`` when it cannot be
                reached, and ``check-provider-refused`` for a request it will never accept.
        """
        if not self._token:
            raise StatusPublishError(
                CODE_PROVIDER_FORBIDDEN,
                (
                    f"No stored credential authorizes writing a check on this {self.provider} "
                    "repository. Link the account the repository was registered with."
                ),
            )
        method, url, body = self.build_call(request)
        fingerprint = self.fingerprint(request)
        try:
            with self._client_factory() as client:
                response = client.request(method, url, json=body, headers=self.headers())
        except httpx.HTTPError as exc:
            # The provider was not reached at all: a DNS failure, a refused connection, a timeout.
            # Redacted like everything else — a proxy error can quote the request it was given.
            detail = redact_secrets(
                str(exc), [self._token], marker=STATUS_TOKEN_REDACTION_MARKER
            )
            raise StatusPublishError(
                CODE_PROVIDER_UNAVAILABLE,
                f"{self.provider} could not be reached to publish the check: {detail}",
                retryable=True,
            ) from exc

        _raise_for_response(response, provider=self.provider, token=self._token)

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, Mapping):
            payload = {}
        return PublishedStatus(
            provider=self.provider,
            status_code=response.status_code,
            fingerprint=fingerprint,
            external_id=self.read_external_id(payload),
            url=self.read_url(payload),
        )


class GitHubCheckRunAdapter(StatusAdapter):
    """GitHub check runs.

    A check run is created with ``POST /repos/{owner}/{repo}/check-runs`` and moved with
    ``PATCH .../check-runs/{id}`` once GitHub has given us an id, which is why
    :attr:`PublishRequest.external_id` is threaded through: re-POSTing the same ``name`` would
    stack a second run on the pull request rather than move the first.

    GitHub is also the one provider that refuses a ``conclusion`` on a run that has not completed,
    so the pending body carries none — see :func:`app.provider_checks.github_conclusion`.
    """

    provider = "github"
    api_url = GITHUB_API_URL

    def headers(self) -> Dict[str, str]:
        """Return GitHub's headers, with the token and the pinned API version.

        Returns:
            The request headers.
        """
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            "User-Agent": _USER_AGENT,
        }

    def build_call(self, request: PublishRequest) -> Tuple[str, str, Dict[str, Any]]:
        """Build the create-or-move call for a check run.

        Args:
            request: The verdict.

        Returns:
            ``(method, url, body)``.
        """
        owner, repo = _split_full_name(request.repo_full_name)
        owner_q, repo_q = quote(owner, safe=""), quote(repo, safe="")
        base = f"{self.api_url}/repos/{owner_q}/{repo_q}/check-runs"

        body: Dict[str, Any] = {
            "name": request.name,
            "head_sha": request.commit_sha,
            "status": github_status(request.state),
            "output": {
                "title": request.title or request.name,
                "summary": request.summary,
            },
        }
        conclusion = github_conclusion(request.state)
        if conclusion:
            body["conclusion"] = conclusion
        if request.details_url:
            body["details_url"] = request.details_url

        if request.external_id:
            return "PATCH", f"{base}/{quote(str(request.external_id), safe='')}", body
        return "POST", base, body

    def read_external_id(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Read GitHub's check-run id from a success body.

        Args:
            payload: The decoded response.

        Returns:
            The id as a string, or ``None``.
        """
        value = payload.get("id")
        return str(value) if value is not None else None

    def read_url(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Read the check run's web page from a success body.

        Args:
            payload: The decoded response.

        Returns:
            The URL, or ``None``.
        """
        value = payload.get("html_url")
        return str(value) if value else None


class GitLabStatusAdapter(StatusAdapter):
    """GitLab commit statuses.

    ``POST /projects/{id}/statuses/{sha}`` is an upsert keyed on ``name``: posting the same name
    again moves that status rather than adding one, so there is no id to thread through. The
    project is addressed by its URL-encoded full path, which is what a webhook delivery's
    ``path_with_namespace`` already gives us.
    """

    provider = "gitlab"
    api_url = GITLAB_API_URL

    def headers(self) -> Dict[str, str]:
        """Return GitLab's headers, with the token.

        Returns:
            The request headers.
        """
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }

    def build_call(self, request: PublishRequest) -> Tuple[str, str, Dict[str, Any]]:
        """Build the commit-status call.

        Args:
            request: The verdict.

        Returns:
            ``(method, url, body)``.
        """
        path = str(request.repo_full_name or "").strip().strip("/")
        if not path:
            # GitLab addresses a project by its whole path, which may be nested, so there is no
            # owner/name split to check — but an empty path would build a URL pointing at every
            # project, and a verdict must never be published at a repository nobody named.
            raise StatusPublishError(
                CODE_PROVIDER_REFUSED,
                f"{request.repo_full_name!r} is not a GitLab project path.",
            )
        project = quote(path, safe="")
        sha = quote(request.commit_sha, safe="")
        body: Dict[str, Any] = {
            "state": gitlab_state(request.state),
            "name": request.name,
            # GitLab shows `description` where GitHub shows the output title; the summary has no
            # home on a commit status, so the link is what carries the detail.
            "description": (request.title or request.name)[:255],
        }
        if request.details_url:
            body["target_url"] = request.details_url
        return "POST", f"{self.api_url}/projects/{project}/statuses/{sha}", body

    def read_url(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Read the status's target URL back from a success body.

        Args:
            payload: The decoded response.

        Returns:
            The URL, or ``None``.
        """
        value = payload.get("target_url")
        return str(value) if value else None


class BitbucketStatusAdapter(StatusAdapter):
    """Bitbucket build statuses.

    ``POST /repositories/{workspace}/{repo}/commit/{sha}/statuses/build`` is an upsert keyed on the
    caller-chosen ``key``, so the check's name is the key and re-publishing moves the same status.
    Bitbucket requires both a ``key`` and a ``url``; a check with no details link would be refused,
    so one is always sent.
    """

    provider = "bitbucket"
    api_url = BITBUCKET_API_URL

    #: Bitbucket refuses a build status with no URL. When a check carries no details link, this
    #: stands in — it is the commit the verdict is about, which is at least true.
    _FALLBACK_URL = "https://bitbucket.org/{full_name}/commits/{sha}"

    #: Mirrors Bitbucket's own limit on a status key.
    _KEY_MAX_CHARS = 40

    def headers(self) -> Dict[str, str]:
        """Return Bitbucket's headers, with the token.

        Returns:
            The request headers.
        """
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }

    def build_call(self, request: PublishRequest) -> Tuple[str, str, Dict[str, Any]]:
        """Build the build-status call.

        Args:
            request: The verdict.

        Returns:
            ``(method, url, body)``.
        """
        workspace, repo = _split_full_name(request.repo_full_name)
        workspace_q, repo_q = quote(workspace, safe=""), quote(repo, safe="")
        sha = quote(request.commit_sha, safe="")
        url = (
            f"{self.api_url}/repositories/{workspace_q}/{repo_q}/commit/{sha}/statuses/build"
        )
        target = request.details_url or self._FALLBACK_URL.format(
            full_name=request.repo_full_name, sha=request.commit_sha
        )
        body: Dict[str, Any] = {
            # The key is the upsert identity, and Bitbucket bounds it well below a check name's
            # 128 characters, so it is truncated rather than allowed to be refused.
            "key": request.name[: self._KEY_MAX_CHARS],
            "state": bitbucket_state(request.state),
            "name": request.name,
            "description": (request.title or request.name)[:255],
            "url": target,
        }
        return "POST", url, body

    def read_url(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Read the status URL back from a success body.

        Args:
            payload: The decoded response.

        Returns:
            The URL, or ``None``.
        """
        value = payload.get("url")
        return str(value) if value else None


#: Every provider that has a status adapter, keyed by the provider id V265 stores.
_ADAPTERS: Dict[str, type] = {
    GitHubCheckRunAdapter.provider: GitHubCheckRunAdapter,
    GitLabStatusAdapter.provider: GitLabStatusAdapter,
    BitbucketStatusAdapter.provider: BitbucketStatusAdapter,
}


def supported_providers() -> Tuple[str, ...]:
    """Return the providers a check can be published to.

    Returns:
        The provider ids, sorted, so the tuple is stable in a response and a test.
    """
    return tuple(sorted(_ADAPTERS))


def adapter_for(
    provider: str,
    token: Optional[str],
    *,
    client_factory: Optional[ClientFactory] = None,
) -> StatusAdapter:
    """Build the adapter for a provider.

    Args:
        provider: The provider id from the binding.
        token: The repository token, resolved server-side.
        client_factory: How to obtain an HTTP client; injected in tests.

    Returns:
        The adapter.

    Raises:
        StatusPublishError: ``check-provider-unsupported`` for a provider with no adapter. Refused
            rather than defaulted to GitHub: publishing a verdict to the wrong API is worse than
            publishing none.
    """
    key = str(provider or "").strip().lower()
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        raise StatusPublishError(
            CODE_PROVIDER_UNSUPPORTED,
            f"No status adapter covers provider {provider!r}; "
            f"checks can be published to {', '.join(supported_providers())}.",
        )
    return adapter(token, client_factory=client_factory)
