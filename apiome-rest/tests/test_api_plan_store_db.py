"""API plans against Postgres — APX-1.2 (#6099).

Each test runs in one rolled-back transaction (the CDG-3.1 ``tx`` fixture) and skips when no
database with V388 is reachable. They exercise the store's SQL and the acceptance criteria end to
end:

* a plan whose environments reference a gateway config without a provisioning-capable connector is
  saved as *declared only* with a notice (and stored so);
* limits validate — positive, windows unique;
* a member with no security scheme for the plan's auth strategy is a warning;
* an export of a revision a product includes reads that product's plans, without ``billing_ref``;
* every write is audited, a slug is unique among a product's live plans and a delete frees it.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest

import app.api_plan_store as store
import app.api_product_store as product_store
from app import api_plans
from app.api_plans import (
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_INVALID,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    NOTICE_DECLARED_ONLY,
    WARNING_AUTH_MISMATCH,
    ApiPlanInput,
    ApiPlanPatch,
    ApiPlanValidationError,
)
from app.api_products import ApiProductInput
from app.consumer_contract_store import ConsumerActor
from tests.test_catalog_graph_db import tx  # noqa: F401 - the shared rolled-back transaction fixture


@pytest.fixture
def env(tx, monkeypatch):  # noqa: F811 - the imported fixture
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.api_plans') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V388 not applied")
    monkeypatch.setattr(store, "db", db)
    monkeypatch.setattr(product_store, "db", db)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"plans {suffix}", f"plans-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]

    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Payments API', 'payments', true) RETURNING id::text AS id""",
        (tenant, user),
    )
    project = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
           VALUES (%s, %s, '1.0.0', true, now()) RETURNING id::text AS id""",
        (project, user),
    )
    version = cursor.fetchone()["id"]

    cursor.execute(
        """INSERT INTO apiome.catalog_connectors (tenant_id, kind, name, base_url)
           VALUES (%s, 'kong-admin', 'Kong', 'https://kong.example.com') RETURNING id::text AS id""",
        (tenant,),
    )
    connector = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.catalog_gateway_configs (tenant_id, connector_id, environment, slug, name, flavor)
           VALUES (%s, %s, 'prod-cp', 'kong-prod-cp', 'Kong · prod-cp', 'kong-admin') RETURNING id::text AS id""",
        (tenant, connector),
    )
    gateway = cursor.fetchone()["id"]

    actor = ConsumerActor(user_id=user, label="tester", kind="user")
    product_store.create_product(
        tenant, ApiProductInput(name="Payments", members=[{"kind": "project_latest", "ref": "payments"}]), actor=actor
    )
    return {"db": db, "cursor": cursor, "tenant": tenant, "project": project, "version": version,
            "gateway": gateway, "actor": actor}


def _refused(env: Dict[str, Any], work) -> ApiPlanValidationError:
    """Run a write the store refuses under a savepoint and return the refusal."""
    cursor = env["cursor"]
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(ApiPlanValidationError) as caught:
        work()
    cursor.execute("ROLLBACK TO SAVEPOINT refused")
    return caught.value


def _create(env: Dict[str, Any], **overrides: Any):
    body = {
        "name": "Standard",
        "limits": [{"window": "minute", "requests": 100}, {"window": "day", "requests": 50000}],
        "environments": ["kong-prod-cp"],
        "billing_ref": "price_123",
        **overrides,
    }
    return store.create_plan(env["tenant"], "payments", ApiPlanInput(**body), actor=env["actor"])


def _stored_declared_only(env: Dict[str, Any], slug: str) -> bool:
    env["cursor"].execute(
        "SELECT declared_only FROM apiome.api_plans WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
        (env["tenant"], slug),
    )
    return env["cursor"].fetchone()["declared_only"]


def test_an_environment_without_provisioning_saves_the_plan_declared_only(env) -> None:
    plan = _create(env)
    assert plan.declared_only is True
    assert [(e.slug, e.environment, e.connector_kind, e.can_provision) for e in plan.environments] == [
        ("kong-prod-cp", "prod-cp", "kong-admin", False),
    ]
    assert [n.code for n in plan.notices] == [NOTICE_DECLARED_ONLY]
    assert "kong-prod-cp cannot be provisioned yet" in plan.notices[0].message
    assert _stored_declared_only(env, "standard") is True
    assert [(limit.window, limit.requests) for limit in plan.limits] == [("minute", 100), ("day", 50000)]


def test_a_provisioning_connector_clears_declared_only(env, monkeypatch) -> None:
    monkeypatch.setattr(api_plans, "PROVISIONING_CONNECTOR_KINDS", frozenset({"kong-admin"}))
    plan = _create(env)
    assert plan.declared_only is False and plan.notices == []
    assert _stored_declared_only(env, "standard") is False

    updated = store.update_plan(env["tenant"], "payments", "standard", ApiPlanPatch(environments=[]),
                                actor=env["actor"])
    assert updated.declared_only is True and _stored_declared_only(env, "standard") is True


def test_limits_validate(env) -> None:
    twice = _refused(env, lambda: _create(env, limits=[{"window": "minute", "requests": 1},
                                                       {"window": "minute", "requests": 2}]))
    assert twice.code == CODE_INVALID
    _create(env)
    bad_patch = _refused(env, lambda: store.update_plan(
        env["tenant"], "payments", "standard",
        ApiPlanPatch(limits=[{"window": "hour", "requests": 5}, {"window": "hour", "requests": 6}]),
        actor=env["actor"],
    ))
    assert bad_patch.code == CODE_INVALID


def test_an_unknown_environment_is_refused(env) -> None:
    assert _refused(env, lambda: _create(env, environments=["kong-nowhere"])).code == CODE_ENVIRONMENT_NOT_FOUND


def test_a_member_without_a_matching_scheme_is_a_warning(env) -> None:
    plan = _create(env)
    assert [w.code for w in plan.warnings] == [WARNING_AUTH_MISMATCH]
    assert plan.warnings[0].member["name"] == "Payments API"

    env["cursor"].execute(
        """INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, in_location, param_name)
           VALUES (%s, 'apiKey', 'apiKey', 'header', 'X-API-Key')""",
        (env["version"],),
    )
    assert store.get_plan(env["tenant"], "payments", "standard").warnings == []
    mtls = store.update_plan(env["tenant"], "payments", "standard", ApiPlanPatch(auth_strategy="mtls"),
                             actor=env["actor"])
    assert [w.code for w in mtls.warnings] == [WARNING_AUTH_MISMATCH]


def test_changing_the_strategy_rechecks_the_stored_auth_config(env) -> None:
    _create(env, auth_config={"header_name": "X-API-Key"})
    refused = _refused(env, lambda: store.update_plan(
        env["tenant"], "payments", "standard", ApiPlanPatch(auth_strategy="mtls"), actor=env["actor"]
    ))
    assert refused.code == CODE_INVALID
    updated = store.update_plan(
        env["tenant"], "payments", "standard",
        ApiPlanPatch(auth_strategy="oauth2_client_credentials", auth_config={"scopes": ["payments:read"]}),
        actor=env["actor"],
    )
    assert updated.auth_strategy == "oauth2_client_credentials" and updated.auth_config.scopes == ["payments:read"]


def test_an_export_of_an_included_revision_reads_the_plans(env) -> None:
    _create(env)
    _create(env, name="Retired", state="published", environments=[])
    store.update_plan(env["tenant"], "payments", "retired", ApiPlanPatch(state="deprecated"), actor=env["actor"])
    store.update_plan(env["tenant"], "payments", "retired", ApiPlanPatch(state="retired"), actor=env["actor"])
    entries = store.plans_for_revision(env["tenant"], env["project"], env["version"])
    assert [(e["product"], e["plan"]) for e in entries] == [("payments", "standard")]
    assert entries[0]["limits"] == [{"window": "minute", "requests": 100}, {"window": "day", "requests": 50000}]
    assert entries[0]["environments"] == ["kong-prod-cp"] and "billing_ref" not in entries[0]

    # An older revision is not the one the product's latest member resolves to.
    env["cursor"].execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
           SELECT %s, creator_id, '0.9.0', true, now() - interval '30 days' FROM apiome.versions WHERE id = %s::uuid
           RETURNING id::text AS id""",
        (env["project"], env["version"]),
    )
    older = env["cursor"].fetchone()["id"]
    assert store.plans_for_revision(env["tenant"], env["project"], older) == []


def test_slugs_are_unique_per_product_and_every_write_is_audited(env) -> None:
    _create(env)
    assert _refused(env, lambda: _create(env)).code == CODE_SLUG_TAKEN
    store.update_plan(env["tenant"], "payments", "standard", ApiPlanPatch(approval="auto"), actor=env["actor"])
    assert store.delete_plan(env["tenant"], "payments", "standard", actor=env["actor"]) == "standard"
    assert _refused(env, lambda: store.get_plan(env["tenant"], "payments", "standard")).code == CODE_NOT_FOUND
    assert _create(env).slug == "standard"

    env["cursor"].execute(
        "SELECT action FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action LIKE 'api_product.plan.%%'",
        (env["tenant"],),
    )
    # One harness transaction: every row has the same timestamp, so compare without an order.
    assert sorted(r["action"] for r in env["cursor"].fetchall()) == [
        "api_product.plan.create", "api_product.plan.create", "api_product.plan.delete", "api_product.plan.update",
    ]
    assert [p.slug for p in store.list_plans(env["tenant"], "payments")] == ["standard"]
