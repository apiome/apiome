"""Unit tests for ``Database.get_version_quality_score`` (MFI-4.4 surfacing).

The SQL runs against Postgres in the integration suite; these guard the Python-side contract:
the tenant-scoped parameter wiring, the non-UUID short-circuit, and the empty-result path. The
connection/cursor is mocked via ``execute_query``.
"""

from unittest.mock import patch

from app.database import Database

_TID = "tenant-1"
_VID = "11111111-1111-4111-8111-111111111111"


def test_get_version_quality_score_returns_row():
    db = Database()
    row = {
        "quality_score": 87,
        "quality_grade": "B",
        "quality_report_fingerprint": "fp-abc",
        "quality_report": {"score": 87, "findings": []},
    }
    with patch.object(db, "execute_query", return_value=[row]) as mq:
        out = db.get_version_quality_score(_VID, _TID)
    assert out == row
    # Scoped to the revision and tenant, in that order.
    assert mq.call_args.args[1] == (_VID, _TID)


def test_get_version_quality_score_missing_returns_none():
    db = Database()
    with patch.object(db, "execute_query", return_value=[]):
        assert db.get_version_quality_score(_VID, _TID) is None


def test_get_version_quality_score_rejects_non_uuid_without_querying():
    db = Database()
    with patch.object(db, "execute_query") as mq:
        assert db.get_version_quality_score("1.0.0", _TID) is None
    mq.assert_not_called()
