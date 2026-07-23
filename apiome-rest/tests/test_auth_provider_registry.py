"""Tests for the server-side provider registry (OLO-8.4, #4970).

The Python registry (:mod:`app.auth_provider_registry`) is a deliberate projection of the canonical
UI registry (``provider-registry.ts``). These pin the facts the REST layer depends on and, crucially,
that the two never silently drift: the slugs, order, and status must match the UI and the V196 CHECK.
"""

from app.auth_provider_registry import (
    PROVIDER_REGISTRY,
    STATUS_AVAILABLE,
    STATUS_COMING_SOON,
    get_provider_descriptor,
    known_provider_ids,
)


def test_registry_ids_and_order_match_ui_and_v196():
    """Slugs and display order mirror PROVIDER_REGISTRY (UI) and the V196 CHECK list."""
    assert known_provider_ids() == ["github", "gitlab", "azure", "google", "aws"]


def test_available_vs_coming_soon_status():
    """github/gitlab/azure are available; google/aws are coming-soon."""
    status = {p.id: p.status for p in PROVIDER_REGISTRY}
    assert status["github"] == STATUS_AVAILABLE
    assert status["gitlab"] == STATUS_AVAILABLE
    assert status["azure"] == STATUS_AVAILABLE
    assert status["google"] == STATUS_COMING_SOON
    assert status["aws"] == STATUS_COMING_SOON


def test_available_providers_require_client_id_and_secret():
    """Available providers require client_id + client_secret; coming-soon require nothing."""
    for provider in PROVIDER_REGISTRY:
        if provider.status == STATUS_AVAILABLE:
            assert provider.required_fields == ("client_id", "client_secret")
        else:
            assert provider.required_fields == ()


def test_lookup_known_and_unknown():
    """Lookup returns the descriptor for a known slug and None otherwise."""
    assert get_provider_descriptor("github").label == "GitHub"
    assert get_provider_descriptor("okta") is None
