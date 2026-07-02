"""Versioned spec envelope upgrade-on-read tests (RAR-1.4, #3515).

The persisted import spec is a forward-compatible envelope
``{ spec_schema_version, options }``. A read of an older-version envelope must
migrate the stored options blob forward to the current shape via the registered
upgrade path. These tests cover the version-0 (legacy, unmarked) -> version-1
upgrade and the read entry points that apply it.
"""

import json

import pytest
from pydantic import ValidationError

from app.models import (
    REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
    SpecImportOptions,
    load_repository_import_options,
    upgrade_repository_import_options,
)


def test_legacy_v0_blob_upgrades_to_current_shape() -> None:
    """A version-0 blob with a removed legacy key upgrades to valid current options.

    The legacy key (``legacy_flatten``, no longer part of ``SpecImportOptions``)
    is dropped by the v0 -> v1 upgrader so the result validates under the current
    ``extra="forbid"`` model, while recognized keys survive.
    """
    legacy_blob = {
        "legacy_flatten": True,  # removed field — must be dropped on upgrade
        "apply_naming_convention": True,
        "class_naming_convention": "PascalCase",
        "selected_schemas": ["Pet", "Order"],
    }

    migrated = upgrade_repository_import_options(legacy_blob, from_version=0)

    assert "legacy_flatten" not in migrated
    # Recognized values carry through the upgrade unchanged.
    assert migrated["apply_naming_convention"] is True
    assert migrated["class_naming_convention"] == "PascalCase"
    assert migrated["selected_schemas"] == ["Pet", "Order"]

    # The migrated dict validates and missing fields fall back to defaults.
    options = SpecImportOptions.model_validate(migrated)
    assert options.class_naming_convention == "PascalCase"
    assert options.skip_duplicate_versions is False


def test_missing_version_treated_as_legacy_v0() -> None:
    """A ``None`` version is treated as the unversioned legacy shape (v0)."""
    migrated = upgrade_repository_import_options(
        {"legacy_flatten": True, "dry_run": True}, from_version=None
    )
    assert migrated == {"dry_run": True}


def test_current_version_is_passthrough_copy() -> None:
    """Options already at the current version are returned unchanged (a copy)."""
    options = {"dry_run": True, "auto_layout": True}
    migrated = upgrade_repository_import_options(
        options, from_version=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION
    )
    assert migrated == options
    assert migrated is not options  # shallow copy, not the original reference


def test_none_options_upgrades_to_empty_dict() -> None:
    """A ``None`` options blob migrates to an empty (all-defaults) dict."""
    assert upgrade_repository_import_options(None, from_version=0) == {}


def test_future_version_rejected() -> None:
    """A version newer than this code understands raises (no silent downgrade)."""
    with pytest.raises(ValueError, match="newer than the supported version"):
        upgrade_repository_import_options(
            {}, from_version=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION + 1
        )


def test_load_from_dao_row_applies_upgrade() -> None:
    """``load_repository_import_options`` upgrades a DAO-shaped row on read."""
    row = {
        "spec_schema_version": 0,
        "options_json": {
            "legacy_flatten": True,
            "incremental_mode": True,
            "property_naming_convention": "snake_case",
        },
    }

    options = load_repository_import_options(row)

    assert isinstance(options, SpecImportOptions)
    assert options.incremental_mode is True
    assert options.property_naming_convention == "snake_case"


def test_load_decodes_jsonb_text_column() -> None:
    """A JSONB column returned as a JSON string is decoded transparently."""
    row = {
        "spec_schema_version": 1,
        "options_json": json.dumps({"dry_run": True}),
    }
    options = load_repository_import_options(row)
    assert options.dry_run is True


def test_load_accepts_model_field_name() -> None:
    """The options blob may live under ``options`` (model field) not ``options_json``."""
    row = {"spec_schema_version": 1, "options": {"auto_layout": True}}
    options = load_repository_import_options(row)
    assert options.auto_layout is True


def test_load_none_and_empty_envelopes_default() -> None:
    """A ``None`` or empty envelope yields default options, never an error."""
    assert load_repository_import_options(None) == SpecImportOptions()
    assert load_repository_import_options({}) == SpecImportOptions()
    assert load_repository_import_options(
        {"spec_schema_version": 1}
    ) == SpecImportOptions()


def test_load_rejects_unknown_field_at_current_version() -> None:
    """An unknown key in a *current*-version row is not silently stripped.

    The upgrade path only rewrites *older* envelopes; a current-version row with
    an unexpected key is a genuine error and must fail validation rather than be
    quietly accepted.
    """
    row = {"spec_schema_version": 1, "options_json": {"bogus_key": 1}}
    with pytest.raises(ValidationError):
        load_repository_import_options(row)
