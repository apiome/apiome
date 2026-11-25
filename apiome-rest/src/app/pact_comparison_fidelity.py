"""The comparison fidelity report of a bi-directional result — PFX-2.5 (#6929). Pure.

A bi-directional comparison (PFX-2.2, :mod:`app.pact_oas_compare`) says whether a provider's
OpenAPI document contradicts a consumer's pact. A ``pass`` only means *nothing that was compared
contradicts it*: a matching rule with no JSON Schema equivalent, a body that is not JSON, a
``oneOf`` that had to be relaxed, or a check that never ran because an earlier one failed are all
things the green verdict does not vouch for. This module turns the stored comparison payload into
a report that says so, interaction by interaction — the same honesty rule as the CTG-4.3
provider-verification coverage:

* **checks** — every check the engine knows, in the order it runs, each with a status:
  ``compared`` (ran, nothing to report), ``partial`` (ran, but fidelity notes say part of it was
  not compared in full), ``failed`` (ran and found a contradiction) or ``not-run`` (with the
  reason);
* **unsupported matching rules** — the matching rules, embedded matchers and generators the
  comparison could not prove (fidelity codes in :data:`MATCHING_RULE_CODES`);
* **could not compare** — everything else that was not compared, or compared more weakly than the
  pact asks (fidelity codes in :data:`NOT_COMPARED_CODES`).

Every fidelity code of :data:`app.pact_oas_result.FIDELITY_CLASSES` (and of the message
comparison's :data:`app.pact_asyncapi_compare.MESSAGE_FIDELITY_CLASSES`) belongs to exactly one of
the two groups, and every failure and warning code to exactly one check, so no note is dropped from
the report (the tests hold the tables together).

A comparison with an AsyncAPI provider contract (PFX-3.6, payload ``contractType: asyncapi``)
compares messages, so its report lists the message checks (:data:`MESSAGE_CHECK_LABELS`) instead of
the HTTP ones, and names the ``asyncapiVersion`` in place of ``oasVersion``.

:func:`build_fidelity_report` reads only the stored payload, so a report of an old result is the
report of what that comparison actually did.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .pact_oas_result import VERDICT_FAIL, VERDICT_PARTIAL, VERDICT_PASS

__all__ = [
    "CHECK_LABELS",
    "CHECK_COMPARED",
    "CHECK_FAILED",
    "CHECK_NOT_RUN",
    "CHECK_PARTIAL",
    "CORE_CHECKS",
    "MESSAGE_CHECK_LABELS",
    "MESSAGE_CORE_CHECKS",
    "MATCHING_RULE_CODES",
    "NOT_COMPARED_CODES",
    "STRENGTH_FAILED",
    "STRENGTH_FULL",
    "STRENGTH_NONE",
    "STRENGTH_PARTIAL",
    "build_fidelity_report",
    "check_of_finding",
    "check_of_note",
]

#: The check ran and found nothing to report.
CHECK_COMPARED = "compared"
#: The check ran, but part of what it covers was not compared in full.
CHECK_PARTIAL = "partial"
#: The check ran and found a contradiction.
CHECK_FAILED = "failed"
#: The check did not run; ``reason`` says why.
CHECK_NOT_RUN = "not-run"

#: Everything that could be compared was compared, and nothing was left out.
STRENGTH_FULL = "full"
#: The comparison passed, but some of the pact was not compared in full.
STRENGTH_PARTIAL = "partial"
#: The provider's document contradicts the pact.
STRENGTH_FAILED = "failed"
#: Nothing was compared (the comparison could not run, or the pact has no HTTP interaction).
STRENGTH_NONE = "none"

#: Every check the engine runs on an HTTP interaction, in the order it runs them, with the label a
#: report shows. The two matching-rule checks run only when the interaction declares rules.
CHECK_LABELS: Dict[str, str] = {
    "request.operation": "Operation (method and path)",
    "request.path-parameters": "Path parameters",
    "request.query": "Query parameters",
    "request.headers": "Request headers",
    "request.body": "Request body",
    "response.status": "Response status",
    "response.headers": "Response headers",
    "response.body": "Response body",
    "request.matching-rules": "Request matching rules and generators",
    "response.matching-rules": "Response matching rules and generators",
}

#: The checks every HTTP interaction is expected to run; one that did not is reported ``not-run``.
CORE_CHECKS: Tuple[str, ...] = tuple(key for key in CHECK_LABELS if not key.endswith(".matching-rules"))

#: Every check the message comparison (PFX-3.6) runs, in order, with its label. The matching-rule
#: check runs only when the message declares rules.
MESSAGE_CHECK_LABELS: Dict[str, str] = {
    "message.channel": "Channel and message",
    "message.content-type": "Content type",
    "message.metadata": "Metadata (message headers)",
    "message.body": "Message contents",
    "message.matching-rules": "Matching rules and generators",
}

#: The checks every message is expected to run.
MESSAGE_CORE_CHECKS: Tuple[str, ...] = tuple(
    key for key in MESSAGE_CHECK_LABELS if not key.endswith(".matching-rules")
)

#: Fidelity codes reported under *unsupported matching rules*.
MATCHING_RULE_CODES: Tuple[str, ...] = (
    "matching-rule-not-mapped",
    "matching-rule-unverified",
    "embedded-matcher-not-mapped",
    "generator-not-applied",
)

#: Fidelity codes reported under *could not compare*.
NOT_COMPARED_CODES: Tuple[str, ...] = (
    "body-not-compared",
    "parameter-not-compared",
    "schema-not-usable",
    "oneof-relaxed",
    "interaction-not-http",
    "findings-truncated",
    "message-direction-undeclared",
    "message-resolved-by-contents",
    "metadata-not-compared",
    "interaction-not-message",
    "synchronous-message-not-compared",
)

#: Fidelity codes that mean "this interaction is not the kind the contract describes".
_NOT_APPLICABLE_CODES = ("interaction-not-http", "interaction-not-message", "synchronous-message-not-compared")

#: Failure and warning codes by the check that raises them, matched on the longest prefix. The
#: body and content-type helpers are shared by both sides, so the side is part of the prefix.
_FINDING_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("interaction.malformed", "request.operation"),
    ("request.operation.", "request.operation"),
    ("request.method.", "request.operation"),
    ("request.path-parameter.", "request.path-parameters"),
    ("request.query.", "request.query"),
    ("request.header.", "request.headers"),
    ("request.content-type.", "request.body"),
    ("request.body.", "request.body"),
    ("request.accept.", "response.status"),
    ("response.status.", "response.status"),
    ("response.header.", "response.headers"),
    ("response.content-type.", "response.body"),
    ("response.body.", "response.body"),
    ("message.channel.", "message.channel"),
    ("message.unknown", "message.channel"),
    ("message.ambiguous", "message.channel"),
    ("message.not-sent", "message.channel"),
    ("message.content-type.", "message.content-type"),
    ("message.metadata.", "message.metadata"),
    ("message.body.", "message.body"),
)

#: The part of a pact request or response a fidelity note points into, by the check it belongs to.
_NOTE_PARTS: Dict[Tuple[str, str], str] = {
    ("request", "path"): "request.path-parameters",
    ("request", "query"): "request.query",
    ("request", "headers"): "request.headers",
    ("request", "body"): "request.body",
    ("request", "matchingRules"): "request.matching-rules",
    ("request", "generators"): "request.matching-rules",
    ("response", "status"): "response.status",
    ("response", "headers"): "response.headers",
    ("response", "body"): "response.body",
    ("response", "matchingRules"): "response.matching-rules",
    ("response", "generators"): "response.matching-rules",
}

#: The same for a message (PFX-3.6), whose parts sit directly on it: one more level up.
_MESSAGE_NOTE_PARTS: Dict[str, str] = {
    "contents": "message.body",
    "metadata": "message.metadata",
    "metaData": "message.metadata",
    "matchingRules": "message.matching-rules",
    "generators": "message.matching-rules",
}


def check_of_finding(code: str) -> Optional[str]:
    """The check a failure or warning code is raised by.

    Args:
        code: A key of :data:`app.pact_oas_result.FAILURE_CLASSES` or ``WARNING_CLASSES``.

    Returns:
        The check key, or ``None`` for a code no check raises.
    """
    for prefix, check in _FINDING_PREFIXES:
        if code == prefix or code.startswith(prefix):
            return check
    return None


def check_of_note(pact_pointer: str, interaction_pointer: str) -> Optional[str]:
    """The check a fidelity note belongs to, from where in the interaction it points.

    Args:
        pact_pointer: The note's JSON Pointer into the pact.
        interaction_pointer: The interaction's own pointer (``/interactions/3``).

    Returns:
        The check key, or ``None`` for a note about the interaction as a whole.
    """
    if not pact_pointer.startswith(interaction_pointer + "/"):
        return None
    parts = pact_pointer[len(interaction_pointer) + 1 :].split("/")
    if parts[0] in _MESSAGE_NOTE_PARTS:
        return _MESSAGE_NOTE_PARTS[parts[0]]
    if len(parts) < 2:
        return None
    return _NOTE_PARTS.get((parts[0], parts[1]))


def _list(value: Any) -> List[Any]:
    """``value`` when it is a list, else an empty one (a payload is read defensively)."""
    return value if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    """``value`` when it is a mapping, else an empty one."""
    return dict(value) if isinstance(value, Mapping) else {}


def _note_entry(note: Mapping[str, Any], check: Optional[str]) -> Dict[str, Any]:
    """One fidelity note as the report lists it: the stored note plus the check it belongs to."""
    keys = ("code", "message", "pactPointer", "reason", "oasPointer", "matcher", "constraint")
    entry = {key: note[key] for key in keys if note.get(key) is not None}
    entry["check"] = check
    return entry


def _not_run_reason(not_http: bool, first_failed: Optional[str], messages: bool = False) -> str:
    """Why a core check did not run."""
    labels = MESSAGE_CHECK_LABELS if messages else CHECK_LABELS
    if not_http:
        if messages:
            return "the interaction has no message to compare"
        return "the interaction has no HTTP exchange to compare"
    if first_failed:
        return f"not run because an earlier check failed ({labels.get(first_failed, first_failed)})"
    return "not run"


def _checks(
    interaction: Mapping[str, Any],
    notes: Sequence[Dict[str, Any]],
    not_http: bool,
    messages: bool = False,
) -> List[Dict[str, Any]]:
    """Every check of one interaction with its status, in run order.

    Args:
        interaction: The stored interaction.
        notes: Its fidelity notes as :func:`_note_entry` made them.
        not_http: Whether the interaction is not the kind the contract describes (a message
            against OpenAPI, an HTTP interaction against AsyncAPI).
        messages: Whether the contract is AsyncAPI, so the message checks apply.

    Returns:
        One entry per check: ``check``, ``label``, ``status``, the counts of ``failures``,
        ``warnings`` and ``notes`` attributed to it, and ``reason`` for a ``not-run`` check.
    """
    ran = [check for check in _list(interaction.get("checks")) if isinstance(check, str)]
    failures: Dict[str, int] = {}
    warnings: Dict[str, int] = {}
    for bucket, findings in ((failures, interaction.get("failures")), (warnings, interaction.get("warnings"))):
        for finding in _list(findings):
            check = check_of_finding(str(_dict(finding).get("code", "")))
            if check is not None:
                bucket[check] = bucket.get(check, 0) + 1
    noted: Dict[str, int] = {}
    for note in notes:
        if note["check"] is not None:
            noted[note["check"]] = noted.get(note["check"], 0) + 1

    labels, core = (MESSAGE_CHECK_LABELS, MESSAGE_CORE_CHECKS) if messages else (CHECK_LABELS, CORE_CHECKS)
    first_failed = next((check for check in ran if failures.get(check)), None)
    keys = [key for key in labels if key in core or key in ran or noted.get(key)]
    keys += [check for check in ran if check not in labels]
    entries: List[Dict[str, Any]] = []
    for key in keys:
        entry: Dict[str, Any] = {"check": key, "label": labels.get(key, key)}
        if failures.get(key):
            entry["status"] = CHECK_FAILED
        elif noted.get(key):
            entry["status"] = CHECK_PARTIAL
        elif key in ran:
            entry["status"] = CHECK_COMPARED
        else:
            entry["status"] = CHECK_NOT_RUN
            entry["reason"] = _not_run_reason(not_http, first_failed, messages)
        entry["failures"] = failures.get(key, 0)
        entry["warnings"] = warnings.get(key, 0)
        entry["notes"] = noted.get(key, 0)
        entries.append(entry)
    return entries


def _interaction_report(interaction: Mapping[str, Any], messages: bool = False) -> Dict[str, Any]:
    """The report of one stored interaction.

    Args:
        interaction: One entry of the payload's ``interactions``.
        messages: Whether the comparison was with an AsyncAPI contract (PFX-3.6).

    Returns:
        ``index``, ``description``, ``pointer``, ``verdict``, ``operation``, ``checks``,
        ``matchingRules`` (the engine's counts), ``unsupportedMatchingRules``, ``couldNotCompare``,
        ``failures`` and ``warnings`` (counts).
    """
    pointer = str(interaction.get("pointer", ""))
    notes = [
        _note_entry(note, check_of_note(str(note.get("pactPointer", "")), pointer))
        for note in (_dict(raw) for raw in _list(interaction.get("fidelity")))
    ]
    not_http = any(note["code"] in _NOT_APPLICABLE_CODES for note in notes)
    report: Dict[str, Any] = {
        "index": interaction.get("index"),
        "description": interaction.get("description"),
        "pointer": pointer,
        "verdict": interaction.get("verdict"),
        "operation": interaction.get("operation"),
    }
    if messages:
        report["message"] = interaction.get("message")
    return {
        **report,
        "checks": _checks(interaction, notes, not_http, messages),
        "matchingRules": _dict(interaction.get("matchingRules")),
        "unsupportedMatchingRules": [note for note in notes if note["code"] in MATCHING_RULE_CODES],
        # A code neither table knows (a newer engine) is still reported, never dropped.
        "couldNotCompare": [note for note in notes if note["code"] not in MATCHING_RULE_CODES],
        "failures": len(_list(interaction.get("failures"))),
        "warnings": len(_list(interaction.get("warnings"))),
    }


def _strength(verdict: Optional[str], interactions: Sequence[Dict[str, Any]], error: bool) -> str:
    """How strong the comparison's answer is (see the ``STRENGTH_*`` constants)."""
    if verdict == VERDICT_FAIL and not error:
        return STRENGTH_FAILED
    compared = [item for item in interactions if any(check["status"] != CHECK_NOT_RUN for check in item["checks"])]
    if error or not compared:
        return STRENGTH_NONE
    if verdict == VERDICT_PASS and len(compared) == len(interactions):
        return STRENGTH_FULL
    return STRENGTH_PARTIAL


def _plural(count: int, word: str) -> str:
    """``1 interaction`` / ``2 interactions``."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def _statement(strength: str, summary: Mapping[str, int], error: Optional[str], messages: bool = False) -> str:
    """One sentence a reader can take the verdict at."""
    if error:
        return f"Nothing was compared: {error}."
    total = summary["interactions"]
    if total == 0:
        return "Nothing was compared: the pact has no interactions."
    if strength == STRENGTH_NONE:
        if messages:
            return "Nothing was compared: no interaction is a message to compare with the AsyncAPI provider contract."
        return "Nothing was compared: no interaction has an HTTP exchange to compare with the provider contract."
    gaps = [
        f"{summary[key]} {one if summary[key] == 1 else many}"
        for key, one, many in (
            ("unsupportedMatchingRules", "unsupported matching rule", "unsupported matching rules"),
            ("couldNotCompare", "item not compared", "items not compared"),
            ("checksNotRun", "check not run", "checks not run"),
        )
        if summary[key]
    ]
    if strength == STRENGTH_FAILED:
        text = f"The provider contract contradicts {summary['failed']} of {_plural(total, 'interaction')}"
        return f"{text}; also {', '.join(gaps)}." if gaps else f"{text}."
    if strength == STRENGTH_FULL:
        return f"Every check ran on all {_plural(total, 'interaction')} and nothing was left out."
    return (
        f"Passed, but not everything was compared: {summary['fullyCompared']} of "
        f"{_plural(total, 'interaction')} compared in full; {', '.join(gaps) or 'some items not compared'}."
    )


def build_fidelity_report(comparison: Mapping[str, Any]) -> Dict[str, Any]:
    """The fidelity report of one stored bi-directional comparison.

    Args:
        comparison: The ``comparison`` payload of a ``kind = bidirectional`` verification result
            (:func:`app.bidirectional_verification.stored_comparison` /
            :func:`~app.bidirectional_verification.error_comparison`, weighed by
            :func:`~app.bidirectional_verification.apply_evidence_policy`).

    Returns:
        ``verdict`` (the stored verdict, ``unverified`` included), ``comparisonVerdict`` (the
        comparison's own), ``strength``, ``statement``, ``selfVerification`` (the provider
        contract's evidence status, when recorded), ``error`` (when nothing could be compared),
        ``summary`` and one entry per interaction. Key and list order are fixed.
    """
    payload = _dict(comparison)
    error = _dict(payload.get("error")) or None
    messages = payload.get("contractType") == "asyncapi"
    interactions = [_interaction_report(_dict(item), messages) for item in _list(payload.get("interactions"))]
    verdict = payload.get("verdict")
    comparison_verdict = payload.get("comparisonVerdict") or verdict
    statuses = [[check["status"] for check in item["checks"]] for item in interactions]
    summary = {
        "interactions": len(interactions),
        "fullyCompared": sum(
            1
            for item, checks in zip(interactions, statuses)
            if item["verdict"] == VERDICT_PASS and all(status == CHECK_COMPARED for status in checks)
        ),
        "partial": sum(1 for item in interactions if item["verdict"] == VERDICT_PARTIAL),
        "failed": sum(1 for item in interactions if item["verdict"] == VERDICT_FAIL),
        "notCompared": sum(1 for checks in statuses if checks and all(status == CHECK_NOT_RUN for status in checks)),
        "checksCompared": sum(checks.count(CHECK_COMPARED) for checks in statuses),
        "checksPartial": sum(checks.count(CHECK_PARTIAL) for checks in statuses),
        "checksFailed": sum(checks.count(CHECK_FAILED) for checks in statuses),
        "checksNotRun": sum(checks.count(CHECK_NOT_RUN) for checks in statuses),
        "unsupportedMatchingRules": sum(len(item["unsupportedMatchingRules"]) for item in interactions),
        "couldNotCompare": sum(len(item["couldNotCompare"]) for item in interactions),
    }
    strength = _strength(comparison_verdict, interactions, error is not None)
    evidence = _dict(payload.get("providerContractEvidence"))
    report: Dict[str, Any] = {
        "verdict": verdict,
        "comparisonVerdict": comparison_verdict,
        "strength": strength,
        "statement": _statement(strength, summary, error.get("message") if error else None, messages),
        "selfVerification": evidence.get("status"),
        "providerContractSha": payload.get("providerContractSha"),
        "consumer": payload.get("consumer"),
        "provider": payload.get("provider"),
        "pactSpecification": payload.get("pactSpecification"),
        **(
            {"contractType": "asyncapi", "asyncapiVersion": payload.get("asyncapiVersion")}
            if messages
            else {"oasVersion": payload.get("oasVersion")}
        ),
        "summary": summary,
        "interactions": interactions,
    }
    if error:
        report["error"] = {"code": error.get("code"), "message": error.get("message")}
    return report
