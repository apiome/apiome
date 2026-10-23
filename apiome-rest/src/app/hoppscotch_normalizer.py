"""Hoppscotch collection → canonical model normalizer — FMT-10.1 (#5473).

The observations :mod:`app.hoppscotch_parser` reads are handed to the shared inferred-spec engine
(:mod:`app.inferred_spec`), which templates paths, unions parameters and infers body schemas — the
same engine every collection and capture format uses, so none of that is forked here. What the
engine has no slot for is layered on afterwards:

* **folders → operation groups:** each operation is tagged with the folder path(s) its requests
  sit in (``Catalogue / Products``);
* **auth:** the scheme each request resolves to after inheritance is recorded as the operation's
  ``extras["security"]`` (read by :mod:`app.canonical_security`) and, with its parameter names, as
  ``extras["hoppscotch_auth"]`` — never a credential;
* **body content types:** the request message carries the body's real media type
  (``application/x-www-form-urlencoded``, ``multipart/form-data``) instead of the engine's JSON
  default;
* **environment variables → server variables:** an endpoint written ``<<baseUrl>>/…`` becomes a
  ``{baseUrl}`` server whose variable default comes from the environment (secret variables keep no
  default);
* **declared limits** (scripts, withheld credentials, secret variables) in
  ``extras["hoppscotch"]["capability_limits"]``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection import annotate_operations, declared_limit, folder_paths, template_servers
from .hoppscotch_parser import FORMAT_KEY, HoppscotchDocument
from .inferred_spec import infer_canonical_api
from .normalizer import Normalizer, normalize_ordering

__all__ = ["HOPPSCOTCH_EXTRAS_KEY", "HoppscotchNormalizer", "PARTIAL_LIMITS"]

#: The root extras key holding the Hoppscotch projection record.
HOPPSCOTCH_EXTRAS_KEY = "hoppscotch"

#: The operation extras key holding each resolved auth declaration (scheme + parameter names).
AUTH_EXTRAS_KEY = "hoppscotch_auth"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset({"hoppscotch.auth_credential", "hoppscotch.secret_variable"})

_limit = declared_limit


def _capability_limits(source: HoppscotchDocument) -> List[Dict[str, Any]]:
    """The constructs the import leaves out or withholds, for the coverage ledger."""
    limits: List[Dict[str, Any]] = []
    scripted = [request.name for request in source.requests if request.has_scripts]
    if scripted:
        limits.append(
            _limit(
                "hoppscotch.script",
                scripted,
                "Pre-request and test scripts are JavaScript run by the client; they are not modelled.",
            )
        )
    authed = [request.name for request in source.requests if request.auth is not None]
    if authed:
        limits.append(
            _limit(
                "hoppscotch.auth_credential",
                authed,
                "The auth scheme and its parameter names are kept; saved credentials are never read.",
            )
        )
    secret = [variable.name for variable in source.variables if variable.secret]
    if secret:
        limits.append(
            _limit(
                "hoppscotch.secret_variable",
                secret,
                "A secret variable is listed by name; its value is withheld.",
            )
        )
    return limits


class HoppscotchNormalizer(Normalizer, register=True):
    """Normalize a parsed Hoppscotch upload via the shared inferred-spec engine."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed Hoppscotch upload.

        Args:
            source: A :class:`~app.hoppscotch_parser.HoppscotchDocument`.
            include_raw: Whether to keep the engine's observation summary on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations.

        Raises:
            ValueError: When ``source`` is not a parsed Hoppscotch document.
        """
        if not isinstance(source, HoppscotchDocument):
            raise ValueError(
                "Hoppscotch source must be a HoppscotchDocument (see app.hoppscotch_parser.parse_hoppscotch_text)"
            )
        api = infer_canonical_api(
            source.observations,
            title=source.title,
            format_key=FORMAT_KEY,
            include_raw=include_raw,
        ).api
        schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
        servers = template_servers(source.server_variables, describe=lambda name: f"Hoppscotch variable `<<{name}>>`.")
        api.servers = sorted(api.servers + servers, key=lambda server: server.url)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[HOPPSCOTCH_EXTRAS_KEY] = {
            "collection_versions": source.collection_versions,
            "environments": sorted(source.environments),
            "folders": folder_paths(source.requests),
            "requests": len(source.requests),
            "variables": [variable.as_dict() for variable in source.variables],
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
