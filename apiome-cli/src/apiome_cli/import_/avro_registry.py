"""Confluent Schema Registry intake for ``apiome import avro --registry`` (MFI-12.6, #3787).

A Confluent-compatible schema registry serves each schema it holds, unescaped, at
``<registry>/subjects/<subject>/versions/<version>/schema`` and
``<registry>/schemas/ids/<id>/schema``. :func:`avro_registry_schema_url` builds that URL; the schema
is then fetched and imported through the ordinary registry-dispatch import under the ``avro``
adapter, exactly as a ``--url`` import would be.

:func:`avro_subject_name` names the subject the way a Kafka producer's serializer does, under
Confluent's three subject naming strategies — the same rules the REST schema-registry connector
uses to infer a crawled subject's strategy (``app.schema_registry_connector_source.infer_strategy``):

* ``topic`` (``TopicNameStrategy``, the default): ``<topic>-value``, or ``<topic>-key``.
* ``record`` (``RecordNameStrategy``): the record's full name, ``com.example.Order``.
* ``topic_record`` (``TopicRecordNameStrategy``): ``<topic>-<record full name>``.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

from apiome_cli.client.schema_registry import STRATEGIES

__all__ = ["avro_registry_schema_url", "avro_subject_name"]

#: The default ``--version``: the subject's newest version.
LATEST = "latest"


def avro_subject_name(
    *,
    subject: str | None = None,
    topic: str | None = None,
    strategy: str | None = None,
    record: str | None = None,
    key: bool = False,
) -> str:
    """Return the registry subject to import.

    Either ``subject`` names it outright, or ``topic`` / ``record`` derive it under ``strategy``.

    Args:
        subject: An explicit subject name (``orders-value``); excludes ``topic`` and ``record``.
        topic: The Kafka topic, for the ``topic`` and ``topic_record`` strategies.
        strategy: ``topic`` (the default), ``record`` or ``topic_record``.
        record: The record's full name (``com.example.Order``), for ``record`` / ``topic_record``.
        key: Name the topic's **key** schema (``<topic>-key``) instead of its value schema; only the
            ``topic`` strategy distinguishes the two.

    Returns:
        The subject name.

    Raises:
        ValueError: For a missing or conflicting input, or an unknown strategy.
    """
    chosen = (strategy or "topic").strip().lower()
    if chosen not in STRATEGIES:
        raise ValueError(f"--strategy must be one of {', '.join(STRATEGIES)}")
    explicit = (subject or "").strip()
    topic_name = (topic or "").strip()
    record_name = (record or "").strip()

    if explicit:
        if topic_name or record_name or strategy or key:
            raise ValueError("--subject names the subject itself; drop --topic, --record, --strategy and --key")
        return explicit
    if key and chosen != "topic":
        raise ValueError("--key applies to the topic strategy only")
    if chosen == "topic":
        if not topic_name:
            raise ValueError("Name the subject: --subject NAME, or --topic NAME (with --strategy)")
        if record_name:
            raise ValueError("--record applies to the record and topic_record strategies only")
        return f"{topic_name}-{'key' if key else 'value'}"
    if not record_name:
        raise ValueError(f"The {chosen} strategy needs --record, the record's full name")
    if chosen == "record":
        if topic_name:
            raise ValueError("The record strategy names the subject after the record alone; drop --topic")
        return record_name
    if not topic_name:
        raise ValueError("The topic_record strategy needs --topic as well as --record")
    return f"{topic_name}-{record_name}"


def avro_registry_schema_url(
    registry_url: str,
    *,
    subject: str | None = None,
    version: str | None = None,
    schema_id: int | None = None,
) -> str:
    """Return the URL a Confluent-compatible registry serves one schema's raw text at.

    Args:
        registry_url: The registry's base URL (``https://registry.example.com:8081``), which may
            carry a path prefix (``https://host/apis/ccompat/v7``). A query string is kept.
        subject: The subject to read; excludes ``schema_id``.
        version: The subject version — ``latest`` (the default) or a positive number.
        schema_id: A global schema id to read instead of a subject version.

    Returns:
        ``<registry>/subjects/<subject>/versions/<version>/schema`` or
        ``<registry>/schemas/ids/<id>/schema``, the subject percent-encoded.

    Raises:
        ValueError: When the URL is empty, not ``http``/``https`` or has no host; when neither or
            both of ``subject`` and ``schema_id`` are given; or for a bad version or id.
    """
    cleaned = (registry_url or "").strip()
    if not cleaned:
        raise ValueError("Schema registry URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Schema registry URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("Schema registry URL has no host")
    if (subject is None) == (schema_id is None):
        raise ValueError("Name exactly one schema: a subject, or --schema-id")

    base = parts.path.rstrip("/")
    if schema_id is not None:
        if version is not None:
            raise ValueError("--version applies to a subject, not to --schema-id")
        if schema_id <= 0:
            raise ValueError("--schema-id must be a positive number")
        path = f"{base}/schemas/ids/{schema_id}/schema"
    else:
        path = f"{base}/subjects/{quote(subject or '', safe='')}/versions/{_version(version)}/schema"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, parts.query, ""))


def _version(version: str | None) -> str:
    """Validate a subject version: ``latest`` or a positive integer (``-1`` is Confluent's latest)."""
    chosen = (version or LATEST).strip().lower()
    if chosen in (LATEST, "-1"):
        return LATEST
    if not chosen.isdigit() or int(chosen) <= 0:
        raise ValueError("--version must be latest or a positive number")
    return str(int(chosen))
