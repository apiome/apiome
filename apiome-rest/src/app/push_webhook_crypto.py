"""Encrypt signing secrets at rest for outbound webhook HMAC (#2588)."""

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def validate_webhook_signing_key() -> None:
    """Validate the configured Fernet key at startup; raise ValueError if misconfigured.

    If no key is set the server starts normally (signing secrets stored as NULL).
    If the key IS set but is not a valid Fernet key the server must not start — fail fast.
    """
    key = settings.webhook_signing_secret_encryption_key
    if not key:
        return  # Encryption not configured — acceptable.
    try:
        Fernet(key.strip().encode("ascii"))
    except Exception as exc:
        raise ValueError(
            "APIOME_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY is set but is not a valid "
            "Fernet key. Generate a valid key with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_signing_secret(plain: str) -> Optional[bytes]:
    """Return Fernet ciphertext, or None if encryption key is not configured."""
    key = settings.webhook_signing_secret_encryption_key
    if not key or not plain:
        return None
    f = Fernet(key.strip().encode("ascii"))
    return f.encrypt(plain.encode("utf-8"))


def decrypt_signing_secret(blob: bytes) -> Optional[str]:
    """Decrypt ciphertext; returns None on missing key or bad data."""
    key = settings.webhook_signing_secret_encryption_key
    if not key or not blob:
        return None
    try:
        f = Fernet(key.strip().encode("ascii"))
        return f.decrypt(blob).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return None
