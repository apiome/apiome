"""CORBA / OMG IDL lint pack — MFI-21.4 (#3994).

Native, deterministic quality rules for OMG IDL interface definitions, layered on the canonical
lint engine (MFI-4.1 :mod:`app.lint_engine`) the way the ONC RPC pack (:mod:`app.oncrpc_lint`)
is. The :class:`CorbaIdlRulePack` is registered under the ``corbaidl`` format key, so it runs
with the always-on common pack on every CORBA IDL artifact. The rules read the model
:class:`~app.corbaidl_normalizer.CorbaIdlNormalizer` builds: the interfaces as declared
(``extras["corbaidl_interfaces"]``), the typedefs (``extras["corbaidl_typedefs"]``) and the
struct / exception / enum types with each member's declared type (``corbaidl_type_expr``).

Most rules state what an IDL compiler (``idlj``, ``omniidl``, TAO's ``tao_idl``) refuses, so a
file that only passed the importer's lenient reader is caught before it reaches one:

* **corbaidl.type-resolves** (error) — a member, parameter, return or attribute type that is
  neither an IDL base type nor a typedef, struct, exception, enum or interface the file declares
  (usually a name from an ``#include`` d file, which is not read).
* **corbaidl.raises-declared** (error) — a ``raises`` clause naming something that is not a
  declared ``exception`` (OMG IDL 4.2 §7.4.3.4.1.2).
* **corbaidl.exception-as-type** (error) — an exception used as a member, parameter, return or
  attribute type: exceptions may only be raised (§7.4.3.4.1.3).
* **corbaidl.oneway-signature** (error) — a ``oneway`` operation that returns something, has an
  ``out`` / ``inout`` parameter or raises: no reply is ever sent (§7.4.3.4.1.1).
* **corbaidl.operation-names-unique** (error) — two operations or attribute accessors of an
  interface whose names differ only in case, or an inherited one redefined: IDL has no
  overloading and identifiers collide case-insensitively (§7.2.3).
* **corbaidl.member-names-unique** (error) — two members of a struct / exception, or two
  parameters of an operation, whose names differ only in case.
* **corbaidl.identifier-not-keyword** (error) — a declared name that is an IDL keyword
  compared case-insensitively (``short``, ``Sequence``, ``Object``…): compilers reject it unless
  it is escaped with a leading ``_`` (§7.2.3.1).
* **corbaidl.inheritance-acyclic** (error) — an interface that inherits from itself.
* **corbaidl.base-interface-declared** (warning) — a base interface the file does not declare:
  its operations are missing from the derived interface (it is probably in an ``#include``).
* **corbaidl.any-typed** (info) — an ``any`` value: the contract does not say what it carries,
  and a gRPC / OpenAPI migration can only write an opaque value.
* **corbaidl.object-reference-typed** (info) — the untyped ``Object`` reference: name the
  interface the caller gets back.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Set, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .corbaidl_emitter import OMG_IDL_KEYWORDS
from .corbaidl_normalizer import attribute_operations
from .lint_engine import LintRule, RulePack

__all__ = ["BASE_TYPES", "CorbaIdlRulePack", "referenced_names", "signatures"]

#: IDL base-type words (multi-word types are matched first by :func:`referenced_names`).
BASE_TYPES = frozenset(
    {
        "void",
        "boolean",
        "char",
        "wchar",
        "octet",
        "short",
        "long",
        "float",
        "double",
        "string",
        "wstring",
        "any",
        "Object",
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "fixed",
        "ValueBase",
    }
)

_MULTI_WORD = re.compile(r"\b(?:unsigned\s+)?long\s+long\b|\bunsigned\s+(?:long|short)\b|\blong\s+double\b")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")

#: A finding: ``(path, message)``.
Finding = Tuple[str, str]


def referenced_names(type_expr: str) -> List[str]:
    """The declared names a type expression refers to (base types and bounds left out).

    Args:
        type_expr: An IDL type expression (``sequence<Account, 10>``, ``unsigned long``).

    Returns:
        The identifiers that must be declared, in order (``["Account"]``).
    """
    stripped = _MULTI_WORD.sub(" ", type_expr or "")
    return [
        word
        for word in _IDENTIFIER.findall(stripped)
        if word not in BASE_TYPES and word not in ("sequence", "unsigned")
    ]


def _interfaces(api: CanonicalApi) -> List[Mapping[str, Any]]:
    listed = api.extras.get("corbaidl_interfaces")
    return [entry for entry in listed if isinstance(entry, Mapping)] if isinstance(listed, list) else []


def signatures(api: CanonicalApi) -> Iterator[Tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    """Every declared operation as ``(path, interface entry, operation entry)``.

    The path is the operation's canonical key (``<module>.<Interface>.<operation>``).
    """
    module = api.identity.namespace or api.extras.get("corbaidl_module")
    for interface in _interfaces(api):
        for operation in interface.get("operations") or []:
            if isinstance(operation, Mapping):
                path = ".".join(str(part) for part in (module, interface.get("name"), operation.get("name")) if part)
                yield path, interface, operation


def _interface_path(api: CanonicalApi, interface: Mapping[str, Any]) -> str:
    module = api.identity.namespace or api.extras.get("corbaidl_module")
    return ".".join(str(part) for part in (module, interface.get("name")) if part)


def _kinds(api: CanonicalApi) -> Dict[str, str]:
    """Declared type name → ``struct`` / ``exception`` / ``enum``."""
    kinds: Dict[str, str] = {}
    for type_ in api.types:
        kind = type_.extras.get("corbaidl_kind") or ("enum" if type_.kind is TypeKind.ENUM else "struct")
        kinds[type_.name] = str(kind)
    return kinds


def _uses(api: CanonicalApi) -> Iterator[Tuple[str, str]]:
    """Every ``(path, type expression)`` a member, parameter, return or attribute declares."""
    for type_ in api.types:
        for field in type_.fields:
            yield field.key, str(field.extras.get("corbaidl_type_expr") or "")
    for path, _, operation in signatures(api):
        if operation.get("return_type") not in (None, "void"):
            yield f"{path}#return", str(operation.get("return_type"))
        for param in operation.get("parameters") or []:
            yield f"{path}#param.{param.get('name')}", str(param.get("type") or "")
    for interface in _interfaces(api):
        for attribute in interface.get("attributes") or []:
            yield f"{_interface_path(api, interface)}.{attribute.get('name')}", str(attribute.get("type") or "")


def _check_type_resolves(api: CanonicalApi) -> Iterable[Finding]:
    """Every referenced type must be a base type or declared by the file."""
    declared = set(_kinds(api)) | {str(i.get("name")) for i in _interfaces(api)}
    declared |= set((api.extras.get("corbaidl_typedefs") or {}).keys())
    for path, expr in _uses(api):
        for name in referenced_names(expr):
            if name not in declared:
                yield (
                    path,
                    f"Type {name!r} is neither an IDL base type nor declared in this file (an #include is "
                    "not read); an IDL compiler rejects it and the catalog cannot resolve it.",
                )


def _check_raises_declared(api: CanonicalApi) -> Iterable[Finding]:
    """A ``raises`` clause may only name declared exceptions."""
    kinds = _kinds(api)
    for path, _, operation in signatures(api):
        for name in operation.get("raises") or []:
            kind = kinds.get(str(name))
            if kind == "exception":
                continue
            what = f"a {kind}, not an exception" if kind else "not declared in this file"
            yield (f"{path}#raises.{name}", f"raises names {name!r}, which is {what}; only exceptions can be raised.")


def _check_exception_as_type(api: CanonicalApi) -> Iterable[Finding]:
    """An exception may not be a member, parameter, return or attribute type."""
    exceptions = {name for name, kind in _kinds(api).items() if kind == "exception"}
    for path, expr in _uses(api):
        for name in referenced_names(expr):
            if name in exceptions:
                yield (path, f"Exception {name!r} is used as a type; IDL exceptions may only be raised.")


def _check_oneway_signature(api: CanonicalApi) -> Iterable[Finding]:
    """A ``oneway`` operation returns nothing, takes only ``in`` parameters and raises nothing."""
    for path, _, operation in signatures(api):
        if not operation.get("oneway"):
            continue
        problems: List[str] = []
        if operation.get("return_type") not in (None, "void"):
            problems.append(f"returns {operation.get('return_type')}")
        outs = [p.get("name") for p in operation.get("parameters") or [] if p.get("direction") != "in"]
        if outs:
            problems.append(f"has out/inout parameter(s) {', '.join(map(str, outs))}")
        if operation.get("raises"):
            problems.append("has a raises clause")
        if problems:
            yield (
                path,
                f"oneway operation {operation.get('name')!r} {'; '.join(problems)}; no reply is ever sent, so "
                "IDL allows only a void, in-only, raise-free oneway.",
            )


def _members(entry: Mapping[str, Any]) -> List[str]:
    names = [str(op.get("name")) for op in entry.get("operations") or []]
    for attribute in entry.get("attributes") or []:
        names.extend(attribute_operations(str(attribute.get("name")), bool(attribute.get("readonly"))))
    return names


def _ancestors(name: str, by_name: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """The interfaces ``name`` inherits from, depth-first in declaration order, each once.

    A base reached twice (the diamond case), an undeclared base and a cycle back to an interface
    already on the walk are not followed again, so the walk always ends.
    """
    order: List[str] = []

    def walk(current: str) -> None:
        for base in (by_name.get(current) or {}).get("bases") or []:
            if base in by_name and base != name and base not in order:
                order.append(base)
                walk(base)

    walk(name)
    return order


def _check_operation_names_unique(api: CanonicalApi) -> Iterable[Finding]:
    """No two operations / accessors of an interface (own or inherited) may collide."""
    by_name = {str(i.get("name")): i for i in _interfaces(api)}
    for name, entry in by_name.items():
        ancestors = _ancestors(name, by_name)
        origins: Dict[str, Tuple[str, str]] = {}
        reported: Set[str] = set()
        for origin in [name, *ancestors]:
            for member in _members(by_name[origin]):
                key = member.lower()
                first = origins.get(key)
                if first is None:
                    origins[key] = (member, origin)
                    continue
                if key in reported:
                    continue
                reported.add(key)
                where = "itself" if first[1] == origin else f"{first[1]!r} and {origin!r}"
                yield (
                    f"{_interface_path(api, entry)}.{member}",
                    f"Interface {name!r} gets {first[0]!r} and {member!r} from {where}; IDL has no overloading "
                    "and names that differ only in case collide.",
                )


def _case_duplicates(names: Iterable[str]) -> List[str]:
    seen: Dict[str, str] = {}
    duplicates: List[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            duplicates.append(name)
        else:
            seen[key] = name
    return duplicates


def _check_member_names_unique(api: CanonicalApi) -> Iterable[Finding]:
    """Struct / exception members and an operation's parameters must not collide by case."""
    for type_ in api.types:
        ordered = sorted(type_.fields, key=lambda f: f.field_number or 0)
        for name in _case_duplicates(f.name for f in ordered):
            yield (
                f"{type_.key}.{name}",
                f"Member {name!r} of {type_.name!r} collides with another (case-insensitively).",
            )
    for path, _, operation in signatures(api):
        for name in _case_duplicates(str(p.get("name")) for p in operation.get("parameters") or []):
            yield (f"{path}#param.{name}", f"Parameter {name!r} collides with another (case-insensitively).")


def _declared_names(api: CanonicalApi) -> Iterator[Tuple[str, str]]:
    """Every ``(path, identifier)`` the file declares: types, members, enumerators, interfaces,
    operations, parameters and attributes."""
    for type_ in api.types:
        yield type_.key, type_.name
        for field in type_.fields:
            yield field.key, field.name
        for value in type_.enum_values:
            yield value.key, value.name
    for interface in _interfaces(api):
        path = _interface_path(api, interface)
        yield path, str(interface.get("name"))
        for attribute in interface.get("attributes") or []:
            yield f"{path}.{attribute.get('name')}", str(attribute.get("name"))
    for path, _, operation in signatures(api):
        yield path, str(operation.get("name"))
        for param in operation.get("parameters") or []:
            yield f"{path}#param.{param.get('name')}", str(param.get("name"))


def _check_identifier_not_keyword(api: CanonicalApi) -> Iterable[Finding]:
    """No declared name may be an IDL keyword (case-insensitively)."""
    for path, name in _declared_names(api):
        if name.lower() in OMG_IDL_KEYWORDS:
            yield (
                path,
                f"{name!r} is the IDL keyword {name.lower()!r} (identifiers are compared with keywords "
                f"case-insensitively); an IDL compiler rejects it. Rename it or escape it as '_{name}'.",
            )


def _check_inheritance_acyclic(api: CanonicalApi) -> Iterable[Finding]:
    """An interface may not (transitively) inherit from itself."""
    by_name = {str(i.get("name")): i for i in _interfaces(api)}
    for name, entry in by_name.items():
        reached: Set[str] = set()
        todo = list(entry.get("bases") or [])
        while todo:
            current = todo.pop()
            if current in reached or current not in by_name:
                continue
            reached.add(current)
            todo.extend(by_name[current].get("bases") or [])
        if name in reached:
            yield (_interface_path(api, entry), f"Interface {name!r} inherits from itself through its bases.")


def _check_base_interface_declared(api: CanonicalApi) -> Iterable[Finding]:
    """A base interface should be declared in the file."""
    declared = {str(i.get("name")) for i in _interfaces(api)}
    for entry in _interfaces(api):
        for base in entry.get("bases") or []:
            if base not in declared:
                yield (
                    _interface_path(api, entry),
                    f"Base interface {base!r} is not declared in this file (an #include is not read); the "
                    "operations it gives the interface are missing from the catalog.",
                )


def _typed(api: CanonicalApi, base: str, message: str) -> Iterable[Finding]:
    pattern = re.compile(rf"\b{re.escape(base)}\b")
    for path, expr in _uses(api):
        if pattern.search(expr):
            yield (path, message)


def _check_any_typed(api: CanonicalApi) -> Iterable[Finding]:
    """An ``any`` value hides what it carries."""
    yield from _typed(
        api,
        "any",
        "The value is typed any; the contract does not say what it carries, and a gRPC or OpenAPI "
        "migration can only write an opaque value. Use a struct or union.",
    )


def _check_object_reference_typed(api: CanonicalApi) -> Iterable[Finding]:
    """The untyped ``Object`` reference hides which interface the caller gets."""
    yield from _typed(
        api,
        "Object",
        "The value is the untyped Object reference; name the interface (a typed reference) so callers "
        "know what they can invoke on it.",
    )


class CorbaIdlRulePack(RulePack, register=True):
    """Native rules for CORBA / OMG IDL artifacts (see the module docstring)."""

    format = "corbaidl"
    pack_id = "corbaidl"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="corbaidl.type-resolves",
            category="structure",
            severity="error",
            description="Every type must be an IDL base type or declared in the file.",
            check=_check_type_resolves,
        ),
        LintRule(
            rule_id="corbaidl.raises-declared",
            category="structure",
            severity="error",
            description="A raises clause may only name declared exceptions.",
            check=_check_raises_declared,
        ),
        LintRule(
            rule_id="corbaidl.exception-as-type",
            category="structure",
            severity="error",
            description="An exception may only be raised, not used as a type.",
            check=_check_exception_as_type,
        ),
        LintRule(
            rule_id="corbaidl.oneway-signature",
            category="structure",
            severity="error",
            description="A oneway operation returns void, takes only in parameters and raises nothing.",
            check=_check_oneway_signature,
        ),
        LintRule(
            rule_id="corbaidl.operation-names-unique",
            category="naming",
            severity="error",
            description="An interface's operations and attributes, inherited ones included, must not collide.",
            check=_check_operation_names_unique,
        ),
        LintRule(
            rule_id="corbaidl.member-names-unique",
            category="naming",
            severity="error",
            description="Struct members and operation parameters must not collide case-insensitively.",
            check=_check_member_names_unique,
        ),
        LintRule(
            rule_id="corbaidl.identifier-not-keyword",
            category="naming",
            severity="error",
            description="A declared name must not be an IDL keyword (compared case-insensitively).",
            check=_check_identifier_not_keyword,
        ),
        LintRule(
            rule_id="corbaidl.inheritance-acyclic",
            category="structure",
            severity="error",
            description="An interface may not inherit from itself.",
            check=_check_inheritance_acyclic,
        ),
        LintRule(
            rule_id="corbaidl.base-interface-declared",
            category="structure",
            severity="warning",
            description="A base interface should be declared in the file.",
            check=_check_base_interface_declared,
        ),
        LintRule(
            rule_id="corbaidl.any-typed",
            category="compatibility",
            severity="info",
            description="An any value hides what it carries.",
            check=_check_any_typed,
        ),
        LintRule(
            rule_id="corbaidl.object-reference-typed",
            category="compatibility",
            severity="info",
            description="The untyped Object reference hides which interface the caller gets.",
            check=_check_object_reference_typed,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the CORBA IDL native rules in deterministic execution order."""
        return list(self._RULES)
