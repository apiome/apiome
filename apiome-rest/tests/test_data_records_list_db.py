"""``Database.list_data_records`` and the class-schema lookup against a live Postgres (#3253, #3255).

Seeds a tenant → project → published version → two classes with frozen class schemas, then writes
records through the real accessors (``insert_data_record``, ``update_data_record``,
``delete_data_record``) so the event log is what production writes. Checks: live records only by
default; ``include_deleted`` brings the deleted one back with its last data and ``deleted_at``;
text filters (numbers and strings); JSON sort on a data field (numeric, missing values last) and on
system fields; limit/offset paging and the total; another class's records never leak in.

Runs in one always-rolled-back transaction (the ``tx`` fixture of ``test_catalog_graph_db``).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest

from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db


@pytest.fixture
def data_tx(tx):  # noqa: F811
    """``tx``, with ``close()`` a no-op: the data-record accessors close their connection."""
    db, cursor = tx
    db.connection.close = lambda: None
    return db, cursor


def _seed(cursor: Any) -> Dict[str, str]:
    """A tenant with project ``billing-<suffix>`` version ``1.0.0`` and classes Charge + Refund."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"data {suffix}", f"data-{suffix}"),
    )
    tenant = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Billing', %s, true) RETURNING id::text AS id, slug""",
        (tenant, user, f"billing-{suffix}"),
    )
    project = cursor.fetchone()
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published)
           VALUES (%s, %s, '1.0.0', true) RETURNING id::text AS id""",
        (project["id"], user),
    )
    version = cursor.fetchone()["id"]
    schemas = {}
    for name in ("Charge", "Refund"):
        cursor.execute(
            "INSERT INTO apiome.classes (version_id, name, schema) VALUES (%s, %s, '{}'::jsonb) RETURNING id::text AS id",
            (version, name),
        )
        class_id = cursor.fetchone()["id"]
        cursor.execute(
            """INSERT INTO apiome.class_schema (version_id, class_id, schema)
               VALUES (%s, %s, %s::jsonb) RETURNING id::text AS id""",
            (version, class_id, '{"type": "object"}'),
        )
        schemas[name] = cursor.fetchone()["id"]
    return {"tenant": tenant, "user": user, "project_slug": project["slug"], "version": version, **schemas}


def _records(db, seed) -> Dict[str, str]:
    """Four Charge records (one updated, one deleted) and one Refund record."""
    ids = {}
    for key, data in {
        "a": {"amount": 100, "status": "succeeded"},
        "b": {"amount": 9.5, "status": "failed"},
        "c": {"amount": 20, "status": "succeeded"},
        "d": {"status": "pending"},
    }.items():
        ids[key] = db.insert_data_record(seed["Charge"], seed["tenant"], data, seed["user"])
    db.update_data_record(ids["b"], seed["Charge"], seed["tenant"], {"amount": 9.5, "status": "refunded"}, seed["user"])
    db.delete_data_record(ids["c"], seed["Charge"], seed["tenant"], seed["user"])
    db.insert_data_record(seed["Refund"], seed["tenant"], {"amount": 1}, seed["user"])
    return ids


def test_live_records_by_default_and_deleted_ones_on_request(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)
    ids = _records(db, seed)

    rows, total = db.list_data_records(seed["Charge"], seed["tenant"], sort_field="record_id")
    assert total == 3
    assert {str(r["record_id"]) for r in rows} == {ids["a"], ids["b"], ids["d"]}
    assert all(r["deleted_at"] is None for r in rows)
    updated = next(r for r in rows if str(r["record_id"]) == ids["b"])
    assert updated["data"]["status"] == "refunded"

    rows, total = db.list_data_records(seed["Charge"], seed["tenant"], include_deleted=True)
    assert total == 4
    deleted = next(r for r in rows if str(r["record_id"]) == ids["c"])
    assert deleted["deleted_at"] is not None
    assert deleted["data"] == {"amount": 20, "status": "succeeded"}


def test_filters_compare_as_text(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)
    ids = _records(db, seed)

    rows, total = db.list_data_records(seed["Charge"], seed["tenant"], filters=[("status", "succeeded")])
    assert total == 1 and str(rows[0]["record_id"]) == ids["a"]
    rows, total = db.list_data_records(seed["Charge"], seed["tenant"], filters=[("amount", "9.5")])
    assert total == 1 and str(rows[0]["record_id"]) == ids["b"]
    rows, total = db.list_data_records(
        seed["Charge"], seed["tenant"], filters=[("amount", "9.5"), ("status", "succeeded")]
    )
    assert (rows, total) == ([], 0)


def test_sort_on_a_data_field_is_numeric_with_missing_values_last(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)
    ids = _records(db, seed)

    rows, _ = db.list_data_records(seed["Charge"], seed["tenant"], sort_field="amount")
    assert [str(r["record_id"]) for r in rows] == [ids["b"], ids["a"], ids["d"]]
    rows, _ = db.list_data_records(seed["Charge"], seed["tenant"], sort_field="amount", descending=True)
    assert [str(r["record_id"]) for r in rows] == [ids["a"], ids["b"], ids["d"]]


def test_limit_and_offset_page_through_with_a_stable_total(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)
    _records(db, seed)

    first, total = db.list_data_records(seed["Charge"], seed["tenant"], sort_field="record_id", limit=2)
    second, total2 = db.list_data_records(seed["Charge"], seed["tenant"], sort_field="record_id", limit=2, offset=2)
    assert total == total2 == 3
    assert len(first) == 2 and len(second) == 1
    assert {r["record_id"] for r in first}.isdisjoint({r["record_id"] for r in second})
    assert [r["record_id"] for r in first + second] == sorted(r["record_id"] for r in first + second)


def test_created_at_sort_and_other_classes_and_tenants_stay_out(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)
    _records(db, seed)

    rows, total = db.list_data_records(seed["Refund"], seed["tenant"], sort_field="created_at", descending=True)
    assert total == 1 and rows[0]["data"] == {"amount": 1}
    other_tenant = str(uuid.uuid4())
    assert db.list_data_records(seed["Charge"], other_tenant) == ([], 0)


def test_class_schema_lookup_finds_the_version_and_its_classes(data_tx):
    db, cursor = data_tx
    seed = _seed(cursor)

    found = db.find_data_version(seed["tenant"], seed["project_slug"], "v1.0.0")
    assert found["version"] == "1.0.0" and found["published"] is True
    classes = db.list_version_class_schemas(str(found["version_record_id"]))
    assert [(c["class_name"], str(c["class_schema_id"])) for c in classes] == [
        ("Charge", seed["Charge"]),
        ("Refund", seed["Refund"]),
    ]
    assert db.find_data_version(str(uuid.uuid4()), seed["project_slug"], "1.0.0") is None
