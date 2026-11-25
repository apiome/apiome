"""Publishing a provider contract with its self-verification evidence — PFX-2.1 / PFX-2.4 (#6928).

``apiome pact publish-provider-contract`` sends a provider's OpenAPI document (inline, or named as
an Apiome version) to ``PUT …/pact-broker/contracts/provider/{p}/version/{v}`` together with the
evidence that the provider honours it: a report file from Schemathesis, Dredd, Newman or any JUnit
writer (``--evidence``), or an Apiome provider-verification report (``--evidence-report``).

This module holds the pure parts — guessing media types from file names, building the request
body, and turning the response into summary lines — so the command stays a thin shell and every
rule here is unit-tested without HTTP. The server reads the report; nothing here interprets it.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

#: Contract media types by file extension.
_CONTRACT_TYPES = {
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

#: Report media types by file extension. Anything else is sent without a type and sniffed.
_EVIDENCE_TYPES = {
    ".xml": "application/xml",
    ".json": "application/json",
    ".ndjson": "application/x-ndjson",
    ".jsonl": "application/x-ndjson",
    ".txt": "text/plain",
    ".log": "text/plain",
}


def contract_content_type(path: Path, explicit: Optional[str]) -> Optional[str]:
    """The media type to send a contract file as.

    Args:
        path: The contract file.
        explicit: ``--content-type`` when given.

    Returns:
        ``explicit``, else the type its extension implies, else ``None`` (the server sniffs).
    """
    if explicit:
        return explicit
    return _CONTRACT_TYPES.get(path.suffix.lower())


def evidence_content_type(path: Path, explicit: Optional[str]) -> Optional[str]:
    """The media type to send a report file as.

    Args:
        path: The report file.
        explicit: ``--evidence-content-type`` when given.

    Returns:
        ``explicit``, else the type its extension implies (``.xml`` JUnit, ``.json`` Newman,
        ``.ndjson`` / ``.jsonl`` Schemathesis, ``.txt`` / ``.log`` plain text), else ``None``.
    """
    if explicit:
        return explicit
    return _EVIDENCE_TYPES.get(path.suffix.lower())


def _b64(raw: bytes) -> str:
    """Base64 text of some bytes."""
    return base64.b64encode(raw).decode("ascii")


def build_verification_results(
    *,
    evidence: Optional[Path],
    evidence_content_type: Optional[str],
    evidence_report: Optional[str],
    exit_code: Optional[int],
    verifier: Optional[str],
    verifier_version: Optional[str],
) -> Optional[dict[str, Any]]:
    """The ``verificationResults`` object of the request, or ``None`` when nothing is sent.

    Args:
        evidence: A report file (``--evidence``).
        evidence_content_type: Its media type (already resolved).
        evidence_report: An Apiome provider-verification report id (``--evidence-report``).
        exit_code: The verifier's exit code (``--verification-exit-code``); ``0`` is success.
        verifier: The tool that wrote the report (``--verifier``).
        verifier_version: Its version (``--verifier-version``).

    Returns:
        ``None`` when no evidence option was given. With a report file and no exit code,
        ``success`` is ``true`` — the server reads the report, and failures in it win. With an
        Apiome report and no exit code, ``success`` is left out: the report says.

    Raises:
        ValueError: when both a report file and an Apiome report id are given.
    """
    if evidence is not None and evidence_report:
        raise ValueError("give --evidence or --evidence-report, not both")
    if evidence is None and not evidence_report and exit_code is None:
        return None
    results: dict[str, Any] = {}
    if exit_code is not None:
        results["success"] = exit_code == 0
    if evidence is not None:
        results.setdefault("success", True)
        results["content"] = _b64(evidence.read_bytes())
        if evidence_content_type:
            results["contentType"] = evidence_content_type
    if evidence_report:
        results["providerVerificationReportId"] = evidence_report.strip()
    if verifier:
        results["verifier"] = verifier
    if verifier_version:
        results["verifierVersion"] = verifier_version
    return results


def build_publish_body(
    *,
    contract: Optional[Path],
    content_type: Optional[str],
    apiome_version: Optional[str],
    branch: Optional[str],
    tags: Optional[list[str]],
    build_url: Optional[str],
    verification_results: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """The JSON body of ``PUT …/contracts/provider/{p}/version/{v}``.

    Args:
        contract: The OpenAPI file, or ``None`` with ``apiome_version``.
        content_type: The contract's media type (already resolved).
        apiome_version: ``<project>@<version>`` to render the contract from instead.
        branch: The provider's branch.
        tags: Tags for the provider version.
        build_url: The CI build URL.
        verification_results: From :func:`build_verification_results`.

    Returns:
        The body, with only the fields that were given.

    Raises:
        ValueError: when both or neither of ``contract`` and ``apiome_version`` are given.
    """
    if (contract is None) == (apiome_version is None):
        raise ValueError("give the OpenAPI file or --apiome-version, exactly one")
    body: dict[str, Any] = {"contractType": "oas"}
    if contract is not None:
        body["content"] = _b64(contract.read_bytes())
        if content_type:
            body["contentType"] = content_type
    else:
        body["apiomeVersion"] = apiome_version
    if branch:
        body["branch"] = branch
    if tags:
        body["tags"] = list(tags)
    if build_url:
        body["buildUrl"] = build_url
    if verification_results is not None:
        body["verificationResults"] = verification_results
    return body


def is_verified(response: dict[str, Any]) -> bool:
    """Whether the published contract has passing self-verification evidence."""
    verification = response.get("selfVerification")
    return isinstance(verification, dict) and verification.get("providerContractVerified") is True


def summary_lines(response: dict[str, Any], *, created: bool) -> list[str]:
    """The human-readable summary of a publish.

    Args:
        response: The response body.
        created: Whether the server answered 201 (a new contract) rather than 200.

    Returns:
        Lines: what was published, the self-verification verdict with its kind, tool, digest,
        counts and reasons, and the bi-directional comparisons it ran.
    """
    provider = (response.get("provider") or {}).get("name") or "?"
    version = response.get("providerVersion") or "?"
    state = "published" if created else "already published (unchanged)"
    lines = [
        f"Provider contract of {provider} {version} {state}",
        f"  contract: sha256:{response.get('contentSha')} · OpenAPI {response.get('oasVersion')} · "
        f"{response.get('operationCount')} operation(s)",
    ]
    verification = response.get("selfVerification") or {}
    status = verification.get("status") or "missing"
    trust = "verified" if is_verified(response) else "UNVERIFIED"
    detail = ", ".join(
        part
        for part in (
            verification.get("kind"),
            f"by {verification['tool']}" if verification.get("tool") else None,
            verification.get("toolVersion"),
        )
        if part
    )
    lines.append(f"  self-verification: {status}{f' ({detail})' if detail else ''} — provider contract {trust}")
    if verification.get("digest"):
        lines.append(f"    digest: {verification['digest']}")
    summary = verification.get("summary")
    if isinstance(summary, dict):
        lines.append(
            "    tests: {tests} total, {passed} passed, {failed} failed, {errors} errored, {skipped} skipped".format(
                **{key: summary.get(key, 0) for key in ("tests", "passed", "failed", "errors", "skipped")}
            )
        )
    for reason in verification.get("reasons") or []:
        lines.append(f"    reason: {reason}")
    for note in verification.get("notes") or []:
        lines.append(f"    note: {note}")
    if not is_verified(response):
        policy = verification.get("unverifiedPolicy") or "warn"
        effect = "fail" if policy == "fail" else "read 'unverified' (warn)"
        lines.append(f"    its bi-directional comparisons {effect}")
    comparisons = response.get("comparisons") or {}
    if comparisons:
        lines.append(
            "  comparisons: {compared} compared, {already} already compared, {errors} errors, {skipped} skipped".format(
                compared=comparisons.get("compared", 0),
                already=comparisons.get("alreadyCompared", 0),
                errors=comparisons.get("errors", 0),
                skipped=comparisons.get("skipped", 0),
            )
        )
        for entry in comparisons.get("results") or []:
            consumer = " ".join(str(p) for p in (entry.get("consumer"), entry.get("consumerVersion")) if p)
            verdict = entry.get("verdict") or entry.get("status")
            lines.append(f"    {consumer}: {verdict}")
    return lines
