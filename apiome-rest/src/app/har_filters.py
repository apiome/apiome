"""Noise filter and import options for HAR captures — MFI-32.2 (#4404).

A browser or proxy capture records *everything* the page loaded: the HTML document, its scripts,
stylesheets, fonts and images, CORS preflights, and the beacons analytics vendors fire on every
click. Only a fraction of a capture is the API the user wants catalogued. This module decides,
entry by entry, which is which:

* :func:`classify_entry` names the built-in reason an entry is noise (``static-asset``,
  ``analytics``, ``cors-preflight``, ``non-http``) or returns ``None`` for an API call. It reads the
  request method and URL, Chrome's ``_resourceType`` hint, the path's file extension and the
  response's media type.
* :class:`HarOptions` carries the user's tuning, read from the import's ``options`` mapping by
  :meth:`HarOptions.from_mapping`: which hosts to import (``har_hosts``), URL patterns to keep
  whatever the built-in filter says (``har_include``) or to drop (``har_exclude``), and a switch
  that turns the built-in filter off (``har_keep_noise``).

The module is pure: it never reads a header or body value, so nothing here can leak a credential.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Tuple

__all__ = [
    "ANALYTICS",
    "ANALYTICS_HOST_SUFFIXES",
    "BROWSER_HEADERS",
    "CORS_PREFLIGHT",
    "EXCLUDED_BY_PATTERN",
    "HAR_EXCLUDE_OPTION",
    "HAR_HOSTS_OPTION",
    "HAR_INCLUDE_OPTION",
    "HAR_KEEP_NOISE_OPTION",
    "HarOptions",
    "HarOptionsError",
    "NON_HTTP",
    "STATIC_ASSET",
    "UNSELECTED_HOST",
    "classify_entry",
    "is_browser_header",
]

#: Import option: the host(s) to import from a multi-host capture (a list, or a comma-separated
#: string). Absent means "the host with the most API calls".
HAR_HOSTS_OPTION = "har_hosts"

#: Import option: URL patterns (``host/path`` globs) kept even when the built-in filter calls them noise.
HAR_INCLUDE_OPTION = "har_include"

#: Import option: URL patterns (``host/path`` globs) always dropped.
HAR_EXCLUDE_OPTION = "har_exclude"

#: Import option: ``true`` turns the built-in noise filter off (patterns and host selection still apply).
HAR_KEEP_NOISE_OPTION = "har_keep_noise"

#: Exclusion reason: a page asset — document, script, stylesheet, image, font, media, manifest.
STATIC_ASSET = "static-asset"

#: Exclusion reason: a call to a known analytics, tag-manager, error-reporting or session-replay vendor.
ANALYTICS = "analytics"

#: Exclusion reason: a CORS preflight (``OPTIONS``) the browser sent on the page's behalf.
CORS_PREFLIGHT = "cors-preflight"

#: Exclusion reason: not an ``http(s)`` request (``data:``, ``blob:``, ``ws:``, an extension URL).
NON_HTTP = "non-http"

#: Exclusion reason: matched one of the user's ``har_exclude`` patterns.
EXCLUDED_BY_PATTERN = "excluded-by-pattern"

#: Exclusion reason: an API call to a host the import did not select.
UNSELECTED_HOST = "unselected-host"

#: Hosts (and their sub-domains) whose traffic is telemetry about the page, never the page's API.
ANALYTICS_HOST_SUFFIXES: Tuple[str, ...] = (
    "google-analytics.com",
    "analytics.google.com",
    "googletagmanager.com",
    "googleadservices.com",
    "googlesyndication.com",
    "doubleclick.net",
    "segment.io",
    "segment.com",
    "mixpanel.com",
    "amplitude.com",
    "hotjar.com",
    "hotjar.io",
    "fullstory.com",
    "heapanalytics.com",
    "clarity.ms",
    "sentry.io",
    "browser-intake-datadoghq.com",
    "browser-intake-datadoghq.eu",
    "nr-data.net",
    "newrelic.com",
    "facebook.net",
    "bat.bing.com",
    "px.ads.linkedin.com",
    "intercomcdn.com",
    "posthog.com",
    "plausible.io",
    "matomo.cloud",
    "cdn.mxpnl.com",
    "launchdarkly.com",
)

#: Chrome's ``_resourceType`` values that are page loads, never API calls. ``xhr``, ``fetch``,
#: ``eventsource`` and ``other`` are kept.
_ASSET_RESOURCE_TYPES = frozenset(
    {
        "document",
        "stylesheet",
        "script",
        "image",
        "font",
        "media",
        "manifest",
        "texttrack",
        "websocket",
        "ping",
        "preflight",
        "prefetch",
        "signedexchange",
        "cspviolationreport",
    }
)

#: Path extensions a page asset carries.
_ASSET_EXTENSIONS = frozenset(
    {
        ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif",
        ".svg", ".ico", ".webp", ".avif", ".bmp", ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp4", ".webm", ".mp3", ".ogg", ".wav", ".wasm", ".webmanifest",
    }
)

#: Response media types (and prefixes ending ``/``) that are page assets.
_ASSET_MEDIA_TYPES: Tuple[str, ...] = (
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "application/wasm",
    "application/manifest+json",
    "application/font-woff",
    "application/x-font-ttf",
    "image/",
    "font/",
    "audio/",
    "video/",
)

#: Request headers the browser (or the HTTP stack) sets on every request by itself. They say
#: nothing about the API, so they never become operation parameters. HTTP/2 pseudo-headers
#: (``:authority``, ``:path`` …) are dropped separately by :func:`is_browser_header`.
BROWSER_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "cache-control",
        "connection",
        "content-length",
        "dnt",
        "host",
        "if-modified-since",
        "if-none-match",
        "keep-alive",
        "origin",
        "pragma",
        "priority",
        "referer",
        "te",
        "upgrade-insecure-requests",
        "user-agent",
    }
)


def is_browser_header(name: str) -> bool:
    """True when a request header is set by the browser or HTTP stack, not by the API's client.

    Args:
        name: The header name as captured.

    Returns:
        ``True`` for HTTP/2 pseudo-headers, ``sec-*`` fetch metadata / client hints, and
        :data:`BROWSER_HEADERS`.
    """
    lower = (name or "").strip().lower()
    return lower.startswith(":") or lower.startswith("sec-") or lower in BROWSER_HEADERS


def _media_type(value: Optional[str]) -> str:
    """The bare, lower-cased media type of a ``Content-Type`` / ``mimeType`` value."""
    return (value or "").split(";", 1)[0].strip().lower()


def _is_analytics_host(host: str) -> bool:
    bare = host.split(":", 1)[0]
    return any(bare == suffix or bare.endswith("." + suffix) for suffix in ANALYTICS_HOST_SUFFIXES)


def _has_asset_extension(path: str) -> bool:
    last = path.rsplit("/", 1)[-1].lower()
    dot = last.rfind(".")
    return dot > 0 and last[dot:] in _ASSET_EXTENSIONS


def _is_asset_media_type(media_type: str) -> bool:
    return any(
        media_type.startswith(prefix) if prefix.endswith("/") else media_type == prefix
        for prefix in _ASSET_MEDIA_TYPES
    )


def classify_entry(
    *,
    method: str,
    scheme: str,
    host: str,
    path: str,
    resource_type: Optional[str],
    response_media_type: Optional[str],
) -> Optional[str]:
    """Name the built-in reason a captured entry is noise, or ``None`` for an API call.

    The checks run cheapest and most certain first: the scheme, the method, the host, Chrome's own
    resource-type hint, the path's extension, and last the response's media type.

    Args:
        method: The request method, any case.
        scheme: The URL scheme, lower-cased (``https``).
        host: The URL host (``api.example.com:8443``), lower-cased.
        path: The URL path.
        resource_type: Chrome's ``_resourceType`` for the entry, when the capture carries one.
        response_media_type: The response ``content.mimeType``, when there is a response.

    Returns:
        :data:`NON_HTTP`, :data:`CORS_PREFLIGHT`, :data:`ANALYTICS` or :data:`STATIC_ASSET`, or
        ``None`` when the entry looks like an API call.
    """
    if scheme not in ("http", "https"):
        return NON_HTTP
    if method.upper() == "OPTIONS":
        return CORS_PREFLIGHT
    if _is_analytics_host(host):
        return ANALYTICS
    if (resource_type or "").strip().lower() in _ASSET_RESOURCE_TYPES:
        return STATIC_ASSET
    if _has_asset_extension(path):
        return STATIC_ASSET
    if _is_asset_media_type(_media_type(response_media_type)):
        return STATIC_ASSET
    return None


class HarOptionsError(ValueError):
    """Raised when an import option this adapter owns has the wrong shape."""


def _string_list(options: Mapping[str, Any], name: str) -> Tuple[str, ...]:
    """Read an option given as a list of strings or one comma-separated string."""
    value = options.get(name)
    if value is None:
        return ()
    if isinstance(value, str):
        items: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise HarOptionsError(f"{name} must be a list of strings or a comma-separated string")
    cleaned = []
    for item in items:
        if not isinstance(item, str):
            raise HarOptionsError(f"{name} must contain only strings")
        if item.strip():
            cleaned.append(item.strip().lower())
    return tuple(dict.fromkeys(cleaned))


@dataclass(frozen=True)
class HarOptions:
    """The user's tuning of a HAR import.

    Attributes:
        hosts: Hosts to import (lower-cased, ``host`` or ``host:port``). Empty selects the host with
            the most API calls.
        include: ``host/path`` glob patterns kept even when the built-in filter calls them noise.
        exclude: ``host/path`` glob patterns always dropped (an exclude beats an include).
        keep_noise: When ``True`` the built-in filter is off; patterns and host selection still apply.
    """

    hosts: Tuple[str, ...] = ()
    include: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()
    keep_noise: bool = False

    @classmethod
    def from_mapping(cls, options: Optional[Mapping[str, Any]]) -> "HarOptions":
        """Read the HAR options from an import's ``options`` mapping, ignoring every other key.

        Args:
            options: The import request's options (may be ``None``).

        Returns:
            The parsed options (defaults when none are given).

        Raises:
            HarOptionsError: When an option is present with the wrong type.
        """
        if not isinstance(options, Mapping):
            return cls()
        keep_noise = options.get(HAR_KEEP_NOISE_OPTION, False)
        if keep_noise is None:
            keep_noise = False
        if not isinstance(keep_noise, bool):
            raise HarOptionsError(f"{HAR_KEEP_NOISE_OPTION} must be true or false")
        return cls(
            hosts=_string_list(options, HAR_HOSTS_OPTION),
            include=_string_list(options, HAR_INCLUDE_OPTION),
            exclude=_string_list(options, HAR_EXCLUDE_OPTION),
            keep_noise=keep_noise,
        )

    @property
    def is_default(self) -> bool:
        """True when no option was set."""
        return self == HarOptions()

    def as_dict(self) -> dict:
        """Serialize for the model's ``extras`` record."""
        return {
            "hosts": list(self.hosts),
            "include": list(self.include),
            "exclude": list(self.exclude),
            "keep_noise": self.keep_noise,
        }

    @staticmethod
    def _matches(patterns: Tuple[str, ...], host: str, path: str) -> bool:
        target = f"{host}{path}".lower()
        return any(fnmatch.fnmatchcase(target, pattern) for pattern in patterns)

    def is_included(self, host: str, path: str) -> bool:
        """True when ``host/path`` matches a ``har_include`` pattern."""
        return self._matches(self.include, host, path)

    def is_excluded(self, host: str, path: str) -> bool:
        """True when ``host/path`` matches a ``har_exclude`` pattern."""
        return self._matches(self.exclude, host, path)
