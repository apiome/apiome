"""Bruno collection → canonical model normalizer — MFI-32.4 (#4406).

The observations :mod:`app.bruno_parser` reads are handed to the shared inferred-spec engine
(:mod:`app.inferred_spec`), which templates paths, unions parameters and infers body schemas. What
the engine has no slot for is layered on afterwards with :mod:`app.client_collection`, exactly as
for Insomnia, Hoppscotch and Thunder Client:

* **folder tree → operation groups:** each operation is tagged with its folder path;
* **auth:** the scheme each request resolves to (request → folder → collection inheritance) becomes
  ``extras["security"]`` and, with its public facts, ``extras["bruno_auth"]`` — never a credential;
* **body content types:** the request message carries the body's real media type;
* **environments → server variables and parameter defaults:** a URL written ``{{baseUrl}}/…``
  becomes a ``{baseUrl}`` server whose default comes from the variables, and a parameter written as
  a whole variable gets that value as its default — never for a secret;
* **declared limits** (scripts, tests and assertions, ``{{process.env.*}}``, non-HTTP requests,
  withheld credentials, secret variables) in ``extras["bruno"]["capability_limits"]``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .bruno_parser import FORMAT_KEY, BrunoDocument
from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection import (
    annotate_operations,
    apply_parameter_defaults,
    declared_limit,
    folder_paths,
    template_servers,
)
from .inferred_spec import infer_canonical_api
from .normalizer import Normalizer, normalize_ordering
from .security_scheme_stubs import apply_security_scheme_stubs

__all__ = ["AUTH_EXTRAS_KEY", "BRUNO_EXTRAS_KEY", "PARTIAL_LIMITS", "BrunoNormalizer"]

#: The root extras key holding the Bruno projection record.
BRUNO_EXTRAS_KEY = "bruno"

#: The operation extras key holding each resolved auth declaration (scheme + public facts).
AUTH_EXTRAS_KEY = "bruno_auth"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset({"bruno.auth_credential", "bruno.secret_variable", "bruno.process_env"})


def _capability_limits(source: BrunoDocument) -> List[Dict[str, Any]]:
    """The constructs the import leaves out or withholds, for the coverage ledger."""
    limits: List[Dict[str, Any]] = []
    rows = (
        (
            "bruno.script",
            [request.name for request in source.requests if request.has_script],
            "Pre-request and post-response scripts and `vars:post-response` captures are run by Bruno; they "
            "are not modelled.",
        ),
        (
            "bruno.test",
            [request.name for request in source.requests if request.has_tests],
            "`tests` scripts and `assert` rules are run by Bruno; they are not modelled.",
        ),
        (
            "bruno.process_env",
            [request.name for request in source.requests if request.uses_process_env],
            "`{{process.env.*}}` values come from the collection's `.env` file, which is never read; the "
            "request is kept with the variable unresolved.",
        ),
        (
            "bruno.auth_credential",
            [request.name for request in source.requests if request.auth is not None],
            "The auth scheme (and an OAuth 2 grant's grant type, URL and scopes, or an API key's name) is "
            "kept; saved credentials are never read.",
        ),
        (
            "bruno.secret_variable",
            [variable.name for variable in source.variables if variable.secret],
            "A secret variable (`vars:secret`, or by its name) is listed by name; its value is withheld.",
        ),
    )
    for construct, locations, note in rows:
        if locations:
            limits.append(declared_limit(construct, locations, note))
    for construct, names in source.skipped.items():
        limits.append(
            declared_limit(construct, names, "Requests that are not HTTP (gRPC, WebSocket) are not modelled.")
        )
    return limits


class BrunoNormalizer(Normalizer, register=True):
    """Normalize a parsed Bruno collection via the shared inferred-spec engine."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed Bruno collection.

        Args:
            source: A :class:`~app.bruno_parser.BrunoDocument`.
            include_raw: Whether to keep the engine's observation summary on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations.

        Raises:
            ValueError: When ``source`` is not a parsed Bruno document.
        """
        if not isinstance(source, BrunoDocument):
            raise ValueError("Bruno source must be a BrunoDocument (see app.bruno_parser.parse_bruno_fileset)")
        api = infer_canonical_api(
            source.observations,
            title=source.title,
            format_key=FORMAT_KEY,
            include_raw=include_raw,
        ).api
        schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
        apply_parameter_defaults(api, source.requests)
        servers = template_servers(source.server_variables, describe=lambda name: f"Bruno variable `{{{{{name}}}}}`.")
        api.servers = sorted(api.servers + servers, key=lambda server: server.url)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[BRUNO_EXTRAS_KEY] = {
            "bruno_version": source.bruno_version,
            "environments": source.environments,
            "folders": folder_paths(source.requests),
            "requests": len(source.requests),
            "variables": [variable.as_dict() for variable in source.variables],
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        apply_security_scheme_stubs(api, auth_extras_key=AUTH_EXTRAS_KEY)
        return normalize_ordering(api)
