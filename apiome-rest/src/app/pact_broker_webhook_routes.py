"""``/v1/tenants/{tenant_slug}/pact-broker`` — contract webhooks, PFX-1.9 (#6922).

What ``pact-broker create-webhook``, ``create-or-update-webhook`` and ``test-webhook`` call,
unmodified, and what a person reads to see what a webhook did:

* ``GET|POST …/webhooks`` — list or create webhooks; the index's ``pb:webhooks`` link;
* ``GET|PUT|DELETE …/webhooks/{uuid}`` — one webhook; the index's ``pb:webhook``. ``PUT`` creates
  the webhook when the workspace has none with that ``uuid``;
* ``POST …/webhooks/{uuid}/execute`` (a webhook's ``pb:execute`` link) and
  ``POST …/webhooks/execute`` — send a saved or an unsaved webhook once, now, and show the result;
* ``GET|POST …/webhooks/provider/{provider}/consumer/{consumer}``, ``…/webhooks/provider/{provider}``,
  ``…/webhooks/consumer/{consumer}`` and ``…/pacts/provider/{p}/consumer/{c}/webhooks`` — the
  webhooks defined for exactly that consumer and/or provider, and creating one there;
* ``GET …/pacts/provider/{p}/consumer/{c}/webhooks/status`` — the latest firing of each webhook
  and event for the pair, with a summary;
* ``GET …/pacts/provider/{p}/consumer/{c}/version/{v}/triggered-webhooks`` and
  ``GET …/pact-version/{sha}/verification-results/{n}/triggered-webhooks`` — what a publication or
  a verification result fired;
* ``GET …/triggered-webhooks/{uuid}/logs`` — the execution log of one firing, as text or JSON.

Reading needs ``pacts:view``; creating a webhook (and running an unsaved one) ``pacts:create``;
replacing or running a saved one ``pacts:edit``; deleting ``pacts:delete``. Responses are
``application/hal+json`` in the Pact Broker's shape; refusals keep Apiome's
``{"detail": {"code", "message", "pointer"}}``.

**No response ever carries a secret.** A password and a secret header read as ``**********``; a
signing secret reads as ``"signed": true``. Sending ``**********`` back keeps the stored value.

**Workspace secrets** (PFX-6.5): ``${user.<name>}`` in the URL's path or query, a header, the body,
the credentials, the GitHub token or the signing secret refers to a secret kept under
``/v1/tenants/{tenant}/pact-secrets`` (:mod:`app.pact_secret_routes`). A reference must name a secret
of the workspace when the webhook is saved or tested, and is resolved only when it is sent; a webhook
that refers to any lists them as ``secretReferences``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from .config import settings
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    _PAIR_PATH,
    HalJSONResponse,
    _base_url,
    _http_error,
    _pacticipant_url,
    _pair_url,
    _read_pact_body,
    _tenant_id,
)
from .pact_publication import PactPublicationError
from .pact_publication_store import get_latest_pact
from .pact_secret import CODE_SECRET_VAULT_UNAVAILABLE
from .pact_webhook import (
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_SECRETS_UNAVAILABLE,
    CODE_WEBHOOK_TEST_RATE_LIMITED,
    EVENT_NAMES,
    METHODS,
    REDACTED,
    SECRET_PASSWORD,
    SECRET_SIGNING,
    TARGET_GITHUB,
    TEMPLATE_PARAMETERS,
    WebhookInput,
    WebhookRecord,
    header_secret_field,
    parse_webhook_request,
    request_description,
    scope_description,
    template_parameters,
    validate_webhook_uuid,
)
from .pact_webhook_delivery import ExecutionResult, UnsendableWebhookError, execute_webhook
from .pact_webhook_events import pact_url
from .pact_webhook_secrets import KEYS_SETTING
from .pact_webhook_store import (
    ANY_SCOPE,
    TriggeredWebhookRecord,
    checked_references,
    create_webhook,
    delete_webhook,
    get_triggered_webhook_logs,
    get_webhook,
    list_triggered_webhooks,
    list_webhooks,
    load_for_delivery,
    replace_webhook,
)
from .pacticipant import PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .permissions import Action, Resource, enforce_permission
from .rate_limit import FixedWindowRateLimiter

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-broker"
_PACT_PAIR = _PREFIX + _PAIR_PATH

_REFUSALS = (PactPublicationError, PacticipantValidationError)

#: Test runs one workspace may make per rate-limit window: each is an outbound request made now.
TEST_RUNS_PER_WINDOW = 30
_test_limiter = FixedWindowRateLimiter()

_WEBHOOK_EXAMPLE = {
    "description": "Verify Ledger API when a pact changes",
    "provider": {"name": "Ledger API"},
    "events": [{"name": "contract_requiring_verification_published"}],
    "request": {
        "method": "POST",
        "url": "https://ci.example.com/hooks/verify-pact",
        "headers": {"Content-Type": "application/json", "Authorization": "Bearer ci-token"},
        "body": {
            "pactUrl": "${pactbroker.pactUrl}",
            "providerVersion": "${pactbroker.providerVersionNumber}",
            "providerBranch": "${pactbroker.providerVersionBranch}",
        },
    },
    "signingSecret": "a-shared-secret-of-16-chars-or-more",
}

_GITHUB_EXAMPLE = {
    "description": "Run the provider's pact verification workflow",
    "provider": {"name": "Ledger API"},
    "events": [{"name": "contract_requiring_verification_published"}],
    "target": {
        "type": TARGET_GITHUB,
        "repository": "acme/ledger-api",
        "eventType": "pact_requires_verification",
        "token": "github-token-with-contents-write",
    },
}

_PACTICIPANT_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string", "description": "A pacticipant of the workspace."}},
}

_WEBHOOK_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "maxLength": 1000},
                    "consumer": {**_PACTICIPANT_SCHEMA, "description": "Only pacts of this consumer. Omit for any."},
                    "provider": {**_PACTICIPANT_SCHEMA, "description": "Only pacts of this provider. Omit for any."},
                    "enabled": {"type": "boolean", "default": True},
                    "events": {
                        "type": "array",
                        "minItems": 1,
                        "description": "Default: `contract_content_changed`.",
                        "items": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {"name": {"type": "string", "enum": list(EVENT_NAMES)}},
                        },
                    },
                    "request": {
                        "type": "object",
                        "required": ["method", "url"],
                        "description": "The HTTP request to send. Send this or `target`.",
                        "properties": {
                            "method": {"type": "string", "enum": list(METHODS)},
                            "url": {
                                "type": "string",
                                "description": (
                                    "http(s), a public host. `${pactbroker.*}` parameters and `${user.<name>}` "
                                    "workspace secrets may appear in the path and query, not in the host."
                                ),
                            },
                            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                            "body": {"description": "A JSON value (sent as JSON) or a string (sent as text)."},
                            "username": {"type": "string"},
                            "password": {
                                "type": "string",
                                "description": "Sealed; reads as `**********`. May be `${user.<name>}`.",
                            },
                        },
                    },
                    "target": {
                        "type": "object",
                        "required": ["type", "repository", "token"],
                        "description": "Apiome: a GitHub Actions `repository_dispatch`, in place of `request`.",
                        "properties": {
                            "type": {"type": "string", "enum": [TARGET_GITHUB]},
                            "repository": {"type": "string", "description": "`owner/name`."},
                            "eventType": {"type": "string", "default": "${pactbroker.eventName}"},
                            "clientPayload": {"type": "object", "maxProperties": 10},
                            "apiUrl": {"type": "string", "description": "GitHub Enterprise Server API root."},
                            "token": {
                                "type": "string",
                                "description": "Sealed; reads as `**********`. May be `${user.<name>}`.",
                            },
                        },
                    },
                    "signingSecret": {
                        "type": "string",
                        "minLength": 16,
                        "description": (
                            "Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the "
                            "HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. "
                            "May be `${user.<name>}`, a workspace secret of 16 characters or more."
                        ),
                    },
                },
            },
            "examples": {
                "http": {"summary": "A generic HTTP webhook", "value": _WEBHOOK_EXAMPLE},
                "github": {"summary": "A GitHub Actions repository_dispatch", "value": _GITHUB_EXAMPLE},
            },
        }
    },
}

_RATE_429 = {
    429: {"description": "`pact-webhook-test-rate-limited`: too many test runs; `Retry-After` says when to retry."}
}
_WRITE_ERRORS = {
    409: {"description": "`pact-webhook-limit-reached`: the workspace already has 200 webhooks."},
    422: {"description": "`pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field."},
    503: {
        "description": (
            "`pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to "
            "seal it with."
        )
    },
}
_NOT_FOUND = {404: {"description": "`pact-webhook-not-found`: no such webhook in this workspace."}}
_PAIR_NOT_FOUND = {404: {"description": "`pacticipant-not-found`: no such consumer or provider."}}

_TEMPLATE_NOTE = "Template parameters: " + ", ".join(f"`${{{name}}}`" for name in TEMPLATE_PARAMETERS) + "."


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------


def _webhooks_url(base: str) -> str:
    """The URL of the webhook collection."""
    return f"{base}/webhooks"


def _webhook_url(base: str, webhook_id: str) -> str:
    """The URL of one webhook."""
    return f"{_webhooks_url(base)}/{webhook_id}"


def _logs_url(base: str, triggered_id: str) -> str:
    """The URL of a firing's execution log."""
    return f"{base}/triggered-webhooks/{triggered_id}/logs"


def _display_description(webhook: WebhookRecord) -> str:
    """The webhook's description, or its request (``POST host``) when it has none."""
    return webhook.description or request_description(webhook.method, webhook.url)


def _webhook_document(base: str, webhook: WebhookRecord) -> Dict[str, Any]:
    """Render a webhook the way a Pact Broker returns one, without any secret.

    Apiome adds ``signed`` (whether deliveries carry an HMAC signature), ``secretReferences`` (the
    workspace secrets it refers to, when any) and, for a GitHub target, ``target`` with the token
    redacted.

    Args:
        base: The broker base URL.
        webhook: The stored webhook.

    Returns:
        The response body.
    """
    request: Dict[str, Any] = {"method": webhook.method, "url": webhook.url}
    headers = webhook.shown_headers()
    if headers:
        request["headers"] = headers
    if webhook.body is not None:
        request["body"] = webhook.body
    if webhook.username:
        request["username"] = webhook.username
    if SECRET_PASSWORD in webhook.secret_fields:
        request["password"] = REDACTED
    body: Dict[str, Any] = {"uuid": webhook.id, "description": _display_description(webhook)}
    if webhook.consumer_name:
        body["consumer"] = {"name": webhook.consumer_name}
    if webhook.provider_name:
        body["provider"] = {"name": webhook.provider_name}
    body["enabled"] = webhook.enabled
    body["request"] = request
    if webhook.target_kind == TARGET_GITHUB:
        body["target"] = {"type": TARGET_GITHUB, **(webhook.target_config or {}), "token": REDACTED}
    body["events"] = [{"name": name} for name in webhook.events]
    body["signed"] = SECRET_SIGNING in webhook.secret_fields
    if webhook.secret_refs:
        body["secretReferences"] = list(webhook.secret_refs)
    body["createdAt"] = webhook.created_at
    if webhook.updated_at and webhook.updated_at != webhook.created_at:
        body["updatedAt"] = webhook.updated_at
    links: Dict[str, Any] = {
        "self": {"title": _display_description(webhook), "href": _webhook_url(base, webhook.id)},
        "pb:execute": {
            "title": (
                "Test the execution of the webhook with the latest matching pact or verification by sending "
                "a POST request to this URL"
            ),
            "href": f"{_webhook_url(base, webhook.id)}/execute",
        },
    }
    if webhook.consumer_slug:
        links["pb:consumer"] = {
            "title": "Consumer",
            "name": webhook.consumer_name,
            "href": _pacticipant_url(base, webhook.consumer_slug),
        }
    if webhook.provider_slug:
        links["pb:provider"] = {
            "title": "Provider",
            "name": webhook.provider_name,
            "href": _pacticipant_url(base, webhook.provider_slug),
        }
    if webhook.consumer_slug and webhook.provider_slug:
        links["pb:pact-webhooks"] = {
            "title": f"All webhooks for consumer {webhook.consumer_name} and provider {webhook.provider_name}",
            "href": f"{_webhooks_url(base)}/provider/{webhook.provider_slug}/consumer/{webhook.consumer_slug}",
        }
    links["pb:webhooks"] = {"title": "All webhooks", "href": _webhooks_url(base)}
    body["_links"] = links
    return body


def _webhooks_document(base: str, webhooks: Sequence[WebhookRecord], self_href: str) -> Dict[str, Any]:
    """A webhook collection: one ``pb:webhooks`` link per webhook, and the webhooks embedded."""
    return {
        "_embedded": {"webhooks": [_webhook_document(base, webhook) for webhook in webhooks]},
        "_links": {
            "self": {"title": "Webhooks", "href": self_href},
            "pb:create": {"title": "POST to create a webhook", "href": self_href},
            "pb:webhooks": [
                {
                    "title": scope_description(webhook.consumer_name, webhook.provider_name),
                    "name": _display_description(webhook),
                    "href": _webhook_url(base, webhook.id),
                }
                for webhook in webhooks
            ],
        },
    }


def _triggered_document(base: str, triggered: TriggeredWebhookRecord) -> Dict[str, Any]:
    """Render one firing the way a Pact Broker returns a triggered webhook."""
    logs = _logs_url(base, triggered.id)
    return {
        "name": triggered.name,
        "status": triggered.status,
        "attemptsMade": triggered.attempts_made,
        "attemptsRemaining": triggered.attempts_remaining,
        "triggerType": triggered.trigger_type,
        "eventName": triggered.event_name,
        "triggeredAt": triggered.triggered_at,
        "_links": {
            "pb:logs": {"href": logs, "title": "Webhook execution logs", "name": triggered.name},
            "logs": {"href": logs, "title": "DEPRECATED - Use pb:logs", "name": triggered.name},
            "pb:webhook": {
                "href": _webhook_url(base, triggered.webhook_id),
                "title": "Webhook",
                "name": triggered.name,
            },
        },
    }


def _triggered_list(
    base: str, triggered: Sequence[TriggeredWebhookRecord], self_href: str, title: str
) -> Dict[str, Any]:
    """A list of firings: ``_embedded.triggeredWebhooks`` and a titled ``self`` link."""
    return {
        "_embedded": {"triggeredWebhooks": [_triggered_document(base, item) for item in triggered]},
        "_links": {"self": {"title": title, "href": self_href}},
    }


def _execution_document(
    base: str, result: ExecutionResult, webhook_id: Optional[str], self_href: str
) -> Dict[str, Any]:
    """Render a test run the way a Pact Broker returns a webhook execution result."""
    body: Dict[str, Any] = {
        "request": {"headers": result.request_headers, "body": result.request_body, "url": result.url},
        "logs": result.logs,
        "success": result.success,
    }
    if result.status is not None:
        body["response"] = {
            "status": result.status,
            "headers": result.response_headers,
            "body": result.response_body,
        }
    elif result.error:
        body["error"] = {"message": result.error}
    links: Dict[str, Any] = {"try-again": {"title": "Execute the webhook again", "href": self_href}}
    if webhook_id:
        links["webhook"] = {"href": _webhook_url(base, webhook_id)}
    body["_links"] = links
    return body


def _self_href(request: Request) -> str:
    """The URL of this request on the broker surface, with its query string."""
    path = request.url.path
    root = _base_url(request, request.path_params["tenant_slug"])
    suffix = path.split("/pact-broker", 1)[1] if "/pact-broker" in path else path
    return f"{root}{suffix}" + (f"?{request.url.query}" if request.url.query else "")


# ---------------------------------------------------------------------------------------------
# Shared steps
# ---------------------------------------------------------------------------------------------


def _scope(tenant_id: str, consumer: Optional[str], provider: Optional[str]) -> tuple:
    """Resolve the consumer and provider of a scoped webhook route.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    return (
        get_pacticipant(db, tenant_id, consumer) if consumer is not None else None,
        get_pacticipant(db, tenant_id, provider) if provider is not None else None,
    )


def _list(request: Request, tenant_slug: str, auth_data: Dict[str, Any], scope: Any) -> HalJSONResponse:
    """List webhooks behind ``pacts:view``; ``scope`` is ``ANY_SCOPE`` or ``(consumer, provider)`` names."""
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        resolved = scope if scope is ANY_SCOPE else _scope(tenant_id, *scope)
        webhooks = list_webhooks(db, tenant_id, scope=resolved)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_webhooks_document(_base_url(request, tenant_slug), webhooks, _self_href(request)))


def _create(
    request: Request,
    tenant_slug: str,
    raw: bytes,
    auth_data: Dict[str, Any],
    *,
    consumer: Optional[str] = None,
    provider: Optional[str] = None,
) -> HalJSONResponse:
    """Create a webhook behind ``pacts:create``; a scoped route's consumer and provider win over the body's."""
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    try:
        scoped_consumer, scoped_provider = _scope(tenant_id, consumer, provider)
        webhook = parse_webhook_request(raw)
        if scoped_consumer is not None:
            webhook.consumer_name = scoped_consumer.name
        if scoped_provider is not None:
            webhook.provider_name = scoped_provider.name
        created = create_webhook(db, tenant_id, webhook, actor=actor_from_auth(auth_data, user_id))
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    return HalJSONResponse(
        _webhook_document(base, created), status_code=201, headers={"Location": _webhook_url(base, created.id)}
    )


def _enforce_test_budget(tenant_id: str) -> None:
    """Count one test run against the workspace's budget.

    Args:
        tenant_id: The caller's tenant.

    Raises:
        HTTPException: 429 ``pact-webhook-test-rate-limited`` with ``Retry-After`` when over
            :data:`TEST_RUNS_PER_WINDOW`.
    """
    if not settings.rate_limit_enabled:
        return
    window = max(1, settings.rate_limit_window_seconds)
    allowed, _remaining, _reset_after, retry_after = _test_limiter.check(
        f"pactwebhooktest:{tenant_id}", TEST_RUNS_PER_WINDOW, window, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CODE_WEBHOOK_TEST_RATE_LIMITED,
                "message": (
                    f"this workspace may test webhooks {TEST_RUNS_PER_WINDOW} times per {window} seconds; "
                    "retry later"
                ),
            },
            headers={"Retry-After": str(retry_after)},
        )


def _test_parameters(tenant_id: str, base: str, consumer: Optional[str], provider: Optional[str]) -> Dict[str, str]:
    """Template parameters for a test run: the pair's latest pact, or placeholders without one."""
    values: Dict[str, Any] = {
        "event_name": "test",
        "consumer_name": consumer or "placeholder-consumer",
        "provider_name": provider or "placeholder-provider",
        "consumer_version_number": "placeholder-consumer-version",
        "provider_version_number": "placeholder-provider-version",
    }
    if consumer and provider:
        try:
            pact = get_latest_pact(db, tenant_id, provider, consumer)
        except _REFUSALS:
            pact = None
        if pact is not None:
            values.update(
                consumer_name=pact.consumer_name,
                provider_name=pact.provider_name,
                consumer_version_number=pact.consumer_version,
                pact_url=pact_url(base, pact.provider_slug, pact.consumer_slug, pact.sha, pact.consumer_version),
            )
    return template_parameters(**values)


def _transient(webhook: WebhookInput, tenant_id: str) -> tuple:
    """An unsaved webhook as a record and its secrets, for a test run.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` for a ``**********`` secret — nothing is
            stored to stand in for it — or a reference to a secret the workspace does not have.
    """
    secrets: Dict[str, Any] = {"headers": dict(webhook.secret_headers)}
    if webhook.password:
        secrets["password"] = webhook.password
    if webhook.signing_secret:
        secrets["signingSecret"] = webhook.signing_secret
    if REDACTED in (webhook.password, webhook.signing_secret, *webhook.secret_headers.values()):
        raise PactPublicationError(
            CODE_WEBHOOK_INVALID,
            f"an unsaved webhook has no stored secret for {REDACTED} to keep; send the value itself",
            pointer="/request",
        )
    record = WebhookRecord(
        id="",
        description=webhook.description,
        consumer_name=webhook.consumer_name,
        provider_name=webhook.provider_name,
        enabled=webhook.enabled,
        events=webhook.events,
        target_kind=webhook.target_kind,
        target_config=webhook.target_config,
        method=webhook.method,
        url=webhook.url,
        headers=webhook.headers,
        body=webhook.body,
        username=webhook.username,
        secret_fields=[header_secret_field(name) for name in webhook.secret_headers],
        secret_refs=checked_references(db, tenant_id, webhook, secrets),
    )
    return record, secrets


def _run(record: WebhookRecord, secrets: Dict[str, Any], tenant_id: str, base: str) -> ExecutionResult:
    """Send a webhook once for a test run, its workspace secret references resolved.

    Raises:
        HTTPException: 422 ``pact-webhook-invalid`` when a referred secret is gone or too short to
            sign with; 503 ``pact-webhook-secrets-unavailable`` when one cannot be opened.
    """
    try:
        return execute_webhook(
            record,
            secrets,
            _test_parameters(tenant_id, base, record.consumer_name, record.provider_name),
            database=db,
            tenant_id=tenant_id,
        )
    except UnsendableWebhookError as exc:
        cause = getattr(exc.__cause__, "code", "")
        code = CODE_WEBHOOK_SECRETS_UNAVAILABLE if cause == CODE_SECRET_VAULT_UNAVAILABLE else CODE_WEBHOOK_INVALID
        raise _http_error(PactPublicationError(code, f"the webhook cannot be sent: {exc}")) from exc


# ---------------------------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------------------------


@router.get(
    _PREFIX + "/webhooks",
    response_class=HalJSONResponse,
    summary="List webhooks",
    description=(
        "Every webhook of the workspace — the index's `pb:webhooks` link. Each is linked under "
        "`_links.pb:webhooks` and embedded under `_embedded.webhooks`. Secrets are never returned: a "
        "password and a secret header read `**********`, a signing secret reads `signed: true`.\n\n"
        "Requires `pacts:view`."
    ),
)
def read_webhooks(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the workspace's webhooks.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The webhooks, oldest first.
    """
    return _list(request, tenant_slug, auth_data, ANY_SCOPE)


_CREATE_DESCRIPTION = (
    "Create a webhook — what `pact-broker create-webhook` posts. The body is the Pact Broker's: "
    "`events` (default `contract_content_changed`), an optional `consumer` and `provider` (omit both "
    "for every pact of the workspace) and the `request` to send.\n\n"
    "- **Events:** `contract_published`, `contract_content_changed`, "
    "`contract_requiring_verification_published` (once per provider version that has not verified "
    "the pact: the head of the provider's main branch and what is deployed or released), "
    "`provider_verification_published`, `provider_verification_succeeded`, "
    "`provider_verification_failed`, and Apiome's `consumer_version_branch_created` and stale-pact "
    "remediation events (`contract_became_stale`, `contract_no_longer_stale`, "
    "`contract_republish_requested`, `contract_republish_request_expired`).\n"
    "- **Templates:** `${pactbroker.*}` parameters are substituted in the URL's path and query, the "
    "headers, the credentials and the body when the webhook fires. " + _TEMPLATE_NOTE + "\n"
    "- **Target:** send `request` for any HTTP endpoint (POST, PUT or PATCH), or Apiome's `target` "
    "of type `github_repository_dispatch` to start a GitHub Actions workflow.\n"
    "- **Where it may go:** http or https, to a public address. Loopback, private and link-local "
    "addresses are refused when the webhook is saved and again on every send; redirects are not "
    "followed.\n"
    "- **Secrets:** `password`, the `target` token, secret headers (`Authorization`, anything "
    "naming a token, secret, API key or cookie) and `signingSecret` are sealed in the credential "
    "vault and never returned or logged.\n"
    "- **Workspace secrets:** `${user.<name>}` in the URL's path or query, a header, the body, the "
    "credentials, the `target` token or `signingSecret` refers to a secret kept under "
    "`/v1/tenants/{tenant}/pact-secrets`; it must exist when the webhook is saved (`422` "
    "`pact-webhook-invalid` naming the field otherwise), is resolved only when the webhook is sent, and "
    "is scrubbed from every log. The webhook lists the names as `secretReferences`.\n"
    "- **Signing:** with `signingSecret`, each delivery carries `X-Apiome-Signature: sha256=<hex>`, "
    "the HMAC-SHA256 of the body.\n"
    "- **Limit:** 200 webhooks per workspace.\n"
    "- **Delivery:** up to 4 attempts (after 10 s, 60 s and 5 min; `Retry-After` is honoured), "
    "then the firing is dead-lettered.\n\n"
    "Answers `201` with the webhook and its URL in `Location`. Requires `pacts:create`."
)


@router.post(
    _PREFIX + "/webhooks",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Create a webhook",
    description=_CREATE_DESCRIPTION,
    openapi_extra={"requestBody": _WEBHOOK_BODY},
    responses=_WRITE_ERRORS,
)
@audited_write("pacts.webhook.create", "pact-webhooks")
def post_webhook(
    tenant_slug: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Create a webhook.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The webhook, ``201``.
    """
    return _create(request, tenant_slug, raw, auth_data)


@router.post(
    _PREFIX + "/webhooks/execute",
    response_class=HalJSONResponse,
    summary="Run an unsaved webhook",
    description=(
        "Send the webhook in the body once, now, without saving it — to try a request before "
        "creating the webhook. Parameters are filled from the latest pact of the named consumer and "
        "provider, or with placeholders. The answer shows the request (secrets redacted), the "
        "response and the execution log. A workspace may make 30 test runs per rate-limit window. "
        "Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _WEBHOOK_BODY},
    responses={**_WRITE_ERRORS, **_RATE_429},
)
@audited_write("pacts.webhook.execute", "pact-webhooks/execute")
def execute_unsaved_webhook(
    tenant_slug: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Run an unsaved webhook once.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        raw: The webhook body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The execution result.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    _enforce_test_budget(tenant_id)
    try:
        record, secrets = _transient(parse_webhook_request(raw), tenant_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    result = _run(record, secrets, tenant_id, base)
    return HalJSONResponse(_execution_document(base, result, None, _self_href(request)))


@router.get(
    _PREFIX + "/webhooks/{uuid}",
    response_class=HalJSONResponse,
    summary="Read a webhook",
    description="One webhook by its `uuid` — the index's `pb:webhook` template. Requires `pacts:view`.",
    responses=_NOT_FOUND,
)
def read_webhook(
    tenant_slug: str,
    uuid: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one webhook.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The webhook's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The webhook.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        webhook = get_webhook(db, _tenant_id(auth_data), validate_webhook_uuid(uuid))
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_webhook_document(_base_url(request, tenant_slug), webhook))


@router.put(
    _PREFIX + "/webhooks/{uuid}",
    response_class=HalJSONResponse,
    summary="Create or replace a webhook",
    description=(
        "Replace the webhook with this `uuid`, or create it when the workspace has none — what "
        "`pact-broker create-or-update-webhook --uuid …` puts, so a pipeline can declare its webhook "
        "on every run. The body is the same as for creating one, and replaces the whole webhook.\n\n"
        "A secret sent back as `**********` keeps the stored value; a secret left out is removed.\n\n"
        "Answers `200` for a replacement and `201` for a new webhook. Requires `pacts:edit` "
        "(`pacts:create` when it creates)."
    ),
    openapi_extra={"requestBody": _WEBHOOK_BODY},
    responses={201: {"description": "The webhook did not exist and was created."}, **_WRITE_ERRORS},
)
@audited_write("pacts.webhook.update", "pact-webhook/{uuid}")
def put_webhook(
    tenant_slug: str,
    uuid: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Create or replace a webhook.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The webhook's id.
        request: The request.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The webhook: ``200`` when replaced, ``201`` when created.
    """
    tenant_id = _tenant_id(auth_data)
    try:
        webhook_id = validate_webhook_uuid(uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    exists = load_for_delivery(db, webhook_id, tenant_id) is not None
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT if exists else Action.CREATE)
    actor = actor_from_auth(auth_data, user_id)
    try:
        webhook = parse_webhook_request(raw)
        stored = (
            replace_webhook(db, tenant_id, webhook_id, webhook, actor=actor)
            if exists
            else create_webhook(db, tenant_id, webhook, actor=actor, webhook_id=webhook_id)
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _webhook_document(_base_url(request, tenant_slug), stored), status_code=200 if exists else 201
    )


@router.delete(
    _PREFIX + "/webhooks/{uuid}",
    status_code=204,
    summary="Delete a webhook",
    description=(
        "Delete a webhook. Its queued deliveries, its triggered-webhook history and their logs go "
        "with it. Requires `pacts:delete`."
    ),
    responses=_NOT_FOUND,
)
@audited_write("pacts.webhook.delete", "pact-webhook/{uuid}")
def remove_webhook(
    tenant_slug: str,
    uuid: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Delete a webhook.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The webhook's id.
        auth_data: The authenticated principal.

    Returns:
        ``204``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE)
    try:
        delete_webhook(db, _tenant_id(auth_data), validate_webhook_uuid(uuid))
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.post(
    _PREFIX + "/webhooks/{uuid}/execute",
    response_class=HalJSONResponse,
    summary="Run a webhook now",
    description=(
        "Send a saved webhook once, now — a webhook's `pb:execute` link and what `pact-broker "
        "test-webhook` posts. Parameters are filled from the latest pact of the webhook's consumer "
        "and provider, or with placeholders; `${pactbroker.eventName}` is `test`. Nothing is queued "
        "or retried. The answer shows the request (secrets redacted), the response and `logs`. A "
        "workspace may make 30 test runs per rate-limit window.\n\n"
        "Requires `pacts:edit`."
    ),
    responses={
        **_NOT_FOUND,
        **_RATE_429,
        503: {"description": "`pact-webhook-secrets-unavailable`: the webhook's secrets cannot be opened."},
    },
)
@audited_write("pacts.webhook.execute", "pact-webhook/{uuid}")
def execute_saved_webhook(
    tenant_slug: str,
    uuid: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Run a saved webhook once.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The webhook's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The execution result.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    _enforce_test_budget(tenant_id)
    try:
        webhook_id = validate_webhook_uuid(uuid)
        hook = load_for_delivery(db, webhook_id, tenant_id)
        if hook is None:
            get_webhook(db, tenant_id, webhook_id)  # raises the 404
        assert hook is not None
        if hook.secrets is None:
            raise PactPublicationError(
                CODE_WEBHOOK_SECRETS_UNAVAILABLE,
                f"the webhook's secrets cannot be opened (check {KEYS_SETTING})",
            )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    record = hook.record
    result = _run(record, hook.secrets, tenant_id, base)
    return HalJSONResponse(_execution_document(base, result, record.id, _self_href(request)))


# ---------------------------------------------------------------------------------------------
# Webhooks of a consumer and/or provider
# ---------------------------------------------------------------------------------------------

_SCOPED_LIST = (
    "The webhooks defined for exactly this scope (a webhook for all pacts is not listed here; see "
    "`GET …/webhooks`). Requires `pacts:view`."
)
_SCOPED_CREATE = (
    "Create a webhook for this scope: the consumer and provider of the URL replace any in the body. "
    "Otherwise as `POST …/webhooks`. Requires `pacts:create`."
)


def _scoped_routes(path: str, what: str, *, consumer: bool, provider: bool) -> None:
    """Register the list and create routes of one scoped webhook path.

    Args:
        path: The path under the broker prefix.
        what: The scope in words, for the summaries.
        consumer: Whether the path names a consumer.
        provider: Whether the path names a provider.
    """

    def names(request: Request) -> tuple:
        params = request.path_params
        return (params.get("consumer") if consumer else None, params.get("provider") if provider else None)

    def read_scoped(
        tenant_slug: str,
        request: Request,
        auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
    ) -> HalJSONResponse:
        """List the webhooks of the scope in the URL."""
        return _list(request, tenant_slug, auth_data, names(request))

    @audited_write("pacts.webhook.create", "pact-webhooks")
    def post_scoped(
        tenant_slug: str,
        request: Request,
        raw: bytes = Depends(_read_pact_body),
        auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
    ) -> HalJSONResponse:
        """Create a webhook for the scope in the URL."""
        scoped_consumer, scoped_provider = names(request)
        return _create(request, tenant_slug, raw, auth_data, consumer=scoped_consumer, provider=scoped_provider)

    # The handlers read the names from ``request.path_params``, so FastAPI does not see them as
    # parameters; declare them so the OpenAPI document resolves every ``{placeholder}`` in the path.
    path_parameters = [
        {"name": name, "in": "path", "required": True, "schema": {"type": "string"}, "description": f"The {name}."}
        for name, used in (("provider", provider), ("consumer", consumer))
        if used
    ]

    router.add_api_route(
        _PREFIX + path,
        read_scoped,
        methods=["GET"],
        response_class=HalJSONResponse,
        summary=f"List the webhooks of {what}",
        description=_SCOPED_LIST,
        openapi_extra={"parameters": path_parameters},
        responses=_PAIR_NOT_FOUND,
    )
    router.add_api_route(
        _PREFIX + path,
        post_scoped,
        methods=["POST"],
        response_class=HalJSONResponse,
        status_code=201,
        summary=f"Create a webhook for {what}",
        description=_SCOPED_CREATE,
        openapi_extra={"requestBody": _WEBHOOK_BODY, "parameters": path_parameters},
        responses={**_PAIR_NOT_FOUND, **_WRITE_ERRORS},
    )


_scoped_routes("/webhooks/provider/{provider}/consumer/{consumer}", "an integration", consumer=True, provider=True)
_scoped_routes("/webhooks/provider/{provider}", "a provider", consumer=False, provider=True)
_scoped_routes("/webhooks/consumer/{consumer}", "a consumer", consumer=True, provider=False)
_scoped_routes(_PAIR_PATH + "/webhooks", "a pact", consumer=True, provider=True)


# ---------------------------------------------------------------------------------------------
# What fired
# ---------------------------------------------------------------------------------------------


def _pair(tenant_id: str, provider: str, consumer: str) -> tuple:
    """Resolve the provider and consumer of a pact route.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    return get_pacticipant(db, tenant_id, provider), get_pacticipant(db, tenant_id, consumer)


def _summary(triggered: Sequence[TriggeredWebhookRecord]) -> Dict[str, int]:
    """Count firings by status, as the Pact Broker's webhook status does."""
    counts = {"successful": 0, "failed": 0, "retrying": 0, "notRun": 0}
    keys = {"success": "successful", "failure": "failed", "retrying": "retrying", "not_run": "notRun"}
    for item in triggered:
        counts[keys.get(item.status, "notRun")] += 1
    return counts


@router.get(
    _PACT_PAIR + "/webhooks/status",
    response_class=HalJSONResponse,
    summary="Webhook status of a pact",
    description=(
        "The latest firing of each webhook and event for the pacts between a consumer and a "
        "provider, with a `summary` (`successful`, `failed`, `retrying`, `notRun`) and a "
        "`pb:error-logs` link per firing that failed or is being retried. `failed` means "
        "dead-lettered: every attempt was used. Requires `pacts:view`."
    ),
    responses=_PAIR_NOT_FOUND,
)
def read_pact_webhooks_status(
    tenant_slug: str,
    provider: str,
    consumer: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the webhook status of a pact.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The summary and the latest firings.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        provider_record, consumer_record = _pair(tenant_id, provider, consumer)
        triggered = list_triggered_webhooks(db, tenant_id, consumer_record, provider_record, latest_only=True)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    pair = _pair_url(base, provider_record.slug, consumer_record.slug)
    document = _triggered_list(base, triggered, _self_href(request), "Webhooks status")
    document["summary"] = _summary(triggered)
    document["_links"].update(
        {
            "pb:error-logs": [
                {"href": _logs_url(base, item.id), "title": "Error logs", "name": item.name}
                for item in triggered
                if item.status in ("failure", "retrying")
            ],
            "pb:pact-webhooks": {
                "title": f"Webhooks for the pact between {consumer_record.name} and {provider_record.name}",
                "href": f"{pair}/webhooks",
            },
            "pb:consumer": {
                "title": "Consumer",
                "name": consumer_record.name,
                "href": _pacticipant_url(base, consumer_record.slug),
            },
            "pb:provider": {
                "title": "Provider",
                "name": provider_record.name,
                "href": _pacticipant_url(base, provider_record.slug),
            },
        }
    )
    return HalJSONResponse(document)


def _read_triggered(
    request: Request,
    tenant_slug: str,
    auth_data: Dict[str, Any],
    provider: str,
    consumer: str,
    title: str,
    **filters: Any,
) -> HalJSONResponse:
    """List the firings of a pair behind ``pacts:view``, narrowed by ``filters``."""
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        provider_record, consumer_record = _pair(tenant_id, provider, consumer)
        triggered = list_triggered_webhooks(db, tenant_id, consumer_record, provider_record, **filters)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_triggered_list(_base_url(request, tenant_slug), triggered, _self_href(request), title))


@router.get(
    _PACT_PAIR + "/version/{consumer_version}/triggered-webhooks",
    response_class=HalJSONResponse,
    summary="Webhooks a publication triggered",
    description=(
        "The webhooks fired by this consumer version's publication of its pact for the provider, "
        "newest first, each with its status and a `pb:logs` link. Requires `pacts:view`."
    ),
    responses=_PAIR_NOT_FOUND,
)
def read_pact_triggered_webhooks(
    tenant_slug: str,
    provider: str,
    consumer: str,
    consumer_version: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List what a publication fired.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        consumer_version: The consumer version that published.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The firings.
    """
    return _read_triggered(
        request,
        tenant_slug,
        auth_data,
        provider,
        consumer,
        "Webhooks triggered by the publication of the pact",
        consumer_version_number=consumer_version,
    )


@router.get(
    _PACT_PAIR + "/pact-version/{sha}/verification-results/{number}/triggered-webhooks",
    response_class=HalJSONResponse,
    summary="Webhooks a verification result triggered",
    description=(
        "The webhooks fired by the publication of this verification result, newest first, each "
        "with its status and a `pb:logs` link. Requires `pacts:view`."
    ),
    responses=_PAIR_NOT_FOUND,
)
def read_verification_triggered_webhooks(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    number: int,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List what a verification result fired.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The verified pact version.
        number: The result's number.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The firings.
    """
    return _read_triggered(
        request,
        tenant_slug,
        auth_data,
        provider,
        consumer,
        "Webhooks triggered by the publication of the verification result",
        verification=((sha or "").strip().lower(), number),
    )


@router.get(
    _PREFIX + "/triggered-webhooks/{uuid}/logs",
    summary="Execution log of a triggered webhook",
    description=(
        "What each attempt of one firing sent and received — a triggered webhook's `pb:logs` link. "
        "As `text/plain` (the default, as a Pact Broker answers) the logs of every attempt, in "
        "order; with `Accept: application/hal+json`, one entry per attempt under `executions` "
        "(`attempt`, `success`, `status`, `logs`, `createdAt`).\n\n"
        "Secret header values read `**********`, and every secret value of the webhook is removed "
        "from the whole log, the receiver's response included. Requires `pacts:view`."
    ),
    responses={
        200: {"content": {"text/plain": {}, "application/hal+json": {}}},
        404: {"description": "`pact-triggered-webhook-not-found`: no such triggered webhook."},
    },
)
def read_triggered_webhook_logs(
    tenant_slug: str,
    uuid: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Read the execution log of one firing.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The firing's id.
        request: The request (its ``Accept`` header chooses text or JSON).
        auth_data: The authenticated principal.

    Returns:
        The log as text, or as a HAL document.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        logs = get_triggered_webhook_logs(db, _tenant_id(auth_data), (uuid or "").strip().lower())
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    if "json" not in request.headers.get("accept", "").lower():
        text = "\n".join(str(execution["logs"]) for execution in logs.executions)
        return PlainTextResponse(text or "Webhook has not executed yet. Please retry in a few seconds.")
    base = _base_url(request, tenant_slug)
    triggered = logs.triggered
    executions: List[Dict[str, Any]] = logs.executions
    return HalJSONResponse(
        {
            "eventName": triggered.event_name,
            "consumerName": triggered.consumer_name,
            "providerName": triggered.provider_name,
            "status": triggered.status,
            "attemptsMade": triggered.attempts_made,
            "attemptsRemaining": triggered.attempts_remaining,
            "executions": executions,
            "_embedded": {"triggeredWebhook": {"uuid": triggered.id}},
            "_links": {
                "self": {"title": "Triggered webhook logs", "href": _self_href(request)},
                "pb:webhook": {"title": "Webhook", "href": _webhook_url(base, triggered.webhook_id)},
            },
        }
    )
