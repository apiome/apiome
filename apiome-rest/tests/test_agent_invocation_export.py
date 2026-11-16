"""Agent invocation audit export — ATQ-4.5 (#5847), without a database.

The live behaviour (a finalized day equals a direct query row for row, the secret sweep) is in
``test_agent_invocation_export_db``. This file pins what needs no database:

* the key fingerprint is stable, case-insensitive, never the bare id, and never derived from
  anything but the id;
* a non-final day is a ``409`` carrying ``finalizesAfter`` (day end + the sweep grace); a day past
  retention is a ``410`` stating the retention and the oldest exportable day; retention wins;
* records keep every stored column in order, append ``key_name`` / ``key_fingerprint``, and render
  UUIDs, instants, decimals and booleans plainly; CSV and JSON Lines lines are well-formed;
* the stream pages on ``(invoked_at, id)`` until a short page;
* the route requires ``api_keys:view``, refuses before auditing, audits
  ``agent.invocations.export`` and streams an attachment.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent_invocation_export import (
    AUDIT_EXPORT,
    CODE_DAY_NOT_FINAL,
    CODE_DAY_PAST_RETENTION,
    EXTRA_COLUMNS,
    FINALIZE_GRACE,
    InvocationExportError,
    check_day,
    csv_line,
    export_columns,
    export_lines,
    export_record,
    jsonl_line,
    key_fingerprint,
)
from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_AUTH = {"tenant_id": _TENANT, "user_id": "user-1", "user_email": "ops@example.com", "auth_method": "jwt"}
_KEY = "0b8e6a4e-9a52-4d1f-8f43-6f1c2f6f4a11"
_TOOLSET = "44444444-4444-4444-8444-444444444444"
_DAY = date(2026, 11, 10)
_NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
_STORED = [
    "id",
    "tenant_id",
    "key_id",
    "toolset_id",
    "tool_name",
    "target",
    "invoked_at",
    "invoked_day",
    "latency_ms",
    "outcome",
    "error_code",
    "http_status",
    "request_bytes",
    "response_bytes",
    "sampled",
]
_URL = "/v1/tenants/acme/agent-invocations/export"


def _row(n: int, *, key_name: Optional[str] = "ci-agent") -> Dict[str, Any]:
    """A stored row as psycopg2 returns it (native types), ``n`` seconds into the day."""
    return {
        "id": uuid.UUID(int=n + 1),
        "tenant_id": uuid.UUID(_TENANT),
        "key_id": uuid.UUID(_KEY),
        "toolset_id": uuid.UUID(_TOOLSET),
        "tool_name": "listPets",
        "target": "prod",
        "invoked_at": datetime(2026, 11, 10, tzinfo=timezone.utc) + timedelta(seconds=n),
        "invoked_day": _DAY,
        "latency_ms": 40 + n,
        "outcome": "success" if n % 2 == 0 else "upstream_error",
        "error_code": None if n % 2 == 0 else "upstream_timeout",
        "http_status": 200 if n % 2 == 0 else None,
        "request_bytes": Decimal(12),
        "response_bytes": 340,
        "sampled": False,
        "key_name": key_name,
    }


class _FakeDb:
    """Answers the export's three reads from memory and records audit writes.

    Attributes:
        rows: The day's stored rows (with ``key_name``), any order.
        finalized_at: The day's finalization instant, or ``None``.
        raw_cutoff: The tenant's raw retention cutoff, or ``None``.
        pages: How many row pages were read.
        audits: Every ``write_access_audit`` call's keyword arguments.
    """

    def __init__(
        self,
        rows: List[Dict[str, Any]],
        *,
        finalized_at: Optional[datetime] = _NOW,
        raw_cutoff: Optional[datetime] = None,
    ) -> None:
        self.rows = rows
        self.finalized_at = finalized_at
        self.raw_cutoff = raw_cutoff
        self.pages = 0
        self.audits: List[Dict[str, Any]] = []

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if "information_schema.columns" in query:
            return [{"column_name": name} for name in _STORED]
        if "agent_invocation_rollup_days" in query:
            return [{"finalized_at": self.finalized_at, "raw_cutoff": self.raw_cutoff}]
        assert "FROM apiome.agent_invocations i" in query
        assert "key_hash" not in query and "key_prefix" not in query
        self.pages += 1
        ordered = sorted(self.rows, key=lambda r: (r["invoked_at"], str(r["id"])))
        if "(i.invoked_at, i.id) >" in query:
            after = (params[3], params[4])
            ordered = [r for r in ordered if (r["invoked_at"], str(r["id"])) > (after[0], after[1])]
        return ordered[: params[-1]]

    def write_access_audit(self, **kwargs: Any) -> None:
        self.audits.append(kwargs)


# ---------------------------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------------------------


def test_fingerprint_is_stable_and_case_insensitive() -> None:
    assert key_fingerprint(_KEY) == key_fingerprint(_KEY.upper()) == key_fingerprint(uuid.UUID(_KEY))
    assert key_fingerprint(_KEY).startswith("sha256:")
    assert len(key_fingerprint(_KEY)) == len("sha256:") + 32


def test_fingerprint_hides_the_id_and_separates_keys() -> None:
    other = "11111111-2222-4333-8444-555555555555"
    assert key_fingerprint(_KEY) != key_fingerprint(other)
    assert _KEY not in key_fingerprint(_KEY)
    assert _KEY.replace("-", "") not in key_fingerprint(_KEY)


def test_fingerprint_of_no_key_is_none() -> None:
    assert key_fingerprint(None) is None


# ---------------------------------------------------------------------------------------------
# Day rules
# ---------------------------------------------------------------------------------------------


def test_a_final_day_within_retention_passes() -> None:
    check_day(_DAY, finalized_at=_NOW, raw_cutoff=_NOW - timedelta(days=30), now=_NOW)
    check_day(_DAY, finalized_at=_NOW, raw_cutoff=None, now=_NOW)


def test_a_day_that_is_not_final_is_409_with_the_finalization_time() -> None:
    with pytest.raises(InvocationExportError) as caught:
        check_day(_DAY, finalized_at=None, raw_cutoff=None, now=_NOW)
    exc = caught.value
    assert exc.status == 409 and exc.code == CODE_DAY_NOT_FINAL
    expected = datetime(2026, 11, 11, tzinfo=timezone.utc) + FINALIZE_GRACE
    assert exc.detail()["finalizesAfter"] == expected.isoformat()
    assert exc.detail()["day"] == "2026-11-10"
    assert expected.isoformat() in exc.message


def test_a_day_past_retention_is_410_with_the_retention_stated() -> None:
    cutoff = _NOW - timedelta(days=7)  # 2026-11-09 12:00: the 9th is partly pruned
    with pytest.raises(InvocationExportError) as caught:
        check_day(date(2026, 11, 9), finalized_at=_NOW, raw_cutoff=cutoff, now=_NOW)
    detail = caught.value.detail()
    assert caught.value.status == 410
    assert detail["code"] == CODE_DAY_PAST_RETENTION
    assert detail["retentionDays"] == 7
    assert detail["oldestExportableDay"] == "2026-11-10"
    assert "7 days" in detail["message"]
    # The first whole day inside retention is exportable.
    check_day(date(2026, 11, 10), finalized_at=_NOW, raw_cutoff=cutoff, now=_NOW)


def test_a_cutoff_at_midnight_keeps_that_day_exportable() -> None:
    cutoff = datetime(2026, 11, 9, tzinfo=timezone.utc)
    check_day(date(2026, 11, 9), finalized_at=_NOW, raw_cutoff=cutoff, now=cutoff + timedelta(days=7))
    with pytest.raises(InvocationExportError) as caught:
        check_day(date(2026, 11, 8), finalized_at=_NOW, raw_cutoff=cutoff, now=cutoff + timedelta(days=7))
    assert caught.value.detail()["oldestExportableDay"] == "2026-11-09"


def test_retention_is_reported_before_finality() -> None:
    with pytest.raises(InvocationExportError) as caught:
        check_day(date(2026, 1, 1), finalized_at=None, raw_cutoff=_NOW - timedelta(days=7), now=_NOW)
    assert caught.value.status == 410


# ---------------------------------------------------------------------------------------------
# Records and lines
# ---------------------------------------------------------------------------------------------


def test_columns_keep_table_order_and_append_the_extras_once() -> None:
    assert export_columns(_STORED) == _STORED + list(EXTRA_COLUMNS)
    assert export_columns(["id", "key_name"]) == ["id", "key_name", "key_fingerprint"]


def test_records_render_stored_values_plainly() -> None:
    record = export_record(_row(1), export_columns(_STORED))
    assert list(record) == export_columns(_STORED)
    assert record["id"] == str(uuid.UUID(int=2))
    assert record["invoked_at"] == "2026-11-10T00:00:01+00:00"
    assert record["invoked_day"] == "2026-11-10"
    assert record["request_bytes"] == 12 and isinstance(record["request_bytes"], int)
    assert record["sampled"] is False and record["http_status"] is None
    assert record["key_name"] == "ci-agent"
    assert record["key_fingerprint"] == key_fingerprint(_KEY)


def test_a_deleted_key_keeps_its_fingerprint_and_has_no_name() -> None:
    record = export_record(_row(0, key_name=None), export_columns(_STORED))
    assert record["key_name"] is None
    assert record["key_fingerprint"] == key_fingerprint(_KEY)


def test_jsonl_and_csv_lines() -> None:
    record = {"a": "x—y", "b": None, "c": True, "d": {"k": [1]}}
    line = jsonl_line(record)
    assert line.endswith("\n") and line.count("\n") == 1 and "—" in line
    assert json.loads(line) == record
    cells = next(csv.reader(io.StringIO(csv_line(list(record.values()) + ['a,"b"']))))
    assert cells == ["x—y", "", "true", '{"k":[1]}', 'a,"b"']


@pytest.mark.parametrize("text", ['=HYPERLINK("http://x")', "+1", "-cmd", "@SUM(A1)", "\tx"])
def test_csv_cells_never_start_a_formula(text: str) -> None:
    cell = next(csv.reader(io.StringIO(csv_line([text]))))[0]
    assert cell == "'" + text


def test_csv_keeps_numbers_and_jsonl_keeps_text_exact() -> None:
    assert next(csv.reader(io.StringIO(csv_line([-5, 0, 12.5]))))[0:3] == ["-5", "0", "12.5"]
    assert json.loads(jsonl_line({"key_name": "=evil"}))["key_name"] == "=evil"


def test_the_stream_pages_until_a_short_page() -> None:
    fake = _FakeDb([_row(n) for n in range(5)])
    lines = list(export_lines(fake, _TENANT, _DAY, "jsonl", page_size=2))
    assert fake.pages == 3
    assert [json.loads(line)["latency_ms"] for line in lines] == [40, 41, 42, 43, 44]


def test_csv_of_an_empty_day_is_just_the_header() -> None:
    fake = _FakeDb([])
    lines = list(export_lines(fake, _TENANT, _DAY, "csv"))
    assert lines == [csv_line(export_columns(_STORED))]
    assert list(export_lines(fake, _TENANT, _DAY, "jsonl")) == []


# ---------------------------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _get(fake: _FakeDb, params: Dict[str, Any], *, guard: Any = None) -> Any:
    """GET the export with the route's and the shared audit helper's ``db`` set to ``fake``.

    Returns:
        ``(response, the enforce_permission mock)``.
    """
    with (
        patch("app.agent_invocation_export_routes.db", fake),
        patch("app.usage_controls_routes.db", fake),
        patch(
            "app.agent_invocation_export_routes.enforce_permission", **(guard or {"return_value": "user-1"})
        ) as enforce,
    ):
        response = client.get(_URL, params=params)
    return response, enforce


def test_route_streams_jsonl_as_an_attachment_and_audits() -> None:
    fake = _FakeDb([_row(n) for n in range(3)])
    response, enforce = _get(fake, {"day": "2026-11-10"})
    assert response.status_code == 200, response.text
    assert enforce.call_args.args[2:] == (Resource.API_KEYS, Action.VIEW)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="agent-invocations-2026-11-10.jsonl"' in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    records = [json.loads(line) for line in response.text.splitlines()]
    assert len(records) == 3 and records[0]["key_fingerprint"] == key_fingerprint(_KEY)
    assert len(fake.audits) == 1
    audit = fake.audits[0]
    assert audit["action"] == AUDIT_EXPORT and audit["tenant_id"] == _TENANT
    assert audit["detail"] == {"day": "2026-11-10", "format": "jsonl"}
    assert audit["actor_id"] == "user-1"


def test_route_streams_csv() -> None:
    fake = _FakeDb([_row(0), _row(1)])
    response, _ = _get(fake, {"day": "2026-11-10", "format": "csv"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [r["outcome"] for r in rows] == ["success", "upstream_error"]
    assert rows[1]["error_code"] == "upstream_timeout" and rows[0]["error_code"] == ""


def test_route_refuses_a_day_that_is_not_final_without_auditing() -> None:
    fake = _FakeDb([_row(0)], finalized_at=None)
    response, _ = _get(fake, {"day": "2026-11-10"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_DAY_NOT_FINAL
    assert response.json()["detail"]["finalizesAfter"]
    assert fake.audits == [] and fake.pages == 0


def test_route_refuses_a_day_past_retention() -> None:
    fake = _FakeDb([_row(0)], raw_cutoff=datetime.now(timezone.utc) - timedelta(days=7))
    response, _ = _get(fake, {"day": "2020-01-01"})
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == CODE_DAY_PAST_RETENTION and detail["retentionDays"] == 7
    assert fake.audits == []


def test_route_without_permission_reads_nothing() -> None:
    fake = _FakeDb([_row(0)])
    denied = HTTPException(status_code=403, detail="Forbidden")
    response, _ = _get(fake, {"day": "2026-11-10"}, guard={"side_effect": denied})
    assert response.status_code == 403
    assert fake.pages == 0 and fake.audits == []


def test_route_without_a_tenant_is_403() -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "user-1"}
    fake = _FakeDb([_row(0)])
    response, _ = _get(fake, {"day": "2026-11-10"})
    assert response.status_code == 403


@pytest.mark.parametrize("params", [{}, {"day": "2026-13-01"}, {"day": "2026-11-10", "format": "ndjson"}])
def test_route_validates_day_and_format(params: Dict[str, Any]) -> None:
    fake = _FakeDb([])
    response, _ = _get(fake, params)
    assert response.status_code == 422
