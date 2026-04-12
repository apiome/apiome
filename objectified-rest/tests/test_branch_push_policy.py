"""Branch push policy (#2583): project patterns + effective require-merge."""

from app.branch_push_policy import effective_require_merge_path, project_patterns_require_merge_path


def test_project_pattern_exact_match():
    meta = {"branchPushPolicy": {"patterns": [{"pattern": "main", "requireMergePath": True}]}}
    assert project_patterns_require_merge_path(meta, "main") is True
    assert project_patterns_require_merge_path(meta, "dev") is False


def test_project_pattern_glob():
    meta = {"branchPushPolicy": {"patterns": [{"pattern": "release/*", "requireMergePath": True}]}}
    assert project_patterns_require_merge_path(meta, "release/1.0") is True
    assert project_patterns_require_merge_path(meta, "main") is False


def test_effective_column_overrides_false_pattern():
    meta = {"branchPushPolicy": {"patterns": [{"pattern": "main", "requireMergePath": False}]}}
    row = {"name": "main", "require_merge_path": True}
    assert effective_require_merge_path(project_metadata=meta, branch_row=row) is True


def test_effective_pattern_when_column_false():
    meta = {"branchPushPolicy": {"patterns": [{"pattern": "main", "requireMergePath": True}]}}
    row = {"name": "main", "require_merge_path": False}
    assert effective_require_merge_path(project_metadata=meta, branch_row=row) is True
