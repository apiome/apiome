"""The messages an AsyncAPI document declares, as a message pact is resolved onto them — PFX-3.6 (#6936).

A Pact message names neither an operation nor a path: it carries a ``description``, some
``metadata`` and its ``contents``. To compare it with a provider's AsyncAPI document
(:mod:`app.pact_asyncapi_compare`) it first has to be resolved onto one of the messages the
document declares. This module lists those messages once per comparison, with everything the
resolution needs:

* **where it is** — the channel it is declared on (its id and its ``address``), the key it is
  listed under, the JSON Pointer of that listing (the *anchor*, the CTG-1.1 identity of the node)
  and of the message object itself once ``$ref``\\ s are followed;
* **what it is called** — its key, ``name``, ``messageId`` (AsyncAPI 2) and ``title``;
* **who sends it** — whether the provider *sends* it. A message pact describes what the provider
  produces and the consumer reads, so a message the provider only *receives* cannot satisfy it.

The two major versions say "who sends it" differently:

* **AsyncAPI 3** — ``operations`` with ``action: send`` or ``receive`` reference a channel and,
  optionally, some of its messages (none listed means all of them).
* **AsyncAPI 2** — a channel's ``subscribe`` operation lists the messages the application
  *sends* (others subscribe to them), ``publish`` the ones it *receives* (others publish them).

A message no operation mentions (or any message of an AsyncAPI 3 document without
``operations``) has an undeclared direction (:attr:`AsyncApiMessage.sends` is ``None``); the
comparison treats it as sent and says so.

Pure: no I/O. Only in-document ``$ref``\\ s are followed, and a reference loop or a reference out
of the document leaves the node unresolved rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple
from urllib.parse import unquote

from .change_taxonomy_enum import json_pointer_escape
from .consumer_surface import SpecIndex
from .pact_interaction_reader import as_dict as _as_dict
from .pact_interaction_reader import media_type_of as _media

__all__ = ["AsyncApiIndex", "AsyncApiMessage", "address_matches"]

#: A ``{parameter}`` in a channel address.
_PARAMETER = re.compile(r"\{[^{}/]+\}")


@dataclass(frozen=True)
class AsyncApiMessage:
    """One message a channel of the document declares.

    Attributes:
        channel: The channel's id: its key under ``channels`` (in AsyncAPI 2 that key is the
            address).
        address: The address messages travel on (``user/{id}/signedup``), or ``None`` when the
            AsyncAPI 3 channel leaves it unknown.
        key: The name the message is listed under: its key in the AsyncAPI 3 channel's
            ``messages``; in AsyncAPI 2 its ``name``, ``messageId`` or ``$ref`` target, else
            ``message`` (or ``message/<n>`` for a ``oneOf`` branch).
        pointer: JSON Pointer of the listing on the channel (or AsyncAPI 2 operation).
        resolved: JSON Pointer of the message object once ``$ref``\\ s are followed.
        node: The message object, references resolved.
        names: Its lowercase identifiers (key, ``name``, ``messageId``, ``title``), for
            resolving a pact message by its description.
        sends: ``True`` when the provider sends it, ``False`` when it only receives it, ``None``
            when the document does not say.
    """

    channel: str
    address: Optional[str]
    key: str
    pointer: str
    resolved: str
    node: Dict[str, Any]
    names: Tuple[str, ...]
    sends: Optional[bool]

    @property
    def action(self) -> Optional[str]:
        """``send``, ``receive`` or ``None`` (undeclared), as the result reports it."""
        if self.sends is None:
            return None
        return "send" if self.sends else "receive"

    def describe(self) -> Dict[str, Any]:
        """The message as an interaction result names it.

        Returns:
            ``channel``, ``address``, ``message``, ``pointer``, ``resolvedPointer`` and ``action``.
        """
        return {
            "channel": self.channel,
            "address": self.address,
            "message": self.key,
            "pointer": self.pointer,
            "resolvedPointer": self.resolved,
            "action": self.action,
        }


def address_matches(address: Optional[str], value: str) -> bool:
    """Whether a concrete destination is an address, ``{parameters}`` standing for any segment.

    Args:
        address: A channel address, possibly templated.
        value: The destination the pact names.

    Returns:
        True for an exact match, or when every ``{parameter}`` of the address can stand for a
        non-empty run of characters without ``/``.
    """
    if not isinstance(address, str) or not address:
        return False
    if address == value:
        return True
    if "{" not in address:
        return False
    parts = _PARAMETER.split(address)
    pattern = "[^/]+".join(re.escape(part) for part in parts)
    return re.fullmatch(pattern, value) is not None


def _names(key: str, node: Mapping[str, Any]) -> Tuple[str, ...]:
    """A message's lowercase identifiers, without blanks or repeats, in a stable order."""
    found: List[str] = []
    for value in (key, node.get("name"), node.get("messageId"), node.get("title")):
        if isinstance(value, str) and value.strip() and value.strip().lower() not in found:
            found.append(value.strip().lower())
    return tuple(found)


def _ref_target(node: Any) -> Optional[str]:
    """The JSON Pointer an in-document ``$ref`` names, or ``None``."""
    ref = node.get("$ref") if isinstance(node, dict) else None
    if isinstance(ref, str) and ref.startswith("#"):
        return unquote(ref[1:])
    return None


class AsyncApiIndex:
    """The messages of one AsyncAPI 2.x or 3.x document, in document order."""

    def __init__(self, document: Mapping[str, Any], spec: Optional[SpecIndex] = None) -> None:
        """Index a document.

        Args:
            document: The AsyncAPI document.
            spec: A :class:`SpecIndex` of the same document to resolve references with (one is
                built when not given).
        """
        self._document = _as_dict(document)
        self._spec = spec or SpecIndex(self._document)
        version = self._document.get("asyncapi")
        self.version = version.strip() if isinstance(version, str) else ""
        self.major = self.version.split(".", 1)[0]
        self.default_content_type = _media(self._document.get("defaultContentType"))
        self.messages: List[AsyncApiMessage] = (
            list(self._index_v2()) if self.major == "2" else list(self._index_v3())
        )

    # -----------------------------------------------------------------------------------------
    # References
    # -----------------------------------------------------------------------------------------

    def _resolve(self, node: Any, pointer: str) -> Tuple[Dict[str, Any], str]:
        """Follow a node's local ``$ref`` chain.

        Args:
            node: The node as written.
            pointer: Where it is written.

        Returns:
            ``(node, pointer)`` of the end of the chain; the input (as a dict) when it is not a
            reference or the reference leads nowhere.
        """
        resolved, target = self._spec.resolve_reference(node)
        if target is None or not isinstance(resolved, dict):
            return _as_dict(node), pointer
        return resolved, target

    # -----------------------------------------------------------------------------------------
    # AsyncAPI 3
    # -----------------------------------------------------------------------------------------

    def _sent_and_received(self) -> Optional[Tuple[Set[str], Set[str]]]:
        """The message listings each kind of AsyncAPI 3 operation covers.

        Returns:
            ``(sent, received)`` — sets of message pointers, a channel's pointer standing for all
            of its messages — or ``None`` when the document declares no operations at all.
        """
        operations = self._document.get("operations")
        if not isinstance(operations, dict) or not operations:
            return None
        sent: Set[str] = set()
        received: Set[str] = set()
        for name in sorted(str(key) for key in operations):
            pointer = f"/operations/{json_pointer_escape(name)}"
            operation, _ = self._resolve(operations[name], pointer)
            action = operation.get("action")
            bucket = sent if action == "send" else received if action == "receive" else None
            if bucket is None:
                continue
            listed = [
                target
                for target in (_ref_target(item) for item in operation.get("messages") or [])
                if target is not None
            ] if isinstance(operation.get("messages"), list) else []
            channel = _ref_target(operation.get("channel"))
            if listed:
                bucket.update(listed)
            elif channel is not None:
                bucket.add(channel)
        return sent, received

    def _index_v3(self) -> Iterator[AsyncApiMessage]:
        """List the messages of an AsyncAPI 3 document."""
        channels = _as_dict(self._document.get("channels"))
        directions = self._sent_and_received()
        for channel_id in channels:
            channel_pointer = f"/channels/{json_pointer_escape(str(channel_id))}"
            channel, channel_real = self._resolve(channels[channel_id], channel_pointer)
            address = channel.get("address")
            messages = _as_dict(channel.get("messages"))
            for key in messages:
                pointer = f"{channel_real}/messages/{json_pointer_escape(str(key))}"
                node, resolved = self._resolve(messages[key], pointer)
                anchor = f"{channel_pointer}/messages/{json_pointer_escape(str(key))}"
                sends: Optional[bool] = None
                if directions is not None:
                    covering = {anchor, pointer, resolved, channel_pointer, channel_real}
                    if covering & directions[0]:
                        sends = True
                    elif covering & directions[1]:
                        sends = False
                yield AsyncApiMessage(
                    channel=str(channel_id),
                    address=address if isinstance(address, str) else None,
                    key=str(key),
                    pointer=anchor,
                    resolved=resolved,
                    node=node,
                    names=_names(str(key), node),
                    sends=sends,
                )

    # -----------------------------------------------------------------------------------------
    # AsyncAPI 2
    # -----------------------------------------------------------------------------------------

    def _index_v2(self) -> Iterator[AsyncApiMessage]:
        """List the messages of an AsyncAPI 2 document.

        A message listed under both ``subscribe`` and ``publish`` of one channel is listed once,
        as sent (the ``subscribe`` listing).
        """
        channels = _as_dict(self._document.get("channels"))
        for address in channels:
            channel_pointer = f"/channels/{json_pointer_escape(str(address))}"
            channel, channel_real = self._resolve(channels[address], channel_pointer)
            seen: Set[str] = set()
            for verb, sends in (("subscribe", True), ("publish", False)):
                if not isinstance(channel.get(verb), dict):
                    continue
                operation, operation_real = self._resolve(channel[verb], f"{channel_real}/{verb}")
                anchor = f"{channel_pointer}/{verb}/message"
                listed, listed_real = self._resolve(operation.get("message"), f"{operation_real}/message")
                branches = listed.get("oneOf")
                entries: List[Tuple[Any, str, str, Optional[str]]] = (
                    [
                        (branch, f"{listed_real}/oneOf/{position}", f"{anchor}/oneOf/{position}", f"message/{position}")
                        for position, branch in enumerate(branches)
                    ]
                    if isinstance(branches, list)
                    else [(operation.get("message"), f"{operation_real}/message", anchor, None)]
                )
                for raw, written, anchor_pointer, fallback in entries:
                    if not isinstance(raw, dict):
                        continue
                    node, resolved = self._resolve(raw, written)
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    target = _ref_target(raw)
                    key = next(
                        (
                            value.strip()
                            for value in (node.get("name"), node.get("messageId"))
                            if isinstance(value, str) and value.strip()
                        ),
                        None,
                    ) or (target.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~") if target else None)
                    key = key or fallback or "message"
                    yield AsyncApiMessage(
                        channel=str(address),
                        address=str(address),
                        key=key,
                        pointer=anchor_pointer,
                        resolved=resolved,
                        node=node,
                        names=_names(key, node),
                        sends=sends,
                    )

    # -----------------------------------------------------------------------------------------
    # Questions
    # -----------------------------------------------------------------------------------------

    def on_channel(self, destination: str) -> List[AsyncApiMessage]:
        """The messages of every channel a destination names.

        Args:
            destination: The channel, topic or queue the pact names.

        Returns:
            The messages whose channel id or address matches it, in document order.
        """
        return [
            message
            for message in self.messages
            if message.channel == destination or address_matches(message.address, destination)
        ]

    def content_type(self, message: AsyncApiMessage) -> Optional[str]:
        """The media type a message is declared with: its own, else the document default.

        Args:
            message: The message.

        Returns:
            The bare media type, or ``None`` when neither is declared.
        """
        return _media(message.node.get("contentType")) or self.default_content_type
