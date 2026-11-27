"""Check a pact against several provider versions before publishing it — PFX-8.4 (#7301). Pure.

``POST …/pact-broker/pacts/check`` takes an unpublished Pact document and a list of
*provider-version selectors*, compares the pact with the provider contract of every version they
name, and writes nothing (:mod:`app.pact_check_store` reads; this module holds the parts with no
database).

**Selectors** (:func:`parse_selectors`):

* ``main`` — the newest version on the provider's main branch that published a provider contract;
* ``deployed:<environment>`` — every version with a contract currently deployed to, or released in,
  that environment;
* ``version:<number>`` — one named provider version;
* ``draft:<revision>`` — a revision (label, revision id or ``latest``) of the Apiome project the
  provider is bound to, rendered as OpenAPI as it stands now. A draft has no self-verification
  evidence yet, so its verdict reads exactly as publishing that revision without evidence would.

**The same verdict as a publish.** Each comparison is the one a publish stores
(:func:`app.bidirectional_store.compare_with_target`): the same engine, the same evidence policy.

**Nothing dropped.** A selector that names nothing is listed in ``unresolved`` with the reason;
versions over the limit are listed in ``skipped``; an unknown request field or selector kind is a
``422`` naming it.

**Per interaction** the answer says ``match`` (``pass`` or ``partial``), ``differs`` (the contract
contradicts the pact) or ``not-in-spec`` (the contract declares no such operation or message), with
what the pact expects beside what the contract declares, for the difference drawer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .pact_oas_result import VERDICT_FAIL

__all__ = [
    "CODE_CHECK_INVALID",
    "CODE_CHECK_RATE_LIMITED",
    "KIND_DEPLOYED",
    "KIND_DRAFT",
    "KIND_MAIN",
    "KIND_VERSION",
    "MAX_DETAIL_BYTES",
    "MAX_SELECTORS",
    "OUTCOME_DIFFERS",
    "OUTCOME_MATCH",
    "OUTCOME_NOT_IN_SPEC",
    "CheckRequest",
    "CheckSelector",
    "PactCheckError",
    "TargetResult",
    "check_summary",
    "declared_part",
    "expected_part",
    "interaction_entries",
    "interaction_outcome",
    "parse_check_request",
    "parse_selectors",
]

#: ``pact-check-invalid``: the request is malformed; ``pointer`` locates the problem.
CODE_CHECK_INVALID = "pact-check-invalid"
#: ``pact-check-rate-limited``: over the workspace's check budget.
CODE_CHECK_RATE_LIMITED = "pact-check-rate-limited"

KIND_MAIN = "main"
KIND_DEPLOYED = "deployed"
KIND_VERSION = "version"
KIND_DRAFT = "draft"

#: The selector kinds, in the order the docs explain them.
KINDS = (KIND_MAIN, KIND_DEPLOYED, KIND_VERSION, KIND_DRAFT)

#: The most selectors one request may send.
MAX_SELECTORS = 10

#: The largest ``expected`` or ``declared`` excerpt returned for one interaction, in bytes of JSON.
MAX_DETAIL_BYTES = 8192

#: The request's fields.
_FIELDS = ("pact", "against")

OUTCOME_MATCH = "match"
OUTCOME_DIFFERS = "differs"
OUTCOME_NOT_IN_SPEC = "not-in-spec"

#: Failure codes saying the contract has no such operation or message at all.
_NOT_IN_SPEC_CODES = frozenset(
    {
        "request.operation.unknown",
        "request.method.undeclared",
        "message.channel.unknown",
        "message.unknown",
    }
)

#: How deep local ``$ref`` s are inlined in a ``declared`` excerpt.
_MAX_REF_DEPTH = 6


class PactCheckError(ValueError):
    """A check request this endpoint refuses.

    Attributes:
        code: :data:`CODE_CHECK_INVALID`.
        pointer: JSON Pointer of the problem in the request body.
    """

    def __init__(self, message: str, *, pointer: str = "") -> None:
        """Build the refusal.

        Args:
            message: What is wrong, in one sentence.
            pointer: Where, in the request body.
        """
        super().__init__(message)
        self.code = CODE_CHECK_INVALID
        self.pointer = pointer


@dataclass(frozen=True)
class CheckSelector:
    """One provider-version selector.

    Attributes:
        raw: The selector as sent (``deployed:production``).
        kind: One of :data:`KINDS`.
        value: The environment, version or revision; ``None`` for ``main``.
    """

    raw: str
    kind: str
    value: Optional[str] = None


@dataclass(frozen=True)
class CheckRequest:
    """A parsed check request.

    Attributes:
        pact: The Pact document (not yet validated as a pact).
        selectors: The selectors, duplicates removed, in the order sent.
    """

    pact: Dict[str, Any]
    selectors: Tuple[CheckSelector, ...]


def _parse_selector(text: Any, index: int) -> CheckSelector:
    """Read one selector.

    Args:
        text: The selector as sent.
        index: Its position in ``against``.

    Returns:
        The selector.

    Raises:
        PactCheckError: For anything but ``main``, ``deployed:<env>``, ``version:<n>`` or
            ``draft:<revision>``.
    """
    pointer = f"/against/{index}"
    if not isinstance(text, str) or not text.strip():
        raise PactCheckError(f"{pointer}: a selector is a non-empty string", pointer=pointer)
    raw = text.strip()
    if len(raw) > 300:
        raise PactCheckError(f"{pointer}: a selector is at most 300 characters", pointer=pointer)
    kind, sep, value = raw.partition(":")
    kind = kind.strip().lower()
    value = value.strip()
    if kind == KIND_MAIN and not sep:
        return CheckSelector(raw=raw, kind=KIND_MAIN)
    if kind in (KIND_DEPLOYED, KIND_VERSION, KIND_DRAFT):
        if not value:
            raise PactCheckError(f"{pointer}: '{kind}:' needs a value after the colon", pointer=pointer)
        return CheckSelector(raw=raw, kind=kind, value=value)
    raise PactCheckError(
        f"{pointer}: '{raw}' is not a selector; use main, deployed:<environment>, version:<number> "
        f"or draft:<revision>",
        pointer=pointer,
    )


def parse_selectors(values: Any) -> Tuple[CheckSelector, ...]:
    """Read ``against``.

    Args:
        values: The field as sent.

    Returns:
        1 to :data:`MAX_SELECTORS` selectors; a selector repeated with the same meaning is kept once.

    Raises:
        PactCheckError: When it is not a list, is empty, is too long or holds a bad selector.
    """
    if not isinstance(values, list):
        raise PactCheckError("/against: a list of provider-version selectors is required", pointer="/against")
    if not 1 <= len(values) <= MAX_SELECTORS:
        raise PactCheckError(
            f"/against: send 1 to {MAX_SELECTORS} selectors; this request has {len(values)}", pointer="/against"
        )
    selectors: List[CheckSelector] = []
    seen = set()
    for index, value in enumerate(values):
        selector = _parse_selector(value, index)
        key = (selector.kind, selector.value)
        if key not in seen:
            seen.add(key)
            selectors.append(selector)
    return tuple(selectors)


def parse_check_request(body: Any) -> CheckRequest:
    """Read the request body (already JSON-decoded).

    Args:
        body: The decoded body.

    Returns:
        The request.

    Raises:
        PactCheckError: When it is not an object, carries a field this endpoint does not read, has
            no ``pact`` object, or ``against`` is not a list of selectors.
    """
    if not isinstance(body, dict):
        raise PactCheckError("the request body must be a JSON object with 'pact' and 'against'")
    unknown = sorted(key for key in body if key not in _FIELDS)
    if unknown:
        raise PactCheckError(
            f"/{unknown[0]}: '{unknown[0]}' is not read by this endpoint; send only 'pact' and 'against'",
            pointer=f"/{unknown[0]}",
        )
    pact = body.get("pact")
    if not isinstance(pact, dict):
        raise PactCheckError("/pact: the Pact document (a JSON object) is required", pointer="/pact")
    return CheckRequest(pact=pact, selectors=parse_selectors(body.get("against")))


# ---------------------------------------------------------------------------------------------
# What each interaction says
# ---------------------------------------------------------------------------------------------


def interaction_outcome(interaction: Mapping[str, Any]) -> str:
    """``match``, ``differs`` or ``not-in-spec`` for one compared interaction.

    Args:
        interaction: One entry of a comparison payload's ``interactions``.

    Returns:
        ``not-in-spec`` when a failure says the contract declares no such operation or message,
        ``differs`` for any other failure, ``match`` otherwise (``partial`` included: its fidelity
        notes travel with it).
    """
    failures = interaction.get("failures") or []
    if any(finding.get("code") in _NOT_IN_SPEC_CODES for finding in failures):
        return OUTCOME_NOT_IN_SPEC
    if failures or interaction.get("verdict") == VERDICT_FAIL:
        return OUTCOME_DIFFERS
    return OUTCOME_MATCH


def _bounded(value: Any) -> Dict[str, Any]:
    """``{"value": …}``, or ``{"truncated": True, "bytes": n}`` past :data:`MAX_DETAIL_BYTES`."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"truncated": True, "bytes": 0}
    if len(encoded.encode("utf-8")) > MAX_DETAIL_BYTES:
        return {"truncated": True, "bytes": len(encoded.encode("utf-8"))}
    return {"value": value}


def _pointer_get(document: Any, pointer: Optional[str]) -> Any:
    """The value at a JSON Pointer (``#/a/b`` or ``/a/b``), or ``None``."""
    if not isinstance(pointer, str):
        return None
    path = pointer[1:] if pointer.startswith("#") else pointer
    node = document
    for part in [p for p in path.split("/") if p != ""] if path else []:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return None
    return node


def _inline_refs(document: Any, node: Any, depth: int = 0) -> Any:
    """``node`` with local ``$ref`` s inlined up to :data:`_MAX_REF_DEPTH` levels (cycles stop there)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#") and depth < _MAX_REF_DEPTH:
            target = _pointer_get(document, ref)
            if target is not None:
                return _inline_refs(document, target, depth + 1)
        return {key: _inline_refs(document, value, depth) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(document, item, depth) for item in node]
    return node


def _pact_interaction(pact: Mapping[str, Any], pointer: Optional[str]) -> Dict[str, Any]:
    """The pact's interaction at ``pointer`` (``/interactions/3``), or ``{}``."""
    found = _pointer_get(pact, pointer)
    return found if isinstance(found, dict) else {}


def expected_part(pact: Mapping[str, Any], interaction: Mapping[str, Any]) -> Dict[str, Any]:
    """What the pact needs, for the difference drawer.

    Args:
        pact: The Pact document.
        interaction: The compared interaction (its ``pointer`` locates it in the pact).

    Returns:
        For an HTTP interaction its ``response`` (status, headers, body); for a message its
        ``contents`` (or ``body``). Bounded by :data:`MAX_DETAIL_BYTES`.
    """
    entry = _pact_interaction(pact, interaction.get("pointer"))
    if isinstance(entry.get("response"), dict):
        return _bounded(entry["response"])
    for key in ("contents", "body"):
        if key in entry:
            return _bounded(entry[key])
    return _bounded(None)


def _response_key(responses: Mapping[str, Any], status: Any) -> Optional[str]:
    """The ``responses`` key that covers ``status``: exact, range (``2XX``) or ``default``."""
    if isinstance(status, int) and not isinstance(status, bool):
        if str(status) in responses:
            return str(status)
        ranged = f"{str(status)[0]}XX"
        for key in responses:
            if str(key).upper() == ranged:
                return str(key)
    return "default" if "default" in responses else None


def declared_part(contract: Any, pact: Mapping[str, Any], interaction: Mapping[str, Any]) -> Dict[str, Any]:
    """What the provider contract declares for the interaction, for the difference drawer.

    Args:
        contract: The provider contract (OpenAPI or AsyncAPI document).
        pact: The Pact document.
        interaction: The compared interaction.

    Returns:
        For an HTTP interaction the operation's response for the expected status (local ``$ref`` s
        inlined), with ``pointer``; for a message the declared message; ``{"value": None}`` when the
        contract declares nothing for it. Bounded by :data:`MAX_DETAIL_BYTES`.
    """
    operation = interaction.get("operation") or {}
    message = interaction.get("message") or {}
    if isinstance(operation, dict) and operation.get("pointer"):
        node = _pointer_get(contract, operation["pointer"])
        responses = node.get("responses") if isinstance(node, dict) else None
        status = (_pact_interaction(pact, interaction.get("pointer")).get("response") or {}).get("status", 200)
        if isinstance(responses, dict):
            key = _response_key(responses, status)
            if key is not None:
                pointer = f"{operation['pointer']}/responses/{key}"
                return {"pointer": pointer, **_bounded(_inline_refs(contract, responses[key]))}
        return {"pointer": operation["pointer"], **_bounded(None)}
    if isinstance(message, dict) and message.get("pointer"):
        node = _pointer_get(contract, message["pointer"])
        return {"pointer": message["pointer"], **_bounded(_inline_refs(contract, node))}
    return _bounded(None)


def _provider_states(entry: Mapping[str, Any]) -> List[str]:
    """The provider states an interaction names (v2 ``providerState`` or v3+ ``providerStates``)."""
    states: List[str] = []
    if isinstance(entry.get("providerState"), str):
        states.append(entry["providerState"])
    for state in entry.get("providerStates") or []:
        name = state.get("name") if isinstance(state, dict) else None
        if isinstance(name, str):
            states.append(name)
    return states


def interaction_entries(pact: Mapping[str, Any], contract: Any, payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One row per interaction, for the check's answer.

    Args:
        pact: The Pact document.
        contract: The provider contract (``None`` when the comparison could not run).
        payload: The comparison payload.

    Returns:
        Each interaction's index, description, method, path, expected status, provider states,
        ``outcome``, verdict, failures and warnings; a ``differs`` or ``not-in-spec`` row also
        carries ``expected`` and ``declared``.
    """
    rows: List[Dict[str, Any]] = []
    for interaction in payload.get("interactions") or []:
        entry = _pact_interaction(pact, interaction.get("pointer"))
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
        outcome = interaction_outcome(interaction)
        row: Dict[str, Any] = {
            "index": interaction.get("index"),
            "description": interaction.get("description"),
            "pointer": interaction.get("pointer"),
            "method": request.get("method"),
            "path": request.get("path"),
            "status": response.get("status"),
            "providerStates": _provider_states(entry),
            "outcome": outcome,
            "verdict": interaction.get("verdict"),
            "operation": interaction.get("operation"),
            "failures": [
                {key: finding.get(key) for key in ("code", "message", "pactPointer", "oasPointer")}
                for finding in interaction.get("failures") or []
            ],
            "warnings": [
                {key: finding.get(key) for key in ("code", "message")} for finding in interaction.get("warnings") or []
            ],
            "fidelity": len(interaction.get("fidelity") or []),
        }
        if outcome != OUTCOME_MATCH:
            row["expected"] = expected_part(pact, interaction)
            row["declared"] = declared_part(contract, pact, interaction) if contract is not None else _bounded(None)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------------------------


@dataclass
class TargetResult:
    """The check against one provider version (or draft).

    Attributes:
        selectors: The selectors that named it, as sent.
        reasons: Why each named it (``main branch main``, ``deployed to production``).
        provider_version: The provider version number, or the draft's label.
        draft: Whether this is a project revision rather than a published contract.
        branches: The provider version's branches.
        environments: Where it is deployed or released.
        verdict: ``pass``, ``partial``, ``fail`` or ``unverified`` — what a publish would record.
        comparison_verdict: The comparison's own verdict, before the evidence policy.
        success: What a publish would record as ``success``.
        evidence: The contract's self-verification status.
        source: The Apiome project and version the contract came from, when known.
        interactions: :func:`interaction_entries`.
        error: Why the comparison could not run, when it could not.
    """

    selectors: List[str]
    reasons: List[str]
    provider_version: str
    draft: bool = False
    branches: Sequence[str] = ()
    environments: Sequence[str] = ()
    verdict: Optional[str] = None
    comparison_verdict: Optional[str] = None
    success: Optional[bool] = None
    evidence: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def counts(self) -> Dict[str, int]:
        """How many interactions match, differ, or are not in the spec."""
        counts = {OUTCOME_MATCH: 0, OUTCOME_DIFFERS: 0, OUTCOME_NOT_IN_SPEC: 0}
        for row in self.interactions:
            counts[row["outcome"]] += 1
        return {
            "match": counts[OUTCOME_MATCH],
            "differs": counts[OUTCOME_DIFFERS],
            "notInSpec": counts[OUTCOME_NOT_IN_SPEC],
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the API (camelCase)."""
        payload: Dict[str, Any] = {
            "selectors": list(self.selectors),
            "reasons": list(self.reasons),
            "providerVersion": self.provider_version,
            "draft": self.draft,
            "branches": list(self.branches),
            "environments": list(self.environments),
            "verdict": self.verdict,
            "comparisonVerdict": self.comparison_verdict,
            "success": self.success,
            "selfVerification": self.evidence,
            "source": self.source,
            "counts": self.counts(),
            "interactions": self.interactions,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def check_summary(
    results: Sequence[TargetResult], unresolved: Sequence[Mapping[str, Any]], skipped: Sequence[Any]
) -> Dict[str, Any]:
    """The counts at the top of the answer, and whether everything passed.

    Args:
        results: The versions compared.
        unresolved: The selectors that named nothing.
        skipped: The versions over the limit.

    Returns:
        ``versions``, ``passed``, ``failed``, ``unresolved``, ``skipped`` and ``success`` — true only
        when at least one version was compared, every one would record ``success`` and every
        selector named something (what ``apiome pact check`` exits ``0`` on).
    """
    passed = sum(1 for result in results if result.success)
    failed = len(results) - passed
    return {
        "versions": len(results),
        "passed": passed,
        "failed": failed,
        "unresolved": len(unresolved),
        "skipped": len(skipped),
        "success": bool(results) and failed == 0 and not unresolved and not skipped,
    }
