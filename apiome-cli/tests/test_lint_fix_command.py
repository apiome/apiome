"""Tests for ``apiome lint --fix`` / ``--dry-run`` in version mode (GVM-3.3, #5871)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.commands.lint import FIX_APPLY_REASON
from apiome_cli.exit_codes import EXIT_FIXES_REMAIN, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_NEW_VERSION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}
_VERSION = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
}

_FIXES_URL = f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint/fixes"
_APPLY_URL = f"{_FIXES_URL}/apply"

_DIFF = (
    "--- a/openapi.json\n+++ b/openapi.json\n@@ -1,3 +1,2 @@\n"
    '   "Order": {\n-    "required": []\n   }\n'
)


def _entry(fix_id: str, rule_id: str, status: str, **extra: object) -> dict[str, object]:
    """One plan entry with the fields the CLI reads."""
    return {
        "fixId": fix_id,
        "ruleId": rule_id,
        "fixClass": "removal",
        "wireVisible": False,
        "path": "components.schemas.Order",
        "pointer": "/components/schemas/Order",
        "findingId": f"lint-{fix_id}",
        "message": "A finding.",
        "ops": [{"op": "remove", "path": "/components/schemas/Order/required"}],
        "status": status,
        "reason": extra.get("reason"),
        "conflictsWith": extra.get("conflictsWith"),
        "classification": None,
    }


def _plan(*entries: dict[str, object]) -> dict[str, object]:
    """A plan whose ``appliedOrder`` is its ready entries."""
    return {
        "documentFingerprint": "a" * 16,
        "fixedDocumentFingerprint": "b" * 16,
        "includeRenames": False,
        "rules": None,
        "operationIdTemplate": "{method}{Path}",
        "counts": {},
        "appliedOrder": [e["fixId"] for e in entries if e["status"] == "ready"],
        "entries": list(entries),
    }


_READY = _entry("fix-ready", "structure.empty-required", "ready")
_BREAKING = _entry("fix-breaking", "naming.schema-pascal-case", "breaking")
_CONFLICT = _entry(
    "fix-conflict", "structure.schema-example-keyword", "conflict", conflictsWith="fix-ready"
)
_EXCLUDED = _entry(
    "fix-excluded", "naming.operation-id-camel-case", "excluded", reason="renames-not-included"
)

_APPLIED = {
    "projectId": _PROJECT_ID,
    "sourceVersionRecordId": _VERSION_ID,
    "versionRecordId": _NEW_VERSION_ID,
    "versionLabel": "1.0.1",
    "appliedFixIds": ["fix-ready"],
    "skipped": [],
    "score": 91,
    "grade": "A",
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )


def _args(*extra: str) -> list[str]:
    return ["lint", "--project", "payments-api", "--version", "1.0.0", "--fix", *extra]


def _posts(httpx_mock: object) -> list[object]:
    return [r for r in httpx_mock.get_requests() if r.method == "POST"]


def test_dry_run_prints_the_diff_and_writes_nothing(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan(_READY, _BREAKING))
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=diff", text=_DIFF)

    result = runner.invoke(app, _args("--dry-run"))

    # A breaking fix remains, but a dry run never exits 3.
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _DIFF in result.stdout
    assert "Fix plan: 1 ready, 0 conflict, 1 breaking, 0 excluded" in result.stderr
    assert "Dry run: nothing was written." in result.stderr
    assert _posts(httpx_mock) == []


def test_dry_run_json_prints_the_plan_only(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    plan = _plan(_READY)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=plan)

    result = runner.invoke(app, ["--json", *_args("--dry-run")])

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == plan
    assert _posts(httpx_mock) == []


def test_dry_run_writes_the_patch_to_output(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    patch = [{"op": "remove", "path": "/components/schemas/Order/required"}]
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan(_READY))
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=patch", json=patch)
    target = tmp_path / "fixes.json"

    result = runner.invoke(app, _args("--dry-run", "--fix-format", "patch", "-o", str(target)))

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(target.read_text()) == patch
    assert "Fix plan: 1 ready" in result.stdout
    assert _posts(httpx_mock) == []


def test_fix_applies_the_ready_fixes_and_prints_the_new_revision(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan(_READY, _EXCLUDED))
    httpx_mock.add_response(url=_APPLY_URL, method="POST", json=_APPLIED)

    result = runner.invoke(app, _args())

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert f"new revision 1.0.1 ({_NEW_VERSION_ID})" in result.stdout
    assert "1 excluded (not selected)" in result.stdout
    (post,) = _posts(httpx_mock)
    assert json.loads(post.content) == {
        "reason": FIX_APPLY_REASON,
        "includeRenames": False,
        "fixIds": ["fix-ready"],
    }


def test_a_breaking_fix_is_never_written_even_with_allow_renames(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_FIXES_URL}?includeRenames=true&format=json", json=_plan(_READY, _BREAKING)
    )
    httpx_mock.add_response(url=_APPLY_URL, method="POST", json=_APPLIED)

    result = runner.invoke(app, _args("--allow-renames"))

    assert result.exit_code == EXIT_FIXES_REMAIN, result.output
    (post,) = _posts(httpx_mock)
    body = json.loads(post.content)
    assert body["fixIds"] == ["fix-ready"]
    assert body["includeRenames"] is True
    assert "1 breaking: never applied" in result.stdout


def test_only_breaking_fixes_means_nothing_is_applied_and_exit_3(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan(_BREAKING))

    result = runner.invoke(app, _args())

    assert result.exit_code == EXIT_FIXES_REMAIN, result.output
    assert _posts(httpx_mock) == []


def test_a_conflict_remaining_exits_3(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan(_READY, _CONFLICT))
    httpx_mock.add_response(url=_APPLY_URL, method="POST", json=_APPLIED)

    result = runner.invoke(app, _args())

    assert result.exit_code == EXIT_FIXES_REMAIN, result.output
    assert "1 conflict: run --fix again" in result.stdout


def test_nothing_to_fix_exits_0_without_applying(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_FIXES_URL}?format=json", json=_plan())

    result = runner.invoke(app, _args())

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Nothing to fix" in result.stdout
    assert _posts(httpx_mock) == []


def test_only_restricts_the_plan_and_the_apply_to_the_named_rules(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_FIXES_URL}?rules=structure.empty-required&format=json", json=_plan(_READY)
    )
    httpx_mock.add_response(url=_APPLY_URL, method="POST", json=_APPLIED)

    result = runner.invoke(
        app, _args("--only", "structure.empty-required, structure.empty-required")
    )

    assert result.exit_code == EXIT_SUCCESS, result.output
    (post,) = _posts(httpx_mock)
    body = json.loads(post.content)
    assert body["rules"] == ["structure.empty-required"]
    assert "fixIds" not in body


def test_only_with_an_unknown_rule_is_refused(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_FIXES_URL}?rules=no.such-rule&format=json",
        status_code=422,
        json={
            "detail": {
                "code": "lint-fix-invalid-options",
                "message": "no fixable rule 'no.such-rule'",
            }
        },
    )

    result = runner.invoke(app, _args("--only", "no.such-rule"))

    assert result.exit_code == EXIT_USAGE
    assert "no.such-rule" in result.output
    assert _posts(httpx_mock) == []


def test_only_naming_no_rule_is_a_usage_error() -> None:
    result = runner.invoke(app, _args("--only", " , "))

    assert result.exit_code == EXIT_USAGE
    assert "at least one rule" in result.output


@pytest.mark.parametrize(
    "extra",
    [["--dry-run"], ["--only", "structure.empty-required"], ["--allow-renames"], ["-o", "x.diff"]],
)
def test_fix_options_need_fix(extra: list[str]) -> None:
    result = runner.invoke(app, ["lint", "--project", "p", "--version", "v", *extra])

    assert result.exit_code == EXIT_USAGE
    assert "only work with --fix" in result.output


def test_fix_refuses_report_options() -> None:
    result = runner.invoke(app, _args("--min-grade", "B"))

    assert result.exit_code == EXIT_USAGE
    assert "cannot be combined" in result.output


def test_fix_refuses_an_unknown_format() -> None:
    result = runner.invoke(app, _args("--fix-format", "json"))

    assert result.exit_code == EXIT_USAGE
    assert "diff, patch, overlay" in result.output
