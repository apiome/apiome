import pytest

from src.app.version_notes import (
    DEFAULT_VERSION_NOTES_LIMITS,
    CommitPolicyViolation,
    extract_breaking_hints_from_changelog,
    validate_version_notes,
)


def test_validate_version_notes_requires_short_message_when_policy_says_so():
    with pytest.raises(CommitPolicyViolation, match="Revision note"):
        validate_version_notes(None, None, DEFAULT_VERSION_NOTES_LIMITS)
    sm, cl = validate_version_notes("x", None, DEFAULT_VERSION_NOTES_LIMITS)
    assert sm == "x" and cl is None


def test_validate_version_notes_max_length():
    lim = DEFAULT_VERSION_NOTES_LIMITS
    with pytest.raises(CommitPolicyViolation, match="Revision note exceeds"):
        validate_version_notes("a" * (lim.max_short_message_chars + 1), None, lim)
    with pytest.raises(CommitPolicyViolation, match="Changelog exceeds"):
        validate_version_notes("ok", "b" * (lim.max_changelog_chars + 1), lim)


def test_extract_breaking_hints_from_changelog():
    text = "- breaking: foo\n- doc: bar\n* Breaking: baz"
    hints = extract_breaking_hints_from_changelog(text)
    assert "- breaking: foo" in hints
    assert "* Breaking: baz" in hints
