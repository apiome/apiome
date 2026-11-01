"""Arazzo emitter validate + round-trip — MFX-10.3 (#3872).

The Arazzo emitter (:class:`app.arazzo_emitter.ArazzoEmitter`, MFX-10.1) writes one Arazzo workflow
document, and its fidelity pack (MFX-10.2) *predicts* what Arazzo cannot carry. This module proves the
document valid and re-importable, and measures the round trip:

* **schema** (``arazzo.schema``) — the official OAI Arazzo JSON Schema for the version the document
  declares, vendored byte for byte from ``spec.openapis.org`` and run offline (the only external
  ``$ref`` is the draft 2020-12 meta-schema, which ``jsonschema`` bundles):

  * ``data/arazzo_1_0_schema_2025_10_15.json`` — ``https://spec.openapis.org/arazzo/1.0/schema/2025-10-15``
    (SHA-256 ``b8715bd8…46ad4``);
  * ``data/arazzo_1_1_schema_2026_04_15.json`` — ``https://spec.openapis.org/arazzo/1.1/schema/2026-04-15``
    (SHA-256 ``37be9084…7ab9e``).

  Every violation is one problem carrying its JSON pointer; ``arazzo.yaml`` when the text does not
  parse. The schema **gates only a rebuilt document** — one the emitter synthesized from a non-Arazzo
  source, whose every field Apiome chose. An Arazzo import is the user's own document, written back as
  it was read: Apiome's importer accepts spellings the schema does not (``name`` for ``workflowId``, a
  ``request:`` block), so its violations are *reported* (:attr:`ArazzoRoundTripReport.schema_violations`)
  but never block its export.
* **re-import** (``arazzo.reimport``) — the document goes through
  :class:`app.arazzo_import_source.ArazzoImportSource` (parse + normalize, which also enforces the
  version range and that every step names something to invoke), the path an upload of it takes.
* **diff + reconcile** — :func:`app.import_source.canonical_diff` against the source and
  :func:`app.roundtrip_matrix.reconcile` with the fidelity report computed for the export's options
  (MFX-2.6).

Pure Python.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from jsonschema.validators import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .arazzo_emitter import ArazzoEmitOptions, ArazzoEmitter, is_workflow_source
from .arazzo_import_source import ArazzoImportSource
from .arazzo_spec import ArazzoVersionError, parse_arazzo_version
from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_ingestion import IngestionError, parse_document
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .odcs_schema import json_projection
from .roundtrip_matrix import reconcile

__all__ = [
    "ARAZZO_SCHEMA_RELEASES",
    "MAX_SCHEMA_PROBLEMS",
    "ArazzoRoundTripReport",
    "RoundTripStatus",
    "arazzo_schema_violations",
    "check_emitted_arazzo",
    "reimport_arazzo",
    "round_trip_arazzo",
]

#: How many schema violations are listed per document (the rest are counted).
MAX_SCHEMA_PROBLEMS = 20

_DATA_DIR = Path(__file__).parent / "data"

#: ``major.minor`` line → the published schema iteration that validates it.
ARAZZO_SCHEMA_RELEASES: Dict[str, str] = {
    "1.0": "https://spec.openapis.org/arazzo/1.0/schema/2025-10-15",
    "1.1": "https://spec.openapis.org/arazzo/1.1/schema/2026-04-15",
}

_SCHEMA_PATHS: Dict[str, Path] = {
    "1.0": _DATA_DIR / "arazzo_1_0_schema_2025_10_15.json",
    "1.1": _DATA_DIR / "arazzo_1_1_schema_2026_04_15.json",
}

# Built once per line, on first use: every export re-validates.
_VALIDATORS: Dict[str, Draft202012Validator] = {}


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — the document does not parse, or (rebuilt only) breaks the Arazzo schema.
    * :attr:`UNPARSEABLE` — it is valid, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class ArazzoRoundTripReport(BaseModel):
    """What validating and round-tripping one Arazzo export found."""

    model_config = ConfigDict(extra="forbid")

    passthrough: bool = Field(
        default=False,
        description="True when the source is an Arazzo import, so the schema does not gate the export.",
    )
    problems: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Why the document is invalid (``rule``, ``message``, ``file``, ``path``); blocks delivery.",
    )
    schema_violations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Schema violations of a pass-through document (reported, not blocking).",
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
        """Whether the document passes its gate **and** imported again."""
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


def _validator(line: str) -> Draft202012Validator:
    """The cached validator for one ``major.minor`` line (``"1.0"`` / ``"1.1"``)."""
    if line not in _VALIDATORS:
        _VALIDATORS[line] = Draft202012Validator(json.loads(_SCHEMA_PATHS[line].read_text(encoding="utf-8")))
    return _VALIDATORS[line]


def arazzo_schema_violations(document: Any) -> List[Tuple[str, str]]:
    """Every Arazzo schema violation of ``document``, in path order.

    The schema is the one for the ``major.minor`` the document's ``arazzo`` marker declares. A
    YAML-loaded document is projected onto its JSON spelling first (a YAML date is a string in JSON).

    Args:
        document: The parsed Arazzo document.

    Returns:
        ``(JSON pointer, message)`` pairs — ``""`` for the root. A missing or unreadable ``arazzo``
        version is itself one violation at ``/arazzo``.
    """
    if not isinstance(document, dict):
        return [("", "An Arazzo document must be a mapping.")]
    try:
        major, minor = parse_arazzo_version(document.get("arazzo"))
    except ArazzoVersionError as exc:
        return [("/arazzo", str(exc))]
    line = f"{major}.{minor}"
    if line not in _SCHEMA_PATHS:
        return [("/arazzo", f"No Arazzo schema is vendored for version {line}.")]
    errors = sorted(
        _validator(line).iter_errors(json_projection(document)),
        key=lambda e: [str(p) for p in e.absolute_path],
    )
    return [("".join(f"/{part}" for part in error.absolute_path), error.message) for error in errors]


def _schema_problems(path: str, document: Any) -> List[Dict[str, Any]]:
    """The schema violations of one document as problems, capped at :data:`MAX_SCHEMA_PROBLEMS`."""
    violations = arazzo_schema_violations(document)
    problems = [
        _problem("arazzo.schema", f"Breaks the Arazzo schema: {message}", path, pointer or "/")
        for pointer, message in violations[:MAX_SCHEMA_PROBLEMS]
    ]
    if len(violations) > MAX_SCHEMA_PROBLEMS:
        problems.append(_problem("arazzo.schema",
                                 f"{len(violations) - MAX_SCHEMA_PROBLEMS} more schema violations.", path))
    return problems


def _parse(path: str, text: str) -> Tuple[Optional[Any], List[Dict[str, Any]]]:
    """Parse one emitted document; ``(None, [arazzo.yaml problem])`` when it does not parse."""
    try:
        return parse_document(text, source_label=path), []
    except IngestionError as exc:
        return None, [_problem("arazzo.yaml", f"Not YAML or JSON: {exc}", path)]


def reimport_arazzo(emit_result: EmitResult) -> CanonicalApi:
    """Import an emitted Arazzo document through the Arazzo import source.

    Args:
        emit_result: The Arazzo emitter's output (one document).

    Returns:
        The re-imported canonical model.

    Raises:
        ImportSourceError: When it does not parse or normalize (a malformed shape the normalizer trips
            over is ``INPUT_MALFORMED``).
    """
    emitted = emit_result.files[0]
    source = ArazzoImportSource()
    try:
        return source.normalize(source.parse(str(emitted.content), source_label=emitted.path), include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed Arazzo document: {exc}", code="INPUT_MALFORMED") from exc


def _validate(emit_result: EmitResult, *, passthrough: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(blocking problems, reported schema violations)`` of every emitted document."""
    problems: List[Dict[str, Any]] = []
    reported: List[Dict[str, Any]] = []
    for emitted in emit_result.files:
        document, parse_problems = _parse(emitted.path, str(emitted.content))
        if parse_problems:
            problems.extend(parse_problems)
            continue
        found = _schema_problems(emitted.path, document)
        (reported if passthrough else problems).extend(found)
    return problems, reported


def check_emitted_arazzo(emit_result: EmitResult, *, passthrough: bool = False) -> List[Dict[str, Any]]:
    """Validate an Arazzo export: parse, the schema (rebuilt documents only), then a re-import.

    Args:
        emit_result: The Arazzo emitter's output.
        passthrough: True when the source is an Arazzo import
            (:func:`app.arazzo_emitter.is_workflow_source`); its schema violations do not block.

    Returns:
        The blocking problems (``rule``, ``message``, ``file``, ``path``); empty when the export is valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The Arazzo export wrote no file.")
    problems, _reported = _validate(emit_result, passthrough=passthrough)
    if not problems:
        try:
            reimport_arazzo(emit_result)
        except ImportSourceError as exc:
            problems.append(_problem("arazzo.reimport", f"The document does not import: {exc}",
                                     emit_result.files[0].path))
    return problems


def round_trip_arazzo(
    api: CanonicalApi,
    *,
    opts: Optional[Union[ArazzoEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> ArazzoRoundTripReport:
    """Validate the Arazzo export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options; the fidelity report is computed for them. When ``emit_result`` is
            given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`ArazzoRoundTripReport`.

    Raises:
        EmitPreconditionError: When ``emit_result`` is not given and the source cannot be exported to
            Arazzo (no operation to sequence).
    """
    emitter = ArazzoEmitter()
    passthrough = is_workflow_source(api)
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    if not emit_result.files:
        return ArazzoRoundTripReport(passthrough=passthrough, predicted_losses=predicted,
                                     problems=[_problem("arazzo.empty", "The export wrote no file.", None)])
    problems, reported = _validate(emit_result, passthrough=passthrough)
    base: Dict[str, Any] = {"passthrough": passthrough, "schema_violations": reported, "predicted_losses": predicted}
    if problems:
        return ArazzoRoundTripReport(problems=problems, **base)
    try:
        reimported = reimport_arazzo(emit_result)
    except ImportSourceError as exc:
        return ArazzoRoundTripReport(import_error=str(exc), **base)
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return ArazzoRoundTripReport(
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        **base,
    )
