"""Endpoint tests for the lint-fix plan and apply routes — GVM-3.2 (#5870).

The database, the OpenAPI reconstruction and the import pipeline are patched; the plan itself
is the real :mod:`app.lint_fix_plan` over :data:`tests.test_lint_fix_plan.MULTI_DEFECT`.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.lint_fix_plan import build_fix_plan
from app.lint_fix_routes import AUDIT_LINT_FIX_APPLIED, SOURCE_LINT_FIX
from app.main import app
from app.openapi_overlay import apply_overlays
from app.style_guide_engine import builtin_fallback_guide
from tests.test_lint_fix_plan import MULTI_DEFECT

client = TestClient(app)

_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}
PID = "00000000-0000-0000-0000-0000000000a1"
VID = "00000000-0000-0000-0000-0000000000b1"
NEW_VID = "00000000-0000-0000-0000-0000000000b2"
BASE = f"/v1/versions/acme/{PID}/{VID}/lint/fixes"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _version(vid: str = VID, *, published: bool = False) -> Dict[str, Any]:
    return {"id": vid, "project_id": PID, "version_id": "1.0.0", "published": published}


def _patches(
    stack: ExitStack,
    *,
    published: bool = False,
    document: Optional[Dict[str, Any]] = None,
    quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, MagicMock]:
    """Patch everything the routes touch outside the plan; return the mocks by name."""
    versions = {VID: _version(VID, published=published), NEW_VID: _version(NEW_VID)}
    mocks: Dict[str, MagicMock] = {}

    def _p(target: str, **kwargs: Any) -> MagicMock:
        mock = stack.enter_context(patch(target, **kwargs))
        mocks[target.rsplit(".", 1)[-1]] = mock
        return mock

    _p("app.lint_fix_routes.enforce_permission", return_value="u1")
    _p("app.lint_fix_routes.db.get_version_by_id", side_effect=lambda vid, _t: versions.get(vid))
    _p("app.lint_fix_routes.db.get_version_quality_score", return_value=quality or {})
    _p("app.lint_fix_routes.openapi_for_revision", return_value=document or MULTI_DEFECT)
    _p("app.lint_fix_routes.resolve_style_guide", return_value=builtin_fallback_guide())
    _p("app.lint_fix_routes.existing_version_labels", return_value=["1.0.0"])
    _p("app.lint_fix_routes.enforce_openapi_quality_gate", new=AsyncMock())
    _p("app.lint_fix_routes.db.get_version_source_projection", return_value={"project_slug": "shop"})
    _p("app.lint_fix_routes.import_openapi_as_version", return_value=NEW_VID)
    _p("app.lint_fix_routes.persist_version_lint_report", return_value=True)
    _p("app.lint_fix_routes.pin_guide_revision_id", return_value=None)
    _p("app.lint_fix_routes.db.record_lint_fix_revision", return_value=True)
    _p("app.lint_fix_routes.db.delete_version", return_value=(True, None))
    return mocks


def _ready_ids() -> List[str]:
    return list(build_fix_plan(MULTI_DEFECT).applied_order)


# ---------------------------------------------------------------------------
# GET …/lint/fixes
# ---------------------------------------------------------------------------


def test_get_plan_json() -> None:
    with ExitStack() as stack:
        mocks = _patches(stack, quality={"quality_report": {"report_fingerprint": "rf1"}})
        response = client.get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["projectId"] == PID
    assert body["versionRecordId"] == VID
    assert body["reportFingerprint"] == "rf1"
    assert body["reportCurrent"] is False  # the stored report carries no content fingerprint
    assert body["counts"]["ready"] == len(_ready_ids())
    entry = body["entries"][0]
    assert set(entry) >= {"fixId", "ruleId", "fixClass", "wireVisible", "path", "ops", "status"}
    mocks["enforce_permission"].assert_called_once()
    assert mocks["enforce_permission"].call_args.args[2:] == ("versions", "view")


def test_get_plan_is_byte_identical_across_requests() -> None:
    with ExitStack() as stack:
        _patches(stack)
        for fmt in ("json", "patch", "overlay", "diff"):
            first = client.get(BASE, params={"format": fmt, "includeRenames": "true"})
            second = client.get(BASE, params={"format": fmt, "includeRenames": "true"})
            assert first.status_code == 200
            assert first.content == second.content


def test_get_plan_patch_overlay_and_diff_formats() -> None:
    with ExitStack() as stack:
        _patches(stack)
        patch_response = client.get(BASE, params={"format": "patch"})
        overlay_response = client.get(BASE, params={"format": "overlay"})
        diff_response = client.get(BASE, params={"format": "diff"})
    assert patch_response.headers["content-type"].startswith("application/json-patch+json")
    assert patch_response.json() == build_fix_plan(MULTI_DEFECT).patch()
    overlay = overlay_response.json()
    assert apply_overlays(MULTI_DEFECT, [("fixes", overlay)]).document == build_fix_plan(MULTI_DEFECT).fixed_document
    assert diff_response.headers["content-type"].startswith("text/x-diff")
    assert diff_response.text.startswith("--- a/openapi.json")


def test_get_plan_rules_filter_and_renames() -> None:
    with ExitStack() as stack:
        _patches(stack)
        response = client.get(BASE, params={"rules": "structure.empty-required", "includeRenames": "true"})
    body = response.json()
    assert body["rules"] == ["structure.empty-required"]
    assert body["includeRenames"] is True
    assert body["appliedOrder"] == [
        e["fixId"] for e in body["entries"] if e["ruleId"] == "structure.empty-required"
    ]


def test_get_plan_refuses_bad_options_and_non_openapi() -> None:
    with ExitStack() as stack:
        _patches(stack)
        bad_rule = client.get(BASE, params={"rules": "no.such-rule"})
        bad_template = client.get(BASE, params={"operationIdTemplate": "{method}"})
    assert bad_rule.status_code == 422
    assert bad_rule.json()["detail"]["code"] == "lint-fix-invalid-options"
    assert bad_template.json()["detail"]["code"] == "lint-fix-invalid-options"
    with ExitStack() as stack:
        _patches(stack, document={"swagger": "2.0"})
        response = client.get(BASE)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lint-fix-not-openapi"


def test_get_plan_unknown_revision_is_404() -> None:
    with ExitStack() as stack:
        _patches(stack)
        response = client.get(f"/v1/versions/acme/{PID}/00000000-0000-0000-0000-00000000dead/lint/fixes")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/lint/fixes/plan
# ---------------------------------------------------------------------------


def test_post_plan_for_a_document() -> None:
    with patch("app.lint_fix_routes.resolve_style_guide", return_value=builtin_fallback_guide()) as guide:
        response = client.post("/v1/lint/fixes/plan", json={"document": json.dumps(MULTI_DEFECT)})
    assert response.status_code == 200
    body = response.json()
    assert body["documentFingerprint"] == build_fix_plan(MULTI_DEFECT).document_fingerprint
    assert body.get("versionRecordId") is None
    guide.assert_called_once_with("t1", None)


def test_post_plan_accepts_yaml_and_formats() -> None:
    fixture = Path(__file__).parent / "fixtures" / "lint_fix" / "structure.unused-component.json"
    yaml_text = yaml.safe_dump(json.loads(fixture.read_text(encoding="utf-8"))["before"], sort_keys=False)
    with patch("app.lint_fix_routes.resolve_style_guide", return_value=builtin_fallback_guide()):
        response = client.post("/v1/lint/fixes/plan", json={"document": yaml_text, "format": "patch"})
    assert response.status_code == 200
    assert response.json() == [{"op": "remove", "path": "/components/schemas/Orphan"}]


def test_post_plan_refuses_bad_input() -> None:
    with patch("app.lint_fix_routes.resolve_style_guide", return_value=builtin_fallback_guide()):
        not_yaml = client.post("/v1/lint/fixes/plan", json={"document": "{ nope: ["})
        not_openapi = client.post("/v1/lint/fixes/plan", json={"document": "a: 1"})
        bad_format = client.post("/v1/lint/fixes/plan", json={"document": "a: 1", "format": "xml"})
    assert not_yaml.status_code == 422
    assert not_openapi.json()["detail"]["code"] == "lint-fix-not-openapi"
    assert bad_format.status_code == 422


# ---------------------------------------------------------------------------
# POST …/lint/fixes/apply
# ---------------------------------------------------------------------------


def test_apply_creates_one_audited_revision() -> None:
    ready = _ready_ids()
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.post(f"{BASE}/apply", json={"fixIds": ready, "reason": "Tidy before review"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["versionRecordId"] == NEW_VID
    assert body["sourceVersionRecordId"] == VID
    assert sorted(body["appliedFixIds"]) == sorted(ready)
    assert body["score"] is not None and body["reportFingerprint"]

    assert mocks["enforce_permission"].call_args.args[2:] == ("versions", "edit")
    mocks["import_openapi_as_version"].assert_called_once()
    imported = json.loads(mocks["import_openapi_as_version"].call_args.kwargs["raw"])
    assert imported == build_fix_plan(MULTI_DEFECT).fixed_document
    mocks["persist_version_lint_report"].assert_called_once()
    assert mocks["persist_version_lint_report"].call_args.args[0] == NEW_VID

    mocks["record_lint_fix_revision"].assert_called_once()
    record = mocks["record_lint_fix_revision"].call_args.kwargs
    assert record["version_record_id"] == NEW_VID
    assert record["audit_action"] == AUDIT_LINT_FIX_APPLIED == "version.lint_fix_applied"
    assert record["provenance"]["source"] == SOURCE_LINT_FIX == "lint-fix"
    assert sorted(record["provenance"]["lintFix"]["fixIds"]) == sorted(ready)
    assert record["audit_detail"]["reason"] == "Tidy before review"
    mocks["delete_version"].assert_not_called()


def test_apply_by_rules_skips_what_is_not_ready() -> None:
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.post(
            f"{BASE}/apply",
            json={"rules": ["structure.unused-component", "structure.schema-example-keyword"], "reason": "r"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["appliedFixIds"]) == 1
    assert [s["status"] for s in body["skipped"]] == ["conflict"]
    mocks["import_openapi_as_version"].assert_called_once()


def test_apply_refuses_a_published_revision() -> None:
    with ExitStack() as stack:
        mocks = _patches(stack, published=True)
        response = client.post(f"{BASE}/apply", json={"fixIds": _ready_ids(), "reason": "r"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "lint-fix-version-published"
    mocks["import_openapi_as_version"].assert_not_called()


def test_apply_never_applies_a_breaking_fix() -> None:
    plan = build_fix_plan(MULTI_DEFECT, include_renames=True)
    breaking = [e.fix_id for e in plan.entries if e.status == "breaking"]
    assert breaking
    with ExitStack() as stack:
        mocks = _patches(stack)
        by_id = client.post(
            f"{BASE}/apply", json={"fixIds": breaking, "includeRenames": True, "reason": "r"}
        )
        by_rule = client.post(f"{BASE}/apply", json={"rules": ["naming.schema-pascal-case"], "reason": "r"})
    assert by_id.status_code == 422
    assert by_id.json()["detail"]["code"] == "lint-fix-breaking"
    assert by_rule.status_code == 422
    assert by_rule.json()["detail"]["code"] == "lint-fix-breaking"
    mocks["import_openapi_as_version"].assert_not_called()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"fixIds": ["fix-unknown"], "reason": "r"}, "lint-fix-unknown"),
        ({"rules": ["structure.nullable-keyword"], "reason": "r"}, "lint-fix-nothing-to-apply"),
        ({"rules": ["no.such-rule"], "reason": "r"}, "lint-fix-invalid-options"),
    ],
)
def test_apply_refusals(payload: Dict[str, Any], code: str) -> None:
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.post(f"{BASE}/apply", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    mocks["import_openapi_as_version"].assert_not_called()


def test_apply_refuses_conflicting_and_excluded_fixes() -> None:
    plan = build_fix_plan(MULTI_DEFECT)
    conflict = next(e.fix_id for e in plan.entries if e.status == "conflict")
    excluded = next(e.fix_id for e in plan.entries if e.status == "excluded")
    with ExitStack() as stack:
        _patches(stack)
        conflict_response = client.post(f"{BASE}/apply", json={"fixIds": [conflict], "reason": "r"})
        excluded_response = client.post(f"{BASE}/apply", json={"fixIds": [excluded], "reason": "r"})
    assert conflict_response.json()["detail"]["code"] == "lint-fix-conflict"
    assert excluded_response.json()["detail"]["code"] == "lint-fix-excluded"


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "r"},
        {"fixIds": ["a"], "rules": ["b"], "reason": "r"},
        {"fixIds": ["a"], "reason": "   "},
        {"fixIds": ["a"]},
    ],
)
def test_apply_validates_its_body(payload: Dict[str, Any]) -> None:
    with ExitStack() as stack:
        _patches(stack)
        response = client.post(f"{BASE}/apply", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("failure", [False, RuntimeError("db down")])
def test_apply_withdraws_the_revision_when_the_record_fails(failure: Any) -> None:
    with ExitStack() as stack:
        mocks = _patches(stack)
        if isinstance(failure, Exception):
            mocks["record_lint_fix_revision"].side_effect = failure
        else:
            mocks["record_lint_fix_revision"].return_value = failure
        response = client.post(f"{BASE}/apply", json={"fixIds": _ready_ids(), "reason": "r"})
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "lint-fix-record-failed"
    mocks["delete_version"].assert_called_once_with(NEW_VID, "t1", "u1")
