"""Tests for ``apiome arazzo run`` — run a stored workflow against a target (COA-1.7, #7043)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.arazzo_run import (
    build_run_body,
    exit_code_for_run,
    load_fixtures,
    load_inputs,
    parse_input_pairs,
    refusal_lines,
    report_lines,
)
from apiome_cli.exit_codes import (
    EXIT_ARAZZO_RUN_FAILED,
    EXIT_POLICY_BLOCKED,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_ITEM_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_PROJECT = {"id": _PROJECT_ID, "name": "Pets", "slug": "pets-flows"}
_VERSION = {"id": _VERSION_ID, "project_id": _PROJECT_ID, "version": "1.0.0", "slug": "1.0.0"}
_SCOPE = ["--project", "pets-flows", "--version", "1.0.0"]
_RUN_URL = f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}/workflows/adoptPet/run"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/pets-flows", json=_PROJECT)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0", json=_VERSION
    )


def _criterion(condition: str, outcome: str = "passed", actual: str | None = None) -> dict:
    return {
        "condition": condition,
        "type": "simple",
        "outcome": outcome,
        "expected": condition,
        "actual": actual,
        "implicit": False,
    }


def _step(step_id: str, outcome: str = "passed", **extra: object) -> dict:
    step = {
        "step_id": step_id,
        "execution": 1,
        "operation_key": "GET /pets/{petId}",
        "method": "GET",
        "path": "/pets/7",
        "outcome": outcome,
        "status_code": 200,
        "attempts": 1,
        "criteria": [_criterion("$statusCode == 200", actual="200 == 200")],
        "outputs": {},
        "action": {"type": "next"},
    }
    step.update(extra)
    return step


def _ran(outcome: str = "passed", steps: list | None = None) -> dict:
    """An executed ``ArazzoWorkflowRunResponse``."""
    return {
        "ok": True,
        "version_id": _VERSION_ID,
        "workflow_id": "adoptPet",
        "digest": "sha256:" + "a" * 64,
        "report": {
            "workflow_id": "adoptPet",
            "outcome": outcome,
            "target": {
                "slug": "pets-mock",
                "environment": "mock",
                "base_url": "http://mock.test/pets",
            },
            "steps": steps if steps is not None else [_step("findPets"), _step("getPet")],
            "not_reached": [],
            "outputs": {"petName": "Rex"},
            "output_errors": [],
            "counts": {"steps": 2, "executed": 2, "passed": 2, "failed": 0, "errored": 0},
        },
        "run": {"id": "run-1"},
        "refusals": [],
        "fixture_findings": [],
        "created": True,
    }


def _refused(*codes: str) -> dict:
    return {
        "ok": False,
        "version_id": _VERSION_ID,
        "workflow_id": "adoptPet",
        "refusals": [
            {"code": code, "message": f"refused: {code}", "step_id": "createPet"} for code in codes
        ],
        "fixture_findings": [],
        "error": {"code": codes[0], "message": "refused"},
    }


# ------------------------------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------------------------------


def test_parse_input_pairs_keeps_json_types():
    assert parse_input_pairs(["status=available", "count=3", "ok=true", 'tags=["a"]', "e="]) == {
        "status": "available",
        "count": 3,
        "ok": True,
        "tags": ["a"],
        "e": "",
    }
    with pytest.raises(ValueError):
        parse_input_pairs(["novalue"])
    with pytest.raises(ValueError):
        parse_input_pairs(["=x"])


def test_load_inputs_merges_file_and_flags(tmp_path: Path):
    path = tmp_path / "inputs.yaml"
    path.write_text("status: sold\nlimit: 5\n", encoding="utf-8")
    assert load_inputs(path, ["status=available"]) == {"status": "available", "limit": 5}
    assert load_inputs(None, None) == {}
    bad = tmp_path / "list.json"
    bad.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_inputs(bad, None)
    with pytest.raises(ValueError):
        load_inputs(tmp_path / "missing.json", None)


def test_load_fixtures_accepts_a_list_or_a_wrapper(tmp_path: Path):
    listed = tmp_path / "fixtures.json"
    listed.write_text(json.dumps([{"operation_key": "POST /pets"}]), encoding="utf-8")
    wrapped = tmp_path / "fixtures.yaml"
    wrapped.write_text("fixtures:\n  - operation_key: DELETE /pets/{petId}\n", encoding="utf-8")
    assert load_fixtures(listed) == [{"operation_key": "POST /pets"}]
    assert load_fixtures(wrapped) == [{"operation_key": "DELETE /pets/{petId}"}]
    assert load_fixtures(None) == []
    bad = tmp_path / "bad.json"
    bad.write_text('{"fixtures": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixtures(bad)


def test_build_run_body():
    body = build_run_body(
        target="pets-mock",
        inputs={"a": 1},
        allow_mutating=True,
        fixtures=[{"operation_key": "POST /pets"}],
        idempotency_key="k",
        context={"commit": "abc"},
    )
    assert body == {
        "target_ref": "pets-mock",
        "inputs": {"a": 1},
        "verification": {"allow_mutating": True, "fixtures": [{"operation_key": "POST /pets"}]},
        "idempotency_key": "k",
        "context": {"commit": "abc"},
    }
    minimal = build_run_body(target="t", inputs={}, allow_mutating=False, fixtures=[])
    assert "idempotency_key" not in minimal and "context" not in minimal


@pytest.mark.parametrize(
    "payload,code",
    [
        (_ran("passed"), EXIT_SUCCESS),
        (_ran("failed"), EXIT_ARAZZO_RUN_FAILED),
        (_ran("errored"), EXIT_ARAZZO_RUN_FAILED),
        (_refused("mutating-method-blocked"), EXIT_POLICY_BLOCKED),
        (_refused("mutating-method-blocked", "mutating-fixture-missing"), EXIT_POLICY_BLOCKED),
        (_refused("mutating-method-blocked", "arazzo-step-unresolved"), EXIT_ARAZZO_RUN_FAILED),
        (_refused("arazzo-inputs-invalid"), EXIT_ARAZZO_RUN_FAILED),
    ],
)
def test_exit_code_for_run(payload: dict, code: int):
    assert exit_code_for_run(payload) == code


def test_report_lines_show_expected_vs_actual_for_failures():
    failed = _step(
        "getPet",
        "failed",
        failure_code="arazzo-criteria-failed",
        failure_message="1 of 2 criteria did not hold",
        criteria=[
            _criterion("$statusCode == 200", actual="200 == 200"),
            _criterion("$response.body#/name == 'Rex'", "failed", "'Fido' == 'Rex'"),
        ],
        action={"type": "end"},
    )
    payload = _ran("failed", [_step("findPets", attempts=2), failed])
    payload["report"]["not_reached"] = ["getOwner"]
    text = "\n".join(report_lines(payload, workflow_id="adoptPet", target="pets-mock"))
    assert "Arazzo workflow adoptPet → target pets-mock — failed" in text
    assert "evidence: run-1" in text
    assert "2 attempts" in text
    assert "FAIL $response.body#/name == 'Rex'  — actual: 'Fido' == 'Rex'" in text
    assert "ok   $statusCode == 200\n" in text + "\n"
    assert "not reached: getOwner" in text
    assert 'petName: "Rex"' in text


def test_report_lines_mark_goto_retry_and_repeat_executions():
    steps = [
        _step("poll", execution=2, action={"type": "retry"}),
        _step("check", action={"type": "goto", "step_id": "poll"}),
    ]
    text = "\n".join(report_lines(_ran("passed", steps), workflow_id="w", target="t"))
    assert "poll (#2)" in text and "then retry" in text and "then goto poll" in text


def test_refusal_lines_include_fixture_findings():
    payload = _refused("mutating-fixture-missing")
    payload["fixture_findings"] = [
        {"code": "fixture-unmatched", "message": "no step", "operation_key": "PUT /x"}
    ]
    lines = refusal_lines(payload)
    assert lines[0] == "  createPet: [mutating-fixture-missing] refused: mutating-fixture-missing"
    assert "fixture PUT /x: [fixture-unmatched]" in lines[1]


# ------------------------------------------------------------------------------------------
# apiome arazzo run
# ------------------------------------------------------------------------------------------


def test_run_posts_the_request_and_prints_the_report(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RUN_URL, method="POST", json=_ran())
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"operation_key": "POST /pets"}]), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "arazzo", "run", "adoptPet", *_SCOPE,
            "--target", "pets-mock",
            "--input", "status=available",
            "--allow-mutating",
            "--fixtures", str(fixtures),
            "--context", "commit=abc",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "— passed" in result.stdout and "findPets" in result.stdout
    sent = json.loads(httpx_mock.get_requests(url=_RUN_URL)[0].content)
    assert sent == {
        "target_ref": "pets-mock",
        "inputs": {"status": "available"},
        "verification": {"allow_mutating": True, "fixtures": [{"operation_key": "POST /pets"}]},
        "context": {"commit": "abc"},
    }


def test_run_failed_criteria_exit_7(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RUN_URL, method="POST", json=_ran("failed"))

    result = runner.invoke(app, ["arazzo", "run", "adoptPet", *_SCOPE, "--target", "pets-mock"])

    assert result.exit_code == EXIT_ARAZZO_RUN_FAILED


def test_run_mutating_refusal_exits_3_and_explains(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RUN_URL, method="POST", json=_refused("mutating-method-blocked"))

    result = runner.invoke(app, ["arazzo", "run", "adoptPet", *_SCOPE, "--target", "pets-mock"])

    assert result.exit_code == EXIT_POLICY_BLOCKED
    assert "nothing was sent" in result.stderr
    assert "[mutating-method-blocked]" in result.stderr


def test_run_json_prints_the_response(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    payload = _ran()
    httpx_mock.add_response(url=_RUN_URL, method="POST", json=payload)

    result = runner.invoke(
        app, ["--json", "arazzo", "run", "adoptPet", *_SCOPE, "--target", "pets-mock"]
    )

    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == payload


def test_run_catalog_uses_the_revision_from_the_catalog_read(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}",
        json={"version_id": _VERSION_ID, "project_id": _ITEM_ID, "workflows": []},
    )
    httpx_mock.add_response(url=_RUN_URL, method="POST", json=_ran())

    result = runner.invoke(
        app, ["arazzo", "run", "adoptPet", "--catalog", _ITEM_ID, "--target", "pets-mock"]
    )

    assert result.exit_code == EXIT_SUCCESS, result.output


def test_run_catalog_without_revisions_is_a_usage_error(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}",
        json={"version_id": None, "project_id": _ITEM_ID, "workflows": []},
    )

    result = runner.invoke(
        app, ["arazzo", "run", "adoptPet", "--catalog", _ITEM_ID, "--target", "t"]
    )

    assert result.exit_code == EXIT_USAGE


def test_run_bad_input_flag_is_a_usage_error() -> None:
    result = runner.invoke(
        app, ["arazzo", "run", "adoptPet", *_SCOPE, "--target", "t", "--input", "oops"]
    )
    assert result.exit_code == EXIT_USAGE


def test_run_requires_a_target() -> None:
    result = runner.invoke(app, ["arazzo", "run", "adoptPet", *_SCOPE])
    assert result.exit_code == EXIT_USAGE


def test_run_unknown_workflow_404_is_a_usage_error(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=_RUN_URL, method="POST", status_code=404, json={"detail": "Workflow not found: adoptPet"}
    )

    result = runner.invoke(app, ["arazzo", "run", "adoptPet", *_SCOPE, "--target", "t"])

    assert result.exit_code == EXIT_USAGE
