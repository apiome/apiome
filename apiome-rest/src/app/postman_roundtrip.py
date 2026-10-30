"""Collection export validate + round-trip — MFX-31.4 (#4292).

The Postman emitter (:class:`app.postman_emitter.PostmanEmitter`, MFX-31.1) writes a Postman Collection
v2.1 document, and its fidelity pack (MFX-31.2) *predicts* what a collection of saved requests cannot
carry. This module proves the export is legal and re-importable, and measures the round trip.

**Flavors** (:func:`collection_flavor`). MFX-31.3 adds Insomnia and Bruno output modes to the same
target, so the check is chosen by what each emitted file *is*, not by the target key — the MFX-5.1
alternate-validator seam:

* **Postman** (``.postman_collection.json``, or JSON whose ``info.schema`` names a Postman collection
  schema) — the published Postman Collection **v2.1.0 JSON Schema** (vendored, offline): every violation
  is one ``postman.schema`` problem carrying its JSON path. Then the collection re-imports through
  :class:`app.postman_import_source.PostmanImportSource` (``postman.reimport``).
* **Insomnia** (a v4 export / v5 collection) and **Bruno** (``bruno.json`` + ``.bru`` requests) — no
  published schema; the authority is the import adapter Apiome already has for each
  (:class:`app.insomnia_import_source.InsomniaImportSource`, MFI-32.3;
  :class:`app.bruno_import_source.BrunoImportSource`, MFI-32.4), which reads the files as one upload
  (``insomnia.reimport`` / ``bruno.reimport``).
* anything else — ``collection.unknown-file``; two flavors in one export — ``collection.mixed-flavors``.

**Round trip** (:func:`round_trip_collection`). The re-imported model is diffed with the source by key
(:func:`app.import_source.canonical_diff`) and reconciled with the fidelity report computed for the
export's options (:func:`app.roundtrip_matrix.reconcile`, MFX-2.6). Pure Python.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .fileset import IntakeFileset
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSource, ImportSourceError, canonical_diff
from .postman_emitter import _SCHEMA_PATH, PostmanEmitOptions, PostmanEmitter
from .roundtrip_matrix import reconcile

__all__ = [
    "CollectionRoundTripReport",
    "RoundTripStatus",
    "check_emitted_collection",
    "collection_flavor",
    "postman_schema_problems",
    "reimport_collection",
    "round_trip_collection",
]

#: The collection formats an export can be written in.
Flavor = Literal["postman", "insomnia", "bruno"]

#: How many schema violations are listed per file (the rest are counted).
MAX_SCHEMA_PROBLEMS = 20


class RoundTripStatus(str, Enum):
    """The outcome of an emit → validate → re-import → diff round trip, worst first.

    * :attr:`INVALID` — a file breaks its schema, is not a collection file, or the export mixes flavors.
    * :attr:`UNPARSEABLE` — it is valid, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class CollectionRoundTripReport(BaseModel):
    """What validating and round-tripping one collection export found."""

    model_config = ConfigDict(extra="forbid")

    flavor: Optional[Flavor] = Field(default=None, description="The collection format the export is written in.")
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
        """Whether every file is valid **and** the export imported again."""
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


# ===========================================================================
# Flavors
# ===========================================================================


def collection_flavor(path: str, text: str) -> Optional[Flavor]:
    """Which collection format an emitted file is written in, or ``None`` when it is none of them."""
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith(".bru") or name == "bruno.json":
        return "bruno"
    from .insomnia_parser import detect_insomnia

    if detect_insomnia(text) is not None:
        return "insomnia"
    if name.endswith(".postman_collection.json"):
        return "postman"
    try:
        document = json.loads(text)
    except ValueError:
        return None
    info = document.get("info") if isinstance(document, dict) else None
    schema = info.get("schema") if isinstance(info, dict) else None
    if isinstance(schema, str) and "getpostman.com" in schema and "collection" in schema:
        return "postman"
    return None


def _source_for(flavor: Flavor) -> ImportSource:
    """The import adapter that reads ``flavor`` back."""
    if flavor == "postman":
        from .postman_import_source import PostmanImportSource

        return PostmanImportSource()
    if flavor == "insomnia":
        from .insomnia_import_source import InsomniaImportSource

        return InsomniaImportSource()
    from .bruno_import_source import BrunoImportSource

    return BrunoImportSource()


# ===========================================================================
# Validation
# ===========================================================================


def postman_schema_problems(path: str, text: str) -> List[Dict[str, Any]]:
    """Validate one Postman collection against the published v2.1.0 JSON Schema.

    Args:
        path: The file's export path.
        text: The collection JSON.

    Returns:
        One ``postman.schema`` problem per violation (with its JSON path, the first
        :data:`MAX_SCHEMA_PROBLEMS`, then a count), or one ``postman.json`` problem when it is not JSON.
    """
    from jsonschema import Draft7Validator

    try:
        document = json.loads(text)
    except ValueError as exc:
        return [_problem("postman.json", f"Not JSON: {exc}", path)]
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path])
    problems = [
        _problem("postman.schema", f"Breaks the Postman Collection v2.1.0 schema: {error.message}", path,
                 "/" + "/".join(str(part) for part in error.absolute_path))
        for error in errors[:MAX_SCHEMA_PROBLEMS]
    ]
    if len(errors) > MAX_SCHEMA_PROBLEMS:
        problems.append(_problem("postman.schema", f"{len(errors) - MAX_SCHEMA_PROBLEMS} more schema violations.",
                                 path))
    return problems


def _flavor_of_export(emit_result: EmitResult) -> Tuple[Optional[Flavor], List[Dict[str, Any]]]:
    """The export's one flavor, or the problems that stop it having one."""
    problems: List[Dict[str, Any]] = []
    flavors: Dict[str, Flavor] = {}
    for emitted in emit_result.files:
        flavor = collection_flavor(emitted.path, str(emitted.content))
        if flavor is None:
            problems.append(_problem("collection.unknown-file",
                                     "Not a Postman, Insomnia or Bruno collection file.", emitted.path))
        else:
            flavors[emitted.path] = flavor
    if len(set(flavors.values())) > 1:
        listed = ", ".join(f"{path} ({flavor})" for path, flavor in flavors.items())
        problems.append(_problem("collection.mixed-flavors", f"One export mixes collection formats: {listed}.", None))
    return (next(iter(flavors.values()), None) if not problems else None), problems


def reimport_collection(emit_result: EmitResult, flavor: Flavor) -> CanonicalApi:
    """Import a collection export through the adapter for its flavor, as one upload.

    Args:
        emit_result: The export.
        flavor: Its collection format (:func:`collection_flavor`).

    Returns:
        The canonical model.

    Raises:
        ImportSourceError: When it does not parse or normalize (a malformed shape the normalizer trips
            over is ``INPUT_MALFORMED``).
    """
    source = _source_for(flavor)
    members = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    try:
        if len(members) == 1:
            path, text = next(iter(members.items()))
            native = source.parse(text, source_label=path)
        else:
            root = next((p for p in members if p.rsplit("/", 1)[-1] == "bruno.json"), emit_result.files[0].path)
            native = source.parse_fileset(IntakeFileset.from_members(members, root=root), source_label=root)
        return source.normalize(native, include_raw=False)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed {flavor} collection: {exc}", code="INPUT_MALFORMED") from exc


def check_emitted_collection(emit_result: EmitResult) -> Tuple[Optional[Flavor], List[Dict[str, Any]]]:
    """Validate a collection export: its flavor, the Postman schema for Postman files, then a re-import.

    Args:
        emit_result: The export.

    Returns:
        ``(flavor, problems)``; ``problems`` is empty when the export is legal and re-importable.

    Raises:
        ValueError: When the export wrote no file.
    """
    if not emit_result.files:
        raise ValueError("The collection export wrote no file.")
    flavor, problems = _flavor_of_export(emit_result)
    if flavor is None:
        return None, problems
    if flavor == "postman":
        for emitted in emit_result.files:
            problems.extend(postman_schema_problems(emitted.path, str(emitted.content)))
    if not problems:
        try:
            reimport_collection(emit_result, flavor)
        except ImportSourceError as exc:
            problems.append(_problem(f"{flavor}.reimport", f"The collection does not import: {exc}",
                                     emit_result.files[0].path))
    return flavor, problems


def round_trip_collection(
    api: CanonicalApi,
    *,
    opts: Optional[Union[PostmanEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> CollectionRoundTripReport:
    """Validate the collection export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options; the fidelity report is computed for them. When ``emit_result`` is
            given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`CollectionRoundTripReport`.
    """
    emitter = PostmanEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    if not emit_result.files:
        return CollectionRoundTripReport(problems=[_problem("collection.empty", "The export wrote no file.", None)],
                                         predicted_losses=predicted)
    flavor, problems = _flavor_of_export(emit_result)
    if flavor == "postman":
        for emitted in emit_result.files:
            problems.extend(postman_schema_problems(emitted.path, str(emitted.content)))
    if problems or flavor is None:
        return CollectionRoundTripReport(flavor=flavor, problems=problems, predicted_losses=predicted)
    try:
        reimported = reimport_collection(emit_result, flavor)
    except ImportSourceError as exc:
        return CollectionRoundTripReport(flavor=flavor, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return CollectionRoundTripReport(
        flavor=flavor,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
