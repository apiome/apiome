"""ONC RPC / XDR lint pack — MFI-21.6 (#3996).

Native, deterministic quality rules for ONC RPC programs written in the RPC language
(RFC 5531) with XDR data definitions (RFC 4506), layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`OncRpcRulePack` is registered under the ``oncrpc`` format key, so it runs with the
always-on common pack on every ONC RPC artifact. The rules read only the canonical model
:class:`~app.oncrpc_normalizer.OncRpcNormalizer` builds — the programs, versions and
procedures it records under ``extras["oncrpc_programs"]``, the typedefs under
``extras["oncrpc_typedefs"]``, and each field's declared type (``oncrpc_type_expr``):

* **oncrpc.program-number-reserved** (warning) — a program number at or above ``0x60000000``:
  RFC 5531 §8.3 reserves that block, so no portmapper or rpcbind will register it.
* **oncrpc.program-number-assigned** (info) — a program number below ``0x20000000``: that block
  is assigned by IANA (``100000`` is the portmapper); a site-defined program belongs in
  ``0x20000000``–``0x3FFFFFFF``.
* **oncrpc.version-numbers-unique** (error) — two versions of a program share a number: the
  server cannot dispatch between them.
* **oncrpc.procedure-numbers-unique** (error) — two procedures of a version share a number: the
  number is what the wire carries, so one of them is unreachable.
* **oncrpc.procedure-names-unique** (error) — two procedures of a version share a name:
  ``rpcgen`` generates one C function per name and version.
* **oncrpc.null-procedure-declared** (info) — a version without procedure ``0``: by convention
  (RFC 5531 §12.1) it is the null procedure ``void NULL(void) = 0`` that ``rpcinfo`` and
  liveness checks call.
* **oncrpc.null-procedure-void** (warning) — procedure ``0`` takes or returns something: callers
  that ping it with no argument get a decode error.
* **oncrpc.variable-length-bounded** (info) — an unbounded ``string<>`` / ``opaque<>`` / array
  ``<>``: the receiver has to accept any length, so a hostile or buggy peer can exhaust it.
  Give it the bound the application already assumes.
* **oncrpc.type-resolves** (error) — a field whose type is neither an XDR base type nor a
  typedef, enum or struct the file declares: ``rpcgen`` would not compile it.
* **oncrpc.union-has-default** (info) — a ``union … switch`` without a ``default`` arm: a
  discriminant value the arms do not list fails to decode instead of being ignored.
* **oncrpc.enum-values-unique** (error) — two enumerators share a number: the wire carries the
  number, so the receiver cannot tell them apart.

The pack also publishes :data:`PROTO3_FOR_XDR` and :func:`migration_note`, the
migrate-to-gRPC note the normalizer records on each item (``extras["oncrpc_migration"]``): where
each XDR construct and each procedure lands when the program is rewritten as a Protocol Buffers
service — the cheap adapter's "how do I leave" answer, as the HL7 v2 pack's FHIR counterparts
are for messages.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .lint_engine import LintRule, RulePack

__all__ = [
    "IANA_ASSIGNED_BELOW",
    "OncRpcRulePack",
    "PROTO3_FOR_XDR",
    "RESERVED_FROM",
    "XDR_BASE_TYPES",
    "migration_note",
    "type_shape",
]

#: Program numbers below this are assigned by IANA (RFC 5531 §8.3): ``100000`` is the
#: portmapper, ``100003`` NFS, ``100005`` the mount protocol …
IANA_ASSIGNED_BELOW = 0x20000000

#: Program numbers from this value up are reserved (RFC 5531 §8.3). ``0x20000000``–``0x3FFFFFFF``
#: is the site-defined block and ``0x40000000``–``0x5FFFFFFF`` the transient one.
RESERVED_FROM = 0x60000000

#: The XDR base types (RFC 4506 §4) plus the ``unsigned`` spelling ``rpcgen`` accepts.
XDR_BASE_TYPES = frozenset(
    {
        "int",
        "unsigned int",
        "unsigned",
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "hyper",
        "unsigned hyper",
        "float",
        "double",
        "quadruple",
        "bool",
        "string",
        "opaque",
        "void",
        "char",
        "unsigned char",
        "wchar",
    }
)

#: The proto3 counterpart of each XDR base type (the migrate-to-gRPC note). ``opaque`` is
#: ``bytes`` whether fixed or variable; ``string<N>`` keeps no bound in proto3; ``hyper`` is 64
#: bits; a ``union … switch`` becomes a ``oneof`` and an optional-data ``*`` an ``optional``.
PROTO3_FOR_XDR: Mapping[str, str] = {
    "int": "int32",
    "unsigned int": "uint32",
    "unsigned": "uint32",
    "short": "int32",
    "unsigned short": "uint32",
    "long": "int32",
    "unsigned long": "uint32",
    "hyper": "int64",
    "unsigned hyper": "uint64",
    "float": "float",
    "double": "double",
    "quadruple": "double",
    "bool": "bool",
    "string": "string",
    "opaque": "bytes",
    "void": "google.protobuf.Empty",
    "char": "int32",
    "unsigned char": "uint32",
    "wchar": "int32",
}

_TYPE_EXPR = re.compile(r"^((?:unsigned )?[\w.]+)(\*)?(?:<(\d*)>|\[(\d+)\])?$")


def type_shape(type_expr: str) -> Dict[str, Any]:
    """Decode a type expression the parser wrote (``opaque<1024>``, ``int[4]``, ``node*``).

    Args:
        type_expr: The declaration's type, as :mod:`app.oncrpc_parser` records it.

    Returns:
        ``base`` (the type name, ``unsigned int`` kept as two words), ``pointer`` (an
        optional-data ``*``), ``variable`` (a ``<…>`` suffix), ``bound`` (its number, or ``None``
        when unbounded or absent) and ``fixed`` (the ``[N]`` size, or ``None``).
    """
    match = _TYPE_EXPR.match(type_expr.strip())
    if match is None:
        return {"base": type_expr.strip(), "pointer": False, "variable": False, "bound": None, "fixed": None}
    base, pointer, var_bound, fixed_size = match.groups()
    return {
        "base": base,
        "pointer": pointer is not None,
        "variable": var_bound is not None,
        "bound": int(var_bound) if var_bound else None,
        "fixed": int(fixed_size) if fixed_size is not None else None,
    }


def _programs(api: CanonicalApi) -> List[Mapping[str, Any]]:
    listed = api.extras.get("oncrpc_programs")
    return [p for p in listed if isinstance(p, Mapping)] if isinstance(listed, list) else []


def _versions(program: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    listed = program.get("versions")
    return [v for v in listed if isinstance(v, Mapping)] if isinstance(listed, list) else []


def _procedures(version: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    listed = version.get("procedures")
    return [p for p in listed if isinstance(p, Mapping)] if isinstance(listed, list) else []


def _typedefs(api: CanonicalApi) -> Dict[str, str]:
    listed = api.extras.get("oncrpc_typedefs")
    return {str(k): str(v) for k, v in listed.items()} if isinstance(listed, Mapping) else {}


def _declared_names(api: CanonicalApi) -> frozenset[str]:
    """The enum and struct / union names the file declares."""
    return frozenset(t.name for t in api.types if "oncrpc_kind" in t.extras)


def _duplicates(items: Iterable[Any]) -> List[Any]:
    seen: set = set()
    duplicated: List[Any] = []
    for item in items:
        if item in seen and item not in duplicated:
            duplicated.append(item)
        seen.add(item)
    return duplicated


# --- programs, versions and procedures ------------------------------------------------------


def _check_program_number_reserved(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A program number must stay below the reserved block."""
    for program in _programs(api):
        number = program.get("number")
        if isinstance(number, int) and number >= RESERVED_FROM:
            yield (
                f"programs.{program.get('name')}",
                f"Program {program.get('name')} is numbered 0x{number:08X}, in the block RFC 5531 "
                "reserves (0x60000000 and up); rpcbind will not register it. Use "
                "0x20000000–0x3FFFFFFF for a site-defined program.",
            )


def _check_program_number_assigned(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A program number below ``0x20000000`` must be one IANA assigned."""
    for program in _programs(api):
        number = program.get("number")
        if isinstance(number, int) and 0 <= number < IANA_ASSIGNED_BELOW:
            yield (
                f"programs.{program.get('name')}",
                f"Program {program.get('name')} is numbered {number} (0x{number:08X}), in the "
                "IANA-assigned block below 0x20000000. Unless that number was assigned to it, a "
                "site-defined program belongs in 0x20000000–0x3FFFFFFF.",
            )


def _check_version_numbers_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Two versions of a program must not share a number."""
    for program in _programs(api):
        for number in _duplicates(v.get("number") for v in _versions(program)):
            yield (
                f"programs.{program.get('name')}.versions.{number}",
                f"Program {program.get('name')} declares version {number} more than once; the "
                "server cannot dispatch between them.",
            )


def _check_procedure_numbers_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Two procedures of a version must not share a number."""
    for program in _programs(api):
        for version in _versions(program):
            for number in _duplicates(p.get("number") for p in _procedures(version)):
                yield (
                    f"programs.{program.get('name')}.versions.{version.get('name')}.procedures.{number}",
                    f"Version {version.get('name')} of {program.get('name')} numbers two procedures "
                    f"{number}; the wire carries the number, so one of them is unreachable.",
                )


def _check_procedure_names_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Two procedures of a version must not share a name."""
    for program in _programs(api):
        for version in _versions(program):
            for name in _duplicates(p.get("name") for p in _procedures(version)):
                yield (
                    f"programs.{program.get('name')}.versions.{version.get('name')}.procedures.{name}",
                    f"Version {version.get('name')} of {program.get('name')} declares {name} twice; "
                    "rpcgen generates one function per name and version.",
                )


def _check_null_procedure_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every version should declare the null procedure (number 0)."""
    for program in _programs(api):
        for version in _versions(program):
            if not any(p.get("number") == 0 for p in _procedures(version)):
                yield (
                    f"programs.{program.get('name')}.versions.{version.get('name')}.procedures.0",
                    f"Version {version.get('name')} of {program.get('name')} has no procedure 0; by "
                    "convention it is the null procedure `void NULL(void) = 0` that rpcinfo and "
                    "liveness checks call.",
                )


def _check_null_procedure_void(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Procedure 0 should take and return ``void``."""
    for program in _programs(api):
        for version in _versions(program):
            for procedure in _procedures(version):
                if procedure.get("number") != 0:
                    continue
                arg, ret = procedure.get("arg_type", "void"), procedure.get("return_type", "void")
                if arg != "void" or ret != "void":
                    yield (
                        f"programs.{program.get('name')}.versions.{version.get('name')}.procedures.0",
                        f"Procedure 0 ({procedure.get('name')}) is `{ret} {procedure.get('name')}({arg})`; "
                        "the null procedure is called with no argument, so a caller pinging it gets a "
                        "decode error. Declare it `void NULL(void) = 0`.",
                    )


# --- types -----------------------------------------------------------------------------------


def _field_declarations(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``(path, type_expr)`` for every struct field and typedef the model records."""
    for name, type_expr in sorted(_typedefs(api).items()):
        yield f"typedefs.{name}", type_expr
    for type_ in api.types:
        if type_.extras.get("oncrpc_kind") != "struct":
            continue
        for field in type_.fields:
            type_expr = field.extras.get("oncrpc_type_expr")
            if isinstance(type_expr, str):
                yield f"types.{type_.name}.{field.name}", type_expr


def _check_variable_length_bounded(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A variable-length string, opaque or array should declare its bound."""
    for path, type_expr in _field_declarations(api):
        shape = type_shape(type_expr)
        if shape["variable"] and shape["bound"] is None:
            yield (
                path,
                f"`{type_expr}` is unbounded; the receiver must accept any length, so a hostile or "
                "buggy peer can exhaust it. Declare the bound the application already assumes "
                f"(`{shape['base']}<N>`).",
            )


def _check_type_resolves(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every field type must be a base type or a type the file declares."""
    typedefs = _typedefs(api)
    declared = _declared_names(api)
    for path, type_expr in _field_declarations(api):
        base = type_shape(type_expr)["base"]
        if base in XDR_BASE_TYPES or base in typedefs or base in declared:
            continue
        yield (
            path,
            f"`{type_expr}` names the type {base}, which is neither an XDR base type nor an enum, "
            "struct, union or typedef this file declares; rpcgen would not compile it.",
        )


def _check_union_has_default(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A discriminated union should carry a ``default`` arm."""
    for type_ in api.types:
        if type_.kind is not TypeKind.UNION or type_.extras.get("oncrpc_kind") != "union":
            continue
        cases = type_.extras.get("oncrpc_union_cases")
        labels = {c.get("label") for c in cases if isinstance(c, Mapping)} if isinstance(cases, list) else set()
        if "default" not in labels:
            yield (
                f"types.{type_.name}",
                f"Union {type_.name} has no `default` arm; a discriminant value its arms do not list "
                "fails to decode instead of being ignored. Add `default: void;`.",
            )


def _check_enum_values_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Two enumerators must not share a number."""
    for type_ in api.types:
        if type_.kind is not TypeKind.ENUM or type_.extras.get("oncrpc_kind") != "enum":
            continue
        for value in _duplicates(v.value for v in type_.enum_values):
            names = [v.name for v in type_.enum_values if v.value == value]
            yield (
                f"types.{type_.name}",
                f"Enum {type_.name} gives {' and '.join(names)} the same value {value}; the wire "
                "carries the number, so the receiver cannot tell them apart.",
            )


# --- the migrate-to-gRPC note ---------------------------------------------------------------


def _proto3_for(type_expr: str, *, typedefs: Mapping[str, str]) -> str:
    """The proto3 field type for one XDR type expression (typedefs resolved)."""
    stacked = re.match(r"^(.+?(?:<\d*>|\[\d+\]))(<\d*>|\[\d+\])$", type_expr.strip())
    if stacked:
        # An array of an already-suffixed expression (``string<256><10>``).
        return f"repeated {_proto3_for(stacked.group(1), typedefs=typedefs)}"
    shape = type_shape(type_expr)
    base = shape["base"]
    if base in typedefs:
        return _proto3_for(typedefs[base] + type_expr.strip()[len(base):], typedefs=typedefs)
    mapped = PROTO3_FOR_XDR.get(base, base)
    if shape["fixed"] is not None or (shape["variable"] and base not in {"string", "opaque"}):
        return f"repeated {mapped}"
    if shape["pointer"]:
        return f"optional {mapped}"
    return mapped


def migration_note(source: Any) -> Dict[str, Any]:
    """The migrate-to-gRPC note for a parsed document.

    Args:
        source: The :class:`~app.oncrpc_parser.OncRpcDocument` being normalized.

    Returns:
        ``target`` (``protobuf``), a one-line ``summary``, ``types`` (each enum, struct, union
        and typedef with the proto3 construct it becomes), ``procedures`` (each procedure as the
        ``rpc`` line it becomes, with its program, version and number, which proto3 does not
        keep) and ``caveats`` (what the rewrite loses).
    """
    typedefs: Dict[str, str] = {t.name: t.type_expr for t in getattr(source, "typedefs", ())}
    types: List[Dict[str, str]] = []
    for enum in getattr(source, "enums", ()):
        types.append({"name": enum.name, "xdr": "enum", "proto3": f"enum {enum.name}"})
    for struct in getattr(source, "structs", ()):
        if getattr(struct, "kind", "struct") == "union":
            types.append(
                {
                    "name": struct.name,
                    "xdr": f"union switch ({struct.switch_type} {struct.switch_field})",
                    "proto3": f"message {struct.name} {{ oneof {struct.switch_field} {{ … }} }}",
                }
            )
        else:
            fields = ", ".join(
                f"{_proto3_for(f.type_expr, typedefs=typedefs)} {f.name}" for f in struct.fields
            )
            types.append({"name": struct.name, "xdr": "struct", "proto3": f"message {struct.name} {{ {fields} }}"})
    for name, type_expr in typedefs.items():
        types.append(
            {
                "name": name,
                "xdr": f"typedef {type_expr}",
                "proto3": f"{_proto3_for(type_expr, typedefs=typedefs)} (inlined; proto3 has no typedef)",
            }
        )
    procedures: List[Dict[str, Any]] = []
    for program in getattr(source, "programs", ()):
        for version in program.versions:
            for procedure in version.procedures:
                arg = _proto3_for(procedure.arg_type, typedefs=typedefs)
                ret = _proto3_for(procedure.return_type, typedefs=typedefs)
                procedures.append(
                    {
                        "program": program.name,
                        "version": version.name,
                        "number": procedure.number,
                        "name": procedure.name,
                        "proto3": f"rpc {procedure.name} ({arg}) returns ({ret});",
                    }
                )
    return {
        "target": "protobuf",
        "summary": (
            "Rewrite each program version as a proto3 service: every procedure becomes an rpc "
            "with its argument and result as messages, XDR structs become messages, unions "
            "become oneofs, enums stay enums."
        ),
        "types": types,
        "procedures": procedures,
        "caveats": [
            "Program, version and procedure numbers have no proto3 counterpart; gRPC routes by "
            "service and method name. Keep them in the service's documentation for the cut-over.",
            "A string<N> or opaque<N> bound is not enforced by proto3; validate it in the handler.",
            "A fixed-length array ([N]) becomes repeated with no length guarantee.",
            "XDR optional-data (*) becomes proto3 optional; a recursive list via a pointer "
            "becomes a repeated field.",
        ],
    }


class OncRpcRulePack(RulePack, register=True):
    """Native rules for ONC RPC / XDR artifacts (see the module docstring)."""

    format = "oncrpc"
    pack_id = "oncrpc"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="oncrpc.program-number-reserved",
            category="structure",
            severity="warning",
            description="A program number must stay below the reserved block (0x60000000).",
            check=_check_program_number_reserved,
        ),
        LintRule(
            rule_id="oncrpc.program-number-assigned",
            category="structure",
            severity="info",
            description="A program number below 0x20000000 must be one IANA assigned.",
            check=_check_program_number_assigned,
        ),
        LintRule(
            rule_id="oncrpc.version-numbers-unique",
            category="structure",
            severity="error",
            description="Two versions of a program must not share a number.",
            check=_check_version_numbers_unique,
        ),
        LintRule(
            rule_id="oncrpc.procedure-numbers-unique",
            category="structure",
            severity="error",
            description="Two procedures of a version must not share a number.",
            check=_check_procedure_numbers_unique,
        ),
        LintRule(
            rule_id="oncrpc.procedure-names-unique",
            category="naming",
            severity="error",
            description="Two procedures of a version must not share a name.",
            check=_check_procedure_names_unique,
        ),
        LintRule(
            rule_id="oncrpc.null-procedure-declared",
            category="structure",
            severity="info",
            description="Every version should declare the null procedure (number 0).",
            check=_check_null_procedure_declared,
        ),
        LintRule(
            rule_id="oncrpc.null-procedure-void",
            category="structure",
            severity="warning",
            description="Procedure 0 should take and return void.",
            check=_check_null_procedure_void,
        ),
        LintRule(
            rule_id="oncrpc.variable-length-bounded",
            category="structure",
            severity="info",
            description="A variable-length string, opaque or array should declare its bound.",
            check=_check_variable_length_bounded,
        ),
        LintRule(
            rule_id="oncrpc.type-resolves",
            category="structure",
            severity="error",
            description="Every field type must be a base type or a type the file declares.",
            check=_check_type_resolves,
        ),
        LintRule(
            rule_id="oncrpc.union-has-default",
            category="structure",
            severity="info",
            description="A discriminated union should carry a default arm.",
            check=_check_union_has_default,
        ),
        LintRule(
            rule_id="oncrpc.enum-values-unique",
            category="structure",
            severity="error",
            description="Two enumerators must not share a number.",
            check=_check_enum_values_unique,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the ONC RPC native rules in deterministic execution order."""
        return list(self._RULES)
