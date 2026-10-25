"""Tyk API definition import source — FMT-7.5 (#5459).

The :class:`~app.import_source.ImportSource` adapter for Tyk's two API-definition forms:

* **Classic** JSON (``api_id`` + ``proxy.listen_path``), optionally with the policies file
  that grants access to it, is read by :func:`app.tyk_parser.parse_tyk_classic` into the
  shared gateway middle: a partial-fidelity, schema-less, non-publishable catalog item
  whose every operation is labelled ``inferred``.
* **Tyk OAS** — an OpenAPI 3 document carrying ``x-tyk-api-gateway`` — is a real spec. It
  is read through the OpenAPI adapter (paths and schemas as declared) and the extension is
  interpreted on top by :func:`app.tyk_parser.interpret_tyk_oas`, its gateway policy
  stamped ``inferred``. The adapter claims such a document *only* because of the
  extension — the same non-greedy rule the AWS API Gateway adapter follows — and the
  OpenAPI adapter steps down for it, so the two never tie.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .canonical_model import CanonicalApi
from .document_markers import top_level_api_marker
from .fileset import IntakeFileset
from .gateway_config_model import GatewayConfigDocument, GatewayConfigParseError
from .gateway_config_normalizer import TYK_FORMAT_KEY
from .import_source import NO_MATCH, DetectionInput, DetectionResult, ImportSourceError, LintReport
from .openapi_fileset_bundle import bundle_openapi_fileset
from .openapi_import_source import OpenApiImportSource
from .proxy_import_source import ProxyRouteImportSource
from .proxy_route_common import directive_capabilities, ordered_members
from .tyk_parser import (
    TYK_DECLARED_CONSTRUCTS,
    TYK_OAS_EXTENSION,
    TYK_READ_CONSTRUCTS,
    has_tyk_extension,
    interpret_tyk_oas,
    is_tyk_classic_document,
    is_tyk_policies_document,
    load_tyk_json,
    parse_tyk_classic,
    policies_from,
)

__all__ = ["TykImportSource"]

#: Confidence for a Tyk OAS document (the extension is unambiguous).
_OAS_CONFIDENCE = 0.97

#: Confidence for a classic definition.
_CLASSIC_CONFIDENCE = 0.95

#: Confidence for a policies file on its own (Tyk, but not an API).
_POLICIES_CONFIDENCE = 0.5


class TykImportSource(ProxyRouteImportSource, register=True):
    """Adapter for Tyk classic and Tyk OAS API definitions."""

    key = TYK_FORMAT_KEY
    label = "Tyk API definition"
    description = (
        "Import a Tyk API definition. Classic definitions (api_id + proxy.listen_path) become "
        "inferred operations from each version's white-listed paths and methods, with per-path "
        "rules, auth flags and an accompanying policies file kept as gateway policy — no "
        "schemas, so the import is a non-publishable catalog item. Tyk OAS definitions are "
        "OpenAPI documents: their paths and schemas import as OpenAPI, and x-tyk-api-gateway "
        "middleware is attached to each operation as inferred gateway policy."
    )
    icon = "route"
    formats = ("tyk",)
    file_extensions = (".json", ".yaml", ".yml")
    capabilities = directive_capabilities("tyk", read=TYK_READ_CONSTRUCTS, declared=TYK_DECLARED_CONSTRUCTS)

    # --- detection -------------------------------------------------------------------

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is None or "\x00" in text:
            return NO_MATCH
        if TYK_OAS_EXTENSION in text:
            try:
                document = OpenApiImportSource().parse(text, source_label=payload.filename)
            except ImportSourceError:
                # Unparseable, but an OpenAPI document carrying the extension is still ours.
                if top_level_api_marker(text) is not None:
                    return DetectionResult(
                        confidence=_OAS_CONFIDENCE,
                        format=TYK_FORMAT_KEY,
                        reason="OpenAPI document carrying `x-tyk-api-gateway` (Tyk OAS) "
                        "(the document did not fully parse)",
                    )
                return NO_MATCH
            if has_tyk_extension(document):
                return DetectionResult(
                    confidence=_OAS_CONFIDENCE,
                    format=TYK_FORMAT_KEY,
                    reason="OpenAPI document carrying `x-tyk-api-gateway` (Tyk OAS)",
                )
            return NO_MATCH
        if "api_id" not in text and "access_rights" not in text:
            return NO_MATCH
        try:
            document = load_tyk_json(text)
        except GatewayConfigParseError:
            return NO_MATCH
        if is_tyk_classic_document(document):
            return DetectionResult(
                confidence=_CLASSIC_CONFIDENCE,
                format=TYK_FORMAT_KEY,
                reason="`api_id` + `proxy` (Tyk classic API definition)",
            )
        if is_tyk_policies_document(document):
            return DetectionResult(
                confidence=_POLICIES_CONFIDENCE,
                format=TYK_FORMAT_KEY,
                reason="Tyk policies (access_rights keyed by api_id), with no API definition",
            )
        return NO_MATCH

    # --- parsing ---------------------------------------------------------------------

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        if TYK_OAS_EXTENSION in raw:
            return self._oas(OpenApiImportSource().parse(raw, source_label=source_label))
        return self._classic(load_tyk_json(raw), [], source_label=source_label)

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        order = ordered_members(members, root)
        if TYK_OAS_EXTENSION in members[order[0]]:
            fileset = IntakeFileset.from_members(dict(members), root=order[0])
            return self._oas(bundle_openapi_fileset(fileset, root=order[0]))
        definition = load_tyk_json(members[order[0]])
        policies: List[Mapping[str, Any]] = []
        for path in order[1:]:
            try:
                document = load_tyk_json(members[path])
            except GatewayConfigParseError as exc:
                raise GatewayConfigParseError(f"{path}: {exc}", code=exc.code) from exc
            if is_tyk_policies_document(document):
                policies.extend(policies_from(document))
            elif is_tyk_classic_document(document):
                raise GatewayConfigParseError(
                    f"{path}: a second API definition — a Tyk import reads one API with the "
                    "policies that grant access to it; import each API definition on its own",
                    code="INPUT_SEMANTIC_INVALID",
                )
        return self._classic(definition, policies, source_label=source_label)

    @staticmethod
    def _oas(document: Any) -> Dict[str, Any]:
        if not has_tyk_extension(document):
            raise GatewayConfigParseError(
                "Document carries no `x-tyk-api-gateway` extension; import it as OpenAPI",
                code="FORMAT_MISMATCH",
            )
        return dict(document)

    @staticmethod
    def _classic(
        document: Any, policies: List[Mapping[str, Any]], *, source_label: Optional[str]
    ) -> GatewayConfigDocument:
        if is_tyk_policies_document(document) and not is_tyk_classic_document(document):
            raise GatewayConfigParseError(
                "A Tyk policies file on its own describes access to APIs, not an API — import "
                "the API definition with the policies file beside it",
                code="INPUT_SEMANTIC_INVALID",
            )
        return parse_tyk_classic(document, policies=policies, source_label=source_label)

    # --- normalization ---------------------------------------------------------------

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Classic → the gateway normalizer; Tyk OAS → OpenAPI, then the extension."""
        if isinstance(native_ast, GatewayConfigDocument):
            return super().normalize(native_ast, include_raw=include_raw)
        if not has_tyk_extension(native_ast):
            raise ImportSourceError("Tyk source must be a classic GatewayConfigDocument or a Tyk OAS document")
        model = OpenApiImportSource().normalize(dict(native_ast), include_raw=include_raw)
        model.format = TYK_FORMAT_KEY
        if include_raw:
            model.raw = dict(native_ast)
        interpret_tyk_oas(model, native_ast)
        return model

    def lint(self, model: CanonicalApi) -> LintReport:
        """A Tyk OAS model is OpenAPI and lints as one; a classic one takes the default."""
        if isinstance(model.extras.get("tyk"), Mapping) and model.extras["tyk"].get("form") == "oas":
            return OpenApiImportSource().lint(model)
        return super().lint(model)
