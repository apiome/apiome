"""A2A Agent Card → canonical model normalizer — MFI-18.1 (#3974).

Maps a parsed :class:`~app.a2a_agent_card_parser.A2aAgentCard` onto a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.AGENT` — the same paradigm the MCP manifest and
LLM-tools adapters produce, so an A2A agent browses, versions and diffs beside them.

The mapping
-----------
* **The agent** is one :class:`~app.canonical_model.Service`, keyed by the agent's name. Its
  ``extras`` carry the card's ``security_schemes`` and card-level ``security_requirements``,
  so an **auth change** between two releases surfaces in
  :func:`app.import_source.canonical_diff` as a changed ``service`` entry.
* **Each skill** is one :class:`~app.canonical_model.Operation` keyed
  ``<agent>.<skill id>``; its ``tags`` become the operation's ``tags`` (the catalog's
  browse / search facet), its description and name carry over, and its effective security
  (its own, else the card's) is recorded twice: ``extras["security_requirements"]`` keeps the
  A2A ``[{scheme: [scopes]}]`` alternatives verbatim, and ``extras["security"]`` lists one
  ``{"scheme", "scopes"}`` record per scheme — the per-operation requirement shape
  :mod:`app.canonical_security` reads for every emitter. A **skill delta**
  between two releases is therefore an added / removed / changed ``operation`` entry.
* **Input / output modes** become a request and a response
  :class:`~app.canonical_model.Message` whose ``content_types`` are the skill's modes, falling
  back to the card's defaults — the effective contract a caller sees.
* **Endpoints** (the primary ``url`` plus ``additionalInterfaces``) become
  :class:`~app.canonical_model.Server` entries whose ``protocol`` is the A2A transport.
* The card's identity: ``identity.name`` is the agent name, ``identity.namespace`` the
  provider organization, ``version`` the agent's own version (the A2A protocol version is
  recorded on ``extras.protocol_version``).

A skill ``id`` repeated in one card would collapse two skills onto one key, so a repeat is
keyed ``<id>~2``, ``<id>~3`` … and marked ``extras.duplicate_of``; the lint pack reports it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .a2a_agent_card_parser import (
    A2aAgentCard,
    A2aSkill,
    dumps_agent_card_for_raw,
)
from .agent_paradigm_keys import unique_keys
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "FORMAT_KEY",
    "A2aAgentCardNormalizer",
    "security_records",
    "security_requirements_as_extras",
]

#: The normalizer / adapter format key.
FORMAT_KEY = "a2a"

#: The response "status" an A2A skill reply is keyed by. A2A has no status codes; a skill
#: answers with a message or a task, so the response message is keyed by that outcome.
_RESPONSE_KEY = "result"


def security_requirements_as_extras(
    requirements: Sequence[Dict[str, Tuple[str, ...]]],
) -> List[Dict[str, List[str]]]:
    """Render parsed security requirements as JSON-ready ``[{scheme: [scopes]}]``.

    Args:
        requirements: Requirements as the parser returns them.

    Returns:
        The same requirements with scope tuples as lists (stable for fingerprinting).
    """
    return [
        {scheme: list(scopes) for scheme, scopes in sorted(requirement.items())}
        for requirement in requirements
    ]


def security_records(requirements: Sequence[Dict[str, List[str]]]) -> List[Dict[str, Any]]:
    """Flatten requirement alternatives into ``{"scheme", "scopes"}`` records.

    This is the per-operation shape :func:`app.canonical_security.operation_security_schemes`
    reads. A scheme named by more than one alternative appears once, with the union of the
    scopes it is asked for, in first-seen order.

    Args:
        requirements: JSON-ready requirements (see :func:`security_requirements_as_extras`).

    Returns:
        One record per distinct scheme.
    """
    scopes: Dict[str, List[str]] = {}
    for requirement in requirements:
        for scheme, wanted in requirement.items():
            bucket = scopes.setdefault(scheme, [])
            bucket.extend(scope for scope in wanted if scope not in bucket)
    return [{"scheme": scheme, "scopes": wanted} for scheme, wanted in scopes.items()]


class A2aAgentCardNormalizer(Normalizer, register=True):
    """Normalize a parsed A2A Agent Card into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.AGENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map the card onto the canonical agent paradigm.

        Args:
            source: The parsed card (:class:`A2aAgentCard`).
            include_raw: Whether to keep the card verbatim in ``raw``.

        Returns:
            The order-normalized canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed card.
        """
        if not isinstance(source, A2aAgentCard):
            raise ValueError(
                "A2A source must be an A2aAgentCard "
                "(see app.a2a_agent_card_parser.parse_a2a_agent_card)"
            )

        service_key = Keys.type(source.name, None)
        card_security = security_requirements_as_extras(source.security)
        streaming = (
            StreamingMode.SERVER
            if source.capabilities.get("streaming") is True
            else StreamingMode.NONE
        )
        operations = [
            self._operation(skill, op_key, duplicate_of, source, card_security, streaming)
            for skill, (op_key, duplicate_of) in zip(
                source.skills,
                unique_keys([Keys.operation_rpc(service_key, skill.id) for skill in source.skills]),
            )
        ]

        service = Service(
            key=service_key,
            name=source.name,
            description=source.description,
            operations=operations,
            extras={
                "security_schemes": source.security_schemes,
                "security_requirements": card_security,
            },
        )

        provider = source.provider
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="a2a",
            identity=ApiIdentity(
                name=source.name,
                namespace=provider.organization if provider else None,
                id=source.url,
            ),
            version=source.version,
            title=source.title,
            description=source.description,
            servers=[
                Server(
                    url=interface.url,
                    name=interface.transport,
                    protocol=interface.transport,
                    description="Primary A2A endpoint" if index == 0 else "Additional A2A interface",
                )
                for index, interface in enumerate(source.interfaces)
            ],
            services=[service],
            raw={FORMAT_KEY: dumps_agent_card_for_raw(source)} if include_raw else None,
            extras={
                "protocol_version": source.protocol_version,
                "preferred_transport": source.preferred_transport,
                "provider": (
                    {"organization": provider.organization, "url": provider.url}
                    if provider
                    else None
                ),
                "documentation_url": source.documentation_url,
                "icon_url": source.icon_url,
                "capabilities": source.capabilities,
                "security_schemes": source.security_schemes,
                "security_requirements": card_security,
                "default_input_modes": list(source.default_input_modes),
                "default_output_modes": list(source.default_output_modes),
                "supports_authenticated_extended_card": source.supports_authenticated_extended_card,
                "signature_count": source.signature_count,
                "skill_count": len(source.skills),
                "skill_tags": sorted({tag for skill in source.skills for tag in skill.tags}),
                "present_keys": list(source.present_keys),
            },
        )
        return normalize_ordering(api)

    @staticmethod
    def _operation(
        skill: A2aSkill,
        op_key: str,
        duplicate_of: Optional[str],
        card: A2aAgentCard,
        card_security: List[Dict[str, List[str]]],
        streaming: StreamingMode,
    ) -> Operation:
        """Build the canonical operation for one skill.

        Args:
            skill: The parsed skill.
            op_key: The operation key already made unique for this skill.
            duplicate_of: The key of the first skill sharing this ``id``, for a repeat.
            card: The whole card (for default modes).
            card_security: The card-level requirements, already JSON-ready.
            streaming: The streaming mode the card's capabilities imply.

        Returns:
            The operation.
        """
        input_modes = list(skill.input_modes or card.default_input_modes)
        output_modes = list(skill.output_modes or card.default_output_modes)
        security = (
            security_requirements_as_extras(skill.security)
            if skill.security is not None
            else card_security
        )
        extras: Dict[str, Any] = {
            "skill_id": skill.id,
            "examples": list(skill.examples),
            "input_modes": input_modes,
            "output_modes": output_modes,
            "security": security_records(security),
            "security_requirements": security,
            "security_source": "skill" if skill.security is not None else "card",
        }
        if duplicate_of is not None:
            extras["duplicate_of"] = duplicate_of
        return Operation(
            key=op_key,
            name=skill.name,
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=streaming,
            description=skill.description,
            tags=list(skill.tags),
            messages=[
                Message(
                    key=Keys.request_message(op_key),
                    role=MessageRole.REQUEST,
                    content_types=input_modes,
                    required=True,
                    description="The message sent to the skill.",
                ),
                Message(
                    key=Keys.response_message(op_key, _RESPONSE_KEY),
                    role=MessageRole.RESPONSE,
                    content_types=output_modes,
                    required=False,
                    status_code=_RESPONSE_KEY,
                    description="The message or task the skill answers with.",
                ),
            ],
            extras=extras,
        )
