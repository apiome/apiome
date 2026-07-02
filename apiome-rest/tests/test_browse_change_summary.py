"""Tests for browse publication change summaries (#3246)."""

from app.browse_change_summary import browse_version_changes_summary


def test_prefers_structured_when_change_model_has_paths_and_classes():
    model = {
        "schemas": {"added": [{"name": "A"}], "removed": [], "modified": [{"name": "B"}]},
        "documentation": [
            {"scope": "operation", "path": "/p1", "changeKind": "added"},
            {"scope": "operation", "path": "/p2", "changeKind": "modified"},
        ],
    }
    out = browse_version_changes_summary(
        change_model_json=model,
        change_log="ignored",
        description=None,
        baseline_version_slug="2.0.0",
    )
    assert out is not None
    assert "2 paths changed" in out
    assert "~2 classes" in out
    assert "vs v2.0.0" in out


def test_falls_back_to_change_log_when_no_structure():
    out = browse_version_changes_summary(
        change_model_json=None,
        change_log="Major: removed legacy /charges\nmore",
        description="desc",
        baseline_version_slug=None,
    )
    assert out == "Major: removed legacy /charges"


def test_falls_back_to_description_without_change_log():
    out = browse_version_changes_summary(
        change_model_json={},
        change_log=None,
        description="Only a description",
        baseline_version_slug=None,
    )
    assert out == "Only a description"
