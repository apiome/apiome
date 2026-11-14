"""``apiome migrations show <plan-id>`` (CLI 11.3, #3262).

Snapshot tests of the human output (``tests/fixtures/migrations/show*.txt``; regenerate with
``UPDATE_SNAPSHOTS=1``) and the command against a mocked
``GET /v1/migration-plans/{t}/{plan_id}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.migration_view import mapping_lines, render_plan_show

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "migrations"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PLAN_ID = "3a910000-0000-4000-8000-00000000b41c"


def _rule(class_name: str, prop: str, outputs: list[str], **extra) -> dict:
    return {
        "class_name": class_name,
        "source_property": prop,
        "rule": {"inputProperties": [prop], "outputProperties": outputs, "ruleType": "simple", **extra},
    }


_PLAN = {
    "id": _PLAN_ID,
    "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "project_slug": "payments-api",
    "project_name": "Payments API",
    "from_version_id": "20000000-0000-4000-8000-000000000020",
    "from_version": "2.0.0",
    "to_version_id": "21000000-0000-4000-8000-000000000021",
    "to_version": "2.1.0",
    "created_at": "2026-04-28T09:00:00Z",
    "updated_at": "2026-05-04T12:43:10Z",
    "rules": [
        _rule("Charge", "fee", []),
        _rule("Charge", "legacy_status", ["status"], name="rename"),
        _rule("Customer", "zip", ["postal_code"], ruleType="script", ruleContent="return zip.strip()"),
    ],
}


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, plan=_PLAN) -> None:
    httpx_mock.add_response(url=f"{_HOST}/migration-plans/acme/{_PLAN_ID}", json=plan)


def _show(*args: str):
    return runner.invoke(app, ["migrations", "show", _PLAN_ID, *args], env=_ENV)


# --- presentation ---------------------------------------------------------------------------


def test_show_snapshot() -> None:
    _snapshot("show", render_plan_show(_PLAN))


def test_show_mappings_snapshot() -> None:
    _snapshot("show_mappings", render_plan_show(_PLAN, scope="mappings"))


def test_mapping_lines_align_the_arrows() -> None:
    lines = mapping_lines(_PLAN["rules"])
    assert lines[0] == "Charge.fee           → (removed)             (simple)"
    assert lines[1] == "Charge.legacy_status → Charge.status         (simple · rename)"
    assert {line.index("→") for line in lines} == {21}
    assert {line.rindex("(") for line in lines} == {45}


def test_mapping_falls_back_to_the_source_property_and_simple() -> None:
    lines = mapping_lines([{"class_name": "Order", "source_property": "total", "rule": {}}])
    assert lines == ["Order.total → (removed)  (simple)"]


def test_mapping_with_several_inputs() -> None:
    rule = {"inputProperties": ["first", "last"], "outputProperties": ["full_name"], "ruleType": "sparkSql"}
    assert mapping_lines([{"class_name": "Person", "source_property": "first", "rule": rule}]) == [
        "Person.first + Person.last → Person.full_name  (sparkSql)"
    ]


def test_plan_without_rules_says_none() -> None:
    text = render_plan_show({**_PLAN, "rules": []})
    assert "Rules:    0 across 0 classes" in text
    assert text.endswith("Mappings:\n  (none)")


def test_missing_version_label_falls_back_to_the_id() -> None:
    text = render_plan_show({**_PLAN, "to_version": None})
    assert "To:       21000000-0000-4000-8000-000000000021" in text


def test_unknown_scope_is_rejected() -> None:
    with pytest.raises(ValueError):
        render_plan_show(_PLAN, scope="notes")


# --- the command ----------------------------------------------------------------------------


def test_show_prints_the_plan(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _show()
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_plan_show(_PLAN) + "\n"


def test_scope_mappings_prints_only_the_mappings(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _show("--scope", "mappings")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout.startswith("Mappings:\n")
    assert "Project:" not in result.stdout


def test_bad_scope_is_a_usage_error() -> None:
    result = _show("--scope", "notes")
    assert result.exit_code == EXIT_USAGE
    assert "--scope must be one of: all, mappings." in result.stderr


def test_non_uuid_is_a_usage_error_without_a_request() -> None:
    result = runner.invoke(app, ["migrations", "show", "mp_3a91"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "'mp_3a91' is not a migration plan id" in result.stderr


def test_unknown_plan_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/migration-plans/acme/{_PLAN_ID}",
        status_code=404,
        json={"detail": f"Migration plan not found: {_PLAN_ID}"},
    )
    result = _show()
    assert result.exit_code == EXIT_USAGE
    assert "Migration plan not found" in result.output


def test_json_returns_the_raw_body(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _show("--json", "--scope", "mappings")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _PLAN


def test_global_json_flag_matches_the_local_one(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["--json", "migrations", "show", _PLAN_ID], env=_ENV)
    assert json.loads(result.stdout) == _PLAN
