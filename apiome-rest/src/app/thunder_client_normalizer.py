"""Thunder Client collection → canonical model normalizer — FMT-10.2 (#5475).

The observations :mod:`app.thunder_client_parser` reads are handed to the shared inferred-spec
engine (:mod:`app.inferred_spec`), which templates paths, unions parameters and infers body schemas
— the same engine every collection and capture format uses, so none of that is forked here. What
the engine has no slot for is layered on afterwards by :mod:`app.client_collection`, exactly as for
Hoppscotch (FMT-10.1):

* **folders → operation groups:** each operation is tagged with the folder path(s) its requests
  sit in (``Tenant A / Read``), rebuilt from the export's ``containerId`` links;
* **auth:** the scheme each request resolves to after inheritance is recorded as the operation's
  ``extras["security"]`` (read by :mod:`app.canonical_security`) and, with its public OAuth facts,
  as ``extras["thunder_client_auth"]`` — never a credential;
* **body content types:** the request message carries the body's real media type
  (``application/x-www-form-urlencoded``, ``multipart/form-data``) instead of the engine's JSON
  default;
* **environment variables → server variables:** a URL written ``{{baseUrl}}/…`` becomes a
  ``{baseUrl}`` server whose variable default comes from the environment (secret-named variables
  keep no default);
* **declared limits** (tests, pre-request steps, withheld credentials, secret variables) in
  ``extras["thunder_client"]["capability_limits"]``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection import annotate_operations, declared_limit, folder_paths, template_servers
from .inferred_spec import infer_canonical_api
from .normalizer import Normalizer, normalize_ordering
from .thunder_client_parser import FORMAT_KEY, ThunderDocument

__all__ = ["AUTH_EXTRAS_KEY", "PARTIAL_LIMITS", "THUNDER_CLIENT_EXTRAS_KEY", "ThunderClientNormalizer"]

#: The root extras key holding the Thunder Client projection record.
THUNDER_CLIENT_EXTRAS_KEY = "thunder_client"

#: The operation extras key holding each resolved auth declaration (scheme + public OAuth facts).
AUTH_EXTRAS_KEY = "thunder_client_auth"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset({"thunder-client.auth_credential", "thunder-client.secret_variable"})


def _capability_limits(source: ThunderDocument) -> List[Dict[str, Any]]:
    """The constructs the import leaves out or withholds, for the coverage ledger."""
    limits: List[Dict[str, Any]] = []
    tested = [request.name for request in source.requests if request.has_tests]
    if tested:
        limits.append(
            declared_limit(
                "thunder-client.test",
                tested,
                "Declarative tests (status, timing and JSON-query assertions, `set-env-var` captures) "
                "are run by the client; they are not modelled.",
            )
        )
    prepared = [request.name for request in source.requests if request.has_pre_request]
    if prepared:
        limits.append(
            declared_limit(
                "thunder-client.pre_request",
                prepared,
                "Pre-request steps (variable setters, pre-run requests) are run by the client; they are not modelled.",
            )
        )
    authed = [request.name for request in source.requests if request.auth is not None]
    if authed:
        limits.append(
            declared_limit(
                "thunder-client.auth_credential",
                authed,
                "The auth scheme (and an OAuth 2 grant's token URL and scopes) is kept; "
                "saved credentials are never read.",
            )
        )
    secret = [variable.name for variable in source.variables if variable.secret]
    if secret:
        limits.append(
            declared_limit(
                "thunder-client.secret_variable",
                secret,
                "A variable whose name says it holds a credential is listed by name; its value is withheld.",
            )
        )
    return limits


class ThunderClientNormalizer(Normalizer, register=True):
    """Normalize a parsed Thunder Client upload via the shared inferred-spec engine."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed Thunder Client upload.

        Args:
            source: A :class:`~app.thunder_client_parser.ThunderDocument`.
            include_raw: Whether to keep the engine's observation summary on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations.

        Raises:
            ValueError: When ``source`` is not a parsed Thunder Client document.
        """
        if not isinstance(source, ThunderDocument):
            raise ValueError(
                "Thunder Client source must be a ThunderDocument (see app.thunder_client_parser.parse_thunder_text)"
            )
        api = infer_canonical_api(
            source.observations,
            title=source.title,
            format_key=FORMAT_KEY,
            include_raw=include_raw,
        ).api
        schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
        servers = template_servers(
            source.server_variables, describe=lambda name: f"Thunder Client variable `{{{{{name}}}}}`."
        )
        api.servers = sorted(api.servers + servers, key=lambda server: server.url)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[THUNDER_CLIENT_EXTRAS_KEY] = {
            "collection_versions": source.collection_versions,
            "environments": sorted(source.environments),
            "folders": folder_paths(source.requests),
            "requests": len(source.requests),
            "variables": [variable.as_dict() for variable in source.variables],
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
