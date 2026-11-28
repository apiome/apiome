"""``/v1/tenants/{tenant_slug}/pact-migration`` runs — the Migration wizard's server side, PFX-8.16 (#7313).

``apiome pact migrate`` reads the source broker on the caller's machine and sends batches to
``…/pact-migration/import``. These routes run the same migration **on the server**, as a job the
product watches (:mod:`app.pact_migration_job`):

* ``POST …/pact-migration/test`` — sign in to the source and count its pacticipants (**Test connection**);
* ``POST …/pact-migration/runs`` — start a run: a ``dry-run`` (read and check, write nothing) or a ``copy``;
* ``GET …/pact-migration/runs`` — the workspace's runs, newest first (**Past migrations**);
* ``GET …/pact-migration/runs/{run_id}`` — one run: counts per kind, findings, failures, the log;
* ``POST …/pact-migration/runs/{run_id}/stop`` — stop it before its next batch;
* ``POST …/pact-migration/runs/{run_id}/resume`` — set a stopped or failed copy running again, or
  retry what a finished one could not copy;
* ``GET`` / ``PUT …/pact-migration/runs/{run_id}/sync`` — keep-in-sync (PFX-8.17): copy what is new
  at the old broker on a schedule until it is switched off (:mod:`app.pact_migration_sync`).

**The source is only read, and its credentials are not stored — except, sealed, while keep-in-sync
is on.** The token (or username and password) is used by the request that starts or resumes a run
and by that run alone, in memory; a resume is given it again. Keep-in-sync has no one to ask, so
switching it on seals the credentials (:mod:`app.pact_migration_sync_store`) and switching it off —
or the sync stopping itself — lets go of them. The source URL must be a public http(s) address.

**Permissions.** Everything that reaches the source or writes — ``test``, starting, resuming,
switching keep-in-sync on or off — needs ``pacts:create`` and ``pacts:edit``, like
``…/pact-migration/import``; stopping needs ``pacts:edit``; reading runs needs ``pacts:view``. A run
belongs to the tenant that started it: another tenant asking for it is told it does not exist.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import pact_migration_run_store as store
from . import pact_migration_sync_store as sync_store
from .consumer_contract_store import ConsumerActor, actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_migration_job import (
    CODE_RUN_BUSY,
    PactMigrationRunOptions,
    PactMigrationRunView,
    RunOptionError,
    migration_jobs,
    run_migration,
    run_view,
    validate_options,
)
from .pact_migration_source import SourceBroker, SourceError, product_of
from .pact_migration_sync import DEFAULT_INTERVAL_MINUTES, UNREACHABLE_LIMIT, workspace_keep
from .pact_retention import RetentionKeep
from .permissions import Action, Resource, enforce_permission, has_permission

__all__ = ["CODE_RUN_NOT_FOUND", "CODE_SYNC_INVALID", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_BASE = "/{tenant_slug}/pact-migration"

#: No run with that id in this workspace (HTTP 404).
CODE_RUN_NOT_FOUND = "pact-migration-run-not-found"
#: Keep-in-sync cannot be switched on for that run (HTTP 422).
CODE_SYNC_INVALID = "pact-migration-sync-invalid"

_SOURCE_ERRORS = {
    422: {
        "description": (
            "`pact-migration-source-invalid` (the URL is not a public http(s) address), "
            "`pact-migration-source-refused` (the source refused the credentials) or "
            "`pact-migration-source-unreadable` (it could not be reached, or is not a Pact Broker)."
        )
    }
}
_NOT_FOUND = {404: {"description": "`pact-migration-run-not-found`: this workspace has no such run."}}
_ACTIVE = {
    409: {"description": "`pact-migration-run-active`: the workspace already has a migration running."},
    429: {"description": "`pact-migration-run-busy`: this server is running as many migrations as it may; try again."},
}


class PactMigrationSourceCredentials(BaseModel):
    """How to sign in to the source. Used for this request's run only; never stored."""

    model_config = ConfigDict(extra="forbid")

    token: Optional[SecretStr] = Field(
        default=None, description="A bearer token for the source; a read-only one is enough. Never stored."
    )
    username: Optional[str] = Field(
        default=None, max_length=512, description="Basic-auth user of an open-source broker without tokens."
    )
    password: Optional[SecretStr] = Field(default=None, description="Basic-auth password. Never stored.")

    def auth_kind(self) -> str:
        """``token``, ``basic`` or ``none``."""
        if self.token and self.token.get_secret_value():
            return "token"
        if self.username or (self.password and self.password.get_secret_value()):
            return "basic"
        return "none"

    def broker(self, source: str) -> SourceBroker:
        """A client for ``source`` holding these credentials.

        Raises:
            SourceError: When the URL may not be read from the server.
        """
        return SourceBroker(
            source,
            token=self.token.get_secret_value() if self.token else None,
            username=self.username,
            password=self.password.get_secret_value() if self.password else None,
        )


class PactMigrationSourceRequest(PactMigrationSourceCredentials):
    """A source broker and how to sign in to it."""

    source: str = Field(
        min_length=1,
        max_length=2048,
        description="The source's base URL, e.g. `https://acme.pactflow.io` (no credentials in it).",
    )


class PactMigrationSourceTestResult(BaseModel):
    """What **Test connection** found."""

    host: str = Field(description="The source's host.")
    product: str = Field(description="`PactFlow` or `Pact Broker`.")
    pacticipants: int = Field(description="Pacticipants the source lists.")


class StartPactMigrationRunRequest(PactMigrationSourceRequest):
    """A run to start."""

    mode: Literal["dry-run", "copy"] = Field(
        default="dry-run", description="`dry-run` reads and checks and writes nothing; `copy` imports."
    )
    options: PactMigrationRunOptions = Field(
        default_factory=PactMigrationRunOptions, description="What to copy and how."
    )


class PactMigrationRunList(BaseModel):
    """The workspace's migration runs."""

    runs: List[PactMigrationRunView] = Field(description="Newest first, without findings, failures or log.")
    can_migrate: bool = Field(
        default=False,
        description=(
            "Whether the caller may test a source and start, stop or resume a run "
            "(`pacts:create` and `pacts:edit`)."
        ),
    )


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _error(status: int, code: str, message: str) -> HTTPException:
    """An HTTP error carrying ``{code, message}``."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _not_found() -> HTTPException:
    """The 404 for a run the tenant does not have."""
    return _error(404, CODE_RUN_NOT_FOUND, "this workspace has no such migration")


def _may_migrate(auth_data: Dict[str, Any]) -> Optional[str]:
    """Enforce ``pacts:create`` and ``pacts:edit``; answer the acting user id."""
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target="pact-migration")
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-migration")
    return user_id


def _keep(tenant_id: str) -> Optional[RetentionKeep]:
    """The workspace's clean-up selectors, or ``None`` when it has saved no keep-rule."""
    return workspace_keep(db, tenant_id)


def _launch(
    row: Dict[str, Any],
    credentials: PactMigrationSourceCredentials,
    actor: ConsumerActor,
    keep: Optional[RetentionKeep],
) -> None:
    """Start the job for a running row on this worker; a broker that cannot be built fails the run."""
    try:
        broker = credentials.broker(row["source"])
    except SourceError as exc:
        store.finish_run(db, row["id"], "failed", error=str(exc))
        raise _error(422, exc.code, str(exc)) from exc
    migration_jobs.start(lambda: run_migration(db, row, broker, actor=actor, keep=keep))


@router.post(
    _BASE + "/test",
    response_model=PactMigrationSourceTestResult,
    summary="Test the connection to a source broker",
    description=(
        "Sign in to a Pact Broker or PactFlow with the credentials given and count its pacticipants — "
        "the wizard's **Test connection** (PFX-8.16). The source is only read; nothing is stored, the "
        "credentials included; the audit trail records that the source was reached, not what was sent. "
        "Requires `pacts:create` and `pacts:edit`."
    ),
    responses=_SOURCE_ERRORS,
)
@audited_write("pacts.migration.source.test", "pact-migration/test")
def test_migration_source(
    tenant_slug: str,
    body: PactMigrationSourceRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationSourceTestResult:
    """Sign in to the source and count its pacticipants.

    Args:
        tenant_slug: The tenant in the URL.
        body: The source and its credentials.
        auth_data: The authenticated principal.

    Returns:
        The source's host, product and pacticipant count.

    Raises:
        HTTPException: 403 without the permissions; 422 when the source cannot be read.
    """
    _may_migrate(auth_data)
    _ = tenant_slug
    try:
        with body.broker(body.source) as broker:
            return PactMigrationSourceTestResult(
                host=broker.host, product=product_of(broker.base_url), pacticipants=broker.count_pacticipants()
            )
    except SourceError as exc:
        raise _error(422, exc.code, str(exc)) from exc


@router.post(
    _BASE + "/runs",
    response_model=PactMigrationRunView,
    status_code=202,
    summary="Start a migration run",
    description=(
        "Run `apiome pact migrate` on the server (PFX-8.16). `mode: dry-run` reads the source and checks "
        "every record against the workspace, writing nothing — its counts fill the wizard's **Choose** "
        "step; `mode: copy` imports, honouring `options` (kinds, labels and tags, history depth, conflict "
        "policy). The answer is the run, `running`: poll `GET …/runs/{run_id}`. A copy skips what earlier "
        "copies from the same source imported unless `options.restart` is set, and importing a record "
        "twice changes nothing, so a run can be repeated. A workspace runs one migration at a time. The "
        "source is only read and its credentials are never stored. Requires `pacts:create` and `pacts:edit`."
    ),
    responses={
        **_SOURCE_ERRORS,
        **_ACTIVE,
        422: {
            "description": (
                "`pact-migration-run-invalid` (choices that cannot be honoured together, e.g. `versions: kept` "
                "without saved keep-rules) or a `pact-migration-source-*` code."
            )
        },
    },
)
@audited_write("pacts.migration.run.start", "pact-migration/runs")
def start_migration_run(
    tenant_slug: str,
    body: StartPactMigrationRunRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationRunView:
    """Start a run.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes the run).
        body: The source, its credentials, the mode and the choices.
        auth_data: The authenticated principal.

    Returns:
        The run, running.

    Raises:
        HTTPException: 403, 409, 422 or 429 as documented.
    """
    user_id = _may_migrate(auth_data)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    keep = _keep(tenant_id)
    try:
        validate_options(body.options, mode=body.mode, keep=keep)
        probe = body.broker(body.source)
    except RunOptionError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except SourceError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    source = probe.base_url
    probe.close()
    if not migration_jobs.has_room():
        raise _error(429, CODE_RUN_BUSY, "this server is running as many migrations as it may; try again shortly")
    actor = actor_from_auth(auth_data, user_id)
    try:
        row = store.create_run(
            db,
            tenant_id,
            source=source,
            auth_kind=body.auth_kind(),
            mode=body.mode,
            options=body.options.model_dump(),
            facts={"product": product_of(source), "cleanup_rules_set": keep is not None},
            actor=actor,
        )
    except store.RunActiveError as exc:
        raise _error(409, exc.code, str(exc)) from exc
    _launch(row, body, actor, keep)
    return run_view(row)


@router.get(
    _BASE + "/runs",
    response_model=PactMigrationRunList,
    summary="List migration runs",
    description=(
        "The workspace's migration runs, newest first — the wizard's **Past migrations** drawer. Each "
        "carries its status, counts and choices; read one for its findings, failures and log. "
        "`can_migrate` says whether the caller may run one. Requires `pacts:view`."
    ),
)
def list_migration_runs(
    tenant_slug: str,
    limit: int = Query(default=50, ge=1, le=200, description="The most runs to answer."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationRunList:
    """List the workspace's runs.

    Args:
        tenant_slug: The tenant in the URL.
        limit: The most runs.
        auth_data: The authenticated principal.

    Returns:
        The runs, newest first.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-migration")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    store.close_stale(db, tenant_id)
    can_migrate = bool(
        has_permission(db, auth_data, Resource.PACTS, Action.CREATE)
        and has_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    )
    return PactMigrationRunList(
        runs=[run_view(row) for row in store.list_runs(db, tenant_id, limit=limit)], can_migrate=can_migrate
    )


@router.get(
    _BASE + "/runs/{run_id}",
    response_model=PactMigrationRunView,
    summary="Read a migration run",
    description=(
        "One run: per-kind counts (copied, unchanged, skipped, failed — or exists / would-create for a "
        "dry run), everything the source holds that cannot be carried over (`findings`), every refused "
        "record with its reason (`failures`), and the log lines after `after`. Poll it while `status` "
        "is `running`. Requires `pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_migration_run(
    tenant_slug: str,
    run_id: str,
    after: int = Query(default=0, ge=0, description="Only log lines numbered above this."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationRunView:
    """Read one run.

    Args:
        tenant_slug: The tenant in the URL.
        run_id: The run.
        after: The last log line the reader has.
        auth_data: The authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: 404 when the workspace has no such run.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-migration")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    store.close_stale(db, tenant_id)
    row = store.get_run(db, tenant_id, run_id)
    if row is None:
        raise _not_found()
    return run_view(row, after=after)


@router.post(
    _BASE + "/runs/{run_id}/stop",
    response_model=PactMigrationRunView,
    summary="Stop a migration run",
    description=(
        "Ask a running migration to stop. It does before its next batch: what was copied stays, and "
        "`…/resume` carries on where it stopped. Stopping a run that is not running changes nothing. "
        "Requires `pacts:edit`."
    ),
    responses=_NOT_FOUND,
)
@audited_write("pacts.migration.run.stop", "pact-migration/runs/{run_id}")
def stop_migration_run(
    tenant_slug: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationRunView:
    """Stop one run.

    Args:
        tenant_slug: The tenant in the URL.
        run_id: The run.
        auth_data: The authenticated principal.

    Returns:
        The run, with ``stop_requested`` set while it winds down.

    Raises:
        HTTPException: 404 when the workspace has no such run.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-migration")
    _ = tenant_slug
    row = store.request_stop(db, _tenant_id(auth_data), run_id)
    if row is None:
        raise _not_found()
    return run_view(row)


@router.post(
    _BASE + "/runs/{run_id}/resume",
    response_model=PactMigrationRunView,
    status_code=202,
    summary="Resume a migration run",
    description=(
        "Set a stopped or failed copy running again, or retry the records a finished copy could not "
        "copy. The source is read again and everything the run already imported is skipped, so nothing "
        "is copied twice. The credentials are given again — they were never stored. Requires "
        "`pacts:create` and `pacts:edit`."
    ),
    responses={**_NOT_FOUND, **_SOURCE_ERRORS, **_ACTIVE},
)
@audited_write("pacts.migration.run.resume", "pact-migration/runs/{run_id}")
def resume_migration_run(
    tenant_slug: str,
    run_id: str,
    body: PactMigrationSourceCredentials,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationRunView:
    """Resume one run.

    Args:
        tenant_slug: The tenant in the URL.
        run_id: The run.
        body: The source's credentials, again.
        auth_data: The authenticated principal.

    Returns:
        The run, running.

    Raises:
        HTTPException: 404 when the workspace has no such finished copy; 409, 422 or 429 as documented.
    """
    user_id = _may_migrate(auth_data)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    if not migration_jobs.has_room():
        raise _error(429, CODE_RUN_BUSY, "this server is running as many migrations as it may; try again shortly")
    try:
        row = store.reopen_run(db, tenant_id, run_id)
    except store.RunActiveError as exc:
        raise _error(409, exc.code, str(exc)) from exc
    if row is None:
        raise _not_found()
    # A resume carries on: what the run imported before it stopped is skipped even if it began "from scratch".
    row["options"] = {**(row.get("options") or {}), "restart": False}
    keep = _keep(tenant_id)
    if (row["options"].get("versions") == "kept") and keep is None:
        message = (
            "this run thins versions by the clean-up rules, which were removed since: "
            "save keep-rules, or start a new migration"
        )
        store.finish_run(db, row["id"], "failed", error=message)
        raise _error(422, RunOptionError.code, message)
    _launch(row, body, actor_from_auth(auth_data, user_id), keep)
    return run_view(row)


# =============================================================================================
# Keep-in-sync — PFX-8.17 (#7314)
# =============================================================================================


class PactMigrationSyncView(BaseModel):
    """Whether a migration is kept in sync, and how its passes have gone."""

    run_id: str
    enabled: bool = Field(description="Whether what is new at the old broker is copied on a schedule.")
    interval_minutes: int = Field(description="How often a pass runs.")
    next_run_at: Optional[str] = Field(default=None, description="When the next pass is due (while enabled).")
    last_pass_at: Optional[str] = None
    last_success_at: Optional[str] = Field(default=None, description="When a pass last copied without failing.")
    unreachable_since: Optional[str] = Field(
        default=None,
        description="Since when the old broker could not be read; after 24 hours the sync stops itself.",
    )
    passes: int = Field(default=0, description="Passes that ran to the end.")
    last_error: Optional[str] = Field(default=None, description="What went wrong in the last pass.")
    stopped_reason: Optional[str] = Field(
        default=None, description="Why the sync stopped itself (an unreachable source, unopenable credentials …)."
    )
    enabled_by: Optional[str] = None
    available: bool = Field(
        description=(
            "Whether this server can keep credentials at all (a master key is configured); without one, "
            "switching on answers 503 `pact-migration-sync-unavailable`."
        )
    )
    unreachable_limit_hours: int = Field(description="How long the source may be unreachable before the sync stops.")


class UpdatePactMigrationSyncRequest(PactMigrationSourceCredentials):
    """Switch keep-in-sync on (with the source's credentials) or off."""

    enabled: bool = Field(description="On: copy what is new on a schedule. Off: stop, and let go of the credentials.")
    interval_minutes: int = Field(
        default=DEFAULT_INTERVAL_MINUTES, ge=5, le=1440, description="How often to copy again (5 minutes to a day)."
    )


def _sync_view(run_id: str, row: Optional[Dict[str, Any]]) -> PactMigrationSyncView:
    """A stored sync (or none) as the API answers it."""
    data = row or {}
    enabled = bool(data.get("enabled"))
    return PactMigrationSyncView(
        run_id=run_id,
        enabled=enabled,
        interval_minutes=int(data.get("interval_seconds") or DEFAULT_INTERVAL_MINUTES * 60) // 60,
        next_run_at=_iso(data.get("next_run_at")) if enabled else None,
        last_pass_at=_iso(data.get("last_pass_at")),
        last_success_at=_iso(data.get("last_success_at")),
        unreachable_since=_iso(data.get("unreachable_since")),
        passes=int(data.get("passes") or 0),
        last_error=data.get("last_error"),
        stopped_reason=data.get("stopped_reason"),
        enabled_by=data.get("enabled_by_label"),
        available=sync_store.credentials_configured(),
        unreachable_limit_hours=int(UNREACHABLE_LIMIT.total_seconds() // 3600),
    )


def _iso(value: Any) -> Optional[str]:
    """A stored timestamp as ISO 8601 UTC text."""
    moment = store.as_utc(value)
    return moment.isoformat().replace("+00:00", "Z") if moment else None


_SYNC_ERRORS = {
    **_NOT_FOUND,
    409: {"description": "`pact-migration-sync-active`: another migration of this workspace is kept in sync."},
    422: {
        "description": (
            "`pact-migration-sync-invalid` (the run is a dry run), or a `pact-migration-source-*` code: the "
            "credentials were tried before anything was kept."
        )
    },
    503: {
        "description": (
            "`pact-migration-sync-unavailable`: no master key (`APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`) is "
            "configured, so the credentials cannot be kept."
        )
    },
}


@router.get(
    _BASE + "/runs/{run_id}/sync",
    response_model=PactMigrationSyncView,
    summary="Read a migration's keep-in-sync",
    description=(
        "Whether the migration is kept in sync with the old broker (PFX-8.17): how often, when the next "
        "pass is due, when one last copied, since when the source could not be read, and why the sync "
        "stopped itself if it did. A run that was never kept in sync answers `enabled: false`. Requires "
        "`pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_migration_sync(
    tenant_slug: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationSyncView:
    """Read one run's keep-in-sync.

    Args:
        tenant_slug: The tenant in the URL.
        run_id: The run.
        auth_data: The authenticated principal.

    Returns:
        The sync.

    Raises:
        HTTPException: 404 when the workspace has no such run.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-migration")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    if store.get_run(db, tenant_id, run_id) is None:
        raise _not_found()
    return _sync_view(run_id, sync_store.get_sync(db, tenant_id, run_id))


@router.put(
    _BASE + "/runs/{run_id}/sync",
    response_model=PactMigrationSyncView,
    summary="Switch a migration's keep-in-sync on or off",
    description=(
        "Keep copying until everyone has moved (PFX-8.17) — the CLI's `apiome pact migrate --follow`, run "
        "by the server. `enabled: true` with the source's credentials: they are tried against the source, "
        "then kept sealed (AES-256-GCM, never in clear) and every `interval_minutes` (15 by default) the "
        "run copies again, skipping everything it already imported — only what is new is copied, and its "
        "agreement check and who-has-moved list are refreshed. `enabled: false` stops it and deletes the "
        "credentials. A sync stops itself, and says why, when the source has been unreachable for 24 hours. "
        "A workspace keeps one migration in sync at a time. Requires `pacts:create` and `pacts:edit`."
    ),
    responses=_SYNC_ERRORS,
)
@audited_write("pacts.migration.sync.update", "pact-migration/runs/{run_id}/sync")
def update_migration_sync(
    tenant_slug: str,
    run_id: str,
    body: UpdatePactMigrationSyncRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactMigrationSyncView:
    """Switch one run's keep-in-sync on or off.

    Args:
        tenant_slug: The tenant in the URL.
        run_id: The run.
        body: On or off, how often, and (to switch on) the source's credentials.
        auth_data: The authenticated principal.

    Returns:
        The sync afterwards.

    Raises:
        HTTPException: 403, 404, 409, 422 or 503 as documented.
    """
    user_id = _may_migrate(auth_data)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    run = store.get_run(db, tenant_id, run_id)
    if run is None:
        raise _not_found()
    if not body.enabled:
        return _sync_view(run_id, sync_store.disable_sync(db, tenant_id, run_id))
    if run["mode"] != "copy":
        raise _error(422, CODE_SYNC_INVALID, "a dry run copies nothing, so it cannot be kept in sync: start a copy")
    if not sync_store.credentials_configured():
        raise _error(
            503,
            sync_store.CODE_SYNC_UNAVAILABLE,
            f"this server cannot keep credentials: set {sync_store.KEYS_SETTING} to keep a migration in sync",
        )
    try:
        with body.broker(run["source"]) as broker:
            broker.get("/")
    except SourceError as exc:
        raise _error(422, exc.code, str(exc)) from exc
    try:
        ciphertext, key_version = sync_store.seal_credentials(
            {
                "token": body.token.get_secret_value() if body.token else None,
                "username": body.username,
                "password": body.password.get_secret_value() if body.password else None,
            }
        )
    except sync_store.SyncCredentialError as exc:
        raise _error(503, sync_store.CODE_SYNC_UNAVAILABLE, str(exc)) from exc
    try:
        row = sync_store.enable_sync(
            db,
            tenant_id,
            run_id,
            ciphertext=ciphertext,
            key_version=key_version,
            interval_seconds=body.interval_minutes * 60,
            actor=actor_from_auth(auth_data, user_id),
        )
    except sync_store.SyncActiveError as exc:
        raise _error(409, exc.code, str(exc)) from exc
    return _sync_view(run_id, row)
