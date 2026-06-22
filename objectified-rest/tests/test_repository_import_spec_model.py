"""Round-trip + shape tests for the RepositoryImportSpec model (RAR-1.1, #3512).

The acceptance criterion is that ``options_json`` round-trips a full
``SpecImportOptions`` payload losslessly. The DAO persists the options as JSONB
(``json.dumps`` in, dict out), so the lossless guarantee lives in the Pydantic
serialization layer exercised here.
"""

import json

from app.models import (
    REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
    RepositoryImportSpec,
    SpecImportOptions,
)


def _full_options() -> SpecImportOptions:
    """Every SpecImportOptions field set to a non-default value."""
    return SpecImportOptions(
        selected_schemas=["Pet", "Order", "User"],
        dry_run=True,
        incremental_mode=True,
        apply_naming_convention=True,
        class_naming_convention="PascalCase",
        property_naming_convention="snake_case",
        auto_layout=True,
        create_relationships=True,
        skip_duplicate_versions=True,
    )


def test_options_json_round_trips_losslessly() -> None:
    options = _full_options()

    # Serialize as the DAO would (the JSONB column), then read back.
    options_json = options.model_dump()
    rehydrated = SpecImportOptions.model_validate(json.loads(json.dumps(options_json)))

    assert rehydrated == options
    # Defaults must not silently drop any field on the way through JSON.
    assert set(options_json.keys()) == set(SpecImportOptions().model_dump().keys())


def test_repository_import_spec_round_trips_through_json() -> None:
    spec = RepositoryImportSpec(
        id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        repository_id="33333333-3333-3333-3333-333333333333",
        branch="main",
        path="specs/petstore.yaml",
        project_id="44444444-4444-4444-4444-444444444444",
        source_kind="openapi-3",
        format_override="yaml",
        content_type="application/yaml",
        options=_full_options(),
        created_by="55555555-5555-5555-5555-555555555555",
    )

    payload = spec.model_dump()
    restored = RepositoryImportSpec.model_validate(json.loads(json.dumps(payload)))

    assert restored == spec
    assert restored.options == _full_options()


def test_spec_defaults_match_table_defaults() -> None:
    """Unset envelope/options default the way the migration column defaults do."""
    spec = RepositoryImportSpec(
        tenant_id="22222222-2222-2222-2222-222222222222",
        repository_id="33333333-3333-3333-3333-333333333333",
        branch="main",
        path="specs/petstore.yaml",
        project_id="44444444-4444-4444-4444-444444444444",
        source_kind="openapi-3",
    )

    assert spec.spec_schema_version == REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION == 1
    assert spec.options == SpecImportOptions()
    assert spec.format_override is None
    assert spec.content_type is None
    assert spec.id is None


def test_repository_import_spec_forbids_unknown_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepositoryImportSpec(
            tenant_id="22222222-2222-2222-2222-222222222222",
            repository_id="33333333-3333-3333-3333-333333333333",
            branch="main",
            path="specs/petstore.yaml",
            project_id="44444444-4444-4444-4444-444444444444",
            source_kind="openapi-3",
            unexpected_field="boom",
        )
