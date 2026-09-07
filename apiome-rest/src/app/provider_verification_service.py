"""Orchestrate compile → resolve → plan → run → report → record for CTG-4.3 (#4489).

Provider verification adds no execution machinery of its own. It composes the pieces Executable
Contract Assurance already ships, in the one order that makes a spec-vs-live check meaningful:

1. :mod:`app.contract_suite_service` compiles the published version into deterministic cases —
   declared examples first, then schema-valid synthesized bodies (SIM-1.3's reuse point);
2. :mod:`app.verification_target_store` resolves and audits the deployment being checked, which is
   where the SSRF guard, the private-network approval, and the credential *reference* live;
3. :mod:`app.provider_verification` decides which of those cases this run may actually send;
4. :mod:`app.contract_runner` sends them and validates every response against the contract's own
   schema (SIM-1.4's reuse point);
5. :mod:`app.provider_verification` reads the results back as a conformance report;
6. :mod:`app.verification_evidence_store` writes the run as immutable evidence, and
   :mod:`app.provider_verification_store` writes the report beside it.

**Evidence is written for every executed run, including a failing one.** The report is a reading of
that evidence, not a substitute for it, so a gate that cites a report can always open the case
records behind it.

**A run that could not happen never invents a green one.** A version that compiles no cases, a
target that cannot be resolved, an auth reference that cannot be materialised — each answers
``ok=false`` with a stable taxonomy code, the same failure shape the rest of this surface uses.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .contract_runner import (
    AuthResolutionError,
    materialize_auth_headers,
    run_suite,
)
from .contract_suite import ContractSuiteOptions
from .contract_suite_service import (
    ContractSuiteCompileRequest,
    SchemaReferenceError,
    compile_version_contract_suite,
)
from .import_source_pipeline import build_job_error
from .mcp_credentials import load_endpoint_auth_headers
from .models import SpecImportJobError
from .provider_verification import (
    VERIFIER_NAME,
    VERIFIER_VERSION,
    ConformanceReport,
    ProviderVerificationOptions,
    TargetIdentity,
    build_conformance_report,
    plan_provider_run,
)
from .provider_verification_store import (
    ConformanceReportRecord,
    ReportActor,
    get_report_for_run,
    save_report,
)
from .verification_evidence import VerificationRunInput, VerificationRunRecord
from .verification_evidence_store import TargetActor, record_run
from .verification_target import AUTH_KIND_STORED
from .verification_target_store import resolve_target

logger = logging.getLogger(__name__)

__all__ = [
    "ProviderVerificationRequest",
    "ProviderVerificationResponse",
    "SchemaReferenceError",
    "verify_version_against_target",
]


class ProviderVerificationRequest(BaseModel):
    """What to verify, against which deployment, and how much of it may be touched."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(
        description="Verification target slug or id (ECA-1.2) naming the deployment to check.",
        min_length=1,
        max_length=200,
    )
    options: ContractSuiteOptions = Field(
        default_factory=ContractSuiteOptions,
        description=(
            "Suite compiler options; hashed into the suite digest the report and the evidence "
            "both record, so two reports with the same digest checked the same requests."
        ),
    )
    verification: ProviderVerificationOptions = Field(
        default_factory=ProviderVerificationOptions,
        description=(
            "What this run may send. Safe methods only by default; mutating operations require "
            "both `allow_mutating` and a fixture naming the operation."
        ),
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Evidence retry key; forwarded to the verification-runs store.",
        max_length=200,
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret CI context (commit, branch, workflow URL). Never credentials.",
    )


class ProviderVerificationResponse(BaseModel):
    """The outcome of one provider verification attempt."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="Whether the suite executed and a report was produced.")
    version_ref: str = Field(description="The version reference exactly as requested.")
    suite_digest: Optional[str] = Field(
        default=None, description="Digest of the suite that was executed, when compiled."
    )
    report: Optional[ConformanceReport] = Field(
        default=None, description="The conformance report when `ok` is true."
    )
    stored: Optional[ConformanceReportRecord] = Field(
        default=None,
        description=(
            "The persisted report, when it was written. Null — with `report` still populated — "
            "when persistence was not possible, so a caller is never handed a report id that "
            "does not exist."
        ),
    )
    run: Optional[VerificationRunRecord] = Field(
        default=None, description="The immutable ECA-1.3 evidence behind the report."
    )
    created: Optional[bool] = Field(
        default=None,
        description="True when evidence was newly written; False on idempotent replay.",
    )
    error: Optional[SpecImportJobError] = Field(
        default=None,
        description="Populated when `ok` is false: stable taxonomy code plus remediation.",
    )


def verify_version_against_target(
    version_ref: str,
    request: ProviderVerificationRequest,
    *,
    tenant_id: str,
    actor: TargetActor,
) -> ProviderVerificationResponse:
    """Verify one published version against one live deployment.

    Args:
        version_ref: ``project/{slug}/{version}`` or ``catalog/{item}/{version}``.
        request: Target reference, compiler options, mutation opt-in and fixtures, CI context.
        tenant_id: Authenticated tenant.
        actor: Who is running — used for the target resolve audit and the report's provenance.

    Returns:
        A :class:`ProviderVerificationResponse`. Addressing faults raise
        :class:`~app.schema_reference.SchemaReferenceError`; target faults raise
        :class:`~app.verification_target.TargetValidationError`; evidence submission faults raise
        :class:`~app.verification_evidence.EvidenceValidationError`.
    """
    compiled = compile_version_contract_suite(
        version_ref,
        ContractSuiteCompileRequest(options=request.options),
        tenant_id=tenant_id,
    )
    if not compiled.ok or compiled.manifest is None:
        return ProviderVerificationResponse(
            ok=False,
            version_ref=version_ref,
            error=compiled.error
            or build_job_error(
                "FORMAT_MISMATCH",
                "No contract suite could be compiled for this version, so there is nothing to "
                "verify a deployment against.",
            ),
        )

    manifest = compiled.manifest
    if not manifest.cases:
        return ProviderVerificationResponse(
            ok=False,
            version_ref=version_ref,
            suite_digest=manifest.digest,
            error=build_job_error(
                "FORMAT_MISMATCH",
                "The compiled suite has no executable cases, so a run would report coverage of "
                "nothing. Fix the suite's findings or widen the compiler options, then retry.",
            ),
        )

    resolved = resolve_target(
        tenant_id, request.target_ref, actor=actor, suite_digest=manifest.digest
    )

    stored_headers: Optional[Dict[str, str]] = None
    if resolved.auth.kind == AUTH_KIND_STORED and resolved.auth.ref:
        stored_headers = load_endpoint_auth_headers(resolved.auth.ref)

    try:
        auth_headers = materialize_auth_headers(resolved.auth, stored_headers=stored_headers)
    except AuthResolutionError as exc:
        return ProviderVerificationResponse(
            ok=False,
            version_ref=version_ref,
            suite_digest=manifest.digest,
            error=build_job_error("SOURCE_AUTH_REQUIRED", str(exc)),
        )

    plan = plan_provider_run(
        manifest,
        request.verification,
        target_allows_mutating=resolved.policy.allow_mutating_methods,
    )
    suite_result = run_suite(
        manifest, resolved, auth_headers=auth_headers, decisions=plan.decisions
    )

    report = build_conformance_report(
        manifest,
        plan,
        suite_result.operations,
        target=TargetIdentity(
            target_id=resolved.target_id,
            slug=resolved.slug,
            environment=resolved.environment,
            network_class=resolved.network_class,
            base_url=resolved.base_url,
        ),
        options=request.verification,
        started_at=suite_result.started_at,
        finished_at=suite_result.finished_at,
    )

    source: Dict[str, Any] = {}
    if manifest.source is not None:
        source = manifest.source.model_dump(mode="json", exclude_none=True)

    recorded = record_run(
        tenant_id,
        VerificationRunInput(
            target_ref=request.target_ref,
            suite_digest=manifest.digest,
            suite_schema_version=manifest.schema_version,
            suite_compiler_version=manifest.compiler_version,
            suite_case_count=len(manifest.cases),
            runner_name=VERIFIER_NAME,
            runner_version=VERIFIER_VERSION,
            started_at=suite_result.started_at,
            finished_at=suite_result.finished_at,
            source=source,
            context=dict(request.context or {}),
            idempotency_key=request.idempotency_key,
            operations=suite_result.operations,
        ),
        actor=actor,
    )

    stored = _persist(
        tenant_id,
        report,
        run_id=recorded.record.id,
        version_ref=version_ref,
        source=source,
        actor=actor,
        created=recorded.created,
    )

    return ProviderVerificationResponse(
        ok=True,
        version_ref=version_ref,
        suite_digest=manifest.digest,
        report=report,
        stored=stored,
        run=recorded.record,
        created=recorded.created,
    )


def _persist(
    tenant_id: str,
    report: ConformanceReport,
    *,
    run_id: str,
    version_ref: str,
    source: Dict[str, Any],
    actor: TargetActor,
    created: bool,
) -> Optional[ConformanceReportRecord]:
    """Store the report, degrading to "not stored" rather than losing the answer.

    **A replay reads rather than writes.** When ``record_run`` matched an ``idempotency_key``, the
    run already exists and already has its report — V252 keeps at most one per run, so inserting
    again would be refused. The stored report is returned instead, which is the same answer a
    sequential retry would have got.

    A storage fault is logged and reported as "not stored", never raised: the verification has
    already happened and its evidence is already immutable by the time this runs, so turning a
    filing failure into an error the caller reads as "the deployment could not be verified" would
    be a lie about the deployment.

    Args:
        tenant_id: The caller's tenant.
        report: The report to store.
        run_id: The evidence run it summarises.
        version_ref: The version reference that was verified.
        source: The manifest's provenance block.
        actor: Who ran it.
        created: Whether ``record_run`` wrote new evidence (``False`` on an idempotent replay).

    Returns:
        The stored record, or ``None`` when it could neither be written nor read back.
    """
    try:
        if not created:
            return get_report_for_run(tenant_id, run_id)
        return save_report(
            tenant_id,
            report,
            run_id=run_id,
            version_ref=version_ref,
            source=source,
            actor=ReportActor(user_id=actor.user_id, label=actor.label, kind=actor.kind),
        )
    except Exception:  # noqa: BLE001 - the check succeeded; only its filing did not
        logger.exception(
            "provider verification report could not be stored for run %s", run_id
        )
        return None
