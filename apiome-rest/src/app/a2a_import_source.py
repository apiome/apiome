"""A2A (Agent2Agent) Agent Card import source — MFI-18.1 (#3974).

The :class:`~app.import_source.ImportSource` adapter that makes A2A Agent Cards importable
into the catalog. MCP covers *agent → tool*; A2A covers *agent → agent*, and every A2A agent
publishes one descriptor — its Agent Card — at ``/.well-known/agent-card.json``.

* **detect** — a ``name`` + ``skills[].id`` object carrying a card-only marker
  (``protocolVersion``, ``capabilities``, ``defaultInputModes`` …); see
  :func:`app.a2a_agent_card_parser.is_a2a_agent_card_document`. The marker set cannot collide
  with the MCP manifest adapter (which keys on ``mcpVersion`` / ``tools``) or the LLM-tools
  adapter (a tool array has no ``skills``). A ``agent-card.json`` / ``agent.json`` filename is a
  weaker hint on its own.
* **parse** — :func:`app.a2a_agent_card_parser.parse_a2a_agent_card` (JSON only).
* **introspect** — the live-discovery seam: fetch the card from an agent's well-known URI
  through the SSRF-guarded client (:mod:`app.a2a_agent_card_discovery`), then parse it.
* **normalize** — :mod:`app.a2a_agent_card_normalizer` onto the ``agent`` paradigm: one service
  per agent, one operation per skill, skill tags as operation tags.
* **fingerprint / diff** — the SPI defaults over that model: a skill added, removed or edited is
  an ``operation`` entry, and an auth change (``securitySchemes`` / ``security``) is a changed
  ``service`` entry.
* **lint** — the shared engine plus the ``a2a`` capability / auth hygiene pack
  (:mod:`app.a2a_agent_card_lint`).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import a2a_agent_card_normalizer  # noqa: F401 — self-registers the normalizer
from .a2a_agent_card_discovery import A2aDiscoveryError, fetch_agent_card
from .a2a_agent_card_normalizer import FORMAT_KEY
from .a2a_agent_card_parser import (
    A2aAgentCard,
    A2aAgentCardParseError,
    is_a2a_agent_card,
    is_a2a_agent_card_document,
    parse_a2a_agent_card,
)
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["A2aImportSource"]

_SHAPE_REASON = "`name` + `skills[].id` with an Agent Card marker (`capabilities`, modes, …)"


class A2aImportSource(ImportSource, register=True):
    """Adapter for A2A Agent Cards (file / url / paste / fileset / live well-known fetch)."""

    key = FORMAT_KEY
    label = "A2A Agent Card"
    description = (
        "Import an A2A (Agent2Agent) Agent Card — the agent's skills, tags, input / output "
        "modes, capabilities and security schemes — from a file, a URL, or live from the "
        "agent's /.well-known/agent-card.json."
    )
    icon = "bot-message-square"
    paradigm = ApiParadigm.AGENT
    input_kinds = (
        InputKind.FILE,
        InputKind.URL,
        InputKind.PASTE,
        InputKind.DISCOVERY,
        InputKind.FILESET,
    )
    supports_live_discovery = True
    formats = (FORMAT_KEY,)
    file_extensions = (".agent-card.json", ".json")
    #: Registry crawl (MFI-18.5, :mod:`app.a2a_registry_crawl`).
    registry_crawl = "a2a-registry"

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Sniff a document for the Agent Card shape.

        Args:
            payload: The detection input (text and/or parsed document, plus hints).

        Returns:
            A high-confidence match on the card shape, a weaker one on a conventional
            ``agent-card.json`` / ``agent.json`` filename, else
            :data:`~app.import_source.NO_MATCH`.
        """
        document = payload.document
        if document is not None and is_a2a_agent_card_document(document):
            return DetectionResult(confidence=0.95, format=FORMAT_KEY, reason=_SHAPE_REASON)

        text = payload.text
        if text is not None and is_a2a_agent_card(text):
            return DetectionResult(confidence=0.95, format=FORMAT_KEY, reason=_SHAPE_REASON)

        filename = (payload.filename or "").lower().rsplit("/", 1)[-1]
        if filename.endswith("agent-card.json") or filename == "agent.json":
            return DetectionResult(
                confidence=0.6,
                format=FORMAT_KEY,
                reason="`agent-card.json` / `agent.json` well-known filename",
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> A2aAgentCard:
        """Parse Agent Card text.

        Args:
            raw: The card text.
            source_label: Optional filename / URL for error messages.

        Returns:
            The parsed :class:`~app.a2a_agent_card_parser.A2aAgentCard`.

        Raises:
            ImportSourceError: Carrying the parser's intake-taxonomy code.
        """
        try:
            return parse_a2a_agent_card(raw, source_label=source_label)
        except A2aAgentCardParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> A2aAgentCard:
        """Parse the card at the root of a fileset (an archive or git selection).

        A card is self-contained, so sibling members are ignored.

        Args:
            fileset: The unpacked set; ``root`` names the card.
            source_label: Optional label for error messages.

        Returns:
            The parsed card.

        Raises:
            ImportSourceError: When the set has no root member or the card cannot be parsed.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "A2A Agent Card fileset is missing its root document", code="INPUT_MALFORMED"
            )
        return self.parse(fileset.members[root], source_label=root or source_label)

    def introspect(
        self,
        endpoint_url: str,
        *,
        auth_type: Optional[str] = None,
        auth_payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        fallback_sdl: Optional[str] = None,
        source_label: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> A2aAgentCard:
        """Discover a live agent's card from its well-known URI and parse it.

        ``endpoint_url`` may be the agent's origin (``https://agent.example.com``) — the
        adapter then tries ``/.well-known/agent-card.json`` and the legacy
        ``/.well-known/agent.json`` — or a direct card URL ending in ``.json``.

        Args:
            endpoint_url: The agent origin or card URL.
            auth_type: Unused (the public card is unauthenticated); accepted for SPI parity.
            auth_payload: Unused; accepted for SPI parity.
            headers: Unused; accepted for SPI parity.
            fallback_sdl: Unused; accepted for SPI parity with GraphQL.
            source_label: Label for parse diagnostics; defaults to the URL the card came from.
            client: Optional httpx client (tests).

        Returns:
            The parsed card.

        Raises:
            ImportSourceError: On SSRF rejection, network failure, no card at either
                well-known path, or a body that is not an Agent Card.
        """
        del auth_type, auth_payload, headers, fallback_sdl  # SPI parity; the card is public.
        try:
            fetched = fetch_agent_card(endpoint_url, client=client)
        except A2aDiscoveryError as exc:
            raise ImportSourceError(str(exc)) from exc
        return self.parse(fetched.text, source_label=source_label or fetched.url)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed card onto the canonical agent-paradigm model.

        Args:
            native_ast: The parsed card.
            include_raw: Whether to preserve the card in ``raw``.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed card.
        """
        if not isinstance(native_ast, A2aAgentCard):
            raise ImportSourceError(
                "A2A source must be an A2aAgentCard "
                "(see app.a2a_agent_card_parser.parse_a2a_agent_card)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
