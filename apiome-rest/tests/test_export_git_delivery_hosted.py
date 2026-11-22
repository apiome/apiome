"""Export git delivery to GitLab, Bitbucket and Azure DevOps — #6654.

End-to-end tests of :func:`app.export_git_delivery_pipeline.deliver_export` against the in-memory
hosts in :mod:`fake_hosted_git`, with the run ledger and the repository store injected. Every test
runs once per provider, so the acceptance criteria are asserted for each:

* **an export delivers as a merge / pull request, and as a direct commit**;
* **failures (credential, permission, protected branch) are ``failed`` runs with redacted logs**;

plus the re-export rules the GitHub channel already keeps (same branch, same pull request, nothing
written when nothing changed) and the delivery manifest's removal rule.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import patch

import pytest
from fake_hosted_git import HOSTED_TOKEN, make_host

from app.export_git_delivery import (
    MANIFEST_RELATIVE_PATH,
    PULL_REQUEST_MARKER,
    BundleFile,
    DeliverySubject,
    NormalizedRequest,
    export_branch_name,
)
from app.export_git_delivery_azure_devops import DESCRIPTION_MAX_CHARS, AzureDevOpsGitClient
from app.export_git_delivery_pipeline import (
    ERROR_PERMISSION_DENIED,
    ERROR_REPOSITORY_ARCHIVED,
    RUN_STATUS_COMMITTED,
    RUN_STATUS_FAILED,
    RUN_STATUS_OPENED,
    RUN_STATUS_UNCHANGED,
    RUN_STATUS_UP_TO_DATE,
    RUN_STATUS_UPDATED,
    ExportDeliveryOutcome,
    deliver_export,
)
from app.export_git_delivery_staged import STAGED_COMMIT_PREFIX, TREE_TRAILER
from app.sdk_git_delivery_github import GIT_TOKEN_REDACTION_MARKER

PROVIDERS = ["gitlab", "bitbucket", "azure_devops"]

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_RUN = "44444444-4444-4444-8444-444444444444"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_LINKED = "77777777-7777-4777-8777-777777777777"
_USER = "88888888-8888-4888-8888-888888888888"
_REPORT = "https://apiome.example/ade/dashboard/export/studio?artifact=x&step=review"
_FIDELITY = {"tier": "lossy", "preservedPercent": 87, "total": 40, "preserved": 35, "dropped": 2,
             "approximated": 3, "synthesized": 0, "headline": "2 constructs are dropped."}
_SINGLE = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders\n")]
_MULTI = [
    BundleFile("orders.proto", "syntax = \"proto3\";\nmessage Order {}\n"),
    BundleFile("common/money.proto", "syntax = \"proto3\";\nmessage Money {}\n"),
    BundleFile("common/types/id.proto", "syntax = \"proto3\";\nmessage Id {}\n"),
]
_BRANCH = export_branch_name("orders", "openapi-3.1", "specs/orders")


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id="job-0001", artifact_id=_ARTIFACT, artifact_slug="orders",
        artifact_name="Orders API", version_record_id=None, version_label="1.4.0", target="openapi-3.1",
        targets=(), snapshot_hash="sha256:abc", fidelity=_FIDELITY, report_url=_REPORT,
    )
    values.update(fields)
    return DeliverySubject(**values)


def _request(**fields: Any) -> NormalizedRequest:
    values: Dict[str, Any] = dict(repository_id=_REPOSITORY, target_path="specs/orders", base_branch=None, mode="pr")
    values.update(fields)
    return NormalizedRequest(**values)


class _Ledger:
    def __init__(self) -> None:
        self.finishes: List[Dict[str, Any]] = []

    def insert(self, **kwargs: Any) -> Dict[str, Any]:
        return {"id": _RUN, **kwargs}

    def finish(self, run_id: str, tenant_id: str, **kwargs: Any) -> Dict[str, Any]:
        self.finishes.append(kwargs)
        return {"id": run_id, **kwargs}


def _deliver(host: Any, provider: str, *, files: Sequence[BundleFile] = _SINGLE,
             subject: Optional[DeliverySubject] = None, request: Optional[NormalizedRequest] = None,
             token: Optional[str] = HOSTED_TOKEN) -> tuple[ExportDeliveryOutcome, _Ledger]:
    ledger = _Ledger()
    repository = {"id": _REPOSITORY, "provider": provider, "source": "linked_account",
                  "repository_full_name": host.full_name, "linked_account_id": _LINKED, "created_by": _USER}
    linked = {"id": _LINKED, "provider": provider, "access_token": token} if token else None
    with patch("app.export_git_delivery_pipeline.db.insert_export_git_delivery_run", ledger.insert), \
        patch("app.export_git_delivery_pipeline.db.finish_export_git_delivery_run", ledger.finish), \
        patch("app.export_git_delivery_pipeline.db.get_tenant_repository", return_value=repository), \
        patch("app.export_git_delivery_pipeline.db.get_external_auth_provider_for_user", return_value=linked):
        outcome = deliver_export(tenant_id=_TENANT, actor_id=_USER, subject=subject or _subject(),
                                 request=request or _request(), files=files, client_factory=host.client_factory)
    return outcome, ledger


# ===========================================================================
# An export delivers as a pull (merge) request
# ===========================================================================


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_first_delivery_opens_a_pull_request_with_the_bundle(provider: str) -> None:
    host = make_host(provider)
    outcome, ledger = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_OPENED and outcome.error_code is None, outcome.error_message
    assert outcome.branch_name == _BRANCH and outcome.pull_request_number == 1
    files = host.files_at(_BRANCH)
    assert files["specs/orders/openapi.yaml"] == _SINGLE[0].text
    assert files["README.md"] == "# widgets\n" and files["specs/orders/NOTES.md"] == "hand-written\n"
    manifest = json.loads(files[f"specs/orders/{MANIFEST_RELATIVE_PATH}"])
    assert [entry["path"] for entry in manifest["files"]] == ["openapi.yaml"]
    [pull] = host.open_pulls()
    assert (pull.base, pull.head) == ("main", _BRANCH)
    assert pull.title == "Apiome export: Orders API 1.4.0 → openapi-3.1" and pull.body.startswith(PULL_REQUEST_MARKER)
    # The run records the host's commit id, never the local staging handle.
    assert outcome.commit_sha == host.refs[_BRANCH] and not outcome.commit_sha.startswith(STAGED_COMMIT_PREFIX)
    assert ledger.finishes[0]["commit_sha"] == host.refs[_BRANCH]
    assert outcome.pull_request_url and str(outcome.pull_request_number) in outcome.pull_request_url
    # The delivery branch is built on the base, with the tree trailer that makes re-delivery a no-op.
    commit = host.commits[host.refs[_BRANCH]]
    assert commit["parents"] == [host.refs["main"]] and f"{TREE_TRAILER}: " in commit["message"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_multi_file_bundle_lands_as_its_directory_tree(provider: str) -> None:
    host = make_host(provider)
    outcome, _ = _deliver(host, provider, files=_MULTI)
    assert outcome.status == RUN_STATUS_OPENED, outcome.error_message
    files = host.files_at(_BRANCH)
    for item in _MULTI:
        assert files[f"specs/orders/{item.path}"] == item.text


@pytest.mark.parametrize("provider", PROVIDERS)
def test_redelivering_the_same_export_writes_nothing(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider)
    before = len(host.written())
    outcome, _ = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_UNCHANGED and outcome.pull_request_number == 1, outcome.error_message
    assert len(host.written()) == before


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_re_export_updates_the_same_branch_and_pull_request(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider)
    changed = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders v2\n")]
    outcome, _ = _deliver(host, provider, files=changed, subject=_subject(job_id="job-0002", version_label="1.5.0"))
    assert outcome.status == RUN_STATUS_UPDATED and outcome.pull_request_number == 1, outcome.error_message
    assert len(host.pulls) == 1 and len(host.open_pulls()) == 1
    assert host.files_at(_BRANCH)["specs/orders/openapi.yaml"] == changed[0].text
    assert "1.5.0" in host.open_pulls()[0].title
    assert host.commits[host.refs[_BRANCH]]["parents"] == [host.refs["main"]]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_re_export_after_the_base_moved_is_rebuilt_on_the_new_base(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider)
    host.commit_to("main", {"CHANGELOG.md": "new\n"})
    outcome, _ = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_UPDATED, outcome.error_message
    assert host.commits[host.refs[_BRANCH]]["parents"] == [host.refs["main"]]
    assert "CHANGELOG.md" in host.files_at(_BRANCH)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_once_merged_an_unchanged_re_export_is_up_to_date(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider)
    host.merge(1)
    outcome, _ = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_UP_TO_DATE and not host.open_pulls(), outcome.error_message


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_file_the_export_no_longer_produces_is_removed_and_hand_written_files_are_kept(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider, files=_MULTI)
    host.merge(1)
    outcome, _ = _deliver(host, provider, files=_MULTI[:1])
    assert outcome.status == RUN_STATUS_OPENED, outcome.error_message
    files = host.files_at(_BRANCH)
    assert "specs/orders/orders.proto" in files and "specs/orders/common/money.proto" not in files
    assert files["specs/orders/NOTES.md"] == "hand-written\n" and outcome.changes["removed"] == 2


# ===========================================================================
# An export delivers as a direct commit
# ===========================================================================


@pytest.mark.parametrize("provider", PROVIDERS)
def test_commit_mode_fast_forwards_the_base_branch(provider: str) -> None:
    host = make_host(provider)
    base = host.refs["main"]
    outcome, _ = _deliver(host, provider, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_COMMITTED and outcome.branch_name == "main", outcome.error_message
    assert outcome.pull_request_number is None and not host.pulls
    assert host.files_at("main")["specs/orders/openapi.yaml"] == _SINGLE[0].text
    assert host.commits[host.refs["main"]]["parents"] == [base] and outcome.commit_sha == host.refs["main"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_commit_mode_updates_files_a_previous_delivery_wrote(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider, request=_request(mode="commit"))
    changed = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders v2\n")]
    outcome, _ = _deliver(host, provider, files=changed, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_COMMITTED, outcome.error_message
    assert host.files_at("main")["specs/orders/openapi.yaml"] == changed[0].text


@pytest.mark.parametrize("provider", PROVIDERS)
def test_commit_mode_with_nothing_new_is_up_to_date(provider: str) -> None:
    host = make_host(provider)
    _deliver(host, provider, request=_request(mode="commit"))
    head = host.refs["main"]
    outcome, _ = _deliver(host, provider, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_UP_TO_DATE and host.refs["main"] == head


_WRITE_ROUTE = {"gitlab": r"/repository/commits$", "bitbucket": r"/src$", "azure_devops": r"/pushes$"}


#: The directory listing each host serves — read after the base branch, before the write.
_LIST_ROUTE = {"gitlab": r"/repository/tree$", "bitbucket": r"/src/[0-9a-f]+/specs/orders/$",
               "azure_devops": r"/items$"}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_commit_mode_fails_rather_than_discard_a_concurrent_push(provider: str) -> None:
    host = make_host(provider)
    # Someone pushes to main after the delivery read it and before it writes.
    host.before("GET", _LIST_ROUTE[provider], lambda: host.commit_to("main", {"OTHER.md": "x\n"}))
    outcome, ledger = _deliver(host, provider, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-push-rejected"
    assert "OTHER.md" in host.files_at("main") and "specs/orders/openapi.yaml" not in host.files_at("main")
    assert ledger.finishes[0]["status"] == RUN_STATUS_FAILED


@pytest.mark.parametrize("provider", PROVIDERS)
def test_commit_mode_into_a_protected_branch_is_a_failed_run(provider: str) -> None:
    host = make_host(provider, protected=["main"])
    head = host.refs["main"]
    outcome, ledger = _deliver(host, provider, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-push-rejected"
    assert host.refs["main"] == head and "fast-forwards" in (outcome.error_message or "")
    assert ledger.finishes[0]["error_code"] == "export-git-delivery-push-rejected"


# ===========================================================================
# Failures are runs with redacted logs
# ===========================================================================


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_rejected_token_is_a_failed_run_and_the_token_never_reaches_the_log(provider: str) -> None:
    host = make_host(provider, token="some-other-token-entirely-000000")
    outcome, ledger = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-credential-rejected"
    stored = json.dumps(ledger.finishes[0]["log"]) + (outcome.error_message or "")
    assert HOSTED_TOKEN not in stored and "re-link" in stored.lower()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_host_error_that_quotes_the_token_is_redacted(provider: str) -> None:
    host = make_host(provider)
    host.fault("GET", r"(widgets-sdk|projects/.*)$", 500, f"internal failure for token {HOSTED_TOKEN}")
    outcome, ledger = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_FAILED and outcome.retryable
    stored = json.dumps(ledger.finishes[0]["log"]) + (outcome.error_message or "")
    assert HOSTED_TOKEN not in stored and GIT_TOKEN_REDACTION_MARKER in stored


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_missing_credential_names_the_provider(provider: str) -> None:
    outcome, _ = _deliver(make_host(provider), provider, token=None)
    label = {"gitlab": "GitLab", "bitbucket": "Bitbucket", "azure_devops": "Azure DevOps"}[provider]
    assert outcome.error_code == "export-git-delivery-credential-missing" and label in (outcome.error_message or "")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_push_without_write_access_is_permission_denied(provider: str) -> None:
    host = make_host(provider)
    host.fault("POST", _WRITE_ROUTE[provider], 403, "Forbidden")
    outcome, _ = _deliver(host, provider)
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == ERROR_PERMISSION_DENIED
    assert not host.open_pulls()


def test_a_gitlab_reporter_is_refused_before_anything_is_written() -> None:
    host = make_host("gitlab", can_push=False)
    outcome, _ = _deliver(host, "gitlab")
    assert outcome.error_code == ERROR_PERMISSION_DENIED and not host.written()
    assert "Developer" in (outcome.error_message or "")


def test_a_bitbucket_read_only_account_is_refused_before_anything_is_written() -> None:
    host = make_host("bitbucket", permission="read")
    outcome, _ = _deliver(host, "bitbucket")
    assert outcome.error_code == ERROR_PERMISSION_DENIED and not host.written()


def test_a_bitbucket_token_that_cannot_read_its_permissions_lets_the_push_decide() -> None:
    host = make_host("bitbucket", permission=None)
    outcome, _ = _deliver(host, "bitbucket")
    assert outcome.status == RUN_STATUS_OPENED, outcome.error_message


@pytest.mark.parametrize("provider", ["gitlab", "azure_devops"])
def test_an_archived_repository_is_refused(provider: str) -> None:
    outcome, _ = _deliver(make_host(provider, archived=True), provider)
    assert outcome.error_code == ERROR_REPOSITORY_ARCHIVED


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_target_path_that_is_a_file_is_refused(provider: str) -> None:
    host = make_host(provider)
    outcome, _ = _deliver(host, provider, request=_request(target_path="README.md"))
    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == "export-git-delivery-target-path-invalid", outcome.error_message


# ===========================================================================
# Provider specifics
# ===========================================================================


def test_bitbucket_opens_a_new_pull_request_when_rebuilding_the_branch_declined_the_old_one() -> None:
    host = make_host("bitbucket", decline_on_branch_delete=True)
    _deliver(host, "bitbucket")
    changed = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders v2\n")]
    outcome, _ = _deliver(host, "bitbucket", files=changed)
    assert outcome.status == RUN_STATUS_UPDATED and outcome.pull_request_number == 2, outcome.error_message
    [pull] = host.open_pulls()
    assert pull.number == 2 and host.files_at(_BRANCH)["specs/orders/openapi.yaml"] == changed[0].text


def test_azure_devops_rebuilds_a_branch_through_a_scratch_branch_it_then_deletes() -> None:
    host = make_host("azure_devops")
    _deliver(host, "azure_devops")
    changed = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders v2\n")]
    outcome, _ = _deliver(host, "azure_devops", files=changed)
    assert outcome.status == RUN_STATUS_UPDATED, outcome.error_message
    assert not [branch for branch in host.refs if branch.startswith("apiome/scratch-")]


def test_azure_devops_without_force_push_is_a_failed_run_naming_the_permission() -> None:
    host = make_host("azure_devops", allow_force=False)
    _deliver(host, "azure_devops")
    host.commit_to("main", {"CHANGELOG.md": "new\n"})
    outcome, _ = _deliver(host, "azure_devops")
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-push-rejected"
    assert "Force push" in (outcome.error_message or "")


def test_azure_devops_shortens_a_description_past_its_limit() -> None:
    long_body = "x" * 9000
    short = AzureDevOpsGitClient._description(long_body)
    assert len(short) <= DESCRIPTION_MAX_CHARS and "shortened" in short and short.startswith("x" * 100)
    assert AzureDevOpsGitClient._description("short") == "short"


def test_azure_devops_accepts_a_long_pull_request_body() -> None:
    host = make_host("azure_devops")
    with patch("app.export_git_delivery_pipeline.pull_request_body", return_value="y" * 9000):
        outcome, _ = _deliver(host, "azure_devops")
    assert outcome.status == RUN_STATUS_OPENED, outcome.error_message
    [pull] = host.open_pulls()
    assert len(pull.body) <= DESCRIPTION_MAX_CHARS and "shortened" in pull.body


def test_azure_devops_reports_a_sign_in_page_as_a_rejected_credential() -> None:
    host = make_host("azure_devops", token="not-for-devops")
    outcome, _ = _deliver(host, "azure_devops")
    assert outcome.error_code == "export-git-delivery-credential-rejected"
    assert "HTTP 203" in (outcome.error_message or "")


def test_gitlab_pages_through_a_large_directory() -> None:
    host = make_host("gitlab")
    host.commit_to("main", {f"specs/orders/extra/f{i:03}.txt": "x\n" for i in range(250)})
    outcome, _ = _deliver(host, "gitlab")
    assert outcome.status == RUN_STATUS_OPENED, outcome.error_message
    tree_reads = [r for r in host.requests if r[0] == "GET" and r[1].endswith("/repository/tree")]
    assert len(tree_reads) >= 3
