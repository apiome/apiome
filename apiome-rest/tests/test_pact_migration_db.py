"""Importing a Pact Broker / PactFlow workspace against a live Postgres — PFX-6.7 (#6959).

What only the real schema proves:

* a whole workspace — pacticipants with labels, versions on branches with tags, a pact, a
  verification result, an environment, a deployment, a release, a webhook — imports in one batch,
  every row keeping the source's ``created_at`` (and the result its source number);
* the imported data reads back through the Pact Broker routes (the pact, the branch head);
* importing again changes nothing; a record that adds a branch or a tag is ``updated``;
* a different pact for an imported consumer version, a deployment where another version is
  deployed, a result whose pact is missing and a deployment whose environment is missing are each
  ``refused`` with the reason — and the rest of the batch is still written;
* a check (dry run) writes nothing and says what exists;
* nothing crosses a tenant: a webhook uuid another workspace uses is given a new one.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of ``test_pact_publication_db``).
Skipped when no database is reachable or V435/V436 are not applied.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest

from app.config import settings
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

IMPORT = "/v1/tenants/t/pact-migration/import"
CHECK = "/v1/tenants/t/pact-migration/check"
WEBHOOK_UUID = "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


@pytest.fixture
def migration(stack: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """The publication stack with the migration routes on its transaction."""
    stack["cursor"].execute(
        "SELECT to_regclass('apiome.pact_webhook') AS w, to_regclass('apiome.deployed_version') AS d"
    )
    row = stack["cursor"].fetchone()
    if not row["w"] or not row["d"]:
        pytest.skip("V435/V436 not applied")
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    monkeypatch.setattr("app.pact_webhook.validate_host", lambda _host: None)
    with (
        patch("app.pact_migration_routes.db", stack["db"]),
        patch("app.pact_migration_routes.enforce_permission", return_value=None),
    ):
        yield stack


def _at(day: int, hour: int = 9) -> str:
    """A fixed source timestamp in March 2025."""
    return f"2025-03-{day:02d}T{hour:02d}:00:00Z"


def _when(day: int, hour: int = 9) -> datetime:
    return datetime(2025, 3, day, hour, tzinfo=timezone.utc)


def _workspace() -> List[Dict[str, Any]]:
    """A small source workspace, in the order ``apiome pact migrate`` sends it."""
    return [
        {
            "kind": "pacticipant",
            "name": "Billing Service",
            "repository_url": "https://github.com/acme/billing",
            "main_branch": "main",
            "labels": ["team-billing"],
            "created_at": _at(1),
        },
        {"kind": "pacticipant", "name": "Ledger API", "created_at": _at(1, 10)},
        {
            "kind": "environment",
            "name": "production",
            "display_name": "Production",
            "production": True,
            "created_at": _at(1, 11),
        },
        {
            "kind": "version",
            "pacticipant": "Billing Service",
            "number": "1.0.0",
            "build_url": "https://ci.example.com/builds/1",
            "branches": ["main"],
            "tags": [{"name": "prod", "created_at": _at(4)}],
            "created_at": _at(2),
        },
        {"kind": "version", "pacticipant": "Ledger API", "number": "7.0.0", "branches": ["main"], "created_at": _at(3)},
        {
            "kind": "pact",
            "consumer": "Billing Service",
            "provider": "Ledger API",
            "consumer_version": "1.0.0",
            "content": publication_db._pact(),
            "created_at": _at(2, 10),
        },
        {
            "kind": "verification",
            "consumer": "Billing Service",
            "provider": "Ledger API",
            "consumer_version": "1.0.0",
            "number": 3,
            "result": {
                "success": True,
                "providerApplicationVersion": "7.0.0",
                "buildUrl": "https://ci.example.com/v/3",
            },
            "created_at": _at(3, 10),
        },
        {
            "kind": "deployment",
            "pacticipant": "Ledger API",
            "version": "7.0.0",
            "environment": "production",
            "created_at": _at(5),
        },
        {
            "kind": "release",
            "pacticipant": "Billing Service",
            "version": "1.0.0",
            "environment": "production",
            "created_at": _at(5, 10),
        },
        {
            "kind": "webhook",
            "uuid": WEBHOOK_UUID,
            "created_at": _at(6),
            "webhook": {
                "description": "Tell CI",
                "events": [{"name": "contract_content_changed"}],
                "request": {
                    "method": "POST",
                    "url": "https://ci.example.com/hooks/pact",
                    "body": {"pact": "${pactbroker.pactUrl}"},
                },
                "provider": {"name": "Ledger API"},
            },
        },
    ]


def _post(stack: Dict[str, Any], path: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    response = stack["client"].post(path, json={"source": "https://broker.example.com", "records": records})
    assert response.status_code == 200, response.text
    return response.json()


def _one(stack: Dict[str, Any], query: str, *params: Any) -> Dict[str, Any]:
    stack["cursor"].execute(query, params)
    row = stack["cursor"].fetchone()
    assert row is not None, query
    return dict(row)


def test_a_workspace_imports_keeping_the_source_times(migration: Dict[str, Any]) -> None:
    report = _post(migration, IMPORT, _workspace())
    assert report["dry_run"] is False
    assert [r["outcome"] for r in report["results"]] == ["created"] * 10, report["results"]
    assert report["counts"] == {"created": 10}
    tenant = migration["seed"]["tenant"]

    billing = _one(
        migration,
        "SELECT id, created_at, repository_url, main_branch FROM apiome.pacticipant WHERE tenant_id = %s AND slug = %s",
        tenant,
        "billing-service",
    )
    assert billing["created_at"] == _when(1)
    assert billing["main_branch"] == "main" and billing["repository_url"] == "https://github.com/acme/billing"
    label = _one(migration, "SELECT created_at FROM apiome.pacticipant_label WHERE pacticipant_id = %s", billing["id"])
    assert label["created_at"] == _when(1)

    version = _one(
        migration,
        "SELECT id, created_at, build_url FROM apiome.pacticipant_version"
        " WHERE pacticipant_id = %s AND number = '1.0.0'",
        billing["id"],
    )
    assert version["created_at"] == _when(2)
    tag = _one(migration, "SELECT created_at FROM apiome.pacticipant_version_tag WHERE version_id = %s", version["id"])
    assert tag["created_at"] == _when(4)
    branch = _one(
        migration, "SELECT created_at FROM apiome.pacticipant_branch WHERE pacticipant_id = %s", billing["id"]
    )
    assert branch["created_at"] == _when(2)

    publication = _one(
        migration, "SELECT created_at FROM apiome.pact_publication WHERE consumer_version_id = %s", version["id"]
    )
    assert publication["created_at"] == _when(2, 10)
    result = _one(
        migration,
        "SELECT number, success, created_at FROM apiome.verification_result WHERE tenant_id = %s",
        tenant,
    )
    assert (result["number"], result["success"], result["created_at"]) == (3, True, _when(3, 10))
    environment = _one(migration, "SELECT created_at FROM apiome.pact_environment WHERE tenant_id = %s", tenant)
    assert environment["created_at"] == _when(1, 11)
    deployed = _one(
        migration, "SELECT created_at, currently_deployed FROM apiome.deployed_version WHERE tenant_id = %s", tenant
    )
    assert deployed == {"created_at": _when(5), "currently_deployed": True}
    released = _one(migration, "SELECT created_at FROM apiome.released_version WHERE tenant_id = %s", tenant)
    assert released["created_at"] == _when(5, 10)
    webhook = _one(migration, "SELECT id::text AS id, created_at FROM apiome.pact_webhook WHERE tenant_id = %s", tenant)
    assert webhook == {"id": WEBHOOK_UUID, "created_at": _when(6)}

    # The imported pact reads back through the Pact Broker routes.
    read = migration["client"].get(f"{publication_db.PAIR}/version/1.0.0")
    assert read.status_code == 200, read.text
    assert read.json()["interactions"] == publication_db._pact()["interactions"]


def test_importing_again_changes_nothing(migration: Dict[str, Any]) -> None:
    _post(migration, IMPORT, _workspace())
    again = _post(migration, IMPORT, _workspace())
    assert again["counts"] == {"unchanged": 10}, again["results"]


def test_a_new_branch_or_tag_on_an_imported_version_is_an_update(migration: Dict[str, Any]) -> None:
    records = _workspace()
    _post(migration, IMPORT, records[:5])
    more = dict(records[3], branches=["main", "release-1"], tags=["prod", "audited"])
    report = _post(migration, IMPORT, [more])
    assert report["results"][0]["outcome"] == "updated"
    versions = migration["client"].get("/v1/tenants/t/pacticipants/billing-service/versions").json()["versions"]
    assert sorted(versions[0]["branches"]) == ["main", "release-1"]
    assert sorted(versions[0]["tags"]) == ["audited", "prod"]


def test_the_branch_head_is_the_newest_imported_version(migration: Dict[str, Any]) -> None:
    records = [
        {"kind": "version", "pacticipant": "Ledger API", "number": number, "branches": ["main"], "created_at": _at(day)}
        for number, day in (("1.0.0", 1), ("1.1.0", 2), ("2.0.0", 3))
    ]
    _post(migration, IMPORT, records)
    branches = migration["client"].get("/v1/tenants/t/pacticipants/ledger-api/branches").json()
    head = branches["branches"][0]
    assert head["name"] == "main"
    assert head["head_version"] == "2.0.0", head


def test_refusals_carry_the_reason_and_the_rest_is_written(migration: Dict[str, Any]) -> None:
    records = _workspace()
    _post(migration, IMPORT, records)
    changed_pact = dict(records[5], content=publication_db._pact(total=1))
    orphan_result = dict(records[6], consumer_version="9.9.9")
    unknown_environment = dict(records[7], environment="staging")
    other_deployment = {"kind": "version", "pacticipant": "Ledger API", "number": "8.0.0", "created_at": _at(7)}
    conflicting = dict(records[7], version="8.0.0")
    bad = {"kind": "version", "pacticipant": "Ledger API", "number": "  ", "created_at": _at(7)}
    report = _post(
        migration,
        IMPORT,
        [changed_pact, orphan_result, unknown_environment, other_deployment, conflicting, bad, {"kind": "team"}],
    )
    by_index = {r["index"]: r for r in report["results"]}
    assert by_index[0]["outcome"] == "refused" and by_index[0]["code"] == "pact-migration-conflict"
    assert by_index[1]["code"] == "pact-migration-reference-missing"
    assert "import the pact before" in by_index[1]["message"]
    assert by_index[2]["code"] == "pact-migration-reference-missing" and "staging" in by_index[2]["message"]
    assert by_index[3]["outcome"] == "created"
    assert by_index[4]["code"] == "pact-migration-conflict"
    assert by_index[5]["outcome"] == "refused" and by_index[5]["message"].startswith("/records/5/number")
    assert by_index[6]["message"].startswith("/records/6/kind")
    # The imported pact was not replaced, and 7.0.0 is still what is deployed.
    read = migration["client"].get(f"{publication_db.PAIR}/version/1.0.0").json()
    assert read["interactions"] == publication_db._pact()["interactions"]
    deployed = _one(
        migration,
        "SELECT count(*) AS n FROM apiome.deployed_version WHERE tenant_id = %s AND currently_deployed",
        migration["seed"]["tenant"],
    )
    assert deployed["n"] == 1


def test_a_colliding_result_number_is_refused_not_reported_as_imported(migration: Dict[str, Any]) -> None:
    records = _workspace()
    _post(migration, IMPORT, records[:7])
    other_result = dict(records[6], result={"success": False, "providerApplicationVersion": "7.0.0"})
    report = _post(migration, IMPORT, [other_result])
    assert report["results"][0]["code"] == "pact-migration-conflict"
    assert "already recorded" in report["results"][0]["message"]


def test_a_check_writes_nothing_and_says_what_exists(migration: Dict[str, Any]) -> None:
    records = _workspace()
    first = _post(migration, CHECK, records)
    assert first["dry_run"] is True
    assert first["counts"] == {"would-create": 10}, first["results"]
    tenant = migration["seed"]["tenant"]
    assert _one(migration, "SELECT count(*) AS n FROM apiome.pacticipant WHERE tenant_id = %s", tenant)["n"] == 0

    _post(migration, IMPORT, records[:4])
    second = _post(migration, CHECK, records)
    assert [r["outcome"] for r in second["results"]] == ["exists"] * 4 + ["would-create"] * 6


def test_nothing_crosses_a_tenant(migration: Dict[str, Any]) -> None:
    other = migration["other"]["tenant"]
    migration["cursor"].execute(
        """
        INSERT INTO apiome.pact_webhook (id, tenant_id, events, request_method, request_url)
        VALUES (%s::uuid, %s::uuid, ARRAY['contract_published'], 'POST', 'https://elsewhere.example.com/hook')
        """,
        (WEBHOOK_UUID, other),
    )
    migration["cursor"].execute(
        "INSERT INTO apiome.pacticipant (tenant_id, slug, name)"
        " VALUES (%s::uuid, 'billing-service', 'Billing Service')",
        (other,),
    )
    report = _post(migration, IMPORT, _workspace())
    assert report["results"][0]["outcome"] == "created"  # the other tenant's handle is not this one's
    webhook = report["results"][-1]
    assert webhook["outcome"] == "created" and "another workspace uses the uuid" in webhook["note"]
    rows = _one(
        migration,
        "SELECT count(*) AS n FROM apiome.pact_webhook WHERE id = %s::uuid AND tenant_id = %s::uuid",
        WEBHOOK_UUID,
        other,
    )
    assert rows["n"] == 1
    other_versions = _one(
        migration,
        "SELECT count(*) AS n FROM apiome.pacticipant_version v JOIN apiome.pacticipant p ON p.id = v.pacticipant_id "
        "WHERE p.tenant_id = %s",
        other,
    )
    assert other_versions["n"] == 0
