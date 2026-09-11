"""The publish pipeline — SDK-4.1 (#4495).

One entry point, :func:`publish`, that takes a published revision and an ecosystem and either
*validates* a release (dry run) or *performs* one. Everything it needs is already owned by another
module — the branding (SDK-3.4), the archive (:mod:`app.sdk_distribution`), the version mapping
(:mod:`app.sdk_publish_version`), the credential (:mod:`app.sdk_registry_credentials`) and the
upload (:mod:`app.sdk_registry_client`) — so what lives here is the *order* those happen in, what
each failure means, and the ledger row that records it.

**Why this is not a job.** SDK-4.1 was specified as "an additional step on the SDK-1.1 job
pipeline". SDK-1.1 (the generator job service and artifact store) was closed **not-planned**, along
with the generator SPI, both MVP language generators and the dashboard/CLI surfaces — so there is
no job pipeline to be a step on. Following the SDK-2.3/2.4/2.5/3.3/3.4 precedent, the work runs
inline against the persisted canonical model and records its own run row. The shape is still a
job's: a run has a status, an event log, a claimed version and an outcome, so a queue can be put
underneath it later without changing what a caller sees.

**Dry run is the same code path, stopped one step early.** It resolves the credential (proving it
is present *and* decryptable), computes the version the next real publish would claim, and builds
the archive — then reports instead of uploading. Anything a dry run reports green, a publish will
too, because the build is byte-deterministic and the only step the dry run skipped is the HTTP
request.

**A version number is claimed before it is uploaded.** The run row is inserted ``in_progress``
carrying the package version, and a partial unique index makes that claim exclusive. Two concurrent
publishes therefore cannot compute the same counter and both upload; the loser sees the conflict,
takes the next number and proceeds. A failed run releases its number (nothing was published under
it); a run that dies mid-upload keeps it, which is the safe failure.

**Nothing secret is written anywhere.** The token is read into memory by
:func:`app.sdk_registry_credentials.resolve_credential`, handed to the transport, and never
touched again. Every log line — including anything a registry said — is passed through
:func:`app.sdk_registry_credentials.redact_secrets` before it is stored, so even a registry that
quotes the credential it rejected cannot put one in the ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import psycopg2

from .canonical_model import CanonicalApi
from .database import db
from .sdk_distribution import Distribution, DistributionError, build_distribution
from .sdk_generation_settings import PatternContext, ResolvedBranding
from .sdk_generation_settings_store import load_settings
from .sdk_kit import KitCoordinates
from .sdk_publish_version import (
    PUBLISH_ECOSYSTEMS,
    ReleaseSeries,
    VersionLineError,
    package_version,
    parse_version_line,
)
from .sdk_registry_client import (
    STATUS_ALREADY_PUBLISHED,
    STATUS_PUBLISHED,
    PublishReceipt,
    RegistryUploadError,
    publish_distribution,
)
from .sdk_registry_credentials import (
    ResolvedCredential,
    credential_encryption_configured,
    resolve_credential,
)
from .sdk_run_log import MAX_LOG_ENTRIES, RunLog

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_CLAIM_ATTEMPTS",
    "MAX_LOG_ENTRIES",
    "RUN_STATUS_ALREADY_PUBLISHED",
    "RUN_STATUS_DRY_RUN",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_IN_PROGRESS",
    "RUN_STATUS_PUBLISHED",
    "PublishContext",
    "PublishError",
    "PublishOutcome",
    "PublishTransport",
    "build_release_distribution",
    "publish",
    "resolve_release_branding",
    "resolve_release_series",
    "run_row_to_outcome",
]

#: Lifecycle statuses, matching V256's ``sdk_publish_runs_status_check``.
RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_PUBLISHED = "published"
RUN_STATUS_ALREADY_PUBLISHED = "already_published"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_DRY_RUN = "dry_run"

#: How many times a publish will take the next counter after losing a claim race. Each attempt is
#: one insert; more than a handful of simultaneous publishes of one series is a caller problem, not
#: something to spin on.
MAX_CLAIM_ATTEMPTS = 5

#: How a distribution is uploaded. Injected so tests exercise the whole pipeline — claim, build,
#: outcome, ledger — without a network.
PublishTransport = Callable[[Distribution, ResolvedCredential], PublishReceipt]


class PublishError(Exception):
    """A publish that cannot proceed, with the code and status a route should answer.

    Attributes:
        code: A stable, machine-readable reason (``sdk-publish-credential-missing``…).
        message: What went wrong and what to do about it, written for the person publishing.
        status_code: The HTTP status a route should map this to.
        detail: Anything else worth returning (the ecosystems that *are* configured, say).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail: Dict[str, Any] = detail or {}


@dataclass(frozen=True)
class PublishContext:
    """Which revision is being published, and by whom.

    The route resolves these from the URL and the token; the pipeline never queries for them again,
    so a publish cannot end up describing a different revision than the one that was authorised.

    Attributes:
        tenant_id: Owning tenant.
        tenant_slug: The tenant's slug, for ``{tenant}`` in SDK-3.4 patterns.
        project_id: The project being published.
        project_slug: The project's slug, for ``{project}``.
        version_record_id: The revision (``versions.id``) — the provenance that matters.
        version_line: The revision's version label (``versions.version_id``), which the package
            version is derived from.
        actor_id: The user who asked for the publish.
    """

    tenant_id: str
    tenant_slug: str
    project_id: str
    project_slug: str
    version_record_id: str
    version_line: Optional[str]
    actor_id: Optional[str] = None


@dataclass(frozen=True)
class PublishOutcome:
    """What a publish (or a dry run) did.

    Attributes:
        run_id: The ledger row, when one was written.
        status: One of the ``RUN_STATUS_*`` values.
        dry_run: Whether anything was uploaded.
        ecosystem: ``npm`` or ``pypi``.
        package_name: The resolved package name.
        package_version: The version claimed.
        release_series: The series the counter was allocated under.
        regen_counter: Which release of that series this is.
        version_line: The version label it was derived from.
        registry_url: Where it published (or would have).
        credential_scope: Which scope supplied the credential.
        artifact_filename: The archive's filename.
        artifact_sha256: The archive's digest — a dry run's must equal the publish's.
        artifact_bytes: The archive's size.
        operation_count: How many operations shipped snippets.
        skipped: Operations no snippet is defined for.
        truncated: Whether the API has more renderable operations than one package carries.
        files: What is inside the archive.
        provenance: The provenance embedded in the package's own metadata.
        log: The event log.
        error_code: Set when the run failed.
        error_message: Set when the run failed, redacted.
        retryable: Whether a failed upload could plausibly succeed if repeated unchanged (a
            timeout or a registry 5xx). Not persisted — it is for an in-process caller such as
            SDK-4.3's auto-regen worker, mirroring SDK-4.2's ``DeliveryOutcome.retryable``.
    """

    run_id: Optional[str]
    status: str
    dry_run: bool
    ecosystem: str
    package_name: str
    package_version: str
    release_series: str
    regen_counter: int
    version_line: Optional[str]
    registry_url: Optional[str]
    credential_scope: Optional[str]
    artifact_filename: Optional[str] = None
    artifact_sha256: Optional[str] = None
    artifact_bytes: Optional[int] = None
    operation_count: int = 0
    truncated: bool = False
    skipped: List[Dict[str, str]] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    log: List[Dict[str, Any]] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False


# -------------------------------------------------------------------------------------------
# Resolution steps
# -------------------------------------------------------------------------------------------


def _require_ecosystem(ecosystem: str) -> str:
    """Return the ecosystem key, or refuse.

    Args:
        ecosystem: The requested ecosystem.

    Returns:
        The normalised key.

    Raises:
        PublishError: When it is not one SDK-4.1 publishes to.
    """
    key = (ecosystem or "").strip().lower()
    if key not in PUBLISH_ECOSYSTEMS:
        raise PublishError(
            "sdk-publish-ecosystem-unsupported",
            f"{ecosystem!r} cannot be published to. SDK-4.1 publishes to "
            f"{' and '.join(PUBLISH_ECOSYSTEMS)}; `gomod` names a module path, and a Go module is "
            "released by pushing a tag rather than by uploading.",
            status_code=400,
            detail={"ecosystems": list(PUBLISH_ECOSYSTEMS)},
        )
    return key


def resolve_release_branding(
    context: PublishContext, ecosystem: str
) -> tuple[ResolvedBranding, str, str]:
    """Resolve the SDK-3.4 branding and the package name to publish under.

    Public because SDK-4.2's git delivery commits the same package a publish would upload, and so
    must name it by the same rule.

    Args:
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        ``(branding, package_name, settings_fingerprint)``.

    Raises:
        PublishError: When the tenant has configured no package-name pattern for this ecosystem,
            or the pattern resolves to a name the registry would reject. A package name is an
            exact identifier, and publishing under a guessed one is worse than not publishing.
    """
    settings = load_settings(
        context.tenant_id,
        context.project_id,
        PatternContext(
            tenant=context.tenant_slug,
            project=context.project_slug,
            version=str(context.version_line or ""),
        ),
    )
    branding = ResolvedBranding(
        package_names=dict(settings.resolved.package_names),
        license_header=settings.resolved.license_header,
        user_agent=settings.resolved.user_agent,
    )
    name = branding.package_names.get(ecosystem)
    if not name:
        raise PublishError(
            "sdk-publish-package-name-missing",
            f"No {ecosystem} package name is configured for this project. Set a "
            f"`packageNamePatterns.{ecosystem}` pattern in the project's or the workspace's SDK "
            "generation settings — a package name is an exact identifier, so it is never guessed.",
            detail={"ecosystem": ecosystem, "settingsSource": settings.source},
        )
    return branding, name, settings.content_fingerprint


def resolve_release_series(context: PublishContext) -> ReleaseSeries:
    """Read the release series from the revision's version line.

    Public for the same reason as :func:`resolve_release_branding`: a delivered SDK carries the
    version number a publish of the same series would.

    Args:
        context: The revision being published.

    Returns:
        The series.

    Raises:
        PublishError: When the version line cannot be mapped onto a package version.
    """
    try:
        return parse_version_line(context.version_line)
    except VersionLineError as exc:
        raise PublishError(
            "sdk-publish-version-line-invalid", str(exc), detail={"versionLine": context.version_line}
        ) from exc


def _resolve_credential(context: PublishContext, ecosystem: str) -> ResolvedCredential:
    """Find the credential this publish will authenticate with.

    Resolved for a dry run too: "is there a token, and can we still open it?" is exactly the kind
    of thing a dry run exists to answer, and it is answered without the token being used.

    Args:
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        The credential in force.

    Raises:
        PublishError: 503 when credential encryption is not configured at all (an operator
            problem, named as one); 422 when this tenant simply has not stored a token.
    """
    if not credential_encryption_configured():
        raise PublishError(
            "sdk-publish-encryption-unconfigured",
            "Package publishing is not available on this deployment: no registry-credential "
            "encryption key is configured. Set APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS and "
            "restart the API.",
            status_code=503,
        )
    credential = resolve_credential(
        context.tenant_id, ecosystem=ecosystem, project_id=context.project_id
    )
    if credential is None:
        raise PublishError(
            "sdk-publish-credential-missing",
            f"No usable {ecosystem} credential is stored for this project or workspace. Add one "
            "before publishing. (A credential sealed under a master key that is no longer "
            "configured counts as missing — it cannot be opened.)",
            detail={"ecosystem": ecosystem},
        )
    return credential


def build_release_distribution(
    api: CanonicalApi,
    *,
    context: PublishContext,
    ecosystem: str,
    branding: ResolvedBranding,
    package_name: str,
    version: str,
    series: ReleaseSeries,
    counter: int,
    source_text: Optional[str],
    source_format: Optional[str],
    settings_fingerprint: Optional[str],
    apiome_version: Optional[str],
) -> Distribution:
    """Build the distribution, turning a build refusal into a publish refusal.

    Public because SDK-4.2 commits exactly this file list to a repository: one builder means a
    delivered SDK and a published package cannot drift apart.

    Args:
        api: The revision's canonical model.
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.
        branding: The resolved SDK-3.4 branding.
        package_name: The resolved package name.
        version: The package version being claimed.
        series: The release series.
        counter: The regen counter.
        source_text: The captured contract.
        source_format: Its format key.
        settings_fingerprint: The settings digest in force.
        apiome_version: The running API version.

    Returns:
        The built :class:`~app.sdk_distribution.Distribution`.

    Raises:
        PublishError: When there is nothing publishable to build.
    """
    try:
        return build_distribution(
            api,
            ecosystem=ecosystem,
            coordinates=KitCoordinates(
                tenant_slug=context.tenant_slug,
                project_slug=context.project_slug,
                version_slug=str(context.version_line or context.version_record_id),
                version_record_id=context.version_record_id,
                version_label=context.version_line,
            ),
            branding=branding,
            package_name=package_name,
            package_version=version,
            release_series=series.key,
            regen_counter=counter,
            source_text=source_text,
            source_format=source_format,
            settings_fingerprint=settings_fingerprint,
            apiome_version=apiome_version,
        )
    except DistributionError as exc:
        raise PublishError("sdk-publish-nothing-to-package", str(exc)) from exc


def _file_summaries(distribution: Distribution) -> List[Dict[str, Any]]:
    """Describe a distribution's contents for the report, without its bytes."""
    return [
        {
            "path": item.path,
            "sizeBytes": item.size_bytes,
            "sha256": item.sha256,
            "subject": item.subject,
        }
        for item in distribution.files
    ]


# -------------------------------------------------------------------------------------------
# The claim
# -------------------------------------------------------------------------------------------


def _claim(
    context: PublishContext,
    *,
    ecosystem: str,
    series: ReleaseSeries,
    package_name: str,
    credential: ResolvedCredential,
    log: RunLog,
) -> tuple[Optional[Dict[str, Any]], int, str]:
    """Take the next free version number for this series, exclusively.

    Computes the counter from the ledger, inserts an ``in_progress`` run holding it, and — when the
    partial unique index says another publish got there first — takes the next one and tries again.

    Args:
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.
        series: The release series.
        package_name: The resolved package name.
        credential: The credential in force, recorded on the run.
        log: The event log.

    Returns:
        ``(run_row, counter, version)``. ``run_row`` is ``None`` when the ids are not UUIDs — a
        unit-test handle — in which case the publish proceeds unledgered rather than refusing.

    Raises:
        PublishError: When :data:`MAX_CLAIM_ATTEMPTS` consecutive numbers were all taken.
    """
    counter = db.next_sdk_publish_counter(
        context.tenant_id, context.project_id, ecosystem, series.key
    )
    for attempt in range(MAX_CLAIM_ATTEMPTS):
        version = package_version(series, ecosystem, counter + attempt)
        try:
            row = db.insert_sdk_publish_run(
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                version_id=context.version_record_id,
                ecosystem=ecosystem,
                status=RUN_STATUS_IN_PROGRESS,
                dry_run=False,
                version_line=context.version_line,
                release_series=series.key,
                regen_counter=counter + attempt,
                package_name=package_name,
                package_version=version,
                registry_url=credential.registry_url,
                credential_scope=credential.scope,
                log=log.entries,
                actor_id=context.actor_id,
            )
        except psycopg2.errors.UniqueViolation:
            log.add(
                "claim",
                f"{package_name}@{version} was claimed by another publish; taking the next "
                "version.",
                level="warn",
            )
            continue
        log.add("claim", f"Claimed {package_name}@{version} for release series {series.key}.")
        return row, counter + attempt, version

    raise PublishError(
        "sdk-publish-version-unavailable",
        f"Could not reserve a version for release series {series.key}: the next "
        f"{MAX_CLAIM_ATTEMPTS} numbers are already claimed. Another publish of this project is "
        "probably in flight — try again in a moment.",
        status_code=409,
        detail={"releaseSeries": series.key, "ecosystem": ecosystem},
    )


# -------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------


def publish(
    api: CanonicalApi,
    *,
    context: PublishContext,
    ecosystem: str,
    dry_run: bool = True,
    source_text: Optional[str] = None,
    source_format: Optional[str] = None,
    apiome_version: Optional[str] = None,
    transport: Optional[PublishTransport] = None,
) -> PublishOutcome:
    """Validate or perform one package release.

    Args:
        api: The revision's canonical model.
        context: Which revision is being published, and by whom.
        ecosystem: ``npm`` or ``pypi``.
        dry_run: When ``True`` (the default — publishing is opt-in, not opt-out), everything is
            resolved and built and nothing is uploaded or claimed.
        source_text: The captured contract, which is what the package carries.
        source_format: Its format key.
        apiome_version: The running API version, recorded as provenance.
        transport: How to upload. Defaults to
            :func:`app.sdk_registry_client.publish_distribution`.

    Returns:
        The :class:`PublishOutcome`.

    Raises:
        PublishError: When the release cannot proceed — an unsupported ecosystem, no configured
            package name, an unmappable version line, no usable credential, nothing to package, or
            no free version number. A registry *refusal* is not raised: it is recorded on the run
            and returned as a failed outcome, because the run row is the thing worth having.
    """
    key = _require_ecosystem(ecosystem)
    branding, package_name, fingerprint = resolve_release_branding(context, key)
    series = resolve_release_series(context)
    credential = _resolve_credential(context, key)

    log = RunLog(secrets=[credential.token])
    log.add(
        "resolve",
        f"Publishing {context.project_slug} {context.version_line or context.version_record_id} "
        f"as {package_name} to {credential.registry_url} "
        f"({credential.scope}-scoped credential).",
    )

    if dry_run:
        return _dry_run(
            api,
            context=context,
            ecosystem=key,
            branding=branding,
            package_name=package_name,
            series=series,
            credential=credential,
            fingerprint=fingerprint,
            source_text=source_text,
            source_format=source_format,
            apiome_version=apiome_version,
            log=log,
        )

    run_row, counter, version = _claim(
        context,
        ecosystem=key,
        series=series,
        package_name=package_name,
        credential=credential,
        log=log,
    )
    run_id = str(run_row["id"]) if run_row else None

    try:
        distribution = build_release_distribution(
            api,
            context=context,
            ecosystem=key,
            branding=branding,
            package_name=package_name,
            version=version,
            series=series,
            counter=counter,
            source_text=source_text,
            source_format=source_format,
            settings_fingerprint=fingerprint,
            apiome_version=apiome_version,
        )
    except PublishError as exc:
        # The claim is released so the number is not lost to a build that never uploaded.
        message = log.redact(exc.message)
        log.add("build", message, level="error")
        _finish(
            run_id, context, RUN_STATUS_FAILED, log, error_code=exc.code, error_message=message
        )
        raise

    log.add(
        "build",
        f"Built {distribution.filename} ({distribution.content_length:,} bytes, "
        f"{len(distribution.files)} files, sha256 {distribution.sha256}).",
    )

    send = transport or publish_distribution
    try:
        receipt = send(distribution, credential)
    except RegistryUploadError as exc:
        message = log.redact(str(exc))
        log.add("upload", message, level="error")
        _finish(
            run_id,
            context,
            RUN_STATUS_FAILED,
            log,
            artifact=distribution,
            error_code="sdk-publish-registry-refused",
            error_message=message,
        )
        return _outcome(
            run_id=run_id,
            status=RUN_STATUS_FAILED,
            dry_run=False,
            context=context,
            ecosystem=key,
            package_name=package_name,
            version=version,
            series=series,
            counter=counter,
            credential=credential,
            distribution=distribution,
            log=log,
            error_code="sdk-publish-registry-refused",
            error_message=message,
            retryable=exc.retryable,
        )

    status = (
        RUN_STATUS_ALREADY_PUBLISHED
        if receipt.status == STATUS_ALREADY_PUBLISHED
        else RUN_STATUS_PUBLISHED
    )
    log.add("upload", receipt.message, level="info" if receipt.status == STATUS_PUBLISHED else "warn")
    _finish(run_id, context, status, log, artifact=distribution)
    return _outcome(
        run_id=run_id,
        status=status,
        dry_run=False,
        context=context,
        ecosystem=key,
        package_name=package_name,
        version=version,
        series=series,
        counter=counter,
        credential=credential,
        distribution=distribution,
        log=log,
    )


def _dry_run(
    api: CanonicalApi,
    *,
    context: PublishContext,
    ecosystem: str,
    branding: ResolvedBranding,
    package_name: str,
    series: ReleaseSeries,
    credential: ResolvedCredential,
    fingerprint: Optional[str],
    source_text: Optional[str],
    source_format: Optional[str],
    apiome_version: Optional[str],
    log: RunLog,
) -> PublishOutcome:
    """Validate a release without claiming a version or contacting the registry.

    Args:
        api: The revision's canonical model.
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.
        branding: The resolved SDK-3.4 branding.
        package_name: The resolved package name.
        series: The release series.
        credential: The credential that *would* be used — resolved but never sent.
        fingerprint: The settings digest in force.
        source_text: The captured contract.
        source_format: Its format key.
        apiome_version: The running API version.
        log: The event log.

    Returns:
        The outcome, with the version the next real publish would claim and the digest it would
        upload.
    """
    counter = db.next_sdk_publish_counter(
        context.tenant_id, context.project_id, ecosystem, series.key
    )
    version = package_version(series, ecosystem, counter)
    log.add(
        "version",
        f"Release series {series.key} is at counter {counter}; the next release is "
        f"{package_name}@{version}.",
    )

    distribution = build_release_distribution(
        api,
        context=context,
        ecosystem=ecosystem,
        branding=branding,
        package_name=package_name,
        version=version,
        series=series,
        counter=counter,
        source_text=source_text,
        source_format=source_format,
        settings_fingerprint=fingerprint,
        apiome_version=apiome_version,
    )
    log.add(
        "build",
        f"Built {distribution.filename} ({distribution.content_length:,} bytes, "
        f"{len(distribution.files)} files, sha256 {distribution.sha256}).",
    )
    log.add(
        "dry-run",
        "Dry run: nothing was uploaded and no version number was claimed. The build is "
        "byte-deterministic, so a real publish uploads exactly these bytes.",
    )

    row = None
    try:
        row = db.insert_sdk_publish_run(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            version_id=context.version_record_id,
            ecosystem=ecosystem,
            status=RUN_STATUS_DRY_RUN,
            dry_run=True,
            version_line=context.version_line,
            release_series=series.key,
            regen_counter=counter,
            package_name=package_name,
            package_version=version,
            artifact_sha256=distribution.sha256,
            artifact_bytes=distribution.content_length,
            registry_url=credential.registry_url,
            credential_scope=credential.scope,
            provenance=distribution.provenance,
            log=log.entries,
            finished=True,
            actor_id=context.actor_id,
        )
    except Exception:  # noqa: BLE001 - a dry run that could not be recorded is still a valid answer
        logger.warning(
            "Could not record the SDK dry-run for project %s", context.project_id, exc_info=True
        )

    return _outcome(
        run_id=str(row["id"]) if row else None,
        status=RUN_STATUS_DRY_RUN,
        dry_run=True,
        context=context,
        ecosystem=ecosystem,
        package_name=package_name,
        version=version,
        series=series,
        counter=counter,
        credential=credential,
        distribution=distribution,
        log=log,
    )


def _finish(
    run_id: Optional[str],
    context: PublishContext,
    status: str,
    log: RunLog,
    *,
    artifact: Optional[Distribution] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Close out a claimed run, best-effort.

    A ledger write that fails must not turn a successful upload into a reported failure — the
    package is on the registry either way — so this logs and returns rather than raising.

    Args:
        run_id: The run to close, or ``None`` when none was written.
        context: The revision being published (for the tenant scope).
        status: The final status.
        log: The event log to store.
        artifact: The built distribution, for its digest, size and embedded provenance.
        error_code: Machine-readable failure code.
        error_message: Redacted failure message.
    """
    if not run_id:
        return
    try:
        db.finish_sdk_publish_run(
            run_id,
            context.tenant_id,
            status=status,
            log=log.entries,
            provenance=artifact.provenance if artifact else None,
            artifact_sha256=artifact.sha256 if artifact else None,
            artifact_bytes=artifact.content_length if artifact else None,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001 - the upload already happened; the ledger is not the truth
        logger.warning("Could not close SDK publish run %s", run_id, exc_info=True)


def _outcome(
    *,
    run_id: Optional[str],
    status: str,
    dry_run: bool,
    context: PublishContext,
    ecosystem: str,
    package_name: str,
    version: str,
    series: ReleaseSeries,
    counter: int,
    credential: ResolvedCredential,
    distribution: Distribution,
    log: RunLog,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    retryable: bool = False,
) -> PublishOutcome:
    """Assemble the outcome a route returns.

    Args:
        run_id: The ledger row.
        status: The final status.
        dry_run: Whether anything was uploaded.
        context: The revision being published.
        ecosystem: ``npm`` or ``pypi``.
        package_name: The resolved package name.
        version: The version claimed.
        series: The release series.
        counter: The regen counter.
        credential: The credential in force.
        distribution: The built archive.
        log: The event log.
        error_code: Set when the run failed.
        error_message: Set when the run failed.
        retryable: Whether a failed upload is worth repeating unchanged.

    Returns:
        The outcome.
    """
    return PublishOutcome(
        run_id=run_id,
        status=status,
        dry_run=dry_run,
        ecosystem=ecosystem,
        package_name=package_name,
        package_version=version,
        release_series=series.key,
        regen_counter=counter,
        version_line=context.version_line,
        registry_url=credential.registry_url,
        credential_scope=credential.scope,
        artifact_filename=distribution.filename,
        artifact_sha256=distribution.sha256,
        artifact_bytes=distribution.content_length,
        operation_count=distribution.operation_count,
        truncated=distribution.truncated,
        skipped=list(distribution.skipped),
        files=_file_summaries(distribution),
        provenance=dict(distribution.provenance),
        log=list(log.entries),
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
    )


def run_row_to_outcome(row: Dict[str, Any]) -> PublishOutcome:
    """Project a stored run row back onto an outcome, for the history routes.

    A stored row keeps the digest and the provenance but not the archive's file list — that is
    rebuildable from the revision and is not worth a column — so ``files`` comes back empty.

    Args:
        row: A row from ``sdk_publish_runs``.

    Returns:
        The outcome.
    """
    provenance = row.get("provenance")
    log = row.get("log")
    return PublishOutcome(
        run_id=str(row.get("id")) if row.get("id") else None,
        status=str(row.get("status") or ""),
        dry_run=bool(row.get("dry_run")),
        ecosystem=str(row.get("ecosystem") or ""),
        package_name=str(row.get("package_name") or ""),
        package_version=str(row.get("package_version") or ""),
        release_series=str(row.get("release_series") or ""),
        regen_counter=int(row.get("regen_counter") or 0),
        version_line=row.get("version_line"),
        registry_url=row.get("registry_url"),
        credential_scope=row.get("credential_scope"),
        artifact_sha256=row.get("artifact_sha256"),
        artifact_bytes=row.get("artifact_bytes"),
        provenance=dict(provenance) if isinstance(provenance, dict) else {},
        log=list(log) if isinstance(log, list) else [],
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )
