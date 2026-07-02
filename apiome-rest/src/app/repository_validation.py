"""
Reachability checks for tenant repository registration (public URLs and GitHub API).

Mirrors apiome-ui `/api/repositories/test-public-url` behavior where practical.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlparse

import httpx

from .ssrf_guard import SSRFError, build_guarded_client, validate_url

_logger = logging.getLogger(__name__)

UA = "Apiome-RepositoryRegistration/1.0"
_HTTP_TIMEOUT = httpx.Timeout(12.0)


def normalize_clone_url_for_dedup(url: str) -> str:
    """
    Stable key for deduplicating clone URLs within a tenant.

    Lowercases scheme and host, trims trailing slashes, strips redundant .git noise for comparison.
    """
    raw = url.strip()
    if not raw:
        raise ValueError("clone URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("only HTTPS clone URLs are supported")
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("invalid clone URL host")
    path = parsed.path or ""
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = [s for s in path.split("/") if s]
    path_norm = "/".join(segments).lower()
    netloc = parsed.netloc.lower().removeprefix("www.")
    return f"https://{netloc}/{path_norm}.git"


def parse_github_owner_repo_from_url(url: str) -> tuple[str, str] | None:
    try:
        u = urlparse(url.strip())
    except Exception:
        return None
    host = (u.hostname or "").lower().removeprefix("www.")
    if host != "github.com":
        return None
    parts = [p for p in (u.path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[: -len(".git")]
    if not owner or not repo:
        return None
    return owner, repo


def parse_bitbucket_workspace_repo(url: str) -> tuple[str, str] | None:
    try:
        u = urlparse(url.strip())
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if host not in ("bitbucket.org", "www.bitbucket.org"):
        return None
    parts = [p for p in (u.path or "").split("/") if p]
    if len(parts) < 2:
        return None
    workspace, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[: -len(".git")]
    if not workspace or not repo:
        return None
    return workspace, repo


def parse_gitlab_project_path(url: str) -> tuple[str, str] | None:
    """Returns (api_origin, url-encoded project path) for GitLab API."""
    try:
        u = urlparse(url.strip())
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if "gitlab" not in host:
        return None
    path = (u.path or "").strip("/")
    if path.lower().endswith(".git"):
        path = path[: -len(".git")]
    path = path.strip("/")
    if path.count("/") < 1:
        return None
    # Reconstruct the origin from the parsed host (urlparse exposes ``hostname``,
    # not ``host``), preserving an explicit port for self-hosted GitLab.
    netloc = u.hostname or ""
    if u.port:
        netloc = f"{netloc}:{u.port}"
    origin = f"{u.scheme}://{netloc}"
    return origin, quote(path, safe="")


def parse_owner_repo_slash(value: str) -> tuple[str, str] | None:
    raw = value.strip()
    m = re.match(r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)$", raw)
    if not m:
        return None
    return m.group(1), m.group(2)


def _try_head_or_get(client: httpx.Client, url: str) -> None:
    r = client.head(url, follow_redirects=True)
    if r.status_code in (405, 501):
        r = client.get(url, follow_redirects=True, headers={"Range": "bytes=0-0"})
    if r.status_code in (200, 206):
        return
    if 400 <= r.status_code < 500:
        raise ValueError(f"URL returned HTTP {r.status_code}; it may be private or invalid.")
    raise ValueError(f"Unexpected HTTP {r.status_code} from URL.")


def validate_public_clone_url(clone_url: str) -> dict:
    """
    Verify that a public clone URL refers to a reachable repository.

    Returns metadata fields for persistence. Raises ValueError on failure.
    """
    url = clone_url.strip()
    if not url.lower().startswith("https://"):
        raise ValueError("only HTTPS clone URLs are supported for public registration")

    gh = parse_github_owner_repo_from_url(url)
    if gh:
        owner, repo = gh
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers={"User-Agent": UA}) as client:
            api_url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
            r = client.get(
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if r.status_code == 200:
            j = r.json()
            full_name = str(j.get("full_name") or f"{owner}/{repo}")
            private = bool(j.get("private"))
            if private:
                raise ValueError("repository is private; use a linked GitHub account instead")
            out = {
                "provider": "github",
                "repository_full_name": full_name,
                "description": j.get("description"),
                "default_branch": str(j.get("default_branch") or "main"),
                "visibility": "private" if private else "public",
                "canonical_clone_url": str(j.get("clone_url") or f"https://github.com/{full_name}.git"),
            }
            bc = count_github_repository_branches(owner, repo, access_token=None)
            if bc is not None:
                out["branch_count"] = bc
            return out
        if r.status_code == 404:
            raise ValueError(
                "GitHub returned 404 — repository may not exist, may be private, or may require authentication."
            )
        if r.status_code == 403:
            raise ValueError("GitHub blocked the request (rate limit or forbidden). Try again shortly.")
        raise ValueError(f"GitHub API error: HTTP {r.status_code}")

    bb = parse_bitbucket_workspace_repo(url)
    if bb:
        workspace, repo = bb
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers={"User-Agent": UA}) as client:
            api_url = f"https://api.bitbucket.org/2.0/repositories/{quote(workspace, safe='')}/{quote(repo, safe='')}"
            r = client.get(api_url)
        if r.status_code == 200:
            j = r.json()
            full_name = str(j.get("full_name") or f"{workspace}/{repo}")
            is_private = bool(j.get("is_private"))
            if is_private:
                raise ValueError("repository is private; use a linked account or different URL")
            main_branch = j.get("mainbranch") or {}
            main_name = main_branch.get("name") if isinstance(main_branch, dict) else None
            return {
                "provider": "bitbucket",
                "repository_full_name": full_name,
                "description": j.get("description"),
                "default_branch": str(main_name or "main"),
                "visibility": "private" if is_private else "public",
                "canonical_clone_url": url.strip().split("?", 1)[0],
            }
        if r.status_code == 404:
            raise ValueError("Bitbucket returned 404 — repository may not exist or may be private.")
        raise ValueError(f"Bitbucket API error: HTTP {r.status_code}")

    gl = parse_gitlab_project_path(url)
    if gl:
        api_origin, enc_path = gl
        # The GitLab API origin is derived from the tenant-supplied host (any host
        # containing "gitlab"), so vet it against the SSRF guard and use the
        # guarded client before reaching out — unlike GitHub/Bitbucket above,
        # which target hardcoded api.* hosts (#3612).
        try:
            validate_url(api_origin)
        except SSRFError as exc:
            raise ValueError(str(exc)) from exc
        with build_guarded_client(timeout=_HTTP_TIMEOUT, headers={"User-Agent": UA}) as client:
            api_url = f"{api_origin}/api/v4/projects/{enc_path}"
            r = client.get(api_url)
        if r.status_code == 200:
            j = r.json()
            path_ns = str(j.get("path_with_namespace") or enc_path.replace("%2F", "/"))
            visibility = str(j.get("visibility") or "unknown")
            if visibility == "private":
                raise ValueError("GitLab project appears private; use a linked account instead")
            https_url = j.get("http_url_to_repo") or j.get("ssh_url_to_repo")
            canonical = str(https_url) if https_url else url.strip().split("?", 1)[0]
            return {
                "provider": "gitlab",
                "repository_full_name": path_ns,
                "description": j.get("description"),
                "default_branch": str(j.get("default_branch") or "main"),
                "visibility": visibility,
                "canonical_clone_url": canonical,
            }
        if r.status_code == 404:
            raise ValueError("GitLab returned 404 — project may not exist or may be private.")
        raise ValueError(f"GitLab API error: HTTP {r.status_code}")

    # Generic (non-provider) URL: this hits an arbitrary tenant-supplied host, so
    # vet it against the SSRF guard before connecting and re-validate redirects
    # via the guarded client (#3612).
    try:
        validate_url(url)
    except SSRFError as exc:
        raise ValueError(str(exc)) from exc
    with build_guarded_client(timeout=_HTTP_TIMEOUT, headers={"User-Agent": UA}) as client:
        try:
            _try_head_or_get(client, url)
        except SSRFError as exc:
            raise ValueError(str(exc)) from exc
        except httpx.RequestError as exc:
            _logger.debug("generic clone URL check failed: %s", exc)
            raise ValueError("could not reach this URL (network error or timeout).") from exc
    return {
        "provider": "public_url",
        "repository_full_name": None,
        "description": None,
        "default_branch": "main",
        "visibility": "unknown",
        "canonical_clone_url": url.strip().split("?", 1)[0],
    }


def count_github_repository_branches(
    owner: str,
    repo: str,
    *,
    access_token: str | None = None,
) -> int | None:
    """
    Paginate GitHub ``/repos/{owner}/{repo}/branches`` and return the total count.

    Returns ``None`` if the API does not return 200 (caller may still register the repo).
    """
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    total = 0
    page = 1
    per_page = 100
    max_pages = 100
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            while page <= max_pages:
                url = (
                    f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/branches"
                    f"?per_page={per_page}&page={page}"
                )
                r = client.get(url, headers=headers)
                if r.status_code != 200:
                    _logger.debug(
                        "github branch count failed owner=%s repo=%s status=%s",
                        owner,
                        repo,
                        r.status_code,
                    )
                    return None
                batch = r.json()
                if not isinstance(batch, list):
                    return None
                total += len(batch)
                if len(batch) < per_page:
                    break
                page += 1
        return total
    except Exception as exc:
        _logger.debug("github branch count error: %s", exc)
        return None


def fetch_github_repo_with_token(access_token: str, owner: str, repo: str) -> dict:
    """Load repo metadata using the user's GitHub OAuth token (linked account)."""
    with httpx.Client(timeout=_HTTP_TIMEOUT, headers={"User-Agent": UA}) as client:
        api_url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        r = client.get(
            api_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if r.status_code == 200:
        j = r.json()
        full_name = str(j.get("full_name") or f"{owner}/{repo}")
        private = bool(j.get("private"))
        clone = str(j.get("clone_url") or f"https://github.com/{full_name}.git")
        out = {
            "provider": "github",
            "repository_full_name": full_name,
            "description": j.get("description"),
            "default_branch": str(j.get("default_branch") or "main"),
            "visibility": "private" if private else "public",
            "canonical_clone_url": clone,
        }
        bc = count_github_repository_branches(owner, repo, access_token=access_token)
        if bc is not None:
            out["branch_count"] = bc
        return out
    if r.status_code == 401:
        raise ValueError("GitHub access token is invalid or expired. Re-link your account.")
    if r.status_code == 404:
        raise ValueError("repository not found or not accessible with this linked account")
    raise ValueError(f"GitHub API error: HTTP {r.status_code}")
