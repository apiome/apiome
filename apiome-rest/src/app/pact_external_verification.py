"""Verification results produced elsewhere — PFX-3.5 (#6935).

A team that already runs ``pact_verifier_cli`` (or a Pact library whose test runner writes JUnit)
in its own CI does not need Apiome's hosted verifier (PFX-3.2) to get a can-i-deploy verdict. It
sends the report it already has, and this module reads it into the verification-result model of
PFX-1.4 (:class:`app.verification_result.VerificationRequest`): ``success`` and per-interaction
``testResults`` of the shape ``{"interactionId", "interactionDescription", "success", "mismatches":
[{"attribute", "description"}]}``.

These inputs are read:

* **pact_verifier_cli JSON** (``--json report.json``). Read tolerantly: the verifier's own result
  (``{"result", "errors", "pendingErrors", "notices", "output"}``, each error an object with an
  interaction id and a mismatch, or an ``[id, mismatch]`` pair) and a per-interaction listing
  (``{"pacts": [{"interactions": [{"description", "success"|"result", "mismatches"}]}]}``).
* **JUnit XML** — ``<testsuites>`` / ``<testsuite>`` / ``<testcase>``; a ``<failure>`` or
  ``<error>`` is a failed interaction, with its message as the mismatch.
* **Schemathesis** (PFX-8.9) — its ``--report ndjson`` stream (one interaction per operation
  label, failed when any ``ScenarioFinished`` of it failed, each failed check a mismatch) or its
  ``--report junit`` file.
* **Newman** (PFX-8.9) — ``newman run -r json`` (one interaction per execution, each failed
  assertion a mismatch) or ``-r junit``.
* **Dredd** (PFX-8.9) — ``--reporter xunit``, read as JUnit.

``format=auto`` tells them apart from the body: XML whose suite is named ``schemathesis`` or
``Dredd Tests`` is that tool's; JSON with ``run.executions`` and ``collection`` is Newman's; NDJSON
with a Schemathesis ``Initialize`` event is Schemathesis'. Newman's JUnit carries no mark of its
tool, so it is read as plain JUnit unless ``format=newman`` says otherwise.

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
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.etree.ElementTree import Element

from .pact_publication import PactPublicationError
from .secure_xml import SecureXmlError, parse_xml
from .verification_result import CODE_VERIFICATION_INVALID, MAX_TEST_RESULTS

__all__ = [
    "FORMAT_AUTO",
    "FORMAT_JUNIT",
    "FORMAT_DREDD",
    "FORMAT_NEWMAN",
    "FORMAT_PACT_VERIFIER_JSON",
    "FORMAT_SCHEMATHESIS",
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
#: A Schemathesis report: ``--report ndjson`` or ``--report junit`` (PFX-8.9).
FORMAT_SCHEMATHESIS = "schemathesis"
#: A Newman report: ``-r json`` or ``-r junit`` (PFX-8.9).
FORMAT_NEWMAN = "newman"
#: A Dredd report: ``--reporter xunit`` (PFX-8.9).
FORMAT_DREDD = "dredd"
#: The values of the ``format`` query parameter.
FORMATS = (FORMAT_AUTO, FORMAT_PACT_VERIFIER_JSON, FORMAT_JUNIT, FORMAT_SCHEMATHESIS, FORMAT_NEWMAN, FORMAT_DREDD)

#: How a report is written: the syntax its reader parsed.
SYNTAX_JSON = "json"
SYNTAX_NDJSON = "ndjson"
SYNTAX_XML = "xml"

#: The implementation recorded in ``verifiedBy`` when the caller does not name one.
_DEFAULT_IMPLEMENTATION = {
    FORMAT_PACT_VERIFIER_JSON: "pact_verifier_cli",
    FORMAT_JUNIT: "JUnit",
    FORMAT_SCHEMATHESIS: "Schemathesis",
    FORMAT_NEWMAN: "Newman",
    FORMAT_DREDD: "Dredd",
}

#: The syntaxes each tool writes, in the order a body is tried.
_TOOL_SYNTAXES = {
    FORMAT_PACT_VERIFIER_JSON: (SYNTAX_JSON,),
    FORMAT_JUNIT: (SYNTAX_XML,),
    FORMAT_SCHEMATHESIS: (SYNTAX_NDJSON, SYNTAX_XML),
    FORMAT_NEWMAN: (SYNTAX_JSON, SYNTAX_XML),
    FORMAT_DREDD: (SYNTAX_XML,),
}

#: What each tool's report is called, for a refusal that names the expected file.
_TOOL_HINT = {
    FORMAT_PACT_VERIFIER_JSON: "pact_verifier_cli --json output",
    FORMAT_JUNIT: "JUnit XML",
    FORMAT_SCHEMATHESIS: "Schemathesis --report ndjson or --report junit output",
    FORMAT_NEWMAN: "newman run -r json or -r junit output",
    FORMAT_DREDD: "dredd --reporter xunit output",
}

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
        format: ``pact-verifier-json``, ``junit``, ``schemathesis``, ``newman`` or ``dredd``.
        success: Whether every interaction passed.
        test_results: The per-interaction results, ready for ``testResults``.
        implementation: The default ``verifiedBy.implementation`` for the format.
        notices: Everything the reader could not use or had to interpret.
        syntax: ``json``, ``ndjson`` or ``xml`` — how the report was written.
    """

    format: str
    success: bool
    test_results: List[Dict[str, Any]]
    implementation: str
    notices: List[Notice] = field(default_factory=list)
    syntax: str = SYNTAX_JSON


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


def _syntax(raw: bytes, content_type: Optional[str]) -> str:
    """How a body is written: XML, a JSON document, or NDJSON (one JSON value per line).

    The content type decides when it names one; otherwise the first byte does, and a body that
    starts like JSON but is several JSON values on separate lines is NDJSON.

    Raises:
        PactPublicationError: For a body that is neither XML nor JSON.
    """
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media in ("application/x-ndjson", "application/ndjson", "application/jsonl", "application/x-jsonlines"):
        return SYNTAX_NDJSON
    if media.endswith("xml"):
        return SYNTAX_XML
    head = raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head == b"<":
        return SYNTAX_XML
    if head in (b"{", b"["):
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) > 1:
            try:
                json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                return SYNTAX_NDJSON
        return SYNTAX_JSON
    if media.endswith("json"):
        return SYNTAX_JSON
    raise _invalid(
        "the report is neither JSON nor XML; send a pact_verifier_cli --json report, JUnit XML, or a "
        "Schemathesis, Newman or Dredd report"
    )


def _detect(raw: bytes, content_type: Optional[str], requested: str) -> Tuple[str, str]:
    """Decide which reader a body goes to.

    Args:
        raw: The report.
        content_type: The request's ``Content-Type``.
        requested: ``format`` — one of :data:`FORMATS`.

    Returns:
        ``(format, syntax)``. With ``auto`` an XML body's tool is decided when it is parsed
        (:func:`_junit_tool`), so the format is :data:`FORMAT_JUNIT` until then.

    Raises:
        PactPublicationError: For an unknown ``format``, a body that is neither JSON nor XML, or a
            body the named tool does not write (a Dredd report that is not XML).
    """
    if requested not in FORMATS:
        raise _invalid(f"format must be one of {', '.join(FORMATS)}", "/format")
    # An explicit format wins over the content type: the body alone says how it is written.
    syntax = _syntax(raw, content_type if requested == FORMAT_AUTO else None)
    if requested == FORMAT_AUTO:
        if syntax == SYNTAX_XML:
            return FORMAT_JUNIT, syntax
        if syntax == SYNTAX_NDJSON:
            return FORMAT_SCHEMATHESIS, syntax
        return FORMAT_PACT_VERIFIER_JSON, syntax
    if syntax not in _TOOL_SYNTAXES[requested]:
        raise _invalid(
            f"format is {requested} but the report is {syntax.upper()}; send {_TOOL_HINT[requested]}", "/format"
        )
    return requested, syntax


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
        FORMAT_PACT_VERIFIER_JSON,
        verdict,
        results,
        _DEFAULT_IMPLEMENTATION[FORMAT_PACT_VERIFIER_JSON],
        notices,
        syntax=SYNTAX_JSON,
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


def _junit_tool(root: Element) -> Optional[str]:
    """The tool a JUnit document names itself after, when it does (Schemathesis, Dredd)."""
    suites = [root] if _local(root.tag) == "testsuite" else [s for s in root if _local(s.tag) == "testsuite"]
    for suite in suites:
        name = (suite.get("name") or "").strip().lower()
        if name == "schemathesis":
            return FORMAT_SCHEMATHESIS
        if name == "dredd tests":
            return FORMAT_DREDD
    return None


def _read_junit(raw: bytes, fmt: str = FORMAT_JUNIT) -> IngestedReport:
    """Read a JUnit XML report — any JUnit writer's, or Schemathesis', Newman's or Dredd's.

    Args:
        raw: The report.
        fmt: The format asked for: :data:`FORMAT_JUNIT` lets the document name its tool.

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
    chosen = (_junit_tool(root) or FORMAT_JUNIT) if fmt == FORMAT_JUNIT else fmt
    return IngestedReport(
        chosen,
        all(r["success"] for r in results),
        results,
        _DEFAULT_IMPLEMENTATION[chosen],
        notices,
        syntax=SYNTAX_XML,
    )


# ---------------------------------------------------------------------------------------------
# Newman JSON
# ---------------------------------------------------------------------------------------------


def _is_newman(document: Any) -> bool:
    """Whether a JSON document is a ``newman run -r json`` report."""
    return (
        isinstance(document, Mapping)
        and isinstance(document.get("run"), Mapping)
        and isinstance(document["run"].get("executions"), list)
        and "collection" in document
    )


def _newman_operation(execution: Mapping[str, Any]) -> Optional[str]:
    """``GET /invoices/abc1`` for an execution, from the request it sent (or the item's)."""
    request = execution.get("request")
    if not isinstance(request, Mapping):
        item = execution.get("item")
        request = item.get("request") if isinstance(item, Mapping) else None
    if not isinstance(request, Mapping):
        return None
    method = str(request.get("method") or "").upper()
    url = request.get("url")
    path: Optional[str] = None
    if isinstance(url, Mapping) and isinstance(url.get("path"), list):
        path = "/" + "/".join(str(part) for part in url["path"])
    elif isinstance(url, str):
        path = url
    return f"{method} {path}".strip() if method or path else None


def _read_newman(document: Mapping[str, Any]) -> IngestedReport:
    """Read a Newman JSON report: one interaction per execution, each failed assertion a mismatch.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` for a report with no executions.
    """
    run = document["run"]
    notices: List[Notice] = []
    results: List[Dict[str, Any]] = []
    for n, execution in enumerate(run["executions"]):
        pointer = _pointer("run", "executions", n)
        if not isinstance(execution, Mapping):
            notices.append(Notice(pointer, "an execution must be an object; not read"))
            continue
        item = execution.get("item") if isinstance(execution.get("item"), Mapping) else {}
        name = item.get("name") if isinstance(item.get("name"), str) else None
        operation = _newman_operation(execution)
        entry: Dict[str, Any] = {
            "interactionId": str(item["id"]) if item.get("id") is not None else None,
            "interactionDescription": name or operation,
            "success": True,
            "mismatches": [],
        }
        if operation and name:
            entry["operation"] = operation
        if execution.get("requestError"):
            error = execution["requestError"]
            text = error.get("message") if isinstance(error, Mapping) else str(error)
            entry["success"] = False
            entry["mismatches"].append(
                {"attribute": "request", "description": _clip(str(text or "the request failed"))}
            )
        assertions = execution.get("assertions") if isinstance(execution.get("assertions"), list) else []
        for a, assertion in enumerate(assertions):
            if not isinstance(assertion, Mapping):
                continue
            title = str(assertion.get("assertion") or f"assertion {a + 1}")
            if assertion.get("skipped"):
                entry["success"] = False
                entry["skipped"] = True
                entry["mismatches"].append({"attribute": "skipped", "description": _clip(f"{title} was skipped")})
                notices.append(
                    Notice(
                        _pointer("run", "executions", n, "assertions", a),
                        "a skipped assertion makes the result unsuccessful",
                    )
                )
                continue
            error = assertion.get("error")
            if error:
                message = error.get("message") if isinstance(error, Mapping) else str(error)
                entry["success"] = False
                entry["mismatches"].append({"attribute": "assertion", "description": _clip(f"{title}: {message}")})
        if not assertions and not execution.get("requestError"):
            notices.append(Notice(pointer, "the execution ran no assertion; it is counted as passed"))
        results.append(entry)
    if run.get("error"):
        notices.append(Notice("/run/error", "Newman reported a run error; the result is recorded as failed"))
    if not results:
        raise _invalid("the Newman report has no executions, so it proves nothing", "/run/executions")
    if len(results) > MAX_TEST_RESULTS:
        raise _invalid(f"the report has more than {MAX_TEST_RESULTS} executions")
    success = all(r["success"] for r in results) and not run.get("error")
    return IngestedReport(
        FORMAT_NEWMAN, success, results, _DEFAULT_IMPLEMENTATION[FORMAT_NEWMAN], notices, syntax=SYNTAX_JSON
    )


# ---------------------------------------------------------------------------------------------
# Schemathesis NDJSON
# ---------------------------------------------------------------------------------------------

#: Schemathesis events that carry nothing to verify; anything else unknown is noticed once.
_SCHEMATHESIS_QUIET = frozenset(
    {"Initialize", "PhaseStarted", "PhaseFinished", "SuiteStarted", "SuiteFinished", "ScenarioStarted", "Interrupted"}
)


def _ndjson_events(raw: bytes) -> List[Tuple[int, Any]]:
    """Parse NDJSON into ``(line number, value)`` pairs, refusing a line that is not JSON."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _invalid(f"the report is not UTF-8 text: {exc}") from exc
    events: List[Tuple[int, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append((number, json.loads(line)))
        except ValueError as exc:
            raise _invalid(f"line {number} of the NDJSON report is not JSON: {exc}", f"/line/{number}") from exc
    return events


def _failed_checks(recorder: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The failed checks of one scenario, as mismatches (``attribute`` is the check's name)."""
    found: List[Dict[str, Any]] = []
    checks = recorder.get("checks")
    if not isinstance(checks, Mapping):
        return found
    for entries in checks.values():
        for check in entries if isinstance(entries, list) else []:
            if not isinstance(check, Mapping) or check.get("status") != "failure":
                continue
            failure = (
                (check.get("failure_info") or {}).get("failure")
                if isinstance(check.get("failure_info"), Mapping)
                else None
            )
            title = failure.get("title") if isinstance(failure, Mapping) else None
            message = failure.get("message") if isinstance(failure, Mapping) else None
            text = ": ".join(str(part) for part in (title, message) if part) or "the check failed"
            found.append({"attribute": str(check.get("name") or "check"), "description": _clip(text)})
    return found


def _read_schemathesis(raw: bytes) -> IngestedReport:
    """Read a Schemathesis ``--report ndjson`` stream: one interaction per operation label.

    Every ``ScenarioFinished`` of a label (examples, coverage, fuzzing …) counts towards it: it
    fails when one failed or errored, and each failed check is a mismatch (repeats dropped and
    counted). A skipped scenario (``No examples in schema``) tested nothing; it is noticed, not
    counted. A stream without ``EngineFinished`` did not finish and is recorded as failed.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` for NDJSON that is not Schemathesis', or
            a stream with no scenario.
    """
    events = _ndjson_events(raw)
    if not any(isinstance(value, Mapping) and isinstance(value.get("Initialize"), Mapping) for _, value in events):
        raise _invalid("the NDJSON report is not a Schemathesis report: it has no Initialize event")
    notices: List[Notice] = []
    by_label: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    skipped: Dict[str, int] = {}
    unknown: Dict[str, int] = {}
    finished: Optional[Mapping[str, Any]] = None
    for number, value in events:
        if not isinstance(value, Mapping) or len(value) != 1:
            notices.append(Notice(f"/line/{number}", "not a Schemathesis event; not read"))
            continue
        ((name, body),) = value.items()
        if name == "EngineFinished":
            finished = body if isinstance(body, Mapping) else {}
            continue
        if name != "ScenarioFinished":
            if name not in _SCHEMATHESIS_QUIET:
                unknown[name] = unknown.get(name, 0) + 1
            continue
        if not isinstance(body, Mapping):
            continue
        recorder = body.get("recorder") if isinstance(body.get("recorder"), Mapping) else {}
        label = str(recorder.get("label") or body.get("label") or "(unnamed operation)")
        status = str(body.get("status") or "")
        if status == "skip":
            skipped[label] = skipped.get(label, 0) + 1
            continue
        entry = by_label.setdefault(
            label,
            {"interactionId": None, "interactionDescription": label, "success": True, "mismatches": [], "_seen": set()},
        )
        if status == "success":
            continue
        entry["success"] = False
        found = _failed_checks(recorder) if status == "failure" else []
        if not found:
            verb = {"failure": "failed", "error": "errored"}.get(status, f"finished as '{status or '(none)'}'")
            phase = f"{body.get('phase')} " if body.get("phase") else ""
            found = [{"attribute": "scenario", "description": f"a {phase}scenario {verb}"}]
        for mismatch in found:
            key = (mismatch["attribute"], mismatch["description"])
            if key in entry["_seen"]:
                continue
            entry["_seen"].add(key)
            entry["mismatches"].append(mismatch)
    for label, count in skipped.items():
        if label not in by_label:
            notices.append(
                Notice(f"/{label}", f"{count} scenario(s) were skipped by Schemathesis and tested nothing; not counted")
            )
    for name, count in sorted(unknown.items()):
        notices.append(Notice(f"/{name}", f"{count} {name} event(s) are not stored"))
    results = []
    for entry in by_label.values():
        entry.pop("_seen")
        results.append(entry)
    if not results:
        raise _invalid("the Schemathesis report has no scenario that ran, so it proves nothing")
    if len(results) > MAX_TEST_RESULTS:
        raise _invalid(f"the report has more than {MAX_TEST_RESULTS} operations")
    success = all(r["success"] for r in results)
    if finished is None:
        notices.append(
            Notice("/EngineFinished", "the Schemathesis run did not finish; the result is recorded as failed")
        )
        success = False
    elif str(finished.get("stop_reason") or "completed") not in ("completed", "failure_limit"):
        notices.append(
            Notice(
                "/EngineFinished/stop_reason",
                f"the run stopped early ({finished.get('stop_reason')}); recorded as failed",
            )
        )
        success = False
    return IngestedReport(
        FORMAT_SCHEMATHESIS,
        success,
        results,
        _DEFAULT_IMPLEMENTATION[FORMAT_SCHEMATHESIS],
        notices,
        syntax=SYNTAX_NDJSON,
    )


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def _read_json(raw: bytes, fmt: str) -> IngestedReport:
    """Read a JSON report: Newman's when it is one (or ``fmt`` says so), else the Pact verifier's."""
    if fmt in (FORMAT_AUTO, FORMAT_NEWMAN):
        try:
            document = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _invalid(f"the report is not JSON: {exc}") from exc
        if _is_newman(document):
            return _read_newman(document)
        if fmt == FORMAT_NEWMAN:
            raise _invalid(
                "format is newman but the JSON has no run.executions and collection; send newman run -r json output",
                "/run",
            )
    return _read_verifier_json(raw)


def read_external_report(raw: bytes, *, content_type: Optional[str] = None, fmt: str = FORMAT_AUTO) -> IngestedReport:
    """Read a verifier report produced elsewhere.

    Args:
        raw: The request body, already size-limited.
        content_type: The request's ``Content-Type``, used when ``fmt`` is ``auto``.
        fmt: One of :data:`FORMATS`.

    Returns:
        The report in the verification-result model, with the notices for anything not used.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` with a pointer when the body is empty,
            malformed, of an unknown format, not what ``fmt`` names, or proves nothing.
    """
    if not raw.strip():
        raise _invalid(
            "the request body is empty; send a pact_verifier_cli --json report, JUnit XML, or a "
            "Schemathesis, Newman or Dredd report"
        )
    chosen, syntax = _detect(raw, content_type, fmt)
    if syntax == SYNTAX_XML:
        return _read_junit(raw, chosen)
    if syntax == SYNTAX_NDJSON:
        return _read_schemathesis(raw)
    return _read_json(raw, FORMAT_AUTO if fmt == FORMAT_AUTO else chosen)


def notices_as_dicts(notices: Sequence[Notice]) -> List[Dict[str, str]]:
    """The notices as the endpoint returns them."""
    return [notice.as_dict() for notice in notices]
