"""Standalone XSD emitter validate + round-trip — MFX-22.5 (#4136).

The XSD emitter (:class:`app.xsd_emitter.XsdEmitter`, MFX-22.1) writes one schema document per target
namespace, joined by ``xs:import``, as XSD 1.0 or 1.1; its fidelity pack (MFX-22.2) *predicts* what
XSD cannot carry. An XSD is a schema language, not an API description, so the authority that proves
it is a schema processor — ``xmlschema``, the same library the WSDL and WADL checks use:

* **XML** (``xsd.xml``) — every document is safe, well-formed XML (:func:`app.secure_xml.parse_xml`).
* **Packaging** (``xsd.bundle-reference``) — every ``xs:import`` / ``xs:include`` / ``xs:redefine``
  ``schemaLocation`` names another document of the export, relative to the one that declares it
  (:func:`app.wsdl_bundle_validation.bundle_reference_problems`); a URL or a path outside the export
  fails, because the unpacked files have nothing else to resolve against.
* **Schema** (``xsd.schema-1.0`` / ``xsd.schema-1.1``) — the export is unpacked into a private
  temporary folder and built by ``xmlschema`` (``allow="sandbox"``: only those files are read, nothing
  is fetched), which checks every type, facet, particle and reference. An XSD 1.0 export must build
  under **both** processors (1.1 accepts every valid 1.0 schema, and consumers run either); an XSD
  1.1 export (``vc:minVersion="1.1"``, ``xs:assertion``) under the 1.1 processor.
* **Re-import** — the export imports again through :class:`app.xsd_import_source.XsdImportSource`
  (the documents as one set when there are several).

**Round trip** (:func:`round_trip_xsd`). The re-imported model is diffed with the source by key and
reconciled with the fidelity report computed for the export's options (MFX-2.6). A source that
arrived as **WSDL** is round-tripped through the WSDL import path instead: the item is written as a
WSDL bundle (:class:`app.wsdl_emitter.WsdlEmitter`, which round-trips WSDL losslessly, MFX-14.1),
its own ``.xsd`` is replaced by this export, and the bundle is imported through
:class:`app.wsdl_import_source.WsdlImportSource` — so the WSDL source and the re-import share one normal
form, and any difference is the XSD export's. Everything here is pure Python.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import xmlschema
from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .fileset import IntakeFileset
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .roundtrip_matrix import reconcile, reimport_emitted
from .secure_xml import SecureXmlError, parse_xml
from .wsdl_bundle_validation import bundle_reference_problems, reader_file, reader_message
from .xsd_emitter import XsdEmitOptions, XsdEmitter
from .xsd_import_source import XsdImportSource
from .zip_bundle import safe_bundle_path

__all__ = [
    "RoundTripStatus",
    "XsdRoundTripReport",
    "check_emitted_xsd",
    "reimport_xsd",
    "round_trip_xsd",
    "xsd_version_of",
]

#: Which import path the round trip measured through.
ImportPath = Literal["xsd", "wsdl"]

_VERSIONING_NS = "http://www.w3.org/2007/XMLSchema-versioning"
_PROCESSORS = {"1.0": xmlschema.XMLSchema10, "1.1": xmlschema.XMLSchema11}


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — a document is not safe XML, an import is not packaged, or the schema does not
      build.
    * :attr:`UNPARSEABLE` — it is a valid schema, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class XsdRoundTripReport(BaseModel):
    """What validating and round-tripping one XSD export found."""

    model_config = ConfigDict(extra="forbid")

    problems: List[Dict[str, Any]] = Field(
        default_factory=list, description="Why the export is invalid (``rule``, ``message``, ``file``, ``path``)."
    )
    import_path: ImportPath = Field(
        default="xsd",
        description="``wsdl`` when a WSDL source was round-tripped through the WSDL import, else ``xsd``.",
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
        """Whether the export is a valid schema **and** imported again."""
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


def xsd_version_of(root: ET.Element) -> str:
    """The XSD version a schema document asks for: ``1.1`` when it carries ``vc:minVersion="1.1"``."""
    return "1.1" if root.get(f"{{{_VERSIONING_NS}}}minVersion") == "1.1" else "1.0"


def _problem(rule: str, message: str, file: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
    return {"rule": rule, "message": message, "file": file, "path": path}


def check_emitted_xsd(emit_result: EmitResult) -> List[Dict[str, Any]]:
    """Check an XSD export as it will be unpacked: XML, packaging, then the schema under each processor.

    Args:
        emit_result: The XSD emitter's output; its first file is the main document.

    Returns:
        The problems (``rule``, ``message``, ``file``, ``path``); empty when the export is valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The XSD export wrote no file.")
    files = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    problems: List[Dict[str, Any]] = []
    roots: Dict[str, ET.Element] = {}
    for path, text in files.items():
        if safe_bundle_path(path) != path:
            problems.append(_problem("xsd.bundle-reference", f"Unsafe file path {path!r}.", path))
            continue
        try:
            roots[path] = parse_xml(text, source_label=path)
        except SecureXmlError as exc:
            problems.append(_problem("xsd.xml", f"Not well-formed, safe XML: {exc}", path))
    for path, root in roots.items():
        for found in bundle_reference_problems(path, root, files, rule="xsd.bundle-reference"):
            problems.append(_problem(found.rule, found.message, found.file, found.path))
    if problems:
        return problems

    main = emit_result.files[0].path
    versions = ["1.1"] if xsd_version_of(roots[main]) == "1.1" else ["1.0", "1.1"]
    with tempfile.TemporaryDirectory(prefix="xsd-export-") as folder:
        for path, text in files.items():
            target = Path(folder, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for version in versions:
            try:
                _PROCESSORS[version](str(Path(folder, main)), allow="sandbox")
            except Exception as exc:  # noqa: BLE001 — any processor failure means "not a valid schema"
                problems.append(
                    _problem(f"xsd.schema-{version}", reader_message(exc, folder), reader_file(exc, folder, main))
                )
    return problems


def reimport_xsd(emit_result: EmitResult) -> CanonicalApi:
    """Import an XSD export the way an upload of it would be (one set when there are several documents).

    Raises:
        ImportSourceError: When it does not parse or normalize.
    """
    try:
        return reimport_emitted(XsdImportSource(), emit_result, multi_file=len(emit_result.files) > 1)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed XSD export: {exc}", code="INPUT_MALFORMED") from exc


def _reimport_through_wsdl(api: CanonicalApi, emit_result: EmitResult) -> CanonicalApi:
    """Splice the XSD export into the item's WSDL bundle in place of its schema, and import the bundle."""
    from .wsdl_emitter import WsdlEmitter
    from .wsdl_import_source import WsdlImportSource

    bundle = WsdlEmitter().emit(api)
    description = bundle.files[0]
    members = {description.path: str(description.content)}
    schema_path = bundle.files[1].path if len(bundle.files) > 1 else emit_result.files[0].path
    # The bundle's WSDL imports its schema by file name; the XSD export's main document takes its place.
    members[schema_path] = str(emit_result.files[0].content)
    for emitted in emit_result.files[1:]:
        members[emitted.path] = str(emitted.content)
    source = WsdlImportSource()
    fileset = IntakeFileset.from_members(members, root=description.path)
    return source.normalize(source.parse_fileset(fileset, source_label=description.path), include_raw=False)


def round_trip_xsd(
    api: CanonicalApi,
    *,
    opts: Optional[Union[XsdEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> XsdRoundTripReport:
    """Validate the XSD export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options (``xsd_version``…); the fidelity report is computed for them. When
            ``emit_result`` is given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`XsdRoundTripReport`.
    """
    emitter = XsdEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    import_path: ImportPath = "wsdl" if api.format == "wsdl" else "xsd"
    try:
        problems = check_emitted_xsd(emit_result)
    except ValueError as exc:
        return XsdRoundTripReport(problems=[_problem("xsd.empty", str(exc))], import_path=import_path,
                                  predicted_losses=predicted)
    if problems:
        return XsdRoundTripReport(problems=problems, import_path=import_path, predicted_losses=predicted)
    try:
        reimported = _reimport_through_wsdl(api, emit_result) if import_path == "wsdl" else reimport_xsd(emit_result)
    except (ImportSourceError, ValueError) as exc:
        return XsdRoundTripReport(import_path=import_path, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return XsdRoundTripReport(
        import_path=import_path,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
