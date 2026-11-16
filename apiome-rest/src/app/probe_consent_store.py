"""Persistence and the run gate for verification-target probe consent — ASP-4.1 (#5939).

:mod:`app.probe_consent` decides *whether* a probe may run; this module is the only place its inputs
are read from the database and settings, its consents are written, and its decisions are audited:

**A consent is granted, read and revoked here, and nowhere else.** A grant revokes the target's
previous live consent and inserts the new one in one transaction (V386 allows one live consent per
target). A consent row is never edited — V386's trigger only lets ``revoked_at``/``revoked_by``
change, once.

**Every grant, revocation and refused run writes an ``access_audit`` row.** Auditing is best-effort,
as elsewhere: a ledger failure is logged and never turns a successful grant into an error, and never
turns a refusal into an allowed run.

**Nothing here handles a secret.** An identity is an ECA-1.2 credential *reference* — an
environment-variable name or a credential-vault id — validated by
:class:`~app.verification_target.TargetAuthReference` and constrained again by V386's CHECKs, so a
pasted token is refused at both layers.

**Reports are written once.** :func:`save_report` writes a ``security_probe_reports`` row whole;
V386 rejects every UPDATE.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .database import db
from .probe_consent import (
    CLASS_EXPLOITED_IN_TEST,
    CLASS_OBSERVED,
    CLASS_SUSPECTED,
    SUBJECT_VERIFICATION_TARGET,
    TARGET_PROFILE_IDS,
    GovernorPolicy,
    ProbeAuthorization,
    ProbeLimits,
    ProbeRefusalError,
    ProbeTargetSubject,
    TargetProbeConsent,
    TenantUsage,
    authorize_verification_target_probe,
    class_rank,
)
from .revision_deprecation import is_uuid_string
from .verification_target import (
    AUTH_KIND_NONE,
    TargetAuthReference,
    VerificationTargetRecord,
)
from .verification_target_store import TargetActor, actor_from_auth

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CONSENT_GRANT",
    "AUDIT_CONSENT_REVOKE",
    "AUDIT_RUN_REFUSED",
    "CODE_CONSENT_NOT_FOUND",
    "CODE_REPORT_INVALID",
    "CODE_REPORT_NOT_FOUND",
    "TargetActor",
    "actor_from_auth",
    "ProbeConsentGrant",
    "ProbeConsentRecord",
    "ProbeConsentStoreError",
    "SecurityProbeReportRecord",
    "SecurityProbeReportSummary",
    "authorize_probe_run",
    "consent_for_gate",
    "get_live_consent",
    "get_report",
    "governor_policy",
    "grant_consent",
    "list_reports",
    "revoke_consent",
    "run_limits",
    "save_report",
    "tenant_usage",
]

#: ``access_audit.action`` for a consent grant.
AUDIT_CONSENT_GRANT = "security_probe.consent.grant"
#: ``access_audit.action`` for a consent revocation.
AUDIT_CONSENT_REVOKE = "security_probe.consent.revoke"
#: ``access_audit.action`` for a refused probe run.
AUDIT_RUN_REFUSED = "security_probe.run.refused"

#: The target has no live consent to read or revoke.
CODE_CONSENT_NOT_FOUND = "probe-consent-not-found"
#: No report with that id in the tenant.
CODE_REPORT_NOT_FOUND = "security-probe-report-not-found"
#: A report whose counts contradict its authorization (a runner bug; refused, never stored).
CODE_REPORT_INVALID = "security-probe-report-invalid"

#: Ceiling on a list read.
MAX_LIST_LIMIT = 200


class ProbeConsentStoreError(ValueError):
    """A store operation refused, with a stable code a route maps to a status.

    Attributes:
        code: The stable code.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# =================================================================================================
# Models.
# =================================================================================================


def _identity_reference(value: Optional[TargetAuthReference]) -> Optional[TargetAuthReference]:
    """Refuse an identity of kind ``none`` — an identity has to reference a credential.

    Args:
        value: The submitted reference.

    Returns:
        The reference unchanged, or ``None``.

    Raises:
        ValueError: When the reference names no credential.
    """
    if value is not None and value.kind == AUTH_KIND_NONE:
        raise ValueError(
            "a test identity must reference a credential (kind 'env' or 'stored'); omit the "
            "identity instead of sending kind 'none'"
        )
    return value


class ProbeConsentGrant(BaseModel):
    """The body of a consent grant."""

    model_config = ConfigDict(extra="forbid")

    ownership_declared: bool = Field(
        description=(
            "You declare that you own this target or are authorized to test it. Must be `true`; "
            "probing a system you do not control is an attack."
        ),
    )
    expires_at: datetime = Field(
        description="When the consent stops authorizing runs. Required, timezone-aware, in the future.",
    )
    profiles_allowed: List[str] = Field(
        min_length=1,
        description=f"Probe profiles the consent authorizes: {', '.join(TARGET_PROFILE_IDS)}.",
    )
    identity_a: Optional[TargetAuthReference] = Field(
        default=None,
        description=(
            "Test identity A — a credential reference (`env` variable name or `stored` vault id), "
            "never a credential."
        ),
    )
    identity_b: Optional[TargetAuthReference] = Field(
        default=None,
        description="Test identity B, for probes that need two identities. Same shape as A.",
    )

    @field_validator("ownership_declared")
    @classmethod
    def _ownership_must_be_declared(cls, value: bool) -> bool:
        """Refuse a grant that does not declare ownership."""
        if value is not True:
            raise ValueError("ownership_declared must be true to grant probe consent")
        return value

    @field_validator("expires_at")
    @classmethod
    def _expiry_is_aware(cls, value: datetime) -> datetime:
        """Refuse a naive timestamp (its meaning depends on the server's clock zone)."""
        if value.tzinfo is None:
            raise ValueError("expires_at must include a timezone offset")
        return value

    @field_validator("profiles_allowed")
    @classmethod
    def _known_profiles(cls, value: List[str]) -> List[str]:
        """Refuse unknown profiles; de-duplicate into invasiveness order."""
        unknown = sorted(set(value) - set(TARGET_PROFILE_IDS))
        if unknown:
            raise ValueError(
                f"unknown probe profile(s) {unknown}; known: {list(TARGET_PROFILE_IDS)}"
            )
        return [p for p in TARGET_PROFILE_IDS if p in value]

    @field_validator("identity_a", "identity_b")
    @classmethod
    def _identity_names_a_credential(
        cls, value: Optional[TargetAuthReference]
    ) -> Optional[TargetAuthReference]:
        """Refuse an identity of kind ``none``."""
        return _identity_reference(value)


class ProbeConsentRecord(BaseModel):
    """A stored consent, as the API returns it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Consent id.")
    tenant_id: str = Field(description="Tenant that owns it.")
    target_id: str = Field(description="Verification target it authorizes probing.")
    ownership_declared: bool = Field(description="The grantor's ownership declaration.")
    approved_by: Optional[str] = Field(default=None, description="User who granted it.")
    approved_at: datetime = Field(description="When it was granted.")
    expires_at: datetime = Field(description="When it stops authorizing runs.")
    profiles_allowed: List[str] = Field(description="Profiles it authorizes.")
    identity_a: Optional[TargetAuthReference] = Field(default=None, description="Test identity A.")
    identity_b: Optional[TargetAuthReference] = Field(default=None, description="Test identity B.")
    revoked_at: Optional[datetime] = Field(default=None, description="When it was revoked.")
    revoked_by: Optional[str] = Field(default=None, description="User who revoked it.")
    created_at: Optional[datetime] = Field(default=None, description="When the row was written.")
    status: str = Field(description="`active`, `expired` or `revoked`, at read time.")


class SecurityProbeReportSummary(BaseModel):
    """A probe report without its body — what a list read returns."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Report id.")
    tenant_id: str = Field(description="Tenant that owns it.")
    target_id: Optional[str] = Field(default=None, description="Target id at run time.")
    target_slug: str = Field(description="Target handle at run time.")
    target_environment: str = Field(description="Environment class at run time.")
    target_network_class: str = Field(default="public", description="`public` or `private`.")
    target_base_url: str = Field(description="Base URL at run time.")
    profile: str = Field(description="Profile that ran.")
    consent_id: Optional[str] = Field(default=None, description="Consent that authorized it.")
    hosted_mock: bool = Field(description="Whether the target was the Apiome-hosted mock.")
    explicit_approval: bool = Field(description="The per-run approval flag.")
    proof_ceiling: str = Field(description="Strongest tier the run could report.")
    limits: Dict[str, Any] = Field(default_factory=dict, description="Per-run limits.")
    count_suspected: int = Field(description="Findings at `suspected`.")
    count_observed: int = Field(description="Findings at `observed`.")
    count_exploited_in_test: int = Field(description="Findings at `exploited-in-test`.")
    evidence_run_id: Optional[str] = Field(default=None, description="ECA-1.3 evidence run.")
    created_at: Optional[datetime] = Field(default=None, description="When it was written.")
    created_by: Optional[str] = Field(default=None, description="User who ran it.")
    actor_label: Optional[str] = Field(default=None, description="Actor label at the time.")
    actor_kind: str = Field(default="user", description="`user`, `api_key` or `system`.")


class SecurityProbeReportRecord(SecurityProbeReportSummary):
    """A probe report with its body."""

    report: Dict[str, Any] = Field(default_factory=dict, description="The stored report body.")


# =================================================================================================
# Row adapters.
# =================================================================================================

_CONSENT_COLUMNS = """
    id::text AS id,
    tenant_id::text AS tenant_id,
    target_id::text AS target_id,
    ownership_declared,
    approved_by::text AS approved_by,
    approved_at,
    expires_at,
    profiles_allowed,
    identity_a_kind, identity_a_scheme, identity_a_ref, identity_a_header_name,
    identity_b_kind, identity_b_scheme, identity_b_ref, identity_b_header_name,
    revoked_at,
    revoked_by::text AS revoked_by,
    created_at
"""

_REPORT_SUMMARY_COLUMNS = """
    id::text AS id,
    tenant_id::text AS tenant_id,
    target_id::text AS target_id,
    target_slug,
    target_environment,
    target_network_class,
    target_base_url,
    profile,
    consent_id::text AS consent_id,
    hosted_mock,
    explicit_approval,
    proof_ceiling,
    limits,
    count_suspected,
    count_observed,
    count_exploited_in_test,
    evidence_run_id::text AS evidence_run_id,
    created_at,
    created_by::text AS created_by,
    actor_label,
    actor_kind
"""


def _now() -> datetime:
    """The current UTC time (one seam for tests)."""
    return datetime.now(timezone.utc)


def _identity_from_row(row: Mapping[str, Any], prefix: str) -> Optional[TargetAuthReference]:
    """Rebuild an identity reference from its four ``<prefix>_*`` columns, or ``None``."""
    kind = row.get(f"{prefix}_kind")
    if not kind:
        return None
    return TargetAuthReference(
        kind=kind,
        scheme=row.get(f"{prefix}_scheme"),
        ref=row.get(f"{prefix}_ref"),
        header_name=row.get(f"{prefix}_header_name"),
    )


def _identity_params(value: Optional[TargetAuthReference]) -> tuple:
    """The four column values for an identity reference (all NULL when absent)."""
    if value is None:
        return (None, None, None, None)
    return (value.kind, value.scheme, value.ref, value.header_name)


def consent_record_from_row(
    row: Mapping[str, Any], now: Optional[datetime] = None
) -> ProbeConsentRecord:
    """Adapt a ``verification_target_probe_consents`` row.

    Args:
        row: The row (``_CONSENT_COLUMNS`` shape).
        now: The time the ``status`` is computed at (defaults to now).

    Returns:
        The record.
    """
    gate = _gate_from_row(row)
    return ProbeConsentRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        target_id=str(row["target_id"]),
        ownership_declared=bool(row["ownership_declared"]),
        approved_by=row.get("approved_by"),
        approved_at=row["approved_at"],
        expires_at=row["expires_at"],
        profiles_allowed=list(row.get("profiles_allowed") or []),
        identity_a=_identity_from_row(row, "identity_a"),
        identity_b=_identity_from_row(row, "identity_b"),
        revoked_at=row.get("revoked_at"),
        revoked_by=row.get("revoked_by"),
        created_at=row.get("created_at"),
        status=gate.status(now or _now()),
    )


def _gate_from_row(row: Mapping[str, Any]) -> TargetProbeConsent:
    """Build the pure gate's view of a consent row."""
    a = _identity_from_row(row, "identity_a")
    b = _identity_from_row(row, "identity_b")
    return TargetProbeConsent(
        consent_id=str(row["id"]),
        target_id=str(row["target_id"]),
        ownership_declared=bool(row["ownership_declared"]),
        approved_by=row.get("approved_by"),
        approved_at=row["approved_at"],
        expires_at=row["expires_at"],
        profiles_allowed=tuple(row.get("profiles_allowed") or ()),
        identity_a=a.model_dump() if a else None,
        identity_b=b.model_dump() if b else None,
        revoked_at=row.get("revoked_at"),
    )


def consent_for_gate(record: ProbeConsentRecord) -> TargetProbeConsent:
    """Convert an API consent record into the pure gate's :class:`TargetProbeConsent`.

    Args:
        record: The stored consent.

    Returns:
        The gate's view of it.
    """
    return TargetProbeConsent(
        consent_id=record.id,
        target_id=record.target_id,
        ownership_declared=record.ownership_declared,
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        expires_at=record.expires_at,
        profiles_allowed=tuple(record.profiles_allowed),
        identity_a=record.identity_a.model_dump() if record.identity_a else None,
        identity_b=record.identity_b.model_dump() if record.identity_b else None,
        revoked_at=record.revoked_at,
    )


def _report_from_row(row: Mapping[str, Any], *, with_body: bool) -> SecurityProbeReportSummary:
    """Adapt a ``security_probe_reports`` row into a summary or a full record."""
    fields: Dict[str, Any] = {
        key: row.get(key)
        for key in SecurityProbeReportSummary.model_fields
        if key in row
    }
    fields["limits"] = dict(row.get("limits") or {})
    if with_body:
        return SecurityProbeReportRecord(**fields, report=dict(row.get("report") or {}))
    return SecurityProbeReportSummary(**fields)


# =================================================================================================
# Audit.
# =================================================================================================


def _audit(
    *,
    tenant_id: str,
    action: str,
    actor: TargetActor,
    target: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Append one ``access_audit`` row, best-effort.

    Args:
        tenant_id: Tenant the action happened in.
        action: One of the ``AUDIT_*`` actions.
        actor: Who acted.
        target: The verification target id the action concerns.
        detail: Non-secret context (codes, profile, expiry — never a credential).
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor.user_id,
            actor_label=actor.label,
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the action it records
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


# =================================================================================================
# Consent: grant, read, revoke.
# =================================================================================================


def get_live_consent(
    tenant_id: str, target_id: str, *, now: Optional[datetime] = None
) -> Optional[ProbeConsentRecord]:
    """Read a target's unrevoked consent (which may have expired).

    Args:
        tenant_id: The caller's tenant.
        target_id: The verification target id.
        now: Time ``status`` is computed at.

    Returns:
        The consent, or ``None`` when the target has no unrevoked consent.
    """
    if not is_uuid_string(str(tenant_id or "")) or not is_uuid_string(str(target_id or "")):
        return None
    rows = db.execute_query(
        f"""
        SELECT {_CONSENT_COLUMNS}
        FROM apiome.verification_target_probe_consents
        WHERE tenant_id = %s::uuid AND target_id = %s::uuid AND revoked_at IS NULL
        """,
        (tenant_id, target_id),
    )
    return consent_record_from_row(rows[0], now) if rows else None


def grant_consent(
    tenant_id: str,
    target: VerificationTargetRecord,
    grant: ProbeConsentGrant,
    *,
    actor: TargetActor,
    now: Optional[datetime] = None,
) -> ProbeConsentRecord:
    """Grant probe consent for a target, replacing any live consent, and audit it.

    The previous live consent (if any) is revoked and the new one inserted in one transaction, so a
    target is never without its one live consent row mid-grant and never has two.

    Args:
        tenant_id: The caller's tenant.
        target: The target (already resolved in this tenant).
        grant: The validated grant body.
        actor: The approving user; ``user_id`` is required (``approved_by`` is NOT NULL).
        now: The grant time.

    Returns:
        The stored consent.

    Raises:
        ProbeConsentStoreError: ``probe-consent-invalid`` when the expiry is not in the future or
            the approver is unattributable.
    """
    at = now or _now()
    if grant.expires_at <= at:
        raise ProbeConsentStoreError(
            "probe-consent-invalid", "expires_at must be in the future"
        )
    if not actor.user_id or not is_uuid_string(str(actor.user_id)):
        raise ProbeConsentStoreError(
            "probe-consent-invalid", "probe consent must be granted by an identified user"
        )
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE apiome.verification_target_probe_consents
                SET revoked_at = %s, revoked_by = %s::uuid
                WHERE tenant_id = %s::uuid AND target_id = %s::uuid AND revoked_at IS NULL
                RETURNING id::text AS id
                """,
                (at, actor.user_id, tenant_id, target.id),
            )
            replaced = [r["id"] for r in cursor.fetchall()]
            cursor.execute(
                f"""
                INSERT INTO apiome.verification_target_probe_consents (
                    tenant_id, target_id, ownership_declared, approved_by, approved_at,
                    expires_at, profiles_allowed,
                    identity_a_kind, identity_a_scheme, identity_a_ref, identity_a_header_name,
                    identity_b_kind, identity_b_scheme, identity_b_ref, identity_b_header_name
                )
                VALUES (
                    %s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s::text[],
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING {_CONSENT_COLUMNS}
                """,
                (
                    tenant_id,
                    target.id,
                    True,
                    actor.user_id,
                    at,
                    grant.expires_at,
                    list(grant.profiles_allowed),
                    *_identity_params(grant.identity_a),
                    *_identity_params(grant.identity_b),
                ),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    record = consent_record_from_row(row, at)
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_CONSENT_GRANT,
        actor=actor,
        target=target.id,
        detail={
            "consent_id": record.id,
            "target_slug": target.slug,
            "environment": target.environment,
            "profiles_allowed": record.profiles_allowed,
            "expires_at": record.expires_at.isoformat(),
            "identities": [
                name for name in ("identity_a", "identity_b") if getattr(record, name) is not None
            ],
            "replaced_consent_ids": replaced,
        },
    )
    return record


def revoke_consent(
    tenant_id: str,
    target: VerificationTargetRecord,
    *,
    actor: TargetActor,
    now: Optional[datetime] = None,
) -> ProbeConsentRecord:
    """Revoke a target's live consent and audit it.

    Args:
        tenant_id: The caller's tenant.
        target: The target.
        actor: Who revoked it.
        now: The revocation time.

    Returns:
        The revoked consent.

    Raises:
        ProbeConsentStoreError: :data:`CODE_CONSENT_NOT_FOUND` when there is nothing to revoke.
    """
    at = now or _now()
    revoked_by = actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None
    rows = db.execute_query(
        f"""
        UPDATE apiome.verification_target_probe_consents
        SET revoked_at = %s, revoked_by = %s::uuid
        WHERE tenant_id = %s::uuid AND target_id = %s::uuid AND revoked_at IS NULL
        RETURNING {_CONSENT_COLUMNS}
        """,
        (at, revoked_by, tenant_id, target.id),
    )
    if not rows:
        raise ProbeConsentStoreError(
            CODE_CONSENT_NOT_FOUND, f"target '{target.slug}' has no live probe consent"
        )
    record = consent_record_from_row(rows[0], at)
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_CONSENT_REVOKE,
        actor=actor,
        target=target.id,
        detail={"consent_id": record.id, "target_slug": target.slug},
    )
    return record


# =================================================================================================
# The run gate.
# =================================================================================================


def governor_policy() -> GovernorPolicy:
    """The kill switch and tenant caps for verification-target probes, from settings."""
    return GovernorPolicy(
        enabled=bool(settings.security_probe_enabled),
        max_concurrent_per_tenant=int(settings.security_probe_max_concurrent_per_tenant),
        max_runs_per_hour_per_tenant=int(settings.security_probe_max_runs_per_hour_per_tenant),
        subject_kind=SUBJECT_VERIFICATION_TARGET,
    )


def run_limits() -> ProbeLimits:
    """The per-run limits for verification-target probes, from settings."""
    return ProbeLimits(max_requests=int(settings.security_probe_max_requests_per_run))


def tenant_usage(
    tenant_id: str, *, now: Optional[datetime] = None, active_runs: int = 0
) -> TenantUsage:
    """Read a tenant's trailing-hour probe run count from ``security_probe_reports``.

    Args:
        tenant_id: The tenant.
        now: The current time.
        active_runs: Runs the caller knows are in flight (reports are written when a run ends, so
            the in-flight count comes from the runner, not from this table).

    Returns:
        The usage the governor checks.
    """
    if not is_uuid_string(str(tenant_id or "")):
        return TenantUsage(active_runs=active_runs)
    since = (now or _now()) - timedelta(hours=1)
    rows = db.execute_query(
        """
        SELECT count(*)::int AS n
        FROM apiome.security_probe_reports
        WHERE tenant_id = %s::uuid AND created_at >= %s
        """,
        (tenant_id, since),
    )
    return TenantUsage(active_runs=active_runs, runs_last_hour=int(rows[0]["n"]) if rows else 0)


def authorize_probe_run(
    tenant_id: str,
    target: VerificationTargetRecord,
    *,
    profile_id: Optional[str],
    explicit_approval: bool,
    actor: TargetActor,
    now: Optional[datetime] = None,
    active_runs: int = 0,
) -> ProbeAuthorization:
    """Decide whether a probe run against ``target`` may start; audit a refusal.

    Reads the live consent, the kill switch, the caps and the tenant's usage, and hands them to
    :func:`app.probe_consent.authorize_verification_target_probe`. A refusal writes an
    ``access_audit`` row (:data:`AUDIT_RUN_REFUSED`, with the stable code and the approval flag) and
    is re-raised. ASP-4.2's runner calls this before sending anything.

    Args:
        tenant_id: The caller's tenant.
        target: The resolved target.
        profile_id: Requested profile (``passive`` when ``None``).
        explicit_approval: The per-run approval flag.
        actor: Who requested the run.
        now: The current time.
        active_runs: Runs in flight for this tenant, when the caller tracks them.

    Returns:
        The authorization the run carries.

    Raises:
        ProbeRefusalError: With the refusal's stable code.
    """
    at = now or _now()
    live = get_live_consent(tenant_id, target.id, now=at)
    try:
        return authorize_verification_target_probe(
            target=ProbeTargetSubject(
                target_id=target.id, environment=target.environment, base_url=target.base_url
            ),
            consent=consent_for_gate(live) if live else None,
            profile_id=profile_id,
            explicit_approval=explicit_approval,
            policy=governor_policy(),
            usage=tenant_usage(tenant_id, now=at, active_runs=active_runs),
            now=at,
            mock_origin=settings.mock_public_base_url,
            limits=run_limits(),
        )
    except ProbeRefusalError as exc:
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_RUN_REFUSED,
            actor=actor,
            target=target.id,
            detail={
                "code": exc.code,
                "message": str(exc),
                "target_slug": target.slug,
                "environment": target.environment,
                "profile": profile_id,
                "explicit_approval": bool(explicit_approval),
                "consent_id": live.id if live else None,
            },
        )
        raise


# =================================================================================================
# Reports.
# =================================================================================================


def save_report(
    tenant_id: str,
    target: VerificationTargetRecord,
    authorization: ProbeAuthorization,
    *,
    counts: Mapping[str, int],
    report: Mapping[str, Any],
    actor: TargetActor,
    evidence_run_id: Optional[str] = None,
) -> SecurityProbeReportRecord:
    """Write one write-once ``security_probe_reports`` row for an authorized run.

    Args:
        tenant_id: The caller's tenant.
        target: The target as it was at run time (snapshotted onto the row).
        authorization: What :func:`authorize_probe_run` returned for the run.
        counts: Findings by tier (``suspected``/``observed``/``exploited-in-test``).
        report: The report body (findings, skipped probes, the ceiling explanation).
        actor: Who ran it.
        evidence_run_id: The ECA-1.3 evidence run, when one was written.

    Returns:
        The stored report.

    Raises:
        ProbeConsentStoreError: :data:`CODE_REPORT_INVALID` when a count is negative or a finding
            sits above the authorization's proof ceiling.
    """
    tiers = {
        CLASS_SUSPECTED: int(counts.get(CLASS_SUSPECTED, 0)),
        CLASS_OBSERVED: int(counts.get(CLASS_OBSERVED, 0)),
        CLASS_EXPLOITED_IN_TEST: int(counts.get(CLASS_EXPLOITED_IN_TEST, 0)),
    }
    if any(v < 0 for v in tiers.values()):
        raise ProbeConsentStoreError(CODE_REPORT_INVALID, "tier counts must be non-negative")
    above = [
        tier
        for tier, n in tiers.items()
        if n and class_rank(tier) > class_rank(authorization.proof_ceiling)
    ]
    if above:
        raise ProbeConsentStoreError(
            CODE_REPORT_INVALID,
            f"the run's proof ceiling is '{authorization.proof_ceiling}', so it cannot report "
            f"{above}",
        )
    created_by = actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.security_probe_reports (
            tenant_id, target_id, target_slug, target_environment, target_network_class,
            target_base_url, profile, consent_id, hosted_mock, explicit_approval, proof_ceiling,
            limits, count_suspected, count_observed, count_exploited_in_test, report,
            evidence_run_id, created_by, actor_label, actor_kind
        )
        VALUES (
            %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s,
            %s::jsonb, %s, %s, %s, %s::jsonb, %s::uuid, %s::uuid, %s, %s
        )
        RETURNING {_REPORT_SUMMARY_COLUMNS}, report
        """,
        (
            tenant_id,
            target.id,
            target.slug,
            target.environment,
            target.network_class,
            target.base_url,
            authorization.profile_id,
            authorization.consent_id,
            authorization.hosted_mock,
            authorization.explicit_approval,
            authorization.proof_ceiling,
            json.dumps(authorization.limits.as_dict(), sort_keys=True),
            tiers[CLASS_SUSPECTED],
            tiers[CLASS_OBSERVED],
            tiers[CLASS_EXPLOITED_IN_TEST],
            json.dumps(dict(report), sort_keys=True, default=str),
            evidence_run_id,
            created_by,
            actor.label,
            actor.kind,
        ),
    )
    return _report_from_row(rows[0], with_body=True)  # type: ignore[return-value]


def list_reports(
    tenant_id: str, *, target_id: Optional[str] = None, limit: int = 50
) -> List[SecurityProbeReportSummary]:
    """A tenant's probe reports, newest first.

    Args:
        tenant_id: The caller's tenant.
        target_id: Restrict to one target.
        limit: Maximum rows (capped at :data:`MAX_LIST_LIMIT`).

    Returns:
        The summaries (empty for a malformed id).
    """
    if not is_uuid_string(str(tenant_id or "")):
        return []
    if target_id is not None and not is_uuid_string(str(target_id)):
        return []
    bounded = max(1, min(int(limit), MAX_LIST_LIMIT))
    clauses = ["tenant_id = %s::uuid"]
    params: List[Any] = [tenant_id]
    if target_id is not None:
        clauses.append("target_id = %s::uuid")
        params.append(target_id)
    params.append(bounded)
    rows = db.execute_query(
        f"""
        SELECT {_REPORT_SUMMARY_COLUMNS}
        FROM apiome.security_probe_reports
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [_report_from_row(row, with_body=False) for row in rows]


def get_report(tenant_id: str, report_id: str) -> SecurityProbeReportRecord:
    """Read one probe report inside a tenant.

    Args:
        tenant_id: The caller's tenant.
        report_id: The report id.

    Returns:
        The report with its body.

    Raises:
        ProbeConsentStoreError: :data:`CODE_REPORT_NOT_FOUND` when nothing matches.
    """
    rows: List[Dict[str, Any]] = []
    if is_uuid_string(str(tenant_id or "")) and is_uuid_string(str(report_id or "")):
        rows = db.execute_query(
            f"""
            SELECT {_REPORT_SUMMARY_COLUMNS}, report
            FROM apiome.security_probe_reports
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            (report_id, tenant_id),
        )
    if not rows:
        raise ProbeConsentStoreError(CODE_REPORT_NOT_FOUND, "security probe report not found")
    return _report_from_row(rows[0], with_body=True)  # type: ignore[return-value]
