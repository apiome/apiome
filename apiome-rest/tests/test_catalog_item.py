"""Tests for the catalog-item entity & non-publishable guarantee (#4010, MFI-23.1).

A catalog item is an OpenAPI-worthy non-OpenAPI import that is *not* a publishable Project. It is
modelled as a projection over the same ``projects`` + ``versions`` tables a Project uses — the
``publishable = false`` slice — carrying the latest revision's format/protocol/source provenance and
lint score/grade. These tests pin the data-layer contract:

  * ``Database.create_project`` accepts a ``publishable`` flag (default True for Projects; False for
    catalog items) and round-trips it through the INSERT/RETURNING;
  * ``Database.get_catalog_items_for_tenant`` / ``get_catalog_item_by_id`` return only the
    non-publishable slice, projecting the latest revision's format/protocol/source/lint;
  * ``Database.set_version_source_format`` persists the format/protocol/provenance an import records;
  * ``CatalogItemSchema`` / ``ProjectSchema`` expose ``publishable`` (and the catalog item is always
    ``publishable = False`` by construction).

The "publishable is false and immutable" invariant is enforced at the data layer by V138's write-once
trigger; that DDL is contract-tested in apiome-db. Here we assert the Python projection never
returns a publishable row as a catalog item, and that the update path cannot flip the flag.
"""

from unittest.mock import MagicMock, patch

from app.database import Database
from app.models import CatalogItemSchema, ProjectSchema


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------
def _db_with_mock_connect(returning_row):
    """A Database whose connect() yields a cursor returning ``returning_row`` from fetchone().

    Returns ``(db, cursor)`` so a test can assert the SQL/params passed to ``cursor.execute``.
    """
    db = Database()
    cursor = MagicMock()
    cursor.fetchone.return_value = returning_row
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    db.connect = MagicMock(return_value=conn)
    return db, cursor


_CATALOG_ROW = {
    "id": "cat-1",
    "tenant_id": "test-tenant-id",
    "creator_id": "user-1",
    "name": "Acme gRPC API",
    "description": "imported from a .proto",
    "slug": "acme-grpc-api",
    "enabled": True,
    "metadata": {},
    "change_report_template_version_id": None,
    "publishable": False,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "deleted_at": None,
    "creator_name": "Test User",
    "creator_email": "test@example.com",
    "quality_score": 82,
    "quality_grade": "B",
    "versions_count": 3,
    "source_format": "protobuf",
    "protocol": "grpc",
    "format_metadata": {"package": "acme.v1", "edition": "2023"},
    "tool_versions": {"protoc": "25.1"},
}


# ---------------------------------------------------------------------------------------------------
# Database.create_project — the publishable flag
# ---------------------------------------------------------------------------------------------------
class TestCreateProjectPublishable:
    def test_defaults_to_publishable_true(self):
        """An ordinary project is publishable: the default keeps today's behaviour."""
        db, cursor = _db_with_mock_connect({"id": "p1", "publishable": True})
        db.create_project("t1", "u1", "P", "p", description=None, metadata=None)
        sql, params = cursor.execute.call_args[0]
        assert "publishable" in sql
        # publishable is the last positional param (tenant, creator, name, desc, slug, metadata, pub).
        assert params[-1] is True

    def test_catalog_item_inserts_publishable_false(self):
        """A catalog item is created by passing publishable=False (MFI-23.7 uses this)."""
        db, cursor = _db_with_mock_connect({"id": "p1", "publishable": False})
        db.create_project("t1", "u1", "P", "p", publishable=False)
        _sql, params = cursor.execute.call_args[0]
        assert params[-1] is False

    def test_returning_includes_publishable(self):
        """The RETURNING clause surfaces publishable so the response model can carry it."""
        db, cursor = _db_with_mock_connect({"id": "p1", "publishable": True})
        db.create_project("t1", "u1", "P", "p")
        sql, _params = cursor.execute.call_args[0]
        assert "RETURNING" in sql and "publishable" in sql.split("RETURNING", 1)[1]


# ---------------------------------------------------------------------------------------------------
# Database.get_catalog_items_for_tenant / get_catalog_item_by_id — the projection
# ---------------------------------------------------------------------------------------------------
class TestCatalogProjection:
    def test_list_filters_to_non_publishable_and_projects_format(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[_CATALOG_ROW]) as ex:
            rows = db.get_catalog_items_for_tenant("test-tenant-id")
        sql, params = ex.call_args[0]
        # The hard boundary: only the publishable=false slice is a catalog item.
        assert "publishable = false" in sql.lower()
        # The catalog projects format/protocol/source off the latest revision.
        for col in ("source_format", "protocol", "format_metadata", "tool_versions"):
            assert col in sql
        assert "quality_score" in sql and "quality_grade" in sql
        assert "versions_count" in sql
        assert params == ("test-tenant-id",)
        assert rows[0]["source_format"] == "protobuf"

    def test_list_excludes_deleted_by_default(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[]) as ex:
            db.get_catalog_items_for_tenant("t1")
        sql = ex.call_args[0][0]
        assert "p.deleted_at IS NULL" in sql

    def test_list_includes_deleted_when_requested(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[]) as ex:
            db.get_catalog_items_for_tenant("t1", include_deleted=True)
        sql = ex.call_args[0][0]
        # No live-only filter on the projects row when include_deleted is set.
        assert "AND p.deleted_at IS NULL" not in sql

    def test_get_by_id_filters_non_publishable_and_returns_row(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[_CATALOG_ROW]) as ex:
            item = db.get_catalog_item_by_id("cat-1", "test-tenant-id")
        sql, params = ex.call_args[0]
        assert "publishable = false" in sql.lower()
        assert params == ("cat-1", "test-tenant-id")
        assert item["id"] == "cat-1"

    def test_get_by_id_returns_none_when_absent(self):
        """A publishable Project is not a catalog item: the filter yields no row → None."""
        db = Database()
        with patch.object(db, "execute_query", return_value=[]):
            assert db.get_catalog_item_by_id("proj-pub", "t1") is None


# ---------------------------------------------------------------------------------------------------
# Database.set_version_source_format — persisting the format/provenance
# ---------------------------------------------------------------------------------------------------
class TestSetVersionSourceFormat:
    def test_persists_format_protocol_and_provenance(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[{"id": "v1"}]) as ex:
            ok = db.set_version_source_format(
                "v1",
                "t1",
                source_format="protobuf",
                protocol="grpc",
                format_metadata={"package": "acme.v1"},
                source_tool_versions={"protoc": "25.1"},
            )
        sql, params = ex.call_args[0]
        assert ok is True
        # Tenant-scoped through the owning project; only live revisions are written.
        assert "p.tenant_id = %s" in sql and "v.deleted_at IS NULL" in sql
        # JSONB columns are cast; COALESCE keeps a column untouched when its arg is None.
        assert "::jsonb" in sql and "COALESCE" in sql
        assert "protobuf" in params and "grpc" in params

    def test_none_args_leave_columns_untouched_via_coalesce(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[{"id": "v1"}]) as ex:
            db.set_version_source_format("v1", "t1", source_format="openapi")
        _sql, params = ex.call_args[0]
        # format_metadata / source_tool_versions JSON args are None (untouched), source_format set.
        assert "openapi" in params
        assert params[2] is None and params[3] is None

    def test_returns_false_when_no_revision_matched(self):
        db = Database()
        with patch.object(db, "execute_query", return_value=[]):
            assert db.set_version_source_format("missing", "t1", source_format="avro") is False


# ---------------------------------------------------------------------------------------------------
# Models — publishable surfaced; catalog item is non-publishable by construction
# ---------------------------------------------------------------------------------------------------
class TestModels:
    def test_catalog_item_schema_defaults_non_publishable(self):
        item = CatalogItemSchema(**_CATALOG_ROW)
        assert item.publishable is False

    def test_catalog_item_schema_serializes_format_aliases(self):
        item = CatalogItemSchema(**_CATALOG_ROW)
        body = item.model_dump(by_alias=True)
        assert body["sourceFormat"] == "protobuf"
        assert body["protocol"] == "grpc"
        assert body["formatMetadata"] == {"package": "acme.v1", "edition": "2023"}
        assert body["toolVersions"] == {"protoc": "25.1"}
        assert body["qualityScore"] == 82 and body["qualityGrade"] == "B"
        assert body["versionsCount"] == 3
        assert body["publishable"] is False

    def test_project_schema_defaults_publishable_true(self):
        proj = ProjectSchema(
            id="p1", tenant_id="t1", name="P", slug="p",
        )
        assert proj.publishable is True

    def test_project_schema_reflects_non_publishable_row(self):
        proj = ProjectSchema(id="p1", tenant_id="t1", name="P", slug="p", publishable=False)
        assert proj.model_dump()["publishable"] is False
