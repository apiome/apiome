"""Product and plan lifecycle against Postgres — APX-1.4 (#6101).

Each test runs in one rolled-back transaction (the CDG-3.1 ``tx`` fixture, through the APX-1.2
``env`` fixture) and skips when no database with V389 is reachable. They exercise the acceptance
criteria end to end:

* deprecating a plan blocks new subscriptions, records the date, message and successor, and
  notifies owners **once** (the ``owners_notified_at`` marker is claimed once per deprecation);
* **migrate to plan** keeps credentials (``credentials_changed`` false), records the successor and
  refuses a target that is not published or uses another auth strategy;
* retiring waits for ``retire_at``; a retired plan leaves the export and cannot come back;
* a product retires only once its plans have; deprecated products and plans are on the sunset
  timeline, filtered by project;
* every lifecycle step is audited under its own action.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import app.api_lifecycle_store as lifecycle_store
import app.api_plan_store as store
import app.api_product_store as product_store
from app.api_lifecycle import CODE_RETIRE_EARLY, CODE_SUCCESSOR_INVALID, CODE_TRANSITION
from app.api_plans import NOTICE_DEPRECATED, ApiPlanMigrateInput, ApiPlanPatch
from app.api_products import CODE_PLANS_LIVE, ApiProductPatch, ApiProductValidationError
from tests.test_api_plan_store_db import _create, _refused, env  # noqa: F401 - the APX-1.2 fixture
from tests.test_catalog_graph_db import tx  # noqa: F401 - the shared rolled-back transaction fixture

_LATER = datetime.now(timezone.utc) + timedelta(days=120)


@pytest.fixture
def life(env, monkeypatch):  # noqa: F811 - the imported fixture
    cursor = env["cursor"]
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
        "AND table_name = 'api_plans' AND column_name = 'successor_plan_id'"
    )
    if not cursor.fetchone():
        pytest.skip("V389 not applied")
    monkeypatch.setattr(lifecycle_store, "db", env["db"])
    _create(env, state="published", environments=[])
    _create(env, name="Premium", state="published", environments=[])
    return env


def _patch(ctx: Dict[str, Any], slug: str, **fields: Any):
    return store.update_plan(ctx["tenant"], "payments", slug, ApiPlanPatch(**fields), actor=ctx["actor"])


def _actions(ctx: Dict[str, Any]) -> List[str]:
    ctx["cursor"].execute(
        "SELECT action FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action LIKE 'api_product.%%'",
        (ctx["tenant"],),
    )
    return sorted(r["action"] for r in ctx["cursor"].fetchall())


def test_deprecating_blocks_subscriptions_and_notifies_owners_once(life) -> None:
    plan = _patch(life, "standard", state="deprecated", retire_at=_LATER, successor="premium",
                  deprecation_message="Move to Premium.")
    assert plan.state == "deprecated" and plan.accepts_subscriptions is False
    assert plan.deprecated_at and plan.retire_at and plan.owners_notified_at
    assert plan.successor and plan.successor.slug == "premium"
    assert NOTICE_DEPRECATED in [n.code for n in plan.notices]

    # Moving the date keeps the plan deprecated and does not notify again.
    first = plan.owners_notified_at
    moved = _patch(life, "standard", retire_at=_LATER + timedelta(days=30))
    assert moved.owners_notified_at == first
    assert "api_product.plan.deprecate" in _actions(life)
    life["cursor"].execute(
        "SELECT detail FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = 'api_product.plan.deprecate'",
        (life["tenant"],),
    )
    assert [r["detail"]["owners_notified"] for r in life["cursor"].fetchall()] == [0]


def test_the_owners_marker_is_claimed_once(life) -> None:
    _patch(life, "standard", state="deprecated")
    plan_id = store.get_plan(life["tenant"], "payments", "standard").id
    now = datetime.now(timezone.utc)
    assert store._notify_owners_once(life["cursor"], life["tenant"], plan_id, now) is None


def test_reinstating_clears_the_deprecation(life) -> None:
    _patch(life, "standard", state="deprecated", retire_at=_LATER, successor="premium")
    plan = _patch(life, "standard", state="published")
    assert plan.accepts_subscriptions is True
    assert (plan.deprecated_at, plan.retire_at, plan.successor, plan.owners_notified_at) == (None, None, None, None)
    assert "api_product.plan.reinstate" in _actions(life)


def test_migration_keeps_credentials_and_records_the_successor(life) -> None:
    refused = _refused(life, lambda: store.migrate_plan(
        life["tenant"], "payments", "standard", ApiPlanMigrateInput(to="premium"), actor=life["actor"]))
    assert refused.code == CODE_TRANSITION

    _patch(life, "standard", state="deprecated")
    dry = store.migrate_plan(
        life["tenant"], "payments", "standard", ApiPlanMigrateInput(to="premium", dry_run=True), actor=life["actor"])
    assert dry.dry_run and dry.credentials_changed is False and dry.subscriptions == 0
    assert store.get_plan(life["tenant"], "payments", "standard").successor is None

    done = store.migrate_plan(
        life["tenant"], "payments", "standard", ApiPlanMigrateInput(to="premium"), actor=life["actor"])
    assert (done.from_group, done.to_group) == ("plan:payments-standard", "plan:payments-premium")
    assert done.credentials_changed is False
    assert store.get_plan(life["tenant"], "payments", "standard").successor.slug == "premium"
    assert _actions(life).count("api_product.plan.migrate") == 1


def test_a_successor_must_be_published_with_the_same_auth(life) -> None:
    _create(life, name="Partner", auth_strategy="mtls", auth_config={}, state="published", environments=[])
    _create(life, name="Beta", state="draft", environments=[])
    _patch(life, "standard", state="deprecated")
    for target in ("partner", "beta", "standard", "nope"):
        refused = _refused(life, lambda t=target: store.migrate_plan(
            life["tenant"], "payments", "standard", ApiPlanMigrateInput(to=t), actor=life["actor"]))
        assert refused.code == CODE_SUCCESSOR_INVALID, target
    assert _refused(life, lambda: _patch(life, "standard", successor="partner")).code == CODE_SUCCESSOR_INVALID
    assert _refused(life, lambda: _patch(life, "premium", successor="standard")).code == CODE_TRANSITION


def test_retiring_waits_for_the_date_and_is_final(life) -> None:
    assert _refused(life, lambda: _patch(life, "standard", state="retired")).code == CODE_TRANSITION
    _patch(life, "standard", state="deprecated", retire_at=_LATER)
    assert _refused(life, lambda: _patch(life, "standard", state="retired")).code == CODE_RETIRE_EARLY

    _patch(life, "standard", retire_at=datetime.now(timezone.utc) - timedelta(days=1))
    retired = _patch(life, "standard", state="retired")
    assert retired.state == "retired" and retired.retired_at and retired.accepts_subscriptions is False
    assert _refused(life, lambda: _patch(life, "standard", state="published")).code == CODE_TRANSITION
    assert [e["plan"] for e in store.plans_for_revision(life["tenant"], life["project"], life["version"])] == [
        "premium"
    ]
    life["cursor"].execute(
        "SELECT detail FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = 'api_product.plan.retire'",
        (life["tenant"],),
    )
    assert [r["detail"]["provisioning_revoked"] for r in life["cursor"].fetchall()] == [0]


def test_a_new_plan_cannot_start_deprecated(life) -> None:
    refused = _refused(life, lambda: _create(life, name="Old", state="deprecated"))
    assert refused.code == "api-lifecycle-invalid-state"


def test_a_product_retires_after_its_plans_and_shows_on_the_timeline(life) -> None:
    tenant, actor = life["tenant"], life["actor"]
    product_store.update_product(tenant, "payments", ApiProductPatch(state="published"), actor=actor)
    patch = ApiProductPatch(state="deprecated", retire_at=_LATER, deprecation_message="Use Payments v2.")
    deprecated = product_store.update_product(tenant, "payments", patch, actor=actor)
    assert deprecated.deprecated_at and deprecated.retire_at and deprecated.deprecation_message == "Use Payments v2."
    _patch(life, "standard", state="deprecated", retire_at=_LATER - timedelta(days=60), successor="premium")

    entries = lifecycle_store.timeline_entries(tenant, today=date.today())
    assert [(e.kind, e.plan_slug, e.successor_plan_slug) for e in entries] == [
        ("plan", "standard", "premium"), ("product", None, None),
    ]
    assert all(e.timeline_status == "announced" and e.lifecycle_phase == "deprecated" for e in entries)
    assert len(lifecycle_store.timeline_entries(tenant, life["project"])) == 2
    assert lifecycle_store.timeline_entries(tenant, "00000000-0000-4000-8000-000000000000") == []

    product_store.update_product(
        tenant, "payments", ApiProductPatch(retire_at=datetime.now(timezone.utc) - timedelta(days=1)), actor=actor
    )
    life["cursor"].execute("SAVEPOINT refused")
    with pytest.raises(ApiProductValidationError) as caught:
        product_store.update_product(tenant, "payments", ApiProductPatch(state="retired"), actor=actor)
    life["cursor"].execute("ROLLBACK TO SAVEPOINT refused")
    assert caught.value.code == CODE_PLANS_LIVE and "premium, standard" in str(caught.value)

    for slug in ("standard", "premium"):
        if slug == "premium":
            _patch(life, slug, state="deprecated")
        _patch(life, slug, retire_at=datetime.now(timezone.utc) - timedelta(days=1))
        _patch(life, slug, state="retired")
    retired = product_store.update_product(tenant, "payments", ApiProductPatch(state="retired"), actor=actor)
    assert retired.state == "retired" and retired.retired_at
    assert {"api_product.deprecate", "api_product.retire"} <= set(_actions(life))
    assert {e.lifecycle_phase for e in lifecycle_store.timeline_entries(tenant)} == {"retired"}
