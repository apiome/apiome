"""ACP (Agent Communication Protocol) import source — MFI-18.2 (#3975).

The :class:`~app.import_source.ImportSource` adapter for ACP, the REST-native agent protocol
(IBM BeeAI, Linux Foundation) teams adopt instead of — or beside — A2A. It catalogs the agent
metadata an ACP server publishes, next to A2A Agent Cards (:mod:`app.a2a_import_source`) in the
``agent`` paradigm.

* **detect** — an agent manifest (a ``name`` beside ACP's ``input_content_types`` /
  ``output_content_types`` or an ACP ``metadata`` key) or a ``{"agents": [manifest, …]}`` listing;
  see :func:`app.acp_agent_parser.is_acp_document`. An A2A card (it has ``skills``) never matches.
* **parse** — :func:`app.acp_agent_parser.parse_acp` (JSON only).
* **introspect** — live discovery: fetch ``<server>/agents`` through the SSRF-guarded client
  (:mod:`app.acp_agent_discovery`), then parse it.
* **normalize** — :mod:`app.acp_agent_normalizer`: one service per agent, one operation per
  capability, with runtime ``status`` and timestamps left out of the model.
* **fingerprint / diff** — the SPI defaults: a capability added or removed is an ``operation``
  entry; a change to an agent's metadata or content types is a changed ``service`` entry.
* **lint** — the shared engine plus the ``acp`` hygiene pack (:mod:`app.acp_agent_lint`).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import acp_agent_normalizer  # noqa: F401 — self-registers the normalizer
from .acp_agent_discovery import fetch_acp_agents
from .acp_agent_normalizer import FORMAT_KEY
from .acp_agent_parser import (
    AcpDocument,
    AcpParseError,
    is_acp_document,
    is_acp_manifest,
    parse_acp,
)
from .agent_descriptor_fetch import AgentDiscoveryError
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

__all__ = ["AcpImportSource"]

_SHAPE_REASON = "ACP agent manifest (`input_content_types` / ACP `metadata`) or `{agents: [...]}`"


class AcpImportSource(ImportSource, register=True):
    """Adapter for ACP agent manifests and ``GET /agents`` listings (file / url / paste / live)."""

    key = FORMAT_KEY
    label = "ACP Agent Manifest"
    description = (
        "Import ACP (Agent Communication Protocol) agent metadata — an agent manifest or a "
        "server's GET /agents listing, with capabilities, content types, tags and domains — "
        "from a file, a URL, or live from the server."
    )
    icon = "bot"
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
    file_extensions = (".acp.json", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Sniff a document for the ACP manifest or listing shape.

        Args:
            payload: The detection input (text and/or parsed document, plus hints).

        Returns:
            A high-confidence match on the shape, a weaker one on a ``.acp.json`` filename, else
            :data:`~app.import_source.NO_MATCH`.
        """
        document = payload.document
        if document is not None and is_acp_document(document):
            return DetectionResult(confidence=0.93, format=FORMAT_KEY, reason=_SHAPE_REASON)
        text = payload.text
        if text is not None and is_acp_manifest(text):
            return DetectionResult(confidence=0.93, format=FORMAT_KEY, reason=_SHAPE_REASON)
        if (payload.filename or "").lower().endswith(".acp.json"):
            return DetectionResult(
                confidence=0.6, format=FORMAT_KEY, reason="`.acp.json` file extension"
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> AcpDocument:
        """Parse ACP manifest or listing text.

        Args:
            raw: The document text.
            source_label: Optional filename / URL for messages and the title.

        Returns:
            The parsed :class:`~app.acp_agent_parser.AcpDocument`.

        Raises:
            ImportSourceError: Carrying the parser's intake-taxonomy code.
        """
        try:
            return parse_acp(raw, source_label=source_label)
        except AcpParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> AcpDocument:
        """Parse the document at the root of a fileset (siblings are ignored).

        Args:
            fileset: The unpacked set; ``root`` names the manifest or listing.
            source_label: Optional label for messages.

        Returns:
            The parsed document.

        Raises:
            ImportSourceError: When the root member is missing or cannot be parsed.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "ACP fileset is missing its root document", code="INPUT_MALFORMED"
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
    ) -> AcpDocument:
        """Discover a live ACP server's agents and parse them.

        ``endpoint_url`` is the server's base URL (``<base>/agents`` is fetched), its ``/agents``
        listing, or one agent's ``/agents/<name>`` URL.

        Args:
            endpoint_url: The server, listing or agent URL.
            auth_type: Unused (the listing is public); accepted for SPI parity.
            auth_payload: Unused; accepted for SPI parity.
            headers: Unused; accepted for SPI parity.
            fallback_sdl: Unused; accepted for SPI parity with GraphQL.
            source_label: Label for parse diagnostics; defaults to the fetched URL, which also
                gives the model its server.
            client: Optional httpx client (tests).

        Returns:
            The parsed document.

        Raises:
            ImportSourceError: On SSRF rejection, network or HTTP failure, or a body that is not
                an ACP document.
        """
        del auth_type, auth_payload, headers, fallback_sdl  # SPI parity; the listing is public.
        try:
            fetched = fetch_acp_agents(endpoint_url, client=client)
        except AgentDiscoveryError as exc:
            raise ImportSourceError(str(exc)) from exc
        return self.parse(fetched.text, source_label=source_label or fetched.url)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed document onto the canonical agent-paradigm model.

        Args:
            native_ast: The parsed document.
            include_raw: Whether to preserve the document in ``raw``.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed ACP document.
        """
        if not isinstance(native_ast, AcpDocument):
            raise ImportSourceError(
                "ACP source must be an AcpDocument (see app.acp_agent_parser.parse_acp)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
