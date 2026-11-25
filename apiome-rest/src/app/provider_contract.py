"""What a provider contract is, and what a valid one looks like — PFX-2.1 (#6925).

Bi-directional contract testing (PFX-EPIC-2) checks a consumer's pact against the provider's
OpenAPI document rather than against a running provider. That document, registered against a
provider version of the broker's model (:mod:`app.pacticipant`), is the **provider contract**.
:mod:`app.provider_contract_store` is the only place one is read or written (apiome-db V438),
:mod:`app.provider_contract_source` renders one from an Apiome version, and
:mod:`app.provider_contract_routes` is the REST surface.

**OpenAPI 3.x, or AsyncAPI 2.x / 3.x.** A document is accepted when it parses (JSON or YAML,
under the DCW-0.2 resource limits of :mod:`app.safe_oas_parse`) and either declares ``openapi:
3.0.x``, ``3.1.x`` or ``3.2.x`` and validates against that version's bundled meta-schema
(:mod:`app.openapi_validator`), or — ``contractType: asyncapi``, PFX-3.6 (#6936), for message
pacts — declares ``asyncapi: 2.x`` or ``3.x`` and passes the structural check of
:func:`validate_asyncapi_contract` (version, ``info``, channels, operations and every local
``$ref``). Swagger 2.0 and anything else are refused. Every refusal names the place (a JSON Pointer
into the document, or into the request body) so the publisher can find it.

**YAML is read as the JSON it stands for.** A mapping key YAML reads as a number or a boolean
(``200:`` under ``responses``) becomes the string the OpenAPI document means (``"200"``), and an
unquoted date becomes its ISO-8601 text. Values JSON cannot carry (binary, ``.nan``, ``.inf``) are
refused with their location — nothing is dropped.

**A contract is addressed by its content.** :func:`provider_contract_sha` is the SHA-256 of the
document's canonical JSON (sorted keys, no insignificant whitespace), so the same document sent as
JSON, as YAML, or rendered from an Apiome version has one address, and publishing it for ten
provider versions stores it once.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .asyncapi_parser import is_supported_asyncapi_version
from .openapi_validator import openapi_document_errors_at
from .pact_asyncapi_index import AsyncApiIndex
from .revision_deprecation import is_uuid_string as _is_uuid
from .safe_oas_parse import safe_oas_parse

__all__ = [
    "CODE_CONTRACT_CONFLICT",
    "CODE_CONTRACT_INVALID",
    "CODE_CONTRACT_NOT_FOUND",
    "CODE_CONTRACT_TOO_LARGE",
    "CODE_REQUEST_INVALID",
    "CODE_SOURCE_NOT_FOUND",
    "CODE_UNSUPPORTED",
    "CONTRACT_TYPE_ASYNCAPI",
    "CONTRACT_TYPE_OAS",
    "CONTRACT_TYPES",
    "JSON_CONTENT_TYPE",
    "SOURCE_APIOME",
    "SOURCE_INLINE",
    "ApiomeReference",
    "ProviderContractError",
    "ProviderContractRecord",
    "ProviderContractToStore",
    "PublishProviderContractRequest",
    "PublishedProviderContract",
    "SelfVerificationResults",
    "check_request",
    "contract_record_from_row",
    "contract_type_of",
    "decode_base64",
    "parse_apiome_reference",
    "parse_openapi",
    "prepare_contract",
    "provider_contract_sha",
    "sent_verification_results",
    "stored_verification_results",
    "validate_asyncapi_contract",
    "validate_contract",
    "validate_openapi_contract",
]

# Stable refusal codes. A client branches on these, never on the message.
CODE_CONTRACT_INVALID = "provider-contract-invalid"
CODE_CONTRACT_TOO_LARGE = "provider-contract-too-large"
CODE_CONTRACT_CONFLICT = "provider-contract-conflict"
CODE_CONTRACT_NOT_FOUND = "provider-contract-not-found"
CODE_REQUEST_INVALID = "provider-contract-request-invalid"
CODE_UNSUPPORTED = "provider-contract-unsupported"
CODE_SOURCE_NOT_FOUND = "provider-contract-source-not-found"

#: Where a stored document came from.
SOURCE_INLINE = "inline"
SOURCE_APIOME = "apiome"

JSON_CONTENT_TYPE = "application/json"

#: Media types read as JSON, and as YAML. Parameters (``; charset=utf-8``) are ignored.
_JSON_TYPES = frozenset(
    {"application/json", "application/vnd.oai.openapi+json", "application/vnd.aai.asyncapi+json", "text/json"}
)
_YAML_TYPES = frozenset(
    {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
        "application/vnd.oai.openapi",
        "application/vnd.aai.asyncapi",
        "application/vnd.aai.asyncapi+yaml",
    }
)

#: An OpenAPI provider contract (PactFlow's ``contractType: oas``), compared with HTTP pacts.
CONTRACT_TYPE_OAS = "oas"
#: An AsyncAPI provider contract (PFX-3.6), compared with message pacts.
CONTRACT_TYPE_ASYNCAPI = "asyncapi"
#: The contract types the endpoint takes.
CONTRACT_TYPES = (CONTRACT_TYPE_OAS, CONTRACT_TYPE_ASYNCAPI)

#: AsyncAPI 3 operation actions.
_ASYNCAPI_ACTIONS = ("send", "receive")
#: The most local ``$ref`` problems the AsyncAPI check looks at before refusing.
_MAX_REF_WALK = 200_000

#: OpenAPI operation keys of a path item.
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace", "query")

#: Most meta-schema errors named in one refusal; the count says how many there were in all.
_MAX_REPORTED_ERRORS = 5


class ProviderContractError(ValueError):
    """A provider-contract refusal carrying a stable machine code and, when known, a location.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        pointer: JSON Pointer to the offending place — in the OpenAPI document for
            ``provider-contract-invalid``, in the request body otherwise — or ``None`` when the
            refusal is not about one place.
    """

    def __init__(self, code: str, message: str, *, pointer: Optional[str] = None) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
            pointer: Where the problem is, as a JSON Pointer (``""`` is the root).
        """
        super().__init__(message)
        self.code = code
        self.pointer = pointer


def _escape(token: Any) -> str:
    """Escape one JSON Pointer token (RFC 6901)."""
    return str(token).replace("~", "~0").replace("/", "~1")


def _invalid(pointer: str, message: str, *, label: str = "the OpenAPI document") -> ProviderContractError:
    """Build a ``provider-contract-invalid`` refusal located at ``pointer`` inside the document."""
    where = pointer or "(document root)"
    return ProviderContractError(CODE_CONTRACT_INVALID, f"{label}: {where}: {message}", pointer=pointer)


# ---------------------------------------------------------------------------------------------
# Reading an OpenAPI document
# ---------------------------------------------------------------------------------------------


def _media_type(content_type: Optional[str]) -> str:
    """The bare, lowercased media type of a ``Content-Type`` value (``""`` when absent)."""
    return (content_type or "").split(";")[0].strip().lower()


def _to_json(value: Any, pointer: str) -> Any:
    """Turn a parsed YAML value into the JSON value it stands for, refusing what JSON cannot hold.

    Args:
        value: The parsed value.
        pointer: Its JSON Pointer, for a refusal.

    Returns:
        The value with every mapping key a string and every date as ISO-8601 text.

    Raises:
        ProviderContractError: ``provider-contract-invalid`` at a binary value, a non-finite number
            or a key that has no text form (a mapping or a list).
    """
    if isinstance(value, dict):
        converted: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, (dict, list, tuple, bytes)):
                raise _invalid(pointer, "a mapping key must be a string")
            if isinstance(key, bool):
                text = "true" if key else "false"
            elif key is None:
                text = "null"
            elif isinstance(key, (datetime.date, datetime.datetime)):
                text = key.isoformat()
            else:
                text = str(key)
            if text in converted:
                raise _invalid(pointer, f"the key '{text}' appears twice once read as text")
            converted[text] = _to_json(item, f"{pointer}/{_escape(text)}")
        return converted
    if isinstance(value, list):
        return [_to_json(item, f"{pointer}/{index}") for index, item in enumerate(value)]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        raise _invalid(pointer, "binary values cannot be part of an OpenAPI document")
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid(pointer, "a number must be finite (.nan and .inf are not JSON)")
    if isinstance(value, set):
        raise _invalid(pointer, "a YAML set cannot be part of an OpenAPI document")
    return value


def parse_openapi(raw: bytes, *, content_type: Optional[str], max_bytes: int) -> Tuple[Dict[str, Any], str]:
    """Parse the bytes of an OpenAPI document sent as JSON or YAML.

    Args:
        raw: The document as sent (UTF-8).
        content_type: Its declared media type. ``None`` sniffs: a document starting with ``{`` is
            JSON, anything else YAML (which also reads JSON).
        max_bytes: The largest document accepted.

    Returns:
        The parsed document, and the media type it was read as (the declared one, or
        ``application/json`` / ``application/yaml`` when sniffed).

    Raises:
        ProviderContractError: ``provider-contract-too-large`` past ``max_bytes``;
            ``provider-contract-unsupported`` (pointer ``/contentType``) for a media type that is
            neither JSON nor YAML; ``provider-contract-invalid`` when the bytes are not UTF-8, do
            not parse, break a resource limit, or are not a mapping.
    """
    if len(raw) > max_bytes:
        raise ProviderContractError(
            CODE_CONTRACT_TOO_LARGE, f"the OpenAPI document is {len(raw)} bytes; the limit is {max_bytes}"
        )
    declared = _media_type(content_type)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid("", f"the document is not UTF-8 text: {exc}") from exc
    if declared in _JSON_TYPES:
        source_format, read_as = "json", declared
    elif declared in _YAML_TYPES:
        source_format, read_as = "yaml", declared
    elif not declared:
        is_json = text.lstrip().startswith("{")
        source_format = "json" if is_json else "yaml"
        read_as = JSON_CONTENT_TYPE if is_json else "application/yaml"
    else:
        raise ProviderContractError(
            CODE_UNSUPPORTED,
            f"content type '{content_type}' is not supported; send the OpenAPI document as "
            f"application/json or application/yaml",
            pointer="/contentType",
        )
    result = safe_oas_parse(text, source_format)  # type: ignore[arg-type]
    if not result.ok:
        diagnostic = result.diagnostics[0]
        where = f" (line {diagnostic.line}, column {diagnostic.col})" if diagnostic.line else ""
        raise _invalid("", f"{diagnostic.message}{where} [{diagnostic.code}]")
    document = _to_json(result.document, "")
    if not isinstance(document, dict):
        raise _invalid("", "an OpenAPI document must be a mapping (a JSON object)")
    return document, read_as


def _operation_count(document: Mapping[str, Any]) -> int:
    """How many operations the document's ``paths`` declare."""
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return 0
    return sum(1 for item in paths.values() if isinstance(item, dict) for method in _HTTP_METHODS if method in item)


def validate_openapi_contract(document: Mapping[str, Any], *, label: str = "the OpenAPI document") -> str:
    """Check that a parsed document is an OpenAPI 3.x document a provider contract can be.

    Args:
        document: The parsed document.
        label: How refusals name the document (``the document rendered from ledger@1.4.0``).

    Returns:
        The ``openapi`` version it declares.

    Raises:
        ProviderContractError: ``provider-contract-invalid`` located at ``/swagger`` for Swagger
            2.0, at ``/asyncapi`` for AsyncAPI, at ``/openapi`` for a missing or non-3.x version,
            and at the first meta-schema error otherwise (the message names up to five, and how
            many there were).
    """
    if "swagger" in document:
        raise _invalid(
            "/swagger",
            f"Swagger {document.get('swagger')} is not supported; a provider contract is OpenAPI 3.0, 3.1 "
            f"or 3.2 (convert the document, or import it into Apiome and publish the version)",
            label=label,
        )
    if "asyncapi" in document:
        raise _invalid(
            "/asyncapi",
            "this is an AsyncAPI document, but the contract type is 'oas'; publish it with contractType "
            "'asyncapi' (or leave contractType out)",
            label=label,
        )
    version = document.get("openapi")
    if not isinstance(version, str) or not version.strip():
        raise _invalid(
            "/openapi", "an OpenAPI document declares its version in 'openapi' (3.0.x, 3.1.x or 3.2.x)", label=label
        )
    parts = version.strip().split(".")
    if len(parts) < 2 or parts[0] != "3" or parts[1] not in ("0", "1", "2"):
        raise _invalid(
            "/openapi",
            f"OpenAPI '{version}' is not supported; a provider contract is OpenAPI 3.0, 3.1 or 3.2",
            label=label,
        )
    errors = openapi_document_errors_at(document)
    if errors:
        first = errors[0]
        listed = "; ".join(
            f"{error['pointer'] or '(document root)'}: {error['message']}" for error in errors[:_MAX_REPORTED_ERRORS]
        )
        more = f" (and {len(errors) - _MAX_REPORTED_ERRORS} more)" if len(errors) > _MAX_REPORTED_ERRORS else ""
        raise ProviderContractError(
            CODE_CONTRACT_INVALID,
            f"{label} does not validate against the OpenAPI {parts[0]}.{parts[1]} schema "
            f"({len(errors)} error(s)): {listed}{more}",
            pointer=first["pointer"],
        )
    return version.strip()


def _local_ref_errors(document: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    """The first in-document ``$ref`` that names nothing, in document order.

    Args:
        document: The parsed document.

    Returns:
        ``(pointer of the $ref, its value)``, or ``None`` when every local reference resolves.
        References to other documents are not followed (and not refused).
    """
    stack: List[Tuple[str, Any]] = [("", document)]
    budget = _MAX_REF_WALK
    while stack and budget > 0:
        pointer, node = stack.pop()
        budget -= 1
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#"):
                target: Any = document
                for token in [part.replace("~1", "/").replace("~0", "~") for part in ref[1:].split("/")[1:]]:
                    if isinstance(target, dict) and token in target:
                        target = target[token]
                    elif isinstance(target, list) and token.isdigit() and int(token) < len(target):
                        target = target[int(token)]
                    else:
                        return f"{pointer}/$ref", ref
            for key in reversed(list(node)):
                if key not in ("examples", "example", "default", "const", "enum"):
                    stack.append((f"{pointer}/{_escape(key)}", node[key]))
        elif isinstance(node, list):
            stack.extend((f"{pointer}/{index}", item) for index, item in reversed(list(enumerate(node))))
    return None


def validate_asyncapi_contract(document: Mapping[str, Any], *, label: str = "the AsyncAPI document") -> str:
    """Check that a parsed document is an AsyncAPI document a provider contract can be — PFX-3.6.

    The check is structural, not the full AsyncAPI specification (that validator is the
    JavaScript ``@asyncapi/parser`` the import path runs): what the message comparison
    (:mod:`app.pact_asyncapi_compare`) reads must be there and be the right shape.

    Args:
        document: The parsed document.
        label: How refusals name the document.

    Returns:
        The ``asyncapi`` version it declares.

    Raises:
        ProviderContractError: ``provider-contract-invalid`` located at ``/openapi`` or
            ``/swagger`` for an HTTP document, ``/asyncapi`` for a missing or unsupported version,
            ``/info`` for missing title or version, ``/channels`` (or a channel, its messages, or
            an AsyncAPI 2 operation) that is not an object, ``/operations/…/action`` that is neither
            ``send`` nor ``receive``, and the first local ``$ref`` that names nothing.
    """
    for key in ("openapi", "swagger"):
        if key in document:
            raise _invalid(
                f"/{key}",
                "this is an HTTP API description, but the contract type is 'asyncapi'; publish it with "
                "contractType 'oas'",
                label=label,
            )
    version = document.get("asyncapi")
    if not isinstance(version, str) or not is_supported_asyncapi_version(version.strip()):
        raise _invalid(
            "/asyncapi",
            f"AsyncAPI '{version}' is not supported; an AsyncAPI provider contract declares 'asyncapi' 2.x or 3.x",
            label=label,
        )
    major = version.strip().split(".", 1)[0]
    info = document.get("info")
    if not isinstance(info, dict) or not all(isinstance(info.get(key), str) for key in ("title", "version")):
        raise _invalid("/info", "an AsyncAPI document carries 'info' with a 'title' and a 'version'", label=label)
    channels = document.get("channels", {} if major == "3" else None)
    if not isinstance(channels, dict):
        raise _invalid("/channels", "'channels' must be an object of channels", label=label)
    for name, channel in channels.items():
        where = f"/channels/{_escape(name)}"
        if not isinstance(channel, dict):
            raise _invalid(where, "a channel must be an object", label=label)
        if major == "3" and "messages" in channel and not isinstance(channel["messages"], dict):
            raise _invalid(f"{where}/messages", "a channel's 'messages' must be an object of messages", label=label)
        if major == "2":
            for verb in ("publish", "subscribe"):
                if verb in channel and not isinstance(channel[verb], dict):
                    raise _invalid(f"{where}/{verb}", f"'{verb}' must be an operation object", label=label)
    if major == "3":
        operations = document.get("operations", {})
        if not isinstance(operations, dict):
            raise _invalid("/operations", "'operations' must be an object of operations", label=label)
        for name, operation in operations.items():
            where = f"/operations/{_escape(name)}"
            if not isinstance(operation, dict):
                raise _invalid(where, "an operation must be an object", label=label)
            if "$ref" not in operation and operation.get("action") not in _ASYNCAPI_ACTIONS:
                raise _invalid(f"{where}/action", "an operation's 'action' is 'send' or 'receive'", label=label)
    broken = _local_ref_errors(document)
    if broken is not None:
        raise _invalid(broken[0], f"the reference '{broken[1]}' names nothing in the document", label=label)
    return version.strip()


def contract_type_of(document: Mapping[str, Any]) -> str:
    """The contract type of a parsed (or stored) document: ``asyncapi`` or ``oas``.

    Args:
        document: The document.

    Returns:
        :data:`CONTRACT_TYPE_ASYNCAPI` when it declares ``asyncapi``, else :data:`CONTRACT_TYPE_OAS`.
    """
    return CONTRACT_TYPE_ASYNCAPI if isinstance(document, Mapping) and "asyncapi" in document else CONTRACT_TYPE_OAS


def validate_contract(
    document: Mapping[str, Any], contract_type: Optional[str], *, label: Optional[str] = None
) -> Tuple[str, str]:
    """Validate a document as the contract type the request names, or the one it declares.

    Args:
        document: The parsed document.
        contract_type: ``oas``, ``asyncapi`` or ``None`` (read from the document: ``asyncapi``
            when it declares one, else ``oas``).
        label: How refusals name the document; a default per type when ``None``.

    Returns:
        ``(contract type, version)`` — the version is ``openapi`` or ``asyncapi``.

    Raises:
        ProviderContractError: ``provider-contract-invalid`` (:func:`validate_openapi_contract`,
            :func:`validate_asyncapi_contract`).
    """
    kind = (contract_type or "").strip().lower() or contract_type_of(document)
    if kind == CONTRACT_TYPE_ASYNCAPI:
        return kind, validate_asyncapi_contract(document, label=label or "the AsyncAPI document")
    return CONTRACT_TYPE_OAS, validate_openapi_contract(document, label=label or "the OpenAPI document")


def _message_count(document: Mapping[str, Any]) -> int:
    """How many messages an AsyncAPI document's channels declare."""
    return len(AsyncApiIndex(document).messages)


def provider_contract_sha(document: Mapping[str, Any]) -> str:
    """The content address of a provider contract: SHA-256 of its canonical JSON.

    Args:
        document: The parsed OpenAPI document.

    Returns:
        64 lowercase hex characters, equal for two documents that are the same JSON value whatever
        their key order or serialization.
    """
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------
# The publish request
# ---------------------------------------------------------------------------------------------


class SelfVerificationResults(BaseModel):
    """The results of checking the provider against its own contract, sent with it.

    The wire names are PactFlow's (camelCase), plus ``providerVerificationReportId`` for an Apiome
    report. What they prove is read by :mod:`app.provider_contract_evidence` (PFX-2.4, #6928):
    either a third-party report in ``content``, or an Apiome provider-verification report
    (CTG-4.3) named by its id — not both.

    Attributes:
        success: Whether the provider passed its self-verification. Required with ``content`` or
            without a report; with ``providerVerificationReportId`` the report says, and a flag
            that disagrees with it fails the evidence.
        content: The verifier's report, base64-encoded.
        content_type: ``contentType`` — the report's media type (``application/xml`` for JUnit,
            ``application/json`` for Newman, ``application/x-ndjson`` for Schemathesis NDJSON,
            ``text/plain`` for a report Apiome stores without reading).
        verifier: The tool that produced it (``schemathesis``, ``dredd``, ``newman``).
        verifier_version: ``verifierVersion`` — that tool's version.
        report_id: ``providerVerificationReportId`` — an Apiome provider-verification report of
            this workspace.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    success: Optional[bool] = Field(
        default=None,
        description="Whether the provider passed its self-verification. Optional with providerVerificationReportId.",
    )
    content: Optional[str] = Field(default=None, description="The verifier's report, base64-encoded.")
    content_type: Optional[str] = Field(default=None, alias="contentType", description="The report's media type.")
    verifier: Optional[str] = Field(default=None, description="The tool that produced the report.")
    verifier_version: Optional[str] = Field(
        default=None, alias="verifierVersion", description="The version of that tool."
    )
    report_id: Optional[str] = Field(
        default=None,
        alias="providerVerificationReportId",
        description="An Apiome provider-verification report (CTG-4.3) of this workspace, instead of content.",
    )


class PublishProviderContractRequest(BaseModel):
    """A provider contract to publish for one provider version.

    Send the document inline (``content``, PactFlow's shape) **or** name an Apiome version to
    render it from (``apiomeVersion``) — exactly one.

    Attributes:
        content: The OpenAPI or AsyncAPI document, base64-encoded.
        contract_type: ``contractType`` — ``oas`` or ``asyncapi`` (PFX-3.6); read from the
            document when omitted.
        content_type: ``contentType`` — how ``content`` is encoded (JSON or YAML).
        apiome_version: ``apiomeVersion`` — ``<project>@<version>``, or just ``<version>`` when the
            provider is bound to a project. ``latest`` names the project's newest version.
        branch: The provider's repository branch the version was built from.
        tags: Tags to put on the provider version.
        build_url: ``buildUrl`` — http(s) URL of the CI build.
        verification_results: ``verificationResults`` — the provider's self-verification.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    content: Optional[str] = Field(default=None, description="The OpenAPI or AsyncAPI document, base64-encoded.")
    contract_type: Optional[str] = Field(
        default=None,
        alias="contractType",
        description="`oas` or `asyncapi`; read from the document when omitted.",
    )
    content_type: Optional[str] = Field(
        default=None,
        alias="contentType",
        description="`application/json` or `application/yaml`; sniffed from the content when omitted.",
    )
    apiome_version: Optional[str] = Field(
        default=None,
        alias="apiomeVersion",
        description="`<project>@<version>` (or `<version>` for a bound provider); `latest` is the newest version.",
        examples=["ledger-api@1.4.0"],
    )
    branch: Optional[str] = Field(default=None, description="The repository branch the version was built from.")
    tags: List[str] = Field(default_factory=list, description="Tags to put on the version (at most 50).")
    build_url: Optional[str] = Field(default=None, alias="buildUrl", description="http(s) URL of the CI build.")
    verification_results: Optional[SelfVerificationResults] = Field(
        default=None, alias="verificationResults", description="The provider's self-verification results."
    )


@dataclass(frozen=True)
class ApiomeReference:
    """An Apiome version a contract is rendered from, as the request names it.

    Attributes:
        project: The project slug or id; ``None`` when the request left it to the provider's binding.
        version: The version label, revision id, or ``latest``.
    """

    project: Optional[str]
    version: str


def parse_apiome_reference(value: str) -> ApiomeReference:
    """Read ``apiomeVersion``: ``<project>@<version>`` or a bare ``<version>``.

    Args:
        value: The field as sent.

    Returns:
        The reference.

    Raises:
        ProviderContractError: ``provider-contract-request-invalid`` (pointer ``/apiomeVersion``)
            when it is empty or either side of the ``@`` is.
    """
    text = (value or "").strip()
    project: Optional[str] = None
    version = text
    if "@" in text:
        project, _, version = (part.strip() for part in text.partition("@"))
        if not project:
            raise ProviderContractError(
                CODE_REQUEST_INVALID,
                f"apiomeVersion '{value}' names no project before '@'; send '<project>@<version>' or just '<version>'",
                pointer="/apiomeVersion",
            )
    if not version:
        raise ProviderContractError(
            CODE_REQUEST_INVALID,
            f"apiomeVersion '{value}' names no version; send '<project>@<version>' "
            f"(a label, a revision id or 'latest')",
            pointer="/apiomeVersion",
        )
    return ApiomeReference(project=project, version=version)


def decode_base64(value: str, pointer: str, what: str) -> bytes:
    """Decode a base64 field of the request.

    Args:
        value: The field as sent.
        pointer: Its JSON Pointer in the request body.
        what: How the message names it.

    Returns:
        The decoded bytes.

    Raises:
        ProviderContractError: ``provider-contract-request-invalid`` at ``pointer``.
    """
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderContractError(
            CODE_REQUEST_INVALID, f"{what} is not valid base64: {exc}", pointer=pointer
        ) from exc


def check_request(body: PublishProviderContractRequest) -> None:
    """Check the parts of a publish request that do not depend on the document.

    Args:
        body: The parsed request.

    Raises:
        ProviderContractError: ``provider-contract-unsupported`` for a contract type other than
            ``oas`` and ``asyncapi``, and for ``asyncapi`` with ``apiomeVersion`` (an AsyncAPI contract
            is sent inline); ``provider-contract-request-invalid`` when the request sends both or neither of
            ``content`` and ``apiomeVersion``, a ``contentType`` other than JSON with
            ``apiomeVersion``, both a report and a report id in ``verificationResults``, a report id
            that is not a UUID, or no ``success`` without a report id.
    """
    kind = (body.contract_type or "").strip().lower()
    if body.contract_type is not None and kind not in CONTRACT_TYPES:
        raise ProviderContractError(
            CODE_UNSUPPORTED,
            f"contractType '{body.contract_type}' is not supported; a provider contract is 'oas' or 'asyncapi'",
            pointer="/contractType",
        )
    has_content = body.content is not None
    has_reference = body.apiome_version is not None
    if kind == CONTRACT_TYPE_ASYNCAPI and has_reference:
        raise ProviderContractError(
            CODE_UNSUPPORTED,
            "an AsyncAPI provider contract cannot be rendered from an Apiome version yet; send the AsyncAPI "
            "document inline in 'content'",
            pointer="/apiomeVersion",
        )
    if has_content == has_reference:
        raise ProviderContractError(
            CODE_REQUEST_INVALID,
            "send the OpenAPI document in 'content' or name an Apiome version in 'apiomeVersion' — exactly one",
            pointer="",
        )
    if has_reference and body.content_type and _media_type(body.content_type) not in _JSON_TYPES:
        raise ProviderContractError(
            CODE_REQUEST_INVALID,
            f"contentType '{body.content_type}' describes 'content'; a contract rendered from an Apiome "
            f"version is always application/json — leave contentType out",
            pointer="/contentType",
        )
    results = body.verification_results
    if results is not None:
        if results.report_id is not None and results.content is not None:
            raise ProviderContractError(
                CODE_REQUEST_INVALID,
                "send the self-verification report in 'content' or name an Apiome report in "
                "'providerVerificationReportId' — not both",
                pointer="/verificationResults",
            )
        if results.report_id is not None and not _is_uuid(results.report_id):
            raise ProviderContractError(
                CODE_REQUEST_INVALID,
                "providerVerificationReportId must be a report id (a UUID)",
                pointer="/verificationResults/providerVerificationReportId",
            )
        if results.report_id is None and results.success is None:
            raise ProviderContractError(
                CODE_REQUEST_INVALID,
                "verificationResults.success is required unless providerVerificationReportId names an Apiome report",
                pointer="/verificationResults/success",
            )


def stored_verification_results(
    results: Optional[SelfVerificationResults], evidence: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """The self-verification results as they are stored: what was sent, its digest and its evidence.

    Args:
        results: The request's ``verificationResults``, if any.
        evidence: What :mod:`app.provider_contract_evidence` read from them (``Evidence.to_dict()``).

    Returns:
        ``None`` without results; otherwise ``success``, ``verifier``, ``verifierVersion``,
        ``contentType``, ``content`` (still base64) and, with content, ``contentSha256`` and
        ``contentBytes`` of the decoded report; ``providerVerificationReportId`` when one was named;
        and ``evidence``.

    Raises:
        ProviderContractError: ``provider-contract-request-invalid`` (pointer
            ``/verificationResults/content``) when the report is not base64.
    """
    if results is None:
        return None
    stored: Dict[str, Any] = {
        "success": results.success,
        "verifier": results.verifier,
        "verifierVersion": results.verifier_version,
        "contentType": results.content_type,
        "content": results.content,
    }
    if results.content is not None:
        report = decode_base64(results.content, "/verificationResults/content", "the verification results content")
        stored["contentSha256"] = hashlib.sha256(report).hexdigest()
        stored["contentBytes"] = len(report)
    if results.report_id is not None:
        stored["providerVerificationReportId"] = results.report_id.strip().lower()
    stored["evidence"] = dict(evidence)
    return stored


def sent_verification_results(stored: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The part of stored results the publisher sent, without what Apiome read from them.

    Two publishes of one provider version are "the same" when they sent the same thing; the
    ``evidence`` Apiome derives is left out so a publication stored before PFX-2.4 (without it)
    still matches a republish of the same results.

    Args:
        stored: Stored ``verification_results``, or ``None``.

    Returns:
        A copy without ``evidence``, or ``None``.
    """
    if stored is None:
        return None
    return {key: value for key, value in stored.items() if key != "evidence"}


# ---------------------------------------------------------------------------------------------
# A contract ready to store
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderContractToStore:
    """One validated provider contract, ready to be written.

    Attributes:
        document: The OpenAPI or AsyncAPI document.
        sha: Its content address (:func:`provider_contract_sha`).
        oas_version: The ``openapi`` version it declares — or, for an AsyncAPI contract, the
            ``asyncapi`` version (the column holds the document's version either way).
        operation_count: How many operations it declares (for AsyncAPI: how many messages).
        content_type: The media type it was sent (or rendered) as.
        source: :data:`SOURCE_INLINE` or :data:`SOURCE_APIOME`.
        source_project_id: For an Apiome source, the project's id.
        source_version_id: For an Apiome source, the revision's id.
        source_project_slug: For an Apiome source, the project's slug.
        source_version_label: For an Apiome source, the version's label.
        verification_results: The self-verification results as stored, or ``None``.
    """

    document: Dict[str, Any]
    sha: str
    oas_version: str
    operation_count: int
    content_type: str
    source: str = SOURCE_INLINE
    source_project_id: Optional[str] = None
    source_version_id: Optional[str] = None
    source_project_slug: Optional[str] = None
    source_version_label: Optional[str] = None
    verification_results: Optional[Dict[str, Any]] = None


def prepare_contract(
    document: Dict[str, Any],
    *,
    content_type: str,
    contract_type: Optional[str] = None,
    verification_results: Optional[Dict[str, Any]] = None,
    source: str = SOURCE_INLINE,
    source_project_id: Optional[str] = None,
    source_version_id: Optional[str] = None,
    source_project_slug: Optional[str] = None,
    source_version_label: Optional[str] = None,
) -> ProviderContractToStore:
    """Validate a parsed document and address it.

    Args:
        document: The parsed OpenAPI or AsyncAPI document.
        content_type: The media type it was sent or rendered as.
        contract_type: ``oas``, ``asyncapi``, or ``None`` to read it from the document.
        verification_results: The self-verification results as stored.
        source: Where it came from.
        source_project_id: For an Apiome source, the project's id.
        source_version_id: For an Apiome source, the revision's id.
        source_project_slug: For an Apiome source, the project's slug.
        source_version_label: For an Apiome source, the version's label.

    Returns:
        The contract, ready for :func:`app.provider_contract_store.publish_provider_contract`.

    Raises:
        ProviderContractError: ``provider-contract-invalid`` with a pointer
            (:func:`validate_contract`).
    """
    label = (
        f"the document rendered from {source_project_slug}@{source_version_label}"
        if source == SOURCE_APIOME
        else None
    )
    kind, version = validate_contract(document, contract_type, label=label)
    return ProviderContractToStore(
        document=document,
        sha=provider_contract_sha(document),
        oas_version=version,
        operation_count=_message_count(document) if kind == CONTRACT_TYPE_ASYNCAPI else _operation_count(document),
        content_type=content_type,
        source=source,
        source_project_id=source_project_id,
        source_version_id=source_version_id,
        source_project_slug=source_project_slug,
        source_version_label=source_version_label,
        verification_results=verification_results,
    )


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class ProviderContractRecord(BaseModel):
    """A stored provider contract, as one provider version published it.

    Attributes:
        provider_slug: The provider's handle.
        provider_name: The provider's display name.
        provider_version: The provider version number that published it.
        sha: The content address of the document.
        content: The OpenAPI or AsyncAPI document.
        oas_version: The ``openapi`` version it declares (the ``asyncapi`` version for an
            AsyncAPI contract).
        operation_count: How many operations it declares (messages, for AsyncAPI).
        content_type: The media type it was sent or rendered as.
        source: ``inline`` or ``apiome``.
        source_project_slug: For an Apiome source, the project's slug at publication.
        source_version_label: For an Apiome source, the version's label at publication.
        source_project_id: For an Apiome source, the project's id (``None`` once it is deleted).
        source_version_id: For an Apiome source, the revision's id (``None`` once it is deleted).
        verification_results: The self-verification results as stored, or ``None``.
        created_at: When the provider version published it.
    """

    model_config = ConfigDict(extra="forbid")

    provider_slug: str
    provider_name: str
    provider_version: str
    sha: str
    content: Dict[str, Any]
    oas_version: str
    operation_count: int = 0
    content_type: str = JSON_CONTENT_TYPE
    source: str = SOURCE_INLINE
    source_project_slug: Optional[str] = None
    source_version_label: Optional[str] = None
    source_project_id: Optional[str] = None
    source_version_id: Optional[str] = None
    verification_results: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

    @property
    def contract_type(self) -> str:
        """``asyncapi`` for an AsyncAPI document, else ``oas`` (read from the stored content)."""
        return contract_type_of(self.content)


class PublishedProviderContract(BaseModel):
    """The outcome of publishing a provider contract.

    Attributes:
        contract: The contract as stored.
        created: Whether this provider version had no contract before (``False``: the same
            contract was published again and nothing changed).
        new_content: Whether the document was new for this provider; ``False`` when an earlier
            provider version already published the same one.
        version_created: Whether the request recorded the provider version.
    """

    model_config = ConfigDict(extra="forbid")

    contract: ProviderContractRecord
    created: bool
    new_content: bool = False
    version_created: bool = False


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _json_column(value: Any) -> Any:
    """A JSONB column as Python: psycopg2 returns it parsed, a stand-in may return text."""
    return json.loads(value) if isinstance(value, str) else value


def _optional_text(value: Any) -> Optional[str]:
    """A nullable column as text."""
    return None if value is None else str(value)


def contract_record_from_row(row: Mapping[str, Any]) -> ProviderContractRecord:
    """Adapt a contract row, as :mod:`app.provider_contract_store` selects it, into its record.

    Args:
        row: The joined ``provider_contract_publication`` / ``provider_contract`` row.

    Returns:
        The record.
    """
    content = _json_column(row.get("content"))
    results = _json_column(row.get("verification_results"))
    return ProviderContractRecord(
        provider_slug=str(row.get("provider_slug") or ""),
        provider_name=str(row.get("provider_name") or ""),
        provider_version=str(row.get("provider_version") or ""),
        sha=str(row.get("sha") or "").strip(),
        content=content if isinstance(content, dict) else {},
        oas_version=str(row.get("oas_version") or ""),
        operation_count=int(row.get("operation_count") or 0),
        content_type=str(row.get("content_type") or JSON_CONTENT_TYPE),
        source=str(row.get("source") or SOURCE_INLINE),
        source_project_slug=_optional_text(row.get("source_project_slug")),
        source_version_label=_optional_text(row.get("source_version_label")),
        source_project_id=_optional_text(row.get("source_project_id")),
        source_version_id=_optional_text(row.get("source_version_id")),
        verification_results=results if isinstance(results, dict) else None,
        created_at=_iso(row.get("created_at")),
    )
