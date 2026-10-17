"""``apiome projects delete`` (CLI 3.5, #3206).

Against a mocked REST API: the impact summary is shown first; a project with published versions
is refused with exit 6 unless ``--force``; a permanent delete needs the slug typed exactly
(case-sensitive) or ``--yes`` with the exact slug as the argument; ``--archive`` soft-deletes
after a y/N; a ``409 delete_blocked`` points at ``--archive``; ``--json`` prints
``{"deleted": true, "slug": …}``.

The summary block is snapshot-tested against ``tests/fixtures/projects_delete/*.txt``; regenerate
with ``UPDATE_SNAPSHOTS=1 uv run pytest tests/test_projects_delete.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.commands.projects import deletion_summary
from apiome_cli.exit_codes import EXIT_PUBLISHED_VERSIONS, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "projects_delete"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BASE = "http://localhost:8000/v1/projects/acme-corp"
_IMPACT = {
    "project_id": _ID,
    "slug": "payments-api",
    "name": "Payments API",
    "deleted": False,
    "versions": 8,
    "published_versions": 0,
    "unpublished_versions": 8,
    "classes": 24,
    "properties": 142,
    "paths": 18,
}


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock_reads(httpx_mock, impact=_IMPACT) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/by-slug/payments-api", json={"id": _ID, "slug": "payments-api"}
    )
    httpx_mock.add_response(url=f"{_BASE}/{_ID}/deletion-impact", json=impact)


def _deletes(httpx_mock) -> list:
    return [r for r in httpx_mock.get_requests() if r.method == "DELETE"]


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the prompts run (CliRunner's stdin is not a TTY)."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_snapshot_permanent() -> None:
    impact = {**_IMPACT, "versions": 2341, "unpublished_versions": 2338, "published_versions": 3}
    _snapshot("permanent", deletion_summary(impact, archive=False))


def test_summary_snapshot_archive() -> None:
    _snapshot("archive", deletion_summary(_IMPACT, archive=True))


# ---------------------------------------------------------------------------
# Permanent delete
# ---------------------------------------------------------------------------


def test_typed_slug_deletes_permanently(httpx_mock, interactive) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}?permanent=true", method="DELETE", json={"permanent": True}
    )
    result = runner.invoke(app, ["projects", "delete", "payments-api"], env=_ENV, input="payments-api\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "This will permanently delete:" in result.stderr
    assert "Classes:" in result.stderr and "142" in result.stderr
    assert result.stdout.strip() == "✔ Deleted payments-api."
    assert len(_deletes(httpx_mock)) == 1


def test_the_typed_slug_is_case_sensitive(httpx_mock, interactive) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(app, ["projects", "delete", "payments-api"], env=_ENV, input="Payments-API\n")
    assert result.exit_code == EXIT_USAGE
    assert "Did not match 'payments-api'; nothing was changed." in result.stderr
    assert _deletes(httpx_mock) == []


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(app, ["projects", "delete", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "Pass --yes" in result.stderr
    assert _deletes(httpx_mock) == []


def test_yes_with_the_exact_slug_skips_the_prompt(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}?permanent=true", method="DELETE", json={})
    result = runner.invoke(app, ["--json", "projects", "delete", "payments-api", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == {"deleted": True, "slug": "payments-api", "permanent": True}


def test_yes_needs_the_slug_not_the_uuid(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_BASE}/{_ID}/deletion-impact", json=_IMPACT)
    result = runner.invoke(app, ["projects", "delete", _ID, "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--yes needs the project's exact slug" in result.stderr
    assert _deletes(httpx_mock) == []


def test_a_uuid_with_a_typed_slug_works(httpx_mock, interactive) -> None:
    httpx_mock.add_response(url=f"{_BASE}/{_ID}/deletion-impact", json=_IMPACT)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}?permanent=true", method="DELETE", json={})
    result = runner.invoke(app, ["projects", "delete", _ID], env=_ENV, input="payments-api\n")
    assert result.exit_code == EXIT_SUCCESS, result.output


# ---------------------------------------------------------------------------
# Published versions
# ---------------------------------------------------------------------------


def test_published_versions_refuse_with_exit_6(httpx_mock) -> None:
    _mock_reads(httpx_mock, {**_IMPACT, "published_versions": 3, "unpublished_versions": 5})
    result = runner.invoke(app, ["projects", "delete", "payments-api", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_PUBLISHED_VERSIONS == 6
    assert "has 3 published versions" in result.stderr
    assert "pass --force" in result.stderr
    assert _deletes(httpx_mock) == []


def test_force_deletes_despite_published_versions(httpx_mock) -> None:
    _mock_reads(httpx_mock, {**_IMPACT, "published_versions": 1})
    httpx_mock.add_response(url=f"{_BASE}/{_ID}?permanent=true", method="DELETE", json={})
    result = runner.invoke(
        app, ["projects", "delete", "payments-api", "--yes", "--force"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_archive_is_gated_by_published_versions_too(httpx_mock) -> None:
    _mock_reads(httpx_mock, {**_IMPACT, "published_versions": 1})
    result = runner.invoke(
        app, ["projects", "delete", "payments-api", "--archive", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_PUBLISHED_VERSIONS


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def test_archive_soft_deletes_after_a_yes_no(httpx_mock, interactive) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="DELETE", json={"permanent": False})
    result = runner.invoke(
        app, ["projects", "delete", "payments-api", "--archive"], env=_ENV, input="y\n"
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "can be restored" in result.stderr
    # The y/N prompt (the shared confirm_action) is echoed first; the result is the last line.
    assert result.stdout.strip().splitlines()[-1].startswith("✔ Archived payments-api.")
    assert "permanent" not in str(_deletes(httpx_mock)[0].url)


def test_declining_the_archive_changes_nothing(httpx_mock, interactive) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app, ["projects", "delete", "payments-api", "--archive"], env=_ENV, input="n\n"
    )
    assert result.exit_code == EXIT_SUCCESS
    assert _deletes(httpx_mock) == []


def test_archive_json(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="DELETE", json={})
    result = runner.invoke(
        app, ["--json", "projects", "delete", "payments-api", "--archive", "--yes"], env=_ENV
    )
    assert json.loads(result.stdout) == {"deleted": True, "slug": "payments-api", "permanent": False}


# ---------------------------------------------------------------------------
# Server refusals
# ---------------------------------------------------------------------------


def test_a_blocked_permanent_delete_suggests_archive(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}?permanent=true",
        method="DELETE",
        status_code=409,
        json={
            "detail": {
                "code": "delete_blocked",
                "message": "The project has history that cannot be deleted "
                "(referenced from source_change_audit); archive it (soft delete) instead.",
                "table": "source_change_audit",
            }
        },
    )
    result = runner.invoke(app, ["projects", "delete", "payments-api", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "source_change_audit" in result.stderr
    assert "apiome projects delete payments-api --archive" in result.stderr


def test_other_errors_use_the_shared_mapping(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}?permanent=true",
        method="DELETE",
        status_code=403,
        json={"detail": "You do not have projects:delete."},
    )
    result = runner.invoke(app, ["projects", "delete", "payments-api", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "projects:delete" in result.stderr
