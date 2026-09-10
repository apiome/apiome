"""Envelope encryption-at-rest, shared by every vault Apiome keeps — SDK-4.1 (#4495).

Two features now store a third-party secret that the database must never be able to reconstruct:
the outbound MCP credentials of MCAT-6.2 (:mod:`app.mcp_credential_crypto`) and the npm / PyPI
registry tokens of SDK-4.1 (:mod:`app.sdk_registry_credential_crypto`). They want *the same*
scheme, and two copies of a security-critical primitive agree exactly until one of them is
changed, so the scheme lives here once and each vault is a configured instance of it.

Scheme — *envelope encryption* with AES-256-GCM (Python ``cryptography``):

* A per-secret random **data-encryption key (DEK)** encrypts the JSON payload (AES-256-GCM, random
  96-bit nonce). A fresh DEK per secret means two rows holding the same token still produce
  unrelated ciphertext, and a single DEK never protects more than one short message.
* A long-lived **master key (KEK)**, supplied from the environment, *wraps* (encrypts) that DEK
  (again AES-256-GCM). Only the wrapped DEK and the payload ciphertext are stored — never the DEK
  itself, and never the master key.
* A stored ``key_version`` records *which* master key sealed a row. Several master keys can be
  configured at once, so the active key can be rotated while every older row stays decryptable
  under the version that sealed it. The key-version is also bound into the GCM
  additional-authenticated-data of both encryptions, so a row cannot be silently re-tagged to a
  different version.

**Each vault has its own magic and its own keys.** :attr:`EnvelopeCipher.magic` is four bytes that
open every blob *and* feed the AAD, so a blob sealed by one vault does not authenticate under
another even when both are configured with the same master key. Key material is read through
callables rather than captured at import, so a test (or a rotation) that changes the process
settings takes effect on the next call.

When no keys are configured the server still starts (mirroring the webhook-secret precedent):
secrets simply cannot be sealed (:meth:`EnvelopeCipher.seal` raises, fail-closed) or unsealed
(:meth:`EnvelopeCipher.unseal` returns ``None``, so the caller degrades rather than crashes).

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
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

__all__ = ["EnvelopeCipher", "EnvelopeEncryptionError"]

# Sealed-blob framing. A stored payload is a self-describing byte string:
#
#   MAGIC(4) | FORMAT(1) | wrap_nonce(12) | wrapped_dek(48) | payload_nonce(12) | ciphertext(>=16)
#
# ``wrapped_dek`` is a 32-byte DEK sealed with AES-256-GCM (32 + 16-byte tag = 48). ``ciphertext``
# is the payload sealed with the DEK (plaintext + 16-byte tag). The MAGIC/FORMAT header lets the
# parser reject foreign bytes and lets the format evolve without ambiguity.
_FORMAT_VERSION = 1
_MAGIC_LEN = 4
_NONCE_LEN = 12  # 96-bit GCM nonce (the recommended size)
_KEY_LEN = 32  # AES-256
_GCM_TAG_LEN = 16
_WRAPPED_DEK_LEN = _KEY_LEN + _GCM_TAG_LEN  # 48
_HEADER_LEN = _MAGIC_LEN + 1  # MAGIC + FORMAT byte
# Smallest legal blob: header + wrap nonce + wrapped DEK + payload nonce + an empty payload's tag.
_MIN_BLOB_LEN = _HEADER_LEN + _NONCE_LEN + _WRAPPED_DEK_LEN + _NONCE_LEN + _GCM_TAG_LEN


class EnvelopeEncryptionError(RuntimeError):
    """Raised when a secret cannot be sealed.

    Causes: encryption is not configured (no master key), the key map is malformed, the requested
    active key-version has no key, or the payload is not JSON-serialisable. The message never
    contains secret material — only the non-secret cause — so it is safe to log and surface.
    """


@dataclass(frozen=True)
class EnvelopeCipher:
    """One configured vault: a magic, a key map, and an active key-version.

    Attributes:
        magic: Exactly four ASCII bytes opening every blob this vault seals, and part of the AAD.
            Two vaults must not share one, so a blob cannot be moved between them.
        subject: Human label for log lines and error messages (e.g. ``"MCP credential"``).
        keys_setting: The environment variable the key map comes from. Named in error messages so
            an operator is told exactly what to configure.
        read_keys: Returns the raw key-map value (a JSON object mapping version to base64 key), or
            ``None`` when unset. A callable rather than a value so settings changes take effect.
        read_active_version: Returns the configured active key-version, or ``None`` to use the
            highest version present.
    """

    magic: bytes
    subject: str
    keys_setting: str
    read_keys: Callable[[], Optional[str]]
    read_active_version: Callable[[], Optional[int]]

    def __post_init__(self) -> None:
        """Reject a misconfigured vault at construction rather than at first use.

        Raises:
            ValueError: If ``magic`` is not exactly four bytes.
        """
        if len(self.magic) != _MAGIC_LEN:
            raise ValueError(
                f"envelope magic must be exactly {_MAGIC_LEN} bytes, got {len(self.magic)}"
            )

    # -------------------------------------------------------------------------------------
    # Key material
    # -------------------------------------------------------------------------------------

    def _decode_master_key(self, b64: str, version: int) -> bytes:
        """Decode one base64 master key, requiring exactly 32 bytes (AES-256).

        Accepts both standard and URL-safe base64. The version appears only in the (non-secret)
        error message; the key bytes themselves are never logged.

        Args:
            b64: The configured base64 key.
            version: The key-version it was configured under.

        Returns:
            The 32 raw key bytes.

        Raises:
            EnvelopeEncryptionError: If the value is not base64 or does not decode to 32 bytes.
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
            raise EnvelopeEncryptionError(
                f"master key for version {version} is not valid base64"
            )
        if len(raw) != _KEY_LEN:
            raise EnvelopeEncryptionError(
                f"master key for version {version} must decode to {_KEY_LEN} bytes (AES-256), "
                f"got {len(raw)}"
            )
        return raw

    def load_key_map(self) -> Dict[int, bytes]:
        """Parse the configured key map into ``{version: 32-byte key}`` (empty when unconfigured).

        Returns:
            Every configured master key by version. Empty when nothing is configured, which is a
            supported state: the server starts and simply cannot seal or unseal.

        Raises:
            EnvelopeEncryptionError: If the value is present but malformed (not JSON, not an
                object, a non-integer version, or a key that is not a 32-byte base64 string).
        """
        raw = self.read_keys()
        if not raw or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EnvelopeEncryptionError(f"{self.keys_setting} is not valid JSON") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise EnvelopeEncryptionError(
                f"{self.keys_setting} must be a non-empty JSON object "
                'mapping version to base64 key, e.g. {"1": "<base64 key>"}'
            )
        keys: Dict[int, bytes] = {}
        for version_str, value in parsed.items():
            try:
                version = int(version_str)
            except (TypeError, ValueError) as exc:
                raise EnvelopeEncryptionError(
                    f"key-version {version_str!r} is not an integer"
                ) from exc
            if version < 1:
                raise EnvelopeEncryptionError(
                    f"key-version {version} is invalid; versions must be >= 1"
                )
            if not isinstance(value, str):
                raise EnvelopeEncryptionError(
                    f"master key for version {version} must be a base64 string"
                )
            keys[version] = self._decode_master_key(value, version)
        return keys

    def active_key_version(self, keys: Mapping[int, bytes]) -> int:
        """Return the key-version new secrets are sealed under.

        Args:
            keys: The parsed key map; must be non-empty.

        Returns:
            The configured active version, or the highest version present when none is configured.

        Raises:
            EnvelopeEncryptionError: If a version is configured but absent from the key map.
        """
        configured = self.read_active_version()
        if configured is not None:
            if configured not in keys:
                raise EnvelopeEncryptionError(
                    f"active key-version {configured} has no configured master key"
                )
            return configured
        return max(keys)

    def configured(self) -> bool:
        """Return ``True`` when at least one master key is configured and parseable."""
        try:
            return bool(self.load_key_map())
        except EnvelopeEncryptionError:
            return False

    def validate(self) -> None:
        """Validate the configured key map at startup; raise if present but misconfigured.

        No keys configured is acceptable (the server starts; secrets cannot be sealed/unsealed).
        If keys ARE configured they must all parse and the active version must resolve — otherwise
        fail fast so a misconfiguration surfaces at boot, not at the first write.

        Raises:
            EnvelopeEncryptionError: If the key map is present but malformed, or the active version
                is absent from it.
        """
        keys = self.load_key_map()
        if not keys:
            return
        self.active_key_version(keys)

    def _aad(self, version: int) -> bytes:
        """Additional authenticated data binding a sealed blob to this vault and key-version.

        Feeding this into both GCM operations means a blob sealed under version *N* will not
        authenticate if presented as version *M*, and a blob from another vault will not
        authenticate here — a row cannot be silently re-pointed at a different key or vault.

        Args:
            version: The key-version sealing (or opening) the blob.

        Returns:
            The AAD bytes.
        """
        return f"{self.magic.decode('ascii')}:v{version}".encode("ascii")

    # -------------------------------------------------------------------------------------
    # Seal / unseal
    # -------------------------------------------------------------------------------------

    def seal(self, payload: Mapping[str, Any]) -> Tuple[bytes, int]:
        """Seal a plaintext payload for storage (envelope-encrypt under the active key).

        Args:
            payload: The plaintext payload (e.g. ``{"token": "..."}``); must be JSON-serialisable.

        Returns:
            An ``(encrypted_payload, key_version)`` pair: the self-describing ciphertext blob to
            store, and the master-key version that sealed it (store alongside).

        Raises:
            EnvelopeEncryptionError: If encryption is not configured, the key map is malformed, or
                the payload is not JSON-serialisable.
        """
        keys = self.load_key_map()
        if not keys:
            raise EnvelopeEncryptionError(
                f"{self.subject} encryption is not configured; set {self.keys_setting} before "
                "storing a secret"
            )
        version = self.active_key_version(keys)
        master = keys[version]
        aad = self._aad(version)

        try:
            plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise EnvelopeEncryptionError(
                f"{self.subject} payload is not JSON-serialisable"
            ) from exc

        dek = AESGCM.generate_key(bit_length=_KEY_LEN * 8)
        payload_nonce = os.urandom(_NONCE_LEN)
        ciphertext = AESGCM(dek).encrypt(payload_nonce, plaintext, aad)

        wrap_nonce = os.urandom(_NONCE_LEN)
        wrapped_dek = AESGCM(master).encrypt(wrap_nonce, dek, aad)

        blob = b"".join(
            (
                self.magic,
                bytes((_FORMAT_VERSION,)),
                wrap_nonce,
                wrapped_dek,
                payload_nonce,
                ciphertext,
            )
        )
        return blob, version

    def _parse_blob(self, blob: bytes) -> Tuple[bytes, bytes, bytes, bytes]:
        """Split a sealed blob into ``(wrap_nonce, wrapped_dek, payload_nonce, ciphertext)``.

        Args:
            blob: The stored bytes.

        Returns:
            The four framed segments.

        Raises:
            ValueError: If the blob is too short, lacks this vault's magic, or carries an unknown
                format version.
        """
        if len(blob) < _MIN_BLOB_LEN:
            raise ValueError("sealed secret is shorter than the minimum envelope length")
        if blob[:_MAGIC_LEN] != self.magic:
            raise ValueError("sealed secret has an unrecognised header")
        if blob[_MAGIC_LEN] != _FORMAT_VERSION:
            raise ValueError(f"sealed secret has unsupported format version {blob[_MAGIC_LEN]}")
        offset = _HEADER_LEN
        wrap_nonce = blob[offset : offset + _NONCE_LEN]
        offset += _NONCE_LEN
        wrapped_dek = blob[offset : offset + _WRAPPED_DEK_LEN]
        offset += _WRAPPED_DEK_LEN
        payload_nonce = blob[offset : offset + _NONCE_LEN]
        offset += _NONCE_LEN
        ciphertext = blob[offset:]
        return wrap_nonce, wrapped_dek, payload_nonce, ciphertext

    def unseal(
        self, encrypted_payload: Optional[bytes], key_version: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """Unseal a stored blob back into its plaintext payload (in-memory, at use time).

        Best-effort and fail-safe: any problem — encryption not configured, no key for the row's
        version, a tampered/foreign/wrong-version blob, or non-object plaintext — returns ``None``
        rather than raising, so a caller degrades instead of crashing.

        Args:
            encrypted_payload: The stored ciphertext blob (``bytes`` or ``memoryview``), or
                ``None``.
            key_version: The master-key version that sealed the blob, or ``None``.

        Returns:
            The decrypted payload dict, or ``None`` when no plaintext can be produced.
        """
        if not encrypted_payload or key_version is None:
            return None

        try:
            keys = self.load_key_map()
        except EnvelopeEncryptionError:
            logger.warning(
                "%s encryption is misconfigured; cannot decrypt (key_version=%s)",
                self.subject,
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
                "no %s master key configured for key_version=%s; cannot decrypt",
                self.subject,
                version,
            )
            return None

        blob = bytes(encrypted_payload)
        aad = self._aad(version)
        try:
            wrap_nonce, wrapped_dek, payload_nonce, ciphertext = self._parse_blob(blob)
            dek = AESGCM(master).decrypt(wrap_nonce, wrapped_dek, aad)
            plaintext = AESGCM(dek).decrypt(payload_nonce, ciphertext, aad)
            decoded = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, UnicodeDecodeError):
            # Tampered/foreign/wrong-version blob, or corrupt plaintext. Message stays secret-free.
            logger.warning(
                "failed to decrypt %s (key_version=%s); the stored secret may be corrupt or "
                "sealed under a different key",
                self.subject,
                version,
            )
            return None
        if not isinstance(decoded, dict):
            logger.warning(
                "decrypted %s (key_version=%s) is not a JSON object; ignoring",
                self.subject,
                version,
            )
            return None
        return decoded

    def needs_reseal(self, key_version: Optional[int]) -> bool:
        """Return ``True`` when a row sealed under ``key_version`` is not on the active key.

        Used by rotation: a row whose version differs from the active version should be re-sealed.

        Args:
            key_version: The version that sealed the row.

        Returns:
            ``False`` when encryption is unconfigured/misconfigured or the version is unknown —
            there is nothing meaningful to rotate to.
        """
        if key_version is None:
            return False
        try:
            keys = self.load_key_map()
        except EnvelopeEncryptionError:
            return False
        if not keys:
            return False
        try:
            return int(key_version) != self.active_key_version(keys)
        except (TypeError, ValueError):
            return False

    def reseal(
        self, encrypted_payload: Optional[bytes], key_version: Optional[int]
    ) -> Optional[Tuple[bytes, int]]:
        """Re-seal a stored blob under the active key (key rotation).

        Decrypts the blob with the key that sealed it, then re-seals the recovered plaintext under
        the active key-version. The plaintext exists only transiently in memory.

        Args:
            encrypted_payload: The currently-stored ciphertext blob.
            key_version: The version that sealed it.

        Returns:
            A fresh ``(encrypted_payload, key_version)`` pair to persist, or ``None`` when the
            existing blob cannot be decrypted (nothing to rotate).

        Raises:
            EnvelopeEncryptionError: If re-sealing fails (e.g. encryption became unconfigured
                between the decrypt and the re-encrypt).
        """
        payload = self.unseal(encrypted_payload, key_version)
        if payload is None:
            return None
        return self.seal(payload)
