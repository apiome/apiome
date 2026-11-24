"""The contract-webhook contract — PFX-1.9 (#6922).

A webhook tells CI that something happened to a pact: one was published, its content changed, it
needs verifying by a provider version, or a verification finished. This module is the pure half —
no database, no network:

* the **events** a webhook can fire on (:data:`EVENT_NAMES`) — the Pact Broker's six, plus
  Apiome's ``consumer_version_branch_created``;
* **reading a webhook body** in the Pact Broker's shape (:func:`parse_webhook_request`): the
  ``request`` to send, or Apiome's ``target`` for a GitHub Actions ``repository_dispatch``;
* the **template parameters** (:func:`template_parameters`) — every ``${pactbroker.*}`` name a
  Pact Broker substitutes — and **rendering** a request from them (:func:`render_request`);
* **redaction**: which header values are secret (:func:`is_secret_header`), how a stored webhook
  is shown without them, and :func:`scrub`, which removes secret values from any text bound for a
  log.

Three rules are enforced here so no caller has to remember them:

**A secret is never part of what is stored in the clear or shown.** :class:`WebhookInput` keeps the
password, the secret header values and the signing secret apart from everything else, so the store
seals exactly those (:mod:`app.pact_webhook_secrets`) and nothing else needs sealing.

**A webhook cannot be pointed inward.** The URL passes :mod:`app.ssrf_guard`: http/https only, no
``user:pass@`` authority, a host that resolves to public addresses — and a template parameter may
not appear in the host, so a pacticipant name can never choose where a request goes.

**Every refusal has a stable code** (:data:`CODE_WEBHOOK_INVALID` with a JSON pointer, …) carried
by :class:`~app.pact_publication.PactPublicationError`, as on every other broker route.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .pact_publication import PactPublicationError
from .revision_deprecation import is_uuid_string
from .ssrf_guard import SSRFError, validate_host, validate_url_policy

__all__ = [
    "CODE_WEBHOOK_INVALID",
    "CODE_WEBHOOK_LIMIT",
    "CODE_WEBHOOK_NOT_FOUND",
    "CODE_WEBHOOK_SECRETS_UNAVAILABLE",
    "CODE_WEBHOOK_TEST_RATE_LIMITED",
    "CODE_TRIGGERED_WEBHOOK_NOT_FOUND",
    "DEFAULT_EVENT",
    "EVENT_BRANCH_CREATED",
    "EVENT_CONTENT_CHANGED",
    "EVENT_NAMES",
    "EVENT_PUBLISHED",
    "EVENT_REQUIRING_VERIFICATION",
    "EVENT_VERIFICATION_FAILED",
    "EVENT_VERIFICATION_PUBLISHED",
    "EVENT_VERIFICATION_SUCCEEDED",
    "MAX_WEBHOOKS_PER_TENANT",
    "METHODS",
    "REDACTED",
    "SECRET_PASSWORD",
    "SECRET_SIGNING",
    "SIGNATURE_HEADER",
    "TARGET_GITHUB",
    "TARGET_HTTP",
    "TEMPLATE_PARAMETERS",
    "RenderedRequest",
    "WebhookInput",
    "WebhookRecord",
    "check_url",
    "header_secret_field",
    "is_secret_header",
    "parse_webhook_request",
    "render_request",
    "render_text",
    "request_description",
    "scope_description",
    "scrub",
    "template_parameters",
    "validate_webhook_uuid",
]

#: The webhook body is malformed (HTTP 422, with a pointer).
CODE_WEBHOOK_INVALID = "pact-webhook-invalid"
#: No such webhook (HTTP 404).
CODE_WEBHOOK_NOT_FOUND = "pact-webhook-not-found"
#: No such triggered webhook (HTTP 404).
CODE_TRIGGERED_WEBHOOK_NOT_FOUND = "pact-triggered-webhook-not-found"
#: The workspace already has :data:`MAX_WEBHOOKS_PER_TENANT` webhooks (HTTP 409).
CODE_WEBHOOK_LIMIT = "pact-webhook-limit-reached"
#: Too many test runs in the rate-limit window (HTTP 429).
CODE_WEBHOOK_TEST_RATE_LIMITED = "pact-webhook-test-rate-limited"
#: The webhook carries a secret and the server has no key to seal it with (HTTP 503).
CODE_WEBHOOK_SECRETS_UNAVAILABLE = "pact-webhook-secrets-unavailable"

EVENT_PUBLISHED = "contract_published"
EVENT_CONTENT_CHANGED = "contract_content_changed"
EVENT_REQUIRING_VERIFICATION = "contract_requiring_verification_published"
EVENT_VERIFICATION_PUBLISHED = "provider_verification_published"
EVENT_VERIFICATION_SUCCEEDED = "provider_verification_succeeded"
EVENT_VERIFICATION_FAILED = "provider_verification_failed"
#: Apiome only: a pact publication recorded the consumer version on a branch that is new.
EVENT_BRANCH_CREATED = "consumer_version_branch_created"

#: Every event a webhook may name (mirrors the V436 CHECK).
EVENT_NAMES: Tuple[str, ...] = (
    EVENT_PUBLISHED,
    EVENT_CONTENT_CHANGED,
    EVENT_REQUIRING_VERIFICATION,
    EVENT_VERIFICATION_PUBLISHED,
    EVENT_VERIFICATION_SUCCEEDED,
    EVENT_VERIFICATION_FAILED,
    EVENT_BRANCH_CREATED,
)
#: The event of a webhook that names none, as in the Pact Broker.
DEFAULT_EVENT = EVENT_CONTENT_CHANGED

#: The most webhooks one workspace may have: every publish queues a delivery per matching webhook.
MAX_WEBHOOKS_PER_TENANT = 200

#: The methods a webhook may use (mirrors the V436 CHECK).
METHODS: Tuple[str, ...] = ("POST", "PUT", "PATCH")

TARGET_HTTP = "http"
TARGET_GITHUB = "github_repository_dispatch"

#: What a secret reads as, and what a client sends back to keep the stored one.
REDACTED = "**********"

#: The header carrying the HMAC-SHA256 of the body — the one every Apiome webhook is signed with.
SIGNATURE_HEADER = "X-Apiome-Signature"

#: Names of the sealed values in ``secret_fields``.
SECRET_PASSWORD = "password"
SECRET_SIGNING = "signingSecret"
_SECRET_HEADER_PREFIX = "header:"

#: Every ``${pactbroker.*}`` name a Pact Broker substitutes.
TEMPLATE_PARAMETERS: Tuple[str, ...] = (
    "pactbroker.consumerName",
    "pactbroker.providerName",
    "pactbroker.consumerVersionNumber",
    "pactbroker.providerVersionNumber",
    "pactbroker.providerVersionTags",
    "pactbroker.providerVersionDescriptions",
    "pactbroker.providerVersionBranch",
    "pactbroker.consumerVersionTags",
    "pactbroker.consumerVersionBranch",
    "pactbroker.pactUrl",
    "pactbroker.verificationResultUrl",
    "pactbroker.githubVerificationStatus",
    "pactbroker.bitbucketVerificationStatus",
    "pactbroker.azureDevOpsVerificationStatus",
    "pactbroker.gitlabVerificationStatus",
    "pactbroker.consumerLabels",
    "pactbroker.providerLabels",
    "pactbroker.eventName",
    "pactbroker.buildUrl",
    "pactbroker.currentlyDeployedProviderVersionNumber",
)

#: A header whose name matches holds a credential: sealed at rest, redacted wherever it is shown.
_SECRET_HEADER = re.compile(r"authorization|token|secret|api[-_]?key|cookie|password|signature", re.IGNORECASE)
#: RFC 9110 field-name.
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PARAMETER = re.compile(r"\$\{(pactbroker\.[A-Za-z]+)\}")
_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")

_MAX_URL = 2048
_MAX_HEADERS = 50
_MAX_HEADER_VALUE = 4096
_MAX_DESCRIPTION = 1000
_MAX_SECRET = 4096
_MIN_SIGNING_SECRET = 16
_MAX_BODY_BYTES = 64 * 1024

#: Headers the sender sets itself; a webhook may not override them.
_RESERVED_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "x-apiome-event",
        "x-apiome-delivery",
        SIGNATURE_HEADER.lower(),
    }
)

#: The ``client_payload`` of a GitHub dispatch that names none. GitHub accepts ten properties.
_GITHUB_DEFAULT_PAYLOAD: Dict[str, str] = {
    "eventName": "${pactbroker.eventName}",
    "pactUrl": "${pactbroker.pactUrl}",
    "consumerName": "${pactbroker.consumerName}",
    "consumerVersionNumber": "${pactbroker.consumerVersionNumber}",
    "consumerVersionBranch": "${pactbroker.consumerVersionBranch}",
    "providerName": "${pactbroker.providerName}",
    "providerVersionNumber": "${pactbroker.providerVersionNumber}",
    "providerVersionBranch": "${pactbroker.providerVersionBranch}",
    "verificationResultUrl": "${pactbroker.verificationResultUrl}",
    "githubVerificationStatus": "${pactbroker.githubVerificationStatus}",
}
_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"


def _invalid(pointer: str, message: str) -> PactPublicationError:
    """A ``pact-webhook-invalid`` refusal locating ``pointer`` in the request body."""
    return PactPublicationError(CODE_WEBHOOK_INVALID, f"{pointer or '(request body)'}: {message}", pointer=pointer)


def is_secret_header(name: str) -> bool:
    """Whether a header of this name holds a credential.

    Args:
        name: The header's field name.

    Returns:
        True for ``Authorization`` and any name mentioning a token, secret, API key, cookie,
        password or signature.
    """
    return bool(_SECRET_HEADER.search(name or ""))


def header_secret_field(name: str) -> str:
    """The ``secret_fields`` entry of a sealed header.

    Args:
        name: The header's field name.

    Returns:
        ``header:<name>``.
    """
    return f"{_SECRET_HEADER_PREFIX}{name}"


def validate_webhook_uuid(value: str) -> str:
    """Return a webhook ``uuid`` from a URL in canonical form, or refuse it.

    Args:
        value: The path segment.

    Returns:
        The lower-case UUID.

    Raises:
        PactPublicationError: ``pact-webhook-not-found`` — an id that is not a UUID names nothing.
    """
    text = (value or "").strip().lower()
    if not is_uuid_string(text):
        raise PactPublicationError(CODE_WEBHOOK_NOT_FOUND, f"no webhook '{value}' in this workspace")
    return text


# ---------------------------------------------------------------------------------------------
# The checked request
# ---------------------------------------------------------------------------------------------


class WebhookInput(BaseModel):
    """A checked webhook body, ready to store or to run.

    Attributes:
        description: What the webhook is for; shown in lists.
        consumer_name: Only pacts of this consumer, or ``None`` for any.
        provider_name: Only pacts of this provider, or ``None`` for any.
        enabled: Whether events fire it.
        events: The events it fires on, distinct, in the order given.
        target_kind: ``http`` or ``github_repository_dispatch``.
        target_config: The GitHub target as given, without its token; ``None`` for ``http``.
        method: ``POST``, ``PUT`` or ``PATCH``.
        url: The URL template.
        headers: Header templates that are not secret.
        body: The body template — a JSON value or a string — or ``None``.
        username: The basic-auth user, or ``None``.
        password: The basic-auth password; :data:`REDACTED` keeps the stored one.
        secret_headers: Secret header templates by name; a :data:`REDACTED` value keeps the stored one.
        signing_secret: The HMAC secret; :data:`REDACTED` keeps the stored one.
    """

    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = None
    consumer_name: Optional[str] = None
    provider_name: Optional[str] = None
    enabled: bool = True
    events: List[str] = Field(default_factory=lambda: [DEFAULT_EVENT])
    target_kind: str = TARGET_HTTP
    target_config: Optional[Dict[str, Any]] = None
    method: str
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Any = None
    username: Optional[str] = None
    password: Optional[str] = None
    secret_headers: Dict[str, str] = Field(default_factory=dict)
    signing_secret: Optional[str] = None

    def has_secrets(self) -> bool:
        """Whether storing this webhook needs the vault."""
        return bool(self.password or self.secret_headers or self.signing_secret)


class WebhookRecord(BaseModel):
    """A stored webhook as everyone reads it: no secret, only which ones are set.

    Attributes:
        id: The webhook's ``uuid``.
        description: What it is for.
        consumer_name: The consumer it is limited to, by name.
        consumer_slug: That consumer's handle.
        provider_name: The provider it is limited to, by name.
        provider_slug: That provider's handle.
        enabled: Whether events fire it.
        events: The events it fires on.
        target_kind: ``http`` or ``github_repository_dispatch``.
        target_config: The GitHub target, without its token.
        method: The request method.
        url: The URL template.
        headers: Header templates that are not secret.
        body: The body template.
        username: The basic-auth user.
        secret_fields: Which values are sealed: ``password``, ``signingSecret``, ``header:<Name>``.
        created_at: When it was created.
        updated_at: When it was last changed.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    description: Optional[str] = None
    consumer_name: Optional[str] = None
    consumer_slug: Optional[str] = None
    provider_name: Optional[str] = None
    provider_slug: Optional[str] = None
    enabled: bool = True
    events: List[str] = Field(default_factory=list)
    target_kind: str = TARGET_HTTP
    target_config: Optional[Dict[str, Any]] = None
    method: str = "POST"
    url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Any = None
    username: Optional[str] = None
    secret_fields: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def secret_header_names(self) -> List[str]:
        """The names of the sealed headers."""
        return [f[len(_SECRET_HEADER_PREFIX) :] for f in self.secret_fields if f.startswith(_SECRET_HEADER_PREFIX)]

    def shown_headers(self) -> Dict[str, str]:
        """The headers as a read shows them: secret ones as :data:`REDACTED`."""
        shown = dict(self.headers)
        shown.update({name: REDACTED for name in self.secret_header_names()})
        return shown


def request_description(method: str, url: str) -> str:
    """How a request is named in a list: ``POST api.github.com``.

    Args:
        method: The request method.
        url: The URL template.

    Returns:
        The method and the URL's host.
    """
    host = urlsplit(_PARAMETER.sub("placeholder", url or "")).hostname or ""
    return f"{(method or '').upper()} {host}".strip()


def scope_description(consumer_name: Optional[str], provider_name: Optional[str]) -> str:
    """Which pacts a webhook is for, in the Pact Broker's words.

    Args:
        consumer_name: The consumer it is limited to, if any.
        provider_name: The provider it is limited to, if any.

    Returns:
        The sentence a webhook list titles the webhook with.
    """
    if consumer_name and provider_name:
        return f"A webhook for the pact between {consumer_name} and {provider_name}"
    if provider_name:
        return f"A webhook for all pacts with provider {provider_name}"
    if consumer_name:
        return f"A webhook for all pacts with consumer {consumer_name}"
    return "A webhook for all pacts"


# ---------------------------------------------------------------------------------------------
# Reading a body
# ---------------------------------------------------------------------------------------------


def _text(value: Any, pointer: str, *, limit: int, required: bool = False) -> Optional[str]:
    """A trimmed single-line string of at most ``limit`` characters, or ``None`` when absent.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` for anything else.
    """
    if value is None:
        if required:
            raise _invalid(pointer, "is required")
        return None
    if not isinstance(value, str):
        raise _invalid(pointer, "must be a string")
    text = value.strip()
    if not text:
        if required:
            raise _invalid(pointer, "cannot be blank")
        return None
    if _CONTROL.search(text):
        raise _invalid(pointer, "must be a single line")
    if len(text) > limit:
        raise _invalid(pointer, f"must be at most {limit} characters")
    return text


def _pacticipant(value: Any, pointer: str) -> Optional[str]:
    """The ``name`` of a ``consumer`` or ``provider`` object, or ``None`` when it is absent.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` for a ``label`` (labels are not supported
            yet) or an object without a name.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid(pointer, "must be an object with a name")
    if value.get("label") is not None:
        raise _invalid(
            f"{pointer}/label",
            "choosing pacticipants by label is not supported yet; name the pacticipant or leave it out for all",
        )
    return _text(value.get("name"), f"{pointer}/name", limit=255, required=True)


def _events(value: Any) -> List[str]:
    """The ``events`` array as distinct event names; the default event when absent.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` locating an unknown event.
    """
    if value is None:
        return [DEFAULT_EVENT]
    if not isinstance(value, list) or not value:
        raise _invalid("/events", "must be an array with at least one event")
    names: List[str] = []
    for index, raw in enumerate(value):
        name = raw.get("name") if isinstance(raw, Mapping) else None
        if name not in EVENT_NAMES:
            raise _invalid(f"/events/{index}/name", f"must be one of {', '.join(EVENT_NAMES)}")
        if name not in names:
            names.append(name)
    return names


def check_url(url: Any, pointer: str, *, resolve: bool = True) -> str:
    """Vet a webhook URL template and return it.

    Template parameters may appear in the path and the query, never in the host. The URL passes
    the SSRF policy: http or https, no ``user:pass@``, and — when ``resolve`` — a host whose every
    address is public (unless ``APIOME_SSRF_ALLOW_PRIVATE`` is set).

    Args:
        url: The value sent.
        pointer: Where it is in the body.
        resolve: Whether to resolve the host. False re-checks only the shape.

    Returns:
        The URL template, trimmed.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` naming the rule that failed.
    """
    text = _text(url, pointer, limit=_MAX_URL, required=True) or ""
    if any(character.isspace() for character in text):
        raise _invalid(pointer, "must not contain whitespace")
    try:
        host = validate_url_policy(_PARAMETER.sub("placeholder", text))
        other = validate_url_policy(_PARAMETER.sub("otherplaceholder", text))
    except SSRFError as exc:
        raise _invalid(pointer, str(exc)) from exc
    if host != other:
        raise _invalid(pointer, "a template parameter cannot be used in the host of the URL")
    if resolve:
        try:
            validate_host(host)
        except SSRFError as exc:
            raise _invalid(pointer, f"{exc}; a webhook can only be sent to a public address") from exc
    return text


def _headers(value: Any, pointer: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Split a ``headers`` object into plain and secret header templates.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` locating the bad header.
    """
    if value is None:
        return {}, {}
    if not isinstance(value, Mapping):
        raise _invalid(pointer, "must be an object of header names and values")
    if len(value) > _MAX_HEADERS:
        raise _invalid(pointer, f"list at most {_MAX_HEADERS} headers")
    plain: Dict[str, str] = {}
    secret: Dict[str, str] = {}
    seen: set = set()
    for name, raw in value.items():
        at = f"{pointer}/{name}"
        if not isinstance(name, str) or not _HEADER_NAME.match(name):
            raise _invalid(at, "is not a valid header name")
        if name.lower() in _RESERVED_HEADERS:
            raise _invalid(at, "is set by Apiome and cannot be overridden")
        if name.lower() in seen:
            raise _invalid(at, "is listed twice")
        seen.add(name.lower())
        if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
            raise _invalid(at, "must be a string")
        text = str(raw)
        if _CONTROL.search(text) or len(text) > _MAX_HEADER_VALUE:
            raise _invalid(at, f"must be a single line of at most {_MAX_HEADER_VALUE} characters")
        (secret if is_secret_header(name) else plain)[name] = text
    return plain, secret


def _body(value: Any, pointer: str) -> Any:
    """The body template: any JSON value, within the size limit.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` over the limit.
    """
    if value is None:
        return None
    encoded = value if isinstance(value, str) else json.dumps(value)
    if len(encoded.encode("utf-8")) > _MAX_BODY_BYTES:
        raise _invalid(pointer, f"must be at most {_MAX_BODY_BYTES} bytes")
    if "\x00" in encoded or "\\u0000" in encoded:
        raise _invalid(pointer, "must not contain a NUL character")
    return value


def _secret(value: Any, pointer: str, *, minimum: int = 1) -> Optional[str]:
    """A secret value of ``minimum`` to 4,096 characters, or ``None`` when absent or empty.

    The message never repeats the value.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` for a value of the wrong type or length.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _invalid(pointer, "must be a string")
    if value == REDACTED:
        return REDACTED
    if _CONTROL.search(value) or not minimum <= len(value) <= _MAX_SECRET:
        raise _invalid(pointer, f"must be a single line of {minimum} to {_MAX_SECRET} characters")
    return value


def _github_request(target: Mapping[str, Any], *, resolve: bool) -> Dict[str, Any]:
    """Build the request of a GitHub Actions ``repository_dispatch`` target.

    Args:
        target: The ``target`` object: ``repository`` (``owner/name``), optional ``eventType``,
            ``clientPayload``, ``apiUrl`` (GitHub Enterprise Server) and ``token``.
        resolve: Whether to resolve the API host.

    Returns:
        The fields of :class:`WebhookInput` the target stands for.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` locating the bad field.
    """
    unknown = sorted(set(target) - {"type", "repository", "eventType", "clientPayload", "apiUrl", "token"})
    if unknown:
        raise _invalid(f"/target/{unknown[0]}", "is not a field of a github_repository_dispatch target")
    repository = _text(target.get("repository"), "/target/repository", limit=140, required=True) or ""
    if not _REPOSITORY.match(repository):
        raise _invalid("/target/repository", "must be a GitHub repository as owner/name")
    event_type = (
        _text(target.get("eventType"), "/target/eventType", limit=100) or "${pactbroker.eventName}"
    )
    payload = target.get("clientPayload")
    if payload is None:
        payload = dict(_GITHUB_DEFAULT_PAYLOAD)
    elif not isinstance(payload, Mapping):
        raise _invalid("/target/clientPayload", "must be an object")
    elif len(payload) > 10:
        raise _invalid("/target/clientPayload", "GitHub accepts at most 10 top-level properties")
    api_url = (_text(target.get("apiUrl"), "/target/apiUrl", limit=_MAX_URL) or _GITHUB_API).rstrip("/")
    if _PARAMETER.search(api_url):
        raise _invalid("/target/apiUrl", "cannot contain a template parameter")
    url = check_url(f"{api_url}/repos/{repository}/dispatches", "/target/apiUrl", resolve=resolve)
    token = _secret(target.get("token"), "/target/token")
    if token is None:
        raise _invalid("/target/token", "is required: a token that may dispatch events to the repository")
    config: Dict[str, Any] = {"repository": repository, "eventType": event_type}
    if target.get("clientPayload") is not None:
        config["clientPayload"] = dict(payload)
    if api_url != _GITHUB_API:
        config["apiUrl"] = api_url
    body = _body({"event_type": event_type, "client_payload": dict(payload)}, "/target/clientPayload")
    return {
        "target_kind": TARGET_GITHUB,
        "target_config": config,
        "method": "POST",
        "url": url,
        "headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": _GITHUB_API_VERSION},
        "body": body,
        "secret_headers": {"Authorization": REDACTED if token == REDACTED else f"Bearer {token}"},
    }


def _http_request(request: Any, *, resolve: bool) -> Dict[str, Any]:
    """Check a ``request`` object: method, URL, headers, body and basic-auth credentials.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` locating the bad field.
    """
    if not isinstance(request, Mapping):
        raise _invalid("/request", "is required: the HTTP request to send")
    method = (_text(request.get("method"), "/request/method", limit=16, required=True) or "").upper()
    if method not in METHODS:
        raise _invalid("/request/method", f"must be one of {', '.join(METHODS)}")
    plain, secret = _headers(request.get("headers"), "/request/headers")
    username = _text(request.get("username"), "/request/username", limit=256)
    password = _secret(request.get("password"), "/request/password")
    if password and not username:
        raise _invalid("/request/username", "is required when a password is given")
    if username and any(name.lower() == "authorization" for name in secret):
        raise _invalid("/request/headers/Authorization", "cannot be combined with a username and password")
    return {
        "target_kind": TARGET_HTTP,
        "target_config": None,
        "method": method,
        "url": check_url(request.get("url"), "/request/url", resolve=resolve),
        "headers": plain,
        "body": _body(request.get("body"), "/request/body"),
        "username": username,
        "password": password,
        "secret_headers": secret,
    }


def parse_webhook_request(raw: bytes, *, resolve: bool = True) -> WebhookInput:
    """Read and check a webhook body (``POST …/webhooks`` or ``PUT …/webhooks/{uuid}``).

    The Pact Broker's webhook: an optional ``description``, ``consumer`` and ``provider`` (each
    ``{"name": …}``), ``enabled`` (default true), ``events`` (default
    ``contract_content_changed``) and the ``request`` — ``method``, ``url``, ``headers``,
    ``body``, ``username``, ``password``. Apiome adds ``signingSecret`` (each delivery is then
    signed) and ``target`` — ``{"type": "github_repository_dispatch", …}`` — in place of
    ``request``. Fields the broker returns but does not take (``uuid``, ``createdAt``, ``_links``,
    ``signed``) are ignored, so a client may send back what it read; a secret sent back as
    ``**********`` keeps the stored value.

    Args:
        raw: The body.
        resolve: Whether to resolve the URL's host against the SSRF policy.

    Returns:
        The checked webhook.

    Raises:
        PactPublicationError: ``pact-webhook-invalid`` with a pointer to the bad field.
    """
    try:
        body = json.loads(raw) if raw and raw.strip() else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid("", f"the request body is not JSON: {exc}") from exc
    if not isinstance(body, Mapping):
        raise _invalid("", "must be a JSON object describing the webhook")

    enabled = body.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise _invalid("/enabled", "must be true or false")

    target = body.get("target")
    if target is not None and body.get("request") is not None:
        raise _invalid("/target", "send either request or target, not both")
    if target is not None:
        if not isinstance(target, Mapping) or target.get("type") not in (TARGET_GITHUB, TARGET_HTTP):
            raise _invalid("/target/type", f"must be {TARGET_GITHUB}")
        if target.get("type") == TARGET_HTTP:
            raise _invalid("/target/type", "for a plain HTTP webhook, send request instead of target")
        fields = _github_request(target, resolve=resolve)
    else:
        fields = _http_request(body.get("request"), resolve=resolve)

    return WebhookInput(
        description=_text(body.get("description"), "/description", limit=_MAX_DESCRIPTION),
        consumer_name=_pacticipant(body.get("consumer"), "/consumer"),
        provider_name=_pacticipant(body.get("provider"), "/provider"),
        enabled=True if enabled is None else enabled,
        events=_events(body.get("events")),
        signing_secret=_secret(body.get("signingSecret"), "/signingSecret", minimum=_MIN_SIGNING_SECRET),
        **fields,
    )


# ---------------------------------------------------------------------------------------------
# Template parameters and rendering
# ---------------------------------------------------------------------------------------------


def _status(success: Optional[bool], passed: str, failed: str, pending: str) -> str:
    """A CI status word for a verification outcome (``None``: not verified yet)."""
    if success is None:
        return pending
    return passed if success else failed


def template_parameters(
    *,
    event_name: str,
    consumer_name: str = "",
    provider_name: str = "",
    consumer_version_number: str = "",
    consumer_version_tags: Sequence[str] = (),
    consumer_version_branch: Optional[str] = None,
    pact_url: str = "",
    provider_version_number: str = "",
    provider_version_tags: Sequence[str] = (),
    provider_version_branch: Optional[str] = None,
    provider_version_descriptions: Sequence[str] = (),
    verification_result_url: str = "",
    verification_success: Optional[bool] = None,
    build_url: Optional[str] = None,
    consumer_labels: Sequence[str] = (),
    provider_labels: Sequence[str] = (),
    currently_deployed_provider_version_number: str = "",
) -> Dict[str, str]:
    """Build the value of every ``${pactbroker.*}`` parameter for one firing.

    The names and the formats are the Pact Broker's: lists are joined with ``", "``, an unknown
    value is the empty string, and the four CI status parameters are derived from the verification
    outcome (``pending`` / ``INPROGRESS`` when there is none yet).

    Args:
        event_name: The event that fired (``test`` for a test run).
        consumer_name: The consumer of the pact.
        provider_name: The provider of the pact.
        consumer_version_number: The consumer version that published the pact.
        consumer_version_tags: That version's tags.
        consumer_version_branch: That version's branch.
        pact_url: Where the pact can be fetched for verification.
        provider_version_number: The provider version that verified, or that must verify.
        provider_version_tags: That version's tags.
        provider_version_branch: That version's branch.
        provider_version_descriptions: Why that version must verify (``latest from main branch``,
            ``deployed in production`` …).
        verification_result_url: The verification result, when there is one.
        verification_success: Its outcome; ``None`` when the pact is not verified yet.
        build_url: The CI build of the version that caused the event.
        consumer_labels: The consumer's labels.
        provider_labels: The provider's labels.
        currently_deployed_provider_version_number: A provider version deployed now.

    Returns:
        A value for each of :data:`TEMPLATE_PARAMETERS`.
    """
    return {
        "pactbroker.consumerName": consumer_name or "",
        "pactbroker.providerName": provider_name or "",
        "pactbroker.consumerVersionNumber": consumer_version_number or "",
        "pactbroker.providerVersionNumber": provider_version_number or "",
        "pactbroker.providerVersionTags": ", ".join(provider_version_tags or ()),
        "pactbroker.providerVersionDescriptions": ", ".join(provider_version_descriptions or ()),
        "pactbroker.providerVersionBranch": provider_version_branch or "",
        "pactbroker.consumerVersionTags": ", ".join(consumer_version_tags or ()),
        "pactbroker.consumerVersionBranch": consumer_version_branch or "",
        "pactbroker.pactUrl": pact_url or "",
        "pactbroker.verificationResultUrl": verification_result_url or "",
        "pactbroker.githubVerificationStatus": _status(verification_success, "success", "failure", "pending"),
        "pactbroker.bitbucketVerificationStatus": _status(verification_success, "SUCCESSFUL", "FAILED", "INPROGRESS"),
        "pactbroker.azureDevOpsVerificationStatus": _status(verification_success, "succeeded", "failed", "pending"),
        "pactbroker.gitlabVerificationStatus": _status(verification_success, "success", "failed", "pending"),
        "pactbroker.consumerLabels": ", ".join(consumer_labels or ()),
        "pactbroker.providerLabels": ", ".join(provider_labels or ()),
        "pactbroker.eventName": event_name or "",
        "pactbroker.buildUrl": build_url or "",
        "pactbroker.currentlyDeployedProviderVersionNumber": currently_deployed_provider_version_number or "",
    }


def render_text(
    template: Optional[str],
    parameters: Mapping[str, str],
    escape: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """Substitute ``${pactbroker.*}`` parameters in a string.

    Args:
        template: The text; ``None`` stays ``None``.
        parameters: The values, from :func:`template_parameters`.
        escape: Applied to each substituted value (URL-encoding, for a URL).

    Returns:
        The text with every known parameter replaced. A ``${pactbroker.…}`` name that is not a
        parameter is left as written, as the Pact Broker leaves it.
    """
    if template is None:
        return None

    def replace(match: "re.Match[str]") -> str:
        value = parameters.get(match.group(1))
        if value is None:
            return match.group(0)
        return escape(str(value)) if escape else str(value)

    return _PARAMETER.sub(replace, template)


def _render_json(value: Any, parameters: Mapping[str, str]) -> Any:
    """Substitute parameters in every string of a JSON value, keys included."""
    if isinstance(value, str):
        return render_text(value, parameters)
    if isinstance(value, list):
        return [_render_json(item, parameters) for item in value]
    if isinstance(value, Mapping):
        return {render_text(str(key), parameters): _render_json(item, parameters) for key, item in value.items()}
    return value


class RenderedRequest(BaseModel):
    """One request ready to send.

    Attributes:
        method: The request method.
        url: The URL, parameters substituted and URL-encoded.
        headers: Every header to send, secret ones included.
        body: The body bytes, or ``None``.
        secrets: Every secret value in the request, for :func:`scrub`.
    """

    model_config = ConfigDict(extra="forbid")

    method: str
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[bytes] = None
    secrets: List[str] = Field(default_factory=list)


def _one_line(value: Optional[str]) -> str:
    """A header value with line breaks removed, so a parameter cannot add a header."""
    return _CONTROL.sub(" ", value or "").strip()


def render_request(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: Any,
    parameters: Mapping[str, str],
    username: Optional[str] = None,
    password: Optional[str] = None,
    secret_headers: Optional[Mapping[str, str]] = None,
) -> RenderedRequest:
    """Render a webhook's request for one firing.

    Parameters are substituted in the URL (URL-encoded), in every header value, in the basic-auth
    credentials and in the body. In a JSON body they are substituted inside each string, so a
    value containing a quote can not break the document. A JSON body is sent as
    ``application/json`` unless the webhook sets its own ``Content-Type``.

    Args:
        method: The request method.
        url: The URL template.
        headers: Header templates that are not secret.
        body: The body template: a JSON value, a string, or ``None``.
        parameters: The values, from :func:`template_parameters`.
        username: The basic-auth user.
        password: The basic-auth password, opened from the vault.
        secret_headers: Secret header templates, opened from the vault.

    Returns:
        The request, and the secret values it carries.
    """
    rendered: Dict[str, str] = {name: _one_line(render_text(value, parameters)) for name, value in headers.items()}
    secrets: List[str] = []
    for name, value in (secret_headers or {}).items():
        text = _one_line(render_text(value, parameters))
        rendered[name] = text
        secrets.append(text)
        # A scheme word is not the secret; the part after it is ("Bearer <token>").
        secrets.extend(part for part in text.split(" ")[1:] if len(part) >= 6)
    if username:
        user = render_text(username, parameters) or ""
        secret = render_text(password, parameters) or ""
        token = base64.b64encode(f"{user}:{secret}".encode("utf-8")).decode("ascii")
        rendered["Authorization"] = f"Basic {token}"
        secrets.append(token)
        if secret:
            secrets.append(secret)

    payload: Optional[bytes] = None
    if isinstance(body, str):
        payload = (render_text(body, parameters) or "").encode("utf-8")
    elif body is not None:
        payload = json.dumps(_render_json(body, parameters), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if not any(name.lower() == "content-type" for name in rendered):
            rendered["Content-Type"] = "application/json; charset=utf-8"

    return RenderedRequest(
        method=method.upper(),
        url=render_text(url, parameters, escape=quote_plus) or "",
        headers=rendered,
        body=payload,
        secrets=sorted({secret for secret in secrets if secret}, key=len, reverse=True),
    )


def scrub(text: Optional[str], secrets: Sequence[str]) -> Optional[str]:
    """Replace every occurrence of a secret value in ``text`` with :data:`REDACTED`.

    The last line of defence for anything written to a log or an error column: a receiver that
    echoes the ``Authorization`` header back in its response body does not get it stored.

    Args:
        text: The text; ``None`` stays ``None``.
        secrets: The secret values of the request (:attr:`RenderedRequest.secrets`).

    Returns:
        The text without them.
    """
    if text is None:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text
