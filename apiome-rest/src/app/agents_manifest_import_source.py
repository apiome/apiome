"""Agentic-web site manifest import source — MFI-18.3 (#3976).

The :class:`~app.import_source.ImportSource` adapter for the site-level manifests of the agentic
web — ``agents.json``, AWP ``agent.json``, ``agents.txt`` and ``llms.txt`` — beside the A2A and
ACP adapters in the ``agent`` paradigm. A manifest enumerates which agent protocols a site speaks
and where their descriptors live, so a cataloged manifest is also a list of **discovery seeds**
(``extras.discovery_seeds``) that point at the A2A cards, ACP servers and MCP servers to import
next.

* **detect** — :func:`app.agents_manifest_parser.detect_dialect` (shape first), then the
  well-known file names as a weaker hint.
* **parse** — :func:`app.agents_manifest_parser.parse_agents_manifest`.
* **introspect** — live discovery: try ``/agents.json``, ``/.well-known/agent.json``,
  ``/agents.txt`` and ``/llms.txt`` through the SSRF-guarded client
  (:mod:`app.agents_manifest_discovery`).
* **normalize** — :mod:`app.agents_manifest_normalizer`: one service per protocol, one
  operation per endpoint or AWP action; payment layers as metadata.
* **fingerprint / diff** — the SPI defaults: an endpoint added or removed is an ``operation``
  entry.
* **lint** — the shared engine plus the ``agents-manifest`` pack
  (:mod:`app.agents_manifest_lint`): broken and insecure endpoint references, duplicates, and AWP
  actions routed through an undeclared protocol.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import agents_manifest_normalizer  # noqa: F401 — self-registers the normalizer
from .agent_descriptor_fetch import AgentDiscoveryError
from .agents_manifest_discovery import fetch_site_manifest
from .agents_manifest_normalizer import FORMAT_KEY
from .agents_manifest_parser import (
    AgentsManifest,
    AgentsManifestParseError,
    detect_dialect,
    is_agents_json_document,
    is_awp_document,
    parse_agents_manifest,
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

__all__ = ["AgentsManifestImportSource"]

#: Confidence per detected dialect. llms.txt is plain Markdown, so its shape alone is weaker
#: evidence than the JSON dialects' markers — unless the file is *named* llms.txt.
_DIALECT_CONFIDENCE = {"awp": 0.95, "agents-json": 0.92, "agents-txt": 0.9, "llms-txt": 0.75}

#: Well-known manifest file names, for the filename-only fallback.
_MANIFEST_FILENAMES = ("agents.json", "agent.json", "agents.txt", "llms.txt", "llms-full.txt")


class AgentsManifestImportSource(ImportSource, register=True):
    """Adapter for agents.json / agent.json / agents.txt / llms.txt (file / url / paste / live)."""

    key = FORMAT_KEY
    label = "Agentic-web Site Manifest"
    description = (
        "Import a site's agentic-web manifest — agents.json, agent.json (Agent Web Protocol), "
        "agents.txt or llms.txt — cataloging the agent protocols and endpoints it declares and "
        "listing the A2A, ACP and MCP descriptors to discover next."
    )
    icon = "globe"
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
    file_extensions = (".json", ".txt")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Sniff a document for one of the four manifest dialects.

        Args:
            payload: The detection input (text and/or parsed document, plus hints).

        Returns:
            A match on the dialect's shape (llms.txt is raised to 0.9 when the file is named
            ``llms.txt``), a weak one on a well-known file name alone, else
            :data:`~app.import_source.NO_MATCH`.
        """
        name = (payload.filename or payload.url or "").rstrip("/").rsplit("/", 1)[-1].lower()
        dialect: Optional[str] = None
        document = payload.document
        if document is not None:
            if is_awp_document(document):
                dialect = "awp"
            elif is_agents_json_document(document):
                dialect = "agents-json"
        if dialect is None and payload.text is not None:
            dialect = detect_dialect(payload.text, filename=name)
        if dialect is not None:
            confidence = _DIALECT_CONFIDENCE[dialect]
            if dialect == "llms-txt" and name.endswith(("llms.txt", "llms-full.txt")):
                confidence = 0.9
            return DetectionResult(
                confidence=confidence, format=FORMAT_KEY, reason=f"{dialect} site manifest"
            )
        if name.endswith(_MANIFEST_FILENAMES):
            return DetectionResult(
                confidence=0.5, format=FORMAT_KEY, reason=f"`{name}` well-known file name"
            )
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> AgentsManifest:
        """Parse manifest text in any dialect.

        Args:
            raw: The document text.
            source_label: Optional filename / URL; a URL also gives relative references a base.

        Returns:
            The parsed :class:`~app.agents_manifest_parser.AgentsManifest`.

        Raises:
            ImportSourceError: Carrying the parser's intake-taxonomy code.
        """
        try:
            return parse_agents_manifest(raw, source_label=source_label)
        except AgentsManifestParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> AgentsManifest:
        """Parse the manifest at the root of a fileset (siblings are ignored).

        Args:
            fileset: The unpacked set; ``root`` names the manifest.
            source_label: Optional label for messages.

        Returns:
            The parsed manifest.

        Raises:
            ImportSourceError: When the root member is missing or cannot be parsed.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError(
                "Site manifest fileset is missing its root document", code="INPUT_MALFORMED"
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
    ) -> AgentsManifest:
        """Discover a live site's manifest and parse it.

        ``endpoint_url`` is the site (its well-known paths are tried in order) or a direct
        manifest URL.

        Args:
            endpoint_url: The site or manifest URL.
            auth_type: Unused (manifests are public); accepted for SPI parity.
            auth_payload: Unused; accepted for SPI parity.
            headers: Unused; accepted for SPI parity.
            fallback_sdl: Unused; accepted for SPI parity with GraphQL.
            source_label: Unused — the fetched URL labels the manifest, so relative references
                resolve against the site it came from.
            client: Optional httpx client (tests).

        Returns:
            The parsed manifest.

        Raises:
            ImportSourceError: On SSRF rejection, network or HTTP failure, no manifest at any
                well-known path, or a manifest that cannot be parsed.
        """
        del auth_type, auth_payload, headers, fallback_sdl, source_label  # SPI parity.
        try:
            return fetch_site_manifest(endpoint_url, client=client).manifest
        except AgentDiscoveryError as exc:
            raise ImportSourceError(str(exc)) from exc
        except AgentsManifestParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed manifest onto the canonical agent-paradigm model.

        Args:
            native_ast: The parsed manifest.
            include_raw: Whether to preserve the document in ``raw``.

        Returns:
            The canonical model.

        Raises:
            ImportSourceError: When ``native_ast`` is not a parsed site manifest.
        """
        if not isinstance(native_ast, AgentsManifest):
            raise ImportSourceError(
                "Site manifest source must be an AgentsManifest "
                "(see app.agents_manifest_parser.parse_agents_manifest)"
            )
        return self._normalize_via_registry(FORMAT_KEY, native_ast, include_raw=include_raw)
