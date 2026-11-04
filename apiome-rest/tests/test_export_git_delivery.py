"""Export git delivery: the rules and the routes — MFX-38.1 (#4328).

The pure half (:mod:`app.export_git_delivery`): request validation, the stable delivery branch, the bundle's
files (from a retained emit result or a stored artifact, a multi-file bundle keeping its directory tree), the
delivery manifest, and the pull request's words (fidelity summary and report link). Then the routes
(:mod:`app.export_git_delivery_routes`): permissions, tenant scoping, which jobs can be delivered, where the
files come from, auditing, and the history listing. The pipeline against a fake GitHub is
``test_export_git_delivery_pipeline.py``.
"""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.emitter import EmitResult, EmittedFile
from app.export_git_delivery import (
    BRANCH_PREFIX,
    MANIFEST_RELATIVE_PATH,
    PULL_REQUEST_BODY_MAX_CHARS,
    PULL_REQUEST_MARKER,
    BundleFile,
    DeliverySubject,
    ExportGitDeliveryRequestError,
    GitDeliveryRequest,
    bundle_files_from_artifact,
    bundle_files_from_emit,
    commit_message,
    delivery_files,
    export_branch_name,
    export_code,
    fidelity_summary,
    normalize_request,
    pull_request_body,
    pull_request_title,
    report_url,
)
from app.export_git_delivery_pipeline import RUN_STATUS_OPENED, ExportDeliveryOutcome
from app.main import app
from app.permissions import Action, Resource
from app.sdk_git_delivery_targets import ref_name_problem

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_RUN = "44444444-4444-4444-8444-444444444444"
_JOB = "job-0001"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "ada@example.com"}
_DELIVER = f"/v1/export/acme/jobs/{_JOB}/deliveries/git"


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id=_JOB, artifact_id=_ARTIFACT, artifact_slug="orders", artifact_name="Orders API",
        version_record_id=_REVISION, version_label="1.4.0", target="openapi-3.1", targets=(),
        snapshot_hash="sha256:abc", fidelity={"tier": "lossy", "preservedPercent": 87, "total": 40, "dropped": 2,
                                               "approximated": 3, "synthesized": 0},
        report_url="https://ui.example/ade/dashboard/export/studio?artifact=a&step=review",
    )
    values.update(fields)
    return DeliverySubject(**values)


# ===========================================================================
# The request
# ===========================================================================


def test_a_request_is_normalised() -> None:
    request = normalize_request(GitDeliveryRequest(repositoryId=f" {_REPOSITORY} ", targetPath="/specs//orders/",
                                                   baseBranch="refs/heads/main", mode="commit"))
    assert (request.repository_id, request.target_path, request.base_branch, request.mode) == (
        _REPOSITORY, "specs/orders", "main", "commit")
    defaults = normalize_request(GitDeliveryRequest(repositoryId=_REPOSITORY))
    assert (defaults.target_path, defaults.base_branch, defaults.mode) == ("", None, "pr")


@pytest.mark.parametrize(("fields", "needle"), [
    ({"repositoryId": " "}, "repositoryId"),
    ({"repositoryId": _REPOSITORY, "targetPath": "../etc"}, "'..'"),
    ({"repositoryId": _REPOSITORY, "targetPath": "a/.git/hooks"}, ".git"),
    ({"repositoryId": _REPOSITORY, "baseBranch": "bad..name"}, "legal branch"),
    ({"repositoryId": _REPOSITORY, "baseBranch": f"{BRANCH_PREFIX}orders-openapi"}, "own export delivery"),
])
def test_a_bad_request_names_every_problem(fields: Dict[str, Any], needle: str) -> None:
    with pytest.raises(ExportGitDeliveryRequestError) as caught:
        normalize_request(GitDeliveryRequest(**fields))
    assert any(needle in error for error in caught.value.errors)


def test_an_unknown_mode_or_field_is_refused() -> None:
    with pytest.raises(ValueError):
        GitDeliveryRequest(repositoryId=_REPOSITORY, mode="push")
    with pytest.raises(ValueError):
        GitDeliveryRequest(repositoryId=_REPOSITORY, token="ghp_x")


def test_reused_sdk_codes_are_re_prefixed() -> None:
    assert export_code("sdk-git-delivery-push-rejected") == "export-git-delivery-push-rejected"
    assert export_code("something-else") == "something-else"


# ===========================================================================
# The branch
# ===========================================================================


def test_the_branch_is_stable_per_artifact_target_and_path_not_per_version() -> None:
    assert export_branch_name("orders", "openapi-3.1", "") == "apiome/export-orders-openapi-3.1"
    sub = export_branch_name("orders", "openapi-3.1", "specs/orders")
    assert sub.startswith("apiome/export-orders-openapi-3.1-") and sub == export_branch_name(
        "orders", "openapi-3.1", "specs/orders")
    assert sub != export_branch_name("orders", "openapi-3.1", "specs/other")
    assert export_branch_name("orders", "proto3", "") != export_branch_name("orders", "openapi-3.1", "")


@pytest.mark.parametrize(("slug", "target"), [("Orders API (v2)", "openapi-3.1"), (None, None), ("x" * 400, "y" * 400),
                                              ("..lock", "a..b")])
def test_the_branch_is_always_a_legal_ref(slug: Any, target: Any) -> None:
    name = export_branch_name(slug, target, "specs")
    assert ref_name_problem(name) is None and len(name) <= 200 and name.startswith(BRANCH_PREFIX)


# ===========================================================================
# The files
# ===========================================================================


def test_emitted_files_keep_their_tree_and_unsafe_paths_are_dropped() -> None:
    files = bundle_files_from_emit([("b/c.proto", "c"), ("a.proto", "a"), ("../x", "x"), (".git/config", "g"),
                                    ("/abs", "z"), ("d\\e.txt", "e")])
    assert [f.path for f in files] == ["a.proto", "b/c.proto", "d/e.txt"]


def _zip(entries: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_a_stored_zip_is_unpacked_without_its_bundle_manifest() -> None:
    body = _zip({"orders.proto": "o", "common/money.proto": "m", "manifest.json": "{}"})
    files = bundle_files_from_artifact(body, media_type="application/zip",
                                       listed_paths=["orders.proto", "common/money.proto"], multi_target=False)
    assert [(f.path, f.text) for f in files] == [("common/money.proto", "m"), ("orders.proto", "o")]


def test_a_multi_target_zip_keeps_one_directory_per_target() -> None:
    body = _zip({"openapi-3.1/openapi.json": "{}", "proto3/orders.proto": "o", "manifest.json": "{}"})
    files = bundle_files_from_artifact(body, media_type="application/zip", listed_paths=[], multi_target=True)
    assert [f.path for f in files] == ["openapi-3.1/openapi.json", "proto3/orders.proto"]


def test_a_single_file_artifact_takes_the_listed_path() -> None:
    files = bundle_files_from_artifact("openapi: 3.1.0\n", media_type="application/yaml",
                                       listed_paths=["openapi.yaml"], multi_target=False)
    assert [(f.path, f.text) for f in files] == [("openapi.yaml", "openapi: 3.1.0\n")]
    raw = bundle_files_from_artifact(b"syntax = 1;\n", media_type="text/plain", listed_paths=["a.proto"],
                                     multi_target=False)
    assert raw[0].text == "syntax = 1;\n"


def test_delivery_files_place_the_bundle_and_a_deterministic_manifest_under_the_path() -> None:
    files = [BundleFile("common/money.proto", "m"), BundleFile("orders.proto", "o")]
    out = delivery_files(_subject(), files, "specs/orders")
    assert [f.path for f in out] == ["specs/orders/.apiome/export-delivery.json", "specs/orders/common/money.proto",
                                     "specs/orders/orders.proto"]
    manifest = json.loads(out[0].text)
    assert manifest["schemaVersion"] == "export.git-delivery.v1" and manifest["target"] == "openapi-3.1"
    assert [entry["path"] for entry in manifest["files"]] == ["common/money.proto", "orders.proto"]
    # No job id or clock: a new job with the same files commits the same manifest.
    assert out[0].text == delivery_files(_subject(job_id="job-0002"), files, "specs/orders")[0].text
    assert MANIFEST_RELATIVE_PATH.endswith("export-delivery.json")


# ===========================================================================
# The words
# ===========================================================================


def test_the_fidelity_summary_is_lifted_from_the_envelope() -> None:
    envelope = {"summary": {"tier": "lossy", "preserved_percent": 87, "total": 40, "preserved": 35, "dropped": 2,
                            "approximated": 3, "synthesized": 0}, "advisory": {"headline": "2 dropped."}}
    assert fidelity_summary(envelope) == {"tier": "lossy", "preservedPercent": 87, "total": 40, "preserved": 35,
                                          "dropped": 2, "approximated": 3, "synthesized": 0, "headline": "2 dropped."}
    assert fidelity_summary(None) == {} and fidelity_summary({"summary": None}) == {}


def test_the_report_link_opens_export_studio_on_the_review_step() -> None:
    url = report_url("https://ui.example/", _ARTIFACT, _REVISION, "openapi-3.1")
    assert url == (f"https://ui.example/ade/dashboard/export/studio?artifact={_ARTIFACT}&version={_REVISION}"
                   "&target=openapi-3.1&step=review")
    assert "target=" not in report_url("https://ui.example", _ARTIFACT, None, "multi")
    assert report_url("", _ARTIFACT, None, None) is None


def test_the_pull_request_carries_the_fidelity_summary_and_the_report_link() -> None:
    changes = {"added": 2, "modified": 0, "removed": 0, "unchanged": 1,
               "files": [{"path": "specs/orders/openapi.yaml", "change": "added"}], "truncated": False}
    body = pull_request_body(_subject(), changes, target_path="specs/orders")
    assert body.startswith(PULL_REQUEST_MARKER)
    assert "| lossy | 87% | 40 | 2 | 3 | 0 |" in body
    assert "[Open the full fidelity report](https://ui.example/" in body
    assert "`specs/orders/openapi.yaml` | added" in body and "`job-0001`" in body
    assert body == pull_request_body(_subject(), changes, target_path="specs/orders")  # no clock
    assert "rebuilds it" not in pull_request_body(_subject(), changes, target_path="", mode="commit")
    assert "No fidelity report" in pull_request_body(_subject(fidelity={}), changes, target_path="")


def test_a_long_change_list_is_folded_and_the_body_capped() -> None:
    files = [{"path": f"f{i}.txt", "change": "added"} for i in range(200)]
    body = pull_request_body(_subject(), {"added": 900, "files": files, "truncated": True}, target_path="")
    assert "… and 850 more" in body and len(body) <= PULL_REQUEST_BODY_MAX_CHARS


def test_the_title_and_commit_message_name_the_export() -> None:
    assert pull_request_title(_subject()) == "Apiome export: Orders API 1.4.0 → openapi-3.1"
    multi = _subject(target="multi", targets=("openapi-3.1", "proto3"))
    assert pull_request_title(multi).endswith("→ openapi-3.1, proto3")
    message = commit_message(_subject())
    assert message.startswith("Apiome export: Orders API 1.4.0") and "Fidelity: lossy, 87% preserved." in message


# ===========================================================================
# The routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _result(**fields: Any) -> SimpleNamespace:
    values: Dict[str, Any] = dict(
        artifact=_ARTIFACT, version_record_id=_REVISION, version_label="1.4.0", target="openapi-3.1", dry_run=False,
        snapshot_hash="sha256:abc", files=[SimpleNamespace(path="openapi.yaml")], targets=None,
        fidelity=SimpleNamespace(model_dump=lambda mode: {"summary": {"tier": "lossy", "preserved_percent": 87}}),
    )
    values.update(fields)
    return SimpleNamespace(**values)


def _status(state: str = "completed", result: Any = "default") -> SimpleNamespace:
    return SimpleNamespace(state=state, result=_result() if result == "default" else result)


def _outcome(**fields: Any) -> ExportDeliveryOutcome:
    values: Dict[str, Any] = dict(run_id=_RUN, status=RUN_STATUS_OPENED, mode="pr", job_id=_JOB,
                                  repository_id=_REPOSITORY, repository_full_name="acme/specs", base_branch="main",
                                  target_path="specs", branch_name="apiome/export-orders-openapi-3.1-abc123",
                                  commit_sha="c" * 40, pull_request_number=7,
                                  pull_request_url="https://github.com/acme/specs/pull/7", changes={"added": 2},
                                  fidelity={"tier": "lossy"})
    values.update(fields)
    return ExportDeliveryOutcome(**values)


class _Patches:
    """Every collaborator of the delivery route, with sensible defaults."""

    def __init__(self, *, status: Any = None, tenant: Any = "default", emitted: Any = "default") -> None:
        emit = EmitResult(files=[EmittedFile(path="openapi.yaml", content="openapi: 3.1.0\n")])
        self.patches = [
            patch("app.export_git_delivery_routes.enforce_permission"),
            patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug",
                  return_value={"id": _TENANT} if tenant == "default" else tenant),
            patch("app.export_git_delivery_routes.get_export_job_status",
                  new=AsyncMock(return_value=status or _status())),
            patch("app.export_git_delivery_routes.get_export_job_emit_result",
                  return_value=emit if emitted == "default" else emitted),
            patch("app.export_git_delivery_routes.resolve_export_download"),
            patch("app.export_git_delivery_routes.db.get_project_by_id",
                  return_value={"id": _ARTIFACT, "slug": "orders", "name": "Orders API"}),
            patch("app.export_git_delivery_routes.deliver_export", return_value=_outcome()),
            patch("app.export_git_delivery_routes.write_audit"),
        ]
        self.mocks: Dict[str, Any] = {}

    def __enter__(self) -> "_Patches":
        names = ["guard", "tenant", "status", "emitted", "download", "project", "deliver", "audit"]
        for name, item in zip(names, self.patches):
            self.mocks[name] = item.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        for item in reversed(self.patches):
            item.__exit__(*exc)


def _body(**fields: Any) -> Dict[str, Any]:
    return {"repositoryId": _REPOSITORY, "targetPath": "specs", **fields}


def test_delivering_requires_versions_publish_and_returns_the_run() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in p.mocks["guard"].call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    body = response.json()
    assert (body["status"], body["pullRequestNumber"], body["jobId"], body["mode"]) == ("opened", 7, _JOB, "pr")
    kwargs = p.mocks["deliver"].call_args.kwargs
    assert kwargs["tenant_id"] == _TENANT and kwargs["request"].target_path == "specs"
    assert [f.path for f in kwargs["files"]] == ["openapi.yaml"]
    subject: DeliverySubject = kwargs["subject"]
    assert (subject.artifact_slug, subject.target, subject.fidelity["tier"]) == ("orders", "openapi-3.1", "lossy")
    assert subject.report_url and "step=review" in subject.report_url
    audit = p.mocks["audit"].call_args.kwargs
    assert audit["action"] == "export.git_delivery" and audit["detail"]["pullRequestNumber"] == 7
    assert "token" not in json.dumps(audit["detail"]).lower()


def test_a_forbidden_caller_is_refused_before_anything_runs() -> None:
    with _Patches() as p:
        p.mocks["guard"].side_effect = HTTPException(status_code=403, detail="Forbidden")
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 403 and not p.mocks["deliver"].called


def test_another_tenant_s_slug_is_404() -> None:
    with _Patches(tenant={"id": "99999999-9999-4999-8999-999999999999"}) as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 404 and not p.mocks["deliver"].called


def test_an_invalid_request_is_400_with_every_problem() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json=_body(targetPath="../x", baseBranch="a..b"))
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "export-git-delivery-request-invalid" and len(detail["errors"]) == 2
    assert not p.mocks["deliver"].called


@pytest.mark.parametrize(("status", "code"), [
    (SimpleNamespace(state="running", result=None), "export-git-delivery-job-not-completed"),
    (SimpleNamespace(state="completed", result=_result(dry_run=True)), "export-git-delivery-dry-run"),
])
def test_a_job_that_cannot_be_delivered_is_409(status: Any, code: str) -> None:
    with _Patches(status=status) as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert not p.mocks["deliver"].called


def test_another_instance_reads_the_stored_artifact() -> None:
    zipped = _zip({"orders.proto": "o", "common/money.proto": "m", "manifest.json": "{}"})
    result = _result(files=[SimpleNamespace(path="orders.proto"), SimpleNamespace(path="common/money.proto")])
    with _Patches(status=_status(result=result), emitted=None) as p:
        p.mocks["download"].return_value = SimpleNamespace(body=zipped, media_type="application/zip")
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200
    files = p.mocks["deliver"].call_args.kwargs["files"]
    assert [f.path for f in files] == ["common/money.proto", "orders.proto"]


def test_an_expired_artifact_is_410() -> None:
    with _Patches(emitted=None) as p:
        p.mocks["download"].side_effect = HTTPException(status_code=410, detail="expired")
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 410 and not p.mocks["deliver"].called


def test_a_multi_target_job_carries_its_weakest_target() -> None:
    def _target(name: str, percent: int) -> SimpleNamespace:
        return SimpleNamespace(target=name, fidelity=SimpleNamespace(
            model_dump=lambda mode: {"summary": {"tier": "lossy", "preserved_percent": percent}}))

    result = _result(target=None, fidelity=None, targets=[_target("openapi-3.1", 100), _target("proto3", 60)])
    with _Patches(status=_status(result=result)) as p:
        assert client.post(_DELIVER, json=_body()).status_code == 200
    subject: DeliverySubject = p.mocks["deliver"].call_args.kwargs["subject"]
    assert subject.target == "multi" and subject.targets == ("openapi-3.1", "proto3")
    assert subject.fidelity["preservedPercent"] == 60 and "proto3" in subject.fidelity["headline"]
    assert "target=" not in (subject.report_url or "")


def test_a_failed_delivery_is_200_with_its_code() -> None:
    with _Patches() as p:
        p.mocks["deliver"].return_value = _outcome(status="failed", error_code="export-git-delivery-push-rejected",
                                                   error_message="refused", pull_request_number=None)
        response = client.post(_DELIVER, json=_body(mode="commit"))
    assert response.status_code == 200
    assert response.json()["errorCode"] == "export-git-delivery-push-rejected"
    assert p.mocks["deliver"].call_args.kwargs["request"].mode == "commit"


def test_listing_a_job_s_deliveries_needs_projects_view() -> None:
    rows: List[Dict[str, Any]] = [{"id": _RUN, "status": "opened", "mode": "pr", "job_id": _JOB, "target_path": "specs",
                                   "pull_request_number": 7, "changes": {}, "fidelity": {}, "log": []}]
    with patch("app.export_git_delivery_routes.enforce_permission") as guard, \
        patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
        patch("app.export_git_delivery_routes.db.list_export_git_delivery_runs", return_value=rows) as listing:
        response = client.get(_DELIVER)
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_TENANT, _JOB)
    assert response.json()["runs"][0]["pullRequestNumber"] == 7
