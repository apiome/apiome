"""The catalog graph against a live Postgres — CDG-3.1 (#5966).

The acceptance criteria that only the real schema can prove:

* materializing twice leaves identical rows;
* each consumer-contract revision yields exactly its pointer count of ``consumes`` edges, and a new
  revision replaces the old one's edges;
* **parity with CTG-4.2**: the consumers :meth:`Database.find_consumer_contracts_by_pointers` (the
  impact read behind ``contracts_affected_by``) returns for a set of changed pointers are exactly
  the consumers reachable through ``consumes`` edges whose pointer overlaps one of them;
* a revoked consumer's edges turn stale (and the read reports them stale) instead of vanishing, and
  are purged after 30 days;
* the producers' in-transaction hook (``soft_delete_consumer``) does this itself.

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped when no database is reachable.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List, Tuple

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app.catalog_graph import list_edges, materialize, materialize_on_cursor
from app.config import settings
from app.database import Database

pytestmark = pytest.mark.requires_db


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


@pytest.fixture
def tx() -> Iterator[Tuple[Database, Any]]:
    """A :class:`Database` and a raw cursor over one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.catalog_edges') AS t, (SELECT id FROM apiome.users LIMIT 1) AS u")
        found = probe.fetchone()
    if not found["t"] or not found["u"]:
        conn.close()
        pytest.skip("V288 not applied or no user to own the seed projects")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        with conn.cursor() as cursor:
            yield db, cursor
    finally:
        conn.rollback()
        conn.close()


def _seed(cursor: Any) -> Dict[str, Any]:
    """A tenant with one project and three consumers holding current contracts."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"graph {suffix}", f"graph-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Orders', %s, true) RETURNING id::text AS id""",
        (tenant, user, f"orders-{suffix}"),
    )
    project = cursor.fetchone()["id"]
    pointers = {
        "web": ["/paths/~1orders/get/responses/200/content/application~1json/schema/properties/id"],
        "mobile": [
            "/paths/~1orders/get/responses/200/content/application~1json/schema/properties/total",
            "/paths/~1orders/post",
        ],
        "batch": ["/components/schemas/Invoice/properties/amount"],
    }
    consumers: Dict[str, str] = {}
    for slug, declared in pointers.items():
        cursor.execute(
            """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
               VALUES (%s, %s, %s, %s) RETURNING id::text AS id""",
            (tenant, project, slug, slug.title()),
        )
        consumers[slug] = cursor.fetchone()["id"]
        _contract(cursor, tenant, project, consumers[slug], 1, declared)
    return {"tenant": tenant, "project": project, "consumers": consumers, "pointers": pointers}


def _contract(cursor: Any, tenant: str, project: str, consumer: str, revision: int, pointers: List[str]) -> None:
    """Write a consumer's current contract revision (retiring the previous one)."""
    cursor.execute(
        "UPDATE apiome.consumer_contract SET is_current = false WHERE consumer_id = %s::uuid AND is_current",
        (consumer,),
    )
    cursor.execute(
        """INSERT INTO apiome.consumer_contract (tenant_id, project_id, consumer_id, revision, surface_pointers)
           VALUES (%s, %s, %s, %s, %s::text[])""",
        (tenant, project, consumer, revision, pointers),
    )


def _edges(cursor: Any, tenant: str) -> List[Dict[str, Any]]:
    """Every edge of the tenant, in a stable order, with the columns that identify and age it."""
    cursor.execute(
        """SELECT from_kind, from_id::text, to_kind, to_id::text, edge_kind, pointer, provenance,
                  source_ref, evidence, first_seen_at, last_seen_at, stale_since
           FROM apiome.catalog_edges WHERE tenant_id = %s::uuid
           ORDER BY edge_kind, from_id, to_id, pointer""",
        (tenant,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _age_edges(cursor: Any, tenant: str, interval: str) -> None:
    """Pretend the last materialization ran ``interval`` ago (a transaction's clock never moves)."""
    cursor.execute(
        f"""UPDATE apiome.catalog_edges
               SET first_seen_at = first_seen_at - interval '{interval}',
                   last_seen_at = last_seen_at - interval '{interval}',
                   stale_since = stale_since - interval '{interval}'
             WHERE tenant_id = %s::uuid""",
        (tenant,),
    )


def test_materializing_twice_leaves_identical_rows(tx) -> None:
    db, cursor = tx
    seed = _seed(cursor)
    first = materialize_on_cursor(cursor, seed["tenant"])
    rows = _edges(cursor, seed["tenant"])
    second = materialize_on_cursor(cursor, seed["tenant"])
    assert _edges(cursor, seed["tenant"]) == rows
    assert first["consumes"]["current"] == second["consumes"]["current"] == 4
    assert second["consumes"]["staled"] == 0

    # Across runs (a later transaction), the identity holds too: nothing is added or staled.
    _age_edges(cursor, seed["tenant"], "1 hour")
    again = materialize(db, seed["tenant"], "test")
    assert again["consumes"] == {"current": 4, "staled": 0, "purged": 0}
    assert len(_edges(cursor, seed["tenant"])) == len(rows)


def test_each_contract_revision_yields_its_pointer_count_of_consumes_edges(tx) -> None:
    _db, cursor = tx
    seed = _seed(cursor)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    edges = [e for e in _edges(cursor, seed["tenant"]) if e["edge_kind"] == "consumes"]
    for slug, declared in seed["pointers"].items():
        mine = [e for e in edges if e["from_id"] == seed["consumers"][slug]]
        assert sorted(e["pointer"] for e in mine) == sorted(declared)
        assert {(e["from_kind"], e["to_kind"], e["to_id"], e["provenance"]) for e in mine} == {
            ("consumer", "project", seed["project"], "derived")
        }
        assert all(e["evidence"] == {"revision": 1, "consumer_slug": slug} for e in mine)

    # Revision 2 of "web" declares three pointers: exactly those three are current afterwards.
    _age_edges(cursor, seed["tenant"], "1 hour")
    revised = [f"/paths/~1orders/get/parameters/{name}" for name in ("page", "size", "sort")]
    _contract(cursor, seed["tenant"], seed["project"], seed["consumers"]["web"], 2, revised)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    web = [e for e in _edges(cursor, seed["tenant"]) if e["from_id"] == seed["consumers"]["web"]]
    assert sorted(e["pointer"] for e in web if e["stale_since"] is None) == sorted(revised)
    assert [e["pointer"] for e in web if e["stale_since"] is not None] == seed["pointers"]["web"]


@pytest.mark.parametrize(
    "changed",
    [
        ["/paths/~1orders/get/responses/200/content/application~1json/schema/properties/id"],
        ["/paths/~1orders/get"],
        ["/paths/~1orders/post/requestBody"],
        ["/components/schemas/Invoice"],
        ["/paths/~1orders/get/responses/200/content/application~1json/schema/properties/total/minimum"],
        ["/paths/~1customers"],
        ["/components/schemas/Invoice/properties/amount", "/paths/~1orders/post"],
    ],
)
def test_impact_set_equals_consumers_reachable_through_overlapping_consumes_edges(tx, changed) -> None:
    db, cursor = tx
    seed = _seed(cursor)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    impact = {
        row["consumer_id"]
        for row in db.find_consumer_contracts_by_pointers(seed["project"], seed["tenant"], changed)
    }
    cursor.execute(
        """SELECT DISTINCT e.from_id::text AS consumer
           FROM apiome.catalog_edges e CROSS JOIN unnest(%s::text[]) AS changed
           WHERE e.tenant_id = %s::uuid AND e.edge_kind = 'consumes' AND e.to_id = %s::uuid
             AND e.stale_since IS NULL
             AND (starts_with(changed, e.pointer) OR starts_with(e.pointer, changed))""",
        (changed, seed["tenant"], seed["project"]),
    )
    reachable = {row["consumer"] for row in cursor.fetchall()}
    assert {str(c) for c in impact} == reachable


def test_a_revoked_consumers_edges_go_stale_then_are_purged(tx) -> None:
    db, cursor = tx
    seed = _seed(cursor)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    _age_edges(cursor, seed["tenant"], "1 hour")

    # The producer's own transaction re-derives the family (CDG-3.1 hook on soft_delete_consumer).
    assert db.soft_delete_consumer(seed["consumers"]["mobile"], seed["tenant"]) is True
    edges = _edges(cursor, seed["tenant"])
    mobile = [e for e in edges if e["from_id"] == seed["consumers"]["mobile"]]
    assert len(mobile) == 2 and all(e["stale_since"] is not None for e in mobile)
    assert all(e["stale_since"] is None for e in edges if e["from_id"] != seed["consumers"]["mobile"])

    page = list_edges(db, seed["tenant"], "consumer", seed["consumers"]["mobile"])
    assert page.total == 2 and all(edge["stale"] for edge in page.edges)
    incoming = list_edges(db, seed["tenant"], "project", seed["project"], direction="in")
    assert [edge["stale"] for edge in incoming.edges] == [False, False, True, True]  # stale last

    # A second run doesn't restamp them; 31 days on they are purged.
    stamped = [e["stale_since"] for e in mobile]
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    mobile_again = [e for e in _edges(cursor, seed["tenant"]) if e["from_id"] == seed["consumers"]["mobile"]]
    assert [e["stale_since"] for e in mobile_again] == stamped
    _age_edges(cursor, seed["tenant"], "31 days")
    counts = materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    assert counts["consumes"]["purged"] == 2
    assert not [e for e in _edges(cursor, seed["tenant"]) if e["from_id"] == seed["consumers"]["mobile"]]


def test_a_returning_source_revives_its_stale_edge(tx) -> None:
    _db, cursor = tx
    seed = _seed(cursor)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    _age_edges(cursor, seed["tenant"], "1 hour")
    cursor.execute("UPDATE apiome.consumer SET deleted_at = now() WHERE id = %s::uuid", (seed["consumers"]["batch"],))
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    _age_edges(cursor, seed["tenant"], "1 hour")
    cursor.execute("UPDATE apiome.consumer SET deleted_at = NULL WHERE id = %s::uuid", (seed["consumers"]["batch"],))
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    batch = [e for e in _edges(cursor, seed["tenant"]) if e["from_id"] == seed["consumers"]["batch"]]
    assert len(batch) == 1 and batch[0]["stale_since"] is None


def test_reads_are_bounded_and_report_truncation(tx) -> None:
    db, cursor = tx
    seed = _seed(cursor)
    materialize_on_cursor(cursor, seed["tenant"], ("consumes",))
    first = list_edges(db, seed["tenant"], "project", seed["project"], direction="in", limit=3)
    assert (len(first.edges), first.total, first.truncated) == (3, 4, True)
    last = list_edges(db, seed["tenant"], "project", seed["project"], direction="in", limit=3, offset=3)
    assert (len(last.edges), last.total, last.truncated) == (1, 4, False)
    past = list_edges(db, seed["tenant"], "project", seed["project"], direction="in", limit=3, offset=10)
    assert (len(past.edges), past.total, past.truncated) == (0, 4, False)
    # The other node kind spelling of a projects row finds the same edges.
    assert list_edges(db, seed["tenant"], "catalog_item", seed["project"], direction="in").total == 4
    served = list_edges(db, seed["tenant"], "project", seed["project"], direction="in", edge_kinds=("served_by",))
    assert served.total == 0
