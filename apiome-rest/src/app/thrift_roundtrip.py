"""Thrift emitter validate + round-trip — MFX-25.4 (#4154).

The Thrift emitter (:class:`app.thrift_emitter.ThriftEmitter`, MFX-25.1) writes an Apache Thrift IDL,
and its fidelity pack (MFX-25.3) *predicts* what Thrift cannot carry. This module proves the export
three ways and measures the round trip:

* **compile** (``thrift.compile``) — the Apache Thrift compiler (``thrift --gen json``,
  :func:`app.thrift_compile.compile_thrift_idl`, through the toolchain runner) parses and type-checks
  the whole IDL; every compiler error line is a finding. The compiler is given one file at a time, so an
  export with an ``include`` (from a multi-file Thrift source) is not compiled; without the compiler
  in this runtime, nothing is compiled and :attr:`ThriftRoundTripReport.compiler` says so.
* **spot-check** (``thrift.thriftpy2-parse`` / ``thrift.parser-disagreement``) — ``thriftpy2``, an
  independent Thrift parser that resolves every type and constant, parses each file, and its AST must
  agree with the reader Apiome imports Thrift with (:func:`app.thrift_parser.parse_thrift`): the same
  enums and members, the same structs / unions / exceptions with the same field ids and names, the same
  services offering every method. Two parsers that disagree mean the export does not say what the import
  will read. Pure Python, so it runs with or without the compiler. Files are parsed from a private
  temporary folder, includes resolve only inside it, and nothing is cached or fetched.
* **re-import** (``thrift.reimport``) — the export imports again through
  :class:`app.thrift_import_source.ThriftImportSource`.
* **diff + reconcile** — :func:`app.import_source.canonical_diff` against the source and
  :func:`app.roundtrip_matrix.reconcile` with the fidelity report (MFX-2.6).
"""

from __future__ import annotations

import os
import posixpath
import re
import tempfile
from enum import Enum
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitOptions, EmitResult, Loss
from .fidelity_engine import compute_lossiness_for_emitter
from .import_source import CanonicalDiff, CanonicalDiffEntry, ImportSourceError, canonical_diff
from .roundtrip_matrix import reconcile, reimport_emitted
from .thrift_emitter import ThriftEmitOptions, ThriftEmitter
from .thrift_import_source import ThriftImportSource
from .thrift_parser import ThriftDocument, ThriftParseError, parse_thrift

__all__ = [
    "RoundTripStatus",
    "ThriftRoundTripReport",
    "compile_problems",
    "reimport_thrift",
    "round_trip_thrift",
    "spot_check_thrift",
]

#: Whether the Thrift compiler checked the export.
CompilerVerdict = Literal["thrift", "unavailable", "includes"]

_INCLUDE_RE = re.compile(r"""^\s*include\s+["']([^"']+)["']""", re.MULTILINE)


class RoundTripStatus(str, Enum):
    """The outcome of an emit → compile → spot-check → re-import → diff round trip, worst first.

    * :attr:`INVALID` — the compiler rejected the IDL, thriftpy2 could not parse it, or the two
      parsers disagree on what it declares.
    * :attr:`UNPARSEABLE` — it is valid, but does not import.
    * :attr:`LOSSY` — it imports, and differs from the source.
    * :attr:`LOSSLESS` — it imports, and matches the source entity for entity.
    """

    INVALID = "invalid"
    UNPARSEABLE = "unparseable"
    LOSSY = "lossy"
    LOSSLESS = "lossless"


class ThriftRoundTripReport(BaseModel):
    """What compiling, spot-checking and round-tripping one Thrift export found."""

    model_config = ConfigDict(extra="forbid")

    compiler: CompilerVerdict = Field(
        description="``thrift`` when the compiler checked every file, ``unavailable`` when it is not in this "
        "runtime, ``includes`` when a file has an ``include`` (the compiler is given one file at a time).",
    )
    problems: List[Dict[str, Any]] = Field(
        default_factory=list, description="Why the export is invalid (``rule``, ``message``, ``file``)."
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
        """Whether the export is valid **and** imported again."""
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


def _problem(rule: str, message: str, file: Optional[str]) -> Dict[str, Any]:
    return {"rule": rule, "message": message, "file": file}


def _includes_resolve(path: str, text: str, files: Mapping[str, str]) -> bool:
    """Whether every ``include`` of ``path`` names another file of the export (relative to it)."""
    base = posixpath.dirname(path)
    for target in _INCLUDE_RE.findall(text):
        if "://" in target or target.startswith(("/", "\\")):
            return False
        resolved = posixpath.normpath(posixpath.join(base, target))
        if resolved.startswith("../") or resolved not in files:
            return False
    return True


# ===========================================================================
# Compile
# ===========================================================================


async def compile_problems(emit_result: EmitResult) -> tuple[CompilerVerdict, List[Dict[str, Any]]]:
    """Compile every emitted file with the Thrift compiler.

    Args:
        emit_result: The Thrift emitter's output.

    Returns:
        ``(compiler, problems)``: whether the compiler checked the export, and one ``thrift.compile``
        problem per compiler error line.
    """
    from . import thrift_compile

    files = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    if any(_INCLUDE_RE.search(text) for text in files.values()):
        return "includes", []  # the compiler is given one file at a time, so an include cannot resolve
    if not thrift_compile.thrift_available():
        return "unavailable", []
    problems: List[Dict[str, Any]] = []
    for path, text in files.items():
        try:
            await thrift_compile.compile_thrift_idl(path, text)
        except thrift_compile.ThriftCompileError as exc:
            if exc.unavailable:
                return "unavailable", []
            problems.extend(_problem("thrift.compile", line, path) for line in (exc.diagnostics or [str(exc)]))
    return "thrift", problems


# ===========================================================================
# thriftpy2 spot-check
# ===========================================================================


def _thriftpy2_shape(module: Any) -> Dict[str, Any]:
    """What a thriftpy2 module declares: enums → members, structs → (kind, {id: name}), services → methods."""
    meta = getattr(module, "__thrift_meta__", {}) or {}
    shape: Dict[str, Any] = {"enums": {}, "structs": {}, "services": {}}
    for enum in meta.get("enums", []):
        shape["enums"][enum.__name__] = sorted(getattr(enum, "_NAMES_TO_VALUES", {}))
    for kind, key in (("struct", "structs"), ("union", "unions"), ("exception", "exceptions")):
        for struct in meta.get(key, []):
            spec = getattr(struct, "thrift_spec", {}) or {}
            shape["structs"][struct.__name__] = (kind, {int(fid): entry[1] for fid, entry in spec.items()})
    for service in meta.get("services", []):
        shape["services"][service.__name__] = set(getattr(service, "thrift_services", []) or [])
    return shape


def _reader_disagreements(path: str, document: ThriftDocument, shape: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Where Apiome's reader and thriftpy2 read the same file differently."""
    problems: List[Dict[str, Any]] = []

    def differ(message: str) -> None:
        problems.append(_problem("thrift.parser-disagreement", message, path))

    for enum in document.enums:
        theirs = shape["enums"].get(enum.name)
        ours = sorted(name for name, _ in enum.values)
        if theirs is None:
            differ(f"thriftpy2 does not read enum {enum.name!r}.")
        elif theirs != ours:
            differ(f"enum {enum.name!r}: the import reads members {ours}, thriftpy2 {theirs}.")
    for struct in document.structs:
        theirs = shape["structs"].get(struct.name)
        ours = {f.id: f.name for f in struct.fields}
        if theirs is None:
            differ(f"thriftpy2 does not read {struct.kind} {struct.name!r}.")
        elif theirs != (struct.kind, ours):
            differ(f"{struct.kind} {struct.name!r}: the import reads {struct.kind} fields {ours}, "
                   f"thriftpy2 {theirs[0]} fields {theirs[1]}.")
    for service in document.services:
        theirs = shape["services"].get(service.name)
        missing = sorted({m.name for m in service.methods} - (theirs or set()))
        if theirs is None:
            differ(f"thriftpy2 does not read service {service.name!r}.")
        elif missing:
            differ(f"service {service.name!r}: thriftpy2 does not read methods {missing}.")
    return problems


def spot_check_thrift(files: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Parse every file with thriftpy2 and check that it agrees with Apiome's Thrift reader.

    A file whose ``include`` names something outside the export is skipped — there is nothing to
    resolve it against, and the reader re-imports it on its own.

    Args:
        files: Every emitted file, path → text.

    Returns:
        The problems (``thrift.thriftpy2-parse`` / ``thrift.parser-disagreement``); empty when they agree.
    """
    from thriftpy2.parser import parse as thriftpy2_parse

    problems: List[Dict[str, Any]] = []
    checked = [path for path, text in files.items() if _includes_resolve(path, text, files)]
    if not checked:
        return problems
    with tempfile.TemporaryDirectory(prefix="apiome-thriftpy2-") as scratch:
        for path, text in files.items():
            target = os.path.join(scratch, *posixpath.normpath(path).split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(text)
        for index, path in enumerate(checked):
            target = os.path.join(scratch, *posixpath.normpath(path).split("/"))
            try:
                module = thriftpy2_parse(
                    target,
                    module_name=f"apiome_export_{index}_thrift",
                    include_dirs=[os.path.dirname(target)],
                    enable_cache=False,
                )
            except Exception as exc:  # noqa: BLE001 — any parse failure is "not valid Thrift", never a crash
                message = str(exc).replace(scratch + os.sep, "")
                problems.append(_problem("thrift.thriftpy2-parse", f"thriftpy2 cannot parse the IDL: {message}", path))
                continue
            try:
                document = parse_thrift(files[path], source_label=path, require_definitions=False)
            except ThriftParseError as exc:
                problems.append(_problem("thrift.reimport", f"The Thrift reader cannot parse the IDL: {exc}", path))
                continue
            problems.extend(_reader_disagreements(path, document, _thriftpy2_shape(module)))
    return problems


# ===========================================================================
# Re-import and round trip
# ===========================================================================


def reimport_thrift(emit_result: EmitResult) -> CanonicalApi:
    """Import a Thrift export the way an upload of it would be (one set when there are several files).

    Raises:
        ImportSourceError: When it does not parse or normalize.
    """
    try:
        return reimport_emitted(ThriftImportSource(), emit_result, multi_file=len(emit_result.files) > 1)
    except ImportSourceError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ImportSourceError(f"Malformed Thrift export: {exc}", code="INPUT_MALFORMED") from exc


async def round_trip_thrift(
    api: CanonicalApi,
    *,
    opts: Optional[Union[ThriftEmitOptions, EmitOptions]] = None,
    emit_result: Optional[EmitResult] = None,
) -> ThriftRoundTripReport:
    """Compile and spot-check the Thrift export of ``api``, import it again, and reconcile the difference.

    Args:
        api: The source canonical model.
        opts: The export options; the fidelity report is computed for them. When ``emit_result`` is
            given, pass the options it was emitted with.
        emit_result: An emission to use instead of emitting here.

    Returns:
        The :class:`ThriftRoundTripReport`.
    """
    emitter = ThriftEmitter()
    if emit_result is None:
        emit_result = emitter.emit(api, opts=opts)
    predicted = list(emit_result.losses)
    if not emit_result.files:
        return ThriftRoundTripReport(compiler="unavailable", predicted_losses=predicted,
                                     problems=[_problem("thrift.empty", "The Thrift export wrote no file.", None)])
    compiler, problems = await compile_problems(emit_result)
    files = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    problems.extend(spot_check_thrift(files))
    if problems:
        return ThriftRoundTripReport(compiler=compiler, problems=problems, predicted_losses=predicted)
    try:
        reimported = reimport_thrift(emit_result)
    except ImportSourceError as exc:
        return ThriftRoundTripReport(compiler=compiler, import_error=str(exc), predicted_losses=predicted)
    measured = canonical_diff(api, reimported)
    options = opts.model_dump() if opts is not None else None
    outcome = reconcile(measured, compute_lossiness_for_emitter(api, emitter, options=options))
    return ThriftRoundTripReport(
        compiler=compiler,
        reimported=True,
        diff=measured,
        unexplained=list(outcome.unexplained),
        overclaims=[item.construct_key for item in outcome.overclaims],
        predicted_losses=predicted,
    )
