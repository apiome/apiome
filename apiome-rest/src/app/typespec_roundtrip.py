"""TypeSpec emitter validate + round-trip (``tsp compile``) — MFX-15.3 (#3895).

The TypeSpec emitter (:class:`app.typespec_emitter.TypeSpecEmitter`, MFX-15.1) writes a ``.tsp``
document, and its fidelity pack (MFX-15.2) *predicts* what TypeSpec cannot carry. TypeSpec is a
source language, not an interchange format: nothing reads a ``.tsp`` back except its compiler. So
this module validates the export the way TypeSpec itself does — **compile it to OpenAPI** — and
then measures what survived by round-tripping that OpenAPI:

* **emit** — :class:`app.typespec_emitter.TypeSpecEmitter`;
* **compile** — :func:`app.typespec_compile.compile_typespec_set` runs the bundled ``tsp`` with
  ``@typespec/http`` + ``@typespec/openapi3`` (MFI-14.1), the compile a TypeSpec project import
  runs; each ``error`` diagnostic makes the export **invalid**;
* **re-import** — the emitted OpenAPI goes through :class:`app.openapi_import_source.OpenApiImportSource`,
  the path a user uploading that OpenAPI would hit; a document that does not import is **unparseable**;
* **diff** — :func:`app.diff.diff` compares the re-imported model with a **baseline**: the source
  exported straight to OpenAPI 3.1 (:class:`app.openapi_emitter.OpenApiEmitter`) and imported the
  same way.

**Why that baseline.** Diffing the compiled OpenAPI against the source model itself would mostly
measure normal-form noise — a TypeSpec item read by the built-in reader keys its types by namespace
(``HelloService.Greeting``), the compiled OpenAPI by name (``Greeting``); an OpenAPI-imported item
carries ``operationId`` extras a canonical model built in code does not. Putting both sides through
the same OpenAPI import cancels that noise, so the diff is exactly **what the TypeSpec hop changes
compared with exporting to OpenAPI directly** — the loss a user picking TypeSpec over OpenAPI takes.

:class:`TypeSpecRoundTripReport` carries one ordered :class:`RoundTripStatus` — ``skipped`` (no
compiler in this runtime), ``invalid``, ``unparseable``, ``lossy``, ``lossless`` — the measured
diff, the predicted losses, and :attr:`~TypeSpecRoundTripReport.diverges` (prediction and
measurement disagree, the MFX-2.6 flag). The compile is a subprocess; call this off the event loop.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import typespec_compile
from .canonical_model import CanonicalApi
from .diff import ModelDiff, diff
from .emitter import EmitOptions, EmitResult, Loss
from .import_source import ImportSourceError
from .openapi_emitter import OpenApiEmitter
from .openapi_import_source import OpenApiImportSource
from .typespec_compile import parse_diagnostics
from .typespec_emitter import TypeSpecEmitOptions, TypeSpecEmitter

__all__ = [
    "RoundTripStatus",
    "TypeSpecRoundTripReport",
    "compile_emitted_typespec",
    "compile_error_diagnostics",
    "import_compiled_openapi",
    "round_trip_typespec",
]


class RoundTripStatus(str, Enum):
    """The outcome of an emit → compile → re-import → diff round trip, worst first.

    * :attr:`SKIPPED` — no TypeSpec compiler in this runtime; nothing was proven either way.
    * :attr:`INVALID` — ``tsp compile`` reported at least one error.
    * :attr:`UNPARSEABLE` — it compiled, but the emitted OpenAPI does not import.
    * :attr:`LOSSY` — the OpenAPI imports, and differs from the baseline.
    * :attr:`LOSSLESS` — the OpenAPI imports, and matches the baseline entity for entity.
    """

    SKIPPED = "skipped"
    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class TypeSpecRoundTripReport(BaseModel):
    """What compiling and round-tripping one TypeSpec export found."""

    model_config = ConfigDict(extra="forbid")

    compiled: bool = Field(description="Whether ``tsp compile`` ran and succeeded.")
    skipped_reason: Optional[str] = Field(
        default=None, description="Why the compile did not run (no compiler in this runtime)."
    )
    compile_errors: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The compile's error diagnostics (``code``, ``message``, ``file``, ``line``, ``column``).",
    )
    openapi: Optional[Dict[str, Any]] = Field(
        default=None, description="The OpenAPI document ``@typespec/openapi3`` emitted, when it compiled."
    )
    reimported: bool = Field(default=False, description="Whether the emitted OpenAPI imported.")
    import_error: Optional[str] = Field(default=None, description="Why the emitted OpenAPI did not import.")
    diff: Optional[ModelDiff] = Field(
        default=None,
        description="Baseline (the source exported straight to OpenAPI) → re-imported model. ``None`` "
        "when there is nothing to compare (no re-import, or the baseline could not be built).",
    )
    predicted_losses: List[Loss] = Field(
        default_factory=list, description="The losses the TypeSpec emitter recorded."
    )

    @property
    def valid(self) -> bool:
        """Whether the export compiled **and** its OpenAPI imported (``False`` when skipped)."""
        return self.compiled and self.reimported

    @property
    def empirically_lossless(self) -> bool:
        """Whether the measured round trip matched the baseline (an empty entity diff)."""
        return self.diff is not None and self.diff.is_empty()

    @property
    def predicted_lossless(self) -> bool:
        """Whether the emitter predicted no loss."""
        return not self.predicted_losses

    @property
    def diverges(self) -> bool:
        """Whether prediction and measurement disagree; ``False`` when nothing was measured."""
        if self.diff is None:
            return False
        return self.empirically_lossless != self.predicted_lossless

    @property
    def status(self) -> RoundTripStatus:
        """The single ordered verdict (see :class:`RoundTripStatus`)."""
        if self.skipped_reason is not None:
            return RoundTripStatus.SKIPPED
        if not self.compiled:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def compile_emitted_typespec(emit_result: EmitResult) -> Dict[str, Any]:
    """Compile an emitted TypeSpec bundle and return the OpenAPI it emits.

    Args:
        emit_result: The TypeSpec emitter's output; its first file is the compile's entry point.

    Returns:
        The OpenAPI 3 document ``@typespec/openapi3`` emitted.

    Raises:
        ImportSourceError: From :func:`app.typespec_compile.compile_typespec_set` —
            ``ADAPTER_UNAVAILABLE`` without a compiler, another code when the compile failed.
        ValueError: When the bundle has no file.
    """
    if not emit_result.files:
        raise ValueError("The TypeSpec export wrote no file.")
    members = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    # Looked up on the module so a test can stand in for the compiler.
    return typespec_compile.compile_typespec_set(members, emit_result.files[0].path).openapi


def compile_error_diagnostics(exc: ImportSourceError, root: str) -> List[Dict[str, Any]]:
    """The error diagnostics a failed compile reported, as dicts (one generic row when none parse).

    Args:
        exc: The compile's failure.
        root: The entry file, used when a diagnostic names no file.

    Returns:
        ``[{"code", "message", "file", "line", "column"}, …]``.
    """
    detail = str(exc).split(": ", 1)[-1]
    rows = [
        {"code": d.code, "message": d.message, "file": d.file or root, "line": d.line, "column": d.column}
        for part in detail.split("; ")
        for d in parse_diagnostics(part)
        if d.severity == "error"
    ]
    return rows or [{"code": exc.code, "message": str(exc), "file": root, "line": None, "column": None}]


def import_compiled_openapi(document: Any) -> CanonicalApi:
    """Import an OpenAPI document the way an upload of it would be imported.

    Args:
        document: The OpenAPI document — a mapping, or JSON / YAML text.

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When the document does not parse or normalize — including a malformed
            shape the normalizer trips over (a ``paths`` that is not a mapping), which is re-raised
            as ``INPUT_MALFORMED`` so a caller handles one error type.
    """
    text = document if isinstance(document, str) else json.dumps(document)
    source = OpenApiImportSource()
    try:
        return source.normalize(source.parse(text, source_label="typespec-openapi"), include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed OpenAPI document: {exc}", code="INPUT_MALFORMED") from exc


def _baseline(api: CanonicalApi) -> Optional[CanonicalApi]:
    """The source exported straight to OpenAPI 3.1 and imported back, or ``None`` if that fails."""
    try:
        content = OpenApiEmitter().emit(api).files[0].content
        if isinstance(content, str):
            content = yaml.safe_load(content)
        return import_compiled_openapi(content)
    except (ImportSourceError, ValueError, KeyError, TypeError, IndexError):
        return None


def round_trip_typespec(
    api: CanonicalApi,
    *,
    opts: Optional[Union[TypeSpecEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> TypeSpecRoundTripReport:
    """Compile the TypeSpec export of ``api`` to OpenAPI, re-import it and diff it with the baseline.

    Args:
        api: The source canonical model.
        opts: Emit options; ignored when ``emit_result`` is given.
        emit_result: An emission to use instead of emitting here (the export job already has one).

    Returns:
        The :class:`TypeSpecRoundTripReport`.
    """
    if emit_result is None:
        emit_result = TypeSpecEmitter().emit(api, opts=opts)
    predicted = list(emit_result.losses)
    root = emit_result.files[0].path if emit_result.files else ""
    try:
        document = compile_emitted_typespec(emit_result)
    except ImportSourceError as exc:
        if exc.code == "ADAPTER_UNAVAILABLE":
            return TypeSpecRoundTripReport(compiled=False, skipped_reason=str(exc), predicted_losses=predicted)
        return TypeSpecRoundTripReport(
            compiled=False, compile_errors=compile_error_diagnostics(exc, root), predicted_losses=predicted
        )
    except ValueError as exc:
        error = {"code": None, "message": str(exc), "file": root, "line": None, "column": None}
        return TypeSpecRoundTripReport(compiled=False, compile_errors=[error], predicted_losses=predicted)

    try:
        reimported = import_compiled_openapi(document)
    except ImportSourceError as exc:
        return TypeSpecRoundTripReport(
            compiled=True, openapi=document, import_error=str(exc), predicted_losses=predicted
        )
    baseline = _baseline(api)
    return TypeSpecRoundTripReport(
        compiled=True,
        openapi=document,
        reimported=True,
        diff=diff(baseline, reimported) if baseline is not None else None,
        predicted_losses=predicted,
    )
