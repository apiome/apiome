"""Kafka facts of an AsyncAPI channel, compiled once per spec — XPC-2.2 (#5736).

For each event channel the compiler asks: does it ride Kafka, which topic does it publish to, and
if it cannot be published, why. The answer is a :class:`KafkaChannel` on the channel's
:class:`~apiome_mock.canonical_compiler.EventChannelRoute`, and its ``support`` string is the
channel's row in the protocol capabilities report (XPC-5.5 reads it; ``GET …/__channels__`` lists
it now):

``supported``
    Published to :attr:`KafkaChannel.topic`.
``unsupported: unresolved-address-parameter``
    The address names a parameter with no declared ``enum``, ``examples`` or ``default`` value, so
    no concrete topic exists. Nothing is published: a guessed value would write to a topic no
    consumer listens on.
``unsupported: invalid-topic``
    The resolved topic is not a legal Kafka topic name (``[A-Za-z0-9._-]{1,249}``, not ``.``/``..``).
``not-kafka``
    The channel does not use Kafka; it is served over WebSocket/SSE only.

**Topic.** The channel's Kafka binding ``topic`` when it declares one; otherwise the address with
its parameters filled and ``/`` turned into ``.`` (``user/signedup`` → ``user.signedup``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.canonical_model import CanonicalApi, CanonicalField, Channel, Message

__all__ = [
    "SUPPORT_INVALID_TOPIC",
    "SUPPORT_NOT_KAFKA",
    "SUPPORT_SUPPORTED",
    "SUPPORT_UNRESOLVED_PARAMETER",
    "KafkaChannel",
    "compile_kafka_channel",
    "is_kafka_channel",
    "parameter_value",
    "resolve_address",
]

SUPPORT_SUPPORTED = "supported"
SUPPORT_UNRESOLVED_PARAMETER = "unsupported: unresolved-address-parameter"
SUPPORT_INVALID_TOPIC = "unsupported: invalid-topic"
SUPPORT_NOT_KAFKA = "not-kafka"

_PARAMETER = re.compile(r"\{([^{}]+)\}")
_TOPIC = re.compile(r"^[A-Za-z0-9._-]{1,249}$")


@dataclass(frozen=True)
class KafkaChannel:
    """A channel's Kafka facts.

    Attributes:
        support: One of the ``SUPPORT_*`` strings.
        topic: The resolved topic, or ``None`` unless ``support`` is ``supported``.
        unresolved: Parameter names that had no declared value.
    """

    support: str
    topic: str | None = None
    unresolved: tuple[str, ...] = ()

    @property
    def publishable(self) -> bool:
        """Whether messages are published for this channel."""
        return self.support == SUPPORT_SUPPORTED


def _kafka_binding(bindings: Any) -> dict[str, Any] | None:
    """Return the ``kafka`` entry of a bindings object, or ``None``."""
    if not isinstance(bindings, dict):
        return None
    for name, value in bindings.items():
        if str(name).lower() == "kafka":
            return value if isinstance(value, dict) else {}
    return None


def is_kafka_channel(channel: Channel, api: CanonicalApi, messages: Iterable[Message] = ()) -> bool:
    """Whether a channel rides Kafka.

    True when the channel's ``protocol`` is ``kafka`` (or, with none, the document's), when the
    channel declares a ``kafka`` binding, or when any of its messages does.
    """
    protocol = (channel.protocol or api.protocol or "").lower()
    if protocol in {"kafka", "kafka-secure"}:
        return True
    if _kafka_binding(channel.bindings) is not None:
        return True
    return any(_kafka_binding((message.extras or {}).get("bindings")) is not None for message in messages)


def parameter_value(parameter: CanonicalField) -> str | None:
    """The declared value of an address parameter: first ``enum``, first example, or ``default``.

    Returns:
        The value as a string, or ``None`` when the parameter declares none.
    """
    constraints = parameter.constraints
    enum = getattr(constraints, "enum", None) if constraints is not None else None
    if enum:
        return str(enum[0])
    examples = (parameter.extras or {}).get("examples")
    if isinstance(examples, list) and examples and examples[0] is not None:
        return str(examples[0])
    if parameter.default is not None:
        return str(parameter.default)
    return None


def resolve_address(channel: Channel) -> tuple[str, tuple[str, ...]]:
    """Fill a channel address's ``{parameters}`` from their declared values.

    Returns:
        ``(address, unresolved)``: the filled address and the names of parameters that had no
        declared value (or were not declared at all), in order of appearance.
    """
    by_name = {parameter.name: parameter for parameter in channel.parameters}
    unresolved: list[str] = []

    def fill(match: "re.Match[str]") -> str:
        name = match.group(1)
        parameter = by_name.get(name)
        value = parameter_value(parameter) if parameter is not None else None
        if value is None:
            unresolved.append(name)
            return match.group(0)
        return value

    return _PARAMETER.sub(fill, channel.address or channel.key), tuple(unresolved)


def compile_kafka_channel(
    channel: Channel | None, api: CanonicalApi, messages: Iterable[Message] = ()
) -> KafkaChannel:
    """Compile one channel's Kafka facts.

    Args:
        channel: The canonical channel, or ``None`` for an operation naming an undeclared channel.
        api: The canonical API (its ``protocol`` is the fallback).
        messages: The channel's outbound event messages (their bindings can mark it Kafka).

    Returns:
        The channel's :class:`KafkaChannel`.
    """
    messages = tuple(messages)
    if channel is None or not is_kafka_channel(channel, api, messages):
        return KafkaChannel(support=SUPPORT_NOT_KAFKA)
    binding = _kafka_binding(channel.bindings) or {}
    declared_topic = binding.get("topic")
    if isinstance(declared_topic, str) and declared_topic.strip():
        topic, unresolved = declared_topic.strip(), ()
    else:
        address, unresolved = resolve_address(channel)
        topic = address.strip("/").replace("/", ".")
    if unresolved:
        return KafkaChannel(support=SUPPORT_UNRESOLVED_PARAMETER, unresolved=unresolved)
    if not _TOPIC.match(topic) or topic in {".", ".."}:
        return KafkaChannel(support=SUPPORT_INVALID_TOPIC)
    return KafkaChannel(support=SUPPORT_SUPPORTED, topic=topic)
