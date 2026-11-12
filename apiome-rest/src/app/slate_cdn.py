"""CDN / edge provider decisions — Slate 10.2 (private-suite#120).

Everything about a lane's CDN that can be decided without I/O lives here, so it is tested without
a database or a socket:

* :func:`normalize_config` — what a valid provider configuration is. The REST layer refuses
  anything this refuses, and V368's CHECKs refuse the same shapes again at the database.
* :func:`plan_cdn_purge` — turn a set of changed paths and the lane's verified hosts into what
  will be purged: a list of absolute URLs, or the whole CDN cache when the scope is larger than
  the provider accepts per purge.
* :func:`build_requests` — the provider API calls that carry out a plan. The only function that
  sees the credential, and it puts it in a header and nowhere else.
* :func:`classify_response` — map what a provider answered to success or a short error code.

**URLs, never tags.** The cache plane's tags (UXE-3.1) label rules; nothing at the origin emits
them as ``Cache-Tag`` / ``Surrogate-Key`` headers, so a tag purge sent to a CDN would match nothing
and report success. Every scope is therefore resolved to paths first and purged by URL.

**Over the cap, purge everything — and say so.** Cloudflare accepts 30 URLs per request and Fastly
purges one URL per request. Past a per-provider cap the plan switches to ``purge-all`` and records
how many URLs it covered, because sending thousands of calls during a deploy is slower, more likely
to be rate-limited, and less correct than one full purge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

__all__ = [
    "CODE_CREDENTIAL_REQUIRED",
    "CODE_INVALID",
    "CODE_NOT_CONFIGURED",
    "CODE_VAULT_NOT_CONFIGURED",
    "CdnConfigError",
    "CdnHttpRequest",
    "CdnPurgePlan",
    "NormalizedCdnConfig",
    "PROVIDERS",
    "build_requests",
    "classify_response",
    "error_sentence",
    "normalize_config",
    "plan_cdn_purge",
    "purge_urls",
    "redact",
]

#: The three providers V368 accepts.
PROVIDERS: Tuple[str, ...] = ("cloudflare", "fastly", "custom")

#: Fixed vendor API roots. Never taken from input, so a configuration cannot redirect a vendor
#: credential to another host.
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
FASTLY_API = "https://api.fastly.com"

#: URLs per Cloudflare ``purge_cache`` call (the limit every plan accepts).
CLOUDFLARE_BATCH = 30

#: Past these many URLs a purge becomes purge-all. Fastly purges one URL per call, so its cap is
#: lowest; a custom endpoint receives one call either way.
URL_CAPS: Dict[str, int] = {"cloudflare": 500, "fastly": 50, "custom": 1000}

#: URLs kept on a dispatch record so an operator can see what was hit.
SAMPLE_LIMIT = 20

#: Longest accepted credential. Anything past this is a pasted file, not a token.
SECRET_MAX_CHARS = 4_096

#: Configuration refusal codes (the route maps them to 422 / 409 / 404).
CODE_INVALID = "cdn-config-invalid"
CODE_CREDENTIAL_REQUIRED = "cdn-credential-required"
CODE_VAULT_NOT_CONFIGURED = "cdn-vault-not-configured"
CODE_NOT_CONFIGURED = "cdn-not-configured"

#: Headers a custom endpoint may not have its credential sent in: each is set by the HTTP client,
#: and overriding it would corrupt the request rather than authenticate it.
_RESERVED_HEADERS = frozenset(
    {"host", "content-length", "content-type", "transfer-encoding", "connection", "cookie"}
)

_CLOUDFLARE_ZONE = re.compile(r"^[0-9a-f]{32}$")
_FASTLY_SERVICE = re.compile(r"^[A-Za-z0-9]{1,64}$")
_HEADER_TOKEN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

#: What each dispatch error code means, in words an operator can act on. The UI prints these
#: verbatim rather than restating them.
_ERROR_SENTENCES: Dict[str, str] = {
    "cdn-auth-rejected": (
        "The CDN rejected the credential. Check that the token or key is current and allowed to "
        "purge."
    ),
    "cdn-rate-limited": (
        "The CDN rate-limited the purge. Cached pages may stay stale until their TTL expires; "
        "purge again shortly."
    ),
    "cdn-rejected": "The CDN refused the purge request. Check the zone or service id and the provider's message.",
    "cdn-provider-error": "The CDN answered with a server error. Purge again once the provider has recovered.",
    "cdn-unreachable": "The CDN could not be reached. Nothing was purged.",
    "cdn-timeout": "The CDN did not answer in time. Some URLs may not have been purged.",
    "cdn-target-refused": "The purge URL is not a public https endpoint, so the credential was not sent.",
    "cdn-credential-unavailable": (
        "The stored credential cannot be opened on this deployment. Re-enter it to purge again."
    ),
    "cdn-no-hosts": "The lane has no verified domain, so there is no URL to purge.",
    "cdn-nothing-to-purge": "No page was in scope, so nothing was sent to the CDN.",
    "cdn-dispatch-error": "The purge could not be sent because of an internal error. Nothing was purged.",
}


def error_sentence(code: Optional[str]) -> Optional[str]:
    """Return the operator-facing sentence for a dispatch error code.

    Args:
        code: A dispatch error code, or None.

    Returns:
        The sentence, the code itself when it has none, or None for no code.
    """
    if not code:
        return None
    return _ERROR_SENTENCES.get(code, code)


class CdnConfigError(ValueError):
    """A provider configuration was refused.

    Attributes:
        code: One of the ``CODE_*`` constants.
        errors: One message per problem, so a form can mark every bad field at once. No message
            ever quotes the credential.
    """

    def __init__(self, code: str, *errors: str) -> None:
        self.code = code
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid CDN configuration")


@dataclass(frozen=True)
class NormalizedCdnConfig:
    """A configuration that passed every rule V368 also enforces.

    Attributes:
        provider: ``cloudflare``, ``fastly`` or ``custom``.
        target: Zone id, service id or https purge URL.
        auth_header_name: The custom endpoint's credential header; None otherwise.
        credential: The new credential, or None to keep the stored one.
    """

    provider: str
    target: str
    auth_header_name: Optional[str]
    credential: Optional[str]


def normalize_config(
    *,
    provider: str,
    target: str,
    auth_header_name: Optional[str],
    credential: Optional[str],
    existing_provider: Optional[str],
) -> NormalizedCdnConfig:
    """Validate and normalize a provider configuration.

    A credential may be omitted only when updating a lane already configured for the same
    provider: the stored credential is kept. Switching provider always needs a new one, because a
    Cloudflare token is meaningless to Fastly.

    Args:
        provider: Requested provider.
        target: Zone id / service id / purge URL as typed.
        auth_header_name: Header name for a custom endpoint.
        credential: The credential as typed; blank means "keep the stored one".
        existing_provider: Provider already stored for the lane, or None.

    Returns:
        The normalized configuration.

    Raises:
        CdnConfigError: ``cdn-config-invalid`` listing every bad field, or
            ``cdn-credential-required`` when a credential is needed and missing.
    """
    errors: List[str] = []
    key = (provider or "").strip().lower()
    if key not in PROVIDERS:
        raise CdnConfigError(CODE_INVALID, "Provider must be Cloudflare, Fastly or Custom origin.")

    raw_target = (target or "").strip()
    header: Optional[str] = None
    if key == "cloudflare":
        raw_target = raw_target.lower()
        if not _CLOUDFLARE_ZONE.match(raw_target):
            errors.append(
                "Zone ID must be the 32-character hexadecimal id shown on the zone's Overview page."
            )
    elif key == "fastly":
        if not _FASTLY_SERVICE.match(raw_target):
            errors.append("Service ID must be the alphanumeric id shown on the Fastly service.")
    else:
        errors.extend(_custom_url_errors(raw_target))
        header = (auth_header_name or "").strip()
        if not _HEADER_TOKEN.match(header):
            errors.append("Auth header must be a header name of letters, digits and hyphens.")
        elif header.lower() in _RESERVED_HEADERS:
            errors.append(f"Auth header cannot be {header}; the HTTP client sets it.")

    secret = (credential or "").strip()
    if secret:
        if len(secret) > SECRET_MAX_CHARS:
            errors.append(f"The credential is longer than {SECRET_MAX_CHARS} characters.")
        elif _CONTROL_CHARS.search(secret):
            errors.append("The credential contains a line break or control character.")

    if errors:
        raise CdnConfigError(CODE_INVALID, *errors)
    if not secret and existing_provider != key:
        raise CdnConfigError(
            CODE_CREDENTIAL_REQUIRED,
            "Enter the credential: a new provider cannot reuse the stored one."
            if existing_provider
            else "Enter the credential the CDN authorizes purges with.",
        )
    return NormalizedCdnConfig(
        provider=key, target=raw_target, auth_header_name=header, credential=secret or None
    )


def _custom_url_errors(url: str) -> List[str]:
    """List what is wrong with a custom purge URL, without resolving it.

    Whether the host is public is checked when a purge is sent (the SSRF guard re-resolves on
    every call); this checks only the shape, which is what V368 also checks.

    Args:
        url: The URL as typed.

    Returns:
        Error messages; empty when the URL is acceptable.
    """
    if not url:
        return ["Purge URL is required."]
    if len(url) > 2048:
        return ["Purge URL is longer than 2048 characters."]
    try:
        parts = urlsplit(url)
    except ValueError:
        return ["Purge URL is not a valid URL."]
    if parts.scheme != "https":
        return ["Purge URL must start with https:// — the credential is sent to it."]
    if not parts.hostname:
        return ["Purge URL must name a host."]
    if parts.username or parts.password:
        return ["Purge URL must not embed a user name or password; use the auth header."]
    if parts.fragment:
        return ["Purge URL must not contain a #fragment."]
    return []


@dataclass(frozen=True)
class CdnPurgePlan:
    """What a purge will do, decided before anything is sent.

    Attributes:
        provider: The provider it is for.
        mode: ``urls`` or ``purge-all``.
        urls: Every URL to purge (empty for purge-all).
        url_count: How many URLs were in scope, including for purge-all.
        sample_urls: A bounded sample for the dispatch record.
        skipped_code: Set when there is nothing to send, e.g. ``cdn-no-hosts``.
    """

    provider: str
    mode: str
    urls: Tuple[str, ...] = ()
    url_count: int = 0
    sample_urls: Tuple[str, ...] = field(default_factory=tuple)
    skipped_code: Optional[str] = None


def purge_urls(hosts: Iterable[str], paths: Iterable[str]) -> List[str]:
    """Join every host with every path into absolute https URLs.

    Args:
        hosts: Verified hostnames serving the lane.
        paths: Site-relative routes, with or without a leading slash.

    Returns:
        Sorted, de-duplicated absolute URLs.
    """
    normalized_paths = {path if path.startswith("/") else f"/{path}" for path in paths if path}
    clean_hosts = {host.strip().lower().rstrip(".") for host in hosts if host and host.strip()}
    return sorted(f"https://{host}{path}" for host in clean_hosts for path in normalized_paths)


def plan_cdn_purge(
    *,
    provider: str,
    hosts: Sequence[str],
    paths: Sequence[str],
    purge_all_if_empty: bool,
) -> CdnPurgePlan:
    """Decide what a purge will send.

    Args:
        provider: The lane's provider.
        hosts: The lane's verified hosts. None means there is no URL the CDN could be serving.
        paths: The routes in scope.
        purge_all_if_empty: When no path is known — a deploy whose release recorded no changed
            pages — purge everything rather than nothing. A deploy cannot prove nothing changed
            without that record, and stale pages are the failure this feature exists to prevent.

    Returns:
        The plan.
    """
    if not hosts:
        return CdnPurgePlan(provider=provider, mode="urls", skipped_code="cdn-no-hosts")

    urls = purge_urls(hosts, paths)
    if not urls:
        if purge_all_if_empty:
            return CdnPurgePlan(provider=provider, mode="purge-all")
        return CdnPurgePlan(provider=provider, mode="urls", skipped_code="cdn-nothing-to-purge")

    sample = tuple(urls[:SAMPLE_LIMIT])
    if len(urls) > URL_CAPS.get(provider, 0):
        return CdnPurgePlan(
            provider=provider, mode="purge-all", url_count=len(urls), sample_urls=sample
        )
    return CdnPurgePlan(
        provider=provider, mode="urls", urls=tuple(urls), url_count=len(urls), sample_urls=sample
    )


@dataclass(frozen=True)
class CdnHttpRequest:
    """One provider API call. Carries the credential, so it is never logged or returned.

    Attributes:
        method: HTTP method.
        url: Absolute URL.
        headers: Request headers, including the credential.
        json: JSON body, or None.
    """

    method: str
    url: str
    headers: Mapping[str, str]
    json: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:  # pragma: no cover - defensive; keeps secrets out of tracebacks
        return f"CdnHttpRequest({self.method} {self.url})"


def build_requests(
    plan: CdnPurgePlan,
    *,
    target: str,
    auth_header_name: Optional[str],
    secret: str,
    context: Mapping[str, Any],
) -> List[CdnHttpRequest]:
    """Build the provider calls that carry out a plan.

    Args:
        plan: A plan with nothing skipped.
        target: Zone id, service id or purge URL.
        auth_header_name: The custom endpoint's header.
        secret: The opened credential.
        context: ``environmentId`` / ``releaseId`` / ``trigger`` for a custom endpoint's body.

    Returns:
        The calls, in order. Empty for a skipped plan.
    """
    if plan.skipped_code:
        return []

    if plan.provider == "cloudflare":
        endpoint = f"{CLOUDFLARE_API}/zones/{target}/purge_cache"
        headers = {"Authorization": f"Bearer {secret}"}
        if plan.mode == "purge-all":
            return [CdnHttpRequest("POST", endpoint, headers, {"purge_everything": True})]
        return [
            CdnHttpRequest("POST", endpoint, headers, {"files": list(batch)})
            for batch in _batches(plan.urls, CLOUDFLARE_BATCH)
        ]

    if plan.provider == "fastly":
        headers = {"Fastly-Key": secret, "Accept": "application/json"}
        if plan.mode == "purge-all":
            return [CdnHttpRequest("POST", f"{FASTLY_API}/service/{target}/purge_all", headers)]
        # Fastly's single-URL purge takes the cached URL without its scheme.
        return [
            CdnHttpRequest("POST", f"{FASTLY_API}/purge/{url.split('://', 1)[1]}", headers)
            for url in plan.urls
        ]

    body = {
        "event": "apiome.slate.cdn.purge",
        "mode": plan.mode,
        "purgeAll": plan.mode == "purge-all",
        "urls": list(plan.urls),
        "urlCount": plan.url_count,
        **{key: value for key, value in context.items() if value is not None},
    }
    return [CdnHttpRequest("POST", target, {str(auth_header_name): secret}, body)]


def _batches(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Split a sequence into consecutive slices of at most ``size``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def classify_response(
    provider: str, status_code: int, body: Any
) -> Optional[Tuple[str, str]]:
    """Map a provider answer to success or an error code and message.

    Args:
        provider: The provider that answered.
        status_code: HTTP status.
        body: The parsed JSON body, or None.

    Returns:
        None on success, else ``(error_code, message)``. The message is the provider's own when it
        gave one — callers must still pass it through :func:`redact`.
    """
    provider_message = _provider_message(body)
    if status_code in (401, 403):
        return "cdn-auth-rejected", provider_message or error_sentence("cdn-auth-rejected") or ""
    if status_code == 429:
        return "cdn-rate-limited", provider_message or error_sentence("cdn-rate-limited") or ""
    if status_code >= 500:
        return "cdn-provider-error", provider_message or f"HTTP {status_code}"
    if status_code >= 400:
        return "cdn-rejected", provider_message or f"HTTP {status_code}"
    # Cloudflare can answer 200 with success: false.
    if provider == "cloudflare" and isinstance(body, Mapping) and body.get("success") is False:
        return "cdn-rejected", provider_message or "Cloudflare reported success: false."
    return None


def _provider_message(body: Any) -> Optional[str]:
    """Extract the human-readable error a provider put in its JSON body, if any."""
    if not isinstance(body, Mapping):
        return None
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], Mapping):
        message = errors[0].get("message")
        if message:
            return str(message)
    for key in ("msg", "message", "detail", "error"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def redact(text: Optional[str], secret: Optional[str], *, limit: int = 300) -> Optional[str]:
    """Remove a credential from text that will be stored or returned, and bound its length.

    Args:
        text: The text, e.g. a provider's error message.
        secret: The credential to remove.
        limit: Longest result.

    Returns:
        The redacted, truncated text, or None for no text.
    """
    if not text:
        return None
    cleaned = text.replace(secret, "[redacted]") if secret else text
    cleaned = _CONTROL_CHARS.sub(" ", cleaned).strip()
    return cleaned[:limit]
