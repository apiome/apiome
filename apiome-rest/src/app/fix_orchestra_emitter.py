"""FIX Orchestra emitter: canonical model → Orchestra repository XML — MFX-37.1 (#4323).

The inverse of the FIX Orchestra importer (FMT-6.9, :mod:`app.fix_orchestra_normalizer`): an item's types
become a **FIX Orchestra 1.0 repository** (namespace ``http://fixprotocol.io/2020/orchestra/repository``),
one ``<name>.orchestra.xml`` document valid against the official Orchestra XSD
(:data:`ORCHESTRA_XSD`, vendored from FIX Trading Community).

What becomes what
-----------------
* **Messages** — the records a source marks as Orchestra messages (``fix_kind = message``); otherwise the
  **root records** (records no other record holds). Each keeps its ``msgType``, ``flow``, scenario and
  ``responses`` when the source carries them.
* **Components** — records another record holds as a field (``componentRef``).
* **Repeating groups** — records held as a list (``groupRef``), each with its ``NumInGroup`` counter field.
  A list of plain values, and a map, become a group of their own (one entry field; a ``key`` and a
  ``value``), and that is reported.
* **Code sets** — enumerations; each value is a code (``Buy`` = ``1``).
* **Fields** — every field, declared once in ``fields`` with its **tag** (``id``) and datatype, and
  referenced by tag from each structure (``fieldRef``), with its presence (``required`` / ``optional`` /
  ``forbidden`` / ``ignored`` / ``constant``) and conditional rules.
* **Actors and flows** — written when the source carries them (an imported Orchestra repository).

Tags and ids
------------
An imported FIX source keeps its tags and its message, component, group and code-set ids. Other sources
have none, so the emitter assigns them: tags from **5000** (FIX's user-defined range), skipping every tag
the source already uses; ids from 1. The assignment is deterministic for a given model; persisting it across
re-exports is MFX-37.2.

Every decision the emitter makes up is recorded as a loss. Whatever the XSD requires and the model lacks
(a code set when the model has no enumeration, a ``version`` the schema's pattern accepts) is synthesized
and reported.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union

from pydantic import Field, ValidationError

from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    Loss,
    LossKind,
    LossTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, types_only_advisory
from .import_source import DiffChangeKind
from .lossiness import LossinessReport, LossinessSeverity

__all__ = [
    "ORCHESTRA_FORMAT_KEY",
    "ORCHESTRA_NAMESPACE",
    "ORCHESTRA_XSD",
    "FixOrchestraEmitOptions",
    "FixOrchestraEmitter",
    "FixOrchestraFidelityRulePack",
    "orchestra_schema_problems",
]

#: Registry key and format — the importer's, so ``fix-orchestra -> fix-orchestra`` pairs in the matrix.
ORCHESTRA_FORMAT_KEY = "fix-orchestra"
ORCHESTRA_NAMESPACE = "http://fixprotocol.io/2020/orchestra/repository"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
XML_MEDIA_TYPE = "application/xml"
ORCHESTRA_SUFFIX = ".orchestra.xml"
#: The vendored official Orchestra 1.0 repository schema (FIX Trading Community, Apache-2.0).
ORCHESTRA_XSD_DIR = Path(__file__).resolve().parent / "data" / "fix_orchestra_xsd"
ORCHESTRA_XSD = ORCHESTRA_XSD_DIR / "repository.xsd"

#: The first tag the emitter assigns: FIX's user-defined range starts at 5000.
FIRST_SYNTHESIZED_TAG = 5000
#: The schema's ``Version_t`` pattern.
_VERSION = re.compile(r"(FIX.2.7)|(FIX.3.0)|(FIX\.4\.[0-4])|((FIX.Latest|(FIX\.5\.0(SP\d{1,2})?))"
                      r"(_EP((9[8-9])|([1-9][0-9][0-9])))?)|(FIXT.1.1)|([0-9]+)\.([0-9]+)|(\d{8})")
_SEMVER = re.compile(r"^(\d+)\.(\d+)")
_NAME_SAFE = re.compile(r"[^0-9A-Za-z_]")
_SCENARIO_SAFE = re.compile(r"[^0-9A-Za-z_-]")
_PRESENCES = frozenset({"required", "optional", "forbidden", "ignored", "constant"})
_RELIABILITY = frozenset({"bestEffort", "idempotent", "recoverable"})

#: Loss subjects.
LOSS_TAG_SYNTHESIZED = "orchestra-tag-synthesized"
LOSS_LIST_AS_GROUP = "orchestra-list-as-group"
LOSS_MAP_AS_GROUP = "orchestra-map-as-group"
LOSS_UNION_AS_COMPONENT = "orchestra-union-as-component"
LOSS_RENAMED = "orchestra-name-rewritten"
LOSS_EMPTY = "orchestra-empty-structure-dropped"
LOSS_PLACEHOLDER_CODESET = "orchestra-placeholder-code-set"
LOSS_VERSION = "orchestra-version-rewritten"
LOSS_UNTYPED = "orchestra-untyped-as-string"
LOSS_SERVICES = "orchestra-services-dropped"
LOSS_STATE_MACHINE = "orchestra-state-machine-dropped"
SYNTH_SUBJECTS = frozenset({LOSS_TAG_SYNTHESIZED, LOSS_PLACEHOLDER_CODESET})

#: Canonical scalar (lower-case) → FIX datatype.
_DATATYPES: Dict[str, str] = {
    "string": "String", "str": "String", "text": "String",
    "integer": "int", "int": "int", "int8": "int", "int16": "int", "int32": "int", "int64": "int", "long": "int",
    "uint8": "int", "uint16": "int", "uint32": "int", "uint64": "int",
    "number": "float", "float": "float", "double": "float", "float32": "float", "float64": "float",
    "decimal": "float", "numeric": "float", "bigdecimal": "float",
    "boolean": "Boolean", "bool": "Boolean",
    "bytes": "data", "binary": "data", "byte": "data",
    "date": "LocalMktDate", "datetime": "UTCTimestamp", "date-time": "UTCTimestamp", "timestamp": "UTCTimestamp",
    "time": "UTCTimeOnly",
}
#: String formats → FIX datatype.
_FORMATS: Dict[str, str] = {"date-time": "UTCTimestamp", "date": "LocalMktDate", "time": "UTCTimeOnly"}
#: FIX datatypes the emitter declares, with their base type (the standard FIX Latest set it can write).
_STANDARD_BASES: Dict[str, Optional[str]] = {
    "int": None, "float": None, "char": None, "String": None, "data": None, "Boolean": "char",
    "NumInGroup": "int", "UTCTimestamp": "String", "LocalMktDate": "String", "UTCTimeOnly": "String",
}


class FixOrchestraEmitOptions(EmitOptions):
    """Per-target options for :class:`FixOrchestraEmitter`."""

    version: Optional[str] = Field(
        default=None,
        description="The repository's `version` (`FIX.Latest`, `FIX.4.4`, `FIX.5.0SP2_EP254`, `1.0` …). Empty "
        "means the source's own FIX version, else the item's version as `major.minor`, else `FIX.Latest`.",
    )


# ===========================================================================
# Names
# ===========================================================================


def _fix_name(name: str) -> str:
    """A legal Orchestra ``Name_t``: a letter, then letters, digits and underscores."""
    safe = _NAME_SAFE.sub("_", name).strip("_") or "Unnamed"
    if not safe[0].isalpha():
        safe = f"F{safe}"
    return safe[:255]


def _scenario(value: Any) -> Optional[str]:
    """A legal non-base scenario name, or ``None`` for the base scenario."""
    if not value or value == "base":
        return None
    safe = _SCENARIO_SAFE.sub("_", str(value))
    return safe if safe[:1].isalpha() else f"S{safe}"


def _int(value: Any) -> Optional[int]:
    """A positive integer id, or ``None``."""
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ===========================================================================
# The repository model the emitter builds, then writes
# ===========================================================================


@dataclass
class _FieldDef:
    tag: int
    name: str
    datatype: str
    description: Optional[str] = None
    scenario: Optional[str] = None


@dataclass
class _Ref:
    """One member of a structure: a ``fieldRef``, ``componentRef`` or ``groupRef``."""

    kind: str  # field | component | group
    id: int
    presence: str = "optional"
    scenario: Optional[str] = None
    value: Optional[str] = None
    rules: List[Dict[str, Any]] = field(default_factory=list)
    description: Optional[str] = None


@dataclass
class _Structure:
    """A message, component or group."""

    kind: str  # message | component | group
    name: str
    id: int
    members: List[_Ref] = field(default_factory=list)
    scenario: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    msg_type: Optional[str] = None
    flow: Optional[str] = None
    responses: List[Dict[str, Any]] = field(default_factory=list)
    num_in_group: Optional[int] = None


@dataclass
class _CodeSet:
    name: str
    id: int
    type: str
    codes: List[Tuple[str, int, str, Optional[str]]]  # name, id, value, description
    scenario: Optional[str] = None
    description: Optional[str] = None


class _Builder:
    """Lays a canonical model out as an Orchestra repository, recording every loss."""

    def __init__(self, api: CanonicalApi, losses: LossTracker) -> None:
        self.api = api
        self.losses = losses
        self.types: Dict[str, Type] = {t.key: t for t in api.types}
        self._by_name: Dict[str, Type] = {t.name: t for t in api.types}
        self.fields: Dict[Tuple[str, Optional[str]], _FieldDef] = {}
        self.structures: Dict[Tuple[str, str], _Structure] = {}  # (kind, type key or synthetic key)
        self.code_sets: Dict[str, _CodeSet] = {}  # enum type key → code set
        self.datatypes: Dict[str, Optional[str]] = {}
        self._tags_used: Set[int] = set()
        self._next_tag = FIRST_SYNTHESIZED_TAG
        self._ids_used: Dict[str, Set[Tuple[int, Optional[str]]]] = {"message": set(), "component": set(),
                                                                       "group": set(), "codeSet": set()}
        self._names_used: Dict[str, Set[Tuple[str, Optional[str]]]] = {"message": set(), "component": set(),
                                                                         "group": set(), "codeSet": set(),
                                                                         "field": set()}
        self._next_id: Dict[str, int] = {"message": 1, "component": 1001, "group": 2001, "codeSet": 1}
        for name, base in ((d.get("name"), d.get("base_type")) for d in (api.extras or {}).get("fix_datatypes") or []):
            if name:
                self.datatypes[_fix_name(str(name))] = _fix_name(str(base)) if base else None
        self._reserve_source_tags()

    # --- lookups ----------------------------------------------------------

    def type_of(self, name: Optional[str]) -> Optional[Type]:
        if name is None:
            return None
        return self.types.get(name) or self._by_name.get(name)

    def _resolve(self, ref: TypeRef, seen: Tuple[str, ...] = ()) -> Tuple[TypeRef, Optional[Type]]:
        """Follow aliases; return the reference and the named type it lands on (``None`` for a scalar)."""
        target = self.type_of(ref.name) if ref.item is None else None
        while target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None \
                and target.key not in seen:
            seen = seen + (target.key,)
            ref = TypeRef(name=target.aliased.name, item=target.aliased.item, nullable=ref.nullable)
            target = self.type_of(ref.name) if ref.item is None else None
        return ref, target

    # --- ids and tags -----------------------------------------------------

    def _reserve_source_tags(self) -> None:
        for type_ in self.api.types:
            for member in type_.fields:
                tag = _int((member.extras or {}).get("fix_tag"))
                if tag is not None:
                    self._tags_used.add(tag)

    def _fresh_tag(self) -> int:
        while self._next_tag in self._tags_used:
            self._next_tag += 1
        tag = self._next_tag
        self._tags_used.add(tag)
        return tag

    def _take_id(self, kind: str, wanted: Any, scenario: Optional[str]) -> Tuple[int, bool]:
        """A unique id for a structure or code set: the source's when free, else the next one. ``(id, made_up)``."""
        used = self._ids_used[kind]
        number = _int(wanted)
        if number is not None and (number, scenario) not in used:
            used.add((number, scenario))
            return number, False
        while (self._next_id[kind], scenario) in used:
            self._next_id[kind] += 1
        number = self._next_id[kind]
        used.add((number, scenario))
        return number, True

    def _take_name(self, kind: str, wanted: str, scenario: Optional[str], pointer: str) -> str:
        """A unique legal name among ``kind`` (the scenario makes a name distinct)."""
        base = _fix_name(wanted)
        if base != wanted:
            self.losses.record(LossKind.INFERRED, LOSS_RENAMED,
                               f"{wanted!r} is not an Orchestra name; written as {base!r}", pointer)
        candidate, n = base, 2
        while (candidate, scenario) in self._names_used[kind]:
            candidate = f"{base}_{n}"
            n += 1
        self._names_used[kind].add((candidate, scenario))
        return candidate

    # --- fields -----------------------------------------------------------

    def field_def(self, member: CanonicalField, name: str, datatype: str) -> _FieldDef:
        """The repository field a structure's member refers to (declared once per name and datatype)."""
        extras = member.extras or {}
        scenario = _scenario(extras.get("fix_field_scenario"))
        source_tag = _int(extras.get("fix_tag"))
        wanted = str(extras.get("fix_field_name") or name)
        fix_name = _fix_name(wanted)
        if fix_name != wanted:
            self.losses.record(LossKind.INFERRED, LOSS_RENAMED,
                               f"{wanted!r} is not an Orchestra name; written as {fix_name!r}", member.key)
        existing = self.fields.get((fix_name, scenario))
        if existing is not None and existing.datatype == datatype and (source_tag in (None, existing.tag)):
            return existing
        if existing is not None:
            fix_name = self._take_name("field", fix_name, scenario, member.key)
        else:
            self._names_used["field"].add((fix_name, scenario))
        if source_tag is not None and not any(f.tag == source_tag for f in self.fields.values()):
            tag = source_tag
        else:
            tag = self._fresh_tag()
            self.losses.record(LossKind.INFERRED, LOSS_TAG_SYNTHESIZED,
                               f"{member.key!r} has no FIX tag; tag {tag} is assigned (user-defined range)",
                               member.key)
        definition = _FieldDef(tag=tag, name=fix_name, datatype=datatype,
                               description=member.description, scenario=scenario)
        self.fields[(fix_name, scenario)] = definition
        return definition

    def _datatype(self, member: CanonicalField, scalar: str) -> str:
        extras = member.extras or {}
        if extras.get("fix_datatype"):
            name = _fix_name(str(extras["fix_datatype"]))
        else:
            fmt = (member.constraints.format or "").lower() if member.constraints and member.constraints.format else ""
            lowered = scalar.lower()
            if fmt in _FORMATS and lowered in ("string", "str", "text"):
                name = _FORMATS[fmt]
            elif lowered in _DATATYPES:
                name = _DATATYPES[lowered]
            else:
                self.losses.record(LossKind.INFERRED, LOSS_UNTYPED,
                                   f"{member.key!r} has the untyped or unknown type {scalar!r}; written as a String",
                                   member.key)
                name = "String"
        self.datatypes.setdefault(name, _STANDARD_BASES.get(name))
        return name

    # --- structures -------------------------------------------------------

    def structure(self, kind: str, type_: Type) -> _Structure:
        """The message, component or group for a record (built once)."""
        key = (kind, type_.key)
        if key in self.structures:
            return self.structures[key]
        extras = type_.extras or {}
        scenario = _scenario(extras.get("fix_scenario"))
        wanted = str(extras.get("fix_msg_name") or type_.name)
        if scenario and wanted.endswith(f"_{scenario}"):
            wanted = wanted[: -len(scenario) - 1]
        if kind == "group" and (extras.get("fix_kind") != "group") and ("component", type_.key) in self.structures:
            wanted = f"{wanted}Grp"
        source_id = extras.get("fix_id") if extras.get("fix_kind") in (kind, None) else None
        number, _ = self._take_id(kind, source_id, scenario)
        built = _Structure(kind=kind, name=self._take_name(kind, wanted, scenario, type_.key), id=number,
                           scenario=scenario, description=type_.description,
                           category=_fix_name(str(extras["fix_category"])) if extras.get("fix_category") else None)
        self.structures[key] = built
        if kind == "message":
            msg_type = extras.get("fix_msg_type")
            built.msg_type = str(msg_type) if msg_type and 1 <= len(str(msg_type)) <= 2 else None
            built.flow = _fix_name(str(extras["fix_flow"])) if extras.get("fix_flow") else None
            built.responses = list(extras.get("fix_responses") or [])
        if kind == "group":
            counter = extras.get("fix_num_in_group")
            built.num_in_group = self._counter(type_, counter)
        built.members = self.members(type_)
        return built

    def _counter(self, type_: Type, source_tag: Any) -> int:
        """The NumInGroup counter field of a group: the source's, else ``No<Group>`` with a new tag."""
        tag = _int(source_tag)
        if tag is not None and any(f.tag == tag for f in self.fields.values()):
            return tag
        name = f"No{_fix_name(type_.name)}"
        member = CanonicalField(key=f"{type_.key}.{name}", name=name, type=TypeRef(name="integer", nullable=False),
                                extras={"fix_tag": tag} if tag is not None else {})
        self.datatypes.setdefault("NumInGroup", "int")
        return self.field_def(member, name, "NumInGroup").tag

    def synthetic_group(self, key: str, name: str, members: List[_Ref], pointer: str) -> _Structure:
        """A group the emitter makes up (a list of plain values, a map's entries)."""
        if ("group", key) in self.structures:
            return self.structures[("group", key)]
        number, _ = self._take_id("group", None, None)
        built = _Structure(kind="group", name=self._take_name("group", name, None, pointer), id=number)
        counter = CanonicalField(key=f"{pointer}.No{name}", name=f"No{name}", type=TypeRef(name="integer"))
        self.datatypes.setdefault("NumInGroup", "int")
        built.num_in_group = self.field_def(counter, f"No{_fix_name(name)}", "NumInGroup").tag
        built.members = members
        self.structures[("group", key)] = built
        return built

    def members(self, type_: Type) -> List[_Ref]:
        """The refs of a record's fields (in field-number order when the source numbered them)."""
        ordered = sorted(type_.fields, key=lambda m: (m.field_number is None, m.field_number or 0))
        refs: List[_Ref] = []
        for member in ordered:
            ref = self.member_ref(member)
            if ref is not None:
                refs.append(ref)
        return refs

    def member_ref(self, member: CanonicalField) -> Optional[_Ref]:
        """One member as a ref, with its presence, rules and scenario."""
        ref = self._ref_for(member, member.type, member.name)
        if ref is None:
            return None
        extras = member.extras or {}
        constraint_extras = (member.constraints.extras if member.constraints else None) or {}
        presence = str(constraint_extras.get("fix_presence") or extras.get("fix_presence") or "")
        if presence not in _PRESENCES:
            presence = "required" if member.type.nullable is False else "optional"
        ref.presence = presence
        if presence == "constant":
            value = member.default if member.default is not None else (
                member.constraints.enum[0] if member.constraints and member.constraints.enum else None)
            if value is None:
                ref.presence = "required"
            else:
                ref.value = str(value)
        ref.scenario = _scenario(extras.get("fix_ref_scenario"))
        ref.rules = [r for r in constraint_extras.get("fix_rules") or [] if isinstance(r, Mapping) and r.get("when")]
        if ref.kind != "field":
            ref.description = member.description
        return ref

    def _ref_for(self, member: CanonicalField, type_ref: TypeRef, name: str) -> Optional[_Ref]:
        resolved, target = self._resolve(type_ref)
        if resolved.item is not None:
            return self._list_ref(member, resolved.item, name)
        if target is not None and target.kind is TypeKind.RECORD:
            if not target.fields:
                self.losses.record(LossKind.NA, LOSS_EMPTY, f"{member.key!r} holds {target.key!r}, a record with "
                                   "no fields; an Orchestra component needs at least one member", member.key)
                return None
            component = self.structure("component", target)
            return _Ref(kind="component", id=component.id, scenario=component.scenario) if component.members else None
        if target is not None and target.kind is TypeKind.MAP:
            return self._map_ref(member, target, name)
        if target is not None and target.kind is TypeKind.UNION:
            return self._union_ref(member, target)
        if target is not None and target.kind is TypeKind.ENUM:
            code_set = self.code_set(target)
            definition = self.field_def(member, name, code_set.name)
            return _Ref(kind="field", id=definition.tag)
        scalar = resolved.name or "any"
        definition = self.field_def(member, name, self._datatype(member, scalar))
        return _Ref(kind="field", id=definition.tag)

    def _list_ref(self, member: CanonicalField, item: TypeRef, name: str) -> Optional[_Ref]:
        resolved, target = self._resolve(item)
        if resolved.item is None and target is not None and target.kind is TypeKind.RECORD:
            if not target.fields:
                self.losses.record(LossKind.NA, LOSS_EMPTY, f"{member.key!r} is a list of {target.key!r}, a record "
                                   "with no fields; an Orchestra group needs at least one member", member.key)
                return None
            group = self.structure("group", target)
            return _Ref(kind="group", id=group.id, scenario=group.scenario)
        self.losses.record(LossKind.INFERRED, LOSS_LIST_AS_GROUP,
                           f"{member.key!r} is a list of plain values; Orchestra repeats only groups, so it is a group "
                           "with one entry field", member.key)
        entry = CanonicalField(key=member.key, name=name, type=resolved, extras=member.extras or {},
                               description=member.description, constraints=member.constraints)
        inner = self._ref_for(entry, resolved, name)
        if inner is None:
            return None
        group = self.synthetic_group(f"{member.key}[]", f"{_fix_name(name)}Grp", [inner], member.key)
        return _Ref(kind="group", id=group.id)

    def _map_ref(self, member: CanonicalField, target: Type, name: str) -> Optional[_Ref]:
        self.losses.record(LossKind.INFERRED, LOSS_MAP_AS_GROUP,
                           f"{member.key!r} holds the map {target.key!r}; Orchestra has no map, so it is a group of "
                           "key / value entries", member.key)
        if ("group", target.key) not in self.structures:
            key_field = CanonicalField(key=f"{target.key}.key", name=f"{_fix_name(target.name)}Key",
                                       type=TypeRef(name=(target.key_type or TypeRef(name="string")).name or "string",
                                                    nullable=False))
            value_field = CanonicalField(key=f"{target.key}.value", name=f"{_fix_name(target.name)}Value",
                                         type=target.value_type or TypeRef(name="string"))
            members = [r for r in (self.member_ref(key_field), self.member_ref(value_field)) if r is not None]
            self.synthetic_group(target.key, f"{_fix_name(target.name)}Grp", members, member.key)
        return _Ref(kind="group", id=self.structures[("group", target.key)].id)

    def _union_ref(self, member: CanonicalField, target: Type) -> Optional[_Ref]:
        self.losses.record(LossKind.INFERRED, LOSS_UNION_AS_COMPONENT,
                           f"{member.key!r} holds the union {target.key!r}; Orchestra has no union, so it is a "
                           "component with one optional member per alternative", member.key)
        key = ("component", target.key)
        if key not in self.structures:
            number, _ = self._take_id("component", None, None)
            built = _Structure(kind="component", name=self._take_name("component", target.name, None, target.key),
                               id=number, description=target.description)
            self.structures[key] = built
            for alternative in target.union_members:
                alt_type = self.type_of(alternative)
                alt_name = alt_type.name if alt_type is not None else alternative
                alt = CanonicalField(key=f"{target.key}.{alt_name}", name=alt_name, type=TypeRef(name=alternative))
                ref = self.member_ref(alt)
                if ref is not None:
                    ref.presence = "optional"
                    built.members.append(ref)
        built = self.structures[key]
        return _Ref(kind="component", id=built.id) if built.members else None

    # --- code sets --------------------------------------------------------

    def code_set(self, type_: Type) -> _CodeSet:
        """The code set of an enumeration (built once)."""
        if type_.key in self.code_sets:
            return self.code_sets[type_.key]
        extras = type_.extras or {}
        scenario = _scenario(extras.get("fix_scenario"))
        wanted = type_.name
        if scenario and wanted.endswith(f"_{scenario}"):
            wanted = wanted[: -len(scenario) - 1]
        number, _ = self._take_id("codeSet", extras.get("fix_id"), scenario)
        values = [str(v.value if v.value is not None else v.name) for v in type_.enum_values]
        # Single-character codes are FIX `char` (Side: 1 = Buy), then whole numbers `int`, else `String`.
        code_type = extras.get("fix_code_type") or (
            "char" if values and all(len(v) == 1 for v in values)
            else "int" if values and all(re.fullmatch(r"-?\d+", v) for v in values) else "String")
        code_type = _fix_name(str(code_type))
        self.datatypes.setdefault(code_type, _STANDARD_BASES.get(code_type))
        codes = []
        taken: Set[str] = set()
        for index, enum_value in enumerate(type_.enum_values, start=1):
            code_name, n = _fix_name(enum_value.name), 2
            base = code_name
            while code_name in taken:
                code_name, n = f"{base}_{n}", n + 1
            taken.add(code_name)
            code_id = _int((enum_value.extras or {}).get("fix_code_id")) or number * 1000 + index
            codes.append((code_name, code_id, values[index - 1], enum_value.description))
        built = _CodeSet(name=self._take_name("codeSet", wanted, scenario, type_.key), id=number, type=code_type,
                         codes=codes, scenario=scenario, description=type_.description)
        self.code_sets[type_.key] = built
        return built


# ===========================================================================
# Building and writing
# ===========================================================================


def _referenced(api: CanonicalApi) -> Set[str]:
    """Every type key a record field, map, union or alias refers to."""
    keys = {t.key for t in api.types}
    by_name = {t.name: t.key for t in api.types}
    seen: Set[str] = set()

    def visit(ref: Optional[TypeRef]) -> None:
        while ref is not None and ref.item is not None:
            ref = ref.item
        if ref is not None and ref.name:
            seen.add(ref.name if ref.name in keys else by_name.get(ref.name, ref.name))

    for type_ in api.types:
        for member in type_.fields:
            visit(member.type)
        visit(type_.key_type)
        visit(type_.value_type)
        visit(type_.aliased)
        seen.update(type_.union_members)
    return seen


def _message_types(api: CanonicalApi) -> List[Type]:
    """The records written as messages: the source's messages, else the root records."""
    records = [t for t in api.types if t.kind is TypeKind.RECORD]
    marked = [t for t in records if (t.extras or {}).get("fix_kind") == "message"]
    if marked:
        return marked
    if any((t.extras or {}).get("fix_kind") for t in records):
        return []
    referenced = _referenced(api)
    return [t for t in records if t.key not in referenced] or records


def _version(api: CanonicalApi, options: FixOrchestraEmitOptions, losses: LossTracker) -> str:
    """The repository ``version``: the option, the source's FIX version, ``major.minor``, else ``FIX.Latest``."""
    for candidate in (options.version, (api.extras or {}).get("fix_repository_version")):
        if candidate and _VERSION.fullmatch(str(candidate)):
            return str(candidate)
    if options.version:
        raise EmitOptionsError(f"{options.version!r} is not an Orchestra version (`FIX.Latest`, `FIX.4.4`, `1.0` …).")
    source = (api.extras or {}).get("fix_repository_version") or api.version
    stem = str(source or "").split("_EP")[0]  # an extension pack the pattern refuses (EP001) is dropped
    match = _SEMVER.match(str(source or ""))
    if stem and _VERSION.fullmatch(stem):
        version = stem
    else:
        version = f"{match.group(1)}.{match.group(2)}" if match else "FIX.Latest"
    if source and str(source) != version:
        losses.record(LossKind.INFERRED, LOSS_VERSION, f"the version {source!r} is not an Orchestra version; "
                      f"written as {version!r}", "")
    return version


def _el(parent: ET.Element, tag: str, **attributes: Any) -> ET.Element:
    """A ``fixr:`` child element with the attributes that are set."""
    element = ET.SubElement(parent, f"{{{ORCHESTRA_NAMESPACE}}}{tag}")
    for name, value in attributes.items():
        if value is not None:
            element.set(name, str(value))
    return element


def _annotate(parent: ET.Element, text: Optional[str]) -> None:
    if text:
        _el(_el(parent, "annotation"), "documentation").text = text


def _write_ref(parent: ET.Element, ref: _Ref, tag: Optional[str] = None) -> None:
    element = _el(parent, tag or f"{ref.kind}Ref", id=ref.id, scenario=ref.scenario,
                  presence=None if ref.presence == "optional" else ref.presence,
                  value=ref.value if ref.kind == "field" else None)
    for rule in ref.rules:
        rule_el = _el(element, "rule", name=_fix_name(str(rule["name"])) if rule.get("name") else None,
                      presence=rule.get("presence") if rule.get("presence") in _PRESENCES else None)
        _el(rule_el, "when").text = str(rule["when"])
    _annotate(element, ref.description)


def _write_actors(root: ET.Element, api: CanonicalApi, builder: _Builder, losses: LossTracker) -> None:
    """Actors (with their state machines) and flows, when the source carries them."""
    extras = api.extras or {}
    actors = [a for a in extras.get("fix_actors") or [] if isinstance(a, Mapping) and a.get("name")]
    if not actors:
        return
    container = _el(root, "actors")
    names: Set[str] = set()
    by_name = {f.name: f for f in builder.fields.values()}
    for actor in actors:
        name = _fix_name(str(actor["name"]))
        names.add(name)
        actor_el = _el(container, "actor", name=name)
        for field_name in actor.get("fields") or []:
            definition = by_name.get(_fix_name(str(field_name)))
            if definition is not None:
                _el(actor_el, "fieldRef", id=definition.tag)
        for machine in actor.get("state_machines") or []:
            states = machine.get("states") or []
            if len(states) < 2:
                losses.record(LossKind.NA, LOSS_STATE_MACHINE, f"the state machine {machine.get('name')!r} of "
                              f"{actor['name']!r} has fewer than two states; Orchestra needs an initial state and "
                              "at least one other", "")
                continue
            machine_el = _el(actor_el, "states", name=_fix_name(str(machine.get("name") or "States")))
            for index, state in enumerate(states):
                state_el = _el(machine_el, "initial" if index == 0 else "state", name=_fix_name(str(state["name"])))
                for transition in state.get("transitions") or []:
                    if not transition.get("name") or not transition.get("target"):
                        continue
                    transition_el = _el(state_el, "transition", name=_fix_name(str(transition["name"])),
                                        target=str(transition["target"]))
                    if transition.get("when"):
                        _el(transition_el, "when").text = str(transition["when"])
    for flow in extras.get("fix_flows") or []:
        if not isinstance(flow, Mapping) or not flow.get("name"):
            continue
        source, destination = _fix_name(str(flow.get("source") or "")), _fix_name(str(flow.get("destination") or ""))
        if source in names and destination in names:
            reliability = flow.get("reliability") if flow.get("reliability") in _RELIABILITY else None
            _el(container, "flow", name=_fix_name(str(flow["name"])), source=source, destination=destination,
                reliability=reliability)


def build_orchestra_repository(api: CanonicalApi, options: Optional[FixOrchestraEmitOptions] = None,
                               losses: Optional[LossTracker] = None) -> ET.Element:
    """Lay a canonical model out as an Orchestra repository element.

    Args:
        api: The canonical model.
        options: The emit options.
        losses: Where every made-up or approximated decision is recorded.

    Returns:
        The ``fixr:repository`` root element.

    Raises:
        EmitPreconditionError: When the model has no record type, or none yields a message with a member.
        EmitOptionsError: When ``version`` is not an Orchestra version.
    """
    options = options or FixOrchestraEmitOptions()
    losses = losses if losses is not None else LossTracker()
    if not any(t.kind is TypeKind.RECORD for t in api.types):
        raise EmitPreconditionError("An Orchestra repository describes messages, and this model has no record type.")
    builder = _Builder(api, losses)
    messages: List[_Structure] = []
    for type_ in _message_types(api):
        message = builder.structure("message", type_)
        if message.members:
            messages.append(message)
        else:
            losses.record(LossKind.NA, LOSS_EMPTY, f"{type_.key!r} has no field Orchestra can hold; a message "
                          "needs at least one member", type_.key)
    if not messages:
        raise EmitPreconditionError("No record has a field an Orchestra message can hold.")
    for type_ in api.types:  # every enumeration is a code set, used or not
        if type_.kind is TypeKind.ENUM:
            builder.code_set(type_)
    if not builder.code_sets:
        losses.record(LossKind.INFERRED, LOSS_PLACEHOLDER_CODESET, "Orchestra requires at least one code set and "
                      "the model has no enumeration; an empty `NoCodeSet` is written", "")
    version = _version(api, options, losses)

    ET.register_namespace("fixr", ORCHESTRA_NAMESPACE)
    ET.register_namespace("dc", DC_NAMESPACE)
    extras = api.extras or {}
    root = ET.Element(f"{{{ORCHESTRA_NAMESPACE}}}repository",
                      {"name": str(extras.get("fix_repository_name") or api.identity.name or api.title or "Repository"),
                       "version": version})
    metadata = _el(root, "metadata")
    title = api.title or api.identity.name or "FIX Orchestra repository"
    ET.SubElement(metadata, f"{{{DC_NAMESPACE}}}title").text = title
    if api.description:
        ET.SubElement(metadata, f"{{{DC_NAMESPACE}}}description").text = api.description

    datatypes = _el(root, "datatypes")
    for name in sorted(builder.datatypes):
        _el(datatypes, "datatype", name=name, baseType=builder.datatypes[name])

    code_sets = _el(root, "codeSets")
    if builder.code_sets:
        for code_set in sorted(builder.code_sets.values(), key=lambda c: (c.id, c.scenario or "")):
            set_el = _el(code_sets, "codeSet", id=code_set.id, name=code_set.name, scenario=code_set.scenario,
                         type=code_set.type)
            for code_name, code_id, value, description in code_set.codes:
                code_el = _el(set_el, "code", id=code_id, name=code_name, value=value)
                _annotate(code_el, description)
            _annotate(set_el, code_set.description)
    else:
        builder.datatypes.setdefault("String", None)
        _el(code_sets, "codeSet", id=1, name="NoCodeSet", type="String")
        if not any(d.get("name") == "String" for d in datatypes):
            _el(datatypes, "datatype", name="String")

    fields_el = _el(root, "fields")
    for definition in sorted(builder.fields.values(), key=lambda f: (f.tag, f.scenario or "")):
        field_el = _el(fields_el, "field", id=definition.tag, name=definition.name, scenario=definition.scenario,
                       type=definition.datatype)
        _annotate(field_el, definition.description)

    _write_actors(root, api, builder, losses)

    for kind, container_tag in (("component", "components"), ("group", "groups")):
        structures = sorted((s for (k, _), s in builder.structures.items() if k == kind and s.members),
                            key=lambda s: (s.id, s.scenario or ""))
        if not structures:
            continue
        container = _el(root, container_tag)
        for structure in structures:
            element = _el(container, kind, id=structure.id, name=structure.name, scenario=structure.scenario,
                          category=structure.category)
            if kind == "group" and structure.num_in_group is not None:
                _el(element, "numInGroup", id=structure.num_in_group)
            for ref in structure.members:
                _write_ref(element, ref)
            _annotate(element, structure.description)

    message_ids = {m.name: m.id for m in messages}
    messages_el = _el(root, "messages")
    for message in sorted(messages, key=lambda m: (m.id, m.scenario or "")):
        element = _el(messages_el, "message", id=message.id, name=message.name, scenario=message.scenario,
                      msgType=message.msg_type, category=message.category, flow=message.flow)
        structure_el = _el(element, "structure")
        for ref in message.members:
            _write_ref(structure_el, ref)
        responses = []
        for response in message.responses:
            refs = [(ref.get("name"), ref.get("msgType")) for ref in response.get("messages") or []
                    if isinstance(ref, Mapping) and _fix_name(str(ref.get("name") or "")) in message_ids]
            if refs:
                responses.append((response.get("name"), refs))
        if responses:
            responses_el = _el(element, "responses")
            for name, refs in responses:
                response_el = _el(responses_el, "response", name=_fix_name(str(name)) if name else None)
                for ref_name, msg_type in refs:
                    fixed = _fix_name(str(ref_name))
                    _el(response_el, "messageRef", name=fixed, id=message_ids[fixed],
                        msgType=msg_type if msg_type and 1 <= len(str(msg_type)) <= 2 else None)
        _annotate(element, message.description)
    if any(s.operations for s in api.services) or api.channels:
        losses.record(LossKind.NA, LOSS_SERVICES, "An Orchestra repository describes messages; the API's operations "
                      "and channels are not written", "")
    return root


def render_orchestra(root: ET.Element) -> str:
    """The repository element as an indented XML document."""
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def orchestra_schema():  # noqa: ANN201 - xmlschema has no public type for this
    """The vendored official Orchestra 1.0 schema, loaded offline (``allow='sandbox'``), once."""
    global _SCHEMA
    if _SCHEMA is None:
        import xmlschema  # noqa: PLC0415 - only exports need it

        _SCHEMA = xmlschema.XMLSchema(
            str(ORCHESTRA_XSD), allow="sandbox",
            locations=[("http://www.w3.org/XML/1998/namespace", str(ORCHESTRA_XSD_DIR / "xml.xsd"))])
    return _SCHEMA


_SCHEMA = None


def orchestra_schema_problems(text: str) -> List[Dict[str, str]]:
    """Validate an Orchestra repository against the official Orchestra 1.0 XSD.

    Args:
        text: The repository XML.

    Returns:
        ``{"rule", "path", "message"}`` per violation; empty when the document is valid.
    """
    import xmlschema  # noqa: PLC0415

    try:
        resource = xmlschema.XMLResource(text, defuse="always", allow="none")
    except (xmlschema.XMLResourceError, ET.ParseError, ValueError) as exc:
        return [{"rule": "xml", "path": "/", "message": str(exc)}]
    return [{"rule": "orchestra.xsd", "path": error.path or "/", "message": error.reason or str(error)}
            for error in orchestra_schema().iter_errors(resource)]


# ===========================================================================
# Fidelity
# ===========================================================================


class FixOrchestraFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for FIX Orchestra export (the full rule set is MFX-37.2).

    Operations, channels and services are ``DROP``ped with the critical types-only advisory; each decision the
    emitter makes up (a tag, a group for a list or map, a component for a union, a renamed entity) is filed under
    its construct; constraints Orchestra cannot hold are dropped. What a re-import reads back is **measured**: the
    pack emits the repository and imports it with the Orchestra importer, and files each difference under the type
    it concerns.
    """

    target_label = "FIX Orchestra"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = FixOrchestraEmitOptions.model_validate(dict(options))
        except (ValidationError, ValueError):
            self._options = FixOrchestraEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build once, measure the round trip, index the losses by construct, then walk the model."""
        options = getattr(self, "_options", None) or FixOrchestraEmitOptions()
        losses = LossTracker()
        self._changes: Dict[str, DiffChangeKind] = {}
        self._added: List[str] = []
        try:
            root = build_orchestra_repository(api, options, losses)
            self._changes, self._added = _measure_round_trip(api, render_orchestra(root))
        except (EmitPreconditionError, EmitOptionsError, ValueError):
            pass
        self._filed: Dict[str, List[Loss]] = {}
        for loss in losses.records():
            self._filed.setdefault(loss.pointer or "", []).append(loss)
        return super().evaluate(api)

    def _filed_verdicts(self, construct: str) -> List[FidelityVerdict]:
        verdicts = []
        for loss in getattr(self, "_filed", {}).get(construct, []):
            if loss.subject in SYNTH_SUBJECTS:
                verdicts.append(FidelityVerdict.synth(message=loss.detail, severity=LossinessSeverity.INFO,
                                                      target_mapping=loss.subject))
            elif loss.kind is LossKind.NA:
                verdicts.append(FidelityVerdict.drop(message=loss.detail, severity=LossinessSeverity.INFO,
                                                     target_mapping=loss.subject))
            else:
                verdicts.append(FidelityVerdict.approx(message=loss.detail, severity=LossinessSeverity.INFO,
                                                       target_mapping=loss.subject))
        return verdicts

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        verdicts = self._filed_verdicts("")
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.insert(0, advisory)
        if self._changes.get("") is not None and not verdicts:
            verdicts.append(FidelityVerdict.approx(
                message=f"{self.target_label} keeps the repository's name, version and title; other API metadata "
                "is not kept", severity=LossinessSeverity.INFO, target_mapping="identity → repository"))
        elif self._changes.get("") is not None:
            verdicts.append(FidelityVerdict.approx(
                message="the repository reads back with its name, version and title only",
                severity=LossinessSeverity.INFO, target_mapping="identity → repository"))
        return verdicts

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        filed = self._filed_verdicts(type_.key)
        change = self._changes.get(type_.key)
        if change is DiffChangeKind.REMOVED:
            return [*filed, FidelityVerdict.drop(
                message=f"{type_.kind.value} {type_.key!r} does not read back under its key: Orchestra names "
                "messages, components, groups and code sets by their own names (and an alias or scalar has no "
                "entity of its own)", severity=LossinessSeverity.INFO, target_mapping="type → re-keyed or not kept")]
        if change is DiffChangeKind.CHANGED:
            return [*filed, FidelityVerdict.approx(
                message=f"{type_.kind.value} {type_.key!r} reads back changed: fields follow Orchestra's refs, "
                "presence and datatypes", severity=LossinessSeverity.INFO, target_mapping="type → Orchestra")]
        return filed or [self.type_verdict(type_)]

    def field_verdicts(self, member: CanonicalField) -> List[FidelityVerdict]:
        return [*super().field_verdicts(member), *self._filed_verdicts(member.key)]

    def _field_identity_verdict(self, member: CanonicalField) -> Optional[FidelityVerdict]:
        """A synthesized tag is filed from the emitter's own record (``orchestra-tag-synthesized``)."""
        return None

    def _constraints_verdict(self, member: CanonicalField) -> Optional[FidelityVerdict]:
        """Orchestra holds presence, constant values and rules; other validation constraints are dropped."""
        constraints: Optional[Constraints] = member.constraints
        if constraints is None:
            return None
        facets = set(constraints.model_dump(exclude={"extras", "format", "enum", "min_items"}, exclude_none=True))
        if not facets:
            return None
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no validation constraints beyond presence and code sets; "
            f"{', '.join(sorted(facets))} of {member.key!r} are dropped",
            severity=LossinessSeverity.INFO, target_mapping="constraints → dropped")

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        return [(key, FidelityVerdict.synth(
            message=f"a re-import names {key!r} after its Orchestra entity", severity=LossinessSeverity.INFO,
            target_mapping="type named by its Orchestra entity")) for key in sorted(getattr(self, "_added", []))]

    def service_verdicts(self, service: Any) -> List[FidelityVerdict]:
        return [FidelityVerdict.drop(message=f"{self.target_label} describes messages; the service {service.key!r} "
                                     "is not written", target_mapping="service → dropped (types-only export)")]


def _measure_round_trip(api: CanonicalApi, text: str) -> Tuple[Dict[str, DiffChangeKind], List[str]]:
    """What a re-import of the repository changes, by type key (``""`` for the root), and the keys it adds."""
    from .import_source import ImportSourceError, canonical_diff, get_import_source  # noqa: PLC0415

    source = get_import_source(ORCHESTRA_FORMAT_KEY)
    if source is None:
        return {}, []
    try:
        back = source.normalize(source.parse(text, source_label="orchestra-export"), include_raw=False)
    except (ImportSourceError, ValueError):
        return {}, []
    changes: Dict[str, DiffChangeKind] = {}
    added: List[str] = []
    for entry in canonical_diff(api, back).entries:
        if entry.entity not in ("type", "root"):
            continue
        if entry.change is DiffChangeKind.ADDED:
            added.append(entry.key)
        else:
            changes[entry.key] = entry.change
    return changes, added


# ===========================================================================
# Emitter
# ===========================================================================


class FixOrchestraEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a FIX Orchestra 1.0 repository (``<name>.orchestra.xml``)."""

    key = ORCHESTRA_FORMAT_KEY
    requires_source = ("record-type",)
    format = ORCHESTRA_FORMAT_KEY
    label = "FIX Orchestra"
    description = (
        "Export the types as a FIX Orchestra repository: messages, components, repeating groups, fields with "
        "their tags, and code sets, valid against the official Orchestra XSD."
    )
    icon = "landmark"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = FixOrchestraEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Messages and their fields with tags; no operations, events, unions or validation constraints."""
        return CapabilityProfile(operations=False, events=False, unions=False, nullability=True, constraints=False,
                                 field_identity=True)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Orchestra rules."""
        return FixOrchestraFidelityRulePack

    def emit(self, api: CanonicalApi, *,
             opts: Optional[Union[FixOrchestraEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit one ``<name>.orchestra.xml`` repository.

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            EmitPreconditionError: When the model has no record type with a field.
        """
        options = _coerce_options(opts)
        losses = LossTracker()
        root = build_orchestra_repository(api, options, losses)
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", root.get("name") or "repository").strip("-") or "repository"
        return EmitResult(files=[EmittedFile(path=f"{stem}{ORCHESTRA_SUFFIX}", content=render_orchestra(root),
                                             media_type=XML_MEDIA_TYPE)],
                          media_type=XML_MEDIA_TYPE, losses=losses.records())


def _coerce_options(opts: Optional[Union[FixOrchestraEmitOptions, EmitOptions]]) -> FixOrchestraEmitOptions:
    if isinstance(opts, FixOrchestraEmitOptions):
        return opts
    try:
        return FixOrchestraEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid FIX Orchestra emit options: {exc}") from exc
