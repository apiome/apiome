"""FIX Orchestra repository parser — FMT-6.9 (#5453).

FIX Orchestra is the machine-readable **specification** of a FIX interface: an XML ``repository``
in the ``http://fixprotocol.io/2020/orchestra/repository`` namespace. Where the ``fix`` adapter
(:mod:`app.fix_parser`) *infers* a schema from ``tag=value`` messages, this reader takes the
declared one:

.. code-block:: text

    repository  name · version · metadata (Dublin Core)
      datatypes    datatype (name, baseType)
      codeSets     codeSet → code (name, id, value)
      fields       field (id, name, type: a datatype or a code set)
      components   component → fieldRef / componentRef / groupRef
      groups       group → numInGroup + fieldRef / componentRef / groupRef
      messages     message (name, msgType, scenario, flow) → structure → refs · responses
      actors       actor (fieldRef, states → state → transition) · flow (source → destination)

Every ref carries a ``presence`` — ``required``, ``optional`` (the default), ``conditional``,
``forbidden``, ``ignored`` or ``constant`` (with its ``value``) — and may carry ``rule`` elements
(``when`` / ``assign`` expressions). They are kept verbatim; :mod:`app.fix_orchestra_normalizer`
maps them onto canonical optionality and constraints.

Entities are keyed by ``(id, scenario)``; a ref names the scenario it means (``base`` by default)
and falls back to the ``base`` entity when that scenario is not declared.

XML goes through :func:`app.secure_xml.parse_xml`. An ``xi:include`` is resolved **only** inside an
uploaded fileset, against its members (:func:`parse_orchestra_fileset`) — never against the network
or the filesystem. **Errors** are :class:`OrchestraParseError`:

* ``INPUT_TRUNCATED`` — the XML ends before the document does;
* ``INPUT_MALFORMED`` — the XML is not well formed;
* ``FORMAT_MISMATCH`` — the text is not XML, or its root is not an Orchestra ``repository``;
* ``INPUT_SEMANTIC_INVALID`` — no messages, an entity without its id or name, a duplicate, or a
  ``presence`` outside the six values;
* ``INPUT_REFERENCE_UNRESOLVED`` — a ref to a field, component or group the repository does not
  declare, or an ``xi:include`` whose target was not uploaded with it.

A guard code from :mod:`app.secure_xml` is kept, and an encoding fault is refused code-less so the
import pipeline's encoding rule names it.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Set, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "BASE_SCENARIO",
    "ORCHESTRA_NAMESPACES",
    "PRESENCE_VALUES",
    "OrchestraActor",
    "OrchestraCode",
    "OrchestraCodeSet",
    "OrchestraComponent",
    "OrchestraDatatype",
    "OrchestraField",
    "OrchestraFlow",
    "OrchestraGroup",
    "OrchestraMember",
    "OrchestraMessage",
    "OrchestraParseError",
    "OrchestraRepository",
    "OrchestraResponse",
    "OrchestraRule",
    "OrchestraState",
    "OrchestraStateMachine",
    "OrchestraTransition",
    "is_orchestra",
    "parse_orchestra",
    "parse_orchestra_fileset",
]

#: Namespaces a repository root may be in: Orchestra 1.0 and the 2016 FIX Repository draft.
ORCHESTRA_NAMESPACES: Tuple[str, ...] = (
    "http://fixprotocol.io/2020/orchestra/repository",
    "http://fixprotocol.io/2016/fixrepository",
)

#: The scenario an entity or ref means when it names none.
BASE_SCENARIO = "base"

#: Every ``presence`` value Orchestra defines; a ref without one is ``optional``.
PRESENCE_VALUES: Tuple[str, ...] = (
    "required",
    "optional",
    "conditional",
    "forbidden",
    "ignored",
    "constant",
)

_XINCLUDE_TAG = "{http://www.w3.org/2001/XInclude}include"
_TRUNCATION_MESSAGES = ("no element found", "unclosed token")
_ENCODING_FAULT_MARKERS = ("\x00", "�")
_ENCODING_WINDOW = 1024
_SNIFF_WINDOW = 65536
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FIRST_ELEMENT_RE = re.compile(r"<(?![?!])")
_ROOT_RE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?repository\b[^>]*?fixprotocol\.io/(?:\d{4}/orchestra/repository|2016/fixrepository)",
    re.S,
)
_MAX_INCLUDE_DEPTH = 8


class OrchestraParseError(ValueError):
    """Raised when text is not a readable FIX Orchestra repository.

    Attributes:
        code: The intake-taxonomy code; ``None`` for an encoding fault, which the import pipeline
            names more precisely than the parser can.
    """

    def __init__(self, message: str, *, code: Optional[str]) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OrchestraRule:
    """A ``rule`` on a ref: a conditional presence (``when``) or a value assignment (``assign``).

    Attributes:
        name: The rule's name.
        presence: The presence the rule switches to when ``when`` holds, if it names one.
        when: The condition expression (Orchestra Score DSL), verbatim.
        assign: The assignment expression, verbatim.
    """

    name: Optional[str]
    presence: Optional[str]
    when: Optional[str]
    assign: Optional[str]


@dataclass(frozen=True)
class OrchestraMember:
    """One entry of a message structure, component or group.

    Attributes:
        kind: ``field``, ``component`` or ``group``.
        id: The referenced entity's id.
        scenario: The scenario of the referenced entity.
        presence: One of :data:`PRESENCE_VALUES`.
        value: The fixed value of a ``constant`` ref.
        rules: The ref's rules, in document order.
        documentation: The ref's own documentation.
    """

    kind: str
    id: str
    scenario: str
    presence: str
    value: Optional[str]
    rules: Tuple[OrchestraRule, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraDatatype:
    """A ``datatype``: a FIX datatype name and the one it is based on."""

    name: str
    base_type: Optional[str]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraCode:
    """One ``code`` of a code set: its name, id and wire value."""

    name: str
    id: Optional[str]
    value: str
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraCodeSet:
    """A ``codeSet``: the enumeration a field of that type draws its values from."""

    name: str
    id: Optional[str]
    scenario: str
    type: Optional[str]
    codes: Tuple[OrchestraCode, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraField:
    """A ``field``: the tag number, its name and its type (a datatype or a code-set name)."""

    id: str
    name: str
    scenario: str
    type: Optional[str]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraComponent:
    """A ``component``: a reusable block of refs."""

    id: str
    name: str
    scenario: str
    category: Optional[str]
    members: Tuple[OrchestraMember, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraGroup:
    """A repeating ``group``: its ``numInGroup`` counter field and the refs of one entry."""

    id: str
    name: str
    scenario: str
    category: Optional[str]
    num_in_group: Optional[str]
    members: Tuple[OrchestraMember, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraResponse:
    """A message's ``response``: its name and the messages it answers with (name, msgType)."""

    name: Optional[str]
    message_refs: Tuple[Tuple[Optional[str], Optional[str]], ...]


@dataclass(frozen=True)
class OrchestraMessage:
    """A ``message`` (one scenario of it): msgType, flow, structure and responses."""

    id: Optional[str]
    name: str
    msg_type: Optional[str]
    scenario: str
    category: Optional[str]
    flow: Optional[str]
    members: Tuple[OrchestraMember, ...]
    responses: Tuple[OrchestraResponse, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraTransition:
    """A state-machine ``transition``: its name, target state and guard."""

    name: Optional[str]
    target: Optional[str]
    when: Optional[str]


@dataclass(frozen=True)
class OrchestraState:
    """A state of a state machine and its outgoing transitions."""

    name: str
    transitions: Tuple[OrchestraTransition, ...]


@dataclass(frozen=True)
class OrchestraStateMachine:
    """An actor's ``states`` element: a named state machine."""

    name: Optional[str]
    id: Optional[str]
    states: Tuple[OrchestraState, ...]


@dataclass(frozen=True)
class OrchestraActor:
    """An ``actor``: the fields it keeps (by id) and its state machines."""

    name: str
    field_ids: Tuple[str, ...]
    state_machines: Tuple[OrchestraStateMachine, ...]
    documentation: Optional[str]


@dataclass(frozen=True)
class OrchestraFlow:
    """A ``flow`` between two actors, with its delivery reliability."""

    name: str
    source: Optional[str]
    destination: Optional[str]
    reliability: Optional[str]


@dataclass
class OrchestraRepository:
    """A parsed Orchestra repository.

    Attributes:
        name: The repository's ``name``.
        version: The repository's ``version`` (``FIX.4.4``, ``FIX.Latest_EP269`` …).
        namespace: The XML namespace of the root.
        metadata: The Dublin Core ``metadata`` entries (``title``, ``creator`` …), first of each.
        datatypes / code_sets / fields / components / groups / messages / actors / flows: The
            declarations, in document order.
        includes: The fileset members pulled in by ``xi:include``, in resolution order.
        raw: The root document text.
        source_label: The file name, when known.
    """

    name: Optional[str]
    version: Optional[str]
    namespace: str
    metadata: Dict[str, str]
    datatypes: List[OrchestraDatatype] = field(default_factory=list)
    code_sets: List[OrchestraCodeSet] = field(default_factory=list)
    fields: List[OrchestraField] = field(default_factory=list)
    components: List[OrchestraComponent] = field(default_factory=list)
    groups: List[OrchestraGroup] = field(default_factory=list)
    messages: List[OrchestraMessage] = field(default_factory=list)
    actors: List[OrchestraActor] = field(default_factory=list)
    flows: List[OrchestraFlow] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    raw: str = ""
    source_label: Optional[str] = None

    def field_by_ref(self, member: OrchestraMember) -> Optional[OrchestraField]:
        """Resolve a ``fieldRef`` (or a ``numInGroup``) to its field, falling back to ``base``."""
        return _lookup(self.fields, member.id, member.scenario)

    def component_by_ref(self, member: OrchestraMember) -> Optional[OrchestraComponent]:
        """Resolve a ``componentRef`` to its component, falling back to ``base``."""
        return _lookup(self.components, member.id, member.scenario)

    def group_by_ref(self, member: OrchestraMember) -> Optional[OrchestraGroup]:
        """Resolve a ``groupRef`` to its group, falling back to ``base``."""
        return _lookup(self.groups, member.id, member.scenario)

    def code_set_named(self, name: Optional[str]) -> Optional[OrchestraCodeSet]:
        """Return the code set a field's ``type`` names (its ``base`` scenario first), if any."""
        if not name:
            return None
        matches = [code_set for code_set in self.code_sets if code_set.name == name]
        base = [code_set for code_set in matches if code_set.scenario == BASE_SCENARIO]
        return (base or matches or [None])[0]

    def datatype_named(self, name: Optional[str]) -> Optional[OrchestraDatatype]:
        """Return the declared datatype called ``name``, if any."""
        return next((datatype for datatype in self.datatypes if datatype.name == name), None)


def _lookup(entities, entity_id: str, scenario: str):
    """Find the entity with ``entity_id`` in ``scenario``, else its ``base`` scenario."""
    fallback = None
    for entity in entities:
        if entity.id != entity_id:
            continue
        if entity.scenario == scenario:
            return entity
        if entity.scenario == BASE_SCENARIO:
            fallback = entity
    return fallback


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


def _local(element: ET.Element) -> str:
    tag = element.tag if isinstance(element.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _namespace(element: ET.Element) -> str:
    tag = element.tag if isinstance(element.tag, str) else ""
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _children(element: ET.Element, name: Optional[str] = None) -> List[ET.Element]:
    return [child for child in element if isinstance(child.tag, str) and (name is None or _local(child) == name)]


def _text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None:
        return None
    text = " ".join("".join(element.itertext()).split())
    return text or None


def _documentation(element: ET.Element) -> Optional[str]:
    """The text of an entity's ``documentation`` (or ``annotation/documentation``) children."""
    parts = [_text(child) for child in _children(element, "documentation")]
    for annotation in _children(element, "annotation"):
        parts.extend(_text(child) for child in _children(annotation, "documentation"))
    joined = " ".join(part for part in parts if part)
    return joined or None


def is_orchestra(text: Optional[str]) -> bool:
    """Whether ``text`` opens with an Orchestra ``repository`` root element.

    Only the first start tag is examined, so a truncated or malformed repository is still claimed
    and the parser names the fault. Never raises.

    Args:
        text: Candidate document text.

    Returns:
        ``True`` when the first element is ``repository`` in an Orchestra namespace.
    """
    if not text or "fixprotocol.io" not in text:
        return False
    head = _COMMENT_RE.sub("", text[:_SNIFF_WINDOW])
    start = _FIRST_ELEMENT_RE.search(head)
    if start is None:
        return False
    end = head.find(">", start.start())
    return bool(_ROOT_RE.match(head[start.start() : end + 1 if end >= 0 else len(head)]))


def _parse_xml(text: str, source_label: Optional[str]) -> ET.Element:
    """Parse XML safely (XInclude elements left in place), mapping faults onto intake codes."""
    head = text[:_ENCODING_WINDOW] if text else ""
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        raise OrchestraParseError(
            f"Document{_label(source_label)} is not valid text in its declared encoding.", code=None
        )
    if text.strip() and not text.lstrip("﻿ \t\r\n").startswith("<"):
        raise OrchestraParseError(
            f"Document{_label(source_label)} is not XML, so it cannot be a FIX Orchestra repository "
            "(a FIX tag=value message imports as FIX).",
            code="FORMAT_MISMATCH",
        )
    try:
        return parse_xml(text, source_label=source_label, allow_xinclude=True)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            raise OrchestraParseError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES) and not text.rstrip().endswith(">")
        raise OrchestraParseError(
            message + (" The document was truncated." if truncated else ""),
            code="INPUT_TRUNCATED" if truncated else "INPUT_MALFORMED",
        ) from exc


def _resolve_includes(
    element: ET.Element,
    *,
    path: str,
    members: Optional[Mapping[str, str]],
    resolved: List[str],
    chain: Tuple[str, ...],
) -> None:
    """Replace every ``xi:include`` under ``element`` with the root of the member it names.

    Args:
        element: The element whose descendants are resolved, in place.
        path: The fileset path of the document ``element`` belongs to (hrefs are relative to it).
        members: Fileset member path → text; ``None`` for a single uploaded file.
        resolved: Collects the member paths pulled in, in order.
        chain: The include chain so far, to refuse a cycle.

    Raises:
        OrchestraParseError: ``INPUT_REFERENCE_UNRESOLVED`` when a target is not a member (or the
            upload is a single file), ``INPUT_SEMANTIC_INVALID`` for an include cycle or a
            non-XML include, or the target's own parse fault.
    """
    for index, child in enumerate(list(element)):
        if child.tag != _XINCLUDE_TAG:
            _resolve_includes(child, path=path, members=members, resolved=resolved, chain=chain)
            continue
        href = (child.attrib.get("href") or "").strip()
        if child.attrib.get("parse", "xml") != "xml":
            raise OrchestraParseError(
                f"Repository{_label(path)} includes {href!r} as text; only XML includes are read.",
                code="INPUT_SEMANTIC_INVALID",
            )
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path or ""), href)) if href else ""
        if members is None or target not in members:
            where = "is not part of the upload" if members is not None else "was not uploaded with it"
            raise OrchestraParseError(
                f"Repository{_label(path)} includes {href or '<no href>'!r}, which {where}. Upload the "
                "repository and the files it includes together as one archive.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        if target in chain or len(chain) >= _MAX_INCLUDE_DEPTH:
            raise OrchestraParseError(
                f"Repository{_label(path)} includes {target!r} in a cycle.", code="INPUT_SEMANTIC_INVALID"
            )
        included = _parse_xml(members[target], target)
        _resolve_includes(included, path=target, members=members, resolved=resolved, chain=chain + (target,))
        resolved.append(target)
        element.remove(child)
        element.insert(index, included)


def _require(element: ET.Element, attribute: str, what: str, source_label: Optional[str]) -> str:
    value = (element.attrib.get(attribute) or "").strip()
    if not value:
        raise OrchestraParseError(
            f"Repository{_label(source_label)} has a {what} without its `{attribute}`.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return value


def _attr(element: ET.Element, attribute: str) -> Optional[str]:
    value = (element.attrib.get(attribute) or "").strip()
    return value or None


def _scenario(element: ET.Element) -> str:
    return _attr(element, "scenario") or BASE_SCENARIO


def _rules(element: ET.Element) -> Tuple[OrchestraRule, ...]:
    return tuple(
        OrchestraRule(
            name=_attr(rule, "name"),
            presence=_attr(rule, "presence"),
            when=_text(next(iter(_children(rule, "when")), None)),
            assign=_text(next(iter(_children(rule, "assign")), None)),
        )
        for rule in _children(element, "rule")
    )


_MEMBER_KINDS = {"fieldRef": "field", "componentRef": "component", "groupRef": "group"}


def _members(element: ET.Element, owner: str, source_label: Optional[str]) -> Tuple[OrchestraMember, ...]:
    """Read the ``fieldRef`` / ``componentRef`` / ``groupRef`` children of ``element``."""
    members: List[OrchestraMember] = []
    for child in _children(element):
        kind = _MEMBER_KINDS.get(_local(child))
        if kind is None:
            continue
        presence = _attr(child, "presence") or "optional"
        if presence not in PRESENCE_VALUES:
            raise OrchestraParseError(
                f"Repository{_label(source_label)}: {owner} gives a {_local(child)} the presence "
                f"{presence!r}; Orchestra defines {', '.join(PRESENCE_VALUES)}.",
                code="INPUT_SEMANTIC_INVALID",
            )
        members.append(
            OrchestraMember(
                kind=kind,
                id=_require(child, "id", f"{_local(child)} in {owner}", source_label),
                scenario=_scenario(child),
                presence=presence,
                value=_attr(child, "value"),
                rules=_rules(child),
                documentation=_documentation(child),
            )
        )
    return tuple(members)


def _sections(root: ET.Element, name: str) -> List[ET.Element]:
    """Every child of every ``name`` section of ``root`` (sections may repeat after an include)."""
    return [child for section in _children(root, name) for child in _children(section)]


def _metadata(root: ET.Element) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for section in _children(root, "metadata"):
        for child in _children(section):
            text = _text(child)
            if text and _local(child) not in metadata:
                metadata[_local(child)] = text
    return metadata


def _state_machine(element: ET.Element) -> OrchestraStateMachine:
    states = tuple(
        OrchestraState(
            name=_attr(state, "name") or "",
            transitions=tuple(
                OrchestraTransition(
                    name=_attr(transition, "name"),
                    target=_attr(transition, "target"),
                    when=_text(next(iter(_children(transition, "when")), None)),
                )
                for transition in _children(state, "transition")
            ),
        )
        for state in _children(element, "state")
    )
    return OrchestraStateMachine(name=_attr(element, "name"), id=_attr(element, "id"), states=states)


def _read_repository(root: ET.Element, source_label: Optional[str]) -> OrchestraRepository:
    """Read the declarations of a (fully included) repository element."""
    label = source_label
    repository = OrchestraRepository(
        name=_attr(root, "name"),
        version=_attr(root, "version"),
        namespace=_namespace(root),
        metadata=_metadata(root),
    )
    for element in _sections(root, "datatypes"):
        if _local(element) == "datatype":
            repository.datatypes.append(
                OrchestraDatatype(
                    name=_require(element, "name", "datatype", label),
                    base_type=_attr(element, "baseType"),
                    documentation=_documentation(element),
                )
            )
    for element in _sections(root, "codeSets"):
        if _local(element) != "codeSet":
            continue
        name = _require(element, "name", "codeSet", label)
        codes = tuple(
            OrchestraCode(
                name=_require(code, "name", f"code of codeSet {name}", label),
                id=_attr(code, "id"),
                value=_require(code, "value", f"code of codeSet {name}", label),
                documentation=_documentation(code),
            )
            for code in _children(element, "code")
        )
        repository.code_sets.append(
            OrchestraCodeSet(
                name=name,
                id=_attr(element, "id"),
                scenario=_scenario(element),
                type=_attr(element, "type"),
                codes=codes,
                documentation=_documentation(element),
            )
        )
    for element in _sections(root, "fields"):
        if _local(element) == "field":
            repository.fields.append(
                OrchestraField(
                    id=_require(element, "id", "field", label),
                    name=_require(element, "name", "field", label),
                    scenario=_scenario(element),
                    type=_attr(element, "type"),
                    documentation=_documentation(element),
                )
            )
    for element in _sections(root, "components"):
        if _local(element) == "component":
            name = _require(element, "name", "component", label)
            repository.components.append(
                OrchestraComponent(
                    id=_require(element, "id", f"component {name}", label),
                    name=name,
                    scenario=_scenario(element),
                    category=_attr(element, "category"),
                    members=_members(element, f"component {name}", label),
                    documentation=_documentation(element),
                )
            )
    for element in _sections(root, "groups"):
        if _local(element) == "group":
            name = _require(element, "name", "group", label)
            counter = next(iter(_children(element, "numInGroup")), None)
            repository.groups.append(
                OrchestraGroup(
                    id=_require(element, "id", f"group {name}", label),
                    name=name,
                    scenario=_scenario(element),
                    category=_attr(element, "category"),
                    num_in_group=_attr(counter, "id") if counter is not None else None,
                    members=_members(element, f"group {name}", label),
                    documentation=_documentation(element),
                )
            )
    for element in _sections(root, "messages"):
        if _local(element) != "message":
            continue
        name = _require(element, "name", "message", label)
        structure = next(iter(_children(element, "structure")), None)
        responses = tuple(
            OrchestraResponse(
                name=_attr(response, "name"),
                message_refs=tuple(
                    (_attr(ref, "name"), _attr(ref, "msgType")) for ref in _children(response, "messageRef")
                ),
            )
            for section in _children(element, "responses")
            for response in _children(section, "response")
        )
        repository.messages.append(
            OrchestraMessage(
                id=_attr(element, "id"),
                name=name,
                msg_type=_attr(element, "msgType"),
                scenario=_scenario(element),
                category=_attr(element, "category"),
                flow=_attr(element, "flow"),
                members=_members(structure, f"message {name}", label) if structure is not None else (),
                responses=responses,
                documentation=_documentation(element),
            )
        )
    for element in _sections(root, "actors"):
        if _local(element) == "actor":
            repository.actors.append(
                OrchestraActor(
                    name=_require(element, "name", "actor", label),
                    field_ids=tuple(_attr(ref, "id") or "" for ref in _children(element, "fieldRef")),
                    state_machines=tuple(_state_machine(states) for states in _children(element, "states")),
                    documentation=_documentation(element),
                )
            )
        elif _local(element) == "flow":
            repository.flows.append(
                OrchestraFlow(
                    name=_require(element, "name", "flow", label),
                    source=_attr(element, "source"),
                    destination=_attr(element, "destination"),
                    reliability=_attr(element, "reliability"),
                )
            )
    return repository


def _check_unique(repository: OrchestraRepository, source_label: Optional[str]) -> None:
    """Refuse two declarations of the same entity in the same scenario."""
    keyed = (
        ("field", [(entity.id, entity.scenario) for entity in repository.fields]),
        ("component", [(entity.id, entity.scenario) for entity in repository.components]),
        ("group", [(entity.id, entity.scenario) for entity in repository.groups]),
        ("codeSet", [(entity.name, entity.scenario) for entity in repository.code_sets]),
        ("message", [(entity.name, entity.scenario) for entity in repository.messages]),
    )
    for what, keys in keyed:
        seen: Set[Tuple[str, str]] = set()
        for key in keys:
            if key in seen:
                raise OrchestraParseError(
                    f"Repository{_label(source_label)} declares {what} {key[0]!r} twice in scenario {key[1]!r}.",
                    code="INPUT_SEMANTIC_INVALID",
                )
            seen.add(key)


def _check_references(repository: OrchestraRepository, source_label: Optional[str]) -> None:
    """Refuse any ref (or ``numInGroup``) to an entity the repository does not declare."""
    missing: List[str] = []

    def check(owner: str, members: Tuple[OrchestraMember, ...]) -> None:
        for member in members:
            if member.kind == "field":
                found = repository.field_by_ref(member)
            elif member.kind == "component":
                found = repository.component_by_ref(member)
            else:
                found = repository.group_by_ref(member)
            if found is None:
                missing.append(f"{owner} → {member.kind} {member.id}")

    for component in repository.components:
        check(f"component {component.name}", component.members)
    for group in repository.groups:
        check(f"group {group.name}", group.members)
        if group.num_in_group and _lookup(repository.fields, group.num_in_group, group.scenario) is None:
            missing.append(f"group {group.name} → numInGroup field {group.num_in_group}")
    for message in repository.messages:
        check(f"message {message.name}", message.members)
    if missing:
        raise OrchestraParseError(
            f"Repository{_label(source_label)} refers to entities it does not declare: " + "; ".join(missing) + ".",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


def _parse(
    text: str,
    *,
    source_label: Optional[str],
    members: Optional[Mapping[str, str]],
    path: str,
) -> OrchestraRepository:
    root = _parse_xml(text, source_label)
    if _local(root) != "repository" or _namespace(root) not in ORCHESTRA_NAMESPACES:
        raise OrchestraParseError(
            f"Document{_label(source_label)} is not a FIX Orchestra repository: its root is "
            f"`{_local(root)}`, not `repository` in {ORCHESTRA_NAMESPACES[0]}.",
            code="FORMAT_MISMATCH",
        )
    includes: List[str] = []
    _resolve_includes(root, path=path, members=members, resolved=includes, chain=(path,))
    repository = _read_repository(root, source_label)
    repository.includes = includes
    repository.raw = text
    repository.source_label = source_label
    if not repository.messages:
        raise OrchestraParseError(
            f"Repository{_label(source_label)} declares no messages, so it describes no interface to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    _check_unique(repository, source_label)
    _check_references(repository, source_label)
    return repository


def parse_orchestra(text: str, *, source_label: Optional[str] = None) -> OrchestraRepository:
    """Parse one FIX Orchestra repository document.

    Args:
        text: The repository XML.
        source_label: The file name, used in errors.

    Returns:
        The :class:`OrchestraRepository`.

    Raises:
        OrchestraParseError: With an intake-taxonomy code (see the module docstring). A document
            that uses ``xi:include`` is refused as ``INPUT_REFERENCE_UNRESOLVED``: upload it with
            the files it includes, as a fileset.
    """
    if not text or not text.strip():
        raise OrchestraParseError(f"Document{_label(source_label)} is empty.", code="INPUT_EMPTY")
    return _parse(text, source_label=source_label, members=None, path=source_label or "")


def parse_orchestra_fileset(
    members: Mapping[str, str], root: str, *, source_label: Optional[str] = None
) -> OrchestraRepository:
    """Parse a fileset whose root is the repository; its ``xi:include`` targets are members.

    Args:
        members: Member path → text.
        root: The root member's path.
        source_label: Fallback label for the root.

    Returns:
        The repository, with every include resolved and recorded in ``includes``.

    Raises:
        OrchestraParseError: As :func:`parse_orchestra`; an include naming a path that is not a
            member is ``INPUT_REFERENCE_UNRESOLVED``.
    """
    text = members[root]
    label = root or source_label
    if not text or not text.strip():
        raise OrchestraParseError(f"Document{_label(label)} is empty.", code="INPUT_EMPTY")
    return _parse(text, source_label=label, members=members, path=root)
