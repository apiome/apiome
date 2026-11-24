"""What a published pact is, and what a valid one looks like — PFX-1.2 (#6915).

:mod:`app.pacticipant` names the applications; this module describes the pacts they publish.
:mod:`app.pact_publication_store` is the only place one is read or written (apiome-db V433) and
:mod:`app.pact_broker_routes` is the Pact Broker–compatible REST surface.

**A pact is accepted as it is.** Pact specification 1.x to 4.x documents are stored as published:
no field is dropped, renamed or rewritten. What is checked is only what makes the document a pact
at all — it is a JSON object, it carries an ``interactions`` or a ``messages`` array, each entry is
an object, and an HTTP interaction has a request with a method and a response. Every refusal names
the place in the document (a JSON Pointer) so the publisher can find it.

**A pact version is addressed by its content.** :func:`pact_content_sha` is the SHA-256 of the
part of the document a verification depends on — the interactions, the messages and the declared
specification version — serialized with sorted keys. The ``metadata`` a Pact library stamps on
every file (its own name and version) is left out, so upgrading the library does not turn an
unchanged pact into a new one, and the same pact published for ten consumer versions is one
``pact_version`` with one thing for the provider to verify. The order of interactions is part of
the content.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .pact_contract_import import (
    pact_consumer_name,
    pact_provider_name,
    pact_specification_version,
)
from .pacticipant import slugify_pacticipant_name

__all__ = [
    "CODE_PACT_CONFLICT",
    "CODE_PACT_INVALID",
    "CODE_PACT_NOT_FOUND",
    "CODE_PACT_TOO_LARGE",
    "CODE_PUBLISH_INVALID",
    "CODE_PUBLISH_RATE_LIMITED",
    "CODE_PUBLISH_UNSUPPORTED",
    "MAX_CONTRACTS_PER_REQUEST",
    "ContractToPublish",
    "PactPublicationError",
    "PactRecord",
    "PactToStore",
    "PublishContractsRequest",
    "PublishedPact",
    "decode_contract_content",
    "pact_content_sha",
    "pact_record_from_row",
    "parse_pact",
    "prepare_pact",
    "validate_pact_document",
]

# Stable refusal codes. A client branches on these, never on the message.
CODE_PACT_INVALID = "pact-invalid"
CODE_PACT_TOO_LARGE = "pact-too-large"
CODE_PACT_CONFLICT = "pact-content-conflict"
CODE_PACT_NOT_FOUND = "pact-not-found"
CODE_PUBLISH_INVALID = "pact-publish-invalid"
CODE_PUBLISH_UNSUPPORTED = "pact-publish-unsupported"
CODE_PUBLISH_RATE_LIMITED = "pact-publish-rate-limited"

#: Most contracts one ``contracts/publish`` request may carry.
MAX_CONTRACTS_PER_REQUEST = 100

#: v4 interaction types that carry an HTTP request and response. An interaction of any other type
#: (a message, a plugin's own) is accepted without looking inside it.
_HTTP_INTERACTION_TYPES = ("synchronous/http", "http")


class PactPublicationError(ValueError):
    """A publication refusal carrying a stable machine code and, when known, a location.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        pointer: JSON Pointer to the offending place — in the Pact document for ``pact-invalid``,
            in the request body for ``pact-publish-*`` — or ``None`` when the refusal is not about
            one place.
    """

    def __init__(self, code: str, message: str, *, pointer: Optional[str] = None) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
            pointer: Where the problem is, as a JSON Pointer (``""`` is the document root).
        """
        super().__init__(message)
        self.code = code
        self.pointer = pointer


# ---------------------------------------------------------------------------------------------
# Reading and validating a Pact document
# ---------------------------------------------------------------------------------------------


def parse_pact(raw: bytes, *, max_bytes: int) -> Dict[str, Any]:
    """Parse the bytes of a Pact document.

    Args:
        raw: The document as sent (UTF-8 JSON).
        max_bytes: The largest document accepted.

    Returns:
        The parsed document.

    Raises:
        PactPublicationError: ``pact-too-large`` past ``max_bytes``; ``pact-invalid`` (pointer
            ``""``) when the bytes are not UTF-8 JSON or the JSON is not an object.
    """
    if len(raw) > max_bytes:
        raise PactPublicationError(
            CODE_PACT_TOO_LARGE, f"the Pact document is {len(raw)} bytes; the limit is {max_bytes}"
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PactPublicationError(
            CODE_PACT_INVALID, f"the Pact document is not valid JSON: {exc}", pointer=""
        ) from exc
    except RecursionError as exc:
        raise PactPublicationError(
            CODE_PACT_INVALID, "the Pact document is nested too deeply to read", pointer=""
        ) from exc
    if not isinstance(document, dict):
        raise PactPublicationError(CODE_PACT_INVALID, "a Pact document must be a JSON object", pointer="")
    return document


def _invalid(pointer: str, message: str) -> PactPublicationError:
    """Build a ``pact-invalid`` refusal located at ``pointer``."""
    return PactPublicationError(CODE_PACT_INVALID, f"{pointer or '(document root)'}: {message}", pointer=pointer)


def _check_named(document: Mapping[str, Any], role: str) -> None:
    """Check the ``consumer`` or ``provider`` block, when the document carries one.

    Args:
        document: The parsed Pact document.
        role: ``consumer`` or ``provider``.

    Raises:
        PactPublicationError: ``pact-invalid`` when the block is not an object with a text name.
    """
    if role not in document:
        return
    block = document[role]
    if not isinstance(block, dict):
        raise _invalid(f"/{role}", f"'{role}' must be an object with a 'name'")
    name = block.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _invalid(f"/{role}/name", f"the {role} name must be a non-empty string")


def _check_http_interaction(interaction: Mapping[str, Any], pointer: str) -> None:
    """Check the request and response of one HTTP interaction.

    Args:
        interaction: The interaction.
        pointer: Its JSON Pointer.

    Raises:
        PactPublicationError: ``pact-invalid`` at the first malformed member.
    """
    request = interaction.get("request")
    if not isinstance(request, dict):
        raise _invalid(f"{pointer}/request", "an HTTP interaction needs a 'request' object")
    method = request.get("method")
    if not isinstance(method, str) or not method.strip():
        raise _invalid(f"{pointer}/request/method", "the request method must be a non-empty string")
    if "path" in request and not isinstance(request["path"], str):
        raise _invalid(f"{pointer}/request/path", "the request path must be a string")
    response = interaction.get("response")
    if not isinstance(response, dict):
        raise _invalid(f"{pointer}/response", "an HTTP interaction needs a 'response' object")
    status = response.get("status")
    if status is not None and (isinstance(status, bool) or not isinstance(status, int)):
        raise _invalid(f"{pointer}/response/status", "the response status must be an integer")


def validate_pact_document(document: Mapping[str, Any]) -> int:
    """Check that a parsed document is a pact, and count what it carries.

    Args:
        document: The parsed Pact document.

    Returns:
        How many interactions and messages it carries.

    Raises:
        PactPublicationError: ``pact-invalid`` with the JSON Pointer of the first problem.
    """
    _check_named(document, "consumer")
    _check_named(document, "provider")
    if "metadata" in document and not isinstance(document["metadata"], dict):
        raise _invalid("/metadata", "'metadata' must be an object")
    if "interactions" not in document and "messages" not in document:
        raise _invalid("", "a Pact document carries an 'interactions' or a 'messages' array; this one has neither")

    count = 0
    for key in ("interactions", "messages"):
        if key not in document:
            continue
        entries = document[key]
        if not isinstance(entries, list):
            raise _invalid(f"/{key}", f"'{key}' must be an array")
        for index, entry in enumerate(entries):
            pointer = f"/{key}/{index}"
            if not isinstance(entry, dict):
                raise _invalid(pointer, "each entry must be an object")
            kind = entry.get("type")
            is_http = key == "interactions" and (
                kind is None or (isinstance(kind, str) and kind.strip().lower() in _HTTP_INTERACTION_TYPES)
            )
            if is_http:
                _check_http_interaction(entry, pointer)
        count += len(entries)
    return count


def pact_content_sha(document: Mapping[str, Any]) -> str:
    """The content address of a pact: SHA-256 of what a verification depends on.

    Args:
        document: The parsed Pact document.

    Returns:
        64 lowercase hex characters. Two documents with the same interactions, messages and
        specification version have the same value, whatever their ``metadata`` or key order.
    """
    canonical: Dict[str, Any] = {key: document[key] for key in ("interactions", "messages") if key in document}
    specification = pact_specification_version(document)
    if specification:
        canonical["pactSpecificationVersion"] = specification
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PactToStore:
    """One validated pact, ready to be written.

    Attributes:
        consumer_name: The consumer, named as the document names it (else as the request does).
        provider_name: The provider it is with, named the same way.
        document: The Pact document, as published.
        sha: Its content address (:func:`pact_content_sha`).
        specification_version: The Pact specification version it declares, if any.
        interaction_count: How many interactions and messages it carries.
    """

    consumer_name: str
    provider_name: str
    document: Dict[str, Any]
    sha: str
    specification_version: Optional[str]
    interaction_count: int


def _same_pacticipant(left: str, right: str) -> bool:
    """Whether two names are the same pacticipant (they reduce to the same handle)."""
    return slugify_pacticipant_name(left) == slugify_pacticipant_name(right)


def prepare_pact(raw: bytes, *, consumer_name: str, provider_name: str, max_bytes: int) -> PactToStore:
    """Parse and validate a Pact document published for a named consumer and provider.

    Args:
        raw: The document as sent.
        consumer_name: The consumer the request names (URL or request body).
        provider_name: The provider the request names.
        max_bytes: The largest document accepted.

    Returns:
        The pact, ready for :func:`app.pact_publication_store.publish_pacts`.

    Raises:
        PactPublicationError: ``pact-too-large``, or ``pact-invalid`` with a pointer — including
            when the document names a different consumer or provider than the request does.
    """
    document = parse_pact(raw, max_bytes=max_bytes)
    count = validate_pact_document(document)
    names = {"consumer": consumer_name, "provider": provider_name}
    for role, declared in (
        ("consumer", pact_consumer_name(document)),
        ("provider", pact_provider_name(document)),
    ):
        if not declared:
            continue
        if not _same_pacticipant(declared, names[role]):
            raise _invalid(
                f"/{role}/name",
                f"the document names the {role} '{declared}' but the request names '{names[role]}'",
            )
        # A URL carries a handle (billing-service); the document carries the name people read.
        names[role] = declared
    return PactToStore(
        consumer_name=names["consumer"],
        provider_name=names["provider"],
        document=document,
        sha=pact_content_sha(document),
        specification_version=pact_specification_version(document),
        interaction_count=count,
    )


# ---------------------------------------------------------------------------------------------
# The bulk publish request (Pact Broker ``pb:publish-contracts``)
# ---------------------------------------------------------------------------------------------


class ContractToPublish(BaseModel):
    """One contract of a bulk publish request. The wire names are the Pact Broker's (camelCase).

    Attributes:
        consumer_name: ``consumerName`` — the consumer; must be the request's ``pacticipantName``.
        provider_name: ``providerName`` — the provider the pact is with.
        specification: Always ``pact`` here.
        content_type: ``contentType`` — always ``application/json`` here.
        content: The Pact document, base64-encoded.
        on_conflict: ``onConflict`` — ``overwrite`` (default) or ``merge``; ``merge`` is not supported.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    consumer_name: str = Field(
        alias="consumerName", description="The consumer; must be the request's `pacticipantName`."
    )
    provider_name: str = Field(alias="providerName", description="The provider the pact is with.")
    specification: str = Field(default="pact", description="The kind of contract. Only `pact` is accepted.")
    content_type: str = Field(
        default="application/json", alias="contentType", description="Only `application/json` is accepted."
    )
    content: str = Field(description="The Pact document, base64-encoded.")
    on_conflict: Optional[str] = Field(
        default=None,
        alias="onConflict",
        description="`overwrite` (the default). `merge` is not supported and is refused.",
    )


class PublishContractsRequest(BaseModel):
    """A bulk publish: one consumer version and the pacts it carries, in the Pact Broker's shape.

    Attributes:
        pacticipant_name: ``pacticipantName`` — the consumer publishing.
        pacticipant_version_number: ``pacticipantVersionNumber`` — its application version (a
            commit SHA, a semantic version).
        tags: Tags to put on the version.
        branch: The repository branch the version was built from.
        build_url: ``buildUrl`` — http(s) URL of the CI build.
        contracts: The pacts, one per provider.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    pacticipant_name: str = Field(
        alias="pacticipantName", description="The consumer publishing.", examples=["Billing Service"]
    )
    pacticipant_version_number: str = Field(
        alias="pacticipantVersionNumber",
        description="Its application version, as the build reports it.",
        examples=["2f4c1a9"],
    )
    tags: List[str] = Field(default_factory=list, description="Tags to put on the version (at most 50).")
    branch: Optional[str] = Field(default=None, description="The repository branch the version was built from.")
    build_url: Optional[str] = Field(default=None, alias="buildUrl", description="http(s) URL of the CI build.")
    contracts: List[ContractToPublish] = Field(description="The pacts, one per provider (1 to 100).")


def decode_contract_content(contract: ContractToPublish, index: int) -> bytes:
    """Check one contract of a bulk publish and return the bytes of its Pact document.

    Args:
        contract: The contract.
        index: Its position in ``contracts``, for the pointer.

    Returns:
        The decoded document.

    Raises:
        PactPublicationError: ``pact-publish-unsupported`` for a specification, content type or
            conflict mode this endpoint does not take; ``pact-publish-invalid`` when ``content`` is
            not base64. The pointer names the field in the request body.
    """
    base = f"/contracts/{index}"
    if contract.specification.strip().lower() != "pact":
        raise PactPublicationError(
            CODE_PUBLISH_UNSUPPORTED,
            f"specification '{contract.specification}' is not supported here; only 'pact' is",
            pointer=f"{base}/specification",
        )
    if contract.content_type.split(";")[0].strip().lower() != "application/json":
        raise PactPublicationError(
            CODE_PUBLISH_UNSUPPORTED,
            f"content type '{contract.content_type}' is not supported; a pact is 'application/json'",
            pointer=f"{base}/contentType",
        )
    if (contract.on_conflict or "overwrite").strip().lower() != "overwrite":
        raise PactPublicationError(
            CODE_PUBLISH_UNSUPPORTED,
            f"onConflict '{contract.on_conflict}' is not supported; publish one complete pact per "
            f"consumer version and provider",
            pointer=f"{base}/onConflict",
        )
    try:
        return base64.b64decode(contract.content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PactPublicationError(
            CODE_PUBLISH_INVALID, f"the contract content is not valid base64: {exc}", pointer=f"{base}/content"
        ) from exc


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class PactRecord(BaseModel):
    """A stored pact, as one consumer version published it.

    Attributes:
        consumer_slug: The consumer's handle.
        consumer_name: The consumer's display name.
        provider_slug: The provider's handle.
        provider_name: The provider's display name.
        consumer_version: The consumer version number that published it.
        sha: The content address of the pact version.
        content: The Pact document, as published.
        specification_version: The Pact specification version it declares, if any.
        interaction_count: How many interactions and messages it carries.
        revision: 1, or more when the pact of this consumer version was replaced.
        created_at: When this consumer version first published a pact for the provider.
        updated_at: When that pact was last replaced.
    """

    model_config = ConfigDict(extra="forbid")

    consumer_slug: str
    consumer_name: str
    provider_slug: str
    provider_name: str
    consumer_version: str
    sha: str
    content: Dict[str, Any]
    specification_version: Optional[str] = None
    interaction_count: int = 0
    revision: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PublishedPact(BaseModel):
    """The outcome of publishing one pact.

    Attributes:
        pact: The pact as stored.
        created: Whether this consumer version had no pact for the provider before.
        replaced: Whether an existing pact of this consumer version was replaced by new content.
        new_content: Whether the content was new for this consumer and provider (a new pact
            version); false when an earlier consumer version already published the same pact.
    """

    model_config = ConfigDict(extra="forbid")

    pact: PactRecord
    created: bool
    replaced: bool = False
    new_content: bool = False


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def pact_record_from_row(row: Mapping[str, Any]) -> PactRecord:
    """Adapt a pact row, as :mod:`app.pact_publication_store` selects it, into its record.

    Args:
        row: The joined ``pact_publication`` / ``pact_version`` row.

    Returns:
        The record.
    """
    content = row.get("content")
    if isinstance(content, str):
        content = json.loads(content)
    return PactRecord(
        consumer_slug=str(row.get("consumer_slug") or ""),
        consumer_name=str(row.get("consumer_name") or ""),
        provider_slug=str(row.get("provider_slug") or ""),
        provider_name=str(row.get("provider_name") or ""),
        consumer_version=str(row.get("consumer_version") or ""),
        sha=str(row.get("sha") or "").strip(),
        content=content if isinstance(content, dict) else {},
        specification_version=row.get("specification_version"),
        interaction_count=int(row.get("interaction_count") or 0),
        revision=int(row.get("revision") or 1),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )
