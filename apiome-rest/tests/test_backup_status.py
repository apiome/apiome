"""Tests for backup status surfacing from RC1-1.3 manifests (RC1-3.2, #3617)."""

import json
from datetime import datetime, timedelta, timezone

from app.backup_status import collect_backup_status

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _write_manifest(directory, manifest_id, created_at, *, kind="full", tenant=None, project=None,
                    size_bytes=1234, encrypted=True):
    """Write a backup manifest sidecar matching the apiome-db manifest shape."""
    payload = {
        "manifestVersion": 1,
        "id": manifest_id,
        "kind": kind,
        "tenant": tenant,
        "project": project,
        "createdAt": created_at,
        "rpoMarker": created_at,
        "artifact": f"{manifest_id}.dump",
        "sizeBytes": size_bytes,
        "sha256": "deadbeef",
        "encrypted": encrypted,
        "tableCounts": {},
    }
    (directory / f"{manifest_id}.manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_unconfigured_when_no_dir():
    result = collect_backup_status(None, stale_after_hours=24, now=_NOW)
    assert result["status"] == "unconfigured"
    assert result["backup_count"] == 0
    assert result["latest"] is None


def test_unavailable_when_dir_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = collect_backup_status(str(missing), stale_after_hours=24, now=_NOW)
    assert result["status"] == "unavailable"


def test_empty_when_no_manifests(tmp_path):
    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["status"] == "empty"
    assert result["backup_count"] == 0


def test_fresh_backup_is_ok(tmp_path):
    created = (_NOW - timedelta(hours=1)).isoformat()
    _write_manifest(tmp_path, "bk-1", created)
    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["status"] == "ok"
    assert result["backup_count"] == 1
    assert result["latest"]["id"] == "bk-1"
    assert result["latest_age_seconds"] == 3600.0


def test_old_backup_is_stale(tmp_path):
    created = (_NOW - timedelta(hours=48)).isoformat()
    _write_manifest(tmp_path, "bk-old", created)
    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["status"] == "stale"
    assert "older than" in result["message"]


def test_latest_selected_across_many_and_grouped_by_kind(tmp_path):
    _write_manifest(tmp_path, "full-old", (_NOW - timedelta(hours=10)).isoformat(), kind="full")
    _write_manifest(tmp_path, "full-new", (_NOW - timedelta(hours=2)).isoformat(), kind="full")
    _write_manifest(
        tmp_path, "tenant-1", (_NOW - timedelta(hours=3)).isoformat(), kind="tenant", tenant="acme"
    )

    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["backup_count"] == 3
    assert result["latest"]["id"] == "full-new"  # newest overall
    assert result["latest_by_kind"]["full"]["id"] == "full-new"
    assert result["latest_by_kind"]["tenant"]["id"] == "tenant-1"
    assert result["latest_by_kind"]["tenant"]["tenant"] == "acme"


def test_z_suffix_timestamp_is_parsed(tmp_path):
    created = _NOW.replace(tzinfo=None).isoformat() + "Z"  # e.g. ...T12:00:00Z
    _write_manifest(tmp_path, "bk-z", created)
    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["status"] == "ok"
    assert result["latest_age_seconds"] == 0.0


def test_malformed_manifests_are_skipped(tmp_path):
    (tmp_path / "bad.manifest.json").write_text("not json", encoding="utf-8")
    (tmp_path / "incomplete.manifest.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    _write_manifest(tmp_path, "good", (_NOW - timedelta(hours=1)).isoformat())
    result = collect_backup_status(str(tmp_path), stale_after_hours=24, now=_NOW)
    assert result["backup_count"] == 1  # only the well-formed manifest counts
    assert result["latest"]["id"] == "good"
