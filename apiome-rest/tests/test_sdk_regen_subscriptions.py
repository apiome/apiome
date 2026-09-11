"""Which SDKs regenerate on publish — SDK-4.3 (#4497).

:mod:`app.sdk_regen_subscriptions` owns the subscription vocabulary, its store helpers and the
moment a publish becomes work. These tests assert:

* the delivery-mode and options vocabulary refuses what it does not know — a misspelt option must
  never silently publish, and ``deliveryMode`` has no default;
* stored options are read back conservatively;
* the publish route queues the regen, and the queueing step never fails a publish.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from test_publish_catalog_item_gate import _OPENAPI, _PUBLISHED_ROW, _UNPUBLISHED

from app.auth import validate_authentication
from app.main import app
from app.sdk_regen_subscriptions import (
    DELIVERY_MODE_GIT,
    DELIVERY_MODE_REGISTRY,
    DELIVERY_MODE_REGISTRY_AND_GIT,
    DELIVERY_MODES,
    REGEN_ECOSYSTEMS,
    RegenSubscriptionError,
    delete_subscription,
    enqueue_regen_on_publish,
    includes_git,
    includes_registry,
    list_subscriptions,
    normalize_delivery_mode,
    normalize_ecosystem,
    normalize_options,
    options_object,
    read_options,
    save_subscription,
    set_subscription_active,
    subscription_out,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_USER = "44444444-4444-4444-8444-444444444444"


def _row(**fields: Any) -> Dict[str, Any]:
    """A stored ``sdk_regen_subscriptions`` row."""
    row: Dict[str, Any] = {
        "id": "sub-1",
        "ecosystem": "npm",
        "delivery_mode": DELIVERY_MODE_REGISTRY_AND_GIT,
        "options": {"dryRun": False},
        "active": True,
        "updated_by": _USER,
    }
    row.update(fields)
    return row


# --------------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------------
def test_the_vocabulary_is_the_sdk_4_1_layouts_and_three_delivery_modes():
    assert REGEN_ECOSYSTEMS == ("npm", "pypi")
    assert DELIVERY_MODES == ("registry", "git", "registry_and_git")
    assert includes_registry("registry") and includes_registry("registry_and_git")
    assert not includes_registry("git") and not includes_registry(None)
    assert includes_git("git") and includes_git("registry_and_git")
    assert not includes_git("registry")


def test_ecosystem_and_mode_are_normalised_or_refused():
    assert normalize_ecosystem(" NPM ") == "npm"
    assert normalize_delivery_mode("Registry_And_Git") == "registry_and_git"
    with pytest.raises(RegenSubscriptionError, match="gomod"):
        normalize_ecosystem("gomod")
    # No default: an absent mode is refused, never assumed.
    for missing in (None, "", "publish"):
        with pytest.raises(RegenSubscriptionError, match="deliveryMode"):
            normalize_delivery_mode(missing)


def test_registry_options_default_to_publishing_and_git_options_are_empty():
    assert normalize_options(DELIVERY_MODE_REGISTRY, None) == {"dryRun": False}
    assert normalize_options(DELIVERY_MODE_REGISTRY_AND_GIT, {"dryRun": True}) == {"dryRun": True}
    assert normalize_options(DELIVERY_MODE_GIT, {}) == {}


def test_an_unknown_or_misspelt_option_is_refused_rather_than_ignored():
    """``dry_run`` ignored would publish for real — the one mistake worth a 422."""
    with pytest.raises(RegenSubscriptionError, match="'dry_run'"):
        normalize_options(DELIVERY_MODE_REGISTRY, {"dry_run": True})


def test_dry_run_must_be_a_boolean_and_belongs_to_registry_modes_only():
    with pytest.raises(RegenSubscriptionError, match="true or false"):
        normalize_options(DELIVERY_MODE_REGISTRY, {"dryRun": "yes"})
    with pytest.raises(RegenSubscriptionError, match="registry step"):
        normalize_options(DELIVERY_MODE_GIT, {"dryRun": True})


def test_stored_options_are_read_conservatively():
    # Only an exact `true` on a registry mode rehearses.
    assert read_options("registry", {"dryRun": True}).dry_run is True
    assert read_options("registry", {"dryRun": "true"}).dry_run is False
    assert read_options("registry", None).dry_run is False
    assert read_options("git", {"dryRun": True}).dry_run is False
    # Anything a newer build stored is ignored, not fatal.
    assert options_object("registry_and_git", {"dryRun": True, "future": 1}) == {"dryRun": True}
    assert options_object("git", {"dryRun": True}) == {}


def test_a_row_projects_onto_its_api_description():
    out = subscription_out(_row(options={"dryRun": True}))
    assert out.model_dump(by_alias=True) == {
        "schemaVersion": "sdk.regen-subscription.v1",
        "ecosystem": "npm",
        "deliveryMode": "registry_and_git",
        "options": {"dryRun": True},
        "active": True,
        "createdAt": None,
        "updatedAt": None,
        "updatedBy": _USER,
    }


# --------------------------------------------------------------------------------------------
# Store helpers
# --------------------------------------------------------------------------------------------
def test_saving_validates_every_field_and_reports_every_problem_at_once():
    with patch("app.sdk_regen_subscriptions.db.upsert_sdk_regen_subscription") as upsert:
        with pytest.raises(RegenSubscriptionError) as refused:
            save_subscription(_TENANT, _PROJECT, ecosystem="gomod", delivery_mode="publish")
    assert len(refused.value.errors) == 2
    upsert.assert_not_called()


def test_saving_stores_normalised_options_for_the_mode():
    with patch(
        "app.sdk_regen_subscriptions.db.upsert_sdk_regen_subscription",
        return_value=_row(delivery_mode="registry", options={"dryRun": False}),
    ) as upsert:
        out = save_subscription(
            _TENANT,
            _PROJECT,
            ecosystem="NPM",
            delivery_mode="registry",
            options=None,
            active=False,
            actor_id=_USER,
        )
    assert upsert.call_args.kwargs == {
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "ecosystem": "npm",
        "delivery_mode": "registry",
        "options": {"dryRun": False},
        "active": False,
        "actor_id": _USER,
    }
    assert out.options == {"dryRun": False}


def test_a_write_that_returns_nothing_is_an_error_not_a_silent_success():
    with patch("app.sdk_regen_subscriptions.db.upsert_sdk_regen_subscription", return_value=None):
        with pytest.raises(RuntimeError):
            save_subscription(_TENANT, _PROJECT, ecosystem="npm", delivery_mode="git")


def test_enable_disable_and_delete_address_one_ecosystem():
    with patch(
        "app.sdk_regen_subscriptions.db.set_sdk_regen_subscription_active",
        return_value=_row(active=False),
    ) as toggle:
        assert set_subscription_active(_TENANT, _PROJECT, "NPM", active=False).active is False
    toggle.assert_called_once_with(_TENANT, _PROJECT, "npm", active=False, actor_id=None)

    with patch(
        "app.sdk_regen_subscriptions.db.set_sdk_regen_subscription_active", return_value=None
    ):
        assert set_subscription_active(_TENANT, _PROJECT, "pypi", active=True) is None

    with patch(
        "app.sdk_regen_subscriptions.db.delete_sdk_regen_subscription", side_effect=[1, 0]
    ):
        assert delete_subscription(_TENANT, _PROJECT, "npm") is True
        assert delete_subscription(_TENANT, _PROJECT, "npm") is False

    with pytest.raises(RegenSubscriptionError):
        delete_subscription(_TENANT, _PROJECT, "gomod")


def test_listing_never_takes_a_screen_down():
    with patch(
        "app.sdk_regen_subscriptions.db.list_sdk_regen_subscriptions",
        side_effect=RuntimeError("db down"),
    ):
        assert list_subscriptions(_TENANT, _PROJECT) == []
    with patch(
        "app.sdk_regen_subscriptions.db.list_sdk_regen_subscriptions",
        return_value=[_row(), _row(ecosystem="pypi", delivery_mode="git", options={})],
    ):
        assert [s.ecosystem for s in list_subscriptions(_TENANT, _PROJECT)] == ["npm", "pypi"]


# --------------------------------------------------------------------------------------------
# The publish event
# --------------------------------------------------------------------------------------------
def test_a_publish_queues_the_subscription_matrix():
    with patch(
        "app.sdk_regen_subscriptions.db.enqueue_sdk_regen_run",
        return_value=[{"ecosystem": "npm"}, {"ecosystem": "pypi"}],
    ) as enqueue:
        queued = enqueue_regen_on_publish(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            published_revision_id=_REVISION,
            version_line="1.4.2",
            actor_id=_USER,
        )
    assert queued == 2
    enqueue.assert_called_once_with(
        tenant_id=_TENANT,
        project_id=_PROJECT,
        version_id=_REVISION,
        version_line="1.4.2",
        published_by=_USER,
    )


def test_queueing_never_fails_a_publish():
    with patch(
        "app.sdk_regen_subscriptions.db.enqueue_sdk_regen_run", side_effect=RuntimeError("db down")
    ):
        assert (
            enqueue_regen_on_publish(
                tenant_id=_TENANT, project_id=_PROJECT, published_revision_id=_REVISION
            )
            == 0
        )


def test_a_unit_test_handle_never_reaches_the_database():
    with patch("app.sdk_regen_subscriptions.db.enqueue_sdk_regen_run") as enqueue:
        assert enqueue_regen_on_publish(tenant_id="t1", project_id="pid-1", published_revision_id="vid-1") == 0
    enqueue.assert_not_called()


@pytest.fixture
def _authenticated():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "t1",
        "user_id": "user-a",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.clear()


def test_the_publish_route_schedules_the_regen_after_publishing(_authenticated):
    """The acceptance criterion's trigger: publishing a version queues its subscribed SDKs."""
    shared = MagicMock()
    shared.get_version_by_id.return_value = dict(_UNPUBLISHED)
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "p", "metadata": {}}
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.publish_version.return_value = dict(_PUBLISHED_ROW)
    regen = MagicMock()

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI
    ), patch(
        "app.version_publish_prechecks.resolve_baseline_revision_id_for_change_report",
        return_value=None,
    ), patch("app.versions_routes.generate_change_report_on_publish", MagicMock()), patch(
        "app.versions_routes.generate_version_changelog_on_publish", MagicMock()
    ), patch("app.versions_routes.notify_version_published_on_publish", MagicMock()), patch(
        "app.versions_routes.enqueue_regen_on_publish", regen
    ):
        response = TestClient(app).post(
            "/v1/versions/acme/pid-1/vid-1/publish", json={"shortMessage": "Test revision note"}
        )

    assert response.status_code == 200
    regen.assert_called_once_with(
        tenant_id="t1",
        project_id="pid-1",
        published_revision_id="vid-1",
        version_line="2.0.0",
        actor_id="user-a",
    )


def test_a_refused_publish_queues_nothing(_authenticated):
    shared = MagicMock()
    shared.get_version_by_id.return_value = {**_UNPUBLISHED, "published": True}
    regen = MagicMock()
    with patch("app.versions_routes.db", shared), patch(
        "app.versions_routes.enqueue_regen_on_publish", regen
    ):
        response = TestClient(app).post("/v1/versions/acme/pid-1/vid-1/publish", json={})
    assert response.status_code == 400
    regen.assert_not_called()
