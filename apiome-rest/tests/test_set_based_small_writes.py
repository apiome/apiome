"""Set-based small writes send the same number of statements for 2 rows and for 200 — DBP-1.7 (#7190).

Each write below used to loop ``cursor.execute`` once per row. Every case runs the write twice
on a recording cursor, with 2 rows and with 200, and asserts that

* the statements are the same both times (same count, same text) — nothing grows with the rows;
* the parameters of the set-based statement carry every row.

The SQL itself runs against Postgres in ``test_set_based_small_writes_db.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import psycopg2.extensions
import pytest

from app import sdk_beacon_store
from app.component_governance import plan_bulk_upgrade, upgrade_confirmation_token
from app.database import Database
from app.sdk_beacon import SdkBeaconBatch
from app.version_path_copy import _copy_canvases

SIZES = (2, 200)
NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)

#: A route's rows: fixed, or computed from the statement's parameters.
Rows = Any
Route = Tuple[str, Rows]


def _id(n: int = 0) -> str:
    """A deterministic (version 4 shaped) UUID string for row ``n``."""
    return str(uuid.UUID(int=n + 1, version=4))


TENANT, USER, PROJECT, VERSION, OTHER = (_id(9000 + n) for n in range(5))


class RecordingCursor:
    """Records every statement and answers ``fetch*`` from the first route its SQL contains.

    Args:
        routes: ``(fragment, rows)`` pairs; ``rows`` is a list of dicts or a callable taking the
            statement's parameters. Double quotes are dropped before matching, so a route reads
            ``INSERT INTO apiome.t`` whether or not the statement quotes its identifiers. A
            statement no route matches answers no rows.
    """

    def __init__(self, routes: Sequence[Route] = ()) -> None:
        self.routes = list(routes)
        self.statements: List[Tuple[str, Any]] = []
        self.rowcount = 1
        self._pending: List[Dict[str, Any]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        text = " ".join(str(sql).split()).replace('"', "")
        self.statements.append((text, params))
        self._pending = []
        for fragment, rows in self.routes:
            if fragment in text:
                self._pending = list(rows(params) if callable(rows) else rows)
                break
        self.rowcount = len(self._pending) or 1

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._pending[0] if self._pending else None

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._pending)

    def find(self, fragment: str) -> List[Tuple[str, Any]]:
        """The recorded statements whose SQL contains ``fragment``."""
        return [(sql, params) for sql, params in self.statements if fragment in sql]


class RecordingConnection:
    """A connection that hands out one :class:`RecordingCursor` and counts commits."""

    class info:  # noqa: N801 - mirrors psycopg2's ``connection.info``
        transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

    def __init__(self, cursor: RecordingCursor) -> None:
        self._cursor = cursor
        self.autocommit = True
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *args: Any, **kwargs: Any) -> RecordingCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _database(cursor: RecordingCursor) -> Tuple[Database, RecordingConnection]:
    """A ``Database`` whose ``connect()`` returns a recording connection over ``cursor``."""
    database = Database()
    conn = RecordingConnection(cursor)
    database.connect = lambda: conn  # type: ignore[method-assign]
    return database, conn


#: One case: given a row count, run the write and return the cursor it ran on, the fragment that
#: names the set-based statement(s), and the per-row values every such statement must carry
#: (``{parameter index: expected list}``).
Case = Callable[[int], Tuple[RecordingCursor, str, Dict[int, List[Any]]]]
CASES: Dict[str, Case] = {}


def case(function: Case) -> Case:
    """Register a case under its function name (minus the ``_case_`` prefix)."""
    CASES[function.__name__.removeprefix("_case_")] = function
    return function


@case
def _case_suite_payloads(n: int):
    cursor = RecordingCursor()
    payloads = [{"name": f"p{i}", "payload_text": f"{{{i}}}"} for i in range(n)]
    Database._insert_suite_payload_rows(cursor, _id(1), TENANT, payloads)
    return cursor, "INSERT INTO apiome.schema_test_suite_payloads", {2: [f"p{i}" for i in range(n)], 8: list(range(n))}


@case
def _case_suite_run_results(n: int):
    cursor = RecordingCursor([("INSERT INTO apiome.schema_test_suite_runs", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    results = [
        {
            "payload_id": _id(i),
            "payload_name": f"p{i}",
            "expected_valid": True,
            "status": "passed",
            "findings": [{"i": i}],
        }
        for i in range(n)
    ]
    database.insert_schema_test_suite_run(
        suite_id=_id(2),
        tenant_id=TENANT,
        suite_version=1,
        requested_ref="r",
        resolved_revision_id=None,
        resolved_version_label=None,
        trigger="manual",
        status="completed",
        total=n,
        passed=n,
        failed=0,
        errored=0,
        regression=False,
        baseline_run_id=None,
        message=None,
        results=results,
    )
    return (
        cursor,
        "INSERT INTO apiome.schema_test_suite_run_results",
        {
            1: [_id(i) for i in range(n)],
            9: [json.dumps([{"i": i}]) for i in range(n)],
            11: list(range(n)),
        },
    )


@case
def _case_style_guide_builtin_rules(n: int):
    cursor = RecordingCursor([("UPDATE apiome.style_guides", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    rules = [{"rule_id": f"r{i}", "enabled": True, "severity": "error"} for i in range(n)]
    assert database.replace_style_guide_builtin_rules(_id(1), TENANT, rules) is True
    return cursor, "INSERT INTO apiome.style_guide_rules", {1: [f"r{i}" for i in range(n)]}


@case
def _case_style_guide_custom_rules(n: int):
    cursor = RecordingCursor([("UPDATE apiome.style_guides", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    rules = [{"rule_id": f"r{i}", "severity": "error", "custom_def": {"given": [i]}} for i in range(n)]
    assert database.replace_style_guide_custom_rules(_id(1), TENANT, rules) is True
    return (
        cursor,
        "INSERT INTO apiome.style_guide_rules",
        {
            1: [f"r{i}" for i in range(n)],
            4: [json.dumps({"given": [i]}) for i in range(n)],
        },
    )


@case
def _case_unpublish_tag_moves(n: int):
    # The database answers in reverse; the result must still follow the plan.
    cursor = RecordingCursor(
        [
            ("UPDATE apiome.versions v", [{"id": VERSION, "project_id": PROJECT}]),
            (
                "UPDATE apiome.version_tags",
                lambda params: [{"id": tag, "ord": i + 1} for i, tag in enumerate(params[0])][::-1],
            ),
        ]
    )
    database, _ = _database(cursor)
    moves = [{"id": _id(i), "toVersionId": OTHER} for i in range(n)]
    result = database.unpublish_version(VERSION, TENANT, USER, tag_moves=moves)
    assert result["moved_tag_ids"] == [_id(i) for i in range(n)]
    return cursor, "UPDATE apiome.version_tags", {0: [_id(i) for i in range(n)], 1: [OTHER] * n}


@case
def _case_role_permissions(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    database.set_role_permissions(_id(1), [(f"res{i}", "read") for i in range(n)])
    return cursor, "INSERT INTO apiome.role_permissions", {1: [f"res{i}" for i in range(n)], 2: ["read"] * n}


@case
def _case_catalog_item_tags(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    tags = [f"tag{i}" for i in range(n)]
    assert database.set_catalog_item_categories(
        tenant_id=TENANT, project_id=PROJECT, domain=None, tags=tags, user_id=USER
    )
    return cursor, "INSERT INTO apiome.artifact_tags", {2: tags, 3: [USER] * n}


@case
def _case_merge_session_conflicts(n: int):
    cursor = RecordingCursor([("INSERT INTO apiome.merge_sessions", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    database.get_project_core = lambda *args, **kwargs: {"id": PROJECT}  # type: ignore[method-assign]
    records = [{"path": f"/p{i}", "kinds": ["schema", str(i)]} for i in range(n)]
    session = database.create_merge_session_for_preview(
        PROJECT, TENANT, "feature", "main", None, VERSION, VERSION, OTHER, records, USER
    )
    assert session == {"id": _id(1)}
    return (
        cursor,
        "INSERT INTO apiome.merge_session_conflicts",
        {
            1: [f"/p{i}" for i in range(n)],
            2: [json.dumps(["schema", str(i)]) for i in range(n)],
            3: list(range(n)),
        },
    )


@case
def _case_branch_refresh_rules(n: int):
    cursor = RecordingCursor([("FROM apiome.tenant_repositories", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    rules = [{"branch_pattern": f"b{i}", "refresh_interval_seconds": i} for i in range(n)]
    assert database.replace_repository_branch_refresh_rules(TENANT, _id(1), rules, created_by=USER) is True
    return (
        cursor,
        "INSERT INTO apiome.repository_branch_refresh_rule",
        {2: [f"b{i}" for i in range(n)], 4: list(range(n))},
    )


@case
def _case_webhook_ip_ranges(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    ranges = [{"cidr": f"10.{i}.0.0/16", "family": 4} for i in range(n)]
    database.replace_webhook_provider_ip_ranges("github", ranges)
    return cursor, "INSERT INTO apiome.webhook_provider_ip_range", {1: [f"10.{i}.0.0/16" for i in range(n)], 2: [4] * n}


@case
def _case_file_codeowners(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    updates = [(f"f{i}.yaml", [f"@o{i}", "@all"]) for i in range(n)]
    database.set_tenant_repository_file_codeowners(_id(1), "main", updates)
    return (
        cursor,
        "UPDATE apiome.tenant_repository_files",
        {
            0: [f"f{i}.yaml" for i in range(n)],
            1: [json.dumps([f"@o{i}", "@all"]) for i in range(n)],
        },
    )


@case
def _case_mcp_endpoint_tags(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    database.list_mcp_endpoint_tags = lambda endpoint_id: []  # type: ignore[method-assign]
    tags = [f"tag{i}" for i in range(n)]
    database.replace_mcp_endpoint_tags(TENANT, _id(1), tags, USER)
    return cursor, "INSERT INTO apiome.mcp_endpoint_tags", {2: tags}


def _collection_database(cursor: RecordingCursor) -> Database:
    """A recording ``Database`` with the collection helpers that read elsewhere stubbed out."""
    database, _ = _database(cursor)
    database._next_available_collection_slug = lambda cur, tenant, slug: slug  # type: ignore[method-assign]
    database._validate_collection_endpoint_ids = lambda cur, tenant, endpoint_ids: None  # type: ignore[method-assign]
    database.list_mcp_collection_members = lambda tenant, collection: []  # type: ignore[method-assign]
    return database


@case
def _case_mcp_collection_create(n: int):
    cursor = RecordingCursor([("INSERT INTO apiome.mcp_collections", [{"id": _id(1)}])])
    endpoints = [_id(100 + i) for i in range(n)]
    row = _collection_database(cursor).create_mcp_collection(
        TENANT, USER, name="Core", slug="core", description=None, is_published=False, endpoint_ids=endpoints
    )
    assert row["member_count"] == n
    return cursor, "INSERT INTO apiome.mcp_collection_members", {2: endpoints, 3: list(range(n))}


@case
def _case_mcp_collection_replace_members(n: int):
    cursor = RecordingCursor([("SELECT 1 FROM apiome.mcp_collections", [{"?column?": 1}])])
    endpoints = [_id(100 + i) for i in range(n)]
    _collection_database(cursor).replace_mcp_collection_members(TENANT, _id(1), endpoints)
    return cursor, "INSERT INTO apiome.mcp_collection_members", {2: endpoints, 3: list(range(n))}


@case
def _case_mcp_collection_add_members(n: int):
    cursor = RecordingCursor(
        [("SELECT 1 FROM apiome.mcp_collections", [{"?column?": 1}]), ("MAX(position)", [{"max_pos": 4}])]
    )
    endpoints = [_id(100 + i) for i in range(n)]
    _collection_database(cursor).add_mcp_collection_members(TENANT, _id(1), endpoints)
    return cursor, "INSERT INTO apiome.mcp_collection_members", {2: endpoints, 3: [5 + i for i in range(n)]}


@case
def _case_tenant_mcp_policy_tools(n: int):
    def stored(params: Any) -> List[Dict[str, Any]]:
        columns = ("tenant_id", "tool_id", "in_ceiling", "default_enabled", "anonymous_enabled")
        return [dict(zip(columns, row)) for row in zip(*params)][::-1]

    cursor = RecordingCursor(
        [
            ("INSERT INTO apiome.tenant_mcp_policies", [{"default_mode": "explicit", "allow_anonymous_mcp": True}]),
            ("INSERT INTO apiome.tenant_mcp_policy_tools", stored),
        ]
    )
    database, _ = _database(cursor)
    database._fetch_tenant_mcp_policy_on_cursor = lambda cur, tenant: None  # type: ignore[method-assign]
    tools = [{"tool_id": f"tool{i:03d}", "in_ceiling": True, "default_enabled": i % 2 == 0} for i in range(n)]
    policy = database.replace_tenant_mcp_policy(
        TENANT, default_mode="explicit", allow_anonymous_mcp=True, tools=tools, updated_by=None
    )
    assert [tool["tool_id"] for tool in policy["tools"]] == [f"tool{i:03d}" for i in range(n)]
    return (
        cursor,
        "INSERT INTO apiome.tenant_mcp_policy_tools",
        {
            1: [f"tool{i:03d}" for i in range(n)],
            3: [i % 2 == 0 for i in range(n)],
        },
    )


@case
def _case_async_job_reaper(n: int):
    jobs = [
        {
            "job_id": f"j{i}",
            "kind": "export",
            "tenant_slug": "t",
            "state": "completed",
            "status": {},
            "extra": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        for i in range(n)
    ]
    cursor = RecordingCursor(
        [
            ("FOR UPDATE SKIP LOCKED", jobs),
            ("DELETE FROM apiome.async_job", [{"job_id": job["job_id"]} for job in jobs]),
        ]
    )
    database, _ = _database(cursor)
    assert len(database.reap_expired_async_jobs(policies={("export", "completed"): NOW}, limit=500)) == n
    return cursor, "INSERT INTO apiome.async_job_history", {0: [f"j{i}" for i in range(n)], 5: [NOW] * n}


@case
def _case_original_document_parts(n: int):
    cursor = RecordingCursor(
        [
            ("FOR UPDATE OF v", [{"id": VERSION, "has_original": False}]),
            ("AS matched", lambda params: [{"matched": len(params[0])}]),
        ]
    )
    database, _ = _database(cursor)
    parts = [(f"part{i}.yaml", _id(100 + i)) for i in range(n)]
    assert database.set_version_original_documents(
        tenant_id=TENANT, version_id=VERSION, original_object_id=_id(1), parts=parts
    )
    return cursor, "WITH wanted AS", {0: [path for path, _ in parts], 1: [object_id for _, object_id in parts]}


def test_original_documents_return_false_when_a_part_does_not_match():
    cursor = RecordingCursor(
        [
            ("FOR UPDATE OF v", [{"id": VERSION, "has_original": False}]),
            ("AS matched", lambda params: [{"matched": len(params[0]) - 1}]),
        ]
    )
    database, conn = _database(cursor)
    parts = [(f"part{i}.yaml", _id(100 + i)) for i in range(3)]
    assert not database.set_version_original_documents(
        tenant_id=TENANT, version_id=VERSION, original_object_id=_id(1), parts=parts
    )
    assert (conn.commits, conn.rollbacks) == (0, 1)


@case
def _case_preservation_claims(n: int):
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    database._preservation_version_row = lambda *args: {"id": VERSION, "published": False}  # type: ignore[method-assign]
    claims = [{"pointer": f"/x-{i}", "value": {"i": [i]}} for i in range(n)]
    assert database.replace_preservation_claims(TENANT, PROJECT, VERSION, claims, USER) == n
    return (
        cursor,
        "INSERT INTO apiome.version_preservation_claims",
        {
            2: [f"/x-{i}" for i in range(n)],
            3: [json.dumps({"i": [i]}) for i in range(n)],
        },
    )


def _evidence(n: int) -> Tuple[RecordingCursor, List[Dict[str, Any]]]:
    """Store a run of ``n`` cases, each with two assertions and one artifact, plus a run artifact."""
    cursor = RecordingCursor([("INSERT INTO apiome.verification_run (", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    cases = [
        {
            "sequence": i,
            "case_id": f"case{i}",
            "assertions": [{"sequence": k, "kind": "status_code", "message": f"{i}/{k}"} for k in range(2)],
            "artifacts": [{"kind": "log", "label": f"case{i}", "uri": f"s3://e/{i}"}],
        }
        for i in range(n)
    ]
    database.insert_verification_evidence(
        run={"tenant_id": TENANT}, operations=cases, artifacts=[{"kind": "report", "label": "run", "uri": "s3://e/run"}]
    )
    return cursor, cases


@case
def _case_verification_cases(n: int):
    cursor, _ = _evidence(n)
    return cursor, "INSERT INTO apiome.verification_run_operation", {4: [f"case{i}" for i in range(n)]}


@case
def _case_verification_assertions(n: int):
    cursor, _ = _evidence(n)
    ((_, case_params),) = cursor.find("INSERT INTO apiome.verification_run_operation")
    case_ids = case_params[0]
    assert len(set(case_ids)) == n
    return (
        cursor,
        "INSERT INTO apiome.verification_run_assertion",
        {
            2: [case_id for case_id in case_ids for _ in range(2)],
            10: [f"{i}/{k}" for i in range(n) for k in range(2)],
        },
    )


@case
def _case_verification_artifacts(n: int):
    cursor, _ = _evidence(n)
    ((_, case_params),) = cursor.find("INSERT INTO apiome.verification_run_operation")
    # Per-case artifacts in case order, then the run-level one (no case).
    return (
        cursor,
        "INSERT INTO apiome.verification_run_artifact",
        {
            2: list(case_params[0]) + [None],
            4: [f"case{i}" for i in range(n)] + ["run"],
            9: [True] * (n + 1),
        },
    )


@case
def _case_agent_toolset_tools(n: int):
    cursor = RecordingCursor(
        [("INSERT INTO apiome.agent_toolsets", [{"id": _id(1)}]), ("FROM apiome.agent_toolsets ts", [{"id": _id(1)}])]
    )
    database, _ = _database(cursor)
    tools = [{"operation_key": f"GET /{i}", "tool_name": f"t{i}", "write_op": False, "enabled": True} for i in range(n)]
    assert database.insert_agent_toolset(tenant_id=TENANT, version_id=VERSION, enabled=True, target="prod", tools=tools)
    return (
        cursor,
        "INSERT INTO apiome.agent_toolset_tools",
        {1: [f"GET /{i}" for i in range(n)], 2: [f"t{i}" for i in range(n)]},
    )


@case
def _case_agent_toolset_enrichments(n: int):
    # The database reports every other proposal as inserted: that is the count.
    cursor = RecordingCursor(
        [
            ("SELECT 1 AS found", [{"found": 1}]),
            (
                "INSERT INTO apiome.agent_toolset_enrichments",
                lambda params: [{"id": _id(i)} for i in range(0, len(params[0]), 2)],
            ),
        ]
    )
    database, _ = _database(cursor)
    proposals = [
        {
            "operation_key": "GET /",
            "target_kind": "tool",
            "target_key": f"k{i}",
            "proposed_description": "d",
            "model": "m",
        }
        for i in range(n)
    ]
    assert database.insert_agent_toolset_enrichments(TENANT, _id(1), proposals) == n // 2
    return cursor, "INSERT INTO apiome.agent_toolset_enrichments", {3: [f"k{i}" for i in range(n)]}


@case
def _case_released_binding_audit(n: int):
    bindings = [
        {"id": _id(100 + i), "project_id": PROJECT, "version_id": _id(500 + i), "ref": "main", "commit_sha": "abc"}
        for i in range(n)
    ]
    # Binding 0 had two pending candidates, binding 1 one, the rest none.
    superseded = [{"binding_id": _id(100)}, {"binding_id": _id(101)}, {"binding_id": _id(100)}]
    cursor = RecordingCursor(
        [
            ("UPDATE apiome.draft_repository_bindings", bindings),
            ("UPDATE apiome.draft_binding_sync_candidates", superseded),
        ]
    )
    database, _ = _database(cursor)
    assert database._release_bindings_for_repository(cursor, tenant_id=TENANT, repository_id=_id(1)) == n
    ((_, audit),) = cursor.find("INSERT INTO apiome.workflow_audit")
    details = [json.loads(detail) for detail in audit[6]]
    assert [detail["binding_id"] for detail in details] == [binding["id"] for binding in bindings]
    assert [detail["candidates_superseded"] for detail in details] == [2, 1] + [0] * (n - 2)
    ((_, candidate_params),) = cursor.find("UPDATE apiome.draft_binding_sync_candidates")
    assert candidate_params == ([binding["id"] for binding in bindings],)
    return cursor, "INSERT INTO apiome.workflow_audit", {2: [_id(500 + i) for i in range(n)], 5: [None] * n}


@case
def _case_draft_sync_conflicts(n: int):
    cursor = RecordingCursor([("INSERT INTO apiome.draft_sync_plans", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    conflicts = [{"pointer": f"/p/{i}", "git_value": {"i": i}} for i in range(n)]
    produced = database.record_draft_sync_plan(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        binding_id=_id(2),
        candidate_id=None,
        base_commit_sha="a",
        base_digest="b",
        git_commit_sha="c",
        git_digest="d",
        draft_digest="e",
        plan_fingerprint="f",
        status="conflicted",
        auto_applied_count=0,
        local_count=0,
        agreed_count=0,
        changes=[],
        conflicts=conflicts,
        conflicts_truncated=False,
        source_file="s",
        source_member_count=1,
        guard="none",
        actor_id=USER,
    )
    assert produced == {"plan_id": _id(1), "created": True}
    return (
        cursor,
        "INSERT INTO apiome.draft_sync_conflicts",
        {
            2: [f"/p/{i}" for i in range(n)],
            9: [json.dumps({"i": i}) for i in range(n)],
        },
    )


def _bulk_upgrade(n: int) -> Tuple[RecordingCursor, Dict[str, Any], List[Dict[str, Any]]]:
    """Upgrade ``n`` pins (one draft version each) of one component to its target revision."""
    component, old, target = _id(1), _id(2), _id(3)
    consumers = [
        {
            "pin_id": _id(100 + i),
            "local_name": f"L{i}",
            "version_id": _id(500 + i),
            "version_label": str(i),
            "published": False,
            "project_id": PROJECT,
            "project_name": "P",
            "revision_id": old,
            "revision": "1.0.0",
        }
        for i in range(n)
    ]
    cursor = RecordingCursor(
        [("FROM apiome.versions WHERE id = ANY", lambda params: [{"id": vid, "published": False} for vid in params[0]])]
    )
    database, _ = _database(cursor)
    database._cursor_component_revision_row = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "state": "published",
        "revision": "2.0.0",
        "component_name": "Page",
    }
    database._cursor_revision_sunset = lambda *args: False  # type: ignore[method-assign]
    database._cursor_component_consumers = lambda *args: consumers  # type: ignore[method-assign]
    token = upgrade_confirmation_token(component, target, plan_bulk_upgrade(consumers, target))
    result = database.execute_component_bulk_upgrade(
        TENANT,
        component,
        target,
        [row["pin_id"] for row in consumers],
        confirmation_token=token,
        policy={},
        actor_id=USER,
    )
    return cursor, result, consumers


@case
def _case_component_upgrade_pins(n: int):
    cursor, result, consumers = _bulk_upgrade(n)
    assert [entry["pinId"] for entry in result["upgraded"]] == [row["pin_id"] for row in consumers]
    ((_, locked),) = cursor.find("FROM apiome.versions WHERE id = ANY")
    assert locked == (sorted(row["version_id"] for row in consumers),)
    ((_, deleted),) = cursor.find("SET deleted_at = CURRENT_TIMESTAMP")
    assert deleted == ([row["pin_id"] for row in consumers],)
    return (
        cursor,
        "INSERT INTO apiome.version_component_pins",
        {
            0: [entry["newPinId"] for entry in result["upgraded"]],
            2: [row["version_id"] for row in consumers],
            4: [f"L{i}" for i in range(n)],
        },
    )


@case
def _case_component_upgrade_audit(n: int):
    cursor, result, consumers = _bulk_upgrade(n)
    # The per-pin audit rows are one statement; the ``upgrade.bulk`` summary is the other.
    per_pin, summary = cursor.find("INSERT INTO apiome.component_library_audit")
    assert [json.loads(detail)["newPinId"] for detail in per_pin[1][7]] == [e["newPinId"] for e in result["upgraded"]]
    assert summary[1][5] == "upgrade.bulk"
    return (
        cursor,
        "SELECT * FROM unnest(%s::uuid[], %s::uuid[], %s::uuid[], %s::uuid[], %s::uuid[],"
        " %s::text[], %s::text[], %s::jsonb[])",
        {
            3: [row["version_id"] for row in consumers],
            5: ["pin.upgrade"] * n,
        },
    )


def _discovery(n: int) -> RecordingCursor:
    """Record a discovery snapshot with ``n`` capability items and ``n`` change rows."""
    cursor = RecordingCursor(
        [("AS next_seq", [{"next_seq": 1}]), ("INSERT INTO apiome.mcp_endpoint_versions", [{"id": _id(1)}])]
    )
    database, _ = _database(cursor)
    database._next_mcp_version_tag = lambda cur, endpoint, base: base  # type: ignore[method-assign]
    items = [
        {"item_type": "tool", "name": f"t{i}", "input_schema": {"required": ["a", str(i)]}, "ordinal": i}
        for i in range(n)
    ]
    changes = [
        {"change_type": "added", "item_type": "tool", "item_name": f"t{i}", "detail": {"i": i}} for i in range(n)
    ]
    database.record_mcp_discovery_version(
        _id(2), version_row={}, capability_rows=items, change_rows=changes, discovered_at=NOW
    )
    return cursor


@case
def _case_mcp_capability_items(n: int):
    return (
        _discovery(n),
        "INSERT INTO apiome.mcp_capability_items",
        {
            2: [f"t{i}" for i in range(n)],
            5: [json.dumps({"required": ["a", str(i)]}) for i in range(n)],
            10: ["{}"] * n,
            11: list(range(n)),
        },
    )


@case
def _case_mcp_version_changes(n: int):
    return (
        _discovery(n),
        "INSERT INTO apiome.mcp_version_changes",
        {
            3: [f"t{i}" for i in range(n)],
            4: [json.dumps({"i": i}) for i in range(n)],
        },
    )


@case
def _case_path_canvases(n: int):
    canvases = [
        {"new_path_id": _id(500 + i), "canvas": json.dumps({"nodes": [{"id": _id(100 + i)}]})} for i in range(n)
    ]
    id_map = [{"old_id": _id(100 + i), "new_id": _id(500 + i)} for i in range(n)]
    cursor = RecordingCursor([("FROM apiome.version_path_canvas c", canvases), ("SELECT old_id::text", id_map)])
    _copy_canvases(cursor)
    return (
        cursor,
        "INSERT INTO apiome.version_path_canvas",
        {
            0: [_id(500 + i) for i in range(n)],
            1: [json.dumps({"nodes": [{"id": _id(500 + i)}]}) for i in range(n)],
        },
    )


@case
def _case_sdk_beacon_counters(n: int):
    class Source:
        kind, tenant_id, project_id, id = sdk_beacon_store.SOURCE_KIND, TENANT, PROJECT, _id(1)

    class BeaconDb:
        def __init__(self, cursor: RecordingCursor) -> None:
            self.cursor = cursor

        def _guarded_tx(self, work: Any) -> Any:
            return work(self.cursor)

    cursor = RecordingCursor()
    events = [
        {
            "sdk_name": "sdk",
            "sdk_version": "1",
            "api_version": "1",
            "spec_revision_id": VERSION,
            "operation_id": f"op{i}",
            "outcome": "ok",
            "count": i + 1,
        }
        for i in range(n)
    ]
    originals = (sdk_beacon_store.load_source, sdk_beacon_store._published_revisions)
    sdk_beacon_store.load_source = lambda db, tenant, ref: Source  # type: ignore[assignment]
    sdk_beacon_store._published_revisions = lambda db, project, revisions: {VERSION}  # type: ignore[assignment]
    try:
        outcome = sdk_beacon_store.ingest_beacons(
            BeaconDb(cursor), tenant_id=TENANT, source_ref=None, batch=SdkBeaconBatch(events=events), now=NOW
        )
    finally:
        sdk_beacon_store.load_source, sdk_beacon_store._published_revisions = originals  # type: ignore[assignment]
    assert outcome.accepted == n
    return (
        cursor,
        "INSERT INTO apiome.usage_sdk_beacon_daily",
        {
            8: [f"op{i}" for i in range(n)],
            10: [i + 1 for i in range(n)],
            3: [NOW.date()] * n,
        },
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_statement_count_does_not_grow_with_the_rows(name: str) -> None:
    small, fragment, _ = CASES[name](SIZES[0])
    large, _, carried = CASES[name](SIZES[1])

    # Same statements, in the same order, whatever the row count.
    assert [sql for sql, _ in small.statements] == [sql for sql, _ in large.statements]
    hits = large.find(fragment)
    assert len(hits) == 1, f"expected one set-based statement matching {fragment!r}, found {len(hits)}"
    assert len(small.find(fragment)) == 1

    # … and that one statement carries every row, one array per column.
    params = hits[0][1]
    for index, expected in carried.items():
        assert list(params[index]) == expected, f"parameter {index} of {fragment!r}"
        assert len(expected) >= SIZES[1]


def test_empty_inputs_send_no_row_statement() -> None:
    cursor = RecordingCursor()
    database, _ = _database(cursor)
    database.set_role_permissions(_id(1), [])
    assert database.set_tenant_repository_file_codeowners(_id(1), "main", []) == 0
    Database._insert_suite_payload_rows(cursor, _id(1), TENANT, [])
    assert [sql.split(" ")[0] for sql, _ in cursor.statements] == ["DELETE"]


def test_repeated_upsert_keys_keep_the_last_row() -> None:
    """A multi-row ``ON CONFLICT DO UPDATE`` cannot touch a row twice; the last entry wins, as it
    did with one upsert per row."""
    cursor = RecordingCursor([("FROM apiome.tenant_repositories", [{"id": _id(1)}])])
    database, _ = _database(cursor)
    rules = [
        {"branch_pattern": "main", "refresh_interval_seconds": 1},
        {"branch_pattern": "dev", "refresh_interval_seconds": 2},
        {"branch_pattern": "main", "refresh_interval_seconds": 3},
    ]
    database.replace_repository_branch_refresh_rules(TENANT, _id(1), rules)
    ((_, params),) = cursor.find("INSERT INTO apiome.repository_branch_refresh_rule")
    assert (params[2], params[4]) == (["main", "dev"], [3, 2])

    database.replace_webhook_provider_ip_ranges(
        "github",
        [
            {"cidr": "10.0.0.0/8", "family": 4, "source": "provider"},
            {"cidr": "10.0.0.0/8", "family": 4, "source": "configured"},
        ],
    )
    ((_, params),) = cursor.find("INSERT INTO apiome.webhook_provider_ip_range")
    assert (params[1], params[3]) == (["10.0.0.0/8"], ["configured"])

    database.set_tenant_repository_file_codeowners(_id(1), "main", [("a", ["@x"]), ("b", []), ("a", ["@y"])])
    ((_, params),) = cursor.find("UPDATE apiome.tenant_repository_files")
    assert (params[0], params[1]) == (["a", "b"], ['["@y"]', "[]"])
