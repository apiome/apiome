"""COBOL copybook lint pack — MFI-21.1 (#3991).

Native, deterministic quality rules for COBOL copybook record layouts, layered on the canonical
lint engine (MFI-4.1 :mod:`app.lint_engine`) the way the ONC RPC pack (:mod:`app.oncrpc_lint`) is.
The :class:`CobolCopybookRulePack` is registered under the ``cobolcopybook`` format key, so it runs
with the always-on common pack on every copybook item.

The rules read the record the normalizer kept (``extras["cobolcopybook_tree"]``, rebuilt by
:func:`~app.cobolcopybook_fingerprint.record_tree`) and its storage layout
(:func:`~app.cobolcopybook_layout.compute_layout`), because what makes a copybook risky — two
layouts over one span of bytes, a table whose size is a runtime value — is positional, and the
canonical field list alone does not show it. Each finding's ``path`` is the item's qualified name
from the record (``PAYMENT-RECORD.CARD-DETAIL``):

* **cobolcopybook.redefines-target-declared** (warning) — a ``REDEFINES`` naming no earlier item
  of the same group: the overlay lives in a copybook this one is copied into, or is a typo, and
  its offset cannot be known from this file.
* **cobolcopybook.redefines-fits** (warning) — a redefining layout larger than the item it
  redefines: below level 01 compilers reject it, and a reader of the larger layout runs into the
  next item's bytes.
* **cobolcopybook.redefines-discriminated** (info) — an *ambiguous* overlay: no item declared
  before it carries enough 88-level conditions to say which layout holds data, so a reader has to
  guess (or know a rule the copybook does not state).
* **cobolcopybook.redefines-variable** (warning) — a ``REDEFINES`` item, or the item it redefines,
  holds an ``OCCURS … DEPENDING ON`` table, which COBOL does not allow to be overlaid.
* **cobolcopybook.odo-controller-declared** (warning) — a ``DEPENDING ON`` naming an item the
  copybook does not declare.
* **cobolcopybook.odo-controller-precedes** (warning) — the ``DEPENDING ON`` controller is
  declared after the table, or inside it: a reader meets the table before the count that sizes it.
* **cobolcopybook.odo-trailing-items** (info) — items follow a variable-length table, so their
  offsets vary at run time (a *complex* ODO); many readers and converters refuse it.
* **cobolcopybook.duplicate-name** (warning) — a data name (other than ``FILLER``) declared more
  than once: programs must qualify it, and the catalog tells the items apart only by position.
* **cobolcopybook.storage-sized** (warning) — an elementary item whose storage length cannot be
  computed (an unsized PICTURE symbol such as ``N``, an unknown USAGE, or no PICTURE), which
  leaves every later offset unknown.
* **cobolcopybook.packed-odd-digits** (info) — a ``COMP-3`` item with an even digit count: packed
  decimal stores an odd count in whole bytes, so the leading half-byte is wasted and may hold
  garbage a reader trips on.
* **cobolcopybook.filler-unused** (info) — a ``FILLER``: bytes no program can read by name.
  Spare room is safe to carve new fields from; data held there should be named.
* **cobolcopybook.condition-values-unique** (warning) — two 88-level conditions of one item test
  the same value, so the value cannot tell them apart.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .canonical_model import CanonicalApi
from .cobolcopybook_fingerprint import record_tree
from .cobolcopybook_layout import BASIS_PACKED, FieldLayout, compute_layout
from .cobolcopybook_parser import CobolField
from .lint_engine import LintRule, RulePack

__all__ = ["CobolCopybookRulePack", "FILLER", "walk_record"]

#: The data name of storage no program addresses by name.
FILLER = "FILLER"

#: A visit of one item: ``(item, parent, qualified path, index among the parent's children)``.
_Visit = Tuple[CobolField, Optional[CobolField], str, int]


def walk_record(root: CobolField) -> Iterator[_Visit]:
    """Every item of a record, depth first in source order.

    Args:
        root: The level-01 item.

    Yields:
        ``(item, parent, path, index)``: ``path`` is the dotted chain of names from the record
        (``PAYMENT-RECORD.CARD-DETAIL.CARD-NUMBER``); ``parent`` is ``None`` and ``index`` ``0`` for
        the root.
    """

    def visit(field: CobolField, parent: Optional[CobolField], path: str, index: int) -> Iterator[_Visit]:
        yield field, parent, path, index
        for position, child in enumerate(field.children):
            yield from visit(child, field, f"{path}.{child.name}", position)

    yield from visit(root, None, root.name, 0)


def _lower_first(reason: Optional[str]) -> str:
    """A layout reason as the second half of a sentence."""
    if not reason:
        return "it cannot be sized."
    return reason[0].lower() + reason[1:]


#: The last :func:`_record` answer, keyed by the tree template it was built from (held, so its id stays
#: unique). Every rule of one lint run asks for the same record; rebuilding the tree and its layout per
#: rule cost seconds on a large copybook.
_LAST_RECORD: Optional[Tuple[Any, Optional[Tuple[CobolField, Dict[int, FieldLayout]]]]] = None


def _record(api: CanonicalApi) -> Optional[Tuple[CobolField, Dict[int, FieldLayout]]]:
    """The record and its layout, or ``None`` when the model carries no copybook tree.

    Rules only read the tree, so the answer for the same template object is reused.
    """
    global _LAST_RECORD
    template = api.extras.get("cobolcopybook_tree")
    cached = _LAST_RECORD
    if cached is not None and template is not None and cached[0] is template:
        return cached[1]
    root = record_tree(api)
    result = None if root is None else (root, compute_layout(root))
    _LAST_RECORD = (template, result)
    return result


def _contains_odo(field: CobolField) -> bool:
    """True when ``field`` or anything under it is an ``OCCURS … DEPENDING ON`` table."""
    return field.depending_on is not None or any(_contains_odo(child) for child in field.children)


def _redefined_sibling(field: CobolField, parent: Optional[CobolField], index: int) -> Optional[CobolField]:
    """The earlier sibling ``field`` redefines, or ``None`` when no earlier sibling has that name."""
    if parent is None or not field.redefines:
        return None
    for sibling in parent.children[:index]:
        if sibling.name == field.redefines:
            return sibling
    return None


def _check_redefines_target_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A REDEFINES must name an earlier item of the same group."""
    record = _record(api)
    if record is None:
        return
    for field, parent, path, index in walk_record(record[0]):
        if field.redefines and parent is not None and _redefined_sibling(field, parent, index) is None:
            yield (
                path,
                f"{field.name} redefines {field.redefines}, which is not declared before it in "
                f"{parent.name}; the overlay's offset cannot be known from this copybook. Declare the "
                "redefined item first, or correct the name.",
            )


def _check_redefines_fits(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A redefining layout must not be larger than the item it redefines."""
    record = _record(api)
    if record is None:
        return
    root, layouts = record
    for field, parent, path, index in walk_record(root):
        target = _redefined_sibling(field, parent, index)
        if target is None or field.level == 1:
            continue
        own, theirs = layouts.get(id(field)), layouts.get(id(target))
        if own is None or theirs is None or own.total_length is None or theirs.total_length is None:
            continue
        if own.total_length > theirs.total_length:
            yield (
                path,
                f"{field.name} needs {own.total_length} bytes but redefines {target.name}, which has "
                f"{theirs.total_length}; a reader of {field.name} runs into the next item's storage. "
                f"Shrink it, or enlarge {target.name}.",
            )


def _check_redefines_discriminated(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """An overlay needs an earlier item whose 88-levels say which layout holds data.

    One pass in source order: the most 88-level conditions any elementary item declared so far is
    enough to decide (an earlier item with at least as many conditions as the overlay has layouts),
    and each group's ``REDEFINES`` targets are indexed once — the check was quadratic in the record.
    """
    record = _record(api)
    if record is None:
        return
    root = record[0]
    redefined_by: Dict[int, Dict[str, List[CobolField]]] = {}
    most_conditions = 0
    for field, parent, path, _index in walk_record(root):
        if parent is not None and not field.redefines:
            by_target = redefined_by.get(id(parent))
            if by_target is None:
                by_target = {}
                for child in parent.children:
                    if child.redefines:
                        by_target.setdefault(child.redefines, []).append(child)
                redefined_by[id(parent)] = by_target
            layouts = by_target.get(field.name)
            if layouts and most_conditions < len(layouts):
                names = ", ".join(c.name for c in layouts)
                yield (
                    path,
                    f"{field.name} is laid out {len(layouts) + 1} ways (redefined by {names}), but no item "
                    "declared before it has enough 88-level conditions to say which layout holds data. Add "
                    "a type code with one condition per layout.",
                )
        if not field.children and field.conditions:
            most_conditions = max(most_conditions, len(field.conditions))


def _check_redefines_variable(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """An OCCURS DEPENDING ON table cannot be redefined or redefine."""
    record = _record(api)
    if record is None:
        return
    for field, parent, path, index in walk_record(record[0]):
        target = _redefined_sibling(field, parent, index)
        if target is None:
            continue
        holder = field if _contains_odo(field) else target if _contains_odo(target) else None
        if holder is not None:
            yield (
                path,
                f"{holder.name} holds a table that varies in size (OCCURS … DEPENDING ON), and COBOL "
                f"does not allow such an item in a REDEFINES ({field.name} REDEFINES {target.name}). "
                "Make the table fixed, or move it out of the overlay.",
            )


def _check_odo_controller_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A DEPENDING ON must name an item this copybook declares."""
    record = _record(api)
    if record is None:
        return
    visits = list(walk_record(record[0]))
    names = {field.name for field, *_ in visits}
    for field, _parent, path, _index in visits:
        if field.depending_on and field.depending_on not in names:
            yield (
                path,
                f"{field.name} DEPENDING ON {field.depending_on}, which this copybook does not declare; "
                "the table's size cannot be read from this file alone.",
            )


def _check_odo_controller_precedes(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """The DEPENDING ON controller must be declared before the table, outside it."""
    record = _record(api)
    if record is None:
        return
    visits = list(walk_record(record[0]))
    for position, (field, _parent, path, _index) in enumerate(visits):
        if not field.depending_on:
            continue
        earlier = {item.name for item, *_ in visits[:position]}
        declared = {item.name for item, *_ in visits}
        if field.depending_on in declared and field.depending_on not in earlier:
            yield (
                path,
                f"{field.name} DEPENDING ON {field.depending_on}, which is declared after the table or "
                "inside it; a reader meets the table before the count that sizes it. Declare the count "
                "first.",
            )


def _check_odo_trailing_items(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Items after a variable-length table have offsets that vary at run time."""
    record = _record(api)
    if record is None:
        return
    root, layouts = record
    for field, parent, path, index in walk_record(root):
        if field.depending_on is None or parent is None:
            continue
        trailing = [c.name for c in parent.children[index + 1 :] if not c.redefines]
        if trailing:
            yield (
                path,
                f"{', '.join(trailing)} follow{'s' if len(trailing) == 1 else ''} the variable-length "
                f"table {field.name}, so their offsets change with {field.depending_on}; many readers "
                "and converters refuse this. Move the table to the end of the record.",
            )


def _check_duplicate_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A data name other than FILLER should be declared once."""
    record = _record(api)
    if record is None:
        return
    seen: Dict[str, str] = {}
    for field, _parent, path, _index in walk_record(record[0]):
        if field.name.upper() == FILLER:
            continue
        if field.name in seen:
            yield (
                path,
                f"{field.name} is also declared at {seen[field.name]}; programs must qualify it "
                "(… OF …) and the catalog tells the two apart only by position. Rename one.",
            )
        else:
            seen[field.name] = path


def _check_storage_sized(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every elementary item's storage should be computable."""
    record = _record(api)
    if record is None:
        return
    root, layouts = record
    for field, _parent, path, _index in walk_record(root):
        if field.children:
            continue
        layout = layouts.get(id(field))
        if layout is not None and layout.length is None:
            yield (
                path,
                f"The storage of {field.name} is not computed: {_lower_first(layout.reason)} Every "
                "offset after it is unknown too.",
            )


def _check_packed_odd_digits(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A COMP-3 item should declare an odd number of digits."""
    record = _record(api)
    if record is None:
        return
    root, layouts = record
    for field, _parent, path, _index in walk_record(root):
        layout = layouts.get(id(field))
        size = layout.picture if layout is not None else None
        if size is None or size.basis != BASIS_PACKED or not size.digits or size.digits % 2:
            continue
        yield (
            path,
            f"{field.name} is packed decimal with {size.digits} digits; packed storage holds an odd "
            f"count in whole bytes, so {size.length} bytes hold {size.digits + 1} and the leading "
            f"half-byte is wasted. Declare {size.digits + 1} digits.",
        )


def _check_filler_unused(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A FILLER is storage no program can read by name."""
    record = _record(api)
    if record is None:
        return
    root, layouts = record
    for field, _parent, path, _index in walk_record(root):
        if field.name.upper() != FILLER:
            continue
        layout = layouts.get(id(field))
        where = (
            f"{layout.total_length} bytes at offset {layout.offset}"
            if layout is not None and layout.offset is not None and layout.total_length is not None
            else "storage"
        )
        yield (
            path,
            f"FILLER reserves {where} that no program can read by name. If it is spare room, new "
            "fields can be carved from it without moving anything; if it holds data, name it.",
        )


def _check_condition_values_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Two 88-levels of one item should not test the same value."""
    record = _record(api)
    if record is None:
        return
    for field, _parent, path, _index in walk_record(record[0]):
        seen: Dict[str, str] = {}
        for condition in field.conditions:
            if condition.value in seen:
                yield (
                    f"{path}.{condition.name}",
                    f"88 {condition.name} tests the same value as 88 {seen[condition.value]} "
                    f"({condition.value!r}); the value of {field.name} cannot tell them apart.",
                )
            else:
                seen[condition.value] = condition.name


class CobolCopybookRulePack(RulePack, register=True):
    """Native rules for COBOL copybook record layouts (see the module docstring)."""

    format = "cobolcopybook"
    pack_id = "cobolcopybook"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="cobolcopybook.redefines-target-declared",
            category="reference",
            severity="warning",
            description="A REDEFINES must name an earlier item of the same group.",
            check=_check_redefines_target_declared,
        ),
        LintRule(
            rule_id="cobolcopybook.redefines-fits",
            category="structure",
            severity="warning",
            description="A redefining layout must not be larger than the item it redefines.",
            check=_check_redefines_fits,
        ),
        LintRule(
            rule_id="cobolcopybook.redefines-discriminated",
            category="structure",
            severity="info",
            description="A REDEFINES overlay needs an earlier item whose 88-levels say which layout holds data.",
            check=_check_redefines_discriminated,
        ),
        LintRule(
            rule_id="cobolcopybook.redefines-variable",
            category="structure",
            severity="warning",
            description="An OCCURS DEPENDING ON table cannot be redefined or redefine.",
            check=_check_redefines_variable,
        ),
        LintRule(
            rule_id="cobolcopybook.odo-controller-declared",
            category="reference",
            severity="warning",
            description="A DEPENDING ON must name an item the copybook declares.",
            check=_check_odo_controller_declared,
        ),
        LintRule(
            rule_id="cobolcopybook.odo-controller-precedes",
            category="structure",
            severity="warning",
            description="A DEPENDING ON controller must be declared before its table, outside it.",
            check=_check_odo_controller_precedes,
        ),
        LintRule(
            rule_id="cobolcopybook.odo-trailing-items",
            category="compatibility",
            severity="info",
            description="Items after a variable-length table have offsets that vary at run time.",
            check=_check_odo_trailing_items,
        ),
        LintRule(
            rule_id="cobolcopybook.duplicate-name",
            category="naming",
            severity="warning",
            description="A data name other than FILLER should be declared once.",
            check=_check_duplicate_name,
        ),
        LintRule(
            rule_id="cobolcopybook.storage-sized",
            category="structure",
            severity="warning",
            description="Every elementary item's storage length should be computable.",
            check=_check_storage_sized,
        ),
        LintRule(
            rule_id="cobolcopybook.packed-odd-digits",
            category="quality",
            severity="info",
            description="A COMP-3 item should declare an odd number of digits.",
            check=_check_packed_odd_digits,
        ),
        LintRule(
            rule_id="cobolcopybook.filler-unused",
            category="documentation",
            severity="info",
            description="A FILLER is storage no program can read by name.",
            check=_check_filler_unused,
        ),
        LintRule(
            rule_id="cobolcopybook.condition-values-unique",
            category="structure",
            severity="warning",
            description="Two 88-level conditions of one item should not test the same value.",
            check=_check_condition_values_unique,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the COBOL copybook native rules in deterministic execution order."""
        return list(self._RULES)
