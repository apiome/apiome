"""NACHA ACH control totals, declared versus observed — FMT-6.6 (#5450).

Every batch closes with a batch control record (``8``) and the file with a file control record
(``9``). Each declares totals about what it closes; this module recomputes every one of them from the
records actually present, following the X12 control-total contract
(:class:`app.edi_analysis_base.ControlCount`): the declaration is recorded beside the observation,
an unreadable declaration is ``None`` rather than zero, and a disagreement is stated, never fixed.

Batch control (``8``)
    entry/addenda count · entry hash · total debit · total credit
File control (``9``)
    batch count · block count · entry/addenda count · entry hash · total debit · total credit

The **entry hash** is recomputed rather than trusted: the sum of every entry's 8-digit receiving DFI
identification, keeping the rightmost ten digits. Debit and credit totals classify each entry by its
transaction code (:func:`app.nacha_records.credit_or_debit`), in cents. The **block count** is the
number of ten-record blocks the file's records fill, padding included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .edi_analysis_base import ControlCount, int_or_none
from .nacha_parser import NachaBatch, NachaEntry, NachaFile
from .nacha_records import BLOCKING_FACTOR, credit_or_debit

__all__ = [
    "ControlTotals",
    "HASH_MODULUS",
    "batch_control_counts",
    "control_counts",
    "control_totals_extras",
    "file_control_counts",
    "observed_totals",
]

#: The entry hash keeps the rightmost ten digits of the sum.
HASH_MODULUS = 10**10

#: Control field name → the phrase a mismatch message counts in.
_COUNTED: Dict[str, str] = {
    "entryAddendaCount": "entry and addenda records",
    "entryHash": "as the entry hash",
    "totalDebitEntryDollarAmount": "cents of debits",
    "totalCreditEntryDollarAmount": "cents of credits",
    "batchCount": "batches",
    "blockCount": "blocks",
}


@dataclass(frozen=True)
class ControlTotals:
    """What a set of entries actually adds up to.

    Attributes:
        entry_addenda_count: Entry detail records plus addenda records.
        entry_hash: Sum of receiving DFI identifications, rightmost ten digits.
        total_debit: Debit amounts in cents.
        total_credit: Credit amounts in cents.
    """

    entry_addenda_count: int
    entry_hash: int
    total_debit: int
    total_credit: int

    def by_field(self) -> Dict[str, int]:
        """The totals keyed by the control-record field names that declare them."""
        return {
            "entryAddendaCount": self.entry_addenda_count,
            "entryHash": self.entry_hash,
            "totalDebitEntryDollarAmount": self.total_debit,
            "totalCreditEntryDollarAmount": self.total_credit,
        }


def observed_totals(entries: Iterable[NachaEntry]) -> ControlTotals:
    """Recompute the four entry-level totals from the entries present.

    An entry whose routing prefix or amount is not numeric contributes nothing to the hash or the
    amount totals — it is still counted, and the analysis shows its value as written.

    Args:
        entries: The entries a control record closes.

    Returns:
        The observed :class:`ControlTotals`.
    """
    count = hash_sum = debit = credit = 0
    for entry in entries:
        count += 1 + len(entry.addenda)
        routing = int_or_none(entry.record.field("receivingDfiIdentification"))
        if routing is not None:
            hash_sum += routing
        amount = int_or_none(entry.record.field("amount")) or 0
        direction = credit_or_debit(entry.transaction_code)
        if direction == "debit":
            debit += amount
        elif direction == "credit":
            credit += amount
    return ControlTotals(
        entry_addenda_count=count,
        entry_hash=hash_sum % HASH_MODULUS,
        total_debit=debit,
        total_credit=credit,
    )


def _counts(
    subject: str, trailer: str, record_fields: Dict[str, str], observed: Dict[str, int]
) -> List[ControlCount]:
    """Pair each declared control field with its observation, in the record's field order."""
    return [
        ControlCount(
            subject=subject,
            counted=_COUNTED[name],
            trailer=f"{trailer}.{name}",
            declared=int_or_none(record_fields[name]),
            observed=value,
        )
        for name, value in observed.items()
    ]


def batch_control_counts(batch: NachaBatch) -> List[ControlCount]:
    """Every total a batch control record declares, beside its observation.

    Args:
        batch: The batch.

    Returns:
        Entry/addenda count, entry hash, total debit and total credit, in that order. Each
        :class:`~app.edi_analysis_base.ControlCount`'s ``trailer`` is ``batchControl.<field>``.
    """
    observed = observed_totals(batch.entries).by_field()
    declared = {name: batch.control.field(name) for name in observed}
    return _counts(f"batch {batch.batch_number}", "batchControl", declared, observed)


def file_control_counts(file: NachaFile) -> List[ControlCount]:
    """Every total the file control record declares, beside its observation.

    Args:
        file: The parsed file.

    Returns:
        Batch count, block count, then the four entry-level totals over every batch.
    """
    totals = observed_totals(entry for _, entry in file.all_entries()).by_field()
    observed: Dict[str, int] = {
        "batchCount": len(file.batches),
        "blockCount": -(-file.record_count // BLOCKING_FACTOR),
        **totals,
    }
    declared = {name: file.control.field(name) for name in observed}
    return _counts("the file", "fileControl", declared, observed)


def control_counts(file: NachaFile) -> List[ControlCount]:
    """Every control total in the file: each batch's, in order, then the file control's."""
    counts: List[ControlCount] = []
    for batch in file.batches:
        counts.extend(batch_control_counts(batch))
    counts.extend(file_control_counts(file))
    return counts


def _row(count: ControlCount) -> Dict[str, Optional[object]]:
    """One declared-versus-observed row for the canonical extras."""
    record, field = count.trailer.split(".", 1)
    return {
        "scope": count.subject,
        "record": record,
        "field": field,
        "declared": count.declared,
        "observed": count.observed,
        "consistent": count.consistent,
    }


def control_totals_extras(file: NachaFile) -> List[Dict[str, Optional[object]]]:
    """Every control total as a JSON-ready declared-versus-observed row.

    Args:
        file: The parsed file.

    Returns:
        One row per control field: ``scope`` (``batch 0000001`` / ``the file``), ``record``
        (``batchControl`` / ``fileControl``), ``field``, ``declared`` (``None`` when unreadable),
        ``observed`` and ``consistent`` (``None`` when nothing was declared).
    """
    return [_row(count) for count in control_counts(file)]
