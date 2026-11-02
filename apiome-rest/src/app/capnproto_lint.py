"""Cap'n Proto lint pack — MFI-19.4 (#3982).

Native, deterministic quality rules for Cap'n Proto schemas, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`CapnProtoRulePack` is registered under the ``capnproto`` format key, so it runs with the
always-on common pack on every Cap'n Proto artifact. The rules read only the canonical model:

* **capnproto.file-id-declared** (error) — no ``@0x…;`` file id: the schema compiler refuses a
  file without one (``capnp id`` generates it).
* **capnproto.unique-ordinals** (error) — two fields of a struct, two methods of an interface or
  two enumerants share an ``@N`` ordinal.
* **capnproto.contiguous-ordinals** (error) — a struct's, interface's or enum's ordinals do not
  run ``@0``, ``@1``, … without a gap; the compiler requires them to.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .lint_engine import LintRule, RulePack

__all__ = ["CapnProtoRulePack"]


def _ordinal_sets(api: CanonicalApi) -> Iterable[Tuple[str, str, List[int]]]:
    """``(path, what, ordinals)`` for every struct, enum and interface of ``api``."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if api_type.kind is TypeKind.ENUM:
            ordinals = [v.value for v in api_type.enum_values if isinstance(v.value, int)]
            yield f"types.{api_type.key}", f"enum '{api_type.name}'", ordinals
        elif api_type.kind is TypeKind.RECORD:
            ordinals = [f.field_number for f in api_type.fields if isinstance(f.field_number, int)]
            yield f"types.{api_type.key}", f"struct '{api_type.name}'", ordinals
    for service in sorted(api.services, key=lambda s: s.key):
        ordinals = [
            op.extras["capnp_slot"] for op in service.operations if isinstance(op.extras.get("capnp_slot"), int)
        ]
        yield f"services.{service.key}", f"interface '{service.name}'", ordinals


def _duplicates(ordinals: Sequence[int]) -> List[int]:
    return sorted(i for i, n in Counter(ordinals).items() if n > 1)


def _gap(ordinals: Sequence[int]) -> Optional[int]:
    """The first ordinal missing from ``@0 … @max``, or ``None`` when they run without a gap."""
    present = set(ordinals)
    return next((i for i in range(max(present) + 1) if i not in present), None) if present else None


def _check_file_id_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """The schema declares its ``@0x…;`` file id."""
    if not api.extras.get("capnp_file_id"):
        yield (
            "file_id",
            "No '@0x…;' file id is declared; the Cap'n Proto compiler refuses the file. Run "
            "'capnp id' and add the id it prints at the top of the file.",
        )


def _check_unique_ordinals(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """No two members of a struct, interface or enum share an ordinal."""
    for path, what, ordinals in _ordinal_sets(api):
        for ordinal in _duplicates(ordinals):
            yield path, f"Ordinal @{ordinal} is used more than once in {what}."


def _check_contiguous_ordinals(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Ordinals run from ``@0`` without a gap."""
    for path, what, ordinals in _ordinal_sets(api):
        if _duplicates(ordinals):
            continue  # reported by capnproto.unique-ordinals
        missing = _gap(ordinals)
        if missing is not None:
            yield path, f"Ordinal @{missing} is missing from {what}; ordinals must run from @0 without a gap."


class CapnProtoRulePack(RulePack, register=True):
    """Native rules for Cap'n Proto artifacts (see the module docstring)."""

    format = "capnproto"
    pack_id = "capnproto"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="capnproto.file-id-declared",
            category="structure",
            severity="error",
            description="A Cap'n Proto schema declares its @0x… file id.",
            check=_check_file_id_declared,
        ),
        LintRule(
            rule_id="capnproto.unique-ordinals",
            category="structure",
            severity="error",
            description="Ordinals must be unique within a struct, interface or enum.",
            check=_check_unique_ordinals,
        ),
        LintRule(
            rule_id="capnproto.contiguous-ordinals",
            category="structure",
            severity="error",
            description="Ordinals run from @0 without a gap.",
            check=_check_contiguous_ordinals,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the Cap'n Proto native rules in deterministic execution order."""
        return list(self._RULES)
