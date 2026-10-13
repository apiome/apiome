"""Tests for cross-format API identity (MFI-6.4, #4410)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


def test_identity_routes_require_auth():
    response = client.get("/v1/identity/test-tenant/projects/p1/related")
    assert response.status_code == 401


def test_get_related_artifacts():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.identity_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_related_artifact_rows.return_value = [
                {
                    "project_id": "p2",
                    "name": "Acme OpenAPI",
                    "slug": "acme-openapi",
                    "publishable": True,
                    "source_format": "openapi",
                    "protocol": "rest",
                    "link_source": "conversion",
                    "deleted": False,
                }
            ]
            response = client.get("/v1/identity/test-tenant/projects/p1/related")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["projectId"] == "p2"
        assert data[0]["linkSource"] == "conversion"
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_link_artifacts():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.identity_routes.db") as mock_db:
            mock_db.link_identity_projects.return_value = "group-1"
            mock_db.get_related_artifact_rows.return_value = []
            response = client.post(
                "/v1/identity/test-tenant/link",
                json={"projectId": "p1", "relatedProjectId": "p2"},
            )
        assert response.status_code == 200
        assert response.json()["identityGroupId"] == "group-1"
        mock_db.link_identity_projects.assert_called_once()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_unlink_artifacts():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.identity_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_identity_group_id_for_project.return_value = None
            mock_db.get_related_artifact_rows.return_value = []
            response = client.request(
                "DELETE",
                "/v1/identity/test-tenant/link",
                json={"projectId": "p1", "relatedProjectId": "p2"},
            )
        assert response.status_code == 200
        mock_db.unlink_identity_projects.assert_called_once()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_identity_suggestions_never_auto_link():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.identity_routes.db") as mock_db:
            mock_db.get_project_identity_profile.return_value = {
                "project_id": "p1",
                "name": "Acme API",
                "format_metadata": {"package": "acme.v1"},
            }
            mock_db.get_identity_suggestion_candidates.return_value = [
                {
                    "project_id": "p2",
                    "name": "Acme API",
                    "slug": "acme-api",
                    "publishable": False,
                    "source_format": "protobuf",
                    "protocol": "grpc",
                    "format_metadata": {"package": "acme.v1"},
                    "identity_name": None,
                    "identity_namespace": None,
                }
            ]
            mock_db.get_operation_keys_for_project.side_effect = [
                {"GetUser", "ListUsers"},
                {"GetUser", "ListUsers"},
            ]
            response = client.get("/v1/identity/test-tenant/projects/p1/suggestions")
        assert response.status_code == 200
        suggestions = response.json()
        assert len(suggestions) >= 1
        assert suggestions[0]["projectId"] == "p2"
        mock_db.link_identity_projects.assert_not_called()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Identity-group writes never fetch (CPDO-4.1, #4804)
# ---------------------------------------------------------------------------
#
# The identity-group writers (INSERT … ON CONFLICT DO NOTHING, UPDATE, DELETE — none
# with a RETURNING clause) used to run through ``execute_query``, whose unconditional
# ``fetchall()`` makes psycopg2 raise "no results to fetch" on any plain write. The
# route suites above mock the data layer, so the first real conversion commit was what
# hit it (the CPDO-4.1 journey e2e). These pin the fix at the SQL boundary with a
# driver-faithful fake: a cursor that, like psycopg2, refuses ``fetchall()`` after a
# statement that produced no result set.


class _WriteOnlyCursor:
    """A psycopg2-shaped cursor for statements that return no rows."""

    rowcount = 1

    def __init__(self, executed):
        self._executed = executed

    def execute(self, query, params=None):
        self._executed.append((" ".join(query.split()), params))

    def fetchall(self):
        raise Exception("no results to fetch")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _WriteOnlyConnection:
    def __init__(self):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _WriteOnlyCursor(self.executed)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _db_with_fake_connection():
    import app.database as database

    fake = _WriteOnlyConnection()
    instance = database.Database.__new__(database.Database)
    instance.connect = lambda: fake  # type: ignore[method-assign]
    return instance, fake


def test_add_identity_member_is_a_pure_write():
    instance, fake = _db_with_fake_connection()

    instance._add_identity_member(
        tenant_id="t1",
        group_id="g1",
        project_id="p1",
        created_by="u1",
        link_source="conversion",
    )

    assert len(fake.executed) == 1
    assert fake.executed[0][0].startswith("INSERT INTO apiome.api_identity_members")
    assert fake.commits == 1
    assert fake.rollbacks == 0


def test_merge_identity_groups_is_a_pure_write():
    instance, fake = _db_with_fake_connection()

    instance._merge_identity_groups("t1", "keep", "drop")

    statements = [query for query, _ in fake.executed]
    assert statements[0].startswith("UPDATE apiome.api_identity_members")
    assert statements[1].startswith("DELETE FROM apiome.api_identity_groups")
    assert fake.commits == 2
    assert fake.rollbacks == 0


# ---------------------------------------------------------------------------
# Body ids are scoped to the token's tenant (OLO-7.3 follow-up, #4963)
# ---------------------------------------------------------------------------
#
# apiome-ui's ``/api/identity/link`` proxy mints a session-bound token and forwards the
# request **body** — ``projectId`` / ``relatedProjectId`` — exactly as the browser sent it.
# Whether those ids belong to the caller's tenant is therefore decided here and nowhere
# else. These pin that decision at three levels: the project lookup filters by tenant in
# SQL, the link writer refuses before it writes anything, and both routes answer 404 for
# a project of another tenant using the *token's* tenant, never the path's.

_OWN_TENANT = "tenant-own"
_FOREIGN_TENANT = "tenant-foreign"


class _ReadCursor:
    """A cursor that records each statement and returns no rows."""

    def __init__(self, executed):
        self._executed = executed

    def execute(self, query, params=None):
        self._executed.append((" ".join(query.split()), params))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _tenant_scoped_db(projects_by_tenant):
    """A real ``Database`` whose project lookup answers from ``{tenant_id: {project ids}}``.

    Every identity writer is replaced with a recorder, so a test can assert that a refused
    link wrote nothing.

    Returns:
        ``(database, writes)`` — ``writes`` collects ``(writer name, kwargs or args)`` tuples.
    """
    import app.database as database

    instance = database.Database.__new__(database.Database)
    writes = []

    def get_project_by_id(project_id, tenant_id, **_kwargs):
        owned = project_id in projects_by_tenant.get(tenant_id, set())
        return {"id": project_id, "tenant_id": tenant_id} if owned else None

    instance.get_project_by_id = get_project_by_id  # type: ignore[method-assign]
    instance.get_identity_group_id_for_project = lambda *_a, **_k: None  # type: ignore[method-assign]
    instance._create_identity_group = (  # type: ignore[method-assign]
        lambda *args, **kwargs: writes.append(("create_group", args or kwargs)) or "group-new"
    )
    instance._add_identity_member = (  # type: ignore[method-assign]
        lambda *args, **kwargs: writes.append(("add_member", args or kwargs))
    )
    instance._merge_identity_groups = (  # type: ignore[method-assign]
        lambda *args, **kwargs: writes.append(("merge", args or kwargs))
    )
    return instance, writes


def test_project_lookup_filters_by_tenant_in_sql():
    import app.database as database

    executed = []

    class _Connection:
        def cursor(self):
            return _ReadCursor(executed)

        def commit(self):
            pass

        def rollback(self):
            pass

    instance = database.Database.__new__(database.Database)
    instance.connect = lambda: _Connection()  # type: ignore[method-assign]

    assert instance.get_project_by_id("project-1", _OWN_TENANT) is None
    query, params = executed[0]
    assert "WHERE p.id = %s AND p.tenant_id = %s" in query
    assert params == ("project-1", _OWN_TENANT)


def test_link_refuses_a_project_of_another_tenant_before_writing():
    import pytest

    instance, writes = _tenant_scoped_db(
        {_OWN_TENANT: {"own-a", "own-b"}, _FOREIGN_TENANT: {"foreign-x"}}
    )
    for project_a, project_b in (("own-a", "foreign-x"), ("foreign-x", "own-a")):
        with pytest.raises(ValueError, match="Project not found: foreign-x"):
            instance.link_identity_projects(
                tenant_id=_OWN_TENANT,
                project_id_a=project_a,
                project_id_b=project_b,
                created_by="user-1",
            )
    assert writes == []


def test_link_writes_only_under_the_callers_tenant():
    instance, writes = _tenant_scoped_db({_OWN_TENANT: {"own-a", "own-b"}})

    group_id = instance.link_identity_projects(
        tenant_id=_OWN_TENANT, project_id_a="own-a", project_id_b="own-b", created_by="user-1"
    )

    assert group_id == "group-new"
    members = [payload for name, payload in writes if name == "add_member"]
    assert {member["project_id"] for member in members} == {"own-a", "own-b"}
    assert {member["tenant_id"] for member in members} == {_OWN_TENANT}


def _client_as(tenant_id):
    """Override authentication so every request is made as a member of ``tenant_id``."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": tenant_id,
        "user_id": "test-user-id",
        "auth_method": "jwt",
    }


def test_link_route_answers_404_for_a_project_of_another_tenant():
    instance, writes = _tenant_scoped_db(
        {_OWN_TENANT: {"own-a"}, _FOREIGN_TENANT: {"foreign-x"}}
    )
    _client_as(_OWN_TENANT)
    try:
        with patch("app.identity_routes.db", instance):
            for body in (
                {"projectId": "own-a", "relatedProjectId": "foreign-x"},
                {"projectId": "foreign-x", "relatedProjectId": "own-a"},
            ):
                response = client.post("/v1/identity/own/link", json=body)
                assert response.status_code == 404
                assert response.json()["detail"] == "Project not found: foreign-x"
        assert writes == []
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_unlink_route_answers_404_for_a_project_of_another_tenant():
    instance, _writes = _tenant_scoped_db(
        {_OWN_TENANT: {"own-a"}, _FOREIGN_TENANT: {"foreign-x"}}
    )
    unlinked = []
    instance.unlink_identity_projects = lambda **kwargs: unlinked.append(kwargs)  # type: ignore[method-assign]
    _client_as(_OWN_TENANT)
    try:
        with patch("app.identity_routes.db", instance):
            for body in (
                {"projectId": "own-a", "relatedProjectId": "foreign-x"},
                {"projectId": "foreign-x", "relatedProjectId": "own-a"},
            ):
                response = client.request("DELETE", "/v1/identity/own/link", json=body)
                assert response.status_code == 404
                assert response.json()["detail"] == "Project not found: foreign-x"
        assert unlinked == []
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_link_routes_scope_by_the_tokens_tenant_not_the_path_slug():
    """Naming another tenant's slug in the URL does not move the lookup to that tenant."""
    instance, writes = _tenant_scoped_db(
        {_OWN_TENANT: {"own-a", "own-b"}, _FOREIGN_TENANT: {"foreign-x", "foreign-y"}}
    )
    instance.get_related_artifact_rows = lambda *_a, **_k: []  # type: ignore[method-assign]
    _client_as(_OWN_TENANT)
    try:
        with patch("app.identity_routes.db", instance):
            foreign = client.post(
                "/v1/identity/foreign/link",
                json={"projectId": "foreign-x", "relatedProjectId": "foreign-y"},
            )
            own = client.post(
                "/v1/identity/foreign/link",
                json={"projectId": "own-a", "relatedProjectId": "own-b"},
            )
        assert foreign.status_code == 404
        assert own.status_code == 200
        assert {
            payload["tenant_id"] for name, payload in writes if name == "add_member"
        } == {_OWN_TENANT}
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
