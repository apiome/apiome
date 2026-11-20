"""``apiome upgrade`` — COA-2.6 (#7049).

* A FILE is planned from its text; ``--output`` writes the upgraded document (JSON, or YAML by
  extension); the plan lists every change unless ``--summary``.
* ``--project`` plans a version; ``--apply`` sends the plan digest and prints the new version.
* Misuse is a usage error: no source, two sources, ``--apply`` with a FILE, a bad ``--to``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.upgrade_output import format_upgrade_applied, format_upgrade_plan

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_PLAN_URL = f"{_BASE}/v1/openapi-upgrade/acme-corp/plan"
_APPLY_URL = f"{_BASE}/v1/openapi-upgrade/acme-corp/apply"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PROJECT = {"id": _PROJECT_ID, "name": "Pets", "slug": "pets", "enabled": True}

_PLAN = {
    "source_version": "3.0.3",
    "source_family": "3.0",
    "target": "3.1",
    "target_version": "3.1.2",
    "hops": ["3.0→3.1"],
    "already_current": False,
    "change_count": 2,
    "review_count": 1,
    "rules": [
        {"rule": "openapi-version", "title": "Version string", "hop": "*", "count": 1},
        {
            "rule": "nullable-ref",
            "title": "nullable next to $ref",
            "hop": "3.0→3.1",
            "count": 1,
        },
    ],
    "changes": [
        {
            "hop": "3.0→3.1",
            "rule": "openapi-version",
            "pointer": "/openapi",
            "summary": "openapi 3.0.3 becomes 3.1.2",
            "review": False,
        },
        {
            "hop": "3.0→3.1",
            "rule": "nullable-ref",
            "pointer": "/components/schemas/Pet",
            "summary": "nullable next to $ref",
            "review": True,
        },
    ],
    "plan_digest": "sha256:abc",
    "document": {
        "openapi": "3.1.2",
        "info": {"title": "Pets", "version": "1"},
        "paths": {},
    },
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "pets.yaml"
    path.write_text(
        "openapi: 3.0.3\ninfo: {title: Pets, version: '1'}\npaths: {}\n",
        encoding="utf-8",
    )
    return path


def _sent(httpx_mock: object, url: str) -> dict:
    request = next(r for r in httpx_mock.get_requests() if str(r.url) == url)
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def test_format_plan_lists_every_change_and_marks_review() -> None:
    lines = format_upgrade_plan(_PLAN)
    assert lines[0].startswith(
        "Upgrade OpenAPI 3.0 (3.0.3) → OpenAPI 3.1.2: 2 change(s), 1 to review"
    )
    assert any("nullable-ref" in line and "1" in line for line in lines)
    assert "  3.0→3.1  nullable-ref  /components/schemas/Pet  [review]" in lines


def test_format_plan_summary_omits_changes() -> None:
    assert "Every change:" not in format_upgrade_plan(_PLAN, summary_only=True)


def test_format_plan_already_current() -> None:
    plan = {
        **_PLAN,
        "already_current": True,
        "source_version": "3.1.0",
        "source_family": "3.1",
    }
    assert format_upgrade_plan(plan) == [
        "OpenAPI 3.1 (3.1.0) is already at 3.1; nothing to upgrade."
    ]


def test_format_applied() -> None:
    lines = format_upgrade_applied(
        {
            "version_label": "2.0.0",
            "target_version": "3.1.2",
            "change_count": 2,
            "source_version_record_id": "r1",
            "version_record_id": "r2",
        }
    )
    assert lines[0].startswith("Created version 2.0.0 (OpenAPI 3.1.2, 2 change(s))")


# ---------------------------------------------------------------------------
# A local file
# ---------------------------------------------------------------------------
def test_upgrade_a_file_prints_the_plan(httpx_mock, source: Path) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    result = runner.invoke(app, ["upgrade", str(source), "--to", "3.1"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Every change:" in result.output
    sent = _sent(httpx_mock, _PLAN_URL)
    assert sent["target"] == "3.1"
    assert sent["document_text"].startswith("openapi: 3.0.3")
    assert sent["include_document"] is False


@pytest.mark.parametrize("name,starts", [("out.json", "{"), ("out.yaml", "openapi")])
def test_upgrade_a_file_writes_the_document(
    httpx_mock, source: Path, tmp_path: Path, name: str, starts: str
) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    out = tmp_path / name
    result = runner.invoke(
        app, ["upgrade", str(source), "--to", "3.1", "--output", str(out), "--summary"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    text = out.read_text(encoding="utf-8")
    assert text.lstrip().startswith(starts)
    assert "3.1.2" in text
    assert _sent(httpx_mock, _PLAN_URL)["include_document"] is True
    assert "Every change:" not in result.output


def test_upgrade_json_mode(httpx_mock, source: Path) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    result = runner.invoke(app, ["--json", "upgrade", str(source), "--to", "3.1"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["plan_digest"] == "sha256:abc"
    assert "document" not in payload


# ---------------------------------------------------------------------------
# A project version
# ---------------------------------------------------------------------------
def test_upgrade_a_project_plans_without_writing(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/pets", json=_PROJECT
    )
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    result = runner.invoke(
        app, ["upgrade", "--project", "pets", "--version", "1.0.0", "--to", "3.1"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Run again with --apply" in result.output
    sent = _sent(httpx_mock, _PLAN_URL)
    assert sent["project_id"] == _PROJECT_ID and sent["version"] == "1.0.0"
    assert not any(str(r.url) == _APPLY_URL for r in httpx_mock.get_requests())


def test_upgrade_a_project_applies_with_the_plan_digest(httpx_mock) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    httpx_mock.add_response(
        url=_APPLY_URL,
        method="POST",
        json={
            "project_id": _PROJECT_ID,
            "version_record_id": "rev-new",
            "version_label": "2.0.0",
            "source_version_record_id": "rev-old",
            "target_version": "3.1.2",
            "change_count": 2,
        },
    )
    result = runner.invoke(
        app,
        [
            "upgrade",
            "--project",
            _PROJECT_ID,
            "--to",
            "3.1",
            "--apply",
            "--version-label",
            "2.0.0",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Created version 2.0.0" in result.output
    assert _sent(httpx_mock, _APPLY_URL) == {
        "target": "3.1",
        "project_id": _PROJECT_ID,
        "plan_digest": "sha256:abc",
        "version_label": "2.0.0",
    }


def test_apply_is_skipped_when_already_current(httpx_mock) -> None:
    httpx_mock.add_response(
        url=_PLAN_URL, method="POST", json={**_PLAN, "already_current": True}
    )
    result = runner.invoke(
        app, ["upgrade", "--project", _PROJECT_ID, "--to", "3.1", "--apply"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "nothing to upgrade" in result.output


def test_a_rest_refusal_is_a_usage_error(httpx_mock) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_PLAN)
    httpx_mock.add_response(
        url=_APPLY_URL,
        method="POST",
        status_code=409,
        json={"detail": {"code": "plan-stale", "message": "changed"}},
    )
    result = runner.invoke(
        app, ["upgrade", "--project", _PROJECT_ID, "--to", "3.1", "--apply"]
    )
    assert result.exit_code == EXIT_USAGE


# ---------------------------------------------------------------------------
# Misuse
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "args",
    [
        ["upgrade", "--to", "3.1"],
        ["upgrade", "x.yaml", "--project", "pets", "--to", "3.1"],
        ["upgrade", "x.yaml", "--to", "3.1", "--apply"],
        ["upgrade", "x.yaml", "--to", "3.1", "--version", "1.0.0"],
        ["upgrade", "--project", "pets", "--to", "3.1", "--version-label", "2.0.0"],
        ["upgrade", "x.yaml", "--to", "4.0"],
    ],
)
def test_misuse_is_a_usage_error(args: list) -> None:
    assert runner.invoke(app, args).exit_code == EXIT_USAGE
