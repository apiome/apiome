"""Change report between two catalog revisions (CDG-1.2, #5953).

Each side is a real Kong declarative document captured on the revision (the fixture files the
Kong connector produces), so the test covers the whole path: captured source → canonical model
→ emitted OpenAPI → shared change report + classified diff → one stored report and one audit row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import catalog_revision_change_report as report
from app.change_report_render import bundled_system_template_row
from app.database import db

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
OLD, NEW = "aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002"
ORDERS = (Path(__file__).parent / "fixtures" / "connectors" / "kong" / "declarative" / "orders.kong.yaml").read_text()
# One route changed: orders-list moves from /orders to /orders/all.
ORDERS_CHANGED = ORDERS.replace(
    "  - name: orders-list\n    protocols:\n    - http\n    - https\n    methods:\n    - GET\n    hosts:\n"
    "    - api.example.com\n    paths:\n    - /orders\n",
    "  - name: orders-list\n    protocols:\n    - http\n    - https\n    methods:\n    - GET\n    hosts:\n"
    "    - api.example.com\n    paths:\n    - /orders/all\n",
)


def _revision(version_id: str, label: str, content: str) -> Dict[str, Any]:
    return {
        "id": version_id,
        "version_id": label,
        "source_format": "kong",
        "protocol": "http",
        "format_metadata": {"sourceContent": content, "sourceLabel": "orders.kong.yaml", "inputKind": "connector"},
        "metadata": {},
        "created_at": None,
    }


@pytest.fixture
def stored(monkeypatch) -> Dict[str, List[Dict[str, Any]]]:
    revisions = {OLD: _revision(OLD, "kong-old", ORDERS), NEW: _revision(NEW, "kong-new", ORDERS_CHANGED)}
    out: Dict[str, List[Dict[str, Any]]] = {"reports": [], "audits": [], "revisions": [revisions]}

    def _query(sql, params):
        version_id, project_id, tenant_id = params
        row = revisions.get(version_id)
        return [row] if row and project_id == PROJECT and tenant_id == TENANT else []

    def _insert(tenant_id, project_id, published_revision_id, **kwargs):
        row = {"tenant_id": tenant_id, "project_id": project_id, "revision": published_revision_id, **kwargs}
        out["reports"].append(row)
        return row

    def _audit(tenant_id, project_id, version_id, action, outcome, actor_id, detail=None):
        out["audits"].append({"action": action, "outcome": outcome, "version": version_id, "detail": detail})

    monkeypatch.setattr(db, "execute_query", _query)
    monkeypatch.setattr(db, "get_project_by_id", lambda pid, tid: {"id": pid, "name": "orders"})
    monkeypatch.setattr(db, "insert_change_report_if_absent", _insert)
    monkeypatch.setattr(db, "insert_workflow_audit", _audit)
    monkeypatch.setattr(
        "app.publication_change_report._resolve_template_row", lambda t, p: bundled_system_template_row()
    )
    return out


def _generate(**overrides):
    kwargs = dict(tenant_id=TENANT, project_id=PROJECT, revision_version_id=NEW, parent_version_id=OLD, actor_id=ACTOR)
    kwargs.update(overrides)
    return report.generate_catalog_revision_change_report(**kwargs)


def test_a_changed_route_writes_one_report_naming_the_moved_path(stored):
    row = _generate()
    assert row is not None and len(stored["reports"]) == 1
    saved = stored["reports"][0]
    assert saved["revision"] == NEW and saved["baseline_revision_id"] == OLD
    model = saved["change_model_json"]
    assert model["noChanges"] is False
    pointers = {c["pointer"]: c for c in model["classifiedChanges"]["changes"]}
    assert "/paths/~1orders~1all" in pointers
    assert pointers["/paths/~1orders~1all"]["before"] is None
    assert model["classifiedChanges"]["counts"]["total"] == len(pointers)
    assert "/orders/all" in saved["rendered_body"] and "kong-old" in saved["rendered_body"]
    [audit] = stored["audits"]
    assert audit["action"] == report.CHANGE_REPORT_ACTION and audit["outcome"] == "success"
    assert audit["version"] == NEW and audit["detail"]["changeCounts"]["operations"] == len(pointers)


def test_identical_revisions_report_no_changes(stored):
    stored["revisions"][0][NEW]["format_metadata"]["sourceContent"] = ORDERS
    _generate()
    model = stored["reports"][0]["change_model_json"]
    assert model["noChanges"] is True and model["classifiedChanges"]["changes"] == []


def test_a_revision_that_cannot_be_rebuilt_is_audited_as_a_failure_and_never_raises(stored):
    stored["revisions"][0][NEW]["format_metadata"] = {}
    assert _generate() is None
    assert stored["reports"] == []
    [audit] = stored["audits"]
    assert audit["outcome"] == "failure" and audit["detail"]["parentVersionId"] == OLD


def test_a_revision_of_another_item_is_not_found(stored):
    assert _generate(project_id="99999999-9999-4999-8999-999999999999") is None
    assert stored["reports"] == [] and stored["audits"][0]["outcome"] == "failure"
