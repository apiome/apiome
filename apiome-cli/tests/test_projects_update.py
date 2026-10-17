"""``apiome projects update`` (CLI 3.4, #3205).

Covers the rules (:mod:`apiome_cli.project_update`) and the command end to end against a mocked
REST API: only changed fields are sent; ``--domain`` keeps the rest of ``metadata``; ``--rename``
needs ``--yes`` or a confirmation and says the old slug stops working; ``--from-file`` applies an
edited ``projects get --json`` dump with its ``updated_at`` as the precondition; a stale write is
exit 6 with a re-fetch hint; ``--dry-run`` prints a diff and sends nothing.

The diff renderer is snapshot-tested against ``tests/fixtures/projects_update/*.txt``; regenerate
with ``UPDATE_SNAPSHOTS=1 uv run pytest tests/test_projects_update.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_UPDATE_CONFLICT, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.project_update import (
    ProjectUpdateError,
    changes_from_file,
    changes_from_flags,
    expected_updated_at,
    metadata_with_domain,
    render_diff,
    request_body,
    validate_domain,
    validate_slug,
)

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "projects_update"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BASE = "http://localhost:8000/v1/projects/acme-corp"
_PROJECT = {
    "id": _ID,
    "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "name": "Payments API",
    "slug": "payments-api",
    "description": "Charges and refunds.",
    "enabled": True,
    "metadata": {"domainCategory": "none", "owner": "team-pay"},
    "publishable": True,
    "created_at": "2026-10-01T09:00:00Z",
    "updated_at": "2026-10-16T12:00:00.123456Z",
    "versionsCount": 3,
}


def _snapshot(name: str, text: str) -> None:
    """Compare ``text`` with the committed snapshot ``name`` (or write it on request)."""
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_flags_send_only_what_changes() -> None:
    changes = changes_from_flags(
        _PROJECT, name="Payments API", description="Charges, refunds, payouts.", domain="finance"
    )
    assert set(changes) == {"description", "metadata"}
    assert changes["metadata"] == {"domainCategory": "finance", "owner": "team-pay"}


def test_domain_keeps_other_metadata_and_drops_a_legacy_free_text_domain() -> None:
    project = {**_PROJECT, "metadata": {"domain": "Payments", "owner": "x"}}
    assert metadata_with_domain(project, "none") == {"owner": "x", "domainCategory": "none"}


def test_an_empty_description_clears_it() -> None:
    changes = changes_from_flags(_PROJECT, description="   ")
    assert changes == {"description": None}
    assert request_body(changes, None) == {"description": ""}


@pytest.mark.parametrize("slug", ["a", "-bad", "bad-", "Has Space", "under_score", "x" * 51])
def test_invalid_slugs_are_refused(slug: str) -> None:
    with pytest.raises(ProjectUpdateError):
        validate_slug(slug)


def test_a_valid_slug_is_normalized() -> None:
    assert validate_slug(" Payments-V2 ") == "payments-v2"


def test_domains_come_from_the_allow_list() -> None:
    assert validate_domain("Finance") == "finance"
    assert validate_domain("none") == "none"
    with pytest.raises(ProjectUpdateError, match="Unknown domain"):
        validate_domain("astrology")


def test_an_empty_name_is_refused() -> None:
    with pytest.raises(ProjectUpdateError):
        changes_from_flags(_PROJECT, name="  ")


def test_a_file_changes_only_editable_fields_that_differ() -> None:
    edited = {**_PROJECT, "name": "Payments v2", "versionsCount": 99, "created_at": "x"}
    assert changes_from_file(_PROJECT, edited) == {"name": "Payments v2"}
    assert expected_updated_at(edited) == _PROJECT["updated_at"]


def test_a_file_for_another_project_is_refused() -> None:
    with pytest.raises(ProjectUpdateError, match="describes project"):
        changes_from_file(_PROJECT, {**_PROJECT, "id": "other"})


def test_a_file_without_updated_at_is_refused() -> None:
    with pytest.raises(ProjectUpdateError, match="updated_at"):
        expected_updated_at({"id": _ID})


def test_request_body_carries_the_precondition() -> None:
    assert request_body({"name": "x"}, "2026-10-16T12:00:00Z") == {
        "name": "x",
        "expectedUpdatedAt": "2026-10-16T12:00:00Z",
    }


# ---------------------------------------------------------------------------
# Diff renderer — snapshots
# ---------------------------------------------------------------------------


def test_diff_snapshot_flags() -> None:
    changes = changes_from_flags(
        _PROJECT,
        name="Payments v2",
        rename="payments-v2",
        description="Charges, refunds, payouts, and disputes.",
        domain="finance",
    )
    _snapshot("flags", render_diff(_PROJECT, changes))


def test_diff_snapshot_from_file() -> None:
    edited = {
        **_PROJECT,
        "enabled": False,
        "description": None,
        "metadata": {"domainCategory": "none", "tier": "gold"},
    }
    _snapshot("from-file", render_diff(_PROJECT, changes_from_file(_PROJECT, edited)))


def test_diff_snapshot_no_changes() -> None:
    _snapshot("no-changes", render_diff(_PROJECT, {}))


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def _mock_reads(httpx_mock, project=_PROJECT) -> None:
    httpx_mock.add_response(url=f"{_BASE}/by-slug/payments-api", json=project)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="GET", json=project)


def _sent_body(httpx_mock) -> dict:
    puts = [r for r in httpx_mock.get_requests() if r.method == "PUT"]
    assert len(puts) == 1
    return json.loads(puts[0].content)


def test_update_sends_only_changed_fields_with_the_read_precondition(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}", method="PUT", json={**_PROJECT, "description": "New."}
    )
    result = runner.invoke(
        app,
        ["projects", "update", "payments-api", "--description", "New.", "--domain", "finance"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent_body(httpx_mock) == {
        "description": "New.",
        "metadata": {"domainCategory": "finance", "owner": "team-pay"},
        "expectedUpdatedAt": _PROJECT["updated_at"],
    }
    assert "Updated project 'payments-api': description, metadata.domainCategory." in result.stdout


def test_update_accepts_a_uuid(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="GET", json=_PROJECT)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="PUT", json=_PROJECT)
    result = runner.invoke(app, ["projects", "update", _ID, "--name", "Renamed"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent_body(httpx_mock)["name"] == "Renamed"


def test_rename_without_yes_refuses_in_a_non_interactive_shell(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--rename", "payments-v2"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "from 'payments-api' to 'payments-v2'" in result.stderr
    assert "will stop working; there is no redirect" in result.stderr
    assert "Pass --yes" in result.stderr
    assert not [r for r in httpx_mock.get_requests() if r.method == "PUT"]


def test_rename_with_yes_sends_the_new_slug(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}", method="PUT", json={**_PROJECT, "slug": "payments-v2"}
    )
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--rename", "Payments-V2", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent_body(httpx_mock)["slug"] == "payments-v2"


def test_dry_run_prints_the_diff_and_sends_nothing(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app,
        ["projects", "update", "payments-api", "--rename", "payments-v2", "--dry-run"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert '- slug: "payments-api"' in result.stdout
    assert '+ slug: "payments-v2"' in result.stdout
    assert not [r for r in httpx_mock.get_requests() if r.method == "PUT"]


def test_dry_run_json_reports_the_changes_and_the_request(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app,
        ["--json", "projects", "update", "payments-api", "--name", "P2", "--dry-run"],
        env=_ENV,
    )
    payload = json.loads(result.stdout)
    assert payload["dryRun"] is True
    assert payload["changes"] == [{"field": "name", "before": "Payments API", "after": "P2"}]
    assert payload["request"] == {"name": "P2", "expectedUpdatedAt": _PROJECT["updated_at"]}


def test_from_file_applies_the_dump_with_its_own_precondition(httpx_mock, tmp_path) -> None:
    dump = {**_PROJECT, "name": "Payments v2", "updated_at": "2026-10-15T08:00:00Z"}
    path = tmp_path / "project.json"
    path.write_text(json.dumps(dump), encoding="utf-8")
    _mock_reads(httpx_mock)
    httpx_mock.add_response(url=f"{_BASE}/{_ID}", method="PUT", json={**_PROJECT, **dump})
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--from-file", str(path)], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent_body(httpx_mock) == {
        "name": "Payments v2",
        "expectedUpdatedAt": "2026-10-15T08:00:00Z",
    }


def test_a_stale_dump_is_exit_6_with_a_re_fetch_hint(httpx_mock, tmp_path) -> None:
    path = tmp_path / "project.json"
    path.write_text(json.dumps({**_PROJECT, "name": "Stale"}), encoding="utf-8")
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}",
        method="PUT",
        status_code=409,
        json={
            "detail": {
                "code": "update_conflict",
                "message": "The project changed since it was read; re-fetch it and retry.",
                "current_updated_at": "2026-10-16T13:00:00+00:00",
            }
        },
    )
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--from-file", str(path)], env=_ENV
    )
    assert result.exit_code == EXIT_UPDATE_CONFLICT == 6
    assert "changed since" in result.stderr and "2026-10-16T13:00:00+00:00" in result.stderr
    assert "apiome projects get <id> --json" in result.stderr


def test_a_taken_slug_409_is_an_ordinary_usage_error(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/{_ID}",
        method="PUT",
        status_code=409,
        json={"detail": "A project with that slug already exists in this tenant"},
    )
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--rename", "taken", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "already exists" in result.stderr


def test_nothing_to_change_exits_0_without_writing(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--name", "Payments API"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "nothing to update" in result.stderr
    assert not [r for r in httpx_mock.get_requests() if r.method == "PUT"]


@pytest.mark.parametrize(
    "args,fragment",
    [
        ([], "Nothing to update"),
        (["--name", "x", "--from-file", "f.json"], "cannot be combined"),
    ],
    ids=["no-flags", "file-and-flags"],
)
def test_usage_errors(args, fragment) -> None:
    result = runner.invoke(app, ["projects", "update", "payments-api", *args], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert fragment in result.stderr


def test_an_invalid_domain_is_a_usage_error(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--domain", "astrology"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "Unknown domain" in result.stderr


def test_an_unreadable_file_is_a_usage_error(httpx_mock, tmp_path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app, ["projects", "update", "payments-api", "--from-file", str(path)], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "is not valid JSON" in result.stderr
