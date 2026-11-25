"""Compare a consumer's message pact with a provider's AsyncAPI document — PFX-3.6 (#6936).

The message counterpart of :mod:`app.pact_oas_compare` (PFX-2.2). A Pact 3 message pact
(``messages``) or the ``Asynchronous/Messages`` interactions of a Pact 4 pact describe messages
the provider *produces* and the consumer *reads*. When the provider publishes its AsyncAPI 2.x or
3.x document as its provider contract (PFX-2.1), this module decides whether that document
satisfies every message of the pact — without running either side. Pure: two parsed documents
in, one :class:`~app.pact_oas_result.ComparisonResult` out; equal inputs give byte-equal output.

What is compared, per message
-----------------------------
1. **Channel and message** (``message.channel``) — the pact message is resolved onto a message
   the document declares (:mod:`app.pact_asyncapi_index`):

   * a destination in the message's metadata (:data:`CHANNEL_KEYS`: ``channel``, ``topic``,
     ``destination``, ``queue`` …) narrows it to the channels with that id or address
     (``{parameters}`` match any segment); one that names no channel fails;
   * the pact ``description`` equal (ignoring case) to a message's key, ``name``,
     ``messageId`` or ``title`` narrows it further;
   * only messages the provider **sends** can satisfy it; one it only receives fails;
   * when several remain, each is tried in document order and the first whose payload accepts
     the message wins (a fidelity note says so); when none does, the message is unknown.

2. **Content type** — the pact's ``contentType`` against the message's ``contentType`` (or the
   document's ``defaultContentType``).
3. **Metadata** — every metadata entry other than the destination and the content type against
   the message's ``headers`` schema. An entry the schema does not declare is a warning only:
   metadata also carries transport details (a Kafka key, a partition) no AsyncAPI ``headers``
   describes.
4. **Body** — the contents against the message's ``payload`` when it is JSON Schema (the AsyncAPI
   Schema Object, or a Multi Format Schema Object whose ``schemaFormat`` is JSON Schema), read
   like a response: ``required`` is not held against the example and undeclared properties are
   refused (:mod:`app.pact_oas_schema`). An Avro or Protobuf payload is not compared, and says so.
5. **Matching rules and generators** — exactly as PFX-2.2 maps them
   (:mod:`app.pact_matching_rules`); Pact 4 ``content`` rules are body rules, ``metadata`` rules
   are checked against the ``headers`` schema.

What is not compared, and is reported as such (never dropped): HTTP and plugin interactions of a
mixed pact (``interaction-not-message``), and Pact 4 ``Synchronous/Messages`` — a request and
its reply — whose comparison and verification are deferred (``synchronous-message-not-compared``).

The code tables (:data:`MESSAGE_FAILURE_CLASSES`, :data:`MESSAGE_WARNING_CLASSES`,
:data:`MESSAGE_FIDELITY_CLASSES`) are published on the comparison-rules page; the tests hold the
page, the tables and the golden corpus together.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .asyncapi_parser import is_supported_asyncapi_version
from .asyncapi_payload_compatibility import JSON_SCHEMA, payload_of, schema_family, schema_format_identity
from .change_taxonomy_enum import json_pointer_escape
from .pact_asyncapi_index import AsyncApiIndex, AsyncApiMessage
from .pact_contract_import import (
    interaction_is_http,
    pact_consumer_name,
    pact_provider_name,
    pact_specification_version,
)
from .pact_interaction_reader import V4_BODY_KEYS
from .pact_interaction_reader import PactBody as _Body
from .pact_interaction_reader import as_dict as _as_dict
from .pact_interaction_reader import is_json_media_type as _is_json
from .pact_interaction_reader import media_type_of as _media
from .pact_interaction_reader import read_body as _read_body
from .pact_matching_rules import MAX_COMPARISON_RULE_LOCATIONS, schema_types
from .pact_oas_compare import _candidates, _InteractionRun, _range_matches, _run_bounded
from .pact_oas_result import (
    FIDELITY_CLASSES,
    ComparisonResult,
    FidelityNote,
    InteractionResult,
    PactOasCompareError,
)
from .pact_oas_schema import ProviderSchemas

__all__ = [
    "CHANNEL_KEYS",
    "MAX_TRIED_MESSAGES",
    "MESSAGE",
    "MESSAGE_FAILURE_CLASSES",
    "MESSAGE_FIDELITY_CLASSES",
    "MESSAGE_WARNING_CLASSES",
    "compare_pact_to_asyncapi",
    "is_asyncapi_document",
]

#: The side a message is checked on: the provider produces it, the consumer reads it, so the
#: provider's schemas are read in the response view.
MESSAGE = "message"

#: Metadata keys that name where a message travels, tried in this order (case ignored).
CHANNEL_KEYS: Tuple[str, ...] = (
    "channel",
    "topic",
    "destination",
    "queue",
    "subject",
    "address",
    "routingKey",
    "kafka_topic",
)

#: Metadata keys that state the content type (case ignored).
_CONTENT_TYPE_KEYS = ("contenttype", "content-type", "content_type")

#: The most messages tried one by one for a pact message that names neither channel nor message.
MAX_TRIED_MESSAGES = 50

#: Every failure the message comparison can report, by code.
MESSAGE_FAILURE_CLASSES: Dict[str, str] = {
    "message.channel.unknown": (
        "The message's metadata names a channel, topic or queue the provider declares no channel for."
    ),
    "message.unknown": "No message the provider declares (on the named channel) accepts the pact's message.",
    "message.ambiguous": (
        "The pact names neither a channel nor a declared message, and more messages could match than "
        "are tried one by one."
    ),
    "message.not-sent": "The provider declares the message only as one it receives, never as one it sends.",
    "message.content-type.mismatch": (
        "The message's content type is not the one the provider declares for the message."
    ),
    "message.metadata.invalid": "A metadata value does not satisfy the message's `headers` schema.",
    "message.body.nullable-mismatch": (
        "The consumer expects `null` where the provider's payload schema does not allow it."
    ),
    "message.body.unknown-property": (
        "The consumer expects a property the provider's payload schema does not declare."
    ),
    "message.body.schema-mismatch": (
        "The message contents break another keyword of the provider's payload schema."
    ),
}

#: Every warning the message comparison can report, by code.
MESSAGE_WARNING_CLASSES: Dict[str, str] = {
    "message.metadata.undeclared": (
        "The message's metadata carries an entry the message's `headers` schema does not declare."
    ),
}

#: Fidelity codes the message comparison shares with the OpenAPI one (same meaning, same text).
_SHARED_FIDELITY = (
    "matching-rule-not-mapped",
    "matching-rule-unverified",
    "embedded-matcher-not-mapped",
    "generator-not-applied",
    "body-not-compared",
    "schema-not-usable",
    "oneof-relaxed",
    "findings-truncated",
)

#: Every kind of entry in the message comparison's fidelity list, by code.
MESSAGE_FIDELITY_CLASSES: Dict[str, str] = {
    **{code: FIDELITY_CLASSES[code] for code in _SHARED_FIDELITY},
    "message-direction-undeclared": (
        "The provider's document does not say whether it sends or receives the message; it was "
        "compared as a message the provider sends."
    ),
    "message-resolved-by-contents": (
        "The pact named no declared message, so it was matched to the first message whose payload "
        "accepts its contents."
    ),
    "metadata-not-compared": (
        "A metadata value was not validated: the `headers` schema combines schemas there, or "
        "declares no schema at all."
    ),
    "interaction-not-message": (
        "An HTTP or plugin interaction has no message to compare with an AsyncAPI document."
    ),
    "synchronous-message-not-compared": (
        "A Pact 4 synchronous message (a request and its reply) is not compared yet."
    ),
}


def is_asyncapi_document(document: Any) -> bool:
    """Whether a parsed provider contract is an AsyncAPI document.

    Args:
        document: The parsed document.

    Returns:
        True when it is a JSON object declaring an ``asyncapi`` version.
    """
    return isinstance(document, dict) and "asyncapi" in document


# =============================================================================================
# Reading a pact message
# =============================================================================================


def _metadata(message: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
    """A message's metadata, and the key it is filed under.

    Pact-JVM writes Pact 3 messages with ``metaData``; the specification says ``metadata``.

    Args:
        message: The pact message.

    Returns:
        ``(metadata, key)``; an empty dict under ``metadata`` when there is none.
    """
    for key in ("metadata", "metaData"):
        if isinstance(message.get(key), dict):
            return message[key], key
    return {}, "metadata"


def _find_key(metadata: Mapping[str, Any], names: Sequence[str]) -> Optional[str]:
    """The first metadata key equal (ignoring case) to one of ``names``, in their order."""
    lowered = {str(key).lower(): str(key) for key in metadata}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _read_contents(message: Mapping[str, Any], pointer: str, v4: bool) -> _Body:
    """Read a message's ``contents`` in the shape its specification version writes.

    Args:
        message: The pact message.
        pointer: JSON Pointer of the message.
        v4: Whether the pact declares specification 4 (``{content, contentType, encoded}``).

    Returns:
        The contents as a :class:`~app.pact_interaction_reader.PactBody`, pointing into
        ``…/contents``.
    """
    raw = message.get("contents")
    wrapped = v4 and isinstance(raw, dict) and "content" in raw and set(raw) <= V4_BODY_KEYS
    body = _read_body({"body": raw} if "contents" in message else {}, "", wrapped)
    if body.pointer.startswith("/body"):
        body.pointer = f"{pointer}/contents{body.pointer[len('/body'):]}"
    return body


# =============================================================================================
# The comparison
# =============================================================================================


class _MessageComparison:
    """State shared by every message of one comparison (the attributes the HTTP run reads)."""

    def __init__(self, pact: Mapping[str, Any], document: Dict[str, Any]) -> None:
        """Prepare the provider's schemas and messages once.

        Args:
            pact: The parsed pact document.
            document: The parsed AsyncAPI document.
        """
        self.schemas = ProviderSchemas(document, asyncapi=True)
        self.index = self.schemas.index
        self.messages = AsyncApiIndex(document, self.index)
        self.v4 = (pact_specification_version(pact) or "").startswith("4")
        self.rule_cache: Dict[Tuple[str, str, str], Optional[str]] = {}
        self.rule_budget = [MAX_COMPARISON_RULE_LOCATIONS]


class _MessageRun(_InteractionRun):
    """The comparison of one pact message with one AsyncAPI document.

    Reuses the PFX-2.2 run for recording, body validation, matching rules and generators; adds
    the resolution onto a declared message and the content-type and metadata checks.
    """

    message_rules = True

    def __init__(
        self, shared: _MessageComparison, index: int, message: Mapping[str, Any], pointer: str
    ) -> None:
        """Bind a pact message to the shared comparison state.

        Args:
            shared: The comparison's shared state.
            index: Position of the message in the pact.
            message: The pact message.
            pointer: JSON Pointer of the message in the pact document.
        """
        super().__init__(shared, index, message, pointer)  # type: ignore[arg-type]
        self.messages = shared.messages

    # -----------------------------------------------------------------------------------------
    # Entry point
    # -----------------------------------------------------------------------------------------

    def run(self) -> InteractionResult:
        """Resolve the message and compare it.

        Returns:
            Its :class:`~app.pact_oas_result.InteractionResult`.
        """
        self.result.checks.append("message.channel")
        candidates = self._candidates()
        if candidates is None:
            return self._finish()
        if len(candidates) == 1:
            self._compare_with(candidates[0])
            return self._finish()
        return self._try_each(candidates)

    def _finish(self) -> InteractionResult:
        """Record how many failures were only counted, and return the result."""
        if self.dropped:
            self.note(
                "findings-truncated",
                f"{self.dropped} more failure(s) in this message are not listed",
                self.pointer,
            )
        return self.result

    # -----------------------------------------------------------------------------------------
    # Resolution
    # -----------------------------------------------------------------------------------------

    def _candidates(self) -> Optional[List[AsyncApiMessage]]:
        """The declared messages the pact message may be, or ``None`` after a recorded failure.

        Returns:
            One or more messages the provider sends (or does not say it receives).
        """
        metadata, metadata_key = _metadata(self.interaction)
        pool = list(self.messages.messages)
        where = "the document"
        channel_key = _find_key(metadata, CHANNEL_KEYS)
        if channel_key is not None and isinstance(metadata[channel_key], (str, int, float)):
            destination = str(metadata[channel_key])
            pool = self.messages.on_channel(destination)
            where = f"channel '{destination}'"
            if not pool:
                self.fail(
                    "message.channel.unknown",
                    f"the message travels on '{destination}' ({channel_key}), but the provider "
                    "declares no channel with that id or address",
                    f"{self.pointer}/{metadata_key}/{json_pointer_escape(channel_key)}",
                    oas_pointer="/channels",
                    resolved_pointer="/channels",
                )
                return None
        description = self.result.description
        named = [
            message
            for message in pool
            if description and description.strip().lower() in message.names
        ]
        if named:
            pool = named
        if not pool:
            self.fail(
                "message.unknown",
                "the provider declares no messages, so nothing can satisfy this one",
                self.pointer,
                oas_pointer="/channels",
                resolved_pointer="/channels",
            )
            return None
        sent = [message for message in pool if message.sends is not False]
        if not sent:
            first = pool[0]
            self.fail(
                "message.not-sent",
                f"the provider declares message '{first.key}' on '{first.channel}' only as one "
                "it receives; a message pact needs a message the provider sends",
                self.pointer,
                oas_pointer=first.pointer,
                resolved_pointer=first.resolved,
            )
            return None
        if len(sent) > MAX_TRIED_MESSAGES:
            self.fail(
                "message.ambiguous",
                f"{len(sent)} messages of {where} could be this one; name the channel in the "
                f"message's metadata ({', '.join(CHANNEL_KEYS[:4])}) or describe the message by "
                "its name",
                self.pointer,
                oas_pointer="/channels",
                resolved_pointer="/channels",
            )
            return None
        self._where = where
        return sent

    def _try_each(self, candidates: Sequence[AsyncApiMessage]) -> InteractionResult:
        """Compare the message with each candidate and keep the first that accepts it.

        Args:
            candidates: Two or more messages, in document order.

        Returns:
            The winning comparison with a ``message-resolved-by-contents`` note, or a
            ``message.unknown`` failure naming how many were tried.
        """
        for candidate in candidates:
            trial = _MessageRun(self.shared, self.result.index, self.interaction, self.pointer)  # type: ignore[arg-type]
            trial.result.checks.append("message.channel")
            trial._compare_with(candidate)
            if not trial.result.failures:
                trial.note(
                    "message-resolved-by-contents",
                    f"{len(candidates)} messages of {self._where} could be this one; it was "
                    f"compared with '{candidate.key}' on '{candidate.channel}', the first whose "
                    "payload accepts it",
                    self.pointer,
                    oas_pointer=candidate.pointer,
                )
                return trial._finish()
        self.fail(
            "message.unknown",
            f"none of the {len(candidates)} messages of {self._where} the provider sends accepts "
            "this message",
            self.pointer,
            oas_pointer="/channels",
            resolved_pointer="/channels",
        )
        return self._finish()

    # -----------------------------------------------------------------------------------------
    # The checks
    # -----------------------------------------------------------------------------------------

    def _compare_with(self, target: AsyncApiMessage) -> None:
        """Run every check of the message against one declared message.

        Args:
            target: The declared message.
        """
        self.result.message = target.describe()
        if target.sends is None:
            self.note(
                "message-direction-undeclared",
                f"the provider's document does not say whether it sends '{target.key}' on "
                f"'{target.channel}'; it was compared as a message the provider sends",
                self.pointer,
                oas_pointer=target.pointer,
            )
        body = _read_contents(self.interaction, self.pointer, self.shared.v4)
        stated = self._check_content_type(target, body)
        self._check_metadata(target)
        self._check_contents(target, body, stated)
        self._check_rules(MESSAGE, self.interaction, self.pointer)
        self._note_generators(self.interaction, self.pointer)

    def _check_content_type(self, target: AsyncApiMessage, body: _Body) -> Optional[str]:
        """Check the message's content type against the declared one.

        Args:
            target: The declared message.
            body: The message contents.

        Returns:
            The content type the pact states for the message, if any.
        """
        self.result.checks.append("message.content-type")
        metadata, metadata_key = _metadata(self.interaction)
        key = _find_key(metadata, _CONTENT_TYPE_KEYS)
        stated = body.media_type or (_media(metadata.get(key)) if key else None)
        declared = self.messages.content_type(target)
        if stated and declared and not _range_matches(declared, stated):
            pact_pointer = (
                f"{self.pointer}/{metadata_key}/{json_pointer_escape(key)}"
                if key and not body.media_type
                else f"{self.pointer}/contents"
            )
            written = "contentType" in target.node
            self.fail(
                "message.content-type.mismatch",
                f"the message is '{stated}', but the provider declares '{declared}' for "
                f"'{target.key}'",
                pact_pointer,
                oas_pointer=f"{target.pointer}/contentType" if written else "/defaultContentType",
                resolved_pointer=f"{target.resolved}/contentType" if written else "/defaultContentType",
            )
        return stated

    def _check_metadata(self, target: AsyncApiMessage) -> None:
        """Check every metadata entry (but the destination and content type) against ``headers``.

        Args:
            target: The declared message.
        """
        self.result.checks.append("message.metadata")
        metadata, metadata_key = _metadata(self.interaction)
        skipped = {name.lower() for name in (*CHANNEL_KEYS, *_CONTENT_TYPE_KEYS)}
        has_headers = isinstance(target.node.get("headers"), dict)
        site = f"{target.resolved}/headers"
        anchor = f"{target.pointer}/headers"
        for name in sorted(str(key) for key in metadata):
            if name.lower() in skipped:
                continue
            value = metadata[name]
            pact_pointer = f"{self.pointer}/{metadata_key}/{json_pointer_escape(name)}"
            pointer, reason = (
                self.schemas.descend(site, [name]) if has_headers else (None, "path-not-declared")
            )
            self.sites[(MESSAGE, "metadata", name.lower())] = (pointer, value)
            if pointer is None and reason == "composition":
                self.note(
                    "metadata-not-compared",
                    f"metadata '{name}' is described by a combination of schemas, so its value "
                    "was not compared",
                    pact_pointer,
                    reason="composition",
                    oas_pointer=anchor,
                )
                continue
            if pointer is None:
                self.warn(
                    "message.metadata.undeclared",
                    f"the message carries metadata '{name}', which the provider's headers for "
                    f"'{target.key}' do not declare",
                    pact_pointer,
                    oas_pointer=anchor if has_headers else target.pointer,
                )
                continue
            self._check_metadata_value(name, value, pointer, anchor, pact_pointer)

    def _check_metadata_value(
        self, name: str, value: Any, site: str, anchor: str, pact_pointer: str
    ) -> None:
        """Validate one metadata value against its declared schema.

        A transport carries metadata as text, so a text value is also read as the number or
        boolean it spells when the schema wants one.

        Args:
            name: The metadata key.
            value: Its value in the pact.
            site: JSON Pointer of its schema in the document.
            anchor: The message-anchored pointer of the ``headers`` schema.
            pact_pointer: JSON Pointer of the value in the pact.
        """
        oas_pointer = f"{anchor}/properties/{json_pointer_escape(name)}"
        resolved = self.schemas.node(self.schemas.follow(site), normalized=True)
        readings = _candidates(value, schema_types(resolved)) if isinstance(value, str) else [value]
        best: Optional[List[Tuple[Any, str, str]]] = None
        for reading in readings:
            placed = self._validate_value(MESSAGE, site, oas_pointer, reading, pact_pointer)
            if placed is None:
                return
            if best is None or len(placed) < len(best):
                best = placed
            if not placed:
                return
        for finding, _, resolved_pointer in (best or [])[:1]:
            self.fail(
                "message.metadata.invalid",
                f"metadata '{name}' does not satisfy the provider's headers schema ({finding.keyword})",
                pact_pointer,
                oas_pointer=oas_pointer,
                resolved_pointer=resolved_pointer,
                keyword=finding.keyword,
                detail=finding.message,
            )

    def _payload_site(self, target: AsyncApiMessage) -> Tuple[Optional[str], Optional[str], Any]:
        """Where the message's payload schema is, and in which language it is written.

        Args:
            target: The declared message.

        Returns:
            ``(site, anchor, schemaFormat)`` — the schema's real pointer and its message-anchored
            one, ``(None, None, …)`` when the message declares no payload.
        """
        if "payload" not in target.node:
            return None, None, target.node.get("schemaFormat")
        site, anchor = f"{target.resolved}/payload", f"{target.pointer}/payload"
        payload, real = self.index.resolve_reference(target.node.get("payload"))
        schema_format, _ = payload_of({**target.node, "payload": payload})
        if isinstance(payload, dict) and "schemaFormat" in payload and "schema" in payload:
            site, anchor = f"{real or site}/schema", f"{anchor}/schema"
        return site, anchor, schema_format

    def _check_contents(self, target: AsyncApiMessage, body: _Body, stated: Optional[str]) -> None:
        """Validate the message contents against the declared payload.

        Args:
            target: The declared message.
            body: The contents.
            stated: The content type the pact states, if any.
        """
        self.result.checks.append("message.body")
        if not body.present:
            return
        if body.embedded:
            self.note(
                "embedded-matcher-not-mapped",
                "the message contents embed matchers in their example; the values were compared, "
                "the matchers were not",
                body.pointer,
            )
        site, anchor, schema_format = self._payload_site(target)
        if site is None or anchor is None:
            self.note(
                "body-not-compared",
                f"the provider declares no payload for '{target.key}', so the contents were not "
                "compared",
                body.pointer,
                reason="no-schema",
                oas_pointer=target.pointer,
            )
            return
        if schema_family(schema_format) != JSON_SCHEMA:
            self.note(
                "body-not-compared",
                f"the payload of '{target.key}' is written in '{schema_format_identity(schema_format)}', "
                "not JSON Schema, so the contents were not validated against it",
                body.pointer,
                reason="schema-format",
                oas_pointer=anchor,
            )
            return
        if body.problem is not None:
            self.note(
                "body-not-compared",
                f"the message contents were not compared: {body.problem}",
                body.pointer,
                reason="not-decodable",
                oas_pointer=anchor,
            )
            return
        effective = stated or self.messages.content_type(target)
        if not _is_json(effective) and not isinstance(body.value, (dict, list)):
            self.note(
                "body-not-compared",
                f"the message contents are '{effective or 'not typed'}', which is not JSON, so "
                "they were not validated against a schema",
                body.pointer,
                reason="content-type",
                oas_pointer=anchor,
            )
            return
        self.sites[(MESSAGE, "body", "")] = (site, body.value)
        if self.schemas.one_of_applies(site, body.value):
            self.note(
                "oneof-relaxed",
                "part of the message contents is described by a oneOf; with required properties "
                "lifted its branches cannot be told apart, so it was compared as anyOf",
                body.pointer,
                oas_pointer=anchor,
            )
        self._check_body_schema(MESSAGE, site, anchor, body)


def _not_compared(
    index: int, interaction: Mapping[str, Any], pointer: str, code: str, message: str
) -> InteractionResult:
    """The result of an interaction the message comparison does not compare.

    Args:
        index: Its position in the pact.
        interaction: The interaction.
        pointer: Its JSON Pointer.
        code: The fidelity code saying why.
        message: The sentence to show.

    Returns:
        A result with that one fidelity note and no checks.
    """
    description = interaction.get("description")
    result = InteractionResult(
        index=index, description=description if isinstance(description, str) else None, pointer=pointer
    )
    result.fidelity.append(FidelityNote(code, message, pointer))
    return result


def _compare_one(
    shared: _MessageComparison, index: int, interaction: Mapping[str, Any], pointer: str, *, message: bool
) -> InteractionResult:
    """Compare one entry of the pact, or record why it is not compared.

    Args:
        shared: The comparison's shared state.
        index: Its position in the pact.
        interaction: The interaction or message.
        pointer: Its JSON Pointer.
        message: Whether it comes from a Pact 3 ``messages`` array.

    Returns:
        Its result.
    """
    kind = interaction.get("type")
    if message or kind == "Asynchronous/Messages":
        return _run_bounded(_MessageRun(shared, index, interaction, pointer))
    if kind == "Synchronous/Messages":
        return _not_compared(
            index,
            interaction,
            pointer,
            "synchronous-message-not-compared",
            "a synchronous message (a request and its reply) is not compared with an AsyncAPI "
            "document yet; only asynchronous messages are",
        )
    label = "an HTTP interaction" if interaction_is_http(interaction) else f"interaction type '{kind}'"
    return _not_compared(
        index,
        interaction,
        pointer,
        "interaction-not-message",
        f"{label} carries no message, so there is nothing to compare with an AsyncAPI document",
    )


def compare_pact_to_asyncapi(pact: Any, asyncapi: Any) -> ComparisonResult:
    """Decide whether a provider's AsyncAPI document satisfies every message of a pact.

    Args:
        pact: The parsed pact document: a Pact 3 message pact (``messages``), or a Pact 4 pact
            whose ``interactions`` include ``Asynchronous/Messages``. HTTP interactions are
            listed as not comparable.
        asyncapi: The parsed provider contract: an AsyncAPI 2.x or 3.x document.

    Returns:
        The :class:`~app.pact_oas_result.ComparisonResult`, with ``asyncapi_version`` set.
        Neither input is modified.

    Raises:
        PactOasCompareError: When ``pact`` is not a JSON object, or ``asyncapi`` is not an
            AsyncAPI 2.x or 3.x document.
    """
    if not isinstance(pact, dict):
        raise PactOasCompareError("the pact is not a JSON object")
    if not isinstance(asyncapi, dict):
        raise PactOasCompareError("the provider contract is not a JSON object")
    version = asyncapi.get("asyncapi")
    if not isinstance(version, str) or not is_supported_asyncapi_version(version.strip()):
        raise PactOasCompareError("the provider contract is not an AsyncAPI 2.x or 3.x document")
    try:
        shared = _MessageComparison(pact, asyncapi)
    except RecursionError as exc:
        raise PactOasCompareError("the provider contract nests too deeply to be read") from exc
    result = ComparisonResult(
        consumer=pact_consumer_name(pact),
        provider=pact_provider_name(pact),
        pact_specification=pact_specification_version(pact),
        oas_version="",
        asyncapi_version=version.strip(),
    )
    for key, is_message in (("interactions", False), ("messages", True)):
        entries = pact.get(key)
        for position, raw in enumerate(entries if isinstance(entries, list) else []):
            result.interactions.append(
                _compare_one(
                    shared,
                    len(result.interactions),
                    _as_dict(raw),
                    f"/{key}/{position}",
                    message=is_message,
                )
            )
    return result
