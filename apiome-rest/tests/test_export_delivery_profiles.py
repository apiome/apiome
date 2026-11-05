"""Export delivery profiles: the rules, the routes and the cross-channel trail — MFX-38.4 (#4331).

The pure half (:mod:`app.export_delivery_profiles`): one channel block per profile, validated by the channel's
own rules; the webhook secret required on create and kept on update; the stored destination rebuilding the
channel's delivery body; the credential reference; the folded outcome. Then the routes
(:mod:`app.export_delivery_profile_routes`): tenant-scoped CRUD (references checked, the secret sealed and never
returned, 400 / 404 / 409 / 503 refusals, audits without secrets), delivering with a profile through each
channel (the profile recorded on the run and in the channel's audit), and the job's and the profile's delivery
trails. Last, the database's cross-channel query and the V357 migration.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.config import settings
from app.database import Database
from app.emitter import EmitResult, EmittedFile
from app.export_delivery_profiles import (
    DeliveryProfileCreate,
    DeliveryProfileRequestError,
    DeliveryProfileUpdate,
    channel_request,
    credential_ref,
    delivery_outcome,
    normalize_create,
    normalize_update,
    public_destination,
)
from app.export_git_delivery import GitDeliveryRequest
from app.export_git_delivery_routes import ExportGitDeliveryRunModel
from app.export_object_storage_delivery import ObjectStorageDeliveryRequest
from app.export_webhook_delivery import WebhookDeliveryRequest
from app.export_webhook_delivery_routes import ExportWebhookDeliveryRunModel
from app.main import app
from app.mcp_credential_crypto import seal_credential_payload, unseal_credential_payload
from app.permissions import Action, Resource
from app.ssrf_guard import SSRFError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_REPOSITORY = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"
_PROFILE = "55555555-5555-4555-8555-555555555555"
_CREDENTIAL = "66666666-6666-4666-8666-666666666666"
_JOB = "job-0001"
_SECRET = "s3cr3t-signing-key-0123456789"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "ada@example.com"}
_PROFILES = "/v1/export/acme/delivery-profiles"
_DELIVERIES = f"/v1/export/acme/jobs/{_JOB}/deliveries"
_ROUTES = "app.export_delivery_profile_routes"


def _git_body(**fields: Any) -> Dict[str, Any]:
    return {"repositoryId": _REPOSITORY, "targetPath": "specs/orders", **fields}


def _webhook_body(**fields: Any) -> Dict[str, Any]:
    return {"url": "https://ci.example.com/hooks/apiome?token=abc", "secret": _SECRET, **fields}


def _storage_body(**fields: Any) -> Dict[str, Any]:
    return {"credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "/exports/", **fields}


# ===========================================================================
# The rules
# ===========================================================================


def test_a_git_profile_stores_the_normalised_git_body() -> None:
    profile = normalize_create(DeliveryProfileCreate(name="  orders-repo ", channel="git", git=_git_body()))
    assert profile.name == "orders-repo"
    assert profile.description is None
    assert profile.destination == {"repositoryId": _REPOSITORY, "targetPath": "specs/orders", "baseBranch": None,
                                   "mode": "pr"}
    assert profile.secret is None


def test_an_object_storage_profile_stores_the_normalised_storage_body() -> None:
    profile = normalize_create(DeliveryProfileCreate.model_validate(
        {"name": "lake", "channel": "object_storage", "objectStorage": _storage_body(partitioning=["artifact"])}))
    assert profile.destination == {"credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "exports",
                                   "partitioning": ["artifact"]}


def test_a_webhook_profile_keeps_its_secret_out_of_the_destination() -> None:
    profile = normalize_create(DeliveryProfileCreate(name="ci", channel="webhook", webhook=_webhook_body()))
    assert profile.destination == {"url": "https://ci.example.com/hooks/apiome?token=abc", "artifact": "auto"}
    assert profile.secret == _SECRET


@pytest.mark.parametrize("body, expected", [
    ({"name": "", "channel": "git", "git": _git_body()}, "name is required"),
    ({"name": "x" * 121, "channel": "git", "git": _git_body()}, "name is longer than 120 characters"),
    ({"name": "a\nb", "channel": "git", "git": _git_body()}, "name cannot contain a control character"),
    ({"name": "a", "channel": "git", "description": "d" * 1001, "git": _git_body()},
     "description is longer than 1000 characters"),
    ({"name": "a", "channel": "git"}, "git is required for a git profile"),
    ({"name": "a", "channel": "git", "git": _git_body(), "webhook": _webhook_body()},
     "a git profile cannot carry webhook"),
    ({"name": "a", "channel": "git", "git": _git_body(targetPath="../escape")}, "git."),
    ({"name": "a", "channel": "object_storage", "objectStorage": _storage_body(bucket="Bad_Bucket")},
     "objectStorage.bucket must be"),
    ({"name": "a", "channel": "webhook", "webhook": {"url": "https://ci.example.com/h"}},
     "webhook.secret is required"),
    ({"name": "a", "channel": "webhook", "webhook": _webhook_body(secret="short")},
     "webhook.secret must be 16–512 characters"),
    ({"name": "a", "channel": "webhook", "webhook": _webhook_body(url="ftp://ci.example.com/h")}, "webhook.url:"),
    ({"name": "a", "channel": "webhook", "webhook": _webhook_body(url="https://user:pw@ci.example.com/h")},
     "webhook.url:"),
])
def test_a_bad_profile_names_every_problem(body: Dict[str, Any], expected: str) -> None:
    with pytest.raises(DeliveryProfileRequestError) as caught:
        normalize_create(DeliveryProfileCreate.model_validate(body))
    assert any(error.startswith(expected) for error in caught.value.errors), caught.value.errors


def _existing(channel: str = "webhook", **fields: Any) -> Dict[str, Any]:
    destinations = {
        "webhook": {"url": "https://ci.example.com/h", "artifact": "auto"},
        "git": {"repositoryId": _REPOSITORY, "targetPath": "", "baseBranch": None, "mode": "pr"},
        "object_storage": {"credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "", "partitioning": []},
    }
    values: Dict[str, Any] = dict(id=_PROFILE, tenant_id=_TENANT, name="ci", description="CI hook", channel=channel,
                                  destination=destinations[channel], has_secret=channel == "webhook")
    values.update(fields)
    return values


def test_an_update_keeps_what_it_leaves_out() -> None:
    profile = normalize_update(DeliveryProfileUpdate(name="ci-2"), _existing())
    assert (profile.name, profile.description, profile.channel) == ("ci-2", "CI hook", "webhook")
    assert profile.destination is None and profile.secret is None


def test_an_update_without_a_secret_keeps_the_stored_one_and_blank_description_clears() -> None:
    profile = normalize_update(DeliveryProfileUpdate.model_validate(
        {"description": "  ", "webhook": {"url": "https://ci.example.com/other", "artifact": "fetch"}}), _existing())
    assert profile.description is None
    assert profile.destination == {"url": "https://ci.example.com/other", "artifact": "fetch"}
    assert profile.secret is None


def test_an_update_cannot_change_the_channel() -> None:
    with pytest.raises(DeliveryProfileRequestError) as caught:
        normalize_update(DeliveryProfileUpdate.model_validate({"git": _git_body()}), _existing())
    assert caught.value.errors == ["a webhook profile cannot carry git; its channel cannot change"]


def test_a_stored_destination_rebuilds_each_channel_s_delivery_body() -> None:
    git = channel_request("git", _existing("git")["destination"])
    assert isinstance(git, GitDeliveryRequest) and git.repository_id == _REPOSITORY
    storage = channel_request("object_storage", _existing("object_storage")["destination"])
    assert isinstance(storage, ObjectStorageDeliveryRequest) and storage.partitioning == []
    webhook = channel_request("webhook", _existing()["destination"], _SECRET)
    assert isinstance(webhook, WebhookDeliveryRequest) and webhook.secret == _SECRET
    with pytest.raises(ValueError):
        channel_request("webhook", _existing()["destination"])
    with pytest.raises(ValueError):
        channel_request("ftp", {})


def test_the_credential_is_a_reference_and_a_webhook_url_hides_its_query() -> None:
    assert credential_ref("git", {"repositoryId": "r"}) == {"kind": "repository", "id": "r"}
    assert credential_ref("object_storage", {"credentialId": "c"}) == {"kind": "storage_credential", "id": "c"}
    assert credential_ref("webhook", {"url": "u"}) == {"kind": "webhook_secret", "id": None}
    assert public_destination("webhook", {"url": "https://h.example.com/p?token=abc"})["url"] == \
        "https://h.example.com/p?…"
    assert public_destination("git", {"targetPath": "a"}) == {"targetPath": "a"}


@pytest.mark.parametrize("channel, status, outcome", [
    ("git", "opened", "delivered"), ("git", "up_to_date", "delivered"), ("git", "committed", "delivered"),
    ("git", "in_progress", "in_progress"), ("git", "failed", "failed"),
    ("webhook", "retrying", "in_progress"), ("webhook", "delivered", "delivered"), ("webhook", "failed", "failed"),
    ("object_storage", "delivered", "delivered"), ("object_storage", "in_progress", "in_progress"),
])
def test_every_channel_s_status_folds_into_one_outcome(channel: str, status: str, outcome: str) -> None:
    assert delivery_outcome(channel, status) == outcome


# ===========================================================================
# The profile routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys",
                        json.dumps({"1": base64.b64encode(os.urandom(32)).decode()}))
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _tenant(tenant_id: str = _TENANT):
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": tenant_id})


def _stored(channel: str = "webhook", **fields: Any) -> Dict[str, Any]:
    return _existing(channel, **fields)


def _inserted(**kwargs: Any) -> Dict[str, Any]:
    """What the insert would return for the arguments the route passed."""
    return dict(id=_PROFILE, tenant_id=kwargs["tenant_id"], name=kwargs["name"], description=kwargs["description"],
                channel=kwargs["channel"], destination=kwargs["destination"],
                has_secret=kwargs.get("sealed_secret") is not None)


def test_creating_a_webhook_profile_seals_the_secret_and_never_returns_it() -> None:
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.validate_url") as ssrf, \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile", side_effect=_inserted) as insert, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.post(_PROFILES, json={"name": "ci", "channel": "webhook", "webhook": _webhook_body()})
    assert response.status_code == 201, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    ssrf.assert_called_once_with("https://ci.example.com/hooks/apiome?token=abc")
    body = response.json()
    assert body["destination"] == {"url": "https://ci.example.com/hooks/apiome?…", "artifact": "auto"}
    assert body["credentialRef"] == {"kind": "webhook_secret", "id": None}
    assert _SECRET not in response.text and "token=abc" not in response.text
    kwargs = insert.call_args.kwargs
    assert unseal_credential_payload(kwargs["sealed_secret"], kwargs["secret_key_version"]) == {"secret": _SECRET}
    assert kwargs["actor_id"] == "u1"
    detail = audit.call_args.kwargs["detail"]
    assert audit.call_args.kwargs["action"] == "export.delivery_profile.created"
    assert _SECRET not in json.dumps(detail) and "token=abc" not in json.dumps(detail)


def test_creating_a_git_profile_checks_the_repository_exists() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_tenant_repository", return_value=None), \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile") as insert:
        response = client.post(_PROFILES, json={"name": "repo", "channel": "git", "git": _git_body()})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-delivery-profile-reference-unknown"
    insert.assert_not_called()
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_tenant_repository", return_value={"id": _REPOSITORY}) as lookup, \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile", side_effect=_inserted) as insert, \
            patch(f"{_ROUTES}.write_audit"):
        response = client.post(_PROFILES, json={"name": "repo", "channel": "git", "git": _git_body()})
    assert response.status_code == 201, response.text
    lookup.assert_called_once_with(_TENANT, _REPOSITORY)
    assert insert.call_args.kwargs["sealed_secret"] is None
    assert response.json()["credentialRef"] == {"kind": "repository", "id": _REPOSITORY}


def test_creating_a_storage_profile_checks_the_credential_exists() -> None:
    body = {"name": "lake", "channel": "object_storage", "objectStorage": _storage_body()}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_storage_credential", return_value=None):
        response = client.post(_PROFILES, json=body)
    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0].startswith("objectStorage.credentialId")
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_storage_credential", return_value={"id": _CREDENTIAL}), \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile", side_effect=_inserted), \
            patch(f"{_ROUTES}.write_audit"):
        response = client.post(_PROFILES, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["credentialRef"] == {"kind": "storage_credential", "id": _CREDENTIAL}


def test_refusals_invalid_refused_taken_and_unconfigured(monkeypatch) -> None:
    hook = {"name": "ci", "channel": "webhook", "webhook": _webhook_body()}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant():
        response = client.post(_PROFILES, json={"name": "", "channel": "webhook", "webhook": {"url": "x"}})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-delivery-profile-invalid"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.validate_url", side_effect=SSRFError("resolves to a private address")):
        response = client.post(_PROFILES, json=hook)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-delivery-profile-destination-refused"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), patch(f"{_ROUTES}.validate_url"), \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile", side_effect=pg_errors.UniqueViolation()):
        response = client.post(_PROFILES, json=hook)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "export-delivery-profile-name-taken"
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), patch(f"{_ROUTES}.validate_url"), \
            patch(f"{_ROUTES}.db.insert_export_delivery_profile") as insert:
        response = client.post(_PROFILES, json=hook)
    assert response.status_code == 503
    insert.assert_not_called()


def test_another_tenant_s_slug_is_404() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant("someone-else"):
        assert client.get(_PROFILES).status_code == 404
        assert client.post(_DELIVERIES, json={"profileId": _PROFILE}).status_code == 404


def test_listing_and_reading_need_projects_view() -> None:
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.list_export_delivery_profiles", return_value=[_stored()]) as listing:
        response = client.get(_PROFILES, params={"channel": "webhook"})
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_TENANT, "webhook")
    assert [p["name"] for p in response.json()["profiles"]] == ["ci"]
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        assert client.get(f"{_PROFILES}/{_PROFILE}").status_code == 404
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored("git")):
        response = client.get(f"{_PROFILES}/{_PROFILE}")
    assert response.status_code == 200 and response.json()["channel"] == "git"
    assert client.get(_PROFILES, params={"channel": "ftp"}).status_code == 422


def test_patching_keeps_the_destination_and_secret_it_leaves_out() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()), \
            patch(f"{_ROUTES}.validate_url") as ssrf, \
            patch(f"{_ROUTES}.db.update_export_delivery_profile", return_value=_stored(name="ci-2")) as update, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.patch(f"{_PROFILES}/{_PROFILE}", json={"name": "ci-2"})
    assert response.status_code == 200, response.text
    ssrf.assert_not_called()
    kwargs = update.call_args.kwargs
    assert kwargs["name"] == "ci-2"
    assert kwargs["destination"] == _stored()["destination"]
    assert kwargs["sealed_secret"] is None
    assert audit.call_args.kwargs["detail"]["secretReplaced"] is False


def test_patching_a_new_secret_reseals_it_and_a_new_destination_is_rechecked() -> None:
    new = {"webhook": {"url": "https://ci.example.com/new", "secret": "another-secret-0123456789"}}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()), \
            patch(f"{_ROUTES}.validate_url") as ssrf, \
            patch(f"{_ROUTES}.db.update_export_delivery_profile", return_value=_stored()) as update, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.patch(f"{_PROFILES}/{_PROFILE}", json=new)
    assert response.status_code == 200, response.text
    ssrf.assert_called_once_with("https://ci.example.com/new")
    kwargs = update.call_args.kwargs
    assert unseal_credential_payload(kwargs["sealed_secret"], kwargs["secret_key_version"]) == {
        "secret": "another-secret-0123456789"}
    assert audit.call_args.kwargs["detail"]["secretReplaced"] is True
    assert "another-secret" not in json.dumps(audit.call_args.kwargs["detail"])


def test_patching_refusals() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        assert client.patch(f"{_PROFILES}/{_PROFILE}", json={"name": "x"}).status_code == 404
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()):
        response = client.patch(f"{_PROFILES}/{_PROFILE}", json={"git": _git_body()})
    assert response.status_code == 400
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()), \
            patch(f"{_ROUTES}.db.update_export_delivery_profile", side_effect=pg_errors.UniqueViolation()):
        assert client.patch(f"{_PROFILES}/{_PROFILE}", json={"name": "taken"}).status_code == 409


def test_deleting_audits_and_404s_an_unknown_profile() -> None:
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()), \
            patch(f"{_ROUTES}.db.delete_export_delivery_profile", return_value=True) as delete, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.delete(f"{_PROFILES}/{_PROFILE}")
    assert response.status_code == 204
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    delete.assert_called_once_with(_TENANT, _PROFILE)
    assert audit.call_args.kwargs["action"] == "export.delivery_profile.deleted"
    assert audit.call_args.kwargs["detail"]["name"] == "ci"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        assert client.delete(f"{_PROFILES}/{_PROFILE}").status_code == 404


# ===========================================================================
# The trails
# ===========================================================================


def _attempt(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        channel="webhook", id=_RUN, job_id=_JOB, artifact_id=_ARTIFACT, export_target="openapi-3.1",
        status="retrying", delivery_profile_id=_PROFILE, profile_name="ci",
        destination="https://ci.example.com/h?token=abc", attempt_count=2, error_code="export-webhook-delivery-x",
        error_message="503", started_at=None, finished_at=None, created_by="u1",
    )
    values.update(fields)
    return values


def test_a_job_s_deliveries_span_every_channel_without_leaking_a_token() -> None:
    rows = [_attempt(), _attempt(channel="git", status="opened", destination="acme/specs", attempt_count=1,
                                 delivery_profile_id=None, profile_name=None, error_code=None)]
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.list_export_delivery_attempts", return_value=rows) as listing:
        response = client.get(_DELIVERIES, params={"limit": 10})
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_TENANT, job_id=_JOB, limit=10)
    first, second = response.json()["deliveries"]
    assert first["destination"] == "https://ci.example.com/h?…"
    assert (first["outcome"], first["attemptCount"], first["profileName"]) == ("in_progress", 2, "ci")
    assert (second["channel"], second["outcome"], second["profileId"]) == ("git", "delivered", None)
    assert "token=abc" not in response.text


def test_a_profile_s_deliveries_are_its_trail() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored()), \
            patch(f"{_ROUTES}.db.list_export_delivery_attempts", return_value=[_attempt()]) as listing:
        response = client.get(f"{_PROFILES}/{_PROFILE}/deliveries")
    assert response.status_code == 200, response.text
    listing.assert_called_once_with(_TENANT, profile_id=_PROFILE, limit=100)
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        assert client.get(f"{_PROFILES}/{_PROFILE}/deliveries").status_code == 404


# ===========================================================================
# Delivering with a profile
# ===========================================================================


def test_delivering_with_a_git_profile_runs_the_git_delivery_with_the_profile() -> None:
    run = ExportGitDeliveryRunModel(run_id=_RUN, status="opened", mode="pr", job_id=_JOB,
                                    repository_full_name="acme/specs")
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored("git")) as lookup, \
            patch(f"{_ROUTES}.perform_git_delivery", new=AsyncMock(return_value=run)) as deliver:
        response = client.post(_DELIVERIES, json={"profileId": _PROFILE})
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    lookup.assert_called_once_with(_TENANT, _PROFILE, with_secret=True)
    args, kwargs = deliver.call_args
    assert args[:3] == ("acme", _TENANT, _JOB)
    assert isinstance(args[3], GitDeliveryRequest) and args[3].repository_id == _REPOSITORY
    assert kwargs == {"profile_id": _PROFILE}
    body = response.json()
    assert (body["channel"], body["outcome"], body["destination"], body["profileName"]) == (
        "git", "delivered", "acme/specs", "ci")
    assert body["run"]["pullRequestNumber"] is None and body["run"]["runId"] == _RUN


def test_delivering_with_a_webhook_profile_unseals_its_secret() -> None:
    sealed, version = seal_credential_payload({"secret": _SECRET})
    run = ExportWebhookDeliveryRunModel(run_id=_RUN, status="delivered", job_id=_JOB,
                                        target_url="https://ci.example.com/h", artifact_delivery="inline",
                                        attempt_count=1, max_attempts=4)
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile",
                  return_value=_stored(sealed_secret=sealed, secret_key_version=version)), \
            patch(f"{_ROUTES}.perform_webhook_delivery", new=AsyncMock(return_value=run)) as deliver:
        response = client.post(_DELIVERIES, json={"profileId": _PROFILE})
    assert response.status_code == 200, response.text
    assert deliver.call_args.args[3].secret == _SECRET
    assert _SECRET not in response.text
    assert response.json()["outcome"] == "delivered"


def test_a_webhook_secret_this_deployment_cannot_open_is_503() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile",
                  return_value=_stored(sealed_secret=b"garbage", secret_key_version=9)), \
            patch(f"{_ROUTES}.perform_webhook_delivery") as deliver:
        response = client.post(_DELIVERIES, json={"profileId": _PROFILE})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "export-delivery-profile-secret-unavailable"
    deliver.assert_not_called()


def test_an_unknown_profile_is_404_and_a_corrupt_destination_is_400() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        assert client.post(_DELIVERIES, json={"profileId": _PROFILE}).status_code == 404
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile",
                  return_value=_stored("git", destination={"repositoryId": _REPOSITORY, "mode": "push"})):
        response = client.post(_DELIVERIES, json={"profileId": _PROFILE})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-delivery-profile-destination-invalid"


def test_an_object_storage_profile_records_itself_on_the_run_and_in_the_audit() -> None:
    """Through the real object-storage delivery route code, with its collaborators faked."""
    status = SimpleNamespace(state="completed", result=SimpleNamespace(
        artifact=_ARTIFACT, version_record_id="r1", version_label="1.4.0", target="openapi-3.1", dry_run=False,
        snapshot_hash="sha256:abc", targets=None,
        files=[SimpleNamespace(path="openapi.yaml", media_type="application/yaml", size_bytes=15)],
        fidelity=SimpleNamespace(model_dump=lambda mode: {"summary": {"tier": "lossless"}}),
    ))
    run = dict(id=_RUN, status="delivered", job_id=_JOB, credential_id=_CREDENTIAL, endpoint_url=None,
               bucket="data-lake", key_prefix="exports", partitioning=[], objects=[], manifest_key=None,
               manifest_sha256=None, fidelity={}, error_code=None, error_message=None)
    storage = "app.export_object_storage_delivery_routes"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=_stored("object_storage", destination={
                "credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "exports", "partitioning": []})), \
            patch(f"{storage}.get_export_job_status", new=AsyncMock(return_value=status)), \
            patch(f"{storage}.get_export_job_emit_result",
                  return_value=EmitResult(files=[EmittedFile(path="openapi.yaml", content="openapi: 3.1.0\n")])), \
            patch("app.export_git_delivery_routes.db.get_project_by_id", return_value={"slug": "orders"}), \
            patch(f"{storage}.deliver_to_object_storage", return_value=run) as deliver, \
            patch(f"{storage}.db.set_export_delivery_run_profile") as link, \
            patch(f"{storage}.write_audit") as audit:
        response = client.post(_DELIVERIES, json={"profileId": _PROFILE})
    assert response.status_code == 200, response.text
    assert deliver.call_args.kwargs["request"].prefix == "exports"
    link.assert_called_once_with("object_storage", _TENANT, _RUN, _PROFILE)
    assert audit.call_args.kwargs["action"] == "export.object_storage_delivery"
    assert audit.call_args.kwargs["detail"]["profileId"] == _PROFILE
    body = response.json()
    assert (body["channel"], body["outcome"], body["destination"]) == ("object_storage", "delivered",
                                                                       "data-lake/exports")


def test_a_direct_delivery_names_no_profile() -> None:
    """The channel routes still work unchanged, and record no profile."""
    storage = "app.export_object_storage_delivery_routes"
    status = SimpleNamespace(state="completed", result=SimpleNamespace(
        artifact=_ARTIFACT, version_record_id=None, version_label=None, target="openapi-3.1", dry_run=False,
        snapshot_hash=None, targets=None, files=[], fidelity=None,
    ))
    run = dict(id=_RUN, status="failed", job_id=_JOB, bucket="data-lake", error_code="x")
    with patch(f"{storage}.enforce_permission"), _tenant(), \
            patch(f"{storage}.get_export_job_status", new=AsyncMock(return_value=status)), \
            patch(f"{storage}.get_export_job_emit_result", return_value=EmitResult(files=[])), \
            patch("app.export_git_delivery_routes.db.get_project_by_id", return_value=None), \
            patch(f"{storage}.deliver_to_object_storage", return_value=run), \
            patch(f"{storage}.db.set_export_delivery_run_profile") as link, \
            patch(f"{storage}.write_audit") as audit:
        response = client.post(f"{_DELIVERIES}/object-storage", json={"credentialId": _CREDENTIAL,
                                                                      "bucket": "data-lake"})
    assert response.status_code == 200, response.text
    link.assert_not_called()
    assert "profileId" not in audit.call_args.kwargs["detail"]


# ===========================================================================
# The database
# ===========================================================================


def _database() -> Database:
    return Database.__new__(Database)


def test_the_cross_channel_query_binds_every_placeholder() -> None:
    database = _database()
    database.execute_query = MagicMock(return_value=[{"channel": "git"}])
    assert database.list_export_delivery_attempts(_TENANT, job_id=_JOB, limit=5) == [{"channel": "git"}]
    query, params = database.execute_query.call_args.args
    assert query.count("%s") == len(params)
    assert params[-1] == 5 and params[:5] == (_TENANT, _JOB, _JOB, None, None)
    for table in ("export_git_delivery_runs", "export_webhook_delivery_runs", "export_object_storage_delivery_runs"):
        assert table in query


def test_the_database_refuses_ids_that_are_not_uuids() -> None:
    database = _database()
    database.execute_query = MagicMock()
    assert database.list_export_delivery_attempts("acme") == []
    assert database.list_export_delivery_attempts(_TENANT, profile_id="nope") == []
    assert database.get_export_delivery_profile(_TENANT, "nope") is None
    assert database.list_export_delivery_profiles("acme") == []
    database.execute_query.assert_not_called()
    with pytest.raises(ValueError):
        database.set_export_delivery_run_profile("ftp", _TENANT, _RUN, _PROFILE)
    assert database.set_export_delivery_run_profile("git", _TENANT, "nope", _PROFILE) is False


# ===========================================================================
# The migration
# ===========================================================================

_MIGRATION = "apiome-db/scripts/V357__export_delivery_profiles_4331.sql"


def _migration_text() -> str:
    return (Path(__file__).resolve().parents[2] / _MIGRATION).read_text(encoding="utf-8")


def test_the_migration_carries_every_structural_promise() -> None:
    text = _migration_text()
    required = (
        "CREATE TABLE IF NOT EXISTS export_delivery_profiles (",
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
        "CONSTRAINT export_delivery_profiles_name_unique UNIQUE (tenant_id, name)",
        "CHECK (channel IN ('git', 'webhook', 'object_storage'))",
        "sealed_secret BYTEA,",
        "CHECK ((channel = 'webhook') = (sealed_secret IS NOT NULL)",
        "-- Rollback notes",
    )
    assert [fragment for fragment in required if fragment not in text] == []
    for table in ("export_git_delivery_runs", "export_webhook_delivery_runs", "export_object_storage_delivery_runs"):
        assert (f"ALTER TABLE {table}\n    ADD COLUMN IF NOT EXISTS delivery_profile_id UUID REFERENCES "
                "export_delivery_profiles(id) ON DELETE SET NULL;") in text


def test_the_database_s_channels_match_the_check() -> None:
    from app.export_delivery_profiles import CHANNELS

    text = _migration_text()
    assert all(f"'{channel}'" in text for channel in CHANNELS)
    assert set(Database._EXPORT_DELIVERY_RUN_TABLES) == set(CHANNELS)
