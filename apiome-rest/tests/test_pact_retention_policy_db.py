"""Stored clean-up rules against a live Postgres — PFX-8.14 (#7311).

What only the real schema (apiome-db V456) and the real routes prove:

* the rules save and read back; a rule set that would remove a deployed version is refused and
  leaves no row;
* **the preview lists exactly what the next nightly sweep deletes**, and the sweep records its run;
* Recently deleted lists the sweep's deletions as *Clean-up* with the workspace's purge date, and a
  restore takes a row off it;
* the purge honours each workspace's own restore window;
* nothing crosses a tenant: another workspace reads its own (default) rules and an empty list.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of ``test_pact_publication_db``).
Skipped when no database is reachable or V456 is not applied.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest

from app.pact_cleanup_store import purge_deleted
from app.pact_retention_policy_store import get_policy, list_recently_deleted, run_nightly_clean_up
from tests import test_pact_cleanup_db as cleanup_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker
cleanup = cleanup_db.cleanup
history = cleanup_db.history

pytestmark = pytest.mark.requires_db

POLICY = "/v1/tenants/t/pact-retention/policy"
DELETED = "/v1/tenants/t/pact-retention/deleted"
NATIVE = cleanup_db.NATIVE


@pytest.fixture
def rules(history: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The clean-up history, V456 applied, the caller allowed to change the rules, main = ``main``."""
    history["cursor"].execute("SELECT to_regclass('apiome.pact_retention_policy') AS t")
    if not history["cursor"].fetchone()["t"]:
        pytest.skip("V456 not applied")
    response = history["client"].patch(f"{NATIVE}/billing-service", json={"main_branch": "main"})
    assert response.status_code == 200, response.text
    with patch("app.pact_retention_routes.has_permission", return_value=True):
        yield history


def _due() -> datetime:
    """A time at which today's nightly run is due (after 02:00 UTC)."""
    now = datetime.now(timezone.utc)
    return max(now, now.replace(hour=2, minute=30, second=0, microsecond=0))


def _deleted_numbers(stack: Dict[str, Any]) -> List[str]:
    return sorted(v["number"] for v in cleanup_db._versions(stack, state="deleted"))


def test_rules_save_and_read_back(rules: Dict[str, Any]) -> None:
    client = rules["client"]
    assert client.get(POLICY).json()["configured"] is False
    saved = client.put(POLICY, json={"keep_main_branch_latest": 2, "keep_tags": ["keep"], "restore_window_days": 7})
    assert saved.status_code == 200, saved.text
    read = client.get(POLICY).json()
    assert (read["configured"], read["keep_main_branch_latest"], read["keep_tags"]) == (True, 2, ["keep"])
    assert (read["restore_window_days"], read["nightly_enabled"], read["can_edit"]) == (7, False, True)
    assert cleanup_db._audits(rules, "pacts.retention.policy")


def test_a_rule_set_that_removes_deployed_versions_leaves_no_row(rules: Dict[str, Any]) -> None:
    refused = rules["client"].put(POLICY, json={"keep_deployed_or_released": False})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "pact-retention-keeps-in-use")
    rules["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.pact_retention_policy WHERE tenant_id = %s::uuid", (rules["seed"]["tenant"],)
    )
    assert rules["cursor"].fetchone()["n"] == 0


def test_the_preview_is_what_the_next_nightly_sweep_deletes(rules: Dict[str, Any]) -> None:
    client = rules["client"]
    body = {
        "keep_main_branch_latest": 2,
        "keep_other_branch_latest": 1,
        "nightly_enabled": True,
        "restore_window_days": 7,
    }
    assert client.put(POLICY, json=body).status_code == 200

    preview = client.post(f"{POLICY}/preview", json={})
    assert preview.status_code == 200, preview.text
    plan = preview.json()["plan"]
    previewed = sorted(d["number"] for row in plan["pacticipants"] for d in row["deletions"])
    # main keeps 4.0.0 / 5.0.0, 1.0.0 is deployed, f-1 is the latest of feat/x.
    assert previewed == ["2.0.0", "3.0.0"]
    assert plan["pacts"] == 2 and preview.json()["nightly_enabled"] is True

    totals = run_nightly_clean_up(rules["db"], now=_due())
    assert totals["deleted"] == 2
    assert _deleted_numbers(rules) == previewed
    last = client.get(POLICY).json()["last_run"]
    assert (last["deleted"], last["remaining"], last["error"]) == (2, 0, None)
    # It ran today: a second tick does nothing.
    assert run_nightly_clean_up(rules["db"], now=_due())["tenants"] == 0


def test_recently_deleted_shows_the_clean_up_and_a_restore_takes_it_off(rules: Dict[str, Any]) -> None:
    client = rules["client"]
    client.put(
        POLICY,
        json={
            "keep_main_branch_latest": 2,
            "keep_other_branch_latest": 1,
            "nightly_enabled": True,
            "restore_window_days": 7,
        },
    )
    run_nightly_clean_up(rules["db"], now=_due())

    page = client.get(DELETED).json()
    assert sorted(item["number"] for item in page["items"]) == ["2.0.0", "3.0.0"]
    first = page["items"][0]
    assert (first["kind"], first["deleted_by"], first["cause"]) == ("version", "Clean-up", "retention")
    deleted_at = datetime.fromisoformat(first["deleted_at"])
    assert datetime.fromisoformat(first["purge_after"]) == deleted_at + timedelta(days=7)
    assert page["restore_window_days"] == 7 and page["can_restore"] is True

    restored = client.post(f"{NATIVE}/billing-service/versions/2.0.0/restore")
    assert restored.status_code == 200, restored.text
    assert [item["number"] for item in client.get(DELETED).json()["items"]] == ["3.0.0"]


def test_the_purge_uses_the_workspaces_own_restore_window(rules: Dict[str, Any]) -> None:
    client = rules["client"]
    assert client.put(POLICY, json={"restore_window_days": 7}).status_code == 200
    assert client.delete(f"{NATIVE}/billing-service/versions/2.0.0").status_code == 204
    assert purge_deleted(rules["db"], now=cleanup_db._later(6))["versions"] == 0
    assert purge_deleted(rules["db"], now=cleanup_db._later(8))["versions"] == 1
    assert _deleted_numbers(rules) == []


def test_nothing_crosses_a_tenant(rules: Dict[str, Any]) -> None:
    client = rules["client"]
    client.put(POLICY, json={"keep_main_branch_latest": 1, "nightly_enabled": True, "restore_window_days": 7})
    assert client.delete(f"{NATIVE}/billing-service/versions/2.0.0").status_code == 204
    other = rules["other"]["tenant"]
    assert get_policy(rules["db"], other, can_edit=False).configured is False
    assert list_recently_deleted(rules["db"], other).items == []
    assert [item["number"] for item in client.get(DELETED).json()["items"]] == ["2.0.0"]
