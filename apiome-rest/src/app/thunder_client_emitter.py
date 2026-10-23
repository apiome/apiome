"""Thunder Client emitter: canonical model → Thunder Client collection + environment — FMT-10.4 (#5479).

The inverse of :mod:`app.thunder_client_parser`. The export is the pair Thunder Client itself writes
and imports: ``thunder-collection_<name>.json`` — a flat ``folders[]`` / ``requests[]`` list linked by
``containerId``, one saved request per HTTP operation — and ``thunder-environment_<name>.json``, whose
``data[]`` declares the ``{{baseUrl}}`` the requests are written against and every credential variable
they reference, each of those with an empty value. Requests, values, auth and losses are planned by
:mod:`app.client_collection_emit`; this module only writes Thunder Client's JSON.

**Auth.** ``bearer``, ``basic``, ``digest`` and ``oauth2`` become Thunder Client auth blocks whose
credential fields are ``{{variable}}`` references. Thunder Client has no API-key auth type, so an
``apiKey`` scheme is written the way a Thunder Client user writes one — a header (or query
parameter) holding ``{{apiKey}}`` — as are a generic ``authorization`` or ``cookie`` requirement.
When every request uses the same auth it is set once in the collection ``settings`` and inherited.

**Determinism.** Thunder Client identifies collections, folders and requests by id. The ids written
here are UUIDv5 values derived from the collection name and the item's position, and no timestamps
are written, so two exports of the same model are byte-identical.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

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
from .thunder_client_parser import CLIENT_NAME, FORMAT_KEY

__all__ = [
    "THUNDER_AUTH_BLOCKS",
    "ThunderClientEmitOptions",
    "ThunderClientEmitter",
    "ThunderClientFidelityRulePack",
    "validate_thunder_client_export",
]

#: The collection export ``version`` written.
COLLECTION_VERSION = "1.2"

#: Canonical schemes Thunder Client writes as an auth block (it has no API-key type).
THUNDER_AUTH_BLOCKS = frozenset({"bearer", "basic", "digest", "oauth2"})

_MEDIA_TYPE = "application/json"
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://apiome.dev/export/thunder-client")
#: A path parameter Thunder Client can spell ``:name`` — a whole segment with a plain name.
_COLON_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
_SORT_STEP = 10000


def ref(variable: str) -> str:
    """A Thunder Client variable reference."""
    return "{{" + variable + "}}"


def validate_thunder_client_export(members: Dict[str, str]) -> None:
    """Validate an emitted collection + environment by re-parsing them as an upload.

    The post-emit gate: the files go back through the ``thunder-client`` import adapter — the same
    reader an intake uses — so an export is held to everything an import would reject.

    Args:
        members: The emitted files' text keyed by path.

    Raises:
        ValueError: When the files do not re-parse as a Thunder Client upload.
    """
    from .fileset import IntakeFileset
    from .import_source import ImportSourceError
    from .thunder_client_import_source import ThunderClientImportSource

    root = next((path for path in sorted(members) if "collection" in path), sorted(members)[0])
    try:
        ThunderClientImportSource().parse_fileset(IntakeFileset.from_members(members, root=root))
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Thunder Client export: {exc}") from exc


class ThunderClientFidelityRulePack(ClientCollectionFidelityRulePack):
    """Fidelity rules for Thunder Client export (shared with Hoppscotch; see the base class)."""

    target_label = "Thunder Client collection"
    format_key = FORMAT_KEY


class ThunderClientEmitOptions(EmitOptions):
    """Per-target options for :class:`ThunderClientEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")


class ThunderClientEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Thunder Client collection and its environment."""

    key = FORMAT_KEY
    format = FORMAT_KEY
    label = "Thunder Client"
    description = (
        "Export as a Thunder Client collection and environment: one saved request per operation, "
        "foldered by tag, against a {{baseUrl}} variable, with auth as empty placeholder variables."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = ThunderClientEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A call surface: operations only (see :func:`app.client_collection_emit.client_collection_profile`)."""
        return client_collection_profile()

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Thunder Client degradation rules."""
        return ThunderClientFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ThunderClientEmitOptions, EmitOptions]] = None,
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
        plan = plan_collection(api, target_label="Thunder Client", auth_blocks=THUNDER_AUTH_BLOCKS)
        indent = options.indent if options.indent > 0 else None
        slug = output_slug(api)
        documents = [
            (f"thunder-collection_{slug}.json", _collection(plan)),
            (f"thunder-environment_{slug}.json", _environment(plan)),
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


def _coerce_options(opts: Optional[Union[ThunderClientEmitOptions, EmitOptions]]) -> ThunderClientEmitOptions:
    """Validate caller-supplied options into :class:`ThunderClientEmitOptions`."""
    if isinstance(opts, ThunderClientEmitOptions):
        return opts
    try:
        return ThunderClientEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Thunder Client emit options: {exc}") from exc


# ===========================================================================
# Rendering
# ===========================================================================


def _id(plan: CollectionPlan, *parts: str) -> str:
    """A stable id for one collection item."""
    return str(uuid.uuid5(_ID_NAMESPACE, "\x1f".join((plan.title,) + parts)))


def _value(pair: ClientPair) -> str:
    """A pair's saved value: a reference for a credential, else the literal."""
    return pair.prefix + ref(pair.variable) if pair.variable else pair.value


def _entry(pair: ClientPair, **extra: Any) -> Dict[str, Any]:
    """A Thunder Client ``{name, value}`` entry; a disabled one carries ``isDisabled``."""
    entry: Dict[str, Any] = {"name": pair.name, "value": _value(pair), **extra}
    if not pair.enabled:
        entry["isDisabled"] = True
    return entry


def _auth(auth: ClientAuth) -> Dict[str, Any]:
    """A Thunder Client auth block; every credential field is a variable reference."""
    if auth.scheme == "bearer":
        return {"type": "bearer", "bearer": ref("accessToken")}
    if auth.scheme in ("basic", "digest"):
        return {"type": auth.scheme, auth.scheme: {"username": ref("username"), "password": ref("password")}}
    return {
        "type": "oauth2",
        "oauth2": {
            "grantType": auth.grant_type or "client_credentials",
            "accessTokenUrl": auth.token_url or "",
            "clientId": ref("clientId"),
            "clientSecret": ref("clientSecret"),
            "scope": " ".join(auth.scopes),
        },
    }


def _body(body: ClientBody) -> Dict[str, Any]:
    """A Thunder Client body: JSON text, or URL-encoded / multipart fields."""
    if not body.is_form:
        return {"type": "json", "raw": body.text(ref), "form": []}
    form = [_entry(field) for field in body.fields]
    if "multipart" in body.content_type:
        return {"type": "formdata", "raw": "", "form": form, "files": []}
    return {"type": "formencoded", "raw": "", "form": form}


def _path(request: PlannedRequest) -> str:
    """The path with each whole-segment parameter as ``:name``, any other as ``{{name}}``."""
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


def _url(plan: CollectionPlan, request: PlannedRequest) -> str:
    """``{{baseUrl}}`` (or the request's own origin) + the path + the enabled query, as Thunder keeps it."""
    query = "&".join(
        f"{quote(pair.name, safe='')}={quote(_value(pair), safe='{}')}" for pair in request.query if pair.enabled
    )
    return (request.origin or ref(plan.base_variable)) + _path(request) + (f"?{query}" if query else "")


def _request(
    plan: CollectionPlan, request: PlannedRequest, index: int, folders: Dict[Tuple[str, ...], str]
) -> Dict[str, Any]:
    """One saved Thunder Client request."""
    params = [_entry(pair, isPath=False) for pair in request.query]
    params.extend({"name": name, "value": value, "isPath": True} for name, value in request.path_values)
    saved: Dict[str, Any] = {
        "_id": _id(plan, "request", str(index)),
        "colId": _id(plan, "collection"),
        "containerId": folders.get(request.folder, ""),
        "name": request.name,
        "url": _url(plan, request),
        "method": request.method,
        "sortNum": (index + 1) * _SORT_STEP,
        "headers": [_entry(pair) for pair in request.headers],
        "params": params,
        "tests": [],
    }
    if request.body is not None:
        saved["body"] = _body(request.body)
    if plan.shared_auth is None and request.auth is not None:
        saved["auth"] = _auth(request.auth)
    return saved


def _collection(plan: CollectionPlan) -> Dict[str, Any]:
    """The collection export: a flat folder list linked by ``containerId``, then the requests."""
    folder_ids: Dict[Tuple[str, ...], str] = {}
    folders: List[Dict[str, Any]] = []
    for index, path in enumerate(plan.folders()):
        folder_ids[path] = _id(plan, "folder", *path)
        folders.append(
            {
                "_id": folder_ids[path],
                "name": path[-1],
                "containerId": folder_ids.get(path[:-1], ""),
                "sortNum": (index + 1) * _SORT_STEP,
            }
        )
    settings: Dict[str, Any] = {}
    if plan.shared_auth is not None:
        settings["auth"] = _auth(plan.shared_auth)
    collection: Dict[str, Any] = {
        "clientName": CLIENT_NAME,
        "collectionName": plan.title,
        "collectionId": _id(plan, "collection"),
        "version": COLLECTION_VERSION,
        "folders": folders,
        "requests": [_request(plan, request, index, folder_ids) for index, request in enumerate(plan.requests)],
    }
    if settings:
        collection["settings"] = settings
    return collection


def _environment(plan: CollectionPlan) -> Dict[str, Any]:
    """The environment export: the base URL and every credential, the credentials empty."""
    return {
        "clientName": CLIENT_NAME,
        "name": plan.title,
        "default": False,
        "data": [{"name": variable.name, "value": variable.value} for variable in plan.variables],
    }
