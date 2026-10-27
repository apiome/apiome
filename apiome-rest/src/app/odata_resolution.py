"""OData reference and key resolution — MFI-11.4 (#3779).

The OASIS schemas (:mod:`app.odata_csdl_schema`, :mod:`app.odata_csdl_xsd`) check that each CSDL
element is *shaped* right; they cannot check that the names it uses point at anything. This
module does: every type, base type, entity set, partner, binding and import a document names
must resolve, and every entity type must have a usable key. A service whose metadata breaks one
of these rules cannot be called the way it describes itself, so the findings feed two blocking
lint rules (:mod:`app.odata_lint`):

* **reference** issues (``odata.unresolved-reference``) — a qualified name that names no
  declaration of the right kind: a property, parameter or return type; a base type; an entity
  set's or singleton's entity type; a navigation property's target, partner or referential
  constraint; a navigation property binding; an action / function import's operation; an
  association set's association or roles (v2/v3).
* **key** issues (``odata.entity-key``) — an entity type with no key of its own and none to
  inherit, a key that redeclares an inherited one, or a key property that does not exist, is
  nullable, is a collection, or is not of a key-able (primitive / enum / type-definition) type.

Two readers, one result shape:

* :func:`resolve_csdl_json` checks OData v4 from its canonical CSDL JSON — the form both v4
  inputs (CSDL XML and CSDL JSON) are validated in.
* :func:`resolve_legacy_document` checks OData v2/v3 from the parsed
  :class:`~app.odata_parser.ODataDocument` (v2/v3 has no CSDL JSON form).

A name in a namespace the document only *references* (``<edmx:Reference>``) and did not merge is
outside the document, so it is never reported: the service resolves it, the upload cannot.
Issue paths are JSON pointers in CSDL JSON shape (``/Namespace/Type/Member``), the shape the OASIS
schema violations already use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .odata_parser import ODataDocument, ODataEntityType, ODataSchema
from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "ISSUE_KEY",
    "ISSUE_REFERENCE",
    "MAX_REPORTED_ISSUES",
    "ResolutionIssue",
    "resolve_csdl_json",
    "resolve_legacy_document",
    "resolve_odata_document",
]

#: Issue kind for a name that resolves to nothing (``odata.unresolved-reference``).
ISSUE_REFERENCE = "reference"
#: Issue kind for an entity-key defect (``odata.entity-key``).
ISSUE_KEY = "key"

#: Most issues recorded for one document (the rest are counted, not listed).
MAX_REPORTED_ISSUES = 50

#: OData v4 primitive types (OData CSDL 4.01 §4.4), plus the abstract types a model may name.
_V4_PRIMITIVES = frozenset(
    {
        "Edm.Binary",
        "Edm.Boolean",
        "Edm.Byte",
        "Edm.Date",
        "Edm.DateTimeOffset",
        "Edm.Decimal",
        "Edm.Double",
        "Edm.Duration",
        "Edm.Guid",
        "Edm.Int16",
        "Edm.Int32",
        "Edm.Int64",
        "Edm.SByte",
        "Edm.Single",
        "Edm.Stream",
        "Edm.String",
        "Edm.TimeOfDay",
        "Edm.Geography",
        "Edm.GeographyPoint",
        "Edm.GeographyLineString",
        "Edm.GeographyPolygon",
        "Edm.GeographyMultiPoint",
        "Edm.GeographyMultiLineString",
        "Edm.GeographyMultiPolygon",
        "Edm.GeographyCollection",
        "Edm.Geometry",
        "Edm.GeometryPoint",
        "Edm.GeometryLineString",
        "Edm.GeometryPolygon",
        "Edm.GeometryMultiPoint",
        "Edm.GeometryMultiLineString",
        "Edm.GeometryMultiPolygon",
        "Edm.GeometryCollection",
        "Edm.PrimitiveType",
        "Edm.Untyped",
        "Edm.AnnotationPath",
        "Edm.PropertyPath",
        "Edm.NavigationPropertyPath",
        "Edm.AnyPropertyPath",
        "Edm.ModelElementPath",
    }
)

#: The abstract structured types v4 lets a property, parameter or term name.
_V4_ABSTRACT_STRUCTURED = frozenset({"Edm.EntityType", "Edm.ComplexType"})

#: OData v2/v3 primitive types ([MS-CSDL] §2.2.1): v4 dropped ``DateTime`` and ``Time``.
_LEGACY_PRIMITIVES = frozenset(
    {
        "Edm.Binary",
        "Edm.Boolean",
        "Edm.Byte",
        "Edm.DateTime",
        "Edm.DateTimeOffset",
        "Edm.Decimal",
        "Edm.Double",
        "Edm.Guid",
        "Edm.Int16",
        "Edm.Int32",
        "Edm.Int64",
        "Edm.SByte",
        "Edm.Single",
        "Edm.String",
        "Edm.Time",
        "Edm.Stream",
        "Edm.Geography",
        "Edm.GeographyPoint",
        "Edm.GeographyLineString",
        "Edm.GeographyPolygon",
        "Edm.GeographyMultiPoint",
        "Edm.GeographyMultiLineString",
        "Edm.GeographyMultiPolygon",
        "Edm.GeographyCollection",
        "Edm.Geometry",
        "Edm.GeometryPoint",
        "Edm.GeometryLineString",
        "Edm.GeometryPolygon",
        "Edm.GeometryMultiPoint",
        "Edm.GeometryMultiLineString",
        "Edm.GeometryMultiPolygon",
        "Edm.GeometryCollection",
    }
)

#: Primitive types a key property may have (CSDL 4.01 §8.2 / [MS-CSDL] §2.1.5): no binary,
#: floating-point, stream or spatial values.
_KEY_PRIMITIVES = frozenset(
    {
        "Edm.Boolean",
        "Edm.Byte",
        "Edm.Date",
        "Edm.DateTime",
        "Edm.DateTimeOffset",
        "Edm.Decimal",
        "Edm.Duration",
        "Edm.Guid",
        "Edm.Int16",
        "Edm.Int32",
        "Edm.Int64",
        "Edm.SByte",
        "Edm.String",
        "Edm.Time",
        "Edm.TimeOfDay",
        # v2/v3 allowed binary keys; v4 does not, but a v4 document that keeps one is a
        # portability concern rather than an unusable key, so it is not reported.
        "Edm.Binary",
    }
)

#: CSDL member kinds that are types, for "expected X" messages.
_STRUCTURED = ("EntityType", "ComplexType")


@dataclass(frozen=True)
class ResolutionIssue:
    """One name that resolves to nothing, or one entity-key defect.

    Attributes:
        kind: :data:`ISSUE_REFERENCE` or :data:`ISSUE_KEY`.
        path: JSON pointer, CSDL JSON shaped (``/ODataDemo/Product/$Key/0``).
        message: What is wrong, naming the unresolved name.
    """

    kind: str
    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        """The issue as ``{"kind", "path", "message"}``."""
        return {"kind": self.kind, "path": self.path, "message": self.message}


def _pointer(*parts: Any) -> str:
    """A JSON pointer from path segments (``~`` and ``/`` escaped)."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _split_type(type_expr: Optional[str]) -> Tuple[Optional[str], bool]:
    """``Collection(NS.T)`` → ``("NS.T", True)``; ``NS.T`` → ``("NS.T", False)``."""
    if not type_expr:
        return None, False
    text = type_expr.strip()
    if text.startswith("Collection(") and text.endswith(")"):
        return text[len("Collection(") : -1].strip(), True
    return text, False


def _split_qualified(name: str) -> Tuple[str, str]:
    """``NS.Sub.Type`` → ``("NS.Sub", "Type")``; an unqualified name has namespace ``""``."""
    namespace, _, simple = name.rpartition(".")
    return namespace, simple


def _article(word: str) -> str:
    """``"a"`` or ``"an"`` for a member kind (``an EntityType``, ``a ComplexType``)."""
    return "an" if word[:1].upper() in "AEIOU" else "a"


def _expected(allowed: Sequence[str]) -> str:
    """``("EntityType", "ComplexType")`` → ``"EntityType or ComplexType"``; nothing → primitive."""
    return " or ".join(allowed) or "a primitive type"


def _kind_message(what: str, type_name: str, kind: str, allowed: Sequence[str]) -> str:
    """The message for a name that resolves to a declaration of the wrong kind."""
    return f"{what} names `{type_name}`, {_article(kind)} {kind}; expected {_expected(allowed)}."


def _primitive_message(what: str, type_name: str, allowed: Sequence[str], primitive: bool, version: str) -> str:
    """The message for an ``Edm.*`` name that is unknown, or a primitive where none may stand."""
    if primitive:
        return f"{what} names `{type_name}`, which is not an OData {version} primitive type."
    return f"{what} names primitive type `{type_name}`; expected {_expected(allowed)}."


def _capped(issues: List[ResolutionIssue]) -> Tuple[List[ResolutionIssue], int]:
    """The first :data:`MAX_REPORTED_ISSUES` issues, and how many there were in all."""
    return issues[:MAX_REPORTED_ISSUES], len(issues)


# ---------------------------------------------------------------------------------------------
# OData v4 — canonical CSDL JSON
# ---------------------------------------------------------------------------------------------


class _CsdlIndex:
    """Name lookup over one CSDL JSON document.

    Attributes:
        aliases: Alias → namespace, for the document's schemas and its referenced includes.
        members: Qualified name (namespace-resolved) → schema member (a dict, or an overload
            list for an action / function).
        local: Namespaces the document declares.
        external: Namespaces the document only references (``$Reference`` / ``$Include``).
    """

    def __init__(self, csdl: Mapping[str, Any]) -> None:
        self.aliases: Dict[str, str] = {}
        self.members: Dict[str, Any] = {}
        self.local: Set[str] = set()
        self.external: Set[str] = set()
        references = csdl.get("$Reference")
        if isinstance(references, Mapping):
            for reference in references.values():
                includes = reference.get("$Include") if isinstance(reference, Mapping) else None
                for include in includes or ():
                    if not isinstance(include, Mapping) or not isinstance(include.get("$Namespace"), str):
                        continue
                    self.external.add(include["$Namespace"])
                    if isinstance(include.get("$Alias"), str):
                        self.aliases[include["$Alias"]] = include["$Namespace"]
        for namespace, schema in self.schemas(csdl):
            self.local.add(namespace)
            if isinstance(schema.get("$Alias"), str):
                self.aliases[schema["$Alias"]] = namespace
            for name, member in schema.items():
                if not name.startswith("$") and "@" not in name:
                    self.members[f"{namespace}.{name}"] = member

    @staticmethod
    def schemas(csdl: Mapping[str, Any]) -> Iterable[Tuple[str, Mapping[str, Any]]]:
        """The document's ``(namespace, schema)`` pairs."""
        for namespace, schema in csdl.items():
            if not namespace.startswith("$") and isinstance(schema, Mapping):
                yield namespace, schema

    def qualify(self, name: str) -> str:
        """``Alias.Type`` → ``Namespace.Type``; any other name is returned unchanged."""
        namespace, simple = _split_qualified(name)
        if namespace in self.aliases:
            return f"{self.aliases[namespace]}.{simple}"
        return name

    def is_external(self, qualified: str) -> bool:
        """Whether a qualified name lives in a namespace the document only references."""
        namespace, _ = _split_qualified(qualified)
        return namespace in self.external and namespace not in self.local

    def kind_of(self, qualified: str) -> Optional[str]:
        """The ``$Kind`` of a declared schema member, or ``None`` when nothing is declared."""
        member = self.members.get(qualified)
        if isinstance(member, list):
            kinds = {item.get("$Kind") for item in member if isinstance(item, Mapping)}
            return next(iter(kinds)) if len(kinds) == 1 else "Action"
        if isinstance(member, Mapping):
            return member.get("$Kind")
        return None


class _CsdlResolver:
    """Walks one CSDL JSON document and collects its :class:`ResolutionIssue` list."""

    def __init__(self, csdl: Mapping[str, Any]) -> None:
        self.csdl = csdl
        self.index = _CsdlIndex(csdl)
        self.issues: List[ResolutionIssue] = []

    # -- helpers ------------------------------------------------------------------------------

    def _reference(self, path: str, message: str) -> None:
        self.issues.append(ResolutionIssue(ISSUE_REFERENCE, path, message))

    def _key(self, path: str, message: str) -> None:
        self.issues.append(ResolutionIssue(ISSUE_KEY, path, message))

    def check_type(
        self,
        type_name: Optional[str],
        *,
        path: str,
        what: str,
        allowed: Sequence[str],
        primitive: bool = True,
    ) -> Optional[str]:
        """Check a type name resolves to a declaration of an allowed kind.

        Args:
            type_name: The type as written (alias or namespace qualified; ``Edm.*`` primitive).
            path: Where the name is written.
            what: What names it, for the message (``property 'ID'``).
            allowed: The member kinds it may name (``EntityType``, ``ComplexType`` …).
            primitive: Whether an ``Edm.*`` primitive type is acceptable too.

        Returns:
            The namespace-qualified name when it resolved to a local declaration, else ``None``.
        """
        if not type_name:
            return None
        if type_name.startswith("Edm."):
            if type_name in _V4_ABSTRACT_STRUCTURED and set(allowed) & set(_STRUCTURED):
                return None
            if primitive and type_name in _V4_PRIMITIVES:
                return None
            self._reference(path, _primitive_message(what, type_name, allowed, primitive, "v4"))
            return None
        qualified = self.index.qualify(type_name)
        if self.index.is_external(qualified):
            return None
        kind = self.index.kind_of(qualified)
        if kind is None:
            namespace, _ = _split_qualified(qualified)
            if namespace and namespace not in self.index.local:
                self._reference(
                    path,
                    f"{what} names `{type_name}`, in namespace `{namespace}` that the document "
                    f"neither declares nor references.",
                )
            else:
                self._reference(path, f"{what} names `{type_name}`, which is not declared.")
            return None
        if kind not in allowed:
            self._reference(path, _kind_message(what, type_name, kind, allowed))
            return None
        return qualified

    def structured(self, qualified: Optional[str]) -> Optional[Mapping[str, Any]]:
        """The declared entity / complex type for a qualified name."""
        member = self.index.members.get(qualified) if qualified else None
        return member if isinstance(member, Mapping) and member.get("$Kind") in _STRUCTURED else None

    def lineage(self, qualified: str) -> List[Tuple[str, Mapping[str, Any]]]:
        """A structured type followed by its base types (cycle-safe, local types only)."""
        chain: List[Tuple[str, Mapping[str, Any]]] = []
        seen: Set[str] = set()
        current: Optional[str] = qualified
        while current and current not in seen:
            seen.add(current)
            member = self.structured(current)
            if member is None:
                break
            chain.append((current, member))
            base = member.get("$BaseType")
            current = self.index.qualify(base) if isinstance(base, str) else None
        return chain

    def has_external_base(self, qualified: str) -> bool:
        """Whether a type inherits from a base the document does not declare."""
        chain = self.lineage(qualified)
        if not chain:
            return False
        base = chain[-1][1].get("$BaseType")
        return isinstance(base, str) and self.structured(self.index.qualify(base)) is None

    def find_member(self, qualified: str, name: str) -> Optional[Mapping[str, Any]]:
        """A property or navigation property of a type or one of its base types."""
        for _, member in self.lineage(qualified):
            value = member.get(name)
            if isinstance(value, Mapping) and not name.startswith("$"):
                return value
        return None

    def walk(self, qualified: str, path_text: str) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
        """Follow a ``/``-separated member path from a structured type.

        Each segment is a member of the current type, or a qualified type cast. Returns the
        final member and ``None``, or ``None`` and the segment that did not resolve; ``(None,
        None)`` when the walk left the document (an external type) and cannot be judged.
        """
        current: Optional[str] = qualified
        found: Optional[Mapping[str, Any]] = None
        for segment in path_text.split("/"):
            if current is None:
                return None, None
            if "." in segment:  # a type cast
                cast = self.index.qualify(segment)
                if self.index.is_external(cast):
                    return None, None
                if self.structured(cast) is None:
                    return None, segment
                current, found = cast, None
                continue
            if self.has_external_base(current) and self.find_member(current, segment) is None:
                return None, None
            found = self.find_member(current, segment)
            if found is None:
                return None, segment
            target, _ = _split_type(found.get("$Type"))
            if target is None or target.startswith("Edm."):
                current = None
            else:
                current = self.index.qualify(target)
                if self.index.is_external(current):
                    current = None
        return found, None

    # -- schema members -----------------------------------------------------------------------

    def run(self) -> List[ResolutionIssue]:
        """Check every schema of the document and return the issues found."""
        for namespace, schema in _CsdlIndex.schemas(self.csdl):
            for name, member in schema.items():
                if name.startswith("$") or "@" in name:
                    continue
                path = _pointer(namespace, name)
                if isinstance(member, list):
                    for position, overload in enumerate(member):
                        if isinstance(overload, Mapping):
                            self.operation(overload, path=_pointer(namespace, name, position), name=name)
                    continue
                if not isinstance(member, Mapping):
                    continue
                kind = member.get("$Kind")
                if kind in _STRUCTURED:
                    self.structured_type(f"{namespace}.{name}", member, path=path, kind=str(kind))
                elif kind == "TypeDefinition":
                    self.check_type(
                        member.get("$UnderlyingType"),
                        path=f"{path}/$UnderlyingType",
                        what=f"type definition '{name}'",
                        allowed=(),
                    )
                elif kind == "Term":
                    self.check_type(
                        member.get("$Type", "Edm.String"),
                        path=f"{path}/$Type",
                        what=f"term '{name}'",
                        allowed=("EntityType", "ComplexType", "EnumType", "TypeDefinition"),
                    )
                    if isinstance(member.get("$BaseTerm"), str):
                        self.check_type(
                            member["$BaseTerm"],
                            path=f"{path}/$BaseTerm",
                            what=f"term '{name}'",
                            allowed=("Term",),
                            primitive=False,
                        )
                elif kind == "EntityContainer":
                    self.container(f"{namespace}.{name}", member, path=path)
        return self.issues

    def structured_type(self, qualified: str, member: Mapping[str, Any], *, path: str, kind: str) -> None:
        """Check an entity / complex type: its base, members and (entity types) its key."""
        simple = _split_qualified(qualified)[1]
        if isinstance(member.get("$BaseType"), str):
            self.check_type(
                member["$BaseType"],
                path=f"{path}/$BaseType",
                what=f"{kind} '{simple}' base type",
                allowed=(kind,),
                primitive=False,
            )
        for name, value in member.items():
            if name.startswith("$") or "@" in name or not isinstance(value, Mapping):
                continue
            member_path = f"{path}{_pointer(name)}"
            type_name, _ = _split_type(value.get("$Type", "Edm.String"))
            if value.get("$Kind") == "NavigationProperty":
                self.navigation(qualified, name, value, path=member_path)
            else:
                self.check_type(
                    type_name,
                    path=f"{member_path}/$Type",
                    what=f"property '{simple}.{name}'",
                    allowed=("ComplexType", "EnumType", "TypeDefinition"),
                )
        if kind == "EntityType":
            self.entity_key(qualified, member, path=path)

    def navigation(self, owner: str, name: str, value: Mapping[str, Any], *, path: str) -> None:
        """Check a navigation property's target type, partner and referential constraint."""
        simple = _split_qualified(owner)[1]
        type_name, _ = _split_type(value.get("$Type"))
        target = self.check_type(
            type_name,
            path=f"{path}/$Type",
            what=f"navigation property '{simple}.{name}'",
            allowed=("EntityType",),
            primitive=False,
        )
        if target is None:
            return
        partner = value.get("$Partner")
        if isinstance(partner, str) and not self.has_external_base(target):
            found, missing = self.walk(target, partner)
            if missing is not None or (found is not None and found.get("$Kind") != "NavigationProperty"):
                self._reference(
                    f"{path}/$Partner",
                    f"navigation property '{simple}.{name}' names partner `{partner}`, which is "
                    f"not a navigation property of `{type_name}`.",
                )
        constraints = value.get("$ReferentialConstraint")
        if isinstance(constraints, Mapping):
            for dependent, principal in constraints.items():
                if dependent.startswith("@") or "@" in dependent:
                    continue
                _, missing = self.walk(owner, dependent)
                if missing is not None:
                    self._reference(
                        f"{path}/$ReferentialConstraint{_pointer(dependent)}",
                        f"referential constraint of '{simple}.{name}' names property `{dependent}`, "
                        f"which `{simple}` does not declare.",
                    )
                if isinstance(principal, str):
                    _, missing = self.walk(target, principal)
                    if missing is not None:
                        self._reference(
                            f"{path}/$ReferentialConstraint{_pointer(dependent)}",
                            f"referential constraint of '{simple}.{name}' names property "
                            f"`{principal}`, which `{type_name}` does not declare.",
                        )

    def entity_key(self, qualified: str, member: Mapping[str, Any], *, path: str) -> None:
        """Check an entity type's key: present (own or inherited), not redeclared, usable."""
        simple = _split_qualified(qualified)[1]
        chain = self.lineage(qualified)
        inherited = next((base for _, base in chain[1:] if "$Key" in base), None)
        own = member.get("$Key")
        if own is None:
            if inherited is None and not member.get("$Abstract") and not self.has_external_base(qualified):
                self._key(
                    path,
                    f"entity type '{simple}' declares no key and inherits none; a non-abstract "
                    f"entity type must have one.",
                )
            return
        if inherited is not None:
            self._key(
                f"{path}/$Key",
                f"entity type '{simple}' declares a key although its base type already has one; "
                f"a derived type inherits its key and must not redeclare it.",
            )
        for position, entry in enumerate(own if isinstance(own, list) else ()):
            key_path = next(iter(entry.values()), None) if isinstance(entry, Mapping) else entry
            if not isinstance(key_path, str):
                continue
            found, missing = self.walk(qualified, key_path)
            entry_path = f"{path}/$Key/{position}"
            if missing is not None:
                self._key(
                    entry_path,
                    f"key of entity type '{simple}' names `{key_path}`, which is not a property of `{simple}`.",
                )
                continue
            if found is None:
                continue  # resolved through a type outside the document
            self.key_property(simple, key_path, found, path=entry_path)

    def key_property(self, owner: str, key_path: str, prop: Mapping[str, Any], *, path: str) -> None:
        """Check one resolved key property is a non-nullable, single, key-able value."""
        if prop.get("$Kind") == "NavigationProperty":
            self._key(path, f"key of entity type '{owner}' names navigation property `{key_path}`.")
            return
        if prop.get("$Collection"):
            self._key(path, f"key property `{key_path}` of entity type '{owner}' is a collection.")
            return
        if prop.get("$Nullable"):
            self._key(
                path,
                f"key property `{key_path}` of entity type '{owner}' is nullable; key properties "
                f'must be declared `Nullable="false"`.',
            )
        type_name = prop.get("$Type", "Edm.String")
        if isinstance(type_name, str) and type_name.startswith("Edm.") and type_name not in _KEY_PRIMITIVES:
            self._key(
                path,
                f"key property `{key_path}` of entity type '{owner}' has type `{type_name}`, which "
                f"cannot be part of a key.",
            )
        elif isinstance(type_name, str) and not type_name.startswith("Edm."):
            kind = self.index.kind_of(self.index.qualify(type_name))
            if kind in _STRUCTURED:
                self._key(
                    path,
                    f"key property `{key_path}` of entity type '{owner}' has structured type "
                    f"`{type_name}`; a key must be a primitive, enumeration or type-definition value.",
                )

    def operation(self, overload: Mapping[str, Any], *, path: str, name: str) -> None:
        """Check an action / function overload's parameter and return types."""
        any_type = ("EntityType", "ComplexType", "EnumType", "TypeDefinition")
        for position, parameter in enumerate(overload.get("$Parameter") or ()):
            if not isinstance(parameter, Mapping):
                continue
            type_name, _ = _split_type(parameter.get("$Type", "Edm.String"))
            self.check_type(
                type_name,
                path=f"{path}/$Parameter/{position}/$Type",
                what=f"parameter '{parameter.get('$Name', position)}' of '{name}'",
                allowed=any_type,
            )
        return_type = overload.get("$ReturnType")
        if isinstance(return_type, Mapping):
            type_name, _ = _split_type(return_type.get("$Type", "Edm.String"))
            self.check_type(
                type_name,
                path=f"{path}/$ReturnType/$Type",
                what=f"return type of '{name}'",
                allowed=any_type,
            )

    # -- entity container ---------------------------------------------------------------------

    def container(self, qualified: str, member: Mapping[str, Any], *, path: str) -> None:
        """Check a container's sets, singletons, bindings and imports."""
        if isinstance(member.get("$Extends"), str):
            self.check_type(
                member["$Extends"],
                path=f"{path}/$Extends",
                what="entity container",
                allowed=("EntityContainer",),
                primitive=False,
            )
        for name, value in member.items():
            if name.startswith("$") or "@" in name or not isinstance(value, Mapping):
                continue
            child_path = f"{path}{_pointer(name)}"
            if "$Action" in value:
                self.import_target(value, "$Action", "Action", qualified, name=name, path=child_path)
            elif "$Function" in value:
                self.import_target(value, "$Function", "Function", qualified, name=name, path=child_path)
            else:
                what = "entity set" if value.get("$Collection") else "singleton"
                entity_type = self.check_type(
                    value.get("$Type"),
                    path=f"{child_path}/$Type",
                    what=f"{what} '{name}'",
                    allowed=("EntityType",),
                    primitive=False,
                )
                self.bindings(qualified, value, entity_type, name=name, path=child_path)

    def resolve_target(self, container: str, target: str) -> Optional[Mapping[str, Any]]:
        """An entity set / singleton named by a binding or import target.

        ``Set`` names a child of ``container``; ``NS.Container/Set`` a child of that container.
        Returns ``{}`` when the target is outside the document (cannot be judged).
        """
        if "/" in target:
            owner_name, _, child = target.partition("/")
            owner = self.index.qualify(owner_name)
            if self.index.is_external(owner):
                return {}
            child = child.split("/", 1)[0]
        else:
            owner, child = container, target
        owner_member = self.index.members.get(owner)
        if not isinstance(owner_member, Mapping) or owner_member.get("$Kind") != "EntityContainer":
            return None
        found = owner_member.get(child)
        if isinstance(found, Mapping) and "$Type" in found:
            return found
        extends = owner_member.get("$Extends")
        if isinstance(extends, str) and "/" not in target:
            parent = self.index.qualify(extends)
            if self.index.is_external(parent):
                return {}
            if parent != container:
                return self.resolve_target(parent, child)
        return None

    def bindings(
        self, container: str, value: Mapping[str, Any], entity_type: Optional[str], *, name: str, path: str
    ) -> None:
        """Check each navigation property binding's path and target."""
        bindings = value.get("$NavigationPropertyBinding")
        if not isinstance(bindings, Mapping):
            return
        for binding_path, target in bindings.items():
            entry_path = f"{path}/$NavigationPropertyBinding{_pointer(binding_path)}"
            if entity_type is not None:
                found, missing = self.walk(entity_type, binding_path)
                if missing is not None or (found is not None and found.get("$Kind") != "NavigationProperty"):
                    self._reference(
                        entry_path,
                        f"navigation property binding of '{name}' names path `{binding_path}`, "
                        f"which is not a navigation property of its entity type.",
                    )
            if isinstance(target, str) and self.resolve_target(container, target) is None:
                self._reference(
                    entry_path,
                    f"navigation property binding of '{name}' targets `{target}`, which is not an "
                    f"entity set or singleton of the container.",
                )

    def import_target(
        self, value: Mapping[str, Any], key: str, kind: str, container: str, *, name: str, path: str
    ) -> None:
        """Check an action / function import's operation and entity set."""
        self.check_type(
            value.get(key),
            path=f"{path}/{key}",
            what=f"{kind.lower()} import '{name}'",
            allowed=(kind,),
            primitive=False,
        )
        entity_set = value.get("$EntitySet")
        if isinstance(entity_set, str) and self.resolve_target(container, entity_set) is None:
            self._reference(
                f"{path}/$EntitySet",
                f"{kind.lower()} import '{name}' names entity set `{entity_set}`, which the container "
                f"does not declare.",
            )


def resolve_csdl_json(csdl: Mapping[str, Any]) -> List[ResolutionIssue]:
    """Resolve every reference and key of an OData v4 CSDL JSON document.

    Args:
        csdl: The canonical CSDL JSON (:func:`app.odata_csdl_json.csdl_xml_to_json`, or an upload).

    Returns:
        Every issue found, in document order.
    """
    return _CsdlResolver(csdl).run()


# ---------------------------------------------------------------------------------------------
# OData v2/v3 — the parsed document
# ---------------------------------------------------------------------------------------------


def _legacy_includes(document: ODataDocument) -> List[Tuple[str, Optional[str], bool]]:
    """Every ``(namespace, alias, merged)`` an ``<edmx:Reference>`` of the document includes.

    A fileset parse records its references (and whether each was merged) on the document; a
    single-file parse does not, so they are read from the source text — a reference there is
    never merged, and its namespaces are outside the document.
    """
    if document.references:
        return [
            (namespace, alias, reference.resolved)
            for reference in document.references
            for namespace, alias in reference.includes
        ]
    try:
        root = parse_xml(document.raw)
    except SecureXmlError:
        return []
    return [
        (include.get("Namespace", ""), include.get("Alias"), False)
        for reference in root
        if reference.tag.rpartition("}")[2] == "Reference"
        for include in reference
        if include.tag.rpartition("}")[2] == "Include" and include.get("Namespace")
    ]


class _LegacyResolver:
    """Walks a parsed v2/v3 :class:`ODataDocument` and collects its issues."""

    def __init__(self, document: ODataDocument) -> None:
        self.document = document
        self.issues: List[ResolutionIssue] = []
        self.aliases: Dict[str, str] = {}
        self.local: Set[str] = set()
        self.external: Set[str] = set()
        self.kinds: Dict[str, str] = {}
        self.entities: Dict[str, ODataEntityType] = {}
        self.complex_props: Dict[str, Dict[str, Any]] = {}
        self.associations: Dict[str, Any] = {}
        for namespace, alias, resolved in _legacy_includes(document):
            if alias:
                self.aliases[alias] = namespace
            if not resolved:
                self.external.add(namespace)
        for schema in document.schemas:
            self._index(schema)

    def _index(self, schema: ODataSchema) -> None:
        namespace = schema.namespace
        self.local.add(namespace)
        if schema.alias:
            self.aliases[schema.alias] = namespace
        for entity in schema.entity_types:
            self.kinds[f"{namespace}.{entity.name}"] = "EntityType"
            self.entities[f"{namespace}.{entity.name}"] = entity
        for complex_type in schema.complex_types:
            self.kinds[f"{namespace}.{complex_type.name}"] = "ComplexType"
        for enum_type in schema.enum_types:
            self.kinds[f"{namespace}.{enum_type.name}"] = "EnumType"
        for association in schema.associations:
            self.kinds[f"{namespace}.{association.name}"] = "Association"
            self.associations[f"{namespace}.{association.name}"] = association

    def qualify(self, name: str) -> str:
        """``Alias.Type`` → ``Namespace.Type``."""
        namespace, simple = _split_qualified(name)
        return f"{self.aliases[namespace]}.{simple}" if namespace in self.aliases else name

    def check_type(
        self, type_expr: Optional[str], *, path: str, what: str, allowed: Sequence[str], primitive: bool = True
    ) -> Optional[str]:
        """Check a type name resolves (see :meth:`_CsdlResolver.check_type`)."""
        type_name, _ = _split_type(type_expr)
        if not type_name:
            return None
        if type_name.startswith("Edm."):
            if primitive and type_name in _LEGACY_PRIMITIVES:
                return None
            version = f"v{self.document.version.split('.')[0]}"
            self.issues.append(
                ResolutionIssue(ISSUE_REFERENCE, path, _primitive_message(what, type_name, allowed, primitive, version))
            )
            return None
        qualified = self.qualify(type_name)
        namespace, _ = _split_qualified(qualified)
        if namespace in self.external and namespace not in self.local:
            return None
        kind = self.kinds.get(qualified)
        if kind is None:
            where = (
                f", in namespace `{namespace}` that the document neither declares nor references"
                if namespace and namespace not in self.local
                else ", which is not declared"
            )
            self.issues.append(ResolutionIssue(ISSUE_REFERENCE, path, f"{what} names `{type_name}`{where}."))
            return None
        if kind not in allowed:
            self.issues.append(ResolutionIssue(ISSUE_REFERENCE, path, _kind_message(what, type_name, kind, allowed)))
            return None
        return qualified

    def lineage(self, qualified: str) -> List[ODataEntityType]:
        """An entity type followed by its local base types (cycle-safe)."""
        chain: List[ODataEntityType] = []
        seen: Set[str] = set()
        current: Optional[str] = qualified
        while current and current not in seen and current in self.entities:
            seen.add(current)
            entity = self.entities[current]
            chain.append(entity)
            current = self.qualify(entity.base_type) if entity.base_type else None
        return chain

    def run(self) -> List[ResolutionIssue]:
        """Check every schema and return the issues found."""
        for schema in self.document.schemas:
            namespace = schema.namespace
            for entity in schema.entity_types:
                self.entity(namespace, entity)
            for complex_type in schema.complex_types:
                path = _pointer(namespace, complex_type.name)
                if complex_type.base_type:
                    self.check_type(
                        complex_type.base_type,
                        path=f"{path}/$BaseType",
                        what=f"ComplexType '{complex_type.name}' base type",
                        allowed=("ComplexType",),
                        primitive=False,
                    )
                for prop in complex_type.properties:
                    self.check_type(
                        prop.type_expr,
                        path=f"{path}{_pointer(prop.name)}/$Type",
                        what=f"property '{complex_type.name}.{prop.name}'",
                        allowed=("ComplexType", "EnumType"),
                    )
            for association in schema.associations:
                self.association(namespace, association)
            if schema.entity_container is not None:
                self.container(namespace, schema)
        return self.issues

    def entity(self, namespace: str, entity: ODataEntityType) -> None:
        """Check an entity type's base type, property types and key."""
        path = _pointer(namespace, entity.name)
        external_base = False
        if entity.base_type:
            resolved = self.check_type(
                entity.base_type,
                path=f"{path}/$BaseType",
                what=f"EntityType '{entity.name}' base type",
                allowed=("EntityType",),
                primitive=False,
            )
            external_base = resolved is None and _split_qualified(self.qualify(entity.base_type))[0] in self.external
        for prop in entity.properties:
            self.check_type(
                prop.type_expr,
                path=f"{path}{_pointer(prop.name)}/$Type",
                what=f"property '{entity.name}.{prop.name}'",
                allowed=("ComplexType", "EnumType"),
            )
        chain = self.lineage(f"{namespace}.{entity.name}")
        inherited = next((base for base in chain[1:] if base.key_properties), None)
        if not entity.key_properties:
            if inherited is None and not entity.abstract and not external_base:
                self.issues.append(
                    ResolutionIssue(
                        ISSUE_KEY,
                        path,
                        f"entity type '{entity.name}' declares no key and inherits none; a non-abstract "
                        f"entity type must have one.",
                    )
                )
            return
        if inherited is not None:
            self.issues.append(
                ResolutionIssue(
                    ISSUE_KEY,
                    f"{path}/$Key",
                    f"entity type '{entity.name}' declares a key although its base type already has one; "
                    f"a derived type inherits its key and must not redeclare it.",
                )
            )
        properties = {prop.name: prop for base in chain for prop in base.properties}
        for position, key_name in enumerate(entity.key_properties):
            entry_path = f"{path}/$Key/{position}"
            prop = properties.get(key_name)
            if prop is None:
                if not external_base:
                    self.issues.append(
                        ResolutionIssue(
                            ISSUE_KEY,
                            entry_path,
                            f"key of entity type '{entity.name}' names `{key_name}`, which is not a "
                            f"property of `{entity.name}`.",
                        )
                    )
                continue
            if prop.nullable is True:
                self.issues.append(
                    ResolutionIssue(
                        ISSUE_KEY,
                        entry_path,
                        f"key property `{key_name}` of entity type '{entity.name}' is nullable; key "
                        f'properties must be declared `Nullable="false"`.',
                    )
                )
            type_name, collection = _split_type(prop.type_expr)
            if (
                collection
                or (type_name and type_name.startswith("Edm.") and type_name not in _KEY_PRIMITIVES)
                or (type_name and self.kinds.get(self.qualify(type_name)) == "ComplexType")
            ):
                self.issues.append(
                    ResolutionIssue(
                        ISSUE_KEY,
                        entry_path,
                        f"key property `{key_name}` of entity type '{entity.name}' has type "
                        f"`{prop.type_expr}`, which cannot be part of a key.",
                    )
                )

    def association(self, namespace: str, association: Any) -> None:
        """Check an association's end types and referential-constraint properties."""
        path = _pointer(namespace, association.name)
        ends: Dict[str, Optional[str]] = {}
        for end in association.ends:
            ends[end.role] = self.check_type(
                end.type_expr,
                path=f"{path}/End{_pointer(end.role)}",
                what=f"association '{association.name}' end '{end.role}'",
                allowed=("EntityType",),
                primitive=False,
            )
        for constraint in association.referential_constraints:
            for role, names in (
                (constraint.principal_role, constraint.principal_properties),
                (constraint.dependent_role, constraint.dependent_properties),
            ):
                if role not in ends:
                    self.issues.append(
                        ResolutionIssue(
                            ISSUE_REFERENCE,
                            f"{path}/ReferentialConstraint",
                            f"referential constraint of association '{association.name}' names role "
                            f"`{role}`, which the association does not declare.",
                        )
                    )
                    continue
                entity_name = ends[role]
                if entity_name is None:
                    continue
                declared = {prop.name for base in self.lineage(entity_name) for prop in base.properties}
                for name in names:
                    if name not in declared:
                        self.issues.append(
                            ResolutionIssue(
                                ISSUE_REFERENCE,
                                f"{path}/ReferentialConstraint",
                                f"referential constraint of association '{association.name}' names "
                                f"property `{name}`, which `{_split_qualified(entity_name)[1]}` does not declare.",
                            )
                        )

    def container(self, namespace: str, schema: ODataSchema) -> None:
        """Check entity sets, association sets and function imports."""
        container = schema.entity_container
        assert container is not None
        path = _pointer(namespace, container.name)
        set_names = {entity_set.name for entity_set in container.entity_sets}
        for entity_set in container.entity_sets:
            self.check_type(
                entity_set.entity_type,
                path=f"{path}{_pointer(entity_set.name)}/$Type",
                what=f"entity set '{entity_set.name}'",
                allowed=("EntityType",),
                primitive=False,
            )
        for association_set in container.association_sets:
            set_path = f"{path}{_pointer(association_set.name)}"
            association_name = self.check_type(
                association_set.association,
                path=f"{set_path}/Association",
                what=f"association set '{association_set.name}'",
                allowed=("Association",),
                primitive=False,
            )
            roles = {end.role for end in self.associations[association_name].ends} if association_name else None
            for end in association_set.ends:
                if roles is not None and end.role not in roles:
                    self.issues.append(
                        ResolutionIssue(
                            ISSUE_REFERENCE,
                            f"{set_path}/End{_pointer(end.role)}",
                            f"association set '{association_set.name}' names role `{end.role}`, which "
                            f"association `{association_set.association}` does not declare.",
                        )
                    )
                if end.entity_set not in set_names:
                    self.issues.append(
                        ResolutionIssue(
                            ISSUE_REFERENCE,
                            f"{set_path}/End{_pointer(end.role)}",
                            f"association set '{association_set.name}' names entity set "
                            f"`{end.entity_set}`, which the container does not declare.",
                        )
                    )
        for function_import in container.function_imports:
            import_path = f"{path}{_pointer(function_import.name)}"
            if function_import.return_type:
                self.check_type(
                    function_import.return_type,
                    path=f"{import_path}/ReturnType",
                    what=f"return type of function import '{function_import.name}'",
                    allowed=("EntityType", "ComplexType", "EnumType"),
                )
            if function_import.entity_set and function_import.entity_set not in set_names:
                self.issues.append(
                    ResolutionIssue(
                        ISSUE_REFERENCE,
                        f"{import_path}/EntitySet",
                        f"function import '{function_import.name}' names entity set "
                        f"`{function_import.entity_set}`, which the container does not declare.",
                    )
                )
            for parameter in function_import.parameters:
                self.check_type(
                    parameter.type_expr,
                    path=f"{import_path}/Parameter{_pointer(parameter.name)}",
                    what=f"parameter '{parameter.name}' of function import '{function_import.name}'",
                    allowed=("EntityType", "ComplexType", "EnumType"),
                )


def resolve_legacy_document(document: ODataDocument) -> List[ResolutionIssue]:
    """Resolve every reference and key of a parsed OData v2/v3 document.

    Args:
        document: The parsed document (:func:`app.odata_parser.parse_odata`).

    Returns:
        Every issue found, in document order.
    """
    return _LegacyResolver(document).run()


def resolve_odata_document(document: ODataDocument) -> Tuple[List[ResolutionIssue], int]:
    """Resolve a parsed document with the reader its version calls for.

    v4 is resolved from ``document.csdl_json`` (so it must already carry it,
    :func:`app.odata_csdl_json.with_csdl_validation`); v2/v3 from the parsed model.

    Args:
        document: The parsed document.

    Returns:
        The first :data:`MAX_REPORTED_ISSUES` issues, and how many there were in all.
    """
    if document.csdl_json is not None:
        return _capped(resolve_csdl_json(document.csdl_json))
    if document.dialect is not None and not document.dialect.is_v4:
        return _capped(resolve_legacy_document(document))
    return [], 0
