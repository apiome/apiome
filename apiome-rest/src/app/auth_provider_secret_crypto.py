"""Envelope encryption-at-rest for server-global OAuth provider secrets (OLO-8.3, #4969).

A deployment signs everyone in through one set of OAuth apps (GitHub/GitLab/Entra/…). An operator
can override the env-supplied provider config from the admin UI (OLO-8.4), and the client secret they
enter is persisted in ``apiome.auth_provider_config.client_secret_encrypted`` (V196, OLO-8.2) as
**ciphertext only** — the database never sees, and cannot reconstruct, a secret. This module is the
single place a provider secret is sealed before it is written and unsealed in-memory on the
server-side read path (OLO-8.5). A plaintext secret in Postgres is strictly worse than one in an env
var, so the key that protects it (the KEK) deliberately lives *outside* the database.

Scheme — *envelope encryption* with AES-256-GCM (Python ``cryptography``):

* A per-secret random **data-encryption key (DEK)** encrypts the secret (AES-256-GCM, random 96-bit
  nonce). A fresh DEK per secret means two providers holding the same secret still produce unrelated
  ciphertext, and a single DEK never protects more than one short message.
* A long-lived **key-encryption-key (KEK)**, supplied from the environment, *wraps* (encrypts) that
  DEK (again AES-256-GCM). Only the wrapped DEK and the secret ciphertext are stored — never the DEK
  itself, and never the KEK.
* The DB column ``enc_key_id`` records *which* KEK sealed a row. Several KEKs can be configured at
  once, so the active key can be rotated while every older row stays decryptable under the id that
  sealed it — rotation without a flag day. The key id is also bound into the GCM
  additional-authenticated-data of both encryptions, so a row cannot be silently re-tagged to a
  different id.

Key configuration (environment) — see :mod:`app.config`:

* ``AUTH_CONFIG_ENC_KEY`` accepts two forms:

  - a **single** base64-encoded 32-byte (AES-256) key (the common case), sealed under the id in
    ``AUTH_CONFIG_ENC_ACTIVE_KEY_ID`` (default ``"default"``); or
  - a **JSON object** mapping a string key id to a base64 key, e.g.
    ``{"v1": "<base64 key>", "v2": "<base64 key>"}``, for flag-day-free rotation.

  Generate a key with::

      python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

* ``AUTH_CONFIG_ENC_ACTIVE_KEY_ID`` — which id new secrets are sealed under. Optional; defaults to
  ``"default"`` (single-key form) or the sole configured id (map form with exactly one entry). With
  several ids configured it must be set so rotation is unambiguous. To rotate: add a new id to the
  map, point the active id at it, and re-seal existing rows with :func:`reseal_provider_secret`.

Read-path failure policy — **fail loud, not silent** (the OLO-8.3 acceptance criterion): unlike the
outbound-MCP-credential vault (which degrades to an unauthenticated run and returns ``None``), a
provider secret that is *stored but cannot be decrypted* — because the KEK is missing, was rotated
away, or the ciphertext is corrupt — must NOT silently fall back to the env secret. Doing so would be
a silent auth outage (users signed into the wrong or a disabled OAuth app). :func:`unseal_provider_secret`
therefore raises :class:`ProviderSecretDecryptionError` with an actionable, secret-free message so the
read path (OLO-8.5) can surface a clear error. Only the genuinely-absent case (no stored secret,
``enc_key_id`` and ciphertext both NULL) returns ``None`` — the normal "fall back to env" path.

Security invariants:

* **No plaintext at rest.** Only the wrapped DEK + ciphertext are returned for storage.
* **Authenticated.** GCM detects any tampering of the ciphertext, wrapped DEK, or key id; a tampered
  or wrong-id blob fails to decrypt and raises rather than yielding garbage.
* **Secrets never logged.** Errors and log lines carry only the (non-secret) key id and the shape of
  the failure — never key material, ciphertext, or the decrypted secret.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from typing import Dict, Mapping, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

logger = logging.getLogger(__name__)

# Default key id for the single-key form of AUTH_CONFIG_ENC_KEY (a bare base64 key with no explicit
# id). Written to enc_key_id so a later switch to the multi-key rotation form can name this id.
_DEFAULT_KEY_ID = "default"

# Sealed-blob framing. The stored ``client_secret_encrypted`` is a self-describing byte string:
#
#   MAGIC(4) | FORMAT(1) | wrap_nonce(12) | wrapped_dek(48) | secret_nonce(12) | ciphertext(>=16)
#
# ``wrapped_dek`` is a 32-byte DEK sealed with AES-256-GCM (32 + 16-byte tag = 48). ``ciphertext`` is
# the secret sealed with the DEK (plaintext + 16-byte tag). The MAGIC/FORMAT header lets the parser
# reject foreign bytes and lets the format evolve without ambiguity. The key id is NOT in the blob —
# it travels in the sibling ``enc_key_id`` column (V196) and is bound in via the GCM AAD.
_MAGIC = b"OAPS"  # apiOme Auth Provider Secret
_FORMAT_VERSION = 1
_NONCE_LEN = 12  # 96-bit GCM nonce (the recommended size)
_KEY_LEN = 32  # AES-256
_GCM_TAG_LEN = 16
_WRAPPED_DEK_LEN = _KEY_LEN + _GCM_TAG_LEN  # 48
_HEADER_LEN = len(_MAGIC) + 1  # MAGIC + FORMAT byte
# Smallest legal blob: header + wrap nonce + wrapped DEK + secret nonce + an empty secret's GCM tag.
_MIN_BLOB_LEN = _HEADER_LEN + _NONCE_LEN + _WRAPPED_DEK_LEN + _NONCE_LEN + _GCM_TAG_LEN


class AuthConfigEncryptionError(RuntimeError):
    """Raised when a provider secret cannot be sealed, or key config is malformed.

    Causes: encryption is not configured (no KEK), the key config is malformed, or the requested
    active key id has no key. The message never contains secret material — only the non-secret cause
    — so it is safe to log and surface.
    """


class ProviderSecretDecryptionError(AuthConfigEncryptionError):
    """Raised when a *stored* provider secret cannot be decrypted on the read path.

    This is the loud, actionable failure the OLO-8.3 acceptance criterion requires: a secret exists
    in ``client_secret_encrypted`` but the KEK that would unseal it is missing, was rotated away, or
    the ciphertext is corrupt. Raising (rather than returning ``None``) stops the read path from
    silently falling back to the env secret — which would be a silent auth outage. The message names
    the non-secret ``enc_key_id`` and the remedy, and carries no secret material.
    """


def _decode_kek(b64: str, key_id: str) -> bytes:
    """Decode one base64 KEK, requiring exactly 32 bytes (AES-256).

    Accepts both standard and URL-safe base64. The key id appears only in the (non-secret) error
    message; the key bytes themselves are never logged.
    """
    candidate = b64.strip()
    # Try standard and url-safe alphabets with strict validation, so a url-safe key (``-``/``_``, as
    # ``Fernet.generate_key`` produces) is not silently mangled by the standard decoder dropping those
    # chars. Prefer whichever decode yields exactly a 32-byte key; only fall back to a wrong-length or
    # undecodable result for the error message.
    decoders = (
        lambda c: base64.b64decode(c, validate=True),
        lambda c: base64.urlsafe_b64decode(c),
    )
    decoded_any: Optional[bytes] = None
    for decoder in decoders:
        try:
            raw = decoder(candidate)
        except (binascii.Error, ValueError):
            continue
        if len(raw) == _KEY_LEN:
            return raw
        decoded_any = raw
    if decoded_any is not None:
        raise AuthConfigEncryptionError(
            f"KEK for key id {key_id!r} must decode to {_KEY_LEN} bytes (AES-256), "
            f"got {len(decoded_any)}"
        )
    raise AuthConfigEncryptionError(
        f"KEK for key id {key_id!r} is not valid base64"
    )


def _load_key_map() -> Dict[str, bytes]:
    """Parse ``AUTH_CONFIG_ENC_KEY`` into ``{key_id: 32-byte KEK}`` (empty when unconfigured).

    Two accepted forms (see the module docstring): a JSON object maps explicit string ids to base64
    keys; anything else is treated as a single bare base64 key under the active id (default
    ``"default"``). A bare 32-byte base64 key is never a JSON object, so the two forms never collide.

    Raises:
        AuthConfigEncryptionError: If the env value is present but malformed — a JSON object with a
            blank/non-string id or non-string value, or a value that is not a 32-byte base64 key.
    """
    raw = settings.auth_config_enc_key
    if not raw or not raw.strip():
        return {}

    parsed = None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        if not parsed:
            raise AuthConfigEncryptionError(
                "AUTH_CONFIG_ENC_KEY is an empty JSON object; provide at least one "
                'key id → base64 key, e.g. {"v1": "<base64 key>"}'
            )
        keys: Dict[str, bytes] = {}
        for key_id, value in parsed.items():
            if not isinstance(key_id, str) or not key_id.strip():
                raise AuthConfigEncryptionError(
                    f"AUTH_CONFIG_ENC_KEY has an invalid key id {key_id!r}; ids must be "
                    "non-empty strings"
                )
            if not isinstance(value, str):
                raise AuthConfigEncryptionError(
                    f"KEK for key id {key_id!r} must be a base64 string"
                )
            keys[key_id] = _decode_kek(value, key_id)
        return keys

    # Single bare base64 key. Sealed under the configured active id, or "default".
    active = settings.auth_config_enc_active_key_id or _DEFAULT_KEY_ID
    return {active: _decode_kek(raw, active)}


def _active_key_id(keys: Mapping[str, bytes]) -> str:
    """Return the key id new secrets are sealed under.

    Resolution: the configured ``AUTH_CONFIG_ENC_ACTIVE_KEY_ID`` if set; otherwise the sole id when
    exactly one is configured. With several ids configured and none chosen, rotation is ambiguous, so
    the operator must name one.

    Raises:
        AuthConfigEncryptionError: If a configured active id is absent from the key map, or several
            ids are configured without one being chosen.
    """
    configured = settings.auth_config_enc_active_key_id
    if configured is not None:
        if configured not in keys:
            raise AuthConfigEncryptionError(
                f"active key id {configured!r} has no configured KEK in AUTH_CONFIG_ENC_KEY"
            )
        return configured
    if len(keys) == 1:
        return next(iter(keys))
    raise AuthConfigEncryptionError(
        "several KEKs are configured in AUTH_CONFIG_ENC_KEY but AUTH_CONFIG_ENC_ACTIVE_KEY_ID is "
        "unset; set it to the id that new secrets should be sealed under"
    )


def _aad(key_id: str) -> bytes:
    """Additional authenticated data binding a sealed blob to its key id.

    Feeding this into both GCM operations means a blob sealed under id *A* will not authenticate if
    presented as id *B* — a row cannot be silently re-pointed at a different key.
    """
    return f"{_MAGIC.decode('ascii')}:{key_id}".encode("utf-8")


def provider_secret_encryption_configured() -> bool:
    """Return ``True`` when at least one KEK is configured and parseable."""
    try:
        return bool(_load_key_map())
    except AuthConfigEncryptionError:
        return False


def validate_auth_config_encryption_keys() -> None:
    """Validate the configured KEK(s) at startup; raise if present but misconfigured.

    No KEK configured is acceptable (the server starts; provider secrets simply cannot be sealed or
    unsealed until one is set). If a KEK IS configured it must parse and the active id must resolve —
    otherwise fail fast so a misconfiguration surfaces at boot, not at the first secret save/read.

    Raises:
        AuthConfigEncryptionError: If the key config is present but malformed, or the active id is
            absent from it / ambiguous.
    """
    keys = _load_key_map()
    if not keys:
        return
    _active_key_id(keys)


def seal_provider_secret(secret: str) -> Tuple[bytes, str]:
    """Seal a plaintext provider client secret for storage (envelope-encrypt under the active KEK).

    Args:
        secret: The plaintext OAuth client secret. Must be a non-empty string — an empty secret is
            indistinguishable from "no secret" (both NULL) and should not be stored.

    Returns:
        An ``(client_secret_encrypted, enc_key_id)`` pair: the self-describing ciphertext blob to
        store in ``client_secret_encrypted`` and the key id that sealed it (store in ``enc_key_id``).
        The two travel together (the V196 CHECK constraint enforces both-or-neither).

    Raises:
        AuthConfigEncryptionError: If encryption is not configured, the key config is malformed, the
            active id has no key, or ``secret`` is empty / not a string.
    """
    if not isinstance(secret, str) or secret == "":
        raise AuthConfigEncryptionError(
            "provider secret to seal must be a non-empty string"
        )
    keys = _load_key_map()
    if not keys:
        raise AuthConfigEncryptionError(
            "auth provider secret encryption is not configured; set AUTH_CONFIG_ENC_KEY before "
            "storing a client secret"
        )
    key_id = _active_key_id(keys)
    kek = keys[key_id]
    aad = _aad(key_id)

    plaintext = secret.encode("utf-8")

    dek = AESGCM.generate_key(bit_length=_KEY_LEN * 8)
    secret_nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(dek).encrypt(secret_nonce, plaintext, aad)

    wrap_nonce = os.urandom(_NONCE_LEN)
    wrapped_dek = AESGCM(kek).encrypt(wrap_nonce, dek, aad)

    blob = b"".join(
        (
            _MAGIC,
            bytes((_FORMAT_VERSION,)),
            wrap_nonce,
            wrapped_dek,
            secret_nonce,
            ciphertext,
        )
    )
    return blob, key_id


def _parse_blob(blob: bytes) -> Tuple[bytes, bytes, bytes, bytes]:
    """Split a sealed blob into ``(wrap_nonce, wrapped_dek, secret_nonce, ciphertext)``.

    Raises:
        ValueError: If the blob is too short, lacks the magic header, or carries an unknown format
            version.
    """
    if len(blob) < _MIN_BLOB_LEN:
        raise ValueError("sealed provider secret is shorter than the minimum envelope length")
    if blob[: len(_MAGIC)] != _MAGIC:
        raise ValueError("sealed provider secret has an unrecognised header")
    if blob[len(_MAGIC)] != _FORMAT_VERSION:
        raise ValueError(
            f"sealed provider secret has unsupported format version {blob[len(_MAGIC)]}"
        )
    offset = _HEADER_LEN
    wrap_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    wrapped_dek = blob[offset : offset + _WRAPPED_DEK_LEN]
    offset += _WRAPPED_DEK_LEN
    secret_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ciphertext = blob[offset:]
    return wrap_nonce, wrapped_dek, secret_nonce, ciphertext


def unseal_provider_secret(
    client_secret_encrypted: Optional[bytes], enc_key_id: Optional[str]
) -> Optional[str]:
    """Unseal a stored provider secret back into plaintext (in-memory, on the read path).

    Fail-loud, per the OLO-8.3 acceptance criterion. A genuinely-absent secret (both arguments
    ``None`` — the V196 both-or-neither invariant) returns ``None`` so the caller falls back to the
    env secret; that is the only silent path. Any *stored* secret that cannot be produced — encryption
    unconfigured, no KEK for the row's id (missing/rotated-away key), or a tampered/corrupt blob —
    raises :class:`ProviderSecretDecryptionError` with an actionable, secret-free message rather than
    silently degrading to the env secret (which would be a silent auth outage).

    Args:
        client_secret_encrypted: The stored ciphertext blob (``bytes`` or ``memoryview``), or ``None``.
        enc_key_id: The key id that sealed the blob, or ``None``.

    Returns:
        The decrypted client secret string, or ``None`` when no secret is stored.

    Raises:
        ProviderSecretDecryptionError: If a secret is stored but cannot be decrypted, or the two
            columns are inconsistent (only one of blob / key id present).
    """
    if not client_secret_encrypted and enc_key_id is None:
        return None
    # Inconsistent pair — the V196 CHECK should prevent this, but never trust the input blindly.
    if not client_secret_encrypted or enc_key_id is None:
        raise ProviderSecretDecryptionError(
            "stored provider secret is inconsistent: exactly one of client_secret_encrypted / "
            "enc_key_id is set (they must both be present or both absent)"
        )

    try:
        keys = _load_key_map()
    except AuthConfigEncryptionError as exc:
        raise ProviderSecretDecryptionError(
            f"a provider secret is stored (enc_key_id={enc_key_id!r}) but AUTH_CONFIG_ENC_KEY is "
            f"misconfigured: {exc}"
        ) from exc
    if not keys:
        raise ProviderSecretDecryptionError(
            f"a provider secret is stored (enc_key_id={enc_key_id!r}) but AUTH_CONFIG_ENC_KEY is "
            "not set; restore the KEK that sealed it (or clear the stored secret to fall back to env)"
        )

    kek = keys.get(enc_key_id)
    if kek is None:
        raise ProviderSecretDecryptionError(
            f"no KEK configured for enc_key_id={enc_key_id!r}; the key may have been rotated away — "
            "restore it in AUTH_CONFIG_ENC_KEY (or re-seal the stored secret under an active key)"
        )

    blob = bytes(client_secret_encrypted)
    aad = _aad(enc_key_id)
    try:
        wrap_nonce, wrapped_dek, secret_nonce, ciphertext = _parse_blob(blob)
        dek = AESGCM(kek).decrypt(wrap_nonce, wrapped_dek, aad)
        plaintext = AESGCM(dek).decrypt(secret_nonce, ciphertext, aad)
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        # Tampered/foreign blob, wrong key, or corrupt plaintext. Message stays secret-free.
        logger.warning(
            "failed to decrypt stored provider secret (enc_key_id=%s); it may be corrupt or "
            "sealed under a different key",
            enc_key_id,
        )
        raise ProviderSecretDecryptionError(
            f"stored provider secret (enc_key_id={enc_key_id!r}) failed to decrypt; it may be "
            "corrupt or the configured KEK for that id is wrong"
        ) from exc


def needs_reseal(enc_key_id: Optional[str]) -> bool:
    """Return ``True`` when a row sealed under ``enc_key_id`` is not on the active key.

    Used by rotation: a row whose id differs from the active id should be re-sealed. Returns
    ``False`` when there is no stored secret, or encryption is unconfigured/misconfigured (nothing
    meaningful to rotate to).
    """
    if enc_key_id is None:
        return False
    try:
        keys = _load_key_map()
        if not keys:
            return False
        return enc_key_id != _active_key_id(keys)
    except AuthConfigEncryptionError:
        return False


def reseal_provider_secret(
    client_secret_encrypted: Optional[bytes], enc_key_id: Optional[str]
) -> Optional[Tuple[bytes, str]]:
    """Re-seal a stored provider secret under the active KEK (key rotation).

    Decrypts the blob with the key that sealed it, then re-seals the recovered plaintext under the
    active key id. The plaintext exists only transiently in memory.

    Args:
        client_secret_encrypted: The currently-stored ciphertext blob.
        enc_key_id: The id that sealed it.

    Returns:
        A fresh ``(client_secret_encrypted, enc_key_id)`` pair to persist, or ``None`` when there is
        no stored secret to rotate.

    Raises:
        ProviderSecretDecryptionError: If the existing blob cannot be decrypted (missing/wrong KEK or
            corrupt ciphertext) — surfaced loudly so a stuck rotation is visible.
        AuthConfigEncryptionError: If re-sealing fails (e.g. encryption became unconfigured between
            the decrypt and the re-encrypt).
    """
    secret = unseal_provider_secret(client_secret_encrypted, enc_key_id)
    if secret is None:
        return None
    return seal_provider_secret(secret)
