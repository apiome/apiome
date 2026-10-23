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

import json
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from .canonical_model import ApiParadigm, CanonicalApi, MessageRole, Server, ServerVariable
from .hoppscotch_parser import FORMAT_KEY, HoppscotchDocument, HoppscotchRequest
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

_FOLDER_SEPARATOR = " / "


def _limit(construct: str, locations: List[str], note: str) -> Dict[str, Any]:
    """One declared-limit record, in the shape the coverage ledger reads."""
    return {"construct": construct, "count": len(locations), "locations": sorted(set(locations)), "note": note}


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


def _folders(source: HoppscotchDocument) -> List[str]:
    """Every folder level that holds a request, directly or in a sub-folder, as a path."""
    return sorted(
        {
            _FOLDER_SEPARATOR.join(request.folder[:depth])
            for request in source.requests
            for depth in range(1, len(request.folder) + 1)
        }
    )


def _requests_by_sample(source: HoppscotchDocument) -> Dict[Tuple[str, str], List[HoppscotchRequest]]:
    """Index the parsed requests by ``(method, url)`` — the coordinates the engine reports samples by."""
    index: Dict[Tuple[str, str], List[HoppscotchRequest]] = defaultdict(list)
    for request in source.requests:
        index[(request.method, request.url)].append(request)
    return index


def _annotate_operations(api: CanonicalApi, source: HoppscotchDocument) -> Set[str]:
    """Add folder tags, auth and body content types to the engine's operations.

    Args:
        api: The engine's model (modified in place).
        source: The parsed upload.

    Returns:
        Every canonical auth scheme an operation declares.
    """
    index = _requests_by_sample(source)
    schemes: Set[str] = set()
    for service in api.services:
        for operation in service.operations:
            evidence = operation.extras.get("inference_evidence") or {}
            matched: List[HoppscotchRequest] = []
            for url in dict.fromkeys(evidence.get("sample_urls") or []):
                matched.extend(index.get((operation.http_method or "", url), []))
            operation.tags = sorted({_FOLDER_SEPARATOR.join(req.folder) for req in matched if req.folder})
            unique = {
                json.dumps(req.auth.as_dict(), sort_keys=True): req.auth.as_dict()
                for req in matched
                if req.auth is not None
            }
            if unique:
                records = [unique[key] for key in sorted(unique)]
                operation.extras[AUTH_EXTRAS_KEY] = records
                operation.extras["security"] = sorted({record["scheme"] for record in records})
                schemes.update(operation.extras["security"])
            content_types = sorted({req.content_type for req in matched if req.content_type})
            for message in operation.messages:
                if message.role is MessageRole.REQUEST and content_types:
                    message.content_types = content_types
    return schemes


def _template_servers(source: HoppscotchDocument) -> List[Server]:
    """One ``{variable}`` server per leading endpoint variable, its default from the environment."""
    servers: List[Server] = []
    for name in sorted(source.server_variables):
        default = source.server_variables[name]
        servers.append(
            Server(
                url="{" + name + "}",
                name=name,
                variables=[
                    ServerVariable(
                        name=name,
                        default=default,
                        description=f"Hoppscotch variable `<<{name}>>`.",
                    )
                ],
            )
        )
    return servers


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
        schemes = _annotate_operations(api, source)
        api.servers = sorted(api.servers + _template_servers(source), key=lambda server: server.url)
        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        extras[HOPPSCOTCH_EXTRAS_KEY] = {
            "collection_versions": source.collection_versions,
            "environments": sorted(source.environments),
            "folders": _folders(source),
            "requests": len(source.requests),
            "variables": [variable.as_dict() for variable in source.variables],
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
