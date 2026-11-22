"""Lean version / project lookups for guards and re-reads — DBP-1.5 (#7188).

Three things are pinned here, without a database:

* **The guard lint.** Every call to the full lookups (``get_version_by_id`` /
  ``get_project_by_id``) in ``src/app`` whose result is only used as a guard — tested for
  truthiness, or read for columns the core lookups also return — fails: it must call
  ``get_version_core`` / ``get_project_core`` instead. The remaining full-row callers are listed in
  :data:`FULL_ROW_CALLERS`; a new one is a deliberate choice (the row is returned, handed on, or
  read for ``metadata``, ``mock_settings``, the security headline, the creator or the versions
  rollup) and is added to the list in the same PR.
* **The SQL shape** of the core lookups: one primary-key probe joined to the tenant only — no
  LATERAL, no aggregate, no creator join — and "not found" for a non-UUID id without a statement.
* **One statement** for ``update_class`` / ``delete_class`` / ``update_path`` / ``delete_path`` /
  ``update_operation`` / ``delete_operation`` and a changing ``update_project``: the tenant guard
  is part of the write.

The same behaviour against PostgreSQL (tenant isolation, column parity with the full lookups, the
project detail contract, ``RETURNING`` shapes) is in ``tests/test_core_lookups_db.py``.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import pytest

from app import database
from app.database import ProjectUpdateConflict

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"

FULL_LOOKUPS = {"get_version_by_id": "get_version_core", "get_project_by_id": "get_project_core"}


def _core_keys(constant: str, *, extra: Tuple[str, ...] = ()) -> Set[str]:
    """The result keys a core lookup returns, parsed from its column constant."""
    sql = getattr(database.Database, constant)
    keys = set(extra)
    for part in sql.split(","):
        token = part.strip().split()[-1]
        keys.add(token.split(".")[-1])
    return keys


#: Keys a guard may read from the full row and still be served by the core lookup.
CORE_KEYS = {
    "get_version_by_id": _core_keys("_VERSION_CORE_COLUMNS"),
    "get_project_by_id": _core_keys("_PROJECT_CORE_COLUMNS"),
}

#: ``file::function`` of every caller that still needs the full row (DBP-1.5 audit, #7188).
#: Each one returns the row, hands it to another function, or reads a column only the full
#: lookup has. Add an entry only for such a caller; a guard uses the core lookup.
FULL_ROW_CALLERS = frozenset(
    {
        "api_check_suite_evidence.py::read_breaking_facts",
        "api_check_suite_store.py::get_run",
        "blast_radius.py::version_document",
        "breaking_publish_guardrail.py::_classified_pairs",
        "breaking_publish_guardrail.py::assess_breaking_publish",
        "catalog_routes.py::lint_catalog_item",
        "change_report_enterprise_routes.py::_load_report",
        "change_report_enterprise_routes.py::export_change_report_pdf",
        "classified_diff_routes.py::_compare",
        "classified_diff_routes.py::_resolve_version_row",
        "comment_store.py::_mention_notifier",
        "comment_store.py::set_thread_status",
        "compatibility_engine.py::openapi_for_revision",
        "compatibility_routes.py::_compare_baselines",
        "compatibility_routes.py::_resolve_revision_pair",
        "compatibility_routes.py::check_revision_compatibility",
        "component_governance_routes.py::_classify_entry",
        "component_library_routes.py::_version_or_404",
        "conversion_job.py::_score_sync",
        "database.py::_branch_from_revision_idempotent_result",
        "database.py::_replace_version_mock_settings_key",
        "database.py::apply_version_refresh_provenance",
        "database.py::create_forked_version",
        "database.py::create_version_branch_from_revision",
        "database.py::create_version_push_transaction",
        "database.py::freeze_version_schema",
        "database.py::resolve_successor_revision_chain",
        "database.py::set_version_mock_enabled",
        "database.py::set_version_mock_scenarios",
        "database.py::update_project",
        "database.py::update_version",
        "deploy_gate_service.py::_resolve_revision",
        "export_source.py::_reconstructed_openapi_item",
        "import_project_delta.py::resolve_project_delta_target",
        "import_project_target.py::resolve_import_project_target",
        "lint_fix_routes.py::_version",
        "lint_fix_routes.py::apply_lint_fixes",
        "lint_policy_service.py::_review_approved",
        "lint_routes.py::lint_revision",
        "lint_routes.py::lint_revision_gate",
        "merge_request_store.py::_version",
        "preservation_routes.py::_version_or_404",
        "projects_routes.py::get_project",
        "projects_routes.py::get_project_openapi_tags",
        "projects_routes.py::replace_project_openapi_tags",
        "projects_routes.py::restore_project",
        "publication_change_report.py::_generate_change_report_on_publish_impl",
        "publication_change_report.py::build_publication_change_report_render",
        "publication_change_report.py::preview_change_report_before_publish",
        "publication_changelog.py::_generate_version_changelog_on_publish_impl",
        "repository_federation_routes.py::_parent_spec",
        "repository_refresh_change_report.py::_generate_change_report_on_refresh_impl",
        "review_store.py::_detail",
        "review_store.py::_review_version",
        "source_provenance_routes.py::get_source_provenance",
        "source_review_routes.py::_version_or_404",
        "spec_import_engine.py::_record_worker_import_snapshot",
        "spec_sync_store.py::get_plan",
        "spec_sync_store.py::resolve_conflict",
        "style_guide_routes.py::preview_style_guide_custom_rules",
        "version_change_report_routes.py::patch_version_change_report",
        "version_change_report_routes.py::preview_change_report_for_publish",
        "version_change_report_routes.py::regenerate_version_change_report",
        "version_merge_routes.py::_rollback_validate_branch_and_revisions",
        "version_merge_routes.py::version_branch_merge",
        "version_merge_routes.py::version_branch_merge_preview",
        "version_merge_routes.py::version_branch_rollback",
        "version_overlay_routes.py::_version",
        "version_publish_prechecks.py::enforce_publish_prechecks",
        "version_quality_capture.py::capture_version_quality_score",
        "versions_routes.py::_freeze_target",
        "versions_routes.py::_get_version_for_mock_scenarios",
        "versions_routes.py::_push_guard_published_immutable",
        "versions_routes.py::_validated_since_row_for_schema_pull_delta",
        "versions_routes.py::create_version",
        "versions_routes.py::fork_version_from_revision",
        "versions_routes.py::get_breaking_publish_guardrail",
        "versions_routes.py::get_version",
        "versions_routes.py::get_version_by_version_id",
        "versions_routes.py::get_version_freeze_status",
        "versions_routes.py::publish_version",
        "versions_routes.py::unpublish_version",
        "versions_routes.py::update_version",
    }
)


# ───────────────────────────── the guard lint ─────────────────────────────


class _Site:
    """One call to a full lookup: where it is and how its result is used."""

    def __init__(self, path: Path, call: ast.Call, lookup: str, func: Optional[str]) -> None:
        self.path = path
        self.call = call
        self.lookup = lookup
        self.func = func
        #: ``None`` when the result escapes (returned, passed on, unpacked …); otherwise the set
        #: of keys read from it (``"<truth>"`` for a truthiness / ``is None`` test).
        self.keys: Optional[Set[str]] = None

    @property
    def label(self) -> str:
        return f"{self.path.name}::{self.func}"

    def is_guard(self) -> bool:
        """Whether the core lookup would serve this call site."""
        return self.keys is not None and self.keys <= CORE_KEYS[self.lookup] | {"<truth>"}


def _lookup_name(call: ast.Call) -> Optional[str]:
    """The full lookup a call makes — directly or as ``run_in_threadpool(db.get_…, …)``."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name in FULL_LOOKUPS:
        return name
    if call.args and isinstance(call.args[0], ast.Attribute) and call.args[0].attr in FULL_LOOKUPS:
        return call.args[0].attr
    return None


def _uses(fn: ast.AST, var: str, parents: Dict[ast.AST, ast.AST]) -> Optional[Set[str]]:
    """Keys read from ``var`` inside ``fn``, or ``None`` when the value escapes."""
    keys: Set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Name) and node.id == var and isinstance(node.ctx, ast.Load)):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Subscript) and parent.value is node and isinstance(parent.slice, ast.Constant):
            keys.add(str(parent.slice.value))
        elif (
            isinstance(parent, ast.Attribute)
            and parent.value is node
            and parent.attr == "get"
            and isinstance(parents.get(parent), ast.Call)
            and parents[parent].args
            and isinstance(parents[parent].args[0], ast.Constant)
        ):
            keys.add(str(parents[parent].args[0].value))
        elif isinstance(parent, (ast.UnaryOp, ast.If, ast.BoolOp, ast.IfExp, ast.Assert)) or (
            isinstance(parent, ast.Compare)
            and any(isinstance(c, ast.Constant) and c.value is None for c in parent.comparators)
        ):
            keys.add("<truth>")
        else:
            return None
    return keys


def _sites(root: Path = APP_DIR) -> Iterator[_Site]:
    """Every full-lookup call under ``root`` (default ``src/app``) with how its result is used."""
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: Dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            lookup = _lookup_name(call)
            if lookup is None:
                continue
            fn: Optional[ast.AST] = call
            while fn is not None and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parents.get(fn)
            site = _Site(path, call, lookup, getattr(fn, "name", None))
            node: ast.AST = call
            parent = parents.get(node)
            while isinstance(parent, ast.Await):
                node, parent = parent, parents.get(parent)
            if isinstance(parent, (ast.UnaryOp, ast.BoolOp)) or (isinstance(parent, ast.If) and parent.test is node):
                site.keys = {"<truth>"}
            elif (
                fn is not None
                and isinstance(parent, ast.Assign)
                and len(parent.targets) == 1
                and isinstance(parent.targets[0], ast.Name)
            ):
                site.keys = _uses(fn, parent.targets[0].id, parents)
            yield site


def test_no_guard_call_site_uses_a_full_lookup() -> None:
    """A call site that only guards on the row must use the core lookup (#7188)."""
    offenders = [
        f"{s.path.relative_to(APP_DIR)}:{s.call.lineno} {s.func}() -> {FULL_LOOKUPS[s.lookup]}"
        for s in _sites()
        if s.is_guard()
    ]
    assert not offenders, "These call sites only guard on the row; use the core lookup:\n" + "\n".join(offenders)


def test_full_row_callers_are_the_listed_ones() -> None:
    """Every remaining full lookup is a listed, deliberate full-row caller."""
    found = {s.label for s in _sites()}
    unlisted = sorted(found - FULL_ROW_CALLERS)
    stale = sorted(FULL_ROW_CALLERS - found)
    assert not unlisted, (
        "New full-row lookups. Use get_version_core / get_project_core for a guard; add the caller to "
        "FULL_ROW_CALLERS only when it needs the full row:\n" + "\n".join(unlisted)
    )
    assert not stale, "No longer calls a full lookup; remove from FULL_ROW_CALLERS:\n" + "\n".join(stale)


def test_the_core_lookups_have_guard_callers() -> None:
    """The migration happened: well over a hundred guards read the core lookups."""
    source = "\n".join(p.read_text(encoding="utf-8") for p in APP_DIR.rglob("*.py"))
    assert source.count("get_version_core(") >= 40
    assert source.count("get_project_core(") >= 70


def test_the_lint_flags_a_guard_shaped_full_lookup(tmp_path) -> None:
    """The lint itself: a truthiness-only full lookup is reported; one that returns the row is not."""
    (tmp_path / "mod.py").write_text(
        "def guard(db, v, t):\n"
        "    version = db.get_version_by_id(v, t)\n"
        "    if not version or version['project_id'] != 'p':\n"
        "        raise KeyError\n"
        "def detail(db, v, t):\n"
        "    return db.get_version_by_id(v, t)\n"
        "def metadata(db, p, t):\n"
        "    project = db.get_project_by_id(p, t)\n"
        "    return project.get('metadata') if project else None\n",
        encoding="utf-8",
    )
    by_func = {s.func: s for s in _sites(tmp_path)}
    assert by_func["guard"].is_guard()
    assert not by_func["detail"].is_guard()
    assert not by_func["metadata"].is_guard()


# ───────────────────────────── a recording Database ─────────────────────────────


class _RecordingDb(database.Database):
    """A ``Database`` whose statements are recorded and answered from a queue."""

    def __init__(self, answers: Optional[List[Any]] = None) -> None:
        super().__init__()
        self.statements: List[Tuple[str, tuple]] = []
        self.answers = list(answers or [])

    def _next(self) -> Any:
        return self.answers.pop(0) if self.answers else []

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:  # type: ignore[override]
        self.statements.append((query, tuple(params or ())))
        return self._next()

    def _execute_write(self, query: str, params: tuple = None) -> int:  # type: ignore[override]
        self.statements.append((query, tuple(params or ())))
        return self._next()

    def connect(self):  # pragma: no cover - a test that reaches it has regressed
        raise AssertionError("opened a connection instead of one execute_query / _execute_write")


VID = "11111111-1111-4111-8111-111111111111"
PID = "22222222-2222-4222-8222-222222222222"
TID = "33333333-3333-4333-8333-333333333333"


def _flat(sql: str) -> str:
    return " ".join(sql.split())


# ───────────────────────────── core lookups: SQL shape ─────────────────────────────


def test_get_version_core_is_one_pk_probe_joined_to_the_tenant() -> None:
    db = _RecordingDb([[{"id": VID, "project_id": PID, "tenant_id": TID}]])
    assert db.get_version_core(VID, TID) == {"id": VID, "project_id": PID, "tenant_id": TID}
    [(sql, params)] = db.statements
    flat = _flat(sql)
    assert params == (VID, TID)
    assert "FROM apiome.versions v JOIN apiome.projects p ON v.project_id = p.id" in flat
    for absent in (
        "LATERAL",
        "jsonb_array_elements",
        "apiome.users",
        "LEFT JOIN",
        "v.metadata",
        "mock_settings",
        "change_log",
    ):
        assert absent not in flat, absent
    for clause in ("v.id = %s", "p.tenant_id = %s", "v.deleted_at IS NULL", "p.deleted_at IS NULL"):
        assert clause in flat


def test_get_project_core_reads_projects_only() -> None:
    db = _RecordingDb([[{"id": PID}]])
    assert db.get_project_core(PID, TID) == {"id": PID}
    [(sql, params)] = db.statements
    flat = _flat(sql)
    assert params == (PID, TID)
    assert "FROM apiome.projects p WHERE p.id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL" in flat
    for absent in ("LATERAL", "COUNT(", "AVG(", "apiome.users", "apiome.versions", "p.metadata"):
        assert absent not in flat, absent


def test_get_project_core_can_include_a_deleted_project() -> None:
    db = _RecordingDb([[{"id": PID}]])
    db.get_project_core(PID, TID, include_deleted=True)
    assert "deleted_at IS NULL" not in db.statements[0][0]


@pytest.mark.parametrize("bad", ["", None, "0.0.1", "my-project", "not-a-uuid"])
def test_core_lookups_treat_a_non_uuid_as_not_found_without_a_statement(bad) -> None:
    db = _RecordingDb()
    assert db.get_version_core(bad, TID) is None
    assert db.get_project_core(bad, TID) is None
    assert db.statements == []


def test_core_lookups_return_none_when_no_row() -> None:
    db = _RecordingDb([[], []])
    assert db.get_version_core(VID, TID) is None
    assert db.get_project_core(PID, TID) is None


def test_core_columns_are_a_subset_of_the_full_lookups() -> None:
    """Swapping a guard to the core lookup never asks for a key the full row lacks."""
    assert {"id", "project_id", "version_id", "published", "revision_locked", "tenant_id", "project_slug"} <= CORE_KEYS[
        "get_version_by_id"
    ]
    assert (
        not {"metadata", "mock_settings", "change_log", "security_score", "creator_name"}
        & CORE_KEYS["get_version_by_id"]
    )
    assert {"id", "tenant_id", "name", "slug", "publishable", "deleted_at", "updated_at"} <= CORE_KEYS[
        "get_project_by_id"
    ]
    assert (
        not {"metadata", "versions_count", "quality_score", "quality_grade", "creator_name"}
        & CORE_KEYS["get_project_by_id"]
    )


# ───────────────────────────── writes: one statement ─────────────────────────────

CID = "44444444-4444-4444-8444-444444444444"


@pytest.mark.parametrize(
    ("method", "args", "answer", "target", "guard_join"),
    [
        (
            "update_class",
            (CID, TID, {"name": "Pet"}),
            [{"id": CID}],
            "UPDATE apiome.classes c",
            "FROM apiome.versions v JOIN apiome.projects p",
        ),
        (
            "delete_class",
            (CID, TID),
            1,
            "UPDATE apiome.classes c SET deleted_at",
            "FROM apiome.versions v JOIN apiome.projects p",
        ),
        (
            "update_path",
            (CID, TID, {"pathname": "/pets"}),
            [{"id": CID}],
            "UPDATE apiome.version_path vp",
            "FROM apiome.versions v JOIN apiome.projects p",
        ),
        (
            "delete_path",
            (CID, TID),
            1,
            "DELETE FROM apiome.version_path vp",
            "USING apiome.versions v JOIN apiome.projects p",
        ),
        (
            "update_operation",
            (CID, TID, {"operation": "get"}),
            [{"id": CID}],
            "UPDATE apiome.path_operation po",
            "FROM apiome.version_path vp JOIN apiome.versions v",
        ),
        (
            "delete_operation",
            (CID, TID),
            1,
            "DELETE FROM apiome.path_operation po",
            "USING apiome.version_path vp JOIN apiome.versions v",
        ),
    ],
)
def test_writes_fold_the_tenant_guard_into_one_statement(method, args, answer, target, guard_join) -> None:
    db = _RecordingDb([answer])
    result = getattr(db, method)(*args)
    assert result == (True if method.startswith("delete") else answer[0])
    [(sql, params)] = db.statements
    flat = _flat(sql)
    assert flat.startswith(target), flat
    assert guard_join in flat
    assert "p.tenant_id = %s" in flat
    assert params[-2:] == (CID, TID)


@pytest.mark.parametrize("method", ["update_class", "update_path", "update_operation"])
def test_an_update_outside_the_tenant_returns_none(method) -> None:
    field = {"update_class": "name", "update_path": "pathname", "update_operation": "operation"}[method]
    db = _RecordingDb([[]])
    assert getattr(db, method)(CID, TID, {field: "x"}) is None
    assert len(db.statements) == 1


@pytest.mark.parametrize("method", ["delete_class", "delete_path", "delete_operation"])
def test_a_delete_outside_the_tenant_returns_false(method) -> None:
    db = _RecordingDb([0])
    assert getattr(db, method)(CID, TID) is False
    assert len(db.statements) == 1


@pytest.mark.parametrize(
    ("method", "reader"),
    [
        ("update_class", "apiome.classes c"),
        ("update_path", "apiome.version_path vp"),
        ("update_operation", "apiome.path_operation po"),
    ],
)
def test_an_empty_update_reads_the_current_row(method, reader) -> None:
    db = _RecordingDb([[{"id": CID}]])
    assert getattr(db, method)(CID, TID, {}) == {"id": CID}
    [(sql, _)] = db.statements
    assert _flat(sql).startswith("SELECT") and reader in sql


def test_update_class_keeps_the_class_columns_qualified() -> None:
    """``versions`` shares column names with ``classes``; RETURNING must not be ambiguous."""
    db = _RecordingDb([[{"id": CID}]])
    db.update_class(CID, TID, {"name": "Pet", "schema": {"type": "object"}, "enabled": True})
    flat = _flat(db.statements[0][0])
    returning = flat.split("RETURNING", 1)[1]
    for column in (
        "id",
        "version_id",
        "name",
        "description",
        "schema",
        "enabled",
        "canvas_metadata",
        "created_at",
        "updated_at",
    ):
        assert f"c.{column}" in returning


# ───────────────────────────── update_project ─────────────────────────────

STAMP = datetime(2026, 11, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)


class _ProjectDb(_RecordingDb):
    """``update_project`` writes through a cursor; record that statement too."""

    def __init__(self, update_row: Optional[Dict[str, Any]], answers: Optional[List[Any]] = None) -> None:
        super().__init__(answers)
        self.update_row = update_row

    def connect(self):
        outer = self

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                outer.statements.append((sql, tuple(params or ())))

            def fetchone(self):
                return outer.update_row

        class _Conn:
            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

            def rollback(self):
                pass

        return _Conn()


def test_update_project_is_one_statement_when_it_changes_something() -> None:
    db = _ProjectDb({"id": PID, "name": "Pets"})
    assert db.update_project(PID, TID, {"name": "Pets"}) == {"id": PID, "name": "Pets"}
    [(sql, params)] = db.statements
    assert _flat(sql).startswith("UPDATE apiome.projects")
    assert params[-2:] == (PID, TID)


def test_update_project_with_a_precondition_is_still_one_statement() -> None:
    db = _ProjectDb({"id": PID})
    db.update_project(PID, TID, {"name": "Pets"}, expected_updated_at=STAMP.replace(tzinfo=None))
    [(sql, params)] = db.statements
    assert "AND updated_at = %s" in sql
    assert params[-1] == STAMP  # a naive value is read as UTC


def test_update_project_conflict_reads_the_core_row() -> None:
    later = STAMP.replace(second=5)
    db = _ProjectDb(None, [[{"id": PID, "updated_at": later}]])
    with pytest.raises(ProjectUpdateConflict) as exc:
        db.update_project(PID, TID, {"name": "Pets"}, expected_updated_at=STAMP)
    assert exc.value.current_updated_at == later
    assert len(db.statements) == 2
    assert "LATERAL" not in db.statements[1][0]


def test_update_project_missing_is_none() -> None:
    db = _ProjectDb(None, [[]])
    assert db.update_project(PID, TID, {"name": "Pets"}, expected_updated_at=STAMP) is None
    db = _ProjectDb(None)
    assert db.update_project(PID, TID, {"name": "Pets"}) is None
    assert len(db.statements) == 1


def test_update_project_with_nothing_to_set_returns_the_full_row_and_checks_the_precondition() -> None:
    row = {"id": PID, "updated_at": STAMP, "versions_count": 3}
    db = _ProjectDb(None, [[row]])
    assert db.update_project(PID, TID, {}) == row
    db = _ProjectDb(None, [[row]])
    with pytest.raises(ProjectUpdateConflict):
        db.update_project(PID, TID, {}, expected_updated_at=STAMP.replace(second=9))
    db = _ProjectDb(None, [[row]])
    assert db.update_project(PID, TID, {}, expected_updated_at=STAMP) == row


# ───────────────────────────── RETURNING instead of re-reads ─────────────────────────────


def test_create_and_update_mcp_category_are_one_statement() -> None:
    row = {"slug": "data", "endpoint_count": 0}
    db = _RecordingDb([[row]])
    assert db.create_mcp_category(TID, None, slug="data", label="Data", description=None, sort_order=1) == row
    db.answers = [[row]]
    assert db.update_mcp_category(TID, "data", {"label": "Data!"}) == row
    db.answers = [[]]
    assert db.update_mcp_category(TID, "nope", {"label": "x"}) is None
    assert len(db.statements) == 3
    for sql, params in db.statements:
        assert "RETURNING *" in sql and "endpoint_count" in sql
        assert params[-1] == TID  # the endpoint_count subquery's tenant


def test_create_and_update_mcp_endpoint_note_are_one_statement() -> None:
    row = {"id": VID, "created_by_name": "A"}
    db = _RecordingDb([[row], [row], []])
    assert db.create_mcp_endpoint_note(TID, PID, VID, body="hi") == row
    assert db.update_mcp_endpoint_note(TID, PID, VID, VID, body="hi!") == row
    assert db.update_mcp_endpoint_note(TID, PID, VID, VID, body="x") is None
    assert len(db.statements) == 3
    for sql, _ in db.statements:
        flat = _flat(sql)
        assert "RETURNING *" in flat and "FROM n LEFT JOIN apiome.users cu" in flat


def test_update_mcp_collection_returns_the_member_count_in_one_statement() -> None:
    row = {"id": VID, "member_count": 2}
    db = _RecordingDb([[row], []])
    assert db.update_mcp_collection(TID, VID, name="New") == row
    assert db.update_mcp_collection(TID, VID, name="New") is None
    assert len(db.statements) == 2
    assert "AS member_count" in db.statements[0][0].split("RETURNING", 1)[1]


def test_revoke_mcp_api_key_writes_first() -> None:
    db = _RecordingDb([[{"id": VID, "revoked_at": STAMP}]])
    db._normalize_mcp_api_key_row = lambda r: dict(r)  # type: ignore[method-assign]
    assert db.revoke_mcp_api_key(TID, VID)["revoked_at"] == STAMP
    assert len(db.statements) == 1 and _flat(db.statements[0][0]).startswith("UPDATE apiome.mcp_api_keys")
    # Already revoked (or missing): the UPDATE matches nothing and the row is read back.
    db = _RecordingDb([[], [{"id": VID, "revoked_at": STAMP}]])
    db._normalize_mcp_api_key_row = lambda r: dict(r)  # type: ignore[method-assign]
    assert db.revoke_mcp_api_key(TID, VID)["revoked_at"] == STAMP
    assert len(db.statements) == 2


def test_get_project_core_looks_up_any_well_formed_uuid() -> None:
    """``get_project_by_id`` has no UUID guard, so the core lookup must not refuse an id it finds:
    any UUID-shaped value is queried, whatever its version or variant bits (e.g. UUIDv7, or the
    scale seed's deterministic ids)."""
    for odd in ("94796aad-6216-8059-9a37-e055760471c0", "0190f0c4-7b3e-7c11-a1b2-3c4d5e6f7a8b"):
        db = _RecordingDb([[{"id": odd}]])
        assert db.get_project_core(odd, TID) == {"id": odd}
        assert len(db.statements) == 1


def test_delete_class_property_is_one_tenant_guarded_statement() -> None:
    db = _RecordingDb([1, 0])
    assert db.delete_class_property(VID, CID, TID) is True
    assert db.delete_class_property(VID, CID, TID) is False
    sql, params = db.statements[0]
    flat = _flat(sql)
    assert flat.startswith("DELETE FROM apiome.class_properties cp USING apiome.classes c")
    assert "cp.class_id = c.id" in flat and "p.tenant_id = %s" in flat
    assert params == (VID, CID, TID)
    assert len(db.statements) == 2
