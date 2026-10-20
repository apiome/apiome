"""Backstage and Compass import against Postgres — CDG-5.5 (#5983).

Each test runs in one rolled-back transaction (the CDG-3.1 ``tx`` fixture) and skips when no
database with V299 is reachable.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

import pytest

import app.catalog_migration_store as store
import app.entity_owner_store as owner_store
import app.team_store as team_store
from app.catalog_migration_models import AcceptInput, MigrationError
from app.consumer_contract_store import ConsumerActor
from tests.test_catalog_graph_db import tx  # noqa: F401 - the shared rolled-back transaction fixture


@pytest.fixture
def env(tx, monkeypatch):  # noqa: F811 - the imported fixture
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.catalog_import_suggestions') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V299 not applied")
    for module in (store, owner_store, team_store):
        monkeypatch.setattr(module, "db", db)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"migration {suffix}", f"migration-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Ledger', 'ledger', true) RETURNING id::text AS id""",
        (tenant, user),
    )
    project = cursor.fetchone()["id"]
    actor = ConsumerActor(user_id=user, label="tester", kind="user")
    return {"db": db, "cursor": cursor, "tenant": tenant, "user": user, "project": project, "actor": actor}


def _export() -> bytes:
    return json.dumps(
        {
            "components": [
                {
                    "id": "ari:cloud:compass:1:component/checkout",
                    "name": "Checkout",
                    "typeId": "SERVICE",
                    "description": "Takes orders",
                    "ownerId": "ari:cloud:identity::team/aaaa1111",
                    "links": [
                        {"type": "CHAT_CHANNEL", "url": "https://chat.example/checkout", "name": "#checkout"},
                        {"type": "ON_CALL", "url": "https://oncall.example/checkout"},
                    ],
                    "relationships": [
                        {"type": "DEPENDS_ON", "endNode": {"id": "ari:cloud:compass:1:component/ledger"}},
                        {"type": "DEPENDS_ON", "endNode": {"id": "ari:cloud:compass:1:component/payments"}},
                    ],
                    "labels": ["tier-1"],
                },
                {
                    "id": "ari:cloud:compass:1:component/ledger",
                    "name": "Ledger",
                    "ownerId": "ari:cloud:identity::team/aaaa1111",
                },
                {"id": "ari:cloud:compass:1:component/payments", "name": "Payments"},
            ],
            "teams": [
                {
                    "id": "ari:cloud:identity::team/aaaa1111",
                    "displayName": "Checkout team",
                    "description": "Owns checkout",
                }
            ],
        }
    ).encode()


def _by_name(run) -> Dict[str, Any]:
    return {s.name: s for s in run.suggestions}


def _count(cursor: Any, sql: str, *params: Any) -> int:
    cursor.execute(sql, params)
    return int(list(cursor.fetchone().values())[0])


def test_a_compass_export_stages_everything_and_creates_nothing(env) -> None:
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(run)
    assert set(names) == {"Checkout team", "Checkout", "Ledger", "Payments"}
    assert all(s.status == "suggested" for s in run.suggestions)
    assert names["Ledger"].match == {"kind": "project", "id": env["project"], "name": "Ledger", "slug": "ledger"}
    assert names["Checkout"].payload["links"][0] == {
        "type": "chat",
        "url": "https://chat.example/checkout",
        "title": "#checkout",
    }
    assert {"entity": "compass:Checkout", "field": "labels", "reason": "no Apiome field"} in [
        u.model_dump() for u in run.unmapped
    ]
    assert run.counts["components"] == 3 and run.counts["teams"] == 1 and run.counts["matched"] == 1
    assert run.pending == 4
    cursor = env["cursor"]
    assert _count(cursor, "SELECT count(*) FROM apiome.teams WHERE tenant_id = %s::uuid", env["tenant"]) == 0
    assert (
        _count(cursor, "SELECT count(*) FROM apiome.catalog_components WHERE tenant_id = %s::uuid", env["tenant"]) == 0
    )
    assert _count(cursor, "SELECT count(*) FROM apiome.entity_owners WHERE tenant_id = %s::uuid", env["tenant"]) == 0
    assert [r.id for r in store.list_runs(env["tenant"])] == [run.id]


def test_accepting_components_writes_edges_and_resolves_references_later(env) -> None:
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(run)
    checkout = store.accept_suggestion(env["tenant"], names["Checkout"].id, AcceptInput(), actor=env["actor"])
    assert (
        checkout.status == "accepted"
        and checkout.entity["kind"] == "component"
        and checkout.entity["slug"] == "checkout"
    )
    cursor = env["cursor"]
    # Ledger is a Project, so that edge resolves; Payments is still only a suggestion.
    cursor.execute(
        "SELECT to_kind, to_id::text AS to_id FROM apiome.catalog_edges "
        "WHERE from_id = %s::uuid AND provenance = 'declared'",
        (checkout.entity["id"],),
    )
    assert [dict(r) for r in cursor.fetchall()] == [{"to_kind": "project", "to_id": env["project"]}]
    cursor.execute(
        "SELECT reference FROM apiome.catalog_unresolved_dependencies WHERE from_id = %s::uuid",
        (checkout.entity["id"],),
    )
    assert [r["reference"] for r in cursor.fetchall()] == ["component:payments"]

    payments = store.accept_suggestion(env["tenant"], names["Payments"].id, AcceptInput(), actor=env["actor"])
    cursor.execute(
        "SELECT to_kind, to_id::text AS to_id FROM apiome.catalog_edges WHERE from_id = %s::uuid ORDER BY to_kind",
        (checkout.entity["id"],),
    )
    assert {(r["to_kind"], r["to_id"]) for r in cursor.fetchall()} == {
        ("project", env["project"]),
        ("component", payments.entity["id"]),
    }
    assert (
        _count(
            cursor,
            "SELECT count(*) FROM apiome.catalog_unresolved_dependencies WHERE from_id = %s::uuid",
            checkout.entity["id"],
        )
        == 0
    )
    component = store.read_component(env["tenant"], "checkout")
    assert component.component_type == "SERVICE" and [link.type for link in component.links] == ["chat", "on_call"]


def test_a_team_becomes_an_owner_suggestion_never_a_confirmed_owner(env) -> None:
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(run)
    checkout = store.accept_suggestion(env["tenant"], names["Checkout"].id, AcceptInput(), actor=env["actor"])
    ledger = store.accept_suggestion(env["tenant"], names["Ledger"].id, AcceptInput(), actor=env["actor"])
    # Matched: applied to the existing Project, no component created.
    assert ledger.entity == {"kind": "project", "id": env["project"], "slug": "ledger"}
    cursor = env["cursor"]
    assert _count(cursor, "SELECT count(*) FROM apiome.entity_owners WHERE tenant_id = %s::uuid", env["tenant"]) == 0

    team = store.accept_suggestion(env["tenant"], names["Checkout team"].id, AcceptInput(), actor=env["actor"])
    assert team.entity["kind"] == "team" and team.entity["slug"] == "checkout-team"
    cursor.execute(
        "SELECT entity_kind, entity_id::text AS id, status, source FROM apiome.entity_owners "
        "WHERE tenant_id = %s::uuid "
        "ORDER BY entity_kind",
        (env["tenant"],),
    )
    assert [dict(r) for r in cursor.fetchall()] == [
        {"entity_kind": "component", "id": checkout.entity["id"], "status": "suggested", "source": "compass"},
        {"entity_kind": "project", "id": env["project"], "status": "suggested", "source": "compass"},
    ]
    cursor.execute("SELECT description FROM apiome.teams WHERE id = %s::uuid", (team.entity["id"],))
    assert cursor.fetchone()["description"] == "Owns checkout"


def test_a_matched_component_can_be_registered_on_its_own(env) -> None:
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    ledger = store.accept_suggestion(
        env["tenant"],
        _by_name(run)["Ledger"].id,
        AcceptInput(slug="ledger-service", as_component=True),
        actor=env["actor"],
    )
    assert ledger.entity["kind"] == "component" and ledger.entity["slug"] == "ledger-service"


def test_decisions_survive_a_newer_upload_and_cannot_be_made_twice(env) -> None:
    first = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(first)
    store.accept_suggestion(env["tenant"], names["Checkout"].id, AcceptInput(), actor=env["actor"])
    store.dismiss_suggestion(env["tenant"], names["Payments"].id, actor=env["actor"])
    with pytest.raises(MigrationError) as refused:
        store.dismiss_suggestion(env["tenant"], names["Payments"].id, actor=env["actor"])
    assert refused.value.code == "migration-suggestion-decided"

    second = store.import_compass_export(env["tenant"], "compass-2.json", _export(), actor=env["actor"])
    statuses = {s.name: s.status for s in second.suggestions}
    assert statuses == {
        "Checkout team": "suggested",
        "Checkout": "accepted",
        "Ledger": "suggested",
        "Payments": "dismissed",
    }
    assert (
        _count(
            env["cursor"],
            "SELECT count(*) FROM apiome.catalog_import_suggestions WHERE tenant_id = %s::uuid",
            env["tenant"],
        )
        == 4
    )


def test_a_taken_component_slug_is_refused(env) -> None:
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(run)
    store.accept_suggestion(env["tenant"], names["Checkout"].id, AcceptInput(), actor=env["actor"])
    with pytest.raises(MigrationError) as refused:
        store.accept_suggestion(env["tenant"], names["Payments"].id, AcceptInput(slug="checkout"), actor=env["actor"])
    assert refused.value.code == "migration-slug-taken"


def test_a_team_suggestion_with_a_live_slug_links_that_team(env) -> None:
    cursor = env["cursor"]
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s, 'checkout-team', 'Checkout') "
        "RETURNING id::text AS id",
        (env["tenant"],),
    )
    existing = cursor.fetchone()["id"]
    run = store.import_compass_export(env["tenant"], "compass.json", _export(), actor=env["actor"])
    names = _by_name(run)
    assert names["Checkout team"].payload["existingTeam"] is True and run.counts["teamsMatched"] == 1
    # The owner resolves to the live team straight away — still only a suggestion.
    cursor.execute("SELECT status FROM apiome.entity_owners WHERE entity_id = %s::uuid", (env["project"],))
    assert [r["status"] for r in cursor.fetchall()] == ["suggested"]
    linked = store.accept_suggestion(env["tenant"], names["Checkout team"].id, AcceptInput(), actor=env["actor"])
    assert linked.entity["id"] == existing
    assert _count(cursor, "SELECT count(*) FROM apiome.teams WHERE tenant_id = %s::uuid", env["tenant"]) == 1


_CATALOG_INFO = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders
  description: Order service
  annotations: {backstage.io/techdocs-ref: dir:.}
spec:
  type: service
  lifecycle: production
  owner: group:default/orders-team
  dependsOn: [component:default/ledger]
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata: {name: orders-api}
spec:
  type: openapi
  owner: orders-team
  definition:
    $text: ./openapi.yaml
"""


def _repository(env) -> str:
    cursor = env["cursor"]
    cursor.execute(
        """INSERT INTO apiome.tenant_repositories
               (tenant_id, source, provider, clone_url, clone_url_normalized, created_by)
           VALUES (%s, 'public_url', 'github', %s, %s, %s) RETURNING id::text AS id""",
        (
            env["tenant"],
            f"https://github.com/acme/orders-{env['tenant'][:8]}.git",
            f"github.com/acme/orders-{env['tenant'][:8]}",
            env["user"],
        ),
    )
    return cursor.fetchone()["id"]


def test_a_scan_imports_api_definitions_once_and_stages_the_rest(env, monkeypatch) -> None:
    cursor = env["cursor"]
    repository = _repository(env)
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'orders-api', 'orders-api', false) RETURNING id::text AS id""",
        (env["tenant"], env["user"]),
    )
    item = cursor.fetchone()["id"]
    imported = []

    def importer(tenant, repo, branch, api, text, *, existing_project_id, actor_id):
        imported.append((api.external_ref, text, existing_project_id))
        return item

    fetched = []

    def fetch_file(path):
        fetched.append(path)
        return "openapi: 3.0.0"

    files = {"catalog-info.yaml": _CATALOG_INFO}
    counts = store.record_backstage_catalog(
        env["tenant"], repository, "main", files, label="acme/orders · main", fetch_file=fetch_file, importer=importer
    )
    assert counts["apisImported"] == 1 and counts["components"] == 1 and counts["teams"] == 1
    assert fetched == ["openapi.yaml"] and imported == [("api:default/orders-api", "openapi: 3.0.0", None)]
    run = store.list_runs(env["tenant"])[0]
    detail = store.read_run(env["tenant"], run.id)
    assert {s.name for s in detail.suggestions} == {"orders-team", "orders"}
    assert any(u.field == "metadata.annotations.backstage.io/techdocs-ref" for u in detail.unmapped)

    # An unchanged definition is not imported again; the report is rewritten, not duplicated.
    store.record_backstage_catalog(
        env["tenant"], repository, "main", files, label="acme/orders · main", fetch_file=fetch_file, importer=importer
    )
    assert len(imported) == 1 and len(store.list_runs(env["tenant"])) == 1

    # Accepting the team suggests it as the imported API's owner.
    team = next(s for s in detail.suggestions if s.kind == "team")
    store.accept_suggestion(env["tenant"], team.id, AcceptInput(), actor=env["actor"])
    cursor.execute("SELECT status, source FROM apiome.entity_owners WHERE entity_id = %s::uuid", (item,))
    assert [dict(r) for r in cursor.fetchall()] == [{"status": "suggested", "source": "backstage"}]

    # With the file gone, the report and its pending suggestions go too.
    store.record_backstage_catalog(
        env["tenant"], repository, "main", {}, label="acme/orders · main", fetch_file=fetch_file, importer=importer
    )
    assert store.list_runs(env["tenant"]) == []
