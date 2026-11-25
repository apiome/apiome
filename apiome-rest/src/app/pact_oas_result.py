"""The result of a cross-contract comparison, and the vocabulary it is written in — PFX-2.2 (#6926).

:func:`app.pact_oas_compare.compare_pact_to_oas` returns a :class:`ComparisonResult`. This
module holds that model and the three code tables every entry of it is drawn from:

* :data:`FAILURE_CLASSES` — the provider's document contradicts the pact;
* :data:`WARNING_CLASSES` — worth a look, never a reason to fail;
* :data:`FIDELITY_CLASSES` — what was not compared, or compared more weakly than the pact asks.

The tables are published on the comparison-rules documentation page; the tests hold the page,
the tables and the golden corpus together, so a code cannot be added without being explained.

Serialization is deterministic: :meth:`ComparisonResult.to_dict` fixes key order and list
order, so equal comparisons serialize to equal JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Optional

__all__ = [
    "FAILURE_CLASSES",
    "FIDELITY_CLASSES",
    "MAX_INTERACTION_FINDINGS",
    "VERDICT_FAIL",
    "VERDICT_PARTIAL",
    "VERDICT_PASS",
    "WARNING_CLASSES",
    "ComparisonResult",
    "Finding",
    "FidelityNote",
    "InteractionResult",
    "PactOasCompareError",
]

VERDICT_PASS = "pass"
VERDICT_PARTIAL = "partial"
VERDICT_FAIL = "fail"

#: How many failures one interaction reports before the rest are only counted.
MAX_INTERACTION_FINDINGS = 50

#: Every failure the engine can report, by code. Published on the comparison-rules page; the
#: tests hold the page, this table and the golden corpus together.
FAILURE_CLASSES: Dict[str, str] = {
    "interaction.malformed": "The interaction's request declares no method or no path.",
    "request.operation.unknown": "The provider declares no operation on the request's path.",
    "request.method.undeclared": (
        "The provider declares the path, but not with the request's method."
    ),
    "request.path-parameter.invalid": (
        "A value in the request's path does not satisfy the path parameter's schema."
    ),
    "request.query.required-missing": (
        "The request leaves out a query parameter the provider requires."
    ),
    "request.query.invalid": "A query parameter's value does not satisfy its schema.",
    "request.header.required-missing": "The request leaves out a header the provider requires.",
    "request.header.invalid": "A request header's value does not satisfy its schema.",
    "request.content-type.undeclared": (
        "The request's content type is not one the operation's request body declares."
    ),
    "request.accept.unsatisfiable": (
        "The request's `Accept` header matches none of the media types the response declares."
    ),
    "request.body.undeclared": "The request sends a body to an operation that declares none.",
    "request.body.required-missing": (
        "The request has no body, but the operation's request body is required."
    ),
    "request.body.required-mismatch": (
        "The request body leaves out a property the provider requires."
    ),
    "request.body.nullable-mismatch": (
        "The request body sends `null` where the provider does not declare the value nullable."
    ),
    "request.body.unknown-property": (
        "The request body sends a property the provider's schema does not accept."
    ),
    "request.body.schema-mismatch": (
        "The request body breaks another keyword of the provider's schema "
        "(`type`, `enum`, `pattern`, a range …)."
    ),
    "response.status.undeclared": (
        "The operation declares neither the expected status, its range (`2XX`) nor `default`."
    ),
    "response.header.undeclared": (
        "The consumer expects a response header the provider does not declare."
    ),
    "response.header.invalid": (
        "An expected response header's value does not satisfy the declared schema."
    ),
    "response.content-type.undeclared": (
        "The expected response content type is not one the response declares."
    ),
    "response.body.undeclared": (
        "The consumer expects a response body, but the response declares no content."
    ),
    "response.body.nullable-mismatch": (
        "The consumer expects `null` where the provider does not declare the value nullable."
    ),
    "response.body.unknown-property": (
        "The consumer expects a property the provider's response schema does not declare."
    ),
    "response.body.schema-mismatch": (
        "The expected response body breaks another keyword of the provider's schema."
    ),
}

#: Every warning, by code.
WARNING_CLASSES: Dict[str, str] = {
    "request.query.undeclared": "The request sends a query parameter the provider does not declare.",
    "request.header.undeclared": "The request sends a header the provider does not declare.",
    "response.status.default": (
        "The expected status is covered only by the operation's `default` response."
    ),
}

#: Every kind of entry in the fidelity list, by code.
FIDELITY_CLASSES: Dict[str, str] = {
    "matching-rule-not-mapped": (
        "A matching rule has no lossless JSON Schema mapping; only its example was compared."
    ),
    "matching-rule-unverified": (
        "A matching rule was mapped, but the provider's schema does not prove it."
    ),
    "embedded-matcher-not-mapped": (
        "A body carries a matcher embedded in the example (Pact 1 Ruby style); its value was "
        "compared, the matcher was not."
    ),
    "generator-not-applied": (
        "A generator replaces the example at verification time; only the example was compared."
    ),
    "body-not-compared": (
        "A body was not validated: its content type is not JSON, it could not be decoded, "
        "the provider declares no schema for it, or it nests too deeply."
    ),
    "parameter-not-compared": (
        "A parameter or header was not validated: it declares no `schema`, is an object, or "
        "uses a `style` the engine does not parse."
    ),
    "schema-not-usable": (
        "A provider schema could not be evaluated (it does not compile, or needs a `$ref` "
        "outside the document)."
    ),
    "oneof-relaxed": (
        "Part of the expected response body is described by a `oneOf`. With `required` lifted "
        "its branches cannot be told apart, so it was compared as `anyOf`."
    ),
    "interaction-not-http": (
        "A message interaction has no HTTP exchange to compare with an OpenAPI document."
    ),
    "findings-truncated": "An interaction produced more failures than are listed.",
}


class PactOasCompareError(ValueError):
    """The inputs are not a pact and an OpenAPI 3.x document, so nothing can be compared."""


# =============================================================================================
# Result model
# =============================================================================================


@dataclass
class Finding:
    """One failure or warning.

    Attributes:
        code: Stable code (:data:`FAILURE_CLASSES` / :data:`WARNING_CLASSES`).
        message: One sentence a person can act on.
        pact_pointer: JSON Pointer of the offending part of the pact document.
        oas_pointer: Operation-anchored JSON Pointer into the OpenAPI document, or ``None``
            when no part of the document is involved.
        resolved_pointer: Where that node actually lives once ``$ref``\\ s are followed.
        keyword: The JSON Schema keyword that failed, for a schema failure.
        detail: The validator's own message, for a schema failure.
    """

    code: str
    message: str
    pact_pointer: str
    oas_pointer: Optional[str] = None
    resolved_pointer: Optional[str] = None
    keyword: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an API response.

        Returns:
            A camelCase mapping without unset fields.
        """
        payload = {
            "code": self.code,
            "message": self.message,
            "pactPointer": self.pact_pointer,
            "oasPointer": self.oas_pointer,
            "resolvedPointer": self.resolved_pointer,
            "keyword": self.keyword,
            "detail": self.detail,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class FidelityNote:
    """One thing the comparison did not vouch for.

    Attributes:
        code: Stable code (:data:`FIDELITY_CLASSES`).
        message: One sentence saying what was not compared and why.
        pact_pointer: JSON Pointer of the part of the pact it concerns.
        reason: Machine-readable reason within the code, when there is one.
        oas_pointer: JSON Pointer into the OpenAPI document, when one is involved.
        matcher: The Pact matcher or generator concerned, when the note is about one.
        constraint: The JSON Schema constraint a matching rule mapped to, when it mapped.
    """

    code: str
    message: str
    pact_pointer: str
    reason: Optional[str] = None
    oas_pointer: Optional[str] = None
    matcher: Optional[str] = None
    constraint: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an API response.

        Returns:
            A camelCase mapping without unset fields.
        """
        payload = {
            "code": self.code,
            "message": self.message,
            "pactPointer": self.pact_pointer,
            "reason": self.reason,
            "oasPointer": self.oas_pointer,
            "matcher": self.matcher,
            "constraint": self.constraint,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class InteractionResult:
    """The comparison of one interaction.

    Attributes:
        index: Position of the interaction in the pact.
        description: The interaction's description.
        pointer: JSON Pointer of the interaction in the pact document.
        operation: The matched operation (``method``, ``path``, ``pointer``, ``operationId``),
            or ``None`` when none was resolved.
        checks: The checks that actually ran, in the order they ran.
        failures: What the provider's document contradicts.
        warnings: What is worth a look.
        fidelity: What was not compared in full.
        matching_rules: Counts of the interaction's rules by outcome (``total``, ``verified``,
            ``unverified``, ``notMapped``).
    """

    index: int
    description: Optional[str]
    pointer: str
    operation: Optional[Dict[str, Any]] = None
    checks: List[str] = dataclass_field(default_factory=list)
    failures: List[Finding] = dataclass_field(default_factory=list)
    warnings: List[Finding] = dataclass_field(default_factory=list)
    fidelity: List[FidelityNote] = dataclass_field(default_factory=list)
    matching_rules: Dict[str, int] = dataclass_field(
        default_factory=lambda: {"total": 0, "verified": 0, "unverified": 0, "notMapped": 0}
    )

    @property
    def verdict(self) -> str:
        """``fail``, ``partial`` or ``pass`` for this interaction alone."""
        if self.failures:
            return VERDICT_FAIL
        return VERDICT_PARTIAL if self.fidelity else VERDICT_PASS

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an API response.

        Returns:
            A camelCase mapping.
        """
        return {
            "index": self.index,
            "description": self.description,
            "pointer": self.pointer,
            "verdict": self.verdict,
            "operation": self.operation,
            "checks": list(self.checks),
            "matchingRules": dict(self.matching_rules),
            "failures": [finding.to_dict() for finding in self.failures],
            "warnings": [finding.to_dict() for finding in self.warnings],
            "fidelity": [note.to_dict() for note in self.fidelity],
        }


@dataclass
class ComparisonResult:
    """The comparison of one pact with one provider OpenAPI document.

    Attributes:
        consumer: The pact's consumer name.
        provider: The pact's provider name.
        pact_specification: The Pact specification version the pact declares.
        oas_version: The ``openapi`` version the provider document declares.
        interactions: One result per interaction, in pact order.
    """

    consumer: Optional[str]
    provider: Optional[str]
    pact_specification: Optional[str]
    oas_version: str
    interactions: List[InteractionResult] = dataclass_field(default_factory=list)

    @property
    def verdict(self) -> str:
        """``fail`` if any interaction fails, else ``partial`` if any is partial, else ``pass``."""
        verdicts = {interaction.verdict for interaction in self.interactions}
        if VERDICT_FAIL in verdicts:
            return VERDICT_FAIL
        return VERDICT_PARTIAL if VERDICT_PARTIAL in verdicts else VERDICT_PASS

    @property
    def success(self) -> bool:
        """Whether the provider's document contradicts nothing in the pact."""
        return self.verdict != VERDICT_FAIL

    @property
    def failures(self) -> List[Finding]:
        """Every failure, in interaction order."""
        return [finding for item in self.interactions for finding in item.failures]

    @property
    def fidelity(self) -> List[FidelityNote]:
        """Every fidelity note, in interaction order."""
        return [note for item in self.interactions for note in item.fidelity]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage and for an API response.

        Returns:
            A camelCase mapping. Key order and list order are fixed, so equal comparisons
            serialize to equal JSON.
        """
        rules = {"total": 0, "verified": 0, "unverified": 0, "notMapped": 0}
        for interaction in self.interactions:
            for key in rules:
                rules[key] += interaction.matching_rules[key]
        by_verdict = {VERDICT_PASS: 0, VERDICT_PARTIAL: 0, VERDICT_FAIL: 0}
        for interaction in self.interactions:
            by_verdict[interaction.verdict] += 1
        return {
            "verdict": self.verdict,
            "success": self.success,
            "consumer": self.consumer,
            "provider": self.provider,
            "pactSpecification": self.pact_specification,
            "oasVersion": self.oas_version,
            "summary": {
                "interactions": len(self.interactions),
                "passed": by_verdict[VERDICT_PASS],
                "partial": by_verdict[VERDICT_PARTIAL],
                "failed": by_verdict[VERDICT_FAIL],
                "failures": len(self.failures),
                "warnings": sum(len(item.warnings) for item in self.interactions),
                "fidelity": len(self.fidelity),
                "failureCodes": sorted({finding.code for finding in self.failures}),
                "fidelityCodes": sorted({note.code for note in self.fidelity}),
                "matchingRules": rules,
            },
            "interactions": [interaction.to_dict() for interaction in self.interactions],
        }
