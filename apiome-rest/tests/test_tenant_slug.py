"""Tenant slug derivation/validation parity tests (OLO-4.3, #4207).

Mirrors the behaviour of ``apiome-ui/lib/auth/tenant-slug.ts`` so the REST
validation stays in lockstep with the UI's instant feedback.
"""

import pytest

from app.tenant_slug import (
    TENANT_SLUG_MAX_LENGTH,
    TENANT_SLUG_MIN_LENGTH,
    generate_tenant_slug,
    validate_tenant_slug,
)


class TestGenerateTenantSlug:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Acme, Inc.", "acme-inc"),
            ("Acme Corp", "acme-corp"),
            ("  Spaced   Out  ", "spaced-out"),
            ("snake_case_name", "snake-case-name"),
            ("UPPER", "upper"),
            ("dash--runs", "dash-runs"),
            ("--edges--", "edges"),
            ("!!!", ""),
            ("", ""),
            ("Ünïcode Org", "ncode-org"),
        ],
    )
    def test_derivation(self, name, expected):
        assert generate_tenant_slug(name) == expected


class TestValidateTenantSlug:
    def test_valid_slug_passes(self):
        assert validate_tenant_slug("acme-inc") is None

    def test_empty_slug_rejected(self):
        assert validate_tenant_slug("") == "Tenant slug is required"
        assert validate_tenant_slug("   ") == "Tenant slug is required"

    def test_too_short_rejected(self):
        assert "at least" in validate_tenant_slug("a")
        assert validate_tenant_slug("ab") is None
        assert TENANT_SLUG_MIN_LENGTH == 2

    def test_too_long_rejected(self):
        assert validate_tenant_slug("a" * TENANT_SLUG_MAX_LENGTH) is None
        assert "at most" in validate_tenant_slug("a" * (TENANT_SLUG_MAX_LENGTH + 1))

    @pytest.mark.parametrize("slug", ["not a slug!", "with_underscore", "dot.com"])
    def test_bad_characters_rejected(self, slug):
        assert "lowercase letters, numbers, and dashes" in validate_tenant_slug(slug)

    def test_case_is_normalized_before_matching(self):
        # Mirrors the UI validator: input is lowercased before the shape check.
        assert validate_tenant_slug("Upper-Case") is None

    def test_reserved_slug_rejected(self):
        assert "reserved" in validate_tenant_slug("me")
