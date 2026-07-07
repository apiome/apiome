"""Tests for the MCP catalog inventory export (V2-MCP-33.2 / MCAT-19.2, #4651).

Two layers:

* **Serializer unit tests** exercise the pure :mod:`app.mcp_catalog_inventory` layer directly — the
  row → record projection, host extraction (and credential redaction), the derived health label,
  RFC-4180 CSV escaping, and the streamed CSV / JSON shapes — all without a database.
* **Route tests** drive ``GET …/endpoints:export`` against a mocked ``db`` (mirroring
  ``test_mcp_report_card.py``): format / scope negotiation, ``Content-Disposition`` filenames,
  tenant-scoped streaming, the published-only ``scope=public`` variant, and keyset paging over a
  large catalog.
"""

import csv
import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_catalog_inventory import (
    INVENTORY_COLUMNS,
    derive_health,
    inventory_record,
    stream_csv,
    stream_json,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}

_EP1 = "11111111-1111-1111-1111-111111111111"
_EP2 = "22222222-2222-2222-2222-222222222222"


def _row(**over):
    """A fully-populated, healthy export row; override any field per test."""
    base = {
        "id": _EP1,
        "name": "Acme Weather",
        "endpoint_url": "https://mcp.acme.example/mcp",
        "transport": "streamable_http",
        "category": "weather",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "last_discovered_at": "2026-07-06T12:00:00+00:00",
        "last_discovery_status": "changed",
        "consecutive_failures": 0,
        "quarantined_at": None,
        "current_version_id": "aaaa1111-1111-1111-1111-111111111111",
        "score": 88,
        "grade": "B",
        "tool_count": 3,
        "resource_count": 2,
        "resource_template_count": 1,
        "prompt_count": 0,
    }
    base.update(over)
    return base


# ===========================================================================================
# Record projection
# ===========================================================================================


def test_inventory_record_projects_every_column():
    rec = inventory_record(_row())
    # Every declared column key is present in the record.
    for key, _header in INVENTORY_COLUMNS:
        assert key in rec, f"missing column {key}"
    assert rec["id"] == _EP1
    assert rec["name"] == "Acme Weather"
    assert rec["host"] == "mcp.acme.example"
    assert rec["transport"] == "streamable_http"
    assert rec["category"] == "weather"
    assert rec["visibility"] == "private"
    assert rec["published"] is False
    assert rec["grade"] == "B"
    assert rec["score"] == 88
    assert rec["tool_count"] == 3
    assert rec["capability_count"] == 6  # 3 + 2 + 1 + 0
    assert rec["last_discovery_status"] == "changed"
    assert rec["health"] == "healthy"


def test_host_extraction_strips_embedded_credentials_and_port():
    # A credential embedded in the URL (and the port) must never survive into the host column.
    rec = inventory_record(_row(endpoint_url="https://user:secret@host.example:8443/mcp"))
    assert rec["host"] == "host.example"
    assert "secret" not in json.dumps(rec)


def test_host_is_none_for_hostless_or_malformed_targets():
    assert inventory_record(_row(endpoint_url="stdio-command --flag"))["host"] is None
    assert inventory_record(_row(endpoint_url=None))["host"] is None


def test_score_and_grade_gaps_stay_null_not_zero():
    rec = inventory_record(_row(score=None, grade=None))
    assert rec["score"] is None
    assert rec["grade"] is None


def test_capability_counts_default_to_zero_when_absent():
    rec = inventory_record(
        _row(tool_count=None, resource_count=None, resource_template_count=None, prompt_count=None)
    )
    assert rec["tool_count"] == 0
    assert rec["capability_count"] == 0


# ===========================================================================================
# Health label
# ===========================================================================================


def test_health_quarantined_takes_precedence():
    assert derive_health(_row(quarantined_at="2026-07-06T00:00:00+00:00", consecutive_failures=5)) == "quarantined"


def test_health_disabled():
    assert derive_health(_row(enabled=False)) == "disabled"


def test_health_undiscovered_when_no_current_version():
    assert derive_health(_row(current_version_id=None, last_discovered_at=None)) == "undiscovered"


def test_health_failing_on_consecutive_failures():
    assert derive_health(_row(consecutive_failures=2)) == "failing"


def test_health_healthy_default():
    assert derive_health(_row()) == "healthy"


# ===========================================================================================
# CSV serialization
# ===========================================================================================


def test_stream_csv_header_then_rows():
    lines = list(stream_csv([inventory_record(_row())]))
    # Header first, then one line per record.
    assert len(lines) == 2
    reader = list(csv.reader(io.StringIO("".join(lines))))
    assert reader[0] == [h for _k, h in INVENTORY_COLUMNS]
    assert reader[1][reader[0].index("name")] == "Acme Weather"
    assert reader[1][reader[0].index("host")] == "mcp.acme.example"


def test_csv_escapes_commas_quotes_and_newlines():
    # A name with a comma, a quote, and a newline must round-trip through a CSV reader intact.
    nasty = 'Acme, "Weather"\nInc.'
    lines = list(stream_csv([inventory_record(_row(name=nasty))]))
    rows = list(csv.reader(io.StringIO("".join(lines))))
    assert rows[1][rows[0].index("name")] == nasty


def test_csv_coerces_bool_and_none():
    lines = list(stream_csv([inventory_record(_row(published=True, category=None, score=None))]))
    rows = list(csv.reader(io.StringIO("".join(lines))))
    header = rows[0]
    assert rows[1][header.index("published")] == "true"
    assert rows[1][header.index("category")] == ""
    assert rows[1][header.index("score")] == ""


def test_stream_csv_is_lazy():
    # The serializer must pull records lazily (never materialize the whole catalog).
    result = stream_csv(inventory_record(r) for r in [_row()])
    assert iter(result) is iter(result)  # a generator, not a pre-built list


# ===========================================================================================
# JSON serialization
# ===========================================================================================


def test_stream_json_is_valid_and_carries_metadata_and_count():
    records = [inventory_record(_row(id=_EP1)), inventory_record(_row(id=_EP2, name="Beta"))]
    body = "".join(
        stream_json(records, tenant_slug="acme", scope="all", generated_at="2026-07-07T00:00:00+00:00")
    )
    doc = json.loads(body)  # must parse — proves the streamed fragments form valid JSON
    assert doc["success"] is True
    assert doc["tenant_slug"] == "acme"
    assert doc["scope"] == "all"
    assert doc["generated_at"] == "2026-07-07T00:00:00+00:00"
    assert doc["count"] == 2
    assert [e["id"] for e in doc["endpoints"]] == [_EP1, _EP2]
    assert doc["endpoints"][1]["name"] == "Beta"


def test_stream_json_empty_catalog_is_valid_with_zero_count():
    body = "".join(stream_json([], tenant_slug="acme", scope="public", generated_at="2026-07-07T00:00:00+00:00"))
    doc = json.loads(body)
    assert doc["endpoints"] == []
    assert doc["count"] == 0
    assert doc["scope"] == "public"


# ===========================================================================================
# Route tests
# ===========================================================================================


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_export_csv_default_format_and_filename():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = [_row(id=_EP1), _row(id=_EP2, name="Beta")]
        r = client.get("/v1/mcp/acme/endpoints:export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="catalog-inventory-acme.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    # Header + the two seeded endpoints, matching the catalog rows.
    assert rows[0] == [h for _k, h in INVENTORY_COLUMNS]
    names = {row[rows[0].index("name")] for row in rows[1:]}
    assert names == {"Acme Weather", "Beta"}


def test_export_json_format_and_filename():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = [_row()]
        r = client.get("/v1/mcp/acme/endpoints:export?format=json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="catalog-inventory-acme.json"' in r.headers["content-disposition"]
    doc = r.json()
    assert doc["count"] == 1
    assert doc["endpoints"][0]["host"] == "mcp.acme.example"


def test_export_scope_public_filters_to_published_only():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = []
        r = client.get("/v1/mcp/acme/endpoints:export?scope=public")
    assert r.status_code == 200
    # The published-only variant must ask the DB layer for published rows only.
    _args, kwargs = mdb.list_mcp_endpoints_export_page.call_args
    assert kwargs["published_only"] is True
    assert 'filename="catalog-inventory-acme-public.csv"' in r.headers["content-disposition"]


def test_export_scope_all_is_not_published_only():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = []
        client.get("/v1/mcp/acme/endpoints:export")
    _args, kwargs = mdb.list_mcp_endpoints_export_page.call_args
    assert kwargs["published_only"] is False


def test_export_is_tenant_scoped():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = []
        client.get("/v1/mcp/acme/endpoints:export")
    # Scoping comes from the token tenant, never the URL slug.
    args, _kwargs = mdb.list_mcp_endpoints_export_page.call_args
    assert args[0] == "t1"


def test_export_unknown_format_is_400():
    with patch("app.mcp_catalog_routes.db"):
        r = client.get("/v1/mcp/acme/endpoints:export?format=xlsx")
    assert r.status_code == 400


def test_export_unknown_scope_is_400():
    with patch("app.mcp_catalog_routes.db"):
        r = client.get("/v1/mcp/acme/endpoints:export?scope=world")
    assert r.status_code == 400


def test_export_never_leaks_the_endpoint_url_credential():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.list_mcp_endpoints_export_page.return_value = [
            _row(endpoint_url="https://user:topsecret@mcp.acme.example/mcp")
        ]
        r = client.get("/v1/mcp/acme/endpoints:export")
    assert "topsecret" not in r.text
    assert "mcp.acme.example" in r.text


def test_export_streams_large_catalog_via_keyset_paging():
    # A catalog larger than one page must be walked page-by-page with a keyset cursor, not one read.
    with patch("app.mcp_catalog_routes._INVENTORY_PAGE_SIZE", 2):
        with patch("app.mcp_catalog_routes.db") as mdb:
            page1 = [_row(id=_EP1), _row(id=_EP2, name="Beta")]
            page2 = [_row(id="33333333-3333-3333-3333-333333333333", name="Gamma")]
            mdb.list_mcp_endpoints_export_page.side_effect = [page1, page2]
            r = client.get("/v1/mcp/acme/endpoints:export?format=json")
    doc = r.json()
    assert doc["count"] == 3
    # Two DB round-trips: the second one keyset-cursored past the first page's last id.
    assert mdb.list_mcp_endpoints_export_page.call_count == 2
    second_kwargs = mdb.list_mcp_endpoints_export_page.call_args_list[1].kwargs
    assert second_kwargs["after_id"] == _EP2
