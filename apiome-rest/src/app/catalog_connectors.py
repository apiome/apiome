"""Catalog connector rules — CDG-1.1 (#5952).

The pure half of the connector registry: the vocabulary, the request and response shapes, and
the checks every write passes before :mod:`app.catalog_connector_store` touches the database.
Nothing here reads the database; the base-URL check resolves DNS through an injectable
resolver so tests drive it with literals.

**Base URLs pass the SSRF rule.** A connector makes the server call a URL the tenant chose, so
:func:`check_connector_base_url` applies the same rules as import-from-URL (:mod:`app.ssrf_guard`):
http(s) only, no credentials in the URL, and every resolved address public. A private,
loopback or link-local address is refused with the stable reason ``private-address`` unless the
operator's allowlist (``APIOME_CONNECTOR_PRIVATE_NETWORK_ALLOWLIST``, CIDRs parsed like the
webhook IP allowlist's) contains every address the host resolves to. ``APIOME_SSRF_ALLOW_PRIVATE``
still disables the address filter for local development, as it does everywhere else.

**Secrets never travel in the clear.** ``scope`` is stored as plain JSON, so a key that looks
like a secret (``password``, ``token``, ``apiKey``, ...) is refused there; secrets go through
``PUT …/credentials``, which seals them and never returns them.

**Provenance.** :func:`connector_provenance_metadata` is the source descriptor a synced
revision carries in ``format_metadata``: ``inputKind: "connector"`` plus the connector id, the
remote id and the remote revision, which the catalog Provenance tab shows.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .repository_conflict_policy import DEFAULT_CONFLICT_POLICY, ConflictPolicy
from .repository_webhook_ip_allowlist import match_cidr, normalize_cidr
from .ssrf_guard import SSRFError, is_disallowed_address, validate_url_policy

_logger = logging.getLogger(__name__)

#: Connector kinds (mirror the V281 CHECK). Only kinds with a registered RefreshSource can sync.
KINDS: Tuple[str, ...] = (
    "kong-konnect",
    "kong-admin",
    "aws-apigateway",
    "azure-apim",
    "apigee",
    "url",
    "schema-registry",
    "mcp-registry",
)

#: Connector statuses (mirror the V281 CHECK).
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_FAILING = "failing"
STATUSES: Tuple[str, ...] = (STATUS_ACTIVE, STATUS_PAUSED, STATUS_FAILING)

#: Inventory item statuses (mirror the V281 CHECK).
ITEM_DISCOVERED = "discovered"
ITEM_IMPORTED = "imported"
ITEM_IGNORED = "ignored"
ITEM_MISSING = "missing"
ITEM_STATUSES: Tuple[str, ...] = (ITEM_DISCOVERED, ITEM_IMPORTED, ITEM_IGNORED, ITEM_MISSING)

#: Conflict policies: the RAR-4.5 values.
CONFLICT_POLICIES: Tuple[str, ...] = tuple(p.value for p in ConflictPolicy)

#: What started a run.
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"

#: The intake kind a synced revision records (``format_metadata.inputKind``).
INPUT_KIND_CONNECTOR = "connector"

#: Refusal codes (the routes map them to HTTP statuses).
CODE_INVALID = "connector-invalid"
CODE_NOT_FOUND = "connector-not-found"
CODE_NAME_TAKEN = "connector-name-taken"
CODE_BASE_URL_REFUSED = "connector-base-url-refused"
CODE_KIND_UNSUPPORTED = "connector-kind-unsupported"
CODE_SYNC_RUNNING = "connector-sync-running"
CODE_ENCRYPTION_UNCONFIGURED = "connector-encryption-unconfigured"

#: Stable reasons a base URL is refused (``detail.reason``).
REASON_MALFORMED = "malformed-url"
REASON_SCHEME = "scheme-not-allowed"
REASON_CREDENTIALS = "credentials-in-url"
REASON_NO_HOST = "missing-host"
REASON_UNRESOLVABLE = "host-unresolvable"
REASON_PRIVATE = "private-address"

NAME_MAX_CHARS = 200
BASE_URL_MAX_CHARS = 2048
SCOPE_MAX_BYTES = 16_384
CREDENTIAL_MAX_FIELDS = 16
CREDENTIAL_VALUE_MAX_CHARS = 4_096

#: Scope keys refused because they look like secrets (compared case- and separator-insensitively).
_SECRET_LIKE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "accesskey",
        "secretaccesskey",
        "clientsecret",
        "privatekey",
        "authorization",
        "bearer",
        "credentials",
    }
)

_VERSION_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_VERSION_LABEL_MAX = 64


class ConnectorError(ValueError):
    """A connector request was refused.

    Attributes:
        code: The stable refusal code (``CODE_*``).
        reason: A finer stable reason, when the code has several (base-URL refusals).
    """

    def __init__(self, code: str, message: str, *, reason: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason

    def as_detail(self) -> Dict[str, Any]:
        """The refusal as a response ``detail`` object."""
        detail: Dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.reason:
            detail["reason"] = self.reason
        return detail


# ---------------------------------------------------------------------------------------
# Request and response shapes
# ---------------------------------------------------------------------------------------


#: The ``scope`` field's description (create and update).
SCOPE_DESCRIPTION = (
    "Kind-specific coordinates; never secrets. `kong-konnect`: `{\"region\": \"us\"|\"eu\"|\"au\"|"
    "\"me\"|\"in\"|\"sg\", \"controlPlanes\": [\"<control plane id>\", …]}` (no control planes = "
    "every control plane the token can read). `kong-admin`: `{\"workspace\": \"…\", "
    "\"environment\": \"…\"}`, both optional. Kinds with a source check their scope on every write."
)


class ConnectorCreate(BaseModel):
    """``POST /v1/tenants/{t}/connectors``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal[
        "kong-konnect",
        "kong-admin",
        "aws-apigateway",
        "azure-apim",
        "apigee",
        "url",
        "schema-registry",
        "mcp-registry",
    ]
    name: str = Field(min_length=1, max_length=NAME_MAX_CHARS)
    base_url: Optional[str] = Field(default=None, alias="baseUrl", max_length=BASE_URL_MAX_CHARS)
    scope: Dict[str, Any] = Field(default_factory=dict, description=SCOPE_DESCRIPTION)
    refresh_interval_seconds: Optional[int] = Field(default=None, alias="refreshIntervalSeconds", gt=0)
    conflict_policy: Literal["overwrite", "hold-for-review", "new-branch"] = Field(
        default=DEFAULT_CONFLICT_POLICY.value, alias="conflictPolicy"
    )
    status: Literal["active", "paused"] = STATUS_ACTIVE


class ConnectorUpdate(BaseModel):
    """``PATCH /v1/tenants/{t}/connectors/{id}``. The kind cannot change."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX_CHARS)
    base_url: Optional[str] = Field(default=None, alias="baseUrl", max_length=BASE_URL_MAX_CHARS)
    scope: Optional[Dict[str, Any]] = Field(default=None, description=SCOPE_DESCRIPTION)
    refresh_interval_seconds: Optional[int] = Field(default=None, alias="refreshIntervalSeconds", gt=0)
    conflict_policy: Optional[Literal["overwrite", "hold-for-review", "new-branch"]] = Field(
        default=None, alias="conflictPolicy"
    )
    status: Optional[Literal["active", "paused"]] = None


class ConnectorCredentialsPut(BaseModel):
    """``PUT /v1/tenants/{t}/connectors/{id}/credentials``: replaces the whole credential."""

    model_config = ConfigDict(extra="forbid")

    credentials: Dict[str, SecretStr] = Field(
        description=(
            "The secret fields the connector's kind needs (for example `{\"token\": \"…\"}` or "
            "`{\"accessKeyId\": \"…\", \"secretAccessKey\": \"…\"}`). Sealed on arrival and never "
            "returned."
        )
    )


class ConnectorOut(BaseModel):
    """A connector, described. Never carries a credential."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    name: str
    base_url: Optional[str] = Field(default=None, serialization_alias="baseUrl")
    scope: Dict[str, Any] = Field(default_factory=dict)
    refresh_interval_seconds: Optional[int] = Field(default=None, serialization_alias="refreshIntervalSeconds")
    conflict_policy: str = Field(serialization_alias="conflictPolicy")
    status: str
    has_credentials: bool = Field(serialization_alias="hasCredentials")
    syncable: bool = Field(
        description="Whether this deployment has a source for the kind, so a sync can run.",
    )
    last_run_at: Optional[str] = Field(default=None, serialization_alias="lastRunAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    created_at: Optional[str] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[str] = Field(default=None, serialization_alias="updatedAt")


class ConnectorListResponse(BaseModel):
    """``GET /v1/tenants/{t}/connectors``."""

    connectors: List[ConnectorOut]
    kinds: List[str]
    syncable_kinds: List[str] = Field(serialization_alias="syncableKinds")


class ConnectorItemOut(BaseModel):
    """One remote API in a connector's inventory."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    remote_id: str = Field(serialization_alias="remoteId")
    remote_name: Optional[str] = Field(default=None, serialization_alias="remoteName")
    environment: Optional[str] = None
    hosts: List[str] = Field(default_factory=list)
    base_path: Optional[str] = Field(default=None, serialization_alias="basePath")
    remote_revision: Optional[str] = Field(default=None, serialization_alias="remoteRevision")
    remote_updated_at: Optional[str] = Field(default=None, serialization_alias="remoteUpdatedAt")
    imported_revision: Optional[str] = Field(default=None, serialization_alias="importedRevision")
    status: str
    project_id: Optional[str] = Field(default=None, serialization_alias="catalogItemId")
    first_seen_at: Optional[str] = Field(default=None, serialization_alias="firstSeenAt")
    last_seen_at: Optional[str] = Field(default=None, serialization_alias="lastSeenAt")
    deployment: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Where and how the provider serves this API, as the latest sync saw it. Kong "
            "connectors record `controlPlaneId`, `controlPlaneName`, `tags`, `enabled`, "
            "`protocols`, `hosts`, `paths`, `updatedAt` and `suggestedOwners` (from "
            "`owner:<team-slug>` tags; suggestions only, never confirmed owners)."
        ),
    )


class ConnectorItemPage(BaseModel):
    """``GET /v1/tenants/{t}/connectors/{id}/items``."""

    items: List[ConnectorItemOut]
    total: int
    limit: int
    offset: int


class ConnectorRunOut(BaseModel):
    """One sync run of a connector (a row of the shared refresh ledger)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    connector_id: str = Field(serialization_alias="connectorId")
    refresh_source: str = Field(serialization_alias="refreshSource")
    trigger: Optional[str] = None
    status: str
    error_class: Optional[str] = Field(default=None, serialization_alias="errorClass")
    http_status: Optional[int] = Field(default=None, serialization_alias="httpStatus")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    pull_count: int = Field(default=0, serialization_alias="pullCount")
    summary: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    started_at: Optional[str] = Field(default=None, serialization_alias="startedAt")
    finished_at: Optional[str] = Field(default=None, serialization_alias="finishedAt")


class ConnectorRunPage(BaseModel):
    """``GET /v1/tenants/{t}/connectors/{id}/runs``: newest first."""

    runs: List[ConnectorRunOut]
    total: int
    limit: int
    offset: int


class ConnectorCredentialsOut(BaseModel):
    """What ``PUT …/credentials`` returns: that a credential is stored, never what it is."""

    model_config = ConfigDict(populate_by_name=True)

    connector_id: str = Field(serialization_alias="connectorId")
    has_credentials: bool = Field(serialization_alias="hasCredentials")
    fields: List[str] = Field(description="The names of the stored fields, never their values.")
    replaced_at: Optional[str] = Field(default=None, serialization_alias="replacedAt")


# ---------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------


def _has_control_chars(value: str) -> bool:
    """True when ``value`` contains a C0/C1 control character."""
    return any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in value)


def validate_name(raw: str) -> str:
    """Return the trimmed connector name, or refuse a blank or control-character name.

    Raises:
        ConnectorError: ``connector-invalid``.
    """
    name = (raw or "").strip()
    if not name:
        raise ConnectorError(CODE_INVALID, "Connector name is required.")
    if len(name) > NAME_MAX_CHARS:
        raise ConnectorError(CODE_INVALID, f"Connector name is longer than {NAME_MAX_CHARS} characters.")
    if _has_control_chars(name):
        raise ConnectorError(CODE_INVALID, "Connector name contains control characters.")
    return name


def _secret_like(key: str) -> bool:
    """True when a scope key names a secret (``api_key``, ``clientSecret``, ...)."""
    folded = re.sub(r"[^a-z]", "", key.lower())
    return folded in _SECRET_LIKE_KEYS or folded.endswith("password") or folded.endswith("secret")


def _secret_like_paths(value: Any, path: str = "") -> List[str]:
    """Return the dotted paths of every secret-like key anywhere in ``value``."""
    found: List[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            here = f"{path}.{key}" if path else str(key)
            if _secret_like(str(key)):
                found.append(here)
            found.extend(_secret_like_paths(child, here))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_like_paths(child, f"{path}[{index}]"))
    return found


def validate_scope(scope: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return the scope as a plain dict, refusing an oversized or secret-bearing one.

    Raises:
        ConnectorError: ``connector-invalid`` when the scope is larger than
            :data:`SCOPE_MAX_BYTES` as JSON, or holds a key that looks like a secret.
    """
    value = dict(scope or {})
    encoded = json.dumps(value, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > SCOPE_MAX_BYTES:
        raise ConnectorError(CODE_INVALID, f"Connector scope is larger than {SCOPE_MAX_BYTES} bytes.")
    secret_paths = _secret_like_paths(value)
    if secret_paths:
        raise ConnectorError(
            CODE_INVALID,
            "Connector scope must not hold secrets; store them with PUT …/credentials. "
            f"Refused key(s): {', '.join(secret_paths)}.",
        )
    return value


def validate_credentials(credentials: Mapping[str, SecretStr]) -> Dict[str, str]:
    """Return the credential fields as plain strings, refusing an empty or oversized set.

    Raises:
        ConnectorError: ``connector-invalid``. The message names fields, never values.
    """
    if not credentials:
        raise ConnectorError(CODE_INVALID, "At least one credential field is required.")
    if len(credentials) > CREDENTIAL_MAX_FIELDS:
        raise ConnectorError(CODE_INVALID, f"At most {CREDENTIAL_MAX_FIELDS} credential fields are accepted.")
    plain: Dict[str, str] = {}
    for key, secret in credentials.items():
        name = str(key).strip()
        if not name or len(name) > 64 or _has_control_chars(name):
            raise ConnectorError(CODE_INVALID, "Credential field names must be 1–64 printable characters.")
        value = secret.get_secret_value() if isinstance(secret, SecretStr) else str(secret)
        if not value:
            raise ConnectorError(CODE_INVALID, f"Credential field {name!r} is empty.")
        if len(value) > CREDENTIAL_VALUE_MAX_CHARS:
            raise ConnectorError(
                CODE_INVALID,
                f"Credential field {name!r} is longer than {CREDENTIAL_VALUE_MAX_CHARS} characters.",
            )
        plain[name] = value
    return plain


def parse_private_network_allowlist(text: Optional[str]) -> Tuple[str, ...]:
    """Parse the operator's comma-separated CIDR allowlist.

    An entry that does not parse is logged and skipped, so one typo cannot widen or break the
    rest of the list.

    Args:
        text: ``APIOME_CONNECTOR_PRIVATE_NETWORK_ALLOWLIST``.

    Returns:
        The canonical CIDRs, in order.
    """
    cidrs: List[str] = []
    for part in (text or "").split(","):
        if not part.strip():
            continue
        try:
            cidrs.append(normalize_cidr(part)[0])
        except ValueError as exc:
            _logger.warning("connector private-network allowlist: skipping %r (%s)", part.strip(), exc)
    return tuple(cidrs)


def _default_resolver(host: str) -> List[str]:
    """Resolve ``host`` to every A/AAAA address (an IP literal resolves to itself)."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos if info[4] and info[4][0]]


def check_connector_base_url(
    raw: str,
    *,
    allowlist: Sequence[str] = (),
    allow_private: bool = False,
    resolver: Callable[[str], List[str]] = _default_resolver,
) -> str:
    """Return the trimmed base URL when the server may call it, or refuse it with a stable reason.

    Args:
        raw: The URL the tenant submitted.
        allowlist: CIDRs the operator allows private addresses in.
        allow_private: ``APIOME_SSRF_ALLOW_PRIVATE`` (local development): skip the address rule.
        resolver: Host → addresses; injectable for tests.

    Returns:
        The URL, trimmed.

    Raises:
        ConnectorError: ``connector-base-url-refused`` with reason ``malformed-url``,
            ``scheme-not-allowed``, ``credentials-in-url``, ``missing-host``,
            ``host-unresolvable`` or ``private-address``.
    """
    url = (raw or "").strip()
    if not url:
        raise ConnectorError(CODE_BASE_URL_REFUSED, "Base URL is empty.", reason=REASON_MALFORMED)
    try:
        host = validate_url_policy(url)
    except SSRFError as exc:
        message = str(exc)
        if "scheme" in message:
            reason = REASON_SCHEME
        elif "credentials" in message:
            reason = REASON_CREDENTIALS
        elif "missing a host" in message:
            reason = REASON_NO_HOST
        else:
            reason = REASON_MALFORMED
        raise ConnectorError(CODE_BASE_URL_REFUSED, f"Base URL refused: {message}.", reason=reason) from exc
    if allow_private:
        return url
    try:
        addresses = resolver(host)
    except (OSError, UnicodeError) as exc:
        raise ConnectorError(
            CODE_BASE_URL_REFUSED,
            f"Base URL refused: could not resolve host {host!r}.",
            reason=REASON_UNRESOLVABLE,
        ) from exc
    if not addresses:
        raise ConnectorError(
            CODE_BASE_URL_REFUSED,
            f"Base URL refused: could not resolve host {host!r}.",
            reason=REASON_UNRESOLVABLE,
        )
    for address in addresses:
        if not is_disallowed_address(address):
            continue
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            parsed = None
        if match_cidr(parsed, allowlist) is None:
            raise ConnectorError(
                CODE_BASE_URL_REFUSED,
                f"Base URL refused: host {host!r} resolves to a private or reserved address. "
                "An operator can allow it with APIOME_CONNECTOR_PRIVATE_NETWORK_ALLOWLIST.",
                reason=REASON_PRIVATE,
            )
    return url


def connector_base_url_from_settings(raw: str) -> str:
    """:func:`check_connector_base_url` under this deployment's settings."""
    from .config import settings

    return check_connector_base_url(
        raw,
        allowlist=parse_private_network_allowlist(settings.connector_private_network_allowlist),
        allow_private=bool(settings.ssrf_allow_private),
    )


def build_connector_http_client(**kwargs: Any) -> httpx.Client:
    """An httpx client for connector sources whose every request (and redirect) is re-checked.

    Sources must fetch through this rather than a bare client, so a provider that redirects to an
    internal address, or a host that re-resolves after the base URL was checked, is still refused.

    Args:
        **kwargs: Forwarded to ``httpx.Client`` (timeouts, base URL, headers).
    """

    def _guard(request: httpx.Request) -> None:
        try:
            connector_base_url_from_settings(str(request.url))
        except ConnectorError as exc:
            raise SSRFError(str(exc)) from exc

    event_hooks = dict(kwargs.pop("event_hooks", {}) or {})
    event_hooks["request"] = list(event_hooks.get("request", [])) + [_guard]
    kwargs.setdefault("trust_env", False)
    return httpx.Client(event_hooks=event_hooks, **kwargs)


# ---------------------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------------------


def revision_label(revision: Optional[str], *, now: Optional[datetime] = None) -> str:
    """The catalog revision label for one synced remote revision.

    A remote revision becomes the label (unsafe characters folded to ``-``, at most 64 chars);
    a remote that reports none gets a UTC timestamp label, so each sync that imports changed
    content lands as a new revision rather than overwriting the last one.

    Args:
        revision: The remote's revision marker, if any.
        now: Clock override for tests.

    Returns:
        The label.
    """
    text = _VERSION_LABEL_UNSAFE.sub("-", (revision or "").strip()).strip("-.")
    if text:
        return text[:_VERSION_LABEL_MAX]
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"sync-{stamp}"


def connector_provenance_metadata(
    connector: Mapping[str, Any],
    *,
    remote_id: str,
    remote_revision: Optional[str],
    remote_name: Optional[str] = None,
    source_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """The source descriptor a synced revision records in ``format_metadata``.

    Args:
        connector: The connector row (``id``, ``kind``, ``name``).
        remote_id: The remote API's id at the provider.
        remote_revision: The remote revision imported, if the provider reports one.
        remote_name: The remote API's display name.
        source_uri: A link to the document at the provider.

    Returns:
        ``{inputKind: "connector", connectorId, connectorKind, connectorName, remoteId,
        remoteRevision[, remoteName][, sourceUri]}``.
    """
    meta: Dict[str, Any] = {
        "inputKind": INPUT_KIND_CONNECTOR,
        "connectorId": str(connector["id"]),
        "connectorKind": connector.get("kind"),
        "connectorName": connector.get("name"),
        "remoteId": remote_id,
        "remoteRevision": remote_revision,
    }
    if remote_name:
        meta["remoteName"] = remote_name
    if source_uri:
        meta["sourceUri"] = source_uri
    return meta
