"""A2A Agent Card emitter: canonical model → ``agent-card.json`` — MFX-32.2 (#4296).

An A2A agent publishes an **Agent Card** at ``/.well-known/agent-card.json``: who the agent is,
where to reach it, what its transport supports, how to authenticate, and the **skills** it offers.
The import side reads one (:mod:`app.a2a_import_source`, MFI-18.1); this module writes one, in the
A2A 0.3 shape that importer reads, so an exported card imports straight back.

Two sources, two tiers
----------------------
**An agent source** (the model has :class:`~app.canonical_model.AgentDescriptor` entries — an
imported A2A card, an ACP agent listing) is written **lossless**: each descriptor becomes one card
with its own name, description, version, provider, capabilities, default modes, security schemes
and requirements, and one skill per :class:`~app.canonical_model.AgentSkill` with its declared id,
tags, examples, modes and security. The card-only facts the A2A importer keeps on ``api.extras``
(``preferredTransport``, ``documentationUrl``, ``iconUrl``, the extended-card flag) and the
additional interfaces (the model's servers after the first) are written back too. What cannot
survive is reported: JWS ``signatures`` sign the original bytes and are not re-written, and a
required field the source left out is synthesized (``SYNTH``).

**A REST or RPC source** (no agent descriptor) is **reframed** as an agent (``APPROX``): the API
becomes one agent named after its title, and its operations become skills —

* ``skills_from="operations"`` (default): one skill per operation, its ``id`` the operation's name
  (deduplicated ``_2``, ``_3`` …), its tags the operation's tags (else the service's name);
* ``skills_from="tags"``: one skill per tag, listing the operations it groups.

A skill carries no parameters or schemas — only media types — so each operation's request and
response bodies are reduced to ``inputModes`` / ``outputModes``. The API's first server becomes the
agent ``url`` (``HTTP+JSON`` transport), the others ``additionalInterfaces``; the security schemes
the model records (:mod:`app.security_scheme_stubs`) become ``securitySchemes``, and an operation's
own requirement (:mod:`app.canonical_security`) the skill's ``security``. Event operations have no
skill form and are dropped; a deprecated one is written only with ``include_deprecated``.

Every card is checked against the vendored AgentCard schema (``data/a2a_agent_card_schema.json``)
before it is returned, so an invalid card cannot ship.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Union

from jsonschema import Draft7Validator
from pydantic import Field, ValidationError

from .canonical_model import (
    AgentDescriptor,
    AgentSecurityScheme,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    MessageRole,
    Operation,
    Type,
)
from .canonical_security import operation_security_schemes
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessReport, LossinessSeverity
from .security_scheme_stubs import SECURITY_SCHEMES_EXTRAS_KEY, scheme_stub
from .tool_projection import EVENT_OPERATION_KINDS

__all__ = [
    "A2A_FORMAT_KEY",
    "A2aEmitOptions",
    "A2aEmitter",
    "A2aFidelityRulePack",
    "AGENT_CARD_FILE",
    "agent_card_schema_violations",
    "build_agent_cards",
]

#: Registry key and format of the emitter — the same key as the A2A importer, so the round-trip
#: matrix pairs ``a2a -> a2a`` without an alias.
A2A_FORMAT_KEY = "a2a"
#: The protocol version a reframed card (or a descriptor that names none) declares.
PROTOCOL_VERSION = "0.3.0"
#: The well-known file name of a card (A2A 0.3+).
AGENT_CARD_FILE = "agent-card.json"
OUTPUT_MEDIA_TYPE = "application/json"
#: The transport a reframed REST/RPC API is written with: A2A's HTTP+JSON binding.
REFRAMED_TRANSPORT = "HTTP+JSON"
#: The transport A2A assumes when a card names none.
DEFAULT_TRANSPORT = "JSONRPC"
#: The endpoint written when the source has none — a placeholder to replace before publishing.
PLACEHOLDER_URL = "https://agent.example.com/a2a"
#: The modes a reframed card declares by default.
DEFAULT_MODES = ("application/json",)

#: Loss subjects this emitter records.
LOSS_SKILL_REFRAMED = "a2a-skill-reframed"
LOSS_SKILL_GROUPED = "a2a-skill-grouped-by-tag"
LOSS_EVENT_NOT_A_SKILL = "a2a-event-not-a-skill"
LOSS_SIGNATURES = "a2a-signatures-not-rewritten"
LOSS_REQUIRED_SYNTHESIZED = "a2a-required-field-synthesized"
LOSS_URL_PLACEHOLDER = "a2a-url-placeholder"
LOSS_PROVIDER_INCOMPLETE = "a2a-provider-incomplete"
LOSS_SCHEME_INVALID = "a2a-security-scheme-invalid"
LOSS_SKILL_ID_SYNTHESIZED = "a2a-skill-id-synthesized"

_SCHEMA_PATH = Path(__file__).parent / "data" / "a2a_agent_card_schema.json"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: :class:`~app.canonical_model.AgentSecurityScheme` field → A2A ``securitySchemes`` key (the
#: inverse of :mod:`app.agent_descriptor_schemes`).
#: The ``type`` values an A2A security scheme may have (the OpenAPI 3 set).
_SCHEME_TYPES = frozenset({"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"})

_SCHEME_KEYS: Tuple[Tuple[str, str], ...] = (
    ("scheme", "scheme"),
    ("location", "in"),
    ("parameter_name", "name"),
    ("bearer_format", "bearerFormat"),
    ("openid_connect_url", "openIdConnectUrl"),
    ("flows", "flows"),
    ("description", "description"),
)


class A2aEmitOptions(EmitOptions):
    """Per-target options for :class:`A2aEmitter`."""

    skills_from: Literal["operations", "tags"] = Field(
        default="operations",
        description="How a REST or RPC source's operations become skills: `operations` (default) "
        "writes one skill per operation; `tags` writes one skill per tag, grouping its operations. "
        "An agent source keeps its own skills either way.",
    )
    url: Optional[str] = Field(
        default=None,
        description="The agent endpoint to write as `url` when the source names none (otherwise "
        f"`{PLACEHOLDER_URL}` is written and reported). The source's own endpoint wins.",
    )
    include_deprecated: bool = Field(
        default=False,
        description="Also write a skill for each deprecated operation of a REST or RPC source.",
    )


# ===========================================================================
# The AgentCard schema
# ===========================================================================


@lru_cache(maxsize=None)
def _card_validator() -> Draft7Validator:
    """The vendored A2A AgentCard schema."""
    return Draft7Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def agent_card_schema_violations(card: Mapping[str, Any]) -> List[str]:
    """Check one emitted card against the A2A AgentCard schema.

    Args:
        card: The card object.

    Returns:
        Human-readable violations (``/path: message``); empty when the card is valid.
    """
    problems = []
    for error in sorted(_card_validator().iter_errors(card), key=lambda e: list(e.absolute_path)):
        pointer = "".join(f"/{part}" for part in error.absolute_path)
        problems.append(f"{pointer or '/'}: {error.message}")
    return problems


# ===========================================================================
# Shared helpers
# ===========================================================================


def _slug(text: str) -> str:
    """A file-name / skill-id slug: lower-case letters, digits and hyphens."""
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "agent"


def _humanize(name: str) -> str:
    """``listPets`` / ``list_pets`` → ``List pets``: a skill's display name from an operation name."""
    words = _CAMEL_RE.sub(" ", name).replace("_", " ").replace("-", " ").split()
    text = " ".join(word.lower() for word in words)
    return text[:1].upper() + text[1:] if text else name


def _scheme_object(scheme: AgentSecurityScheme) -> Dict[str, Any]:
    """One canonical scheme as the A2A ``securitySchemes`` entry it was read from."""
    body: Dict[str, Any] = {"type": scheme.type}
    for attribute, key in _SCHEME_KEYS:
        value = getattr(scheme, attribute)
        if value is not None:
            body[key] = value
    body.update(scheme.extras or {})
    return body


def _requirements(requirements: Sequence[Mapping[str, Sequence[str]]]) -> List[Dict[str, List[str]]]:
    """Security requirements as JSON-ready ``[{scheme: [scopes]}]``."""
    return [{name: list(scopes) for name, scopes in requirement.items()} for requirement in requirements]


@dataclass
class _CardPlan:
    """One card being assembled, and what it cost.

    Attributes:
        file: The file name the card is written to.
        card: The card object.
        skill_of: Operation key → the id of the skill it was written as.
        synthesized: ``(pointer, reason)`` per value invented to satisfy the schema.
        dropped: ``(pointer, reason)`` per source value left out because A2A cannot hold it.
    """

    file: str
    card: Dict[str, Any]
    skill_of: Dict[str, str] = field(default_factory=dict)
    synthesized: List[Tuple[str, str]] = field(default_factory=list)
    dropped: List[Tuple[str, str]] = field(default_factory=list)


def _fill_required(plan: _CardPlan, key: str, value: Any, fallback: Any, reason: str) -> None:
    """Set a required card member, synthesizing ``fallback`` (and noting why) when ``value`` is empty."""
    if value:
        plan.card[key] = value
    else:
        plan.card[key] = fallback
        plan.synthesized.append((f"/{key}", reason))


def _endpoint(api: CanonicalApi, preferred: Optional[str], options: A2aEmitOptions, plan: _CardPlan) -> None:
    """Write ``url`` (and note a placeholder) from the preferred URL, the servers or the options."""
    url = preferred or (api.servers[0].url if api.servers else None) or options.url
    if url:
        plan.card["url"] = url
        return
    plan.card["url"] = PLACEHOLDER_URL
    plan.synthesized.append(
        ("/url", f"the source names no endpoint; {PLACEHOLDER_URL!r} is a placeholder — set the `url` option "
         "or replace it before publishing")
    )


# ===========================================================================
# Agent source → card (lossless tier)
# ===========================================================================


def _descriptor_card(
    api: CanonicalApi, descriptor: AgentDescriptor, file: str, options: A2aEmitOptions
) -> _CardPlan:
    """One card from one agent descriptor, in A2A member order."""
    plan = _CardPlan(file=file, card={})
    card = plan.card
    extras = api.extras or {}
    from_a2a = descriptor.protocol == "a2a"
    _fill_required(
        plan, "protocolVersion", descriptor.protocol_version if from_a2a else None, PROTOCOL_VERSION,
        f"the {descriptor.protocol.upper()} agent declares no A2A protocol version; {PROTOCOL_VERSION!r} is written",
    )
    card["name"] = descriptor.name
    _fill_required(
        plan, "description", descriptor.description, f"The {descriptor.name} agent.",
        "the agent has no description; one is made from its name",
    )
    _endpoint(api, descriptor.url, options, plan)
    transport = extras.get("preferred_transport") if from_a2a else None
    if isinstance(transport, str) and transport:
        card["preferredTransport"] = transport
    interfaces = [
        {"url": server.url, "transport": server.protocol or transport or DEFAULT_TRANSPORT}
        for server in api.servers
        if server.url != card["url"]
    ]
    if interfaces:
        card["additionalInterfaces"] = [{"url": card["url"], "transport": transport or DEFAULT_TRANSPORT}, *interfaces]
    if isinstance(extras.get("icon_url"), str):
        card["iconUrl"] = extras["icon_url"]
    provider = descriptor.provider
    if provider is not None and provider.organization and provider.url:
        card["provider"] = {"organization": provider.organization, "url": provider.url}
    elif provider is not None and (provider.organization or provider.url):
        plan.dropped.append(
            ("/provider", "A2A requires a provider's organization and url; the source gives only one, "
             "so the provider is not written")
        )
    _fill_required(
        plan, "version", descriptor.version, api.version or "0.0.0",
        "the agent has no version; the model's version (or 0.0.0) is written",
    )
    if isinstance(extras.get("documentation_url"), str):
        card["documentationUrl"] = extras["documentation_url"]
    card["capabilities"] = dict(descriptor.capabilities)
    if descriptor.security_schemes:
        schemes = {}
        for scheme in descriptor.security_schemes:
            if scheme.type in _SCHEME_TYPES:
                schemes[scheme.name] = _scheme_object(scheme)
            else:
                plan.dropped.append((
                    f"/securitySchemes/{scheme.name}",
                    f"security scheme {scheme.name!r} has type {scheme.type!r}, which A2A does not define; "
                    "it is not written",
                ))
        if schemes:
            card["securitySchemes"] = schemes
    if descriptor.security:
        card["security"] = _requirements(descriptor.security)
    card["defaultInputModes"] = list(descriptor.default_input_modes)
    card["defaultOutputModes"] = list(descriptor.default_output_modes)
    skills: List[Dict[str, Any]] = []
    for index, skill in enumerate(descriptor.skills):
        entry: Dict[str, Any] = {"id": skill.id, "name": skill.name}
        if skill.description:
            entry["description"] = skill.description
        else:
            entry["description"] = skill.name
            plan.synthesized.append(
                (f"/skills/{index}/description", f"skill {skill.id!r} has no description; its name is written")
            )
        entry["tags"] = list(skill.tags)
        for key, values in (("examples", skill.examples), ("inputModes", skill.input_modes),
                            ("outputModes", skill.output_modes)):
            if values:
                entry[key] = list(values)
        if skill.security is not None:
            entry["security"] = _requirements(skill.security)
        skills.append(entry)
        if skill.operation_ref:
            plan.skill_of[skill.operation_ref] = skill.id
    card["skills"] = skills
    if extras.get("supports_authenticated_extended_card") is True and from_a2a:
        card["supportsAuthenticatedExtendedCard"] = True
    return plan


# ===========================================================================
# REST / RPC source → card (reframed)
# ===========================================================================


def _skill_operations(api: CanonicalApi, options: A2aEmitOptions) -> List[Tuple[str, Operation]]:
    """``(service name, operation)`` for every operation that becomes (part of) a skill."""
    chosen = []
    for service in api.services:
        for operation in service.operations:
            if operation.kind in EVENT_OPERATION_KINDS:
                continue
            if operation.deprecated and not options.include_deprecated:
                continue
            chosen.append((service.name or service.key, operation))
    return chosen


def _modes(operation: Operation, role: MessageRole) -> List[str]:
    """The media types an operation's request (or responses) declare, in order, deduplicated."""
    modes: List[str] = []
    for message in operation.messages:
        if message.role is role:
            modes.extend(mode for mode in message.content_types if mode not in modes)
    return modes


def _operation_description(operation: Operation) -> str:
    """A skill description: the operation's own, else what it calls."""
    if operation.description:
        return operation.description
    if operation.http_method and operation.http_path:
        return f"Calls {operation.http_method.upper()} {operation.http_path}."
    return f"Calls the {operation.name} operation."


def _operation_security(api: CanonicalApi, operation: Operation) -> List[str]:
    """The schemes an operation itself requires (never a model-wide observation)."""
    schemes, scope = operation_security_schemes(api, operation)
    return schemes if scope == "operation" else []


def _unique(ids: Sequence[str]) -> List[str]:
    """Deduplicate skill ids in order: a repeat gets ``_2``, ``_3`` …"""
    seen: Dict[str, int] = {}
    out = []
    for value in ids:
        seen[value] = seen.get(value, 0) + 1
        out.append(value if seen[value] == 1 else f"{value}_{seen[value]}")
    return out


def _skill_entry(skill_id: str, name: str, description: str, tags: List[str],
                 operations: Sequence[Operation], api: CanonicalApi) -> Dict[str, Any]:
    """One reframed skill from the operations it covers."""
    entry: Dict[str, Any] = {"id": skill_id, "name": name, "description": description, "tags": tags}
    for key, role in (("inputModes", MessageRole.REQUEST), ("outputModes", MessageRole.RESPONSE)):
        modes: List[str] = []
        for operation in operations:
            modes.extend(mode for mode in _modes(operation, role) if mode not in modes)
        if modes and modes != list(DEFAULT_MODES):
            entry[key] = modes
    schemes: List[str] = []
    for operation in operations:
        schemes.extend(name for name in _operation_security(api, operation) if name not in schemes)
    if schemes:
        # The skill needs every scheme any of its operations needs — one alternative per scheme.
        entry["security"] = [{name: []} for name in schemes]
    return entry


def _reframed_card(api: CanonicalApi, options: A2aEmitOptions, losses: LossTracker) -> _CardPlan:
    """One card for a REST or RPC model: the API as an agent, its operations as skills."""
    plan = _CardPlan(file=AGENT_CARD_FILE, card={})
    card = plan.card
    name = api.title or api.identity.name or "API"
    card["protocolVersion"] = PROTOCOL_VERSION
    card["name"] = name
    _fill_required(
        plan, "description", api.description, f"An agent interface to the {name} API.",
        "the API has no description; one is made from its title",
    )
    _endpoint(api, None, options, plan)
    card["preferredTransport"] = REFRAMED_TRANSPORT
    others = [server.url for server in api.servers[1:] if server.url != card["url"]]
    if others:
        card["additionalInterfaces"] = [
            {"url": url, "transport": REFRAMED_TRANSPORT} for url in [card["url"], *others]
        ]
    card["version"] = api.version or "0.0.0"
    if not api.version:
        plan.synthesized.append(("/version", "the API has no version; 0.0.0 is written"))

    chosen = _skill_operations(api, options)
    for service in api.services:
        for operation in service.operations:
            if operation.kind in EVENT_OPERATION_KINDS:
                losses.record(
                    LossKind.NA, LOSS_EVENT_NOT_A_SKILL,
                    f"event operation {operation.key!r} has no skill form; an A2A skill answers a message",
                    pointer=operation.key,
                )
    card["capabilities"] = {
        "streaming": any(operation.streaming.value != "none" for _, operation in chosen),
        "pushNotifications": False,
    }

    stubs = (api.extras or {}).get(SECURITY_SCHEMES_EXTRAS_KEY)
    stubs = stubs if isinstance(stubs, Mapping) else {}
    used = [scheme for _, op in chosen for scheme in _operation_security(api, op)]
    if used:
        card["securitySchemes"] = {
            scheme: dict(stubs[scheme]) if isinstance(stubs.get(scheme), Mapping) else scheme_stub(scheme)
            for scheme in dict.fromkeys(used)
        }
    card["defaultInputModes"] = list(DEFAULT_MODES)
    card["defaultOutputModes"] = list(DEFAULT_MODES)

    skills: List[Dict[str, Any]] = []
    if options.skills_from == "tags":
        groups: Dict[str, List[Operation]] = {}
        for service_name, operation in chosen:
            groups.setdefault(operation.tags[0] if operation.tags else service_name, []).append(operation)
        ids = _unique([_slug(tag) for tag in groups])
        for skill_id, (tag, operations) in zip(ids, groups.items()):
            listed = ", ".join(op.name for op in operations)
            skills.append(_skill_entry(
                skill_id, tag, f"Operations tagged {tag}: {listed}.", [tag], operations, api,
            ))
            for operation in operations:
                plan.skill_of[operation.key] = skill_id
                losses.record(
                    LossKind.INFERRED, LOSS_SKILL_GROUPED,
                    f"operation {operation.key!r} is written as part of the {tag!r} skill {skill_id!r}; "
                    "a skill has no parameters or schemas, only media types",
                    pointer=operation.key,
                )
    else:
        ids = _unique([op.name or op.key for _, op in chosen])
        for skill_id, (service_name, operation) in zip(ids, chosen):
            tags = list(operation.tags) or [service_name]
            skills.append(_skill_entry(
                skill_id, _humanize(operation.name or operation.key), _operation_description(operation),
                tags, [operation], api,
            ))
            plan.skill_of[operation.key] = skill_id
            losses.record(
                LossKind.INFERRED, LOSS_SKILL_REFRAMED,
                f"operation {operation.key!r} is reframed as skill {skill_id!r}; a skill has no parameters "
                "or schemas, so its request and response are reduced to media types",
                pointer=operation.key,
            )
            if skill_id != (operation.name or operation.key):
                losses.record(
                    LossKind.INFERRED, LOSS_SKILL_ID_SYNTHESIZED,
                    f"skill id {skill_id!r} was deduplicated from {operation.name!r}",
                    pointer=operation.key,
                )
    card["skills"] = skills
    return plan


# ===========================================================================
# Building the cards
# ===========================================================================


def build_agent_cards(
    api: CanonicalApi,
    options: A2aEmitOptions,
    *,
    losses: LossTracker,
    tracker: Optional[ProvenanceTracker] = None,
) -> List[_CardPlan]:
    """Build the Agent Card(s) for ``api``.

    Args:
        api: The canonical model to export.
        options: The emit options.
        losses: Loss tracker the build records onto.
        tracker: Provenance tracker for synthesized values (``None`` to skip provenance).

    Returns:
        One plan per card: one per agent descriptor for an agent source (``agent-card.json`` for a
        single agent, ``<agent>.agent-card.json`` for several), else one reframed card.

    Raises:
        EmitPreconditionError: When a REST or RPC model has no operation a skill can be made of.
        ValueError: When a card fails the AgentCard schema.
    """
    if api.agents:
        single = len(api.agents) == 1
        names = _unique([_slug(agent.name) for agent in api.agents])
        plans = [
            _descriptor_card(api, agent, AGENT_CARD_FILE if single else f"{name}.{AGENT_CARD_FILE}", options)
            for agent, name in zip(api.agents, names)
        ]
        signatures = (api.extras or {}).get("signature_count")
        if isinstance(signatures, int) and signatures > 0:
            losses.record(
                LossKind.NA, LOSS_SIGNATURES,
                f"the card's {signatures} JWS signature(s) sign the original bytes and are not re-written; "
                "sign the exported card again",
            )
    else:
        plan = _reframed_card(api, options, losses)
        if not plan.card["skills"]:
            raise EmitPreconditionError(
                "An Agent Card lists the skills an agent offers, and this model has no operation to make "
                "a skill of (an event-only or schema-only model has none)."
            )
        plans = [plan]

    problems: List[str] = []
    for plan in plans:
        problems += [f"{plan.file}{p}" for p in agent_card_schema_violations(plan.card)]
        for pointer, reason in plan.synthesized:
            subject = LOSS_URL_PLACEHOLDER if pointer == "/url" else LOSS_REQUIRED_SYNTHESIZED
            losses.record(LossKind.INFERRED, subject, reason, pointer=pointer)
            if tracker is not None:
                tracker.record(f"/{plan.file}{pointer}", Provenance.INFERRED, reason)
        for pointer, reason in plan.dropped:
            subject = LOSS_PROVIDER_INCOMPLETE if pointer == "/provider" else LOSS_SCHEME_INVALID
            losses.record(LossKind.NA, subject, reason, pointer=pointer)
    if problems:
        raise ValueError("The Agent Card is not valid: " + "; ".join(problems))
    return plans


# ===========================================================================
# Fidelity
# ===========================================================================


class A2aFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for A2A Agent Card export.

    **Agent source:** a skill's operation is ``OK`` (the card is the source's own shape); an
    operation no skill points at is ``DROP``ped; JWS signatures are ``DROP``ped (they sign the
    original bytes), and a required field the source left out is ``SYNTH``.

    **REST / RPC source:** the API is reframed as an agent, so the root is ``APPROX`` and so is each
    operation written as (part of) a skill; an event operation, or a deprecated one without
    ``include_deprecated``, is ``DROP``ped. A skill has no schema vocabulary, so every named type is
    ``DROP``ped (a skill keeps media types only), as is every channel.
    """

    target_label = "A2A Agent Card"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = A2aEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = A2aEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the card(s) once to learn each operation's skill, then walk the model."""
        options = getattr(self, "_options", None) or A2aEmitOptions()
        self._agent_source = bool(api.agents)
        try:
            self._plans = build_agent_cards(api, options, losses=LossTracker())
        except (EmitPreconditionError, ValueError):
            self._plans = []
        self._skill_of = {key: skill for plan in self._plans for key, skill in plan.skill_of.items()}
        self._a2a_skills = {
            skill.operation_ref for agent in api.agents if agent.protocol == "a2a" for skill in agent.skills
        }
        self._grouped = options.skills_from == "tags"
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The reframing (REST/RPC), signatures, and synthesized required fields."""
        verdicts: List[FidelityVerdict] = []
        if not self._agent_source:
            verdicts.append(FidelityVerdict.approx(
                message=f"an {self.target_label} describes an agent; the API is reframed as one agent whose "
                "skills are its operations — an agent must front the API at the card's url to serve them",
                target_mapping="API → agent; servers → url + additionalInterfaces (HTTP+JSON)",
            ))
        signatures = (api.extras or {}).get("signature_count")
        if self._agent_source and isinstance(signatures, int) and signatures > 0:
            verdicts.append(FidelityVerdict.drop(
                message=f"the card's {signatures} JWS signature(s) sign the original bytes and are not "
                "re-written; sign the exported card again",
                severity=LossinessSeverity.WARN,
                target_mapping="signatures → dropped",
            ))
        for plan in self._plans:
            for pointer, reason in plan.synthesized:
                verdicts.append(FidelityVerdict.synth(
                    message=reason, severity=LossinessSeverity.INFO, target_mapping=f"{pointer} → synthesized",
                ))
            for pointer, reason in plan.dropped:
                verdicts.append(FidelityVerdict.drop(
                    message=reason, severity=LossinessSeverity.WARN, target_mapping=f"{pointer} → dropped",
                ))
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """OK (agent source), APPROX (reframed) or DROP (no skill)."""
        skill = self._skill_of.get(operation.key)
        if skill is None:
            if operation.kind in EVENT_OPERATION_KINDS:
                reason = "an event operation has no skill form"
            elif operation.deprecated and not self._agent_source:
                reason = "a deprecated operation gets a skill only with include_deprecated"
            else:
                reason = "no skill is written for it"
            return FidelityVerdict.drop(
                message=f"{self.target_label}: {reason}; {operation.key!r} is dropped",
                target_mapping="operation → no skill",
            )
        if self._agent_source:
            if operation.key in self._a2a_skills:
                return FidelityVerdict.ok(message=f"skill carried to the card as {skill!r}")
            return FidelityVerdict.approx(
                message=f"the agent's skill is written as the A2A skill {skill!r}; what A2A has no field for "
                "(the source protocol's own run modes, metadata and schemas) is not carried",
                target_mapping=f"agent skill → A2A skill {skill}",
            )
        how = "grouped into the tag skill" if self._grouped else "reframed as skill"
        return FidelityVerdict.approx(
            message=f"operation {how} {skill!r}; a skill has no parameters or schemas, so its request and "
            "response are reduced to media types",
            target_mapping=f"operation → skill {skill}",
        )

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """A channel has no skill representation."""
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no channel vocabulary; channel {channel.key!r} is dropped",
            target_mapping="channel → dropped",
        )

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A skill declares media types, not schemas."""
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no schema vocabulary (a skill declares media types only); "
            f"type {type_.key!r} is dropped",
            severity=LossinessSeverity.WARN,
            target_mapping="named type → dropped",
        )

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """A field goes with its type (already dropped), so it adds nothing."""
        return []


# ===========================================================================
# Emitter
# ===========================================================================


class A2aEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an A2A Agent Card (``agent-card.json``)."""

    key = A2A_FORMAT_KEY
    #: Offered greyed out with the reason when the source has neither an agent nor an operation.
    requires_source = ("skill-operation",)
    format = A2A_FORMAT_KEY
    label = "A2A Agent Card"
    description = (
        "Export as an A2A agent-card.json: an agent source keeps its own skills, capabilities, "
        "endpoints and auth; a REST or RPC API is reframed as an agent whose skills are its operations."
    )
    icon = "bot"
    paradigm = ApiParadigm.AGENT
    multi_file = False
    options_model = A2aEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A card names skills and media types; it has no schemas, events or field identity."""
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=False,
            constraints=False,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the A2A Agent Card rules."""
        return A2aFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[A2aEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one Agent Card (one per agent for a multi-agent source).

        Args:
            api: The canonical model to export.
            opts: Per-target options; the defaults write one skill per operation.

        Returns:
            An :class:`~app.emitter.EmitResult` whose files are the cards' JSON text.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            EmitPreconditionError: When a REST or RPC model has no operation to make a skill of.
            ValueError: When a card fails the AgentCard schema.
        """
        options = _coerce_options(opts)
        losses = LossTracker()
        tracker = ProvenanceTracker()
        plans = build_agent_cards(api, options, losses=losses, tracker=tracker)
        files = [
            EmittedFile(
                path=plan.file,
                content=json.dumps(plan.card, indent=2, ensure_ascii=False) + "\n",
                media_type=OUTPUT_MEDIA_TYPE,
            )
            for plan in plans
        ]
        return EmitResult(
            files=files,
            media_type=OUTPUT_MEDIA_TYPE,
            provenance=tracker.records(),
            losses=losses.records(),
        )


def _coerce_options(opts: Optional[Union[A2aEmitOptions, EmitOptions]]) -> A2aEmitOptions:
    """Validate caller-supplied options into :class:`A2aEmitOptions`."""
    if isinstance(opts, A2aEmitOptions):
        return opts
    try:
        return A2aEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid A2A emit options: {exc}") from exc
