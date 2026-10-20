"""A2A (Agent2Agent) Agent Card parser — MFI-18.1 (#3974).

An A2A agent describes itself with an **Agent Card**: a JSON document served at
``/.well-known/agent-card.json`` (``/.well-known/agent.json`` before A2A 0.3). It names the
agent (``name`` / ``description`` / ``version`` / ``provider``), says where to reach it
(``url`` + ``preferredTransport``, plus ``additionalInterfaces``), what the transport supports
(``capabilities``: streaming, push notifications, extensions), how to authenticate
(``securitySchemes`` + ``security``), and — the part a catalog cares most about — the
**skills** it offers, each with an ``id``, ``name``, ``description``, ``tags``, ``examples``
and input / output media types.

This module turns that document into a typed :class:`A2aAgentCard`. It decides only what the
document *says*; mapping it onto the canonical agent paradigm is
:mod:`app.a2a_agent_card_normalizer`, and judging its hygiene is :mod:`app.a2a_agent_card_lint`.

What the parser insists on
--------------------------
A card must be a JSON object with a non-empty ``name`` and a ``skills`` array, and every skill
must carry a non-empty ``id`` and ``name`` (the spec requires both; without an ``id`` a skill
has no identity to version or diff by). Everything else the spec calls required — ``url``,
``version``, ``capabilities``, the default modes — is *read when present* and reported by lint
when absent, because a card missing its ``version`` is still worth cataloguing and the lint
report is where a reader learns what to fix.

JSON only, deliberately
-----------------------
An Agent Card is JSON by specification, and the parser does not fall back to YAML, for the
reason the MCP manifest parser gives (:mod:`app.mcp_manifest_parser`): YAML accepts a trailing
comma no A2A client would. YAML is parsed on the failure path only to tell a different format
(an OpenAPI file handed to the wrong importer) apart from broken JSON, and the shared
:func:`app.mcp_manifest_parser.is_unclosed_json` scan separates truncated from malformed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .mcp_manifest_parser import is_unclosed_json

__all__ = [
    "A2aAgentCard",
    "A2aAgentCardParseError",
    "A2aInterface",
    "A2aProvider",
    "A2aSkill",
    "WELL_KNOWN_AGENT_CARD_PATH",
    "LEGACY_WELL_KNOWN_AGENT_CARD_PATH",
    "dumps_agent_card_for_raw",
    "is_a2a_agent_card",
    "is_a2a_agent_card_document",
    "parse_a2a_agent_card",
]

#: The well-known URI an A2A agent publishes its card at (A2A 0.3+, RFC 8615).
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"

#: The well-known URI used before A2A 0.3; still served by many agents.
LEGACY_WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent.json"

#: Root keys that prove the document is a *different* API description, so the failure reads
#: ``FORMAT_MISMATCH`` rather than "broken Agent Card".
_FOREIGN_FORMAT_MARKERS: Tuple[str, ...] = (
    "openapi",
    "swagger",
    "asyncapi",
    "arazzo",
    "openrpc",
    "discoveryVersion",
    "mcpVersion",
)

#: Card-level keys only an Agent Card carries. Detection needs ``name`` + ``skills`` *and* at
#: least one of these, so a random ``{name, skills}`` object (a résumé, a game save) is not
#: mistaken for an agent.
_CARD_MARKERS: Tuple[str, ...] = (
    "protocolVersion",
    "preferredTransport",
    "defaultInputModes",
    "defaultOutputModes",
    "capabilities",
    "securitySchemes",
    "additionalInterfaces",
    "supportsAuthenticatedExtendedCard",
)


class A2aAgentCardParseError(ValueError):
    """Raised when an Agent Card cannot be parsed.

    Args:
        message: Human-readable description of the failure.
        code: Stable intake-taxonomy code (see :mod:`app.intake_error_taxonomy`).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class A2aProvider:
    """The organization that operates the agent (``provider``).

    Attributes:
        organization: The provider's name.
        url: The provider's website, when given.
    """

    organization: Optional[str]
    url: Optional[str]


@dataclass(frozen=True)
class A2aInterface:
    """One endpoint the agent can be reached at.

    Attributes:
        url: The endpoint URL.
        transport: The A2A transport binding (``JSONRPC`` / ``GRPC`` / ``HTTP+JSON``), when
            given.
    """

    url: str
    transport: Optional[str]


@dataclass(frozen=True)
class A2aSkill:
    """One skill the agent offers (an entry of ``skills``).

    Attributes:
        id: The skill's stable identifier — the key it is versioned and diffed by.
        name: Human-readable skill name.
        description: What the skill does, when given.
        tags: Keywords for discovery (deduplicated, source order kept).
        examples: Example prompts the skill handles.
        input_modes: Media types the skill accepts; empty means "the card's defaults".
        output_modes: Media types the skill produces; empty means "the card's defaults".
        security: The skill's own security requirements (``[{scheme: [scopes]}]``), or
            ``None`` when it inherits the card's.
        raw: The skill entry verbatim.
    """

    id: str
    name: str
    description: Optional[str]
    tags: Tuple[str, ...]
    examples: Tuple[str, ...]
    input_modes: Tuple[str, ...]
    output_modes: Tuple[str, ...]
    security: Optional[Tuple[Dict[str, Tuple[str, ...]], ...]]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class A2aAgentCard:
    """A parsed A2A Agent Card, ready for normalization.

    Attributes:
        name: The agent's name.
        description: The agent's description, when given.
        url: The agent's primary endpoint, when given.
        version: The agent's own version string (not the protocol's), when given.
        protocol_version: The A2A protocol version the card declares, when given.
        preferred_transport: The transport of the primary ``url``, when given.
        provider: The operating organization, when given.
        documentation_url: Link to human documentation, when given.
        icon_url: Link to the agent's icon, when given.
        interfaces: Every endpoint — the primary ``url`` first, then
            ``additionalInterfaces`` — deduplicated by ``(url, transport)``.
        capabilities: The ``capabilities`` object verbatim (empty when absent).
        security_schemes: Scheme name → scheme object, verbatim.
        security: Card-level security requirements (``[{scheme: [scopes]}]``).
        default_input_modes: Media types every skill accepts unless it says otherwise.
        default_output_modes: Media types every skill produces unless it says otherwise.
        supports_authenticated_extended_card: Whether an extended card is served to
            authenticated callers.
        signature_count: How many JWS ``signatures`` the card carries.
        skills: The agent's skills, in source order.
        title: Display title (the agent's name).
        raw: The card text verbatim.
        source_label: Filename / URL the card came from, when known.
        present_keys: The top-level keys the card actually carried, so lint can tell an
            absent field from an empty one.
    """

    name: str
    description: Optional[str]
    url: Optional[str]
    version: Optional[str]
    protocol_version: Optional[str]
    preferred_transport: Optional[str]
    provider: Optional[A2aProvider]
    documentation_url: Optional[str]
    icon_url: Optional[str]
    interfaces: Tuple[A2aInterface, ...]
    capabilities: Dict[str, Any]
    security_schemes: Dict[str, Dict[str, Any]]
    security: Tuple[Dict[str, Tuple[str, ...]], ...]
    default_input_modes: Tuple[str, ...]
    default_output_modes: Tuple[str, ...]
    supports_authenticated_extended_card: bool
    signature_count: int
    skills: Tuple[A2aSkill, ...]
    title: str
    raw: str
    source_label: Optional[str] = None
    present_keys: Tuple[str, ...] = field(default_factory=tuple)


# ===========================================================================
# Detection
# ===========================================================================


def is_a2a_agent_card_document(document: Any) -> bool:
    """Return ``True`` when a parsed value looks like an A2A Agent Card.

    The test is a ``name`` string, a ``skills`` array whose entries are objects with an
    ``id``, and at least one card-only marker (:data:`_CARD_MARKERS`). It declines anything
    carrying another format's root marker, so an OpenAPI or MCP document never matches.

    Args:
        document: Any parsed JSON/YAML value.

    Returns:
        Whether the value is shaped like an Agent Card.
    """
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        return False
    if not isinstance(document.get("name"), str):
        return False
    skills = document.get("skills")
    if not isinstance(skills, list):
        return False
    if any(not isinstance(skill, Mapping) or "id" not in skill for skill in skills):
        return False
    return any(marker in document for marker in _CARD_MARKERS)


def is_a2a_agent_card(content: str) -> bool:
    """Return ``True`` when ``content`` is JSON text shaped like an A2A Agent Card.

    Cheap and never raises: anything that is not decodable JSON is simply "not a card".

    Args:
        content: Raw document text.

    Returns:
        Whether the text is an Agent Card.
    """
    if not content or not isinstance(content, str) or not content.strip():
        return False
    if "\x00" in content[:256]:
        return False
    try:
        document = json.loads(content)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return False
    return is_a2a_agent_card_document(document)


# ===========================================================================
# Parsing
# ===========================================================================


def parse_a2a_agent_card(content: str, *, source_label: Optional[str] = None) -> A2aAgentCard:
    """Parse A2A Agent Card JSON into an :class:`A2aAgentCard`.

    Args:
        content: The raw card text (JSON).
        source_label: Optional filename / URL used in error messages.

    Returns:
        The parsed card.

    Raises:
        A2aAgentCardParseError: With a taxonomy ``code`` — ``INPUT_EMPTY`` for blank input,
            ``INPUT_ENCODING_INVALID`` for non-UTF-8 text, ``INPUT_TRUNCATED`` for a card
            that stops mid-value, ``INPUT_MALFORMED`` for broken JSON, ``FORMAT_MISMATCH``
            for a different format, and ``INPUT_SEMANTIC_INVALID`` for well-formed JSON whose
            ``name`` or skills are unusable.
    """
    where = f" ({source_label})" if source_label else ""
    document = _load_card(content, where=where, source_label=source_label)

    name = _optional_str(document.get("name"))
    if name is None:
        raise A2aAgentCardParseError(
            f"Agent Card{where} has no `name`", code="INPUT_SEMANTIC_INVALID"
        )

    skills = _parse_skills(document.get("skills"), where=where)
    url = _optional_str(document.get("url"))
    preferred_transport = _optional_str(document.get("preferredTransport"))

    return A2aAgentCard(
        name=name,
        description=_optional_str(document.get("description")),
        url=url,
        version=_optional_scalar_str(document.get("version")),
        protocol_version=_optional_scalar_str(document.get("protocolVersion")),
        preferred_transport=preferred_transport,
        provider=_parse_provider(document.get("provider")),
        documentation_url=_optional_str(document.get("documentationUrl")),
        icon_url=_optional_str(document.get("iconUrl")),
        interfaces=_parse_interfaces(url, preferred_transport, document.get("additionalInterfaces")),
        capabilities=_as_dict(document.get("capabilities")),
        security_schemes=_parse_security_schemes(document.get("securitySchemes")),
        security=_parse_security(document.get("security")) or (),
        default_input_modes=_str_tuple(document.get("defaultInputModes")),
        default_output_modes=_str_tuple(document.get("defaultOutputModes")),
        supports_authenticated_extended_card=document.get("supportsAuthenticatedExtendedCard")
        is True,
        signature_count=len(document["signatures"])
        if isinstance(document.get("signatures"), list)
        else 0,
        skills=skills,
        title=name,
        raw=content,
        source_label=source_label,
        present_keys=tuple(sorted(str(key) for key in document)),
    )


def dumps_agent_card_for_raw(card: A2aAgentCard) -> Any:
    """Return the card as a JSON value for the canonical model's ``raw`` fidelity bag.

    Args:
        card: The parsed card.

    Returns:
        The decoded card object (its text was validated as JSON when it was parsed).
    """
    return json.loads(card.raw)


# ===========================================================================
# Internals
# ===========================================================================


def _load_card(content: str, *, where: str, source_label: Optional[str]) -> Mapping[str, Any]:
    """Decode card text to a JSON object, classifying every way that can fail.

    Args:
        content: The raw card text.
        where: Pre-formatted ``" (label)"`` suffix for messages.
        source_label: Label passed to the intake resource guards.

    Returns:
        The parsed top-level object.

    Raises:
        A2aAgentCardParseError: With the taxonomy code for the specific failure.
    """
    if not content or not content.strip():
        raise A2aAgentCardParseError(f"Agent Card is empty{where}", code="INPUT_EMPTY")
    if "\x00" in content or "�" in content[:64]:
        raise A2aAgentCardParseError(
            f"Agent Card is not UTF-8 text{where} — it looks like UTF-16 or binary content",
            code="INPUT_ENCODING_INVALID",
        )

    try:
        guard_document_text(content, source_label=source_label)
    except IntakeLimitError as exc:
        raise A2aAgentCardParseError(str(exc), code=getattr(exc, "code", None)) from exc

    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise _classify_json_failure(content, exc, where=where) from exc

    try:
        guard_parsed_document(document, source_label=source_label)
    except IntakeLimitError as exc:
        raise A2aAgentCardParseError(str(exc), code=getattr(exc, "code", None)) from exc

    if not isinstance(document, Mapping):
        raise A2aAgentCardParseError(
            f"Agent Card must be a JSON object{where}, not a {type(document).__name__}",
            code="FORMAT_MISMATCH",
        )
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        raise A2aAgentCardParseError(
            f"Content looks like another API description (OpenAPI/AsyncAPI/MCP/…){where}, "
            "not an A2A Agent Card",
            code="FORMAT_MISMATCH",
        )
    if "skills" not in document:
        raise A2aAgentCardParseError(
            f"Content is not an A2A Agent Card{where}: it has no `skills` array",
            code="FORMAT_MISMATCH",
        )
    return document


def _classify_json_failure(
    content: str, exc: json.JSONDecodeError, *, where: str
) -> A2aAgentCardParseError:
    """Turn a JSON decode failure into the right taxonomy code.

    In precedence order: text that parses as YAML into a mapping that has no ``skills`` key, or
    carries another format's root marker, is a different format (``FORMAT_MISMATCH``) — the
    test is deliberately looser than detection, so a small broken card is still reported as a
    broken card; text that leaves a string or bracket open is
    ``INPUT_TRUNCATED``; anything else (a trailing comma, a bare word) is ``INPUT_MALFORMED``.

    Args:
        content: The text that failed to decode.
        exc: The decode error.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The error to raise.
    """
    try:
        loose = yaml.safe_load(content)
    except Exception:  # noqa: BLE001 - a YAML failure only means "no second opinion"
        loose = None
    if isinstance(loose, Mapping) and (
        "skills" not in loose or any(marker in loose for marker in _FOREIGN_FORMAT_MARKERS)
    ):
        return A2aAgentCardParseError(
            f"Content is not an A2A Agent Card{where}: {exc.msg}", code="FORMAT_MISMATCH"
        )
    if is_unclosed_json(content):
        return A2aAgentCardParseError(
            f"Agent Card is truncated{where}: {exc.msg} at line {exc.lineno}",
            code="INPUT_TRUNCATED",
        )
    return A2aAgentCardParseError(
        f"Agent Card is not valid JSON{where}: {exc.msg} at line {exc.lineno} "
        f"column {exc.colno}",
        code="INPUT_MALFORMED",
    )


def _parse_skills(value: Any, *, where: str) -> Tuple[A2aSkill, ...]:
    """Parse the ``skills`` array.

    Args:
        value: The raw ``skills`` value.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The skills in source order.

    Raises:
        A2aAgentCardParseError: ``INPUT_SEMANTIC_INVALID`` when ``skills`` is not an array, or
            an entry is not an object or lacks a non-empty ``id`` / ``name``.
    """
    if not isinstance(value, list):
        raise A2aAgentCardParseError(
            f"Agent Card{where} `skills` must be an array", code="INPUT_SEMANTIC_INVALID"
        )
    skills: List[A2aSkill] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise A2aAgentCardParseError(
                f"Agent Card{where} skill at index {index} is not an object",
                code="INPUT_SEMANTIC_INVALID",
            )
        skill_id = _optional_scalar_str(entry.get("id"))
        name = _optional_str(entry.get("name"))
        if skill_id is None or name is None:
            missing = "`id`" if skill_id is None else "`name`"
            raise A2aAgentCardParseError(
                f"Agent Card{where} skill at index {index} is missing a non-empty {missing}",
                code="INPUT_SEMANTIC_INVALID",
            )
        skills.append(
            A2aSkill(
                id=skill_id,
                name=name,
                description=_optional_str(entry.get("description")),
                tags=_str_tuple(entry.get("tags")),
                examples=_str_tuple(entry.get("examples")),
                input_modes=_str_tuple(entry.get("inputModes")),
                output_modes=_str_tuple(entry.get("outputModes")),
                security=_parse_security(entry.get("security")),
                raw=dict(entry),
            )
        )
    return tuple(skills)


def _parse_provider(value: Any) -> Optional[A2aProvider]:
    """Parse ``provider``; ``None`` when absent or empty."""
    if not isinstance(value, Mapping):
        return None
    organization = _optional_str(value.get("organization"))
    url = _optional_str(value.get("url"))
    if organization is None and url is None:
        return None
    return A2aProvider(organization=organization, url=url)


def _parse_interfaces(
    url: Optional[str], preferred_transport: Optional[str], additional: Any
) -> Tuple[A2aInterface, ...]:
    """Collect the primary endpoint and ``additionalInterfaces``, deduplicated.

    Args:
        url: The card's primary ``url``.
        preferred_transport: The primary endpoint's transport.
        additional: The raw ``additionalInterfaces`` value.

    Returns:
        The primary interface first (when ``url`` is set), then each additional one not
        already listed.
    """
    out: List[A2aInterface] = []
    seen = set()
    candidates: List[Tuple[Optional[str], Optional[str]]] = [(url, preferred_transport)]
    if isinstance(additional, list):
        for entry in additional:
            if isinstance(entry, Mapping):
                candidates.append(
                    (_optional_str(entry.get("url")), _optional_str(entry.get("transport")))
                )
    for candidate_url, transport in candidates:
        if candidate_url is None or (candidate_url, transport) in seen:
            continue
        seen.add((candidate_url, transport))
        out.append(A2aInterface(url=candidate_url, transport=transport))
    return tuple(out)


def _parse_security_schemes(value: Any) -> Dict[str, Dict[str, Any]]:
    """Return scheme name → scheme object for every object-valued entry, sorted by name."""
    if not isinstance(value, Mapping):
        return {}
    return {
        str(name): dict(scheme)
        for name, scheme in sorted(value.items(), key=lambda item: str(item[0]))
        if isinstance(scheme, Mapping)
    }


def _parse_security(value: Any) -> Optional[Tuple[Dict[str, Tuple[str, ...]], ...]]:
    """Parse a security-requirement list (``[{scheme: [scopes]}]``).

    Args:
        value: The raw ``security`` value.

    Returns:
        One ``{scheme: scopes}`` mapping per requirement object, or ``None`` when the value is
        absent or not a list (so a skill can be told apart from one that inherits).
    """
    if not isinstance(value, list):
        return None
    requirements: List[Dict[str, Tuple[str, ...]]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        requirements.append(
            {str(scheme): _str_tuple(scopes) for scheme, scopes in sorted(entry.items())}
        )
    return tuple(requirements)


def _as_dict(value: Any) -> Dict[str, Any]:
    """Return ``value`` as a plain dict, or ``{}`` when it is not a mapping."""
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> Optional[str]:
    """Return a stripped non-empty string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_scalar_str(value: Any) -> Optional[str]:
    """Like :func:`_optional_str`, but also accepts a number (``"version": 1``)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return _optional_str(value)


def _str_tuple(value: Any) -> Tuple[str, ...]:
    """Return the non-empty strings of a list, stripped and deduplicated in order."""
    if not isinstance(value, list):
        return ()
    out: List[str] = []
    for item in value:
        text = _optional_str(item)
        if text is not None and text not in out:
            out.append(text)
    return tuple(out)
