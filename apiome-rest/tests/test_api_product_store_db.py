"""API products against Postgres — APX-1.1 (#6098).

Each test runs in one rolled-back transaction (the CDG-3.1 ``tx`` fixture) and skips when no
database with V387 is reachable. They exercise the store's SQL and the acceptance criteria end to
end: a ``payments@latest`` member follows a new publish, the blast radius of a change in a member
lists the product, and ``portal`` needs every member published.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import psycopg2
import pytest

import app.api_product_store as store
from app.api_products import (
    CODE_MEMBER_DUPLICATE,
    CODE_PORTAL_UNPUBLISHED,
    CODE_SLUG_TAKEN,
    ApiProductInput,
    ApiProductMemberInput,
    ApiProductPatch,
    ApiProductValidationError,
)
from app.blast_radius import BlastRadiusRequest, blast_radius
from app.consumer_contract_store import ConsumerActor
from tests.test_catalog_graph_db import tx  # noqa: F401 - the shared rolled-back transaction fixture


@pytest.fixture
def env(tx, monkeypatch):  # noqa: F811 - the imported fixture
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.api_product_members') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V387 not applied")
    monkeypatch.setattr(store, "db", db)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"products {suffix}", f"products-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]

    def project(slug: str, publishable: bool = True) -> str:
        cursor.execute(
            """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
               VALUES (%s, %s, %s, %s, %s) RETURNING id::text AS id""",
            (tenant, user, slug.title(), slug, publishable),
        )
        return cursor.fetchone()["id"]

    def version(project_id: str, label: str, published: bool, days_ago: int = 0) -> None:
        cursor.execute(
            """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
               VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() - make_interval(days => %s) END)""",
            (project_id, user, label, published, published, days_ago),
        )

    payments, refunds = project("payments"), project("refunds")
    version(payments, "1.0.0", True, days_ago=5)
    version(refunds, "1.0.0", True, days_ago=5)
    version(refunds, "2.0.0", False)
    cursor.execute(
        """INSERT INTO apiome.mcp_endpoints (tenant_id, creator_id, name, slug, endpoint_url, transport, published)
           VALUES (%s, %s, 'Payments MCP', 'payments-mcp', 'https://mcp.example/payments', 'streamable_http', false)
           RETURNING id::text AS id""",
        (tenant, user),
    )
    mcp = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s, 'payments', 'Payments') RETURNING id::text AS id",
        (tenant,),
    )
    actor = ConsumerActor(user_id=user, label="tester", kind="user")
    return {"db": db, "cursor": cursor, "tenant": tenant, "payments": payments, "refunds": refunds, "mcp": mcp,
            "version": version, "actor": actor}


def _refused(env: Dict[str, Any], work) -> ApiProductValidationError:
    """Run a write the database refuses under a savepoint and return the refusal.

    The harness's single transaction would otherwise stay aborted after the failed statement
    (in production ``_guarded_tx`` rolls the write's own transaction back).
    """
    cursor = env["cursor"]
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(ApiProductValidationError) as caught:
        work()
    cursor.execute("ROLLBACK TO SAVEPOINT refused")
    return caught.value


def _create(env: Dict[str, Any], **overrides: Any):
    body = {"name": "Payments", "owner_team": "payments", **overrides}
    return store.create_product(env["tenant"], ApiProductInput(**body), actor=env["actor"])


def test_a_latest_member_follows_a_new_publish(env) -> None:
    product = _create(env, members=[{"kind": "project_latest", "ref": "payments"}])
    assert product.members[0].resolved_version.label == "1.0.0"

    env["version"](env["payments"], "1.1.0", True)
    member = store.get_product(env["tenant"], "payments").members[0]
    assert member.resolved_version.label == "1.1.0" and member.published


def test_a_range_member_ignores_an_unpublished_version_in_range(env) -> None:
    product = _create(env, members=[{"kind": "project_version", "ref": "refunds", "version": "1.x"},
                                    {"kind": "project_version", "ref": "refunds", "version": "2.x"}])
    by_selector = {m.version_selector: m for m in product.members}
    assert by_selector["1.x"].resolved_version.label == "1.0.0" and by_selector["1.x"].published
    assert by_selector["2.x"].resolved_version.label == "2.0.0" and not by_selector["2.x"].published
    assert product.portal_ready is False and product.owner_team.slug == "payments"


def test_the_blast_radius_of_a_change_in_a_member_lists_the_product(env) -> None:
    product = _create(env, members=[{"kind": "project_latest", "ref": "payments"}])
    result = blast_radius(env["db"], env["tenant"], BlastRadiusRequest(kind="project", entity="payments"))

    direct = [e for e in result["direct"] if e["kind"] == "api_product"]
    assert [(e["id"], e["slug"], e["edge_kind"]) for e in direct] == [(product.id, "payments", "includes")]
    assert direct[0]["owner"]["slug"] == "payments"

    # The harness is one transaction, so CURRENT_TIMESTAMP never moves; age the edges so the
    # delete's re-derive can tell them from fresh ones, as a later transaction would.
    env["cursor"].execute(
        "UPDATE apiome.catalog_edges SET last_seen_at = last_seen_at - interval '1 minute' WHERE tenant_id = %s::uuid",
        (env["tenant"],),
    )
    store.delete_product(env["tenant"], "payments", actor=env["actor"])
    after = blast_radius(env["db"], env["tenant"], BlastRadiusRequest(kind="project", entity="payments"))
    assert not [e for e in after["direct"] if e["kind"] == "api_product"]


def test_includes_edges_point_at_projects_and_mcp_servers(env) -> None:
    product = _create(env, members=[{"kind": "project_latest", "ref": "payments"},
                                    {"kind": "mcp_server", "ref": "payments-mcp"}])
    cursor = env["cursor"]
    cursor.execute(
        """SELECT to_kind, to_id::text AS to_id FROM apiome.catalog_edges
           WHERE tenant_id = %s::uuid AND from_id = %s::uuid AND edge_kind = 'includes' AND stale_since IS NULL
           ORDER BY to_kind""",
        (env["tenant"], product.id),
    )
    assert [(r["to_kind"], r["to_id"]) for r in cursor.fetchall()] == [
        ("mcp_endpoint", env["mcp"]), ("project", env["payments"]),
    ]


def test_portal_needs_every_member_published(env) -> None:
    _create(env, members=[{"kind": "project_latest", "ref": "payments"},
                          {"kind": "mcp_server", "ref": "payments-mcp"}])
    with pytest.raises(ApiProductValidationError) as caught:
        store.update_product(env["tenant"], "payments", ApiProductPatch(visibility="portal"), actor=env["actor"])
    assert caught.value.code == CODE_PORTAL_UNPUBLISHED
    assert [b["name"] for b in caught.value.blockers] == ["Payments MCP"]

    env["cursor"].execute("UPDATE apiome.mcp_endpoints SET published = true WHERE id = %s::uuid", (env["mcp"],))
    updated = store.update_product(env["tenant"], "payments", ApiProductPatch(visibility="portal"), actor=env["actor"])
    assert updated.visibility == "portal" and updated.portal_ready


def test_unique_keys_map_to_their_codes_and_every_write_is_audited(env) -> None:
    _create(env)
    assert _refused(env, lambda: _create(env)).code == CODE_SLUG_TAKEN

    member = ApiProductMemberInput(kind="project_latest", ref="payments", environment="production")
    store.add_member(env["tenant"], "payments", member, actor=env["actor"])
    duplicate = _refused(env, lambda: store.add_member(env["tenant"], "payments", member, actor=env["actor"]))
    assert duplicate.code == CODE_MEMBER_DUPLICATE

    env["cursor"].execute(
        "SELECT action FROM apiome.access_audit WHERE tenant_id = %s::uuid ORDER BY created_at, id", (env["tenant"],)
    )
    assert [r["action"] for r in env["cursor"].fetchall()] == ["api_product.create", "api_product.member.add"]


def test_the_schema_refuses_a_selector_on_a_latest_member(env) -> None:
    product = _create(env)
    cursor = env["cursor"]
    cursor.execute("SAVEPOINT bad_member")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            """INSERT INTO apiome.api_product_members (tenant_id, product_id, member_kind, member_ref, version_selector)
               VALUES (%s, %s, 'project_latest', %s, '1.x')""",
            (env["tenant"], product.id, env["payments"]),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT bad_member")
