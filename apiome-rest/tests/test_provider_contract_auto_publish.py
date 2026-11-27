"""Automatic provider-contract publishes from standing sources — PFX-8.7 (#7304).

:mod:`app.provider_contract_auto_publish`, with the store, the renderer and the comparison faked
(``test_provider_contract_auto_publish_db`` runs the SQL against the real schema). Asserted here:

* a published project version is published as each following provider's contract, at its label,
  on the provider's main branch; a **draft never is** (skipped, audited, nothing stored);
* a push publishes the file at the pushed commit, the commit being the provider version;
* idempotent per version: the same contract again is ``unchanged`` and compares nothing; a
  different one is ``failed`` with the conflict as the reason;
* every failure path — unrenderable version, unreadable or oversized file, a non-GitHub
  repository, a deleted repository, an invalid document, an unexpected error — is audited with
  its reason and never raises;
* the webhook dispatcher hands the pushed commit on, but not for a redelivery, and the version
  publish and webhook routes schedule the background tasks.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from app import provider_contract_auto_publish as auto
from app.bidirectional_verification import ComparisonRun
from app.provider_contract import CODE_CONTRACT_CONFLICT, ProviderContractError, prepare_contract

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "44444444-4444-4444-8444-444444444444"
_REVISION = "77777777-7777-4777-8777-777777777777"
_REPO = "33333333-3333-4333-8333-333333333333"
_USER = "22222222-2222-4222-8222-222222222222"
_SHA = "9f31c20aa1b2c3d4e5f60718293a4b5c6d7e8f90"

_OAS = {
    "openapi": "3.1.0",
    "info": {"title": "Billing", "version": "2.7.0"},
    "paths": {"/invoices": {"get": {"responses": {"200": {"description": "ok"}}}}},
}


def _contract(**fields: Any) -> Any:
    return prepare_contract(dict(_OAS), content_type="application/json", **fields)


class FakeDb:
    """Answers the provider lookups and the row reads, and records the audit rows."""

    def __init__(self, *, published: bool = True, providers: Optional[List[Dict[str, Any]]] = None) -> None:
        self.published = published
        self.providers = (
            providers
            if providers is not None
            else [
                {
                    "id": "p-1",
                    "slug": "billing-service",
                    "name": "Billing Service",
                    "main_branch": "main",
                    "repository_path": "openapi.yaml",
                },
            ]
        )
        self.repository: Optional[Dict[str, Any]] = {
            "id": _REPO,
            "provider": "github",
            "clone_url": "https://github.com/acme/billing.git",
            "repository_full_name": "acme/billing",
            "visibility": "public",
        }
        self.queries: List[Tuple[str, Tuple[Any, ...]]] = []
        self.audits: List[Dict[str, Any]] = []

    def execute_query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        self.queries.append((sql, params))
        return list(self.providers)

    def get_version_core(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        if version_id != _REVISION or tenant_id != _TENANT:
            return None
        return {"id": _REVISION, "project_id": _PROJECT, "version_id": "2.7.0", "published": self.published}

    def get_project_core(self, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return {"id": _PROJECT, "slug": "billing-api"} if project_id == _PROJECT else None

    def get_tenant_repository(self, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
        return self.repository if tenant_id == _TENANT and repository_id == _REPO else None

    def get_external_auth_provider_for_user(self, *_: Any) -> None:
        return None

    def write_access_audit(self, **row: Any) -> None:
        self.audits.append(row)


def _published(created: bool = True) -> MagicMock:
    outcome = MagicMock()
    outcome.created = created
    outcome.contract.provider_slug = "billing-service"
    outcome.contract.provider_version = "2.7.0"
    return outcome


@pytest.fixture
def store() -> Any:
    """Fake publish + comparison; ``store.publish`` / ``store.compare`` are the mocks."""
    with (
        patch.object(auto, "publish_provider_contract", return_value=_published()) as publish,
        patch.object(auto, "compare_provider_contract", return_value=ComparisonRun()) as compare,
        patch.object(auto, "render_apiome_contract", return_value=_contract()) as render,
    ):
        yield MagicMock(publish=publish, compare=compare, render=render)


# ---------------------------------------------------------------------------------------------
# On every project publish
# ---------------------------------------------------------------------------------------------


def test_a_published_version_becomes_the_contract_of_its_label(store: Any) -> None:
    db = FakeDb()
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION, actor_id=_USER)
    assert (outcome.provider, outcome.provider_version, outcome.outcome) == ("billing-service", "2.7.0", "published")
    kwargs = store.publish.call_args.kwargs
    assert (kwargs["provider_name"], kwargs["version_number"], kwargs["branch"]) == ("billing-service", "2.7.0", "main")
    assert kwargs["actor"].user_id == _USER
    [resolved] = store.render.call_args.args[2:3]
    assert (resolved.project_slug, resolved.version_id, resolved.version_label) == ("billing-api", _REVISION, "2.7.0")
    store.compare.assert_called_once()
    [audit] = db.audits
    assert audit["action"] == "pacts.contract.auto_publish"
    assert audit["target"] == "pacticipant/billing-service/version/2.7.0/contract"
    assert audit["detail"]["trigger"] == "project-publish"
    assert audit["detail"]["outcome"] == "published"
    assert audit["detail"]["comparisons"] == {"compared": 0, "alreadyCompared": 0, "errors": 0, "skipped": 0}
    assert audit["source"] == "system"
    # The providers are read in the caller's tenant, for this project only.
    assert db.queries[0][1] == (_TENANT, _PROJECT)


def test_a_draft_is_never_published(store: Any) -> None:
    db = FakeDb(published=False)
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert outcome.outcome == "skipped"
    assert "draft" in (outcome.reason or "")
    store.publish.assert_not_called()
    store.render.assert_not_called()
    assert db.audits[0]["detail"]["outcome"] == "skipped"


def test_a_version_of_another_project_is_skipped(store: Any) -> None:
    db = FakeDb()
    [outcome] = auto.publish_on_project_version(db, _TENANT, "88888888-8888-4888-8888-888888888888", _REVISION)
    assert outcome.outcome == "skipped"
    store.publish.assert_not_called()


def test_no_following_provider_reads_nothing_more(store: Any) -> None:
    db = FakeDb(providers=[])
    assert auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION) == []
    assert db.audits == []
    store.publish.assert_not_called()


def test_the_same_contract_again_is_unchanged_and_compares_nothing(store: Any) -> None:
    store.publish.return_value = _published(created=False)
    db = FakeDb()
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert outcome.outcome == "unchanged"
    assert "already has this contract" in (outcome.reason or "")
    store.compare.assert_not_called()


def test_a_different_contract_for_the_version_fails_with_the_conflict(store: Any) -> None:
    store.publish.side_effect = ProviderContractError(CODE_CONTRACT_CONFLICT, "Cannot change the provider contract")
    db = FakeDb()
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert (outcome.outcome, outcome.code) == ("failed", CODE_CONTRACT_CONFLICT)
    assert db.audits[0]["detail"]["reason"] == "Cannot change the provider contract"
    store.compare.assert_not_called()


def test_an_unrenderable_version_fails_with_why(store: Any) -> None:
    store.render.side_effect = ProviderContractError("provider-contract-source-not-found", "cannot be rendered")
    [outcome] = auto.publish_on_project_version(FakeDb(), _TENANT, _PROJECT, _REVISION)
    assert outcome.outcome == "failed"
    assert outcome.reason == "cannot be rendered"
    store.publish.assert_not_called()


def test_an_unexpected_error_is_audited_not_raised(store: Any) -> None:
    store.publish.side_effect = RuntimeError("boom")
    db = FakeDb()
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert outcome.outcome == "failed"
    assert "unexpected error" in (outcome.reason or "")
    assert db.audits[0]["detail"]["outcome"] == "failed"


def test_one_failing_provider_does_not_stop_the_next(store: Any) -> None:
    db = FakeDb(
        providers=[
            {"id": "p-1", "slug": "a-service", "name": "A", "main_branch": None},
            {"id": "p-2", "slug": "b-service", "name": "B", "main_branch": "trunk"},
        ]
    )
    store.publish.side_effect = [ProviderContractError("provider-contract-invalid", "bad"), _published()]
    outcomes = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert [o.outcome for o in outcomes] == ["failed", "published"]
    assert store.publish.call_args_list[0].kwargs["branch"] is None
    assert store.publish.call_args_list[1].kwargs["branch"] == "trunk"
    assert len(db.audits) == 2


def test_an_audit_failure_never_fails_the_publish(store: Any) -> None:
    db = FakeDb()
    db.write_access_audit = MagicMock(side_effect=RuntimeError("audit down"))  # type: ignore[method-assign]
    [outcome] = auto.publish_on_project_version(db, _TENANT, _PROJECT, _REVISION)
    assert outcome.outcome == "published"


def test_the_background_entry_point_never_raises() -> None:
    with patch.object(auto, "publish_on_project_version", side_effect=RuntimeError("db down")):
        auto.run_on_project_version(tenant_id=_TENANT, project_id=_PROJECT, version_record_id=_REVISION)
    with patch.object(auto, "publish_on_push", side_effect=RuntimeError("db down")):
        auto.run_on_push(tenant_id=_TENANT, repository_id=_REPO, branch="main", commit_sha=_SHA)


# ---------------------------------------------------------------------------------------------
# On every push
# ---------------------------------------------------------------------------------------------


def _reader(text: str = json.dumps(_OAS), truncated: bool = False) -> MagicMock:
    return MagicMock(return_value=(text, truncated))


@pytest.fixture
def push_store() -> Any:
    with (
        patch.object(auto, "publish_provider_contract", return_value=_published()) as publish,
        patch.object(auto, "compare_provider_contract", return_value=ComparisonRun()) as compare,
    ):
        yield MagicMock(publish=publish, compare=compare)


def test_a_push_publishes_the_file_at_the_commit(push_store: Any) -> None:
    db = FakeDb()
    read = _reader()
    [outcome] = auto.publish_on_push(db, _TENANT, _REPO, "main", _SHA, read=read)
    assert (outcome.outcome, outcome.provider_version) == ("published", _SHA)
    assert read.call_args.args[:4] == ("acme", "billing", "openapi.yaml", _SHA)
    kwargs = push_store.publish.call_args.kwargs
    assert (kwargs["version_number"], kwargs["branch"]) == (_SHA, "main")
    assert kwargs["contract"].sha == _contract().sha
    assert db.queries[0][1] == (_TENANT, _REPO, "main")
    detail = db.audits[0]["detail"]
    assert detail["trigger"] == "push"
    assert detail["source"] == {
        "kind": "repository",
        "repositoryId": _REPO,
        "repository": "acme/billing",
        "path": "openapi.yaml",
        "branch": "main",
        "commit": _SHA,
    }


def test_a_yaml_file_is_read_as_yaml(push_store: Any) -> None:
    yaml_text = "openapi: 3.1.0\ninfo: {title: Billing, version: 2.7.0}\npaths: {}\n"
    [outcome] = auto.publish_on_push(FakeDb(), _TENANT, _REPO, "main", _SHA, read=_reader(yaml_text))
    assert outcome.outcome == "published"
    assert push_store.publish.call_args.kwargs["contract"].content_type == "application/yaml"


@pytest.mark.parametrize(
    "setup, says",
    [
        (lambda db, read: setattr(db, "repository", None), "no longer registered"),
        (lambda db, read: db.repository.update(provider="gitlab"), "only GitHub's can"),
        (lambda db, read: setattr(read, "side_effect", ValueError("GitHub file not found")), "GitHub file not found"),
        (lambda db, read: setattr(read, "return_value", ("{}", True)), "APIOME_PACT_MAX_BYTES"),
        (lambda db, read: db.repository.update(visibility="private"), "linked account token"),
    ],
)
def test_a_file_that_cannot_be_read_fails_with_why(push_store: Any, setup: Any, says: str) -> None:
    db = FakeDb()
    read = _reader()
    setup(db, read)
    [outcome] = auto.publish_on_push(db, _TENANT, _REPO, "main", _SHA, read=read)
    assert outcome.outcome == "failed"
    assert says in (outcome.reason or "")
    push_store.publish.assert_not_called()
    assert says in db.audits[0]["detail"]["reason"]


def test_a_file_that_is_not_openapi_fails_with_the_validation_reason(push_store: Any) -> None:
    [outcome] = auto.publish_on_push(FakeDb(), _TENANT, _REPO, "main", _SHA, read=_reader('{"swagger": "2.0"}'))
    assert outcome.outcome == "failed"
    assert outcome.code is not None and outcome.code.startswith("provider-contract")
    push_store.publish.assert_not_called()


def test_a_push_nobody_follows_reads_nothing(push_store: Any) -> None:
    read = _reader()
    assert auto.publish_on_push(FakeDb(providers=[]), _TENANT, _REPO, "main", _SHA, read=read) == []
    read.assert_not_called()


# ---------------------------------------------------------------------------------------------
# The triggers
# ---------------------------------------------------------------------------------------------


def test_the_version_publish_route_schedules_the_auto_publish() -> None:
    from app import versions_routes

    assert versions_routes.run_contract_auto_publish_on_version is auto.run_on_project_version
    source = open(versions_routes.__file__, encoding="utf-8").read()
    publish = source[source.index("def publish_version(") : source.index("def publish_version_mock_captures(")]
    assert "background_tasks.add_task(\n        run_contract_auto_publish_on_version," in publish


def test_the_webhook_route_schedules_the_auto_publish_for_a_pushed_commit() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.repository_webhook_dispatch import OUTCOME_IGNORED, WebhookIngestResult

    result = WebhookIngestResult(
        outcome=OUTCOME_IGNORED,
        reason="branch_not_tracked",
        repository_id=_REPO,
        tenant_id=_TENANT,
        branch="main",
        pushed_commit=_SHA,
    )
    with (
        patch("app.repository_webhook_routes.guard_webhook_delivery", return_value=MagicMock(allowed=True)),
        patch("app.repository_webhook_routes.ingest_webhook_delivery", return_value=result),
        patch("app.repository_webhook_routes.run_contract_auto_publish_on_push") as run,
    ):
        response = TestClient(app).post("/v1/repositories/webhook/github", content=b"{}")
    assert response.status_code == 200, response.text
    run.assert_called_once_with(tenant_id=_TENANT, repository_id=_REPO, branch="main", commit_sha=_SHA)


def test_the_webhook_route_schedules_nothing_without_a_pushed_commit() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.repository_webhook_dispatch import OUTCOME_DUPLICATE, WebhookIngestResult

    with (
        patch("app.repository_webhook_routes.guard_webhook_delivery", return_value=MagicMock(allowed=True)),
        patch(
            "app.repository_webhook_routes.ingest_webhook_delivery",
            return_value=WebhookIngestResult(outcome=OUTCOME_DUPLICATE, repository_id=_REPO),
        ),
        patch("app.repository_webhook_routes.run_contract_auto_publish_on_push") as run,
    ):
        TestClient(app).post("/v1/repositories/webhook/github", content=b"{}")
    run.assert_not_called()
