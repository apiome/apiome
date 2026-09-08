"""Generation-settings persistence — SDK-3.4 (#4494).

The store's contract with ``db`` patched: which scopes contribute, what a scope with nothing saved
answers, and that an unreadable row degrades rather than raising.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

from app.sdk_generation_settings import (
    SETTINGS_SOURCE_DEFAULT,
    SETTINGS_SOURCE_MERGED,
    SETTINGS_SOURCE_PROJECT,
    SETTINGS_SOURCE_TENANT,
    PatternContext,
    SdkSettingsError,
)
from app.sdk_generation_settings_store import (
    audit_detail,
    clear_settings,
    load_branding,
    load_settings,
    save_settings,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
_CTX = PatternContext(tenant="acme", project="petstore", version="1.0.0", year="2026")


def _row(
    settings: Any,
    *,
    project_id: Optional[str] = None,
    row_id: str = "33333333-3333-4333-8333-333333333333",
) -> Dict[str, Any]:
    """One stored settings row."""
    return {
        "id": row_id,
        "tenant_id": _TENANT,
        "project_id": project_id,
        "settings": settings,
        "content_fingerprint": "sha256:" + "0" * 64,
        "created_by": None,
        "updated_by": "44444444-4444-4444-8444-444444444444",
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ===========================================================================
# Reading
# ===========================================================================


def test_a_scope_with_nothing_saved_answers_default() -> None:
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=[],
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.source == SETTINGS_SOURCE_DEFAULT
    assert out.scope == "project"
    assert out.scope_body is None
    assert out.settings.user_agent is None
    assert out.content_fingerprint.startswith("sha256:")
    assert out.degraded is False


def test_a_project_inherits_the_tenant_when_it_saved_nothing() -> None:
    rows = [_row({"userAgent": "acme-sdk/1.0"})]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.source == SETTINGS_SOURCE_TENANT
    assert out.settings.user_agent == "acme-sdk/1.0"
    # Nothing is saved at project scope, so an editor sees an empty override.
    assert out.scope_body is None


def test_both_scopes_contributing_reports_merged() -> None:
    rows = [
        _row({"userAgent": "acme-sdk/1.0", "licenseHeader": "Copyright Acme"}),
        _row({"userAgent": "petstore-sdk/2.0"}, project_id=_PROJECT, row_id=_PROJECT),
    ]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.source == SETTINGS_SOURCE_MERGED
    assert out.settings.user_agent == "petstore-sdk/2.0"
    assert out.settings.license_header == "Copyright Acme"
    assert out.scope_body == {"userAgent": "petstore-sdk/2.0"}
    assert out.tenant_settings_id is not None
    assert out.project_settings_id == _PROJECT


def test_the_precedence_does_not_depend_on_row_order() -> None:
    """Rows are split on ``project_id``, so a reordered query cannot invert the override."""
    rows = [
        _row({"userAgent": "petstore-sdk/2.0"}, project_id=_PROJECT, row_id=_PROJECT),
        _row({"userAgent": "acme-sdk/1.0"}),
    ]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.settings.user_agent == "petstore-sdk/2.0"


def test_a_tenant_read_ignores_a_project_row() -> None:
    """The tenant scope must show its own defaults, not a project's override of them."""
    rows = [_row({"userAgent": "acme-sdk/1.0"})]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ) as read:
        out = load_settings(_TENANT, None, PatternContext(tenant="acme"))
    read.assert_called_once_with(_TENANT, None)
    assert out.source == SETTINGS_SOURCE_TENANT
    assert out.scope == "tenant"
    assert out.project_settings_id is None


def test_a_project_only_override_reports_project() -> None:
    rows = [_row({"userAgent": "petstore-sdk/2.0"}, project_id=_PROJECT, row_id=_PROJECT)]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.source == SETTINGS_SOURCE_PROJECT


def test_a_store_failure_degrades_instead_of_raising() -> None:
    """Every branding read path would break if this raised."""
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        side_effect=RuntimeError("connection reset"),
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.source == SETTINGS_SOURCE_DEFAULT
    assert out.degraded is True


def test_an_unreadable_row_is_skipped_and_flagged() -> None:
    """A body a newer release wrote is substituted for, visibly, not raised on."""
    rows = [_row("not-an-object")]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.degraded is True
    assert out.settings.user_agent is None


def test_a_missing_tenant_never_reaches_the_store() -> None:
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows"
    ) as read:
        out = load_settings("", None)
    read.assert_not_called()
    assert out.source == SETTINGS_SOURCE_DEFAULT


def test_resolved_values_substitute_the_context() -> None:
    rows = [
        _row(
            {
                "packageNamePatterns": {"npm": "@{tenant}/{project}-sdk"},
                "licenseHeader": "Copyright (c) {year} Acme",
                "userAgent": "{project}-sdk/{version}",
            }
        )
    ]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, _PROJECT, _CTX)
    assert out.resolved.package_names == {"npm": "@acme/petstore-sdk"}
    assert out.resolved.license_header == "Copyright (c) 2026 Acme"
    assert out.resolved.user_agent == "petstore-sdk/1.0.0"


# ===========================================================================
# load_branding
# ===========================================================================


def test_load_branding_returns_the_resolved_values_only() -> None:
    rows = [_row({"userAgent": "acme-sdk/{version}"})]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        branding = load_branding(_TENANT, _PROJECT, _CTX)
    assert branding.user_agent == "acme-sdk/1.0.0"
    assert branding.license_header is None


def test_load_branding_without_a_tenant_is_empty_and_reads_nothing() -> None:
    """The anonymous surface may resolve a revision whose tenant it could not determine."""
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows"
    ) as read:
        branding = load_branding(None, _PROJECT, _CTX)
    read.assert_not_called()
    assert branding.is_empty()


# ===========================================================================
# Writing
# ===========================================================================


def test_saving_stores_only_the_named_keys_and_returns_what_is_in_force() -> None:
    stored = _row({"userAgent": "petstore-sdk/2.0"}, project_id=_PROJECT, row_id=_PROJECT)
    with patch(
        "app.sdk_generation_settings_store.db.upsert_sdk_generation_settings",
        return_value=stored,
    ) as upsert, patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=[_row({"licenseHeader": "Copyright Acme"}), stored],
    ):
        out = save_settings(
            _TENANT,
            project_id=_PROJECT,
            body={"userAgent": "petstore-sdk/2.0"},
            actor_id="44444444-4444-4444-8444-444444444444",
            context=_CTX,
        )
    body = upsert.call_args.kwargs["settings"]
    assert body["userAgent"] == "petstore-sdk/2.0"
    assert "licenseHeader" not in body
    assert upsert.call_args.kwargs["content_fingerprint"].startswith("sha256:")
    # The response is the merged result, not just what was written.
    assert out.settings.license_header == "Copyright Acme"


def test_saving_an_invalid_body_never_reaches_the_store() -> None:
    with patch(
        "app.sdk_generation_settings_store.db.upsert_sdk_generation_settings"
    ) as upsert:
        with pytest.raises(SdkSettingsError):
            save_settings(_TENANT, body={"userAgent": "bad\nagent"})
    upsert.assert_not_called()


def test_a_write_returning_no_row_is_an_error() -> None:
    with patch(
        "app.sdk_generation_settings_store.db.upsert_sdk_generation_settings",
        return_value=None,
    ):
        with pytest.raises(RuntimeError):
            save_settings(_TENANT, body={"userAgent": "acme/1.0"})


def test_clearing_reports_whether_a_row_existed() -> None:
    with patch(
        "app.sdk_generation_settings_store.db.delete_sdk_generation_settings",
        return_value=1,
    ):
        assert clear_settings(_TENANT, project_id=_PROJECT) is True
    with patch(
        "app.sdk_generation_settings_store.db.delete_sdk_generation_settings",
        return_value=0,
    ):
        assert clear_settings(_TENANT) is False


def test_the_audit_payload_records_the_header_by_length_not_verbatim() -> None:
    """The ledger is not a document store, and a licence may be four thousand characters."""
    rows = [_row({"licenseHeader": "Copyright Acme", "userAgent": "acme/1.0"})]
    with patch(
        "app.sdk_generation_settings_store.db.get_sdk_generation_settings_rows",
        return_value=rows,
    ):
        out = load_settings(_TENANT, None, PatternContext(tenant="acme"))
    detail = audit_detail(out)
    assert detail["settings"]["licenseHeader"] == "<14 characters>"
    assert detail["settings"]["userAgent"] == "acme/1.0"
    assert detail["contentFingerprint"] == out.content_fingerprint
    assert detail["scope"] == "tenant"
