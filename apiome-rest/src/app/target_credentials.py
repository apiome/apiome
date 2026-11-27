"""Turning a verification target's credential reference into request headers — PFX-6.5 (#6957).

A target names where its credential lives (:class:`~app.verification_target.TargetAuthReference`):
an environment variable, a row of the MCP credential vault (``stored``) or, since PFX-6.5, a
workspace secret (``secret``). Every runner — the contract runner, provider verification, the Pact
verifier and Arazzo workflow runs — needs the same three steps: open what the reference points at,
then present it with the target's scheme. :func:`target_auth_headers` is those steps, once.

The opened value lives only in the returned headers, for the run; nothing here logs or stores it.
A workspace secret resolves only within the target's own tenant.
"""

from __future__ import annotations

from typing import Dict, Optional

from .contract_runner import AuthResolutionError, materialize_auth_headers
from .database import db
from .mcp_credentials import load_endpoint_auth_headers
from .pact_secret import PactSecretError
from .pact_secret_store import resolve_secrets
from .verification_target import AUTH_KIND_SECRET, AUTH_KIND_STORED, TargetAuthReference

__all__ = ["target_auth_headers"]


def target_auth_headers(tenant_id: str, auth: TargetAuthReference) -> Dict[str, str]:
    """Open a target's credential and return the headers every request of a run carries.

    Args:
        tenant_id: The tenant of the target (and so of the secret it may name).
        auth: The target's credential reference.

    Returns:
        The headers — empty for ``kind=none``.

    Raises:
        AuthResolutionError: When the credential cannot be resolved: an unset environment
            variable, an unopenable stored credential, or a workspace secret that is missing or
            cannot be opened. The message names the reference, never a value.
    """
    stored_headers: Optional[Dict[str, str]] = None
    secret_value: Optional[str] = None
    if auth.kind == AUTH_KIND_STORED and auth.ref:
        stored_headers = load_endpoint_auth_headers(auth.ref)
    elif auth.kind == AUTH_KIND_SECRET and auth.ref:
        try:
            secret_value = resolve_secrets(db, tenant_id, [auth.ref])[auth.ref]
        except PactSecretError as exc:
            raise AuthResolutionError(f"{exc}; the runner cannot authorize") from exc
    return materialize_auth_headers(auth, stored_headers=stored_headers, secret_value=secret_value)
