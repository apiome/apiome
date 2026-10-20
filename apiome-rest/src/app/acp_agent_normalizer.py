"""ACP agent manifest → canonical model normalizer — MFI-18.2 (#3975).

Maps a parsed :class:`~app.acp_agent_parser.AcpDocument` onto a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.AGENT`, beside the A2A adapter
(:mod:`app.a2a_agent_card_normalizer`), the MCP manifest and the LLM-tools bundle.

The mapping
-----------
* **Each agent** is one :class:`~app.canonical_model.Service`, keyed by its ``name``. Its
  ``extras`` carry the manifest's descriptive metadata — content types, tags, domains, framework,
  languages, license, author, links, dependencies, recommended models — so a change to any of it
  surfaces in :func:`app.import_source.canonical_diff` as a changed ``service`` entry.
* **Each capability** (``metadata.capabilities[]``) is one
  :class:`~app.canonical_model.Operation` keyed ``<agent>.<capability name>``, with the agent's
  tags as operation ``tags`` and its input / output content types on a request and a response
  :class:`~app.canonical_model.Message`. A capability added or removed between two releases is
  therefore an added / removed ``operation`` entry.
* An agent list (``GET /agents``) becomes one model with one service per agent; a single manifest
  becomes a model with one service.
* **Each agent** is also one first-class :class:`~app.canonical_model.AgentDescriptor` on
  ``agents`` (MFI-18.4), with one :class:`~app.canonical_model.AgentSkill` per capability keyed
  like its operation, so capability-level diffs are stable.
* When the document came from a live server (its label is the ``…/agents`` URL), that server is
  the model's :class:`~app.canonical_model.Server`. A file carries no address, so none is invented.

**Not normalized:** ``status`` (average tokens, run time, success rate) and the ``created_at`` /
``updated_at`` stamps. They are runtime facts that change on every deployment; folding them into
the model would make an unchanged contract fingerprint as a new version. They stay in ``raw``.

A repeated agent or capability name is keyed ``~2`` … by :func:`app.agent_paradigm_keys.unique_keys`
and marked ``extras.duplicate_of``; the lint pack reports it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from .acp_agent_parser import AcpAgent, AcpDocument, dumps_acp_for_raw
from .agent_paradigm_keys import unique_keys
from .canonical_model import (
    AgentDescriptor,
    AgentSkill,
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

__all__ = ["FORMAT_KEY", "AcpAgentNormalizer", "acp_server_url"]

#: The normalizer / adapter format key.
FORMAT_KEY = "acp"

#: The response key of a capability's reply (ACP runs answer with output messages, not statuses).
_RESPONSE_KEY = "output"


def acp_server_url(source_label: Optional[str]) -> Optional[str]:
    """Derive the ACP server's base URL from a document's label, when it is a live URL.

    Args:
        source_label: The URL or filename the document came from.

    Returns:
        ``scheme://host[/prefix]`` for a label ending in ``/agents`` or ``/agents/<name>``, else
        ``None`` (a file, or a URL that is not an ACP listing).
    """
    if not source_label:
        return None
    parts = urlsplit(source_label)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    segments = parts.path.rstrip("/").split("/")
    if segments and segments[-1] == "agents":
        prefix = segments[:-1]
    elif len(segments) >= 2 and segments[-2] == "agents":
        prefix = segments[:-2]
    else:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc, "/".join(prefix), "", ""))


class AcpAgentNormalizer(Normalizer, register=True):
    """Normalize a parsed ACP document into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.AGENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map the document onto the canonical agent paradigm.

        Args:
            source: The parsed document (:class:`AcpDocument`).
            include_raw: Whether to keep the document verbatim in ``raw``.

        Returns:
            The order-normalized canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed ACP document.
        """
        if not isinstance(source, AcpDocument):
            raise ValueError(
                "ACP source must be an AcpDocument (see app.acp_agent_parser.parse_acp)"
            )

        agent_keys = unique_keys([Keys.type(agent.name, None) for agent in source.agents])
        services = [
            self._service(agent, service_key, duplicate_of)
            for agent, (service_key, duplicate_of) in zip(source.agents, agent_keys)
        ]
        server_url = acp_server_url(source.source_label)
        single = source.agents[0] if len(source.agents) == 1 else None

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="acp",
            identity=ApiIdentity(name=source.title),
            title=source.title,
            description=single.description if single else None,
            servers=[
                Server(url=server_url, name="ACP server", protocol="acp")
            ]
            if server_url
            else [],
            services=services,
            agents=[
                self._descriptor(agent, service_key, duplicate_of)
                for agent, (service_key, duplicate_of) in zip(source.agents, agent_keys)
            ],
            raw={FORMAT_KEY: dumps_acp_for_raw(source)} if include_raw else None,
            extras={
                "shape": source.shape,
                "agent_count": len(source.agents),
                "capability_count": sum(len(agent.capabilities) for agent in source.agents),
                "agent_tags": sorted({tag for agent in source.agents for tag in agent.tags}),
                "domains": sorted({d for agent in source.agents for d in agent.domains}),
            },
        )
        return normalize_ordering(api)

    def _service(self, agent: AcpAgent, service_key: str, duplicate_of: Optional[str]) -> Service:
        """Build the canonical service for one agent.

        Args:
            agent: The parsed agent.
            service_key: The agent's unique service key.
            duplicate_of: The first agent's key when this one repeats a name.

        Returns:
            The service, with one operation per capability.
        """
        extras: Dict[str, Any] = {
            "agent_name": agent.name,
            "input_content_types": list(agent.input_content_types),
            "output_content_types": list(agent.output_content_types),
            "content_types_declared": agent.content_types_declared,
            "tags": list(agent.tags),
            "domains": list(agent.domains),
            "framework": agent.framework,
            "programming_language": agent.programming_language,
            "natural_languages": list(agent.natural_languages),
            "license": agent.license,
            "documentation": agent.documentation,
            "author": agent.author,
            "contributors": list(agent.contributors),
            "links": list(agent.links),
            "dependencies": list(agent.dependencies),
            "recommended_models": list(agent.recommended_models),
        }
        if duplicate_of is not None:
            extras["duplicate_of"] = duplicate_of
        return Service(
            key=service_key,
            name=agent.name,
            description=agent.description,
            operations=self._operations(agent, service_key),
            extras=extras,
        )

    @staticmethod
    def _descriptor(
        agent: AcpAgent, service_key: str, duplicate_of: Optional[str]
    ) -> AgentDescriptor:
        """Build the first-class agent descriptor for one agent (MFI-18.4).

        ACP declares content types per agent, not per capability, so they are the
        descriptor's default modes and every skill inherits them (empty skill modes). ACP has
        no capability flags or security schemes; the agent's tags and domains ride on the
        descriptor's ``extras``.

        Args:
            agent: The parsed agent.
            service_key: The agent's unique service key (also the descriptor key).
            duplicate_of: The first agent's key when this one repeats a name.

        Returns:
            The descriptor, one skill per capability pointing at its operation.
        """
        keyed = unique_keys([Keys.operation_rpc(service_key, c.name) for c in agent.capabilities])
        extras: Dict[str, Any] = {"tags": list(agent.tags), "domains": list(agent.domains)}
        if duplicate_of is not None:
            extras["duplicate_of"] = duplicate_of
        return AgentDescriptor(
            key=service_key,
            name=agent.name,
            description=agent.description,
            protocol="acp",
            default_input_modes=list(agent.input_content_types),
            default_output_modes=list(agent.output_content_types),
            skills=[
                AgentSkill(
                    key=key,
                    id=capability.name,
                    name=capability.name,
                    description=capability.description,
                    operation_ref=key,
                    extras={"duplicate_of": first} if first else {},
                )
                for capability, (key, first) in zip(agent.capabilities, keyed)
            ],
            service_ref=service_key,
            extras=extras,
        )

    @staticmethod
    def _operations(agent: AcpAgent, service_key: str) -> List[Operation]:
        """Build one operation per declared capability.

        Args:
            agent: The parsed agent.
            service_key: The agent's service key.

        Returns:
            The operations, in source order.
        """
        operations: List[Operation] = []
        keyed = unique_keys([Keys.operation_rpc(service_key, c.name) for c in agent.capabilities])
        for capability, (op_key, duplicate_of) in zip(agent.capabilities, keyed):
            extras: Dict[str, Any] = {"capability": capability.name}
            if duplicate_of is not None:
                extras["duplicate_of"] = duplicate_of
            operations.append(
                Operation(
                    key=op_key,
                    name=capability.name,
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    description=capability.description,
                    tags=list(agent.tags),
                    messages=[
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            content_types=list(agent.input_content_types),
                            required=True,
                            description="The input messages of a run.",
                        ),
                        Message(
                            key=Keys.response_message(op_key, _RESPONSE_KEY),
                            role=MessageRole.RESPONSE,
                            content_types=list(agent.output_content_types),
                            required=False,
                            status_code=_RESPONSE_KEY,
                            description="The output messages of a run.",
                        ),
                    ],
                    extras=extras,
                )
            )
        return operations
