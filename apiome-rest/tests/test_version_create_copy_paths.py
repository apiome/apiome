"""POST create version with ``copyPaths`` — #771 (route level, DB mocked).

The copy itself is covered against Postgres in ``test_version_path_copy.py``; here: the flag is
validated, forwarded to the push transaction, and its counts reach the response and the audit.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from tests.test_push_base_revision import _MOCK_AUTH, _version_row

client = TestClient(app)

HEAD = "00000000-0000-0000-0000-000000000010"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _post(mdb, body):
    mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
    mdb.get_latest_version_for_project.return_value = None
    mdb.list_version_branches_for_project.return_value = []
    mdb.get_latest_revision_id_for_project.return_value = HEAD
    mdb.get_version_by_id.return_value = _version_row(HEAD)
    return client.post(
        "/v1/versions/tn/proj-1",
        json={"version_id": "1.1.0", "shortMessage": "next", "baseRevisionId": HEAD, **body},
    )


def test_copy_paths_is_forwarded_and_counted():
    row = {**_version_row("rev-new"), "copied_paths": 3, "copied_operations": 7}
    with patch("app.versions_routes.db") as mdb:
        mdb.create_version_push_transaction.return_value = (row, 4)
        r = _post(mdb, {"source_version_id": HEAD, "copyPaths": True})
        assert r.status_code == 200, r.text
        kw = mdb.create_version_push_transaction.call_args.kwargs
        assert kw["copy_paths"] is True
        assert kw["source_version_id"] == HEAD
        detail = mdb.insert_workflow_audit.call_args_list[0].args[6]
    body = r.json()
    assert body["copied_classes"] == 4
    assert body["copied_paths"] == 3
    assert body["copied_operations"] == 7
    assert detail["copiedPaths"] == 3


def test_copy_paths_defaults_off():
    with patch("app.versions_routes.db") as mdb:
        mdb.create_version_push_transaction.return_value = (_version_row("rev-new"), 2)
        r = _post(mdb, {"source_version_id": HEAD})
        assert r.status_code == 200, r.text
        assert mdb.create_version_push_transaction.call_args.kwargs["copy_paths"] is False
    body = r.json()
    assert body["copied_classes"] == 2
    assert body["copied_paths"] is None


def test_copy_paths_accepts_the_snake_case_name():
    with patch("app.versions_routes.db") as mdb:
        mdb.create_version_push_transaction.return_value = (_version_row("rev-new"), 0)
        r = _post(mdb, {"source_version_id": HEAD, "copy_paths": True})
        assert r.status_code == 200, r.text
        assert mdb.create_version_push_transaction.call_args.kwargs["copy_paths"] is True


@pytest.mark.parametrize("source", [None, "", "   "])
def test_copy_paths_without_a_source_is_422(source):
    with patch("app.versions_routes.db") as mdb:
        body = {"copyPaths": True}
        if source is not None:
            body["source_version_id"] = source
        r = _post(mdb, body)
        assert r.status_code == 422
        assert "copyPaths requires source_version_id" in r.json()["detail"]
        mdb.create_version_push_transaction.assert_not_called()


def test_missing_source_warns_and_copies_nothing():
    with patch("app.versions_routes.db") as mdb:
        mdb.create_version_push_transaction.return_value = (_version_row("rev-new"), 0)
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = HEAD
        mdb.get_version_by_id.side_effect = lambda vid, _t: _version_row(HEAD) if vid == HEAD else None
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.1.0",
                "shortMessage": "next",
                "baseRevisionId": HEAD,
                "source_version_id": "00000000-0000-0000-0000-00000000dead",
                "copyPaths": True,
            },
        )
        assert r.status_code == 200, r.text
        assert mdb.create_version_push_transaction.call_args.kwargs["source_version_id"] is None
    assert r.json()["copy_warning"].startswith("Source version not found")
