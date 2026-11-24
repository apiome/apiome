"""Shared pytest fixtures for apiome-rest tests."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# MFI-14.2: a single ``.tsp`` file is compiled through ``tsp`` when the compiler is installed. Pin the
# built-in reader for the suite so the corpus goldens and adapter tests read the same model on a
# machine with ``tsp`` as on one without; tests of the compiled single-file path turn it back on.
os.environ.setdefault("APIOME_TYPESPEC_COMPILE_SINGLE_FILES", "0")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register repo-wide test options.

    ``--update-golden`` regenerates the IXH-1.6 canonical corpus snapshots
    (``tests/golden/corpus/``) instead of comparing against them, so an intended
    contract change is a one-command refresh whose diff lands in review. The
    ``UPDATE_CORPUS_GOLDENS=1`` environment variable does the same, mirroring the
    EFP-1.3 projection corpus's idiom.

    ``--update-roundtrip-matrix`` regenerates the IXH-1.7 round-trip matrix
    artifact (``tests/golden/roundtrip/matrix.json``); ``UPDATE_ROUNDTRIP_MATRIX=1``
    does the same.

    ``--update-corpus-parity`` regenerates the FMT-1.4 corpus parity coverage report
    (``tests/golden/parity/corpus_parity.json`` and its Markdown companion);
    ``UPDATE_CORPUS_PARITY=1`` does the same.

    ``--scale`` opts this run into the IXH-1.5 scale benchmark suite, which is
    otherwise skipped because it costs minutes and hundreds of megabytes;
    ``RUN_SCALE_SUITE=1`` does the same. ``--update-scale-budgets`` rewrites its
    committed baseline (``tests/scale/scale_budgets.json``) from the run instead of
    asserting against it.
    """
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Regenerate canonical corpus golden snapshots (tests/golden/corpus/) "
            "instead of asserting against them."
        ),
    )
    parser.addoption(
        "--update-roundtrip-matrix",
        action="store_true",
        default=False,
        help=(
            "Regenerate the round-trip conformance matrix artifact "
            "(tests/golden/roundtrip/matrix.json) instead of asserting against it."
        ),
    )
    parser.addoption(
        "--update-export-conformance",
        action="store_true",
        default=False,
        help=(
            "Regenerate the X1 export conformance matrix and its silent-loss ledger "
            "(tests/golden/export_conformance/, tests/export_conformance_ledger.py) instead of "
            "comparing against them."
        ),
    )
    parser.addoption(
        "--update-corpus-parity",
        action="store_true",
        default=False,
        help=(
            "Regenerate the corpus parity coverage report "
            "(tests/golden/parity/corpus_parity.json) instead of asserting against it."
        ),
    )
    parser.addoption(
        "--scale",
        action="store_true",
        default=False,
        help=(
            "Run the IXH-1.5 scale benchmark suite (tests/test_scale_corpus.py), "
            "which is opt-in because it costs minutes and hundreds of megabytes."
        ),
    )
    parser.addoption(
        "--large-spec",
        action="store_true",
        default=False,
        help=(
            "Run the COA-5.11 large-spec benchmark suite (tests/test_large_spec_benchmark.py), "
            "skipped by default. RUN_LARGE_SPEC_SUITE=1 does the same."
        ),
    )
    parser.addoption(
        "--update-large-spec-budgets",
        action="store_true",
        default=False,
        help=(
            "Rewrite the committed large-spec budgets (tests/scale/large_spec_budgets.json) "
            "from this run instead of asserting against them."
        ),
    )
    parser.addoption(
        "--update-scale-budgets",
        action="store_true",
        default=False,
        help=(
            "Rewrite the committed scale budgets (tests/scale/scale_budgets.json) "
            "from this run instead of asserting against them."
        ),
    )


#: Test module holding the opt-in IXH-1.5 scale benchmark suite (#5091).
_SCALE_SUITE_MODULE = "test_scale_corpus.py"
#: Test module holding the opt-in COA-5.11 large-spec benchmark suite (#7087).
_LARGE_SPEC_SUITE_MODULE = "test_large_spec_benchmark.py"


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip the opt-in scale benchmark suite unless this run asked for it.

    The IXH-1.5 suite builds multi-megabyte documents and runs minutes of real
    pipeline work, so by acceptance criterion it is opt-in locally (``--scale`` /
    ``RUN_SCALE_SUITE=1``) and scheduled — not per-PR — in CI. The decision lives
    here rather than in the module because pytest only honours collection hooks from
    ``conftest.py`` and plugins.

    Args:
        config: The pytest config carrying the ``--scale`` option.
        items: The collected test items, mutated in place.
    """
    from scale_corpus_spec import scale_suite_enabled

    optional = (
        (_SCALE_SUITE_MODULE, scale_suite_enabled(config), "scale suite is opt-in: run with --scale or RUN_SCALE_SUITE=1"),
        (
            _LARGE_SPEC_SUITE_MODULE,
            _large_spec_enabled(config),
            "large-spec suite is opt-in: run with --large-spec or RUN_LARGE_SPEC_SUITE=1",
        ),
    )
    for module, enabled, reason in optional:
        if enabled:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if item.nodeid.split("::", 1)[0].endswith(module):
                item.add_marker(skip)


def _large_spec_enabled(config: pytest.Config) -> bool:
    """Whether the COA-5.11 large-spec suite is enabled (env var or ``--large-spec``).

    Decided here rather than through ``large_spec_benchmark`` for the same reason as the scale
    suite: that module imports the service, and this runs on every pytest invocation.
    """
    return os.environ.get("RUN_LARGE_SPEC_SUITE") == "1" or bool(config.getoption("--large-spec", default=False))


@pytest.fixture(autouse=True)
def _disable_rate_limiting(monkeypatch):
    """
    Disable the per-tenant rate-limit middleware (#3612) for the test session.

    ``RateLimitMiddleware`` keeps an in-process fixed-window counter that is shared across every
    request the app handles. The route tests reuse one ``TestClient`` / app per module and hammer the
    same API-key bucket, so the cumulative request count trips the ``429`` limit partway through the
    full suite — making otherwise-passing tests fail purely as a function of suite ordering and size.
    Route tests assert endpoint behaviour, not throttling, so the limiter is switched off by default
    here. The dedicated coverage in ``test_rate_limit.py`` re-enables it explicitly (it builds its own
    app and monkeypatches ``settings`` per-test), so this default does not weaken limiter coverage.
    """
    try:
        from app.config import settings
    except Exception:
        return
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


@pytest.fixture
def repo_root() -> Path:
    """Monorepo root (parent of ``apiome-rest/``)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _restore_dependency_overrides():
    """
    Snapshot and restore FastAPI dependency overrides around every test.

    Many route tests install ``app.dependency_overrides[...]`` to stub authentication and clear it in
    their own teardown. If a test body raises *before* that cleanup runs (e.g. a ``patch()`` whose
    target was renamed away in the product code), the override leaks into subsequent, unrelated tests
    and corrupts their auth context — producing order-dependent failures that pass in isolation.
    Snapshotting the overrides before the test and restoring them afterwards makes the suite
    deterministic regardless of per-test cleanup discipline.
    """
    try:
        from app.main import app
    except Exception:
        # If the app cannot be imported (pure-unit modules that never touch FastAPI), there is
        # nothing to guard; let the test run untouched.
        yield
        return
    saved = dict(app.dependency_overrides)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


@pytest.fixture(autouse=True)
def _in_memory_async_job_store(monkeypatch):
    """Back the shared async-job store (migration V158) with a per-test in-memory fake.

    The spec-import and export engines mirror every job state change to ``apiome.async_job`` and
    read polls back from it so a round-robin deployment can poll any instance (previously the
    in-memory dict 404'd on instances that didn't create the job). Routing those five ``db``
    methods to a fresh dict per test keeps the engine tests hermetic and deterministic — no
    Postgres dependency, no cross-test accumulation in the table — while still exercising the
    real mirror→read round-trip through the fake. Tests that replace the whole ``db`` singleton
    with their own mock are unaffected (this patches the real singleton's methods only).

    Also backs the export artifact store (IXH-6.1 / V206) so completed exports persist download
    bytes into the same in-memory dict and a simulated non-owning instance can serve them.
    """
    try:
        module = __import__("app.database", fromlist=["db"])
    except Exception:
        yield
        return

    store: dict = {}
    artifacts: dict = {}

    def _upsert(*, job_id, kind, tenant_slug, state, status, extra=None):
        row = store.get(job_id) or {"cancel_requested": False, "extra": None}
        row.update(
            {
                "job_id": job_id,
                "kind": kind,
                "tenant_slug": tenant_slug,
                "state": state,
                "status": status,
            }
        )
        if extra is not None:  # COALESCE: never null out a value already recorded
            row["extra"] = extra
        store[job_id] = row

    def _matches(row, tenant_slug, kind):
        return row is not None and row["tenant_slug"] == tenant_slug and row["kind"] == kind

    def _get(job_id, tenant_slug, kind):
        row = store.get(job_id)
        return dict(row) if _matches(row, tenant_slug, kind) else None

    def _list(
        tenant_slug,
        kind,
        *,
        limit=50,
        offset=0,
        state=None,
        created_after=None,
        created_before=None,
        cursor=None,
        include_total=False,
    ):
        page_limit = max(1, min(int(limit), 200))
        page_offset = 0 if cursor else max(0, int(offset))
        rows = [dict(r) for r in store.values() if _matches(r, tenant_slug, kind)]
        if state is not None and str(state).strip():
            want = str(state).strip()
            rows = [r for r in rows if r.get("state") == want]
        # Fake store has no created_at; date filters are no-ops in unit tests.
        _ = (created_after, created_before)
        rows.sort(key=lambda r: r.get("job_id") or "", reverse=True)
        total = len(rows)
        # Every fake row shares one created_at, so the keyset order is the job_id order (#7196).
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for row in rows:
            row.setdefault("created_at", epoch)
        if cursor is not None:
            rows = [r for r in rows if (r["created_at"], r.get("job_id") or "") < tuple(cursor)]
        window = rows[page_offset : page_offset + page_limit + 1]
        return {
            "jobs": window[:page_limit],
            "total": total if include_total else None,
            "limit": page_limit,
            "offset": page_offset,
            "has_more": len(window) > page_limit,
        }

    def _request_cancel(job_id, tenant_slug, kind):
        row = store.get(job_id)
        if _matches(row, tenant_slug, kind):
            row["cancel_requested"] = True
            return True
        return False

    def _cancel_requested(job_id):
        row = store.get(job_id)
        return bool(row and row.get("cancel_requested"))

    def _upsert_artifact(
        *,
        job_id,
        tenant_slug,
        content_sha256,
        size_bytes,
        media_type,
        filename,
        backend,
        content,
        storage_uri,
        expires_at,
    ):
        raw = content
        if raw is not None and hasattr(raw, "adapted"):
            # psycopg2.Binary wrapper from database.upsert_export_job_artifact
            raw = raw.adapted
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        elif isinstance(raw, bytearray):
            raw = bytes(raw)
        artifacts[job_id] = {
            "job_id": job_id,
            "tenant_slug": tenant_slug,
            "content_sha256": content_sha256,
            "size_bytes": size_bytes,
            "media_type": media_type,
            "filename": filename,
            "backend": backend,
            "content": bytes(raw) if raw is not None else None,
            "storage_uri": storage_uri,
            "expires_at": expires_at,
            "reaped_at": None,
            "created_at": None,
        }

    def _get_artifact(job_id, tenant_slug):
        row = artifacts.get(job_id)
        if row is None or row["tenant_slug"] != tenant_slug:
            return None
        return dict(row)

    def _delete_artifact(job_id, tenant_slug):
        row = artifacts.get(job_id)
        if row is None or row["tenant_slug"] != tenant_slug:
            return False
        del artifacts[job_id]
        return True

    def _reap_expired(*, now=None, limit=100):
        from datetime import datetime, timezone

        cutoff = now or datetime.now(timezone.utc)
        if getattr(cutoff, "tzinfo", None) is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        reaped = 0
        for row in list(artifacts.values()):
            if reaped >= limit:
                break
            if row.get("reaped_at") is not None:
                continue
            exp = row.get("expires_at")
            if exp is None:
                continue
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= cutoff:
                row["reaped_at"] = cutoff
                row["content"] = None
                row["storage_uri"] = None
                reaped += 1
        return reaped

    monkeypatch.setattr(module.db, "upsert_async_job", _upsert)
    monkeypatch.setattr(module.db, "get_async_job", _get)
    monkeypatch.setattr(module.db, "list_async_jobs", _list)
    monkeypatch.setattr(module.db, "request_async_job_cancel", _request_cancel)
    monkeypatch.setattr(module.db, "async_job_cancel_requested", _cancel_requested)
    monkeypatch.setattr(module.db, "upsert_export_job_artifact", _upsert_artifact)
    monkeypatch.setattr(module.db, "get_export_job_artifact", _get_artifact)
    monkeypatch.setattr(module.db, "delete_export_job_artifact", _delete_artifact)
    monkeypatch.setattr(module.db, "reap_expired_export_job_artifacts", _reap_expired)
    yield

@pytest.fixture(autouse=True)
def _pin_test_tool_availability(monkeypatch):
    """
    Report every toolchain test-drive check (MFX-44.1) as "not installed" in the test session.

    An export target's descriptor carries ``test_tools``, and a toolchain check's ``available`` flag
    depends on which binaries the machine running the tests has (``buf`` on one laptop, nothing in
    CI). Descriptors are recorded in many golden fixtures — the target-card fixtures the CLI and UI
    replay, the export goldens — so an unpinned flag would make them differ from machine to machine.
    Pinning it here keeps every recording deterministic. ``test_export_test_tools.py`` patches the
    same seam per test to cover both answers.
    """
    try:
        module = __import__("app.export_test_tools", fromlist=["_tool_installed"])
    except Exception:
        return
    monkeypatch.setattr(module, "_tool_installed", lambda tool: False)


@pytest.fixture(autouse=True)
def _allow_permissions_by_default(monkeypatch):
    """
    Default the RBAC permission guard (#3611) to "allow" for route unit tests.

    Every mutating route now calls ``db.user_has_permission(...)`` via the central guard. Route unit
    tests that exercise the real ``db`` singleton (patching only the specific data methods they care
    about) would otherwise drive the guard into Postgres with synthetic ids (e.g. ``"t1"``). These
    tests assert route behaviour, not authorization, so the guard is stubbed to allow here. Tests
    that replace the whole module-level ``db`` with a mock are unaffected (the guard uses that mock),
    and the dedicated guard tests in ``test_permission_guard.py`` exercise the real predicate.

    The guard (and ``get_authenticated_user_id``) also resolve an *acting* user id before authorizing.
    For keyless (legacy) API-key callers that id comes from
    ``db.get_fallback_creator_user_id_for_tenant(tenant_id)`` — a real Postgres lookup. It is stubbed
    to return ``None`` (the "no legacy fallback user" default), which keeps the guard out of the
    database and preserves the JWT-only routes' behaviour: a keyless API key resolves to no user and
    is rejected with ``403``. Tests that need a resolvable API-key actor set ``user_id`` on their auth
    payload or patch their module-level ``db`` directly, so this default does not affect them.
    """
    allow = lambda *a, **k: True  # noqa: E731 - tiny stub
    no_fallback_actor = lambda *a, **k: None  # noqa: E731
    try:
        module = __import__("app.database", fromlist=["db"])
    except Exception:
        yield
        return
    monkeypatch.setattr(module.db, "user_has_permission", allow)
    monkeypatch.setattr(module.db, "get_fallback_creator_user_id_for_tenant", no_fallback_actor)
    yield


@pytest.fixture(autouse=True)
def _no_repository_manifest_by_default(monkeypatch):
    """
    Keep whole-scan tests off the network: the scanner reads ``.apiome/repo.yaml`` (REPO-2.2)
    at the start of every pass. Default that read to "no manifest" so tests that drive
    ``scan_repository_branch_into_index`` without stubbing GitHub run on the default ignore
    rules; the REPO-2.2 tests pass their own ``manifest_fetch``.
    """

    def _missing(*_args, **_kwargs):
        raise ValueError("GitHub file not found (path or ref may be stale)")

    monkeypatch.setattr("app.repository_file_scan.read_scan_manifest_text", _missing)


@pytest.fixture(autouse=True)
def _no_stored_overlay_chain_by_default(request, monkeypatch):
    """
    Keep export tests hermetic: every export and verify reads the revision's stored overlay chain
    (GVM-4.3, ``apiome.version_overlays``) before applying inline overlays. Default that read to
    "no chain" so export tests run without Postgres. Tests of the chain patch it with their own rows,
    and ``requires_db`` tests read the real table.
    """
    if request.node.get_closest_marker("requires_db") is not None:
        return
    monkeypatch.setattr("app.version_overlay_store.list_overlays", lambda *_args, **_kwargs: [])


@pytest.fixture(autouse=True)
def _no_contract_webhook_events_by_default(request, monkeypatch):
    """
    Keep Pact Broker route tests off the database: after a publish or a verification result the
    routes queue contract webhooks (PFX-1.9, ``app.pact_webhook_events``), which reads the webhook
    tables. Default that to "nothing queued" so route tests with a faked store stay hermetic.
    ``requires_db`` tests run the real thing, and tests of the hook patch it themselves.
    """
    if request.node.get_closest_marker("requires_db") is not None:
        return
    monkeypatch.setattr("app.pact_broker_routes.fire_publish_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "app.pact_broker_verification_routes.fire_verification_events", lambda *_args, **_kwargs: []
    )


@pytest.fixture(autouse=True)
def _fresh_authz_cache():
    """Start every test with empty authorization and API-key caches (DBP-1.3, #7186).

    The caches are process-wide, so a context or key resolved in one test would otherwise be
    served to a later test that seeds different members, roles or keys (often with raw SQL,
    which does not invalidate them).
    """
    try:
        from app import authz_cache
    except Exception:
        yield
        return
    authz_cache.invalidate_all()
    yield
    authz_cache.invalidate_all()


@pytest.fixture(autouse=True)
def _fresh_browse_public_cache():
    """Start every test with an empty public Browse directory cache (DBP-1.16, #7199).

    The cache is process-wide and keyed by the query's parameters, so a directory answer read in
    one test would otherwise be served to a later test that patches the database with other rows.
    """
    try:
        from app import browse_public_cache
    except Exception:
        yield
        return
    browse_public_cache.invalidate_all()
    yield
    browse_public_cache.invalidate_all()


@pytest.fixture(autouse=True)
def _fresh_mcp_catalog_insight_cache():
    """Start every test with an empty MCP catalog insight cache (DBP-1.17, #7200).

    The cache is process-wide and keyed by tenant id, so an insight read in one test would
    otherwise be served to a later test that patches the database with another catalog.
    """
    try:
        from app import mcp_catalog_insight_cache
    except Exception:
        yield
        return
    mcp_catalog_insight_cache.invalidate_all()
    yield
    mcp_catalog_insight_cache.invalidate_all()


@pytest.fixture(autouse=True)
def _fresh_canonical_model_cache():
    """Start every test with an empty canonical-model cache (COA-5.4, #7080).

    The cache is process-wide and keyed by source digest, so a model parsed in one test would
    otherwise be served to a later test that patches the adapter for the same text.
    """
    from app.revision_source import canonical_model_cache

    canonical_model_cache().clear()
    yield
    canonical_model_cache().clear()


@pytest.fixture(autouse=True)
def _fresh_document_store():
    """
    Give every test its own process-wide document store (COA-5.3, #7079). Imports write their
    original through ``get_document_store()``, and the ``db`` backend keeps the database handle it
    first saw, so a store built while one test had ``app.database.db`` patched must not reach the
    next test.
    """
    from app.document_store import set_document_store

    set_document_store(None)
    yield
    set_document_store(None)
