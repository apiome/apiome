"""Tests for slug derivation utilities (V13/V14 DB CHECK constraints).

Covers:
- Project slug generation (^[a-z0-9]([a-z0-9-]*[a-z0-9])?$)
- Version slug generation (^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$)
- Edge cases: spaces, uppercase, underscores, dots, special characters
- Unicode policy: NFKC, combining-mark stripping, fullwidth digits, emoji
- Error handling when no alphanumeric characters remain
"""

from __future__ import annotations

import pytest

from apiome_cli.extract.slug import (
    PROJECT_SLUG_RE,
    VERSION_SLUG_RE,
    normalize_unicode_for_slug,
    slugify_project_name,
    slugify_version,
)

# DB constraint regexes (mirrors V13/V14 migrations).
_PROJECT_SLUG_RE = PROJECT_SLUG_RE
_VERSION_SLUG_RE = VERSION_SLUG_RE


def _valid_project_slug(slug: str) -> bool:
    """Return True when *slug* satisfies the V13 DB constraint."""
    return bool(_PROJECT_SLUG_RE.match(slug))


def _valid_version_slug(slug: str) -> bool:
    """Return True when *slug* satisfies the V14 DB constraint."""
    return bool(_VERSION_SLUG_RE.match(slug))


# ---------------------------------------------------------------------------
# Unicode normalization policy
# ---------------------------------------------------------------------------


def test_normalize_unicode_nfkc_ligature() -> None:
    """NFKC expands compatibility ligatures (e.g. fi ligature → fi)."""
    assert normalize_unicode_for_slug("ﬁle") == "file"


def test_normalize_unicode_strips_combining_marks() -> None:
    """Combining marks are removed after NFD (é → e)."""
    assert normalize_unicode_for_slug("café") == "cafe"


def test_normalize_unicode_fullwidth_digits() -> None:
    """NFKC maps fullwidth digits to ASCII."""
    assert normalize_unicode_for_slug("１.０") == "1.0"


def test_project_slug_accented_name() -> None:
    """Accented letters in project names fold to ASCII slug segments."""
    assert slugify_project_name("Café API") == "cafe-api"


def test_project_slug_umlaut_name() -> None:
    """Umlauts are stripped to base letters in project slugs."""
    assert slugify_project_name("Müller Service") == "muller-service"


def test_project_slug_emoji_stripped() -> None:
    """Emoji and other non-slug characters are removed."""
    assert slugify_project_name("My 🚀 API") == "my-api"


def test_project_slug_cjk_only_raises() -> None:
    """A name with only CJK characters cannot produce a valid slug."""
    with pytest.raises(ValueError, match="project slug"):
        slugify_project_name("日本語")


def test_version_slug_fullwidth_semver() -> None:
    """Fullwidth version digits normalise to ASCII semver slug."""
    assert slugify_version("１.０.０") == "1.0.0"


def test_version_slug_accented_prerelease() -> None:
    """Accented characters in version labels fold before slug rules."""
    assert slugify_version("1.0 café") == "1.0-cafe"


# ---------------------------------------------------------------------------
# Slug generation: slugify_project_name
# ---------------------------------------------------------------------------


def test_project_slug_lowercase_alphanumeric() -> None:
    """Simple lowercase alphanumeric name produces the same slug."""
    assert slugify_project_name("myapi") == "myapi"


def test_project_slug_uppercase_lowercased() -> None:
    """Uppercase letters are lowercased in the project slug."""
    assert slugify_project_name("MyAPI") == "myapi"


def test_project_slug_spaces_become_hyphens() -> None:
    """Spaces are replaced with hyphens in the project slug."""
    assert slugify_project_name("My Pet Store") == "my-pet-store"


def test_project_slug_underscores_become_hyphens() -> None:
    """Underscores are replaced with hyphens."""
    assert slugify_project_name("my_api_service") == "my-api-service"


def test_project_slug_dots_become_hyphens() -> None:
    """Dots are replaced with hyphens in project slugs."""
    assert slugify_project_name("my.api") == "my-api"


def test_project_slug_consecutive_separators_collapsed() -> None:
    """Multiple consecutive separators collapse to a single hyphen."""
    assert slugify_project_name("My  API  Service") == "my-api-service"


def test_project_slug_matches_db_regex() -> None:
    """Generated project slug always matches the V13 DB constraint."""
    names = [
        "My API",
        "PetStore v2",
        "ACME Corp Service",
        "hello-world",
        "a",
        "ab",
        "1",
        "1.0 API",
        "my_service_name",
    ]
    for name in names:
        slug = slugify_project_name(name)
        assert _valid_project_slug(slug), f"Slug {slug!r} from {name!r} failed V13 regex"


def test_project_slug_no_hyphens_at_edges() -> None:
    """Project slug never starts or ends with a hyphen."""
    slug = slugify_project_name("  My API  ")
    assert not slug.startswith("-")
    assert not slug.endswith("-")


def test_project_slug_special_chars_stripped() -> None:
    """Characters outside [a-z0-9-] are removed from project slug."""
    slug = slugify_project_name("API@2.0!")
    assert _valid_project_slug(slug)
    assert "@" not in slug
    assert "!" not in slug


def test_project_slug_empty_after_normalisation_raises() -> None:
    """Text that leaves no alphanumeric chars after normalisation raises ValueError."""
    with pytest.raises(ValueError, match="project slug"):
        slugify_project_name("---")


def test_project_slug_only_special_chars_raises() -> None:
    """A string of only special characters raises ValueError."""
    with pytest.raises(ValueError, match="project slug"):
        slugify_project_name("@@@!!!")


# ---------------------------------------------------------------------------
# Slug generation: slugify_version
# ---------------------------------------------------------------------------


def test_version_slug_semver() -> None:
    """SemVer version strings are preserved as valid version slugs."""
    assert slugify_version("1.0.0") == "1.0.0"


def test_version_slug_semver_prerelease() -> None:
    """SemVer pre-release labels are kept intact."""
    assert slugify_version("1.0.0-beta.1") == "1.0.0-beta.1"


def test_version_slug_semver_with_v_prefix() -> None:
    """A leading 'v' prefix is preserved in the version slug."""
    assert slugify_version("v2.3.4") == "v2.3.4"


def test_version_slug_uppercase_lowercased() -> None:
    """Uppercase letters in version strings are lowercased."""
    assert slugify_version("V1.0.0-BETA") == "v1.0.0-beta"


def test_version_slug_spaces_become_hyphens() -> None:
    """Spaces in version strings become hyphens."""
    assert slugify_version("1.0 beta") == "1.0-beta"


def test_version_slug_matches_db_regex() -> None:
    """Generated version slug always matches the V14 DB constraint."""
    versions = [
        "1.0.0",
        "2.0-rc1",
        "v1.0.0-beta.1",
        "1",
        "1.0",
        "0.1.0-alpha.3",
        "2024.01.15",
        "latest",
    ]
    for ver in versions:
        slug = slugify_version(ver)
        assert _valid_version_slug(slug), f"Slug {slug!r} from {ver!r} failed V14 regex"


def test_version_slug_no_hyphens_or_dots_at_edges() -> None:
    """Version slug never starts or ends with a hyphen or dot."""
    slug = slugify_version("  1.0.0  ")
    assert not slug.startswith(("-", "."))
    assert not slug.endswith(("-", "."))


def test_version_slug_dots_preserved() -> None:
    """Dots are preserved in version slugs (unlike project slugs)."""
    slug = slugify_version("1.2.3")
    assert "." in slug


def test_version_slug_empty_after_normalisation_raises() -> None:
    """Text that yields no alphanumeric chars raises ValueError."""
    with pytest.raises(ValueError, match="version slug"):
        slugify_version("---")


# ---------------------------------------------------------------------------
# Exported regex constants match DB constraints
# ---------------------------------------------------------------------------


def test_project_slug_re_matches_v13_migration() -> None:
    """PROJECT_SLUG_RE mirrors the V13 chk_projects_slug pattern."""
    assert PROJECT_SLUG_RE.pattern == r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"


def test_version_slug_re_matches_v14_migration() -> None:
    """VERSION_SLUG_RE mirrors the V14 chk_pv_slug pattern."""
    assert VERSION_SLUG_RE.pattern == r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$"
