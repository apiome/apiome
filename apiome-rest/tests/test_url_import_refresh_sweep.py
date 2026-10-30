"""Refresh URL-sourced imports — fetch, capture and sweep (RAR-6.1, #3538).

The store is an in-memory fake and the network a mock transport or a scripted fetcher, so the
tests pin behaviour without a database: the conditional GET sends the validators and reads 304 /
200 / errors; capture records the validators (or the error) and never fetches an authenticated
URL; a tick skips 304s and unchanged documents, holds an edited version, starts a spec-faithful
re-import for a newer document and promotes its validators once the import completes, backs off
on failures, and does nothing with the kill switch off.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app import url_import_refresh_sweep as sweep
from app import url_import_store
from app.refresh_source import RefreshSourceError
from app.url_import_refresh import UrlImportError, checksum_bytes

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_VERSION = "33333333-3333-4333-8333-333333333333"
_USER = "44444444-4444-4444-8444-444444444444"
_URL = "https://specs.example.com/orders.json"
_OLD = "Wed, 21 Oct 2026 07:28:00 GMT"
_NEW = "Thu, 29 Oct 2026 09:00:00 GMT"
_V1 = b'{"openapi":"3.1.0","info":{"version":"1"}}'
_V2 = b'{"openapi":"3.1.0","info":{"version":"2"}}'
_NOW = datetime(2026, 10, 30, 14, 3, tzinfo=timezone.utc)


# --- fetch_conditional ----------------------------------------------------------------------


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Treat every host as public (no DNS lookups in tests)."""
    monkeypatch.setattr("app.ssrf_guard.validate_url", lambda url, **kw: None)


def test_a_conditional_get_sends_the_validators_and_reads_200():
    seen: List[httpx.Request] = []

    def handler(request):
        seen.append(request)
        headers = {"ETag": '"v2"', "Last-Modified": _NEW, "Content-Type": "application/json"}
        return httpx.Response(200, content=_V2, headers=headers)

    result = sweep.fetch_conditional(_URL, etag='"v1"', last_modified=_OLD, client=_client(handler))
    assert seen[0].headers["if-none-match"] == '"v1"' and seen[0].headers["if-modified-since"] == _OLD
    assert (result.status_code, result.body, result.etag, result.last_modified) == (200, _V2, '"v2"', _NEW)
    assert result.content_type == "application/json"


def test_a_304_has_no_body():
    result = sweep.fetch_conditional(_URL, etag='"v1"', client=_client(lambda r: httpx.Response(304)))
    assert (result.status_code, result.body) == (304, b"")


@pytest.mark.parametrize(("status", "error_class"), [(404, "not-found"), (401, "auth"), (503, "unavailable")])
def test_an_http_error_raises_with_its_class(status, error_class):
    with pytest.raises(RefreshSourceError) as caught:
        sweep.fetch_conditional(_URL, client=_client(lambda r: httpx.Response(status)))
    assert caught.value.error_class == error_class and caught.value.http_status == status


def test_no_answer_and_oversized_documents_raise(monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(RefreshSourceError) as caught:
        sweep.fetch_conditional(_URL, client=_client(down))
    assert caught.value.error_class == "unavailable"
    monkeypatch.setattr(sweep, "MAX_DOCUMENT_BYTES", 4)
    with pytest.raises(RefreshSourceError, match="larger than"):
        sweep.fetch_conditional(_URL, client=_client(lambda r: httpx.Response(200, content=_V1)))


def test_a_blocked_address_raises(monkeypatch):
    from app.ssrf_guard import SSRFError

    def refuse(url, **kw):
        raise SSRFError("private address")

    monkeypatch.setattr("app.ssrf_guard.validate_url", refuse)
    with pytest.raises(RefreshSourceError) as caught:
        sweep.fetch_conditional("http://10.0.0.1/a.json", client=_client(lambda r: httpx.Response(200)))
    assert caught.value.error_class == "blocked"


# --- fake store -----------------------------------------------------------------------------


class _Store:
    """In-memory url_import_store."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.versions: Dict[str, Optional[str]] = {}  # version id -> content checksum
        self.calls: List[tuple] = []

    def install(self, monkeypatch) -> "_Store":
        for name in (
            "upsert_spec",
            "list_due",
            "tenant_slug",
            "record_check",
            "record_anchors",
            "record_failure",
            "record_started",
            "record_diverged",
            "record_finished",
        ):
            monkeypatch.setattr(url_import_store, name, getattr(self, name))
        monkeypatch.setattr(
            sweep,
            "current_version_checksum",
            lambda db, tenant_id, version_id: (version_id in self.versions, self.versions.get(version_id)),
        )
        return self

    def add(self, **overrides) -> Dict[str, Any]:
        row = {
            "id": f"s-{len(self.rows) + 1}",
            "tenant_id": _TENANT,
            "project_id": _PROJECT,
            "url": _URL,
            "source_kind": "openapi",
            "format_override": None,
            "content_type": "application/json",
            "options_json": {"classPrefix": "Ord"},
            "spec_schema_version": 1,
            "created_by": _USER,
            "authenticated": False,
            "etag": '"v1"',
            "last_modified": _OLD,
            "content_checksum": checksum_bytes(_V1),
            "last_version_id": _VERSION,
            "post_import_checksum": "pc-1",
            "pending_job_id": None,
            "last_status": None,
            "consecutive_failures": 0,
            **overrides,
        }
        self.rows[row["id"]] = row
        self.versions.setdefault(_VERSION, "pc-1")
        return row

    def upsert_spec(self, db, **kw):
        self.calls.append(("upsert", kw))
        return {"id": "s-new", **kw}

    def list_due(self, db, **kw):
        return [dict(r) for r in self.rows.values() if r.get("auto_refresh_enabled", True) and not r["authenticated"]]

    def tenant_slug(self, db, tenant_id):
        return "acme"

    def record_check(self, db, spec_id, *, status, reason):
        self.rows[spec_id].update(last_status=status, last_reason=reason)

    def record_anchors(self, db, spec_id, *, etag, last_modified, checksum, reason):
        self.rows[spec_id].update(etag=etag, last_modified=last_modified, content_checksum=checksum, last_reason=reason)

    def record_failure(self, db, spec_id, *, reason, error, default_interval_seconds):
        row = self.rows[spec_id]
        row.update(last_status="failed", last_reason=reason, last_error=error, pending_job_id=None)
        row["consecutive_failures"] += 1

    def record_started(self, db, spec_id, *, job_id, etag, last_modified, checksum, reason):
        self.rows[spec_id].update(
            pending_job_id=job_id, pending_etag=etag, pending_last_modified=last_modified,
            pending_checksum=checksum, last_status="refreshing", last_reason=reason,
        )

    def record_diverged(self, db, spec_id, *, reason):
        self.rows[spec_id].update(last_status="diverged", last_reason=reason)

    def record_finished(self, db, spec_id, *, version_id, post_import_checksum):
        row = self.rows[spec_id]
        row.update(
            etag=row["pending_etag"], last_modified=row["pending_last_modified"],
            content_checksum=row["pending_checksum"], last_version_id=version_id,
            post_import_checksum=post_import_checksum, last_status="refreshed", pending_job_id=None,
        )


class _DB:
    """Answers only the advisory lock queries."""

    def __init__(self, locked: bool = True) -> None:
        self.locked = locked

    def execute_query(self, sql, params=None):
        return [{"locked": self.locked, "unlocked": True}]


class _Engine:
    """Scripted spec-import engine."""

    def __init__(self) -> None:
        self.started: List[tuple] = []
        self.states: Dict[str, Any] = {}

    async def schedule(self, slug, tenant_id, user_id, request):
        job_id = f"job-{len(self.started) + 1}"
        self.started.append((slug, tenant_id, user_id, request))
        self.states[job_id] = SimpleNamespace(state="running", result=None, error=None)
        return SimpleNamespace(job_id=job_id)

    async def status(self, slug, job_id):
        if job_id not in self.states:
            raise LookupError(job_id)
        return self.states[job_id]


def _fetcher(*responses):
    """A fetch function answering the scripted responses in order and recording its calls."""
    queue = list(responses)
    calls: List[Dict[str, Any]] = []

    def fetch(url, *, etag=None, last_modified=None):
        calls.append({"url": url, "etag": etag, "last_modified": last_modified})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    fetch.calls = calls
    return fetch


@pytest.fixture
def fake(monkeypatch) -> _Store:
    return _Store().install(monkeypatch)


@pytest.fixture
def engine() -> _Engine:
    return _Engine()


def _tick(engine: _Engine, fetch, db=None):
    return asyncio.run(
        sweep.process_url_import_refresh_sweep(
            db or _DB(), fetch=fetch, schedule=engine.schedule, job_status=engine.status, now=_NOW
        )
    )


# --- sweep ----------------------------------------------------------------------------------


def test_a_304_is_up_to_date(fake, engine):
    row = fake.add()
    fetch = _fetcher(sweep.FetchResult(status_code=304))
    assert _tick(engine, fetch) == {"up-to-date": 1}
    assert fetch.calls[0] == {"url": _URL, "etag": '"v1"', "last_modified": _OLD}
    stored = fake.rows[row["id"]]
    assert (stored["last_status"], stored["last_reason"]) == ("up-to-date", "not-modified")
    assert engine.started == []


def test_an_unchanged_200_is_up_to_date(fake, engine):
    row = fake.add()
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V1, '"v1b"', _NEW))) == {"up-to-date": 1}
    assert fake.rows[row["id"]]["last_reason"] == "idempotent" and engine.started == []


def test_a_newer_document_starts_a_spec_faithful_reimport_then_promotes_its_validators(fake, engine):
    row = fake.add()
    fetch = _fetcher(sweep.FetchResult(200, _V2, '"v2"', _NEW, "application/json"))
    assert _tick(engine, fetch) == {"refreshing": 1}
    [(slug, tenant_id, user_id, request)] = engine.started
    assert (slug, tenant_id, user_id) == ("acme", _TENANT, _USER)
    assert request.metadata.project.project_id == _PROJECT
    assert request.metadata.version.version_id == "2026-10-30T14:03Z"
    assert request.metadata.repository_import_spec.options["classPrefix"] == "Ord"
    stored = fake.rows[row["id"]]
    assert (stored["pending_job_id"], stored["etag"]) == ("job-1", '"v1"')  # anchors move only on success

    # Still running: nothing changes.
    assert _tick(engine, _fetcher()) == {}
    # Completed: the new version and validators become the anchors.
    new_version = "55555555-5555-4555-8555-555555555555"
    fake.versions[new_version] = "pc-2"
    engine.states["job-1"] = SimpleNamespace(
        state="completed", result=SimpleNamespace(version_record_id=new_version), error=None
    )
    assert _tick(engine, _fetcher()) == {"refreshed": 1}
    stored = fake.rows[row["id"]]
    anchors = (stored["etag"], stored["last_modified"], stored["content_checksum"])
    assert anchors == ('"v2"', _NEW, checksum_bytes(_V2))
    promoted = (stored["last_version_id"], stored["post_import_checksum"], stored["pending_job_id"])
    assert promoted == (new_version, "pc-2", None)


def test_a_failed_import_keeps_the_old_anchors(fake, engine):
    row = fake.add(pending_job_id="job-9")
    engine.states["job-9"] = SimpleNamespace(state="failed", result=None, error=SimpleNamespace(message="bad spec"))
    assert _tick(engine, _fetcher()) == {"failed": 1}
    stored = fake.rows[row["id"]]
    assert (stored["etag"], stored["last_reason"], stored["last_error"]) == ('"v1"', "import-failed", "bad spec")


def test_a_lost_import_job_fails(fake, engine):
    row = fake.add(pending_job_id="job-gone")
    assert _tick(engine, _fetcher()) == {"failed": 1}
    assert fake.rows[row["id"]]["last_reason"] == "import-lost"


def test_an_edited_version_holds_the_refresh(fake, engine):
    row = fake.add()
    fake.versions[_VERSION] = "pc-edited"
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V2, None, _NEW))) == {"diverged": 1}
    assert (fake.rows[row["id"]]["last_status"], fake.rows[row["id"]]["last_reason"]) == ("diverged", "manual-edit")
    assert engine.started == []


def test_a_deleted_baseline_version_does_not_hold(fake, engine):
    fake.add(last_version_id="66666666-6666-4666-8666-666666666666")
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V2, None, _NEW))) == {"refreshing": 1}


def test_no_anchors_records_a_baseline(fake, engine):
    row = fake.add(etag=None, last_modified=None, content_checksum=None)
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V2, '"v2"', _NEW))) == {"up-to-date": 1}
    stored = fake.rows[row["id"]]
    baseline = (stored["etag"], stored["content_checksum"], stored["last_reason"])
    assert baseline == ('"v2"', checksum_bytes(_V2), "baseline")
    assert engine.started == []


def test_a_fetch_failure_is_recorded_and_does_not_stop_the_tick(fake, engine):
    first = fake.add()
    second = fake.add(url="https://other.example.com/b.json")
    fetch = _fetcher(RefreshSourceError("HTTP 503", http_status=503), sweep.FetchResult(status_code=304))
    assert _tick(engine, fetch) == {"failed": 1, "up-to-date": 1}
    failed = fake.rows[first["id"]]
    assert (failed["last_reason"], failed["consecutive_failures"]) == ("unavailable", 1)
    assert fake.rows[second["id"]]["last_status"] == "up-to-date"


def test_an_unknown_importer_fails(fake, engine):
    fake.add(created_by=None)
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V2, None, _NEW))) == {"failed": 1}


def test_a_schedule_error_fails_the_lineage(fake, engine):
    row = fake.add()

    async def boom(*args):
        raise RuntimeError("worker down")

    engine.schedule = boom
    assert _tick(engine, _fetcher(sweep.FetchResult(200, _V2, None, _NEW))) == {"failed": 1}
    assert fake.rows[row["id"]]["last_reason"] == "unexpected"


def test_the_kill_switch_and_the_lock_stop_the_tick(fake, engine, monkeypatch):
    from app.config import settings

    fake.add()
    fetch = _fetcher()
    assert _tick(engine, fetch, db=_DB(locked=False)) == {}
    monkeypatch.setattr(settings, "refresh_enabled", False)
    assert _tick(engine, fetch) == {}
    assert fetch.calls == []


# --- capture --------------------------------------------------------------------------------


def _record(fake, monkeypatch, **overrides):
    kw = dict(
        tenant_id=_TENANT,
        user_id=_USER,
        project_id=_PROJECT,
        url="HTTPS://Specs.Example.com/orders.json#x",
        source_kind="openapi",
        format_override=None,
        content_type="application/json",
        options={"classPrefix": "Ord", "dryRun": False},
        authenticated=False,
        version_id=_VERSION,
    )
    kw.update(overrides)
    return sweep.record_url_import(None, **kw)


def test_capture_records_the_validators_and_the_baseline(fake, monkeypatch):
    fetch = _fetcher(sweep.FetchResult(200, _V1, '"v1"', _OLD))
    fake.versions[_VERSION] = "pc-1"
    _record(fake, monkeypatch, fetch=fetch)
    [(_, stored)] = fake.calls
    assert stored["url"] == "https://specs.example.com/orders.json"
    anchors = (stored["etag"], stored["last_modified"], stored["content_checksum"])
    assert anchors == ('"v1"', _OLD, checksum_bytes(_V1))
    assert (stored["last_version_id"], stored["post_import_checksum"]) == (_VERSION, "pc-1")
    assert stored["options"] == {"classPrefix": "Ord"} and stored["last_error"] is None


def test_capture_records_a_failed_fetch(fake, monkeypatch):
    _record(fake, monkeypatch, fetch=_fetcher(RefreshSourceError("HTTP 404", http_status=404)))
    [(_, stored)] = fake.calls
    assert stored["etag"] is None and stored["content_checksum"] is None and stored["last_error"] == "HTTP 404"


def test_an_authenticated_import_is_never_fetched(fake, monkeypatch):
    fetch = _fetcher()
    _record(fake, monkeypatch, authenticated=True, fetch=fetch)
    assert fetch.calls == [] and fake.calls[0][1]["authenticated"] is True


def test_capture_refuses_a_url_with_credentials(fake, monkeypatch):
    with pytest.raises(UrlImportError):
        _record(fake, monkeypatch, url="https://me:pw@example.com/a.json", fetch=_fetcher())
