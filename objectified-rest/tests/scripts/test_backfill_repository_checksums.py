import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_backfill_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_repository_checksums.py"
    spec = importlib.util.spec_from_file_location("backfill_repository_checksums", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        normalized = " ".join(query.split())
        if "UPDATE odb.repository_file" in normalized:
            file_id = str(params[1]) if params is not None else ""
            self.rowcount = 1 if file_id in self.connection.updatable_file_ids else 0
            self.connection.file_updates.append(file_id)
            return
        if "INSERT INTO odb.workflow_audit" in normalized:
            detail_json = str(params[1]) if params is not None else "{}"
            self.connection.audit_rows.append(json.loads(detail_json))
            self.rowcount = 1
            return
        if "UPDATE odb.versions" in normalized:
            version_id = str(params[1]) if params is not None else ""
            self.rowcount = 1 if version_id in self.connection.updatable_version_ids else 0
            self.connection.version_updates.append(version_id)
            return
        raise AssertionError(f"Unexpected SQL in fake cursor: {normalized}")


class _FakeConnection:
    def __init__(self) -> None:
        self.updatable_file_ids: set[str] = set()
        self.updatable_version_ids: set[str] = set()
        self.file_updates: list[str] = []
        self.version_updates: list[str] = []
        self.audit_rows: list[dict[str, Any]] = []
        self.commit_calls = 0

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commit_calls += 1


def test_validate_repository_source_payload_normalizes_expected_fields() -> None:
    mod = _load_backfill_module()
    payload = {
        "repositoryId": "123e4567-e89b-42d3-a456-426614174000",
        "branch": "main",
        "path": "apis/openapi.yaml",
        "commitSha": "A" * 40,
        "contentChecksum": "B" * 64,
        "contentAlgo": "SHA256",
        "importedAt": "2026-04-26T21:30:00Z",
    }

    normalized, error = mod.validate_repository_source_payload(payload)

    assert error is None
    assert normalized is not None
    assert normalized["commitSha"] == "a" * 40
    assert normalized["contentChecksum"] == "b" * 64
    assert normalized["contentAlgo"] == "sha256"


def test_validate_repository_source_payload_rejects_missing_required_fields() -> None:
    mod = _load_backfill_module()
    normalized, error = mod.validate_repository_source_payload({"repositoryId": "123e4567-e89b-42d3-a456-426614174000"})

    assert normalized is None
    assert error is not None
    assert "missing required fields" in error


def test_backfill_file_checksums_updates_rows_writes_audit_and_tracks_failures(monkeypatch) -> None:
    mod = _load_backfill_module()
    conn = _FakeConnection()
    conn.updatable_file_ids.add("file-1")
    report = mod.BackfillReport()

    candidates = [
        mod.FileChecksumCandidate(
            file_id="file-1",
            tenant_id="00000000-0000-0000-0000-000000000111",
            repository_id="00000000-0000-0000-0000-000000000222",
            provider="github",
            owner="acme",
            name="repo",
            path="apis/openapi.yaml",
            blob_sha="abc123",
            linked_account_id="00000000-0000-0000-0000-000000000333",
            access_token="token-1",
        ),
        mod.FileChecksumCandidate(
            file_id="file-2",
            tenant_id="00000000-0000-0000-0000-000000000111",
            repository_id="00000000-0000-0000-0000-000000000222",
            provider="github",
            owner="acme",
            name="repo",
            path="apis/other.yaml",
            blob_sha="def456",
            linked_account_id="00000000-0000-0000-0000-000000000333",
            access_token=None,
        ),
    ]

    monkeypatch.setattr(mod, "_iter_checksum_candidates", lambda _conn, batch_size: [candidates])
    monkeypatch.setattr(mod, "_fetch_github_blob_checksum", lambda **kwargs: "c" * 64)

    class _NoopClient:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mod.httpx, "Client", _NoopClient)

    limiter = mod.CredentialRateLimiter(1000.0)
    mod._backfill_file_checksums(conn, report=report, batch_size=100, limiter=limiter)

    assert report.rows_hashed == 1
    assert report.rows_failed == 1
    assert conn.commit_calls == 1
    assert len(conn.audit_rows) == 1
    assert conn.audit_rows[0]["path"] == "apis/openapi.yaml"
    assert conn.audit_rows[0]["content_checksum_short"] == ("c" * 12)


def test_backfill_file_checksums_counts_reused_when_row_already_updated(monkeypatch) -> None:
    mod = _load_backfill_module()
    conn = _FakeConnection()
    report = mod.BackfillReport(rows_reused=7)

    candidates = [
        mod.FileChecksumCandidate(
            file_id="file-existing",
            tenant_id="00000000-0000-0000-0000-000000000111",
            repository_id="00000000-0000-0000-0000-000000000222",
            provider="github",
            owner="acme",
            name="repo",
            path="apis/openapi.yaml",
            blob_sha="abc123",
            linked_account_id="00000000-0000-0000-0000-000000000333",
            access_token="token-1",
        )
    ]

    monkeypatch.setattr(mod, "_iter_checksum_candidates", lambda _conn, batch_size: [candidates])
    monkeypatch.setattr(mod, "_fetch_github_blob_checksum", lambda **kwargs: "d" * 64)

    class _NoopClient:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mod.httpx, "Client", _NoopClient)

    mod._backfill_file_checksums(conn, report=report, batch_size=100, limiter=mod.CredentialRateLimiter(1000.0))

    assert report.rows_hashed == 0
    assert report.rows_reused == 8
    assert conn.audit_rows == []


def test_migrate_version_repository_source_migrates_valid_and_rejects_invalid(monkeypatch) -> None:
    mod = _load_backfill_module()
    conn = _FakeConnection()
    conn.updatable_version_ids.add("00000000-0000-0000-0000-000000000901")
    report = mod.BackfillReport()

    valid_metadata = {
        "repositorySource": {
            "repositoryId": "123e4567-e89b-42d3-a456-426614174000",
            "branch": "main",
            "path": "apis/openapi.yaml",
            "commitSha": "a" * 40,
            "contentChecksum": "b" * 64,
            "contentAlgo": "sha256",
            "importedAt": "2026-04-26T21:30:00Z",
        }
    }
    invalid_metadata = {"repositorySource": {"repositoryId": "bad-id"}}
    candidates = [
        mod.VersionSourceCandidate(version_id="00000000-0000-0000-0000-000000000901", metadata=valid_metadata),
        mod.VersionSourceCandidate(version_id="00000000-0000-0000-0000-000000000902", metadata=invalid_metadata),
    ]
    monkeypatch.setattr(mod, "_iter_version_source_candidates", lambda _conn, batch_size: [candidates])

    mod._migrate_version_repository_source(conn, report=report, batch_size=100)

    assert report.versions_migrated == 1
    assert report.versions_rejected == 1
    assert report.version_rejections[0]["versionId"] == "00000000-0000-0000-0000-000000000902"
    assert conn.commit_calls == 1
