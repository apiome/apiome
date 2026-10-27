"""Catalog item refresh — request bodies and table rows for ``apiome catalog refresh`` (MFI-31.1).

Pure helpers, so the command module only parses options, calls REST and prints. REST is the
authority on every rule (refreshable adapters, the SSRF URL policy, credential shapes); these
helpers only build the body it expects and flatten its answer into rows.
"""

from __future__ import annotations

from typing import Any

#: Cadences REST accepts, in order.
CADENCES = ("off", "manual", "hourly", "daily", "weekly")

#: Credential types REST accepts for a live source.
AUTH_TYPES = ("none", "bearer", "header", "oauth2")

#: Fields each credential type needs in its credentials file (a hint for error messages).
CREDENTIAL_FIELDS = {
    "bearer": '{"token": "…"}',
    "header": '{"name": "X-Api-Key", "value": "…"}',
    "oauth2": '{"access_token": "…"}',
}


def refresh_body(
    *,
    cadence: str,
    adapter: str,
    endpoint: str,
    secure: bool,
    auth_type: str | None,
    credentials: dict[str, str] | None,
) -> dict[str, Any]:
    """The ``PUT …/refresh`` body.

    The credential follows REST's three-way contract: left out keeps the stored one,
    ``auth_type == "none"`` clears it (``null``), and a type with its fields replaces it.

    Args:
        cadence: One of :data:`CADENCES`.
        adapter: The adapter key (``graphql`` or ``grpc``).
        endpoint: The live endpoint.
        secure: gRPC only: open a TLS channel.
        auth_type: ``None`` to keep the stored credential, else one of :data:`AUTH_TYPES`.
        credentials: The credential fields read from the credentials file.

    Returns:
        The JSON body.

    Raises:
        ValueError: A credential type other than ``none`` without credentials, or credentials
            without a type.
    """
    body: dict[str, Any] = {
        "cadence": cadence,
        "adapter": adapter,
        "endpoint": endpoint.strip(),
        "options": {"secure": secure} if adapter == "grpc" else {},
    }
    if auth_type is None:
        if credentials:
            raise ValueError("--credentials-file needs --auth-type (bearer, header or oauth2)")
        return body
    if auth_type == "none":
        body["credential"] = None
        return body
    if not credentials:
        raise ValueError(
            f"--auth-type {auth_type} needs --credentials-file with {CREDENTIAL_FIELDS[auth_type]}"
        )
    body["credential"] = {"authType": auth_type, "payload": credentials}
    return body


def refresh_rows(refresh: dict[str, Any]) -> list[dict[str, str]]:
    """``Field`` / ``Value`` rows for one item's refresh answer; never a credential.

    Args:
        refresh: The ``GET …/refresh`` (or PUT / check) response.

    Returns:
        Rows for the two-column table.
    """
    if not refresh.get("configured"):
        rows = [{"field": "Refresh", "value": "Not set up (off)"}]
    else:
        options = refresh.get("options") or {}
        rows = [
            {"field": "Status", "value": str(refresh.get("status") or "never")},
            {"field": "Cadence", "value": str(refresh.get("cadence"))},
            {"field": "Adapter", "value": str(refresh.get("adapter"))},
            {"field": "Endpoint", "value": str(refresh.get("endpoint"))},
            {
                "field": "Credential",
                "value": f"{refresh.get('authType')} (stored)" if refresh.get("hasCredential") else "none",
            },
            {"field": "Last checked", "value": refresh.get("lastCheckedAt") or "never"},
            {"field": "Next check", "value": refresh.get("nextCheckAt") or "—"},
        ]
        if refresh.get("adapter") == "grpc":
            rows.insert(4, {"field": "TLS", "value": "yes" if options.get("secure") else "no"})
        if refresh.get("lastFingerprint"):
            rows.append({"field": "Fingerprint", "value": str(refresh["lastFingerprint"])})
        if refresh.get("status") == "failed":
            rows.append({"field": "Last error", "value": str(refresh.get("lastError") or "")})
            rows.append({"field": "Failures in a row", "value": str(refresh.get("consecutiveFailures") or 0)})
    if refresh.get("tenantEnabled") is False:
        rows.append({"field": "Workspace", "value": "catalog refresh is switched off"})
    return rows
