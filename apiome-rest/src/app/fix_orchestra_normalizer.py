"""FIX Orchestra → canonical model normalizer — FMT-6.9 (#5453).

Maps a parsed :class:`~app.fix_orchestra_parser.OrchestraRepository` onto a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA` — the declared schema, where the ``fix``
adapter infers one from messages:

* each **message** (each scenario of it) → a ``RECORD`` type named by the message (``NewOrderSingle``,
  ``NewOrderSingle_dark`` for a non-``base`` scenario) with its ``msgType``, flow and responses in
  ``extras``;
* each **code set** → an ``ENUM`` type whose values are the codes (``Buy`` = ``1``);
* each **component** → a ``RECORD`` type, used by a ``componentRef`` field;
* each **group** → a ``RECORD`` type for one entry, used by a ``groupRef`` field that is a **list**
  of it (``minItems: 1`` — a group is sent with at least one entry);
* each **fieldRef** → a field named by the FIX field, typed by its code set or by the primitive its
  datatype resolves to, with the tag as ``field_number``.

**Presence** maps onto optionality and constraints, and a field is never dropped for it:

==============  ===========  ==================================================================
``presence``    nullable     constraint
==============  ===========  ==================================================================
``required``    no           —
``optional``    yes          —
``conditional`` yes          ``extras.fix_presence = conditional`` plus its rules (``when``)
``forbidden``   yes          ``extras.fix_presence = forbidden`` — the field must not be sent
``ignored``     yes          ``extras.fix_presence = ignored`` — accepted, never acted on
``constant``    no           ``enum: [value]`` and the value as ``default``
==============  ===========  ==================================================================

Every ref's ``rule`` (``when`` / ``assign``) is carried in the constraint's ``extras.fix_rules``.
Actors, flows, state machines and declared datatypes are recorded in the model ``extras``; the
repository's Dublin Core metadata stays in ``raw`` so a re-dated, otherwise unchanged repository is
the same version.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .fix_orchestra_parser import (
    BASE_SCENARIO,
    OrchestraActor,
    OrchestraCodeSet,
    OrchestraField,
    OrchestraMember,
    OrchestraRepository,
    OrchestraRule,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["FORMAT_KEY", "FixOrchestraNormalizer", "fix_primitive"]

FORMAT_KEY = "fix-orchestra"

#: FIX datatypes and the primitive each is carried as. A declared datatype resolves through its
#: ``baseType`` chain to one of these; an unknown name is a ``string``.
_FIX_PRIMITIVES: Dict[str, str] = {
    "int": "integer",
    "Length": "integer",
    "TagNum": "integer",
    "SeqNum": "integer",
    "NumInGroup": "integer",
    "DayOfMonth": "integer",
    "float": "number",
    "Qty": "number",
    "Price": "number",
    "PriceOffset": "number",
    "Amt": "number",
    "Percentage": "number",
    "Boolean": "boolean",
}

#: FIX datatypes carried as strings with a JSON Schema ``format``.
_FIX_FORMATS: Dict[str, str] = {
    "UTCTimestamp": "date-time",
    "TZTimestamp": "date-time",
    "UTCDateOnly": "date",
    "LocalMktDate": "date",
    "UTCTimeOnly": "time",
    "TZTimeOnly": "time",
}

_MAX_BASE_CHAIN = 16


def fix_primitive(repository: OrchestraRepository, datatype: Optional[str]) -> Tuple[str, Optional[str]]:
    """Resolve a FIX datatype name to a canonical primitive and an optional string ``format``.

    Args:
        repository: The repository, whose declared ``datatypes`` may rebase a name.
        datatype: The datatype a field names (``Price``, ``UTCTimestamp`` …).

    Returns:
        ``(primitive, format)`` — ``("number", None)``, ``("string", "date-time")`` …
    """
    name = datatype
    for _ in range(_MAX_BASE_CHAIN):
        if not name:
            break
        if name in _FIX_PRIMITIVES:
            return _FIX_PRIMITIVES[name], None
        if name in _FIX_FORMATS:
            return "string", _FIX_FORMATS[name]
        declared = repository.datatype_named(name)
        if declared is None or not declared.base_type or declared.base_type == name:
            break
        name = declared.base_type
    return "string", None


def _scenario_name(name: str, scenario: str) -> str:
    return name if scenario == BASE_SCENARIO else f"{name}_{scenario}"


def _rule_extras(rule: OrchestraRule) -> Dict[str, Any]:
    return {
        key: value
        for key, value in (
            ("name", rule.name),
            ("presence", rule.presence),
            ("when", rule.when),
            ("assign", rule.assign),
        )
        if value is not None
    }


def _presence_constraints(member: OrchestraMember, *, min_items: Optional[int] = None) -> Optional[Constraints]:
    """The constraint a ref's presence and rules declare, or ``None`` when it declares none."""
    extras: Dict[str, Any] = {}
    if member.presence in ("conditional", "forbidden", "ignored", "constant"):
        extras["fix_presence"] = member.presence
    if member.rules:
        extras["fix_rules"] = [_rule_extras(rule) for rule in member.rules]
    enum = [member.value] if member.presence == "constant" and member.value is not None else None
    if not extras and enum is None and min_items is None:
        return None
    return Constraints(enum=enum, min_items=min_items, extras=extras)


class _Builder:
    """Accumulates the canonical types of one repository with unique names and keys."""

    def __init__(self, repository: OrchestraRepository) -> None:
        self.repository = repository
        self.types: List[Type] = []
        self._names: Dict[Tuple[str, str, str], str] = {}
        self._taken: Dict[str, str] = {}

    def type_name(self, kind: str, entity_id: str, name: str, scenario: str) -> str:
        """The canonical type name for an entity, unique across kinds (``Side_codeSet`` on a clash)."""
        key = (kind, entity_id, scenario)
        if key not in self._names:
            candidate = _scenario_name(name, scenario)
            if self._taken.get(candidate, kind) != kind:
                candidate = f"{candidate}_{kind}"
            self._taken[candidate] = kind
            self._names[key] = candidate
        return self._names[key]

    def code_set_type(self, code_set: OrchestraCodeSet) -> str:
        """Add the ``ENUM`` type for a code set (once) and return its key."""
        name = self.type_name("codeSet", code_set.name, code_set.name, code_set.scenario)
        type_key = Keys.type(name)
        if any(existing.key == type_key for existing in self.types):
            return type_key
        values = [
            EnumValue(
                key=Keys.enum_value(type_key, code.name),
                name=code.name,
                value=code.value,
                description=code.documentation,
                extras={"fix_code_id": code.id} if code.id else {},
            )
            for code in code_set.codes
        ]
        extras: Dict[str, Any] = {"fix_kind": "codeSet", "fix_code_type": code_set.type}
        if code_set.id:
            extras["fix_id"] = code_set.id
        if code_set.scenario != BASE_SCENARIO:
            extras["fix_scenario"] = code_set.scenario
        self.types.append(
            Type(
                key=type_key,
                name=name,
                kind=TypeKind.ENUM,
                description=code_set.documentation,
                enum_values=values,
                extras=extras,
            )
        )
        return type_key

    def field_ref(self, fix_field: OrchestraField, *, nullable: bool) -> Tuple[TypeRef, Dict[str, Any], Optional[str]]:
        """The type reference of a FIX field, its extras, and the string ``format`` it carries."""
        extras: Dict[str, Any] = {"fix_tag": fix_field.id, "fix_datatype": fix_field.type}
        if fix_field.scenario != BASE_SCENARIO:
            extras["fix_field_scenario"] = fix_field.scenario
        code_set = self.repository.code_set_named(fix_field.type)
        if code_set is not None:
            return TypeRef(name=self.code_set_type(code_set), nullable=nullable), extras, None
        primitive, string_format = fix_primitive(self.repository, fix_field.type)
        return TypeRef(name=primitive, nullable=nullable), extras, string_format

    def fields(self, owner_key: str, members: Tuple[OrchestraMember, ...]) -> List[CanonicalField]:
        """Build the canonical fields of a message structure, component or group."""
        built: List[CanonicalField] = []
        used: Dict[str, int] = {}
        for member in members:
            nullable = member.presence not in ("required", "constant")
            field_number: Optional[int] = None
            description = member.documentation
            constraints = _presence_constraints(member)
            if member.kind == "field":
                fix_field = self.repository.field_by_ref(member)
                assert fix_field is not None  # the parser refuses unresolved refs
                name = fix_field.name
                type_ref, extras, string_format = self.field_ref(fix_field, nullable=nullable)
                field_number = int(fix_field.id) if fix_field.id.isdigit() else None
                description = description or fix_field.documentation
                if string_format:
                    constraints = (constraints or Constraints()).model_copy(update={"format": string_format})
            elif member.kind == "component":
                component = self.repository.component_by_ref(member)
                assert component is not None
                name = component.name
                type_ref = TypeRef(name=self.component_type(component), nullable=nullable)
                extras = {"fix_component_id": component.id}
            else:
                group = self.repository.group_by_ref(member)
                assert group is not None
                name = group.name
                type_ref = TypeRef(item=TypeRef(name=self.group_type(group), nullable=False), nullable=nullable)
                extras = {"fix_group_id": group.id}
                if group.num_in_group:
                    counter = self.repository.field_by_ref(
                        OrchestraMember("field", group.num_in_group, group.scenario, "required", None, (), None)
                    )
                    extras["fix_num_in_group"] = {
                        "tag": group.num_in_group,
                        "name": counter.name if counter is not None else None,
                    }
                constraints = _presence_constraints(member, min_items=1)
            extras["fix_presence"] = member.presence
            if member.scenario != BASE_SCENARIO:
                extras["fix_ref_scenario"] = member.scenario
            occurrence = used.get(name, 0) + 1
            used[name] = occurrence
            field_name = name if occurrence == 1 else f"{name}_{occurrence}"
            built.append(
                CanonicalField(
                    key=Keys.field(owner_key, field_name),
                    name=field_name,
                    type=type_ref,
                    field_number=field_number,
                    default=member.value if member.presence == "constant" else None,
                    constraints=constraints,
                    description=description,
                    extras=extras,
                )
            )
        return built

    def component_type(self, component) -> str:
        """Add the ``RECORD`` type of a component (once) and return its key."""
        type_key = Keys.type(self.type_name("component", component.id, component.name, component.scenario))
        if not any(existing.key == type_key for existing in self.types):
            placeholder = Type(key=type_key, name=type_key, kind=TypeKind.RECORD)
            self.types.append(placeholder)  # reserved first so a self-referencing component terminates
            extras: Dict[str, Any] = {
                "fix_kind": "component",
                "fix_id": component.id,
                "fix_category": component.category,
            }
            if component.scenario != BASE_SCENARIO:
                extras["fix_scenario"] = component.scenario
            self._replace(
                placeholder,
                Type(
                    key=type_key,
                    name=type_key,
                    kind=TypeKind.RECORD,
                    description=component.documentation,
                    fields=self.fields(type_key, component.members),
                    extras=extras,
                ),
            )
        return type_key

    def group_type(self, group) -> str:
        """Add the ``RECORD`` type of one group entry (once) and return its key."""
        type_key = Keys.type(self.type_name("group", group.id, group.name, group.scenario))
        if not any(existing.key == type_key for existing in self.types):
            placeholder = Type(key=type_key, name=type_key, kind=TypeKind.RECORD)
            self.types.append(placeholder)
            extras: Dict[str, Any] = {
                "fix_kind": "group",
                "fix_id": group.id,
                "fix_category": group.category,
                "fix_num_in_group": group.num_in_group,
            }
            if group.scenario != BASE_SCENARIO:
                extras["fix_scenario"] = group.scenario
            self._replace(
                placeholder,
                Type(
                    key=type_key,
                    name=type_key,
                    kind=TypeKind.RECORD,
                    description=group.documentation,
                    fields=self.fields(type_key, group.members),
                    extras=extras,
                ),
            )
        return type_key

    def _replace(self, placeholder: Type, built: Type) -> None:
        index = next(i for i, existing in enumerate(self.types) if existing is placeholder)
        self.types[index] = built


def _actor_extras(repository: OrchestraRepository, actor: OrchestraActor) -> Dict[str, Any]:
    fields = []
    for field_id in actor.field_ids:
        fix_field = repository.field_by_ref(
            OrchestraMember("field", field_id, BASE_SCENARIO, "optional", None, (), None)
        )
        fields.append(fix_field.name if fix_field is not None else field_id)
    return {
        "name": actor.name,
        "fields": fields,
        "state_machines": [
            {
                "name": machine.name,
                "id": machine.id,
                "states": [
                    {
                        "name": state.name,
                        "transitions": [
                            {
                                key: value
                                for key, value in (("name", t.name), ("target", t.target), ("when", t.when))
                                if value
                            }
                            for t in state.transitions
                        ],
                    }
                    for state in machine.states
                ],
            }
            for machine in actor.state_machines
        ],
    }


class FixOrchestraNormalizer(Normalizer, register=True):
    """Normalize a parsed FIX Orchestra repository into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize ``source`` (an :class:`OrchestraRepository`).

        Args:
            source: The parsed repository.
            include_raw: Whether to keep the repository text and metadata in ``raw``.

        Returns:
            The canonical model, collections in deterministic order.

        Raises:
            ValueError: When ``source`` is not an :class:`OrchestraRepository`.
        """
        if not isinstance(source, OrchestraRepository):
            raise ValueError(
                "FIX Orchestra source must be an OrchestraRepository (see app.fix_orchestra_parser.parse_orchestra)"
            )
        builder = _Builder(source)
        for code_set in source.code_sets:
            builder.code_set_type(code_set)
        for message in source.messages:
            name = builder.type_name("message", message.name, message.name, message.scenario)
            type_key = Keys.type(name)
            extras: Dict[str, Any] = {
                "fix_kind": "message",
                "fix_msg_type": message.msg_type,
                "fix_msg_name": message.name,
                "fix_id": message.id,
                "fix_category": message.category,
                "fix_scenario": message.scenario,
            }
            if message.flow:
                extras["fix_flow"] = message.flow
            if message.responses:
                extras["fix_responses"] = [
                    {
                        "name": response.name,
                        "messages": [
                            {"name": ref_name, "msgType": msg_type} for ref_name, msg_type in response.message_refs
                        ],
                    }
                    for response in message.responses
                ]
            builder.types.append(
                Type(
                    key=type_key,
                    name=name,
                    kind=TypeKind.RECORD,
                    description=message.documentation,
                    fields=builder.fields(type_key, message.members),
                    extras=extras,
                )
            )

        title = source.metadata.get("title") or source.name or "FIX Orchestra repository"
        msg_types = sorted({message.msg_type for message in source.messages if message.msg_type})
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=source.name or title, namespace=source.version),
            version=source.version,
            title=title,
            types=builder.types,
            raw=(
                {"fix_orchestra": source.raw, "metadata": dict(source.metadata), "includes": list(source.includes)}
                if include_raw
                else None
            ),
            extras={
                "fix_repository_name": source.name,
                "fix_repository_version": source.version,
                "fix_namespace": source.namespace,
                "fix_msg_types": msg_types,
                "fix_messages": [
                    {"name": message.name, "msgType": message.msg_type, "scenario": message.scenario}
                    for message in source.messages
                ],
                "fix_datatypes": [
                    {"name": datatype.name, "base_type": datatype.base_type} for datatype in source.datatypes
                ],
                "fix_field_count": len(source.fields),
                "fix_actors": [_actor_extras(source, actor) for actor in source.actors],
                "fix_flows": [
                    {
                        "name": flow.name,
                        "source": flow.source,
                        "destination": flow.destination,
                        "reliability": flow.reliability,
                    }
                    for flow in source.flows
                ],
            },
        )
        return normalize_ordering(api)
