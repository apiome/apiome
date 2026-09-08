"""Tests for ``apiome diff`` CI gate (CTG-2.1 / #4471)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import jsonschema
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.output_diff import gate_should_fail, parse_against

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SPEC_FILE = _FIXTURES / "diff-property-removed.yaml"
_SCHEMA_FILE = _FIXTURES / "diff-classified-response.schema.json"

_DIFF_URL = "http://localhost:8000/v1/diff/acme-corp/classified"

_BREAKING_PAYLOAD = {
    "changes": [
        {
            "ruleId": "ctg.property_removed",
            "severity": "breaking",
            "pointer": "/components/schemas/Pet/properties/name",
            "before": {"type": "string"},
            "after": None,
            "unclassified": False,
            "changeKind": "property_removed",
        }
    ],
    "counts": {
        "breaking": 1,
        "non-breaking": 0,
        "docs-only": 0,
        "unclassified": 0,
        "total": 1,
    },
    "maxSeverity": "breaking",
    "base": {
        "projectId": "proj-1",
        "projectSlug": "payments",
        "versionRecordId": "base-rev",
        "versionLabel": "1.0.0",
    },
    "head": {
        "source": "inline",
        "projectId": None,
        "projectSlug": None,
        "versionRecordId": None,
        "versionLabel": None,
    },
}

_NON_BREAKING_PAYLOAD = {
    **_BREAKING_PAYLOAD,
    "changes": [
        {
            "ruleId": "ctg.property_added",
            "severity": "non-breaking",
            "pointer": "/components/schemas/Pet/properties/tag",
            "before": None,
            "after": {"type": "string"},
            "unclassified": False,
            "changeKind": "property_added",
        }
    ],
    "counts": {
        "breaking": 0,
        "non-breaking": 1,
        "docs-only": 0,
        "unclassified": 0,
        "total": 1,
    },
    "maxSeverity": "non-breaking",
}

_SAFE_PAYLOAD = {
    **_BREAKING_PAYLOAD,
    "changes": [],
    "counts": {
        "breaking": 0,
        "non-breaking": 0,
        "docs-only": 0,
        "unclassified": 0,
        "total": 0,
    },
    "maxSeverity": None,
}

_DOCS_ONLY_PAYLOAD = {
    **_BREAKING_PAYLOAD,
    "changes": [
        {
            "ruleId": "ctg.docs_description",
            "severity": "docs-only",
            "pointer": "/info/description",
            "before": "a",
            "after": "b",
            "unclassified": False,
            "changeKind": "docs_description",
        }
    ],
    "counts": {
        "breaking": 0,
        "non-breaking": 0,
        "docs-only": 1,
        "unclassified": 0,
        "total": 1,
    },
    "maxSeverity": "docs-only",
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def test_parse_against() -> None:
    assert parse_against("payments@latest") == ("payments", "latest")
    assert parse_against("pets@1.0.0") == ("pets", "1.0.0")
    with pytest.raises(ValueError):
        parse_against("payments")
    with pytest.raises(ValueError):
        parse_against("@latest")


def test_gate_should_fail_thresholds() -> None:
    assert gate_should_fail("breaking", "breaking") is True
    assert gate_should_fail("non-breaking", "breaking") is False
    assert gate_should_fail("non-breaking", "warn") is True
    assert gate_should_fail("docs-only", "warn") is False
    assert gate_should_fail(None, "breaking") is False


def test_diff_breaking_exits_one_and_prints_rule_id(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_BREAKING_PAYLOAD)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest"],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert "ctg.property_removed" in result.stdout


def test_diff_fail_on_warn_vs_breaking(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_NON_BREAKING_PAYLOAD)
    warn = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@1.0.0",
            "--fail-on",
            "warn",
        ],
    )
    assert warn.exit_code == EXIT_ERROR, warn.output

    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_NON_BREAKING_PAYLOAD)
    breaking = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@1.0.0",
            "--fail-on",
            "breaking",
        ],
    )
    assert breaking.exit_code == EXIT_SUCCESS, breaking.output


def test_diff_docs_only_passes_warn(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_DOCS_ONLY_PAYLOAD)
    result = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@latest",
            "--fail-on",
            "warn",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_diff_json_schema_stable(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_BREAKING_PAYLOAD)
    result = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@latest",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    payload = json.loads(result.stdout)
    schema = json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)
    assert payload["maxSeverity"] == "breaking"
    assert payload["changes"][0]["ruleId"] == "ctg.property_removed"


def test_diff_auth_error_exits_two(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_DIFF_URL,
        method="POST",
        status_code=401,
        json={"message": "Unauthorized"},
    )
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest"],
    )
    assert result.exit_code == EXIT_USAGE, result.output
    assert result.exit_code != EXIT_ERROR


def test_diff_oversize_local_exits_two(tmp_path: Path) -> None:
    huge = tmp_path / "huge.yaml"
    # Cap is 10MB; write slightly over without hitting the network.
    huge.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    result = runner.invoke(
        app,
        ["diff", str(huge), "--against", "payments@latest"],
    )
    assert result.exit_code == EXIT_USAGE, result.output
    assert "exceeds" in result.stderr.lower()


def test_diff_connection_error_exits_two(httpx_mock: object) -> None:
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=_DIFF_URL,
        method="POST",
    )
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest"],
    )
    assert result.exit_code == EXIT_USAGE, result.output


def test_diff_format_md_uses_accept_markdown(httpx_mock: object) -> None:
    md_body = "# Changelog\n\n- **Property removed** (`ctg.property_removed`)\n"
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_BREAKING_PAYLOAD)
    httpx_mock.add_response(
        url=_DIFF_URL,
        method="POST",
        text=md_body,
        headers={"content-type": "text/markdown; charset=utf-8"},
    )
    result = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@latest",
            "--format",
            "md",
        ],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stdout.startswith("# Changelog")
    assert "ctg.property_removed" in result.stdout

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].headers.get("Accept") == "application/json"
    assert requests[1].headers.get("Accept") == "text/markdown"


def test_diff_safe_exits_zero(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_SAFE_PAYLOAD)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output


# ---------------------------------------------------------------------------------------------
# CTG-4.2 per-consumer verdicts (#4480)
# ---------------------------------------------------------------------------------------------

_CONSUMER_IMPACT = {
    "schemaVersion": "ctg.consumer-impact.v1",
    "summary": (
        "breaks 1 of 2 consumers: billing-service "
        "(1 registered consumer has declared no surface)"
    ),
    "maxSeverity": "breaking",
    "counts": {
        "consumers_total": 3,
        "consumers_declared": 2,
        "consumers_undeclared": 1,
        "consumers_affected": 1,
        "consumers_breaking": 1,
        "changes_total": 1,
        "changes_attributed": 1,
        "changes_unattributed": 0,
    },
    "consumers": [
        {
            "consumerId": "c-1",
            "consumerSlug": "billing-service",
            "consumerName": "Billing Service",
            "owner": "Payments",
            "contact": None,
            "declared": True,
            "verdict": "breaking",
            "contractId": "k-1",
            "contractRevision": 2,
            "contractVersionLabel": "1.0.0",
            "contractMatchesBase": True,
            "operationsDeclared": 1,
            "fieldsDeclared": 1,
            "operationsAffected": 1,
            "counts": {
                "breaking": 1,
                "non-breaking": 0,
                "docs-only": 0,
                "unclassified": 0,
                "total": 1,
            },
            "impacts": [
                {
                    "ruleId": "ctg.property_removed",
                    "severity": "breaking",
                    "pointer": "/components/schemas/Pet/properties/name",
                    "changeKind": "property_removed",
                    "unclassified": False,
                    "match": "field",
                    "declaredPointer": "/components/schemas/Pet/properties/name",
                    "method": "get",
                    "path": "/pets",
                    "operationId": None,
                    "fieldPath": "name",
                    "fieldLocation": "response",
                    "fieldStatus": "200",
                }
            ],
            "truncated": False,
        },
        {
            "consumerId": "c-2",
            "consumerSlug": "mobile-app",
            "consumerName": "Mobile App",
            "owner": None,
            "contact": None,
            "declared": True,
            "verdict": "unaffected",
            "contractId": "k-2",
            "contractRevision": 1,
            "contractVersionLabel": "1.0.0",
            "contractMatchesBase": True,
            "operationsDeclared": 1,
            "fieldsDeclared": 1,
            "operationsAffected": 0,
            "counts": {
                "breaking": 0,
                "non-breaking": 0,
                "docs-only": 0,
                "unclassified": 0,
                "total": 0,
            },
            "impacts": [],
            "truncated": False,
        },
        {
            "consumerId": "c-3",
            "consumerSlug": "ghost",
            "consumerName": "Ghost",
            "owner": None,
            "contact": None,
            "declared": False,
            "verdict": "undeclared",
            "contractId": None,
            "contractRevision": None,
            "contractVersionLabel": None,
            "contractMatchesBase": None,
            "operationsDeclared": 0,
            "fieldsDeclared": 0,
            "operationsAffected": 0,
            "counts": {
                "breaking": 0,
                "non-breaking": 0,
                "docs-only": 0,
                "unclassified": 0,
                "total": 0,
            },
            "impacts": [],
            "truncated": False,
        },
    ],
    "breakingConsumers": ["billing-service"],
    "attribution": [
        {
            "ruleId": "ctg.property_removed",
            "severity": "breaking",
            "pointer": "/components/schemas/Pet/properties/name",
            "changeKind": "property_removed",
            "unclassified": False,
            "consumers": ["billing-service"],
        }
    ],
}

_CONSUMERS_PAYLOAD = {
    **_BREAKING_PAYLOAD,
    "changes": [
        {**_BREAKING_PAYLOAD["changes"][0], "consumers": ["billing-service"]},
    ],
    "consumers": _CONSUMER_IMPACT,
}


def _last_request_body(httpx_mock: object) -> dict:
    request = httpx_mock.get_requests()[-1]
    return json.loads(request.content.decode("utf-8"))


def test_diff_consumers_flag_is_opt_in(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_BREAKING_PAYLOAD)
    runner.invoke(app, ["diff", str(_SPEC_FILE), "--against", "payments@latest"])
    assert "consumers" not in _last_request_body(httpx_mock)


def test_diff_consumers_flag_requests_and_prints_per_consumer_verdicts(
    httpx_mock: object,
) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_CONSUMERS_PAYLOAD)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest", "--consumers"],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert _last_request_body(httpx_mock)["consumers"] is True
    assert "breaks 1 of 2 consumers: billing-service" in result.stdout
    assert "  breaks billing-service" in result.stdout
    assert "mobile-app: unaffected" in result.stdout
    assert "ghost: no declared surface" in result.stdout
    assert "GET /pets — 200 response `name`" in result.stdout
    # The change line itself names who it breaks, so grepping one line is enough.
    assert "ctg.property_removed /components/schemas/Pet/properties/name — breaks billing-service" in (
        result.stdout
    )


def test_diff_consumers_json_stays_schema_stable(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_CONSUMERS_PAYLOAD)
    result = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@latest",
            "--consumers",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    payload = json.loads(result.stdout)
    jsonschema.validate(
        instance=payload, schema=json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))
    )
    assert payload["consumers"]["breakingConsumers"] == ["billing-service"]
    assert payload["changes"][0]["consumers"] == ["billing-service"]


def test_diff_consumers_does_not_change_the_gate_threshold(httpx_mock: object) -> None:
    """A consumer verdict reports; the exit code still grades the whole specification."""
    safe_with_consumers = {
        **_SAFE_PAYLOAD,
        "consumers": {
            **_CONSUMER_IMPACT,
            "summary": "breaks 0 of 2 consumers",
            "breakingConsumers": [],
            "maxSeverity": None,
            "attribution": [],
        },
    }
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=safe_with_consumers)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest", "--consumers"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "breaks 0 of 2 consumers" in result.stdout


def test_diff_consumers_reports_changes_nobody_is_affected_by(httpx_mock: object) -> None:
    payload = {
        **_BREAKING_PAYLOAD,
        "changes": [{**_BREAKING_PAYLOAD["changes"][0], "consumers": []}],
        "consumers": {
            **_CONSUMER_IMPACT,
            "summary": "breaks 0 of 2 consumers",
            "breakingConsumers": [],
            "counts": {**_CONSUMER_IMPACT["counts"], "changes_unattributed": 1},
            "consumers": [_CONSUMER_IMPACT["consumers"][1]],
            "attribution": [
                {**_CONSUMER_IMPACT["attribution"][0], "consumers": []},
            ],
        },
    }
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=payload)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "payments@latest", "--consumers"],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert "1 change(s) affect no registered consumer" in result.stdout
    assert "breaks billing-service" not in result.stdout


def test_diff_consumers_markdown_asks_the_server_for_the_section(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_CONSUMERS_PAYLOAD)
    httpx_mock.add_response(
        url=_DIFF_URL,
        method="POST",
        text="# Changelog\n\n## Consumer impact\n\n_breaks 1 of 2 consumers: billing-service._\n",
        headers={"content-type": "text/markdown; charset=utf-8"},
    )
    result = runner.invoke(
        app,
        [
            "diff",
            str(_SPEC_FILE),
            "--against",
            "payments@latest",
            "--consumers",
            "--format",
            "md",
        ],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert "## Consumer impact" in result.stdout
    for request in httpx_mock.get_requests():
        assert json.loads(request.content.decode("utf-8"))["consumers"] is True
