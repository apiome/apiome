"""OpenAPI / Swagger import source — MFI-1.1 (#3733).

The reference :class:`~app.import_source.ImportSource` adapter and the seam the
existing OpenAPI/Swagger import path is refactored behind. It wraps machinery that
already exists rather than reimplementing it:

* **parse** reuses :func:`app.import_ingestion.parse_document` (the JSON-or-YAML
  loader the import pipeline already uses);
* **normalize** delegates to the registered OpenAPI
  :class:`~app.normalizer.Normalizer` (MFI-2.3,
  :class:`app.openapi_normalizer.OpenApiNormalizer`) — no normalization logic is
  duplicated here;
* **lint** delegates to the existing deterministic OpenAPI linter
  (:func:`app.schema_lint.lint_openapi_spec`) when the native OpenAPI document is
  preserved on :attr:`CanonicalApi.raw`;
* **fingerprint**/**diff** use the canonical-model defaults from
  :mod:`app.import_source`.

Because nothing in the live import flow is rewired by this adapter (generalizing
the job engine onto adapters is MFI-1.2), wrapping the OpenAPI path behind the SPI
is **behavior-preserving**: the same parser, normalizer, and linter run.

Detection recognizes both OpenAPI 3.x and Swagger 2.0 so each routes to this
adapter. Swagger 2.0 normalization is handled by
:class:`app.swagger2_normalizer.Swagger2Normalizer` (MFI-30.1); OpenAPI 3.x by
:class:`app.openapi_normalizer.OpenApiNormalizer` (MFI-2.3).
"""

from __future__ import annotations

from typing import Any, Optional

# Importing the normalizers self-registers format keys resolved by
# :meth:`OpenApiImportSource.normalize`.
from . import openapi_normalizer  # noqa: F401
from . import swagger2_normalizer  # noqa: F401
from .canonical_model import ApiParadigm, CanonicalApi
from .import_ingestion import IngestionError, parse_document
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
    LintReport,
)

__all__ = ["OpenApiImportSource"]


class OpenApiImportSource(ImportSource, register=True):
    """Adapter for OpenAPI 3.x / Swagger 2.0 REST descriptions."""

    key = "openapi"
    label = "OpenAPI / Swagger"
    description = "Import an OpenAPI 3.0/3.1 or Swagger 2.0 REST API description."
    icon = "file-json"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE)
    supports_live_discovery = False
    formats = ("openapi-3.0", "openapi-3.1", "swagger-2.0")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Recognize an OpenAPI/Swagger document by its version marker.

        Reads the already-parsed ``document`` when present, else parses ``text``
        cheaply (a malformed document is simply not a match — never raises). An
        ``openapi: 3.x`` marker pins ``openapi-3.0``/``openapi-3.1`` with high
        confidence; a ``swagger: 2.x`` marker pins ``swagger-2.0``.
        """
        document = payload.document
        if document is None and payload.text:
            try:
                document = parse_document(payload.text, source_label=payload.filename)
            except IngestionError:
                return NO_MATCH
        if not isinstance(document, dict):
            return NO_MATCH

        version = document.get("openapi")
        if isinstance(version, str) and version.startswith("3."):
            fmt = "openapi-3.0" if version.startswith("3.0") else "openapi-3.1"
            return DetectionResult(
                confidence=0.99, format=fmt, reason=f"`openapi: {version}` marker"
            )

        swagger = document.get("swagger")
        if isinstance(swagger, str) and swagger.startswith("2."):
            return DetectionResult(
                confidence=0.95, format="swagger-2.0", reason=f"`swagger: {swagger}` marker"
            )

        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        """Parse OpenAPI/Swagger source text (JSON or YAML) into a ``dict``.

        Reuses the import pipeline's loader so YAML- and JSON-authored documents
        behave identically.

        Raises:
            ImportSourceError: If the text is not valid JSON/YAML or is not a
                mapping at the top level.
        """
        try:
            return parse_document(raw, source_label=source_label)
        except IngestionError as exc:
            raise ImportSourceError(str(exc)) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a parsed OpenAPI/Swagger document into a :class:`CanonicalApi`.

        Detects the precise format and delegates to its registered normalizer.

        Raises:
            ImportSourceError: If ``native_ast`` is not a mapping, is not an
                OpenAPI/Swagger document, or names a format with no registered
                normalizer.
        """
        if not isinstance(native_ast, dict):
            raise ImportSourceError("OpenAPI/Swagger source must be a parsed mapping (dict)")

        detection = self.detect(DetectionInput(document=native_ast))
        if detection.format is None:
            raise ImportSourceError(
                "Document is not an OpenAPI 3.x or Swagger 2.0 description "
                "(no `openapi`/`swagger` version marker)"
            )
        return self._normalize_via_registry(
            detection.format, native_ast, include_raw=include_raw
        )

    def lint(self, model: CanonicalApi) -> LintReport:
        """Lint via the existing OpenAPI linter when the native document is present.

        The deterministic OpenAPI linter (:func:`app.schema_lint.lint_openapi_spec`)
        operates on an OpenAPI document, which the normalizer preserves on
        :attr:`CanonicalApi.raw`. Its result is adapted into a :class:`LintReport` via
        :meth:`LintReport.from_lint_result`, so the report carries the same score, grade,
        and stable ``report_fingerprint`` the schema linter computes (MFI-4.2).

        When ``raw`` is absent (``include_raw=False`` at normalize time) or is not an OpenAPI
        document, the canonical-model engine default (:meth:`ImportSource.lint`) is used, so
        the revision is still rolled up to a deterministic score rather than left unscored.
        """
        raw = model.raw
        if not isinstance(raw, dict) or not isinstance(raw.get("openapi"), str):
            return super().lint(model)

        # Imported lazily: the linter pulls in the schema-lint rule catalogue,
        # which is only needed on the lint path.
        from .schema_lint import lint_openapi_spec

        return LintReport.from_lint_result(lint_openapi_spec(raw))
