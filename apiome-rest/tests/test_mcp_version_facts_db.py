"""MCP endpoint version facts against Postgres — DBP-1.17 (#7200).

V425 stores each snapshot's derived facts on ``mcp_endpoint_versions`` and the catalog reads them
instead of recomputing them from the capability items. These tests run against a real database
(they skip when none with V425 is reachable) and pin the ticket's acceptance criteria:

* a snapshot recorded through :meth:`Database.record_mcp_discovery_version` carries facts that
  the SQL recomputation (``apiome.verify_mcp_version_facts``) agrees with;
* the backfill is resumable, idempotent and verified the same way;
* **the reads return the same values** whether a snapshot's facts are stored or not — every
  catalog read is run on snapshots with no facts (the original expressions) and again after the
  backfill, and must give identical results;
* the catalog grid, the insight and the evolution series run at most two statements each;
* the write-once guard still refuses every other update of a snapshot row;
* similar servers and cross-tenant duplicate hints, now computed in SQL, match the Python that
  used to compute them.

Like the content-stamp suite these tests commit; the fixture deletes everything it created.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

import psycopg2
import pytest

from app.config import settings
from app.database import Database
from app.mcp_duplicate_detection import build_mcp_cross_tenant_hints
from app.mcp_insight_aggregation import (
    compute_capability_overlap,
    overlap_neighbors_from_rows,
)
from app.mcp_version_facts import VERSION_FACT_COLUMNS, derive_version_facts
from app.statement_stats import CountingDictCursor, capture

pytestmark = pytest.mark.requires_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _schema(count: int) -> Dict[str, Any]:
    return {"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(count)}}


def _tool(name: str, ordinal: int, *, annotations: Any = None, props: Optional[int] = 1) -> Dict[str, Any]:
    return {
        "item_type": "tool",
        "name": name,
        "description": f"Does {name}",
        "input_schema": _schema(props) if props is not None else None,
        "annotations": annotations,
        "raw": {"name": name},
        "ordinal": ordinal,
    }


def _item(kind: str, name: str, ordinal: int) -> Dict[str, Any]:
    return {"item_type": kind, "name": name, "description": None, "raw": {}, "ordinal": ordinal}


#: Capability surfaces chosen to exercise every branch of every fact.
SURFACES: Dict[str, List[Dict[str, Any]]] = {
    # every tool read-only; the widest tool has 6 properties
    "read-only": [
        _tool("get_weather", 0, annotations={"readOnlyHint": True}, props=6),
        _tool("get_forecast", 1, annotations={"readOnlyHint": True, "destructiveHint": False}, props=2),
        _item("resource", "cities", 0),
        _item("prompt", "summarize", 0),
    ],
    # one destructive tool among unannotated ones; 12 properties → "complex"
    "destructive": [
        _tool("delete_city", 0, annotations={"destructiveHint": True}, props=12),
        _tool("get_weather", 1, props=0),
        _tool("list_cities", 2, annotations={"readOnlyHint": True}),
        _item("resource_template", "city/{id}", 0),
    ],
    # hints that are not the JSON boolean, schemas that are not objects
    "odd": [
        _tool("a", 0, annotations={"destructiveHint": "true", "readOnlyHint": 1}, props=None),
        {**_tool("b", 1), "input_schema": {"properties": ["x", "y"]}},
        {**_tool("c", 2), "input_schema": ["not", "an", "object"], "annotations": ["readOnlyHint"]},
    ],
    # no tools at all
    "no-tools": [_item("resource", "r1", 0), _item("resource", "r2", 1), _item("prompt", "p", 0)],
    # nothing
    "empty": [],
}

CHANGES = [
    {"change_type": "added", "item_type": "tool", "item_name": "x", "detail": {}},
    {"change_type": "removed", "item_type": "tool", "item_name": "y", "detail": {}},
    {"change_type": "modified", "item_type": "tool", "item_name": "z", "detail": {"field": "description"}},
    {"change_type": "added", "item_type": "prompt", "item_name": "p", "detail": {}},
]


@pytest.fixture
def env() -> Iterator[Dict[str, Any]]:
    """A committing connection with a :class:`Database` on it and an empty seeded tenant.

    Yields a dict with ``conn``, ``db``, ``tenant``, ``other_tenant`` (for cross-tenant reads),
    ``user`` and an ``endpoint(name, **columns)`` factory. Everything created is deleted afterwards.
    """
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=CountingDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regproc('apiome.verify_mcp_version_facts') AS f, "
            "(SELECT id::text FROM apiome.users LIMIT 1) AS u"
        )
        found = cur.fetchone()
    conn.commit()
    if not found["f"] or not found["u"]:
        conn.close()
        pytest.skip("V425 not applied or no user to own the seed endpoints")

    suffix = uuid.uuid4().hex[:10]
    tenants = []
    with conn.cursor() as cur:
        for label in ("facts", "facts-other"):
            cur.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"{label} {suffix}", f"{label}-{suffix}"),
            )
            tenants.append(cur.fetchone()["id"])
    conn.commit()

    db = Database()
    db.connection = conn
    ctx: Dict[str, Any] = {
        "conn": conn,
        "db": db,
        "tenant": tenants[0],
        "other_tenant": tenants[1],
        "user": found["u"],
        "suffix": suffix,
    }

    def endpoint(name: str, *, tenant: Optional[str] = None, **columns: Any) -> str:
        values = {
            "tenant_id": tenant or ctx["tenant"],
            "creator_id": ctx["user"],
            "name": name,
            "slug": f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
            "endpoint_url": f"https://{name.lower().replace(' ', '-')}.{suffix}.example.com/mcp",
            "transport": "streamable_http",
            **columns,
        }
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO apiome.mcp_endpoints ({names}) VALUES ({marks}) RETURNING id::text AS id",
                tuple(values.values()),
            )
            created = cur.fetchone()["id"]
        conn.commit()
        return created

    ctx["endpoint"] = endpoint
    try:
        yield ctx
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.mcp_endpoints WHERE tenant_id = ANY(%s::uuid[])", (tenants,))
            cur.execute("DELETE FROM apiome.tenants WHERE id = ANY(%s::uuid[])", (tenants,))
        conn.commit()
        conn.close()


def _record(ctx: Dict[str, Any], endpoint_id: str, surface: str, *, changes: int = 0, at: int = 0) -> str:
    """Record a snapshot through the real write path; returns its id."""
    result = ctx["db"].record_mcp_discovery_version(
        endpoint_id,
        version_row={"protocol_version": "2025-06-18", "server_name": surface, "surface_fingerprint": f"fp-{surface}"},
        capability_rows=[dict(row) for row in SURFACES[surface]],
        change_rows=[dict(row) for row in CHANGES[:changes]],
        discovered_at=T0 + timedelta(minutes=at),
    )
    return str(result["version_id"])


def _legacy_snapshot(ctx: Dict[str, Any], endpoint_id: str, surface: str, *, changes: int = 0, seq: int = 1) -> str:
    """Insert a snapshot the way one written before V425 looks: rows present, no facts."""
    conn = ctx["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.mcp_endpoint_versions "
            "(endpoint_id, version_seq, version_tag, protocol_version, server_name, surface_fingerprint, "
            "discovered_at) "
            "VALUES (%s::uuid, %s, %s, '2025-06-18', %s, %s, %s) RETURNING id::text AS id",
            (endpoint_id, seq, f"legacy-{seq}", surface, f"fp-{surface}", T0 + timedelta(minutes=seq)),
        )
        version_id = cur.fetchone()["id"]
        for row in SURFACES[surface]:
            cur.execute(
                "INSERT INTO apiome.mcp_capability_items "
                "(version_id, item_type, name, description, input_schema, annotations, raw, ordinal) "
                "VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)",
                (
                    version_id,
                    row["item_type"],
                    row["name"],
                    row.get("description"),
                    json.dumps(row["input_schema"]) if row.get("input_schema") is not None else None,
                    json.dumps(row["annotations"]) if row.get("annotations") is not None else None,
                    json.dumps(row.get("raw") or {}),
                    row["ordinal"],
                ),
            )
        for change in CHANGES[:changes]:
            cur.execute(
                "INSERT INTO apiome.mcp_version_changes (version_id, change_type, item_type, item_name, detail) "
                "VALUES (%s::uuid, %s, %s, %s, %s::jsonb)",
                (
                    version_id,
                    change["change_type"],
                    change["item_type"],
                    change["item_name"],
                    json.dumps(change["detail"]),
                ),
            )
        cur.execute(
            "UPDATE apiome.mcp_endpoints SET current_version_id = %s::uuid, last_discovered_at = %s, "
            "last_discovery_status = 'changed' WHERE id = %s::uuid",
            (version_id, T0, endpoint_id),
        )
    conn.commit()
    return version_id


def _facts(ctx: Dict[str, Any], version_id: str) -> Dict[str, Any]:
    with ctx["conn"].cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(VERSION_FACT_COLUMNS)} FROM apiome.mcp_endpoint_versions WHERE id = %s::uuid",
            (version_id,),
        )
        row = dict(cur.fetchone())
    ctx["conn"].commit()
    return row


def _mismatches(ctx: Dict[str, Any], version_ids: List[str]) -> List[Dict[str, Any]]:
    """Rows of ``apiome.verify_mcp_version_facts`` for the given snapshots."""
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "SELECT * FROM apiome.verify_mcp_version_facts(2000000) WHERE version_id = ANY(%s::uuid[])",
            (version_ids,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    ctx["conn"].commit()
    return rows


def _sql(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
    ctx["conn"].commit()
    return rows


# ───────────────────────────── written once, with the row ─────────────────────────────


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_a_recorded_snapshot_carries_the_facts_python_derived_and_sql_agrees(env, surface) -> None:
    version = _record(env, env["endpoint"](f"S {surface}"), surface, changes=3)
    assert _facts(env, version) == derive_version_facts(SURFACES[surface], CHANGES[:3])
    assert _mismatches(env, [version]) == [], "the SQL recomputation disagrees with app.mcp_version_facts"


def test_the_recorded_facts_are_what_the_surfaces_say(env) -> None:
    read_only = _facts(env, _record(env, env["endpoint"]("RO"), "read-only"))
    assert (read_only["tool_count"], read_only["resource_count"], read_only["prompt_count"]) == (2, 1, 1)
    assert (read_only["has_destructive"], read_only["read_only_only"], read_only["max_tool_props"]) == (False, True, 6)

    destructive = _facts(env, _record(env, env["endpoint"]("D"), "destructive", changes=4))
    assert (destructive["has_destructive"], destructive["read_only_only"]) == (True, False)
    assert (destructive["max_tool_props"], destructive["resource_template_count"], destructive["change_count"]) == (
        12,
        1,
        4,
    )

    odd = _facts(env, _record(env, env["endpoint"]("O"), "odd"))
    # None of the three "odd" tools has a properties object, so the widest has 0 — not NULL:
    # the snapshot does have tools.
    assert (odd["tool_count"], odd["has_destructive"], odd["read_only_only"], odd["max_tool_props"]) == (
        3,
        False,
        False,
        0,
    )

    no_tools = _facts(env, _record(env, env["endpoint"]("N"), "no-tools"))
    assert (no_tools["tool_count"], no_tools["read_only_only"], no_tools["max_tool_props"]) == (0, False, None)


# ───────────────────────────── backfill ─────────────────────────────


def test_the_backfill_derives_legacy_snapshots_and_is_verified(env) -> None:
    versions = [
        _legacy_snapshot(env, env["endpoint"](f"L {surface}"), surface, changes=index % 4)
        for index, surface in enumerate(sorted(SURFACES))
    ]
    assert all(_facts(env, v)["tool_count"] is None for v in versions)
    assert _mismatches(env, versions) == [], "a snapshot with no facts is not a mismatch"

    derived = _sql(env, "SELECT apiome.derive_mcp_version_facts(%s::uuid[]) AS n", (versions,))[0]["n"]
    assert derived == len(versions)
    for index, (version, surface) in enumerate(zip(versions, sorted(SURFACES))):
        assert _facts(env, version) == derive_version_facts(SURFACES[surface], CHANGES[: index % 4]), surface
    assert _mismatches(env, versions) == []


def test_the_backfill_is_resumable_and_idempotent(env) -> None:
    versions = [_legacy_snapshot(env, env["endpoint"](f"R{i}"), "destructive") for i in range(5)]

    def pending() -> int:
        return _sql(
            env,
            "SELECT count(*) AS n FROM apiome.mcp_endpoint_versions WHERE id = ANY(%s::uuid[]) AND tool_count IS NULL",
            (versions,),
        )[0]["n"]

    assert _sql(env, "SELECT apiome.backfill_mcp_version_facts(0) AS n")[0]["n"] == 0
    assert pending() == 5

    # Each call is its own transaction and does at most its limit; stopping after any of them
    # loses nothing — the next call continues where the snapshots still lack facts.
    calls = 0
    while pending():
        done = _sql(env, "SELECT apiome.backfill_mcp_version_facts(2) AS n")[0]["n"]
        assert 0 < done <= 2
        calls += 1
        assert calls < 10_000, "the backfill does not make progress"
    assert calls >= 3
    assert _mismatches(env, versions) == []

    # Deriving again changes nothing and does not trip the write-once guard.
    before = [_facts(env, v) for v in versions]
    assert _sql(env, "SELECT apiome.derive_mcp_version_facts(%s::uuid[]) AS n", (versions,))[0]["n"] == 0
    assert [_facts(env, v) for v in versions] == before


def test_a_wrong_stored_fact_is_reported_by_the_verification(env) -> None:
    """The check is real: a snapshot inserted with facts that do not match its items is listed."""
    endpoint = env["endpoint"]("Wrong")
    version = _sql(
        env,
        "INSERT INTO apiome.mcp_endpoint_versions (endpoint_id, version_seq, version_tag, discovered_at, "
        "tool_count, resource_count, resource_template_count, prompt_count, has_destructive, read_only_only, "
        "max_tool_props, change_count) VALUES (%s::uuid, 1, 'w', %s, 7, 0, 0, 0, true, false, 3, 0) "
        "RETURNING id::text AS id",
        (endpoint, T0),
    )[0]["id"]
    rows = _mismatches(env, [version])
    assert len(rows) == 1
    assert rows[0]["stored"]["tool_count"] == 7 and rows[0]["recomputed"]["tool_count"] == 0
    assert rows[0]["stored"]["has_destructive"] is True and rows[0]["recomputed"]["has_destructive"] is False


# ───────────────────────────── the write-once guard ─────────────────────────────


@pytest.mark.parametrize(
    "assignment",
    [
        "server_title = 'edited'",
        "tool_count = 99",
        "tool_count = NULL",
        "has_destructive = NOT has_destructive",
        "change_count = change_count + 1",
        "discovered_at = now()",
    ],
)
def test_a_derived_snapshot_cannot_be_updated(env, assignment) -> None:
    version = _record(env, env["endpoint"]("G"), "destructive")
    with pytest.raises(psycopg2.Error) as raised:
        _sql(env, f"UPDATE apiome.mcp_endpoint_versions SET {assignment} WHERE id = %s::uuid", (version,))
    env["conn"].rollback()
    assert "immutable" in str(raised.value)
    assert raised.value.pgcode == "23001"  # restrict_violation, as the V128 guard raised


def test_facts_cannot_be_filled_together_with_another_change(env) -> None:
    version = _legacy_snapshot(env, env["endpoint"]("G2"), "read-only")
    with pytest.raises(psycopg2.Error):
        _sql(
            env,
            "UPDATE apiome.mcp_endpoint_versions SET tool_count = 2, resource_count = 1, resource_template_count = 0, "
            "prompt_count = 1, has_destructive = false, read_only_only = true, max_tool_props = 6, change_count = 0, "
            "server_title = 'smuggled' WHERE id = %s::uuid",
            (version,),
        )
    env["conn"].rollback()
    assert _facts(env, version)["tool_count"] is None


def test_a_legacy_snapshot_without_facts_still_cannot_be_edited(env) -> None:
    version = _legacy_snapshot(env, env["endpoint"]("G3"), "read-only")
    with pytest.raises(psycopg2.Error):
        _sql(env, "UPDATE apiome.mcp_endpoint_versions SET server_title = 'x' WHERE id = %s::uuid", (version,))
    env["conn"].rollback()


# ───────────────────────────── same values, fewer statements ─────────────────────────────


def _catalog(ctx: Dict[str, Any]) -> List[str]:
    """A small catalog of legacy snapshots (no facts yet) across categories, grades and tags."""
    conn = ctx["conn"]
    versions = []
    for index, surface in enumerate(sorted(SURFACES) * 2):
        endpoint = ctx["endpoint"](
            f"Server {index:02d}",
            category=("weather", "finance", None)[index % 3],
            transport=("streamable_http", "sse")[index % 2],
            published=index % 2 == 0,
            consecutive_failures=1 if index == 4 else 0,
        )
        versions.append(_legacy_snapshot(ctx, endpoint, surface, changes=index % 5))
        with conn.cursor() as cur:
            if index % 3 != 2:
                cur.execute(
                    "INSERT INTO apiome.mcp_version_scores (version_id, score, grade, report) "
                    "VALUES (%s::uuid, %s, %s, '{}'::jsonb)",
                    (versions[-1], 50 + index * 4, "ABCDF"[index % 5]),
                )
            for tag in ("beta", "core")[: index % 3]:
                cur.execute(
                    "INSERT INTO apiome.mcp_endpoint_tags (endpoint_id, tenant_id, tag) "
                    "VALUES (%s::uuid, %s::uuid, %s)",
                    (endpoint, ctx["tenant"], tag),
                )
        conn.commit()
    ctx["endpoint"]("Never discovered")
    return versions


def _reads(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Every catalog read the ticket changed, as plain comparable data."""
    db, tenant = ctx["db"], ctx["tenant"]
    first = db.browse_mcp_endpoints(tenant)
    insight = db.get_mcp_catalog_insight(tenant)
    insight["tool_count_rows"] = sorted(row["tool_count"] for row in insight["tool_count_rows"])
    reads = {
        "browse": first,
        "browse page": db.browse_mcp_endpoints(tenant, limit=4, cursor=[first[2]["name"], str(first[2]["id"])]),
        "browse filtered": db.browse_mcp_endpoints(
            tenant, categories=["weather", "uncategorized"], tags=["beta", "untagged"]
        ),
        "facets": db.search_mcp_catalog_faceted(tenant, limit=5),
        "facets safety": db.search_mcp_catalog_faceted(tenant, safety=["has_destructive", "read_only_only"]),
        "facets complexity": db.search_mcp_catalog_faceted(
            tenant, complexity=["complex", "unknown"], grades=["A", "ungraded"]
        ),
        "facets none": db.search_mcp_catalog_faceted(tenant, categories=["nothing-here"]),
        "facets many": db.search_mcp_catalog_faceted(
            tenant,
            transports=["sse"],
            health=["healthy", "failing", "undiscovered"],
            tags=["core", "untagged"],
            visibility="private",
        ),
        "insight": insight,
        "evolution": [db.get_mcp_evolution_series(str(row["id"])) for row in first],
    }
    return json.loads(json.dumps(reads, default=str, sort_keys=True))


def test_every_read_returns_the_same_values_before_and_after_the_facts_are_stored(env) -> None:
    """The acceptance criterion: same values as before on the MCP fixtures.

    Before the backfill every fact is recomputed by the original expressions; afterwards every
    fact is read from its column. The two passes must be indistinguishable.
    """
    versions = _catalog(env)
    recomputed = _reads(env)

    assert _sql(env, "SELECT apiome.derive_mcp_version_facts(%s::uuid[]) AS n", (versions,))[0]["n"] == len(versions)
    stored = _reads(env)

    assert stored == recomputed
    # The fixture is not trivially empty: the interesting buckets are populated.
    facets = stored["facets"]
    assert facets["total"] == len(versions) + 1
    assert facets["safety_counts"]["has_destructive"] == 2 and facets["safety_counts"]["read_only_only"] == 2
    assert {row["label"] for row in facets["complexity_rows"]} == {"simple", "moderate", "complex", "unknown"}
    assert stored["facets none"]["total"] == 0 and stored["facets none"]["grade_rows"] == []
    assert stored["facets none"]["safety_counts"] == {"has_destructive": 0, "read_only_only": 0, "untagged": 0}
    assert stored["insight"]["endpoint_count"] == len(versions) + 1
    assert len(stored["insight"]["change_leader_rows"]) == 8
    assert stored["browse"][-1]["name"] == "Server 09" or stored["browse"][0]["name"] == "Never discovered"


def test_a_never_discovered_endpoint_reads_as_empty(env) -> None:
    env["endpoint"]("Lonely")
    row = env["db"].browse_mcp_endpoints(env["tenant"])[0]
    assert (row["tool_count"], row["resource_count"], row["prompt_count"]) == (0, 0, 0)
    assert (row["has_destructive"], row["read_only_only"], row["complexity_band"]) == (False, False, "unknown")
    assert row["health"] == "undiscovered"


def test_the_catalog_reads_stay_within_two_statements(env) -> None:
    """The acceptance criterion: the grid, the insight and the evolution chart, two statements at most."""
    versions = _catalog(env)
    _sql(env, "SELECT apiome.derive_mcp_version_facts(%s::uuid[])", (versions,))
    db, tenant = env["db"], env["tenant"]
    endpoint = str(db.browse_mcp_endpoints(tenant)[1]["id"])

    budgets = {
        "catalog grid (browse)": (1, lambda: db.browse_mcp_endpoints(tenant)),
        "catalog grid (faceted search)": (2, lambda: db.search_mcp_catalog_faceted(tenant, safety=["has_destructive"])),
        "insight dashboard": (2, lambda: db.get_mcp_catalog_insight(tenant)),
        "evolution chart series": (1, lambda: db.get_mcp_evolution_series(endpoint)),
        "evolution chart (series + change rows)": (
            2,
            lambda: (db.get_mcp_evolution_series(endpoint), db.get_mcp_version_changes_for_endpoint(endpoint)),
        ),
        "similar servers": (2, lambda: db.get_mcp_similar_servers(tenant, endpoint)),
        "cross-tenant duplicate hints": (1, lambda: db.list_published_mcp_duplicate_hints(tenant)),
    }
    for label, (budget, call) in budgets.items():
        with capture() as stats:
            call()
        env["conn"].rollback()
        assert stats.count <= budget, f"{label}: {stats.count} statements > {budget}: {stats.statements}"


def test_the_statement_count_does_not_grow_with_the_catalog(env) -> None:
    db, tenant = env["db"], env["tenant"]

    def count() -> int:
        with capture() as stats:
            db.search_mcp_catalog_faceted(tenant)
            db.get_mcp_catalog_insight(tenant)
            db.browse_mcp_endpoints(tenant)
        env["conn"].rollback()
        return stats.count

    env["endpoint"]("One")
    small = count()
    _catalog(env)
    assert count() == small == 5


# ───────────────────────────── similarity and duplicates in SQL ─────────────────────────────


def test_similar_servers_in_sql_match_the_python_overlap(env) -> None:
    surfaces = {
        "Target": ["get_weather", "get_forecast", "list_cities", " Padded ", "MiXeD"],
        "Near": ["GET_WEATHER", "get_forecast", "list_cities", "padded"],
        "Mid": ["get_weather", "mixed", "a", "b", "c"],
        "Dup names": ["get_weather", "get_weather", "Get_Weather"],
        "Far": ["x", "y"],
        "Empty": [],
    }
    ids = {}
    for name, names in surfaces.items():
        ids[name] = env["endpoint"](name, category="weather")
        env["db"].record_mcp_discovery_version(
            ids[name],
            version_row={"server_name": name, "surface_fingerprint": f"fp-{name}"},
            capability_rows=[_tool(n, i) for i, n in enumerate(names)],
            change_rows=[],
            discovered_at=T0,
        )
    ids["Never"] = env["endpoint"]("Never")

    result = env["db"].get_mcp_similar_servers(env["tenant"], ids["Target"], limit=10, with_embeddings=False)
    got = overlap_neighbors_from_rows(result["target_capability_count"], result["overlap_rows"], limit=10)

    peers = [
        {"endpoint_id": ids[name], "name": name, "slug": None, "category": "weather", "capability_names": names}
        for name, names in surfaces.items()
        if name != "Target"
    ]
    expected = compute_capability_overlap(surfaces["Target"], peers, limit=10)
    assert [
        (n.endpoint_id, n.similarity, n.shared_count, n.candidate_capability_count, n.shared_capabilities) for n in got
    ] == [
        (n.endpoint_id, n.similarity, n.shared_count, n.candidate_capability_count, n.shared_capabilities)
        for n in expected
    ]
    assert [n.name for n in got] == ["Near", "Mid", "Dup names"]
    assert result["target_capability_count"] == 5
    assert result["embedding_rows"] == []

    # The limit is applied in the database, on the same ranking.
    top = env["db"].get_mcp_similar_servers(env["tenant"], ids["Target"], limit=1, with_embeddings=False)
    assert [row["name"] for row in top["overlap_rows"]] == ["Near"]

    # A target with no capabilities, and an endpoint of another tenant, have no neighbours.
    for target, tenant in ((ids["Never"], env["tenant"]), (ids["Target"], env["other_tenant"])):
        empty = env["db"].get_mcp_similar_servers(tenant, target, with_embeddings=False)
        assert empty == {"target_capability_count": 0, "overlap_rows": [], "embedding_rows": []}


def test_similar_servers_never_include_another_tenants_endpoint(env) -> None:
    mine = env["endpoint"]("Mine")
    theirs = env["endpoint"]("Theirs", tenant=env["other_tenant"])
    for endpoint in (mine, theirs):
        env["db"].record_mcp_discovery_version(
            endpoint,
            version_row={"server_name": "s"},
            capability_rows=[_tool("shared_tool", 0)],
            change_rows=[],
            discovered_at=T0,
        )
    result = env["db"].get_mcp_similar_servers(env["tenant"], mine, with_embeddings=True)
    assert result["target_capability_count"] == 1
    assert result["overlap_rows"] == [] and result["embedding_rows"] == []


def test_duplicate_hints_read_only_the_foreign_endpoints_that_can_match(env) -> None:
    db, tenant, other = env["db"], env["tenant"], env["other_tenant"]
    host = f"dup.{env['suffix']}.example.com"
    local = env["endpoint"]("Local", endpoint_url=f"https://{host}/mcp/")
    _record(env, local, "read-only")

    same_url = env["endpoint"](
        "Same URL", tenant=other, published=True, endpoint_url=f"HTTPS://user:pw@{host.upper()}:443/mcp"
    )
    same_surface = env["endpoint"]("Same surface", tenant=other, published=True)
    _record(env, same_surface, "read-only")
    unrelated = env["endpoint"]("Unrelated", tenant=other, published=True)
    _record(env, unrelated, "destructive")
    unpublished = env["endpoint"]("Unpublished twin", tenant=other, published=False, endpoint_url=f"https://{host}/mcp")
    stdio_local = env["endpoint"]("Local stdio", transport="stdio", endpoint_url=f"npx  server-{env['suffix']}")
    stdio_foreign = env["endpoint"](
        "Foreign stdio", tenant=other, published=True, transport="stdio", endpoint_url=f"npx  server-{env['suffix']}"
    )

    rows = db.list_published_mcp_duplicate_hints(tenant)
    returned = {str(row["id"]) for row in rows}
    assert returned == {same_url, same_surface, stdio_foreign}
    assert unrelated not in returned and unpublished not in returned
    assert {row["tenant_slug"] for row in rows} == {f"facts-other-{env['suffix']}"}
    assert sorted(row["name"] for row in rows) == ["Foreign stdio", "Same URL", "Same surface"]

    # The exact matching is unchanged, so the hints are the ones a full read of every published
    # endpoint would have produced.
    everything = _sql(
        env,
        "SELECT e.id, e.tenant_id, e.name, e.slug, e.endpoint_url, e.transport, t.slug AS tenant_slug, "
        "v.surface_fingerprint FROM apiome.mcp_endpoints e JOIN apiome.tenants t ON t.id = e.tenant_id "
        "LEFT JOIN apiome.mcp_endpoint_versions v ON v.id = e.current_version_id "
        "WHERE e.deleted_at IS NULL AND e.published = true AND e.tenant_id = %s::uuid "
        "ORDER BY t.slug, e.name, e.id",
        (other,),
    )
    candidates = db.list_mcp_duplicate_candidates(tenant)
    assert build_mcp_cross_tenant_hints(tenant, candidates, rows) == build_mcp_cross_tenant_hints(
        tenant, candidates, everything
    )
    kinds = {hint.kind for hint in build_mcp_cross_tenant_hints(tenant, candidates, rows)}
    assert kinds == {"exact_url", "identical_surface"}
    assert stdio_local  # the stdio pair matched through the trimmed URL key
