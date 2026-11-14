"""End-to-end ``apiome data import`` → ``apiome data list`` over a stateful mocked REST API (#3259).

The mock keeps every record ``POST /v1/data/{tenant}/records`` receives and answers
``GET /v1/data/{tenant}/records`` from them, so the test checks what a real round trip would: the
1000-row fixture is imported in parallel batches and ``data list`` then counts 1000 records.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app

_ENV = {
    "APIOME_API_KEY": "test-integration-key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_CS = "33333333-3333-4333-8333-333333333333"
_CLASSES = "http://localhost:8000/v1/data/acme/classes?project=billing&version=1.0.0"
_RECORDS = "http://localhost:8000/v1/data/acme/records"
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "data" / "charges-1000.ndjson"
_LOOKUP = {
    "success": True,
    "project": "billing",
    "version": "1.0.0",
    "published": True,
    "classes": [
        {
            "class_schema_id": _CS,
            "class_name": "Charge",
            "schema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string", "enum": ["USD", "EUR"]},
                    "status": {"type": "string"},
                },
                "required": ["amount", "currency", "status"],
            },
        }
    ],
}


class _RecordStore:
    """Holds created records; serves the create and list endpoints from them."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._lock = threading.Lock()

    def create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        with self._lock:
            record_id = f"rc_{len(self.items) + 1}"
            self.items.append({"record_id": record_id, "created_at": None, "data": body["data"]})
        return httpx.Response(200, json={"success": True, "record_id": record_id})

    def list(self, request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        limit = int(query["limit"][0])
        offset = int(query.get("cursor", ["0"])[0])
        page = self.items[offset : offset + limit]
        more = offset + limit < len(self.items)
        return httpx.Response(
            200,
            json={
                "success": True,
                "class_schema_id": query["class_schema_id"][0],
                "total": len(self.items),
                "next_cursor": str(offset + limit) if more else None,
                "items": page,
            },
        )


def test_import_1000_rows_then_list_counts_them(httpx_mock, tmp_path: Path) -> None:
    store = _RecordStore()
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP, is_reusable=True)
    httpx_mock.add_callback(store.create, url=_RECORDS, method="POST", is_reusable=True)
    httpx_mock.add_callback(store.list, url=re.compile(re.escape(_RECORDS) + r"\?.*"), method="GET", is_reusable=True)
    runner = CliRunner()
    report = tmp_path / "report.json"

    imported = runner.invoke(
        app,
        ["data", "import", str(_FIXTURE), "--class", "billing/1.0.0/Charge", "--batch", "100", "--report", str(report)],
        env=_ENV,
    )
    assert imported.exit_code == EXIT_SUCCESS, imported.output
    assert "✔ Imported 1,000 records into billing/1.0.0/Charge." in imported.stdout
    written = json.loads(report.read_text())
    assert written["created_count"] == 1000 and written["failed_count"] == 0
    assert [row["row"] for row in written["rows"]] == list(range(1, 1001))

    listed = runner.invoke(
        app, ["--json", "data", "list", "--class", "billing/1.0.0/Charge", "--all"], env=_ENV
    )
    assert listed.exit_code == EXIT_SUCCESS, listed.output
    records = json.loads(listed.stdout)
    assert len(records) == 1000
    assert sorted(r["data"]["amount"] for r in records) == sorted(round(i * 1.25, 2) for i in range(1, 1001))
