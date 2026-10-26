"""HAR capture → canonical model normalizer — MFI-32.2 (#4404).

The observations :mod:`app.har_parser` reads are handed to the shared inferred-spec engine
(:mod:`app.inferred_spec`), which clusters them into parameterized operations, unions parameters and
widens body schemas across samples — none of that is forked here. What the engine has no slot for is
layered on afterwards with the same helper the API-client importers use
(:func:`app.client_collection.annotate_operations`):

* **auth:** the scheme each captured request carried (``bearer``, ``basic``, ``apiKey``, ``cookie``)
  becomes the operation's ``extras["security"]`` (read by :mod:`app.canonical_security`) — never the
  credential;
* **body content types:** a request message carries the body's captured media type instead of the
  engine's JSON default;
* **the capture record** in ``extras["har"]``: HAR versions and creators, every host with its API
  call count and whether this import selected it, the options that shaped the read, how many
  entries were left out and why, and the declared limits the coverage ledger reads.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection import annotate_operations
from .har_filters import (
    ANALYTICS,
    CORS_PREFLIGHT,
    EXCLUDED_BY_PATTERN,
    NON_HTTP,
    STATIC_ASSET,
    UNSELECTED_HOST,
)
from .har_parser import FORMAT_KEY, HarDocument
from .inferred_spec import infer_canonical_api
from .normalizer import Normalizer, normalize_ordering

__all__ = ["AUTH_EXTRAS_KEY", "HAR_EXTRAS_KEY", "LIMIT_LOCATION_CAP", "PARTIAL_LIMITS", "HarNormalizer"]

#: The root extras key holding the HAR capture record.
HAR_EXTRAS_KEY = "har"

#: The operation extras key holding each captured auth scheme record.
AUTH_EXTRAS_KEY = "har_auth"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a set of entries left out.
PARTIAL_LIMITS = frozenset({"har.auth_credential", "har.cookie"})

#: At most this many distinct locations are listed per limit; ``count`` still counts every entry.
LIMIT_LOCATION_CAP = 25

#: Exclusion reason → (limit construct, what the import did).
_EXCLUSION_LIMITS: Dict[str, tuple] = {
    STATIC_ASSET: (
        "har.static_asset",
        "Page assets (documents, scripts, stylesheets, images, fonts, media) are not API calls and were "
        "left out. Keep them with the `har_keep_noise` option or a `har_include` pattern.",
    ),
    ANALYTICS: (
        "har.analytics",
        "Calls to analytics, tag-manager, error-reporting and session-replay vendors were left out. "
        "Keep them with a `har_include` pattern.",
    ),
    CORS_PREFLIGHT: (
        "har.cors_preflight",
        "CORS preflight (`OPTIONS`) requests the browser sent on the page's behalf were left out.",
    ),
    NON_HTTP: (
        "har.non_http",
        "Entries that are not HTTP(S) requests (`data:`, `blob:`, WebSocket, extension URLs) were left out.",
    ),
    EXCLUDED_BY_PATTERN: (
        "har.excluded_by_pattern",
        "Entries matching a `har_exclude` pattern were left out.",
    ),
    UNSELECTED_HOST: (
        "har.unselected_host",
        "API calls to another host were left out: each host becomes its own catalog item. Import the "
        "same capture again with the `har_hosts` option to catalog another host.",
    ),
}


def _limit(construct: str, locations: Sequence[str], note: str) -> Dict[str, Any]:
    """One declared-limit record: every entry counted, at most :data:`LIMIT_LOCATION_CAP` locations."""
    distinct = sorted(set(locations))
    return {
        "construct": construct,
        "count": len(locations),
        "locations": distinct[:LIMIT_LOCATION_CAP],
        "note": note,
    }


def _capability_limits(source: HarDocument) -> List[Dict[str, Any]]:
    """The entries the import left out and the details it withheld, for the coverage ledger."""
    limits: List[Dict[str, Any]] = []
    for reason, locations in sorted(source.exclusions.items()):
        construct, note = _EXCLUSION_LIMITS.get(reason, (f"har.{reason}", "Entries were left out."))
        limits.append(_limit(construct, locations, note))
    if source.credential_entries:
        authed = [entry.location for entry in source.requests if entry.carries_credential]
        limits.append(
            _limit(
                "har.auth_credential",
                authed,
                "The `Authorization` scheme is kept; the captured credential is never stored.",
            )
        )
    if source.cookie_entries:
        cookied = [entry.location for entry in source.requests if entry.carries_cookies]
        limits.append(
            _limit(
                "har.cookie",
                cookied,
                "Cookies are never read: a `Cookie` header is kept by name only (as cookie auth) and the "
                "`cookies` lists are skipped.",
            )
        )
    return limits


class HarNormalizer(Normalizer, register=True):
    """Normalize a parsed HAR capture via the shared inferred-spec engine."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed HAR capture.

        Args:
            source: A :class:`~app.har_parser.HarDocument`.
            include_raw: Whether to keep the engine's observation summary on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations for the selected host.

        Raises:
            ValueError: When ``source`` is not a parsed HAR document.
        """
        if not isinstance(source, HarDocument):
            raise ValueError("HAR source must be a HarDocument (see app.har_parser.parse_har_text)")
        api = infer_canonical_api(
            source.observations,
            title=source.title,
            format_key=FORMAT_KEY,
            include_raw=include_raw,
        ).api
        schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[HAR_EXTRAS_KEY] = {
            "versions": source.versions,
            "creators": source.creators,
            "entries": source.total_entries,
            "api_calls": len(source.requests),
            "hosts": [host.as_dict() for host in source.hosts],
            "excluded": {reason: len(locations) for reason, locations in sorted(source.exclusions.items())},
            "options": source.options.as_dict(),
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
