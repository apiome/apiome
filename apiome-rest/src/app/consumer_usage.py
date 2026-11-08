"""Consumer usage of one stored version, projected onto its pointers — DCW-0.5 (private-suite #2422).

An authoring tool asks a narrower question than the consumer registry answers: *which of this
version's operations, fields and schemas do registered consumers use, and how many of them?*
:func:`project_consumer_usage` answers it from the registry's own current contracts (CTG-4.1,
#4479), so nothing here stores, ingests or resolves anything new.

**Only contracts resolved against this version are projected.** A contract's pointers were
resolved against the revision it names (``ConsumerContractRecord.version_id``); projecting a
contract declared against another revision onto this one would claim usage the registry never
established. Those consumers are counted in ``other_version_consumer_count`` and nothing more.

**Counts are for everyone; names are not.** The counts are computed from the platform's view of
the registry, so they never depend on who asked. Consumer names are attached only when the reader
holds ``consumer_contracts:view`` — the CTG-4.5 gate's rule, as :func:`app.api_check_suite_store.
redact_consumers` applies it — and a reader without it sees ``consumers: null`` and
``consumers_visible: false``, never an empty list that would read as "nobody".
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import ConsumerSummary

__all__ = [
    "ConsumerRef",
    "ConsumerUsageResponse",
    "FieldUsage",
    "OperationUsage",
    "SchemaUsage",
    "project_consumer_usage",
]


class ConsumerRef(BaseModel):
    """A consumer named in the projection — present only for a reader allowed to see names.

    Attributes:
        id: The consumer's row id.
        slug: Its stable handle.
        name: Its display name.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Consumer id.")
    slug: str = Field(description="Consumer handle.")
    name: str = Field(description="Consumer display name.")


class FieldUsage(BaseModel):
    """How many consumers use one field of an operation.

    Attributes:
        pointer: Operation-anchored JSON Pointer to the field.
        schema_pointer: Where the node lives (a ``$ref`` target, or the same pointer).
        location: ``response``, ``request`` or ``parameter``.
        consumer_count: Consumers that declared this field.
        consumers: Those consumers, or ``None`` when the reader may not see names.
    """

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="Operation-anchored JSON Pointer to the field.")
    schema_pointer: str = Field(description="Where the node lives (a $ref target, or the same pointer).")
    location: str = Field(description="response | request | parameter.")
    consumer_count: int = Field(description="Consumers that declared this field.")
    consumers: Optional[List[ConsumerRef]] = Field(
        default=None, description="The consumers; null when the reader may not see names."
    )


class OperationUsage(BaseModel):
    """How many consumers call one operation, and which of its fields they use.

    Attributes:
        pointer: ``/paths/<escaped path>/<method>``.
        method: Lowercase HTTP method.
        path: The specification's path template.
        operation_id: Declared ``operationId``, when there is one.
        consumer_count: Consumers that declared this operation.
        consumers: Those consumers, or ``None`` when the reader may not see names.
        fields: Per-field usage, ordered by pointer.
    """

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="/paths/<escaped path>/<method>.")
    method: str = Field(description="Lowercase HTTP method.")
    path: str = Field(description="Specification path template.")
    operation_id: Optional[str] = Field(default=None, description="Declared operationId.")
    consumer_count: int = Field(description="Consumers that declared this operation.")
    consumers: Optional[List[ConsumerRef]] = Field(
        default=None, description="The consumers; null when the reader may not see names."
    )
    fields: List[FieldUsage] = Field(default_factory=list, description="Per-field usage.")


class SchemaUsage(BaseModel):
    """How many consumers reach one component schema through the fields they use.

    Attributes:
        schema_pointer: The ``/components/schemas/<Name>`` pointer.
        consumer_count: Consumers with at least one declared field inside that schema.
        consumers: Those consumers, or ``None`` when the reader may not see names.
    """

    model_config = ConfigDict(extra="forbid")

    schema_pointer: str = Field(description="/components/schemas/<Name>.")
    consumer_count: int = Field(description="Consumers using a field inside this schema.")
    consumers: Optional[List[ConsumerRef]] = Field(
        default=None, description="The consumers; null when the reader may not see names."
    )


class ConsumerUsageResponse(BaseModel):
    """Consumer usage of one stored version.

    Attributes:
        version_record_id: The revision the usage is bound to.
        version_label: That revision's label.
        consumers_visible: Whether consumer names are included for this reader.
        consumer_count: Consumers whose current contract was resolved against this revision.
        other_version_consumer_count: Consumers whose current contract names another revision.
        undeclared_consumer_count: Consumers registered but with no contract yet.
        operations: Per-operation usage, ordered by pointer.
        schemas: Per-component-schema usage, ordered by pointer.
    """

    model_config = ConfigDict(extra="forbid")

    version_record_id: str = Field(description="Revision the usage is bound to.")
    version_label: Optional[str] = Field(default=None, description="That revision's label.")
    consumers_visible: bool = Field(
        description="Whether consumer names are included — requires `consumer_contracts:view`."
    )
    consumer_count: int = Field(
        description="Consumers whose current contract was resolved against this revision."
    )
    other_version_consumer_count: int = Field(
        description="Consumers whose current contract names another revision; not projected."
    )
    undeclared_consumer_count: int = Field(
        description="Registered consumers that have declared no contract yet."
    )
    operations: List[OperationUsage] = Field(default_factory=list, description="Per-operation usage.")
    schemas: List[SchemaUsage] = Field(default_factory=list, description="Per-schema usage.")


_SCHEMA_PREFIX = "/components/schemas/"


def _schema_root(schema_pointer: str) -> Optional[str]:
    """Return the ``/components/schemas/<Name>`` pointer a node lives under, if any.

    Args:
        schema_pointer: Where a field's node lives.

    Returns:
        The component schema's own pointer, or ``None`` for an inline node.
    """
    if not schema_pointer.startswith(_SCHEMA_PREFIX):
        return None
    name = schema_pointer[len(_SCHEMA_PREFIX):].split("/", 1)[0]
    return f"{_SCHEMA_PREFIX}{name}" if name else None


def _refs(ids: Sequence[str], by_id: Dict[str, ConsumerRef], visible: bool) -> Optional[List[ConsumerRef]]:
    """Name the consumers behind a count, or hide them.

    Args:
        ids: Consumer ids, in first-seen order.
        by_id: Every projected consumer by id.
        visible: Whether the reader may see names.

    Returns:
        The consumers ordered by slug, or ``None`` when names are hidden.
    """
    if not visible:
        return None
    return sorted((by_id[i] for i in ids), key=lambda ref: ref.slug)


@dataclass
class _FieldSlot:
    """Accumulator for one field: where it lives and who declared it."""

    schema_pointer: str
    location: str
    ids: List[str] = dc_field(default_factory=list)


@dataclass
class _OperationSlot:
    """Accumulator for one operation: its identity, who declared it, and its fields."""

    method: str
    path: str
    operation_id: Optional[str]
    ids: List[str] = dc_field(default_factory=list)
    fields: Dict[str, _FieldSlot] = dc_field(default_factory=dict)


def _add(ids: List[str], consumer_id: str) -> None:
    """Record a consumer once, keeping first-seen order."""
    if consumer_id not in ids:
        ids.append(consumer_id)


def project_consumer_usage(
    summaries: Sequence[ConsumerSummary],
    *,
    version_record_id: str,
    version_label: Optional[str],
    consumers_visible: bool,
) -> ConsumerUsageResponse:
    """Project the registry's current contracts onto one revision's pointers.

    Args:
        summaries: Every live consumer of the project with its current contract.
        version_record_id: The revision to project onto.
        version_label: That revision's label.
        consumers_visible: Whether the reader holds ``consumer_contracts:view``.

    Returns:
        The usage: counts always, names only when ``consumers_visible``.
    """
    by_id: Dict[str, ConsumerRef] = {}
    operations: Dict[str, _OperationSlot] = {}
    schemas: Dict[str, List[str]] = {}
    other_version = 0
    undeclared = 0

    for summary in summaries:
        contract = summary.contract
        if contract is None:
            undeclared += 1
            continue
        if str(contract.version_id or "") != version_record_id:
            other_version += 1
            continue
        consumer = summary.consumer
        by_id[consumer.id] = ConsumerRef(id=consumer.id, slug=consumer.slug, name=consumer.name)
        for operation in contract.surface.operations:
            slot = operations.setdefault(
                operation.pointer,
                _OperationSlot(operation.method, operation.path, operation.operation_id),
            )
            _add(slot.ids, consumer.id)
            for field in operation.fields:
                entry = slot.fields.setdefault(
                    field.pointer, _FieldSlot(field.schema_pointer, field.location)
                )
                _add(entry.ids, consumer.id)
                root = _schema_root(field.schema_pointer)
                if root is not None:
                    _add(schemas.setdefault(root, []), consumer.id)

    return ConsumerUsageResponse(
        version_record_id=version_record_id,
        version_label=version_label,
        consumers_visible=consumers_visible,
        consumer_count=len(by_id),
        other_version_consumer_count=other_version,
        undeclared_consumer_count=undeclared,
        operations=[
            OperationUsage(
                pointer=pointer,
                method=slot.method,
                path=slot.path,
                operation_id=slot.operation_id,
                consumer_count=len(slot.ids),
                consumers=_refs(slot.ids, by_id, consumers_visible),
                fields=[
                    FieldUsage(
                        pointer=field_pointer,
                        schema_pointer=entry.schema_pointer,
                        location=entry.location,
                        consumer_count=len(entry.ids),
                        consumers=_refs(entry.ids, by_id, consumers_visible),
                    )
                    for field_pointer, entry in sorted(slot.fields.items())
                ],
            )
            for pointer, slot in sorted(operations.items())
        ],
        schemas=[
            SchemaUsage(
                schema_pointer=pointer,
                consumer_count=len(ids),
                consumers=_refs(ids, by_id, consumers_visible),
            )
            for pointer, ids in sorted(schemas.items())
        ],
    )
