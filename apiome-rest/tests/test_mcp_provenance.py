"""Tests for the pure MCP discovery-provenance assembly (V2-MCP-34.5 / MCAT-20.5, #4659).

Exercises :mod:`app.mcp_provenance` directly over dict fixtures — no DB, no routes. The
central fixture is the acceptance-criteria scenario: one endpoint whose version history
spans **manual + sweep + registry** origins plus one pre-provenance (unattributed)
snapshot, which must reconstruct into the right per-version origins, per-origin counts,
run tallies, and current-version attribution — with the unattributed snapshot reading
``unrecorded``, never any concrete origin.
"""

from datetime import datetime, timezone

from app.mcp_provenance import (
    MAX_VERSION_ORIGINS,
    TRIGGER_UNRECORDED,
    build_endpoint_provenance,
    provenance_added_via_label,
    provenance_trigger_label,
)

_EP = "11111111-1111-1111-1111-111111111111"
_CURRENT = "44444444-4444-4444-4444-444444444444"


def _dt(hour):
    return datetime(2026, 7, 1, hour, 0, 0, tzinfo=timezone.utc)


def _endpoint(**over):
    base = {
        "id": _EP,
        "added_via": "manual",
        "created_at": _dt(8),
        "last_discovered_at": _dt(14),
        "current_version_id": _CURRENT,
    }
    base.update(over)
    return base


def _version(version_id, seq, trigger, *, job=None, hour=9):
    return {
        "id": version_id,
        "version_seq": seq,
        "version_tag": f"2026-07-01T{hour:02d}:00Z",
        "discovery_trigger": trigger,
        "discovery_job_id": job,
        "discovered_at": _dt(hour),
    }


#: The seeded acceptance-criteria history: a pre-provenance v1, then one version per
#: concrete origin — manual (v2), sweep (v3), registry (v4, current).
_SEEDED_VERSIONS = [
    _version("aaaa0000-0000-0000-0000-000000000001", 1, None, hour=9),
    _version("aaaa0000-0000-0000-0000-000000000002", 2, "manual", job="job-m", hour=10),
    _version("aaaa0000-0000-0000-0000-000000000003", 3, "sweep", job="job-s", hour=12),
    _version(_CURRENT, 4, "registry", job="job-r", hour=14),
]

_SEEDED_JOB_STATS = [
    {"trigger": "manual", "total": 2, "completed": 2},
    {"trigger": "registry", "total": 1, "completed": 1},
    {"trigger": "sweep", "total": 6, "completed": 5},
]


def test_seeded_history_reconstructs_across_all_three_origins():
    prov = build_endpoint_provenance(_endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS)
    assert prov.added_via == "manual"
    assert prov.added_via_label == "Registered manually"
    assert prov.version_count == 4
    # One version per concrete origin, plus the unattributed pre-provenance snapshot.
    assert prov.origin_counts == {
        "manual": 1,
        "sweep": 1,
        "registry": 1,
        "unrecorded": 1,
    }
    # Newest-first regardless of input order; each row carries its trigger and job.
    by_seq = [(o.version_seq, o.trigger, o.job_id) for o in prov.origins]
    assert by_seq == [
        (4, "registry", "job-r"),
        (3, "sweep", "job-s"),
        (2, "manual", "job-m"),
        (1, TRIGGER_UNRECORDED, None),
    ]


def test_seeded_history_reconstructs_from_any_input_order():
    shuffled = [_SEEDED_VERSIONS[2], _SEEDED_VERSIONS[0], _SEEDED_VERSIONS[3], _SEEDED_VERSIONS[1]]
    assert build_endpoint_provenance(
        _endpoint(), shuffled, _SEEDED_JOB_STATS
    ) == build_endpoint_provenance(_endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS)


def test_current_origin_flags_the_current_version():
    prov = build_endpoint_provenance(_endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS)
    assert prov.current_origin is not None
    assert prov.current_origin.version_id == _CURRENT
    assert prov.current_origin.trigger == "registry"
    assert prov.current_origin.is_current is True
    # Exactly one row is flagged current.
    assert sum(1 for o in prov.origins if o.is_current) == 1


def test_run_counts_tally_completed_jobs_per_trigger():
    prov = build_endpoint_provenance(_endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS)
    # Completed runs only (queued/running/failed jobs are not "how a version was found").
    assert prov.run_counts == {"manual": 2, "sweep": 5, "registry": 1, "total": 8}


def test_first_and_last_discovered_span_the_history():
    prov = build_endpoint_provenance(_endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS)
    assert prov.first_discovered_at == _dt(9).isoformat()
    assert prov.last_discovered_at == _dt(14).isoformat()


def test_never_discovered_endpoint_still_has_added_provenance():
    prov = build_endpoint_provenance(
        _endpoint(current_version_id=None, last_discovered_at=None), [], []
    )
    assert prov.added_via == "manual"
    assert prov.added_at == _dt(8).isoformat()
    assert prov.version_count == 0
    assert prov.current_origin is None
    assert prov.origins == ()
    assert prov.first_discovered_at is None
    assert prov.last_discovered_at is None
    assert prov.run_counts == {"manual": 0, "sweep": 0, "registry": 0, "total": 0}


def test_unrecorded_is_never_presented_as_a_concrete_origin():
    prov = build_endpoint_provenance(
        _endpoint(current_version_id="aaaa0000-0000-0000-0000-000000000001"),
        [_version("aaaa0000-0000-0000-0000-000000000001", 1, None)],
        [],
    )
    origin = prov.origins[0]
    assert origin.trigger == TRIGGER_UNRECORDED
    assert origin.trigger_label == "Unrecorded"
    assert prov.current_origin is not None
    assert prov.current_origin.trigger == TRIGGER_UNRECORDED
    assert prov.origin_counts["manual"] == 0


def test_unknown_trigger_value_buckets_as_unrecorded_not_mislabeled():
    prov = build_endpoint_provenance(
        _endpoint(),
        [_version("aaaa0000-0000-0000-0000-000000000009", 1, "someday-new-source")],
        [],
    )
    assert prov.origins[0].trigger == TRIGGER_UNRECORDED
    assert prov.origin_counts[TRIGGER_UNRECORDED] == 1


def test_origins_are_capped_with_explicit_overflow():
    many = [
        _version(f"aaaa0000-0000-0000-0000-{i:012d}", i, "sweep", hour=9)
        for i in range(1, MAX_VERSION_ORIGINS + 6)
    ]
    prov = build_endpoint_provenance(_endpoint(current_version_id=None), many, [])
    assert len(prov.origins) == MAX_VERSION_ORIGINS
    assert prov.origins_truncated == 5
    # The cap keeps the newest snapshots and drops the oldest.
    assert prov.origins[0].version_seq == MAX_VERSION_ORIGINS + 5
    # The counts still cover the full history, not just the itemized rows.
    assert prov.origin_counts["sweep"] == MAX_VERSION_ORIGINS + 5


def test_unknown_job_stat_trigger_counts_toward_total_only():
    prov = build_endpoint_provenance(
        _endpoint(),
        _SEEDED_VERSIONS,
        [{"trigger": "mystery", "total": 3, "completed": 3}],
    )
    assert prov.run_counts == {"manual": 0, "sweep": 0, "registry": 0, "total": 3}


def test_as_dict_serializes_the_full_picture():
    payload = build_endpoint_provenance(
        _endpoint(), _SEEDED_VERSIONS, _SEEDED_JOB_STATS
    ).as_dict()
    assert payload["added_via"] == "manual"
    assert payload["added_via_label"] == "Registered manually"
    assert payload["origin_counts"]["registry"] == 1
    assert payload["run_counts"]["total"] == 8
    assert payload["current_origin"]["trigger"] == "registry"
    assert [o["version_seq"] for o in payload["origins"]] == [4, 3, 2, 1]
    assert payload["origins"][0]["trigger_label"] == "Registry refresh"
    assert payload["origins_truncated"] == 0


def test_labels_cover_every_trigger_and_added_via_value():
    assert provenance_trigger_label("manual") == "Manual run"
    assert provenance_trigger_label("sweep") == "Scheduled sweep"
    assert provenance_trigger_label("registry") == "Registry refresh"
    assert provenance_trigger_label(None) == "Unrecorded"
    assert provenance_trigger_label("bogus") == "Unrecorded"
    assert provenance_added_via_label("manual") == "Registered manually"
    assert provenance_added_via_label("registry") == "Imported from a registry"
    assert provenance_added_via_label("import") == "Bulk import"
    # An unknown stored value passes through verbatim rather than being mislabeled.
    assert provenance_added_via_label("weird") == "weird"
    assert provenance_added_via_label(None) == "Unrecorded"


def test_missing_added_via_defaults_to_manual():
    endpoint = _endpoint()
    endpoint.pop("added_via")
    prov = build_endpoint_provenance(endpoint, [], [])
    assert prov.added_via == "manual"
