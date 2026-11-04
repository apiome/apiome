"""The export git delivery pipeline — MFX-38.1 (#4328).

End-to-end tests of :func:`app.export_git_delivery_pipeline.deliver_export` against an in-memory GitHub
(:mod:`fake_github_git`), with the run ledger and the repository store injected — so the whole sequence
(resolve the repository and its linked-account token, lay the bundle out under the target path, plan the
change against the base branch, push, open or update the pull request — or commit directly — and close
the run) runs without a database or a network.

What is asserted is the ticket's acceptance criteria:

* **an export lands as a pull request containing the bundle files and the fidelity summary**;
* **multi-file bundles map to directory trees; a re-export updates the same branch** (and the same pull
  request — never a second one);

plus direct-commit mode, the delivery manifest's removal rule, and failures as runs with redacted logs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import patch

from fake_github_git import DEFAULT_TOKEN, FakeGitHub

from app.export_git_delivery import (
    MANIFEST_RELATIVE_PATH,
    PULL_REQUEST_MARKER,
    BundleFile,
    DeliverySubject,
    NormalizedRequest,
    export_branch_name,
)
from app.export_git_delivery_pipeline import (
    ERROR_BASE_BRANCH_MISSING,
    ERROR_CREDENTIAL_MISSING,
    ERROR_EMPTY_BUNDLE,
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
    run_row_to_outcome,
)
from app.sdk_git_delivery_github import GIT_TOKEN_REDACTION_MARKER

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_LINKED = "77777777-7777-4777-8777-777777777777"
_USER = "88888888-8888-4888-8888-888888888888"
_JOB = "job-0001"
_REPORT = "https://apiome.example/ade/dashboard/export/studio?artifact=x&step=review"
_FIDELITY = {"tier": "lossy", "preservedPercent": 87, "total": 40, "preserved": 35, "dropped": 2,
             "approximated": 3, "synthesized": 0, "headline": "2 constructs are dropped."}


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id=_JOB, artifact_id=_ARTIFACT, artifact_slug="orders", artifact_name="Orders API",
        version_record_id=_REVISION, version_label="1.4.0", target="openapi-3.1", targets=(),
        snapshot_hash="sha256:abc", fidelity=_FIDELITY, report_url=_REPORT,
    )
    values.update(fields)
    return DeliverySubject(**values)


def _request(**fields: Any) -> NormalizedRequest:
    values: Dict[str, Any] = dict(repository_id=_REPOSITORY, target_path="specs/orders", base_branch=None,
                                  mode="pr")
    values.update(fields)
    return NormalizedRequest(**values)


_SINGLE = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders\n")]
_MULTI = [
    BundleFile("orders.proto", "syntax = \"proto3\";\nmessage Order {}\n"),
    BundleFile("common/money.proto", "syntax = \"proto3\";\nmessage Money {}\n"),
    BundleFile("common/types/id.proto", "syntax = \"proto3\";\nmessage Id {}\n"),
]


def _repository(**fields: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": _REPOSITORY, "provider": "github", "source": "linked_account",
                           "repository_full_name": "acme/widgets-sdk", "linked_account_id": _LINKED,
                           "created_by": _USER}
    row.update(fields)
    return row


class _Ledger:
    """A stand-in for ``export_git_delivery_runs``."""

    def __init__(self) -> None:
        self.inserts: List[Dict[str, Any]] = []
        self.finishes: List[Dict[str, Any]] = []

    def insert(self, **kwargs: Any) -> Dict[str, Any]:
        self.inserts.append(kwargs)
        return {"id": _RUN, **kwargs}

    def finish(self, run_id: str, tenant_id: str, **kwargs: Any) -> Dict[str, Any]:
        self.finishes.append({"run_id": run_id, "tenant_id": tenant_id, **kwargs})
        return {"id": run_id, **kwargs}


_DEFAULT = object()


def _deliver(github: FakeGitHub, *, files: Sequence[BundleFile] = _SINGLE, subject: Optional[DeliverySubject] = None,
             request: Optional[NormalizedRequest] = None, repository: Any = _DEFAULT,
             token: Optional[str] = DEFAULT_TOKEN) -> tuple[ExportDeliveryOutcome, _Ledger]:
    ledger = _Ledger()
    linked = {"id": _LINKED, "provider": "github", "access_token": token} if token else None
    with patch("app.export_git_delivery_pipeline.db.insert_export_git_delivery_run", ledger.insert), \
        patch("app.export_git_delivery_pipeline.db.finish_export_git_delivery_run", ledger.finish), \
        patch("app.export_git_delivery_pipeline.db.get_tenant_repository",
              return_value=_repository() if repository is _DEFAULT else repository), \
        patch("app.export_git_delivery_pipeline.db.get_external_auth_provider_for_user", return_value=linked) as lookup:
        outcome = deliver_export(tenant_id=_TENANT, actor_id=_USER, subject=subject or _subject(),
                                 request=request or _request(), files=files, client_factory=github.client_factory)
    if repository is _DEFAULT and token is not None and files:
        lookup.assert_called_with(_LINKED, _USER)  # the repository's linked account, never the caller's
    return outcome, ledger


def _github(**fields: Any) -> FakeGitHub:
    github = FakeGitHub(**fields)
    github.seed({"README.md": "# widgets\n", "specs/orders/NOTES.md": "hand-written\n"})
    return github


_BRANCH = export_branch_name("orders", "openapi-3.1", "specs/orders")


# ===========================================================================
# An export lands as a pull request with the bundle and the fidelity summary
# ===========================================================================


def test_a_first_delivery_opens_a_pull_request_carrying_the_bundle_and_the_fidelity_summary() -> None:
    github = _github()
    outcome, ledger = _deliver(github)
    assert outcome.status == RUN_STATUS_OPENED and outcome.error_code is None
    assert outcome.branch_name == _BRANCH and outcome.pull_request_number == 1
    files = github.files_at(_BRANCH)
    assert files["specs/orders/openapi.yaml"] == _SINGLE[0].text
    assert files["README.md"] == "# widgets\n" and files["specs/orders/NOTES.md"] == "hand-written\n"
    manifest = json.loads(files[f"specs/orders/{MANIFEST_RELATIVE_PATH}"])
    assert [entry["path"] for entry in manifest["files"]] == ["openapi.yaml"]
    assert manifest["fidelity"]["tier"] == "lossy" and "jobId" not in manifest
    [pull] = github.open_pulls()
    assert pull.base == "main" and pull.head == _BRANCH
    assert pull.title == "Apiome export: Orders API 1.4.0 → openapi-3.1"
    assert pull.body.startswith(PULL_REQUEST_MARKER)
    assert "| lossy | 87% | 40 | 2 | 3 | 0 |" in pull.body and "2 constructs are dropped." in pull.body
    assert f"]({_REPORT})" in pull.body and "`specs/orders/openapi.yaml` | added" in pull.body
    # The run was opened in progress, then closed with what it wrote.
    assert ledger.inserts[0]["status"] == "in_progress" and ledger.inserts[0]["mode"] == "pr"
    finish = ledger.finishes[0]
    assert finish["status"] == RUN_STATUS_OPENED and finish["pull_request_number"] == 1
    assert finish["fidelity"] == _FIDELITY and finish["changes"]["added"] == 2


def test_a_multi_file_bundle_lands_as_its_directory_tree() -> None:
    github = _github()
    outcome, _ = _deliver(github, files=_MULTI)
    assert outcome.status == RUN_STATUS_OPENED
    files = github.files_at(_BRANCH)
    for item in _MULTI:
        assert files[f"specs/orders/{item.path}"] == item.text
    assert {"specs/orders/common/money.proto", "specs/orders/common/types/id.proto"} <= set(files)


def test_the_repository_root_is_a_valid_target() -> None:
    github = _github()
    outcome, _ = _deliver(github, request=_request(target_path=""))
    branch = export_branch_name("orders", "openapi-3.1", "")
    assert outcome.branch_name == branch == "apiome/export-orders-openapi-3.1"
    assert github.files_at(branch)["openapi.yaml"] == _SINGLE[0].text


# ===========================================================================
# A re-export updates the same branch and pull request
# ===========================================================================


def _ref_and_pull_writes(github: FakeGitHub) -> List[tuple]:
    """Writes that change what a reader sees: refs, commits and pull requests (tree objects excluded)."""
    return [w for w in github.written() if "/git/trees" not in w[1] and "/git/blobs" not in w[1]]


def test_redelivering_the_same_export_writes_nothing() -> None:
    github = _github()
    _deliver(github)
    before = len(_ref_and_pull_writes(github))
    outcome, _ = _deliver(github)
    assert outcome.status == RUN_STATUS_UNCHANGED and outcome.pull_request_number == 1
    assert len(_ref_and_pull_writes(github)) == before


def test_a_re_export_updates_the_same_branch_and_pull_request() -> None:
    github = _github()
    _deliver(github)
    changed = [BundleFile("openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Orders v2\n")]
    outcome, _ = _deliver(github, files=changed, subject=_subject(job_id="job-0002", version_label="1.5.0"))
    assert outcome.status == RUN_STATUS_UPDATED and outcome.pull_request_number == 1
    assert len(github.open_pulls()) == 1 and len(github.pulls) == 1
    assert github.files_at(_BRANCH)["specs/orders/openapi.yaml"] == changed[0].text
    assert "1.5.0" in github.open_pulls()[0].title and "job-0002" in github.open_pulls()[0].body


def test_a_new_job_with_the_same_files_only_refreshes_the_description() -> None:
    github = _github()
    _deliver(github)
    tree = github.tree_of(_BRANCH)
    outcome, _ = _deliver(github, subject=_subject(job_id="job-0002"))
    assert outcome.status == RUN_STATUS_UPDATED and github.tree_of(_BRANCH) == tree
    assert "job-0002" in github.open_pulls()[0].body


def test_once_merged_an_unchanged_re_export_is_up_to_date() -> None:
    github = _github()
    _deliver(github)
    github.merge(1)
    outcome, _ = _deliver(github)
    assert outcome.status == RUN_STATUS_UP_TO_DATE and not github.open_pulls()


def test_a_file_the_export_no_longer_produces_is_removed_and_hand_written_files_are_kept() -> None:
    github = _github()
    _deliver(github, files=_MULTI)
    github.merge(1)
    outcome, _ = _deliver(github, files=_MULTI[:1])
    assert outcome.status == RUN_STATUS_OPENED
    files = github.files_at(_BRANCH)
    assert "specs/orders/orders.proto" in files and "specs/orders/common/money.proto" not in files
    assert files["specs/orders/NOTES.md"] == "hand-written\n"
    assert outcome.changes["removed"] == 2


def test_two_paths_in_one_repository_use_two_branches() -> None:
    github = _github()
    first, _ = _deliver(github)
    second, _ = _deliver(github, request=_request(target_path="specs/orders-v2"))
    assert first.branch_name != second.branch_name and len(github.open_pulls()) == 2


# ===========================================================================
# Direct-commit mode
# ===========================================================================


def test_commit_mode_fast_forwards_the_base_branch_without_a_pull_request() -> None:
    github = _github()
    base = github.refs["main"]
    outcome, ledger = _deliver(github, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_COMMITTED and outcome.branch_name == "main"
    assert outcome.pull_request_number is None and not github.pulls
    assert github.files_at("main")["specs/orders/openapi.yaml"] == _SINGLE[0].text
    assert github.commits[github.refs["main"]]["parents"] == [base]
    assert ledger.finishes[0]["status"] == RUN_STATUS_COMMITTED


def test_commit_mode_into_a_named_base_branch() -> None:
    github = _github()
    github.seed({"README.md": "# release\n"}, branch="release")
    outcome, _ = _deliver(github, request=_request(mode="commit", base_branch="release"))
    assert outcome.status == RUN_STATUS_COMMITTED
    assert "specs/orders/openapi.yaml" in github.files_at("release")
    assert "specs/orders/openapi.yaml" not in github.files_at("main")


def test_commit_mode_with_nothing_new_is_up_to_date() -> None:
    github = _github()
    _deliver(github, request=_request(mode="commit"))
    head = github.refs["main"]
    outcome, _ = _deliver(github, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_UP_TO_DATE and github.refs["main"] == head


def test_commit_mode_never_forces_a_protected_branch() -> None:
    github = _github(protected=["main"])
    head = github.refs["main"]
    outcome, ledger = _deliver(github, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == "export-git-delivery-push-rejected"
    assert "fast-forwards" in (outcome.error_message or "") and github.refs["main"] == head
    assert ledger.finishes[0]["error_code"] == "export-git-delivery-push-rejected"


def test_commit_mode_fails_rather_than_discard_a_concurrent_push() -> None:
    github = _github()
    github.before("PATCH", r"/git/refs/heads/main", lambda: github.commit_to("main", {"OTHER.md": "x\n"}))
    outcome, _ = _deliver(github, request=_request(mode="commit"))
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-push-rejected"
    assert "OTHER.md" in github.files_at("main")


# ===========================================================================
# Failures are runs
# ===========================================================================


def test_a_repository_whose_linked_account_has_no_token_fails_naming_the_fix() -> None:
    outcome, _ = _deliver(_github(), token=None)
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == ERROR_CREDENTIAL_MISSING
    assert "Re-link" in (outcome.error_message or "")


def test_a_public_url_repository_has_no_credential() -> None:
    outcome, _ = _deliver(_github(), repository=_repository(linked_account_id=None, source="public_url"))
    assert outcome.error_code == "export-git-delivery-repository-unlinked"


def test_a_removed_repository_is_a_failed_run() -> None:
    outcome, _ = _deliver(_github(), repository=None)
    assert outcome.error_code == "export-git-delivery-repository-missing"


def test_a_repository_on_another_provider_is_refused() -> None:
    outcome, _ = _deliver(_github(), repository=_repository(provider="gitlab"))
    assert outcome.error_code == "export-git-delivery-provider-unsupported"


def test_a_read_only_account_is_refused_before_anything_is_written() -> None:
    github = _github(can_push=False)
    outcome, _ = _deliver(github)
    assert outcome.error_code == ERROR_PERMISSION_DENIED and not github.written()


def test_an_archived_repository_is_refused() -> None:
    outcome, _ = _deliver(_github(archived=True))
    assert outcome.error_code == ERROR_REPOSITORY_ARCHIVED


def test_a_missing_base_branch_is_a_failed_run() -> None:
    outcome, _ = _deliver(_github(), request=_request(base_branch="does-not-exist"))
    assert outcome.error_code == ERROR_BASE_BRANCH_MISSING


def test_an_empty_bundle_is_refused() -> None:
    github = _github()
    outcome, _ = _deliver(github, files=[])
    assert outcome.error_code == ERROR_EMPTY_BUNDLE and not github.written()


def test_a_rejected_token_is_a_failed_run_and_the_token_never_reaches_the_log() -> None:
    github = _github(token="ghp_someOtherTokenEntirely000000000000")
    github.fault("GET", r"^/repos/acme/widgets-sdk$", 401, f"Bad credentials for {DEFAULT_TOKEN}")
    outcome, ledger = _deliver(github)
    assert outcome.status == RUN_STATUS_FAILED and outcome.error_code == "export-git-delivery-credential-rejected"
    stored = json.dumps(ledger.finishes[0]["log"]) + (outcome.error_message or "")
    assert DEFAULT_TOKEN not in stored and (GIT_TOKEN_REDACTION_MARKER in stored or "credential" in stored.lower())


def test_a_stored_run_reads_back_as_an_outcome() -> None:
    outcome = run_row_to_outcome({"id": _RUN, "status": "opened", "mode": "pr", "job_id": _JOB,
                                  "repository_id": _REPOSITORY, "target_path": "specs", "pull_request_number": 3,
                                  "changes": {"added": 1}, "fidelity": {"tier": "lossless"}, "log": []})
    assert (outcome.run_id, outcome.pull_request_number, outcome.fidelity) == (_RUN, 3, {"tier": "lossless"})
    assert run_row_to_outcome({"status": "failed", "changes": None}).changes == {}
