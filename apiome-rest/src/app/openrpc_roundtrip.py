"""OpenRPC emitter validate + round-trip — MFX-33.3 (#4303).

The OpenRPC emitter (:class:`app.openrpc_emitter.OpenRpcEmitter`, MFX-33.1) writes one OpenRPC 1.x
document for a JSON-RPC 2.0 API, and its fidelity pack (MFX-33.2) *predicts* what OpenRPC cannot carry.
This module proves the document valid and re-importable, and measures the round trip:

* **meta-schema** (``openrpc.meta-schema``) — the OpenRPC document meta-schema (``@open-rpc/meta-schema``
  1.14.9, vendored, offline; :func:`app.openrpc_emitter.meta_schema_violations`). Every violation is one
  problem carrying its JSON pointer; ``openrpc.json`` when the text is not JSON.
* **references** (``openrpc.unresolved-ref``) — every ``$ref`` must resolve inside the document. A
  meta-schema cannot see ``{"$ref": "#/components/schemas/Missing"}`` — it is a well-formed reference — so
  each one is looked up with ``referencing`` (:func:`app.jsonschema_roundtrip.unresolved_references`, the
  walker the JSON Schema export uses); a reference to an absolute URI outside the document is left alone.
* **re-import** (``openrpc.reimport``) — the document goes through
  :class:`app.openrpc_import_source.OpenRpcImportSource` (MFI-19.1), parse + normalize, the path an upload
  of it takes.
* **diff + reconcile** — :func:`app.import_source.canonical_diff` against the source and
  :func:`app.roundtrip_matrix.reconcile` with the fidelity report computed for the export's options
  (MFX-2.6).

Pure Python.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .jsonschema_roundtrip import unresolved_references
from .openrpc_emitter import OpenRpcEmitOptions, OpenRpcEmitter, meta_schema_violations
from .openrpc_import_source import OpenRpcImportSource
from .roundtrip_matrix import reconcile

__all__ = [
    "MAX_META_SCHEMA_PROBLEMS",
    "OpenRpcRoundTripReport",
    "RoundTripStatus",
    "check_emitted_openrpc",
    "reimport_openrpc",
    "round_trip_openrpc",
]

#: How many meta-schema violations are listed per document (the rest are counted).
MAX_META_SCHEMA_PROBLEMS = 20


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — the document breaks the meta-schema, is not JSON, or has a dangling ``$ref``.
    * :attr:`UNPARSEABLE` — it is valid, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class OpenRpcRoundTripReport(BaseModel):
    """What validating and round-tripping one OpenRPC export found."""

    model_config = ConfigDict(extra="forbid")

    problems: List[Dict[str, Any]] = Field(
        default_factory=list, description="Why the document is invalid (``rule``, ``message``, ``file``, ``path``)."
    )
    reimported: bool = Field(default=False, description="Whether the document imported again.")
    import_error: Optional[str] = Field(default=None, description="Why it did not import.")
    diff: Optional[CanonicalDiff] = Field(
        default=None, description="Source → re-imported model, by key. ``None`` when it did not import."
    )
    unexplained: List[CanonicalDiffEntry] = Field(
        default_factory=list, description="Differences no fidelity finding explains (silent losses)."
    )
    overclaims: List[str] = Field(
        default_factory=list, description="Constructs the fidelity report called preserved that changed."
    )
    predicted_losses: List[Loss] = Field(default_factory=list, description="The losses the emitter recorded.")

    @property
    def valid(self) -> bool:
        """Whether the document is valid **and** imported again."""
        return not self.problems and self.reimported

    @property
    def empirically_lossless(self) -> bool:
        """Whether the measured round trip changed nothing."""
        return self.diff is not None and self.diff.is_empty

    @property
    def explained(self) -> bool:
        """Whether every measured difference is explained and nothing is over-claimed."""
        return self.diff is not None and not self.unexplained and not self.overclaims

    @property
    def diverges(self) -> bool:
        """Whether prediction and measurement disagree (MFX-2.6); ``False`` when nothing was measured."""
        return self.diff is not None and not self.explained

    @property
    def status(self) -> RoundTripStatus:
        """The single ordered verdict (see :class:`RoundTripStatus`)."""
        if self.problems:
            return RoundTripStatus.INVALID
        if not self.reimported:
            return RoundTripStatus.UNPARSEABLE
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


def _problem(rule: str, message: str, file: Optional[str], path: Optional[str] = None) -> Dict[str, Any]:
    return {"rule": rule, "message": message, "file": file, "path": path}


def _document_problems(path: str, text: str) -> List[Dict[str, Any]]:
    """The meta-schema and reference problems of one emitted document."""
    try:
        document = json.loads(text)
    except ValueError as exc:
        return [_problem("openrpc.json", f"Not JSON: {exc}", path)]
    violations = meta_schema_violations(document)
    problems = [
        _problem("openrpc.meta-schema", f"Breaks the OpenRPC meta-schema: {message}", path, pointer or "/")
        for pointer, message in violations[:MAX_META_SCHEMA_PROBLEMS]
    ]
    if len(violations) > MAX_META_SCHEMA_PROBLEMS:
        problems.append(_problem("openrpc.meta-schema",
                                 f"{len(violations) - MAX_META_SCHEMA_PROBLEMS} more meta-schema violations.", path))
    if not problems and isinstance(document, dict):
        for found in unresolved_references({path: document}):
            problems.append(_problem("openrpc.unresolved-ref", found["message"], path, found["path"]))
    return problems


def reimport_openrpc(emit_result: EmitResult) -> CanonicalApi:
    """Import an emitted OpenRPC document through the OpenRPC import source (MFI-19.1).

    Raises:
        ImportSourceError: When it does not parse or normalize (a malformed shape the normalizer trips
            over is ``INPUT_MALFORMED``).
    """
    emitted = emit_result.files[0]
    source = OpenRpcImportSource()
    try:
        return source.normalize(source.parse(str(emitted.content), source_label=emitted.path), include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed OpenRPC document: {exc}", code="INPUT_MALFORMED") from exc


def check_emitted_openrpc(emit_result: EmitResult) -> List[Dict[str, Any]]:
    """Validate an OpenRPC export: meta-schema, references, then a re-import.

    Args:
        emit_result: The OpenRPC emitter's output.

    Returns:
        The problems (``rule``, ``message``, ``file``, ``path``); empty when the export is valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The OpenRPC export wrote no file.")
    problems: List[Dict[str, Any]] = []
    for emitted in emit_result.files:
        problems.extend(_document_problems(emitted.path, str(emitted.content)))
    if not problems:
        try:
            reimport_openrpc(emit_result)
        except ImportSourceError as exc:
            problems.append(_problem("openrpc.reimport", f"The document does not import: {exc}",
                                     emit_result.files[0].path))
    return problems


def round_trip_openrpc(
    api: CanonicalApi,
    *,
    opts: Optional[Union[OpenRpcEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> OpenRpcRoundTripReport:
    """Validate the OpenRPC export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options; the fidelity report is computed for them. When ``emit_result`` is
            given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`OpenRpcRoundTripReport`.
    """
    emitter = OpenRpcEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    if not emit_result.files:
        return OpenRpcRoundTripReport(problems=[_problem("openrpc.empty", "The export wrote no file.", None)],
                                      predicted_losses=predicted)
    problems = [p for e in emit_result.files for p in _document_problems(e.path, str(e.content))]
    if problems:
        return OpenRpcRoundTripReport(problems=problems, predicted_losses=predicted)
    try:
        reimported = reimport_openrpc(emit_result)
    except ImportSourceError as exc:
        return OpenRpcRoundTripReport(import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return OpenRpcRoundTripReport(
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
