"""Confluent Schema Registry subject naming, shared by every format — MFX-19.3 (#3911), MFX-19.6 (#4183).

A registry files each schema under a **subject**. Confluent's serializers pick the subject with a
naming strategy, and the strategies work the same way for Avro, JSON Schema and Protobuf; only the
**record name** they start from differs per format:

* **Avro** — the record's full name (``acme.Widget``);
* **JSON Schema** — the schema's ``title`` (``Widget``), which is what Confluent's JSON Schema
  serializer reads as the record name;
* **Protobuf** — the full name of the file's first message, ``<package>.<Message>`` (``acme.Widget``),
  or of its first enum when it has no message.

From that record name, :func:`registry_subject` builds the subject the same way for all three:

* ``record_name`` (Confluent ``RecordNameStrategy``) → ``{record}-{role}``;
* ``topic_name`` (``TopicNameStrategy``) → ``{topic}-{role}``;
* ``topic_record_name`` (``TopicRecordNameStrategy``) → ``{topic}-{record}-{role}``;

where ``role`` is ``value`` or ``key``.
See https://docs.confluent.io/platform/current/schema-registry/fundamentals/serdes-develop/index.html
"""

from __future__ import annotations

from typing import Literal, Optional

__all__ = ["SUBJECT_NAMING_STRATEGIES", "SubjectNaming", "SubjectRole", "registry_subject"]

#: The subject naming strategies, by option value.
SUBJECT_NAMING_STRATEGIES = ("record_name", "topic_name", "topic_record_name")

#: A subject naming strategy's option value.
SubjectNaming = Literal["record_name", "topic_name", "topic_record_name"]

#: Whether the schema describes a Kafka message's value or its key.
SubjectRole = Literal["value", "key"]


def registry_subject(record: str, naming: str, topic: Optional[str], role: str) -> str:
    """The subject a schema is registered under.

    Args:
        record: The schema's record name, as its format's serializer reads it (see the module doc).
        naming: ``record_name``, ``topic_name`` or ``topic_record_name``.
        topic: The Kafka topic; needed by the two topic strategies.
        role: ``value`` or ``key``: the subject's suffix.

    Returns:
        The subject, such as ``acme.Widget-value`` or ``orders-acme.Widget-key``.

    Raises:
        ValueError: ``naming`` is not a strategy, or a topic strategy has no topic.
    """
    if naming not in SUBJECT_NAMING_STRATEGIES:
        raise ValueError(f"subject_naming must be one of {', '.join(SUBJECT_NAMING_STRATEGIES)}")
    suffix = f"-{role}"
    if naming == "record_name":
        return f"{record}{suffix}"
    clean_topic = (topic or "").strip()
    if not clean_topic:
        raise ValueError("topic is required when subject_naming is topic_name or topic_record_name")
    if naming == "topic_name":
        return f"{clean_topic}{suffix}"
    return f"{clean_topic}-{record}{suffix}"
