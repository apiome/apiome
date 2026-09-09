"""Where a canonical model records authentication — the one place that reads it.

The canonical model (:mod:`app.canonical_model`) has no first-class security field: importers
record auth in ``extras`` instead, and they record it in two shapes that mean **different
things**. Three emitters need to read those shapes, so the reading rules live here rather than
once per emitter:

* :class:`app.http_file_emitter.HttpFileEmitter` turns a scheme into a request header;
* :mod:`app.llm_tools_emitter` names the schemes a tool array is dropping;
* :mod:`app.go_client_generator` turns a scheme into a Go client option (SDK-2.4, #4488).

**The two shapes.**

``operation.extras["security"]`` — what an OpenAPI or gateway import writes — is a *per-operation
requirement*: this call needs this credential. A generator may act on it.

``api.extras["inferred_auth_schemes"]`` — what an inferred import (a cURL or request-file intake)
writes — says only that the API was *observed* using a scheme somewhere. Acting on it per
operation would assert a requirement no source stated. :func:`operation_security_schemes` keeps
the two apart by returning the scope alongside the schemes so a caller can apply that rule;
:func:`declared_security_schemes` deliberately merges them, because "which schemes does this API
mention at all" is a different and weaker question.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .canonical_model import CanonicalApi, Operation

__all__ = [
    "AUTH_SCHEME_HEADERS",
    "declared_security_schemes",
    "operation_security_schemes",
]

#: Canonical security-scheme identifier → the ``(header name, header value)`` that carries it.
#:
#: The mapping is the inverse of the one :mod:`app.inferred_spec` reads schemes back out with, so
#: an emitted header re-imports to the scheme it was emitted from. A scheme absent from this table
#: has no request-header representation (``mutualTLS``) and callers report that rather than
#: approximating it.
AUTH_SCHEME_HEADERS: Dict[str, Tuple[str, str]] = {
    "authorization": ("Authorization", "$AUTHORIZATION"),
    "bearer": ("Authorization", "Bearer $ACCESS_TOKEN"),
    "basic": ("Authorization", "Basic $CREDENTIALS"),
    "digest": ("Authorization", "Digest $CREDENTIALS"),
    "oauth2": ("Authorization", "Bearer $ACCESS_TOKEN"),
    "openIdConnect": ("Authorization", "Bearer $ACCESS_TOKEN"),
    "apiKey": ("X-API-Key", "$API_KEY"),
    "cookie": ("Cookie", "$SECRET"),
}


def _collect(entries: object) -> List[str]:
    """Read scheme identifiers out of one ``extras`` value, in order and deduplicated.

    Args:
        entries: The raw ``extras`` value — a list of names, a list of ``{"scheme": name}``
            records, or anything else (which yields nothing).

    Returns:
        The scheme identifiers, in declaration order, without repeats.
    """
    schemes: List[str] = []
    if not isinstance(entries, (list, tuple)):
        return schemes
    for entry in entries:
        scheme: Optional[str] = None
        if isinstance(entry, str):
            scheme = entry
        elif isinstance(entry, dict) and isinstance(entry.get("scheme"), str):
            scheme = entry["scheme"]
        if scheme and scheme not in schemes:
            schemes.append(scheme)
    return schemes


def operation_security_schemes(api: CanonicalApi, operation: Operation) -> Tuple[List[str], str]:
    """Return the security schemes that apply to ``operation``, and where they were declared.

    Args:
        api: The canonical model the operation belongs to.
        operation: The operation whose auth is wanted.

    Returns:
        ``(schemes, scope)`` — scheme identifiers in declaration order, deduplicated, and
        ``"operation"`` when the operation itself declared them or ``"api"`` when they are the
        model's inferred observation. An empty list has scope ``"api"`` and no effect.
    """
    declared = _collect(operation.extras.get("security"))
    if declared:
        return declared, "operation"
    return _collect(api.extras.get("inferred_auth_schemes")), "api"


def declared_security_schemes(api: CanonicalApi) -> List[str]:
    """Return every security-scheme identifier the model mentions anywhere, sorted.

    Both shapes are merged here on purpose: the question this answers is "which schemes does this
    API mention at all", which a loss report and a client's auth-helper set both ask, and neither
    is making a per-operation claim.

    Args:
        api: The model to read.

    Returns:
        The distinct scheme identifiers, sorted for determinism.
    """
    names = set()
    inferred = (api.extras or {}).get("inferred_auth_schemes")
    if isinstance(inferred, list):
        names.update(str(item) for item in inferred if item)
    elif isinstance(inferred, dict):
        names.update(str(key) for key in inferred)
    for service in api.services:
        for operation in service.operations:
            declared = (operation.extras or {}).get("security")
            if isinstance(declared, list):
                names.update(str(item) for item in declared if isinstance(item, str))
            elif isinstance(declared, str):
                names.add(declared)
    return sorted(names)
