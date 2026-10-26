"""Shared pieces of the API-client collection importers — FMT-10.1 (#5473), FMT-10.2 (#5475).

Hoppscotch and Thunder Client exports are read the same way: every saved request becomes a
concrete :class:`~app.inferred_spec.HttpObservation` for the shared inferred-spec engine, and the
facts the engine has no slot for (the folder a request sits in, the auth it resolves to, its body's
media type, the variables its URLs are written against) are layered onto the engine's operations
afterwards. The format readers differ in their JSON shape and variable syntax; what they share —
loading JSON with the taxonomy codes, scrubbing values through the secret-scrub gate, and the
post-processing of the engine's model — lives here so it is written once.

**Credentials.** :func:`scrub_value` passes a value through the shared gate
(:mod:`app.intake_secret_scrub`); :func:`scrub_named` additionally redacts a header, parameter or
form field outright when its *name* says it holds a secret. Readers never read auth credential
fields at all; these helpers cover every other value that reaches an observation.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Mapping, Optional, Pattern, Protocol, Sequence, Set, Tuple

import yaml

from .canonical_model import CanonicalApi, MessageRole, ParameterLocation, Server, ServerVariable
from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .intake_secret_scrub import REDACTION_MARKER, scrub_document_text

__all__ = [
    "FOLDER_SEPARATOR",
    "SECRET_NAME_RE",
    "annotate_operations",
    "apply_parameter_defaults",
    "check_client_text",
    "declared_limit",
    "folder_paths",
    "load_client_json",
    "load_client_yaml",
    "scrub_named",
    "scrub_value",
    "template_servers",
]

#: How a nested folder path is spelled as an operation tag (``Catalogue / Products``).
FOLDER_SEPARATOR = " / "

#: A header, parameter or form-field name that says its value is a credential.
SECRET_NAME_RE = re.compile(
    r"(authorization|cookie|password|passwd|secret|api[-_]?key|apikey|token|credential"
    r"|passphrase|session|signature|private[-_]?key)",
    re.IGNORECASE,
)

_ENCODING_FAULT_MARKERS = ("\x00", "�")

#: Builds the reader's own error from a message and a taxonomy code.
ErrorFactory = Callable[[str, str], Exception]


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def load_client_json(text: str, label: Optional[str], *, product: str, error: ErrorFactory) -> Any:
    """Load one client export, applying the encoding check and the shared intake guards.

    Args:
        text: The decoded upload.
        label: The member path or filename, for messages.
        product: The client's name (``Hoppscotch``), for messages.
        error: Builds the reader's error from ``(message, code)``.

    Returns:
        The loaded JSON value.

    Raises:
        Exception: The reader's error, with ``INPUT_ENCODING_INVALID`` (NULs, replacement characters
            or a byte-order mark — a UTF-16 upload decoded as UTF-8), ``INPUT_TRUNCATED`` (the JSON
            ends while a value is open), ``INPUT_MALFORMED`` (any other syntax error, an empty
            upload) or a resource-guard code.
    """
    check_client_text(text, label, product=product, syntax="JSON", error=error)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        # The decoder reports the offset where it gave up; at (or past) the end of the meaningful
        # text, a value was still open when the bytes ran out.
        if exc.pos >= len(text.rstrip()):
            raise error(
                f"The collection{_where(label)} ends while a value is still open — the upload is truncated: {exc}",
                "INPUT_TRUNCATED",
            ) from exc
        raise error(f"Invalid JSON{_where(label)}: {exc}", "INPUT_MALFORMED") from exc
    try:
        guard_parsed_document(document, source_label=label)
    except IntakeLimitError as exc:
        raise error(str(exc), exc.code) from exc
    return document


def check_client_text(text: str, label: Optional[str], *, product: str, syntax: str, error: ErrorFactory) -> None:
    """The checks every client export gets before it is parsed: encoding, emptiness, intake guards.

    Args:
        text: The decoded upload.
        label: The member path or filename, for messages.
        product: The client's name, for messages.
        syntax: What the export is written in (``JSON``, ``YAML``, ``.bru``), for messages.
        error: Builds the reader's error from ``(message, code)``.

    Raises:
        Exception: The reader's error with ``INPUT_ENCODING_INVALID``, ``INPUT_MALFORMED`` (an empty
            upload) or a resource-guard code.
    """
    if text.startswith("\ufeff") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
        raise error(
            f"The upload{_where(label)} is not UTF-8 text (NULs, replacement characters or a "
            f"byte-order mark); {product} exports are UTF-8 {syntax}",
            "INPUT_ENCODING_INVALID",
        )
    if not text.strip():
        raise error(f"The upload{_where(label)} is empty", "INPUT_MALFORMED")
    try:
        guard_document_text(text, source_label=label)
    except IntakeLimitError as exc:
        raise error(str(exc), exc.code) from exc


def load_client_yaml(text: str, label: Optional[str], *, product: str, error: ErrorFactory) -> Any:
    """Load one YAML client export (Insomnia v5), with the same checks as :func:`load_client_json`.

    ``yaml.safe_load`` builds plain data only (no Python objects); the intake guards bound its alias
    expansion, depth and size before it runs and the parsed tree after.

    Args:
        text: The decoded upload.
        label: The member path or filename, for messages.
        product: The client's name, for messages.
        error: Builds the reader's error from ``(message, code)``.

    Returns:
        The loaded YAML value.

    Raises:
        Exception: The reader's error, with ``INPUT_ENCODING_INVALID``, ``INPUT_TRUNCATED`` (the
            stream ends inside a quoted scalar or flow collection), ``INPUT_MALFORMED`` or a
            resource-guard code.
    """
    check_client_text(text, label, product=product, syntax="YAML", error=error)
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        message = str(exc)
        if "end of stream" in message or "<stream end>" in message:
            raise error(
                f"The export{_where(label)} ends while a value is still open — the upload is truncated: {message}",
                "INPUT_TRUNCATED",
            ) from exc
        raise error(f"Invalid YAML{_where(label)}: {message}", "INPUT_MALFORMED") from exc
    try:
        guard_parsed_document(document, source_label=label)
    except IntakeLimitError as exc:
        raise error(str(exc), exc.code) from exc
    return document


def scrub_value(value: str) -> str:
    """Pass one value through the shared secret-scrub gate (named patterns and entropy)."""
    if not value:
        return value
    return scrub_document_text(value).text


def scrub_named(name: str, value: str, *, reference: Pattern[str]) -> str:
    """Scrub a header, parameter or form-field value, redacting it outright if its name is secret.

    A value written entirely as a variable reference is a reference, not a credential, and is kept.

    Args:
        name: The header / parameter / field name.
        value: Its saved value.
        reference: Matches a value that is a whole variable reference (``<<x>>``, ``{{x}}``).

    Returns:
        The value safe to keep in the model.
    """
    if not value or reference.match(value):
        return value
    if SECRET_NAME_RE.search(name or ""):
        return REDACTION_MARKER
    return scrub_value(value)


def declared_limit(construct: str, locations: List[str], note: str) -> Dict[str, Any]:
    """One declared-limit record, in the shape the coverage ledger reads.

    Args:
        construct: The limit's construct id (``hoppscotch.script``).
        locations: Where it occurs (request or variable names; repeats count once each time).
        note: What the import does with it.

    Returns:
        ``{construct, count, locations, note}`` with the locations de-duplicated and sorted.
    """
    return {"construct": construct, "count": len(locations), "locations": sorted(set(locations)), "note": note}


class _Auth(Protocol):
    def as_dict(self) -> Dict[str, Any]: ...


class ClientRequest(Protocol):
    """The per-request facts :func:`annotate_operations` reads."""

    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[_Auth]
    content_type: Optional[str]


def folder_paths(requests: Sequence[ClientRequest]) -> List[str]:
    """Every folder level that holds a request, directly or in a sub-folder, as a path."""
    return sorted(
        {
            FOLDER_SEPARATOR.join(request.folder[:depth])
            for request in requests
            for depth in range(1, len(request.folder) + 1)
        }
    )


def annotate_operations(api: CanonicalApi, requests: Sequence[ClientRequest], *, auth_extras_key: str) -> Set[str]:
    """Add folder tags, auth and body content types to the engine's operations.

    The engine reports the ``(method, url)`` samples each operation was built from; those are
    matched back to the parsed requests.

    Args:
        api: The engine's model (modified in place).
        requests: The parsed requests.
        auth_extras_key: The operation extras key for the resolved auth records.

    Returns:
        Every canonical auth scheme an operation declares.
    """
    index: Dict[Tuple[str, str], List[ClientRequest]] = defaultdict(list)
    for request in requests:
        index[(request.method, request.url)].append(request)
    schemes: Set[str] = set()
    for service in api.services:
        for operation in service.operations:
            evidence = operation.extras.get("inference_evidence") or {}
            matched: List[ClientRequest] = []
            for url in dict.fromkeys(evidence.get("sample_urls") or []):
                matched.extend(index.get((operation.http_method or "", url), []))
            operation.tags = sorted({FOLDER_SEPARATOR.join(req.folder) for req in matched if req.folder})
            unique = {
                json.dumps(req.auth.as_dict(), sort_keys=True): req.auth.as_dict()
                for req in matched
                if req.auth is not None
            }
            if unique:
                records = [unique[key] for key in sorted(unique)]
                operation.extras[auth_extras_key] = records
                operation.extras["security"] = sorted({record["scheme"] for record in records})
                schemes.update(operation.extras["security"])
            content_types = sorted({req.content_type for req in matched if req.content_type})
            for message in operation.messages:
                if message.role is MessageRole.REQUEST and content_types:
                    message.content_types = content_types
    return schemes


class DefaultedRequest(Protocol):
    """The per-request facts :func:`apply_parameter_defaults` reads."""

    method: str
    url: str
    defaults: Tuple[Tuple[str, str, str], ...]


_DEFAULT_LOCATIONS = {"query": ParameterLocation.QUERY, "header": ParameterLocation.HEADER}


def apply_parameter_defaults(api: CanonicalApi, requests: Sequence[DefaultedRequest]) -> None:
    """Set query / header parameter defaults from environment values, where every sample agrees.

    A reader records, per request, ``(location, name, value)`` for each parameter written as a
    whole variable whose (non-secret) value an environment defines — header names lower-cased, as
    the engine names header parameters. The requests are matched back to the engine's operations
    through ``inference_evidence.sample_urls`` (as in :func:`annotate_operations`), and a parameter
    gets a default only when all its samples give the same value.

    Args:
        api: The engine's model (modified in place).
        requests: The parsed requests.
    """
    index: Dict[Tuple[str, str], List[DefaultedRequest]] = defaultdict(list)
    for request in requests:
        index[(request.method, request.url)].append(request)
    for service in api.services:
        for operation in service.operations:
            evidence = operation.extras.get("inference_evidence") or {}
            values: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
            for url in dict.fromkeys(evidence.get("sample_urls") or []):
                for request in index.get((operation.http_method or "", url), []):
                    for location, name, value in request.defaults:
                        values[(location, name)].add(value)
            for parameter in operation.parameters:
                for location, enum in _DEFAULT_LOCATIONS.items():
                    found = values.get((location, parameter.name))
                    if parameter.location is enum and found and len(found) == 1:
                        parameter.default = next(iter(found))


def template_servers(server_variables: Mapping[str, Optional[str]], *, describe: Callable[[str], str]) -> List[Server]:
    """One ``{variable}`` server per leading URL variable, its default from the environment.

    Args:
        server_variables: Variable name → its default (``None`` when unknown or secret).
        describe: Builds the variable's description from its name.

    Returns:
        The servers, sorted by variable name.
    """
    return [
        Server(
            url="{" + name + "}",
            name=name,
            variables=[ServerVariable(name=name, default=server_variables[name], description=describe(name))],
        )
        for name in sorted(server_variables)
    ]
