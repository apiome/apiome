"""Tenant package-registry credentials — SDK-4.1 (#4495).

Publishing to npm or PyPI on a tenant's behalf means holding a token that can publish *as* them.
This module is the whole life of that token: what a valid one looks like, how it is sealed before
it is written, how it is described without being revealed, and how the one in force for a publish
is chosen.

**Sealed, never stored in the clear.** The token lives in
``apiome.sdk_registry_credentials.encrypted_token`` as ciphertext only (V256), sealed by the
shared envelope cipher (:mod:`app.envelope_crypto`) under its own master-key map. Separate keys
from the MCP vault on purpose: a publish token and an outbound MCP token are different blast
radii, and the SDK vault's own magic means a blob cannot be moved between the two even under a
shared key.

**Described, never echoed.** Every read path returns *metadata* — the ecosystem, the registry, the
scheme prefix the token declares (``npm_``, ``pypi-``), its length, and a truncated digest — and
never the token. The digest is what lets an operator confirm "the token I rotated is the token
that is stored" without the API ever handing one back. There is deliberately no reveal route: a
credential is write-only, exactly like a webhook signing secret.

**Two scopes, whole-row override.** A credential is tenant-wide (``project_id IS NULL``) or
belongs to one project. Unlike SDK-3.4's settings — which merge key by key — a project override
replaces the tenant credential entirely, because a token is atomic: half of one tenant's token and
half of another's is not a credential. That is the "scoped per project where supported" of the
ticket, and it is what lets one workspace publish most projects under a shared org token while a
single project uses its own.

**Fails closed.** No configured master key means a credential cannot be stored (a clear refusal at
write time, not a silent plaintext write) and a stored one cannot be opened (the publish fails
rather than proceeding unauthenticated).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .config import settings
from .database import db
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError
from .sdk_publish_version import NPM_ECOSYSTEM, PUBLISH_ECOSYSTEMS, PYPI_ECOSYSTEM

logger = logging.getLogger(__name__)

__all__ = [
    "CREDENTIAL_SCOPE_PROJECT",
    "CREDENTIAL_SCOPE_TENANT",
    "DEFAULT_REGISTRY_URLS",
    "REDACTION_MARKER",
    "REGISTRY_CREDENTIAL_SCHEMA_VERSION",
    "TOKEN_MAX_CHARS",
    "TOKEN_MIN_CHARS",
    "RegistryCredentialError",
    "RegistryCredentialOut",
    "ResolvedCredential",
    "credential_encryption_configured",
    "delete_credential",
    "describe_token",
    "list_credentials",
    "normalize_registry_url",
    "redact_secrets",
    "resolve_credential",
    "save_credential",
    "validate_registry_credential_keys",
]

#: The addressable shape of a credential's metadata projection.
REGISTRY_CREDENTIAL_SCHEMA_VERSION = "sdk.registry-credential.v1"

#: Scope labels, matching SDK-3.4's vocabulary so one reader knows both surfaces.
CREDENTIAL_SCOPE_TENANT = "tenant"
CREDENTIAL_SCOPE_PROJECT = "project"

#: Where each ecosystem publishes when a credential names no registry of its own. npm's is an API
#: root; PyPI's is the legacy upload endpoint, which is the only one that accepts an upload.
DEFAULT_REGISTRY_URLS: Dict[str, str] = {
    NPM_ECOSYSTEM: "https://registry.npmjs.org",
    PYPI_ECOSYSTEM: "https://upload.pypi.org/legacy/",
}

#: What a redacted secret is replaced by. Distinct from the intake scrubber's marker so a reader
#: can tell "a publish log hid a registry token" from "an uploaded document was scrubbed".
REDACTION_MARKER = "[registry-token-redacted]"

#: A token shorter than this is a typo, not a credential.
TOKEN_MIN_CHARS = 8

#: Generous upper bound. A PyPI API token is a macaroon and runs to several hundred characters; a
#: value past this is a pasted file, and refusing it beats sealing a megabyte.
TOKEN_MAX_CHARS = 4_000

#: Registry URLs must be plain HTTPS. ``http://`` would send a publish token in the clear.
_HTTPS_URL = re.compile(r"^https://[A-Za-z0-9.\-]+(?::\d{1,5})?(?:/[^\s]*)?$")

#: A token may not contain whitespace or control characters: every registry sends it in a header,
#: where a newline is a request-splitting hazard rather than a formatting quirk.
_TOKEN_ILLEGAL = re.compile(r"[\s\x00-\x1f\x7f]")

#: Public scheme prefixes worth reporting back. These are *not* secret — they are how npm and PyPI
#: label their own token formats — and naming the one a stored token carries is what lets an
#: operator see they pasted a PyPI token into the npm slot.
_TOKEN_PREFIXES = ("npm_", "npms_", "pypi-", "gh_", "ghp_")

#: How much of the token digest is projected. Sixteen hex characters is 64 bits — far too little to
#: attack, and far more than enough to tell two tokens apart.
_FINGERPRINT_CHARS = 16

#: The SDK registry vault. ``OSRV`` = *Apiome SDK Registry Vault*.
_CIPHER = EnvelopeCipher(
    magic=b"OSRV",
    subject="SDK registry credential",
    keys_setting="APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS",
    read_keys=lambda: settings.sdk_registry_credential_encryption_keys,
    read_active_version=lambda: settings.sdk_registry_credential_active_key_version,
)


class RegistryCredentialError(ValueError):
    """Raised when a credential cannot be accepted or stored.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once rather than
            one per round trip.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid registry credential")


class RegistryCredentialOut(BaseModel):
    """A stored credential, described without being revealed.

    Attributes:
        schema_version: The projection's shape.
        ecosystem: ``npm`` or ``pypi``.
        scope: ``tenant`` or ``project``.
        project_id: The project this credential belongs to, when it is a project override.
        registry_url: Where it publishes.
        token_prefix: The public scheme prefix the token declares, when it declares one.
        token_length: How many characters the stored token has.
        token_fingerprint: A truncated SHA-256 of the token, for confirming a rotation.
        key_version: Which master key sealed it.
        readable: Whether the stored token can currently be decrypted. ``False`` means the key
            that sealed it is not configured — the credential is present but unusable, and saying
            so beats a publish failing with a decryption error.
        created_at: When it was first stored.
        updated_at: When it was last replaced.
        updated_by: Who last replaced it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=REGISTRY_CREDENTIAL_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    ecosystem: str = Field(description="``npm`` or ``pypi``.")
    scope: str = Field(description="``tenant`` or ``project``.")
    project_id: Optional[str] = Field(default=None, serialization_alias="projectId")
    registry_url: str = Field(serialization_alias="registryUrl")
    token_prefix: Optional[str] = Field(default=None, serialization_alias="tokenPrefix")
    token_length: Optional[int] = Field(default=None, serialization_alias="tokenLength")
    token_fingerprint: Optional[str] = Field(default=None, serialization_alias="tokenFingerprint")
    key_version: Optional[int] = Field(default=None, serialization_alias="keyVersion")
    readable: bool = Field(default=True)
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


@dataclass(frozen=True)
class ResolvedCredential:
    """The credential in force for one publish, with its plaintext token.

    Lives only in memory, for the duration of one publish. Nothing that logs, audits or persists
    ever receives this object — callers pass :attr:`token` to the transport and
    :attr:`RegistryCredentialOut` everywhere else.

    Attributes:
        ecosystem: ``npm`` or ``pypi``.
        token: The plaintext registry token.
        registry_url: Where to publish.
        scope: Which scope supplied it (``tenant`` or ``project``).
        credential_id: The row it came from.
    """

    ecosystem: str
    token: str
    registry_url: str
    scope: str
    credential_id: Optional[str] = None


# -------------------------------------------------------------------------------------------
# Validation and description
# -------------------------------------------------------------------------------------------


def credential_encryption_configured() -> bool:
    """Return ``True`` when a master key is configured, so credentials can be stored."""
    return _CIPHER.configured()


def validate_registry_credential_keys() -> None:
    """Validate the configured key map at startup.

    No keys configured is acceptable — the server starts and the credential routes refuse with a
    clear message. Keys that are *present but malformed* fail fast, so the misconfiguration
    surfaces at boot rather than at the first publish.

    Raises:
        EnvelopeEncryptionError: If the key map is present but malformed, or the active version is
            absent from it.
    """
    _CIPHER.validate()


def normalize_registry_url(ecosystem: str, raw: Optional[str]) -> str:
    """Resolve and check the registry a credential publishes to.

    Args:
        ecosystem: ``npm`` or ``pypi``.
        raw: The configured URL, or ``None``/blank for the ecosystem's default.

    Returns:
        The URL to publish to, with any trailing whitespace removed.

    Raises:
        RegistryCredentialError: If the URL is not plain HTTPS. A publish token sent over ``http``
            is a token given away, so this refuses rather than warns.
    """
    candidate = (raw or "").strip()
    if not candidate:
        return DEFAULT_REGISTRY_URLS[ecosystem]
    if not _HTTPS_URL.match(candidate):
        raise RegistryCredentialError(
            f"registryUrl must be an `https://` URL, got {candidate!r}. A publish token sent "
            "over plain HTTP is a token disclosed."
        )
    return candidate


def _validate_ecosystem(ecosystem: str) -> str:
    """Return the ecosystem key, or refuse.

    Args:
        ecosystem: The requested ecosystem.

    Returns:
        The normalised key.

    Raises:
        RegistryCredentialError: When it is not one SDK-4.1 publishes to.
    """
    key = (ecosystem or "").strip().lower()
    if key not in PUBLISH_ECOSYSTEMS:
        raise RegistryCredentialError(
            f"ecosystem must be one of {', '.join(PUBLISH_ECOSYSTEMS)}, got {ecosystem!r}. "
            "`gomod` names a module path rather than a registry, and a Go module is released by "
            "pushing a tag (SDK-4.2), not by uploading."
        )
    return key


def _validate_token(token: Optional[str]) -> str:
    """Return the token, or refuse.

    Args:
        token: The submitted token.

    Returns:
        The token with surrounding whitespace stripped — a pasted token routinely carries a
        trailing newline, and silently sending that in a header would fail confusingly.

    Raises:
        RegistryCredentialError: When the token is absent, too short, too long, or carries
            whitespace or control characters. The message never quotes the token.
    """
    candidate = (token or "").strip()
    problems: List[str] = []
    if not candidate:
        problems.append("token is required")
    else:
        if len(candidate) < TOKEN_MIN_CHARS:
            problems.append(f"token is shorter than {TOKEN_MIN_CHARS} characters")
        if len(candidate) > TOKEN_MAX_CHARS:
            problems.append(f"token is longer than {TOKEN_MAX_CHARS:,} characters")
        if _TOKEN_ILLEGAL.search(candidate):
            problems.append("token contains whitespace or control characters")
    if problems:
        raise RegistryCredentialError(*problems)
    return candidate


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of a known secret with :data:`REDACTION_MARKER`.

    The belt to the pipeline's braces. Nothing in SDK-4.1 *writes* a token into a log line, but a
    registry's own error body is outside our control and could quote the credential it rejected,
    and a log is forever. This is exact-substring redaction over the tokens actually held in
    memory — not a heuristic — so it cannot miss the one secret that matters or corrupt text that
    merely looks random. Contrast :mod:`app.intake_secret_scrub`, which must find secrets it was
    never told about in an uploaded document.

    Args:
        text: The text about to be stored or logged.
        secrets: The plaintext secrets in play. Empty or very short entries are ignored: replacing
            every ``ab`` in a log would destroy it.

    Returns:
        The text with each secret replaced.
    """
    redacted = text or ""
    for secret in secrets:
        if secret and len(secret) >= TOKEN_MIN_CHARS:
            redacted = redacted.replace(secret, REDACTION_MARKER)
    return redacted


def describe_token(token: str) -> Dict[str, Any]:
    """Describe a token without revealing it.

    Args:
        token: The plaintext token.

    Returns:
        ``{"token_prefix", "token_length", "token_fingerprint"}``. The prefix is only ever a
        *public* scheme marker (``npm_``, ``pypi-``); no part of the secret body is projected, and
        the fingerprint is a truncated digest rather than a substring.
    """
    prefix = next((known for known in _TOKEN_PREFIXES if token.startswith(known)), None)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:_FINGERPRINT_CHARS]
    return {
        "token_prefix": prefix,
        "token_length": len(token),
        "token_fingerprint": f"sha256:{digest}",
    }


# -------------------------------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------------------------------


def _scope_of(project_id: Optional[str]) -> str:
    """Return the scope label a project id addresses."""
    return CREDENTIAL_SCOPE_PROJECT if project_id else CREDENTIAL_SCOPE_TENANT


def _project_id_of(row: Mapping[str, Any]) -> Optional[str]:
    """Return a row's project id as a string, or ``None`` for a tenant-wide row."""
    value = row.get("project_id")
    return str(value) if value else None


def _out(row: Mapping[str, Any], *, readable: bool) -> RegistryCredentialOut:
    """Project a stored row onto its metadata response.

    Args:
        row: The stored row.
        readable: Whether the token could be decrypted with the keys configured now.

    Returns:
        The response. The ciphertext and the plaintext are both absent by construction.
    """
    project_id = _project_id_of(row)
    metadata = row.get("token_metadata")
    described: Dict[str, Any] = dict(metadata) if isinstance(metadata, Mapping) else {}
    return RegistryCredentialOut(
        ecosystem=str(row.get("ecosystem") or ""),
        scope=_scope_of(project_id),
        project_id=project_id,
        registry_url=str(row.get("registry_url") or ""),
        token_prefix=described.get("token_prefix"),
        token_length=described.get("token_length"),
        token_fingerprint=described.get("token_fingerprint"),
        key_version=row.get("key_version"),
        readable=readable,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )


def save_credential(
    tenant_id: str,
    *,
    ecosystem: str,
    token: str,
    project_id: Optional[str] = None,
    registry_url: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> RegistryCredentialOut:
    """Store (or replace) the credential for one scope and ecosystem.

    Args:
        tenant_id: Owning tenant.
        ecosystem: ``npm`` or ``pypi``.
        token: The plaintext registry token. Sealed here and never persisted in the clear.
        project_id: The project this credential is for, or ``None`` for the tenant-wide one.
        registry_url: Where to publish; defaults to the ecosystem's public registry.
        actor_id: The user storing it.

    Returns:
        The stored credential's metadata.

    Raises:
        RegistryCredentialError: When the ecosystem, token or registry URL is not acceptable.
        EnvelopeEncryptionError: When encryption is not configured. Deliberately *not* caught: a
            token that cannot be sealed must not be written, and the caller turns this into a
            503 naming the environment variable to set.
        RuntimeError: When the write returned no row.
    """
    key = _validate_ecosystem(ecosystem)
    plaintext = _validate_token(token)
    url = normalize_registry_url(key, registry_url)

    encrypted, key_version = _CIPHER.seal({"token": plaintext})
    row = db.upsert_sdk_registry_credential(
        tenant_id=tenant_id,
        project_id=project_id,
        ecosystem=key,
        registry_url=url,
        encrypted_token=encrypted,
        key_version=key_version,
        token_metadata=describe_token(plaintext),
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError("The registry credential could not be stored for this tenant.")
    return _out(row, readable=True)


def list_credentials(
    tenant_id: str, *, project_id: Optional[str] = None
) -> List[RegistryCredentialOut]:
    """List the credentials visible to a scope, most specific last.

    Args:
        tenant_id: Owning tenant.
        project_id: When given, tenant-wide credentials *and* that project's overrides; otherwise
            only the tenant-wide ones.

    Returns:
        One entry per stored row, ordered tenant-first so a reader sees what a project overrides.
        Never raises: a store failure logs and returns an empty list, because this is a read of
        configuration rather than a step in a publish.
    """
    try:
        rows = db.get_sdk_registry_credentials(tenant_id, project_id)
    except Exception:  # noqa: BLE001 - listing configuration must not take a screen down
        logger.warning(
            "Could not list SDK registry credentials for tenant %s", tenant_id, exc_info=True
        )
        return []
    out: List[RegistryCredentialOut] = []
    for row in rows:
        readable = _CIPHER.unseal(row.get("encrypted_token"), row.get("key_version")) is not None
        out.append(_out(row, readable=readable))
    return out


def delete_credential(
    tenant_id: str, *, ecosystem: str, project_id: Optional[str] = None
) -> bool:
    """Remove the credential stored at exactly one scope.

    Nothing cascades: dropping a project override falls back to the tenant credential, and dropping
    the tenant credential leaves project overrides in place — those were configured deliberately.

    Args:
        tenant_id: Owning tenant.
        ecosystem: ``npm`` or ``pypi``.
        project_id: The project override to drop, or ``None`` for the tenant-wide row.

    Returns:
        ``True`` when a credential was stored at that exact scope and has now been removed.

    Raises:
        RegistryCredentialError: When the ecosystem is not one SDK-4.1 publishes to.
    """
    key = _validate_ecosystem(ecosystem)
    return db.delete_sdk_registry_credential(tenant_id, key, project_id) > 0


def resolve_credential(
    tenant_id: str, *, ecosystem: str, project_id: Optional[str] = None
) -> Optional[ResolvedCredential]:
    """Return the credential a publish should use, with its plaintext token.

    The project override wins whole — a token is atomic, so there is nothing to merge. A row whose
    token cannot be decrypted (its sealing key is no longer configured) is treated as **absent**
    rather than as an error, and the more general scope is tried: a tenant token that still opens
    is a better answer than a project token nobody can read.

    Args:
        tenant_id: Owning tenant.
        ecosystem: ``npm`` or ``pypi``.
        project_id: The project being published.

    Returns:
        The :class:`ResolvedCredential`, or ``None`` when no readable credential exists. The caller
        turns ``None`` into a refusal naming the ecosystem — never into an unauthenticated publish.
    """
    key = _validate_ecosystem(ecosystem)
    try:
        rows = db.get_sdk_registry_credentials(tenant_id, project_id, ecosystem=key)
    except Exception:  # noqa: BLE001 - a store fault is "no credential", and the publish refuses
        logger.warning(
            "Could not read SDK registry credentials for tenant %s", tenant_id, exc_info=True
        )
        return None

    # Most specific first: a project row, then the tenant-wide row.
    ordered = sorted(rows, key=lambda row: 0 if _project_id_of(row) else 1)
    for row in ordered:
        payload = _CIPHER.unseal(row.get("encrypted_token"), row.get("key_version"))
        token = (payload or {}).get("token") if payload else None
        if not isinstance(token, str) or not token:
            logger.warning(
                "SDK registry credential %s (%s) could not be opened; trying the next scope",
                row.get("id"),
                key,
            )
            continue
        return ResolvedCredential(
            ecosystem=key,
            token=token,
            registry_url=str(row.get("registry_url") or DEFAULT_REGISTRY_URLS[key]),
            scope=_scope_of(_project_id_of(row)),
            credential_id=str(row["id"]) if row.get("id") else None,
        )
    return None


# Re-exported so a caller handling a save needs one import for the two errors it can raise.
CredentialEncryptionError = EnvelopeEncryptionError
