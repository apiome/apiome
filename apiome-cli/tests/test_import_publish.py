"""Tests for import publish visibility normalization."""

from __future__ import annotations

import pytest

from apiome_cli.import_.publish import (
    normalize_cli_import_visibility,
    resolve_publish_visibility,
    resolve_type_publish_system,
)


def test_normalize_cli_import_visibility_maps_private_to_protected() -> None:
    assert normalize_cli_import_visibility("private") == "protected"
    assert normalize_cli_import_visibility("PRIVATE") == "protected"


def test_normalize_cli_import_visibility_accepts_public_and_protected() -> None:
    assert normalize_cli_import_visibility("public") == "public"
    assert normalize_cli_import_visibility("protected") == "protected"


def test_normalize_cli_import_visibility_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="--publish must be 'public' or 'private'"):
        normalize_cli_import_visibility("draft")


def test_resolve_publish_visibility_prefers_publish_flag() -> None:
    assert resolve_publish_visibility(publish="public", visibility=None) == "public"
    assert resolve_publish_visibility(publish="private", visibility=None) == "protected"


def test_resolve_publish_visibility_accepts_visibility_alias() -> None:
    assert resolve_publish_visibility(publish=None, visibility="private") == "protected"


def test_resolve_publish_visibility_rejects_both_flags() -> None:
    with pytest.raises(ValueError, match="only one of --publish and --visibility"):
        resolve_publish_visibility(publish="public", visibility="private")


def test_resolve_type_publish_system_maps_public_to_system_library() -> None:
    assert resolve_type_publish_system(publish="public", visibility=None) is True
    assert resolve_type_publish_system(publish=None, visibility="public") is True


def test_resolve_type_publish_system_maps_private_to_tenant_scope() -> None:
    assert resolve_type_publish_system(publish="private", visibility=None) is False
    assert resolve_type_publish_system(publish=None, visibility="private") is False


def test_resolve_type_publish_system_omits_when_unset() -> None:
    assert resolve_type_publish_system(publish=None, visibility=None) is None


def test_resolve_type_publish_system_rejects_both_flags() -> None:
    with pytest.raises(ValueError, match="only one of --publish and --visibility"):
        resolve_type_publish_system(publish="public", visibility="private")
