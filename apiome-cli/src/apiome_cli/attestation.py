"""Offline verification of Apiome lint gate attestations (CLX-4.2, #4860).

A lint gate attestation is an in-toto Statement v1 wrapped in a DSSE envelope, HMAC-SHA256
signed over the DSSE PAEv1 encoding of the payload. Verification is symmetric: any holder of
the shared signing secret can verify with the standard library alone — no network, no server.

This module is a deliberate lockstep mirror of the server-side signer
(``apiome-rest/src/app/lint_attestation.py``); the PAE encoding, payload type, and HMAC
construction must stay identical on both sides.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Mapping, Optional

#: DSSE payload type for in-toto statements — must match the server-side signer.
PAYLOAD_TYPE = "application/vnd.in-toto+json"


def _pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding v1: ``DSSEv1 <len> <type> <len> <payload>``."""
    type_bytes = payload_type.encode("utf-8")
    return b" ".join(
        [
            b"DSSEv1",
            str(len(type_bytes)).encode("ascii"),
            type_bytes,
            str(len(payload)).encode("ascii"),
            payload,
        ]
    )


def verify_attestation_envelope(envelope: Mapping[str, Any], secret: str) -> bool:
    """Verify a DSSE envelope's HMAC-SHA256 signature against the shared secret.

    Args:
        envelope: The parsed attestation JSON (``payloadType`` / ``payload`` / ``signatures``).
        secret: The shared HMAC secret (``APIOME_LINT_ATTESTATION_SIGNING_SECRET`` server-side).

    Returns:
        ``True`` when at least one signature verifies; ``False`` for missing/invalid
        signatures, wrong payload type, or undecodable payloads (never raises).
    """
    if not secret or not isinstance(envelope, Mapping):
        return False
    if envelope.get("payloadType") != PAYLOAD_TYPE:
        return False
    try:
        payload = base64.b64decode(str(envelope.get("payload") or ""), validate=True)
    except Exception:  # noqa: BLE001 - malformed payloads are just unverifiable
        return False
    expected = hmac.new(
        secret.encode("utf-8"), _pae(PAYLOAD_TYPE, payload), hashlib.sha256
    ).hexdigest()
    for signature in envelope.get("signatures") or []:
        if not isinstance(signature, Mapping):
            continue
        if hmac.compare_digest(str(signature.get("sig") or ""), expected):
            return True
    return False


def attestation_statement(envelope: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Decode the in-toto statement carried by a DSSE envelope (no verification).

    Args:
        envelope: The parsed attestation JSON.

    Returns:
        The statement dict, or ``None`` when the payload cannot be decoded.
    """
    try:
        payload = base64.b64decode(str(envelope.get("payload") or ""), validate=True)
        statement = json.loads(payload.decode("utf-8"))
    except Exception:  # noqa: BLE001 - malformed payloads have no statement
        return None
    return statement if isinstance(statement, dict) else None
