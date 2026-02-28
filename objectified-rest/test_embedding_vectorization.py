"""
Unit tests for pgvector/embedding vectorization use cases.

Covers:
- embedding.get_embedding / embed_record_data (Ollama response handling)
- data_routes._schedule_embedding_update (best-effort flow)
- database.update_data_snapshot_embedding (no-op on empty, pgvector unavailable, success path)
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.app.embedding import (
    get_embedding,
    embed_record_data,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
)
from src.app.database import Database
from src.app.data_routes import _schedule_embedding_update


# ---------------------------------------------------------------------------
# embedding.get_embedding
# ---------------------------------------------------------------------------


class TestGetEmbedding:
    """Unit tests for get_embedding (Ollama /api/embed)."""

    @patch("src.app.embedding.urlopen")
    def test_returns_vector_when_ollama_returns_valid_embeddings(self, mock_urlopen):
        """When Ollama returns 200 with embeddings array, returns list of floats."""
        vector = [0.1] * EMBEDDING_DIMENSIONS
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"embeddings": [vector]}).encode("utf-8")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = get_embedding("hello world")

        assert result is not None
        assert len(result) == EMBEDDING_DIMENSIONS
        assert result[0] == 0.1
        mock_urlopen.assert_called_once()

    @patch("src.app.embedding.urlopen")
    def test_returns_none_when_ollama_returns_non_200(self, mock_urlopen):
        """When Ollama returns non-200, returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.reason = "Internal Server Error"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = get_embedding("hello")

        assert result is None

    @patch("src.app.embedding.urlopen")
    def test_returns_none_when_response_has_no_embeddings(self, mock_urlopen):
        """When response has no embeddings key or empty list, returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({}).encode("utf-8")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = get_embedding("hello")

        assert result is None

    @patch("src.app.embedding.urlopen")
    def test_returns_none_when_embeddings_not_list_of_numbers(self, mock_urlopen):
        """When embeddings[0] is not a list of numbers, returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"embeddings": ["not a vector"]}).encode("utf-8")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = get_embedding("hello")

        assert result is None

    @patch("src.app.embedding.urlopen")
    def test_returns_none_on_network_error(self, mock_urlopen):
        """When urlopen raises URLError, returns None."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")

        result = get_embedding("hello")

        assert result is None

    @patch("src.app.embedding.urlopen")
    def test_returns_none_on_invalid_json(self, mock_urlopen):
        """When response body is not valid JSON, returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"not json"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = get_embedding("hello")

        assert result is None

    @patch("src.app.embedding.urlopen")
    def test_request_includes_model_and_dimensions(self, mock_urlopen):
        """Request payload includes model, input, dimensions, truncate."""
        vector = [0.0] * EMBEDDING_DIMENSIONS
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"embeddings": [vector]}).encode("utf-8")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        get_embedding("test input")

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.data is not None
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == EMBEDDING_MODEL
        assert payload["input"] == "test input"
        assert payload["dimensions"] == EMBEDDING_DIMENSIONS
        assert payload.get("truncate") is True


# ---------------------------------------------------------------------------
# embedding.embed_record_data
# ---------------------------------------------------------------------------


class TestEmbedRecordData:
    """Unit tests for embed_record_data."""

    @patch("src.app.embedding.get_embedding")
    def test_serializes_dict_to_json_and_calls_get_embedding(self, mock_get_embedding):
        """embed_record_data JSON-serializes the dict and passes to get_embedding."""
        mock_get_embedding.return_value = [0.1, 0.2]

        result = embed_record_data({"name": "Alice", "count": 3})

        assert result == [0.1, 0.2]
        mock_get_embedding.assert_called_once()
        call_text = mock_get_embedding.call_args[0][0]
        assert "name" in call_text
        assert "Alice" in call_text
        assert "count" in call_text
        assert "3" in call_text

    @patch("src.app.embedding.get_embedding")
    def test_uses_empty_json_object_for_non_dict(self, mock_get_embedding):
        """When data is not a dict, uses '{}' as input."""
        mock_get_embedding.return_value = []

        embed_record_data(None)

        mock_get_embedding.assert_called_once_with("{}")


# ---------------------------------------------------------------------------
# data_routes._schedule_embedding_update
# ---------------------------------------------------------------------------


class TestScheduleEmbeddingUpdate:
    """Unit tests for _schedule_embedding_update (best-effort vectorization)."""

    @patch("src.app.data_routes.db")
    @patch("src.app.data_routes.embed_record_data")
    def test_calls_update_when_embedding_returned(self, mock_embed, mock_db):
        """When embed_record_data returns a vector, update_data_snapshot_embedding is called."""
        mock_embed.return_value = [0.1] * 2000

        _schedule_embedding_update("rec-123", {"x": 1})

        mock_embed.assert_called_once_with({"x": 1})
        mock_db.update_data_snapshot_embedding.assert_called_once()
        call_args = mock_db.update_data_snapshot_embedding.call_args[0]
        assert call_args[0] == "rec-123"
        assert call_args[1] == [0.1] * 2000
        assert call_args[2] == EMBEDDING_MODEL

    @patch("src.app.data_routes.db")
    @patch("src.app.data_routes.embed_record_data")
    def test_does_not_call_update_when_embedding_is_none(self, mock_embed, mock_db):
        """When embed_record_data returns None, update_data_snapshot_embedding is not called."""
        mock_embed.return_value = None

        _schedule_embedding_update("rec-456", {"y": 2})

        mock_embed.assert_called_once()
        mock_db.update_data_snapshot_embedding.assert_not_called()

    @patch("src.app.data_routes.db")
    @patch("src.app.data_routes.embed_record_data")
    def test_swallows_exception_and_does_not_raise(self, mock_embed, mock_db):
        """When embed_record_data or update raises, exception is caught and not re-raised."""
        mock_embed.side_effect = RuntimeError("Ollama down")

        _schedule_embedding_update("rec-789", {})

        # No exception propagates
        mock_db.update_data_snapshot_embedding.assert_not_called()

    @patch("src.app.data_routes.db")
    @patch("src.app.data_routes.embed_record_data")
    def test_swallows_exception_from_update_data_snapshot_embedding(self, mock_embed, mock_db):
        """When update_data_snapshot_embedding raises, exception is caught and not re-raised."""
        mock_embed.return_value = [0.0] * 2000
        mock_db.update_data_snapshot_embedding.side_effect = ValueError("dimension mismatch")

        _schedule_embedding_update("rec-999", {"z": 3})

        # No exception propagates
        mock_db.update_data_snapshot_embedding.assert_called_once()


# ---------------------------------------------------------------------------
# database.update_data_snapshot_embedding
# ---------------------------------------------------------------------------


class TestUpdateDataSnapshotEmbedding:
    """Unit tests for Database.update_data_snapshot_embedding."""

    def test_no_op_when_embedding_is_none(self):
        """When embedding is None, returns without calling connect or execute."""
        db = Database()
        with patch.object(db, "connect") as mock_connect:
            db.update_data_snapshot_embedding("rec-1", None, "model-1")
            mock_connect.assert_not_called()

    def test_no_op_when_embedding_is_empty_list(self):
        """When embedding is [], returns without calling connect or execute."""
        db = Database()
        with patch.object(db, "connect") as mock_connect:
            db.update_data_snapshot_embedding("rec-1", [], "model-1")
            mock_connect.assert_not_called()

    @patch("pgvector.psycopg2.register_vector")
    def test_executes_update_when_pgvector_available(self, mock_register_vector):
        """When pgvector registers and cursor executes, UPDATE runs and commit is called."""
        db = Database()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(db, "connect", return_value=mock_conn):
            vector = [0.1] * 2000
            db.update_data_snapshot_embedding("rec-abc", vector, "qwen3-embedding:4b")

        mock_register_vector.assert_called_once_with(mock_conn)
        mock_cursor.execute.assert_called_once()
        execute_sql = mock_cursor.execute.call_args[0][0]
        assert "UPDATE odb.data_snapshot" in execute_sql
        assert "embedding" in execute_sql
        assert "embedding_model" in execute_sql
        assert "embedding_updated_at" in execute_sql
        execute_args = mock_cursor.execute.call_args[0][1]
        assert execute_args[1] == "qwen3-embedding:4b"
        assert execute_args[2] == "rec-abc"
        mock_conn.commit.assert_called_once()

    @patch("pgvector.psycopg2.register_vector")
    def test_returns_without_raising_when_register_vector_fails(self, mock_register_vector):
        """When register_vector raises (pgvector not available), returns without raising."""
        mock_register_vector.side_effect = ImportError("pgvector not installed")

        db = Database()
        with patch.object(db, "connect", return_value=MagicMock()):
            db.update_data_snapshot_embedding("rec-1", [0.0] * 2000, "model")

        # No exception; connect was called, register_vector failed
        mock_register_vector.assert_called_once()

    @patch("pgvector.psycopg2.register_vector")
    def test_returns_without_raising_when_execute_raises_vector_type_error(self, mock_register_vector):
        """When cursor.execute raises (e.g. vector type missing), returns without re-raising."""
        db = Database()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        err = Exception("type \"vector\" does not exist")
        err.pgcode = "42704"  # undefined_object in PostgreSQL
        mock_cursor.execute.side_effect = err

        with patch.object(db, "connect", return_value=mock_conn):
            db.update_data_snapshot_embedding("rec-1", [0.0] * 2000, "model")

        mock_conn.rollback.assert_called_once()

    @patch("pgvector.psycopg2.register_vector")
    def test_re_raises_when_execute_raises_unrelated_error(self, mock_register_vector):
        """When cursor.execute raises an error not related to vector type, re-raises."""
        db = Database()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = Exception("unique violation")

        with patch.object(db, "connect", return_value=mock_conn):
            with pytest.raises(Exception) as exc_info:
                db.update_data_snapshot_embedding("rec-1", [0.0] * 2000, "model")
            assert "unique violation" in str(exc_info.value)

    @patch("pgvector.psycopg2.register_vector")
    def test_accepts_list_and_passes_to_execute(self, mock_register_vector):
        """Embedding can be a list; it is converted and passed to execute."""
        db = Database()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(db, "connect", return_value=mock_conn):
            db.update_data_snapshot_embedding("rec-1", [0.5, 0.5, 0.5], "m")

        # First arg to execute should be the embedding (possibly as ndarray)
        call_args = mock_cursor.execute.call_args[0][1]
        assert call_args[0] is not None
        assert len(call_args[0]) == 3 or (hasattr(call_args[0], "__len__") and len(call_args[0]) == 3)
