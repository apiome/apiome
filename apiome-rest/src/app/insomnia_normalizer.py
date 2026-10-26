"""Insomnia export → canonical model normalizer — MFI-32.3 (#4405).

The observations :mod:`app.insomnia_parser` reads are handed to the shared inferred-spec engine
(:mod:`app.inferred_spec`), which templates paths, unions parameters and infers body schemas — the
same engine every collection and capture format uses, so none of that is forked here. What the
engine has no slot for is layered on afterwards with :mod:`app.client_collection`, as for Hoppscotch
and Thunder Client:

* **folders → operation groups:** each operation is tagged with its folder path (``Users / Admin``);
* **auth:** the scheme each request resolves to after folder inheritance becomes the operation's
  ``extras["security"]`` (read by :mod:`app.canonical_security`) and, with its public facts,
  ``extras["insomnia_auth"]`` — never a credential;
* **body content types:** the request message carries the body's real media type;
* **environment variables → server variables and parameter defaults:** a URL written
  ``{{ _.baseUrl }}/…`` becomes a ``{baseUrl}`` server whose default comes from the environments,
  and a query or header parameter written as a whole variable gets that variable's value as its
  default — never for a secret variable;
* **declared limits** (scripts, template tags, gRPC / WebSocket requests, unit tests, an API spec,
  mock routes, cookie jars, withheld credentials, secret variables) in
  ``extras["insomnia"]["capability_limits"]``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence, Set, Tuple

from .canonical_model import ApiParadigm, CanonicalApi, ParameterLocation
from .client_collection import annotate_operations, declared_limit, folder_paths, template_servers
from .inferred_spec import infer_canonical_api
from .insomnia_parser import FORMAT_KEY, InsomniaDocument, InsomniaRequest
from .normalizer import Normalizer, normalize_ordering

__all__ = ["AUTH_EXTRAS_KEY", "INSOMNIA_EXTRAS_KEY", "PARTIAL_LIMITS", "InsomniaNormalizer"]

#: The root extras key holding the Insomnia projection record.
INSOMNIA_EXTRAS_KEY = "insomnia"

#: The operation extras key holding each resolved auth declaration (scheme + public facts).
AUTH_EXTRAS_KEY = "insomnia_auth"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset({"insomnia.auth_credential", "insomnia.secret_variable", "insomnia.template_tag"})

#: Construct → what the import does with what it left out.
_SKIPPED_NOTES: Dict[str, str] = {
    "insomnia.grpc_request": (
        "gRPC requests are not HTTP calls; they are not modelled. Import the `.proto` files instead."
    ),
    "insomnia.websocket_request": "WebSocket requests are not modelled.",
    "insomnia.unit_test": "Unit test suites are run by Insomnia; they are not modelled.",
    "insomnia.api_spec": "A design document's API spec is not read by this import; import it as OpenAPI.",
    "insomnia.mock_route": "Mock servers and routes are not modelled.",
    "insomnia.cookie_jar": "Cookie jars hold session state, not API description; they are never read.",
}

_LOCATIONS = {"query": ParameterLocation.QUERY, "header": ParameterLocation.HEADER}


def _capability_limits(source: InsomniaDocument) -> List[Dict[str, Any]]:
    """The constructs the import leaves out or withholds, for the coverage ledger."""
    limits: List[Dict[str, Any]] = []
    scripted = [request.name for request in source.requests if request.has_script]
    if scripted:
        limits.append(
            declared_limit(
                "insomnia.script",
                scripted,
                "Pre-request and after-response scripts are run by Insomnia; they are not modelled.",
            )
        )
    tagged = [request.name for request in source.requests if request.has_template_tag]
    if tagged:
        limits.append(
            declared_limit(
                "insomnia.template_tag",
                tagged,
                "Template tags (`{% response %}`, `{% uuid %}` …) are evaluated by Insomnia at send time; the "
                "request is kept and a tag in its path becomes a path parameter.",
            )
        )
    authed = [request.name for request in source.requests if request.auth is not None]
    if authed:
        limits.append(
            declared_limit(
                "insomnia.auth_credential",
                authed,
                "The auth scheme (and an OAuth 2 grant's grant type, URL and scopes, or an API key's name) is "
                "kept; saved credentials are never read.",
            )
        )
    secret = [variable.name for variable in source.variables if variable.secret]
    if secret:
        limits.append(
            declared_limit(
                "insomnia.secret_variable",
                secret,
                "A secret variable (by its name, or Insomnia's `secret` type) is listed by name; "
                "its value is withheld.",
            )
        )
    for construct, names in source.skipped.items():
        limits.append(declared_limit(construct, names, _SKIPPED_NOTES.get(construct, "Not modelled.")))
    return limits


def _apply_defaults(api: CanonicalApi, requests: Sequence[InsomniaRequest]) -> None:
    """Set query / header parameter defaults from the environments, where every sample agrees."""
    index: Dict[Tuple[str, str], List[InsomniaRequest]] = defaultdict(list)
    for request in requests:
        index[(request.method, request.url)].append(request)
    for service in api.services:
        for operation in service.operations:
            evidence = operation.extras.get("inference_evidence") or {}
            matched = [
                request
                for url in dict.fromkeys(evidence.get("sample_urls") or [])
                for request in index.get((operation.http_method or "", url), [])
            ]
            values: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
            for request in matched:
                for location, name, value in request.defaults:
                    values[(location, name)].add(value)
            for parameter in operation.parameters:
                for location, enum in _LOCATIONS.items():
                    found = values.get((location, parameter.name))
                    if parameter.location is enum and found and len(found) == 1:
                        parameter.default = next(iter(found))


class InsomniaNormalizer(Normalizer, register=True):
    """Normalize a parsed Insomnia upload via the shared inferred-spec engine."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed Insomnia upload.

        Args:
            source: An :class:`~app.insomnia_parser.InsomniaDocument`.
            include_raw: Whether to keep the engine's observation summary on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations.

        Raises:
            ValueError: When ``source`` is not a parsed Insomnia document.
        """
        if not isinstance(source, InsomniaDocument):
            raise ValueError(
                "Insomnia source must be an InsomniaDocument (see app.insomnia_parser.parse_insomnia_text)"
            )
        api = infer_canonical_api(
            source.observations,
            title=source.title,
            format_key=FORMAT_KEY,
            include_raw=include_raw,
        ).api
        schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
        _apply_defaults(api, source.requests)
        servers = template_servers(
            source.server_variables, describe=lambda name: f"Insomnia environment variable `{{{{ _.{name} }}}}`."
        )
        api.servers = sorted(api.servers + servers, key=lambda server: server.url)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[INSOMNIA_EXTRAS_KEY] = {
            "export_formats": source.export_formats,
            "environments": source.environments,
            "folders": folder_paths(source.requests),
            "requests": len(source.requests),
            "variables": [variable.as_dict() for variable in source.variables],
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
