"""Generation settings vocabulary — SDK-3.4 (#4494).

Pure-function tests for :mod:`app.sdk_generation_settings`: what a body may say, how two scopes
merge, what a pattern resolves to, and the determinism guarantee the fingerprint carries.
"""

from __future__ import annotations

import pytest

from app.sdk_generation_settings import (
    ECOSYSTEMS,
    LICENSE_HEADER_MAX_CHARS,
    PATTERN_TOKENS,
    SDK_GENERATION_SETTINGS_SCHEMA_VERSION,
    USER_AGENT_MAX_CHARS,
    PatternContext,
    SdkGenerationSettings,
    SdkSettingsError,
    canonical_settings_body,
    merge_settings_bodies,
    parse_settings_body,
    render_pattern,
    resolve_branding,
    resolve_package_names,
    settings_content_fingerprint,
    settings_from_body,
)

_ACME = PatternContext(tenant="acme", project="petstore", version="2.1.0", year="2026")


# ===========================================================================
# Parsing
# ===========================================================================


def test_an_absent_key_is_not_stored() -> None:
    """Only the keys an author named survive — that is what makes inheritance possible."""
    body = parse_settings_body({"userAgent": "acme-sdk/1.0"})
    assert body == {
        "schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION,
        "userAgent": "acme-sdk/1.0",
    }


def test_an_explicit_null_is_stored_as_none() -> None:
    """``null`` is a deliberate "none", and must survive parsing to block inheritance."""
    body = parse_settings_body({"licenseHeader": None})
    assert "licenseHeader" in body
    assert body["licenseHeader"] is None


def test_an_empty_body_is_valid_and_stores_nothing() -> None:
    assert parse_settings_body({}) == {
        "schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION
    }
    assert parse_settings_body(None) == {
        "schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION
    }


def test_every_problem_is_reported_at_once() -> None:
    """A caller fixes everything in one round trip rather than one mistake per request."""
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body(
            {
                "userAgent": "bad\nagent",
                "licenseHeader": "Copyright {owner}",
                "packageNamePatterns": {"npm": "@ACME/{project}"},
            }
        )
    joined = " | ".join(excinfo.value.errors)
    assert len(excinfo.value.errors) == 3
    assert "userAgent" in joined
    assert "licenseHeader" in joined
    assert "packageNamePatterns.npm" in joined


def test_an_unknown_setting_is_refused_with_the_accepted_list() -> None:
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"logoUrl": "https://acme.example/logo.png"})
    assert "logoUrl" in excinfo.value.errors[0]
    assert "packageNamePatterns" in excinfo.value.errors[0]


def test_an_unknown_ecosystem_is_refused() -> None:
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"packageNamePatterns": {"cargo": "acme-{project}"}})
    assert "cargo" in excinfo.value.errors[0]
    for ecosystem in ECOSYSTEMS:
        assert ecosystem in excinfo.value.errors[0]


def test_an_unknown_token_is_refused_with_the_vocabulary() -> None:
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"userAgent": "acme-sdk/{revision}"})
    message = excinfo.value.errors[0]
    assert "revision" in message
    for token in PATTERN_TOKENS:
        assert token in message


def test_an_empty_string_is_refused_rather_than_silently_clearing() -> None:
    """Clearing is ``null``; an empty string is far likelier to be an accidental blank field."""
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"userAgent": "   "})
    assert "null" in excinfo.value.errors[0]


@pytest.mark.parametrize(
    "pattern",
    ["@acme/{project}-sdk", "acme-{project}", "{tenant}-{project}", "@acme/client"],
)
def test_a_legal_npm_pattern_is_accepted(pattern: str) -> None:
    body = parse_settings_body({"packageNamePatterns": {"npm": pattern}})
    assert body["packageNamePatterns"]["npm"] == pattern


@pytest.mark.parametrize(
    "pattern",
    ["@ACME/{project}", "acme sdk", "@acme/{project}/extra", ".hidden-{project}"],
)
def test_an_illegal_npm_pattern_is_refused_by_resolving_it(pattern: str) -> None:
    """A pattern is judged by the name it produces, not by its own characters."""
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"packageNamePatterns": {"npm": pattern}})
    assert "packageNamePatterns.npm" in excinfo.value.errors[0]


def test_an_illegal_pypi_pattern_is_refused() -> None:
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"packageNamePatterns": {"pypi": "acme/{project}"}})
    assert "PyPI" in excinfo.value.errors[0]


def test_a_user_agent_with_a_newline_is_refused() -> None:
    """Header injection: a user-agent is written into a request header."""
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"userAgent": "acme\r\nX-Admin: true"})
    assert "header" in excinfo.value.errors[0]


def test_the_caps_are_enforced() -> None:
    with pytest.raises(SdkSettingsError):
        parse_settings_body({"userAgent": "a" * (USER_AGENT_MAX_CHARS + 1)})
    with pytest.raises(SdkSettingsError):
        parse_settings_body({"licenseHeader": "a" * (LICENSE_HEADER_MAX_CHARS + 1)})


def test_a_multi_line_license_header_is_accepted() -> None:
    header = "Copyright (c) {year} Acme, Inc.\nSPDX-License-Identifier: Apache-2.0"
    body = parse_settings_body({"licenseHeader": header})
    assert body["licenseHeader"] == header


# ===========================================================================
# Merging
# ===========================================================================


def test_a_project_overrides_only_the_keys_it_names() -> None:
    tenant = parse_settings_body(
        {
            "packageNamePatterns": {"npm": "@acme/{project}", "pypi": "acme-{project}"},
            "licenseHeader": "Copyright Acme",
            "userAgent": "acme-sdk/1.0",
        }
    )
    project = parse_settings_body({"userAgent": "petstore-sdk/2.0"})
    merged = settings_from_body(merge_settings_bodies(tenant, project))
    assert merged.user_agent == "petstore-sdk/2.0"
    assert merged.license_header == "Copyright Acme"
    assert merged.package_name_patterns == {
        "npm": "@acme/{project}",
        "pypi": "acme-{project}",
    }


def test_a_project_null_blocks_inheritance() -> None:
    """The distinction the JSONB body exists for: cleared is not the same as unset."""
    tenant = parse_settings_body({"licenseHeader": "Copyright Acme"})
    project = parse_settings_body({"licenseHeader": None})
    merged = settings_from_body(merge_settings_bodies(tenant, project))
    assert merged.license_header is None


def test_package_patterns_merge_one_ecosystem_at_a_time() -> None:
    tenant = parse_settings_body(
        {"packageNamePatterns": {"npm": "@acme/{project}", "pypi": "acme-{project}"}}
    )
    project = parse_settings_body(
        {"packageNamePatterns": {"npm": "@acme/petstore-client"}}
    )
    merged = settings_from_body(merge_settings_bodies(tenant, project))
    assert merged.package_name_patterns == {
        "npm": "@acme/petstore-client",
        "pypi": "acme-{project}",
    }


def test_a_project_can_clear_one_ecosystem() -> None:
    tenant = parse_settings_body(
        {"packageNamePatterns": {"npm": "@acme/{project}", "pypi": "acme-{project}"}}
    )
    project = parse_settings_body({"packageNamePatterns": {"npm": None}})
    merged = settings_from_body(merge_settings_bodies(tenant, project))
    assert merged.package_name_patterns == {"pypi": "acme-{project}"}


def test_a_project_can_clear_every_pattern_at_once() -> None:
    tenant = parse_settings_body(
        {"packageNamePatterns": {"npm": "@acme/{project}", "pypi": "acme-{project}"}}
    )
    merged = settings_from_body(
        merge_settings_bodies(tenant, {"packageNamePatterns": None})
    )
    assert merged.package_name_patterns == {}


def test_merging_nothing_yields_nothing() -> None:
    merged = settings_from_body(merge_settings_bodies(None, None))
    assert merged == SdkGenerationSettings()


def test_a_body_from_a_newer_release_still_resolves() -> None:
    """Forward compatibility: unknown keys are ignored on read, not raised."""
    merged = settings_from_body(
        {"userAgent": "acme/1.0", "somethingNew": {"deep": True}}
    )
    assert merged.user_agent == "acme/1.0"


# ===========================================================================
# Resolution
# ===========================================================================


def test_tokens_substitute_from_the_context() -> None:
    assert render_pattern("@{tenant}/{project}-sdk", _ACME) == "@acme/petstore-sdk"
    assert render_pattern("Copyright (c) {year} Acme", _ACME) == "Copyright (c) 2026 Acme"
    assert render_pattern("acme-sdk/{version}", _ACME) == "acme-sdk/2.1.0"


def test_a_package_pattern_with_an_unfillable_token_is_omitted() -> None:
    """At tenant scope ``acme-{project}`` has no answer; ``acme-`` would be a wrong one."""
    settings = settings_from_body({"packageNamePatterns": {"npm": "acme-{project}"}})
    assert resolve_package_names(settings, PatternContext(tenant="acme")) == {}


def test_the_same_pattern_resolves_once_a_project_is_known() -> None:
    settings = settings_from_body({"packageNamePatterns": {"npm": "acme-{project}"}})
    resolved = resolve_package_names(
        settings, PatternContext(tenant="acme", project="petstore")
    )
    assert resolved == {"npm": "acme-petstore"}


def test_a_license_token_with_nothing_behind_it_renders_away() -> None:
    """The opposite rule from package names: a partial sentence still reads."""
    settings = settings_from_body({"licenseHeader": "Copyright {tenant} — {project}"})
    branding = resolve_branding(settings, PatternContext(tenant="acme"))
    assert branding.license_header == "Copyright acme — "


def test_year_defaults_to_the_clock() -> None:
    rendered = render_pattern("{year}", PatternContext(tenant="acme"))
    assert rendered.isdigit() and len(rendered) == 4


def test_an_unknown_token_survives_rendering_untouched() -> None:
    """Save-time validation refuses these; reaching one here means a newer release wrote it."""
    assert render_pattern("acme-{unknown}", _ACME) == "acme-{unknown}"


def test_a_pattern_that_resolves_illegally_is_omitted_not_emitted_broken() -> None:
    """A real project slug is not a probe; a publisher must never get an unpublishable name."""
    settings = settings_from_body({"packageNamePatterns": {"npm": "@acme/{project}"}})
    resolved = resolve_package_names(
        settings, PatternContext(tenant="acme", project="Not A Slug")
    )
    assert resolved == {}


def test_resolve_branding_substitutes_every_field() -> None:
    settings = settings_from_body(
        merge_settings_bodies(
            parse_settings_body(
                {
                    "packageNamePatterns": {"npm": "@{tenant}/{project}-sdk"},
                    "licenseHeader": "Copyright (c) {year} {tenant}",
                    "userAgent": "{project}-sdk/{version}",
                }
            )
        )
    )
    branding = resolve_branding(settings, _ACME)
    assert branding.package_names == {"npm": "@acme/petstore-sdk"}
    assert branding.license_header == "Copyright (c) 2026 acme"
    assert branding.user_agent == "petstore-sdk/2.1.0"
    assert not branding.is_empty()


def test_nothing_configured_is_empty_branding() -> None:
    assert resolve_branding(SdkGenerationSettings(), _ACME).is_empty()


# ===========================================================================
# Fingerprint
# ===========================================================================


def test_identical_settings_fingerprint_identically() -> None:
    """SDK-3.4's determinism guarantee, stated as a test."""
    one = settings_from_body(
        merge_settings_bodies({"userAgent": "acme/1.0"}, {"licenseHeader": "MIT"})
    )
    two = settings_from_body(
        merge_settings_bodies({"licenseHeader": "MIT"}, {"userAgent": "acme/1.0"})
    )
    assert settings_content_fingerprint(one) == settings_content_fingerprint(two)


def test_a_changed_setting_changes_the_fingerprint() -> None:
    before = settings_from_body({"userAgent": "acme/1.0"})
    after = settings_from_body({"userAgent": "acme/2.0"})
    assert settings_content_fingerprint(before) != settings_content_fingerprint(after)


def test_the_fingerprint_is_prefixed_and_stable_in_length() -> None:
    digest = settings_content_fingerprint(SdkGenerationSettings())
    assert digest.startswith("sha256:")
    # V255 stores this in a VARCHAR(71): 7 for the prefix plus 64 hex characters.
    assert len(digest) == 71


def test_the_canonical_body_carries_every_key_even_when_unset() -> None:
    """A stored fingerprint must keep meaning the same thing after a release adds a setting."""
    body = canonical_settings_body(SdkGenerationSettings())
    assert body == {
        "packageNamePatterns": {},
        "licenseHeader": None,
        "userAgent": None,
        # SDK-3.3 (#4493). Unlike its three neighbours this one defaults to False rather than
        # None: it is an access control, and "not configured" must read as "not allowed".
        "publicSdkEnabled": False,
        "schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION,
    }


# ===========================================================================
# The public-SDK gate — SDK-3.3 (#4493)
# ===========================================================================


def test_public_sdk_access_is_off_by_default() -> None:
    """Nothing configured means not allowed. An access control has no other safe default."""
    assert SdkGenerationSettings().public_sdk_enabled is False
    assert settings_from_body({}).public_sdk_enabled is False
    assert settings_from_body(None).public_sdk_enabled is False


def test_public_sdk_access_round_trips_both_booleans() -> None:
    for value in (True, False):
        parsed = parse_settings_body({"publicSdkEnabled": value})
        assert parsed["publicSdkEnabled"] is value
        assert settings_from_body(parsed).public_sdk_enabled is value


def test_a_non_boolean_public_sdk_value_is_refused() -> None:
    """`1` must not become a permission grant — `isinstance(True, int)` makes that easy to miss."""
    for value in (1, 0, "true", [], {}):
        with pytest.raises(SdkSettingsError) as excinfo:
            parse_settings_body({"publicSdkEnabled": value})
        assert "publicSdkEnabled" in excinfo.value.errors[0]


def test_the_accepted_key_list_names_public_sdk_enabled() -> None:
    with pytest.raises(SdkSettingsError) as excinfo:
        parse_settings_body({"nope": True})
    assert "publicSdkEnabled" in excinfo.value.errors[0]


def test_a_project_inherits_its_workspace_public_sdk_answer() -> None:
    """An absent key inherits: a workspace can open every project at once."""
    merged = merge_settings_bodies({"publicSdkEnabled": True}, {"userAgent": "acme/1.0"})
    assert settings_from_body(merged).public_sdk_enabled is True


def test_a_project_can_close_a_workspace_that_opened_it() -> None:
    merged = merge_settings_bodies({"publicSdkEnabled": True}, {"publicSdkEnabled": False})
    assert settings_from_body(merged).public_sdk_enabled is False


def test_an_explicit_null_blocks_inheritance_and_reads_as_off() -> None:
    """`null` is "deliberately none"; for a gate, none means closed."""
    merged = merge_settings_bodies({"publicSdkEnabled": True}, {"publicSdkEnabled": None})
    assert merged["publicSdkEnabled"] is None
    assert settings_from_body(merged).public_sdk_enabled is False


def test_a_project_can_open_a_workspace_that_left_it_closed() -> None:
    merged = merge_settings_bodies({"userAgent": "acme/1.0"}, {"publicSdkEnabled": True})
    assert settings_from_body(merged).public_sdk_enabled is True


def test_the_fingerprint_distinguishes_the_two_answers() -> None:
    """Opening a project's SDK is a change a fingerprint must be able to attribute."""
    closed = settings_content_fingerprint(settings_from_body({"publicSdkEnabled": False}))
    opened = settings_content_fingerprint(settings_from_body({"publicSdkEnabled": True}))
    assert closed != opened
