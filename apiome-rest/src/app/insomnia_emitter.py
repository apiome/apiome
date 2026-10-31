"""Insomnia emitter: canonical model → Insomnia v4 export — MFX-31.3 (#4291).

The inverse of :mod:`app.insomnia_parser` (v4 reading). The export is the one JSON document Insomnia
writes with **Export → Insomnia v4** and reads with **Import**: ``{"_type": "export",
"__export_format": 4, "resources": [...]}`` — a *flat* list linked by ``parentId``:

* one ``workspace`` (``scope: collection``) named after the API;
* one ``request_group`` per folder level, under its parent folder (or the workspace);
* one ``request`` per HTTP operation (and per body media type), under its folder;
* one base ``environment`` whose ``data`` holds the ``baseUrl`` the requests are written against and
  every credential variable they reference, each credential with an empty value.

Requests, values, auth and losses are planned by :mod:`app.client_collection_emit` — the request tree
the Postman collection (MFX-31.1), Hoppscotch and Thunder Client are written from — and this module
only writes Insomnia's JSON. Variables are Nunjucks references (``{{ _.baseUrl }}``).

**Auth.** ``bearer``, ``basic``, ``digest``, ``apiKey`` and ``oauth2`` become Insomnia
``authentication`` blocks whose credential fields are variable references; an ``authorization`` or
``cookie`` requirement travels as a header holding a reference. Insomnia v4 has no collection-level
auth, so a request carries its own block even when every request shares it.

**Not carried** (reported by :class:`InsomniaFidelityRulePack` and the plan's losses): declared
responses (an export saves the call, not the reply), the API description, servers beyond the first,
and the schemas behind the example bodies.

**Determinism.** Resource ids are derived from the collection name and each item's position
(``req_<uuid5 hex>``), and no timestamps are written, so two exports of the same model are
byte-identical.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection_emit import (
    ClientAuth,
    ClientBody,
    ClientPair,
    CollectionPlan,
    PlannedRequest,
    client_collection_profile,
    output_slug,
    plan_collection,
)
from .client_collection_fidelity import ExampleCollectionFidelityRulePack
from .emitter import CapabilityProfile, EmitOptions, EmitOptionsError, EmitResult, EmittedFile, Emitter
from .fidelity_rulepack import CapabilityRulePack
from .insomnia_parser import FORMAT_KEY

__all__ = [
    "INSOMNIA_AUTH_BLOCKS",
    "InsomniaEmitOptions",
    "InsomniaEmitter",
    "InsomniaFidelityRulePack",
    "validate_insomnia_export",
]

#: Canonical schemes Insomnia writes as an ``authentication`` block.
INSOMNIA_AUTH_BLOCKS = frozenset({"bearer", "basic", "digest", "apiKey", "oauth2"})

#: The ``__export_source`` stamp (Insomnia records the app that wrote an export there). It names the
#: format, which is what lets format detection claim the file firmly as an Insomnia v4 export.
EXPORT_SOURCE = "apiome:insomnia-v4-export"

_MEDIA_TYPE = "application/json"
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://apiome.dev/export/insomnia")
#: A path parameter Insomnia can spell ``:name`` — a whole segment with a plain name.
_COLON_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
#: Insomnia orders siblings by ``metaSortKey`` (ascending); spaced so a user can insert between.
_SORT_STEP = 100


def ref(variable: str) -> str:
    """An Insomnia (Nunjucks) environment-variable reference: ``{{ _.name }}``."""
    return "{{ _." + variable + " }}"


def validate_insomnia_export(text: str) -> None:
    """Validate an emitted export by re-parsing it as an upload through the Insomnia reader.

    Args:
        text: The export JSON.

    Raises:
        ValueError: When the text is not an Insomnia v4 export the importer reads.
    """
    from .insomnia_parser import InsomniaParseError, parse_insomnia_text

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Insomnia export: not JSON ({exc.msg})") from exc
    if not isinstance(document, dict) or document.get("_type") != "export" or document.get("__export_format") != 4:
        raise ValueError("Invalid Insomnia export: not an Insomnia v4 export (`_type: export`, `__export_format: 4`)")
    try:
        parse_insomnia_text(text)
    except InsomniaParseError as exc:
        raise ValueError(f"Invalid Insomnia export: {exc}") from exc


class InsomniaFidelityRulePack(ExampleCollectionFidelityRulePack):
    """Fidelity rules for Insomnia export.

    The example-collection rules (MFX-31.2, :mod:`app.client_collection_fidelity`): schemas become
    example bodies, unions one representative example, generated values are synthesized, streaming
    and auth Insomnia has no type for are named. An Insomnia export saves no responses, so declared
    responses are dropped.
    """

    target_label = "Insomnia export"
    format_key = FORMAT_KEY
    auth_blocks = INSOMNIA_AUTH_BLOCKS
    carries_responses = False
    native_is_lossless = False


class InsomniaEmitOptions(EmitOptions):
    """Per-target options for :class:`InsomniaEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")
    folder_strategy: Literal["tag", "auto", "service", "flat"] = Field(
        default="tag",
        description="How requests are filed into folders: `tag` (first tag), `auto` (first tag, else service "
        "when the API has more than one), `service` or `flat`. An item imported from Insomnia keeps its own "
        "folders under `tag`.",
    )
    example_depth: Literal["minimal", "full"] = Field(
        default="minimal",
        description="Synthesized example bodies fill required properties only (`minimal`) or every "
        "declared property (`full`).",
    )


class InsomniaEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an Insomnia v4 export document."""

    key = FORMAT_KEY
    format = FORMAT_KEY
    label = "Insomnia"
    description = (
        "Export as an Insomnia v4 export: a workspace with one request per operation, foldered by tag, "
        "against a {{ _.baseUrl }} environment variable, with auth as empty placeholder variables."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = InsomniaEmitOptions
    #: X1 (#6222): refused with a reason, never crashed, when the source lacks this.
    requires_source = ("http-operation",)

    OUTPUT_MEDIA_TYPE = _MEDIA_TYPE

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A call surface (see :func:`app.client_collection_emit.client_collection_profile`)."""
        return client_collection_profile()

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Insomnia degradation rules."""
        return InsomniaFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[InsomniaEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one Insomnia v4 export.

        Args:
            api: The canonical model to export.
            opts: Per-target options (:class:`InsomniaEmitOptions`).

        Returns:
            A one-file :class:`~app.emitter.EmitResult` (``<name>.insomnia.json``).

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            EmitPreconditionError: When ``api`` has no HTTP operation.
        """
        options = _coerce_options(opts)
        plan = plan_collection(
            api,
            target_label="Insomnia",
            auth_blocks=INSOMNIA_AUTH_BLOCKS,
            folder_strategy=options.folder_strategy,
            example_depth=options.example_depth,
        )
        indent = options.indent if options.indent > 0 else None
        return EmitResult(
            files=[
                EmittedFile(
                    path=f"{output_slug(api)}.insomnia.json",
                    content=json.dumps(_export(plan), indent=indent, ensure_ascii=False) + "\n",
                    media_type=_MEDIA_TYPE,
                )
            ],
            media_type=_MEDIA_TYPE,
            provenance=plan.tracker.records(),
            losses=plan.losses.records(),
        )


def _coerce_options(opts: Optional[Union[InsomniaEmitOptions, EmitOptions]]) -> InsomniaEmitOptions:
    """Validate caller-supplied options into :class:`InsomniaEmitOptions`."""
    if isinstance(opts, InsomniaEmitOptions):
        return opts
    try:
        return InsomniaEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Insomnia emit options: {exc}") from exc


# ===========================================================================
# Rendering
# ===========================================================================


def _id(plan: CollectionPlan, prefix: str, *parts: str) -> str:
    """A stable Insomnia resource id (``req_<hex>``) for one item."""
    return f"{prefix}_{uuid.uuid5(_ID_NAMESPACE, chr(31).join((plan.title,) + parts)).hex}"


def _value(pair: ClientPair) -> str:
    """A pair's saved value: a reference for a credential, else the literal."""
    return pair.prefix + ref(pair.variable) if pair.variable else pair.value


def _entry(pair: ClientPair) -> Dict[str, Any]:
    """An Insomnia ``{name, value, disabled}`` entry (headers, parameters, form fields)."""
    return {"name": pair.name, "value": _value(pair), "disabled": not pair.enabled}


def _auth(auth: ClientAuth) -> Dict[str, Any]:
    """An Insomnia ``authentication`` block; every credential field is a variable reference."""
    if auth.scheme == "bearer":
        return {"type": "bearer", "token": ref("accessToken"), "prefix": ""}
    if auth.scheme in ("basic", "digest"):
        return {"type": auth.scheme, "username": ref("username"), "password": ref("password")}
    if auth.scheme == "apiKey":
        return {
            "type": "apikey",
            "key": auth.parameter or "X-API-Key",
            "value": ref("apiKey"),
            "addTo": "queryParams" if auth.location == "query" else "header",
        }
    block: Dict[str, Any] = {
        "type": "oauth2",
        "grantType": auth.grant_type or "client_credentials",
        "clientId": ref("clientId"),
        "clientSecret": ref("clientSecret"),
        "scope": " ".join(auth.scopes),
    }
    if auth.token_url:
        block["accessTokenUrl"] = auth.token_url
    return block


def _body(body: ClientBody) -> Dict[str, Any]:
    """An Insomnia body: JSON text, or URL-encoded / multipart ``params``."""
    if not body.is_form:
        return {"mimeType": body.content_type, "text": body.text(ref)}
    return {"mimeType": body.content_type, "params": [_entry(field) for field in body.fields]}


def _path(request: PlannedRequest) -> str:
    """The path with each whole-segment parameter as ``:name``, any other as a variable reference."""
    rendered: List[str] = []
    parts = request.path
    for index, (kind, text) in enumerate(parts):
        if kind == "literal":
            rendered.append(text)
            continue
        before = parts[index - 1][1] if index > 0 else "/"
        after = parts[index + 1][1] if index + 1 < len(parts) else ""
        whole_segment = before.endswith("/") and (not after or after.startswith("/"))
        rendered.append(":" + text if whole_segment and _COLON_NAME_RE.match(text) else ref(text))
    return "".join(rendered)


def _request(plan: CollectionPlan, request: PlannedRequest, index: int, parent: str) -> Dict[str, Any]:
    """One Insomnia ``request`` resource."""
    saved: Dict[str, Any] = {
        "_id": _id(plan, "req", str(index)),
        "_type": "request",
        "parentId": parent,
        "name": request.name,
        "description": "",
        "method": request.method,
        "url": (request.origin or ref(plan.base_variable)) + _path(request),
        "parameters": [_entry(pair) for pair in request.query],
        "pathParameters": [{"name": name, "value": value} for name, value in request.path_values],
        "headers": [_entry(pair) for pair in request.headers],
        "body": _body(request.body) if request.body is not None else {},
        "authentication": _auth(request.auth) if request.auth is not None else {},
        "metaSortKey": (index + 1) * _SORT_STEP,
        "isPrivate": False,
        "settingEncodeUrl": True,
    }
    return saved


def _export(plan: CollectionPlan) -> Dict[str, Any]:
    """The export document: workspace, folders, requests, then the base environment."""
    workspace = _id(plan, "wrk", "workspace")
    resources: List[Dict[str, Any]] = [
        {
            "_id": workspace,
            "_type": "workspace",
            "parentId": None,
            "name": plan.title,
            "description": "",
            "scope": "collection",
        }
    ]
    folder_ids: Dict[Tuple[str, ...], str] = {}
    for index, path in enumerate(plan.folders()):
        folder_ids[path] = _id(plan, "fld", *path)
        resources.append(
            {
                "_id": folder_ids[path],
                "_type": "request_group",
                "parentId": folder_ids.get(path[:-1], workspace),
                "name": path[-1],
                "description": "",
                "environment": {},
                "metaSortKey": (index + 1) * _SORT_STEP,
            }
        )
    for index, request in enumerate(plan.requests):
        resources.append(_request(plan, request, index, folder_ids.get(request.folder, workspace)))
    data = {variable.name: variable.value for variable in plan.variables}
    resources.append(
        {
            "_id": _id(plan, "env", "base"),
            "_type": "environment",
            "parentId": workspace,
            "name": "Base Environment",
            "data": data,
            "dataPropertyOrder": {"&": list(data)},
            "isPrivate": False,
            "metaSortKey": _SORT_STEP,
        }
    )
    return {
        "_type": "export",
        "__export_format": 4,
        "__export_source": EXPORT_SOURCE,
        "resources": resources,
    }
