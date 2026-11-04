"""Push an Avro export to a live Confluent Schema Registry — MFX-19.4 (#3912).

The Avro export (MFX-19.1) writes one ``.avsc`` per named type, each with the subject MFX-19.3's
naming strategy gives it. This module registers those schemas on an upstream registry that speaks
the Confluent Schema Registry REST API (Confluent Platform or Cloud, Karapace, Apicurio's ``ccompat``
API) through an existing ``schema-registry`` connector: the connector's base URL and its stored
credentials, over the same SSRF-guarded client the connector's sync uses
(:class:`~app.schema_registry_connector_source.SchemaRegistrySource`). It is the import connector's
client used in reverse.

**Plan** (:func:`plan_avro_push`). Each emitted file becomes one unit: its subject, its schema text
and the other units it references by name. A schema that names a type of another file is
registered with a Confluent ``references`` entry (``{name, subject, version}``) pointing at that
file's subject, so the units are ordered dependencies first. Two files with the same subject — every
type under ``topic_name`` — cannot be pushed: a subject holds one schema.

**Push** (:func:`push_avro_subjects`) runs the push every format shares,
:func:`app.schema_registry_push.push_registry_subjects` (MFX-19.6): look the schema up, check it
against the subject's latest version, register it — referenced schemas first. A dry run registers
nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

import httpx

from .emitter import EmitResult
from .schema_registry_push import (
    RegistryPushError,
    RegistryPushReference,
    RegistryPushSubjectResult,
    RegistryPushUnit,
    duplicate_subject_error,
    order_by_dependencies,
    push_registry_subjects,
)

__all__ = [
    "AvroPushError",
    "AvroPushSubjectResult",
    "AvroPushUnit",
    "plan_avro_push",
    "push_avro_subjects",
    "to_registry_units",
]

#: Avro's primitive type names — a type position holding one of these is not a reference.
_PRIMITIVES = frozenset({"null", "boolean", "int", "long", "float", "double", "bytes", "string"})

#: The Avro schema types that define a name.
_NAMED = frozenset({"record", "error", "enum", "fixed"})


class AvroPushError(RegistryPushError):
    """A push refused before anything is sent to the registry (``AVRO_PUSH_…`` codes)."""


@dataclass(frozen=True)
class AvroPushUnit:
    """One emitted schema to register.

    Attributes:
        subject: The registry subject (MFX-19.3).
        file: The emitted file's path.
        schema: The schema text sent to the registry.
        record: The schema's full name, when it defines one (a top-level union or map does not).
        depends_on: The full names of other units' types this schema references.
    """

    subject: str
    file: str
    schema: str
    record: Optional[str] = None
    depends_on: Sequence[str] = field(default_factory=tuple)


#: A Confluent schema reference (the shared push's model, MFX-19.6).
AvroPushReference = RegistryPushReference

#: What the push did for one subject (the shared push's model, MFX-19.6).
AvroPushSubjectResult = RegistryPushSubjectResult


# ---------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------


def _split_name(name: str, namespace: Optional[str]) -> tuple:
    """``(fullname, namespace)`` of a name as Avro resolves it inside ``namespace``."""
    if "." in name:
        return name, name.rpartition(".")[0]
    return (f"{namespace}.{name}" if namespace else name), namespace


def _names(schema: Any) -> tuple:
    """``(defined, referenced)`` full names of one schema, walked as Avro resolves names."""
    defined: Set[str] = set()
    referenced: Set[str] = set()

    def walk(node: Any, namespace: Optional[str]) -> None:
        if isinstance(node, str):
            if node not in _PRIMITIVES:
                referenced.add(_split_name(node, namespace)[0])
        elif isinstance(node, list):
            for member in node:
                walk(member, namespace)
        elif isinstance(node, Mapping):
            kind = node.get("type")
            if kind in _NAMED and isinstance(node.get("name"), str):
                own_namespace = node.get("namespace") if isinstance(node.get("namespace"), str) else namespace
                fullname, inner = _split_name(node["name"], own_namespace or None)
                defined.add(fullname)
                for entry in node.get("fields") or []:
                    if isinstance(entry, Mapping):
                        walk(entry.get("type"), inner)
            elif kind == "array":
                walk(node.get("items"), namespace)
            elif kind == "map":
                walk(node.get("values"), namespace)
            else:
                walk(kind, namespace)

    walk(schema, None)
    return defined, referenced


def _top_name(schema: Any) -> Optional[str]:
    """The full name a top-level schema defines, if any."""
    if isinstance(schema, Mapping) and schema.get("type") in _NAMED and isinstance(schema.get("name"), str):
        namespace = schema.get("namespace") if isinstance(schema.get("namespace"), str) else None
        return _split_name(schema["name"], namespace or None)[0]
    return None


def _schema_object(content: Any, path: str) -> Any:
    """An emitted file's schema as JSON data (the emitter writes a dict; text is parsed)."""
    if isinstance(content, (bytes, str)):
        try:
            return json.loads(content)
        except ValueError as exc:
            raise AvroPushError("AVRO_PUSH_NOT_AVSC", f"{path} is not an Avro JSON schema (.avsc).") from exc
    return content


def plan_avro_push(emit: EmitResult) -> List[AvroPushUnit]:
    """The units of an Avro export to register, dependencies first.

    Args:
        emit: The Avro emitter's ``.avsc`` output (one file per named type, each with a subject).

    Returns:
        One unit per file, ordered so every schema comes after the schemas it references (ties by
        subject, so the order is deterministic).

    Raises:
        AvroPushError: The export wrote no schema, a file has no subject or is not ``.avsc``, two
            files share a subject, or the references form a cycle.
    """
    if not emit.files:
        raise AvroPushError("AVRO_PUSH_EMPTY", "The Avro export wrote no schema to register.")
    drafts: List[Dict[str, Any]] = []
    owners: Dict[str, str] = {}
    by_subject: Dict[str, str] = {}
    for emitted in emit.files:
        subject = (emitted.subject or "").strip()
        if not subject:
            raise AvroPushError("AVRO_PUSH_NO_SUBJECT", f"{emitted.path} has no registry subject.")
        if subject in by_subject:
            raise duplicate_subject_error(
                "AVRO_PUSH_DUPLICATE_SUBJECT", by_subject[subject], emitted.path, subject, error_type=AvroPushError
            )
        by_subject[subject] = emitted.path
        schema = _schema_object(emitted.content, emitted.path)
        defined, referenced = _names(schema)
        record = _top_name(schema)
        for name in defined:
            owners.setdefault(name, subject)
        drafts.append({"subject": subject, "file": emitted.path, "schema": schema, "record": record,
                       "defined": defined, "referenced": referenced})

    units: Dict[str, AvroPushUnit] = {}
    for draft in drafts:
        # Only a name another unit defines at its top level is a cross-subject reference.
        deps = sorted(
            name for name in draft["referenced"] - draft["defined"]
            if owners.get(name) not in (None, draft["subject"])
        )
        units[draft["subject"]] = AvroPushUnit(
            subject=draft["subject"],
            file=draft["file"],
            schema=json.dumps(draft["schema"], ensure_ascii=False, separators=(",", ":")),
            record=draft["record"],
            depends_on=tuple(deps),
        )

    order = order_by_dependencies(
        {subject: {owners[d] for d in unit.depends_on} for subject, unit in units.items()},
        lambda pending: AvroPushError(
            "AVRO_PUSH_REFERENCE_CYCLE",
            f"The schemas of subjects {', '.join(pending)} reference each other; a registry cannot hold them.",
        ),
    )
    return [units[subject] for subject in order]


# ---------------------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------------------


def push_avro_subjects(
    client: httpx.Client,
    registry_url: str,
    units: Sequence[AvroPushUnit],
    *,
    dry_run: bool = False,
    compatibility_level: Optional[str] = None,
    credentials: Optional[Mapping[str, str]] = None,
) -> List[AvroPushSubjectResult]:
    """Check and register each unit on the registry, in plan order.

    Args:
        client: An SSRF-guarded client carrying the connector's credentials.
        registry_url: The registry's base URL.
        units: The plan from :func:`plan_avro_push`.
        dry_run: Look up and check every subject, but register nothing.
        compatibility_level: A Confluent level to set on each subject the push registers (MFX-19.6).
        credentials: The connector's credentials, removed from any registry message reported back.

    Returns:
        One result per unit, in the same order.
    """
    return push_registry_subjects(
        client,
        registry_url,
        to_registry_units(units),
        dry_run=dry_run,
        compatibility_level=compatibility_level,
        credentials=credentials,
    )


def to_registry_units(units: Sequence[AvroPushUnit]) -> List[RegistryPushUnit]:
    """The Avro plan as the shared push takes it: each reference named by its type's full name."""
    subject_of = {unit.record: unit.subject for unit in units if unit.record}
    return [
        RegistryPushUnit(
            subject=unit.subject,
            file=unit.file,
            schema=unit.schema,
            schema_type="AVRO",
            record=unit.record,
            references=tuple((name, subject_of[name]) for name in unit.depends_on),
        )
        for unit in units
    ]
