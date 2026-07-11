"""Endpoint tests for custom-rule DSL validation — POST /v1/lint/custom-rules/validate (GOV-1.3, #4429)."""

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

VALIDATE = "/v1/lint/custom-rules/validate"

GOOD_GUIDE = """
rules:
  servers-use-https:
    description: Every server URL uses https.
    severity: error
    given: "$.servers[*].url"
    then: {function: pattern, functionOptions: {match: '^https://'}}
  operations-have-summary:
    description: Every operation carries a summary.
    given: "$.paths[*][*]"
    then:
      field: summary
      function: truthy
"""


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_session_credentials] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def test_valid_guide_returns_parsed_rules():
    r = client.post(VALIDATE, json={"yaml": GOOD_GUIDE})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["count"] == 2
    assert [rule["ruleId"] for rule in body["rules"]] == [
        "servers-use-https",
        "operations-have-summary",
    ]
    https_rule = body["rules"][0]
    assert https_rule["severity"] == "error"
    assert https_rule["given"] == ["$.servers[*].url"]
    assert https_rule["then"] == [
        {"field": None, "function": "pattern", "functionOptions": {"match": "^https://"}}
    ]
    summary_rule = body["rules"][1]
    assert summary_rule["severity"] == "warning"  # default
    assert summary_rule["then"][0]["field"] == "summary"


def test_malformed_rule_returns_422_with_pointer():
    guide = (
        "rules:\n"
        "  broken:\n"
        "    description: d\n"
        "    given: $.info\n"
        "    then: {function: pattern, functionOptions: {match: '('}}\n"
    )
    r = client.post(VALIDATE, json={"yaml": guide})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["pointer"] == "rules.broken.then.functionOptions.match"
    assert "regular expression" in detail["message"]


def test_unparseable_yaml_returns_422_with_document_pointer():
    r = client.post(VALIDATE, json={"yaml": "rules:\n  bad: [unclosed\n"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["pointer"] == ""
    assert "invalid YAML" in detail["message"]


def test_custom_rule_may_not_shadow_a_builtin_rule_id():
    from app.lint_rule_registry import builtin_rule_ids

    builtin_id = builtin_rule_ids()[0]
    guide = (
        "rules:\n"
        f"  {builtin_id}:\n"
        "    description: d\n"
        "    given: $.info\n"
        "    then: {function: defined}\n"
    )
    r = client.post(VALIDATE, json={"yaml": guide})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["pointer"] == f"rules.{builtin_id}"
    assert "shadows a built-in rule" in detail["message"]


def test_missing_yaml_body_rejected():
    assert client.post(VALIDATE, json={}).status_code == 422
    assert client.post(VALIDATE, json={"yaml": ""}).status_code == 422


def test_validate_requires_authentication():
    app.dependency_overrides.clear()
    r = client.post(VALIDATE, json={"yaml": GOOD_GUIDE})
    assert r.status_code == 401
