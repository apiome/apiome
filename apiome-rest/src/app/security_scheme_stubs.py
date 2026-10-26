"""Security-scheme stubs for imported collections and captures — MFI-32.5 (#4407).

Collection and capture imports learn *that* an API uses auth — a Postman / Insomnia / Bruno auth
block, an observed ``Authorization`` header — but they must never keep the credential. This module
turns what they recorded into OpenAPI ``securityScheme`` **stubs**: the scheme's *type* and the
fields OpenAPI needs to say where a credential goes (``scheme: bearer``; an API key's ``in`` and
header ``name``), and nothing else — no token, no client secret, no flow URLs.

:func:`apply_security_scheme_stubs` writes them to ``api.extras["security_schemes"]`` (scheme name →
stub). The importers call it after recording their schemes; :mod:`app.openapi_emitter` writes the
stubs as ``components.securitySchemes`` and each operation's ``extras["security"]`` as its
``security`` requirement, so a converted catalog item carries its auth as stubs a user can fill in.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from .canonical_model import CanonicalApi
from .canonical_security import declared_security_schemes

__all__ = [
    "SECURITY_SCHEMES_EXTRAS_KEY",
    "STUB_DESCRIPTION",
    "apply_security_scheme_stubs",
    "scheme_stub",
    "security_scheme_stubs",
]

#: The root extras key holding the stubs.
SECURITY_SCHEMES_EXTRAS_KEY = "security_schemes"

#: The description every stub carries, so a reader of the converted document knows to fill it in.
STUB_DESCRIPTION = "Stub recorded at import: the scheme type only — no credential material was kept."

#: Canonical HTTP-auth schemes → their RFC 7235 scheme name.
_HTTP_SCHEMES: Mapping[str, str] = {"bearer": "bearer", "basic": "basic", "digest": "digest"}

#: API-key placements as importers spell them → OpenAPI ``in``.
_KEY_LOCATIONS: Mapping[str, str] = {
    "header": "header",
    "query": "query",
    "queryparams": "query",
    "queryparam": "query",
    "cookie": "cookie",
}


def scheme_stub(scheme: str, *, key_name: Optional[str] = None, key_location: Optional[str] = None) -> Dict[str, Any]:
    """The OpenAPI ``securityScheme`` stub for one canonical scheme identifier.

    Args:
        scheme: A canonical scheme (``bearer``, ``basic``, ``digest``, ``oauth2``, ``apiKey``,
            ``cookie``, ``authorization`` …), as :mod:`app.canonical_security` reads them.
        key_name: An API key's header / parameter (or cookie) name, when the import recorded it.
        key_location: Where an API key is sent (``header``, ``queryParams``, ``cookie``).

    Returns:
        The stub — type plus the placement fields OpenAPI requires, never a credential. An
        unrecognised scheme is a generic ``Authorization`` header requirement.
    """
    if scheme in _HTTP_SCHEMES:
        stub: Dict[str, Any] = {"type": "http", "scheme": _HTTP_SCHEMES[scheme]}
    elif scheme == "oauth2":
        stub = {"type": "oauth2", "flows": {}}
    elif scheme == "apiKey":
        location = _KEY_LOCATIONS.get(str(key_location or "header").strip().lower(), "header")
        stub = {"type": "apiKey", "in": location, "name": key_name or "X-API-Key"}
    elif scheme == "cookie":
        stub = {"type": "apiKey", "in": "cookie", "name": key_name or "session"}
    else:
        stub = {"type": "apiKey", "in": "header", "name": "Authorization"}
    stub["description"] = STUB_DESCRIPTION
    return stub


def _auth_records(api: CanonicalApi, auth_extras_key: Optional[str]) -> Iterable[Mapping[str, Any]]:
    """Every auth record (``{"scheme", "key_name", "key_location", …}``) the operations carry."""
    if not auth_extras_key:
        return []
    records: List[Mapping[str, Any]] = []
    for service in api.services:
        for operation in service.operations:
            for record in operation.extras.get(auth_extras_key) or []:
                if isinstance(record, Mapping):
                    records.append(record)
    return records


def security_scheme_stubs(
    api: CanonicalApi,
    *,
    auth_extras_key: Optional[str] = None,
    placements: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build one stub per scheme the model mentions.

    The scheme identifier is the stub's name, which is what operations' ``extras["security"]``
    refers to. For ``apiKey`` / ``cookie`` the placement comes from the first auth record (in
    model order) that names one; an import that recorded none gets OpenAPI's conventional default.

    Args:
        api: The normalized model.
        auth_extras_key: The operation extras key of the importer's auth records
            (``insomnia_auth``, ``bruno_auth`` …), or ``None``.
        placements: Scheme → ``{"key_name", "key_location"}`` for an importer whose extras do not
            carry auth records (Postman); these win over the records.

    Returns:
        Scheme name → stub, sorted by name; empty when the model mentions no auth.
    """
    placement: Dict[str, Mapping[str, Any]] = dict(placements or {})
    for record in _auth_records(api, auth_extras_key):
        scheme = record.get("scheme")
        if isinstance(scheme, str) and scheme not in placement and record.get("key_name"):
            placement[scheme] = record
    stubs: Dict[str, Dict[str, Any]] = {}
    for scheme in declared_security_schemes(api):
        record = placement.get(scheme, {})
        stubs[scheme] = scheme_stub(
            scheme,
            key_name=record.get("key_name") if isinstance(record.get("key_name"), str) else None,
            key_location=record.get("key_location") if isinstance(record.get("key_location"), str) else None,
        )
    return dict(sorted(stubs.items()))


def apply_security_scheme_stubs(
    api: CanonicalApi,
    *,
    auth_extras_key: Optional[str] = None,
    placements: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> None:
    """Write :func:`security_scheme_stubs` to ``api.extras["security_schemes"]`` (when there are any).

    Args:
        api: The normalized model (modified in place).
        auth_extras_key: See :func:`security_scheme_stubs`.
        placements: See :func:`security_scheme_stubs`.
    """
    stubs = security_scheme_stubs(api, auth_extras_key=auth_extras_key, placements=placements)
    if stubs:
        api.extras = {**api.extras, SECURITY_SCHEMES_EXTRAS_KEY: stubs}
