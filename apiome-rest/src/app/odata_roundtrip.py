"""OData emitter validate + round-trip (OASIS schema) — MFX-16.3 (#3899).

The OData emitter (:class:`app.odata_emitter.ODataEmitter`, MFX-16.1) writes OData v4 metadata as CSDL
JSON 4.01, CSDL XML (EDMX), or both; its fidelity pack (MFX-16.2) *predicts* what CSDL cannot carry.
This module proves each emitted document valid by the standard's own rules and measures the round trip.

**Validation reuses the import's checks.** Every emitted document is parsed by
:class:`app.odata_import_source.ODataImportSource`, which runs the three checks an OData import goes
through (:func:`app.odata_validation.validate_odata_document`, MFI-11.1 / 11.4) and records what each
found on the parsed document. Each finding becomes one problem with its JSON pointer:

* ``odata.csdl-schema`` — the OASIS **CSDL JSON** schema (vendored ``odata-csdl-4.01`` JSON Schema);
* ``odata.csdl-xml-schema`` — for CSDL XML, the OASIS **EDMX / EDM XML schemas** (vendored XSDs);
* ``odata.unresolved-reference`` / ``odata.key`` — **reference and key resolution**: every ``$Type``,
  base type, entity set, navigation target and bound operation names a declared element, and every
  ``$Key`` property exists. A schema accepts ``"$Type": "ODataDemo.Missing"``; resolution does not.
* ``odata.parse`` — the document does not parse at all.

Counts beyond the listed findings are reported as one extra problem, so a truncated list is never
mistaken for the whole. With ``output: both``, the JSON and the XML document must also **describe the
same model** — both are re-imported and diffed (``odata.outputs-disagree``).

**Round trip** (:func:`round_trip_odata`). The re-imported model (from the CSDL JSON document when
there is one) is diffed with the source by key (:func:`app.import_source.canonical_diff`) and reconciled
with the fidelity report for the export's options (:func:`app.roundtrip_matrix.reconcile`, MFX-2.6).
Pure Python.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, EmittedFile, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .odata_csdl_json import is_csdl_json
from .odata_emitter import ODataEmitOptions, ODataEmitter
from .odata_import_source import ODataImportSource
from .odata_parser import ODataDocument
from .roundtrip_matrix import reconcile

__all__ = [
    "ODataRoundTripReport",
    "RoundTripStatus",
    "check_emitted_odata",
    "document_problems",
    "round_trip_odata",
]

#: The resolution issue kinds and the rule each is reported under.
_RESOLUTION_RULES = {"reference": "odata.unresolved-reference", "key": "odata.key"}


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — a document breaks the OASIS schema, does not resolve, or the two outputs disagree.
    * :attr:`UNPARSEABLE` — it is valid, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class ODataRoundTripReport(BaseModel):
    """What validating and round-tripping one OData export found."""

    model_config = ConfigDict(extra="forbid")

    problems: List[Dict[str, Any]] = Field(
        default_factory=list, description="Why the export is invalid (``rule``, ``message``, ``file``, ``path``)."
    )
    reimported: bool = Field(default=False, description="Whether the export imported again.")
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
        """Whether every document is valid **and** the export imported again."""
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


def _listed(rule: str, found: Any, total: int, file: str, label: str) -> List[Dict[str, Any]]:
    """One problem per recorded finding, plus a count of any the document did not list."""
    problems = [_problem(rule, f"{label}: {item['message']}", file, item.get("path") or "/") for item in found]
    if total > len(problems):
        problems.append(_problem(rule, f"{total - len(problems)} more not listed.", file))
    return problems


def document_problems(document: ODataDocument, file: str) -> List[Dict[str, Any]]:
    """The OASIS schema and resolution findings the import recorded on a parsed document.

    Args:
        document: The document as :class:`app.odata_import_source.ODataImportSource` parsed it.
        file: Its export path.

    Returns:
        One problem per finding (``odata.csdl-schema``, ``odata.csdl-xml-schema``,
        ``odata.unresolved-reference``, ``odata.key``).
    """
    problems = _listed("odata.csdl-schema", document.csdl_violations, document.csdl_violation_count, file,
                       "Breaks the OASIS CSDL JSON schema")
    problems += _listed("odata.csdl-xml-schema", document.xsd_violations, document.xsd_violation_count, file,
                        "Breaks the OASIS EDMX / EDM XML schema")
    for issue in document.resolution_issues:
        rule = _RESOLUTION_RULES.get(issue.get("kind", ""), "odata.unresolved-reference")
        problems.append(_problem(rule, issue["message"], file, issue.get("path") or "/"))
    if document.resolution_issue_count > len(document.resolution_issues):
        hidden = document.resolution_issue_count - len(document.resolution_issues)
        problems.append(_problem("odata.unresolved-reference", f"{hidden} more resolution issues not listed.", file))
    return problems


def _schema_only_problems(emitted: EmittedFile) -> List[Dict[str, Any]]:
    """The OASIS schema findings of a document the import could not finish reading."""
    import json

    from .odata_csdl_schema import validate_csdl_json
    from .odata_csdl_xsd import validate_csdl_xml

    text = str(emitted.content)
    try:
        if is_csdl_json(text):
            violations, total = validate_csdl_json(json.loads(text))
            rule, label = "odata.csdl-schema", "Breaks the OASIS CSDL JSON schema"
        else:
            checked = validate_csdl_xml(text, source_label=emitted.path)
            violations, total = checked if checked is not None else ((), 0)
            rule, label = "odata.csdl-xml-schema", "Breaks the OASIS EDMX / EDM XML schema"
    except Exception:  # noqa: BLE001 — nothing more can be said; the caller reports odata.parse
        return []
    return _listed(rule, [{"path": v.path, "message": v.message} for v in violations], total, emitted.path, label)


def _parse(emitted: EmittedFile) -> ODataDocument:
    """Parse one emitted document through the OData import source (which runs the OASIS checks)."""
    return ODataImportSource().parse(str(emitted.content), source_label=emitted.path)


def _normalize(document: ODataDocument) -> CanonicalApi:
    try:
        return ODataImportSource().normalize(document, include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed OData document: {exc}", code="INPUT_MALFORMED") from exc


def _validate(emit_result: EmitResult) -> Tuple[List[Dict[str, Any]], Dict[str, CanonicalApi], Optional[str]]:
    """Parse, check and normalize every document; ``(problems, models by path, import error)``."""
    problems: List[Dict[str, Any]] = []
    models: Dict[str, CanonicalApi] = {}
    import_error: Optional[str] = None
    for emitted in emit_result.files:
        try:
            document = _parse(emitted)
        except ImportSourceError as exc:
            problems.append(_problem("odata.parse", f"Not OData metadata: {exc}", emitted.path))
            continue
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            # Malformed metadata can trip the import's resolution step; its schema findings still say why.
            problems.extend(_schema_only_problems(emitted)
                            or [_problem("odata.parse", f"Not OData metadata: {exc}", emitted.path)])
            continue
        found = document_problems(document, emitted.path)
        problems.extend(found)
        if found:
            continue
        try:
            models[emitted.path] = _normalize(document)
        except ImportSourceError as exc:
            import_error = import_error or f"{emitted.path}: {exc}"
    if len(models) > 1 and not problems:
        (first_path, first), *rest = models.items()
        for path, model in rest:
            entries = canonical_diff(first, model).entries
            if entries:
                changed = ", ".join(f"{e.entity} {e.key or '(root)'}" for e in entries[:5])
                problems.append(_problem("odata.outputs-disagree",
                                         f"{path} and {first_path} describe different models ({changed}).", path))
    return problems, models, import_error


def check_emitted_odata(emit_result: EmitResult) -> List[Dict[str, Any]]:
    """Validate an OData export: every document's OASIS schema and resolution, its re-import, and agreement.

    Args:
        emit_result: The OData emitter's output.

    Returns:
        The problems (``rule``, ``message``, ``file``, ``path``); empty when the export is valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The OData export wrote no file.")
    problems, _models, import_error = _validate(emit_result)
    if import_error is not None and not problems:
        problems.append(_problem("odata.reimport", f"The document does not import: {import_error}",
                                 emit_result.files[0].path))
    return problems


def round_trip_odata(
    api: CanonicalApi,
    *,
    opts: Optional[Union[ODataEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> ODataRoundTripReport:
    """Validate the OData export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options (``output``…); the fidelity report is computed for them. When
            ``emit_result`` is given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`ODataRoundTripReport`.
    """
    emitter = ODataEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    if not emit_result.files:
        return ODataRoundTripReport(problems=[_problem("odata.empty", "The export wrote no file.", None)],
                                    predicted_losses=predicted)
    problems, models, import_error = _validate(emit_result)
    if problems:
        return ODataRoundTripReport(problems=problems, predicted_losses=predicted)
    if import_error is not None or not models:
        return ODataRoundTripReport(import_error=import_error or "Nothing imported.", predicted_losses=predicted)
    json_path = next((e.path for e in emit_result.files if is_csdl_json(str(e.content))), None)
    reimported = models[json_path] if json_path in models else next(iter(models.values()))
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return ODataRoundTripReport(
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
