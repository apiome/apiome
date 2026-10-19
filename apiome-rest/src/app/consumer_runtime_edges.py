"""Declared versus observed: a consumer's runtime edges — RDG-1.8 (#5765).

A CTG-4.1 contract says which operations a consumer **declares** it uses. The usage index says which
operations it **calls**, once bindings (:mod:`app.consumer_binding`) attribute traffic to it. This
module compares the two, per consumer and per operation:

* ``declared_and_used`` — in the contract and called in the window: a confirmed edge;
* ``declared_unused`` — in the contract and never called in the window: a stale declaration, or a
  consumer whose traffic is not bound yet;
* ``used_undeclared`` — called but not in the contract: the edge a breaking-change analysis would
  otherwise miss. The UI offers "Add to contract" for it, which writes a new contract revision
  through the existing ``PUT …/contract`` path.

These are the edges the CDG-3 dependency graph draws and the Designer overlays project onto the
canvas. Calls no binding attributes are reported under the reserved ``anonymous`` consumer (all of
them ``used_undeclared``: nobody declared anything for them).

The module is pure. It takes the rows :func:`app.consumer_binding_store.usage_by_consumer` read from
``usage_daily`` and the consumers' current contracts, and its output depends on nothing else — the
same fixture always yields the same report, in the same order (operations by path, then method).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import ANONYMOUS_CONSUMER_SLUG, ConsumerContractSurface, RuntimeSummary

__all__ = [
    "CONTRACT_DECLARED",
    "CONTRACT_NONE",
    "CONTRACT_UNDECLARED",
    "ConsumerRuntime",
    "RuntimeConsumer",
    "RuntimeOperation",
    "RuntimeSummary",
    "UsageRow",
    "build_runtime",
    "build_runtime_report",
    "parse_operation_key",
]

#: The consumer has a current contract.
CONTRACT_DECLARED = "declared"
#: The consumer is registered but has declared nothing.
CONTRACT_UNDECLARED = "undeclared"
#: The reserved ``anonymous`` consumer: there is nothing it could declare.
CONTRACT_NONE = "none"


@dataclass(frozen=True)
class UsageRow:
    """One operation's calls attributed to one consumer over the window.

    Attributes:
        consumer_id: The consumer the binding named, or ``None`` for unattributed calls.
        operation_key: ``/paths/<escaped template>/<method>``.
        calls: Calls in the window.
        errors: Of them, 4xx and 5xx.
        last_seen: The newest UTC day with a call.
    """

    consumer_id: Optional[str]
    operation_key: str
    calls: int
    errors: int
    last_seen: date


@dataclass(frozen=True)
class RuntimeConsumer:
    """A consumer to report on.

    Attributes:
        consumer_id: Its id (``None`` for ``anonymous``).
        slug: Its handle.
        name: Its display name.
        contract: Its current contract surface, or ``None`` when it has declared none.
    """

    consumer_id: Optional[str]
    slug: str
    name: str
    contract: Optional[ConsumerContractSurface]


class RuntimeOperation(BaseModel):
    """One operation on one side of the comparison."""

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(description="/paths/<escaped template>/<method>.")
    method: str = Field(description="Lowercase HTTP method.")
    path: str = Field(description="Specification path template.")
    calls: int = Field(default=0, description="Calls in the window (0 for declared_unused).")
    errors: int = Field(default=0, description="Of them, responses with status 4xx or 5xx.")
    last_seen_day: Optional[str] = Field(default=None, description="Newest UTC day with a call.")


class ConsumerRuntime(BaseModel):
    """Declared versus observed for one consumer."""

    model_config = ConfigDict(extra="forbid")

    consumer_id: Optional[str] = Field(default=None, description="Null for the anonymous consumer.")
    slug: str
    name: str
    contract_state: str = Field(description="declared, undeclared, or none (anonymous).")
    since_day: str = Field(description="First UTC day of the window.")
    until_day: str = Field(description="Last UTC day of the window.")
    summary: RuntimeSummary
    declared_and_used: List[RuntimeOperation] = Field(default_factory=list)
    declared_unused: List[RuntimeOperation] = Field(default_factory=list)
    used_undeclared: List[RuntimeOperation] = Field(default_factory=list)


def _unescape(segment: str) -> str:
    """Undo JSON Pointer escaping (``~1`` → ``/``, then ``~0`` → ``~``)."""
    return segment.replace("~1", "/").replace("~0", "~")


def parse_operation_key(operation_key: str) -> Tuple[str, str]:
    """Split an operation pointer into its method and path template.

    Args:
        operation_key: ``/paths/<escaped template>/<method>``.

    Returns:
        ``(method, path)``. A key that is not shaped like one comes back as ``("", key)``.
    """
    if not operation_key.startswith("/paths/"):
        return "", operation_key
    escaped, _, method = operation_key[len("/paths/"):].rpartition("/")
    if not escaped:
        return "", operation_key
    return method, _unescape(escaped)


def _operation(key: str, *, method: str = "", path: str = "", row: Optional[UsageRow] = None) -> RuntimeOperation:
    """Build one report entry, falling back to the key for the method and path."""
    parsed_method, parsed_path = parse_operation_key(key)
    return RuntimeOperation(
        operation_key=key,
        method=method or parsed_method,
        path=path or parsed_path,
        calls=row.calls if row else 0,
        errors=row.errors if row else 0,
        last_seen_day=row.last_seen.isoformat() if row else None,
    )


def _sort(operations: Iterable[RuntimeOperation]) -> List[RuntimeOperation]:
    """Path, then method, then key — the stored contract order."""
    return sorted(operations, key=lambda op: (op.path, op.method, op.operation_key))


def _merge(rows: Iterable[UsageRow]) -> Dict[str, UsageRow]:
    """Collapse rows per operation (several bindings of one consumer add up to one consumer)."""
    merged: Dict[str, UsageRow] = {}
    for row in rows:
        seen = merged.get(row.operation_key)
        if seen is None:
            merged[row.operation_key] = row
            continue
        merged[row.operation_key] = UsageRow(
            consumer_id=row.consumer_id,
            operation_key=row.operation_key,
            calls=seen.calls + row.calls,
            errors=seen.errors + row.errors,
            last_seen=max(seen.last_seen, row.last_seen),
        )
    return merged


def build_runtime(
    consumer: RuntimeConsumer, rows: Sequence[UsageRow], *, since: date, until: date
) -> ConsumerRuntime:
    """Compare one consumer's contract with its attributed calls.

    Args:
        consumer: The consumer and its current contract.
        rows: Usage rows. Only those whose ``consumer_id`` equals the consumer's are used, so the
            whole project's rows may be passed.
        since: First day of the window (for the response).
        until: Last day of the window (for the response).

    Returns:
        The report, every list sorted by path then method.
    """
    used = _merge(row for row in rows if row.consumer_id == consumer.consumer_id and row.calls > 0)
    declared: Dict[str, Tuple[str, str]] = {}
    if consumer.contract is not None:
        for operation in consumer.contract.operations:
            declared[operation.pointer] = (operation.method, operation.path)

    both = [_operation(key, method=m, path=p, row=used[key]) for key, (m, p) in declared.items() if key in used]
    unused = [_operation(key, method=m, path=p) for key, (m, p) in declared.items() if key not in used]
    undeclared = [_operation(key, row=row) for key, row in used.items() if key not in declared]

    last_days = [row.last_seen for row in used.values()]
    if consumer.consumer_id is None:
        state = CONTRACT_NONE
    elif consumer.contract is not None:
        state = CONTRACT_DECLARED
    else:
        state = CONTRACT_UNDECLARED
    return ConsumerRuntime(
        consumer_id=consumer.consumer_id,
        slug=consumer.slug,
        name=consumer.name,
        contract_state=state,
        since_day=since.isoformat(),
        until_day=until.isoformat(),
        summary=RuntimeSummary(
            declared_and_used=len(both),
            declared_unused=len(unused),
            used_undeclared=len(undeclared),
            calls=sum(row.calls for row in used.values()),
            last_seen_day=max(last_days).isoformat() if last_days else None,
        ),
        declared_and_used=_sort(both),
        declared_unused=_sort(unused),
        used_undeclared=_sort(undeclared),
    )


def build_runtime_report(
    consumers: Sequence[RuntimeConsumer], rows: Sequence[UsageRow], *, since: date, until: date
) -> List[ConsumerRuntime]:
    """Every consumer's runtime edges, then the anonymous consumer's.

    Args:
        consumers: The project's consumers with their current contracts, in display order.
        rows: The project's usage rows for the window.
        since: First day of the window.
        until: Last day of the window.

    Returns:
        One report per consumer, in the order given, followed by ``anonymous`` (always present, so
        "how much traffic is still unattributed" has an answer even when it is zero).
    """
    reports = [build_runtime(consumer, rows, since=since, until=until) for consumer in consumers]
    anonymous = RuntimeConsumer(
        consumer_id=None, slug=ANONYMOUS_CONSUMER_SLUG, name="Anonymous", contract=None
    )
    reports.append(build_runtime(anonymous, rows, since=since, until=until))
    return reports
