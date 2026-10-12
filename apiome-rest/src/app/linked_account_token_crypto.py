"""Envelope encryption-at-rest for linked-account tokens (OLO-7.3 follow-up, #4960).

A linked account (``apiome.external_auth_providers``, V010) holds the OAuth access / refresh token
a provider issued at sign-in, or a personal access token the user pasted in. Those are live
credentials to the user's external repositories, so they are stored as **ciphertext only**: a
database read (backup leak, replica, SQL injection) must not yield a usable token.

**The scheme itself lives in :mod:`app.envelope_crypto`** — AES-256-GCM envelope encryption with a
per-secret data key wrapped by a versioned master key. This module is that primitive configured for
linked-account tokens (magic ``OLAT``), plus the *string* form the token columns hold.

**Two services share this vault.** apiome-ui seals a token when it writes the row
(``apiome-ui/lib/auth/linked-account-token-crypto.ts`` is a byte-compatible port of this module)
and apiome-rest unseals it when it calls the provider. Both must therefore be given the same key
map; the cross-language fixtures in ``tests/fixtures/linked_account_token_vectors.json`` pin the
format on both sides.

Stored form — the columns stay ``TEXT`` and a sealed value is self-describing::

    enc:v1:<key_version>:<base64(envelope blob)>

``enc:v1`` is the string format, ``key_version`` names the master key that sealed the blob, and the
blob's plaintext is the JSON object ``{"token": "<the token>"}``. A value *without* the prefix is a
**legacy plaintext** token written before V275: :func:`unseal_token` returns it unchanged so an
upgraded deployment keeps working, and :func:`seal_plaintext_tokens`
(``python -m app.seal_linked_account_tokens``) converts those rows.

Key configuration (environment, identical in apiome-ui and apiome-rest):

* ``APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS`` — a JSON object mapping an integer key-version to
  a base64-encoded 32-byte (AES-256) master key, e.g. ``{"1": "<base64 key>"}``. Generate a key
  with::

      python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

* ``APIOME_LINKED_ACCOUNT_TOKEN_ACTIVE_KEY_VERSION`` — which version new tokens are sealed under.
  Optional; defaults to the highest version present. To rotate: add a new (higher) version to the
  map in both services, then run ``python -m app.seal_linked_account_tokens`` to re-seal existing rows.

Failure policy:

* **Sealing fails closed.** With no key configured :func:`seal_token` raises — a token is never
  written in plaintext as a fallback.
* **Unsealing fails safe.** A sealed value that cannot be opened (no key, key rotated away,
  tampered) yields ``None`` — "no token" — never the ciphertext, so a caller can only ever send a
  provider a real token or nothing.
* **Secrets never logged.** Log lines carry only the key-version and the shape of the failure.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Dict, Optional, Tuple

from .config import settings
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError

logger = logging.getLogger(__name__)

__all__ = [
    "KEYS_SETTING",
    "SEALED_PREFIX",
    "LinkedAccountTokenEncryptionError",
    "is_sealed",
    "linked_account_token_encryption_configured",
    "needs_reseal",
    "seal_plaintext_tokens",
    "seal_token",
    "unseal_token",
    "validate_linked_account_token_keys",
]

#: The environment variable both services read the key map from.
KEYS_SETTING = "APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS"

#: Opens every sealed column value. No provider issues a token beginning with it, so its presence
#: is what tells a sealed value from a legacy plaintext one.
SEALED_PREFIX = "enc:v1:"

#: The single key of the sealed JSON payload.
_PAYLOAD_KEY = "token"

#: Raised when a token cannot be sealed (encryption not configured, or the key map is malformed).
#: The message never contains secret material. An alias of the shared envelope error so a caller
#: may catch either name.
LinkedAccountTokenEncryptionError = EnvelopeEncryptionError

#: The linked-account token vault. ``OLAT`` = *OAuth Linked-Account Token* — the magic opening every
#: blob and part of the AAD, so a blob cannot be moved to (or from) another vault.
_CIPHER = EnvelopeCipher(
    magic=b"OLAT",
    subject="linked-account token",
    keys_setting=KEYS_SETTING,
    read_keys=lambda: settings.linked_account_token_encryption_keys,
    read_active_version=lambda: settings.linked_account_token_active_key_version,
)


def linked_account_token_encryption_configured() -> bool:
    """Return ``True`` when at least one master key is configured and parseable."""
    return _CIPHER.configured()


def validate_linked_account_token_keys() -> None:
    """Validate the configured key map at startup; raise if it is present but misconfigured.

    No keys configured is acceptable — the server starts, legacy plaintext rows still read, and
    sealed rows read as "no token". If keys ARE configured they must all parse and the active
    version must resolve, so a misconfiguration surfaces at boot rather than at the first scan.

    Raises:
        LinkedAccountTokenEncryptionError: If the key map is present but malformed, or the active
            version is absent from it.
    """
    _CIPHER.validate()


def is_sealed(value: Optional[str]) -> bool:
    """Return ``True`` when a stored column value is in the sealed ``enc:v1:`` form.

    Args:
        value: The raw column value, or ``None``.

    Returns:
        ``True`` for a sealed value; ``False`` for ``None``, an empty string or legacy plaintext.
    """
    return isinstance(value, str) and value.startswith(SEALED_PREFIX)


def _split_sealed(value: str) -> Optional[Tuple[int, bytes]]:
    """Split a sealed column value into ``(key_version, envelope blob)``.

    Args:
        value: A column value that :func:`is_sealed` accepted.

    Returns:
        The key-version and the decoded blob, or ``None`` when the value is malformed (a
        non-integer version, or a body that is not base64).
    """
    version_text, separator, body = value[len(SEALED_PREFIX) :].partition(":")
    if not separator or not version_text.isdigit():
        return None
    try:
        blob = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        return None
    return int(version_text), blob


def seal_token(token: str) -> str:
    """Seal a plaintext token into the string stored in a token column.

    Args:
        token: The plaintext OAuth token or personal access token. Must be a non-empty string.

    Returns:
        The sealed ``enc:v1:<key_version>:<base64>`` value to store.

    Raises:
        LinkedAccountTokenEncryptionError: If encryption is not configured or the key map is
            malformed. The caller must not fall back to storing the plaintext.
        ValueError: If ``token`` is not a non-empty string.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    blob, version = _CIPHER.seal({_PAYLOAD_KEY: token})
    return f"{SEALED_PREFIX}{version}:{base64.b64encode(blob).decode('ascii')}"


def unseal_token(value: Optional[str]) -> Optional[str]:
    """Return the plaintext token a stored column value represents.

    Args:
        value: The raw column value: sealed, legacy plaintext, empty or ``None``.

    Returns:
        The plaintext token; ``None`` when there is no token or a sealed value cannot be opened
        (encryption not configured, no key for its version, tampered or malformed). A legacy
        plaintext value is returned unchanged. The ciphertext itself is never returned.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    if not is_sealed(value):
        return value
    parts = _split_sealed(value)
    if parts is None:
        logger.warning("stored linked-account token is malformed; treating it as absent")
        return None
    version, blob = parts
    payload = _CIPHER.unseal(blob, version)
    token = payload.get(_PAYLOAD_KEY) if payload else None
    return token if isinstance(token, str) and token else None


def needs_reseal(value: Optional[str]) -> bool:
    """Return ``True`` when a stored value should be (re-)sealed under the active key.

    Args:
        value: The raw column value.

    Returns:
        ``True`` for legacy plaintext and for a value sealed under a non-active key-version.
        ``False`` for ``None`` / empty, for a value already on the active key, for a malformed
        sealed value, and whenever encryption is not configured (there is nothing to seal with).
    """
    if not isinstance(value, str) or not value.strip():
        return False
    if not _CIPHER.configured():
        return False
    if not is_sealed(value):
        return True
    parts = _split_sealed(value)
    return parts is not None and _CIPHER.needs_reseal(parts[0])


# -------------------------------------------------------------------------------------------
# Backfill / rotation
# -------------------------------------------------------------------------------------------

#: The token columns of ``apiome.external_auth_providers``.
_TOKEN_COLUMNS = ("access_token", "refresh_token")

_SELECT_BATCH = """
    SELECT id, access_token, refresh_token
    FROM apiome.external_auth_providers
    WHERE (%s::uuid IS NULL OR id > %s::uuid)
      AND (access_token IS NOT NULL OR refresh_token IS NOT NULL)
    ORDER BY id
    LIMIT %s
"""


def seal_plaintext_tokens(
    database: Any, *, dry_run: bool = False, batch_size: int = 200
) -> Dict[str, int]:
    """Seal every legacy plaintext token, and re-seal tokens on an old key (backfill / rotation).

    Walks ``apiome.external_auth_providers`` in id order. A column is rewritten when
    :func:`needs_reseal` says so; each rewrite is a compare-and-set on the value that was read, so
    a token the user replaces mid-run is never overwritten by a stale one. Idempotent — a second
    run finds nothing to do.

    Args:
        database: The apiome-rest database handle (``execute_query`` / ``_execute_write``).
        dry_run: When ``True``, count what would change and write nothing.
        batch_size: Rows read per round trip; clamped to at least 1.

    Returns:
        Counts only, never token material: ``rows_scanned``; ``tokens_sealed`` (legacy plaintext
        converted); ``tokens_resealed`` (moved to the active key); ``tokens_unreadable`` (sealed
        values no configured key opens — left untouched); ``tokens_skipped`` (changed by someone
        else between the read and the write).

    Raises:
        LinkedAccountTokenEncryptionError: If encryption is not configured or misconfigured.
    """
    validate_linked_account_token_keys()
    if not linked_account_token_encryption_configured():
        raise LinkedAccountTokenEncryptionError(
            f"linked-account token encryption is not configured; set {KEYS_SETTING} first"
        )
    limit = max(1, int(batch_size or 1))
    summary = {
        "rows_scanned": 0,
        "tokens_sealed": 0,
        "tokens_resealed": 0,
        "tokens_unreadable": 0,
        "tokens_skipped": 0,
    }
    cursor_id: Optional[str] = None
    while True:
        rows = database.execute_query(_SELECT_BATCH, (cursor_id, cursor_id, limit))
        if not rows:
            return summary
        for row in rows:
            summary["rows_scanned"] += 1
            for column in _TOKEN_COLUMNS:
                _reseal_column(database, row, column, summary, dry_run=dry_run)
        cursor_id = str(rows[-1]["id"])


def _reseal_column(
    database: Any, row: Any, column: str, summary: Dict[str, int], *, dry_run: bool
) -> None:
    """Seal or re-seal one token column of one row, updating ``summary`` in place.

    Args:
        database: The apiome-rest database handle.
        row: The row read by :data:`_SELECT_BATCH`.
        column: One of :data:`_TOKEN_COLUMNS` (a fixed identifier, never caller input).
        summary: The running counts returned by :func:`seal_plaintext_tokens`.
        dry_run: When ``True``, count the change without writing it.
    """
    stored = row.get(column)
    if not isinstance(stored, str) or not stored.strip():
        return
    was_sealed = is_sealed(stored)
    if not needs_reseal(stored):
        if was_sealed and unseal_token(stored) is None:
            summary["tokens_unreadable"] += 1
        return
    token = unseal_token(stored)
    if token is None:
        summary["tokens_unreadable"] += 1
        return
    counter = "tokens_resealed" if was_sealed else "tokens_sealed"
    if dry_run:
        summary[counter] += 1
        return
    updated = database._execute_write(
        f"UPDATE apiome.external_auth_providers SET {column} = %s "
        f"WHERE id = %s::uuid AND {column} = %s",
        (seal_token(token), str(row["id"]), stored),
    )
    summary[counter if updated else "tokens_skipped"] += 1
