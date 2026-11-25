"""Verification results produced elsewhere — PFX-3.5 (#6935).

A team that already runs ``pact_verifier_cli`` (or a Pact library whose test runner writes JUnit)
in its own CI does not need Apiome's hosted verifier (PFX-3.2) to get a can-i-deploy verdict. It
sends the report it already has, and this module reads it into the verification-result model of
PFX-1.4 (:class:`app.verification_result.VerificationRequest`): ``success`` and per-interaction
``testResults`` of the shape ``{"interactionId", "interactionDescription", "success", "mismatches":
[{"attribute", "description"}]}``.

Two inputs are read:

* **pact_verifier_cli JSON** (``--json report.json``). Read tolerantly: the verifier's own result
  (``{"result", "errors", "pendingErrors", "notices", "output"}``, each error an object with an
  interaction id and a mismatch, or an ``[id, mismatch]`` pair) and a per-interaction listing
  (``{"pacts": [{"interactions": [{"description", "success"|"result", "mismatches"}]}]}``).
* **JUnit XML** — ``<testsuites>`` / ``<testsuite>`` / ``<testcase>``; a ``<failure>`` or
  ``<error>`` is a failed interaction, with its message as the mismatch.

Nothing is dropped silently. Whatever the reader keeps verbatim goes into ``testResults``; whatever
it cannot use is returned as a :class:`Notice` naming the JSON Pointer (or XML location) and the
reason, and the endpoint hands them back to the caller. A report that proves nothing — no
interactions at all — is refused instead of being published as a pass. A skipped test case is never
counted as verified: it makes the result unsuccessful, because a skipped interaction was not
replayed.

The reader does not cross-check the report against the interactions of the pact version it is
published for: the report is the verifier's word, as it is for a result published by a Pact
library (PFX-1.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from xml.etree.ElementTree import Element

from .pact_publication import PactPublicationError
from .secure_xml import SecureXmlError, parse_xml
from .verification_result import CODE_VERIFICATION_INVALID, MAX_TEST_RESULTS

__all__ = [
    "FORMAT_AUTO",
    "FORMAT_JUNIT",
    "FORMAT_PACT_VERIFIER_JSON",
    "FORMATS",
    "IngestedReport",
    "Notice",
    "notices_as_dicts",
    "read_external_report",
]

#: Sniff the format from ``format``, the content type and the body.
FORMAT_AUTO = "auto"
#: ``pact_verifier_cli --json`` output.
FORMAT_PACT_VERIFIER_JSON = "pact-verifier-json"
#: A JUnit XML report.
FORMAT_JUNIT = "junit"
#: The values of the ``format`` query parameter.
FORMATS = (FORMAT_AUTO, FORMAT_PACT_VERIFIER_JSON, FORMAT_JUNIT)

#: The implementation recorded in ``verifiedBy`` when the caller does not name one.
_DEFAULT_IMPLEMENTATION = {FORMAT_PACT_VERIFIER_JSON: "pact_verifier_cli", FORMAT_JUNIT: "JUnit"}

#: Longest text kept for a mismatch description.
_DESCRIPTION_LIMIT = 4_000

#: Keys of the verifier's own result that this reader understands (anything else is noticed).
_RESULT_KEYS = {"result", "errors", "pendingErrors", "pending_errors", "notices", "output"}
#: Keys of one entry of a per-interaction listing that this reader understands.
_INTERACTION_KEYS = {
    "id",
    "interactionId",
    "interaction_id",
    "key",
    "description",
    "interactionDescription",
    "success",
    "result",
    "mismatches",
    "pending",
    "providerStates",
    "provider_states",
}


@dataclass(frozen=True)
class Notice:
    """One thing the reader kept, changed or could not use, with where and why.

    Attributes:
        pointer: A JSON Pointer into a JSON report, or an XPath-like location in a JUnit one.
        reason: What happened to it, in a sentence.
    """

    pointer: str
    reason: str

    def as_dict(self) -> Dict[str, str]:
        """The notice as the endpoint returns it."""
        return {"pointer": self.pointer, "reason": self.reason}


@dataclass
class IngestedReport:
    """A report read into the verification-result model.

    Attributes:
        format: ``pact-verifier-json`` or ``junit``.
        success: Whether every interaction passed.
        test_results: The per-interaction results, ready for ``testResults``.
        implementation: The default ``verifiedBy.implementation`` for the format.
        notices: Everything the reader could not use or had to interpret.
    """

    format: str
    success: bool
    test_results: List[Dict[str, Any]]
    implementation: str
    notices: List[Notice] = field(default_factory=list)


def _invalid(message: str, pointer: str = "") -> PactPublicationError:
    """A ``pact-verification-invalid`` refusal."""
    return PactPublicationError(CODE_VERIFICATION_INVALID, f"{pointer or '(report)'}: {message}", pointer=pointer)


def _clip(text: str) -> str:
    """Bound a description to :data:`_DESCRIPTION_LIMIT` characters."""
    text = text.strip()
    return text if len(text) <= _DESCRIPTION_LIMIT else text[: _DESCRIPTION_LIMIT - 1] + "…"


def _pointer(*parts: Any) -> str:
    """A JSON Pointer made of ``parts`` (RFC 6901 escaping)."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


# ---------------------------------------------------------------------------------------------
# Choosing the format
# ---------------------------------------------------------------------------------------------


def _detect(raw: bytes, content_type: Optional[str], requested: str) -> str:
    """Decide which reader a body goes to.

    Args:
        raw: The report.
        content_type: The request's ``Content-Type``.
        requested: ``format`` — one of :data:`FORMATS`.

    Returns:
        :data:`FORMAT_PACT_VERIFIER_JSON` or :data:`FORMAT_JUNIT`.

    Raises:
        PactPublicationError: For an unknown ``format`` or a body that is neither JSON nor XML.
    """
    if requested not in FORMATS:
        raise _invalid(f"format must be one of {', '.join(FORMATS)}", "/format")
    if requested != FORMAT_AUTO:
        return requested
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media.endswith("json"):
        return FORMAT_PACT_VERIFIER_JSON
    if media.endswith("xml"):
        return FORMAT_JUNIT
    head = raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head == b"<":
        return FORMAT_JUNIT
    if head in (b"{", b"["):
        return FORMAT_PACT_VERIFIER_JSON
    raise _invalid("the report is neither JSON nor XML; send a pact_verifier_cli --json report or JUnit XML")


# ---------------------------------------------------------------------------------------------
# pact_verifier_cli JSON
# ---------------------------------------------------------------------------------------------


def _mismatch(value: Any, pointer: str, notices: List[Notice]) -> Dict[str, Any]:
    """One verifier mismatch as ``{"attribute", "description"}``, keeping the original too.

    A string is the description. An object contributes its ``type`` (or ``attribute``) as the
    attribute and its ``description`` / ``mismatch`` / ``message`` as the description; when it has
    none of those the whole object is kept as JSON text and a notice says so. The original object
    is always kept under ``detail`` so no field of the verifier's output is lost.
    """
    if isinstance(value, str):
        return {"attribute": "mismatch", "description": _clip(value)}
    if isinstance(value, Mapping):
        attribute = value.get("attribute") or value.get("type") or "mismatch"
        text = value.get("description") or value.get("mismatch") or value.get("message")
        if not isinstance(text, str):
            text = json.dumps(value, sort_keys=True, default=str)
            notices.append(Notice(pointer, "the mismatch has no description; its fields are kept as JSON text"))
        return {"attribute": str(attribute), "description": _clip(text), "detail": dict(value)}
    notices.append(
        Notice(pointer, f"a mismatch must be a string or an object, not {type(value).__name__}; kept as text")
    )
    return {"attribute": "mismatch", "description": _clip(json.dumps(value, default=str))}


def _failure_entry(value: Any, pointer: str, notices: List[Notice], *, pending: bool) -> Dict[str, Any]:
    """One entry of ``errors`` / ``pendingErrors`` as a failed test result."""
    interaction_id: Any = None
    description: Any = None
    mismatch: Any = value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        interaction_id, mismatch = value
    elif isinstance(value, Mapping):
        interaction_id = value.get("interactionId") or value.get("interaction_id") or value.get("id")
        description = value.get("interactionDescription") or value.get("description")
        mismatch = value.get("mismatch", value.get("mismatches", value))
        if isinstance(mismatch, Sequence) and not isinstance(mismatch, (str, bytes)):
            mismatch = list(mismatch)
    mismatches = mismatch if isinstance(mismatch, list) else [mismatch]
    entry: Dict[str, Any] = {
        "interactionId": str(interaction_id) if interaction_id is not None else None,
        "interactionDescription": description if isinstance(description, str) else None,
        "success": False,
        "mismatches": [_mismatch(item, f"{pointer}/mismatch/{n}", notices) for n, item in enumerate(mismatches)],
    }
    if pending:
        entry["pending"] = True
    if entry["interactionId"] is None and entry["interactionDescription"] is None:
        notices.append(Notice(pointer, "the entry names no interaction; its mismatches are kept unattributed"))
    return entry


def _interaction_entry(value: Any, pointer: str, notices: List[Notice]) -> Dict[str, Any]:
    """One interaction of a per-interaction listing as a test result."""
    if not isinstance(value, Mapping):
        raise _invalid("an interaction must be an object", pointer)
    outcome = value.get("success", value.get("result"))
    if isinstance(outcome, str):
        outcome = {"ok": True, "pass": True, "passed": True, "success": True}.get(outcome.lower(), False)
    mismatches = value.get("mismatches")
    if not isinstance(outcome, bool):
        outcome = not mismatches
        notices.append(
            Notice(pointer, "the interaction has no success flag; it is read as failed when it has mismatches")
        )
    items = mismatches if isinstance(mismatches, list) else ([] if mismatches is None else [mismatches])
    entry: Dict[str, Any] = {
        "interactionId": next(
            (str(value[k]) for k in ("interactionId", "interaction_id", "id", "key") if value.get(k) is not None), None
        ),
        "interactionDescription": next(
            (value[k] for k in ("interactionDescription", "description") if isinstance(value.get(k), str)), None
        ),
        "success": outcome,
        "mismatches": [_mismatch(item, f"{pointer}/mismatches/{n}", notices) for n, item in enumerate(items)],
    }
    if value.get("pending") is True:
        entry["pending"] = True
    for key in value:
        if key not in _INTERACTION_KEYS:
            notices.append(Notice(f"{pointer}{_pointer(key)}", "unrecognised field not stored"))
    if not outcome and not entry["mismatches"]:
        notices.append(Notice(pointer, "the interaction failed without naming a mismatch"))
    return entry


def _read_verifier_json(raw: bytes) -> IngestedReport:
    """Read a ``pact_verifier_cli --json`` report.

    Args:
        raw: The report.

    Returns:
        The report in the verification-result model.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` for JSON that does not parse, is not an
            object, or has no interactions to judge.
    """
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid(f"the report is not JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise _invalid("the report must be a JSON object")
    notices: List[Notice] = []
    results: List[Dict[str, Any]] = []
    verdict: Optional[bool] = None

    pacts = document.get("pacts")
    if isinstance(pacts, list):
        for p, pact in enumerate(pacts):
            interactions = pact.get("interactions") if isinstance(pact, Mapping) else None
            if not isinstance(interactions, list):
                notices.append(Notice(_pointer("pacts", p), "no interactions array; nothing read from this pact"))
                continue
            for i, interaction in enumerate(interactions):
                results.append(_interaction_entry(interaction, _pointer("pacts", p, "interactions", i), notices))
        for key in document:
            if key != "pacts":
                notices.append(Notice(_pointer(key), "unrecognised field not stored"))
        if isinstance(document.get("result"), bool):
            verdict = document["result"]
    else:
        result_flag = document.get("result")
        if isinstance(result_flag, bool):
            verdict = result_flag
        elif result_flag is not None:
            raise _invalid("result must be true or false", "/result")
        for key, pending in (("errors", False), ("pendingErrors", True), ("pending_errors", True)):
            entries = document.get(key)
            if entries is None:
                continue
            if not isinstance(entries, list):
                raise _invalid(f"{key} must be an array", _pointer(key))
            for n, entry in enumerate(entries):
                results.append(_failure_entry(entry, _pointer(key, n), notices, pending=pending))
        if isinstance(document.get("notices"), list) and document["notices"]:
            notices.append(
                Notice(
                    "/notices",
                    f"{len(document['notices'])} verifier notice(s) (pending / WIP explanations) are not stored",
                )
            )
        if isinstance(document.get("output"), list) and document["output"]:
            notices.append(
                Notice("/output", f"{len(document['output'])} line(s) of verifier log output are not stored")
            )
        for key in document:
            if key not in _RESULT_KEYS:
                notices.append(Notice(_pointer(key), "unrecognised field not stored"))

    if len(results) > MAX_TEST_RESULTS:
        raise _invalid(f"the report has more than {MAX_TEST_RESULTS} interactions")
    real_failures = [r for r in results if not r["success"] and not r.get("pending")]
    if verdict is None:
        if not results:
            raise _invalid(
                "the report has no result flag and no interactions, so it proves nothing; "
                "send the report of a run that replayed at least one interaction"
            )
        verdict = not real_failures
        notices.append(Notice("/result", "the report has no result flag; success is derived from its interactions"))
    elif verdict and real_failures:
        notices.append(Notice("/result", "the report says success but lists failed interactions; recorded as failed"))
        verdict = False
    if not results and verdict is not True:
        raise _invalid("the report records a failure but names no interaction or mismatch", "/errors")
    return IngestedReport(
        FORMAT_PACT_VERIFIER_JSON, verdict, results, _DEFAULT_IMPLEMENTATION[FORMAT_PACT_VERIFIER_JSON], notices
    )


# ---------------------------------------------------------------------------------------------
# JUnit
# ---------------------------------------------------------------------------------------------


def _local(tag: Any) -> str:
    """An element's tag without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _junit_case(case: Element, location: str, notices: List[Notice]) -> Dict[str, Any]:
    """One ``<testcase>`` as a test result."""
    name = (case.get("name") or "").strip()
    classname = (case.get("classname") or "").strip()
    description = name or classname or None
    entry: Dict[str, Any] = {
        "interactionId": None,
        "interactionDescription": description,
        "success": True,
        "mismatches": [],
    }
    if classname and name:
        entry["suite"] = classname
    if description is None:
        notices.append(Notice(location, "the test case has no name; it is kept without a description"))
    for child in case:
        kind = _local(child.tag)
        if kind in ("failure", "error"):
            entry["success"] = False
            text = (child.get("message") or child.text or "").strip() or f"the test case reported an {kind}"
            entry["mismatches"].append({"attribute": child.get("type") or kind, "description": _clip(text)})
        elif kind == "skipped":
            entry["success"] = False
            entry["skipped"] = True
            reason = (child.get("message") or child.text or "").strip()
            entry["mismatches"].append(
                {
                    "attribute": "skipped",
                    "description": _clip(reason or "the test case was skipped, so it was not verified"),
                }
            )
            notices.append(Notice(location, "a skipped test case was not replayed; it makes the result unsuccessful"))
    return entry


def _read_junit(raw: bytes) -> IngestedReport:
    """Read a JUnit XML report.

    Args:
        raw: The report.

    Returns:
        The report in the verification-result model.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` for XML that does not parse, declares a
            DTD or entities, is not a JUnit document, or has no test cases.
    """
    try:
        root = parse_xml(raw.decode("utf-8-sig"), source_label="report")
    except UnicodeDecodeError as exc:
        raise _invalid(f"the report is not UTF-8 text: {exc}") from exc
    except SecureXmlError as exc:
        raise _invalid(str(exc)) from exc
    if _local(root.tag) not in ("testsuites", "testsuite"):
        raise _invalid(
            f"the XML report is not JUnit: its root element is <{_local(root.tag)}>, not <testsuites> or <testsuite>"
        )
    notices: List[Notice] = []
    results: List[Dict[str, Any]] = []
    counters: Dict[str, int] = {}
    for case in root.iter():
        if _local(case.tag) != "testcase":
            continue
        n = counters.get("case", 0)
        counters["case"] = n + 1
        results.append(_junit_case(case, f"//testcase[{n + 1}]", notices))
    if not results:
        raise _invalid("the JUnit report has no <testcase> elements, so it proves nothing")
    if len(results) > MAX_TEST_RESULTS:
        raise _invalid(f"the report has more than {MAX_TEST_RESULTS} test cases")
    return IngestedReport(
        FORMAT_JUNIT, all(r["success"] for r in results), results, _DEFAULT_IMPLEMENTATION[FORMAT_JUNIT], notices
    )


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def read_external_report(raw: bytes, *, content_type: Optional[str] = None, fmt: str = FORMAT_AUTO) -> IngestedReport:
    """Read a verifier report produced elsewhere.

    Args:
        raw: The request body, already size-limited.
        content_type: The request's ``Content-Type``, used when ``fmt`` is ``auto``.
        fmt: ``auto``, ``pact-verifier-json`` or ``junit``.

    Returns:
        The report in the verification-result model, with the notices for anything not used.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` with a pointer when the body is empty,
            malformed, of an unknown format, or proves nothing.
    """
    if not raw.strip():
        raise _invalid("the request body is empty; send a pact_verifier_cli --json report or JUnit XML")
    chosen = _detect(raw, content_type, fmt)
    return _read_verifier_json(raw) if chosen == FORMAT_PACT_VERIFIER_JSON else _read_junit(raw)


def notices_as_dicts(notices: Sequence[Notice]) -> List[Dict[str, str]]:
    """The notices as the endpoint returns them."""
    return [notice.as_dict() for notice in notices]
