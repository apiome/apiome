"""Shared adapter base for the reverse-proxy route sources — FMT-7.5 (#5459).

Traefik, nginx, HAProxy and Consul adapters differ only in detection and in which parser
they call; everything else — translating parser errors into import errors, the fileset
seam, normalizing through the shared gateway normalizer, and publishing the parser's own
capability vocabulary — is the same, and lives on :class:`ProxyRouteImportSource` once.
The Tyk adapter builds on it too and overrides the OpenAPI-backed half of its own form.
"""

from __future__ import annotations

from typing import Any, ClassVar, Mapping, Optional

from . import gateway_config_normalizer  # noqa: F401 — self-registers the normalizers
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .gateway_config_model import GatewayConfigDocument, GatewayConfigParseError
from .import_source import ImportSource, ImportSourceError, InputKind
from .payload_analysis import AnalyzerCapabilities

__all__ = ["ProxyRouteImportSource"]


class ProxyRouteImportSource(ImportSource):
    """Base for the FMT-7.5 adapters (not registered itself).

    Subclasses set the usual descriptor attributes, :attr:`capabilities`, and implement
    :meth:`detect`, :meth:`_parse_text` and :meth:`_parse_members`.
    """

    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False

    #: The parser's declared construct vocabulary (read / declared), for the registry.
    capabilities: ClassVar[AnalyzerCapabilities] = AnalyzerCapabilities()

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        """Parse one text (subclass hook)."""
        raise NotImplementedError

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        """Parse a fileset's members (subclass hook)."""
        raise NotImplementedError

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        try:
            return self._parse_text(raw, source_label=source_label)
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Any:
        if not fileset.members:
            raise ImportSourceError(f"{self.label} fileset has no members", code="INPUT_MALFORMED")
        try:
            return self._parse_members(fileset.members, root=fileset.root, source_label=source_label or fileset.root)
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, GatewayConfigDocument):
            raise ImportSourceError(f"{self.label} source must be a GatewayConfigDocument")
        return self._normalize_via_registry(self.key, native_ast, include_raw=include_raw)

    def analysis_capabilities(self) -> AnalyzerCapabilities:
        """The directives / constructs the parser reads and the ones it declares (FMT-7.5)."""
        return self.capabilities
