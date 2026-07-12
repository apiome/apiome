"""Emitted-artifact validation — MFX-5.1 (#3852).

A buggy emitter could produce output that is *not* legal in its target format. This
module closes that hole: it feeds a freshly emitted artifact back through the **matching
MFI import parser/validator** and reports whether it parses. The export job (MFX-EPIC-3)
runs this after emit and **fails the job** when the artifact is invalid, so a broken
document never reaches delivery (MFX-4.x) — the MFX-5.1 acceptance criterion, "valid output
passes; deliberately broken output is caught".

It **reuses, does not rebuild** (the MFX-5.1 / MFX-2.6 directive). Every format already
ships a re-import path, and MFX-9.3 / 13.5 / 8.x wrapped three of them in an *emit → validate
→ re-import → diff* round-trip module whose :attr:`valid` verdict is *defined* as this
check. This module is the thin dispatcher that picks the matching validator per emitted
:attr:`~app.emitter.Emitter.format` and collapses each into one uniform
:class:`EmittedArtifactValidation` the job can gate on:

* ``openapi-3.1`` — :func:`app.openapi_roundtrip.round_trip_openapi` (meta-schema check +
  a genuine re-parse through :class:`app.openapi_import_source.OpenApiImportSource`);
* ``graphql`` — :func:`app.graphql_roundtrip.round_trip_graphql` (the MFI-10.1 ``build_schema``
  validation + GraphQL normalizer re-import; pure Python, always available);
* ``asyncapi-3`` — :func:`app.asyncapi_roundtrip.round_trip_asyncapi` (the authoritative
  ``@asyncapi/parser`` + AsyncAPI normalizer; needs the ``asyncapi-parser`` toolchain);
* ``avro`` — :func:`app.avro_emitter.validate_avro_schema` (``fastavro.parse_schema`` over
  every emitted ``.avsc`` with a shared named-schema registry; pure Python);
* ``proto3`` — :func:`app.proto_descriptor.compile_proto_descriptor_set` (the emitted
  ``.proto`` is compiled by ``buf``; needs the ``buf`` toolchain);
* ``sample-noop`` and any unregistered format — *not applicable* (the sample emitter is an
  internal no-op with no importable artifact).

**Honesty about what ran.** A toolchain-backed validator (AsyncAPI, protobuf) cannot run
when its tool is absent from the runtime (MFI-5.2). Rather than fail a *valid* export because
we could not check it, such a case is reported as :attr:`~EmittedArtifactValidation.validated`
``False`` with a reason — the job proceeds but records that the artifact was **not** re-parsed.
Only a validator that actually *ran and rejected* the artifact fails the job
(:attr:`~EmittedArtifactValidation.failed`).

Validation is read-only and (for the pure-Python validators) deterministic, so it is safe to
run on the export engine's event loop; the CPU-bound re-parses are dispatched to a worker
thread and the toolchain-backed ones are awaited.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitResult, EmittedFile

__all__ = [
    "EmittedArtifactValidation",
    "ValidationFinding",
    "validate_emitted_artifact",
]


class ValidationFinding(BaseModel):
    """One structured emitted-artifact validation failure (MFX-5.3).

    Carries the parser/toolchain detail UIs render — message, JSON-pointer path, bundle file,
    and line/column when the underlying validator provides them.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Human-readable failure description.")
    path: Optional[str] = Field(
        default=None,
        description="JSON Pointer or logical location within the artifact when provided.",
    )
    file: Optional[str] = Field(
        default=None,
        description="Bundle-relative file path when the failure is tied to one emitted file.",
    )
    line: Optional[int] = Field(default=None, description="1-based line number when available.")
    column: Optional[int] = Field(default=None, description="1-based column number when available.")
    keyword: Optional[str] = Field(
        default=None,
        description="Validator-specific rule keyword (e.g. a JSON Schema ``keyword``).",
    )


class EmittedArtifactValidation(BaseModel):
    """The verdict of re-validating one emitted artifact through its MFI parser (MFX-5.1).

    Collapses each format's re-import path into a single, uniform shape the export job can
    gate on. The four cases the job distinguishes:

    * **passed** — ``applicable`` and ``validated`` and ``valid``: the artifact re-parsed
      cleanly; the job proceeds.
    * **failed** — ``applicable`` and ``validated`` and not ``valid``: the matching parser
      rejected the artifact; the job fails (:attr:`failed`). ``errors`` carries the detail.
    * **skipped** — ``applicable`` but not ``validated``: a required toolchain was unavailable,
      so the artifact could not be re-parsed here; the job proceeds but records ``detail``.
    * **not applicable** — not ``applicable``: no importer matches the format (the sample
      no-op target); nothing to validate.
    """

    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="The resolved target format key that was validated (e.g. ``openapi-3.1``).")
    applicable: bool = Field(
        description="Whether a matching MFI import parser/validator is registered for this "
        "format. ``False`` for the internal sample no-op target and any unregistered format.",
    )
    validated: bool = Field(
        description="Whether validation actually ran. ``False`` when a required toolchain "
        "(``asyncapi-parser`` for AsyncAPI, ``buf`` for protobuf) is unavailable in this "
        "runtime, so the artifact could not be re-parsed — the export is *not* proven valid.",
    )
    valid: bool = Field(
        description="Whether the emitted artifact re-parsed cleanly through its matching "
        "parser. Meaningful only when ``validated`` is ``True``; ``True`` by convention "
        "otherwise (there is nothing to fail on).",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Human-readable failure detail from the parser. Non-empty only when the "
        "artifact was validated and found invalid. Mirrors :attr:`findings` as one-liners.",
    )
    findings: List[ValidationFinding] = Field(
        default_factory=list,
        description="Structured parser/toolchain failures for UI rendering (MFX-5.3). "
        "Non-empty only when the artifact was validated and found invalid.",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Why validation did not run (not applicable, or a toolchain was "
        "unavailable). ``None`` when validation ran.",
    )

    @property
    def failed(self) -> bool:
        """Whether a validator ran and rejected the artifact — the gate the export job fails on.

        A not-applicable or skipped validation is **not** a failure: the artifact was never
        proven invalid, so the job must not be failed on it.
        """
        return self.applicable and self.validated and not self.valid


# ===========================================================================
# Per-format validators — each reuses an existing re-import/validate facility
# ===========================================================================


def _passed(target: str) -> EmittedArtifactValidation:
    """A validator ran and accepted the artifact."""
    return EmittedArtifactValidation(target=target, applicable=True, validated=True, valid=True)


def _rejected(
    target: str,
    findings: List[ValidationFinding],
) -> EmittedArtifactValidation:
    """A validator ran and rejected the artifact, carrying its failure detail."""
    if not findings:
        findings = [
            ValidationFinding(
                message="The emitted artifact did not re-parse through its matching import parser."
            )
        ]
    errors = [_finding_to_line(f) for f in findings]
    return EmittedArtifactValidation(
        target=target,
        applicable=True,
        validated=True,
        valid=False,
        errors=errors,
        findings=findings,
    )


def _skipped(target: str, reason: str) -> EmittedArtifactValidation:
    """A validator matches the format but could not run (a toolchain was unavailable)."""
    return EmittedArtifactValidation(
        target=target, applicable=True, validated=False, valid=True, detail=reason
    )


def _not_applicable(target: str, reason: str) -> EmittedArtifactValidation:
    """No importer matches this format; there is nothing to re-validate."""
    return EmittedArtifactValidation(
        target=target, applicable=False, validated=False, valid=True, detail=reason
    )


def _finding_to_line(finding: ValidationFinding) -> str:
    """Render one structured finding as a human-readable one-liner (legacy ``errors`` list)."""
    location = finding.path or finding.file or ""
    if finding.line is not None:
        col = f":{finding.column}" if finding.column is not None else ""
        location = f"{location or finding.file or ''}:{finding.line}{col}".strip(":")
    if location:
        return f"{finding.message} ({location})".strip()
    return finding.message


def _findings_from_diagnostics(
    diagnostics: List[Dict[str, str]], *, file: Optional[str] = None
) -> List[ValidationFinding]:
    """Convert a parser's structured diagnostics into :class:`ValidationFinding` rows."""
    findings: List[ValidationFinding] = []
    for diag in diagnostics:
        message = diag.get("message") or ""
        if not message:
            continue
        line_raw = diag.get("line")
        column_raw = diag.get("column")
        findings.append(
            ValidationFinding(
                message=message,
                path=diag.get("path") or diag.get("locations"),
                file=file or diag.get("file"),
                line=int(line_raw) if line_raw and line_raw.isdigit() else None,
                column=int(column_raw) if column_raw and column_raw.isdigit() else None,
                keyword=diag.get("keyword"),
            )
        )
    return findings


def _finding_from_message(message: str, *, file: Optional[str] = None) -> ValidationFinding:
    """Build one finding from a free-form parser message."""
    return ValidationFinding(message=message, file=file)


def _findings_from_avro_errors(errors: List[str]) -> List[ValidationFinding]:
    """Parse Avro per-file errors of the form ``path.avsc: reason`` into findings."""
    findings: List[ValidationFinding] = []
    for error in errors:
        if ": " in error:
            file_path, message = error.split(": ", 1)
            findings.append(ValidationFinding(message=message, file=file_path))
        else:
            findings.append(ValidationFinding(message=error))
    return findings


async def _validate_openapi(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted OpenAPI document (meta-schema + MFI OpenAPI re-import)."""
    from .openapi_roundtrip import round_trip_openapi

    report = await asyncio.to_thread(round_trip_openapi, api, emit_result=emit_result)
    if report.valid:
        return _passed(target)
    findings = _findings_from_diagnostics(report.schema_errors)
    if report.import_error:
        findings.append(_finding_from_message(report.import_error))
    return _rejected(target, findings)


async def _validate_graphql(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted GraphQL SDL (MFI-10.1 ``build_schema`` + GraphQL re-import)."""
    from .graphql_roundtrip import round_trip_graphql

    report = await asyncio.to_thread(round_trip_graphql, api, emit_result=emit_result)
    if report.valid:
        return _passed(target)
    findings = _findings_from_diagnostics(report.validation_errors)
    if report.import_error:
        findings.append(_finding_from_message(report.import_error))
    return _rejected(target, findings)


async def _validate_asyncapi(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted AsyncAPI document (``@asyncapi/parser`` + AsyncAPI re-import).

    Needs the ``asyncapi-parser`` toolchain; when it is unavailable the artifact cannot be
    re-parsed here, so this reports *skipped* rather than failing a possibly-valid export.
    """
    from .asyncapi_parser import ASYNCAPI_PARSER_TOOL_KEY, AsyncApiParseError
    from .asyncapi_roundtrip import round_trip_asyncapi
    from .toolchain_runner import is_tool_available

    if not is_tool_available(ASYNCAPI_PARSER_TOOL_KEY):
        return _skipped(
            target,
            f"The {ASYNCAPI_PARSER_TOOL_KEY!r} toolchain is unavailable in this runtime; the "
            "emitted AsyncAPI artifact was not re-validated.",
        )
    try:
        report = await round_trip_asyncapi(api, emit_result=emit_result)
    except AsyncApiParseError as exc:
        # Infrastructure failure (tool vanished mid-flight / timed out) — the artifact is not
        # proven invalid, so skip rather than fail the export.
        return _skipped(
            target,
            f"The AsyncAPI parser could not run ({exc}); the emitted artifact was not re-validated.",
        )
    if report.valid:
        return _passed(target)
    findings = _findings_from_diagnostics(report.validation_errors)
    if report.import_error:
        findings.append(_finding_from_message(report.import_error))
    return _rejected(target, findings)


def _avro_fullname(content: object) -> Optional[str]:
    """Return the fully-qualified name of an emitted Avro schema (``namespace.name``)."""
    if not isinstance(content, dict):
        return None
    name = content.get("name")
    if not name:
        return None
    namespace = content.get("namespace")
    return f"{namespace}.{name}" if namespace else str(name)


async def _validate_avro(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate every emitted ``.avsc`` with ``fastavro`` (shared named-schema registry).

    Each named type is emitted to its own ``.avsc`` and may reference another by name, so a
    file cannot always be validated in isolation. This resolves the cross-file references the
    way the emitter's own ``render()`` does — validating with a shared registry and registering
    each schema once it parses — but **order-independently**: it iterates to a fixed point, so a
    valid bundle passes regardless of the emitted files' order, while a genuinely broken schema
    (or a dangling reference an emitter should never produce) never resolves and is reported.
    Pure Python (``fastavro``), so it always runs.
    """
    from .avro_emitter import validate_avro_schema

    def _run() -> List[str]:
        named_schemas: Dict[str, object] = {}
        pending = list(emit_result.files)
        while True:
            unresolved: List[EmittedFile] = []
            errors: List[str] = []
            progressed = False
            for emitted in pending:
                try:
                    validate_avro_schema(emitted.content, named_schemas=named_schemas)
                except (ValueError, TypeError) as exc:
                    unresolved.append(emitted)
                    errors.append(f"{emitted.path}: {exc}")
                    continue
                fullname = _avro_fullname(emitted.content)
                if fullname is not None:
                    named_schemas[fullname] = emitted.content
                progressed = True
            if not unresolved:
                return []
            if not progressed:
                # A full pass registered nothing new: the remainder are genuine failures
                # (invalid schema or an unresolvable reference), not an ordering artifact.
                return errors
            pending = unresolved

    errors = await asyncio.to_thread(_run)
    return _passed(target) if not errors else _rejected(target, _findings_from_avro_errors(errors))


async def _validate_proto(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted ``.proto`` by compiling it with ``buf`` (MFI-9.1).

    Needs the ``buf`` toolchain; when it is unavailable the artifact cannot be compiled here,
    so this reports *skipped* rather than failing a possibly-valid export.
    """
    from .proto_descriptor import (
        BUF_TOOL_KEY,
        ProtoCompileError,
        ProtoFile,
        compile_proto_descriptor_set,
    )
    from .toolchain_runner import is_tool_available

    if not is_tool_available(BUF_TOOL_KEY):
        return _skipped(
            target,
            f"The {BUF_TOOL_KEY!r} toolchain is unavailable in this runtime; the emitted "
            "protobuf artifact was not re-validated.",
        )
    files = [ProtoFile(path=f.path, content=str(f.content)) for f in emit_result.files]
    try:
        await compile_proto_descriptor_set(files)
    except ProtoCompileError as exc:
        diagnostics = getattr(exc, "diagnostics", None)
        findings = [_finding_from_message(str(exc))]
        if diagnostics:
            findings.append(_finding_from_message(str(diagnostics)))
        return _rejected(target, findings)
    return _passed(target)


# emitter ``format`` key → the validator that re-parses its output through the matching MFI
# importer. A format absent here has no importable artifact (the sample no-op) and is reported
# not-applicable. Keyed by the resolved emitter format so it tracks the emitter registry.
_Validator = Callable[[str, EmitResult, CanonicalApi], Awaitable[EmittedArtifactValidation]]

async def _validate_asn1(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted ASN.1 module with ``asn1tools``."""
    from .asn1_emitter import validate_asn1_module

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_asn1_module(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_edix12(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted EDI X12 interchange with ``pyx12``."""
    from .edix12_emitter import validate_edix12_interchange

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_edix12_interchange(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_oncrpc(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted ONC RPC / XDR ``.x`` document by re-parsing it."""
    from .oncrpc_emitter import validate_oncrpc_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_oncrpc_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_corbaidl(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted CORBA / OMG IDL ``.idl`` document by re-parsing it."""
    from .corbaidl_emitter import validate_corbaidl_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_corbaidl_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_odata(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted OData EDMX / CSDL document by re-parsing it."""
    from .odata_emitter import validate_odata_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_odata_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_fhir(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted FHIR JSON document by re-parsing it."""
    from .fhir_emitter import validate_fhir_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_fhir_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_typespec(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted TypeSpec `.tsp` document by re-parsing it."""
    from .typespec_emitter import validate_typespec_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_typespec_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_hl7v2(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted HL7 v2 message by re-parsing it."""
    from .hl7v2_emitter import validate_hl7v2_message

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_hl7v2_message(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_iso20022(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted ISO 20022 XML document by re-parsing it."""
    from .iso20022_emitter import validate_iso20022_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_iso20022_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_iso8583(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted ISO 8583 JSON document by re-parsing it."""
    from .iso8583_emitter import validate_iso8583_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_iso8583_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


async def _validate_cobolcopybook(
    target: str, emit_result: EmitResult, api: CanonicalApi
) -> EmittedArtifactValidation:
    """Re-validate an emitted COBOL copybook by re-parsing it."""
    from .cobolcopybook_emitter import validate_cobolcopybook_document

    errors: List[str] = []
    for emitted in emit_result.files:
        try:
            validate_cobolcopybook_document(str(emitted.content))
        except Exception as exc:
            errors.append(f"{emitted.path}: {exc}")
    return _passed(target) if not errors else _rejected(target, [_finding_from_message(err) for err in errors])


_VALIDATORS: Dict[str, _Validator] = {
    "openapi-3.1": _validate_openapi,
    "graphql": _validate_graphql,
    "asyncapi-3": _validate_asyncapi,
    "avro": _validate_avro,
    "proto3": _validate_proto,
    "asn1": _validate_asn1,
    "edix12": _validate_edix12,
    "oncrpc": _validate_oncrpc,
    "corbaidl": _validate_corbaidl,
    "odata": _validate_odata,
    "fhir": _validate_fhir,
    "typespec": _validate_typespec,
    "hl7v2": _validate_hl7v2,
    "iso20022": _validate_iso20022,
    "iso8583": _validate_iso8583,
    "cobolcopybook": _validate_cobolcopybook,
}


async def validate_emitted_artifact(
    target_format: str,
    emit_result: EmitResult,
    *,
    api: CanonicalApi,
) -> EmittedArtifactValidation:
    """Re-validate an emitted artifact through its matching MFI import parser (MFX-5.1).

    Picks the validator registered for ``target_format`` and runs it over ``emit_result``,
    returning a uniform :class:`EmittedArtifactValidation`. A format with no matching importer
    (the sample no-op target, or any unregistered format) is reported *not applicable* and is
    never a failure.

    Args:
        target_format: The resolved emitter format key of the emitted artifact (e.g.
            ``openapi-3.1``), selecting the matching parser.
        emit_result: The emitter's output bundle to re-validate.
        api: The source canonical model the artifact was emitted from — the round-trip
            validators re-import the artifact and reuse ``api`` as the diff baseline.

    Returns:
        The :class:`EmittedArtifactValidation` verdict. A caller gates delivery on
        :attr:`EmittedArtifactValidation.failed` (a validator ran and rejected the artifact).
    """
    validator = _VALIDATORS.get(target_format)
    if validator is None:
        return _not_applicable(
            target_format,
            f"No import parser matches the {target_format!r} target; the emitted artifact "
            "was not re-validated.",
        )
    return await validator(target_format, emit_result, api)
