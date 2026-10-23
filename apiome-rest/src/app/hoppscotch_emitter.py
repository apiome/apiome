"""Hoppscotch emitter: canonical model → Hoppscotch collection + environment — FMT-10.4 (#5479).

The inverse of :mod:`app.hoppscotch_parser`. The export is the pair a Hoppscotch user imports: a
collection export (``<name>.hoppscotch_collection.json``) holding one saved request per HTTP
operation, foldered by tag, and an environment export (``<name>.hoppscotch_environment.json``)
declaring the ``<<baseUrl>>`` the requests are written against plus every credential variable they
reference — each of those with an empty value and ``"secret": true``. Requests, values, auth and
losses are planned by :mod:`app.client_collection_emit`; this module only writes Hoppscotch's JSON.

**Auth.** ``bearer``, ``basic``, ``digest``, ``apiKey`` and ``oauth2`` become Hoppscotch auth blocks
whose credential fields are ``<<variable>>`` references (``<<accessToken>>``, ``<<username>>`` /
``<<password>>``, ``<<apiKey>>``, ``<<clientId>>`` / ``<<clientSecret>>``); a generic
``authorization`` or ``cookie`` requirement becomes a header holding a reference. When every request
uses the same auth it is set once on the collection and each request inherits it, which is how a
Hoppscotch user sets it up and how the importer reads it back.

**Versions.** The collection is written at schema ``v`` 6 (requests ``"v": "11"``) and the
environment at ``v`` 2 — versions every current Hoppscotch release imports and migrates forward.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlencode

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection_emit import (
    ClientAuth,
    ClientBody,
    ClientCollectionFidelityRulePack,
    ClientPair,
    CollectionPlan,
    PlannedRequest,
    client_collection_profile,
    output_slug,
    plan_collection,
)
from .emitter import CapabilityProfile, EmitOptions, EmitOptionsError, EmitResult, EmittedFile, Emitter
from .fidelity_rulepack import CapabilityRulePack
from .hoppscotch_parser import FORMAT_KEY

__all__ = [
    "HOPPSCOTCH_AUTH_BLOCKS",
    "HoppscotchEmitOptions",
    "HoppscotchEmitter",
    "HoppscotchFidelityRulePack",
    "validate_hoppscotch_export",
]

#: Collection schema version written (and the folder version, which Hoppscotch keeps equal).
COLLECTION_VERSION = 6
#: Request schema version written.
REQUEST_VERSION = "11"
#: Environment schema version written.
ENVIRONMENT_VERSION = 2

#: Canonical schemes Hoppscotch writes as an auth block.
HOPPSCOTCH_AUTH_BLOCKS = frozenset({"bearer", "basic", "digest", "apiKey", "oauth2"})

_MEDIA_TYPE = "application/json"
_INHERIT = {"authType": "inherit", "authActive": True}
_NO_AUTH = {"authType": "none", "authActive": True}


def ref(variable: str) -> str:
    """A Hoppscotch variable reference."""
    return f"<<{variable}>>"


def validate_hoppscotch_export(members: Dict[str, str]) -> None:
    """Validate an emitted collection + environment by re-parsing them as an upload.

    The post-emit gate: the files go back through the ``hoppscotch`` import adapter — the same
    reader an intake uses — so an export is held to everything an import would reject.

    Args:
        members: The emitted files' text keyed by path.

    Raises:
        ValueError: When the files do not re-parse as a Hoppscotch upload.
    """
    from .fileset import IntakeFileset
    from .hoppscotch_import_source import HoppscotchImportSource
    from .import_source import ImportSourceError

    root = next((path for path in sorted(members) if "collection" in path), sorted(members)[0])
    try:
        HoppscotchImportSource().parse_fileset(IntakeFileset.from_members(members, root=root))
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Hoppscotch export: {exc}") from exc


class HoppscotchFidelityRulePack(ClientCollectionFidelityRulePack):
    """Fidelity rules for Hoppscotch export (shared with Thunder Client; see the base class)."""

    target_label = "Hoppscotch collection"
    format_key = FORMAT_KEY


class HoppscotchEmitOptions(EmitOptions):
    """Per-target options for :class:`HoppscotchEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")


class HoppscotchEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Hoppscotch collection and its environment."""

    key = FORMAT_KEY
    format = FORMAT_KEY
    label = "Hoppscotch"
    description = (
        "Export as a Hoppscotch collection and environment: one saved request per operation, foldered "
        "by tag, against a <<baseUrl>> variable, with auth as secret placeholder variables."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = HoppscotchEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A call surface: operations only (see :func:`app.client_collection_emit.client_collection_profile`)."""
        return client_collection_profile()

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Hoppscotch degradation rules."""
        return HoppscotchFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[HoppscotchEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as a collection export and an environment export.

        Args:
            api: The canonical model to export.
            opts: Per-target options.

        Returns:
            A two-file :class:`~app.emitter.EmitResult` (collection first).

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            ValueError: When ``api`` has no HTTP operation.
        """
        options = _coerce_options(opts)
        plan = plan_collection(api, target_label="Hoppscotch", auth_blocks=HOPPSCOTCH_AUTH_BLOCKS)
        indent = options.indent if options.indent > 0 else None
        slug = output_slug(api)
        documents = [
            (f"{slug}.hoppscotch_collection.json", _collection(plan)),
            (f"{slug}.hoppscotch_environment.json", _environment(plan)),
        ]
        return EmitResult(
            files=[
                EmittedFile(
                    path=path,
                    content=json.dumps(document, indent=indent, ensure_ascii=False) + "\n",
                    media_type=_MEDIA_TYPE,
                )
                for path, document in documents
            ],
            media_type=_MEDIA_TYPE,
            provenance=plan.tracker.records(),
            losses=plan.losses.records(),
        )


def _coerce_options(opts: Optional[Union[HoppscotchEmitOptions, EmitOptions]]) -> HoppscotchEmitOptions:
    """Validate caller-supplied options into :class:`HoppscotchEmitOptions`."""
    if isinstance(opts, HoppscotchEmitOptions):
        return opts
    try:
        return HoppscotchEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Hoppscotch emit options: {exc}") from exc


# ===========================================================================
# Rendering
# ===========================================================================


def _value(pair: ClientPair) -> str:
    """A pair's saved value: a reference for a credential, else the literal."""
    return pair.prefix + ref(pair.variable) if pair.variable else pair.value


def _pairs(pairs: Tuple[ClientPair, ...]) -> List[Dict[str, Any]]:
    """Hoppscotch ``params`` / ``headers`` entries."""
    return [{"key": pair.name, "value": _value(pair), "active": pair.enabled, "description": ""} for pair in pairs]


def _auth(auth: Optional[ClientAuth]) -> Dict[str, Any]:
    """A Hoppscotch auth block; every credential field is a variable reference."""
    if auth is None:
        return dict(_NO_AUTH)
    block: Dict[str, Any] = {"authType": "none", "authActive": True}
    if auth.scheme == "bearer":
        block.update(authType="bearer", token=ref("accessToken"))
    elif auth.scheme in ("basic", "digest"):
        block.update(authType=auth.scheme, username=ref("username"), password=ref("password"))
    elif auth.scheme == "apiKey":
        block.update(
            authType="api-key",
            key=auth.parameter,
            value=ref("apiKey"),
            addTo="QUERY_PARAMS" if auth.location == "query" else "HEADERS",
        )
    elif auth.scheme == "oauth2":
        block.update(
            authType="oauth-2",
            grantTypeInfo={
                "grantType": (auth.grant_type or "client_credentials").upper(),
                "authEndpoint": auth.token_url or "",
                "clientID": ref("clientId"),
                "clientSecret": ref("clientSecret"),
                "scopes": " ".join(auth.scopes),
                "token": "",
            },
            addTo="HEADERS",
        )
    return block


def _body(body: Optional[ClientBody]) -> Dict[str, Any]:
    """A Hoppscotch body: text, URL-encoded text, or multipart field list."""
    if body is None:
        return {"contentType": None, "body": None}
    if not body.is_form:
        return {"contentType": body.content_type, "body": body.text(ref)}
    if "multipart" in body.content_type:
        return {
            "contentType": body.content_type,
            "body": [
                {"key": field.name, "value": _value(field), "active": True, "isFile": False} for field in body.fields
            ],
        }
    encoded = urlencode([(field.name, _value(field)) for field in body.fields], safe="<>", quote_via=quote)
    return {"contentType": body.content_type, "body": encoded}


def _endpoint(plan: CollectionPlan, request: PlannedRequest) -> str:
    """``<<baseUrl>>`` (or the request's own origin) + the path, each path parameter as ``<<name>>``."""
    path = "".join(ref(text) if kind == "param" else text for kind, text in request.path)
    return (request.origin or ref(plan.base_variable)) + path


def _request(plan: CollectionPlan, request: PlannedRequest) -> Dict[str, Any]:
    """One saved Hoppscotch request."""
    return {
        "v": REQUEST_VERSION,
        "name": request.name,
        "method": request.method,
        "endpoint": _endpoint(plan, request),
        "params": _pairs(request.query),
        "headers": _pairs(request.headers),
        "auth": dict(_INHERIT) if plan.shared_auth is not None else _auth(request.auth),
        "body": _body(request.body),
        "preRequestScript": "",
        "testScript": "",
        "requestVariables": [{"key": name, "value": value, "active": True} for name, value in request.path_values],
    }


def _node(name: str) -> Dict[str, Any]:
    """An empty collection / folder node."""
    return {"v": COLLECTION_VERSION, "name": name, "folders": [], "requests": [], "auth": dict(_INHERIT), "headers": []}


def _collection(plan: CollectionPlan) -> Dict[str, Any]:
    """The collection export: folders nested by path, requests in plan order."""
    root = _node(plan.title)
    root["auth"] = _auth(plan.shared_auth)
    nodes: Dict[Tuple[str, ...], Dict[str, Any]] = {(): root}
    for path in plan.folders():
        node = _node(path[-1])
        nodes[path[:-1]]["folders"].append(node)
        nodes[path] = node
    for request in plan.requests:
        nodes[request.folder]["requests"].append(_request(plan, request))
    return root


def _environment(plan: CollectionPlan) -> Dict[str, Any]:
    """The environment export: the base URL and every credential (empty, secret)."""
    return {
        "v": ENVIRONMENT_VERSION,
        "name": plan.title,
        "variables": [
            {
                "key": variable.name,
                "initialValue": variable.value,
                "currentValue": variable.value,
                "secret": variable.secret,
            }
            for variable in plan.variables
        ],
    }
