"""Envelope encryption-at-rest for outbound MCP credentials (MCAT-6.2, #3678).

A protected MCP server is reached by holding a secret (a bearer token, a custom-header value, an
OAuth2 token set, …). That secret is persisted in ``apiome.mcp_endpoint_credentials.encrypted_payload``
as **ciphertext only** (V129); this module is the single place the plaintext is sealed before it is
written and unsealed in-memory at connect time. The database never sees, and cannot reconstruct, a
token.

**The scheme itself lives in :mod:`app.envelope_crypto`** — AES-256-GCM envelope encryption with a
per-secret data key wrapped by a versioned master key, the key-version bound into the AAD of both
encryptions. SDK-4.1 (#4495) needed the identical scheme for npm / PyPI registry tokens, so it was
extracted rather than copied; this module is that primitive configured for MCP credentials, and
its stored blob format is unchanged (magic ``OMCV``, format version 1), so rows sealed by earlier
releases still decrypt.

Key configuration (environment):

* ``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`` — a JSON object mapping an integer key-version to a
  base64-encoded 32-byte (AES-256) master key, e.g. ``{"1": "<base64 key>", "2": "<base64 key>"}``.
  Generate a key with::

      python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

* ``APIOME_MCP_CREDENTIAL_ACTIVE_KEY_VERSION`` — which version new secrets are sealed under.
  Optional; defaults to the highest version present. To rotate: add a new (higher) version to the
  map, point the active version at it, and re-seal existing rows with :func:`reseal_credential_payload`.

When no keys are configured the server still starts (mirroring the webhook-secret precedent): secrets
simply cannot be sealed (:func:`seal_credential_payload` raises, fail-closed) or unsealed
(:func:`unseal_credential_payload` returns ``None``, so discovery proceeds unauthenticated).

Security invariants:

* **No plaintext at rest.** Only the wrapped DEK + ciphertext are returned for storage.
* **Authenticated.** GCM detects any tampering of the ciphertext, wrapped DEK, or key-version; a
  tampered or wrong-version blob fails to decrypt and yields ``None`` rather than garbage.
* **Secrets never logged.** Errors and log lines carry only the (non-secret) key-version and the
  shape of the failure — never key material, ciphertext, or decrypted payload.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .config import settings
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError

__all__ = [
    "CredentialEncryptionError",
    "credential_encryption_configured",
    "needs_reseal",
    "reseal_credential_payload",
    "seal_credential_payload",
    "unseal_credential_payload",
    "validate_credential_encryption_keys",
]

#: Raised when a credential cannot be sealed.
#:
#: Causes: encryption is not configured (no master key), the key map is malformed, the requested
#: active key-version has no key, or the payload is not JSON-serialisable. The message never
#: contains secret material — only the non-secret cause — so it is safe to log and surface. An
#: alias of the shared :class:`~app.envelope_crypto.EnvelopeEncryptionError` so a caller may catch
#: either name.
CredentialEncryptionError = EnvelopeEncryptionError

#: The MCP credential vault. ``OMCV`` = *Apiome MCP Credential Vault* — the magic that has opened
#: every stored blob since V129, and part of the AAD, so a blob cannot be moved to another vault.
_CIPHER = EnvelopeCipher(
    magic=b"OMCV",
    subject="MCP credential",
    keys_setting="APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS",
    read_keys=lambda: settings.mcp_credential_encryption_keys,
    read_active_version=lambda: settings.mcp_credential_active_key_version,
)


def credential_encryption_configured() -> bool:
    """Return ``True`` when at least one master key is configured and parseable."""
    return _CIPHER.configured()


def validate_credential_encryption_keys() -> None:
    """Validate the configured key map at startup; raise if it is present but misconfigured.

    No keys configured is acceptable (the server starts; secrets cannot be sealed/unsealed). If keys
    ARE configured they must all parse and the active version must resolve — otherwise fail fast so a
    misconfiguration surfaces at boot, not at the first connect attempt.

    Raises:
        CredentialEncryptionError: If the key map is present but malformed, or the active version is
            absent from it.
    """
    _CIPHER.validate()


def seal_credential_payload(payload: Mapping[str, Any]) -> Tuple[bytes, int]:
    """Seal a plaintext credential payload for storage (envelope-encrypt under the active key).

    Args:
        payload: The plaintext credential payload (e.g. ``{"token": "..."}``); must be
            JSON-serialisable.

    Returns:
        A ``(encrypted_payload, key_version)`` pair: the self-describing ciphertext blob to store in
        ``encrypted_payload`` and the master-key version that sealed it (store in ``key_version``).

    Raises:
        CredentialEncryptionError: If encryption is not configured, the key map is malformed, or the
            payload is not JSON-serialisable.
    """
    return _CIPHER.seal(payload)


def unseal_credential_payload(
    encrypted_payload: Optional[bytes], key_version: Optional[int]
) -> Optional[Dict[str, Any]]:
    """Unseal a stored credential blob back into its plaintext payload (in-memory, at connect time).

    Best-effort and fail-safe: any problem — encryption not configured, no key for the row's
    version, a tampered/foreign/wrong-version blob, or non-object plaintext — returns ``None`` rather
    than raising, so a caller degrades to an unauthenticated run instead of crashing discovery.

    Args:
        encrypted_payload: The stored ciphertext blob (``bytes`` or ``memoryview``), or ``None``.
        key_version: The master-key version that sealed the blob, or ``None``.

    Returns:
        The decrypted payload dict, or ``None`` when no plaintext can be produced.
    """
    return _CIPHER.unseal(encrypted_payload, key_version)


def needs_reseal(key_version: Optional[int]) -> bool:
    """Return ``True`` when a row sealed under ``key_version`` is not on the active key.

    Used by rotation: a row whose version differs from the active version should be re-sealed.
    Returns ``False`` when encryption is unconfigured/misconfigured or the version is unknown (there
    is nothing meaningful to rotate to).
    """
    return _CIPHER.needs_reseal(key_version)


def reseal_credential_payload(
    encrypted_payload: Optional[bytes], key_version: Optional[int]
) -> Optional[Tuple[bytes, int]]:
    """Re-seal a stored credential under the active key (key rotation).

    Decrypts the blob with the key that sealed it, then re-seals the recovered plaintext under the
    active key-version. The plaintext exists only transiently in memory.

    Args:
        encrypted_payload: The currently-stored ciphertext blob.
        key_version: The version that sealed it.

    Returns:
        A fresh ``(encrypted_payload, key_version)`` pair to persist, or ``None`` when the existing
        blob cannot be decrypted (nothing to rotate).

    Raises:
        CredentialEncryptionError: If re-sealing fails (e.g. encryption became unconfigured between
            the decrypt and the re-encrypt).
    """
    return _CIPHER.reseal(encrypted_payload, key_version)
