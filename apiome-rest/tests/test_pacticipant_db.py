"""The pacticipant registry against a live Postgres — PFX-1.1 (#6914).

The acceptance criteria only the real schema and the real routes can prove (apiome-db V432):

* create, list, read and delete pacticipants, with names unique per tenant;
* versions are immutable — a repeat is answered with the stored row, and an UPDATE is refused;
* a branch head moves forward only, and only when a version is recorded;
* tags and branch membership are idempotent;
* deleting a project, softly or for good, keeps its pacticipant and clears the binding;
* nothing crosses a tenant: not a read, not a binding, not a branch or a tag;
* the ``pacts`` grants of the four built-in roles.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``). Skipped when no database is reachable or V432 is not applied.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.pact_cleanup_store import purge_deleted
from app.pacticipant import PacticipantInput, PacticipantVersionInput
from app.pacticipant_store import create_pacticipant, get_pacticipant, record_version
from tests import test_usage_index_db as index_db

tx = index_db.tx

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")


@pytest.fixture
def stack(tx: Tuple[Any, Any]) -> Iterator[Dict[str, Any]]:
    """Two tenants (each with a project) and a client whose routes run on ``tx`` as the first."""
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.pacticipant') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V432 not applied")
    seed = index_db._tenant(cursor)
    other = index_db._tenant(cursor)
    auth = {"tenant_id": seed["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_authentication] = lambda: auth
    with patch("app.pacticipant_routes.db", db), patch(
        "app.pacticipant_routes.enforce_permission", return_value=None
    ):
        yield {
            "db": db,
            "cursor": cursor,
            "seed": seed,
            "other": other,
            "auth": auth,
            "client": TestClient(app),
            "base": "/v1/tenants/t/pacticipants",
        }
    app.dependency_overrides.clear()


@contextmanager
def _refused(cursor: Any, error: type) -> Iterator[None]:
    """Expect ``error`` from the statements inside, without losing the test's transaction."""
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(error):
        yield
    cursor.execute("ROLLBACK TO SAVEPOINT refused")


def _register(stack: Dict[str, Any], **body: Any) -> Dict[str, Any]:
    response = stack["client"].post(stack["base"], json={"name": "Billing Service", **body})
    assert response.status_code == 201, response.text
    return response.json()


def _record(stack: Dict[str, Any], number: str, slug: str = "billing-service", **body: Any) -> Any:
    return stack["client"].put(f"{stack['base']}/{slug}/versions/{number}", json=body)


def _branches(stack: Dict[str, Any], slug: str = "billing-service") -> Dict[str, Dict[str, Any]]:
    response = stack["client"].get(f"{stack['base']}/{slug}/branches")
    assert response.status_code == 200, response.text
    return {branch["name"]: branch for branch in response.json()["branches"]}


def _count(cursor: Any, table: str, pacticipant_id: str) -> int:
    cursor.execute(f"SELECT count(*) AS n FROM apiome.{table} WHERE pacticipant_id = %s", (pacticipant_id,))
    return cursor.fetchone()["n"]


# ---------------------------------------------------------------------------------------------
# Pacticipants
# ---------------------------------------------------------------------------------------------


def test_create_list_read_update_and_delete(stack: Dict[str, Any]) -> None:
    client, base = stack["client"], stack["base"]
    created = _register(stack, repository_url="https://github.com/example/billing", main_branch="main")
    assert created["slug"] == "billing-service" and created["tenant_id"] == stack["seed"]["tenant"]
    _register(stack, name="Accounts", slug="accounts")

    listed = client.get(base).json()
    assert [row["slug"] for row in listed["pacticipants"]] == ["accounts", "billing-service"]
    assert listed["has_more"] is False

    first = client.get(base, params={"limit": 1}).json()
    assert first["has_more"] is True and [row["slug"] for row in first["pacticipants"]] == ["accounts"]
    second = client.get(base, params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert [row["slug"] for row in second["pacticipants"]] == ["billing-service"] and not second["has_more"]

    # By handle, by id, and by the name a Pact file carries.
    for ref in ("billing-service", created["id"], "Billing Service"):
        assert client.get(f"{base}/{ref}").json()["id"] == created["id"]

    patched = client.patch(f"{base}/billing-service", json={"name": "Billing", "repository_url": None})
    assert patched.status_code == 200, patched.text
    assert (patched.json()["name"], patched.json()["repository_url"], patched.json()["main_branch"]) == (
        "Billing",
        None,
        "main",
    )
    assert patched.json()["slug"] == "billing-service"

    assert client.delete(f"{base}/billing-service").status_code == 204
    assert client.get(f"{base}/billing-service").status_code == 404
    assert client.delete(f"{base}/billing-service").status_code == 404


def test_deleting_a_pacticipant_hides_it_and_the_purge_removes_its_history(stack: Dict[str, Any]) -> None:
    created = _register(stack)
    assert _record(stack, "1.0.0", branch="main", tags=["prod"]).status_code == 201
    assert _record(stack, "1.1.0", branch="main").status_code == 201
    assert stack["client"].delete(f"{stack['base']}/billing-service").status_code == 204
    # Soft (PFX-1.11): gone from every read, kept until the grace period has passed.
    assert stack["client"].get(f"{stack['base']}/billing-service").status_code == 404
    assert _count(stack["cursor"], "pacticipant_version", created["id"]) == 2
    purge_deleted(stack["db"], now=datetime.now(timezone.utc) + timedelta(days=365))
    for table in ("pacticipant_version", "pacticipant_branch", "pacticipant_branch_version", "pacticipant_version_tag"):
        assert _count(stack["cursor"], table, created["id"]) == 0


def test_a_name_is_unique_per_tenant_not_across_tenants(stack: Dict[str, Any]) -> None:
    db, cursor = stack["db"], stack["cursor"]
    _register(stack)
    # The same handle in another tenant is a different pacticipant.
    theirs = create_pacticipant(db, stack["other"]["tenant"], PacticipantInput(name="Billing Service"), actor=ACTOR)
    assert theirs.slug == "billing-service" and theirs.tenant_id == stack["other"]["tenant"]
    with _refused(cursor, psycopg2.errors.UniqueViolation):
        cursor.execute(
            "INSERT INTO apiome.pacticipant (tenant_id, slug, name) VALUES (%s, 'billing-service', 'Again')",
            (stack["seed"]["tenant"],),
        )
    with _refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO apiome.pacticipant (tenant_id, slug, name) VALUES (%s, 'Not A Slug', 'x')",
            (stack["seed"]["tenant"],),
        )


def test_another_tenants_pacticipant_cannot_be_read_or_written(stack: Dict[str, Any]) -> None:
    client, base = stack["client"], stack["base"]
    theirs = create_pacticipant(
        stack["db"], stack["other"]["tenant"], PacticipantInput(name="Their Service"), actor=ACTOR
    )
    record_version(stack["db"], theirs, "9.9.9", PacticipantVersionInput(branch="main"), actor=ACTOR)
    for ref in (theirs.slug, theirs.id):
        assert client.get(f"{base}/{ref}").status_code == 404
        assert client.get(f"{base}/{ref}/versions").status_code == 404
        assert client.get(f"{base}/{ref}/branches").status_code == 404
        assert client.put(f"{base}/{ref}/versions/1.0.0", json={}).status_code == 404
        assert client.patch(f"{base}/{ref}", json={"name": "Mine now"}).status_code == 404
        assert client.delete(f"{base}/{ref}").status_code == 404
    assert client.get(base).json()["pacticipants"] == []
    assert get_pacticipant(stack["db"], stack["other"]["tenant"], theirs.slug).name == "Their Service"


# ---------------------------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------------------------


def test_a_binding_cannot_cross_a_tenant(stack: Dict[str, Any]) -> None:
    cursor, seed, other = stack["cursor"], stack["seed"], stack["other"]
    refused = stack["client"].post(stack["base"], json={"name": "Billing Service", "project": other["project"]})
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "pacticipant-project-not-found"

    cursor.execute(
        """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
           VALUES (%s, %s, 'theirs', 'Theirs') RETURNING id::text AS id""",
        (other["tenant"], other["project"]),
    )
    their_consumer = cursor.fetchone()["id"]
    refused = stack["client"].post(stack["base"], json={"name": "Billing Service", "consumer_id": their_consumer})
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "pacticipant-consumer-not-found"

    # The database refuses it too, whatever the application does.
    for column, value in (("project_id", other["project"]), ("consumer_id", their_consumer)):
        with _refused(cursor, psycopg2.errors.ForeignKeyViolation):
            cursor.execute(
                f"INSERT INTO apiome.pacticipant (tenant_id, slug, name, {column}) VALUES (%s, 'crossing', 'x', %s)",
                (seed["tenant"], value),
            )


@pytest.mark.parametrize("how", ["soft", "hard"])
def test_deleting_a_project_keeps_the_pacticipant_and_clears_the_binding(stack: Dict[str, Any], how: str) -> None:
    cursor, seed = stack["cursor"], stack["seed"]
    created = _register(stack, project=seed["project"])
    assert created["project_id"] == seed["project"]
    _register(stack, name="Unbound")

    if how == "soft":
        assert stack["db"].delete_project(seed["project"], seed["tenant"]) is True
    else:
        cursor.execute("DELETE FROM apiome.usage_source WHERE project_id = %s", (seed["project"],))
        cursor.execute("DELETE FROM apiome.projects WHERE id = %s", (seed["project"],))
        assert cursor.rowcount == 1

    after = stack["client"].get(f"{stack['base']}/billing-service").json()
    assert after["id"] == created["id"] and after["project_id"] is None
    assert after["tenant_id"] == seed["tenant"]
    assert len(stack["client"].get(stack["base"]).json()["pacticipants"]) == 2


@pytest.mark.parametrize("how", ["retire", "delete"])
def test_retiring_or_deleting_a_consumer_clears_the_consumer_binding(stack: Dict[str, Any], how: str) -> None:
    cursor, seed = stack["cursor"], stack["seed"]
    cursor.execute(
        """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
           VALUES (%s, %s, 'billing', 'Billing') RETURNING id::text AS id""",
        (seed["tenant"], seed["project"]),
    )
    consumer = cursor.fetchone()["id"]
    created = _register(stack, consumer_id=consumer)
    assert created["consumer_id"] == consumer

    unbound = stack["client"].patch(f"{stack['base']}/billing-service", json={"consumer_id": None}).json()
    assert unbound["consumer_id"] is None
    rebound = stack["client"].patch(f"{stack['base']}/billing-service", json={"consumer_id": consumer}).json()
    assert rebound["consumer_id"] == consumer

    if how == "retire":
        assert stack["db"].soft_delete_consumer(consumer, seed["tenant"]) is True
    else:
        cursor.execute("DELETE FROM apiome.consumer WHERE id = %s", (consumer,))
    after = stack["client"].get(f"{stack['base']}/billing-service").json()
    assert after["id"] == created["id"] and after["consumer_id"] is None


# ---------------------------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------------------------


def test_a_version_is_created_once_and_never_changes(stack: Dict[str, Any]) -> None:
    cursor = stack["cursor"]
    _register(stack)
    first = _record(stack, "1.0.0", build_url="https://ci.example.com/builds/1")
    assert first.status_code == 201 and first.json()["created"] is True
    stored = first.json()["version"]

    again = _record(stack, "1.0.0", build_url="https://ci.example.com/builds/2", tags=["prod"])
    assert again.status_code == 200 and again.json()["created"] is False
    unchanged = again.json()["version"]
    assert unchanged["build_url"] == "https://ci.example.com/builds/1"
    assert {key: unchanged[key] for key in ("id", "number", "seq", "created_at", "actor_label")} == {
        key: stored[key] for key in ("id", "number", "seq", "created_at", "actor_label")
    }
    # The repeat added the tag without touching the version.
    assert unchanged["tags"] == ["prod"]

    for assignment in ("build_url = 'https://evil.example.com'", "number = '2.0.0'", "actor_label = 'x'"):
        with _refused(cursor, psycopg2.errors.RestrictViolation):
            cursor.execute(f"UPDATE apiome.pacticipant_version SET {assignment} WHERE id = %s", (stored["id"],))

    read = stack["client"].get(f"{stack['base']}/billing-service/versions/1.0.0").json()
    assert read["build_url"] == "https://ci.example.com/builds/1" and read["number"] == "1.0.0"
    assert stack["client"].get(f"{stack['base']}/billing-service/versions/0.0.1").status_code == 404


def test_removing_the_recording_user_is_the_one_update_a_version_allows(stack: Dict[str, Any]) -> None:
    cursor = stack["cursor"]
    created = _register(stack)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.pacticipant_version (pacticipant_id, number, created_by)
           VALUES (%s, '1.0.0', %s) RETURNING id::text AS id""",
        (created["id"], user),
    )
    version = cursor.fetchone()["id"]
    # What ON DELETE SET NULL does when that user is deleted.
    cursor.execute("UPDATE apiome.pacticipant_version SET created_by = NULL WHERE id = %s", (version,))
    assert cursor.rowcount == 1
    with _refused(cursor, psycopg2.errors.RestrictViolation):
        cursor.execute("UPDATE apiome.pacticipant_version SET created_by = %s WHERE id = %s", (user, version))


def test_versions_list_latest_first_and_filter_by_branch_and_tag(stack: Dict[str, Any]) -> None:
    client, base = stack["client"], stack["base"]
    _register(stack)
    _record(stack, "1.0.0", branch="main", tags=["prod"])
    _record(stack, "1.1.0", branch="feat/new-invoice")
    _record(stack, "1.2.0", branch="main")

    def numbers(**params: Any) -> list:
        response = client.get(f"{base}/billing-service/versions", params=params)
        assert response.status_code == 200, response.text
        return [version["number"] for version in response.json()["versions"]]

    assert numbers() == ["1.2.0", "1.1.0", "1.0.0"]
    assert numbers(branch="main") == ["1.2.0", "1.0.0"]
    assert numbers(branch="feat/new-invoice") == ["1.1.0"]
    assert numbers(tag="prod") == ["1.0.0"]
    assert numbers(tag="nope") == []

    page = client.get(f"{base}/billing-service/versions", params={"limit": 2}).json()
    assert page["has_more"] is True
    rest = client.get(f"{base}/billing-service/versions", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [version["number"] for version in rest["versions"]] == ["1.0.0"] and rest["has_more"] is False


# ---------------------------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------------------------


def test_a_branch_head_moves_forward_only(stack: Dict[str, Any]) -> None:
    _register(stack, main_branch="main")
    assert _record(stack, "1.0.0", branch="main").json()["head_moved"] is True
    assert _branches(stack)["main"]["head_version"] == "1.0.0"

    assert _record(stack, "1.1.0", branch="main").json()["head_moved"] is True
    assert _branches(stack)["main"]["head_version"] == "1.1.0"

    # Recording the older version again — a re-run of an old build — does not move the head back.
    replay = _record(stack, "1.0.0", branch="main").json()
    assert replay["created"] is False and replay["head_moved"] is False
    assert _branches(stack)["main"]["head_version"] == "1.1.0"

    # Nor does recording the head itself again.
    assert _record(stack, "1.1.0", branch="main").json()["head_moved"] is False

    # A version recorded earlier on another branch joins main without becoming its head …
    _record(stack, "0.9.0-hotfix", branch="hotfix")
    _record(stack, "1.2.0", branch="main")
    joined = _record(stack, "0.9.0-hotfix", branch="main").json()
    assert joined["head_moved"] is False and joined["version"]["branches"] == ["hotfix", "main"]
    branches = _branches(stack)
    assert branches["main"]["head_version"] == "1.2.0" and branches["main"]["is_main"] is True
    assert branches["hotfix"]["head_version"] == "0.9.0-hotfix" and branches["hotfix"]["is_main"] is False


def test_a_head_only_moves_when_a_version_is_recorded_on_the_branch(stack: Dict[str, Any]) -> None:
    _register(stack)
    _record(stack, "1.0.0", branch="main")
    # A version with no branch, a version on another branch, and a tag leave main where it was.
    _record(stack, "1.1.0")
    _record(stack, "1.2.0", branch="release")
    stack["client"].put(f"{stack['base']}/billing-service/versions/1.2.0/tags/main")
    assert _branches(stack)["main"]["head_version"] == "1.0.0"


def test_branch_membership_is_recorded_once(stack: Dict[str, Any]) -> None:
    created = _register(stack)
    for _ in range(3):
        assert _record(stack, "1.0.0", branch="main").json()["version"]["branches"] == ["main"]
    assert _count(stack["cursor"], "pacticipant_branch_version", created["id"]) == 1
    assert _count(stack["cursor"], "pacticipant_branch", created["id"]) == 1


def _main_branch(stack: Dict[str, Any], slug: str = "billing-service") -> Any:
    response = stack["client"].get(f"{stack['base']}/{slug}")
    assert response.status_code == 200, response.text
    return response.json()["main_branch"]


def test_the_first_candidate_branch_becomes_the_main_branch(stack: Dict[str, Any]) -> None:
    """The Pact Broker's ``auto_detect_main_branch`` (PFX-1.8, #6921)."""
    _register(stack)
    # A branch that is not a candidate leaves the main branch unset …
    _record(stack, "0.1.0", branch="feat/login")
    assert _main_branch(stack) is None
    # … the first candidate sets it …
    _record(stack, "1.0.0", branch="main")
    assert _main_branch(stack) == "main"
    # … and a later candidate does not replace it.
    _record(stack, "1.1.0", branch="develop")
    assert _main_branch(stack) == "main"


def test_a_main_branch_set_by_hand_is_never_replaced(stack: Dict[str, Any]) -> None:
    _register(stack, main_branch="trunk")
    _record(stack, "1.0.0", branch="master")
    assert _main_branch(stack) == "trunk"


def test_a_branch_and_a_tag_can_only_name_a_version_of_the_same_pacticipant(stack: Dict[str, Any]) -> None:
    cursor = stack["cursor"]
    billing = _register(stack)
    accounts = _register(stack, name="Accounts")
    billing_version = _record(stack, "1.0.0", branch="main").json()["version"]["id"]
    accounts_version = _record(stack, "7.0.0", slug="accounts", branch="main").json()["version"]["id"]
    cursor.execute("SELECT id::text AS id FROM apiome.pacticipant_branch WHERE pacticipant_id = %s", (billing["id"],))
    billing_branch = cursor.fetchone()["id"]

    with _refused(cursor, psycopg2.errors.ForeignKeyViolation):
        cursor.execute(
            "INSERT INTO apiome.pacticipant_branch_version (branch_id, pacticipant_id, version_id) VALUES (%s, %s, %s)",
            (billing_branch, billing["id"], accounts_version),
        )
    with _refused(cursor, psycopg2.errors.ForeignKeyViolation):
        cursor.execute(
            "UPDATE apiome.pacticipant_branch SET head_version_id = %s WHERE id = %s",
            (accounts_version, billing_branch),
        )
    with _refused(cursor, psycopg2.errors.ForeignKeyViolation):
        cursor.execute(
            "INSERT INTO apiome.pacticipant_version_tag (version_id, pacticipant_id, name) VALUES (%s, %s, 'prod')",
            (billing_version, accounts["id"]),
        )


# ---------------------------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------------------------


def test_tags_are_idempotent(stack: Dict[str, Any]) -> None:
    client, base = stack["client"], stack["base"]
    created = _register(stack)
    _record(stack, "1.0.0", tags=["prod", "prod"])
    for _ in range(3):
        tagged = client.put(f"{base}/billing-service/versions/1.0.0/tags/prod")
        assert tagged.status_code == 200 and tagged.json()["tags"] == ["prod"]
    assert _record(stack, "1.0.0", tags=["prod", "eu"]).json()["version"]["tags"] == ["eu", "prod"]
    assert _count(stack["cursor"], "pacticipant_version_tag", created["id"]) == 2

    # A tag may be a branch-like name; the version must exist.
    assert client.put(f"{base}/billing-service/versions/1.0.0/tags/feat/new-invoice").json()["tags"] == [
        "eu",
        "feat/new-invoice",
        "prod",
    ]
    missing = client.put(f"{base}/billing-service/versions/2.0.0/tags/prod")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "pacticipant-version-not-found"


# ---------------------------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------------------------


def test_builtin_roles_get_the_pacts_grants(stack: Dict[str, Any]) -> None:
    cursor, tenant = stack["cursor"], stack["seed"]["tenant"]
    cursor.execute("SELECT apiome.seed_builtin_roles(%s)", (tenant,))
    cursor.execute(
        """
        SELECT r.slug, array_agg(rp.action ORDER BY rp.action) AS actions
        FROM apiome.roles r JOIN apiome.role_permissions rp ON rp.role_id = r.id
        WHERE r.tenant_id = %s AND rp.resource = 'pacts'
        GROUP BY r.slug
        """,
        (tenant,),
    )
    grants = {row["slug"]: row["actions"] for row in cursor.fetchall()}
    assert grants == {
        "owner": ["create", "delete", "edit", "view"],
        "admin": ["create", "delete", "edit", "view"],
        "editor": ["create", "edit", "view"],
        "viewer": ["view"],
    }
