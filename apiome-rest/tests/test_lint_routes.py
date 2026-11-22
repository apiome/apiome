"""Endpoint tests for the quality-scoring / lint API (#3609)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication, validate_session_credentials
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

PID = "00000000-0000-0000-0000-0000000000a1"
VID = "00000000-0000-0000-0000-0000000000b1"
BASE_VID = "00000000-0000-0000-0000-0000000000b0"

HEAD_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Payments", "version": "1.0.0"},  # missing description -> a finding
    "paths": {},
    "components": {
        "schemas": {
            "Payment": {
                "type": "object",
                "description": "A payment.",
                "properties": {
                    "amount": {"type": "integer", "description": "cents", "example": 1},
                },
            }
        }
    },
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    # The tenant-less rule-catalog route (GOV-1.2) authenticates via session credentials.
    app.dependency_overrides[validate_session_credentials] = _override_auth
    yield
    app.dependency_overrides.clear()


def _version_row(vid: str):
    return {"id": vid, "project_id": PID, "version_id": "1.0.0", "metadata": None}


def test_lint_returns_score_and_findings():
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["score"], int)
    assert body["grade"] in {"A", "B", "C", "D", "F"}
    assert body["versionRecordId"] == VID
    assert body["versionId"] == "1.0.0"
    assert "reportFingerprint" in body
    rules = {f["rule"] for f in body["findings"]}
    assert "documentation.info-missing-description" in rules
    assert body["baseRevisionId"] is None
    assert body["compatibilityOverall"] is None


def test_lint_is_deterministic_for_fixed_input():
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        a = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
        b = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    assert a["reportFingerprint"] == b["reportFingerprint"]
    assert a["score"] == b["score"]
    # Determinism extends to the per-category rollup (MFI-25.6).
    assert a["categories"] == b["categories"]


def test_lint_returns_category_score_rollup():
    # MFI-25.6 (#4091): the report carries a `categories[{name, score}]` array with 0-100 scores,
    # driving the UI's category bars with real values. The in-spec categories are always present.
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()

    categories = body["categories"]
    assert isinstance(categories, list) and categories
    for c in categories:
        assert set(c) == {"name", "score"}
        assert isinstance(c["name"], str) and c["name"]
        assert isinstance(c["score"], int) and 0 <= c["score"] <= 100
    names = [c["name"] for c in categories]
    # Always-evaluated in-spec categories are present and sorted; no un-compared compatibility bar.
    assert {"naming", "documentation", "structure"}.issubset(set(names))
    assert "compatibility" not in names
    assert names == sorted(names)
    # HEAD_SPEC omits info.description → the documentation category is dinged below 100.
    doc = next(c for c in categories if c["name"] == "documentation")
    assert doc["score"] < 100


def test_lint_with_base_revision_adds_compatibility_category():
    # A base comparison that surfaces a breaking change adds a compatibility category bar.
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id",
        side_effect=lambda vid, _tid: _version_row(vid),
    ), patch(
        "app.lint_routes.openapi_for_revision",
        side_effect=[HEAD_SPEC, {**HEAD_SPEC, "paths": {"/gone": {"get": {}}}}],
    ):
        body = client.get(
            f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={BASE_VID}"
        ).json()
    names = {c["name"] for c in body["categories"]}
    assert "compatibility" in names


def test_lint_project_not_found():
    with patch("app.lint_routes.db.get_project_core", return_value=None):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 404


def test_lint_revision_not_found():
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=None
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 404


def test_lint_revision_wrong_project():
    other = {"id": VID, "project_id": "different", "version_id": "1.0.0", "metadata": None}
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=other
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 400


def test_lint_with_base_revision_folds_compatibility():
    rows = {VID: _version_row(VID), BASE_VID: _version_row(BASE_VID)}
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", side_effect=lambda vid, tid: rows.get(vid)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={BASE_VID}")
    assert r.status_code == 200
    body = r.json()
    assert body["baseRevisionId"] == BASE_VID
    # Identical head/base specs are compatible.
    assert body["compatibilityOverall"] == "safe"


def test_lint_base_revision_must_differ():
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={VID}")
    assert r.status_code == 400


# --- MFI-4.4: captured (import-time) score surfacing -----------------------------------------


def _captured(score, grade, fingerprint, *, quality_report=None):
    """Build a get_version_quality_score row (the persisted MFI-4.2 score)."""
    return {
        "quality_score": score,
        "quality_grade": grade,
        "quality_report_fingerprint": fingerprint,
        "quality_report": quality_report or {},
    }


def test_lint_surfaces_captured_score_when_current():
    """When the persisted fingerprint matches the live recompute, the score is not stale."""
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        # First read the live fingerprint (no captured score), then claim it as the stored one.
        with patch(
            "app.lint_routes.db.get_version_quality_score",
            return_value=_captured(None, None, None),
        ):
            live = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
        with patch(
            "app.lint_routes.db.get_version_quality_score",
            return_value=_captured(live["score"], live["grade"], live["reportFingerprint"]),
        ):
            body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    assert body["capturedScore"] == live["score"]
    assert body["capturedGrade"] == live["grade"]
    assert body["capturedReportFingerprint"] == live["reportFingerprint"]
    assert body["scoreIsStale"] is False


def test_lint_flags_stale_captured_score():
    """A persisted fingerprint that differs from the live recompute marks the score stale."""
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC), patch(
        "app.lint_routes.db.get_version_quality_score",
        return_value=_captured(42, "F", "stale-fingerprint-does-not-match"),
    ):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    assert body["capturedScore"] == 42
    assert body["capturedGrade"] == "F"
    assert body["scoreIsStale"] is True


def test_lint_no_captured_score_is_not_stale():
    """A never-scored version surfaces null captured fields and is not stale."""
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC), patch(
        "app.lint_routes.db.get_version_quality_score", return_value=_captured(None, None, None)
    ):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    assert body["capturedScore"] is None
    assert body["capturedGrade"] is None
    assert body["capturedReportFingerprint"] is None
    assert body["scoreIsStale"] is False


def test_lint_base_revision_comparison_never_stale():
    """A base-revision compare folds in extra findings, so it never flags the captured score."""
    rows = {VID: _version_row(VID), BASE_VID: _version_row(BASE_VID)}
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", side_effect=lambda vid, tid: rows.get(vid)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC), patch(
        "app.lint_routes.db.get_version_quality_score",
        return_value=_captured(42, "F", "definitely-different-fingerprint"),
    ):
        body = client.get(
            f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={BASE_VID}"
        ).json()
    assert body["capturedScore"] == 42
    assert body["scoreIsStale"] is False


def test_lint_serves_stored_quality_report_without_recompute():
    """When a full report was persisted at import, GET lint serves it without OpenAPI recompute."""
    stored = {
        "score": 56,
        "grade": "C",
        "report_fingerprint": "fp-stored-capnp",
        "rule_hits": {"common.type-missing-description": 3},
        "severity_counts": {"warning": 3, "error": 0, "info": 0},
        "findings": [
            {
                "id": "lint-abc",
                "path": "types.Person",
                "category": "documentation",
                "rule": "common.type-missing-description",
                "severity": "warning",
                "message": "Type Person has no description.",
            }
        ],
        "categories": [{"name": "documentation", "score": 40}],
    }
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision") as m_recon, patch(
        "app.lint_routes.db.get_version_quality_score",
        return_value=_captured(56, "C", "fp-stored-capnp", quality_report=stored),
    ):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    m_recon.assert_not_called()
    assert body["score"] == 56
    assert body["grade"] == "C"
    assert body["reportFingerprint"] == "fp-stored-capnp"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["rule"] == "common.type-missing-description"
    assert body["scoreIsStale"] is False
    assert body["capturedScore"] == 56


def test_lint_captured_read_failure_does_not_break_live_report():
    """A failure reading the persisted score degrades gracefully to no captured score."""
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC), patch(
        "app.lint_routes.db.get_version_quality_score", side_effect=RuntimeError("no db")
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 200
    body = r.json()
    assert body["capturedScore"] is None
    assert body["scoreIsStale"] is False


# ---------------------------------------------------------------------------
# GET /v1/lint/rules — built-in rule catalog registry (GOV-1.2, #4428)
# ---------------------------------------------------------------------------


def test_lint_rules_catalog_returns_every_registered_rule():
    from app.lint_rule_registry import LINT_RULE_DOCS_PAGE, builtin_rule_ids

    r = client.get("/v1/lint/rules")
    assert r.status_code == 200
    body = r.json()
    assert body["docsPage"] == LINT_RULE_DOCS_PAGE
    assert body["count"] == len(body["rules"]) == len(builtin_rule_ids())
    assert [rule["ruleId"] for rule in body["rules"]] == builtin_rule_ids()


def test_lint_rules_catalog_entries_are_fully_populated():
    body = client.get("/v1/lint/rules").json()
    for rule in body["rules"]:
        assert set(rule) == {
            "ruleId",
            "pack",
            "category",
            "defaultSeverity",
            "rationale",
            "docsAnchor",
            # CLX-4.3 transparency fields (null for non-blocking rules).
            "reference",
            "remediation",
            "falsePositiveGuidance",
            "fixtureId",
            "scanModes",
            # ASP-1.3 security-score fields: weight for `security` rules, OWASP ids when cited.
            "weight",
            "owasp",
            # GVM-3.1 fix capability (null fix metadata for a rule that is not fixable).
            "fixable",
            "fixClass",
            "wireVisible",
            "fixSummary",
            "fixScope",
            "fixDefault",
            "fixOwner",
            # GVM-4.4 earlier ids that still match the rule (empty for most rules).
            "aliases",
        }
        assert isinstance(rule["aliases"], list)
        assert rule["ruleId"] and rule["pack"] and rule["category"]
        assert rule["defaultSeverity"] in {"error", "warning", "info"}
        assert rule["rationale"].strip()
        assert rule["docsAnchor"] == rule["ruleId"].replace(".", "-")
        if rule["defaultSeverity"] == "error":
            assert rule["reference"]
            assert rule["remediation"]
            assert rule["scanModes"]
        if rule["category"] == "security":
            assert rule["weight"] is not None and rule["weight"] >= 1.0
        else:
            assert rule["weight"] is None
        if rule["owasp"] is not None:
            assert rule["owasp"] and set(rule["owasp"]) <= {f"API{n}" for n in range(1, 11)}


def test_lint_rules_catalog_resolves_the_arazzo_operation_ref_alias():
    """GVM-4.4 AC: the typo id is an alias of the corrected rule, published on its entry."""
    body = client.get("/v1/lint/rules").json()
    by_id = {rule["ruleId"]: rule for rule in body["rules"]}
    assert "arzzo.unresolvable-operation-ref" not in by_id
    entry = by_id["arazzo.unresolvable-operation-ref"]
    assert entry["aliases"] == ["arzzo.unresolvable-operation-ref"]
    assert entry["pack"] == "arazzo" and entry["defaultSeverity"] == "error"
    assert entry["fixtureId"] == "catalog/arazzo-unresolvable-operation-ref"
    aliased = [rule["ruleId"] for rule in body["rules"] if rule["aliases"]]
    assert aliased == ["arazzo.unresolvable-operation-ref"]


def test_lint_rules_catalog_publishes_the_security_weights():
    """ASP-1.3: the per-rule weights are public — a `security` rule's weight is on its entry."""
    from app.security_score import SECURITY_RULE_WEIGHTS, security_rule_weight

    body = client.get("/v1/lint/rules").json()
    for rule in body["rules"]:
        if rule["category"] != "security":
            continue
        assert rule["weight"] == security_rule_weight(rule["ruleId"])
        if rule["ruleId"] in SECURITY_RULE_WEIGHTS:
            assert rule["weight"] == 2.0


def test_lint_rules_catalog_lists_at_least_twelve_fixable_rules():
    """GVM-3.1 acceptance: `GET /v1/lint/rules` lists at least twelve `fixable: true` rules."""
    body = client.get("/v1/lint/rules").json()
    fixable = [rule for rule in body["rules"] if rule["fixable"]]
    assert len(fixable) >= 12
    for rule in fixable:
        assert rule["fixClass"] in {"structural", "removal", "fill-in", "rename"}
        assert isinstance(rule["wireVisible"], bool)
        assert rule["fixSummary"].strip()
        assert rule["fixScope"] in {"finding", "document"}
        assert isinstance(rule["fixDefault"], bool)
        assert rule["fixOwner"] == "engine"


def test_lint_rules_catalog_says_who_repairs_a_rule_that_is_not_fixable():
    body = client.get("/v1/lint/rules").json()
    by_id = {rule["ruleId"]: rule for rule in body["rules"]}
    unfixable = by_id["documentation.operation-missing-summary"]
    assert unfixable["fixable"] is False and unfixable["fixOwner"] == "agent"
    assert [unfixable[key] for key in ("fixClass", "wireVisible", "fixSummary", "fixScope", "fixDefault")] == [None] * 5
    assert by_id["structure.unbounded-array"]["fixOwner"] == "human"
    rename = by_id["naming.schema-pascal-case"]
    assert (rename["fixClass"], rename["wireVisible"], rename["fixScope"], rename["fixDefault"]) == (
        "rename",
        True,
        "document",
        False,
    )


def test_lint_rules_catalog_is_deterministic():
    a = client.get("/v1/lint/rules").json()
    b = client.get("/v1/lint/rules").json()
    assert a == b


def test_lint_report_findings_attributable_to_rule_catalog():
    # Acceptance: every violation the lint report emits carries a registered rule id.
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        report = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    catalog = client.get("/v1/lint/rules").json()
    registered = {rule["ruleId"] for rule in catalog["rules"]}
    assert report["findings"]  # HEAD_SPEC trips at least the info-description rule
    for finding in report["findings"]:
        assert finding["rule"] in registered


def test_lint_rules_requires_authentication():
    # Drop the module-level auth override: the catalog is still an authenticated v1 endpoint.
    app.dependency_overrides.clear()
    r = client.get("/v1/lint/rules")
    assert r.status_code == 401


# ===========================================================================
# GOV-1.4 (#4430): lint runs under the resolved style guide
# ===========================================================================


def test_lint_reports_the_fallback_guide_when_nothing_is_assigned():
    """With no resolvable guide the report is scored (and labelled) by the in-code defaults."""
    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()

    assert body["guideId"] is None
    assert body["guideName"] == "Apiome Recommended"
    assert body["guideSource"] == "fallback"


def test_lint_scores_under_the_assigned_style_guide():
    """An assigned guide governs the report: disabled rules vanish, severities remap."""
    guide_row = {"id": "00000000-0000-4000-8000-0000000000d1", "name": "Team Guide", "source": "custom"}
    # Enable only the info-description rule, escalated to error; everything else is ungoverned.
    rules = [
        {
            "rule_id": "documentation.info-missing-description",
            "enabled": True,
            "severity": "error",
            "custom_def": None,
        }
    ]

    with patch("app.lint_routes.db.get_project_core", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC), patch(
        "app.lint_routes.db.get_assigned_style_guide", return_value=guide_row
    ) as m_resolve, patch(
        "app.lint_routes.db.get_style_guide_rules", return_value=rules
    ):
        body = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()

    assert body["guideId"] == guide_row["id"]
    assert body["guideName"] == "Team Guide"
    assert body["guideSource"] == "custom"
    # HEAD_SPEC's only governed defect: info.description missing — escalated info -> error.
    assert {f["rule"] for f in body["findings"]} == {"documentation.info-missing-description"}
    assert body["findings"][0]["severity"] == "error"
    assert body["severityCounts"]["error"] == 1
    assert body["score"] == 90  # one error-severity rule: 100 - 10
    # Guided lint + external-validation evidence each resolve the assigned guide.
    assert m_resolve.call_count >= 1
    m_resolve.assert_called_with("t1", PID)
