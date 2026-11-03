"""Per-branch refresh policy — the pure rules (RAR-6.4, #3541).

``app.repository_branch_refresh_policy`` decides which rule governs a branch, the switch, cadence
and version line the branch refreshes with, whether it is due, and how a version-line refresh is
labelled and parented. These tests pin:

* matching: an exact name, ``*`` within one segment, ``**`` across segments, ``?``;
* the most specific rule wins (exact over glob, then the longest literal glob), whatever the order;
* a branch no rule matches follows the repository; the repository switch stays the master;
* a rule without an interval inherits the repository's, and every cadence is clamped to the floor;
* validation of patterns and version lines;
* ``<line>-<UTC timestamp>`` labels and the parent picked from the line's versions;
* the migration's shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.repository_branch_refresh_policy import (
    BranchRefreshRule,
    effective_branch_refresh,
    is_branch_due,
    is_glob,
    pattern_matches,
    resolve_branch_rule,
    rule_from_row,
    select_version_line_parent,
    validate_branch_pattern,
    validate_version_line,
    version_line_label,
)

_NOW = datetime(2026, 11, 3, 21, 0, tzinfo=timezone.utc)


# ===========================================================================
# Matching
# ===========================================================================


@pytest.mark.parametrize(
    ("pattern", "branch", "expected"),
    [
        ("main", "main", True),
        ("main", "main2", False),
        ("release/*", "release/2.0", True),
        ("release/*", "release/2.0/hotfix", False),  # `*` stays within one segment
        ("release/**", "release/2.0/hotfix", True),  # `**` crosses segments
        ("v?.x", "v2.x", True),
        ("v?.x", "v10.x", False),
        ("v?.x", "v/.x", False),  # `?` never matches `/`
        ("feature/*", "feature/", True),
        ("rel.ease", "relXease", False),  # `.` is literal
    ],
)
def test_pattern_matches(pattern: str, branch: str, expected: bool) -> None:
    assert pattern_matches(pattern, branch) is expected


def test_is_glob() -> None:
    assert is_glob("release/*") and is_glob("v?.x")
    assert not is_glob("main")


def test_no_rule_matches() -> None:
    assert resolve_branch_rule([BranchRefreshRule("release/*")], "main") is None


@pytest.mark.parametrize("reverse", [False, True])
def test_the_most_specific_rule_wins_whatever_the_order(reverse: bool) -> None:
    rules = [
        BranchRefreshRule("**"),
        BranchRefreshRule("release/*"),
        BranchRefreshRule("release/2.*"),
        BranchRefreshRule("release/2.0"),
    ]
    if reverse:
        rules.reverse()
    assert resolve_branch_rule(rules, "release/2.0").branch_pattern == "release/2.0"
    assert resolve_branch_rule(rules, "release/2.1").branch_pattern == "release/2.*"
    assert resolve_branch_rule(rules, "release/3.0").branch_pattern == "release/*"
    assert resolve_branch_rule(rules, "sandbox").branch_pattern == "**"


# ===========================================================================
# Effective settings
# ===========================================================================

_RULES = [
    BranchRefreshRule("main", refresh_interval_seconds=300, target_version_line="latest"),
    BranchRefreshRule("release/*", refresh_interval_seconds=3600, target_version_line="2.x"),
    BranchRefreshRule("sandbox", refresh_enabled=False),
]


def _effective(branch: str, *, enabled: bool = True, interval: int = 900, floor: int = 60):
    return effective_branch_refresh(
        _RULES, branch, repository_enabled=enabled, repository_interval_seconds=interval, floor_seconds=floor
    )


def test_a_rule_sets_the_switch_cadence_and_line() -> None:
    main = _effective("main")
    assert (main.enabled, main.interval_seconds, main.target_version_line, main.rule_pattern) == (
        True, 300, "latest", "main"
    )
    release = _effective("release/2.0")
    assert (release.interval_seconds, release.target_version_line, release.rule_pattern) == (
        3600, "2.x", "release/*"
    )
    assert _effective("sandbox").enabled is False


def test_an_unmatched_branch_follows_the_repository() -> None:
    other = _effective("feature/x", interval=900)
    assert (other.enabled, other.interval_seconds, other.target_version_line, other.rule_pattern) == (
        True, 900, None, None
    )


def test_a_rule_without_an_interval_inherits_the_repositorys() -> None:
    assert _effective("sandbox", interval=1200).interval_seconds == 1200


def test_the_repository_switch_is_the_master() -> None:
    assert _effective("main", enabled=False).enabled is False


def test_every_cadence_is_clamped_to_the_floor() -> None:
    assert _effective("main", floor=600).interval_seconds == 600


def test_is_branch_due() -> None:
    assert is_branch_due(None, 300, _NOW)
    assert is_branch_due(_NOW - timedelta(seconds=300), 300, _NOW)
    assert not is_branch_due(_NOW - timedelta(seconds=299), 300, _NOW)


# ===========================================================================
# Validation
# ===========================================================================


def test_valid_patterns_are_stripped() -> None:
    assert validate_branch_pattern("  release/*  ") == "release/*"


@pytest.mark.parametrize("bad", ["", "   ", "rel ease", "/main", "release/"])
def test_invalid_patterns_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_branch_pattern(bad)


def test_valid_lines_and_blank() -> None:
    assert validate_version_line(" 2.x ") == "2.x"
    assert validate_version_line("latest") == "latest"
    assert validate_version_line("") is None
    assert validate_version_line(None) is None


@pytest.mark.parametrize("bad", ["-2.x", "2 x", "2/x", "x" * 65])
def test_invalid_lines_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_version_line(bad)


# ===========================================================================
# Version-line labels and parents
# ===========================================================================


def test_version_line_label() -> None:
    assert version_line_label("2.x", _NOW) == "2.x-2026-11-03T21:00Z"


def test_the_parent_is_the_latest_version_of_the_line() -> None:
    versions = [
        {"id": "a", "version_id": "2.x-2026-10-01T00:00Z", "created_at": _NOW - timedelta(days=30)},
        {"id": "b", "version_id": "2.x-2026-11-01T00:00Z", "created_at": _NOW - timedelta(days=2)},
        {"id": "c", "version_id": "latest-2026-11-02T00:00Z", "created_at": _NOW - timedelta(days=1)},
        {"id": "d", "version_id": "2.xy", "created_at": _NOW},  # another line that shares a prefix
    ]
    assert select_version_line_parent(versions, "2.x")["id"] == "b"
    assert select_version_line_parent(versions, "latest")["id"] == "c"
    assert select_version_line_parent(versions, "3.x") is None


def test_a_version_labelled_exactly_the_line_belongs_to_it() -> None:
    assert select_version_line_parent([{"id": "x", "version_id": "2.x", "created_at": _NOW}], "2.x")["id"] == "x"


def test_rule_from_row() -> None:
    rule = rule_from_row(
        {"branch_pattern": "main", "refresh_enabled": False, "refresh_interval_seconds": 120, "target_version_line": ""}
    )
    assert rule == BranchRefreshRule(
        "main", refresh_enabled=False, refresh_interval_seconds=120, target_version_line=None
    )


# ===========================================================================
# Migration
# ===========================================================================

_MIGRATION = "apiome-db/scripts/V350__repository_branch_refresh_rules_3541.sql"


def test_migration_defines_the_rules_state_and_job_line(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS apiome.repository_branch_refresh_rule",
        "CONSTRAINT uq_repository_branch_refresh_rule_pattern UNIQUE (repository_id, branch_pattern)",
        "refresh_enabled          BOOLEAN NOT NULL DEFAULT TRUE",
        "CREATE TABLE IF NOT EXISTS apiome.repository_branch_refresh_state",
        "PRIMARY KEY (repository_id, branch)",
        "ADD COLUMN IF NOT EXISTS target_version_line VARCHAR(64)",
    ):
        assert fragment in text, fragment
