"""Database tests for registry coverage/stats aggregation (#3454)."""

from unittest.mock import MagicMock, patch

from app.database import Database


def test_get_registry_coverage_stats_maps_row():
    db = Database()
    db.execute_query = MagicMock(
        return_value=[
            {
                "core_type_count": 10,
                "tenant_type_count": 4,
                "imported_count": 2,
                "namespace_count": 3,
                "properties_bound_count": 15,
                "bound_class_count": 5,
                "unresolved_ref_count": 1,
            }
        ]
    )
    out = db.get_registry_coverage_stats("tenant-1")
    assert out == {
        "core_type_count": 10,
        "tenant_type_count": 4,
        "imported_count": 2,
        "namespace_count": 3,
        "properties_bound_count": 15,
        "bound_class_count": 5,
        "unresolved_ref_count": 1,
    }
    db.execute_query.assert_called_once()
    assert db.execute_query.call_args[0][1] == ("tenant-1", "tenant-1", "tenant-1")


def test_get_registry_coverage_stats_empty():
    db = Database()
    db.execute_query = MagicMock(return_value=[])
    out = db.get_registry_coverage_stats("tenant-1")
    assert out == {
        "core_type_count": 0,
        "tenant_type_count": 0,
        "imported_count": 0,
        "namespace_count": 0,
        "properties_bound_count": 0,
        "bound_class_count": 0,
        "unresolved_ref_count": 0,
    }
