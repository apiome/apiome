"""Regression suite for Slate tenant resolution — UXE-3.1 (private-suite#2473).

``validate_authentication`` declares ``tenant_slug: str`` with no default. Routers that carry
``{tenant_slug}`` in their path satisfy that as a path parameter; the Slate routers, which read
tenancy from the credential instead, do not — so FastAPI bound it as a **required query
parameter** and every ``/v1/slate/*`` call answered 422 before authentication ran.

This file exists because ``tests/test_slate_routes.py`` cannot catch that. It installs
``app.dependency_overrides[...] = lambda: dict(_MOCK_JWT)``, which replaces the very signature
that was wrong; the routes passed while the deployed surface was unreachable. **Nothing here
overrides the auth dependency.** The stubs go one layer lower, at the database and the store,
so the real dependency signature is exercised end to end.

The last test is the one that matters most over time: it sweeps every route on every Slate
router and asserts none of them declares a required ``tenant_slug`` query parameter, so a new
endpoint added later cannot quietly reintroduce the defect.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"

TENANT_ROW: Dict[str, Any] = {
    "tenant_id": TENANT_ID,
    "tenant_slug": "acme",
    "tenant_name": "Acme",
}
OTHER_TENANT_ROW: Dict[str, Any] = {
    "tenant_id": OTHER_TENANT_ID,
    "tenant_slug": "other",
    "tenant_name": "Other",
}


def bearer(*, tenant_id: str | None = TENANT_ID) -> Dict[str, str]:
    """Mint the same shape of session token the Studio BFF signs.

    Args:
        tenant_id: Value for the ``current_tenant_id`` claim, or ``None`` to omit it.

    Returns:
        An ``Authorization`` header mapping ready to pass to the test client.
    """
    claims: Dict[str, Any] = {"user_id": USER_ID, "sub": USER_ID, "email": "a@b.c"}
    if tenant_id is not None:
        claims["current_tenant_id"] = tenant_id
    token = jwt.encode(claims, settings.effective_jwt_secret, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tenant_lookup() -> Iterator[None]:
    """Stub tenant resolution and membership below the dependency, never the dependency itself."""

    def by_id(tenant_id: str) -> Dict[str, Any] | None:
        return {TENANT_ID: TENANT_ROW, OTHER_TENANT_ID: OTHER_TENANT_ROW}.get(tenant_id)

    def by_slug(slug: str) -> Dict[str, Any] | None:
        return {"acme": TENANT_ROW, "other": OTHER_TENANT_ROW}.get(slug)

    with (
        patch("app.slate_auth.db.get_active_tenant_auth_row_by_id", side_effect=by_id),
        patch("app.auth.db.get_active_tenant_auth_row", side_effect=by_slug),
        # The user belongs to acme only. `other` exists but is not theirs.
        patch(
            "app.auth.db.user_has_tenant_access",
            side_effect=lambda user_id, tenant_id: tenant_id == TENANT_ID,
        ),
    ):
        yield


@pytest.fixture
def empty_sites() -> Iterator[None]:
    """Answer the sites listing with nothing, so the test is about auth and not about data."""
    with patch("app.slate_routes.list_sites", return_value=[]):
        yield


class TestSlateTenantResolution:
    """The defect, and the behaviours that must hold once it is fixed."""

    def test_session_jwt_alone_reaches_the_route(self, tenant_lookup, empty_sites) -> None:
        """The regression. Before the fix this was 422 for a missing query parameter."""
        response = client.get("/v1/slate/sites", headers=bearer())
        assert response.status_code != 422, (
            "tenant_slug is bound as a required query parameter again: "
            f"{response.json()}"
        )
        assert response.status_code == 200

    def test_no_credential_is_unauthenticated_not_unprocessable(self) -> None:
        """A missing credential is a 401. 422 would describe the URL, not the problem."""
        response = client.get("/v1/slate/sites")
        assert response.status_code == 401

    def test_jwt_without_tenant_claim_is_unauthenticated(self, tenant_lookup) -> None:
        """A token that names no tenant cannot be silently defaulted to one."""
        response = client.get("/v1/slate/sites", headers=bearer(tenant_id=None))
        assert response.status_code == 401

    def test_unknown_tenant_claim_is_unauthenticated(self, tenant_lookup) -> None:
        """A forged tenant id resolves to nothing and leaks nothing about what exists."""
        response = client.get(
            "/v1/slate/sites",
            headers=bearer(tenant_id="99999999-9999-9999-9999-999999999999"),
        )
        assert response.status_code == 401

    def test_explicit_slug_for_a_foreign_tenant_is_refused(self, tenant_lookup, empty_sites) -> None:
        """Naming a tenant explicitly does not grant it: authorization still runs."""
        response = client.get(
            "/v1/slate/sites?tenantSlug=other",
            headers=bearer(),
        )
        assert response.status_code == 403

    def test_explicit_slug_is_honoured_for_the_caller_own_tenant(
        self, tenant_lookup, empty_sites
    ) -> None:
        """The explicit path stays open for CLI and API-key callers."""
        response = client.get("/v1/slate/sites?tenantSlug=acme", headers=bearer())
        assert response.status_code == 200


class TestSlateRouteSurface:
    """Structural guards, so a new endpoint cannot reintroduce the defect."""

    def test_no_slate_route_requires_a_tenant_slug_query_parameter(self) -> None:
        """Sweep the whole surface rather than the routes that happen to be tested."""
        schema = app.openapi()
        offenders: list[str] = []
        for path, operations in schema["paths"].items():
            if not path.startswith("/v1/slate"):
                continue
            for method, operation in operations.items():
                for parameter in operation.get("parameters", []):
                    if parameter.get("in") != "query":
                        continue
                    if parameter.get("name") not in {"tenant_slug", "tenantSlug"}:
                        continue
                    if parameter.get("required"):
                        offenders.append(f"{method.upper()} {path}")
        assert offenders == [], (
            "Slate routes must read tenancy from the credential, not from a required query "
            f"parameter: {offenders}"
        )

    def test_slate_routes_are_registered_at_all(self) -> None:
        """Guards the sweep above: a passing sweep over an empty set proves nothing."""
        schema = app.openapi()
        slate_paths = [p for p in schema["paths"] if p.startswith("/v1/slate")]
        assert len(slate_paths) > 5
