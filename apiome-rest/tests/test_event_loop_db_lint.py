"""Blocking database work stays off the event loop (DBP-1.4, #7187).

Three things are covered here:

- the lint over ``src/app`` (:mod:`tests.event_loop_db_lint`) and its allowlist;
- the request thread pool size, kept below the database connection cap;
- the acceptance check: while one request is held inside a 5-second query, a health check and a
  simple GET still answer.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import anyio.to_thread
import httpx
import pytest

from app import ops_routes, projects_routes, request_threads
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from tests.event_loop_db_lint import (
    AWAITLESS,
    DB_ON_LOOP,
    check_paths,
    check_source,
    route_module_paths,
)

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "app"

#: Handlers the lint may keep flagging, each with the reason it is safe. Key:
#: ``<file>::<handler>::<rule>``. Add an entry only when the flagged line cannot block the event
#: loop; otherwise make the handler a plain ``def`` or wrap the call in ``run_in_threadpool``.
ALLOWLIST: Dict[str, str] = {
    "ops_routes.py::liveness::awaitless": (
        "Returns a constant and never touches the database. It stays on the event loop so the "
        "liveness probe answers even when every request thread is busy."
    ),
    "bulk_import_routes.py::start_bulk_import::db-on-loop": (
        "ProjectReconciler(db, ...) only stores the handle; its queries run later inside "
        "asyncio.to_thread(_reconcile_groups, ...)."
    ),
    "catalog_refresh_routes.py::check_catalog_item_refresh::db-on-loop": (
        "run_refresh_check is a coroutine that awaits the network fetch and makes each of its "
        "database calls through asyncio.to_thread."
    ),
    "export_auto_routes.py::release_auto_export_run::db-on-loop": (
        "release_halted_run is a coroutine that makes each of its database calls through "
        "asyncio.to_thread."
    ),
}


# ─────────────────────────────── the lint over the service ───────────────────────────────


def test_no_route_handler_runs_database_work_on_the_event_loop() -> None:
    """Every violation in ``src/app`` is on the allowlist."""
    violations = [v for v in check_paths(route_module_paths(APP_DIR)) if v.key not in ALLOWLIST]
    assert not violations, (
        "These route handlers would block the event loop. Make the handler a plain `def`, or wrap "
        "the blocking call: `await run_in_threadpool(fn, *args)`.\n" + "\n".join(str(v) for v in violations)
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    """An allowlist entry whose handler is clean again must be removed."""
    live = {v.key for v in check_paths(route_module_paths(APP_DIR))}
    stale = sorted(set(ALLOWLIST) - live)
    assert not stale, f"Remove these allowlist entries, the lint no longer flags them: {stale}"


def test_every_allowlist_entry_says_why() -> None:
    """Each exception carries a real justification."""
    assert all(len(reason.strip()) >= 40 for reason in ALLOWLIST.values())


def test_the_lint_reads_the_route_modules() -> None:
    """Guard against the lint passing because it found nothing to read."""
    paths = route_module_paths(APP_DIR)
    assert any(path.name == "projects_routes.py" for path in paths)
    assert len(paths) > 100


# ─────────────────────────────── the lint rules ───────────────────────────────

_HEADER = "from fastapi.concurrency import run_in_threadpool\nimport asyncio\n"


def _rules(body: str) -> List[str]:
    """Rules the lint reports for a module made of ``body``."""
    return [f"{v.handler}:{v.rule}" for v in check_source(_HEADER + body, "sample_routes.py")]


def test_an_async_handler_without_an_await_is_flagged() -> None:
    assert _rules('@router.get("/x")\nasync def h():\n    return db.get_x()\n') == [f"h:{AWAITLESS}"]


def test_a_plain_def_handler_is_never_flagged() -> None:
    assert _rules('@router.get("/x")\ndef h():\n    return db.get_x()\n') == []


def test_a_direct_db_call_in_an_awaiting_handler_is_flagged() -> None:
    body = '@router.post("/x")\nasync def h(request):\n    body = await request.json()\n    return db.save(body)\n'
    assert _rules(body) == [f"h:{DB_ON_LOOP}"]


def test_passing_the_db_handle_to_a_call_is_flagged() -> None:
    body = '@router.post("/x")\nasync def h(request):\n    await request.json()\n    enforce_permission(db, 1)\n'
    violations = check_source(_HEADER + body, "sample_routes.py")
    assert [v.rule for v in violations] == [DB_ON_LOOP]
    assert "passes db to enforce_permission" in violations[0].detail


def test_a_same_module_helper_that_reaches_db_is_flagged_through_other_helpers() -> None:
    body = (
        "def _load(x):\n    return db.get_x(x)\n\n"
        "def _outer(x):\n    return _load(x)\n\n"
        "def _pure(x):\n    return x + 1\n\n"
        '@router.get("/x")\nasync def h(x):\n    await asyncio.sleep(0)\n    _pure(x)\n    return _outer(x)\n'
    )
    violations = check_source(_HEADER + body, "sample_routes.py")
    assert [(v.rule, v.detail) for v in violations] == [(DB_ON_LOOP, "calls _outer(...), which reaches db")]


def test_a_nested_function_called_on_the_loop_is_flagged() -> None:
    body = (
        '@router.get("/x")\nasync def h(x):\n'
        "    def run():\n        return db.get_x(x)\n"
        "    await asyncio.sleep(0)\n    return run()\n"
    )
    assert _rules(body) == [f"h:{DB_ON_LOOP}"]


@pytest.mark.parametrize(
    "call",
    [
        "await run_in_threadpool(db.get_x, x)",
        "await asyncio.to_thread(db.get_x, x)",
        "await run_in_threadpool(enforce_permission, db, x)",
        "await asyncio.to_thread(lambda: db.get_x(x))",
        "await asyncio.get_running_loop().run_in_executor(None, db.get_x, x)",
        "await run_in_threadpool(_load, x)",
    ],
)
def test_work_inside_a_thread_hop_is_allowed(call: str) -> None:
    body = f'def _load(x):\n    return db.get_x(x)\n\n@router.get("/x")\nasync def h(x):\n    return {call}\n'
    assert _rules(body) == []


def test_a_nested_function_handed_to_a_thread_hop_is_allowed() -> None:
    body = (
        '@router.get("/x")\nasync def h(x):\n'
        "    def run():\n        return db.get_x(x)\n"
        "    return await asyncio.to_thread(run)\n"
    )
    assert _rules(body) == []


def test_functions_that_are_not_routes_are_ignored() -> None:
    assert _rules("async def helper():\n    return db.get_x()\n") == []


def test_a_violation_names_its_file_handler_and_line() -> None:
    source = '@router.get("/x")\nasync def h(request):\n    await request.body()\n    return db.get_x()\n'
    (violation,) = check_source(source, "sample_routes.py")
    assert (violation.file, violation.handler, violation.line) == ("sample_routes.py", "h", 4)
    assert violation.key == "sample_routes.py::h::db-on-loop"
    assert "sample_routes.py:4 h [db-on-loop] calls db.get_x(...)" == str(violation)


# ─────────────────────────────── request thread pool size ───────────────────────────────


@pytest.mark.parametrize(
    ("configured", "cap", "expected"),
    [
        (40, 80, 40),  # the defaults
        (40, 20, 10),  # lowered to half the cap
        (8, 80, 8),  # a smaller pool is kept
        (200, 0, 200),  # no cap: as configured
        (0, 80, 1),  # never below one thread
        (40, 1, 1),  # a tiny cap still leaves one thread
    ],
)
def test_request_thread_limit_stays_within_half_the_connection_cap(configured: int, cap: int, expected: int) -> None:
    assert request_threads.request_thread_limit(configured, cap) == expected


def test_the_default_pool_fits_the_default_connection_cap() -> None:
    fields = type(settings).model_fields
    default_size = fields["request_thread_pool_size"].default
    default_cap = fields["db_pool_max_in_use"].default
    assert request_threads.request_thread_limit(default_size, default_cap) == default_size
    assert default_size < default_cap


async def test_configure_applies_the_limit_to_the_running_loop(monkeypatch, caplog) -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    before = limiter.total_tokens
    monkeypatch.setattr(settings, "request_thread_pool_size", 64)
    monkeypatch.setattr(settings, "db_pool_max_in_use", 24)
    try:
        with caplog.at_level(logging.INFO, logger="test.request_threads"):
            limit = request_threads.configure_request_thread_pool(logging.getLogger("test.request_threads"))
        assert limit == 12
        assert limiter.total_tokens == 12
        assert any("lowered to 12" in record.getMessage() for record in caplog.records)
    finally:
        limiter.total_tokens = before


async def test_configure_does_not_warn_when_the_size_fits(monkeypatch, caplog) -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    before = limiter.total_tokens
    monkeypatch.setattr(settings, "request_thread_pool_size", 16)
    monkeypatch.setattr(settings, "db_pool_max_in_use", 80)
    try:
        with caplog.at_level(logging.INFO, logger="test.request_threads"):
            assert request_threads.configure_request_thread_pool(logging.getLogger("test.request_threads")) == 16
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    finally:
        limiter.total_tokens = before


# ─────────────────────────────── a held query does not stall other requests ───────────────────────────────

#: How long the held query waits before giving up. The issue's "5 s query".
HOLD_SECONDS = 5.0
#: The other requests must answer well inside the hold.
NORMAL_SECONDS = 2.0


class _HoldingDb:
    """Stands in for the database: one tenant's project list blocks until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.released_in_time = False

    def get_projects_for_tenant(self, tenant_id: str, **_kwargs: Any) -> List[Dict[str, Any]]:
        """Block for the ``slow`` tenant until released (or ``HOLD_SECONDS``); others answer at once."""
        if tenant_id == "slow":
            self.started.set()
            self.released_in_time = self.release.wait(HOLD_SECONDS)
        return []

    def execute_query(self, _sql: str, *_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
        """The readiness probe's ``SELECT 1``."""
        return [{"ok": 1}]


async def test_a_held_query_does_not_stall_a_health_check_or_a_simple_get(monkeypatch) -> None:
    """One request sits in a 5 s query; ``/livez``, ``/readyz`` and a project list still answer."""
    holding = _HoldingDb()
    monkeypatch.setattr(projects_routes, "db", holding)
    monkeypatch.setattr(ops_routes, "db", holding)

    def fake_auth(tenant_slug: str) -> Dict[str, Any]:
        return {"tenant_id": tenant_slug, "tenant_slug": tenant_slug, "auth_type": "jwt", "user_id": "user-1"}

    app.dependency_overrides[validate_authentication] = fake_auth
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            slow = asyncio.create_task(client.get("/v1/projects/slow"))
            # Wait until the slow request is inside its query, without blocking this loop.
            assert await asyncio.to_thread(holding.started.wait, HOLD_SECONDS), "the slow request never started"

            started = time.monotonic()
            live, ready, simple = await asyncio.wait_for(
                asyncio.gather(
                    client.get("/livez"),
                    client.get("/readyz"),
                    client.get("/v1/projects/fast"),
                ),
                timeout=HOLD_SECONDS,
            )
            elapsed = time.monotonic() - started

            assert not slow.done(), "the slow request should still be held"
            holding.release.set()
            slow_response = await asyncio.wait_for(slow, timeout=HOLD_SECONDS)
    finally:
        holding.release.set()
        app.dependency_overrides.pop(validate_authentication, None)

    assert (live.status_code, ready.status_code, simple.status_code) == (200, 200, 200)
    assert ready.json() == {"status": "ready", "database": "connected"}
    assert simple.json() == []
    assert elapsed < NORMAL_SECONDS, f"other requests took {elapsed:.2f}s while one query was held"
    assert holding.released_in_time, "the held query timed out: the other requests were stuck behind it"
    assert slow_response.status_code == 200
