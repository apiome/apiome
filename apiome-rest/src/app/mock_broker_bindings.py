"""Mock broker bindings and their credential vault — XPC-2.1 (#5735).

A version whose AsyncAPI channels should reach a real Kafka consumer is *bound* to a broker: the
hosted mock publishes there (XPC-2.2) and ``apiome verify`` consumes from there (XPC-2.3). This
module is a binding's whole life: how it is validated, sealed, described without being revealed,
rotated, removed, and opened for one connection.

**One binding per version and protocol.** ``kafka`` today; ``mqtt`` and ``amqp`` are reserved for
XPC-2.5 and refused until then.

**Address checked before anything is stored.** Every bootstrap host is normalized and resolved,
and the binding is refused ``broker-address-disallowed`` when any address is private or otherwise
non-public (:mod:`app.mock_broker_addresses`). The check runs again before every connect.

**The SASL credential is sealed, never stored in the clear.** It lives in
``apiome.mock_broker_bindings.credential_ciphertext`` as ciphertext only (V372), sealed by the
shared envelope cipher (:mod:`app.envelope_crypto`) under its own key map
(``APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS``) and its own magic (``OMBB``), so a blob can't be
moved into or out of another vault even under a shared key.

**Write-only.** Create and rotate accept a credential; nothing returns one. Every read is a
:class:`BrokerBindingOut`: the address, the TLS flags, the mechanism, which master key sealed the
credential, whether it currently opens, and timestamps. There is deliberately no digest of the
username or password either. The only function that opens a credential is :func:`open_credential`,
and it hands the result to the caller in memory, never to a route.

**Rotation without downtime.** :func:`rotate_binding` seals the new credential first, then replaces
the stored one with a single ``UPDATE`` of the same row.

**Fails closed.** No configured master key means a credential can't be stored (a 503 naming the
variable to set) and a stored one can't be opened.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .config import settings
from .database import db
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError
from .mock_broker_addresses import (
    BootstrapAddressError,
    BootstrapEntry,
    check_bootstrap,
    dev_broker_bootstrap,
    normalize_bootstrap,
    parse_entry,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BROKER_BINDING_SCHEMA_VERSION",
    "CODE_ADDRESS_DISALLOWED",
    "CODE_BINDING_EXISTS",
    "CODE_BINDING_INVALID",
    "CODE_BINDING_NOT_FOUND",
    "CODE_PROTOCOL_UNSUPPORTED",
    "PROTOCOL_KAFKA",
    "PROTOCOLS_RESERVED",
    "SASL_MECHANISMS",
    "BrokerBindingCreate",
    "BrokerBindingError",
    "BrokerBindingOut",
    "BrokerBindingRotate",
    "BrokerCredential",
    "BrokerCredentialInput",
    "BrokerTls",
    "broker_encryption_configured",
    "create_binding",
    "delete_binding",
    "describe_row",
    "get_binding",
    "list_bindings",
    "open_credential",
    "rotate_binding",
    "stored_bootstrap",
    "validate_broker_credential_keys",
]

#: The addressable shape of a binding's metadata projection.
BROKER_BINDING_SCHEMA_VERSION = "xpc.mock-broker-binding.v1"

#: Refusal codes (the route maps them to 422 / 409 / 404).
CODE_BINDING_INVALID = "broker-binding-invalid"
CODE_ADDRESS_DISALLOWED = "broker-address-disallowed"
CODE_PROTOCOL_UNSUPPORTED = "broker-protocol-unsupported"
CODE_BINDING_EXISTS = "broker-binding-exists"
CODE_BINDING_NOT_FOUND = "broker-binding-not-found"

#: The protocol a binding can be created for today.
PROTOCOL_KAFKA = "kafka"

#: Protocols the schema accepts but the API refuses until XPC-2.5 ships their adapters.
PROTOCOLS_RESERVED = ("mqtt", "amqp")

#: SASL mechanisms accepted (mirrors the V372 CHECK). GSSAPI and OAUTHBEARER need more than a
#: username and password, so they are not offered.
SASL_MECHANISMS = ("PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512")

#: Longest accepted username or password. Past this it is a pasted file, not a credential.
_CREDENTIAL_MAX_CHARS = 1_024

#: The broker vault. ``OMBB`` = *apiome Mock Broker Binding*.
_CIPHER = EnvelopeCipher(
    magic=b"OMBB",
    subject="broker credential",
    keys_setting="APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS",
    read_keys=lambda: settings.broker_credential_encryption_keys,
    read_active_version=lambda: settings.broker_credential_active_key_version,
)


class BrokerBindingError(ValueError):
    """A binding request was refused.

    Attributes:
        code: One of the ``CODE_*`` constants.
        errors: One message per problem, so a form can mark every bad field at once. No message
            ever quotes a credential.
    """

    def __init__(self, code: str, *errors: str) -> None:
        self.code = code
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid broker binding")


@dataclass(frozen=True)
class BrokerCredential:
    """An opened SASL credential, held in memory only for one connection.

    ``repr`` never shows the password, so it can't leak through a log line or a traceback.

    Attributes:
        username: The SASL username.
        password: The SASL password.
    """

    username: str
    password: str

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "BrokerCredential(username=***, password=***)"


# -------------------------------------------------------------------------------------------
# Request and response models
# -------------------------------------------------------------------------------------------


class BrokerCredentialInput(BaseModel):
    """The write-only SASL credential.

    Both fields are :class:`~pydantic.SecretStr`, so a model that ends up in a log line prints
    ``**********`` instead of the value.

    Attributes:
        username: The SASL username.
        password: The SASL password.
    """

    model_config = ConfigDict(extra="forbid")

    username: SecretStr = Field(description="The SASL username.")
    password: SecretStr = Field(description="The SASL password.")


class BrokerTls(BaseModel):
    """How the broker connection is secured.

    Attributes:
        enabled: Connect over TLS (``SSL`` / ``SASL_SSL``).
        verify: Verify the broker's certificate and hostname. Only turn off for a self-signed
            test cluster.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Connect over TLS.")
    verify: bool = Field(
        default=True, description="Verify the broker certificate and hostname (TLS only)."
    )


class BrokerBindingCreate(BaseModel):
    """Body for binding a version's mock to a broker.

    Attributes:
        protocol: ``kafka``. ``mqtt`` / ``amqp`` are reserved (XPC-2.5) and refused.
        bootstrap: The broker's ``host:port`` entries, as a list or a comma-separated string.
        tls: TLS flags.
        sasl_mechanism: ``PLAIN``, ``SCRAM-SHA-256`` or ``SCRAM-SHA-512``; omit for no SASL.
        credential: The SASL credential; required exactly when a mechanism is given.
        client_id_prefix: The Kafka ``client.id`` prefix Apiome's connections present.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol: Literal["kafka", "mqtt", "amqp"] = Field(
        default=PROTOCOL_KAFKA,
        description="`kafka`. `mqtt` and `amqp` are reserved for a later release and refused.",
    )
    bootstrap: Union[List[str], str] = Field(
        description=(
            "The broker's bootstrap servers: `host:port` entries (port defaults to 9092), as a "
            "list or a comma-separated string. Every host must resolve to a public address."
        )
    )
    tls: BrokerTls = Field(default_factory=BrokerTls, description="TLS flags.")
    sasl_mechanism: Optional[Literal["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"]] = Field(
        default=None,
        alias="saslMechanism",
        description="The SASL mechanism, or omit it for a broker without authentication.",
    )
    credential: Optional[BrokerCredentialInput] = Field(
        default=None,
        description=(
            "Write-only SASL `{username, password}`; required with `saslMechanism`. Stored "
            "encrypted; never returned by any route."
        ),
    )
    client_id_prefix: str = Field(
        default="apiome-mock",
        alias="clientIdPrefix",
        description="The Kafka `client.id` prefix: 1–64 of `A-Z a-z 0-9 . _ -`.",
    )


class BrokerBindingRotate(BaseModel):
    """Body for replacing a binding's SASL credential in place.

    Attributes:
        credential: The replacement credential.
    """

    model_config = ConfigDict(extra="forbid")

    credential: BrokerCredentialInput = Field(
        description="The replacement `{username, password}`, in the same shape as at creation."
    )


class BrokerBindingOut(BaseModel):
    """A stored binding, described without revealing its credential.

    Attributes:
        schema_version: The projection's shape.
        id: The binding id.
        version_id: The version it belongs to.
        protocol: ``kafka``.
        bootstrap: The normalized ``host:port`` entries.
        dev_broker: Whether the binding points at the configured dev broker.
        tls: TLS flags.
        sasl_mechanism: The SASL mechanism, or ``None``.
        has_credential: Whether a SASL credential is stored.
        key_version: Which master key sealed the credential, or ``None``.
        readable: Whether the credential can be opened with the keys configured now (``True``
            when there is none to open). ``False`` means every connection would fail closed.
        client_id_prefix: The ``client.id`` prefix.
        created_at: When it was stored.
        created_by: Who stored it.
        rotated_at: When its credential was last replaced, or ``None``.
        rotated_by: Who last replaced it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=BROKER_BINDING_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    id: str
    version_id: str = Field(serialization_alias="versionId")
    protocol: str
    bootstrap: List[str]
    dev_broker: bool = Field(default=False, serialization_alias="devBroker")
    tls: BrokerTls
    sasl_mechanism: Optional[str] = Field(default=None, serialization_alias="saslMechanism")
    has_credential: bool = Field(default=False, serialization_alias="hasCredential")
    key_version: Optional[int] = Field(default=None, serialization_alias="keyVersion")
    readable: bool = True
    client_id_prefix: str = Field(serialization_alias="clientIdPrefix")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    rotated_at: Optional[datetime] = Field(default=None, serialization_alias="rotatedAt")
    rotated_by: Optional[str] = Field(default=None, serialization_alias="rotatedBy")


# -------------------------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------------------------


def broker_encryption_configured() -> bool:
    """Return ``True`` when a master key is configured, so a SASL credential can be stored."""
    return _CIPHER.configured()


def validate_broker_credential_keys() -> None:
    """Validate the configured key map at startup.

    No keys is acceptable (bindings without SASL still work; storing a credential is refused).
    Keys that are present but malformed fail fast, so the misconfiguration surfaces at boot.

    Raises:
        EnvelopeEncryptionError: If the key map is present but malformed.
    """
    _CIPHER.validate()


# -------------------------------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------------------------------


def _client_id_prefix_ok(value: str) -> bool:
    """Return ``True`` when ``value`` matches the V372 ``client_id_prefix`` CHECK."""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    return 1 <= len(value) <= 64 and set(value) <= allowed


def _validate_credential(credential: BrokerCredentialInput) -> Dict[str, str]:
    """Check a SASL credential and return the payload to seal.

    Args:
        credential: The submitted credential.

    Returns:
        ``{"username", "password"}``, the username stripped of surrounding whitespace (a pasted
        value routinely carries a trailing newline) and the password kept exactly as sent.

    Raises:
        BrokerBindingError: ``broker-binding-invalid``, naming fields and limits, never values.
    """
    username = credential.username.get_secret_value().strip()
    password = credential.password.get_secret_value()
    problems: List[str] = []
    if not username:
        problems.append("credential.username must not be empty")
    if not password:
        problems.append("credential.password must not be empty")
    for name, value in (("username", username), ("password", password)):
        if len(value) > _CREDENTIAL_MAX_CHARS:
            problems.append(f"credential.{name} is longer than {_CREDENTIAL_MAX_CHARS:,} characters")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            problems.append(f"credential.{name} contains control characters")
    if problems:
        raise BrokerBindingError(CODE_BINDING_INVALID, *problems)
    return {"username": username, "password": password}


def _bootstrap_list(value: Union[List[str], str]) -> List[str]:
    """Return the submitted bootstrap as a list of raw entries."""
    return [value] if isinstance(value, str) else list(value)


def _validate_create(body: BrokerBindingCreate) -> Dict[str, Any]:
    """Validate a create request's shape and address, collecting every problem.

    Args:
        body: The create request.

    Returns:
        ``{"bootstrap": [...], "payload": {...} | None}``: the normalized, SSRF-checked entries
        and the credential payload to seal (``None`` without SASL).

    Raises:
        BrokerBindingError: ``broker-protocol-unsupported`` for a reserved protocol;
            ``broker-address-disallowed`` when a host is non-public or does not resolve;
            ``broker-binding-invalid`` for anything else.
    """
    if body.protocol != PROTOCOL_KAFKA:
        raise BrokerBindingError(
            CODE_PROTOCOL_UNSUPPORTED,
            f"protocol '{body.protocol}' is reserved and not served on this deployment yet; "
            "use kafka",
        )

    problems: List[str] = []
    entries: List[BootstrapEntry] = []
    try:
        entries = normalize_bootstrap(_bootstrap_list(body.bootstrap))
    except BootstrapAddressError as exc:
        problems.extend(exc.errors)

    payload: Optional[Dict[str, str]] = None
    if body.sasl_mechanism and body.credential is None:
        problems.append(f"credential is required with saslMechanism {body.sasl_mechanism}")
    elif body.credential is not None and not body.sasl_mechanism:
        problems.append("credential applies only with a saslMechanism")
    elif body.credential is not None:
        try:
            payload = _validate_credential(body.credential)
        except BrokerBindingError as exc:
            problems.extend(exc.errors)

    if not body.tls.enabled and not body.tls.verify:
        problems.append("tls.verify applies only when tls.enabled is true")
    if not _client_id_prefix_ok(body.client_id_prefix):
        problems.append("clientIdPrefix must be 1–64 of A-Z a-z 0-9 . _ -")
    if problems:
        raise BrokerBindingError(CODE_BINDING_INVALID, *problems)

    # The address rule runs last, on a list known to be well-formed, so a malformed request is
    # never answered with a DNS lookup.
    try:
        check_bootstrap(entries)
    except BootstrapAddressError as exc:
        raise BrokerBindingError(CODE_ADDRESS_DISALLOWED, *exc.errors) from exc
    return {"bootstrap": [entry.render() for entry in entries], "payload": payload}


# -------------------------------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------------------------------


def _text(value: Any) -> Optional[str]:
    """Return a value as a string, or ``None`` when it is empty."""
    return str(value) if value else None


def stored_bootstrap(row: Mapping[str, Any]) -> List[BootstrapEntry]:
    """Parse a stored row's bootstrap back into entries (they were normalized on the way in).

    Args:
        row: A stored binding row.

    Returns:
        The entries. A stored entry that no longer parses is dropped and logged.
    """
    entries: List[BootstrapEntry] = []
    for raw in row.get("bootstrap") or []:
        try:
            entries.append(parse_entry(str(raw)))
        except BootstrapAddressError:
            logger.warning("Skipping malformed stored bootstrap entry on binding %s", row.get("id"))
    return entries


def _out(row: Mapping[str, Any], *, readable: bool) -> BrokerBindingOut:
    """Project a stored row onto its metadata response.

    Args:
        row: The stored row. May include ``credential_ciphertext``; it is never read here.
        readable: Whether the credential opens with the keys configured now.

    Returns:
        The response. The ciphertext and the plaintext are both absent by construction.
    """
    bootstrap = [str(entry) for entry in row.get("bootstrap") or []]
    dev = {entry.render() for entry in dev_broker_bootstrap()}
    return BrokerBindingOut(
        id=str(row.get("id") or ""),
        version_id=str(row.get("version_id") or ""),
        protocol=str(row.get("protocol") or ""),
        bootstrap=bootstrap,
        dev_broker=bool(bootstrap) and set(bootstrap) <= dev,
        tls=BrokerTls(
            enabled=bool(row.get("tls_enabled")), verify=bool(row.get("tls_verify", True))
        ),
        sasl_mechanism=row.get("sasl_mechanism"),
        has_credential=row.get("key_version") is not None,
        key_version=row.get("key_version"),
        readable=readable,
        client_id_prefix=str(row.get("client_id_prefix") or ""),
        created_at=row.get("created_at"),
        created_by=_text(row.get("created_by")),
        rotated_at=row.get("rotated_at"),
        rotated_by=_text(row.get("rotated_by")),
    )


def _opens(row: Mapping[str, Any]) -> bool:
    """Return whether a row's credential opens now (``True`` when it has none)."""
    if row.get("key_version") is None:
        return True
    return _CIPHER.unseal(row.get("credential_ciphertext"), row.get("key_version")) is not None


def create_binding(
    tenant_id: str,
    version_id: str,
    body: BrokerBindingCreate,
    *,
    actor_id: Optional[str] = None,
) -> BrokerBindingOut:
    """Validate, seal and store a new binding for one version.

    Args:
        tenant_id: Owning tenant.
        version_id: The version (already checked to exist in the tenant).
        body: The create request.
        actor_id: The user storing it.

    Returns:
        The stored binding's metadata.

    Raises:
        BrokerBindingError: see :func:`_validate_create`; ``broker-binding-exists`` when the
            version already has a binding for that protocol.
        EnvelopeEncryptionError: When a credential was given and encryption is not configured.
            Deliberately not caught: a credential that cannot be sealed must not be written.
    """
    validated = _validate_create(body)
    payload = validated["payload"]
    ciphertext: Optional[bytes] = None
    key_version: Optional[int] = None
    if payload is not None:
        ciphertext, key_version = _CIPHER.seal(payload)
    row = db.insert_mock_broker_binding(
        tenant_id=tenant_id,
        version_id=version_id,
        protocol=body.protocol,
        bootstrap=validated["bootstrap"],
        tls_enabled=body.tls.enabled,
        tls_verify=body.tls.verify,
        sasl_mechanism=body.sasl_mechanism,
        credential_ciphertext=ciphertext,
        key_version=key_version,
        client_id_prefix=body.client_id_prefix,
        actor_id=actor_id,
    )
    if row is None:
        raise BrokerBindingError(
            CODE_BINDING_EXISTS,
            f"this version already has a {body.protocol} broker binding; delete it first",
        )
    return _out(row, readable=True)


def rotate_binding(
    tenant_id: str,
    version_id: str,
    binding_id: str,
    body: BrokerBindingRotate,
    *,
    actor_id: Optional[str] = None,
) -> BrokerBindingOut:
    """Replace a binding's SASL credential in place, atomically.

    Args:
        tenant_id: Owning tenant.
        version_id: The version the binding belongs to.
        binding_id: The binding.
        body: The replacement credential.
        actor_id: The user rotating it.

    Returns:
        The binding's metadata after the rotation.

    Raises:
        BrokerBindingError: ``broker-binding-not-found``; ``broker-binding-invalid`` when the
            binding has no SASL mechanism or the credential is not acceptable.
        EnvelopeEncryptionError: When encryption is not configured.
    """
    current = db.get_mock_broker_binding(tenant_id, version_id, binding_id)
    if current is None:
        raise BrokerBindingError(CODE_BINDING_NOT_FOUND, "no such broker binding for this version")
    if not current.get("sasl_mechanism"):
        raise BrokerBindingError(
            CODE_BINDING_INVALID,
            "this binding has no SASL mechanism, so it has no credential to rotate",
        )
    payload = _validate_credential(body.credential)
    ciphertext, key_version = _CIPHER.seal(payload)
    row = db.rotate_mock_broker_binding(
        tenant_id=tenant_id,
        version_id=version_id,
        binding_id=binding_id,
        credential_ciphertext=ciphertext,
        key_version=key_version,
        actor_id=actor_id,
    )
    if row is None:
        # Deleted between the read and the swap. Nothing was written.
        raise BrokerBindingError(CODE_BINDING_NOT_FOUND, "no such broker binding for this version")
    return _out(row, readable=True)


def delete_binding(tenant_id: str, version_id: str, binding_id: str) -> Optional[BrokerBindingOut]:
    """Remove a binding. The version's events go back to WebSocket/SSE only.

    Args:
        tenant_id: Owning tenant.
        version_id: The version the binding belongs to.
        binding_id: The binding.

    Returns:
        The removed binding's metadata (for the audit row), or ``None`` when nothing matched.
    """
    row = db.delete_mock_broker_binding(tenant_id, version_id, binding_id)
    return _out(row, readable=False) if row else None


def get_binding(tenant_id: str, version_id: str, binding_id: str) -> Optional[Dict[str, Any]]:
    """Return one stored binding row, *with* its ciphertext, for the probe to open.

    Never project the result into a response; use :func:`describe_row` for that.

    Args:
        tenant_id: Owning tenant.
        version_id: The version.
        binding_id: The binding.

    Returns:
        The row, or ``None``.
    """
    return db.get_mock_broker_binding(tenant_id, version_id, binding_id, with_credential=True)


def describe_row(row: Mapping[str, Any]) -> BrokerBindingOut:
    """Describe a stored row (metadata only), reporting whether its credential opens."""
    return _out(row, readable=_opens(row))


def list_bindings(tenant_id: str, version_id: str) -> List[BrokerBindingOut]:
    """Describe a version's bindings: metadata only.

    Args:
        tenant_id: Owning tenant.
        version_id: The version.

    Returns:
        One entry per binding, by protocol. Never raises: a store failure logs and returns an
        empty list, because this is a read of configuration.
    """
    try:
        rows = db.list_mock_broker_bindings(tenant_id, version_id)
    except Exception:  # noqa: BLE001 - listing configuration must not take a screen down
        logger.warning(
            "Could not list broker bindings for tenant %s version %s",
            tenant_id,
            version_id,
            exc_info=True,
        )
        return []
    return [describe_row(row) for row in rows]


def open_credential(row: Mapping[str, Any]) -> Optional[BrokerCredential]:
    """Open a binding row's SASL credential for one connection.

    Args:
        row: A row from :func:`get_binding` (with ``credential_ciphertext``).

    Returns:
        The credential, or ``None`` when the row has none *or* it cannot be opened. The caller
        tells the two apart by ``row["sasl_mechanism"]`` and fails closed on the second.
    """
    if row.get("key_version") is None:
        return None
    payload = _CIPHER.unseal(row.get("credential_ciphertext"), row.get("key_version"))
    if not isinstance(payload, Mapping):
        return None
    username, password = payload.get("username"), payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        logger.warning("Broker credential on binding %s does not fit its shape", row.get("id"))
        return None
    return BrokerCredential(username=username, password=password)


# Re-exported so a caller handling a save needs one import for the errors it can raise.
CredentialEncryptionError = EnvelopeEncryptionError
