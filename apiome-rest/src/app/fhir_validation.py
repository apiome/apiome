"""FHIR export validation — MFX-26.1 (#4157).

Two layers, so an export is checked wherever it runs:

1. **The official HL7 FHIR validator** (toolchain tool ``fhir-validator``: ``validator_cli`` with the R4 and R5
   core packages cached in the image, :data:`FHIR_VALIDATOR_TOOL_KEY`). :func:`validate_with_fhir_validator`
   writes the emitted resources to a private directory, runs ``fhir-validator <files> -version 4.0.1|5.0.0
   -tx n/a -output <outcome.json>`` and reads the ``OperationOutcome`` (a ``Bundle`` of them for several
   files): each ``error`` / ``fatal`` issue is a finding. Terminology is checked offline (``-tx n/a``).
2. **Apiome's structural FHIR rules** (:func:`structural_issues`), used when the validator is not installed:
   the required elements, codes and patterns the FHIR specification sets for the resources this export
   writes — StructureDefinition (logical models), ValueSet, CodeSystem, CapabilityStatement and Bundle —
   element ids / paths, cardinality, bindings to ValueSets that exist, and constraint keys.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .import_source import ImportSourceError
from .toolchain_runner import ToolchainError, ToolExecutionError, ToolNotAvailableError, run_tool_blocking

__all__ = [
    "FHIR_VALIDATOR_TOOL_KEY",
    "FhirValidationIssue",
    "fhir_validator_available",
    "structural_issues",
    "structural_problems",
    "validate_with_fhir_validator",
]

FHIR_VALIDATOR_TOOL_KEY = "fhir-validator"
_TIMEOUT_SECONDS = 300.0
_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
_NAME_RE = re.compile(r"^[A-Z]([A-Za-z0-9_]){0,254}$")
_CODE_RE = re.compile(r"^[^\s]+( [^\s]+)*$")
_PATH_SEGMENT_RE = re.compile(r"^[^\s.,:;'\"/|?!@#$%&*()\[\]{}]{1,64}$")
_STATUS = frozenset({"draft", "active", "retired", "unknown"})
_VERSIONS = frozenset({"4.0.1", "5.0.0"})
_STRENGTHS = frozenset({"required", "extensible", "preferred", "example"})
_BUNDLE_TYPES = frozenset({"collection", "document", "searchset", "transaction", "batch", "history", "message",
                           "transaction-response", "batch-response", "subscription-notification"})


@dataclass(frozen=True)
class FhirValidationIssue:
    """One error the FHIR validator reported.

    Attributes:
        message: The validator's diagnostics.
        file: The emitted file it concerns, when known.
        location: The FHIRPath / JSON location of the issue, when given.
        code: The issue type (``structure``, ``invariant``, ``required`` …).
    """

    message: str
    file: Optional[str] = None
    location: Optional[str] = None
    code: Optional[str] = None


def fhir_validator_available() -> bool:
    """Whether the ``fhir-validator`` tool resolves in this runtime."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(FHIR_VALIDATOR_TOOL_KEY)
    return bool(probe and probe.available)


def validate_with_fhir_validator(members: Mapping[str, str], version: str) -> List[FhirValidationIssue]:
    """Validate emitted FHIR JSON files with the official validator.

    Args:
        members: Emitted file path → JSON text.
        version: ``4.0.1`` or ``5.0.0``.

    Returns:
        The ``error`` and ``fatal`` issues (warnings and information are not returned).

    Raises:
        ImportSourceError: ``ADAPTER_UNAVAILABLE`` when the tool is not installed; ``INPUT_MALFORMED`` when
            it fails without writing an OperationOutcome.
    """
    work = Path(tempfile.mkdtemp(prefix="apiome-fhir-"))
    try:
        files: Dict[str, str] = {}
        for index, (path, text) in enumerate(members.items()):
            local = work / f"{index:03d}-{Path(path).name}"
            local.write_text(text, encoding="utf-8")
            files[str(local)] = path
        outcome_path = work / "outcome.json"
        args = [*files, "-version", version, "-tx", "n/a", "-output", str(outcome_path)]
        try:
            run_tool_blocking(FHIR_VALIDATOR_TOOL_KEY, args, timeout=_TIMEOUT_SECONDS, thread_name="fhir-validator",
                              cwd=str(work), extra_env={"HOME": str(work)})
        except ToolNotAvailableError as exc:
            raise ImportSourceError("The FHIR validator is not installed on this server.",
                                    code="ADAPTER_UNAVAILABLE") from exc
        except ToolExecutionError:
            # The validator exits non-zero when it finds errors; the OperationOutcome holds them.
            pass
        except ToolchainError as exc:
            raise ImportSourceError(f"The FHIR validator failed: {exc}", code="INPUT_MALFORMED") from exc
        if not outcome_path.is_file():
            raise ImportSourceError("The FHIR validator wrote no OperationOutcome.", code="INPUT_MALFORMED")
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        return _outcome_issues(outcome, files)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _outcome_issues(outcome: Mapping[str, Any], files: Mapping[str, str]) -> List[FhirValidationIssue]:
    """The ``error`` / ``fatal`` issues of an OperationOutcome, or of each one in a Bundle."""
    outcomes = ([entry.get("resource") or {} for entry in outcome.get("entry") or []]
                if outcome.get("resourceType") == "Bundle" else [outcome])
    issues: List[FhirValidationIssue] = []
    for item in outcomes:
        source = _outcome_file(item, files)
        for issue in item.get("issue") or []:
            if issue.get("severity") not in ("error", "fatal"):
                continue
            locations = issue.get("expression") or issue.get("location") or []
            issues.append(FhirValidationIssue(
                message=issue.get("diagnostics") or (issue.get("details") or {}).get("text") or "FHIR validation error",
                file=source,
                location=locations[0] if locations else None,
                code=issue.get("code"),
            ))
    return issues


def _outcome_file(outcome: Mapping[str, Any], files: Mapping[str, str]) -> Optional[str]:
    for extension in outcome.get("extension") or []:
        value = extension.get("valueString")
        if isinstance(value, str):
            for local, original in files.items():
                if value.endswith(Path(local).name):
                    return original
    return next(iter(files.values()), None) if len(files) == 1 else None


# ===========================================================================
# Structural rules
# ===========================================================================


def structural_problems(path: str, text: str) -> List[Dict[str, Any]]:
    """Check one emitted FHIR file without the validator — MFX-26.4 (#4160).

    The fallback the export gate uses when the official validator is not in this runtime: each broken
    structural rule is one problem (``fhir.structure``) carrying the resource path it is at, so a fallback
    rejection names every issue the way the validator's ``OperationOutcome`` would. A file that is not
    JSON is ``fhir.json``; one that the FHIR reader cannot read back is ``fhir.reimport``.

    Args:
        path: The file's export path.
        text: Its JSON text.

    Returns:
        ``{"rule", "message", "file", "path"}`` dicts; empty when the file is sound.
    """
    from .fhir_parser import parse_fhir

    try:
        document = json.loads(text)
    except ValueError as exc:
        return [{"rule": "fhir.json", "message": f"Not JSON: {exc}", "file": path, "path": None}]
    problems = []
    for issue in structural_issues(document):
        location, _, message = issue.partition(": ")
        problems.append({"rule": "fhir.structure", "message": message or issue, "file": path,
                         "path": location if message else None})
    if not problems:
        try:
            parse_fhir(text, source_label=path)
        except Exception as exc:  # noqa: BLE001 — any reader failure means "does not read back"
            problems.append({"rule": "fhir.reimport", "message": f"The FHIR reader cannot read it: {exc}",
                             "file": path, "path": None})
    return problems


def structural_issues(document: Any) -> List[str]:
    """Apiome's structural FHIR rules for an emitted resource or Bundle.

    Args:
        document: A FHIR resource (``StructureDefinition``, ``ValueSet``, ``CodeSystem``,
            ``CapabilityStatement``) or a ``collection`` ``Bundle`` of them.

    Returns:
        One message per broken rule (``<resource>/<path>: <rule>``); empty when the document is sound.
        Resource kinds this export does not write (a resource instance) are only checked for
        ``resourceType``.
    """
    if not isinstance(document, Mapping) or not isinstance(document.get("resourceType"), str):
        return ["(root): a FHIR resource needs a resourceType"]
    if document["resourceType"] == "Bundle":
        issues = []
        if document.get("type") not in _BUNDLE_TYPES:
            issues.append("Bundle/type: a Bundle needs a valid type")
        resources = [entry.get("resource") for entry in document.get("entry") or [] if isinstance(entry, Mapping)]
        value_sets = {r.get("url") for r in resources if isinstance(r, Mapping) and r.get("resourceType") == "ValueSet"}
        for index, entry in enumerate(document.get("entry") or []):
            resource = entry.get("resource") if isinstance(entry, Mapping) else None
            if entry.get("fullUrl") is not None and not str(entry["fullUrl"]).startswith(("http://", "https://",
                                                                                            "urn:")):
                issues.append(f"Bundle/entry[{index}]/fullUrl: must be an absolute URL")
            issues += [f"Bundle/entry[{index}]/{issue}" for issue in _resource_issues(resource, value_sets)]
        return issues
    return _resource_issues(document, None)


def _resource_issues(resource: Any, value_sets: Optional[set]) -> List[str]:
    if not isinstance(resource, Mapping) or not isinstance(resource.get("resourceType"), str):
        return ["resource: missing resourceType"]
    kind = resource["resourceType"]
    checks = {"StructureDefinition": _structure_issues, "ValueSet": _value_set_issues,
              "CodeSystem": _code_system_issues, "CapabilityStatement": _capability_issues}
    issues = []
    if "id" in resource and not _ID_RE.match(str(resource["id"])):
        issues.append(f"{kind}/id: {resource['id']!r} is not a FHIR id")
    if kind in checks:
        issues += _canonical_issues(resource) + checks[kind](resource, value_sets)
    return [issue if issue.startswith(kind) else f"{kind}/{issue}" for issue in issues]


def _canonical_issues(resource: Mapping[str, Any]) -> List[str]:
    issues = []
    kind = resource["resourceType"]
    url = resource.get("url")
    if kind in ("StructureDefinition", "ValueSet", "CodeSystem") and not (isinstance(url, str) and "://" in url):
        issues.append(f"{kind}/url: an absolute canonical URL is required")
    if resource.get("status") not in _STATUS:
        issues.append(f"{kind}/status: one of {sorted(_STATUS)} is required")
    name = resource.get("name")
    if kind in ("StructureDefinition", "CapabilityStatement") and not isinstance(name, str):
        issues.append(f"{kind}/name: required")
    elif isinstance(name, str) and not _NAME_RE.match(name):
        issues.append(f"{kind}/name: {name!r} is not a computable name")
    return issues


def _structure_issues(resource: Mapping[str, Any], value_sets: Optional[set]) -> List[str]:
    issues = []
    for key in ("kind", "type", "abstract"):
        if key not in resource:
            issues.append(f"StructureDefinition/{key}: required")
    if resource.get("kind") not in ("primitive-type", "complex-type", "resource", "logical"):
        issues.append("StructureDefinition/kind: invalid")
    if resource.get("fhirVersion") is not None and resource["fhirVersion"] not in _VERSIONS:
        issues.append("StructureDefinition/fhirVersion: 4.0.1 or 5.0.0 expected")
    if resource.get("derivation") is not None and not resource.get("baseDefinition"):
        issues.append("StructureDefinition/baseDefinition: required with a derivation")
    elements = ((resource.get("differential") or {}).get("element") or
                (resource.get("snapshot") or {}).get("element") or [])
    if not elements:
        issues.append("StructureDefinition: a differential or snapshot with elements is required (sdf-6)")
        return issues
    root = str(resource.get("type", "")).rstrip("/").rsplit("/", 1)[-1]
    seen = set()
    for index, element in enumerate(elements):
        where = f"StructureDefinition/differential/element[{index}]"
        path = element.get("path")
        if not isinstance(path, str) or not all(_PATH_SEGMENT_RE.match(p.removesuffix("[x]"))
                                                for p in path.split(".")):
            issues.append(f"{where}/path: {path!r} is not a valid element path (eld-19)")
            continue
        if resource.get("kind") == "logical" and path.split(".")[0] != root:
            issues.append(f"{where}/path: must start with {root!r}, the type's name")
        if element.get("id") is not None and element["id"] != path:
            issues.append(f"{where}/id: must equal the path for an element without slices")
        if path in seen:
            issues.append(f"{where}/path: {path!r} is repeated")
        seen.add(path)
        # A profile's differential is sparse; a logical model's declares its whole tree.
        logical = resource.get("kind") == "logical"
        if logical and index and "." in path and path.rsplit(".", 1)[0] not in seen:
            issues.append(f"{where}/path: its parent {path.rsplit('.', 1)[0]!r} is not declared before it")
        minimum, maximum = element.get("min"), element.get("max")
        if minimum is not None and (not isinstance(minimum, int) or minimum < 0):
            issues.append(f"{where}/min: a non-negative integer is required")
        if maximum is not None and not (maximum == "*" or (isinstance(maximum, str) and maximum.isdigit())):
            issues.append(f"{where}/max: '*' or a number as a string is required")
        if isinstance(minimum, int) and isinstance(maximum, str) and maximum.isdigit() and minimum > int(maximum):
            issues.append(f"{where}: min > max (eld-2)")
        if logical and index and not element.get("type") and not any(
                e.get("path", "").startswith(f"{path}.") for e in elements):
            issues.append(f"{where}/type: an element with no children needs a type")
        for type_ in element.get("type") or []:
            if not isinstance(type_.get("code"), str) or not type_["code"]:
                issues.append(f"{where}/type: each type needs a code")
        binding = element.get("binding")
        if binding is not None:
            if binding.get("strength") not in _STRENGTHS:
                issues.append(f"{where}/binding/strength: required")
            if value_sets is not None and binding.get("valueSet") and binding["valueSet"] not in value_sets:
                issues.append(f"{where}/binding/valueSet: {binding['valueSet']!r} is not in the bundle")
        for constraint in element.get("constraint") or []:
            if not (constraint.get("key") and constraint.get("severity") and constraint.get("human")):
                issues.append(f"{where}/constraint: key, severity and human are required")
            if not _ID_RE.match(str(constraint.get("key", ""))):
                issues.append(f"{where}/constraint/key: {constraint.get('key')!r} is not a valid key")
        if element.get("maxLength") is not None and (not isinstance(element["maxLength"], int)
                                                     or element["maxLength"] < 0):
            issues.append(f"{where}/maxLength: a non-negative integer is required")
    return issues


def _value_set_issues(resource: Mapping[str, Any], _: Optional[set]) -> List[str]:
    issues = []
    for include in (resource.get("compose") or {}).get("include") or []:
        if not include.get("system") and not include.get("valueSet"):
            issues.append("ValueSet/compose/include: a system or valueSet is required (vsd-1)")
    return issues


def _code_system_issues(resource: Mapping[str, Any], _: Optional[set]) -> List[str]:
    issues = []
    if resource.get("content") not in ("not-present", "example", "fragment", "complete", "supplement"):
        issues.append("CodeSystem/content: required")
    codes = set()
    for concept in resource.get("concept") or []:
        code = concept.get("code")
        if not isinstance(code, str) or not _CODE_RE.match(code):
            issues.append(f"CodeSystem/concept: {code!r} is not a valid code")
        elif code in codes:
            issues.append(f"CodeSystem/concept: {code!r} is repeated (csd-1)")
        codes.add(code)
    return issues


def _capability_issues(resource: Mapping[str, Any], _: Optional[set]) -> List[str]:
    issues = []
    for key in ("date", "kind", "fhirVersion", "format"):
        if not resource.get(key):
            issues.append(f"CapabilityStatement/{key}: required")
    if resource.get("kind") == "capability" and not resource.get("software"):
        issues.append("CapabilityStatement/software: required when kind is capability (cpb-15)")
    if not (resource.get("rest") or resource.get("messaging") or resource.get("document")):
        issues.append("CapabilityStatement: rest, messaging or document is required (cpb-1)")
    return issues
