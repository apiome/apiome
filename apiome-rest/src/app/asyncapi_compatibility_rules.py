"""AsyncAPI channel and operation compatibility, per side and mode — XPC-4.4 (#5748).

The format-agnostic baseline grades an AsyncAPI diff from structure alone: a removed channel is
breaking, an added one safe, and every other move a generic attribute grade. It cannot say *who*
a change breaks. An event contract has two sides, and a change can break one and not the other:

* the **consumer** side — consumers that upgrade first: new consumers against old producers. This
  is the side ``BACKWARD`` checks.
* the **producer** side — producers that upgrade first: old consumers against new producers. This
  is the side ``FORWARD`` checks. ``FULL`` checks both.

Each rule grades both sides (:class:`~app.asyncapi_payload_compatibility.SideFinding`), and the
classifier reads the grades by its mode (:func:`severity_under`): a side the mode checks keeps its
grade, a side it does not check drops one tier — a break there is flagged DANGEROUS for review (as
the JSON Schema and Avro classifiers grade a break in the other direction), a review item there is
SAFE. So an added message, SAFE for consumers and DANGEROUS for producers, is SAFE under
``BACKWARD`` and DANGEROUS under ``FORWARD`` and ``FULL``.

=====================================  ===========  ===========  ==========================================
Change                                 Consumers    Producers    Rule id
=====================================  ===========  ===========  ==========================================
channel address / template changed    breaking     dangerous    ``asyncapi.consumer.address-changed``
address parameter added, no default   breaking     dangerous    ``asyncapi.consumer.parameter-added``
address parameter added with default  safe         safe         ``asyncapi.both.parameter-added-with-default``
protocol changed                      breaking     breaking     ``asyncapi.both.protocol-changed``
channel / operation / message binding  breaking     breaking     ``asyncapi.both.binding-changed``
operation ``action`` send↔receive      breaking     breaking     ``asyncapi.both.action-flipped``
operation ``reply`` removed            breaking     dangerous    ``asyncapi.consumer.reply-removed``
message removed from the union         breaking     safe         ``asyncapi.consumer.message-removed``
message added to the union             safe         dangerous    ``asyncapi.producer.message-added``
payload ``schemaFormat`` changed       breaking     breaking     ``asyncapi.both.schema-format-changed``
payload schema changed                 by the payload's own check (Avro, JSON Schema, Protobuf rule ids)
server added / removed / changed       dangerous    dangerous    ``asyncapi.both.server-changed``
server or operation security changed   dangerous    dangerous    ``asyncapi.both.security-changed``
=====================================  ===========  ===========  ==========================================

Requesters consume a reply, so a removed ``reply`` is graded on the consumer side. A message joins
the union rules only when its operation exists in both versions; a message that arrives or leaves
with its whole operation keeps the baseline grade (that operation's own add/remove is the change).

**Pairing.** A channel's key is its address, so an address change reaches the diff as one channel
removed and another added. The two are paired — and both graded ``address-changed`` — when the
channel keeps its AsyncAPI 3 map name, or an operation present in both versions moved from one to
the other. An AsyncAPI 2 operation without an ``operationId`` is keyed ``"<action> <address>"``, so a
flipped action reaches the diff as one operation removed and another added on the same channel;
those two are paired as ``action-flipped``.

**What is left to the baseline.** A change with no rule above keeps its baseline grade, and on a
modified entity every attribute no rule handles (a header, a content type, a parameter removed or
changed) is still graded by the baseline and counted in the worst-of. Servers are not a diff
category, so server findings are returned *unattributed* (they still count toward the overall
grade); so is a payload finding on a message the canonical diff does not list (an AsyncAPI 2
``.proto`` text payload, which the canonical model does not keep).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple

from .asyncapi_normalizer import AsyncApiNormalizer
from .asyncapi_payload_compatibility import SideFinding, compare_payloads, side_rule_id
from .breaking_change import Severity, _classify_modified_attribute, _worst
from .canonical_model import CanonicalApi, Message
from .diff import ChangeKind, EntityCategory, EntityChange, FieldChange, ModelDiff
from .jsonschema_compatibility import mode_directions

__all__ = [
    "CONSUMER",
    "PRODUCER",
    "MODE_TEXT",
    "ChangeFindings",
    "RuleReport",
    "attribute_severity",
    "coerce_mode",
    "evaluate",
    "mode_sides",
    "rationale",
    "severity_under",
]

CONSUMER = "consumer"
PRODUCER = "producer"

#: Reader/writer direction (as :func:`app.jsonschema_compatibility.mode_directions` names it) → side.
_SIDE_OF_DIRECTION = {"backward": CONSUMER, "forward": PRODUCER}

#: What each mode checks, in the words a rationale uses.
MODE_TEXT = {
    "BACKWARD": "new consumers against old producers",
    "FORWARD": "old consumers against new producers",
    "FULL": "consumers and producers both ways",
}

#: Prefix of the pseudo-attribute a moved ``extras`` key is graded as (``extras.reply``).
_EXTRAS_SEPARATOR = "extras."


def coerce_mode(mode: Optional[str]) -> str:
    """Normalize a compatibility mode name.

    Args:
        mode: ``BACKWARD`` (the default for ``None`` / blank), ``FORWARD`` or ``FULL``, optionally
            with ``_TRANSITIVE`` (two versions are compared, so it grades like the plain mode);
            any case.

    Returns:
        The upper-cased mode name.

    Raises:
        ValueError: If ``mode`` is not a known compatibility mode.
    """
    key = (mode or "BACKWARD").strip().upper() or "BACKWARD"
    mode_directions(key)  # validates
    return key


def mode_sides(mode: str) -> FrozenSet[str]:
    """The sides a mode checks: ``BACKWARD`` → consumers, ``FORWARD`` → producers, ``FULL`` → both."""
    return frozenset(_SIDE_OF_DIRECTION[d] for d in mode_directions(mode))


#: A side the mode does not check drops one tier.
_UNCHECKED = {Severity.BREAKING: Severity.DANGEROUS, Severity.DANGEROUS: Severity.SAFE, Severity.SAFE: Severity.SAFE}


def severity_under(finding: SideFinding, mode: str) -> Severity:
    """Grade a finding under ``mode``.

    Args:
        finding: The per-side finding.
        mode: A compatibility mode (see :func:`coerce_mode`).

    Returns:
        The worst of the checked sides' grades and the unchecked sides' grades one tier down.
    """
    sides = mode_sides(mode)
    consumer = finding.consumer if CONSUMER in sides else _UNCHECKED[finding.consumer]
    producer = finding.producer if PRODUCER in sides else _UNCHECKED[finding.producer]
    return _worst([consumer, producer])


def rationale(finding: SideFinding, mode: str) -> str:
    """One finding's sentence: the mode, what changed, and the grade for each side."""
    base_mode = mode.replace("_TRANSITIVE", "")
    return (
        f"[{mode}: {MODE_TEXT[base_mode]}] {finding.message} "
        f"(consumers: {finding.consumer.value}, producers: {finding.producer.value})"
    )


@dataclass
class ChangeFindings:
    """The rule findings for one canonical change.

    Attributes:
        findings: Every finding the rules produced for the change.
        unhandled: The attribute moves no rule graded (the baseline still grades them).
    """

    findings: List[SideFinding] = field(default_factory=list)
    unhandled: List[FieldChange] = field(default_factory=list)


@dataclass
class RuleReport:
    """Everything the rules found in one diff.

    Attributes:
        by_position: Diff change position → its findings (only changes a rule fired on).
        unattributed: ``(shape, finding)`` pairs no canonical change carries (servers, payloads of
            messages the diff does not list).
    """

    by_position: Dict[int, ChangeFindings] = field(default_factory=dict)
    unattributed: List[Tuple[str, SideFinding]] = field(default_factory=list)


# ===========================================================================
# Finding builders
# ===========================================================================


def _finding(rule: str, consumer: Severity, producer: Severity, message: str) -> SideFinding:
    return SideFinding(side_rule_id(rule, consumer, producer), consumer, producer, message)


def _address_changed(old: str, new: str) -> SideFinding:
    return _finding(
        "address-changed",
        Severity.BREAKING,
        Severity.DANGEROUS,
        f"channel address changed from {old!r} to {new!r}; consumers subscribed to the old address stop receiving",
    )


def _binding_changed(where: str) -> SideFinding:
    return _finding(
        "binding-changed",
        Severity.BREAKING,
        Severity.BREAKING,
        f"{where} protocol bindings changed; both sides must agree on the transport settings",
    )


def _protocol_changed(where: str, old: Any, new: Any) -> SideFinding:
    return _finding(
        "protocol-changed",
        Severity.BREAKING,
        Severity.BREAKING,
        f"{where} protocol changed from {old!r} to {new!r}",
    )


def _security_changed(where: str) -> SideFinding:
    return _finding(
        "security-changed", Severity.DANGEROUS, Severity.DANGEROUS, f"{where} security requirements changed"
    )


def _server_changed(message: str) -> SideFinding:
    return _finding("server-changed", Severity.DANGEROUS, Severity.DANGEROUS, message)


def _action_flipped(key: str, old: Any, new: Any) -> SideFinding:
    return _finding(
        "action-flipped",
        Severity.BREAKING,
        Severity.BREAKING,
        f"operation {key!r} action flipped from {old} to {new}",
    )


def _message_removed(key: str) -> SideFinding:
    return _finding(
        "message-removed",
        Severity.BREAKING,
        Severity.SAFE,
        f"message {key!r} removed from the operation's messages; "
        "new consumers break on it while old producers still send it",
    )


def _message_added(key: str) -> SideFinding:
    return _finding(
        "message-added",
        Severity.SAFE,
        Severity.DANGEROUS,
        f"message {key!r} added to the operation's messages; " "old consumers must handle it once producers send it",
    )


# ===========================================================================
# Small readers over the diff's self-projections
# ===========================================================================


def _extras(projection: Any) -> Mapping[str, Any]:
    extras = projection.get("extras") if isinstance(projection, Mapping) else None
    return extras if isinstance(extras, Mapping) else {}


def _parameters(projection: Any) -> Dict[str, Mapping[str, Any]]:
    """A channel projection's address parameters, by name."""
    params = projection.get("parameters") if isinstance(projection, Mapping) else None
    out: Dict[str, Mapping[str, Any]] = {}
    for param in params or []:
        if isinstance(param, Mapping) and isinstance(param.get("name"), str):
            out[param["name"]] = param
    return out


def _parameter_findings(before: Any, after: Any) -> Tuple[List[SideFinding], bool]:
    """Grade added address parameters.

    Returns:
        ``(findings, only_additions)``: a finding per added parameter, and whether every
        parameter move was an addition (otherwise the rest is left to the baseline).
    """
    old, new = _parameters(before), _parameters(after)
    findings: List[SideFinding] = []
    for name in sorted(set(new) - set(old)):
        if new[name].get("default") is None:
            findings.append(
                _finding(
                    "parameter-added",
                    Severity.BREAKING,
                    Severity.DANGEROUS,
                    f"address parameter {name!r} added without a default; consumers must now supply it",
                )
            )
        else:
            findings.append(
                _finding(
                    "parameter-added-with-default",
                    Severity.SAFE,
                    Severity.SAFE,
                    f"address parameter {name!r} added with default {new[name].get('default')!r}",
                )
            )
    only_additions = set(old) <= set(new) and all(old[n] == new[n] for n in old)
    return findings, only_additions


def _channel_pair_findings(old_key: str, new_key: str, before: Any, after: Any) -> List[SideFinding]:
    """Findings for a channel whose address changed (graded on both halves of the pair)."""
    findings = [_address_changed(old_key, new_key)]
    findings += _parameter_findings(before, after)[0]
    if (before or {}).get("bindings") != (after or {}).get("bindings"):
        findings.append(_binding_changed(f"channel {new_key!r}"))
    if (before or {}).get("protocol") != (after or {}).get("protocol"):
        findings.append(
            _protocol_changed(f"channel {new_key!r}", (before or {}).get("protocol"), (after or {}).get("protocol"))
        )
    return findings


def _owner_operation(message_key: str) -> str:
    """The operation key a message key belongs to (``<operation>#event.<name>``)."""
    return message_key.rsplit("#event.", 1)[0]


def _operation_keys(model: CanonicalApi) -> Set[str]:
    return {operation.key for service in model.services for operation in service.operations}


def _operations(model: CanonicalApi) -> Dict[str, Any]:
    return {operation.key: operation for service in model.services for operation in service.operations}


# ===========================================================================
# Message objects as the source wrote them (for payload delegation)
# ===========================================================================


class _MessageCapture(AsyncApiNormalizer):
    """The AsyncAPI normalizer, recording each message object under its canonical key.

    The canonical model keeps only a dict payload, so a ``.proto`` text payload and an AsyncAPI 2
    message-level ``schemaFormat`` are read back from the source document through the very code
    path that keys the messages.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: Dict[str, Mapping[str, Any]] = {}

    def _message(
        self, op_key: str, message_name: str, spec: Dict[str, Any], coercer: Any, default_content_type: Optional[str]
    ) -> Message:  # type: ignore[override]
        message = super()._message(op_key, message_name, spec, coercer, default_content_type)
        self.messages[message.key] = spec
        return message


def _message_objects(model: CanonicalApi) -> Dict[str, Mapping[str, Any]]:
    """Each message's source object by canonical key (rebuilt from the canonical model without ``raw``)."""
    if isinstance(model.raw, dict):
        capture = _MessageCapture()
        try:
            capture.normalize(model.raw, include_raw=False)
            return capture.messages
        except ValueError:
            pass
    out: Dict[str, Mapping[str, Any]] = {}
    for service in model.services:
        for operation in service.operations:
            for message in operation.messages:
                obj: Dict[str, Any] = {"payload": message.payload_schema}
                if "schemaFormat" in message.extras:
                    obj["schemaFormat"] = message.extras["schemaFormat"]
                out[message.key] = obj
    return out


# ===========================================================================
# Per-category rules
# ===========================================================================


def _split_fields(change: EntityChange) -> List[FieldChange]:
    """The change's moved attributes, with ``extras`` split into one ``extras.<key>`` per moved key."""
    out: List[FieldChange] = []
    for moved in change.fields:
        if moved.field != "extras":
            out.append(moved)
            continue
        before = moved.before if isinstance(moved.before, Mapping) else {}
        after = moved.after if isinstance(moved.after, Mapping) else {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                out.append(FieldChange(field=f"{_EXTRAS_SEPARATOR}{key}", before=before.get(key), after=after.get(key)))
    return out


def _modified_channel(change: EntityChange) -> ChangeFindings:
    result = ChangeFindings()
    where = f"channel {change.key!r}"
    for moved in _split_fields(change):
        name = moved.field
        if name == "address":
            result.findings.append(_address_changed(str(moved.before), str(moved.after)))
        elif name == "parameters":
            found, only_additions = _parameter_findings(change.before, change.after)
            result.findings += found
            if not only_additions:
                result.unhandled.append(moved)
        elif name == "bindings":
            result.findings.append(_binding_changed(where))
        elif name == "protocol":
            result.findings.append(_protocol_changed(where, moved.before, moved.after))
        elif name == "extras.servers":
            result.findings.append(_server_changed(f"{where} servers changed from {moved.before!r} to {moved.after!r}"))
        else:
            result.unhandled.append(moved)
    return result


def _modified_operation(change: EntityChange) -> ChangeFindings:
    result = ChangeFindings()
    where = f"operation {change.key!r}"
    flipped = False
    for moved in _split_fields(change):
        name = moved.field
        if name in ("kind", "extras.action"):
            if not flipped:
                old_action = _extras(change.before).get("action", (change.before or {}).get("kind"))
                new_action = _extras(change.after).get("action", (change.after or {}).get("kind"))
                result.findings.append(_action_flipped(change.key, old_action, new_action))
                flipped = True
        elif name == "channel_ref":
            result.findings.append(_address_changed(str(moved.before), str(moved.after)))
        elif name == "extras.reply" and moved.before is not None and moved.after is None:
            result.findings.append(
                _finding(
                    "reply-removed",
                    Severity.BREAKING,
                    Severity.DANGEROUS,
                    f"{where} no longer replies; requesters waiting for the reply break",
                )
            )
        elif name == "extras.bindings":
            result.findings.append(_binding_changed(where))
        elif name == "extras.security":
            result.findings.append(_security_changed(where))
        else:
            result.unhandled.append(moved)
    return result


def _modified_message(change: EntityChange, payload: Optional[List[SideFinding]]) -> ChangeFindings:
    result = ChangeFindings()
    payload_fields = {"payload_schema", "extras.schemaFormat"}
    for moved in _split_fields(change):
        if moved.field in payload_fields and payload is not None:
            continue  # graded once, below, by the payload's own check
        if moved.field == "extras.bindings":
            result.findings.append(_binding_changed(f"message {change.key!r}"))
        else:
            result.unhandled.append(moved)
    if payload is not None and any(f.field in payload_fields for f in _split_fields(change)):
        result.findings += payload
    return result


def _pair_channels(
    changes: List[EntityChange], base: CanonicalApi, target: CanonicalApi
) -> Dict[int, Tuple[str, str, Any, Any]]:
    """Pair removed and added channels that are one channel with a new address.

    Returns:
        Position of each paired change → ``(old key, new key, old projection, new projection)``.
    """
    removed = {
        c.key: (i, c)
        for i, c in enumerate(changes)
        if c.category is EntityCategory.CHANNEL and c.kind is ChangeKind.REMOVED
    }
    added = {
        c.key: (i, c)
        for i, c in enumerate(changes)
        if c.category is EntityCategory.CHANNEL and c.kind is ChangeKind.ADDED
    }
    if not removed or not added:
        return {}
    links: List[Tuple[str, str]] = []
    added_by_name = {(c.after or {}).get("name"): key for key, (_, c) in added.items() if (c.after or {}).get("name")}
    for key, (_, c) in sorted(removed.items()):
        name = (c.before or {}).get("name")
        if name and name in added_by_name:
            links.append((key, added_by_name[name]))
    old_ops, new_ops = _operations(base), _operations(target)
    for op_key in sorted(set(old_ops) & set(new_ops)):
        old_ref, new_ref = old_ops[op_key].channel_ref, new_ops[op_key].channel_ref
        if old_ref in removed and new_ref in added:
            links.append((old_ref, new_ref))
    pairs: Dict[int, Tuple[str, str, Any, Any]] = {}
    used: Set[str] = set()
    for old_key, new_key in links:
        if old_key in used or new_key in used:
            continue
        used |= {old_key, new_key}
        old_pos, old_change = removed[old_key]
        new_pos, new_change = added[new_key]
        pair = (old_key, new_key, old_change.before, new_change.after)
        pairs[old_pos] = pair
        pairs[new_pos] = pair
    return pairs


def _is_fallback_keyed(change: EntityChange, projection: Any) -> bool:
    """Whether an operation is keyed ``"<action> <address>"`` (an AsyncAPI 2 operation without an ``operationId``)."""
    action, channel = _extras(projection).get("action"), (projection or {}).get("channel_ref")
    return bool(action and channel) and change.key == f"{action} {channel}"


def _pair_flipped_operations(changes: List[EntityChange]) -> Dict[int, SideFinding]:
    """Pair a removed and an added operation on one channel with the other action (AsyncAPI 2 fallback keys)."""
    removed = [
        (i, c)
        for i, c in enumerate(changes)
        if c.category is EntityCategory.OPERATION and c.kind is ChangeKind.REMOVED and _is_fallback_keyed(c, c.before)
    ]
    added = [
        (i, c)
        for i, c in enumerate(changes)
        if c.category is EntityCategory.OPERATION and c.kind is ChangeKind.ADDED and _is_fallback_keyed(c, c.after)
    ]
    out: Dict[int, SideFinding] = {}
    used: Set[int] = set()
    for old_pos, old in removed:
        before = old.before or {}
        for new_pos, new in added:
            after = new.after or {}
            if (
                new_pos in used
                or not before.get("channel_ref")
                or before.get("channel_ref") != after.get("channel_ref")
            ):
                continue
            if before.get("kind") == after.get("kind"):
                continue
            finding = _action_flipped(
                f"{old.key} -> {new.key}",
                _extras(before).get("action", before.get("kind")),
                _extras(after).get("action", after.get("kind")),
            )
            out[old_pos] = finding
            out[new_pos] = finding
            used.add(new_pos)
            break
    return out


# ===========================================================================
# Servers (not a diff category: unattributed)
# ===========================================================================

#: Server ``extras`` keys that describe rather than constrain a connection.
_DESCRIPTIVE_SERVER_EXTRAS = frozenset({"tags", "externalDocs", "title", "summary"})


def _server_view(server: Any) -> Dict[str, Any]:
    view = server.model_dump(mode="json", exclude={"description"})
    view["extras"] = {k: v for k, v in (view.get("extras") or {}).items() if k not in _DESCRIPTIVE_SERVER_EXTRAS}
    return view


def _server_findings(base: CanonicalApi, target: CanonicalApi) -> Iterable[Tuple[str, SideFinding]]:
    """Findings for servers added, removed or changed, paired by name (then URL)."""
    old = {s.name or s.url: s for s in base.servers}
    new = {s.name or s.url: s for s in target.servers}
    for name in sorted(set(old) | set(new)):
        shape = f"servers/{name}"
        if name not in new:
            yield shape, _server_changed(f"server {name!r} was removed")
            continue
        if name not in old:
            yield shape, _server_changed(f"server {name!r} was added")
            continue
        before, after = _server_view(old[name]), _server_view(new[name])
        if before == after:
            continue
        if before.get("protocol") != after.get("protocol"):
            yield shape, _protocol_changed(f"server {name!r}", before.get("protocol"), after.get("protocol"))
        moved = {
            k for k in set(before) | set(after) if k not in ("protocol", "extras") and before.get(k) != after.get(k)
        }
        old_extras, new_extras = before.get("extras") or {}, after.get("extras") or {}
        moved |= {f"extras.{k}" for k in set(old_extras) | set(new_extras) if old_extras.get(k) != new_extras.get(k)}
        if "extras.security" in moved:
            yield shape, _security_changed(f"server {name!r}")
            moved.discard("extras.security")
        if "extras.bindings" in moved:
            yield shape, _binding_changed(f"server {name!r}")
            moved.discard("extras.bindings")
        if moved:
            yield shape, _server_changed(f"server {name!r} changed {', '.join(sorted(moved))}")


# ===========================================================================
# Entry point
# ===========================================================================


def evaluate(model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> RuleReport:
    """Run every AsyncAPI channel, operation, message, payload and server rule over a diff.

    Args:
        model_diff: The canonical diff of ``base`` → ``target``.
        base: The old version.
        target: The new version.

    Returns:
        The :class:`RuleReport`: findings per diff change position, and unattributed findings.
    """
    report = RuleReport()
    changes = model_diff.changes
    channel_pairs = _pair_channels(changes, base, target)
    flipped = _pair_flipped_operations(changes)
    old_ops, new_ops = _operation_keys(base), _operation_keys(target)

    old_messages, new_messages = _message_objects(base), _message_objects(target)
    payloads: Dict[str, Optional[List[SideFinding]]] = {
        key: compare_payloads(old_messages[key], new_messages[key])
        for key in sorted(set(old_messages) & set(new_messages))
    }
    listed_messages = {c.key for c in changes if c.category is EntityCategory.MESSAGE}

    for position, change in enumerate(changes):
        found: Optional[ChangeFindings] = None
        if position in channel_pairs:
            old_key, new_key, before, after = channel_pairs[position]
            found = ChangeFindings(findings=_channel_pair_findings(old_key, new_key, before, after))
        elif position in flipped:
            found = ChangeFindings(findings=[flipped[position]])
        elif change.kind is ChangeKind.MODIFIED:
            if change.category is EntityCategory.CHANNEL:
                found = _modified_channel(change)
            elif change.category is EntityCategory.OPERATION:
                found = _modified_operation(change)
            elif change.category is EntityCategory.MESSAGE:
                found = _modified_message(change, payloads.get(change.key))
        elif change.category is EntityCategory.MESSAGE:
            owner = _owner_operation(change.key)
            if change.kind is ChangeKind.REMOVED and owner in new_ops:
                found = ChangeFindings(findings=[_message_removed(change.key)])
            elif change.kind is ChangeKind.ADDED and owner in old_ops:
                found = ChangeFindings(findings=[_message_added(change.key)])
        if found is not None and found.findings:
            report.by_position[position] = found

    for key, payload in payloads.items():
        if key not in listed_messages and payload:
            report.unattributed += [(key, finding) for finding in payload]
    report.unattributed += list(_server_findings(base, target))
    return report


def attribute_severity(moved: FieldChange) -> Severity:
    """The baseline grade of an attribute move no rule handles (``extras.<key>`` grades as ``extras``)."""
    if moved.field.startswith(_EXTRAS_SEPARATOR):
        return _classify_modified_attribute(FieldChange(field="extras", before=moved.before, after=moved.after))
    return _classify_modified_attribute(moved)
