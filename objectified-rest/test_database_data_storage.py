"""
Unit tests for Database Data Storage implementation.

Tests version_has_data_records, unpublish guard (409 when version has data),
Pydantic models for class_schema / data_record / data_snapshot,
and delete/restore record logic.
"""

import json
import pytest
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.app.main import app
from src.app.database import Database
from src.app.models import FrozenClassSchemaModel, DataRecordModel, DataSnapshotModel


client = TestClient(app)


def _make_conn_cursor_mock(fetchone_returns):
    """Build a mock connection whose cursor returns given fetchone values in order."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = fetchone_returns
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Database.version_has_data_records
# ---------------------------------------------------------------------------

class TestVersionHasDataRecords:
    """Unit tests for Database.version_has_data_records."""

    def test_returns_false_when_no_data_records(self):
        """When no data_record exists for the version's class_schema, returns False."""
        db = Database()
        with patch.object(db, 'execute_query', return_value=[]) as mock_execute:
            result = db.version_has_data_records('version-uuid-123')
            mock_execute.assert_called_once()
            assert mock_execute.call_args[0][1] == ('version-uuid-123',)
            assert result is False

    def test_returns_true_when_data_records_exist(self):
        """When at least one data_record exists for the version's class_schema, returns True."""
        db = Database()
        with patch.object(db, 'execute_query', return_value=[{'1': 1}]) as mock_execute:
            result = db.version_has_data_records('version-uuid-456')
            mock_execute.assert_called_once()
            assert result is True


# ---------------------------------------------------------------------------
# Unpublish endpoint: 409 when version has data records
# ---------------------------------------------------------------------------

def _fake_validate_authentication(
    tenant_slug: str,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
):
    """Fake auth that returns tenant and user for testing. Signature matches validate_authentication."""
    return {
        'tenant_id': 'tenant-1',
        'user_id': 'user-1',
        'auth_method': 'jwt',
    }


class TestUnpublishVersionHasDataGuard:
    """Test that unpublish returns 409 with VERSION_HAS_DATA when version has data records."""

    def teardown_method(self):
        """Clear dependency overrides after each test."""
        if hasattr(app, 'dependency_overrides') and app.dependency_overrides:
            from src.app.auth import validate_authentication
            if validate_authentication in app.dependency_overrides:
                del app.dependency_overrides[validate_authentication]

    @patch('src.app.versions_routes.db')
    def test_unpublish_returns_409_when_version_has_data_records(self, mock_db):
        """Unpublish returns 409 and detail.code VERSION_HAS_DATA when version has data records."""
        from src.app.auth import validate_authentication

        mock_db.get_version_by_id.return_value = {
            'id': 'ver-1',
            'project_id': 'proj-1',
            'published': True,
            'version_id': '1.0.0',
        }
        mock_db.version_has_data_records.return_value = True
        mock_db.unpublish_version.return_value = None

        app.dependency_overrides[validate_authentication] = _fake_validate_authentication
        try:
            response = client.post(
                '/v1/versions/tenant-slug/proj-1/ver-1/unpublish',
                headers={'Authorization': 'Bearer fake-token'},
            )
        finally:
            if validate_authentication in app.dependency_overrides:
                del app.dependency_overrides[validate_authentication]

        assert response.status_code == 409
        data = response.json()
        assert 'detail' in data
        detail = data['detail']
        if isinstance(detail, dict):
            assert detail.get('code') == 'VERSION_HAS_DATA'
            assert 'data records' in detail.get('message', '')
        else:
            assert 'VERSION_HAS_DATA' in str(detail) or 'data records' in str(detail).lower()
        mock_db.unpublish_version.assert_not_called()

    @patch('src.app.versions_routes.db')
    def test_unpublish_succeeds_when_no_data_records(self, mock_db):
        """Unpublish returns 200 and calls unpublish_version when version has no data records."""
        from src.app.auth import validate_authentication

        mock_db.get_version_by_id.return_value = {
            'id': 'ver-1',
            'project_id': 'proj-1',
            'published': True,
            'version_id': '1.0.0',
        }
        mock_db.version_has_data_records.return_value = False
        mock_db.unpublish_version.return_value = {
            'id': 'ver-1',
            'project_id': 'proj-1',
            'published': False,
            'version_id': '1.0.0',
        }

        app.dependency_overrides[validate_authentication] = _fake_validate_authentication
        try:
            response = client.post(
                '/v1/versions/tenant-slug/proj-1/ver-1/unpublish',
                headers={'Authorization': 'Bearer fake-token'},
            )
        finally:
            if validate_authentication in app.dependency_overrides:
                del app.dependency_overrides[validate_authentication]

        assert response.status_code == 200
        mock_db.version_has_data_records.assert_called_once_with('ver-1')
        mock_db.unpublish_version.assert_called_once()


# ---------------------------------------------------------------------------
# Pydantic models for data storage
# ---------------------------------------------------------------------------

class TestDataStorageModels:
    """Unit tests for FrozenClassSchemaModel, DataRecordModel, DataSnapshotModel."""

    def test_frozen_class_schema_model(self):
        """FrozenClassSchemaModel accepts valid fields."""
        m = FrozenClassSchemaModel(
            id='cs-1',
            version_id='ver-1',
            class_id='cls-1',
            schema={'type': 'object', 'properties': {'name': {'type': 'string'}}},
        )
        assert m.id == 'cs-1'
        assert m.version_id == 'ver-1'
        assert m.class_id == 'cls-1'
        assert m.schema['type'] == 'object'

    def test_data_record_model(self):
        """DataRecordModel accepts valid action enum and fields."""
        m = DataRecordModel(
            id='dr-1',
            record_id='rec-1',
            class_schema_id='cs-1',
            action='created',
            record_sequence=1,
            data={'name': 'Test'},
            tenant_id='tenant-1',
        )
        assert m.action == 'created'
        assert m.record_sequence == 1

    def test_data_record_model_actions(self):
        """DataRecordModel accepts all action values."""
        for action in ('created', 'updated', 'deleted', 'restored'):
            m = DataRecordModel(
                id='dr-1',
                record_id='rec-1',
                class_schema_id='cs-1',
                action=action,
                record_sequence=1,
                tenant_id='t1',
            )
            assert m.action == action

    def test_data_record_model_accepts_restored_action(self):
        """DataRecordModel accepts action='restored' (undelete)."""
        m = DataRecordModel(
            id='dr-1',
            record_id='rec-1',
            class_schema_id='cs-1',
            action='restored',
            record_sequence=2,
            data={'name': 'Restored'},
            tenant_id='t1',
        )
        assert m.action == 'restored'
        assert m.record_sequence == 2
        assert m.data == {'name': 'Restored'}

    def test_data_record_model_rejects_invalid_action(self):
        """DataRecordModel raises ValidationError for invalid action values."""
        with pytest.raises(ValidationError) as exc_info:
            DataRecordModel(
                id='dr-1',
                record_id='rec-1',
                class_schema_id='cs-1',
                action='invalid',
                record_sequence=1,
                tenant_id='t1',
            )
        err = exc_info.value
        assert 'action' in str(err).lower() or any(
            'action' in e.get('loc', ()) for e in err.errors()
        )

    def test_data_snapshot_model(self):
        """DataSnapshotModel accepts valid fields."""
        m = DataSnapshotModel(
            record_id='rec-1',
            class_schema_id='cs-1',
            data={'name': 'Current'},
            tenant_id='tenant-1',
        )
        assert m.record_id == 'rec-1'
        assert m.data['name'] == 'Current'


# ---------------------------------------------------------------------------
# Migration script content (data_record_action enum)
# ---------------------------------------------------------------------------

def _scripts_dir() -> Path:
    """Path to objectified-db/scripts (repo root is parent of objectified-rest)."""
    this_file = Path(__file__).resolve()
    repo_root = this_file.parent.parent  # objectified-rest -> objectified-commercial
    return repo_root / 'objectified-db' / 'scripts'


class TestDataRecordActionMigrationScripts:
    """Unit tests that migration scripts contain expected data_record_action enum changes."""

    def test_initial_script_includes_restored_in_enum(self):
        """20260227-120000.sql creates data_record_action with 'restored'."""
        path = _scripts_dir() / '20260227-120000.sql'
        if not path.exists():
            pytest.skip(f"Migration script not found: {path}")
        content = path.read_text()
        assert "data_record_action" in content
        assert "'restored'" in content
        assert "ENUM ('created', 'updated', 'deleted', 'restored')" in content

    def test_alter_script_adds_restored_value(self):
        """20260227-160000.sql alters enum to add 'restored'."""
        path = _scripts_dir() / '20260227-160000.sql'
        if not path.exists():
            pytest.skip(f"Migration script not found: {path}")
        content = path.read_text()
        assert "data_record_action" in content
        assert "ADD VALUE 'restored'" in content
        assert "restored (undeleted)" in content or "restored" in content
        assert "COMMENT ON COLUMN data_record.action" in content


# ---------------------------------------------------------------------------
# Database.delete_data_record
# ---------------------------------------------------------------------------

class TestDeleteDataRecord:
    """Unit tests for Database.delete_data_record."""

    def test_raises_when_access_denied(self):
        """delete_data_record raises ValueError when tenant has no access."""
        db = Database()
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=False) as mock_access:
            with pytest.raises(ValueError) as exc_info:
                db.delete_data_record(
                    record_id='rec-1',
                    class_schema_id='cs-1',
                    tenant_id='tenant-1',
                )
            assert "Access denied" in str(exc_info.value)
            mock_access.assert_called_once_with('cs-1', 'tenant-1')

    def test_raises_when_record_not_found(self):
        """delete_data_record raises ValueError when no snapshot row exists."""
        db = Database()
        mock_conn, mock_cursor = _make_conn_cursor_mock([None])
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=True):
            with patch.object(db, 'connect', return_value=mock_conn):
                with pytest.raises(ValueError) as exc_info:
                    db.delete_data_record(
                        record_id='rec-1',
                        class_schema_id='cs-1',
                        tenant_id='tenant-1',
                    )
                assert "Record not found" in str(exc_info.value)
        mock_conn.rollback.assert_called()
        mock_conn.commit.assert_not_called()

    def test_appends_deleted_event_and_removes_snapshot(self):
        """delete_data_record inserts deleted data_record and deletes data_snapshot."""
        db = Database()
        snapshot_data = {'name': 'Test', 'value': 42}
        mock_conn, mock_cursor = _make_conn_cursor_mock([
            {'data': snapshot_data},
            {'next_seq': 2},
        ])
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=True):
            with patch.object(db, 'connect', return_value=mock_conn):
                db.delete_data_record(
                    record_id='rec-1',
                    class_schema_id='cs-1',
                    tenant_id='tenant-1',
                    deleted_by='user-1',
                )
        assert mock_cursor.execute.call_count == 4
        calls = mock_cursor.execute.call_args_list
        assert 'data_snapshot' in calls[0][0][0] and 'SELECT' in calls[0][0][0]
        assert calls[0][0][1] == ('rec-1', 'cs-1', 'tenant-1')
        assert 'INSERT' in calls[2][0][0] and 'deleted' in calls[2][0][0]
        insert_args = calls[2][0][1]
        assert insert_args[0] == 'rec-1' and insert_args[1] == 'cs-1'
        assert insert_args[2] == 2
        assert json.loads(insert_args[3]) == snapshot_data
        assert insert_args[4] == 'tenant-1' and insert_args[5] == 'user-1'
        assert 'DELETE' in calls[3][0][0] and 'data_snapshot' in calls[3][0][0]
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Database.restore_data_record
# ---------------------------------------------------------------------------

class TestRestoreDataRecord:
    """Unit tests for Database.restore_data_record."""

    def test_raises_when_access_denied(self):
        """restore_data_record raises ValueError when tenant has no access."""
        db = Database()
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=False) as mock_access:
            with pytest.raises(ValueError) as exc_info:
                db.restore_data_record(
                    record_id='rec-1',
                    class_schema_id='cs-1',
                    tenant_id='tenant-1',
                )
            assert "Access denied" in str(exc_info.value)
            mock_access.assert_called_once_with('cs-1', 'tenant-1')

    def test_raises_when_record_not_found(self):
        """restore_data_record raises ValueError when no data_record exists."""
        db = Database()
        mock_conn, mock_cursor = _make_conn_cursor_mock([None])
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=True):
            with patch.object(db, 'connect', return_value=mock_conn):
                with pytest.raises(ValueError) as exc_info:
                    db.restore_data_record(
                        record_id='rec-1',
                        class_schema_id='cs-1',
                        tenant_id='tenant-1',
                    )
                assert "Record not found" in str(exc_info.value)
        mock_conn.rollback.assert_called()
        mock_conn.commit.assert_not_called()

    def test_raises_when_latest_action_not_deleted(self):
        """restore_data_record raises ValueError when latest event is not 'deleted'."""
        db = Database()
        mock_conn, mock_cursor = _make_conn_cursor_mock([
            {'data': {'x': 1}, 'record_sequence': 1, 'action': 'created'},
        ])
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=True):
            with patch.object(db, 'connect', return_value=mock_conn):
                with pytest.raises(ValueError) as exc_info:
                    db.restore_data_record(
                        record_id='rec-1',
                        class_schema_id='cs-1',
                        tenant_id='tenant-1',
                    )
                assert "not deleted" in str(exc_info.value).lower()
        mock_conn.rollback.assert_called()
        mock_conn.commit.assert_not_called()

    def test_inserts_restored_event_and_snapshot(self):
        """restore_data_record inserts restored data_record and new data_snapshot."""
        db = Database()
        data_to_restore = {'name': 'Restored', 'id': 'rec-1'}
        mock_conn, mock_cursor = _make_conn_cursor_mock([
            {'data': data_to_restore, 'record_sequence': 2, 'action': 'deleted'},
        ])
        with patch.object(db, 'assert_class_schema_tenant_access', return_value=True):
            with patch.object(db, 'connect', return_value=mock_conn):
                db.restore_data_record(
                    record_id='rec-1',
                    class_schema_id='cs-1',
                    tenant_id='tenant-1',
                    restored_by='user-1',
                )
        assert mock_cursor.execute.call_count == 3
        calls = mock_cursor.execute.call_args_list
        assert 'data_record' in calls[0][0][0] and 'ORDER BY record_sequence DESC' in calls[0][0][0]
        assert 'INSERT' in calls[1][0][0] and 'restored' in calls[1][0][0]
        insert_args = calls[1][0][1]
        assert insert_args[0] == 'rec-1' and insert_args[1] == 'cs-1'
        assert insert_args[2] == 3
        assert insert_args[3] == 'tenant-1' and insert_args[4] == 'user-1'
        assert 'INSERT' in calls[2][0][0] and 'data_snapshot' in calls[2][0][0]
        snap_args = calls[2][0][1]
        assert json.loads(snap_args[2]) == data_to_restore
        mock_conn.commit.assert_called_once()
