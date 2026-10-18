"""Declared dependencies against a live Postgres — CDG-3.2 (#5967).

The acceptance criteria:

* a spec with two ``x-apiome-depends-on`` entries, one unresolvable, yields one declared edge and
  one visible unresolved entry;
* a Backstage ``consumesApis`` list yields ``consumes`` edges with provenance ``declared`` and
  ``source_ref`` ``backstage:<path>``;
* re-importing (or re-scanning, or re-PUTting) never duplicates edges, and dropping a reference
  drops its row;

plus: sources never touch each other's rows or the derived edges, ``providesApis`` picks the
declaring API, and a vanished ``catalog-info`` file takes its declarations with it.

Runs in one always-rolled-back transaction (the ``tx`` fixture of ``test_catalog_graph_db``).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest

from app import declared_dependency_store as store
from app.catalog_graph import materialize_on_cursor
from app.consumer_contract_store import ConsumerActor
from app.declared_dependencies import DependencyValidationError
from tests.test_catalog_graph_db import _seed, tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db


@pytest.fixture
def world(tx, monkeypatch) -> Dict[str, Any]:  # noqa: F811 - the imported fixture
    """The CDG-3.1 seed plus two more APIs (``payments``, ``customers``) and a repository."""
    db, cursor = tx
    monkeypatch.setattr(store, "db", db)
    seed = _seed(cursor)
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    for slug, publishable in (("payments", True), ("customers", False)):
        cursor.execute(
            """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
               VALUES (%s, %s, %s, %s, %s) RETURNING id::text AS id""",
            (seed["tenant"], user, slug.title(), slug, publishable),
        )
        seed[slug] = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:8]
    cursor.execute(
        """INSERT INTO apiome.tenant_repositories (tenant_id, source, provider, clone_url, clone_url_normalized)
           VALUES (%s, 'public_url', 'github', %s, %s) RETURNING id::text AS id""",
        (seed["tenant"], f"https://github.com/acme/orders-{suffix}.git", f"github.com/acme/orders-{suffix}"),
    )
    seed["repository"] = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.repository_import_spec (tenant_id, repository_id, branch, path, project_id, source_kind)
           VALUES (%s, %s, 'main', 'api/openapi.yaml', %s, 'openapi')""",
        (seed["tenant"], seed["repository"], seed["project"]),
    )
    seed["db"], seed["cursor"] = db, cursor
    return seed


def _declared(cursor: Any, tenant: str, project: str) -> list:
    cursor.execute(
        """SELECT edge_kind, to_kind, to_id::text AS to_id, pointer, source_ref, provenance
           FROM apiome.catalog_edges
           WHERE tenant_id = %s::uuid AND from_id = %s::uuid AND provenance = 'declared'
           ORDER BY source_ref, edge_kind, to_id, pointer""",
        (tenant, project),
    )
    return [dict(row) for row in cursor.fetchall()]


def test_a_spec_with_one_resolvable_and_one_unresolvable_entry(world) -> None:
    document = {"openapi": "3.1.0", "x-apiome-depends-on": ["payments#/components/schemas/Card", "ledger"]}
    counts = store.record_spec_dependencies(world["tenant"], "project", world["project"], document)
    assert counts == {"declared": 1, "removed": 0, "unresolved": 1}
    edges = _declared(world["cursor"], world["tenant"], world["project"])
    assert edges == [{
        "edge_kind": "depends_on", "to_kind": "project", "to_id": world["payments"],
        "pointer": "/components/schemas/Card", "source_ref": "spec", "provenance": "declared",
    }]
    read = store.read_dependencies(world["tenant"], "project", world["project"])
    assert [edge["evidence"]["reference"] for edge in read["declared"]] == ["payments#/components/schemas/Card"]
    assert [(u["reference"], u["reason"], u["source_ref"]) for u in read["unresolved"]] == [
        ("ledger", "not-found", "spec")
    ]

    # Re-import: nothing duplicates. Then the extension changes: the old entry goes, a new one comes.
    store.record_spec_dependencies(world["tenant"], "project", world["project"], document)
    assert len(_declared(world["cursor"], world["tenant"], world["project"])) == 1
    assert len(store.read_dependencies(world["tenant"], "project", world["project"])["unresolved"]) == 1
    counts = store.record_spec_dependencies(
        world["tenant"], "project", world["project"], {"x-apiome-depends-on": "customers"}
    )
    assert counts == {"declared": 1, "removed": 1, "unresolved": 0}
    assert [e["to_kind"] for e in _declared(world["cursor"], world["tenant"], world["project"])] == ["catalog_item"]
    assert store.read_dependencies(world["tenant"], "project", world["project"])["unresolved"] == []


def test_a_self_reference_is_unresolved(world) -> None:
    slug_of_self = world["cursor"]
    slug_of_self.execute("SELECT slug FROM apiome.projects WHERE id = %s::uuid", (world["project"],))
    slug = slug_of_self.fetchone()["slug"]
    store.record_spec_dependencies(world["tenant"], "project", world["project"], {"x-apiome-depends-on": [slug]})
    unresolved = store.read_dependencies(world["tenant"], "project", world["project"])["unresolved"]
    assert [u["reason"] for u in unresolved] == ["self"]


_CATALOG_INFO = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders-service
spec:
  type: service
  providesApis: [api:default/{slug}]
  consumesApis:
    - api:default/payments
    - api:customers
    - api:default/ledger
  dependsOn:
    - component:payments
"""


def test_backstage_consumes_apis_become_declared_consumes_edges(world) -> None:
    cursor = world["cursor"]
    cursor.execute("SELECT slug FROM apiome.projects WHERE id = %s::uuid", (world["project"],))
    text = _CATALOG_INFO.format(slug=cursor.fetchone()["slug"])
    files = {"catalog-info.yaml": text}
    totals = store.record_backstage_dependencies(world["tenant"], world["repository"], "main", files)
    assert totals == {"entities": 1, "declared": 3, "unresolved": 1}
    edges = _declared(cursor, world["tenant"], world["project"])
    assert {(e["edge_kind"], e["to_id"]) for e in edges} == {
        ("consumes", world["payments"]), ("consumes", world["customers"]), ("depends_on", world["payments"])
    }
    assert {e["source_ref"] for e in edges} == {"backstage:catalog-info.yaml"}
    assert {e["provenance"] for e in edges} == {"declared"}
    unresolved = store.read_dependencies(world["tenant"], "project", world["project"])["unresolved"]
    assert [(u["reference"], u["edge_kind"]) for u in unresolved] == [("api:default/ledger", "consumes")]

    # A re-scan doesn't duplicate; a removed file takes its declarations with it.
    store.record_backstage_dependencies(world["tenant"], world["repository"], "main", files)
    assert len(_declared(cursor, world["tenant"], world["project"])) == 3
    store.record_backstage_dependencies(world["tenant"], world["repository"], "main", {})
    assert _declared(cursor, world["tenant"], world["project"]) == []
    assert store.read_dependencies(world["tenant"], "project", world["project"])["unresolved"] == []


def test_provides_apis_naming_another_api_skips_this_one(world) -> None:
    cursor = world["cursor"]
    cursor.execute(
        """INSERT INTO apiome.repository_import_spec (tenant_id, repository_id, branch, path, project_id, source_kind)
           VALUES (%s, %s, 'main', 'payments/openapi.yaml', %s, 'openapi')""",
        (world["tenant"], world["repository"], world["payments"]),
    )
    text = _CATALOG_INFO.format(slug="payments")
    store.record_backstage_dependencies(world["tenant"], world["repository"], "main", {"svc/catalog-info.yaml": text})
    assert _declared(cursor, world["tenant"], world["project"]) == []
    # payments consumes itself (self) and customers; the ledger is unresolved.
    assert {e["to_id"] for e in _declared(cursor, world["tenant"], world["payments"])} == {world["customers"]}


def test_put_replaces_only_manual_declarations_and_is_audited(world) -> None:
    store.record_spec_dependencies(world["tenant"], "project", world["project"], {"x-apiome-depends-on": "payments"})
    actor = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
    items = [
        {"to": {"slug": "customers"}, "pointer": "/paths/~1customers", "note": "address lookup"},
        {"to": {"kind": "project", "id": world["payments"]}},
        {"to": {"slug": "nowhere"}},
    ]
    result = store.put_dependencies(world["tenant"], "project", world["project"], items, actor=actor)
    sources = sorted((e["source_ref"], e["to_id"]) for e in result["declared"])
    assert sources == sorted([
        ("manual", world["customers"]), ("manual", world["payments"]), ("spec", world["payments"])
    ])
    note = next(e for e in result["declared"] if e["pointer"] == "/paths/~1customers")["evidence"]["note"]
    assert note == "address lookup"
    assert [u["reference"] for u in result["unresolved"]] == ["nowhere"]

    again = store.put_dependencies(world["tenant"], "project", world["project"], items, actor=actor)
    assert len(again["declared"]) == 3
    cleared = store.put_dependencies(world["tenant"], "project", world["project"], [], actor=actor)
    assert [(e["source_ref"], e["to_id"]) for e in cleared["declared"]] == [("spec", world["payments"])]
    assert cleared["unresolved"] == []

    cursor = world["cursor"]
    cursor.execute(
        "SELECT count(*) AS n FROM apiome.access_audit WHERE tenant_id = %s::uuid "
        "AND action = 'graph.dependencies.update'",
        (world["tenant"],),
    )
    assert cursor.fetchone()["n"] == 3


def test_declared_edges_survive_the_derived_materializer(world) -> None:
    store.record_spec_dependencies(world["tenant"], "project", world["project"], {"x-apiome-depends-on": "payments"})
    materialize_on_cursor(world["cursor"], world["tenant"])
    edges = _declared(world["cursor"], world["tenant"], world["project"])
    assert len(edges) == 1


def test_a_slug_names_the_declaring_entity_and_unknowns_are_refused(world) -> None:
    cursor = world["cursor"]
    assert store.read_dependencies(world["tenant"], "catalog_item", "customers")["kind"] == "catalog_item"
    for kind, entity in (("project", "nowhere"), ("consumer", "not-an-id"), ("galaxy", world["project"])):
        with pytest.raises(DependencyValidationError):
            store.read_dependencies(world["tenant"], kind, entity)
    assert cursor  # the transaction is still usable
