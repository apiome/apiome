"""Envelope encryption-at-rest for outbound MCP credentials (MCAT-6.2, #3678).

A protected MCP server is reached by holding a secret (a bearer token, a custom-header value, an
OAuth2 token set, …). That secret is persisted in ``odb.mcp_endpoint_credentials.encrypted_payload``
as **ciphertext only** (V129); this module is the single place the plaintext is sealed before it is
written and unsealed in-memory at connect time. The database never sees, and cannot reconstruct, a
token.

Scheme — *envelope encryption* with AES-256-GCM (Python ``cryptography``):

* A per-secret random **data-encryption key (DEK)** encrypts the JSON payload (AES-256-GCM, random
  96-bit nonce). A fresh DEK per secret means two endpoints holding the same token still produce
  unrelated ciphertext, and a single DEK never protects more than one short message.
* A long-lived **master key (KEK)**, supplied from the environment, *wraps* (encrypts) that DEK
  (again AES-256-GCM). Only the wrapped DEK and the payload ciphertext are stored — never the DEK
  itself, and never the master key.
* The DB column ``key_version`` records *which* master key sealed a row. Several master keys can be
  configured at once, so the active key can be rotated while every older row stays decryptable under
  the version that sealed it. The key-version is also bound into the GCM additional-authenticated-data
  of both encryptions, so a row cannot be silently re-tagged to a different version.

Key configuration (environment):

* ``OBJECTIFIED_MCP_CREDENTIAL_ENCRYPTION_KEYS`` — a JSON object mapping an integer key-version to a
  base64-encoded 32-byte (AES-256) master key, e.g. ``{"1": "<base64 key>", "2": "<base64 key>"}``.
  Generate a key with::

      python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

* ``OBJECTIFIED_MCP_CREDENTIAL_ACTIVE_KEY_VERSION`` — which version new secrets are sealed under.
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

import base64
import binascii
import json
import logging
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

logger = logging.getLogger(__name__)

# Sealed-blob framing. The stored ``encrypted_payload`` is a self-describing byte string:
#
#   MAGIC(4) | FORMAT(1) | wrap_nonce(12) | wrapped_dek(48) | payload_nonce(12) | ciphertext(>=16)
#
# ``wrapped_dek`` is a 32-byte DEK sealed with AES-256-GCM (32 + 16-byte tag = 48). ``ciphertext`` is
# the payload sealed with the DEK (plaintext + 16-byte tag). The MAGIC/FORMAT header lets the parser
# reject foreign bytes and lets the format evolve without ambiguity.
_MAGIC = b"OMCV"  # Objectified MCP Credential Vault
_FORMAT_VERSION = 1
_NONCE_LEN = 12  # 96-bit GCM nonce (the recommended size)
_KEY_LEN = 32  # AES-256
_GCM_TAG_LEN = 16
_WRAPPED_DEK_LEN = _KEY_LEN + _GCM_TAG_LEN  # 48
_HEADER_LEN = len(_MAGIC) + 1  # MAGIC + FORMAT byte
# Smallest legal blob: header + wrap nonce + wrapped DEK + payload nonce + an empty payload's GCM tag.
_MIN_BLOB_LEN = _HEADER_LEN + _NONCE_LEN + _WRAPPED_DEK_LEN + _NONCE_LEN + _GCM_TAG_LEN


class CredentialEncryptionError(RuntimeError):
    """Raised when a credential cannot be sealed.

    Causes: encryption is not configured (no master key), the key map is malformed, the requested
    active key-version has no key, or the payload is not JSON-serialisable. The message never
    contains secret material — only the non-secret cause — so it is safe to log and surface.
    """


def _decode_master_key(b64: str, version: int) -> bytes:
    """Decode one base64 master key, requiring exactly 32 bytes (AES-256).

    Accepts both standard and URL-safe base64. The version appears only in the (non-secret) error
    message; the key bytes themselves are never logged.
    """
    candidate = b64.strip()
    raw: Optional[bytes] = None
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(candidate)
            break
        except (binascii.Error, ValueError):
            continue
    if raw is None:
        raise CredentialEncryptionError(
            f"master key for version {version} is not valid base64"
        )
    if len(raw) != _KEY_LEN:
        raise CredentialEncryptionError(
            f"master key for version {version} must decode to {_KEY_LEN} bytes (AES-256), "
            f"got {len(raw)}"
        )
    return raw


def _load_key_map() -> Dict[int, bytes]:
    """Parse the configured key map into ``{version: 32-byte key}`` (empty when unconfigured).

    Raises:
        CredentialEncryptionError: If the env value is present but malformed (not JSON, not an
            object, a non-integer version, or a key that is not a 32-byte base64 string).
    """
    raw = settings.mcp_credential_encryption_keys
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialEncryptionError(
            "OBJECTIFIED_MCP_CREDENTIAL_ENCRYPTION_KEYS is not valid JSON"
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise CredentialEncryptionError(
            "OBJECTIFIED_MCP_CREDENTIAL_ENCRYPTION_KEYS must be a non-empty JSON object "
            'mapping version to base64 key, e.g. {"1": "<base64 key>"}'
        )
    keys: Dict[int, bytes] = {}
    for version_str, value in parsed.items():
        try:
            version = int(version_str)
        except (TypeError, ValueError) as exc:
            raise CredentialEncryptionError(
                f"key-version {version_str!r} is not an integer"
            ) from exc
        if version < 1:
            raise CredentialEncryptionError(
                f"key-version {version} is invalid; versions must be >= 1"
            )
        if not isinstance(value, str):
            raise CredentialEncryptionError(
                f"master key for version {version} must be a base64 string"
            )
        keys[version] = _decode_master_key(value, version)
    return keys


def _active_key_version(keys: Mapping[int, bytes]) -> int:
    """Return the key-version new secrets are sealed under (configured, or the highest present).

    Raises:
        CredentialEncryptionError: If a version is configured but absent from the key map.
    """
    configured = settings.mcp_credential_active_key_version
    if configured is not None:
        if configured not in keys:
            raise CredentialEncryptionError(
                f"active key-version {configured} has no configured master key"
            )
        return configured
    return max(keys)


def _aad(version: int) -> bytes:
    """Additional authenticated data binding a sealed blob to its key-version.

    Feeding this into both GCM operations means a blob sealed under version *N* will not authenticate
    if presented as version *M* — a row cannot be silently re-pointed at a different key.
    """
    return f"{_MAGIC.decode('ascii')}:v{version}".encode("ascii")


def credential_encryption_configured() -> bool:
    """Return ``True`` when at least one master key is configured and parseable."""
    try:
        return bool(_load_key_map())
    except CredentialEncryptionError:
        return False


def validate_credential_encryption_keys() -> None:
    """Validate the configured key map at startup; raise if it is present but misconfigured.

    No keys configured is acceptable (the server starts; secrets cannot be sealed/unsealed). If keys
    ARE configured they must all parse and the active version must resolve — otherwise fail fast so a
    misconfiguration surfaces at boot, not at the first connect attempt.

    Raises:
        CredentialEncryptionError: If the key map is present but malformed, or the active version is
            absent from it.
    """
    keys = _load_key_map()
    if not keys:
        return
    _active_key_version(keys)


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
    keys = _load_key_map()
    if not keys:
        raise CredentialEncryptionError(
            "MCP credential encryption is not configured; set "
            "OBJECTIFIED_MCP_CREDENTIAL_ENCRYPTION_KEYS before storing a secret"
        )
    version = _active_key_version(keys)
    master = keys[version]
    aad = _aad(version)

    try:
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CredentialEncryptionError("credential payload is not JSON-serialisable") from exc

    dek = AESGCM.generate_key(bit_length=_KEY_LEN * 8)
    payload_nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(dek).encrypt(payload_nonce, plaintext, aad)

    wrap_nonce = os.urandom(_NONCE_LEN)
    wrapped_dek = AESGCM(master).encrypt(wrap_nonce, dek, aad)

    blob = b"".join(
        (
            _MAGIC,
            bytes((_FORMAT_VERSION,)),
            wrap_nonce,
            wrapped_dek,
            payload_nonce,
            ciphertext,
        )
    )
    return blob, version


def _parse_blob(blob: bytes) -> Tuple[bytes, bytes, bytes, bytes]:
    """Split a sealed blob into ``(wrap_nonce, wrapped_dek, payload_nonce, ciphertext)``.

    Raises:
        ValueError: If the blob is too short, lacks the magic header, or carries an unknown format
            version.
    """
    if len(blob) < _MIN_BLOB_LEN:
        raise ValueError("sealed credential is shorter than the minimum envelope length")
    if blob[: len(_MAGIC)] != _MAGIC:
        raise ValueError("sealed credential has an unrecognised header")
    if blob[len(_MAGIC)] != _FORMAT_VERSION:
        raise ValueError(f"sealed credential has unsupported format version {blob[len(_MAGIC)]}")
    offset = _HEADER_LEN
    wrap_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    wrapped_dek = blob[offset : offset + _WRAPPED_DEK_LEN]
    offset += _WRAPPED_DEK_LEN
    payload_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ciphertext = blob[offset:]
    return wrap_nonce, wrapped_dek, payload_nonce, ciphertext


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
    if not encrypted_payload or key_version is None:
        return None

    try:
        keys = _load_key_map()
    except CredentialEncryptionError:
        logger.warning(
            "MCP credential encryption is misconfigured; cannot decrypt credential "
            "(key_version=%s)",
            key_version,
        )
        return None
    if not keys:
        return None

    try:
        version = int(key_version)
    except (TypeError, ValueError):
        return None
    master = keys.get(version)
    if master is None:
        logger.warning(
            "no MCP credential master key configured for key_version=%s; cannot decrypt",
            version,
        )
        return None

    blob = bytes(encrypted_payload)
    aad = _aad(version)
    try:
        wrap_nonce, wrapped_dek, payload_nonce, ciphertext = _parse_blob(blob)
        dek = AESGCM(master).decrypt(wrap_nonce, wrapped_dek, aad)
        plaintext = AESGCM(dek).decrypt(payload_nonce, ciphertext, aad)
        decoded = json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, ValueError, UnicodeDecodeError):
        # Tampered/foreign/wrong-version blob, or corrupt plaintext. Message stays secret-free.
        logger.warning(
            "failed to decrypt MCP credential (key_version=%s); the stored secret may be "
            "corrupt or sealed under a different key",
            version,
        )
        return None
    if not isinstance(decoded, dict):
        logger.warning(
            "decrypted MCP credential (key_version=%s) is not a JSON object; ignoring",
            version,
        )
        return None
    return decoded


def needs_reseal(key_version: Optional[int]) -> bool:
    """Return ``True`` when a row sealed under ``key_version`` is not on the active key.

    Used by rotation: a row whose version differs from the active version should be re-sealed.
    Returns ``False`` when encryption is unconfigured/misconfigured or the version is unknown (there
    is nothing meaningful to rotate to).
    """
    if key_version is None:
        return False
    try:
        keys = _load_key_map()
    except CredentialEncryptionError:
        return False
    if not keys:
        return False
    try:
        return int(key_version) != _active_key_version(keys)
    except (TypeError, ValueError):
        return False


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
    payload = unseal_credential_payload(encrypted_payload, key_version)
    if payload is None:
        return None
    return seal_credential_payload(payload)
