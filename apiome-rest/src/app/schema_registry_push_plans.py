"""Plan a JSON Schema or Protobuf export's registry push — MFX-19.6 (#4183).

The Avro plan is :func:`app.avro_registry_push.plan_avro_push`. These two turn a JSON Schema export
(MFX-21.1) or a Protobuf export (MFX-12.1) into :class:`~app.schema_registry_push.RegistryPushUnit`\\ s
for :func:`~app.schema_registry_push.push_registry_subjects`, with subjects named by the same
strategies as Avro (:func:`app.schema_registry_subjects.registry_subject`).

**JSON Schema** (``schemaType: JSON``). Each emitted document is one unit; with ``packaging:
per-type`` (what the push asks for by default) that is one subject per type. The record name is the
document's ``title`` (the file name's stem without one). A ``$ref`` to another file of the export
(``Owner.schema.json``, or ``Owner.schema.json#/…``) is a Confluent reference named by that file part.

**Protobuf** (``schemaType: PROTOBUF``). Each emitted ``.proto`` (one per package) is one unit. The
record name is the full name of its first top-level ``message`` (``acme.Widget``), else of its first
``enum``. An ``import`` of another file of the export is a reference named by the import path; an
import of a Protobuf well-known type (``google/protobuf/…``) is not, since every registry has them.

Both refuse, before anything is sent: an export with no file, two files on one subject, references
that form a cycle, and (Protobuf) a file that declares no message or enum to name it by.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Optional, Set

from .emitter import EmitResult, EmittedFile
from .schema_registry_push import (
    RegistryPushError,
    RegistryPushUnit,
    SchemaType,
    duplicate_subject_error,
    order_by_dependencies,
)
from .schema_registry_subjects import registry_subject

__all__ = ["plan_jsonschema_push", "plan_protobuf_push"]

_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT = re.compile(r'^import\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;', re.MULTILINE)
#: A top-level declaration starts its line; a nested one is indented.
_TOP_LEVEL = re.compile(r"^(message|enum)\s+(\w+)", re.MULTILINE)
#: The import prefix of Protobuf's well-known types, which registries provide themselves.
_WELL_KNOWN = "google/protobuf/"


def _text(emitted: EmittedFile) -> str:
    """An emitted file's content as text."""
    content = emitted.content
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _subject(record: str, naming: str, topic: Optional[str], role: str) -> str:
    """The unit's subject; a naming the strategy refuses (a topic strategy with no topic) is a 422."""
    try:
        return registry_subject(record, naming, topic, role)
    except ValueError as exc:
        raise RegistryPushError("REGISTRY_PUSH_SUBJECT_NAMING", str(exc)) from exc


def _plan(
    drafts: List[Dict[str, Any]],
    schema_type: SchemaType,
    naming: str,
    topic: Optional[str],
    role: str,
) -> List[RegistryPushUnit]:
    """Units from per-file drafts, dependencies first.

    Args:
        drafts: ``{file, schema, record, refs}`` per file; ``refs`` are the paths of the other files
            of the same export it references. In both formats a reference is named by that path (the
            ``$ref`` file part, or the ``import`` path).
        schema_type: The registry's ``schemaType``.
        naming: The subject naming strategy.
        topic: The Kafka topic of a topic strategy.
        role: ``value`` or ``key``.

    Returns:
        One unit per draft, every schema after the schemas it references.

    Raises:
        RegistryPushError: Two files map to one subject, or the references form a cycle.
    """
    subject_of: Dict[str, str] = {}
    for draft in drafts:
        subject = _subject(draft["record"], naming, topic, role)
        taken = next((f for f, s in subject_of.items() if s == subject), None)
        if taken is not None:
            raise duplicate_subject_error("REGISTRY_PUSH_DUPLICATE_SUBJECT", taken, draft["file"], subject)
        subject_of[draft["file"]] = subject

    units: Dict[str, RegistryPushUnit] = {}
    for draft in drafts:
        subject = subject_of[draft["file"]]
        units[subject] = RegistryPushUnit(
            subject=subject,
            file=draft["file"],
            schema=draft["schema"],
            schema_type=schema_type,
            record=draft["record"],
            references=tuple((path, subject_of[path]) for path in sorted(draft["refs"])),
        )
    order = order_by_dependencies(
        {subject: {ref_subject for _, ref_subject in unit.references} for subject, unit in units.items()},
        lambda pending: RegistryPushError(
            "REGISTRY_PUSH_REFERENCE_CYCLE",
            f"The schemas of subjects {', '.join(pending)} reference each other; a registry cannot hold them.",
        ),
    )
    return [units[subject] for subject in order]


def _require_files(emit: EmitResult, label: str) -> None:
    if not emit.files:
        raise RegistryPushError("REGISTRY_PUSH_EMPTY", f"The {label} export wrote no schema to register.")


# ---------------------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------------------


def _refs(node: Any) -> Iterator[str]:
    """Every ``$ref`` string in a JSON Schema document."""
    if isinstance(node, dict):
        for keyword, value in node.items():
            if keyword == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def _stem(path: str) -> str:
    """``Owner`` for ``dir/Owner.schema.json``."""
    name = path.rsplit("/", 1)[-1]
    for suffix in (".schema.json", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def plan_jsonschema_push(
    emit: EmitResult, *, naming: str = "record_name", topic: Optional[str] = None, role: str = "value"
) -> List[RegistryPushUnit]:
    """The units of a JSON Schema export to register, dependencies first.

    Args:
        emit: The JSON Schema emitter's output (a bundle, or one document per type).
        naming: ``record_name``, ``topic_name`` or ``topic_record_name``.
        topic: The Kafka topic of a topic strategy.
        role: ``value`` or ``key``.

    Returns:
        One unit per document, ``schemaType: JSON``, each after the documents it ``$ref``\\ s.

    Raises:
        RegistryPushError: No document, a document that is not JSON, two documents on one subject,
            a cycle of ``$ref``\\ s, or a topic strategy with no topic.
    """
    _require_files(emit, "JSON Schema")
    paths = {emitted.path for emitted in emit.files}
    drafts: List[Dict[str, Any]] = []
    for emitted in emit.files:
        try:
            document = json.loads(_text(emitted))
        except ValueError as exc:
            raise RegistryPushError(
                "REGISTRY_PUSH_NOT_JSON_SCHEMA", f"{emitted.path} is not a JSON Schema document."
            ) from exc
        title = document.get("title") if isinstance(document, dict) else None
        record = title.strip() if isinstance(title, str) and title.strip() else _stem(emitted.path)
        refs: Set[str] = set()
        for ref in _refs(document):
            target = ref.split("#", 1)[0]
            if target and target != emitted.path and target in paths:
                refs.add(target)
        drafts.append({
            "file": emitted.path,
            "schema": json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            "record": record,
            "refs": refs,
        })
    return _plan(drafts, "JSON", naming, topic, role)


# ---------------------------------------------------------------------------------------
# Protobuf
# ---------------------------------------------------------------------------------------


def plan_protobuf_push(
    emit: EmitResult, *, naming: str = "record_name", topic: Optional[str] = None, role: str = "value"
) -> List[RegistryPushUnit]:
    """The units of a Protobuf export to register, dependencies first.

    Args:
        emit: The proto3 emitter's output (one ``.proto`` per package).
        naming: ``record_name``, ``topic_name`` or ``topic_record_name``.
        topic: The Kafka topic of a topic strategy.
        role: ``value`` or ``key``.

    Returns:
        One unit per ``.proto`` file, ``schemaType: PROTOBUF``, each after the files it imports.

    Raises:
        RegistryPushError: No file, a file with no message or enum, two files on one subject, a cycle
            of imports, or a topic strategy with no topic.
    """
    _require_files(emit, "Protobuf")
    paths = {emitted.path for emitted in emit.files}
    drafts: List[Dict[str, Any]] = []
    for emitted in emit.files:
        text = _text(emitted)
        declared = _TOP_LEVEL.findall(text)
        if not declared:
            raise RegistryPushError(
                "REGISTRY_PUSH_NO_RECORD",
                f"{emitted.path} declares no message or enum, so it has no record name to register it "
                "under; a registry subject holds message types.",
            )
        name = next((n for kind, n in declared if kind == "message"), declared[0][1])
        package = _PACKAGE.search(text)
        record = f"{package.group(1)}.{name}" if package else name
        refs = {
            path
            for path in _IMPORT.findall(text)
            if not path.startswith(_WELL_KNOWN) and path in paths and path != emitted.path
        }
        drafts.append({"file": emitted.path, "schema": text, "record": record, "refs": refs})
    return _plan(drafts, "PROTOBUF", naming, topic, role)
