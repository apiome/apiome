"""Labels, soft delete, restore, retention and purge against a live Postgres — PFX-1.11 (#6924).

What only the real schema (apiome-db V437) and the real routes prove:

* deleting a version hides its pacts, the results it published and its deployments from every read
  (pact reads, the matrix, environments), moves a branch head back, frees the number, and is
  audited; restoring brings all of it back, or is refused when the number was taken meanwhile;
* a version that is deployed is not deleted without ``force``;
* deleting a pacticipant (broker or native API) hides it and its versions, frees the handle, and a
  restore brings back only the versions deleted with it;
* labels — native and broker shape — are idempotent, filter the pacticipant list and vanish with a
  deleted pacticipant;
* a retention run is dry-run first, keeps the latest version, the newest N per branch and anything
  deployed, refuses a stale digest, and its deletions are restorable;
* the purge waits for the grace period, then removes rows for good and keeps branch heads valid;
* V432's immutability trigger still refuses every change but the deletion stamp;
* nothing crosses a tenant.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of ``test_pact_publication_db``).
Skipped when no database is reachable or V437 is not applied.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import psycopg2
import pytest

from app.pact_cleanup_store import purge_deleted
from app.pacticipant import PacticipantInput
from app.pacticipant_store import create_pacticipant
from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PAIR = publication_db.PAIR
NATIVE = "/v1/tenants/t/pacticipants"
RETENTION = "/v1/tenants/t/pact-retention"
ACTOR = publication_db.ACTOR


@pytest.fixture
def cleanup(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The matrix stack, with this ticket's routes on the same transaction."""
    broker["cursor"].execute("SELECT to_regclass('apiome.pacticipant_label') AS t")
    if not broker["cursor"].fetchone()["t"]:
        pytest.skip("V437 not applied")
    modules = ("pact_broker_cleanup_routes", "pact_retention_routes")
    patches = [patch(f"app.{module}.db", broker["db"]) for module in modules]
    patches += [patch(f"app.{module}.enforce_permission", return_value=None) for module in modules]
    for item in patches:
        item.start()
    try:
        yield broker
    finally:
        for item in patches:
            item.stop()


@contextmanager
def _refused(cursor: Any, error: type) -> Iterator[None]:
    """Expect ``error`` from the statements inside, without losing the test's transaction."""
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(error):
        yield
    cursor.execute("ROLLBACK TO SAVEPOINT refused")


def _publish(stack: Dict[str, Any], version: str, branch: str = "main") -> str:
    """Billing Service ``version`` publishes a pact (distinct content per version) on ``branch``."""
    return matrix_db._publish(stack, version, total=1000 + len(stack.setdefault("_published", [])), branch=branch)


def _versions(stack: Dict[str, Any], slug: str = "billing-service", **params: Any) -> List[Dict[str, Any]]:
    response = stack["client"].get(f"{NATIVE}/{slug}/versions", params=params)
    assert response.status_code == 200, response.text
    return response.json()["versions"]


def _heads(stack: Dict[str, Any], slug: str = "billing-service") -> Dict[str, str]:
    response = stack["client"].get(f"{NATIVE}/{slug}/branches")
    assert response.status_code == 200, response.text
    return {branch["name"]: branch["head_version"] for branch in response.json()["branches"]}


def _audits(stack: Dict[str, Any], action: str) -> List[Dict[str, Any]]:
    stack["cursor"].execute(
        "SELECT target, detail FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = %s ORDER BY created_at",
        (stack["seed"]["tenant"], action),
    )
    return [dict(row) for row in stack["cursor"].fetchall()]


def _later(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


# ---------------------------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------------------------


def test_deleting_a_version_hides_its_pact_moves_the_head_and_frees_the_number(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "2.0.0")
    assert _heads(cleanup) == {"main": "2.0.0"}

    response = client.delete(f"{NATIVE}/billing-service/versions/2.0.0", params={"reason": "broken build"})
    assert response.status_code == 204, response.text
    assert client.get(f"{PAIR}/version/2.0.0").status_code == 404
    assert client.get(f"{PAIR}/latest").json()["_links"]["pb:consumer-version"]["name"] == "1.0.0"
    assert client.get(f"{NATIVE}/billing-service/versions/2.0.0").status_code == 404
    assert _heads(cleanup) == {"main": "1.0.0"}
    assert [v["number"] for v in _versions(cleanup)] == ["1.0.0"]

    (deleted,) = _versions(cleanup, state="deleted")
    assert (deleted["number"], deleted["delete_cause"]) == ("2.0.0", "version")
    assert deleted["delete_reason"] == "broken build"
    assert deleted["purge_after"] and deleted["deleted_at"]
    (audit,) = _audits(cleanup, "pacts.version.delete")
    assert audit["target"] == "pacticipant/billing-service/version/2.0.0"
    assert audit["detail"]["reason"] == "broken build"

    # The number is free: publishing it again records a new version, and the old one cannot come back.
    _publish(cleanup, "2.0.0")
    assert _heads(cleanup) == {"main": "2.0.0"}
    conflict = client.post(f"{NATIVE}/billing-service/versions/2.0.0/restore")
    assert (conflict.status_code, conflict.json()["detail"]["code"]) == (409, "pacticipant-restore-conflict")


def test_restoring_a_version_brings_back_its_pact_and_its_head(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "2.0.0")
    assert client.delete(f"{BASE}/pacticipants/billing-service/versions/2.0.0").status_code == 204
    assert _heads(cleanup) == {"main": "1.0.0"}

    restored = client.post(f"{NATIVE}/billing-service/versions/2.0.0/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert _heads(cleanup) == {"main": "2.0.0"}
    assert client.get(f"{PAIR}/version/2.0.0").status_code == 200
    assert len(_audits(cleanup, "pacts.version.restore")) == 1

    again = client.post(f"{NATIVE}/billing-service/versions/2.0.0/restore")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "pacticipant-not-deleted")
    missing = client.post(f"{NATIVE}/billing-service/versions/9.9.9/restore")
    assert missing.status_code == 404


def test_a_branch_whose_versions_are_all_deleted_is_hidden_until_one_is_recorded(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "f-1", branch="feat/x")
    assert client.delete(f"{NATIVE}/billing-service/versions/f-1").status_code == 204
    assert _heads(cleanup) == {"main": "1.0.0"}
    _publish(cleanup, "f-2", branch="feat/x")
    assert _heads(cleanup) == {"main": "1.0.0", "feat/x": "f-2"}


def test_a_deployed_version_is_refused_unless_forced_and_its_deployment_goes_with_it(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    environment_db._create_environment(cleanup, "production", production=True)
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "2.0.0")
    matrix_db._deploy(cleanup, "billing-service", "1.0.0")

    refused = client.delete(f"{NATIVE}/billing-service/versions/1.0.0")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "pacticipant-version-in-use")
    assert "1.0.0" in refused.json()["detail"]["message"]
    whole = client.delete(f"{BASE}/pacticipants/billing-service")
    assert whole.status_code == 409

    assert client.delete(f"{NATIVE}/billing-service/versions/1.0.0", params={"force": "true"}).status_code == 204
    env = environment_db._environment_resource(cleanup, "production")
    current = client.get(
        environment_db._path(env["_links"]["pb:currently-deployed-deployed-versions"]["href"]),
        params={"pacticipant": "billing-service"},
    )
    assert current.json()["_embedded"]["deployedVersions"] == []
    assert _audits(cleanup, "pacts.version.delete")[0]["detail"]["forced"] is True


def test_a_deleted_provider_version_takes_its_verification_results_out_of_the_matrix(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    sha = _publish(cleanup, "1.0.0")
    matrix_db._provider_version(cleanup, "p-1")
    matrix_db._verify(cleanup, sha, "p-1", True)
    pairs = [("q[][pacticipant]", "Billing Service"), ("q[][version]", "1.0.0"), ("latestby", "cvp")]
    (row,) = matrix_db._get(cleanup, "matrix", pairs).json()["matrix"]
    assert row["verificationResult"]["success"] is True

    assert client.delete(f"{BASE}/pacticipants/ledger-api/versions/p-1").status_code == 204
    rows = matrix_db._get(cleanup, "matrix", pairs).json()["matrix"]
    assert all(not row.get("verificationResult") for row in rows)
    assert client.get(f"{PAIR}/pact-version/{sha}/verification-results/1").status_code == 404


# ---------------------------------------------------------------------------------------------
# Pacticipants
# ---------------------------------------------------------------------------------------------


def test_a_deleted_pacticipant_frees_its_handle_and_restores_only_what_went_with_it(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "2.0.0")
    # Deleted on its own first: it stays deleted when the pacticipant comes back.
    assert client.delete(f"{NATIVE}/billing-service/versions/1.0.0").status_code == 204
    original = client.get(f"{NATIVE}/billing-service").json()["id"]

    assert client.delete(f"{BASE}/pacticipants/billing-service", params={"reason": "renamed"}).status_code == 204
    assert client.get(f"{NATIVE}/billing-service").status_code == 404
    assert client.get(f"{BASE}/pacticipants/billing-service").status_code == 404
    assert client.get(f"{PAIR}/latest").status_code == 404
    (listed,) = client.get(NATIVE, params={"state": "deleted"}).json()["pacticipants"]
    assert (listed["id"], listed["delete_reason"]) == (original, "renamed")
    assert listed["purge_after"]

    # Publishing the name again registers a new pacticipant; the deleted one cannot take it back.
    _publish(cleanup, "3.0.0")
    fresh = client.get(f"{NATIVE}/billing-service").json()
    assert fresh["id"] != original
    conflict = client.post(f"{NATIVE}/{original}/restore")
    assert (conflict.status_code, conflict.json()["detail"]["code"]) == (409, "pacticipant-restore-conflict")

    assert client.delete(f"{NATIVE}/billing-service").status_code == 204
    restored = client.post(f"{NATIVE}/{original}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == original and restored.json()["deleted_at"] is None
    assert [v["number"] for v in _versions(cleanup)] == ["2.0.0"]
    assert [v["number"] for v in _versions(cleanup, state="deleted")] == ["1.0.0"]
    assert _heads(cleanup) == {"main": "2.0.0"}
    assert client.get(f"{PAIR}/latest").json()["_links"]["pb:consumer-version"]["name"] == "2.0.0"
    assert [a["detail"]["versions"] for a in _audits(cleanup, "pacts.pacticipant.restore")] == [1]


def test_nothing_crosses_a_tenant(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    theirs = create_pacticipant(
        cleanup["db"], cleanup["other"]["tenant"], PacticipantInput(name="Their Service"), actor=ACTOR
    )
    for response in (
        client.delete(f"{NATIVE}/{theirs.id}"),
        client.delete(f"{BASE}/pacticipants/{theirs.slug}"),
        client.put(f"{NATIVE}/{theirs.slug}/labels/mine"),
        client.put(f"{BASE}/pacticipants/{theirs.slug}/labels/mine"),
        client.post(f"{NATIVE}/{theirs.id}/restore"),
    ):
        assert response.status_code == 404, response.text
    retention = client.post(RETENTION, json={"keep": {"latest_per_branch": 1}, "pacticipants": [theirs.slug]})
    assert retention.status_code == 404


# ---------------------------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------------------------


def test_labels_in_both_shapes(cleanup: Dict[str, Any]) -> None:
    client = cleanup["client"]
    _publish(cleanup, "1.0.0")
    assert client.put(f"{NATIVE}/billing-service/labels/team-billing").status_code == 201
    assert client.put(f"{NATIVE}/billing-service/labels/team-billing").status_code == 200
    created = client.put(f"{BASE}/pacticipants/billing-service/labels/tier/1")
    assert created.status_code == 201, created.text
    assert created.headers["location"].endswith("/pacticipants/billing-service/labels/tier%2F1")
    assert created.json()["_links"]["pacticipant"]["name"] == "Billing Service"
    assert client.put(f"{BASE}/pacticipants/billing-service/labels/tier/1").status_code == 200
    assert client.put(f"{NATIVE}/billing-service/labels/%20padded").status_code == 400

    labels = client.get(f"{BASE}/labels").json()
    assert [label["name"] for label in labels["_embedded"]["labels"]] == ["team-billing", "tier/1"]
    assert [row["name"] for row in client.get("/v1/tenants/t/pacticipant-labels").json()["labels"]] == [
        "team-billing",
        "tier/1",
    ]
    with_label = client.get(f"{BASE}/pacticipants/label/team-billing").json()
    (document,) = with_label["_embedded"]["pacticipants"]
    assert [label["name"] for label in document["_embedded"]["labels"]] == ["team-billing", "tier/1"]
    assert document["_links"]["pb:label"]["templated"] is True
    assert client.get(f"{BASE}/pacticipants/label/nobody").json()["_embedded"]["pacticipants"] == []
    assert [p["slug"] for p in client.get(NATIVE, params={"label": "team-billing"}).json()["pacticipants"]] == [
        "billing-service"
    ]
    assert client.get(f"{BASE}/pacticipants/billing-service").json()["_embedded"]["labels"][0]["name"] == "team-billing"

    assert client.delete(f"{BASE}/pacticipants/billing-service/labels/team-billing").status_code == 204
    assert client.get(f"{BASE}/pacticipants/billing-service/labels/team-billing").status_code == 404
    assert client.delete(f"{NATIVE}/billing-service/labels/team-billing").status_code == 404
    assert len(_audits(cleanup, "pacts.label.add")) == 2
    assert len(_audits(cleanup, "pacts.label.remove")) == 1

    # A deleted pacticipant's labels are not the workspace's any more.
    assert client.delete(f"{NATIVE}/billing-service").status_code == 204
    assert client.get(f"{BASE}/labels").json()["_embedded"]["labels"] == []


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def history(cleanup: Dict[str, Any]) -> Dict[str, Any]:
    """main: 1.0.0 (deployed), 2.0.0, 3.0.0, 4.0.0, 5.0.0; feat/x: f-1 (between 3 and 4)."""
    environment_db._create_environment(cleanup, "production", production=True)
    for version, branch in (("1.0.0", "main"), ("2.0.0", "main"), ("3.0.0", "main"), ("f-1", "feat/x")):
        _publish(cleanup, version, branch=branch)
    for version in ("4.0.0", "5.0.0"):
        _publish(cleanup, version)
    matrix_db._deploy(cleanup, "billing-service", "1.0.0")
    return cleanup


def test_a_retention_run_is_dry_run_first_and_applies_exactly_its_plan(history: Dict[str, Any]) -> None:
    client = history["client"]
    body = {"keep": {"latest_per_branch": 2}, "pacticipants": ["billing-service"], "reason": "monthly cleanup"}
    dry = client.post(RETENTION, json=body)
    assert dry.status_code == 200, dry.text
    plan = dry.json()
    assert (plan["dry_run"], plan["applied"], plan["deleted"], plan["evaluated"]) == (True, False, 2, 6)
    (row,) = plan["pacticipants"]
    assert [deletion["number"] for deletion in row["deletions"]] == ["2.0.0", "3.0.0"]
    assert row["kept_by"] == {"latest": 1, "latest_per_branch": 2, "deployed_or_released": 1}
    assert len(_versions(history)) == 6  # Nothing changed.

    missing = client.post(RETENTION, json={**body, "dry_run": False})
    assert (missing.status_code, missing.json()["detail"]["code"]) == (422, "pact-retention-plan-digest-required")
    stale = client.post(RETENTION, json={**body, "dry_run": False, "plan_digest": "sha256:" + "0" * 64})
    assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "pact-retention-plan-changed")
    assert stale.json()["detail"]["plan"]["plan_digest"] == plan["plan_digest"]

    applied = client.post(RETENTION, json={**body, "dry_run": False, "plan_digest": plan["plan_digest"]})
    assert applied.status_code == 200, applied.text
    assert (applied.json()["applied"], applied.json()["deleted"]) == (True, 2)
    assert [v["number"] for v in _versions(history)] == ["5.0.0", "4.0.0", "f-1", "1.0.0"]
    assert {v["number"]: v["delete_cause"] for v in _versions(history, state="deleted")} == {
        "3.0.0": "retention",
        "2.0.0": "retention",
    }
    (audit,) = _audits(history, "pacts.retention.apply")
    assert audit["detail"]["deleted"] == 2 and audit["detail"]["pacticipants"] == {"billing-service": 2}
    # A retention deletion is restorable like any other.
    assert client.post(f"{NATIVE}/billing-service/versions/2.0.0/restore").status_code == 200


def test_a_plan_that_moved_since_the_dry_run_is_refused(history: Dict[str, Any]) -> None:
    client = history["client"]
    body = {"keep": {"latest_per_branch": 2}}
    plan = client.post(RETENTION, json=body).json()
    _publish(history, "6.0.0")  # 4.0.0 drops out of main's newest two.
    stale = client.post(RETENTION, json={**body, "dry_run": False, "plan_digest": plan["plan_digest"]})
    assert stale.status_code == 409
    assert stale.json()["detail"]["plan"]["deleted"] == plan["deleted"] + 1
    assert len(_versions(history)) == 7


def test_the_selectors_and_their_refusals(history: Dict[str, Any]) -> None:
    client = history["client"]
    recent = client.post(RETENTION, json={"keep": {"created_within_days": 7}}).json()
    assert recent["deleted"] == 0
    nothing_deployed = client.post(
        RETENTION, json={"keep": {"latest_per_branch": 1, "deployed_or_released": False}}
    ).json()
    (row,) = [r for r in nothing_deployed["pacticipants"] if r["slug"] == "billing-service"]
    assert [d["number"] for d in row["deletions"]] == ["1.0.0", "2.0.0", "3.0.0", "4.0.0"]
    none = client.post(RETENTION, json={"keep": {"deployed_or_released": False}})
    assert (none.status_code, none.json()["detail"]["code"]) == (422, "pact-retention-no-selector")
    unknown = client.post(RETENTION, json={"keep": {"latest_per_branch": 1}, "pacticipants": ["nobody"]})
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "pacticipant-not-found")
    assert client.post(RETENTION, json={"keep": {"latest_per_branch": 0}}).status_code == 422


# ---------------------------------------------------------------------------------------------
# Purge and the database's own rules
# ---------------------------------------------------------------------------------------------


def test_the_purge_waits_for_the_grace_period_and_keeps_heads_valid(cleanup: Dict[str, Any]) -> None:
    client, cursor = cleanup["client"], cleanup["cursor"]
    _publish(cleanup, "1.0.0")
    _publish(cleanup, "2.0.0")
    _publish(cleanup, "f-1", branch="feat/x")
    for number in ("2.0.0", "f-1"):
        assert client.delete(f"{NATIVE}/billing-service/versions/{number}").status_code == 204

    assert purge_deleted(cleanup["db"], now=_later(29))["versions"] == 0
    assert purge_deleted(cleanup["db"], now=_later(31))["versions"] >= 2
    cursor.execute(
        """
        SELECT v.number FROM apiome.pacticipant_version v
        JOIN apiome.pacticipant p ON p.id = v.pacticipant_id
        WHERE p.tenant_id = %s::uuid AND p.slug = 'billing-service'
        """,
        (cleanup["seed"]["tenant"],),
    )
    assert [row["number"] for row in cursor.fetchall()] == ["1.0.0"]
    assert _heads(cleanup) == {"main": "1.0.0"}
    cursor.execute(
        """
        SELECT b.name FROM apiome.pacticipant_branch b JOIN apiome.pacticipant p ON p.id = b.pacticipant_id
        WHERE p.tenant_id = %s::uuid
        """,
        (cleanup["seed"]["tenant"],),
    )
    assert [row["name"] for row in cursor.fetchall()] == ["main"]
    assert _audits(cleanup, "pacts.purge")[0]["detail"]["versions"] >= 2


def test_versions_still_never_change_except_their_deletion_stamp(cleanup: Dict[str, Any]) -> None:
    cursor = cleanup["cursor"]
    _publish(cleanup, "1.0.0")
    version_id = _versions(cleanup)[0]["id"]
    with _refused(cursor, psycopg2.errors.RestrictViolation):
        cursor.execute("UPDATE apiome.pacticipant_version SET number = '1.0.1' WHERE id = %s::uuid", (version_id,))
    with _refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            "UPDATE apiome.pacticipant_version SET deleted_at = now() WHERE id = %s::uuid", (version_id,)
        )  # A stamp needs its cause.
    cursor.execute(
        "UPDATE apiome.pacticipant_version SET deleted_at = now(), delete_cause = 'version' WHERE id = %s::uuid",
        (version_id,),
    )
    with _refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            "UPDATE apiome.pacticipant_version SET delete_cause = 'whim' WHERE id = %s::uuid", (version_id,)
        )
