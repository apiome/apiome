"""Self-verification evidence of a provider contract — PFX-2.4 (#6928). Pure: no database, no HTTP.

A provider contract (PFX-2.1) is the provider's word about its own API. Bi-directional testing
(PFX-2.3) compares consumer pacts with that word, so the comparison is only as good as the word:
**a provider contract is trusted only when evidence says the provider matches it.** That evidence
rides on the publish request in ``verificationResults`` and is read here into one
:class:`Evidence` — what kind of report it is, which tool wrote it, the SHA-256 of what was sent,
what it counted, and a status:

* ``verified`` — the report was read, it executed tests, and none failed or errored;
* ``failed`` — the report records failed or errored tests, or the publisher said it failed;
* ``inconclusive`` — evidence was sent but proves nothing Apiome can rely on: a report Apiome cannot
  read (``text/plain``, a JSON shape it does not know), a report that executed no tests, a run that
  did not finish, or an Apiome report about a different version than the contract;
* ``missing`` — nothing was sent.

Anything but ``verified`` makes the provider contract **unverified**: its bi-directional verdicts
read ``unverified`` and, under the ``fail`` policy, fail (:func:`apply_evidence_policy` in
:mod:`app.bidirectional_verification`).

**What is read** (one worked example per tool is on the docs page ``bi-directional.mdx``):

* **JUnit XML** — Schemathesis (``--report junit``), Dredd (``--reporter xunit``), Newman
  (``-r junit``) and any other JUnit writer. Test cases are counted from the ``<testcase>``
  elements, never from the suite attributes (Newman leaves ``failures`` off the root and Dredd
  writes ``skip`` instead of ``skipped``).
* **Newman JSON** (``newman run -r json``) — ``run.stats`` and ``run.failures``.
* **Schemathesis NDJSON** (``--report ndjson``) — one ``ScenarioFinished`` event per scenario,
  and the ``EngineFinished`` event that says the run completed.
* **An Apiome provider-verification report** (CTG-4.3), named by ``providerVerificationReportId``
  — a run of Apiome's own verifier against a registered verification target.

**Nothing is dropped silently.** Input Apiome refuses — over the size limit, a media type no
report is written in, content that is not what its media type says (XML that does not parse, JSON
that is not JSON), XML with a DTD — is a :class:`~app.provider_contract.ProviderContractError`
with a pointer into the request. Input it accepts but cannot interpret is stored as
``inconclusive`` with the reason.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from .provider_contract import CODE_REQUEST_INVALID, ProviderContractError

__all__ = [
    "CODE_EVIDENCE_INVALID",
    "CODE_EVIDENCE_REPORT_NOT_FOUND",
    "CODE_EVIDENCE_TOO_LARGE",
    "CODE_EVIDENCE_UNSUPPORTED",
    "KIND_APIOME_REPORT",
    "KIND_JUNIT",
    "KIND_NEWMAN_JSON",
    "KIND_SCHEMATHESIS_NDJSON",
    "KIND_UNREADABLE",
    "STATUS_FAILED",
    "STATUS_INCONCLUSIVE",
    "STATUS_MISSING",
    "STATUS_VERIFIED",
    "SUPPORTED_CONTENT_TYPES",
    "ContractSource",
    "Evidence",
    "EvidenceSummary",
    "decode_report",
    "evidence_from_conformance_report",
    "evidence_of",
    "missing_evidence",
    "read_uploaded_report",
    "unsent_evidence",
]

# Stable refusal codes. A client branches on these, never on the message.
CODE_EVIDENCE_INVALID = "provider-contract-evidence-invalid"
CODE_EVIDENCE_TOO_LARGE = "provider-contract-evidence-too-large"
CODE_EVIDENCE_UNSUPPORTED = "provider-contract-evidence-unsupported"
CODE_EVIDENCE_REPORT_NOT_FOUND = "provider-contract-evidence-report-not-found"

#: Evidence statuses. Only ``verified`` makes a provider contract trusted.
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_MISSING = "missing"

#: Evidence kinds: what the report is.
KIND_JUNIT = "junit"
KIND_NEWMAN_JSON = "newman-json"
KIND_SCHEMATHESIS_NDJSON = "schemathesis-ndjson"
KIND_APIOME_REPORT = "apiome-provider-verification"
KIND_UNREADABLE = "unreadable"

#: Tools Apiome recognises by name. Any other ``verifier`` is kept as sent.
TOOL_SCHEMATHESIS = "schemathesis"
TOOL_DREDD = "dredd"
TOOL_NEWMAN = "newman"
TOOL_JUNIT = "junit"
TOOL_APIOME = "apiome-provider-verifier"

#: Where the report sits in the publish request, for refusals.
_POINTER = "/verificationResults/content"
_POINTER_TYPE = "/verificationResults/contentType"

#: The media types a report may be sent as, by how it is read. Parameters are ignored.
_XML_TYPES = frozenset({"application/xml", "text/xml", "application/junit+xml"})
_JSON_TYPES = frozenset({"application/json", "text/json"})
_NDJSON_TYPES = frozenset(
    {
        "application/x-ndjson",
        "application/ndjson",
        "application/jsonl",
        "application/x-jsonlines",
        "application/jsonlines",
    }
)
_TEXT_TYPES = frozenset({"text/plain"})
SUPPORTED_CONTENT_TYPES = tuple(sorted(_XML_TYPES | _JSON_TYPES | _NDJSON_TYPES | _TEXT_TYPES))

#: Schemathesis ``ScenarioFinished`` statuses and what they count as.
_SCHEMATHESIS_STATUS = {"success": "passed", "failure": "failed", "error": "errors", "skip": "skipped"}

#: How a reader of the evidence is told what to send instead of something unreadable.
_READABLE_HINT = (
    "send JUnit XML (Schemathesis --report junit, Dredd --reporter xunit, Newman -r junit), "
    "Newman JSON (-r json) or Schemathesis NDJSON (--report ndjson)"
)


# ---------------------------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSummary:
    """What a report counted.

    Attributes:
        tests: Test cases (scenarios, assertions) the report accounts for.
        passed: Those that passed.
        failed: Those that failed: the provider disagreed with its contract.
        errors: Those that errored: the check itself could not complete.
        skipped: Those deliberately not run.
    """

    tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    @property
    def executed(self) -> int:
        """Test cases that ran (were not skipped)."""
        return self.tests - self.skipped

    def to_dict(self) -> Dict[str, int]:
        """Serialize for storage and the API (camelCase)."""
        return {
            "tests": self.tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class Evidence:
    """The self-verification evidence of one provider contract, read.

    Attributes:
        status: :data:`STATUS_VERIFIED`, :data:`STATUS_FAILED`, :data:`STATUS_INCONCLUSIVE` or
            :data:`STATUS_MISSING`.
        kind: What the report is (:data:`KIND_JUNIT`, :data:`KIND_NEWMAN_JSON`,
            :data:`KIND_SCHEMATHESIS_NDJSON`, :data:`KIND_APIOME_REPORT`,
            :data:`KIND_UNREADABLE`); ``None`` when nothing was sent.
        tool: The tool that wrote it (``schemathesis``, ``dredd``, ``newman``, ``junit`` for an
            unnamed JUnit writer, ``apiome-provider-verifier``, or the ``verifier`` as sent).
        tool_version: That tool's version, from the report or the request.
        digest: ``sha256:<hex>`` of the report as sent (of the stored report, for an Apiome one).
        content_type: The media type the report was read as.
        summary: What the report counted; ``None`` when it could not be read.
        reasons: Why the evidence is not ``verified``; empty when it is.
        notes: What a reader should know even when it is (a ``verifier`` that disagrees with the
            report, an inline contract Apiome could not tie to an Apiome report).
        report_id: For :data:`KIND_APIOME_REPORT`: the report.
        target: For :data:`KIND_APIOME_REPORT`: the verification target's ``slug`` and
            ``environment`` at run time.
        coverage: For :data:`KIND_APIOME_REPORT`: ``operationsTotal``, ``operationsExercised``
            and ``percent``.
    """

    status: str
    kind: Optional[str] = None
    tool: Optional[str] = None
    tool_version: Optional[str] = None
    digest: Optional[str] = None
    content_type: Optional[str] = None
    summary: Optional[EvidenceSummary] = None
    reasons: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    report_id: Optional[str] = None
    target: Optional[Dict[str, str]] = None
    coverage: Optional[Dict[str, Any]] = None

    @property
    def verified(self) -> bool:
        """Whether the evidence makes the provider contract trusted."""
        return self.status == STATUS_VERIFIED

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage and the API (camelCase, unset fields left out)."""
        payload: Dict[str, Any] = {
            "status": self.status,
            "kind": self.kind,
            "tool": self.tool,
            "toolVersion": self.tool_version,
            "digest": self.digest,
            "contentType": self.content_type,
            "summary": self.summary.to_dict() if self.summary is not None else None,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "reportId": self.report_id,
            "target": self.target,
            "coverage": self.coverage,
        }
        return {key: value for key, value in payload.items() if value is not None and value != []}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Evidence":
        """Read evidence back from what :meth:`to_dict` stored.

        Args:
            payload: The stored ``evidence`` object.

        Returns:
            The evidence. An unknown ``status`` reads as ``inconclusive``.
        """
        status = payload.get("status")
        if status not in (STATUS_VERIFIED, STATUS_FAILED, STATUS_INCONCLUSIVE, STATUS_MISSING):
            status = STATUS_INCONCLUSIVE
        summary = payload.get("summary")
        return cls(
            status=str(status),
            kind=payload.get("kind"),
            tool=payload.get("tool"),
            tool_version=payload.get("toolVersion"),
            digest=payload.get("digest"),
            content_type=payload.get("contentType"),
            summary=EvidenceSummary(**{k: int(summary.get(k) or 0) for k in EvidenceSummary.__dataclass_fields__})
            if isinstance(summary, Mapping)
            else None,
            reasons=tuple(str(r) for r in payload.get("reasons") or ()),
            notes=tuple(str(n) for n in payload.get("notes") or ()),
            report_id=payload.get("reportId"),
            target=payload.get("target"),
            coverage=payload.get("coverage"),
        )


def missing_evidence() -> Evidence:
    """The evidence of a contract published without ``verificationResults``."""
    return Evidence(
        status=STATUS_MISSING,
        reasons=("no self-verification results were published with the provider contract",),
    )


def unsent_evidence(success: bool, *, verifier: Optional[str], verifier_version: Optional[str]) -> Evidence:
    """The evidence of ``verificationResults`` that carry a success flag and no report.

    A flag alone is the publisher's claim, not evidence: ``success: true`` without a report is
    ``inconclusive``; ``success: false`` is taken at its word and ``failed``.

    Args:
        success: The flag sent.
        verifier: The tool named, if any.
        verifier_version: Its version, if any.

    Returns:
        The evidence.
    """
    if not success:
        return Evidence(
            status=STATUS_FAILED,
            tool=_tool_name(verifier),
            tool_version=verifier_version,
            reasons=("the publisher reported that the self-verification failed (success: false)",),
        )
    return Evidence(
        status=STATUS_INCONCLUSIVE,
        tool=_tool_name(verifier),
        tool_version=verifier_version,
        reasons=(
            "success: true was sent without a report, and a success flag alone is not evidence — "
            "send the report in content or name an Apiome report in providerVerificationReportId",
        ),
    )


# ---------------------------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------------------------


def _decide(summary: EvidenceSummary, success: Optional[bool], extra: Iterable[str] = ()) -> Tuple[str, List[str]]:
    """The status a read report earns, and the reasons when it is not ``verified``.

    Args:
        summary: What the report counted.
        success: The publisher's flag, when sent.
        extra: Reasons the reader already found (a run that did not finish).

    Returns:
        ``(status, reasons)``. Failures win over everything; then the publisher's ``false``; then
        a report with nothing executed, or a reader's own reason, is ``inconclusive``.
    """
    reasons: List[str] = []
    if summary.failed or summary.errors:
        message = f"the report records {summary.failed} failed and {summary.errors} errored of {summary.tests} tests"
        if success:
            message += " although success: true was sent"
        return STATUS_FAILED, [message]
    if success is False:
        return STATUS_FAILED, [
            "the publisher reported that the self-verification failed (success: false), though the report "
            "records no failures"
        ]
    reasons.extend(extra)
    if summary.executed <= 0:
        reasons.append(f"the report executed no tests ({summary.tests} recorded, {summary.skipped} skipped)")
    if reasons:
        return STATUS_INCONCLUSIVE, reasons
    return STATUS_VERIFIED, []


def _tool_name(verifier: Optional[str]) -> Optional[str]:
    """The ``verifier`` as a tool name: trimmed and lower-cased, ``None`` when blank."""
    text = (verifier or "").strip().lower()
    return text or None


def _media_type(content_type: Optional[str]) -> str:
    """The media type without parameters, lower-cased; empty when none was sent."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def _digest(raw: bytes) -> str:
    """``sha256:<hex>`` of some bytes."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _invalid(message: str, pointer: str = _POINTER) -> ProviderContractError:
    """A 422 for a report that is not what it says it is."""
    return ProviderContractError(CODE_EVIDENCE_INVALID, message, pointer=pointer)


# ---------------------------------------------------------------------------------------------
# Reading an uploaded report
# ---------------------------------------------------------------------------------------------


def _sniff(raw: bytes) -> str:
    """Guess a report's media type from its first bytes, when none was sent."""
    head = raw.lstrip()[:1]
    if head == b"<":
        return "application/xml"
    if head in (b"{", b"["):
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) > 1:
            try:
                json.loads(raw)
            except ValueError:
                return "application/x-ndjson"
        return "application/json"
    return "text/plain"


def _text(raw: bytes) -> str:
    """Decode a report as UTF-8 (a BOM is allowed), refusing anything else."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _invalid(f"the report is not UTF-8 text (byte {exc.start})") from exc


# --- JUnit ------------------------------------------------------------------------------------


def _local(tag: str) -> str:
    """An element's tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _junit_summary(root: Element) -> EvidenceSummary:
    """Count the ``<testcase>`` elements of a JUnit document by outcome."""
    passed = failed = errors = skipped = 0
    for case in root.iter():
        if _local(case.tag) != "testcase":
            continue
        children = {_local(child.tag) for child in case}
        if "error" in children:
            errors += 1
        elif "failure" in children:
            failed += 1
        elif "skipped" in children:
            skipped += 1
        else:
            passed += 1
    return EvidenceSummary(
        tests=passed + failed + errors + skipped, passed=passed, failed=failed, errors=errors, skipped=skipped
    )


def _junit_tool(root: Element) -> Optional[str]:
    """The tool a JUnit document names itself after, when it does."""
    suites = [root] if _local(root.tag) == "testsuite" else [s for s in root if _local(s.tag) == "testsuite"]
    for suite in suites:
        name = (suite.get("name") or "").strip().lower()
        if name == "schemathesis":
            return TOOL_SCHEMATHESIS
        if name == "dredd tests":
            return TOOL_DREDD
    return None


def _read_junit(raw: bytes) -> Tuple[EvidenceSummary, Optional[str], Optional[str], List[str]]:
    """Read a JUnit XML report.

    Returns:
        ``(summary, detected tool, tool version, reasons)``.

    Raises:
        ProviderContractError: ``provider-contract-evidence-invalid`` for XML that does not parse,
            carries a DTD or entity declarations, or whose root is not ``<testsuites>`` /
            ``<testsuite>``.
    """
    try:
        root = fromstring(raw, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise _invalid(
            f"the XML report declares a DTD or entities, which are not accepted ({type(exc).__name__})"
        ) from exc
    except ParseError as exc:
        raise _invalid(f"the report is not well-formed XML: {exc}") from exc
    if _local(root.tag) not in ("testsuites", "testsuite"):
        raise _invalid(
            f"the XML report is not JUnit: its root element is <{_local(root.tag)}>, not <testsuites> or <testsuite>"
        )
    return _junit_summary(root), _junit_tool(root), None, []


# --- Newman JSON ------------------------------------------------------------------------------


def _count(stats: Mapping[str, Any], key: str, field_name: str) -> int:
    """``stats[key][field]`` as a non-negative int (0 when absent)."""
    value = (stats.get(key) or {}).get(field_name) if isinstance(stats.get(key), Mapping) else None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 0


def _is_newman(document: Any) -> bool:
    """Whether a JSON document is a Newman ``-r json`` report."""
    return (
        isinstance(document, Mapping)
        and isinstance(document.get("run"), Mapping)
        and isinstance(document["run"].get("stats"), Mapping)
        and "collection" in document
    )


def _read_newman(document: Mapping[str, Any]) -> Tuple[EvidenceSummary, Optional[str], Optional[str], List[str]]:
    """Read a Newman JSON report: assertions are the tests; script and request failures errors."""
    run = document["run"]
    stats = run["stats"]
    total = _count(stats, "assertions", "total")
    failed = _count(stats, "assertions", "failed")
    pending = _count(stats, "assertions", "pending")
    errors = (
        _count(stats, "requests", "failed")
        + _count(stats, "testScripts", "failed")
        + _count(stats, "prerequestScripts", "failed")
    )
    if run.get("error"):
        errors += 1
    passed = max(total - failed - pending, 0)
    summary = EvidenceSummary(
        tests=passed + failed + errors + pending, passed=passed, failed=failed, errors=errors, skipped=pending
    )
    return summary, TOOL_NEWMAN, None, []


# --- Schemathesis NDJSON ----------------------------------------------------------------------


def _ndjson_events(text: str) -> List[Tuple[int, Any]]:
    """Parse NDJSON into ``(line number, value)`` pairs, refusing a line that is not JSON."""
    events = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append((number, json.loads(line)))
        except ValueError as exc:
            raise _invalid(f"line {number} of the NDJSON report is not JSON: {exc}") from exc
    return events


def _is_schemathesis(events: List[Tuple[int, Any]]) -> bool:
    """Whether NDJSON events are a Schemathesis ``--report ndjson`` stream."""
    return any(
        isinstance(value, Mapping)
        and isinstance(value.get("Initialize"), Mapping)
        and "schemathesis_version" in value["Initialize"]
        for _, value in events
    )


def _read_schemathesis(
    events: List[Tuple[int, Any]],
) -> Tuple[EvidenceSummary, Optional[str], Optional[str], List[str]]:
    """Read a Schemathesis NDJSON stream: one test per ``ScenarioFinished`` event."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    version: Optional[str] = None
    finished: Optional[Mapping[str, Any]] = None
    reasons: List[str] = []
    unknown: Dict[str, int] = {}
    for _, value in events:
        if not isinstance(value, Mapping) or len(value) != 1:
            continue
        ((name, body),) = value.items()
        if not isinstance(body, Mapping):
            continue
        if name == "Initialize":
            version = str(body.get("schemathesis_version") or "") or None
        elif name == "ScenarioFinished":
            status = str(body.get("status") or "")
            bucket = _SCHEMATHESIS_STATUS.get(status)
            if bucket is None:
                unknown[status] = unknown.get(status, 0) + 1
                bucket = "errors"
            counts[bucket] += 1
        elif name == "EngineFinished":
            finished = body
    for status, count in sorted(unknown.items()):
        reasons.append(f"{count} scenario(s) finished with status '{status or '(none)'}', counted as errors")
    extra: List[str] = []
    if finished is None:
        extra.append("the Schemathesis run did not finish: the report has no EngineFinished event")
    elif str(finished.get("stop_reason") or "completed") not in ("completed", "failure_limit"):
        extra.append(f"the Schemathesis run stopped early ({finished.get('stop_reason')})")
    summary = EvidenceSummary(tests=sum(counts.values()), **counts)
    return summary, TOOL_SCHEMATHESIS, version, reasons + extra


# --- Entry point ------------------------------------------------------------------------------


def decode_report(content: str) -> bytes:
    """Decode the base64 ``verificationResults.content``.

    Raises:
        ProviderContractError: ``provider-contract-request-invalid`` when it is not base64.
    """
    try:
        return base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderContractError(
            CODE_REQUEST_INVALID, f"the verification results content is not valid base64: {exc}", pointer=_POINTER
        ) from exc


def read_uploaded_report(
    raw: bytes,
    *,
    content_type: Optional[str],
    verifier: Optional[str],
    verifier_version: Optional[str],
    success: Optional[bool],
    max_bytes: int,
) -> Evidence:
    """Read a third-party self-verification report.

    Args:
        raw: The decoded report.
        content_type: The ``contentType`` sent; sniffed from the first bytes when omitted.
        verifier: The ``verifier`` sent (``schemathesis``, ``dredd``, ``newman``).
        verifier_version: The ``verifierVersion`` sent.
        success: The ``success`` flag sent.
        max_bytes: The largest report accepted.

    Returns:
        The evidence, with ``digest`` the SHA-256 of ``raw``.

    Raises:
        ProviderContractError: ``provider-contract-evidence-too-large`` over ``max_bytes``;
            ``provider-contract-evidence-unsupported`` for a media type no report is read as;
            ``provider-contract-evidence-invalid`` for content that is not what its media type says.
    """
    if len(raw) > max_bytes:
        raise ProviderContractError(
            CODE_EVIDENCE_TOO_LARGE,
            f"the self-verification report is {len(raw)} bytes; the limit is {max_bytes}",
            pointer=_POINTER,
        )
    media = _media_type(content_type) or _sniff(raw)
    if media not in SUPPORTED_CONTENT_TYPES:
        raise ProviderContractError(
            CODE_EVIDENCE_UNSUPPORTED,
            f"contentType '{content_type}' is not a report type Apiome accepts; send one of "
            f"{', '.join(SUPPORTED_CONTENT_TYPES)}",
            pointer=_POINTER_TYPE,
        )
    named = _tool_name(verifier)
    base = {"digest": _digest(raw), "content_type": media}

    def unreadable(reason: str) -> Evidence:
        status = STATUS_FAILED if success is False else STATUS_INCONCLUSIVE
        reasons = [reason]
        if success is False:
            reasons.insert(0, "the publisher reported that the self-verification failed (success: false)")
        return Evidence(
            status=status,
            kind=KIND_UNREADABLE,
            tool=named,
            tool_version=verifier_version,
            reasons=tuple(reasons),
            **base,
        )

    if media in _TEXT_TYPES:
        return unreadable(f"Apiome cannot read a {media} report; {_READABLE_HINT}")
    text = _text(raw)
    if media in _XML_TYPES:
        kind = KIND_JUNIT
        summary, detected, version, extra = _read_junit(raw)
        detected = detected or named or TOOL_JUNIT
    else:
        document: Any = None
        events: List[Tuple[int, Any]] = []
        if media in _JSON_TYPES:
            try:
                document = json.loads(text)
            except ValueError as exc:
                lines = [line for line in text.splitlines() if line.strip()]
                if len(lines) < 2:
                    raise _invalid(f"the report is not JSON: {exc}") from exc
                events = _ndjson_events(text)
        else:
            events = _ndjson_events(text)
        if document is not None and _is_newman(document):
            kind = KIND_NEWMAN_JSON
            summary, detected, version, extra = _read_newman(document)
        elif events and _is_schemathesis(events):
            kind = KIND_SCHEMATHESIS_NDJSON
            summary, detected, version, extra = _read_schemathesis(events)
        else:
            return unreadable(f"Apiome does not recognise this JSON report; {_READABLE_HINT}")
    notes: List[str] = []
    if named and detected != named:
        notes.append(f"verifier '{verifier}' was sent, but the report was written by {detected}")
    status, reasons = _decide(summary, success, extra)
    return Evidence(
        status=status,
        kind=kind,
        tool=detected,
        tool_version=version or verifier_version,
        summary=summary,
        reasons=tuple(reasons),
        notes=tuple(notes),
        **base,
    )


# ---------------------------------------------------------------------------------------------
# An Apiome provider-verification report (CTG-4.3)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractSource:
    """The Apiome version a provider contract was rendered from, to match a report against.

    Attributes:
        project_id: The project's id.
        project_slug: Its slug.
        version_label: The version's label.
    """

    project_id: Optional[str]
    project_slug: str
    version_label: str


@dataclass(frozen=True)
class _ReportView:
    """The fields of a conformance report record this module reads (keeps the module pure)."""

    report_id: str
    outcome: str
    artifact_id: Optional[str]
    artifact_slug: Optional[str]
    version_label: Optional[str]
    target_slug: str
    target_environment: str
    cases: EvidenceSummary
    operations_total: int
    operations_exercised: int
    coverage_percent: float
    digest: str


def _report_view(record: Any) -> _ReportView:
    """Read what is needed from a :class:`app.provider_verification_store.ConformanceReportRecord`."""
    report_json = record.report.model_dump(mode="json")
    canonical = json.dumps(report_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _ReportView(
        report_id=str(record.id),
        outcome=str(record.outcome),
        artifact_id=record.artifact_id,
        artifact_slug=record.artifact_slug,
        version_label=record.version_label,
        target_slug=record.target_slug,
        target_environment=record.target_environment,
        cases=EvidenceSummary(
            tests=int(record.cases_total),
            passed=int(record.cases_passed),
            failed=int(record.cases_failed),
            errors=int(record.cases_errored),
            skipped=int(record.cases_skipped),
        ),
        operations_total=int(record.operations_total),
        operations_exercised=int(record.operations_exercised),
        coverage_percent=float(record.coverage_percent),
        digest=_digest(canonical.encode("utf-8")),
    )


def evidence_from_conformance_report(
    record: Any, *, success: Optional[bool], source: Optional[ContractSource]
) -> Evidence:
    """Evidence from an Apiome provider-verification report.

    Args:
        record: The report (a ``ConformanceReportRecord``, already read in the caller's tenant).
        success: The ``success`` flag sent, if any. A flag that disagrees with the report fails.
        source: The Apiome version the contract was rendered from; ``None`` for an inline
            contract.

    Returns:
        The evidence. A report about a different project or version than the contract was
        rendered from is ``inconclusive``: it proves nothing about this contract. An inline
        contract cannot be tied to the report, which the ``notes`` say.
    """
    view = _report_view(record)
    extra: List[str] = []
    notes: List[str] = []
    if view.outcome != "passed" and not (view.cases.failed or view.cases.errors):
        extra.append(f"the provider-verification report's outcome is '{view.outcome}'")
    if source is not None:
        same_project = (source.project_id and view.artifact_id == source.project_id) or (
            view.artifact_slug == source.project_slug
        )
        if not same_project or view.version_label != source.version_label:
            extra.append(
                f"the provider-verification report verified {view.artifact_slug or '?'}@{view.version_label or '?'}, "
                f"but the contract was rendered from {source.project_slug}@{source.version_label}"
            )
    else:
        notes.append(
            f"the report verified {view.artifact_slug or '?'}@{view.version_label or '?'}; the contract was sent "
            f"inline, so Apiome did not tie the two"
        )
    status, reasons = _decide(view.cases, success, extra)
    return Evidence(
        status=status,
        kind=KIND_APIOME_REPORT,
        tool=TOOL_APIOME,
        digest=view.digest,
        summary=view.cases,
        reasons=tuple(reasons),
        notes=tuple(notes),
        report_id=view.report_id,
        target={"slug": view.target_slug, "environment": view.target_environment},
        coverage={
            "operationsTotal": view.operations_total,
            "operationsExercised": view.operations_exercised,
            "percent": view.coverage_percent,
        },
    )


# ---------------------------------------------------------------------------------------------
# Evidence of a stored publication
# ---------------------------------------------------------------------------------------------


def evidence_of(stored_results: Optional[Mapping[str, Any]], *, max_bytes: int) -> Evidence:
    """The evidence of a stored publication's ``verification_results``.

    Publications since PFX-2.4 carry their evidence in ``evidence``. One published before (PFX-2.1)
    has only what was sent; its report is read now, the same way, and anything that cannot be read
    is ``inconclusive`` rather than an error — the publish was accepted long ago.

    Args:
        stored_results: The ``verification_results`` column; ``None`` when none were sent.
        max_bytes: The report size limit.

    Returns:
        The evidence.
    """
    if not stored_results:
        return missing_evidence()
    stored = stored_results.get("evidence")
    if isinstance(stored, Mapping):
        return Evidence.from_dict(stored)
    success = stored_results.get("success")
    success = success if isinstance(success, bool) else None
    content = stored_results.get("content")
    if not isinstance(content, str):
        return unsent_evidence(
            bool(success),
            verifier=stored_results.get("verifier"),
            verifier_version=stored_results.get("verifierVersion"),
        )
    try:
        return read_uploaded_report(
            decode_report(content),
            content_type=stored_results.get("contentType"),
            verifier=stored_results.get("verifier"),
            verifier_version=stored_results.get("verifierVersion"),
            success=success,
            max_bytes=max_bytes,
        )
    except ProviderContractError as exc:
        return Evidence(status=STATUS_INCONCLUSIVE, kind=KIND_UNREADABLE, reasons=(str(exc),))
