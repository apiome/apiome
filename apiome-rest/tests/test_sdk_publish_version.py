"""The version-line → package-version mapping — SDK-4.1 (#4495).

The acceptance criterion is that version numbers follow the version-line + regen-counter mapping
**deterministically**, so these are pure-function tests of :mod:`app.sdk_publish_version`. Three
properties matter more than any individual example:

* **Injective.** Two different (series, counter) pairs never produce one version, or a publish
  would collide with an earlier one on the registry.
* **Monotonic.** Successive counters produce successively *later* versions in each ecosystem's own
  ordering — including for prereleases, which must stay below their eventual stable release.
* **Refusing rather than guessing.** A line with no leading number has no ordering to inherit.
"""

from __future__ import annotations

import pytest

from app.sdk_publish_version import (
    MAX_COMPONENT,
    NPM_ECOSYSTEM,
    PUBLISH_ECOSYSTEMS,
    PYPI_ECOSYSTEM,
    ReleaseSeries,
    VersionLineError,
    package_version,
    parse_version_line,
    resolve_package_version,
)


# --------------------------------------------------------------------------------------------
# Reading a version line
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line, major, minor, tag",
    [
        ("1.4", 1, 4, None),
        ("1.4.2", 1, 4, None),
        ("2", 2, 0, None),
        ("v3", 3, 0, None),
        ("V3.1", 3, 1, None),
        ("2026-01-04", 2026, 1, None),
        ("2026_01", 2026, 1, None),
        ("1.5-beta", 1, 5, "beta"),
        ("1.0.0-rc.2", 1, 0, "rc"),
        ("1.0.0-BETA", 1, 0, "beta"),
        ("2.0.0-snapshot", 2, 0, "snapshot"),
        ("1.0.0+build.5", 1, 0, "build"),
        ("1.0.0-", 1, 0, None),
    ],
)
def test_reads_the_release_series(line, major, minor, tag):
    series = parse_version_line(line)
    assert (series.major, series.minor, series.prerelease) == (major, minor, tag)


def test_a_date_line_is_not_read_as_a_prerelease():
    """``2026-01-04``'s hyphens separate numbers, not a tag — the trap this parser exists for."""
    assert parse_version_line("2026-01-04").prerelease is None


@pytest.mark.parametrize("line", ["latest", "current", "draft", "", "   ", None, "beta"])
def test_a_line_with_no_leading_number_is_refused(line):
    with pytest.raises(VersionLineError):
        parse_version_line(line)


def test_the_refusal_says_what_would_work():
    """The message is read by the person who named the version, so it must be actionable."""
    with pytest.raises(VersionLineError, match="1.4|v2|2026"):
        parse_version_line("latest")


def test_an_absurdly_large_component_is_refused():
    with pytest.raises(VersionLineError, match="larger than"):
        parse_version_line(f"{MAX_COMPONENT + 1}.0")


def test_the_series_key_is_the_counter_allocation_key():
    assert ReleaseSeries(1, 4).key == "1.4"
    assert ReleaseSeries(1, 5, "beta").key == "1.5-beta"


def test_lines_differing_only_in_patch_share_a_series():
    """The rule that stops ``1.4.2`` and ``1.4.3`` both publishing ``1.4.0``."""
    assert parse_version_line("1.4.2").key == parse_version_line("1.4.3").key


# --------------------------------------------------------------------------------------------
# Rendering a package version
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ecosystem", PUBLISH_ECOSYSTEMS)
def test_the_counter_is_the_patch_for_a_stable_line(ecosystem):
    series = parse_version_line("1.4")
    assert package_version(series, ecosystem, 0) == "1.4.0"
    assert package_version(series, ecosystem, 7) == "1.4.7"


def test_npm_keeps_a_prerelease_a_prerelease():
    series = parse_version_line("1.5-beta")
    assert package_version(series, NPM_ECOSYSTEM, 0) == "1.5.0-beta.0"
    assert package_version(series, NPM_ECOSYSTEM, 3) == "1.5.0-beta.3"


@pytest.mark.parametrize(
    "line, expected",
    [
        ("1.5-alpha", "1.5.0a3"),
        ("1.5-beta", "1.5.0b3"),
        ("1.5-rc", "1.5.0rc3"),
        ("1.5-preview", "1.5.0rc3"),
        ("1.5-snapshot", "1.5.0.dev3"),
    ],
)
def test_pypi_maps_a_prerelease_onto_pep_440(line, expected):
    assert package_version(parse_version_line(line), PYPI_ECOSYSTEM, 3) == expected


def test_an_unpublishable_ecosystem_is_refused():
    with pytest.raises(ValueError, match="gomod"):
        package_version(parse_version_line("1.0"), "gomod", 0)


def test_a_negative_counter_is_refused():
    with pytest.raises(ValueError, match="negative"):
        package_version(parse_version_line("1.0"), NPM_ECOSYSTEM, -1)


def test_an_exhausted_series_is_refused():
    with pytest.raises(ValueError, match="exhausted"):
        package_version(parse_version_line("1.0"), NPM_ECOSYSTEM, MAX_COMPONENT + 1)


# --------------------------------------------------------------------------------------------
# The three properties
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ecosystem", PUBLISH_ECOSYSTEMS)
def test_the_mapping_is_injective_across_lines_and_counters(ecosystem):
    """No two (line, counter) pairs may produce one version — that would be a registry collision."""
    lines = ["1.4", "1.4.2", "1.4.9", "1.5", "1.5-beta", "1.5-rc", "2.0", "2026-01-04"]
    produced = {}
    for line in lines:
        series = parse_version_line(line)
        for counter in range(4):
            version = package_version(series, ecosystem, counter)
            key = (series.key, counter)
            clash = produced.get(version)
            assert clash in (None, key), f"{version} produced by both {clash} and {key}"
            produced[version] = key


def test_npm_versions_are_monotonic_in_the_counter():
    """Uses the semver ordering npm itself applies."""
    series = parse_version_line("1.5-beta")
    ordered = [package_version(series, NPM_ECOSYSTEM, n) for n in range(12)]
    # Numeric prerelease identifiers compare numerically, so `beta.9` < `beta.10`.
    numbers = [int(v.rsplit(".", 1)[1]) for v in ordered]
    assert numbers == sorted(numbers) == list(range(12))


def test_a_prerelease_sorts_below_its_stable_release():
    """`1.5.0-beta.N` precedes `1.5.0` in semver, and `1.5.0bN` precedes `1.5.0` in PEP 440."""
    assert package_version(parse_version_line("1.5-beta"), NPM_ECOSYSTEM, 2).startswith("1.5.0-")
    assert package_version(parse_version_line("1.5-beta"), PYPI_ECOSYSTEM, 2) == "1.5.0b2"


def test_resolve_returns_the_series_the_caller_must_store():
    series, version = resolve_package_version("1.4.2", NPM_ECOSYSTEM, 5)
    assert series.key == "1.4"
    assert version == "1.4.5"


def test_the_same_inputs_always_produce_the_same_version():
    """Determinism is the acceptance criterion, so it gets its own assertion."""
    first = resolve_package_version("2026-01-04", PYPI_ECOSYSTEM, 11)
    second = resolve_package_version("2026-01-04", PYPI_ECOSYSTEM, 11)
    assert first[1] == second[1] == "2026.1.11"
