"""The upstream auth vault — AGX-2.2 (#4534).

Agents must never hold real API credentials. When an agent calls a tenant's API through a managed
MCP toolset, the AGX-2.1 invocation proxy (#4533) injects the tenant's upstream credential
server-side, so the agent only ever holds a scoped Apiome agent key. This module is that credential's
whole life: how it is validated, sealed, described without being revealed, rotated, removed, and
opened for one bound request.

**Sealed, never stored in the clear.** The secret lives in
``apiome.upstream_credentials.encrypted_secret`` as ciphertext only (V268), sealed by the shared
envelope cipher (:mod:`app.envelope_crypto`: AES-256-GCM with a per-secret data key wrapped by a
versioned master key from the environment). The vault has its own key map
(``APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS``) and its own magic (``OUCV``), so a blob can't be
moved into or out of the MCP or SDK-registry vaults even under a shared key.

**Write-only.** Create, rotate and delete accept a secret; nothing returns one. Every read is a
:class:`UpstreamCredentialOut`: the binding (toolset and server URL), the kind and placement, which
master key sealed it, whether it can currently be opened, and timestamps. There is deliberately no
digest of the secret either: a truncated hash of a basic-auth password is an offline guessing
oracle. The only function that opens a secret is :func:`resolve_injection`, and it hands the result
to the caller in memory, never to a route.

**Bound to a toolset and a server URL.** A credential is only opened for a request whose URL
:func:`~app.upstream_credential_binding.binds` to the credential's server URL, so it is only ever
sent to the host it was registered for.

**Rotation without downtime.** :func:`rotate_credential` seals the new secret first, then replaces
the stored one with a single ``UPDATE`` of the same row. A concurrent :func:`resolve_injection`
reads either the old row or the new one, never a gap. An invocation already in flight holds its
own opened copy and is not affected at all.

**Fails closed.** No configured master key means a credential can't be stored (a 503 naming the
variable to set) and a stored one can't be opened. A bound credential that won't open raises
:class:`UpstreamCredentialUnavailableError`; it never silently turns into an unauthenticated call.

**Use is audited as metadata only.** Every open writes one ``upstream_credential_uses`` row: which
credential, which toolset, when, and whether it opened. It records no secret and no request data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .config import settings
from .database import db
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError
from .upstream_credential_binding import (
    API_KEY_IN_HEADER,
    KIND_API_KEY,
    KIND_BASIC,
    KIND_BEARER,
    BindingError,
    CredentialInjection,
    binds,
    build_injection,
    normalize_server_url,
    validate_api_key_placement,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_CREDENTIAL_EXISTS",
    "CODE_CREDENTIAL_INVALID",
    "CODE_CREDENTIAL_NOT_FOUND",
    "SECRET_MAX_CHARS",
    "UPSTREAM_CREDENTIAL_SCHEMA_VERSION",
    "USE_OUTCOME_INJECTED",
    "USE_OUTCOME_UNAVAILABLE",
    "CredentialEncryptionError",
    "UpstreamCredentialCreate",
    "UpstreamCredentialError",
    "UpstreamCredentialOut",
    "UpstreamCredentialRotate",
    "UpstreamCredentialUnavailableError",
    "UpstreamSecretInput",
    "create_credential",
    "credential_encryption_configured",
    "delete_credential",
    "list_credentials",
    "record_use",
    "resolve_injection",
    "rotate_credential",
    "validate_secret",
    "validate_upstream_credential_keys",
]

#: The addressable shape of a credential's metadata projection.
UPSTREAM_CREDENTIAL_SCHEMA_VERSION = "agx.upstream-credential.v1"

#: Refusal codes (the route maps them to 422 / 409 / 404).
CODE_CREDENTIAL_INVALID = "upstream-credential-invalid"
CODE_CREDENTIAL_EXISTS = "upstream-credential-exists"
CODE_CREDENTIAL_NOT_FOUND = "upstream-credential-not-found"

#: Use outcomes recorded in ``upstream_credential_uses`` (mirror the V268 CHECK).
USE_OUTCOME_INJECTED = "injected"
USE_OUTCOME_UNAVAILABLE = "unavailable"

#: Longest accepted secret field. An API key, a token or a password past this is a pasted file,
#: and refusing it beats sealing a megabyte.
SECRET_MAX_CHARS = 4_096

#: Longest accepted basic-auth username.
_USERNAME_MAX_CHARS = 256

#: The secret fields each kind takes. Anything else is refused, so a value can't be stored in a
#: field that is never presented.
_SECRET_FIELDS: Dict[str, tuple] = {
    KIND_API_KEY: ("value",),
    KIND_BEARER: ("token",),
    KIND_BASIC: ("username", "password"),
}

#: The upstream vault. ``OUCV`` = *Apiome Upstream Credential Vault*.
_CIPHER = EnvelopeCipher(
    magic=b"OUCV",
    subject="upstream credential",
    keys_setting="APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS",
    read_keys=lambda: settings.upstream_credential_encryption_keys,
    read_active_version=lambda: settings.upstream_credential_active_key_version,
)

#: Re-exported so a caller handling a save needs one import for the errors it can raise.
CredentialEncryptionError = EnvelopeEncryptionError


class UpstreamCredentialError(ValueError):
    """A credential request was refused.

    Attributes:
        code: One of the ``CODE_*`` constants.
        errors: One message per problem, so a form can mark every bad field at once. No message
            ever quotes a secret.
    """

    def __init__(self, code: str, *errors: str) -> None:
        self.code = code
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid upstream credential")


class UpstreamCredentialUnavailableError(RuntimeError):
    """A credential is bound to the request but could not be opened.

    Its master key is not configured, or the stored blob fails authentication. The invocation
    must fail rather than go out without the credential. The message names the credential id,
    never material.

    Attributes:
        credential_id: The row that could not be opened.
    """

    def __init__(self, credential_id: str) -> None:
        self.credential_id = credential_id
        super().__init__(
            f"upstream credential {credential_id} cannot be opened on this deployment; "
            "check APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS or rotate the credential"
        )


# -------------------------------------------------------------------------------------------
# Request and response models
# -------------------------------------------------------------------------------------------


class UpstreamSecretInput(BaseModel):
    """The write-only secret material. Which fields apply depends on the credential's kind.

    Every field is a :class:`~pydantic.SecretStr`, so a model that ends up in a log line or a
    traceback prints ``**********`` instead of the value.

    Attributes:
        value: ``apiKey``: the key.
        token: ``bearer``: the token sent as ``Authorization: Bearer <token>``.
        username: ``basic``: the user-id (may not contain ``:``, per RFC 7617).
        password: ``basic``: the password (may be empty, for APIs that use the key as username).
    """

    model_config = ConfigDict(extra="forbid")

    value: Optional[SecretStr] = Field(default=None, description="`apiKey` only: the key.")
    token: Optional[SecretStr] = Field(default=None, description="`bearer` only: the token.")
    username: Optional[SecretStr] = Field(
        default=None, description="`basic` only: the user-id. May not contain `:`."
    )
    password: Optional[SecretStr] = Field(
        default=None, description="`basic` only: the password. May be empty."
    )


class UpstreamCredentialCreate(BaseModel):
    """Body for storing a new upstream credential.

    Attributes:
        server_url: The only upstream the credential will be sent to.
        kind: ``apiKey``, ``bearer`` or ``basic``.
        api_key_in: ``apiKey`` only: ``header`` or ``query``.
        api_key_name: ``apiKey`` only: the header or query-parameter name.
        secret: The secret material. Sealed on arrival and never returned.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    server_url: str = Field(
        alias="serverUrl",
        description=(
            "The upstream server this credential is bound to: an `https://` origin plus an "
            "optional base path, e.g. `https://api.example.com/v1`. The credential is only "
            "injected into requests under this URL."
        ),
    )
    kind: Literal["apiKey", "bearer", "basic"] = Field(
        description="How the secret is presented, in OpenAPI security-scheme terms."
    )
    api_key_in: Optional[Literal["header", "query"]] = Field(
        default=None,
        alias="in",
        description="`apiKey` only: send the key as a header or a query parameter.",
    )
    api_key_name: Optional[str] = Field(
        default=None,
        alias="name",
        description="`apiKey` only: the header or query-parameter name, e.g. `X-Api-Key`.",
    )
    secret: UpstreamSecretInput = Field(
        description=(
            "Write-only secret material: `{value}` for apiKey, `{token}` for bearer, "
            "`{username, password}` for basic. Stored encrypted; never returned by any route."
        )
    )


class UpstreamCredentialRotate(BaseModel):
    """Body for rotating a credential's secret in place.

    Attributes:
        secret: The replacement secret. Must have the fields the credential's kind needs.
    """

    model_config = ConfigDict(extra="forbid")

    secret: UpstreamSecretInput = Field(
        description="The replacement secret, in the same shape as at creation."
    )


class UpstreamCredentialOut(BaseModel):
    """A stored credential, described without being revealed.

    Attributes:
        schema_version: The projection's shape.
        id: The credential id.
        toolset_id: The agent toolset it serves.
        server_url: The only upstream it is sent to.
        kind: ``apiKey``, ``bearer`` or ``basic``.
        api_key_in: ``apiKey`` only: ``header`` or ``query``.
        api_key_name: ``apiKey`` only: the header or parameter name.
        key_version: Which master key sealed the secret.
        readable: Whether the secret can be opened with the keys configured now. ``False`` means
            the credential is present but unusable: every call through it would fail closed.
        created_at: When it was stored.
        created_by: Who stored it.
        rotated_at: When its secret was last replaced, or ``None``.
        rotated_by: Who last replaced it.
        last_used_at: When it was last injected into a request, or ``None``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=UPSTREAM_CREDENTIAL_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    id: str
    toolset_id: str = Field(serialization_alias="toolsetId")
    server_url: str = Field(serialization_alias="serverUrl")
    kind: str
    api_key_in: Optional[str] = Field(default=None, serialization_alias="in")
    api_key_name: Optional[str] = Field(default=None, serialization_alias="name")
    key_version: Optional[int] = Field(default=None, serialization_alias="keyVersion")
    readable: bool = True
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    rotated_at: Optional[datetime] = Field(default=None, serialization_alias="rotatedAt")
    rotated_by: Optional[str] = Field(default=None, serialization_alias="rotatedBy")
    last_used_at: Optional[datetime] = Field(default=None, serialization_alias="lastUsedAt")


# -------------------------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------------------------


def credential_encryption_configured() -> bool:
    """Return ``True`` when a master key is configured, so credentials can be stored."""
    return _CIPHER.configured()


def validate_upstream_credential_keys() -> None:
    """Validate the configured key map at startup.

    No keys configured is acceptable: the server starts and the create route refuses with a
    clear message. Keys that are *present but malformed* fail fast, so the misconfiguration
    surfaces at boot rather than at the first agent call.

    Raises:
        EnvelopeEncryptionError: If the key map is present but malformed, or the active version is
            absent from it.
    """
    _CIPHER.validate()


# -------------------------------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------------------------------


def _reveal(secret: Optional[SecretStr]) -> Optional[str]:
    """Return a :class:`SecretStr`'s value, or ``None`` when it is absent."""
    return secret.get_secret_value() if secret is not None else None


def _printable_ascii(value: str) -> bool:
    """Return ``True`` when every character of ``value`` is printable ASCII (0x20–0x7E)."""
    return all(0x20 <= ord(char) <= 0x7E for char in value)


def _control_chars(value: str) -> bool:
    """Return ``True`` when ``value`` contains a C0 control character or DEL.

    A newline in a header value is a request-splitting hazard, not a formatting quirk.
    """
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def validate_secret(
    kind: str, secret: UpstreamSecretInput, *, api_key_in: Optional[str] = None
) -> Dict[str, str]:
    """Check a secret has exactly the fields its kind needs, and return the payload to seal.

    Args:
        kind: ``apiKey``, ``bearer`` or ``basic``.
        secret: The submitted secret.
        api_key_in: For ``apiKey``: ``header`` or ``query``. A value sent as a header must be
            printable ASCII, like a bearer token, because HTTP clients encode header values as
            ASCII and a value that can't be sent is better refused now than at the first call.
            A query value is percent-encoded and a basic pair base64-encoded, so both may be
            any UTF-8.

    Returns:
        The plaintext payload: ``{"value"}``, ``{"token"}`` or ``{"username", "password"}``. A
        key or token is stripped of surrounding whitespace, since a pasted value routinely
        carries a trailing newline. A username or password is kept exactly as sent.

    Raises:
        UpstreamCredentialError: ``upstream-credential-invalid``, listing every problem. The
            messages name fields and limits, never values.
    """
    allowed = _SECRET_FIELDS[kind]
    submitted = {
        name: _reveal(getattr(secret, name))
        for name in ("value", "token", "username", "password")
        if getattr(secret, name) is not None
    }
    problems: List[str] = [
        f"secret.{name} does not apply to a {kind} credential"
        for name in submitted
        if name not in allowed
    ]

    payload: Dict[str, str] = {}
    for name in allowed:
        raw = submitted.get(name)
        if raw is None:
            problems.append(f"secret.{name} is required for a {kind} credential")
            continue
        value = raw.strip() if name in ("value", "token") else raw
        limit = _USERNAME_MAX_CHARS if name == "username" else SECRET_MAX_CHARS
        if not value and name != "password":
            problems.append(f"secret.{name} must not be empty")
        if len(value) > limit:
            problems.append(f"secret.{name} is longer than {limit:,} characters")
        if _control_chars(value):
            problems.append(f"secret.{name} contains control characters")
        if name == "token" and any(char.isspace() for char in value):
            problems.append("secret.token must not contain whitespace")
        sent_as_header = name == "token" or (name == "value" and api_key_in == API_KEY_IN_HEADER)
        if sent_as_header and not _printable_ascii(value):
            problems.append(f"secret.{name} must be printable ASCII to be sent in a header")
        if name == "username" and ":" in value:
            problems.append("secret.username must not contain ':' (RFC 7617)")
        payload[name] = value

    if problems:
        raise UpstreamCredentialError(CODE_CREDENTIAL_INVALID, *problems)
    return payload


def _validate_binding(body: UpstreamCredentialCreate) -> Dict[str, Optional[str]]:
    """Validate a create request's server URL and placement.

    Args:
        body: The create request.

    Returns:
        ``{"server_url", "api_key_in", "api_key_name"}``, normalized.

    Raises:
        UpstreamCredentialError: ``upstream-credential-invalid``, listing every problem.
    """
    problems: List[str] = []
    server_url: Optional[str] = None
    try:
        server_url = normalize_server_url(body.server_url)
    except BindingError as exc:
        problems.append(str(exc))

    api_key_in: Optional[str] = None
    api_key_name: Optional[str] = None
    if body.kind == KIND_API_KEY:
        try:
            api_key_in, api_key_name = validate_api_key_placement(
                body.api_key_in, body.api_key_name
            )
        except BindingError as exc:
            problems.append(str(exc))
    elif body.api_key_in is not None or body.api_key_name is not None:
        problems.append(
            f"`in` and `name` apply only to apiKey credentials; a {body.kind} credential is "
            "always sent as the Authorization header"
        )

    if problems:
        raise UpstreamCredentialError(CODE_CREDENTIAL_INVALID, *problems)
    return {"server_url": server_url, "api_key_in": api_key_in, "api_key_name": api_key_name}


# -------------------------------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------------------------------


def _text(value: Any) -> Optional[str]:
    """Return a value as a string, or ``None`` when it is empty."""
    return str(value) if value else None


def _out(row: Mapping[str, Any], *, readable: bool) -> UpstreamCredentialOut:
    """Project a stored row onto its metadata response.

    Args:
        row: The stored row. May include ``encrypted_secret``; it is never read here.
        readable: Whether the secret opens with the keys configured now.

    Returns:
        The response. The ciphertext and the plaintext are both absent by construction.
    """
    return UpstreamCredentialOut(
        id=str(row.get("id") or ""),
        toolset_id=str(row.get("toolset_id") or ""),
        server_url=str(row.get("server_url") or ""),
        kind=str(row.get("kind") or ""),
        api_key_in=row.get("api_key_in"),
        api_key_name=row.get("api_key_name"),
        key_version=row.get("key_version"),
        readable=readable,
        created_at=row.get("created_at"),
        created_by=_text(row.get("created_by")),
        rotated_at=row.get("rotated_at"),
        rotated_by=_text(row.get("rotated_by")),
        last_used_at=row.get("last_used_at"),
    )


def _opens(row: Mapping[str, Any]) -> bool:
    """Return whether a row's secret can be opened now. The plaintext is discarded at once."""
    return _CIPHER.unseal(row.get("encrypted_secret"), row.get("key_version")) is not None


def create_credential(
    tenant_id: str,
    toolset_id: str,
    body: UpstreamCredentialCreate,
    *,
    actor_id: Optional[str] = None,
) -> UpstreamCredentialOut:
    """Validate, seal and store a new credential for one toolset and server.

    Args:
        tenant_id: Owning tenant.
        toolset_id: The agent toolset it serves.
        body: The create request.
        actor_id: The user storing it.

    Returns:
        The stored credential's metadata.

    Raises:
        UpstreamCredentialError: ``upstream-credential-invalid`` when the server URL, placement
            or secret is not acceptable; ``upstream-credential-exists`` when this toolset
            already has a credential for that server (rotate it instead).
        EnvelopeEncryptionError: When encryption is not configured. Deliberately *not* caught: a
            secret that cannot be sealed must not be written, and the route turns this into a
            503 naming the variable to set.
        RuntimeError: When the write returned no row for a valid tenant.
    """
    problems: List[str] = []
    binding: Dict[str, Optional[str]] = {}
    payload: Dict[str, str] = {}
    try:
        binding = _validate_binding(body)
    except UpstreamCredentialError as exc:
        problems.extend(exc.errors)
    try:
        payload = validate_secret(body.kind, body.secret, api_key_in=body.api_key_in)
    except UpstreamCredentialError as exc:
        problems.extend(exc.errors)
    if problems:
        raise UpstreamCredentialError(CODE_CREDENTIAL_INVALID, *problems)

    encrypted, key_version = _CIPHER.seal(payload)
    row = db.insert_upstream_credential(
        tenant_id=tenant_id,
        toolset_id=toolset_id,
        server_url=binding["server_url"],
        kind=body.kind,
        api_key_in=binding["api_key_in"],
        api_key_name=binding["api_key_name"],
        encrypted_secret=encrypted,
        key_version=key_version,
        actor_id=actor_id,
    )
    if row is None:
        raise UpstreamCredentialError(
            CODE_CREDENTIAL_EXISTS,
            f"this toolset already has a credential for {binding['server_url']}; rotate it "
            "instead, or delete it first",
        )
    return _out(row, readable=True)


def rotate_credential(
    tenant_id: str,
    toolset_id: str,
    credential_id: str,
    body: UpstreamCredentialRotate,
    *,
    actor_id: Optional[str] = None,
) -> UpstreamCredentialOut:
    """Replace a credential's secret in place, atomically.

    The new secret is validated against the credential's stored kind and sealed *before* the
    store is touched; the swap is then one ``UPDATE`` of the same row. A concurrent resolve reads
    the old secret or the new one, never neither, and an invocation already holding the old
    secret finishes with it.

    Args:
        tenant_id: Owning tenant.
        toolset_id: The toolset the credential belongs to.
        credential_id: The credential to rotate.
        body: The replacement secret.
        actor_id: The user rotating it.

    Returns:
        The credential's metadata after the rotation.

    Raises:
        UpstreamCredentialError: ``upstream-credential-not-found`` when no such credential
            exists for this tenant and toolset; ``upstream-credential-invalid`` when the secret
            does not fit the credential's kind.
        EnvelopeEncryptionError: When encryption is not configured.
    """
    current = db.get_upstream_credential(tenant_id, toolset_id, credential_id)
    if current is None:
        raise UpstreamCredentialError(
            CODE_CREDENTIAL_NOT_FOUND, "no such upstream credential for this toolset"
        )
    payload = validate_secret(
        str(current.get("kind")), body.secret, api_key_in=current.get("api_key_in")
    )
    encrypted, key_version = _CIPHER.seal(payload)
    row = db.rotate_upstream_credential(
        tenant_id=tenant_id,
        toolset_id=toolset_id,
        credential_id=credential_id,
        encrypted_secret=encrypted,
        key_version=key_version,
        actor_id=actor_id,
    )
    if row is None:
        # Deleted between the read and the swap. Nothing was written.
        raise UpstreamCredentialError(
            CODE_CREDENTIAL_NOT_FOUND, "no such upstream credential for this toolset"
        )
    return _out(row, readable=True)


def delete_credential(
    tenant_id: str, toolset_id: str, credential_id: str
) -> Optional[UpstreamCredentialOut]:
    """Remove a credential. The toolset's next call to that server goes out without it.

    Args:
        tenant_id: Owning tenant.
        toolset_id: The toolset the credential belongs to.
        credential_id: The credential to remove.

    Returns:
        The removed credential's metadata (for the audit row), or ``None`` when nothing matched.
    """
    row = db.delete_upstream_credential(tenant_id, toolset_id, credential_id)
    return _out(row, readable=False) if row else None


def list_credentials(tenant_id: str, toolset_id: str) -> List[UpstreamCredentialOut]:
    """Describe a toolset's credentials: metadata only.

    Args:
        tenant_id: Owning tenant.
        toolset_id: The toolset.

    Returns:
        One entry per credential, ordered by server URL. Never raises: a store failure logs and
        returns an empty list, because this is a read of configuration.
    """
    try:
        rows = db.list_upstream_credentials(tenant_id, toolset_id)
    except Exception:  # noqa: BLE001 - listing configuration must not take a screen down
        logger.warning(
            "Could not list upstream credentials for tenant %s toolset %s",
            tenant_id,
            toolset_id,
            exc_info=True,
        )
        return []
    return [_out(row, readable=_opens(row)) for row in rows]


# -------------------------------------------------------------------------------------------
# Use (the AGX-2.1 invocation proxy's entry point)
# -------------------------------------------------------------------------------------------


def record_use(tenant_id: str, credential_id: str, toolset_id: str, outcome: str) -> None:
    """Append one metadata-only use record (best-effort).

    Records which credential, which toolset, when, and the outcome. A ledger failure is logged
    and swallowed: an invocation that succeeded must not fail because its audit row could not be
    appended.

    Args:
        tenant_id: Owning tenant.
        credential_id: The credential that was opened (or failed to open).
        toolset_id: The toolset it was opened for.
        outcome: :data:`USE_OUTCOME_INJECTED` or :data:`USE_OUTCOME_UNAVAILABLE`.
    """
    try:
        db.insert_upstream_credential_use(
            tenant_id=tenant_id,
            credential_id=credential_id,
            toolset_id=toolset_id,
            outcome=outcome,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning(
            "Failed to record upstream credential use (credential=%s toolset=%s outcome=%s)",
            credential_id,
            toolset_id,
            outcome,
            exc_info=True,
        )


def resolve_injection(
    tenant_id: str, toolset_id: str, request_url: str
) -> Optional[CredentialInjection]:
    """Open the credential bound to one outgoing request, for the invocation proxy.

    This is the only place a secret is opened for use. The proxy calls it with the absolute URL
    it is about to request; the credential whose server URL binds that URL (the most specific
    one, when base paths nest) is opened and returned as a :class:`CredentialInjection`, which
    the proxy applies with :meth:`CredentialInjection.apply`. Every open is audited as metadata.

    Args:
        tenant_id: Owning tenant.
        toolset_id: The toolset the invocation belongs to.
        request_url: The absolute upstream URL about to be called.

    Returns:
        The injection, or ``None`` when no credential of this toolset is bound to the URL. A
        toolset may legitimately call an upstream that needs no credential, and ``None`` never
        means "failed to open".

    Raises:
        UpstreamCredentialUnavailableError: A credential is bound to the URL but can't be opened
            (key not configured, blob fails authentication, or its payload doesn't fit its kind).
            The call must fail closed rather than go out without it.
    """
    rows = db.get_upstream_credential_bindings(tenant_id, toolset_id)
    bound = [row for row in rows if binds(str(row.get("server_url") or ""), request_url)]
    if not bound:
        return None
    row = max(bound, key=lambda candidate: len(str(candidate.get("server_url") or "")))
    credential_id = str(row.get("id"))

    payload = _CIPHER.unseal(row.get("encrypted_secret"), row.get("key_version"))
    injection: Optional[CredentialInjection] = None
    if payload is not None:
        try:
            injection = build_injection(
                credential_id=credential_id,
                kind=str(row.get("kind") or ""),
                api_key_in=row.get("api_key_in"),
                api_key_name=row.get("api_key_name"),
                secret=payload,
            )
        except BindingError:
            logger.warning(
                "Upstream credential %s opened but does not fit its kind; failing closed",
                credential_id,
            )
    if injection is None:
        record_use(tenant_id, credential_id, toolset_id, USE_OUTCOME_UNAVAILABLE)
        raise UpstreamCredentialUnavailableError(credential_id)

    record_use(tenant_id, credential_id, toolset_id, USE_OUTCOME_INJECTED)
    return injection
