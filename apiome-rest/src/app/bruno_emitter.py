"""Bruno emitter: canonical model → Bruno collection folder — MFX-31.3 (#4291).

The inverse of :mod:`app.bruno_parser`. A Bruno collection is a **folder**, so the export is a set
of files the export job delivers as one zip (MFX-4.2):

* ``bruno.json`` — the collection manifest (``version``, ``name``, ``type: collection``);
* one ``.bru`` file per HTTP operation (and per body media type), in a folder per folder level, each
  folder with a ``folder.bru`` holding its display name and order;
* ``collection.bru`` — the auth every request shares, when they all share one (requests then
  ``inherit`` it);
* ``environments/Default.bru`` — the ``baseUrl`` the requests are written against, and every
  credential variable they reference listed under ``vars:secret`` (Bruno keeps secret values on the
  user's machine, never in the collection).

Requests, values, auth and losses are planned by :mod:`app.client_collection_emit` — the request tree
the Postman collection (MFX-31.1), Insomnia, Hoppscotch and Thunder Client are written from — and
this module only writes the ``.bru`` language (``{{variable}}`` references).

**Auth.** ``bearer``, ``basic``, ``digest``, ``apiKey`` and ``oauth2`` become ``auth:<mode>`` blocks
whose credential fields are variable references; an ``authorization`` or ``cookie`` requirement
travels as a header holding a reference.

**Not carried** (reported by :class:`BrunoFidelityRulePack` and the plan's losses): declared
responses, the API description, servers beyond the first, the schemas behind the example bodies,
and an operation on a method Bruno has no block for.

**Determinism.** File names come from the folder and request names, and nothing time-dependent is
written, so two exports of the same model are byte-identical.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from pydantic import Field

from .bruno_parser import FORMAT_KEY, METHODS
from .canonical_model import ApiParadigm, CanonicalApi
from .client_collection_emit import (
    ClientAuth,
    ClientBody,
    ClientPair,
    CollectionPlan,
    PlannedRequest,
    client_collection_profile,
    plan_collection,
)
from .client_collection_fidelity import ExampleCollectionFidelityRulePack
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
)
from .fidelity_rulepack import CapabilityRulePack

__all__ = [
    "BRUNO_AUTH_BLOCKS",
    "BrunoEmitOptions",
    "BrunoEmitter",
    "BrunoFidelityRulePack",
    "bru_dictionary",
    "validate_bruno_export",
]

#: Canonical schemes Bruno writes as an ``auth:<mode>`` block, and the mode each is written as.
_AUTH_MODES: Dict[str, str] = {
    "bearer": "bearer",
    "basic": "basic",
    "digest": "digest",
    "apiKey": "apikey",
    "oauth2": "oauth2",
}
BRUNO_AUTH_BLOCKS = frozenset(_AUTH_MODES)

#: The environment file every export writes.
ENVIRONMENT_NAME = "Default"

_MEDIA_TYPE = "text/plain"
_JSON_MEDIA_TYPE = "application/json"
_INDENT = "  "
_MULTILINE_MARK = "'''"
#: Names the reader gives a meaning of their own, so a folder or request may not take them.
_RESERVED_FILES = frozenset({"collection", "folder"})
_RESERVED_ROOT_FOLDER = "environments"
#: A path parameter Bruno can spell ``:name`` — a whole segment with a plain name.
_COLON_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
#: Characters kept in a folder or file name; anything else becomes ``-``.
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 ._\-]+")
#: A dictionary key that has to be written quoted (``"quoted key": value``).
_QUOTED_KEY_RE = re.compile(r"[:\"{}\[\]]|^[~\s]|\s$")


def ref(variable: str) -> str:
    """A Bruno variable reference: ``{{name}}``."""
    return "{{" + variable + "}}"


def validate_bruno_export(members: Dict[str, str]) -> None:
    """Validate an emitted collection by re-parsing its files as one upload through the Bruno reader.

    Args:
        members: The emitted files' text keyed by path (``bruno.json`` among them).

    Raises:
        ValueError: When the files do not re-parse as a Bruno collection.
    """
    from .bruno_parser import BrunoParseError, parse_bruno_fileset

    try:
        parse_bruno_fileset(members, root="bruno.json")
    except BrunoParseError as exc:
        raise ValueError(f"Invalid Bruno export: {exc}") from exc


class BrunoFidelityRulePack(ExampleCollectionFidelityRulePack):
    """Fidelity rules for Bruno export.

    The example-collection rules (MFX-31.2, :mod:`app.client_collection_fidelity`): schemas become
    example bodies, unions one representative example, generated values are synthesized, streaming
    and auth Bruno has no mode for are named. A Bruno collection saves no responses, so declared
    responses are dropped.
    """

    target_label = "Bruno collection"
    format_key = FORMAT_KEY
    auth_blocks = BRUNO_AUTH_BLOCKS
    carries_responses = False
    native_is_lossless = False


class BrunoEmitOptions(EmitOptions):
    """Per-target options for :class:`BrunoEmitter`."""

    folder_strategy: Literal["tag", "auto", "service", "flat"] = Field(
        default="tag",
        description="How requests are filed into folders: `tag` (first tag), `auto` (first tag, else service "
        "when the API has more than one), `service` or `flat`. An item imported from Bruno keeps its own "
        "folders under `tag`.",
    )
    example_depth: Literal["minimal", "full"] = Field(
        default="minimal",
        description="Synthesized example bodies fill required properties only (`minimal`) or every "
        "declared property (`full`).",
    )


class BrunoEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Bruno collection (``bruno.json`` + ``.bru`` files)."""

    key = FORMAT_KEY
    format = FORMAT_KEY
    label = "Bruno"
    description = (
        "Export as a Bruno collection, delivered as a zip: bruno.json and one .bru file per operation, "
        "foldered by tag, against a {{baseUrl}} environment variable, with credentials as secret variables."
    )
    icon = "send"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = BrunoEmitOptions
    #: X1 (#6222): refused with a reason, never crashed, when the source lacks this.
    requires_source = ("http-operation",)

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A call surface (see :func:`app.client_collection_emit.client_collection_profile`)."""
        return client_collection_profile()

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Bruno degradation rules."""
        return BrunoFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[BrunoEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as a Bruno collection.

        Args:
            api: The canonical model to export.
            opts: Per-target options (:class:`BrunoEmitOptions`).

        Returns:
            A multi-file :class:`~app.emitter.EmitResult`: ``bruno.json`` first, then
            ``collection.bru`` (when the requests share auth), the requests, and the environment.

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            EmitPreconditionError: When ``api`` has no HTTP operation Bruno can save.
        """
        options = _coerce_options(opts)
        plan = plan_collection(
            api,
            target_label="Bruno",
            auth_blocks=BRUNO_AUTH_BLOCKS,
            folder_strategy=options.folder_strategy,
            example_depth=options.example_depth,
        )
        files = _Writer(plan).files()
        return EmitResult(
            files=[
                EmittedFile(
                    path=path,
                    content=content,
                    media_type=_JSON_MEDIA_TYPE if path.endswith(".json") else _MEDIA_TYPE,
                )
                for path, content in files
            ],
            media_type=_MEDIA_TYPE,
            provenance=plan.tracker.records(),
            losses=plan.losses.records(),
        )


def _coerce_options(opts: Optional[Union[BrunoEmitOptions, EmitOptions]]) -> BrunoEmitOptions:
    """Validate caller-supplied options into :class:`BrunoEmitOptions`."""
    if isinstance(opts, BrunoEmitOptions):
        return opts
    try:
        return BrunoEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Bruno emit options: {exc}") from exc


# ===========================================================================
# The .bru language
# ===========================================================================


def _key(name: str) -> str:
    """A dictionary key, quoted when it holds a character the grammar gives a meaning to."""
    if _QUOTED_KEY_RE.search(name):
        return '"' + name.replace('"', '\\"') + '"'
    return name


def bru_dictionary(name: str, entries: Sequence[Tuple[str, str, bool]]) -> str:
    """Write one dictionary block (``headers { … }``).

    Args:
        name: The block name (``headers``, ``params:query``, ``auth:bearer`` …).
        entries: ``(key, value, enabled)``; a disabled entry is written ``~key: value``, a value
            spanning lines as a ``'''`` block.

    Returns:
        The block text, ending with a newline.
    """
    lines = [f"{name} {{"]
    for key, value, enabled in entries:
        prefix = _INDENT + ("" if enabled else "~") + _key(key) + ":"
        if "\n" in value:
            lines.append(f"{prefix} {_MULTILINE_MARK}")
            lines.extend(_INDENT * 2 + line for line in value.split("\n"))
            lines.append(_INDENT + _MULTILINE_MARK)
        else:
            lines.append(f"{prefix} {value}" if value else prefix)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _text_block(name: str, text: str) -> str:
    """Write one text block (``body:json { … }``); every line is indented, so none closes it early."""
    body = "\n".join(_INDENT + line if line else line for line in text.split("\n"))
    return f"{name} {{\n{body}\n}}\n"


def _list_block(name: str, items: Sequence[str]) -> str:
    """Write one list block (``vars:secret [ … ]``)."""
    return f"{name} [\n" + ",\n".join(_INDENT + item for item in items) + "\n]\n"


def _safe_name(name: str, fallback: str) -> str:
    """A file or folder name from a display name (letters, digits, spaces, ``.``, ``_`` and ``-``)."""
    safe = _UNSAFE_NAME_RE.sub("-", name).strip(" .-")
    return safe or fallback


# ===========================================================================
# Rendering
# ===========================================================================


def _value(pair: ClientPair) -> str:
    """A pair's saved value: a reference for a credential, else the literal."""
    return pair.prefix + ref(pair.variable) if pair.variable else pair.value


def _entries(pairs: Sequence[ClientPair]) -> List[Tuple[str, str, bool]]:
    return [(pair.name, _value(pair), pair.enabled) for pair in pairs]


def _auth_block(auth: ClientAuth) -> str:
    """The ``auth:<mode>`` block; every credential field is a variable reference."""
    mode = _AUTH_MODES[auth.scheme]
    if auth.scheme == "bearer":
        entries = [("token", ref("accessToken"), True)]
    elif auth.scheme in ("basic", "digest"):
        entries = [("username", ref("username"), True), ("password", ref("password"), True)]
    elif auth.scheme == "apiKey":
        entries = [
            ("key", auth.parameter or "X-API-Key", True),
            ("value", ref("apiKey"), True),
            ("placement", "queryparams" if auth.location == "query" else "header", True),
        ]
    else:
        entries = [
            ("grant_type", auth.grant_type or "client_credentials", True),
            ("access_token_url", auth.token_url or "", True),
            ("client_id", ref("clientId"), True),
            ("client_secret", ref("clientSecret"), True),
            ("scope", " ".join(auth.scopes), True),
        ]
    return bru_dictionary(f"auth:{mode}", entries)


def _body_mode(body: Optional[ClientBody]) -> str:
    """The method block's ``body`` mode."""
    if body is None:
        return "none"
    if not body.is_form:
        return "json"
    return "multipartForm" if "multipart" in body.content_type else "formUrlEncoded"


def _body_block(body: ClientBody) -> str:
    """The ``body:<mode>`` block."""
    if not body.is_form:
        return _text_block("body:json", body.text(ref))
    name = "body:multipart-form" if "multipart" in body.content_type else "body:form-urlencoded"
    return bru_dictionary(name, _entries(body.fields))


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
    """``{{baseUrl}}`` (or the request's own origin) + the path + the enabled query, as Bruno keeps it."""
    query = "&".join(
        f"{quote(pair.name, safe='')}={quote(_value(pair), safe='{}')}" for pair in request.query if pair.enabled
    )
    return (request.origin or ref(plan.base_variable)) + _path(request) + (f"?{query}" if query else "")


class _Writer:
    """Lays one :class:`CollectionPlan` out as Bruno's files."""

    def __init__(self, plan: CollectionPlan) -> None:
        self.plan = plan
        #: Folder path → its directory in the collection.
        self._directories: Dict[Tuple[str, ...], str] = {(): ""}
        #: Directory → the file and folder names already taken in it.
        self._taken: Dict[str, set] = {}

    def files(self) -> List[Tuple[str, str]]:
        """Every file of the collection as ``(path, text)``: ``bruno.json`` first."""
        plan = self.plan
        requests = [request for request in plan.requests if request.method.lower() in METHODS]
        for request in plan.requests:
            if request.method.lower() not in METHODS:
                plan.losses.record(
                    LossKind.NA,
                    "method-not-supported",
                    f"Bruno has no {request.method} request; {request.operation_key!r} is not saved.",
                    pointer=request.operation_key,
                )
        if not requests:
            raise EmitPreconditionError(
                "Bruno export requires at least one HTTP operation on a method Bruno saves "
                f"({', '.join(m.upper() for m in METHODS)})."
            )
        manifest = {"version": "1", "name": plan.title, "type": "collection", "ignore": ["node_modules", ".git"]}
        out: List[Tuple[str, str]] = [("bruno.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")]
        if plan.shared_auth is not None:
            out.append(("collection.bru", self._collection_file(plan.shared_auth)))
        for index, path in enumerate(plan.folders()):
            if not any(request.folder[: len(path)] == path for request in requests):
                continue
            directory = self._directory(path)
            meta = bru_dictionary("meta", [("name", path[-1], True), ("seq", str(index + 1), True)])
            out.append((f"{directory}/folder.bru", meta))
        for index, request in enumerate(requests):
            directory = self._directory(request.folder)
            stem = self._unique(directory, _safe_name(request.name, "request"))
            path = f"{directory}/{stem}.bru" if directory else f"{stem}.bru"
            out.append((path, self._request_file(request, index)))
        out.append((f"environments/{ENVIRONMENT_NAME}.bru", self._environment_file()))
        return out

    def _unique(self, directory: str, name: str) -> str:
        """``name``, or ``name-2`` … when the directory already holds it (or it is reserved)."""
        taken = self._taken.setdefault(directory, set())
        candidate, suffix = name, 2
        while candidate.lower() in taken or candidate.lower() in _RESERVED_FILES or (
            not directory and candidate.lower() == _RESERVED_ROOT_FOLDER
        ):
            candidate, suffix = f"{name}-{suffix}", suffix + 1
        taken.add(candidate.lower())
        return candidate

    def _directory(self, path: Tuple[str, ...]) -> str:
        """The directory a folder path is written to, creating parent directories first."""
        if path in self._directories:
            return self._directories[path]
        parent = self._directory(path[:-1])
        name = self._unique(parent, _safe_name(path[-1], "folder"))
        directory = f"{parent}/{name}" if parent else name
        self._directories[path] = directory
        return directory

    def _collection_file(self, auth: ClientAuth) -> str:
        """``collection.bru``: the auth every request inherits."""
        return bru_dictionary("auth", [("mode", _AUTH_MODES[auth.scheme], True)]) + "\n" + _auth_block(auth)

    def _request_file(self, request: PlannedRequest, index: int) -> str:
        """One request ``.bru`` file."""
        plan = self.plan
        if plan.shared_auth is not None:
            auth_mode = "inherit"
        elif request.auth is not None:
            auth_mode = _AUTH_MODES[request.auth.scheme]
        else:
            auth_mode = "none"
        meta = [("name", request.name, True), ("type", "http", True), ("seq", str(index + 1), True)]
        method = [
            ("url", _url(plan, request), True),
            ("body", _body_mode(request.body), True),
            ("auth", auth_mode, True),
        ]
        blocks = [bru_dictionary("meta", meta), bru_dictionary(request.method.lower(), method)]
        if request.query:
            blocks.append(bru_dictionary("params:query", _entries(request.query)))
        if request.path_values:
            blocks.append(bru_dictionary("params:path", [(name, value, True) for name, value in request.path_values]))
        if request.headers:
            blocks.append(bru_dictionary("headers", _entries(request.headers)))
        if plan.shared_auth is None and request.auth is not None:
            blocks.append(_auth_block(request.auth))
        if request.body is not None:
            blocks.append(_body_block(request.body))
        return "\n".join(blocks)

    def _environment_file(self) -> str:
        """``environments/Default.bru``: the base URL, and every credential listed as secret."""
        plain = [(variable.name, variable.value, True) for variable in self.plan.variables if not variable.secret]
        secret = [variable.name for variable in self.plan.variables if variable.secret]
        blocks = [bru_dictionary("vars", plain)]
        if secret:
            blocks.append(_list_block("vars:secret", secret))
        return "\n".join(blocks)
