"""JSON Schema emitter validate + round-trip — MFX-21.4 (#4129).

The JSON Schema emitter (:class:`app.jsonschema_emitter.JsonSchemaEmitter`, MFX-21.1) writes a 2020-12,
draft-07 or draft-04 schema — one bundle, or one file per type — and its fidelity pack (MFX-21.2)
*predicts* what the chosen draft cannot carry. The MFX-EPIC-5 rule is that an emitter never ships an
invalid artifact, so this module checks every emitted file and then **measures** the round trip:

* **metaschema** — each document passes the metaschema of the draft it declares (2020-12 when it
  declares none; :func:`app.jsonschema_emitter.validate_jsonschema_document`, which also re-parses it
  through the import adapter). A JSON Type Definition document (``mode="jtd"``) is checked against the
  RFC 8927 schema rules instead (``jsonschema.jtd``).
* **references** — every ``$ref`` must resolve. A metaschema cannot see a dangling reference
  (``{"$ref": "#/$defs/Missing"}`` is a valid schema), so each reference is looked up across the
  emitted files with ``referencing``: a reference into the export (a ``#/$defs/…`` pointer, or another
  ``<Type>.schema.json`` of a per-type export, relative or under ``id_base``) must exist. A reference to
  an absolute URI outside the export (a source that pointed at a published schema) is left alone.
* **re-import** — the document goes through :class:`app.jsonschema_import_source.JsonSchemaImportSource`
  (parse + normalize), the path an upload of it takes (MFI-26.7).
* **diff + reconcile** — for a one-document export, :func:`app.import_source.canonical_diff` compares the
  re-imported model with the source and :func:`app.roundtrip_matrix.reconcile` joins every difference
  to the fidelity finding that explains it (MFX-2.6), with the report computed for the export's own
  options (so a draft downgrade's losses count). The JSON Schema import reads one document, so a
  per-type export and a JTD document are validated and re-parsed but not diffed
  (:attr:`RoundTripStatus.VALID`).

The import keeps field types shallow — it does not read ``format`` or numeric bounds back (the raw
document carries them for a later conversion) — so a source whose fields carry constraints measures as
changed even though the schema wrote them; the reconciliation shows that as an overclaim.
Everything here is pure Python.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union
from urllib.parse import urldefrag, urljoin

from pydantic import BaseModel, ConfigDict, Field
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .jsonschema_emitter import JsonSchemaEmitOptions, JsonSchemaEmitter, _jtd_document, validate_jsonschema_document
from .jsonschema_import_source import JsonSchemaImportSource
from .jsonschema_jtd import check_jtd_schema
from .roundtrip_matrix import reconcile

__all__ = [
    "RoundTripStatus",
    "JsonSchemaRoundTripReport",
    "check_emitted_jsonschema",
    "reimport_document",
    "round_trip_jsonschema",
    "unresolved_references",
]

#: The base URI an emitted file without an ``$id`` is resolved under (``<base><path>``). It must be a
#: hierarchical URI (``urljoin`` does not resolve relative references against a ``urn:``), and
#: ``.invalid`` can never name a real host.
BUNDLE_BASE = "https://export.apiome.invalid/"

#: Keywords whose value maps names to subschemas (the names are not keywords).
_SCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
#: Keywords whose value is data, never a schema.
_DATA_KEYWORDS = frozenset({"enum", "const", "default", "examples", "example"})


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — a document failed its metaschema (or the JTD rules), or a reference dangles.
    * :attr:`UNPARSEABLE` — it validated, but does not import.
    * :attr:`VALID` — valid and importable, but not diffed (a per-type or JTD export).
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    VALID = "valid"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class JsonSchemaRoundTripReport(BaseModel):
    """What validating and round-tripping one JSON Schema export found."""

    model_config = ConfigDict(extra="forbid")

    problems: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Why a document is invalid (``rule``, ``message``, ``file``, ``path``).",
    )
    reimported: bool = Field(default=False, description="Whether every document imported again.")
    import_error: Optional[str] = Field(default=None, description="Why a document did not import.")
    diff: Optional[CanonicalDiff] = Field(
        default=None,
        description="Source → re-imported model, by key. ``None`` when nothing was diffed (it did not "
        "import, or the export is per-type or JTD).",
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
        """Whether every document validated **and** imported again."""
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
        if self.diff is None:
            return RoundTripStatus.VALID
        if self.empirically_lossless:
            return RoundTripStatus.LOSSLESS
        return RoundTripStatus.LOSSY


# ===========================================================================
# References
# ===========================================================================


def _base_uri(path: str, document: Mapping[str, Any]) -> str:
    """The URI a file's relative references resolve against: its ``$id`` (draft-04: ``id``), else its path."""
    for keyword in ("$id", "id"):
        value = document.get(keyword)
        if isinstance(value, str) and value:
            return urljoin(BUNDLE_BASE + path, value)
    return BUNDLE_BASE + path


def _references(schema: Any, base: str, pointer: str = "") -> Iterator[Tuple[str, str, str]]:
    """Every ``$ref`` in a schema as ``(base URI it resolves against, the reference, its JSON pointer)``.

    A subschema's own ``$id`` moves the base for everything under it. The names under ``properties``,
    ``$defs`` and their kin are not keywords, and ``enum`` / ``const`` / ``default`` / ``examples``
    hold data, so neither is read as a schema.
    """
    if isinstance(schema, list):
        for index, item in enumerate(schema):
            yield from _references(item, base, f"{pointer}/{index}")
        return
    if not isinstance(schema, dict):
        return
    own_id = schema.get("$id")
    if isinstance(own_id, str) and own_id and pointer:
        base = urljoin(base, own_id)
    for keyword, value in schema.items():
        location = f"{pointer}/{keyword.replace('~', '~0').replace('/', '~1')}"
        if keyword == "$ref" and isinstance(value, str):
            yield base, value, location
        elif keyword in _DATA_KEYWORDS:
            continue
        elif keyword in _SCHEMA_MAPS and isinstance(value, dict):
            for name, subschema in value.items():
                yield from _references(subschema, base, f"{location}/{name.replace('~', '~0').replace('/', '~1')}")
        else:
            yield from _references(value, base, location)


def unresolved_references(documents: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The ``$ref`` s that point into the export but name nothing there.

    Args:
        documents: Each emitted JSON Schema document, keyed by its file path.

    Returns:
        One problem per dangling reference (``rule`` ``jsonschema.unresolved-ref``, ``file``, ``path``,
        ``message``). A reference to a document outside the export is not checked.
    """
    resources = {
        _base_uri(path, document): Resource.from_contents(document, default_specification=DRAFT202012)
        for path, document in documents.items()
    }
    registry = Registry().with_resources(resources.items()).crawl()
    exported = {urldefrag(uri).url for uri in resources}
    problems: List[Dict[str, Any]] = []
    for path, document in documents.items():
        base = _base_uri(path, document)
        for ref_base, ref, pointer in _references(document, base):
            target = urldefrag(urljoin(ref_base, ref)).url
            if target not in exported and "://" in ref:
                continue  # an absolute reference to a schema outside the export
            try:
                registry.resolver(base_uri=ref_base).lookup(ref)
            except Unresolvable:
                problems.append(
                    {
                        "rule": "jsonschema.unresolved-ref",
                        "message": f"$ref {ref!r} does not resolve within the export.",
                        "file": path,
                        "path": pointer,
                    }
                )
    return problems


# ===========================================================================
# Validation and re-import
# ===========================================================================


def check_emitted_jsonschema(emit_result: EmitResult) -> List[Dict[str, Any]]:
    """Validate every emitted file: its metaschema (or the JTD rules), then the export's references.

    Args:
        emit_result: The JSON Schema emitter's output.

    Returns:
        The problems (``rule``, ``message``, ``file``, ``path``); empty when every file is valid.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The JSON Schema export wrote no file.")
    problems: List[Dict[str, Any]] = []
    documents: Dict[str, Dict[str, Any]] = {}
    for emitted in emit_result.files:
        text = str(emitted.content)
        jtd = _jtd_document(text)
        try:
            if jtd is not None:
                check_jtd_schema(jtd)
                continue
            validate_jsonschema_document(text)
        except Exception as exc:  # noqa: BLE001 — any failure is "not valid", never a crash
            rule = "jsonschema.jtd" if jtd is not None else "jsonschema.metaschema"
            problems.append({"rule": rule, "message": str(exc), "file": emitted.path, "path": None})
            continue
        document = json.loads(text)
        if isinstance(document, dict):
            documents[emitted.path] = document
    if not problems:
        problems.extend(unresolved_references(documents))
    return problems


def reimport_document(text: str, *, source_label: Optional[str] = None) -> CanonicalApi:
    """Import one emitted JSON Schema document the way an upload of it would be imported.

    Args:
        text: The document.
        source_label: Label used in error messages.

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When it does not parse or normalize (a malformed shape the normalizer trips
            over is ``INPUT_MALFORMED``).
    """
    source = JsonSchemaImportSource()
    try:
        return source.normalize(source.parse(text, source_label=source_label), include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed JSON Schema document: {exc}", code="INPUT_MALFORMED") from exc


def round_trip_jsonschema(
    api: CanonicalApi,
    *,
    opts: Optional[Union[JsonSchemaEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> JsonSchemaRoundTripReport:
    """Validate the JSON Schema export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options (they choose the draft, the packaging and the mode, and the fidelity
            report the measurement is reconciled with). When ``emit_result`` is given, pass the options
            it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`JsonSchemaRoundTripReport`.
    """
    emitter = JsonSchemaEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    try:
        problems = check_emitted_jsonschema(emit_result)
    except ValueError as exc:
        failure = {"rule": "jsonschema.empty", "message": str(exc), "file": None, "path": None}
        return JsonSchemaRoundTripReport(problems=[failure], predicted_losses=predicted)
    if problems:
        return JsonSchemaRoundTripReport(problems=problems, predicted_losses=predicted)

    schemas = [emitted for emitted in emit_result.files if _jtd_document(str(emitted.content)) is None]
    reimported: Optional[CanonicalApi] = None
    try:
        for emitted in schemas:
            reimported = reimport_document(str(emitted.content), source_label=emitted.path)
    except ImportSourceError as exc:
        return JsonSchemaRoundTripReport(import_error=str(exc), predicted_losses=predicted)
    if len(emit_result.files) != 1 or reimported is None:
        return JsonSchemaRoundTripReport(reimported=True, predicted_losses=predicted)

    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return JsonSchemaRoundTripReport(
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
