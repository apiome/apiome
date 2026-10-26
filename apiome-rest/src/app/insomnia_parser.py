"""Reader for Insomnia exports (v4 JSON and v5 YAML) — MFI-32.3 (#4405).

Insomnia is a desktop API client. Two export shapes are current:

* **v4** (``Export → Insomnia v4``, JSON): ``{"_type": "export", "__export_format": 4,
  "resources": [...]}`` — a *flat* list of resources (``workspace``, ``request_group`` folders,
  ``request``, ``environment``, ``cookie_jar``, ``grpc_request`` …) linked by ``parentId``, so the
  folder tree is rebuilt from those links;
* **v5** (Insomnia 10 and later, YAML): ``type: collection.insomnia.rest/5.0`` with a *nested*
  ``collection:`` list (a folder is an item with ``children``), an ``environments:`` block with
  ``subEnvironments``, and a ``cookieJar``. A design document (``spec.insomnia.rest/5.0``) carries a
  collection beside its API spec, and a global environment exports as ``environment.insomnia.rest/5.0``.

Both are turned into the same tree and read once into an :class:`InsomniaDocument`: one concrete
:class:`~app.inferred_spec.HttpObservation` per saved HTTP request for the shared inferred-spec
engine (single-sample operations; bodies as declared), plus what the engine has no slot for — the
folder each request sits in, the auth it resolves to, its body's media type, the server variables
its URLs are written against, and parameter defaults taken from the environments.

Variables are Nunjucks: ``{{ _.baseUrl }}`` (or ``{{ baseUrl }}``, ``{{ _.api.host }}`` into a
nested value). A URL starting with a variable becomes a ``{variable}`` server whose default comes
from the environments; a variable inside the path becomes a path parameter, as does ``:name``.
Template tags (``{% response … %}``, ``{% uuid %}``) are run by Insomnia and never evaluated here.

**Credentials never leave this module.** Auth blocks are read as *scheme and public facts only* —
token, password, client-secret and API-key value fields are never read. Every other value is
passed through the shared secret-scrub gate, a header or parameter whose name says it holds a
secret is redacted outright, and a variable that is secret (by its name, or Insomnia's ``secret``
type) never becomes a server-variable or parameter default. Cookie jars are never read.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark.
* ``INPUT_TRUNCATED`` — the JSON or YAML ends while a value is still open.
* ``INPUT_MALFORMED`` — any other syntax error, or resources / items whose structure is wrong.
* ``FORMAT_MISMATCH`` — valid JSON or YAML that is not an Insomnia export.
* ``FORMAT_VERSION_UNSUPPORTED`` — an Insomnia export in a format other than v4 or v5.
* ``INPUT_SEMANTIC_INVALID`` — no HTTP request to import, a resource whose ``parentId`` names
  nothing (or a folder cycle), a request with no URL (or one written only as an undefined
  variable), or an environment / design document with no requests uploaded on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit

from .client_collection import (
    SECRET_NAME_RE,
    load_client_json,
    load_client_yaml,
    scrub_named,
    scrub_value,
)
from .inferred_spec import HttpObservation

__all__ = [
    "AUTH_SCHEMES",
    "FORMAT_KEY",
    "InsomniaAuth",
    "InsomniaDocument",
    "InsomniaParseError",
    "InsomniaRequest",
    "InsomniaVariable",
    "MEMBER_SUFFIXES",
    "detect_insomnia",
    "parse_insomnia_fileset",
    "parse_insomnia_text",
]

#: The registry key of the format.
FORMAT_KEY = "insomnia"

#: Fileset members read as exports; any other member (a README) is ignored.
MEMBER_SUFFIXES = (".json", ".yaml", ".yml")

#: Insomnia auth ``type`` → the canonical scheme :mod:`app.canonical_security` reads. Types that
#: sign the request (OAuth 1, AWS IAM, NTLM, Hawk, ASAP, netrc) have no canonical scheme of their
#: own and are recorded as a generic ``authorization`` requirement.
AUTH_SCHEMES: Mapping[str, str] = {
    "basic": "basic",
    "digest": "digest",
    "bearer": "bearer",
    "oauth2": "oauth2",
    "apikey": "apiKey",
    "oauth1": "authorization",
    "iam": "authorization",
    "ntlm": "authorization",
    "hawk": "authorization",
    "asap": "authorization",
    "netrc": "authorization",
}

#: The OAuth 2 fields that are public endpoints, never credentials. Only these (and the grant type
#: and scope) are read from an ``oauth2`` block.
_OAUTH_URL_FIELDS = ("accessTokenUrl", "authorizationUrl")

#: Body media types that are sent as form fields (read from ``params``).
_FORM_TYPES = frozenset({"application/x-www-form-urlencoded", "multipart/form-data"})

#: The v5 document ``type`` marker: ``collection.insomnia.rest/5.0``.
_V5_TYPE_RE = re.compile(r"^(collection|spec|environment|mock)\.insomnia\.rest/(\d+)(?:\.\d+)*$")
_V5_TYPE_LINE_RE = re.compile(
    r"^type:\s*[\"']?((?:collection|spec|environment|mock)\.insomnia\.rest/\d+(?:\.\d+)*)[\"']?\s*$", re.MULTILINE
)

#: ``{{ _.name }}`` / ``{{ name }}`` / ``{{ _.api.host }}``, optionally with a Nunjucks filter.
_NAME = r"[A-Za-z_$][A-Za-z0-9_$\-]*(?:\.[A-Za-z0-9_$\-]+)*"
_VARIABLE_RE = re.compile(r"\{\{\s*(?:_\.)?(" + _NAME + r")\s*(?:\|[^}]*)?\}\}")
_LEADING_VARIABLE_RE = re.compile(r"^\s*\{\{\s*(?:_\.)?(" + _NAME + r")\s*(?:\|[^}]*)?\}\}")
_WHOLE_VARIABLE_RE = re.compile(r"^\s*\{\{\s*(?:_\.)?(" + _NAME + r")\s*(?:\|[^}]*)?\}\}\s*$")
#: A ``{{ variable }}`` written as a bare JSON value (``"qty": {{ _.qty }}``).
_BARE_JSON_VARIABLE_RE = re.compile(r'(?<!")(\{\{\s*(?:_\.)?' + _NAME + r'\s*(?:\|[^}]*)?\}\})(?!")')
#: A template tag Insomnia runs at send time (``{% response … %}``, ``{% uuid %}``).
_TEMPLATE_TAG_RE = re.compile(r"\{%.*?%\}", re.DOTALL)
#: A ``:name`` path segment.
_PATH_PARAM_RE = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_\-]*)(?=/|$)")

_MAX_VARIABLE_DEPTH = 5


class InsomniaParseError(ValueError):
    """Raised when an Insomnia upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InsomniaAuth:
    """A resolved auth declaration — scheme and public facts only, never a credential.

    Attributes:
        type: The Insomnia auth ``type`` (``bearer``, ``basic``, ``oauth2``, ``apikey`` …).
        scheme: The canonical scheme identifier (see :data:`AUTH_SCHEMES`).
        declared_at: The folder path the auth was inherited from, or ``request``.
        grant_type: An OAuth 2 grant type, when stated.
        token_url: An OAuth 2 token / authorization URL, when stated (scrubbed).
        scopes: OAuth 2 scopes, when stated.
        key_name: An API key's header / query parameter name (the name, never the key).
        key_location: Where an API key is sent (``header``, ``queryParams``, ``cookie``).
    """

    type: str
    scheme: str
    declared_at: str
    grant_type: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Tuple[str, ...] = ()
    key_name: Optional[str] = None
    key_location: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag, leaving unset facts out."""
        record: Dict[str, Any] = {"type": self.type, "scheme": self.scheme, "declared_at": self.declared_at}
        for key, value in (
            ("grant_type", self.grant_type),
            ("token_url", self.token_url),
            ("key_name", self.key_name),
            ("key_location", self.key_location),
        ):
            if value:
                record[key] = value
        if self.scopes:
            record["scopes"] = list(self.scopes)
        return record


@dataclass(frozen=True)
class InsomniaRequest:
    """The facts about one saved request that the inferred-spec engine has no slot for.

    Attributes:
        name: The request's name.
        method: The upper-cased HTTP method.
        url: The URL handed to the engine.
        folder: The folder path from the collection root (empty at the root).
        auth: The auth the request resolves to after inheritance, or ``None``.
        content_type: The body's media type, when the request has a body.
        has_script: Whether a pre-request or after-response script applies (its own or a folder's).
        has_template_tag: Whether a ``{% … %}`` template tag appears in the request.
        defaults: ``(location, name, value)`` for each query / header parameter written as a whole
            variable whose (non-secret) value the environments define; header names lower-cased.
    """

    name: str
    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[InsomniaAuth]
    content_type: Optional[str]
    has_script: bool = False
    has_template_tag: bool = False
    defaults: Tuple[Tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class InsomniaVariable:
    """A variable an environment defines — its *name* and where, never its value.

    Attributes:
        name: The variable name (dotted for a nested value: ``api.host``).
        source: ``environment:<name>`` or ``folder:<path>``.
        secret: Whether the value is a credential (by name, or Insomnia's ``secret`` type).
    """

    name: str
    source: str
    secret: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        return {"name": self.name, "source": self.source, "secret": self.secret}


@dataclass
class InsomniaDocument:
    """A parsed Insomnia upload, ready for the inferred-spec engine.

    Attributes:
        title: The workspace / collection name (several joined with ``·``).
        export_formats: The export format of each export read (``v4``, ``v5``).
        observations: One concrete request sample per saved HTTP request.
        requests: Per-request facts, aligned with ``observations``.
        server_variables: Server URL variable → its default (``None`` when undefined or secret).
        variables: Every variable the environments and folders define, by name.
        environments: The names of the environments read, base first.
        skipped: Construct id → the names of what was left out (gRPC and WebSocket requests, unit
            tests, an API spec, mock routes, cookie jars).
        source_label: The filename or paste label.
    """

    title: str
    export_formats: List[str] = field(default_factory=list)
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[InsomniaRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[InsomniaVariable] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    skipped: Dict[str, List[str]] = field(default_factory=dict)
    source_label: Optional[str] = None


# ---------------------------------------------------------------------------
# The shared tree both export formats are read into
# ---------------------------------------------------------------------------


@dataclass
class _Folder:
    """A folder (or the collection root): its own settings and its children in order."""

    name: str
    auth: Any = None
    headers: Any = None
    environment: Mapping[str, Any] = field(default_factory=dict)
    has_script: bool = False
    children: List[Tuple[str, Any, str]] = field(default_factory=list)  # (kind, node, pointer)


@dataclass
class _Environment:
    """One environment's variables: ``data`` (possibly nested) plus Insomnia's key-value pairs."""

    name: str
    data: Mapping[str, Any]
    secret_names: frozenset = frozenset()


@dataclass
class _Export:
    """One export read into the shared shape."""

    format: str
    title: str
    roots: List[_Folder] = field(default_factory=list)
    environments: List[_Environment] = field(default_factory=list)
    skipped: Dict[str, List[str]] = field(default_factory=dict)


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def _error(message: str, code: str) -> InsomniaParseError:
    return InsomniaParseError(message, code=code)


def _skip(skipped: Dict[str, List[str]], construct: str, name: Any) -> None:
    skipped.setdefault(construct, []).append(str(name or construct))


def _is_script(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _environment(name: str, data: Any, kv_pairs: Any) -> _Environment:
    """Read an environment's ``data`` mapping and ``kvPairData`` list (Insomnia's key-value editor)."""
    values: Dict[str, Any] = dict(data) if isinstance(data, Mapping) else {}
    secret: set = set()
    for pair in kv_pairs if isinstance(kv_pairs, list) else []:
        if not isinstance(pair, Mapping) or not isinstance(pair.get("name"), str) or pair.get("enabled") is False:
            continue
        key = pair["name"].strip()
        if not key:
            continue
        if str(pair.get("type") or "").lower() == "secret":
            secret.add(key)
            values.setdefault(key, None)  # a secret's value is never read
        else:
            values.setdefault(key, pair.get("value"))
    return _Environment(name=name, data=values, secret_names=frozenset(secret))


# --- v4 ------------------------------------------------------------------


def _v4_scripts(resource: Mapping[str, Any]) -> bool:
    return _is_script(resource.get("preRequestScript")) or _is_script(resource.get("afterResponseScript"))


def _read_v4(document: Mapping[str, Any], label: Optional[str]) -> _Export:
    """Rebuild a v4 export's folder tree from its ``parentId`` links."""
    export_format = document.get("__export_format")
    if export_format != 4:
        raise _error(
            f"This is an Insomnia export in format {export_format!r}{_where(label)}; this importer reads "
            "format 4 (JSON) and 5 (YAML). Export it again from a current Insomnia",
            "FORMAT_VERSION_UNSUPPORTED",
        )
    resources = document.get("resources")
    if not isinstance(resources, list):
        raise _error(f"`resources` must be a list{_where(label)}", "INPUT_MALFORMED")
    by_id: Dict[str, Tuple[int, Mapping[str, Any]]] = {}
    for index, resource in enumerate(resources):
        if not isinstance(resource, Mapping) or not isinstance(resource.get("_type"), str):
            raise _error(f"resources[{index}] has no `_type`{_where(label)}", "INPUT_MALFORMED")
        if isinstance(resource.get("_id"), str):
            by_id[resource["_id"]] = (index, resource)
    children: Dict[str, List[Tuple[int, Mapping[str, Any]]]] = {}
    for index, resource in enumerate(resources):
        children.setdefault(str(resource.get("parentId") or ""), []).append((index, resource))
    for siblings in children.values():
        siblings.sort(key=lambda item: (_sort_key(item[1].get("metaSortKey")), item[0]))

    workspaces = [(index, res) for index, res in enumerate(resources) if res["_type"] == "workspace"]
    export = _Export(format="v4", title=" · ".join(str(res.get("name") or "").strip() for _, res in workspaces))
    tree_types = {"request_group", "request", "grpc_request", "websocket_request"}
    roots = {str(res.get("_id")) for _, res in workspaces}
    for index, resource in enumerate(resources):
        if resource["_type"] in tree_types | {"environment"} and str(resource.get("parentId") or "") not in by_id:
            raise _error(
                f"{resource['_type']} {resource.get('name')!r} (resources[{index}]) names parent "
                f"`{resource.get('parentId')}`, which the export does not declare — the folder tree cannot be rebuilt",
                "INPUT_SEMANTIC_INVALID",
            )

    def _build_folder(folder: _Folder, parent_id: str, seen: Tuple[str, ...]) -> None:
        for index, resource in children.get(parent_id, []):
            kind = resource["_type"]
            if kind == "request_group":
                child_id = str(resource.get("_id"))
                if child_id in seen:
                    raise _error(f"The folders form a cycle at {resource.get('name')!r}", "INPUT_SEMANTIC_INVALID")
                sub = _Folder(
                    name=str(resource.get("name") or "Folder"),
                    auth=resource.get("authentication"),
                    headers=resource.get("headers"),
                    environment=resource.get("environment") if isinstance(resource.get("environment"), Mapping) else {},
                    has_script=_v4_scripts(resource),
                )
                _build_folder(sub, child_id, seen + (child_id,))
                folder.children.append(("folder", sub, f"resources/{index}"))
            elif kind == "request":
                folder.children.append(("request", resource, f"resources/{index}"))
            elif kind == "grpc_request":
                _skip(export.skipped, "insomnia.grpc_request", resource.get("name"))
            elif kind == "websocket_request":
                _skip(export.skipped, "insomnia.websocket_request", resource.get("name"))

    for _, workspace in workspaces:
        root = _Folder(name=str(workspace.get("name") or ""))
        _build_folder(root, str(workspace.get("_id")), (str(workspace.get("_id")),))
        export.roots.append(root)

    # Base environments hang off a workspace; sub-environments off a base environment.
    base_ids = []
    for _, resource in [(i, r) for i, r in enumerate(resources) if r["_type"] == "environment"]:
        if str(resource.get("parentId") or "") in roots:
            base_ids.append(str(resource.get("_id")))
            export.environments.append(
                _environment(
                    str(resource.get("name") or "Base Environment"), resource.get("data"), resource.get("kvPairData")
                )
            )
    for base_id in base_ids:
        for _, resource in children.get(base_id, []):
            if resource["_type"] == "environment":
                export.environments.append(
                    _environment(
                        str(resource.get("name") or "Environment"), resource.get("data"), resource.get("kvPairData")
                    )
                )

    for resource in resources:
        kind = resource["_type"]
        if kind in ("unit_test_suite", "unit_test"):
            _skip(export.skipped, "insomnia.unit_test", resource.get("name"))
        elif kind == "api_spec" and _is_script(resource.get("contents")):
            _skip(export.skipped, "insomnia.api_spec", resource.get("fileName") or resource.get("name"))
        elif kind in ("mock_server", "mock_route"):
            _skip(export.skipped, "insomnia.mock_route", resource.get("name"))
        elif kind == "cookie_jar" and resource.get("cookies"):
            _skip(export.skipped, "insomnia.cookie_jar", resource.get("name") or "Default Jar")
    return export


def _sort_key(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --- v5 ------------------------------------------------------------------


def _v5_scripts(node: Mapping[str, Any]) -> bool:
    scripts = node.get("scripts")
    return isinstance(scripts, Mapping) and any(_is_script(value) for value in scripts.values())


def _v5_environments(block: Any) -> List[_Environment]:
    """A v5 ``environments`` block (or a global environment document): base first, then sub-environments."""
    if not isinstance(block, Mapping):
        return []
    found = [_environment(str(block.get("name") or "Base Environment"), block.get("data"), block.get("kvPairData"))]
    for sub in block.get("subEnvironments") or []:
        if isinstance(sub, Mapping):
            found.append(_environment(str(sub.get("name") or "Environment"), sub.get("data"), sub.get("kvPairData")))
    return found


def _read_v5(document: Mapping[str, Any], kind: str, label: Optional[str]) -> _Export:
    """Read a v5 document's nested collection into the shared shape."""
    export = _Export(format="v5", title=str(document.get("name") or "").strip())

    def _read_items(items: Any, folder: _Folder, pointer: str, seen_depth: int) -> None:
        if items is None:
            return
        if not isinstance(items, list):
            raise _error(f"`{pointer}` must be a list{_where(label)}", "INPUT_MALFORMED")
        if seen_depth > 64:
            raise _error(f"Folders nest too deeply at `{pointer}`", "INPUT_SEMANTIC_INVALID")
        for index, item in enumerate(items):
            where = f"{pointer}/{index}"
            if not isinstance(item, Mapping):
                raise _error(f"`{where}` must be a mapping{_where(label)}", "INPUT_MALFORMED")
            url = item.get("url")
            if isinstance(item.get("children"), list) or ("children" in item and url is None):
                sub = _Folder(
                    name=str(item.get("name") or "Folder"),
                    auth=item.get("authentication"),
                    headers=item.get("headers"),
                    environment=item.get("environment") if isinstance(item.get("environment"), Mapping) else {},
                    has_script=_v5_scripts(item),
                )
                _read_items(item.get("children"), sub, f"{where}/children", seen_depth + 1)
                folder.children.append(("folder", sub, where))
            elif isinstance(url, str) and url.strip().lower().startswith(("ws://", "wss://")):
                _skip(export.skipped, "insomnia.websocket_request", item.get("name"))
            elif item.get("protoFileId") or item.get("protoMethodName"):
                _skip(export.skipped, "insomnia.grpc_request", item.get("name"))
            else:
                folder.children.append(("request", item, where))

    root = _Folder(name=export.title)
    _read_items(document.get("collection"), root, "collection", 0)
    export.roots.append(root)
    export.environments = _v5_environments(document.get("environments"))
    if kind == "environment":
        export.environments = _v5_environments(document) if "environments" not in document else export.environments
    spec = document.get("spec")
    if isinstance(spec, Mapping) and spec.get("contents"):
        _skip(export.skipped, "insomnia.api_spec", export.title or "API spec")
    for suite in document.get("testSuites") or []:
        if isinstance(suite, Mapping):
            _skip(export.skipped, "insomnia.unit_test", suite.get("name"))
    jar = document.get("cookieJar")
    if isinstance(jar, Mapping) and jar.get("cookies"):
        _skip(export.skipped, "insomnia.cookie_jar", jar.get("name") or "Default Jar")
    return export


# ---------------------------------------------------------------------------
# Detection and loading
# ---------------------------------------------------------------------------


def _v5_kind(document: Any) -> Optional[Tuple[str, int]]:
    """``(kind, major)`` for a v5-style document (``collection``, 5), else ``None``."""
    if not isinstance(document, Mapping) or not isinstance(document.get("type"), str):
        return None
    match = _V5_TYPE_RE.match(document["type"].strip())
    return (match.group(1), int(match.group(2))) if match else None


def detect_insomnia(text: str) -> Optional[Tuple[str, float]]:
    """Recognise an Insomnia export from its text, without parsing YAML.

    Args:
        text: The decoded upload.

    Returns:
        ``(reason, confidence)``, or ``None`` when the text is not an Insomnia export.
    """
    head = text.lstrip()
    if head.startswith("{"):
        try:
            document = json.loads(text)
        except ValueError:
            return None
        if isinstance(document, Mapping) and document.get("_type") == "export" and "resources" in document:
            source = str(document.get("__export_source") or "").lower()
            if document.get("__export_format") == 4 and "insomnia" in source:
                return "Insomnia v4 export (_type: export, insomnia.desktop.app)", 0.97
            return "Insomnia-style export (_type: export, resources[])", 0.88
        kind = _v5_kind(document)
        return (f"Insomnia {kind[0]} document (JSON)", 0.9) if kind else None
    match = _V5_TYPE_LINE_RE.search(text[:4096])
    if not match:
        return None
    kind = _V5_TYPE_RE.match(match.group(1))
    assert kind is not None
    if kind.group(1) in ("collection", "spec"):
        return f"Insomnia v{kind.group(2)} {kind.group(1)} ({match.group(1)})", 0.97
    return f"Insomnia v{kind.group(2)} {kind.group(1)} document ({match.group(1)})", 0.5


def _looks_like_other_format(document: Any) -> Optional[str]:
    """Name the format a document that is not an Insomnia export looks like, if any."""
    if not isinstance(document, Mapping):
        return None
    info = document.get("info")
    if isinstance(info, Mapping) and ("_postman_id" in info or "getpostman" in str(info.get("schema", ""))):
        return "a Postman collection"
    if str(document.get("clientName") or "") == "Thunder Client":
        return "a Thunder Client export"
    if isinstance(document.get("folders"), list) and isinstance(document.get("requests"), list):
        return "a Hoppscotch collection"
    if "openapi" in document or "swagger" in document:
        return "an OpenAPI document"
    if isinstance(document.get("log"), Mapping) and "entries" in document["log"]:
        return "a HAR capture"
    return None


def _load(text: str, label: Optional[str]) -> Any:
    if text.lstrip().startswith(("{", "[")):
        return load_client_json(text, label, product="Insomnia", error=_error)
    return load_client_yaml(text, label, product="Insomnia", error=_error)


def _read_export(document: Any, label: Optional[str]) -> _Export:
    """Classify and read one loaded member.

    Raises:
        InsomniaParseError: ``FORMAT_MISMATCH`` when it is not an Insomnia export,
            ``FORMAT_VERSION_UNSUPPORTED`` for another export format.
    """
    if isinstance(document, Mapping) and document.get("_type") == "export":
        return _read_v4(document, label)
    kind = _v5_kind(document)
    if kind is not None:
        if kind[1] != 5:
            raise _error(
                f"This is an Insomnia v{kind[1]} document{_where(label)}; this importer reads format 4 "
                "(JSON) and 5 (YAML)",
                "FORMAT_VERSION_UNSUPPORTED",
            )
        if kind[0] == "mock":
            raise _error(
                f"This is an Insomnia mock server{_where(label)}, not a collection — export the collection instead",
                "INPUT_SEMANTIC_INVALID",
            )
        return _read_v5(document, kind[0], label)
    other = _looks_like_other_format(document)
    if other:
        raise _error(f"The upload{_where(label)} is {other}, not an Insomnia export", "FORMAT_MISMATCH")
    raise _error(
        f"The upload{_where(label)} is not an Insomnia export: expected a v4 JSON export "
        "(`_type: export`, `resources[]`) or a v5 YAML export (`type: collection.insomnia.rest/5.0`)",
        "FORMAT_MISMATCH",
    )


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


def _scalar(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Nested environment data → dotted names (``{"api": {"host": …}}`` → ``api.host``)."""
    flat: Dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{name}."))
        flat.setdefault(name, value)
    return flat


@dataclass
class _Scope:
    """Variable values, closest scope first; a secret variable is defined but valueless."""

    layers: Tuple[Dict[str, Any], ...] = ()
    secret: frozenset = frozenset()

    def child(self, data: Mapping[str, Any]) -> "_Scope":
        """A scope with a folder's own variables in front (a secret-named one defined but valueless)."""
        if not data:
            return self
        flat = _flatten(data)
        secret = {name for name in flat if SECRET_NAME_RE.search(name)}
        return _Scope(layers=(flat,) + self.layers, secret=self.secret | secret)

    def lookup(self, name: str) -> Tuple[bool, Optional[str]]:
        """Return ``(defined, value)`` for ``name``."""
        for layer in self.layers:
            if name in layer:
                return True, (None if name in self.secret else _scalar(layer[name]))
        return False, None

    def resolve(self, text: str) -> Optional[str]:
        """Substitute every variable in ``text``, or ``None`` when one has no value (or a tag remains)."""
        current = text
        for _ in range(_MAX_VARIABLE_DEPTH):
            if _TEMPLATE_TAG_RE.search(current):
                return None
            missing = False

            def _replace(match: "re.Match[str]") -> str:
                nonlocal missing
                defined, value = self.lookup(match.group(1))
                if not defined or value is None:
                    missing = True
                    return match.group(0)
                return value

            current = _VARIABLE_RE.sub(_replace, current)
            if missing:
                return None
            if not _VARIABLE_RE.search(current):
                return current
        return None


def _param_name(variable: str) -> str:
    """A variable's name as a path / server parameter (``api.host`` → ``api_host``)."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", variable.lstrip("$"))


def _scrub_named(name: str, value: str) -> str:
    """Scrub a header / parameter / form value; a whole ``{{ variable }}`` reference is kept."""
    return scrub_named(name, value, reference=_WHOLE_VARIABLE_RE)


# ---------------------------------------------------------------------------
# Auth, bodies, URLs
# ---------------------------------------------------------------------------


def _read_auth(auth: Any, declared_at: str) -> Tuple[bool, Optional[InsomniaAuth]]:
    """Read one ``authentication`` block.

    Returns:
        ``(inherits, auth)`` — ``inherits`` is ``True`` for a missing / empty block or
        ``type: inherit``; ``auth`` is ``None`` for no auth (``type: none``, ``disabled: true``).
    """
    if not isinstance(auth, Mapping) or not auth:
        return True, None
    auth_type = str(auth.get("type") or "").strip().lower()
    if auth_type in ("", "inherit"):
        return True, None
    if auth_type == "none" or auth.get("disabled") is True:
        return False, None
    grant_type = token_url = key_name = key_location = None
    scopes: Tuple[str, ...] = ()
    if auth_type == "oauth2":
        if isinstance(auth.get("grantType"), str) and auth["grantType"].strip():
            grant_type = auth["grantType"].strip()
        for key in _OAUTH_URL_FIELDS:
            endpoint = auth.get(key)
            if isinstance(endpoint, str) and endpoint.strip() and not _WHOLE_VARIABLE_RE.match(endpoint):
                token_url = scrub_value(endpoint.strip())
                break
        if isinstance(auth.get("scope"), str):
            scopes = tuple(scope for scope in re.split(r"[\s,]+", auth["scope"]) if scope)
    scheme = AUTH_SCHEMES.get(auth_type, "authorization")
    if auth_type == "apikey":
        if isinstance(auth.get("key"), str) and auth["key"].strip() and not _WHOLE_VARIABLE_RE.match(auth["key"]):
            key_name = auth["key"].strip()  # the header / parameter *name*; its value is never read
        key_location = str(auth.get("addTo") or "header")
        if key_location == "cookie":
            scheme = "cookie"
    return False, InsomniaAuth(
        type=auth_type,
        scheme=scheme,
        declared_at=declared_at,
        grant_type=grant_type,
        token_url=token_url,
        scopes=scopes,
        key_name=key_name,
        key_location=key_location,
    )


def _enabled_pairs(entries: Any, *, label: str) -> List[Tuple[str, str, Mapping[str, Any]]]:
    """The enabled ``{name, value, disabled}`` entries of a ``headers`` / ``parameters`` / ``params`` list."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise _error(f"{label} must be a list", "INPUT_MALFORMED")
    found: List[Tuple[str, str, Mapping[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise _error(f"{label} entries must be objects", "INPUT_MALFORMED")
        name = entry.get("name")
        if entry.get("disabled") is True or not isinstance(name, str) or not name.strip():
            continue
        value = entry.get("value")
        found.append((name.strip(), "" if value is None else str(value), entry))
    return found


def _json_text(raw: str) -> str:
    """Scrub a JSON body, quoting bare ``{{ variables }}`` when that is what keeps it parseable."""
    scrubbed = scrub_value(raw)
    try:
        json.loads(scrubbed)
    except json.JSONDecodeError:
        scrubbed = _BARE_JSON_VARIABLE_RE.sub(lambda match: json.dumps(match.group(1)), scrubbed)
    return scrubbed


def _media_type(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split(";", 1)[0].strip().lower()


def _body(request: Mapping[str, Any], label: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(content_type, body_text)`` for a request, the text scrubbed (bodies as declared).

    A JSON body stays JSON so the engine infers its schema; a GraphQL body (``application/graphql``,
    whose text is ``{query, variables}``) is sent as JSON; a form body becomes the JSON object of
    its fields (a file part is a string). Any other body keeps its media type and text.
    """
    body = request.get("body")
    if body is None or (isinstance(body, Mapping) and not body):
        return None, None
    if not isinstance(body, Mapping):
        raise _error(f"{label}: `body` must be an object", "INPUT_MALFORMED")
    media_type = _media_type(body.get("mimeType"))
    text = body.get("text") if isinstance(body.get("text"), str) and body["text"].strip() else None
    if media_type in _FORM_TYPES:
        fields = {
            name: ("" if entry.get("type") == "file" else _scrub_named(name, value))
            for name, value, entry in _enabled_pairs(body.get("params"), label=f"{label} body params")
        }
        return (media_type, json.dumps(fields, sort_keys=True)) if fields else (media_type, None)
    if media_type == "application/graphql":
        if text is None:
            return None, None
        try:
            document = json.loads(_json_text(text))
        except json.JSONDecodeError:
            document = {"query": text}
        payload: Dict[str, Any] = {}
        if isinstance(document, Mapping):
            if isinstance(document.get("query"), str):
                payload["query"] = scrub_value(document["query"])
            if isinstance(document.get("variables"), Mapping):
                payload["variables"] = document["variables"]
        return ("application/json", json.dumps(payload, sort_keys=True)) if payload else (None, None)
    if media_type and (media_type == "application/json" or media_type.endswith("+json")):
        return media_type, _json_text(text) if text else None
    if text is not None:
        return media_type or "text/plain", scrub_value(text)
    if media_type:
        return media_type, None  # a file body: the media type only
    return None, None


def _request_url(
    url: str,
    scope: _Scope,
    server_variables: Dict[str, Optional[str]],
    label: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Turn a saved URL into the engine's URL plus the query pairs written into it.

    A URL that starts with a variable (``{{ _.baseUrl }}/users``) is a server template: the variable
    becomes a server variable whose default is resolved from the environments unless it is secret,
    and the rest is the path. Every other variable, template tag and ``:name`` inside the path is a
    path parameter.

    Raises:
        InsomniaParseError: ``INPUT_SEMANTIC_INVALID`` for an empty URL or one written only as a
            variable nothing defines.
    """
    url = url.strip()
    if not url:
        raise _error(f"{label} has no URL", "INPUT_SEMANTIC_INVALID")
    leading = _LEADING_VARIABLE_RE.match(url)
    if leading:
        name = leading.group(1)
        rest = url[leading.end() :]
        defined, value = scope.lookup(name)
        if not rest.strip("/") and not rest.startswith("?") and not defined:
            raise _error(
                f"{label} has a URL written only as `{{{{ _.{name} }}}}`, which nothing in the upload "
                "defines — its path cannot be known",
                "INPUT_SEMANTIC_INVALID",
            )
        resolved = scope.resolve(value) if isinstance(value, str) else None
        server = _param_name(name)
        server_variables.setdefault(server, None)
        if resolved is not None and server_variables[server] is None:
            server_variables[server] = scrub_value(resolved)
        url = rest if rest.startswith("/") else "/" + rest
    tags = iter(range(1, 1000))
    url = _TEMPLATE_TAG_RE.sub(lambda _match: "{templateTag" + str(next(tags)) + "}", url)
    url = _VARIABLE_RE.sub(lambda match: "{" + _param_name(match.group(1)) + "}", url)
    parts = urlsplit(url if "://" in url or url.startswith("/") else f"http://{url}")
    path = _PATH_PARAM_RE.sub(lambda match: "{" + match.group(1) + "}", parts.path or "/")
    query = [(key, _scrub_named(key, value)) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    if parts.netloc:
        host = parts.netloc.rsplit("@", 1)[-1]  # userinfo is a credential, never kept
        return f"{parts.scheme or 'http'}://{host}{path}", query
    return path, query


def _has_tag(*values: Any) -> bool:
    return any(isinstance(value, str) and _TEMPLATE_TAG_RE.search(value) for value in values)


# ---------------------------------------------------------------------------
# Reading the tree
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    """What a request inherits from the folders above it."""

    path: Tuple[str, ...]
    auth: Optional[InsomniaAuth]
    headers: Tuple[Tuple[str, str], ...]
    has_script: bool
    scope: _Scope


@dataclass
class _Reader:
    """Reads exports into observations, sharing one server table."""

    source_label: Optional[str]
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[InsomniaRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[InsomniaVariable] = field(default_factory=list)

    def read_folder(self, folder: _Folder, context: _Context, *, member: Optional[str]) -> None:
        """Read every request below ``folder``."""
        for kind, node, pointer in folder.children:
            if kind == "folder":
                path = context.path + (node.name,)
                inherits, own = _read_auth(node.auth, " / ".join(path))
                headers = dict((key.lower(), (key, value)) for key, value in context.headers)
                for key, value, _ in _enabled_pairs(node.headers, label=f"Folder {node.name!r} headers"):
                    headers[key.lower()] = (key, value)
                for name in sorted(_flatten(node.environment)):
                    self.variables.append(
                        InsomniaVariable(
                            name=name, source=f"folder:{' / '.join(path)}", secret=bool(SECRET_NAME_RE.search(name))
                        )
                    )
                child = _Context(
                    path=path,
                    auth=context.auth if inherits else own,
                    headers=tuple(headers[key] for key in sorted(headers)),
                    has_script=context.has_script or node.has_script,
                    scope=context.scope.child(node.environment),
                )
                self.read_folder(node, child, member=member)
            else:
                self.read_request(node, context, pointer=pointer, member=member)

    def read_request(
        self, request: Mapping[str, Any], context: _Context, *, pointer: str, member: Optional[str]
    ) -> None:
        """Read one saved request into an observation."""
        name = str(request.get("name") or pointer)
        label = f"Request {name!r}"
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            raise _error(f"{label} has no method", "INPUT_MALFORMED")
        raw_url = request.get("url")
        if not isinstance(raw_url, str):
            raise _error(f"{label} has no URL", "INPUT_SEMANTIC_INVALID")
        scope = context.scope
        url, url_query = _request_url(raw_url, scope, self.server_variables, label)
        inherits, own = _read_auth(request.get("authentication"), "request")
        auth = context.auth if inherits else own

        defaults: List[Tuple[str, str, str]] = []

        def _default(location: str, key: str, value: str) -> None:
            whole = _WHOLE_VARIABLE_RE.match(value)
            if not whole:
                return
            resolved = scope.resolve(value)
            if resolved is not None and not SECRET_NAME_RE.search(key) and not SECRET_NAME_RE.search(whole.group(1)):
                defaults.append((location, key.lower() if location == "header" else key, scrub_value(resolved)))

        merged: Dict[str, Tuple[str, str]] = {key.lower(): (key, value) for key, value in context.headers}
        raw_headers = _enabled_pairs(request.get("headers"), label=f"{label} headers")
        for key, value, _ in raw_headers:
            merged[key.lower()] = (key, value)  # a request's own header wins
        content_type, body = _body(request, label)
        if content_type and "content-type" not in merged:
            merged["content-type"] = ("Content-Type", content_type)
        for key, value in merged.values():
            _default("header", key, value)
        headers = tuple((key, _scrub_named(key, value)) for key, value in (merged[k] for k in sorted(merged)))

        listed = [
            (key, value) for key, value, _ in _enabled_pairs(request.get("parameters"), label=f"{label} parameters")
        ]
        names = {key for key, _ in listed}
        for key, value in listed:
            _default("query", key, value)
        query = [(key, _scrub_named(key, value)) for key, value in listed] + [
            (key, value) for key, value in url_query if key not in names
        ]
        body_text = request.get("body", {}).get("text") if isinstance(request.get("body"), Mapping) else None
        observation = HttpObservation(
            method=method.strip().upper(),
            url=url,
            headers=headers,
            query=tuple(query),
            request_body=body,
            source_location=pointer,
            source_label=name,
            source_file=member or self.source_label,
        )
        self.observations.append(observation)
        has_script = (
            context.has_script
            or _is_script(request.get("preRequestScript"))
            or _is_script(request.get("afterResponseScript"))
            or _v5_scripts(request)
        )
        self.requests.append(
            InsomniaRequest(
                name=name,
                method=observation.method,
                url=url,
                folder=context.path,
                auth=auth,
                content_type=content_type,
                has_script=has_script,
                has_template_tag=_has_tag(
                    raw_url, body_text, *(value for _, value, _ in raw_headers), *(v for _, v in listed)
                ),
                defaults=tuple(sorted(set(defaults))),
            )
        )


def _build(exports: Sequence[Tuple[Optional[str], _Export]], source_label: Optional[str]) -> InsomniaDocument:
    """Read the loaded exports (and environment documents) into one document.

    The environments of every export share one scope. The **base** environment's value wins; a
    variable only sub-environments define takes the first one's value, in Insomnia's order.

    Raises:
        InsomniaParseError: ``INPUT_SEMANTIC_INVALID`` when no HTTP request is left to import.
    """
    layers: List[Dict[str, Any]] = []
    secret: set = set()
    variables: List[InsomniaVariable] = []
    environment_names: List[str] = []
    skipped: Dict[str, List[str]] = {}
    for _, export in exports:
        for construct, names in export.skipped.items():
            skipped.setdefault(construct, []).extend(names)
        for environment in export.environments:
            environment_names.append(environment.name)
            flat = _flatten(environment.data)
            for name, value in flat.items():
                is_secret = name in environment.secret_names or bool(SECRET_NAME_RE.search(name))
                if is_secret:
                    secret.add(name)
                if isinstance(value, Mapping):
                    continue
                variables.append(
                    InsomniaVariable(name=name, source=f"environment:{environment.name}", secret=is_secret)
                )
            layers.append(flat)
    # Earlier layers win in lookup order, so a variable the base defines is never overridden.
    scope = _Scope(layers=tuple(layers), secret=frozenset(secret))

    reader = _Reader(source_label=source_label)
    for member, export in exports:
        for root in export.roots:
            reader.read_folder(
                root, _Context(path=(), auth=None, headers=(), has_script=False, scope=scope), member=member
            )
    if not reader.observations:
        left_out = sorted(k.split(".", 1)[1].replace("_", " ") for k in skipped if "request" in k)
        hint = f" (it has {' and '.join(left_out)}s, which are not HTTP requests)" if left_out else ""
        if any(export.environments for _, export in exports) and not any(
            root.children for _, export in exports for root in export.roots
        ):
            hint = " — upload an environment together with the collection that uses it"
        if "insomnia.api_spec" in skipped:
            hint = " — a design document's API spec imports as OpenAPI; this import reads its requests"
        raise _error(f"The upload has no HTTP requests to import{hint}", "INPUT_SEMANTIC_INVALID")

    titles = [export.title for _, export in exports if export.title]
    return InsomniaDocument(
        title=" · ".join(dict.fromkeys(titles)) or "Insomnia collection",
        export_formats=[export.format for _, export in exports],
        observations=reader.observations,
        requests=reader.requests,
        server_variables=reader.server_variables,
        variables=sorted(set(variables + reader.variables), key=lambda var: (var.name, var.source)),
        environments=environment_names,
        skipped={construct: names for construct, names in sorted(skipped.items())},
        source_label=source_label,
    )


def parse_insomnia_text(raw: str, *, source_label: Optional[str] = None) -> InsomniaDocument:
    """Parse one Insomnia export (v4 JSON or v5 YAML).

    Args:
        raw: The decoded upload.
        source_label: The filename or paste label.

    Returns:
        The parsed document.

    Raises:
        InsomniaParseError: With the taxonomy code for the fault (see the module docstring).
    """
    export = _read_export(_load(raw, source_label), source_label)
    return _build([(None, export)], source_label)


def parse_insomnia_fileset(
    members: Mapping[str, str],
    *,
    root: Optional[str] = None,
    source_label: Optional[str] = None,
) -> InsomniaDocument:
    """Parse several exports — collections and the environment files they use — into one API.

    Every ``.json`` / ``.yaml`` / ``.yml`` member is read; other members (a README) are ignored.

    Args:
        members: Member text keyed by path.
        root: The root member's path (read first).
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        InsomniaParseError: With the taxonomy code for the fault; a set with no export is
            ``FORMAT_MISMATCH``.
    """
    names = [name for name in sorted(members) if PurePosixPath(name).suffix.lower() in MEMBER_SUFFIXES]
    if root in names:
        names.remove(root)
        names.insert(0, root)
    if not names:
        raise _error(f"The upload{_where(source_label)} has no Insomnia export among its files", "FORMAT_MISMATCH")
    exports = [(name, _read_export(_load(members[name], name), name)) for name in names]
    return _build(exports, source_label or root)
