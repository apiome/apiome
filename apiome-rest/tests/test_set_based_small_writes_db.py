"""Set-based small writes against Postgres — DBP-1.7 (#7190).

Each write here used to send one statement per row; it now sends one statement for all of them.
The fake-cursor suite (``test_set_based_small_writes.py``) pins the statement counts; this one
runs the real SQL and pins what it leaves behind: the rows, and the results that used to be
built row by row (a list in ``RETURNING`` order, an inserted count under ``ON CONFLICT DO
NOTHING``, the "one row did not insert" early return).

Where the old loop is short enough to quote, the test replays it in a savepoint, rolls back, and
compares the set-based result with it. Every test is one transaction that is rolled back.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Sequence, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app.component_governance import plan_bulk_upgrade, upgrade_confirmation_token
from app.config import settings
from app.database import Database
from app.sdk_beacon import SdkBeaconBatch
from app.sdk_beacon_store import ingest_beacons
from app.version_path_copy import copy_paths_between_versions
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def _one(cur: Any, sql: str, params: Sequence[Any] = ()) -> Any:
    """Run ``sql`` and return the first column of its first row (``None`` without a row)."""
    cur.execute(sql, params)
    row = cur.fetchone()
    return next(iter(row.values())) if row else None


def _all(cur: Any, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    """Run ``sql`` and return every row as a dict."""
    cur.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


@pytest.fixture
def seeded() -> Iterator[Tuple[Database, Any, Dict[str, str]]]:
    """A tenant with a user, a project, a published revision (``v1``) and a draft (``v2``)."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.version_documents') AS t")
        if not probe.fetchone()["t"]:
            conn.close()
            pytest.skip("V403 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    suffix = uuid.uuid4().hex[:10]
    try:
        with conn.cursor() as cur:
            user = _one(
                cur,
                "INSERT INTO apiome.users (name, email, password, verified) VALUES ('o', %s,"
                " '', true) RETURNING id::text",
                (f"owner-{suffix}@example.com",),
            )
            tenant = _one(
                cur,
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text",
                (suffix, f"t-{suffix}"),
            )
            project = _one(
                cur,
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s,"
                " %s, 'Pets', %s) RETURNING id::text",
                (tenant, user, f"pets-{suffix}"),
            )
            v1 = _one(
                cur,
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)"
                " VALUES (%s, %s, '1.0.0', true, now()) RETURNING id::text",
                (project, user),
            )
            v2 = _one(
                cur,
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, published)"
                " VALUES (%s, %s, '2.0.0', false) RETURNING id::text",
                (project, user),
            )
            yield db, cur, {"tenant": tenant, "user": user, "project": project, "v1": v1, "v2": v2, "suffix": suffix}
    finally:
        conn.rollback()
        conn.close()


def _replay(cur: Any, work: Any) -> Any:
    """Run ``work()`` in a savepoint and roll it back, returning what ``work`` returned.

    Used to see what the old one-statement-per-row loop leaves behind without keeping it.
    """
    cur.execute("SAVEPOINT replay")
    try:
        return work()
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT replay")


# ---------------------------------------------------------------------------------------------
# An unnest UPDATE whose RETURNING order is the result
# ---------------------------------------------------------------------------------------------


def test_unpublish_moves_tags_and_reports_them_in_plan_order(seeded):
    db, cur, ids = seeded
    tags = {}
    for name, immutable in (("a", False), ("b", False), ("c", False), ("frozen", True)):
        tags[name] = _one(
            cur,
            "INSERT INTO apiome.version_tags (project_id, version_id, name, immutable) VALUES"
            " (%s, %s, %s, %s) RETURNING id::text",
            (ids["project"], ids["v1"], name, immutable),
        )
    # Not in id order; one immutable tag, one unknown tag and one tag named twice.
    plan = [
        {"id": tags["c"], "toVersionId": ids["v2"]},
        {"id": tags["frozen"], "toVersionId": ids["v2"]},
        {"id": tags["a"], "toVersionId": ids["v2"]},
        {"id": str(uuid.uuid4()), "toVersionId": ids["v2"]},
        {"id": tags["b"], "toVersionId": ids["v2"]},
        {"id": tags["a"], "toVersionId": ids["v2"]},
    ]

    def per_row() -> List[str]:
        moved = []
        for move in plan:
            cur.execute(
                """
                UPDATE apiome.version_tags
                SET version_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND version_id = %s AND project_id = %s AND immutable = false
                RETURNING id
                """,
                (move["toVersionId"], move["id"], ids["v1"], ids["project"]),
            )
            hit = cur.fetchone()
            if hit:
                moved.append(str(hit["id"]))
        return moved

    expected = _replay(cur, per_row)
    assert expected == [tags["c"], tags["a"], tags["b"]]

    result = db.unpublish_version(ids["v1"], ids["tenant"], ids["user"], reason="r", tag_moves=plan)

    assert result["moved_tag_ids"] == expected
    assert result["version"]["published"] is False
    where = {
        row["name"]: str(row["version_id"])
        for row in _all(
            cur, "SELECT name, version_id FROM apiome.version_tags WHERE project_id = %s", (ids["project"],)
        )
    }
    assert where == {"a": ids["v2"], "b": ids["v2"], "c": ids["v2"], "frozen": ids["v1"]}


def test_unpublish_without_tag_moves_moves_nothing(seeded):
    db, _, ids = seeded
    assert db.unpublish_version(ids["v1"], ids["tenant"], ids["user"])["moved_tag_ids"] == []


def _repository(cur: Any, ids: Dict[str, str]) -> str:
    """Register a repository for the tenant and return its id."""
    url = f"https://github.com/acme/{ids['suffix']}"
    return _one(
        cur,
        "INSERT INTO apiome.tenant_repositories (tenant_id, source, provider, clone_url, clone_url_normalized)"
        " VALUES (%s, 'public_url', 'github', %s, %s) RETURNING id::text",
        (ids["tenant"], url, url),
    )


def test_codeowners_are_stored_per_file_and_only_changes_count(seeded):
    db, cur, ids = seeded
    repository = _repository(cur, ids)
    for path, owners in (("a.yaml", ["@old"]), ("b.yaml", []), ("c.yaml", ["@same"]), ("other.yaml", ["@keep"])):
        cur.execute(
            "INSERT INTO apiome.tenant_repository_files (repository_id, branch, path, name, codeowners)"
            " VALUES (%s, 'main', %s, %s, %s::text[])",
            (repository, path, path, owners),
        )
    updates = [
        ("a.yaml", ["@x", "@y"]),
        ("b.yaml", ["@z"]),
        ("c.yaml", ["@same"]),
        ("gone.yaml", ["@q"]),
        ("a.yaml", []),
    ]

    def per_row() -> int:
        changed = 0
        for path, owners in updates:
            cur.execute(
                """
                UPDATE apiome.tenant_repository_files SET codeowners = %s::text[]
                WHERE repository_id = %s::uuid AND branch = %s AND path = %s
                  AND codeowners IS DISTINCT FROM %s::text[]
                """,
                (list(owners), repository, "main", path, list(owners)),
            )
            changed += cur.rowcount or 0
        return changed

    def stored() -> Dict[str, List[str]]:
        rows = _all(
            cur, "SELECT path, codeowners FROM apiome.tenant_repository_files WHERE repository_id = %s", (repository,)
        )
        return {row["path"]: list(row["codeowners"]) for row in rows}

    cur.execute("SAVEPOINT replay")
    per_row()
    expected = stored()
    cur.execute("ROLLBACK TO SAVEPOINT replay")

    # ``a.yaml`` is named twice: the loop wrote it twice (and counted both), the set-based write
    # stores its last owners once.
    assert db.set_tenant_repository_file_codeowners(repository, "main", updates) == 2
    assert stored() == expected == {"a.yaml": [], "b.yaml": ["@z"], "c.yaml": ["@same"], "other.yaml": ["@keep"]}
    # Owners keep their order, and an unchanged set writes nothing.
    assert db.set_tenant_repository_file_codeowners(repository, "main", [("b.yaml", ["@m", "@a"])]) == 1
    assert stored()["b.yaml"] == ["@m", "@a"]
    assert db.set_tenant_repository_file_codeowners(repository, "main", [("b.yaml", ["@m", "@a"])]) == 0


# ---------------------------------------------------------------------------------------------
# ON CONFLICT inserts whose count or survivor is the result
# ---------------------------------------------------------------------------------------------


def _toolset(cur: Any, ids: Dict[str, str]) -> str:
    """Give the published revision a toolset and return its id."""
    return _one(
        cur,
        "INSERT INTO apiome.agent_toolsets (tenant_id, version_id) VALUES (%s, %s) RETURNING id::text",
        (ids["tenant"], ids["v1"]),
    )


def _proposal(key: str, text: str = "new") -> Dict[str, Any]:
    return {
        "operation_key": "GET /pets",
        "target_kind": "tool",
        "target_key": key,
        "parameter_name": None,
        "original_description": None,
        "proposed_description": text,
        "model": "m",
    }


def test_enrichment_insert_counts_only_the_rows_it_inserted(seeded):
    db, cur, ids = seeded
    toolset = _toolset(cur, ids)
    assert db.insert_agent_toolset_enrichments(ids["tenant"], toolset, [_proposal("op:a", "first")]) == 1
    # ``op:a`` is stored already, ``op:b`` is named twice: two of the four are new.
    batch = [_proposal("op:a"), _proposal("op:b", "kept"), _proposal("op:b", "dropped"), _proposal("op:c")]

    def per_row() -> int:
        inserted = 0
        for proposal in batch:
            cur.execute(
                """
                INSERT INTO apiome.agent_toolset_enrichments
                    (toolset_id, operation_key, target_kind, target_key, parameter_name,
                     original_description, proposed_description, model)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (toolset_id, target_key) DO NOTHING
                """,
                (
                    toolset,
                    proposal["operation_key"],
                    proposal["target_kind"],
                    proposal["target_key"],
                    proposal.get("parameter_name"),
                    proposal.get("original_description"),
                    proposal["proposed_description"],
                    proposal["model"],
                ),
            )
            inserted += max(cur.rowcount or 0, 0)
        return inserted

    assert _replay(cur, per_row) == 2
    assert db.insert_agent_toolset_enrichments(ids["tenant"], toolset, batch) == 2
    stored = _all(
        cur,
        "SELECT target_key, proposed_description FROM apiome.agent_toolset_enrichments WHERE"
        " toolset_id = %s ORDER BY target_key",
        (toolset,),
    )
    assert [(row["target_key"], row["proposed_description"]) for row in stored] == [
        ("op:a", "first"),
        ("op:b", "kept"),
        ("op:c", "new"),
    ]
    assert db.insert_agent_toolset_enrichments(ids["tenant"], toolset, batch) == 0


def test_agent_toolset_is_stored_with_its_tools(seeded):
    db, cur, ids = seeded
    tools = [
        {"operation_key": f"GET /pets/{i}", "tool_name": f"get_pet_{i}", "write_op": False, "enabled": i % 2 == 0}
        for i in range(5)
    ]
    created = db.insert_agent_toolset(
        tenant_id=ids["tenant"], version_id=ids["v1"], enabled=True, target="prod", tools=tools, actor_id=ids["user"]
    )
    stored = _all(
        cur,
        "SELECT tool_name, enabled, updated_by::text AS updated_by FROM apiome.agent_toolset_tools"
        " WHERE toolset_id = %s ORDER BY tool_name",
        (created["id"],),
    )
    assert [(row["tool_name"], row["enabled"]) for row in stored] == [(f"get_pet_{i}", i % 2 == 0) for i in range(5)]
    assert {row["updated_by"] for row in stored} == {ids["user"]}
    # A version has one toolset: the second create writes nothing.
    assert (
        db.insert_agent_toolset(tenant_id=ids["tenant"], version_id=ids["v1"], enabled=True, target="prod", tools=tools)
        is None
    )


def test_branch_refresh_rules_keep_the_last_rule_of_a_repeated_pattern(seeded):
    db, cur, ids = seeded
    repository = _repository(cur, ids)
    first = [
        {
            "branch_pattern": "main",
            "refresh_enabled": True,
            "refresh_interval_seconds": 600,
            "target_version_line": "1.x",
        },
        {
            "branch_pattern": "old/*",
            "refresh_enabled": True,
            "refresh_interval_seconds": None,
            "target_version_line": None,
        },
    ]
    assert db.replace_repository_branch_refresh_rules(ids["tenant"], repository, first, created_by=ids["user"]) is True
    second = [
        {
            "branch_pattern": "main",
            "refresh_enabled": False,
            "refresh_interval_seconds": 900,
            "target_version_line": "2.x",
        },
        {
            "branch_pattern": "release/*",
            "refresh_enabled": True,
            "refresh_interval_seconds": 60,
            "target_version_line": None,
        },
        {
            "branch_pattern": "release/*",
            "refresh_enabled": False,
            "refresh_interval_seconds": None,
            "target_version_line": "3.x",
        },
    ]
    assert db.replace_repository_branch_refresh_rules(ids["tenant"], repository, second, created_by=None) is True
    stored = _all(
        cur,
        "SELECT branch_pattern, refresh_enabled, refresh_interval_seconds, target_version_line,"
        " created_by::text AS created_by"
        " FROM apiome.repository_branch_refresh_rule WHERE repository_id = %s ORDER BY branch_pattern",
        (repository,),
    )
    assert [tuple(row.values()) for row in stored] == [
        # The kept pattern is updated in place and keeps who created it.
        ("main", False, 900, "2.x", ids["user"]),
        # The repeated pattern keeps its last rule, as one upsert per rule left it.
        ("release/*", False, None, "3.x", None),
    ]


def test_webhook_ip_ranges_are_replaced_and_upserted(seeded):
    db, cur, ids = seeded
    provider = "bitbucket"  # V-checked vocabulary; the transaction is rolled back
    cur.execute("DELETE FROM apiome.webhook_provider_ip_range WHERE provider = %s", (provider,))
    first = [{"cidr": "10.0.0.0/8", "family": 4, "source": "provider"}, {"cidr": "10.1.0.0/16", "family": 4}]
    assert db.replace_webhook_provider_ip_ranges(provider, first) == 0
    created = _one(
        cur,
        "SELECT id::text FROM apiome.webhook_provider_ip_range WHERE provider = %s AND cidr = '10.0.0.0/8'",
        (provider,),
    )
    second = [
        {"cidr": "10.0.0.0/8", "family": 4, "source": "configured"},
        {"cidr": "2001:db8::/32", "family": 6, "source": "provider"},
        {"cidr": "2001:db8::/32", "family": 6, "source": "configured"},
    ]
    assert db.replace_webhook_provider_ip_ranges(provider, second) == 1
    stored = _all(
        cur,
        "SELECT id::text AS id, cidr, family, source FROM apiome.webhook_provider_ip_range"
        " WHERE provider = %s ORDER BY cidr",
        (provider,),
    )
    assert [(row["cidr"], row["family"], row["source"]) for row in stored] == [
        ("10.0.0.0/8", 4, "configured"),
        ("2001:db8::/32", 6, "configured"),
    ]
    assert stored[0]["id"] == created, "a surviving range is updated, not recreated"


# ---------------------------------------------------------------------------------------------
# set_version_original_documents: all parts or nothing
# ---------------------------------------------------------------------------------------------


def _objects(cur: Any, tenant: str, count: int) -> List[str]:
    """Store ``count`` document objects for ``tenant`` and return their ids."""
    return [
        _one(
            cur,
            "INSERT INTO apiome.document_objects (tenant_id, sha256, size_bytes, backend, storage_key)"
            " VALUES (%s, %s, 1, 'db', %s) RETURNING id::text",
            (tenant, uuid.uuid4().hex + uuid.uuid4().hex, f"k/{uuid.uuid4().hex}"),
        )
        for _ in range(count)
    ]


def _documents(cur: Any, version_id: str) -> List[Tuple[str, Any, str]]:
    """A revision's ``(role, part_path, object_id)`` rows, ordered."""
    rows = _all(
        cur,
        "SELECT role, part_path, object_id::text AS object_id FROM apiome.version_documents"
        " WHERE version_id = %s ORDER BY role, part_path",
        (version_id,),
    )
    return [(row["role"], row["part_path"], row["object_id"]) for row in rows]


def test_original_documents_write_every_part_with_one_statement(seeded):
    db, cur, ids = seeded
    manifest, a, b, c, a2 = _objects(cur, ids["tenant"], 5)
    parts = [("a.yaml", a), ("b.yaml", b), ("c.yaml", c)]
    assert db.set_version_original_documents(
        tenant_id=ids["tenant"], version_id=ids["v2"], original_object_id=manifest, parts=parts
    )
    assert _documents(cur, ids["v2"]) == [
        ("original", None, manifest),
        ("original_part", "a.yaml", a),
        ("original_part", "b.yaml", b),
        ("original_part", "c.yaml", c),
    ]
    kept = _one(
        cur,
        "SELECT id::text FROM apiome.version_documents WHERE version_id = %s AND part_path = 'b.yaml'",
        (ids["v2"],),
    )
    # A second write: ``a.yaml`` changes (and is named twice — the last one stays), ``b.yaml`` is
    # upserted in place, ``c.yaml`` is dropped.
    assert db.set_version_original_documents(
        tenant_id=ids["tenant"],
        version_id=ids["v2"],
        original_object_id=manifest,
        parts=[("a.yaml", c), ("b.yaml", b), ("a.yaml", a2)],
    )
    assert _documents(cur, ids["v2"]) == [
        ("original", None, manifest),
        ("original_part", "a.yaml", a2),
        ("original_part", "b.yaml", b),
    ]
    assert kept == _one(
        cur,
        "SELECT id::text FROM apiome.version_documents WHERE version_id = %s AND part_path = 'b.yaml'",
        (ids["v2"],),
    )


def test_original_documents_refuse_a_part_that_is_not_the_tenants(seeded):
    db, cur, ids = seeded
    manifest, a = _objects(cur, ids["tenant"], 2)
    (foreign,) = _objects(cur, str(uuid.uuid4()), 1)
    for parts in (
        [("a.yaml", a), ("b.yaml", foreign)],
        [("a.yaml", a), ("b.yaml", str(uuid.uuid4()))],
        # The object that is missing is the one a later duplicate would replace: still refused.
        [("a.yaml", foreign), ("a.yaml", a)],
    ):
        assert (
            db.set_version_original_documents(
                tenant_id=ids["tenant"], version_id=ids["v2"], original_object_id=manifest, parts=parts
            )
            is False
        )
    # Another tenant's revision is refused before anything is written.
    assert (
        db.set_version_original_documents(
            tenant_id=str(uuid.uuid4()), version_id=ids["v2"], original_object_id=manifest, parts=[("a.yaml", a)]
        )
        is False
    )


# ---------------------------------------------------------------------------------------------
# Parents with client-assigned ids and their children
# ---------------------------------------------------------------------------------------------


def _evidence_run(ids: Dict[str, str]) -> Dict[str, Any]:
    return {
        "tenant_id": ids["tenant"],
        "suite_digest": "sha256:" + "a" * 64,
        "suite_schema_version": "1",
        "suite_compiler_version": "1",
        "suite_case_count": 3,
        "target_slug": "prod",
        "target_environment": "production",
        "target_base_url": "https://api.example.com",
        "runner_name": "apiome-cli",
        "runner_version": "1.0.0",
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=3),
        "duration_ms": 3000,
        "outcome": "failed",
        "total_cases": 3,
        "passed_cases": 2,
        "failed_cases": 1,
    }


def _evidence_case(index: int, *, assertions: int, artifacts: int) -> Dict[str, Any]:
    return {
        "sequence": index,
        "case_id": f"case-{index}",
        "operation_key": f"GET /pets/{index}",
        "operation_name": None,
        "case_source": "generated",
        "http_method": "GET",
        "http_path": f"/pets/{index}",
        "outcome": "passed" if index else "failed",
        "failure_code": None if index else "status",
        "failure_message": None,
        "expected_status": "200",
        "actual_status": 200 if index else None,
        "started_at": NOW if index else None,
        "finished_at": NOW.isoformat() if index else None,
        "duration_ms": 10 * index,
        "attempts": 1,
        "assertions": [
            {
                "sequence": n,
                "kind": "status_code",
                "outcome": "passed",
                "subject": None,
                "expected": "200",
                "actual": f"{index}-{n}",
            }
            for n in range(assertions)
        ],
        "artifacts": [
            {
                "kind": "response",
                "label": f"case-{index}-{n}",
                "uri": f"s3://evidence/{index}/{n}",
                "redaction": {"n": n},
            }
            for n in range(artifacts)
        ],
    }


def test_verification_evidence_links_every_child_to_its_case(seeded):
    db, cur, ids = seeded
    cases = [
        _evidence_case(0, assertions=2, artifacts=1),
        _evidence_case(1, assertions=0, artifacts=0),
        _evidence_case(2, assertions=3, artifacts=2),
    ]
    run = db.insert_verification_evidence(
        run=_evidence_run(ids),
        operations=cases,
        artifacts=[{"kind": "log", "label": "run", "uri": "s3://evidence/run.log", "size_bytes": 12}],
    )
    run_id = str(run["id"])
    stored_cases = _all(
        cur,
        "SELECT id::text AS id, case_id, actual_status, started_at, duration_ms FROM apiome.verification_run_operation"
        " WHERE run_id = %s ORDER BY sequence",
        (run_id,),
    )
    assert [row["case_id"] for row in stored_cases] == ["case-0", "case-1", "case-2"]
    assert [row["actual_status"] for row in stored_cases] == [None, 200, 200]
    assert [row["started_at"] for row in stored_cases] == [None, NOW, NOW]
    assert len({row["id"] for row in stored_cases}) == 3
    by_case = {row["id"]: row["case_id"] for row in stored_cases}

    assertions = _all(
        cur,
        "SELECT operation_id::text AS operation_id, sequence, actual FROM apiome.verification_run_assertion"
        " WHERE run_id = %s ORDER BY actual",
        (run_id,),
    )
    assert [(by_case[row["operation_id"]], row["actual"]) for row in assertions] == [
        ("case-0", "0-0"),
        ("case-0", "0-1"),
        ("case-2", "2-0"),
        ("case-2", "2-1"),
        ("case-2", "2-2"),
    ]
    artifacts = _all(
        cur,
        "SELECT operation_id::text AS operation_id, label, redacted, redaction, size_bytes"
        " FROM apiome.verification_run_artifact WHERE run_id = %s ORDER BY label",
        (run_id,),
    )
    assert [(by_case.get(row["operation_id"]), row["label"], row["redaction"]) for row in artifacts] == [
        ("case-0", "case-0-0", {"n": 0}),
        ("case-2", "case-2-0", {"n": 0}),
        ("case-2", "case-2-1", {"n": 1}),
        (None, "run", {}),
    ]
    assert all(row["redacted"] is True for row in artifacts)


def test_verification_evidence_without_cases_writes_only_the_run(seeded):
    db, cur, ids = seeded
    run = db.insert_verification_evidence(run=_evidence_run(ids))
    assert _one(cur, "SELECT COUNT(*) FROM apiome.verification_run_operation WHERE run_id = %s", (str(run["id"]),)) == 0


def test_component_bulk_upgrade_replaces_every_selected_pin(seeded):
    db, cur, ids = seeded
    component = _one(
        cur,
        "INSERT INTO apiome.operational_components (tenant_id, name, kind) VALUES (%s, %s,"
        " 'parameter') RETURNING id::text",
        (ids["tenant"], f"Page{ids['suffix']}"),
    )
    revisions = {}
    for label in ("1.0.0", "2.0.0"):
        revisions[label] = _one(
            cur,
            "INSERT INTO apiome.operational_component_revisions"
            " (tenant_id, component_id, revision, canonical_payload, payload_digest, state)"
            " VALUES (%s, %s, %s, '{}'::jsonb, %s, 'published') RETURNING id::text",
            (ids["tenant"], component, label, f"sha256:{label}"),
        )
    drafts = [ids["v2"]]
    for label in ("3.0.0", "4.0.0"):
        drafts.append(
            _one(
                cur,
                "INSERT INTO apiome.versions (project_id, creator_id, version_id, published)"
                " VALUES (%s, %s, %s, false) RETURNING id::text",
                (ids["project"], ids["user"], label),
            )
        )
    pins = [
        _one(
            cur,
            "INSERT INTO apiome.version_component_pins (tenant_id, version_id, component_revision_id, local_name)"
            " VALUES (%s, %s, %s, %s) RETURNING id::text",
            (ids["tenant"], version, revisions["1.0.0"], f"Local{n}"),
        )
        for n, version in enumerate(drafts)
    ]
    target = revisions["2.0.0"]
    token = upgrade_confirmation_token(
        component, target, plan_bulk_upgrade(db.get_component_consumers(ids["tenant"], component), target)
    )
    selected = [pins[2], pins[0]]

    result = db.execute_component_bulk_upgrade(
        ids["tenant"], component, target, selected, confirmation_token=token, policy={"p": 1}, actor_id=ids["user"]
    )

    assert [entry["pinId"] for entry in result["upgraded"]] == selected
    assert [entry["versionId"] for entry in result["upgraded"]] == [drafts[2], drafts[0]]
    live = _all(
        cur,
        "SELECT id::text AS id, version_id::text AS version_id, component_revision_id::text AS revision, local_name,"
        " created_by::text AS created_by FROM apiome.version_component_pins"
        " WHERE tenant_id = %s AND deleted_at IS NULL ORDER BY local_name",
        (ids["tenant"],),
    )
    new_ids = [entry["newPinId"] for entry in result["upgraded"]]
    assert [(row["id"], row["version_id"], row["revision"], row["local_name"], row["created_by"]) for row in live] == [
        (new_ids[1], drafts[0], target, "Local0", ids["user"]),
        (pins[1], drafts[1], revisions["1.0.0"], "Local1", None),
        (new_ids[0], drafts[2], target, "Local2", ids["user"]),
    ]
    audit = _all(
        cur,
        "SELECT action, version_id::text AS version_id, detail FROM apiome.component_library_audit"
        " WHERE component_id = %s ORDER BY action, detail->>'pinId'",
        (component,),
    )
    assert [row["action"] for row in audit] == ["pin.upgrade", "pin.upgrade", "upgrade.bulk"]
    per_pin = {row["detail"]["pinId"]: row for row in audit[:2]}
    for entry in result["upgraded"]:
        row = per_pin[entry["pinId"]]
        assert row["version_id"] == entry["versionId"] and row["detail"]["newPinId"] == entry["newPinId"]
        assert row["detail"]["oldRevision"] == "1.0.0" and row["detail"]["newRevision"] == "2.0.0"
        assert row["detail"]["policy"] == {"p": 1}
    assert audit[2]["detail"]["pinCount"] == 2


# ---------------------------------------------------------------------------------------------
# Plain multi-row inserts: every row lands, in order, with the same values
# ---------------------------------------------------------------------------------------------


def test_role_permissions_and_catalog_tags_are_replaced(seeded):
    db, cur, ids = seeded
    role = _one(
        cur,
        "INSERT INTO apiome.roles (tenant_id, slug, name) VALUES (%s, %s, 'R') RETURNING id::text",
        (ids["tenant"], f"r-{ids['suffix']}"),
    )
    db.set_role_permissions(role, [("project", "read"), ("project", "write"), ("project", "read")])
    db.set_role_permissions(role, [("project", "read"), ("version", "publish"), ("project", "read")])
    grid = _all(cur, "SELECT resource, action FROM apiome.role_permissions WHERE role_id = %s ORDER BY 1, 2", (role,))
    assert [(row["resource"], row["action"]) for row in grid] == [("project", "read"), ("version", "publish")]
    db.set_role_permissions(role, [])
    assert _one(cur, "SELECT COUNT(*) FROM apiome.role_permissions WHERE role_id = %s", (role,)) == 0

    item = _one(
        cur,
        "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable) VALUES"
        " (%s, %s, 'Item', %s, false)"
        " RETURNING id::text",
        (ids["tenant"], ids["user"], f"item-{ids['suffix']}"),
    )
    for tags in (["beta", "public"], ["internal", "stable"]):
        assert db.set_catalog_item_categories(
            tenant_id=ids["tenant"], project_id=item, domain="finance", tags=tags, user_id=ids["user"]
        )
    stored = _all(
        cur,
        "SELECT tag, created_by::text AS created_by FROM apiome.artifact_tags WHERE project_id = %s ORDER BY tag",
        (item,),
    )
    assert [(row["tag"], row["created_by"]) for row in stored] == [("internal", ids["user"]), ("stable", ids["user"])]


def test_style_guide_rules_and_preservation_claims_are_replaced(seeded):
    db, cur, ids = seeded
    guide = _one(
        cur,
        "INSERT INTO apiome.style_guides (tenant_id, name) VALUES (%s, %s) RETURNING id::text",
        (ids["tenant"], f"g-{ids['suffix']}"),
    )
    builtin = [{"rule_id": f"rule-{n}", "enabled": n % 2 == 0, "severity": "warning"} for n in range(4)]
    custom = [
        {
            "rule_id": "custom-1",
            "severity": "error",
            "custom_def": {"given": "$.paths", "then": [{"function": "truthy"}]},
        },
        {"rule_id": "custom-2", "enabled": False, "severity": "warning", "custom_def": ["a", "b"]},
    ]
    assert db.replace_style_guide_builtin_rules(guide, ids["tenant"], builtin) is True
    assert db.replace_style_guide_custom_rules(guide, ids["tenant"], custom) is True
    stored = _all(
        cur,
        "SELECT rule_id, enabled, severity, custom_def FROM apiome.style_guide_rules WHERE"
        " guide_id = %s ORDER BY rule_id",
        (guide,),
    )
    assert [tuple(row.values()) for row in stored] == [
        ("custom-1", True, "error", {"given": "$.paths", "then": [{"function": "truthy"}]}),
        ("custom-2", False, "warning", ["a", "b"]),
        ("rule-0", True, "warning", None),
        ("rule-1", False, "warning", None),
        ("rule-2", True, "warning", None),
        ("rule-3", False, "warning", None),
    ]

    claims = [
        {"pointer": "/info/x-a", "value": {"k": [1, 2]}, "source_file": "a.yaml", "source_digest": "d"},
        {"pointer": "/info/x-b", "value": ["list", "value"]},
        {"pointer": "/info/x-c", "value": None},
        {"pointer": "/info/x-d", "value": "text"},
    ]
    assert db.replace_preservation_claims(ids["tenant"], ids["project"], ids["v2"], claims, ids["user"]) == 4
    stored = _all(
        cur,
        "SELECT pointer, payload, source_file, created_by::text AS created_by FROM apiome.version_preservation_claims"
        " WHERE version_id = %s AND deleted_at IS NULL ORDER BY pointer",
        (ids["v2"],),
    )
    assert [(row["pointer"], row["payload"], row["source_file"]) for row in stored] == [
        ("/info/x-a", {"k": [1, 2]}, "a.yaml"),
        ("/info/x-b", ["list", "value"], None),
        ("/info/x-c", None, None),
        ("/info/x-d", "text", None),
    ]
    assert {row["created_by"] for row in stored} == {ids["user"]}


def test_schema_suite_payloads_and_run_results_are_stored_in_order(seeded):
    db, cur, ids = seeded
    payloads = [
        {
            "name": f"p{n}",
            "payload_text": json.dumps({"n": n}),
            "validity_class": "valid" if n else "invalid",
            "synthetic": n == 1,
        }
        for n in range(3)
    ]
    suite = db.create_schema_test_suite(
        tenant_id=ids["tenant"],
        name=f"s-{ids['suffix']}",
        description=None,
        ref_kind="project",
        ref_artifact="pets",
        ref_artifact_id=None,
        ref_type=None,
        payloads=payloads,
    )
    stored = _all(
        cur,
        "SELECT id::text AS id, name, media_type, validity_class, synthetic, position FROM"
        " apiome.schema_test_suite_payloads"
        " WHERE suite_id = %s ORDER BY position",
        (str(suite["id"]),),
    )
    assert [tuple(row.values())[1:] for row in stored] == [
        ("p0", "application/json", "invalid", False, 0),
        ("p1", "application/json", "valid", True, 1),
        ("p2", "application/json", "valid", False, 2),
    ]
    results = [
        {
            "payload_id": stored[0]["id"],
            "payload_name": "p0",
            "expected_valid": False,
            "valid": False,
            "validated": True,
            "status": "passed",
            "findings": [{"path": "/n", "message": "bad"}],
        },
        {
            "payload_id": "not-a-uuid",
            "payload_name": "p1",
            "expected_valid": True,
            "valid": None,
            "status": "error",
            "message": "boom",
        },
    ]
    run = db.insert_schema_test_suite_run(
        suite_id=str(suite["id"]),
        tenant_id=ids["tenant"],
        suite_version=1,
        requested_ref="pets@1.0.0",
        resolved_revision_id=None,
        resolved_version_label=None,
        trigger="manual",
        status="completed",
        total=2,
        passed=1,
        failed=0,
        errored=1,
        regression=False,
        baseline_run_id=None,
        message=None,
        results=results,
    )
    stored_results = _all(
        cur,
        "SELECT payload_id::text AS payload_id, payload_name, valid, validated, status, findings, message, position"
        " FROM apiome.schema_test_suite_run_results WHERE run_id = %s ORDER BY position",
        (str(run["id"]),),
    )
    assert [tuple(row.values()) for row in stored_results] == [
        (stored[0]["id"], "p0", False, True, "passed", [{"path": "/n", "message": "bad"}], None, 0),
        (None, "p1", None, False, "error", [], "boom", 1),
    ]


def _endpoints(cur: Any, ids: Dict[str, str], count: int) -> List[str]:
    """Register ``count`` MCP endpoints for the tenant and return their ids."""
    return [
        _one(
            cur,
            "INSERT INTO apiome.mcp_endpoints (tenant_id, creator_id, name, slug, endpoint_url, transport)"
            " VALUES (%s, %s, %s, %s, 'https://mcp.example.com', 'streamable_http') RETURNING id::text",
            (ids["tenant"], ids["user"], f"e{n}", f"e{n}-{ids['suffix']}"),
        )
        for n in range(count)
    ]


def test_mcp_tags_collections_and_policy_tools(seeded):
    db, cur, ids = seeded
    e0, e1, e2 = _endpoints(cur, ids, 3)

    assert db.replace_mcp_endpoint_tags(ids["tenant"], e0, ["beta", "alpha"], ids["user"]) == ["alpha", "beta"]
    first = _one(cur, "SELECT created_at FROM apiome.mcp_endpoint_tags WHERE endpoint_id = %s AND tag = 'alpha'", (e0,))
    assert db.replace_mcp_endpoint_tags(ids["tenant"], e0, ["alpha", "gamma"], None) == ["alpha", "gamma"]
    assert first == _one(
        cur, "SELECT created_at FROM apiome.mcp_endpoint_tags WHERE endpoint_id = %s AND tag = 'alpha'", (e0,)
    )
    assert db.replace_mcp_endpoint_tags(ids["tenant"], e0, [], None) == []

    def members(collection_id: str) -> List[Tuple[str, int]]:
        rows = _all(
            cur,
            "SELECT endpoint_id::text AS endpoint_id, position FROM apiome.mcp_collection_members"
            " WHERE collection_id = %s ORDER BY position",
            (collection_id,),
        )
        return [(row["endpoint_id"], row["position"]) for row in rows]

    collection = db.create_mcp_collection(
        ids["tenant"],
        ids["user"],
        name="Core",
        slug=f"core-{ids['suffix']}",
        description=None,
        is_published=False,
        endpoint_ids=[e1, e0],
    )
    collection_id = str(collection["id"])
    assert collection["member_count"] == 2 and members(collection_id) == [(e1, 0), (e0, 1)]
    db.replace_mcp_collection_members(ids["tenant"], collection_id, [e2, e1])
    assert members(collection_id) == [(e2, 0), (e1, 1)]
    # ``e1`` is a member already and keeps its position; the batch names ``e0`` twice.
    db.add_mcp_collection_members(ids["tenant"], collection_id, [e1, e0, e0])
    assert members(collection_id) == [(e2, 0), (e1, 1), (e0, 3)]

    tools = [
        {"tool_id": "zeta", "in_ceiling": True, "default_enabled": False},
        {"tool_id": "alpha", "in_ceiling": True, "default_enabled": True, "anonymous_enabled": False},
    ]
    policy = db.replace_tenant_mcp_policy(
        ids["tenant"], default_mode="explicit", allow_anonymous_mcp=True, tools=tools, updated_by=ids["user"]
    )
    assert [
        (tool["tool_id"], tool["in_ceiling"], tool["default_enabled"], tool["anonymous_enabled"])
        for tool in policy["tools"]
    ] == [
        ("alpha", True, True, False),
        ("zeta", True, False, True),
    ]
    assert (
        _one(cur, "SELECT COUNT(*) FROM apiome.tenant_mcp_policy_changes WHERE tenant_id = %s", (ids["tenant"],)) == 1
    )


def test_mcp_discovery_version_stores_items_and_changes(seeded):
    db, cur, ids = seeded
    (endpoint,) = _endpoints(cur, ids, 1)
    items = [
        {
            "item_type": "tool",
            "name": f"tool-{n}",
            "title": None,
            "description": "d",
            "input_schema": {"type": "object", "required": ["a", "b"]} if n else None,
            "output_schema": None,
            "annotations": ["x"] if n == 2 else None,
            "raw": {"name": f"tool-{n}"} if n else None,
            "ordinal": n,
        }
        for n in range(3)
    ]
    changes = [
        {"change_type": "added", "item_type": "tool", "item_name": "tool-0", "detail": {"k": [1]}},
        {"change_type": "added", "item_type": "tool", "item_name": "tool-1", "detail": None},
    ]
    out = db.record_mcp_discovery_version(
        endpoint,
        version_row={"protocol_version": "2025-06-18"},
        capability_rows=items,
        change_rows=changes,
        discovered_at=NOW,
    )
    stored = _all(
        cur,
        "SELECT name, input_schema, annotations, raw, ordinal FROM apiome.mcp_capability_items"
        " WHERE version_id = %s ORDER BY ordinal",
        (out["version_id"],),
    )
    assert [tuple(row.values()) for row in stored] == [
        ("tool-0", None, None, {}, 0),
        ("tool-1", {"type": "object", "required": ["a", "b"]}, None, {"name": "tool-1"}, 1),
        ("tool-2", {"type": "object", "required": ["a", "b"]}, ["x"], {"name": "tool-2"}, 2),
    ]
    stored_changes = _all(
        cur,
        "SELECT item_name, detail FROM apiome.mcp_version_changes WHERE version_id = %s ORDER BY item_name",
        (out["version_id"],),
    )
    assert [tuple(row.values()) for row in stored_changes] == [("tool-0", {"k": [1]}), ("tool-1", {})]


def test_expired_async_jobs_are_summarised_then_deleted(seeded):
    db, cur, ids = seeded
    kind = f"k-{ids['suffix']}"
    jobs = [f"job-{ids['suffix']}-{n}" for n in range(3)]
    for n, job in enumerate(jobs):
        cur.execute(
            "INSERT INTO apiome.async_job (job_id, kind, tenant_slug, state, status, created_at, updated_at)"
            " VALUES (%s, %s, 't', 'completed', %s::jsonb, %s, %s)",
            (job, kind, json.dumps({"n": n}), NOW - timedelta(days=9), NOW - timedelta(days=8 - n)),
        )
    # One job was reaped before and came back: its history row is overwritten.
    cur.execute(
        "INSERT INTO apiome.async_job_history (job_id, kind, tenant_slug, state, created_at, finished_at)"
        " VALUES (%s, 'stale', 't', 'failed', %s, %s)",
        (jobs[1], NOW, NOW),
    )
    reaped = db.reap_expired_async_jobs(policies={(kind, "completed"): NOW})
    assert sorted(row["job_id"] for row in reaped) == jobs
    history = _all(
        cur,
        "SELECT job_id, kind, state, finished_at, summary FROM apiome.async_job_history WHERE"
        " job_id = ANY(%s) ORDER BY job_id",
        (jobs,),
    )
    assert [(row["job_id"], row["kind"], row["state"]) for row in history] == [(job, kind, "completed") for job in jobs]
    assert [row["finished_at"] for row in history] == [NOW - timedelta(days=8 - n) for n in range(3)]
    assert all(isinstance(row["summary"], dict) for row in history)
    assert _one(cur, "SELECT COUNT(*) FROM apiome.async_job WHERE job_id = ANY(%s)", (jobs,)) == 0


def test_merge_session_conflicts_keep_their_sort_order(seeded):
    db, cur, ids = seeded
    records = [
        {"path": " /pets ", "kinds": ["operation", "schema"]},
        {"path": "  ", "kinds": ["skipped"]},
        {"path": "/owners", "kinds": None},
    ]
    session = db.create_merge_session_for_preview(
        ids["project"], ids["tenant"], "feature", "main", None, ids["v1"], ids["v2"], ids["v1"], records, ids["user"]
    )
    stored = _all(
        cur,
        "SELECT path, kinds, sort_order FROM apiome.merge_session_conflicts WHERE"
        " merge_session_id = %s ORDER BY sort_order",
        (str(session["id"]),),
    )
    assert [tuple(row.values()) for row in stored] == [("/pets", ["operation", "schema"], 0), ("/owners", [], 2)]


def _binding(cur: Any, ids: Dict[str, str], repository: str, version: str) -> str:
    """Bind ``version`` to ``repository`` and return the binding id."""
    return _one(
        cur,
        "INSERT INTO apiome.draft_repository_bindings (tenant_id, project_id, version_id, repository_id, provider,"
        " repo_full_name, repo_url, ref, path, commit_sha, source_digest, created_by)"
        " VALUES (%s, %s, %s, %s, 'github', 'acme/pets', 'https://github.com/acme/pets',"
        " 'main', 'spec', %s, 'sha256:one', %s)"
        " RETURNING id::text",
        (ids["tenant"], ids["project"], version, repository, "a" * 40, ids["user"]),
    )


def test_removing_a_repository_releases_bindings_and_audits_each(seeded):
    db, cur, ids = seeded
    repository = _repository(cur, ids)
    third = _one(
        cur,
        "INSERT INTO apiome.versions (project_id, creator_id, version_id, published) VALUES"
        " (%s, %s, '3.0.0', false) RETURNING id::text",
        (ids["project"], ids["user"]),
    )
    bindings = {version: _binding(cur, ids, repository, version) for version in (ids["v2"], third)}
    for n in range(2):
        cur.execute(
            "INSERT INTO apiome.draft_binding_sync_candidates (binding_id, tenant_id, ref,"
            " from_commit_sha, from_digest,"
            " to_commit_sha, origin) VALUES (%s, %s, 'main', %s, 'sha256:one', %s, 'webhook')",
            (bindings[ids["v2"]], ids["tenant"], "a" * 40, f"{n}" * 40),
        )

    assert db.delete_tenant_repository(ids["tenant"], repository) is True

    assert (
        _one(
            cur,
            "SELECT COUNT(*) FROM apiome.draft_repository_bindings WHERE repository_id = %s AND released_at IS NULL",
            (repository,),
        )
        == 0
    )
    statuses = _all(
        cur, "SELECT status FROM apiome.draft_binding_sync_candidates WHERE tenant_id = %s", (ids["tenant"],)
    )
    assert [row["status"] for row in statuses] == ["superseded", "superseded"]
    audit = _all(
        cur,
        "SELECT version_id::text AS version_id, outcome, actor_id, detail FROM apiome.workflow_audit"
        " WHERE tenant_id = %s AND action = 'binding.released'",
        (ids["tenant"],),
    )
    by_version = {row["version_id"]: row for row in audit}
    assert set(by_version) == {ids["v2"], third}
    assert by_version[ids["v2"]]["detail"]["candidates_superseded"] == 2
    assert by_version[third]["detail"]["candidates_superseded"] == 0
    for version, row in by_version.items():
        assert row["outcome"] == "success" and row["actor_id"] is None
        assert row["detail"]["binding_id"] == bindings[version] and row["detail"]["repository_id"] == repository


def test_a_sync_plan_stores_its_conflicts_once_per_pointer(seeded):
    db, cur, ids = seeded
    binding = _binding(cur, ids, _repository(cur, ids), ids["v2"])
    conflicts = [
        {
            "pointer": "/info/version",
            "scope": "document",
            "base_value": "1",
            "git_value": {"a": [1]},
            "draft_value": ["x"],
            "source_line": 4,
        },
        {"pointer": "/info/title", "git_kind": "deletion", "base_value": None, "git_value": None, "draft_value": "T"},
        {"pointer": "/info/version", "base_value": "dropped"},
    ]
    produced = db.record_draft_sync_plan(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        version_id=ids["v2"],
        binding_id=binding,
        candidate_id=None,
        base_commit_sha="a" * 40,
        base_digest="sha256:one",
        git_commit_sha="b" * 40,
        git_digest="sha256:two",
        draft_digest="sha256:draft",
        plan_fingerprint="sha256:plan",
        status="conflicted",
        auto_applied_count=0,
        local_count=0,
        agreed_count=0,
        changes=[],
        conflicts=conflicts,
        conflicts_truncated=False,
        source_file="spec/openapi.yaml",
        source_member_count=1,
        guard="none",
        actor_id=ids["user"],
    )
    assert produced["created"] is True
    stored = _all(
        cur,
        "SELECT pointer, git_kind, base_value, git_value, draft_value, source_line FROM apiome.draft_sync_conflicts"
        " WHERE plan_id = %s ORDER BY pointer",
        (produced["plan_id"],),
    )
    assert [tuple(row.values()) for row in stored] == [
        ("/info/title", "deletion", None, None, "T", None),
        ("/info/version", "update", "1", {"a": [1]}, ["x"], 4),
    ]


def test_path_copy_carries_every_canvas(seeded):
    db, cur, ids = seeded
    paths = [
        _one(
            cur,
            "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, %s) RETURNING id::text",
            (ids["v1"], f"/p{n}"),
        )
        for n in range(3)
    ]
    for path in paths[:2]:
        cur.execute(
            "INSERT INTO apiome.version_path_canvas (version_path_id, canvas) VALUES (%s, %s::jsonb)",
            (path, json.dumps({"nodes": [{"id": path}], "edges": []})),
        )
    assert copy_paths_between_versions(cur, ids["v1"], ids["v2"])["paths"] == 3
    copied = _all(
        cur,
        "SELECT p.id::text AS id, p.pathname, c.canvas FROM apiome.version_path p"
        " LEFT JOIN apiome.version_path_canvas c ON c.version_path_id = p.id WHERE p.version_id"
        " = %s ORDER BY p.pathname",
        (ids["v2"],),
    )
    assert [row["pathname"] for row in copied] == ["/p0", "/p1", "/p2"]
    # Each copied canvas names its own (new) path id.
    assert [row["canvas"] for row in copied] == [
        {"nodes": [{"id": copied[0]["id"]}], "edges": []},
        {"nodes": [{"id": copied[1]["id"]}], "edges": []},
        None,
    ]
    assert set(paths).isdisjoint(row["id"] for row in copied)


def test_sdk_beacons_upsert_every_counter_in_one_report(seeded):
    db, cur, ids = seeded
    source = _one(
        cur,
        "INSERT INTO apiome.usage_source (tenant_id, project_id, kind, environment) VALUES (%s,"
        " %s, 'sdk_beacon', 'prod') RETURNING id::text",
        (ids["tenant"], ids["project"]),
    )

    def report(operations: Sequence[str]) -> None:
        events = [
            {
                "sdk_name": "pets-go",
                "sdk_version": "1.0.0",
                "api_version": "1.0.0",
                "spec_revision_id": ids["v1"],
                "operation_id": operation,
                "outcome": "ok",
                "count": 2,
            }
            for operation in operations
        ]
        ingest_beacons(db, tenant_id=ids["tenant"], source_ref=source, batch=SdkBeaconBatch(events=events), now=NOW)

    report(["getPet", "listPets", "getPet"])
    report(["getPet", "addPet"])
    stored = _all(
        cur,
        "SELECT operation_id, calls FROM apiome.usage_sdk_beacon_daily WHERE source_id = %s ORDER BY operation_id",
        (source,),
    )
    assert [(row["operation_id"], row["calls"]) for row in stored] == [("addPet", 2), ("getPet", 6), ("listPets", 2)]
