"""Unit tests for revision governance lifecycle tags (#739)."""

import pytest

from app.revision_lifecycle import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_BETA,
    LIFECYCLE_DEPRECATED,
    LIFECYCLE_STABLE,
    effective_lifecycle,
    prepare_version_metadata_update,
    validate_lifecycle_transition,
)


def test_effective_lifecycle_explicit():
    assert effective_lifecycle({"lifecycle": "beta"}) == LIFECYCLE_BETA
    assert effective_lifecycle({"lifecycle": "Archived"}) == LIFECYCLE_ARCHIVED


def test_effective_lifecycle_infer_deprecated():
    assert effective_lifecycle({"deprecated": True}) == LIFECYCLE_DEPRECATED
    assert effective_lifecycle({}) == LIFECYCLE_STABLE


def test_transition_beta_to_stable():
    validate_lifecycle_transition(LIFECYCLE_BETA, LIFECYCLE_STABLE)


def test_transition_archived_blocked():
    with pytest.raises(ValueError):
        validate_lifecycle_transition(LIFECYCLE_ARCHIVED, LIFECYCLE_STABLE, allow_exit_archived=False)


def test_transition_archived_admin_exit():
    validate_lifecycle_transition(LIFECYCLE_ARCHIVED, LIFECYCLE_STABLE, allow_exit_archived=True)


def test_prepare_sets_deprecated_for_deprecated_lifecycle():
    out = prepare_version_metadata_update(None, {"lifecycle": "deprecated"})
    assert out["lifecycle"] == LIFECYCLE_DEPRECATED
    assert out["deprecated"] is True


def test_prepare_clears_deprecated_when_stable_after_deprecated():
    existing = {"lifecycle": "deprecated", "deprecated": True}
    out = prepare_version_metadata_update(existing, {"lifecycle": "stable"})
    assert out["lifecycle"] == LIFECYCLE_STABLE
    assert out.get("deprecated") is False


def test_prepare_rejects_invalid_token():
    with pytest.raises(ValueError, match="Invalid lifecycle"):
        prepare_version_metadata_update(None, {"lifecycle": "gamma"})
