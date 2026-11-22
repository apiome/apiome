"""Linked-account repository registration beyond GitHub — #6654.

``POST /v1/tenants/{tenant}/repositories`` with ``source: linked_account`` registers a repository
through an account the user linked (``external_auth_providers``), checking with the host — using
that account's token — that the repository exists and is spelled as given. Until #6654 that was
GitHub only. This module adds the other three hosts export git delivery writes to, and one
dispatch, :func:`fetch_linked_repository`, the route calls for all four.

* a ``github`` account registers ``github`` repositories named ``owner/repo``
  (``GET api.github.com/repos/…``);
* a ``gitlab`` account registers ``gitlab`` projects named ``group[/subgroup…]/project``
  (``GET gitlab.com/api/v4/projects/…``);
* a ``bitbucket`` account registers ``bitbucket`` repositories named ``workspace/repo``
  (``GET api.bitbucket.org/2.0/repositories/…``);
* an ``azure`` (Microsoft) account registers ``azure_devops`` repositories named
  ``organization/project/repository`` (``GET dev.azure.com/…/_apis/git/repositories/…``).

Each fetcher returns the metadata dict the route stores (``provider``, ``repository_full_name``,
``description``, ``default_branch``, ``visibility``, ``canonical_clone_url``) and raises
:class:`ValueError` with a message for the caller. The hosts are fixed — never tenant-supplied — so
there is no request-forgery surface; a clone URL never carries the user-info part some hosts put in
it (``https://user@bitbucket.org/…``).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote, urlparse, urlunparse

import httpx

from .export_git_delivery_azure_devops import AZURE_DEVOPS_API_URL, AZURE_DEVOPS_API_VERSION, split_azure_devops_name
from .export_git_delivery_bitbucket import BITBUCKET_API_URL
from .export_git_delivery_gitlab import GITLAB_API_URL
from .repository_validation import fetch_github_repo_with_token, parse_owner_repo_slash

_logger = logging.getLogger(__name__)

__all__ = [
    "LINKED_REGISTRATION_PROVIDERS",
    "fetch_azure_devops_repo_with_token",
    "fetch_bitbucket_repo_with_token",
    "fetch_gitlab_project_with_token",
    "fetch_linked_repository",
    "linked_repository_provider",
]

#: Linked-account provider → the ``tenant_repositories.provider`` its repositories are stored under.
#: A Microsoft (Entra ID) account registers Azure DevOps repositories.
LINKED_REGISTRATION_PROVIDERS: Dict[str, str] = {
    "github": "github",
    "gitlab": "gitlab",
    "bitbucket": "bitbucket",
    "azure": "azure_devops",
}

_HTTP_TIMEOUT = 20.0
_USER_AGENT = "apiome-repository-registration"

#: A GitLab project path: two or more segments.
_GITLAB_PATH = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.][A-Za-z0-9_.-]*)+$")

#: Every fetcher takes ``(token, repository_full_name, client)``.
Fetcher = Callable[[str, str, Optional[httpx.Client]], Dict[str, Any]]


def linked_repository_provider(linked_provider: Optional[str]) -> Optional[str]:
    """The repository provider a linked account registers, or ``None`` when it registers none.

    Args:
        linked_provider: ``external_auth_providers.provider`` (``github``, ``gitlab``, …).

    Returns:
        ``github``, ``gitlab``, ``bitbucket`` or ``azure_devops``; ``None`` for any other account.
    """
    return LINKED_REGISTRATION_PROVIDERS.get(str(linked_provider or "").strip().lower())


def _strip_userinfo(url: str) -> str:
    """Drop ``user@`` (and any password) from a clone URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse(parsed._replace(netloc=netloc))


def _get(
    client: Optional[httpx.Client], url: str, token: str, params: Optional[Dict[str, str]] = None
) -> httpx.Response:
    """One authenticated GET, through the injected client or a short-lived one."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": _USER_AGENT}
    if client is not None:
        return client.get(url, headers=headers, params=params)
    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as owned:
        return owned.get(url, headers=headers, params=params)


def _refusal(label: str, status: int) -> ValueError:
    """The error a refused metadata read becomes."""
    if status in (401, 203):
        return ValueError(f"{label} access token is invalid or expired. Re-link your account.")
    if status in (403, 404):
        return ValueError("repository not found or not accessible with this linked account")
    return ValueError(f"{label} API error: HTTP {status}")


def fetch_gitlab_project_with_token(
    token: str, full_name: str, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """Load a GitLab project's metadata with the linked account's token.

    Args:
        token: The linked GitLab account's OAuth token.
        full_name: The project path (``group/subgroup/project``).
        client: An HTTP client to use (tests inject one).

    Returns:
        The registration metadata; ``repository_full_name`` is GitLab's ``path_with_namespace``.

    Raises:
        ValueError: For a malformed path or a refused read.
    """
    path = full_name.strip().strip("/")
    if not _GITLAB_PATH.match(path):
        raise ValueError("repository_full_name must be a GitLab project path (group/project or group/subgroup/project)")
    response = _get(client, f"{GITLAB_API_URL}/projects/{quote(path, safe='')}", token)
    if response.status_code != 200:
        raise _refusal("GitLab", response.status_code)
    payload = response.json() or {}
    canonical = str(payload.get("path_with_namespace") or path)
    return {
        "provider": "gitlab",
        "repository_full_name": canonical,
        "description": payload.get("description"),
        "default_branch": str(payload.get("default_branch") or "main"),
        "visibility": str(payload.get("visibility") or "private"),
        "canonical_clone_url": _strip_userinfo(str(payload.get("http_url_to_repo") or f"https://gitlab.com/{canonical}.git")),
    }


def fetch_bitbucket_repo_with_token(
    token: str, full_name: str, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """Load a Bitbucket Cloud repository's metadata with the linked account's token.

    Args:
        token: The linked Bitbucket account's OAuth token.
        full_name: ``workspace/repo``.
        client: An HTTP client to use (tests inject one).

    Returns:
        The registration metadata.

    Raises:
        ValueError: For a malformed name or a refused read.
    """
    parts = parse_owner_repo_slash(full_name)
    if not parts:
        raise ValueError("repository_full_name must be workspace/repo")
    workspace, repo = parts
    url = f"{BITBUCKET_API_URL}/repositories/{quote(workspace, safe='')}/{quote(repo, safe='')}"
    response = _get(client, url, token)
    if response.status_code != 200:
        raise _refusal("Bitbucket", response.status_code)
    payload = response.json() or {}
    canonical = str(payload.get("full_name") or f"{workspace}/{repo}")
    clone = next((str(link.get("href")) for link in ((payload.get("links") or {}).get("clone") or [])
                  if isinstance(link, dict) and link.get("name") == "https" and link.get("href")),
                 f"https://bitbucket.org/{canonical}.git")
    return {
        "provider": "bitbucket",
        "repository_full_name": canonical,
        "description": payload.get("description"),
        "default_branch": str((payload.get("mainbranch") or {}).get("name") or "main"),
        "visibility": "private" if payload.get("is_private", True) else "public",
        "canonical_clone_url": _strip_userinfo(clone),
    }


def fetch_azure_devops_repo_with_token(
    token: str, full_name: str, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """Load an Azure DevOps repository's metadata with the linked Microsoft account's token.

    Args:
        token: The linked Microsoft account's token, issued for Azure DevOps.
        full_name: ``organization/project/repository``.
        client: An HTTP client to use (tests inject one).

    Returns:
        The registration metadata; ``repository_full_name`` is spelled as Azure DevOps spells the
        project and repository.

    Raises:
        ValueError: For a malformed name or a refused read.
    """
    try:
        org, project, repo = split_azure_devops_name(full_name)
    except ValueError as exc:
        raise ValueError("repository_full_name must be organization/project/repository") from exc
    url = (f"{AZURE_DEVOPS_API_URL}/{quote(org, safe='')}/{quote(project, safe='')}/_apis/git/repositories/"
           f"{quote(repo, safe='')}")
    response = _get(client, url, token, params={"api-version": AZURE_DEVOPS_API_VERSION})
    if response.status_code != 200:
        raise _refusal("Azure DevOps", response.status_code)
    payload = response.json() or {}
    project_payload = payload.get("project") or {}
    canonical = f"{org}/{project_payload.get('name') or project}/{payload.get('name') or repo}"
    default = str(payload.get("defaultBranch") or "refs/heads/main")
    return {
        "provider": "azure_devops",
        "repository_full_name": canonical,
        "description": project_payload.get("description"),
        "default_branch": default[len("refs/heads/"):] if default.startswith("refs/heads/") else default,
        "visibility": str(project_payload.get("visibility") or "private"),
        "canonical_clone_url": _strip_userinfo(str(payload.get("remoteUrl") or url)),
    }


def _github(token: str, full_name: str, client: Optional[httpx.Client]) -> Dict[str, Any]:
    parts = parse_owner_repo_slash(full_name)
    if not parts:
        raise ValueError("repository_full_name must be owner/repo")
    return fetch_github_repo_with_token(token, parts[0], parts[1])


_FETCHERS: Dict[str, Fetcher] = {
    "github": _github,
    "gitlab": fetch_gitlab_project_with_token,
    "bitbucket": fetch_bitbucket_repo_with_token,
    "azure_devops": fetch_azure_devops_repo_with_token,
}


def fetch_linked_repository(provider: str, token: str, full_name: str,
                            client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Load a repository's registration metadata from its host.

    Args:
        provider: The repository provider (:func:`linked_repository_provider`).
        token: The linked account's token.
        full_name: The name the caller gave, in the provider's shape.
        client: An HTTP client to use (tests inject one; GitHub opens its own).

    Returns:
        The registration metadata.

    Raises:
        ValueError: For an unknown provider, a malformed name or a refused read.
    """
    fetcher = _FETCHERS.get(provider)
    if fetcher is None:
        raise ValueError(f"linked repository registration does not support {provider!r}")
    try:
        return fetcher(token, full_name, client)
    except httpx.HTTPError as exc:
        _logger.info("linked repository metadata read failed provider=%s: %s", provider, type(exc).__name__)
        raise ValueError(f"{provider} could not be reached; try again") from exc
