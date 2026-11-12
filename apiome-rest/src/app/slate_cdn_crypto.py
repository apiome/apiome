"""Encryption at rest for Slate CDN purge credentials — Slate 10.2 (private-suite#120).

A Cloudflare API token, Fastly API key or custom purge-endpoint secret can flush a tenant's
production cache, so it is never stored in the clear. This module is the only place the
credential is sealed or opened: :mod:`app.slate_cdn_store` writes what :func:`seal_cdn_credential`
returns into ``apiome.slate_cdn_providers.credential_ciphertext`` / ``credential_key_version``,
and :mod:`app.slate_cdn_dispatch` opens it in memory at the moment a purge is sent.

The vault is :class:`app.envelope_crypto.EnvelopeCipher` under its own magic (``OSCV`` — *Apiome
Slate CDN Vault*) and its own key map (``APIOME_SLATE_CDN_CREDENTIAL_ENCRYPTION_KEYS``), so a CDN
token cannot be opened with the key that seals another vault's secrets.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .config import settings
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError

__all__ = [
    "CdnCredentialEncryptionError",
    "cdn_vault_configured",
    "seal_cdn_credential",
    "unseal_cdn_credential",
    "validate_slate_cdn_credential_keys",
]

#: The setting an operator sets to enable the vault, named in every refusal.
KEYS_SETTING = "APIOME_SLATE_CDN_CREDENTIAL_ENCRYPTION_KEYS"

_CIPHER = EnvelopeCipher(
    magic=b"OSCV",
    subject="Slate CDN credential",
    keys_setting=KEYS_SETTING,
    read_keys=lambda: settings.slate_cdn_credential_encryption_keys,
    read_active_version=lambda: settings.slate_cdn_credential_active_key_version,
)

#: Re-exported so a caller handling a save needs one import for the error it can raise.
CdnCredentialEncryptionError = EnvelopeEncryptionError


def cdn_vault_configured() -> bool:
    """Report whether a key map is configured, so a save can be refused before it is attempted.

    Returns:
        True when credentials can be sealed on this deployment.
    """
    return _CIPHER.configured()


def seal_cdn_credential(secret: str) -> Tuple[bytes, int]:
    """Seal a purge credential for storage.

    Args:
        secret: The plaintext credential.

    Returns:
        ``(ciphertext, key_version)`` to store side by side.

    Raises:
        CdnCredentialEncryptionError: When no key map is configured or it is malformed.
    """
    return _CIPHER.seal({"secret": secret})


def unseal_cdn_credential(
    ciphertext: Optional[bytes], key_version: Optional[int]
) -> Optional[str]:
    """Open a stored purge credential in memory.

    Fail-safe like :meth:`EnvelopeCipher.unseal`: a missing key, a rotated-away version or a
    tampered blob returns None, and the caller reports the purge as failed rather than sending it
    without a credential.

    Args:
        ciphertext: The stored blob.
        key_version: The version that sealed it.

    Returns:
        The plaintext credential, or None when it cannot be opened.
    """
    payload = _CIPHER.unseal(ciphertext, key_version)
    if not payload:
        return None
    secret = payload.get("secret")
    return secret if isinstance(secret, str) and secret else None


def validate_slate_cdn_credential_keys() -> None:
    """Validate the key map at startup.

    No keys is acceptable (attaching a provider is refused with a clear reason); keys that are
    present but malformed fail at boot rather than at the first purge.

    Raises:
        CdnCredentialEncryptionError: When the key map is present but malformed.
    """
    _CIPHER.validate()
