"""FlatBuffers lint pack — MFI-19.4 (#3982).

Native, deterministic quality rules for FlatBuffers schemas, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`FlatBuffersRulePack` is registered under the ``flatbuffers`` format key, so it runs with the
always-on common pack on every FlatBuffers artifact. The rules read only the canonical model:

* **flatbuffers.root-type-declared** (info) — no ``root_type``: ``flatc`` generates no
  ``GetRoot…`` accessor and a buffer has no declared entry table.
* **flatbuffers.namespace-declared** (info) — no ``namespace``: generated code lands in the
  global scope of every language.
* **flatbuffers.unique-field-ids** (error) — two fields (or a field and a deprecated slot) of a
  table share an id; ``flatc`` refuses this.
* **flatbuffers.explicit-ids-all-or-none** (error) — a table gives ``(id: N)`` to some fields but
  not others; ``flatc`` requires all or none.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .lint_engine import LintRule, RulePack
from .numbered_field_breaking import flatbuffers_wire_ids

__all__ = ["FlatBuffersRulePack"]


def _tables(api: CanonicalApi):
    return [t for t in sorted(api.types, key=lambda t: t.key) if t.extras.get("fbs_kind") == "table"]


def _check_root_type_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A schema with tables should declare its ``root_type``."""
    if _tables(api) and not api.extras.get("fbs_root_type"):
        yield (
            "root_type",
            "No 'root_type' is declared; flatc generates no root accessor and a buffer has no "
            "declared entry table. Add 'root_type <Table>;'.",
        )


def _check_namespace_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """The schema should declare a ``namespace``."""
    if not api.identity.namespace:
        yield (
            "namespace",
            "No 'namespace' is declared; generated code lands in the global scope. Add one, "
            "e.g. 'namespace Game.Monsters;'.",
        )


def _check_unique_field_ids(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Field ids — deprecated slots included — must be unique within a table."""
    union_keys = frozenset(t.key for t in api.types if t.kind is TypeKind.UNION)
    for table in _tables(api):
        ids: List[int] = list(flatbuffers_wire_ids(table, union_keys).values())
        ids += [int(key) for key in (table.extras.get("fbs_deprecated") or {}) if str(key).isdigit()]
        for field_id in sorted(i for i, n in Counter(ids).items() if n > 1):
            yield (
                f"types.{table.key}",
                f"Field id {field_id} is used more than once in table '{table.name}'.",
            )


def _check_explicit_ids_all_or_none(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A table gives ``(id: N)`` to every field or to none."""
    for table in _tables(api):
        if table.extras.get("fbs_mixed_ids") is True:
            yield (
                f"types.{table.key}",
                f"Table '{table.name}' gives '(id: N)' to some fields but not others; flatc "
                "requires either every field or none to declare an id.",
            )


class FlatBuffersRulePack(RulePack, register=True):
    """Native rules for FlatBuffers artifacts (see the module docstring)."""

    format = "flatbuffers"
    pack_id = "flatbuffers"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="flatbuffers.root-type-declared",
            category="structure",
            severity="info",
            description="A FlatBuffers schema should declare its root_type.",
            check=_check_root_type_declared,
        ),
        LintRule(
            rule_id="flatbuffers.namespace-declared",
            category="naming",
            severity="info",
            description="A FlatBuffers schema should declare a namespace.",
            check=_check_namespace_declared,
        ),
        LintRule(
            rule_id="flatbuffers.unique-field-ids",
            category="structure",
            severity="error",
            description="Field ids must be unique within a table.",
            check=_check_unique_field_ids,
        ),
        LintRule(
            rule_id="flatbuffers.explicit-ids-all-or-none",
            category="structure",
            severity="error",
            description="A table declares an id on every field or on none.",
            check=_check_explicit_ids_all_or_none,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the FlatBuffers native rules in deterministic execution order."""
        return list(self._RULES)
