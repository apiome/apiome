"""Standing contract sources of a provider — PFX-8.7 (#7304).

``GET`` / ``PUT /v1/tenants/{t}/pacticipants/{p}/contract-sources`` and
:mod:`app.pacticipant_contract_sources`. The database is a fake that records the statements; the
real SQL runs in ``test_provider_contract_auto_publish_db``. Asserted here:

* the routes are gated on ``pacts:view`` / ``pacts:edit`` (``imports:view`` too with a repository),
  denied before anything is read, and the write is audited;
* every setting that could never fire is refused with a reason — no project to follow, a
  repository of another workspace, a repository that is not GitHub, a path that is not a
  repository-relative ``.yaml`` / ``.yml`` / ``.json`` file — and an unknown field is a 422;
* both off removes the row; warnings name a source that will not fire right now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pacticipant import PacticipantRecord, PacticipantValidationError
from app.pacticipant_contract_sources import (
    CODE_INVALID_PATH,
    CODE_NO_PROJECT,
    CODE_REPOSITORY_NOT_FOUND,
    CODE_REPOSITORY_UNSUPPORTED,
    ContractSourcesInput,
    get_contract_sources,
    put_contract_sources,
    validate_contract_path,
)
from app.permissions import Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "22222222-2222-4222-8222-222222222222"
_REPO = "33333333-3333-4333-8333-333333333333"
_PROJECT = "44444444-4444-4444-8444-444444444444"
_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"}
_URL = "/v1/tenants/acme/pacticipants/billing-service/contract-sources"
_ROUTES = "app.pacticipant_contract_source_routes"


def _pacticipant(project_id: Optional[str] = _PROJECT) -> PacticipantRecord:
    return PacticipantRecord(
        id="55555555-5555-4555-8555-555555555555",
        tenant_id=_TENANT,
        slug="billing-service",
        name="Billing Service",
        project_id=project_id,
        main_branch="main",
        created_at="2026-11-27T00:00:00Z",
        updated_at="2026-11-27T00:00:00Z",
    )


class FakeDb:
    """Answers the statements the module runs, and records them.

    Attributes:
        row: The stored ``provider_contract_source`` row (with the repository's columns), or ``None``.
        repositories: Registered repositories by id, all of ``_TENANT``.
        webhooks: Repository ids with a push webhook.
        statements: ``(sql, params)`` of every statement run.
    """

    def __init__(self) -> None:
        self.row: Optional[Dict[str, Any]] = None
        self.repositories: Dict[str, Dict[str, Any]] = {
            _REPO: {"id": _REPO, "provider": "github", "repository_full_name": "acme/billing"},
        }
        self.webhooks = {_REPO}
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute_query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        self.statements.append((sql, params))
        if sql.lstrip().startswith("DELETE"):
            self.row = None
            return []
        if "INSERT INTO apiome.provider_contract_source" in sql:
            _, _, on_publish, repository_id, path, branch, _ = params
            repository = self.repositories.get(repository_id or "") or {}
            self.row = {
                "on_project_publish": on_publish,
                "repository_id": repository_id,
                "repository_path": path,
                "repository_branch": branch,
                "updated_at": datetime(2026, 11, 27, tzinfo=timezone.utc),
                "repository_full_name": repository.get("repository_full_name"),
                "repository_provider": repository.get("provider"),
            }
            return [{"pacticipant_id": params[0]}]
        if "FROM apiome.provider_contract_source" in sql:
            return [dict(self.row)] if self.row else []
        raise AssertionError(f"unexpected statement: {sql}")

    def get_project_core(self, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        if project_id == _PROJECT and tenant_id == _TENANT:
            return {"id": _PROJECT, "slug": "billing-api", "name": "Billing API"}
        return None

    def get_tenant_repository(self, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
        return self.repositories.get(repository_id) if tenant_id == _TENANT else None

    def get_repository_webhook_subscription(self, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
        return {"repository_id": repository_id} if repository_id in self.webhooks else None


def _repository(**overrides: Any) -> Dict[str, Any]:
    return {"repositoryId": _REPO, "path": "openapi/billing.yaml", "branch": "main", **overrides}


# ---------------------------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("openapi.yaml", "openapi.yaml"),
        ("./specs/billing.JSON", "specs/billing.JSON"),
        ("specs\\billing.yml", "specs/billing.yml"),
    ],
)
def test_a_repository_relative_contract_path_is_kept(path: str, expected: str) -> None:
    assert validate_contract_path(path) == expected


@pytest.mark.parametrize(
    "path, says",
    [
        ("", "empty"),
        ("/etc/openapi.yaml", "absolute"),
        ("specs/../../secrets.yaml", "plain repository path"),
        ("specs//openapi.yaml", "plain repository path"),
        ("README.md", ".yaml, .yml or .json"),
        ("a/" * 600 + "x.yaml", "over 1024"),
    ],
)
def test_a_path_that_is_not_a_contract_file_is_refused_with_why(path: str, says: str) -> None:
    with pytest.raises(PacticipantValidationError) as caught:
        validate_contract_path(path)
    assert caught.value.code == CODE_INVALID_PATH
    assert says in str(caught.value)


def test_a_provider_that_never_set_a_source_has_both_off() -> None:
    record = get_contract_sources(FakeDb(), _TENANT, _pacticipant())
    assert record.on_project_publish is False
    assert record.repository is None
    assert record.project is not None and record.project.slug == "billing-api"
    assert record.warnings == []


def test_both_sources_are_stored_and_read_back() -> None:
    db = FakeDb()
    body = ContractSourcesInput.model_validate({"onProjectPublish": True, "repository": _repository()})
    record = put_contract_sources(db, _TENANT, _pacticipant(), body, user_id=_USER)
    assert record.on_project_publish is True
    assert record.repository is not None
    assert (record.repository.full_name, record.repository.path, record.repository.branch) == (
        "acme/billing",
        "openapi/billing.yaml",
        "main",
    )
    assert record.repository.webhook is True
    assert record.warnings == []
    insert = next(params for sql, params in db.statements if "INSERT" in sql)
    assert insert[:3] == ("55555555-5555-4555-8555-555555555555", _TENANT, True)
    assert insert[-1] == _USER


def test_both_off_removes_the_setting() -> None:
    db = FakeDb()
    put_contract_sources(db, _TENANT, _pacticipant(), ContractSourcesInput(on_project_publish=True), user_id=_USER)
    record = put_contract_sources(db, _TENANT, _pacticipant(), ContractSourcesInput(), user_id=_USER)
    assert db.row is None
    assert any(sql.lstrip().startswith("DELETE") for sql, _ in db.statements)
    assert record.on_project_publish is False and record.repository is None


def test_on_project_publish_without_a_bound_project_is_refused() -> None:
    db = FakeDb()
    with pytest.raises(PacticipantValidationError) as caught:
        put_contract_sources(
            db, _TENANT, _pacticipant(project_id=None), ContractSourcesInput(on_project_publish=True), user_id=_USER
        )
    assert caught.value.code == CODE_NO_PROJECT
    assert "not bound to an Apiome project" in str(caught.value)
    assert db.statements == []


def test_a_repository_of_another_workspace_is_not_found() -> None:
    db = FakeDb()
    body = ContractSourcesInput.model_validate({"repository": _repository()})
    with pytest.raises(PacticipantValidationError) as caught:
        put_contract_sources(db, "99999999-9999-4999-8999-999999999999", _pacticipant(), body, user_id=_USER)
    assert caught.value.code == CODE_REPOSITORY_NOT_FOUND
    assert db.row is None


def test_a_repository_id_that_is_not_a_uuid_is_not_found() -> None:
    body = ContractSourcesInput.model_validate({"repository": _repository(repositoryId="acme/billing")})
    with pytest.raises(PacticipantValidationError) as caught:
        put_contract_sources(FakeDb(), _TENANT, _pacticipant(), body, user_id=_USER)
    assert caught.value.code == CODE_REPOSITORY_NOT_FOUND


def test_a_repository_whose_files_cannot_be_read_is_refused_with_why() -> None:
    db = FakeDb()
    db.repositories[_REPO]["provider"] = "gitlab"
    body = ContractSourcesInput.model_validate({"repository": _repository()})
    with pytest.raises(PacticipantValidationError) as caught:
        put_contract_sources(db, _TENANT, _pacticipant(), body, user_id=_USER)
    assert caught.value.code == CODE_REPOSITORY_UNSUPPORTED
    assert "only GitHub repositories are supported" in str(caught.value)
    assert db.row is None


def test_a_repository_without_a_webhook_is_kept_with_a_warning() -> None:
    db = FakeDb()
    db.webhooks.clear()
    body = ContractSourcesInput.model_validate({"repository": _repository()})
    record = put_contract_sources(db, _TENANT, _pacticipant(), body, user_id=_USER)
    assert record.repository is not None and record.repository.webhook is False
    assert record.warnings == [
        "acme/billing has no push webhook, so no push reaches Apiome; set one up on the repository's page."
    ]


def test_a_deleted_repository_and_an_unbound_project_are_warned_about() -> None:
    db = FakeDb()
    db.row = {
        "on_project_publish": True,
        "repository_id": None,
        "repository_path": "openapi.yaml",
        "repository_branch": "main",
        "updated_at": None,
        "repository_full_name": None,
        "repository_provider": None,
    }
    record = get_contract_sources(db, _TENANT, _pacticipant(project_id=None))
    assert len(record.warnings) == 2
    assert "not bound to a project" in record.warnings[0]
    assert "was deleted" in record.warnings[1]


# ---------------------------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def authenticated() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def fake() -> Iterator[Dict[str, Any]]:
    db = FakeDb()
    audit = MagicMock()
    db.write_access_audit = audit  # type: ignore[attr-defined]
    with (
        patch(f"{_ROUTES}.db", db),
        patch(f"{_ROUTES}.enforce_permission", return_value=_USER) as guard,
        patch(f"{_ROUTES}.get_pacticipant", return_value=_pacticipant()),
    ):
        yield {"db": db, "guard": guard, "audit": audit}


def test_read_needs_pacts_view(fake: Dict[str, Any]) -> None:
    response = client.get(_URL)
    assert response.status_code == 200, response.text
    assert response.json()["onProjectPublish"] is False
    [call] = fake["guard"].call_args_list
    assert (call.args[2], call.args[3]) == (Resource.PACTS, "view")


def test_put_stores_audits_and_answers_in_camel_case(fake: Dict[str, Any]) -> None:
    response = client.put(_URL, json={"onProjectPublish": True, "repository": _repository()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["onProjectPublish"] is True
    assert body["repository"]["repositoryId"] == _REPO
    assert body["repository"]["fullName"] == "acme/billing"
    assert body["project"]["slug"] == "billing-api"
    resources = [(call.args[2], call.args[3]) for call in fake["guard"].call_args_list]
    assert resources == [(Resource.PACTS, "edit"), (Resource.IMPORTS, "view")]
    fake["audit"].assert_called_once()
    assert fake["audit"].call_args.kwargs["action"] == "pacts.contract_source.update"


def test_put_without_a_repository_does_not_ask_for_imports(fake: Dict[str, Any]) -> None:
    assert client.put(_URL, json={"onProjectPublish": True}).status_code == 200
    assert [call.args[2] for call in fake["guard"].call_args_list] == [Resource.PACTS]


def test_a_refused_permission_reads_nothing(fake: Dict[str, Any]) -> None:
    fake["guard"].side_effect = HTTPException(status_code=403, detail="pacts:edit required")
    response = client.put(_URL, json={"onProjectPublish": True})
    assert response.status_code == 403
    assert fake["db"].statements == []
    fake["audit"].assert_not_called()


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"repository": _repository(path="../x.yaml")}, 400, CODE_INVALID_PATH),
        (
            {"repository": _repository(repositoryId="66666666-6666-4666-8666-666666666666")},
            404,
            CODE_REPOSITORY_NOT_FOUND,
        ),
        ({"repository": _repository(branch="  ")}, 400, "pacticipant-invalid-branch"),
    ],
)
def test_each_refusal_has_its_status_and_code(
    fake: Dict[str, Any], body: Dict[str, Any], status: int, code: str
) -> None:
    response = client.put(_URL, json=body)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert fake["db"].row is None


def test_a_provider_without_a_project_is_a_409(fake: Dict[str, Any]) -> None:
    with patch(f"{_ROUTES}.get_pacticipant", return_value=_pacticipant(project_id=None)):
        response = client.put(_URL, json={"onProjectPublish": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_NO_PROJECT


def test_a_gitlab_repository_is_a_422(fake: Dict[str, Any]) -> None:
    fake["db"].repositories[_REPO]["provider"] = "gitlab"
    response = client.put(_URL, json={"repository": _repository()})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_REPOSITORY_UNSUPPORTED


def test_an_unknown_field_is_named_not_dropped(fake: Dict[str, Any]) -> None:
    response = client.put(_URL, json={"onProjectPublish": True, "onEveryTag": True})
    assert response.status_code == 422
    assert "onEveryTag" in response.text
    assert fake["db"].statements == []


def test_an_unknown_pacticipant_is_a_404(fake: Dict[str, Any]) -> None:
    with patch(
        f"{_ROUTES}.get_pacticipant",
        side_effect=PacticipantValidationError("pacticipant-not-found", "no pacticipant 'x' in this tenant"),
    ):
        response = client.get(_URL)
    assert response.status_code == 404
