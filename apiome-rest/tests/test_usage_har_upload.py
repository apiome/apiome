"""A HAR upload through the ingest pipeline — RDG-1.4 (#5762).

``tests/golden/usage_har_upload/petstore.events.json`` is what ``apiome usage upload`` builds from
the CLI's HAR fixture corpus (``apiome-cli/tests/fixtures/usage-har/petstore.har``; the CLI's
``test_usage_har.py`` pins that it still does). Here those events run through
:func:`app.usage_ingest.plan_batch` against a published petstore revision, proving the acceptance
criteria on the server side: the counters are deterministic, nothing from the HAR's credential
headers, query values or bodies reaches a planned row, and the field presence the CLI computed
lands in ``usage_field_daily`` grains.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.consumer_surface import SpecIndex
from app.usage_ingest import RevisionMatcher, SourceConfig, plan_batch

GOLDEN = Path(__file__).resolve().parent / "golden" / "usage_har_upload" / "petstore.events.json"
SOURCE_ID = "6f1c9a52-4a5e-4c1b-9d0e-1f2a3b4c5d6e"
NOW = datetime(2026, 10, 18, 13, tzinfo=timezone.utc)

PUBLISHED = {
    "openapi": "3.1.0",
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {"/pets": {"get": {}, "post": {}}, "/pets/{petId}": {"get": {}, "delete": {}}},
}

#: Every credential and value in the CLI's HAR fixture.
SECRETS = (
    "abcDEF1234567890ghiJKL",
    "s3cr3tSessionValue42",
    "ak_live_9f8e7d6c5b4a39281706f5e4d3c2b1a0",
    "c2VjcmV0",
    "alice@example.com",
    "Rex",
    "Spot",
)


def _events() -> List[Dict[str, Any]]:
    return json.loads(GOLDEN.read_text())


def _plan():
    source = SourceConfig(
        id=SOURCE_ID, tenant_id="t", project_id="p", kind="har", environment="staging", field_capture=True
    )
    matcher = RevisionMatcher([("rev-1", SpecIndex(PUBLISHED))])
    return plan_batch(_events(), source, matcher, now=NOW)


def test_the_cli_events_are_accepted_and_matched() -> None:
    plan = _plan()
    assert (plan.received, plan.accepted, plan.unmatched, plan.rejected, plan.sampled_out) == (5, 4, 1, 0, 0)
    operations = sorted({key[3] for key in plan.hourly})
    assert len(operations) == 4
    assert {key[2] for key in plan.unmatched_rows} == {"GET"}


def test_the_counters_are_deterministic() -> None:
    first, second = _plan(), _plan()
    assert repr(sorted(first.hourly.items(), key=repr)) == repr(sorted(second.hourly.items(), key=repr))
    assert repr(sorted(first.field_groups.items(), key=repr)) == repr(sorted(second.field_groups.items(), key=repr))


def test_query_names_and_body_fields_count_as_field_presence() -> None:
    pointers = set()
    for (_env, _day, _operation, direction, _status), group in _plan().field_groups.items():
        pointers |= {(direction, pointer) for pointer in group.pointers}
    assert ("request", "/parameters/query:limit") in pointers
    assert ("request", "/parameters/query:cursor") in pointers
    assert ("response", "/items/0/name") in pointers
    assert ("request", "/tag") in pointers


def test_nothing_from_a_header_query_value_or_body_reaches_a_planned_row() -> None:
    plan = _plan()
    planned = repr(
        (
            plan.hourly,
            plan.unmatched_rows,
            plan.field_groups,
            plan.samples,
            {key: asdict(value) for key, value in plan.unattributed_clients.items()},
        )
    )
    for secret in SECRETS:
        assert secret not in planned
