"""Pact verification results: what a verifier publishes — PFX-1.4 (#6917).

After a provider build replays a pact, its Pact verifier ``POST``s the outcome to the pact's
``pb:publish-verification-results`` link. This module is the pure part of that: the request body
(:func:`parse_verification_request`, the Pact Broker's ``VerificationContract``) and the stored
record (:class:`VerificationResultRecord`). Persistence is :mod:`app.verification_result_store`.

The body, as pact-js / pact-core and the other verifiers send it::

    {
      "success": false,
      "providerApplicationVersion": "4f1e2d0",
      "buildUrl": "https://ci.example.com/builds/77",
      "testResults": [
        {"interactionId": "…", "interactionDescription": "a request for an invoice", "success": false,
         "mismatches": [{"attribute": "status", "description": "expected 200 but was 404"}]}
      ],
      "verifiedBy": {"implementation": "Pact-Rust", "version": "1.2.0",
                     "clientLanguage": {"name": "pact-js", "version": "13.1.0", "testFramework": "jest"}}
    }

``success`` and ``providerApplicationVersion`` are required, as the broker requires them.
``testResults`` is stored as sent, so a failed result keeps every mismatch. Pact-Ruby's verifier sends
an object instead (``{"tests": [...], "summary": …, "metadata": …}``); its ``tests`` array is what is
stored (PFX-1.8, #6921). Apiome adds one optional
field, ``providerVerificationReportId``: the CTG-4.3 conformance report the result was produced
with, linked rather than copied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .pact_publication import PactPublicationError
from .pacticipant import validate_url, validate_version_number
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_REPORT_NOT_FOUND",
    "CODE_VERIFICATION_INVALID",
    "CODE_VERIFICATION_NOT_FOUND",
    "MAX_TEST_RESULTS",
    "VerificationRequest",
    "VerificationResultRecord",
    "parse_verification_request",
    "verification_result_from_row",
]

#: The body of a verification result is malformed (HTTP 422, with a pointer).
CODE_VERIFICATION_INVALID = "pact-verification-invalid"
#: No such verification result (HTTP 404).
CODE_VERIFICATION_NOT_FOUND = "pact-verification-not-found"
#: ``providerVerificationReportId`` names no conformance report of this workspace (HTTP 422).
CODE_REPORT_NOT_FOUND = "pact-verification-report-not-found"

#: The most per-interaction entries one result may carry.
MAX_TEST_RESULTS = 10_000

#: The longest a ``verifiedBy`` value may be (the column width).
_LABEL_MAX = 255


class VerificationRequest(BaseModel):
    """A checked verification result, ready to store.

    Attributes:
        success: Whether every interaction passed.
        provider_version: The provider application version that verified.
        build_url: The CI build, when sent.
        test_results: The per-interaction results, as sent.
        verified_by: ``implementation``, ``version``, ``client_implementation``, ``client_version``
            and ``client_test_framework`` — each ``None`` when not sent.
        report_id: The linked CTG-4.3 conformance report, when sent.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    provider_version: str
    build_url: Optional[str] = None
    test_results: List[Any] = []
    verified_by: Dict[str, Optional[str]] = {}
    report_id: Optional[str] = None


def _invalid(pointer: str, message: str) -> PactPublicationError:
    """A ``pact-verification-invalid`` refusal locating ``pointer``."""
    return PactPublicationError(CODE_VERIFICATION_INVALID, f"{pointer or '(request body)'}: {message}", pointer=pointer)


def _label(value: Any, pointer: str) -> Optional[str]:
    """A ``verifiedBy`` value: a short string, or ``None`` when not sent.

    Raises:
        PactPublicationError: For a value that is not a string, or is too long.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(pointer, "must be a string")
    text = value.strip()
    if len(text) > _LABEL_MAX:
        raise _invalid(pointer, f"must be at most {_LABEL_MAX} characters")
    return text or None


def _verified_by(raw: Any) -> Dict[str, Optional[str]]:
    """Read ``verifiedBy`` (and its nested ``clientLanguage``)."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise _invalid("/verifiedBy", "verifiedBy must be an object")
    client = raw.get("clientLanguage")
    if client is None:
        client = {}
    if not isinstance(client, Mapping):
        raise _invalid("/verifiedBy/clientLanguage", "clientLanguage must be an object")
    return {
        "implementation": _label(raw.get("implementation"), "/verifiedBy/implementation"),
        "version": _label(raw.get("version"), "/verifiedBy/version"),
        "client_implementation": _label(client.get("name"), "/verifiedBy/clientLanguage/name"),
        "client_version": _label(client.get("version"), "/verifiedBy/clientLanguage/version"),
        "client_test_framework": _label(client.get("testFramework"), "/verifiedBy/clientLanguage/testFramework"),
    }


def parse_verification_request(raw: bytes) -> VerificationRequest:
    """Read and check the body of ``POST …/pact-version/{sha}/verification-results``.

    Unknown fields are ignored, as the broker ignores them.

    Args:
        raw: The request body, already size-limited.

    Returns:
        The checked result.

    Raises:
        PactPublicationError: ``pact-verification-invalid`` with the JSON Pointer of the problem.
        PacticipantValidationError: ``pacticipant-invalid-version`` or ``pacticipant-invalid-url``
            for a malformed provider version or build URL.
    """
    try:
        body = json.loads(raw) if raw.strip() else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid("", f"the request body is not JSON: {exc}") from exc
    if not isinstance(body, Mapping):
        raise _invalid("", "the request body must be a JSON object")

    success = body.get("success")
    if not isinstance(success, bool):
        raise _invalid("/success", "success is required and must be true or false")

    version = body.get("providerApplicationVersion")
    if not isinstance(version, str) or not version.strip():
        raise _invalid("/providerApplicationVersion", "providerApplicationVersion is required")
    version = validate_version_number(version)

    build_url = body.get("buildUrl")
    if build_url is not None and not isinstance(build_url, str):
        raise _invalid("/buildUrl", "buildUrl must be a string")
    build_url = validate_url(build_url, what="build URL")

    test_results = body.get("testResults")
    if test_results is None:
        test_results = []
    if isinstance(test_results, dict) and isinstance(test_results.get("tests"), list):
        # Pact-Ruby (pact-provider-verifier, the pact-cli image) sends its beta format —
        # {"tests": [...], "summary": {...}, "metadata": {...}} — found by the conformance suite
        # (PFX-1.8, #6921). The per-interaction results are `tests`; the summary is derivable.
        test_results = test_results["tests"]
    if not isinstance(test_results, list):
        raise _invalid("/testResults", "testResults must be an array, or an object with a tests array")
    if len(test_results) > MAX_TEST_RESULTS:
        raise _invalid("/testResults", f"send at most {MAX_TEST_RESULTS} test results")

    report_id = body.get("providerVerificationReportId")
    if report_id is not None and (not isinstance(report_id, str) or not is_uuid_string(report_id.strip())):
        raise _invalid("/providerVerificationReportId", "providerVerificationReportId must be a report id (a UUID)")

    return VerificationRequest(
        success=success,
        provider_version=version,
        build_url=build_url,
        test_results=test_results,
        verified_by=_verified_by(body.get("verifiedBy")),
        report_id=report_id.strip().lower() if isinstance(report_id, str) else None,
    )


class VerificationResultRecord(BaseModel):
    """A stored verification result, with the names its links need.

    Attributes:
        id: Row id.
        number: Its number among the results of its pact version (1, 2, 3 …).
        consumer_slug: The consumer's handle.
        consumer_name: The consumer's display name.
        provider_slug: The provider's handle.
        provider_name: The provider's display name.
        provider_version: The provider version that verified.
        consumer_version: The latest consumer version that published the verified pact.
        sha: The verified pact version.
        success: Whether every interaction passed.
        build_url: The CI build.
        provider_branch: The provider branch the verification ran on, when known.
        test_results: The per-interaction results, as sent.
        verified_by: The verifier and its client, as in :class:`VerificationRequest`.
        pact_pending: Whether the pact was pending when the verifier fetched it, when known.
        wip: Whether the pact was fetched as a work-in-progress pact.
        report_id: The linked CTG-4.3 conformance report, if any.
        created_at: When it was published (the broker's ``verificationDate``).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    number: int
    consumer_slug: str
    consumer_name: str
    provider_slug: str
    provider_name: str
    provider_version: str
    consumer_version: Optional[str] = None
    sha: str
    success: bool
    build_url: Optional[str] = None
    provider_branch: Optional[str] = None
    test_results: List[Any] = []
    verified_by: Dict[str, Optional[str]] = {}
    pact_pending: Optional[bool] = None
    wip: bool = False
    report_id: Optional[str] = None
    created_at: Optional[str] = None


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def verification_result_from_row(row: Mapping[str, Any]) -> VerificationResultRecord:
    """Build a record from a row of :data:`app.verification_result_store._RESULT_SELECT`.

    Args:
        row: The row.

    Returns:
        The record.
    """
    return VerificationResultRecord(
        id=str(row["id"]),
        number=int(row["number"]),
        consumer_slug=row["consumer_slug"],
        consumer_name=row["consumer_name"],
        provider_slug=row["provider_slug"],
        provider_name=row["provider_name"],
        provider_version=row["provider_version"],
        consumer_version=row.get("consumer_version"),
        sha=row["sha"],
        success=bool(row["success"]),
        build_url=row.get("build_url"),
        provider_branch=row.get("provider_branch"),
        test_results=list(row.get("test_results") or []),
        verified_by={
            "implementation": row.get("verified_by_implementation"),
            "version": row.get("verified_by_version"),
            "client_implementation": row.get("verified_by_client_implementation"),
            "client_version": row.get("verified_by_client_version"),
            "client_test_framework": row.get("verified_by_client_test_framework"),
        },
        pact_pending=row.get("pact_pending"),
        wip=bool(row.get("wip")),
        report_id=str(row["provider_verification_report_id"]) if row.get("provider_verification_report_id") else None,
        created_at=_iso(row.get("created_at")),
    )
