"""Sending purges to a lane's CDN — Slate 10.2 (private-suite#120).

:mod:`app.slate_cdn` decides what to purge; this module sends it and reports what happened.

* :func:`send_purge` opens the sealed credential in memory, builds the provider calls and sends
  them through the SSRF-guarded HTTP client, stopping at the first failure. It never raises for a
  provider problem: every outcome — success, refusal, timeout, unreachable — is a
  :class:`CdnPurgeOutcome` with a short error code, because a purge is evidence an operator reads
  after an incident and an exception is not.
* :func:`dispatch_deploy_purge` is the deploy hook. :func:`app.slate_routes._run_activation` calls
  it after a promotion or rollback has committed, with the changed pages of the releases involved.
  A CDN failure is reported on the activation response and in the dispatch log; it never undoes
  or fails the activation, because the origin is already serving the new release and refusing to
  say so would be worse than a stale edge.

**The credential goes in one header and nowhere else.** Provider messages are passed through
:func:`app.slate_cdn.redact` before they are stored or returned, so a provider that echoes the
token in an error cannot leak it through this service.

**Vendor hosts are constants.** Cloudflare and Fastly calls go to fixed API roots; only a custom
endpoint's URL comes from configuration, and the guarded client re-checks it on every request so a
purge URL that resolves to a private address is refused (``cdn-target-refused``) instead of sent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import httpx

from .config import settings
from .slate_cache_store import routes_for_release
from .slate_cdn import (
    CdnPurgePlan,
    build_requests,
    classify_response,
    error_sentence,
    plan_cdn_purge,
    redact,
)
from .slate_cdn_crypto import unseal_cdn_credential
from .slate_cdn_store import get_provider, record_dispatch, verified_hosts
from .ssrf_guard import SSRFError, build_guarded_async_client

__all__ = [
    "CdnClientFactory",
    "CdnPurgeOutcome",
    "default_client_factory",
    "dispatch_deploy_purge",
    "get_cdn_client_factory",
    "send_purge",
]

_log = logging.getLogger(__name__)

#: Per-call timeout. A purge call that has not answered in this long is not going to.
REQUEST_TIMEOUT_SECONDS = 5.0

#: Ceiling on the whole purge, so a deploy never waits on a CDN for longer than this.
DEADLINE_SECONDS = 20.0

#: Builds the HTTP client a purge is sent with. A FastAPI dependency returns it, so tests swap in
#: an ``httpx.MockTransport`` and the suite never opens a socket.
CdnClientFactory = Callable[[], httpx.AsyncClient]


def default_client_factory() -> httpx.AsyncClient:
    """Build the SSRF-guarded client purges are sent with.

    Redirects are not followed: a purge endpoint that redirects is misconfigured, and following it
    would carry the credential to wherever it pointed.

    Returns:
        A new async client; the caller closes it.
    """
    return build_guarded_async_client(
        allow_private=bool(settings.ssrf_allow_private),
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
        follow_redirects=False,
    )


def get_cdn_client_factory() -> CdnClientFactory:
    """FastAPI dependency returning the client factory purges are sent with.

    Returns:
        :func:`default_client_factory`; tests override this dependency.
    """
    return default_client_factory


@dataclass(frozen=True)
class CdnPurgeOutcome:
    """What a purge did.

    Attributes:
        status: ``succeeded``, ``failed`` or ``skipped``.
        provider: The provider.
        mode: ``urls`` or ``purge-all``.
        url_count: URLs in scope.
        sample_urls: Bounded sample of them.
        http_status: The provider's last HTTP status, when it answered.
        error_code: Why it failed or was skipped; None on success.
        error_message: Redacted explanation; None on success.
        requests_sent: How many provider calls were made.
        dispatch_id: The dispatch-log row, once recorded.
    """

    status: str
    provider: str
    mode: str
    url_count: int = 0
    sample_urls: Sequence[str] = field(default_factory=tuple)
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    requests_sent: int = 0
    dispatch_id: Optional[str] = None

    @property
    def sentence(self) -> str:
        """Describe the outcome in one sentence an operator can act on."""
        if self.status == "succeeded":
            if self.mode == "purge-all":
                return f"The whole {self.provider_label} cache was purged."
            noun = "URL" if self.url_count == 1 else "URLs"
            return f"{self.url_count} {noun} purged at {self.provider_label}."
        return error_sentence(self.error_code) or "Nothing was purged."

    @property
    def provider_label(self) -> str:
        """The provider's display name."""
        return {"cloudflare": "Cloudflare", "fastly": "Fastly"}.get(self.provider, "custom CDN")

    def with_dispatch_id(self, dispatch_id: Optional[str]) -> "CdnPurgeOutcome":
        """Return a copy carrying the dispatch-log row id."""
        return CdnPurgeOutcome(**{**self.__dict__, "dispatch_id": dispatch_id})


def _skipped(plan: CdnPurgePlan, code: str) -> CdnPurgeOutcome:
    """Build the outcome for a purge that sent nothing."""
    return CdnPurgeOutcome(
        status="skipped",
        provider=plan.provider,
        mode=plan.mode,
        url_count=plan.url_count,
        sample_urls=plan.sample_urls,
        error_code=code,
        error_message=error_sentence(code),
    )


async def send_purge(
    provider_row: Mapping[str, Any],
    plan: CdnPurgePlan,
    *,
    context: Mapping[str, Any],
    client_factory: CdnClientFactory,
) -> CdnPurgeOutcome:
    """Send a planned purge to the lane's provider.

    Args:
        provider_row: The ``slate_cdn_providers`` row, credential columns included.
        plan: What to purge.
        context: ``environmentId`` / ``releaseId`` / ``trigger`` for a custom endpoint's body.
        client_factory: Builds the HTTP client.

    Returns:
        The outcome. Never raises for a provider or network problem.
    """
    if plan.skipped_code:
        return _skipped(plan, plan.skipped_code)

    secret = unseal_cdn_credential(
        provider_row.get("credential_ciphertext"), provider_row.get("credential_key_version")
    )
    if not secret:
        failed = _skipped(plan, "cdn-credential-unavailable")
        return CdnPurgeOutcome(**{**failed.__dict__, "status": "failed"})

    requests = build_requests(
        plan,
        target=str(provider_row["target"]),
        auth_header_name=provider_row.get("auth_header_name"),
        secret=secret,
        context=context,
    )
    state: Dict[str, Any] = {"sent": 0, "http_status": None}

    def failure(code: str, message: Optional[str]) -> CdnPurgeOutcome:
        return CdnPurgeOutcome(
            status="failed",
            provider=plan.provider,
            mode=plan.mode,
            url_count=plan.url_count,
            sample_urls=plan.sample_urls,
            http_status=state["http_status"],
            error_code=code,
            error_message=redact(message or error_sentence(code), secret),
            requests_sent=state["sent"],
        )

    async def run() -> Optional[CdnPurgeOutcome]:
        async with client_factory() as client:
            for request in requests:
                response = await client.request(
                    request.method, request.url, headers=dict(request.headers), json=request.json
                )
                state["sent"] += 1
                state["http_status"] = response.status_code
                try:
                    body = response.json()
                except ValueError:
                    body = None
                verdict = classify_response(plan.provider, response.status_code, body)
                if verdict is not None:
                    return failure(*verdict)
        return None

    try:
        failed = await asyncio.wait_for(run(), timeout=DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        return failure("cdn-timeout", None)
    except SSRFError:
        return failure("cdn-target-refused", None)
    except httpx.TimeoutException:
        return failure("cdn-timeout", None)
    except httpx.HTTPError as exc:
        return failure("cdn-unreachable", f"{error_sentence('cdn-unreachable')} ({type(exc).__name__})")

    if failed is not None:
        return failed
    return CdnPurgeOutcome(
        status="succeeded",
        provider=plan.provider,
        mode=plan.mode,
        url_count=plan.url_count,
        sample_urls=plan.sample_urls,
        http_status=state["http_status"],
        requests_sent=state["sent"],
    )


def _changed_routes(db: Any, release_ids: Sequence[Optional[str]]) -> List[str]:
    """Union the changed pages of every release a deploy touched.

    A promotion changes the pages the new release changed; a rollback changes the pages the
    release being left had changed. Taking both covers either direction without guessing which.
    """
    routes: set[str] = set()
    for release_id in release_ids:
        if release_id:
            routes.update(routes_for_release(db, release_id=str(release_id)))
    return sorted(routes)


async def dispatch_deploy_purge(
    db: Any,
    *,
    tenant_id: str,
    environment_id: str,
    release_id: str,
    replaced_release_id: Optional[str],
    actor_id: Optional[str],
    actor_name: str,
    client_factory: CdnClientFactory,
) -> Optional[CdnPurgeOutcome]:
    """Purge the lane's CDN after a release was activated, and log the dispatch.

    Args:
        db: Database handle.
        tenant_id: Owning tenant.
        environment_id: The lane.
        release_id: The release now serving.
        replaced_release_id: The release it replaced, when there was one.
        actor_id: Who deployed.
        actor_name: Their display name.
        client_factory: Builds the HTTP client.

    Returns:
        The outcome, or None when the lane has no CDN. When purge-on-deploy is off the outcome is
        ``skipped`` (``cdn-purge-on-deploy-off``) and is not logged, since nothing was attempted.
        Never raises: an internal failure is reported as ``cdn-dispatch-error``.
    """
    try:
        provider_row = get_provider(db, tenant_id=tenant_id, environment_id=environment_id)
    except Exception:  # noqa: BLE001 — the activation has committed; report, never raise
        _log.exception("Could not read the CDN provider for environment %s", environment_id)
        return None
    if not provider_row:
        return None
    provider = str(provider_row["provider"])
    if not provider_row.get("purge_on_deploy", True):
        return CdnPurgeOutcome(
            status="skipped",
            provider=provider,
            mode="urls",
            error_code="cdn-purge-on-deploy-off",
            error_message="Purge on deploy is off for this lane.",
        )

    try:
        plan = plan_cdn_purge(
            provider=provider,
            hosts=verified_hosts(db, tenant_id=tenant_id, environment_id=environment_id),
            paths=_changed_routes(db, [release_id, replaced_release_id]),
            purge_all_if_empty=True,
        )
        outcome = await send_purge(
            provider_row,
            plan,
            context={
                "trigger": "deploy",
                "environmentId": environment_id,
                "releaseId": release_id,
            },
            client_factory=client_factory,
        )
    except Exception:  # noqa: BLE001 — the activation has committed; report, never raise
        _log.exception("CDN deploy purge failed for environment %s", environment_id)
        outcome = CdnPurgeOutcome(
            status="failed",
            provider=provider,
            mode="urls",
            error_code="cdn-dispatch-error",
            error_message=error_sentence("cdn-dispatch-error"),
        )

    try:
        written = record_dispatch(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            release_id=release_id,
            cache_purge_id=None,
            trigger="deploy",
            provider=provider,
            mode=outcome.mode,
            url_count=outcome.url_count,
            sample_urls=outcome.sample_urls,
            status=outcome.status,
            http_status=outcome.http_status,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
            actor_id=actor_id,
            actor_name=actor_name,
        )
    except Exception:  # noqa: BLE001 — losing the log row must not fail the deploy either
        _log.exception("Could not record CDN deploy purge for environment %s", environment_id)
        return outcome
    return outcome.with_dispatch_id(str(written["id"]) if written.get("id") else None)
