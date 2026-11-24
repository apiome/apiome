"""Sealing a contract webhook's secrets — PFX-1.9 (#6922).

A webhook may carry three kinds of secret: a basic-auth password, secret header values (an
``Authorization`` token) and an HMAC signing secret. They are stored only as ciphertext, in
``apiome.pact_webhook.secret_ciphertext`` (V436), sealed by the shared envelope cipher
(:mod:`app.envelope_crypto`: AES-256-GCM with a per-secret data key wrapped by a versioned master
key from the environment).

The master keys are the credential vault's (``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS``), so a
deployment that already stores credentials needs nothing new. The magic is this vault's own
(``OPWH``), so a sealed webhook secret does not open as any other vault's blob, and no other
vault's blob opens here.

**Fails closed.** Without a configured key a webhook that carries a secret cannot be stored
(:class:`~app.envelope_crypto.EnvelopeEncryptionError`; the route answers 503 naming the variable),
and a stored one cannot be opened (:func:`unseal_webhook_secrets` returns ``None``; the delivery
fails and is retried rather than sent without its credentials).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .config import settings
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError

__all__ = [
    "KEYS_SETTING",
    "WebhookSecretError",
    "seal_webhook_secrets",
    "unseal_webhook_secrets",
    "webhook_secrets_configured",
]

#: The environment variable holding the master keys.
KEYS_SETTING = "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS"

#: Raised when secrets cannot be sealed. Its message never contains secret material.
WebhookSecretError = EnvelopeEncryptionError

#: ``OPWH`` = *apiome Pact WebHook*.
_CIPHER = EnvelopeCipher(
    magic=b"OPWH",
    subject="contract webhook secret",
    keys_setting=KEYS_SETTING,
    read_keys=lambda: settings.mcp_credential_encryption_keys,
    read_active_version=lambda: settings.mcp_credential_active_key_version,
)


def webhook_secrets_configured() -> bool:
    """Return ``True`` when a master key is configured, so secrets can be sealed and opened."""
    return _CIPHER.configured()


def seal_webhook_secrets(secrets: Mapping[str, Any]) -> Tuple[bytes, int]:
    """Seal a webhook's secrets for storage.

    Args:
        secrets: ``{"password": …, "signingSecret": …, "headers": {name: value}}``, each optional.

    Returns:
        ``(ciphertext, key_version)`` for ``secret_ciphertext`` and ``key_version``.

    Raises:
        WebhookSecretError: When no master key is configured or the key map is malformed.
    """
    return _CIPHER.seal(secrets)


def unseal_webhook_secrets(ciphertext: Optional[bytes], key_version: Optional[int]) -> Optional[Dict[str, Any]]:
    """Open a webhook's sealed secrets, in memory, for one send.

    Args:
        ciphertext: The stored blob, or ``None`` for a webhook without secrets.
        key_version: The master key version that sealed it.

    Returns:
        The secrets; ``{}`` for a webhook that has none; ``None`` when a stored blob cannot be
        opened (no key, wrong key, tampered).
    """
    if ciphertext is None:
        return {}
    return _CIPHER.unseal(bytes(ciphertext), key_version)
