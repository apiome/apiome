"""Publish prechecks: descriptions + compatibility (#3212)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.change_report_render import bundled_system_template_row
from app.compatibility_engine import CompatibilityCheckResult
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_UNPUBLISHED = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "published": False,
    "version_id": "2.0.0",
    "description": None,
    "change_log": None,
}

_BASE_PUBLISHED = {
    "id": "base-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "published": True,
    "version_id": "1.0.0",
    "description": None,
    "change_log": None,
}

_OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "API", "version": "1.0.0"},
    "paths": {},
    "components": {"schemas": {}},
}

_PUBLISHED_ROW = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "version_id": "2.0.0",
    "short_message": None,
    "changelog": None,
    "visibility": "private",
    "published": True,
    "published_at": datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
    "published_immutable": True,
    "enabled": True,
    "parent_version_id": None,
    "merge_parent_version_id": None,
    "forked_from_revision_id": None,
    "upstream_project_id": None,
    "revision_locked": False,
    "metadata": None,
    "creator_name": None,
    "creator_email": None,
    "project_name": "P",
    "project_slug": "p",
    "created_at": None,
    "updated_at": None,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_publish_blocks_when_class_descriptions_missing():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()
    shared.get_version_by_id.return_value = draft
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": ""}]

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch("app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )

    assert res.status_code == 422
    assert "missing required descriptions" in res.json()["detail"]


def test_publish_blocks_breaking_without_allow_breaking():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()

    def gv(vid: str, _tid: str):
        if str(vid) == "vid-1":
            return draft
        if str(vid) == "base-1":
            return dict(_BASE_PUBLISHED)
        return None

    shared.get_version_by_id.side_effect = gv
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay"}
    shared.get_prior_published_baseline_revision_id.return_value = "base-1"

    breaking = CompatibilityCheckResult(
        overall="breaking",
        findings=tuple(),
        rule_hits=MappingProxyType({}),
        report_fingerprint="ab" * 32,
    )

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch("app.publication_change_report.db", shared), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.version_publish_prechecks.CompatibilityCheckEngine.run",
        return_value=breaking,
    ):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )

    assert res.status_code == 409
    body = res.json()
    assert "detail" in body
    assert "Breaking schema changes" in body["detail"]


def test_publish_allows_breaking_when_allow_breaking_true():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()

    def gv(vid: str, _tid: str):
        if str(vid) == "vid-1":
            return draft
        if str(vid) == "base-1":
            return dict(_BASE_PUBLISHED)
        return None

    shared.get_version_by_id.side_effect = gv
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}
    shared.get_prior_published_baseline_revision_id.return_value = "base-1"
    shared.publish_version.return_value = _PUBLISHED_ROW

    breaking = CompatibilityCheckResult(
        overall="breaking",
        findings=tuple(),
        rule_hits=MappingProxyType({}),
        report_fingerprint="cd" * 32,
    )

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.version_publish_prechecks.CompatibilityCheckEngine.run",
        return_value=breaking,
    ), patch("app.publication_change_report.db", shared), patch(
        "app.publication_change_report.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.publication_change_report.resolve_effective_change_report_template",
        return_value=bundled_system_template_row(),
    ):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"allowBreaking": True, "shortMessage": "Test revision note"},
        )

    assert res.status_code == 200
    shared.publish_version.assert_called_once()


# ===========================================================================
# GOV-1.4 (#4430): the prechecks compute the style-guide error-violation count
# ===========================================================================


def _direct_precheck(request_kwargs=None, guided_lint=None):
    """Call enforce_publish_prechecks directly with a happy-path mocked environment."""
    from app.models import VersionPublishRequest
    from app.version_publish_prechecks import enforce_publish_prechecks

    shared = MagicMock()
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]

    patches = [
        patch("app.version_publish_prechecks.db", shared),
        patch("app.publication_change_report.db", shared),
        patch("app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI),
    ]
    shared.get_prior_published_baseline_revision_id.return_value = None
    if guided_lint is not None:
        patches.append(patch("app.style_guide_engine.guided_lint_openapi_spec", guided_lint))

    request = VersionPublishRequest(**(request_kwargs or {"short_message": "Note"}))
    with patches[0], patches[1], patches[2], (
        patches[3] if len(patches) > 3 else patch("app.version_publish_prechecks.logger")
    ):
        return enforce_publish_prechecks(
            tenant_slug="acme",
            tenant_id="t1",
            project_id="pid-1",
            existing=dict(_UNPUBLISHED),
            request=request,
        )


def test_prechecks_report_the_style_guide_error_count():
    """The publish check consumes the error-level violation count under the resolved guide."""
    from types import SimpleNamespace

    guided = MagicMock(
        return_value=(
            SimpleNamespace(
                severity_counts={"error": 0, "warning": 1, "info": 0},
                findings=(),
            ),
            SimpleNamespace(guide_id="g-1", name="Team Guide", source="custom"),
        )
    )
    outcome = _direct_precheck(guided_lint=guided)

    assert outcome.lint_error_count == 0
    assert outcome.guide_id == "g-1"
    assert outcome.guide_name == "Team Guide"
    guided.assert_called_once_with(_OPENAPI, "t1", project_id="pid-1")


def test_prechecks_skip_returns_an_empty_outcome():
    """skip_publish_checks bypasses every gate — including the lint signal."""
    outcome = _direct_precheck(
        request_kwargs={
            "short_message": "Note",
            "skip_publish_checks": True,
            "force_publish_reason": "Test bypass",
        }
    )
    assert outcome.lint_error_count is None
    assert outcome.guide_id is None
    assert outcome.guide_name is None


def test_precheck_lint_fault_never_blocks_the_publish():
    """A style-guide lint fault degrades to 'no signal' — the other gates still run."""
    guided = MagicMock(side_effect=RuntimeError("guide engine down"))
    outcome = _direct_precheck(guided_lint=guided)
    assert outcome.lint_error_count is None
    assert outcome.guide_id is None


def test_prechecks_compute_a_zero_error_count_for_a_clean_spec():
    """End-to-end through the real engine: _OPENAPI has no error-level violations."""
    outcome = _direct_precheck()
    assert outcome.lint_error_count == 0
    assert outcome.guide_name == "Apiome Recommended"  # fallback guide (tenant 't1' unresolvable)
    assert outcome.guide_id is None


def test_prechecks_block_publish_on_style_guide_error_violations():
    """GOV-2.5 (#4437): error-severity guide violations return 422."""
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.schema_lint import LintFinding

    guided = MagicMock(
        return_value=(
            SimpleNamespace(
                severity_counts={"error": 2, "warning": 1, "info": 0},
                findings=(
                    LintFinding(
                        path="components.schemas.Pet",
                        category="documentation",
                        rule="schema-description",
                        severity="error",
                        message="Missing description",
                    ),
                    LintFinding(
                        path="components.schemas.Cat",
                        category="documentation",
                        rule="schema-description",
                        severity="error",
                        message="Missing description",
                    ),
                ),
            ),
            SimpleNamespace(guide_id="g-1", name="Team Guide", source="custom"),
        )
    )
    with pytest.raises(HTTPException) as exc:
        _direct_precheck(guided_lint=guided)
    assert exc.value.status_code == 422
    assert "2 style-guide error violation(s)" in exc.value.detail
    assert "Team Guide" in exc.value.detail
    assert "schema-description" in exc.value.detail


def test_prechecks_allow_warn_only_violations():
    """Warn/info violations do not block publish (GOV-2.5)."""
    from types import SimpleNamespace

    from app.schema_lint import LintFinding

    guided = MagicMock(
        return_value=(
            SimpleNamespace(
                severity_counts={"error": 0, "warning": 2, "info": 1},
                findings=(
                    LintFinding(
                        path="components.schemas.Pet",
                        category="naming",
                        rule="schema-pascal-case",
                        severity="warning",
                        message="Use PascalCase",
                    ),
                ),
            ),
            SimpleNamespace(guide_id="g-1", name="Team Guide", source="custom"),
        )
    )
    outcome = _direct_precheck(guided_lint=guided)
    assert outcome.lint_error_count == 0
    assert outcome.severity_counts == {"error": 0, "warning": 2, "info": 1}


def test_publish_force_requires_reason():
    """skipPublishChecks without forcePublishReason is rejected at validation."""
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()
    shared.get_version_by_id.return_value = draft
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}

    with patch("app.versions_routes.db", shared):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Note", "skipPublishChecks": True},
        )

    assert res.status_code == 422
    assert "forcePublishReason" in str(res.json()["detail"])


def test_publish_force_audits_reason():
    """Force publish records the override reason to workflow audit (GOV-2.5)."""
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()
    shared.get_version_by_id.return_value = draft
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}
    shared.publish_version.return_value = _PUBLISHED_ROW

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch("app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI), patch(
        "app.publication_change_report.db", shared,
    ), patch(
        "app.publication_change_report.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.publication_change_report.resolve_effective_change_report_template",
        return_value=bundled_system_template_row(),
    ):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={
                "shortMessage": "Note",
                "skipPublishChecks": True,
                "forcePublishReason": "Emergency hotfix for prod",
            },
        )

    assert res.status_code == 200
    shared.insert_workflow_audit.assert_called_once()
    args = shared.insert_workflow_audit.call_args[0]
    assert args[3] == "version.publish_checks_override"
    assert args[4] == "success"
    assert shared.insert_workflow_audit.call_args[0][6]["reason"] == "Emergency hotfix for prod"
