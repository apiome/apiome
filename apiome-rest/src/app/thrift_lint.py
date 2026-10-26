"""Apache Thrift lint pack — MFI-19.3 (#3981).

Native, deterministic quality rules for Thrift IDL, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) the way the Protobuf pack (:mod:`app.proto_lint`) is. The
:class:`ThriftRulePack` is registered under the ``thrift`` format key, so it runs with the
always-on common pack on every Thrift artifact. The rules read only the canonical model:

* **thrift.namespace-declared** (info) — no ``namespace``: generated code lands in the default
  package / module of every language.
* **thrift.field-no-required** (warning) — ``required`` is a one-way door: the field can never
  be removed, and a peer that omits it is rejected (Apache Thrift's own guidance is to avoid
  it).
* **thrift.unique-field-ids** (error) — two fields of a struct, two parameters of a method or
  two exceptions of a method share an id; the Thrift compiler refuses this.
* **thrift.enum-explicit-values** (warning) — an enum value without ``= N`` takes its number
  from its position, so reordering or inserting values silently changes the wire.
* **thrift.oneway-void** (error) — a ``oneway`` method must return ``void`` and declare no
  ``throws``: no reply is ever sent.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Tuple

from .canonical_model import CanonicalApi, MessageRole, TypeKind
from .lint_engine import LintRule, RulePack

__all__ = ["ThriftRulePack"]


def _duplicates(ids: Iterable[object]) -> List[object]:
    """The ids that occur more than once, in sorted order."""
    counts = Counter(i for i in ids if i is not None)
    return sorted((i for i, n in counts.items() if n > 1), key=str)


def _check_namespace_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """The document should declare a ``namespace``."""
    if not api.extras.get("thrift_namespaces"):
        yield (
            "namespace",
            "No 'namespace' is declared; generated code lands in each language's default "
            "package. Add one, e.g. 'namespace java com.example.orders.v1'.",
        )


def _check_field_no_required(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """No struct field should be ``required``."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        for field in sorted(api_type.fields, key=lambda f: f.key):
            if field.extras.get("thrift_required") is True:
                yield (
                    f"types.{api_type.key}.fields.{field.key}",
                    f"Field '{field.name}' is 'required'; a required field can never be removed "
                    "and peers that omit it are rejected — prefer 'optional'.",
                )


def _check_unique_field_ids(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Field, parameter and exception ids must be unique within their struct or method."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        for field_id in _duplicates(f.field_number for f in api_type.fields):
            yield (
                f"types.{api_type.key}",
                f"Field id {field_id} is used by more than one field of '{api_type.name}'.",
            )
    for service in sorted(api.services, key=lambda s: s.key):
        for operation in sorted(service.operations, key=lambda o: o.key):
            path = f"services.{service.key}.operations.{operation.key}"
            params = [
                p.get("id")
                for m in operation.messages
                if m.role is MessageRole.REQUEST
                for p in (m.extras.get("thrift_parameters") or [])
                if isinstance(p, dict)
            ]
            for param_id in _duplicates(params):
                yield (path, f"Parameter id {param_id} is used more than once in '{operation.name}'.")
            throws = [m.extras.get("thrift_throw_id") for m in operation.messages if m.role is MessageRole.ERROR]
            for throw_id in _duplicates(throws):
                yield (path, f"Exception id {throw_id} is used more than once in '{operation.name}' throws.")


def _check_enum_explicit_values(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every enum value should have an explicit number."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if api_type.kind is not TypeKind.ENUM:
            continue
        for value in sorted(api_type.enum_values, key=lambda v: v.key):
            if value.extras.get("thrift_implicit_value") is True:
                yield (
                    f"types.{api_type.key}.enum_values.{value.key}",
                    f"Enum value '{value.name}' has no explicit number; reordering or inserting "
                    f"values changes it on the wire. Write '{value.name} = {value.value}'.",
                )


def _check_oneway_void(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``oneway`` method returns ``void`` and throws nothing."""
    for service in sorted(api.services, key=lambda s: s.key):
        for operation in sorted(service.operations, key=lambda o: o.key):
            if operation.extras.get("thrift_oneway") is not True:
                continue
            replies = [m for m in operation.messages if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)]
            if replies:
                yield (
                    f"services.{service.key}.operations.{operation.key}",
                    f"Oneway method '{operation.name}' must return 'void' and declare no "
                    "'throws'; no reply is ever sent.",
                )


class ThriftRulePack(RulePack, register=True):
    """Native rules for Apache Thrift artifacts (see the module docstring)."""

    format = "thrift"
    pack_id = "thrift"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="thrift.namespace-declared",
            category="naming",
            severity="info",
            description="A Thrift document should declare a namespace.",
            check=_check_namespace_declared,
        ),
        LintRule(
            rule_id="thrift.field-no-required",
            category="structure",
            severity="warning",
            description="Fields should not be 'required'.",
            check=_check_field_no_required,
        ),
        LintRule(
            rule_id="thrift.unique-field-ids",
            category="structure",
            severity="error",
            description="Field, parameter and exception ids must be unique.",
            check=_check_unique_field_ids,
        ),
        LintRule(
            rule_id="thrift.enum-explicit-values",
            category="structure",
            severity="warning",
            description="Enum values should have explicit numbers.",
            check=_check_enum_explicit_values,
        ),
        LintRule(
            rule_id="thrift.oneway-void",
            category="structure",
            severity="error",
            description="A oneway method must return void and declare no throws.",
            check=_check_oneway_void,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the Thrift native rules in deterministic execution order."""
        return list(self._RULES)
