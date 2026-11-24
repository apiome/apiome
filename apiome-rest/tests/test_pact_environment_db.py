"""Environments and deployment recording against a live Postgres — PFX-1.5 (#6918).

What only the real schema and the real routes prove (apiome-db V435). Each flow follows the links
exactly as the ``pact-broker`` CLI (pact_broker-client) does, so it works unmodified:

* ``create-environment`` posts to the index's ``pb:environments``; ``list-environments`` reads it;
* ``record-deployment`` reads the version through ``pb:pacticipant-version`` and posts to its
  ``pb:record-deployment`` link named after the environment;
* recording a deployment marks the previous one (same application instance) undeployed, keeps it
  as history, and leaves other instances deployed;
* ``record-undeployment`` finds the environment through ``pb:environments``, reads
  ``pb:currently-deployed-deployed-versions?pacticipant=…`` and patches each match's ``self``;
* ``record-release`` / ``record-support-ended`` the same way for releases; releasing again
  supports again;
* the for-verification ``deployed`` selector returns what is deployed;
* history rows refuse any other change; nothing crosses a tenant; names are unique per tenant.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V435 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import patch

import psycopg2
import pytest

from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE


@pytest.fixture
def broker(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The publication stack, with the environment routes on the same transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.deployed_version') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V435 not applied")
    with (
        patch("app.pact_broker_environment_routes.db", stack["db"]),
        patch("app.pact_broker_environment_routes.enforce_permission", return_value=None),
    ):
        yield stack


@pytest.fixture
def published(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Service 1.0.0 and 2.0.0 on main published their pacts for Ledger API."""
    for version in ("1.0.0", "2.0.0"):
        response = broker["client"].post(
            f"{BASE}/contracts/publish", json=publication_db._bulk(version, publication_db._pact(), branch="main")
        )
        assert response.status_code == 200, response.text
    return broker


def _path(href: str) -> str:
    """The path of an absolute link, for the test client."""
    return href[href.index("/v1/") :]


def _index(stack: Dict[str, Any]) -> Dict[str, Any]:
    return stack["client"].get(BASE).json()["_links"]


def _create_environment(stack: Dict[str, Any], name: str, production: bool = False) -> Dict[str, Any]:
    """``pact-broker create-environment --name <name> [--production]``."""
    response = stack["client"].post(
        _path(_index(stack)["pb:environments"]["href"]),
        json={"name": name, "displayName": name.title(), "production": production},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _record(
    stack: Dict[str, Any], rel: str, pacticipant: str, version: str, environment: str, instance: Optional[str] = None
) -> Any:
    """``pact-broker record-deployment`` / ``record-release``: follow the version's named link."""
    template = _index(stack)["pb:pacticipant-version"]["href"]
    version_doc = stack["client"].get(_path(template.replace("{pacticipant}", pacticipant).replace("{version}", version)))
    assert version_doc.status_code == 200, version_doc.text
    links = [link for link in version_doc.json()["_links"][rel] if link["name"] == environment]
    assert len(links) == 1, version_doc.json()["_links"][rel]
    body = {"applicationInstance": instance, "target": instance} if instance else {}
    return stack["client"].post(_path(links[0]["href"]), json=body)


def _environment_resource(stack: Dict[str, Any], name: str) -> Dict[str, Any]:
    """What the CLI does to find an environment: ``pb:environments`` → the link named ``name``."""
    listing = stack["client"].get(_path(_index(stack)["pb:environments"]["href"])).json()
    link = next(link for link in listing["_links"]["pb:environments"] if link["name"] == name)
    return stack["client"].get(_path(link["href"])).json()


def _undeploy(stack: Dict[str, Any], pacticipant: str, environment: str, instance: Optional[str] = None) -> List[Any]:
    """``pact-broker record-undeployment``: read the current deployments, patch each match."""
    env = _environment_resource(stack, environment)
    current = stack["client"].get(
        _path(env["_links"]["pb:currently-deployed-deployed-versions"]["href"]), params={"pacticipant": pacticipant}
    )
    assert current.status_code == 200, current.text
    matches = [e for e in current.json()["_embedded"]["deployedVersions"] if e["applicationInstance"] == instance]
    return [
        stack["client"].patch(
            _path(entry["_links"]["self"]["href"]),
            content=b'{"currentlyDeployed": false}',
            headers={"Content-Type": "application/merge-patch+json"},
        )
        for entry in matches
    ]


def _rows(stack: Dict[str, Any], table: str) -> List[Dict[str, Any]]:
    stack["cursor"].execute(
        f"SELECT * FROM apiome.{table} WHERE tenant_id = %s::uuid ORDER BY seq", (stack["seed"]["tenant"],)
    )
    return [dict(row) for row in stack["cursor"].fetchall()]


def test_create_and_list_environments_like_the_cli(broker: Dict[str, Any]) -> None:
    created = _create_environment(broker, "production", production=True)
    assert (created["name"], created["displayName"], created["production"]) == ("production", "Production", True)
    assert created["contractRequired"] is False
    listing = broker["client"].get(f"{BASE}/environments").json()
    assert [e["uuid"] for e in listing["_embedded"]["environments"]] == [created["uuid"]]
    template = _index(broker)["pb:environment"]["href"]
    described = broker["client"].get(_path(template.replace("{uuid}", created["uuid"])))
    assert described.json()["name"] == "production"
    # Names are unique per workspace, not across workspaces.
    again = broker["client"].post(f"{BASE}/environments", json={"name": "production"})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "pact-environment-name-taken")


def test_a_deployment_replaces_the_previous_one_and_keeps_history(published: Dict[str, Any]) -> None:
    _create_environment(published, "production", production=True)
    first = _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production")
    assert first.status_code == 201, first.text
    assert first.json()["currentlyDeployed"] is True
    second = _record(published, "pb:record-deployment", "Billing Service", "2.0.0", "production")
    assert second.status_code == 201, second.text

    rows = _rows(published, "deployed_version")
    assert [row["currently_deployed"] for row in rows] == [False, True]
    assert rows[0]["undeployed_at"] is not None
    old = published["client"].get(_path(first.json()["_links"]["self"]["href"])).json()
    assert (old["currentlyDeployed"], old["_embedded"]["version"]["number"]) == (False, "1.0.0")

    # Recording the current version again changes nothing.
    again = _record(published, "pb:record-deployment", "Billing Service", "2.0.0", "production")
    assert (again.status_code, again.json()["uuid"]) == (200, second.json()["uuid"])
    assert len(_rows(published, "deployed_version")) == 2


def test_application_instances_are_deployed_independently(published: Dict[str, Any]) -> None:
    _create_environment(published, "production", production=True)
    assert _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production", "eu-1").status_code == 201
    assert _record(published, "pb:record-deployment", "Billing Service", "2.0.0", "production", "us-1").status_code == 201
    assert [row["currently_deployed"] for row in _rows(published, "deployed_version")] == [True, True]

    env = _environment_resource(published, "production")
    url = _path(env["_links"]["pb:currently-deployed-deployed-versions"]["href"])
    only_eu = published["client"].get(url, params={"pacticipant": "Billing Service", "applicationInstance": "eu-1"})
    assert [e["applicationInstance"] for e in only_eu.json()["_embedded"]["deployedVersions"]] == ["eu-1"]
    unnamed = published["client"].get(url, params={"applicationInstance": ""})
    assert unnamed.json()["_embedded"]["deployedVersions"] == []

    patched = _undeploy(published, "Billing Service", "production", "eu-1")
    assert [p.status_code for p in patched] == [200]
    assert patched[0].json()["currentlyDeployed"] is False
    rows = _rows(published, "deployed_version")
    assert [(row["application_instance"], row["currently_deployed"]) for row in rows] == [
        ("eu-1", False),
        ("us-1", True),
    ]
    # Nothing left to undeploy on that instance: the CLI reports it, nothing changes.
    assert _undeploy(published, "Billing Service", "production", "eu-1") == []


def test_the_deployed_selector_returns_what_runs_in_production(published: Dict[str, Any]) -> None:
    _create_environment(published, "production", production=True)
    _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production")
    response = published["client"].post(
        f"{BASE}/pacts/provider/ledger-api/for-verification",
        json={"consumerVersionSelectors": [{"deployed": True, "environment": "production"}]},
    )
    assert response.status_code == 200, response.text
    pacts = response.json()["_embedded"]["pacts"]
    assert len(pacts) == 1
    assert pacts[0]["shortDescription"] == "deployed to production"
    _undeploy(published, "Billing Service", "production")
    after = published["client"].post(
        f"{BASE}/pacts/provider/ledger-api/for-verification",
        json={"consumerVersionSelectors": [{"deployed": True}]},
    )
    assert after.json()["_embedded"]["pacts"] == []


def test_releases_stay_supported_until_support_ends(published: Dict[str, Any]) -> None:
    _create_environment(published, "app-store", production=True)
    one = _record(published, "pb:record-release", "Billing Service", "1.0.0", "app-store")
    two = _record(published, "pb:record-release", "Billing Service", "2.0.0", "app-store")
    assert (one.status_code, two.status_code) == (201, 201)
    assert [row["currently_supported"] for row in _rows(published, "released_version")] == [True, True]

    # `pact-broker record-support-ended --version 1.0.0`.
    env = _environment_resource(published, "app-store")
    supported = published["client"].get(
        _path(env["_links"]["pb:currently-supported-released-versions"]["href"]),
        params={"pacticipant": "Billing Service", "version": "1.0.0"},
    )
    entries = supported.json()["_embedded"]["releasedVersions"]
    assert [e["_embedded"]["version"]["number"] for e in entries] == ["1.0.0"]
    ended = published["client"].patch(_path(entries[0]["_links"]["self"]["href"]), json={"currentlySupported": False})
    assert ended.status_code == 200
    assert ended.json()["currentlySupported"] is False
    assert [row["currently_supported"] for row in _rows(published, "released_version")] == [False, True]

    # Releasing it again supports it again: one row per version and environment.
    again = _record(published, "pb:record-release", "Billing Service", "1.0.0", "app-store")
    assert (again.status_code, again.json()["currentlySupported"]) == (200, True)
    assert len(_rows(published, "released_version")) == 2


def test_recording_needs_a_recorded_version(published: Dict[str, Any]) -> None:
    env = _create_environment(published, "production")
    response = published["client"].post(
        f"{BASE}/pacticipants/billing-service/versions/9.9.9/deployed-versions/environment/{env['uuid']}", json={}
    )
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "pacticipant-version-not-found")


def test_history_rows_refuse_any_other_change(published: Dict[str, Any]) -> None:
    _create_environment(published, "production")
    _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production")
    _undeploy(published, "Billing Service", "production")
    cursor = published["cursor"]
    cursor.execute("SAVEPOINT revive")
    with pytest.raises(psycopg2.Error) as caught:
        cursor.execute(
            "UPDATE apiome.deployed_version SET currently_deployed = TRUE, undeployed_at = NULL"
            " WHERE tenant_id = %s::uuid",
            (published["seed"]["tenant"],),
        )
    assert "can only be marked undeployed" in str(caught.value)
    cursor.execute("ROLLBACK TO SAVEPOINT revive")


def test_nothing_crosses_a_tenant(published: Dict[str, Any]) -> None:
    env = _create_environment(published, "production")
    deployed = _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production").json()
    other = {"tenant_id": published["other"]["tenant"], "user_id": None, "auth_method": "jwt"}
    from app.main import app
    from app.pact_broker_auth import validate_broker_authentication

    app.dependency_overrides[validate_broker_authentication] = lambda: other
    client = published["client"]
    assert client.get(f"{BASE}/environments").json()["_embedded"]["environments"] == []
    assert client.get(f"{BASE}/environments/{env['uuid']}").status_code == 404
    assert client.get(_path(deployed["_links"]["self"]["href"])).status_code == 404
    assert client.patch(_path(deployed["_links"]["self"]["href"]), json={"currentlyDeployed": False}).status_code == 404
    # The same name is free in another workspace.
    assert client.post(f"{BASE}/environments", json={"name": "production"}).status_code == 201


def test_deleting_an_environment_deletes_what_was_recorded_to_it(published: Dict[str, Any]) -> None:
    env = _create_environment(published, "production")
    _record(published, "pb:record-deployment", "Billing Service", "1.0.0", "production")
    _record(published, "pb:record-release", "Billing Service", "1.0.0", "production")
    assert published["client"].delete(f"{BASE}/environments/{env['uuid']}").status_code == 204
    assert _rows(published, "deployed_version") == []
    assert _rows(published, "released_version") == []
