"""The git delivery pipeline — SDK-4.2 (#4496).

End-to-end tests of :mod:`app.sdk_git_delivery_pipeline` against an in-memory GitHub
(:mod:`fake_github_git`), with the store and the SDK-3.4 settings injected — so the whole sequence
(resolve the repository and its existing linked-account token, build the SDK-4.1 layout, plan the
change against the base branch, push, open or update the pull request, close the run) runs without
a database or a network.

What is asserted is the ticket's acceptance criteria rather than any one call:

* a delivery produces a pull request carrying the SDK, with provenance in its body;
* re-running for the same inputs updates the same pull request — never a second one — and writes
  nothing when nothing changed;
* credential failures and push rejections are *failed runs* with actionable, redacted logs;
* the credential is the repository's existing linked-account token.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from fake_github_git import DEFAULT_TOKEN, FakeGitHub, FakePull
from test_sdk_distribution import _SPEC, _api, _http_op
from test_sdk_publish_pipeline import _settings

from app.canonical_model import Operation, OperationKind
from app.sdk_git_delivery_changes import MANIFEST_RELATIVE_PATH
from app.sdk_git_delivery_github import (
    ERROR_CREDENTIAL_REJECTED,
    ERROR_PERMISSION_DENIED,
    ERROR_PROVIDER_UNAVAILABLE,
    ERROR_PUSH_REJECTED,
    ERROR_RATE_LIMITED,
    ERROR_TARGET_PATH_INVALID,
    ERROR_TREE_TOO_LARGE,
    GIT_TOKEN_REDACTION_MARKER,
    GitHubGitClient,
)
from app.sdk_git_delivery_pipeline import (
    ERROR_BASE_BRANCH_MISSING,
    ERROR_CREDENTIAL_MISSING,
    ERROR_INTERNAL,
    ERROR_REPOSITORY_ARCHIVED,
    RUN_STATUS_FAILED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_OPENED,
    RUN_STATUS_UNCHANGED,
    RUN_STATUS_UP_TO_DATE,
    RUN_STATUS_UPDATED,
    DeliveryOutcome,
    deliver,
    run_row_to_outcome,
)
from app.sdk_git_delivery_summary import PULL_REQUEST_MARKER
from app.sdk_git_delivery_targets import DeliveryTarget
from app.sdk_publish_pipeline import PublishContext

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_TARGET = "66666666-6666-4666-8666-666666666666"
_LINKED = "77777777-7777-4777-8777-777777777777"
_USER = "88888888-8888-4888-8888-888888888888"
_BRANCH = "apiome/sdk-regen-1.4.2-widgets-npm"

_CONTEXT = PublishContext(
    tenant_id=_TENANT,
    tenant_slug="acme",
    project_id=_PROJECT,
    project_slug="widgets",
    version_record_id=_REVISION,
    version_line="1.4.2",
    actor_id=_USER,
)

_TARGET_TS = DeliveryTarget(
    target_id=_TARGET,
    ecosystem="npm",
    repository_id=_REPOSITORY,
    base_branch=None,
    target_path="sdks/ts",
)


def _repository(**fields: Any) -> Dict[str, Any]:
    """A ``tenant_repositories`` row registered through a linked GitHub account."""
    row: Dict[str, Any] = {
        "id": _REPOSITORY,
        "provider": "github",
        "source": "linked_account",
        "repository_full_name": "acme/widgets-sdk",
        "linked_account_id": _LINKED,
        "created_by": _USER,
    }
    row.update(fields)
    return row


class _Ledger:
    """A stand-in for ``sdk_git_delivery_runs``."""

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


def _deliver(
    github: FakeGitHub,
    *,
    api=None,
    target: DeliveryTarget = _TARGET_TS,
    repository: Any = _DEFAULT,
    token: Optional[str] = DEFAULT_TOKEN,
    settings=None,
    counter: int = 0,
    context: PublishContext = _CONTEXT,
    source_text: str = _SPEC,
    **kwargs: Any,
) -> tuple[DeliveryOutcome, _Ledger]:
    """Run one delivery with every collaborator injected."""
    ledger = _Ledger()
    linked = {"id": _LINKED, "provider": "github", "access_token": token} if token else None
    with patch("app.sdk_publish_pipeline.load_settings", return_value=settings or _settings()), \
        patch("app.sdk_git_delivery_pipeline.db.next_sdk_publish_counter", return_value=counter), \
        patch("app.sdk_git_delivery_pipeline.db.insert_sdk_git_delivery_run", ledger.insert), \
        patch("app.sdk_git_delivery_pipeline.db.finish_sdk_git_delivery_run", ledger.finish), \
        patch(
            "app.sdk_git_delivery_pipeline.db.get_tenant_repository",
            return_value=_repository() if repository is _DEFAULT else repository,
        ), \
        patch(
            "app.sdk_git_delivery_pipeline.db.get_external_auth_provider_for_user",
            return_value=linked,
        ) as lookup:
        outcome = deliver(
            api or _api(),
            context=context,
            target=target,
            source_text=source_text,
            source_format="openapi-3.1",
            apiome_version="1.184.0",
            client_factory=github.client_factory,
            **kwargs,
        )
    if repository is _DEFAULT and token is not None:
        # The credential is the repository's existing linked account — looked up by the account the
        # repository names and the user who registered it, never by the caller.
        lookup.assert_called_with(_LINKED, _USER)
    return outcome, ledger


def _github(**fields: Any) -> FakeGitHub:
    """A repository with a README on ``main``."""
    github = FakeGitHub(**fields)
    github.seed({"README.md": "# widgets sdk\n"})
    return github


def _pull_writes(github: FakeGitHub, start: int = 0) -> List[tuple]:
    """Ref, commit and pull-request writes after request ``start`` (tree/blob objects excluded)."""
    return [
        item
        for item in github.requests[start:]
        if item[0] in ("POST", "PATCH")
        and (item[1].endswith("/git/commits") or "/git/refs" in item[1] or "/pulls" in item[1])
    ]


def _two_operation_api():
    """The fixture API plus a second HTTP operation."""
    return _api(
        [
            _http_op("getWidget", path="/widgets/{id}"),
            _http_op("listWidgets", path="/widgets"),
            Operation(key="Query.widgets", name="widgetsQuery", kind=OperationKind.QUERY),
        ]
    )


# --------------------------------------------------------------------------------------------
# A delivery opens a pull request carrying the SDK
# --------------------------------------------------------------------------------------------
def test_a_first_delivery_opens_a_pull_request_carrying_the_sdk():
    github = _github()
    main_before = github.refs["main"]

    outcome, ledger = _deliver(github)

    assert outcome.status == RUN_STATUS_OPENED
    assert outcome.error_code is None
    assert outcome.branch_name == _BRANCH
    assert outcome.pull_request_number == 1
    assert outcome.pull_request_url == "https://github.com/acme/widgets-sdk/pull/1"
    assert outcome.commit_sha == github.refs[_BRANCH]
    assert outcome.base_branch == "main"
    assert outcome.base_sha == main_before

    # The base branch is untouched; the SDK lives on the delivery branch, built on top of it.
    assert github.refs["main"] == main_before
    assert github.commits[github.refs[_BRANCH]]["parents"] == [main_before]
    files = github.files_at(_BRANCH)
    assert files["README.md"] == "# widgets sdk\n"
    package = json.loads(files["sdks/ts/package.json"])
    assert package["name"] == "@acme/widgets-sdk"
    assert package["version"] == "1.4.0"
    assert package["apiome"]["versionRecordId"] == _REVISION
    assert files["sdks/ts/spec/spec.json"] == _SPEC
    assert "sdks/ts/snippets/getWidget.ts" in files
    manifest = json.loads(files[f"sdks/ts/{MANIFEST_RELATIVE_PATH}"])
    assert "snippets/getWidget.ts" in {entry["path"] for entry in manifest["files"]}

    [pull] = github.open_pulls()
    assert (pull.head, pull.base) == (_BRANCH, "main")
    assert pull.title == "Apiome SDK: @acme/widgets-sdk 1.4.0 (widgets 1.4.2)"
    assert pull.body.startswith(PULL_REQUEST_MARKER)
    # Spec version, generator version, changed files and provenance — the acceptance criterion.
    assert "`1.4.2`" in pull.body and f"`{_REVISION}`" in pull.body
    assert "Apiome `1.184.0`" in pull.body
    assert "`sdks/ts/package.json`" in pull.body
    assert "### Provenance" in pull.body and "`versionRecordId`" in pull.body

    message = github.commits[github.refs[_BRANCH]]["message"]
    assert f"Apiome-Revision: {_REVISION}" in message
    assert "Apiome-Package: npm @acme/widgets-sdk@1.4.0" in message

    assert ledger.inserts[0]["status"] == RUN_STATUS_IN_PROGRESS
    assert ledger.inserts[0]["target_id"] == _TARGET
    [finish] = ledger.finishes
    assert finish["status"] == RUN_STATUS_OPENED
    assert finish["pull_request_number"] == 1
    assert finish["branch_name"] == _BRANCH
    assert finish["changes"]["added"] == len([p for p in files if p.startswith("sdks/ts/")])
    assert finish["changes"]["removed"] == 0
    assert finish["provenance"]["packageVersion"] == "1.4.0"


def test_a_repository_root_target_keeps_the_rest_of_the_repository():
    github = _github()
    github.commit_to("main", {".github/workflows/ci.yml": "on: push\n"})
    target = DeliveryTarget(_TARGET, "npm", _REPOSITORY, None, "")

    outcome, _ = _deliver(github, target=target)

    assert outcome.status == RUN_STATUS_OPENED
    files = github.files_at(_BRANCH)
    # Everything the layout does not generate is kept...
    assert files[".github/workflows/ci.yml"] == "on: push\n"
    assert "package.json" in files and MANIFEST_RELATIVE_PATH in files
    # ...and a file it does generate is replaced, visibly, as a modification.
    assert files["README.md"].startswith("# @acme/widgets-sdk")
    assert {"path": "README.md", "change": "modified"} in outcome.changes["files"]


def test_a_pypi_target_commits_the_sdist_layout():
    github = _github()
    target = DeliveryTarget(_TARGET, "pypi", _REPOSITORY, None, "python")

    outcome, _ = _deliver(github, target=target)

    assert outcome.status == RUN_STATUS_OPENED
    assert outcome.branch_name == "apiome/sdk-regen-1.4.2-widgets-pypi"
    files = github.files_at(outcome.branch_name)
    assert "python/pyproject.toml" in files
    assert "python/acme_widgets/__init__.py" in files


# --------------------------------------------------------------------------------------------
# Idempotency: the same inputs update the same pull request
# --------------------------------------------------------------------------------------------
def test_rerunning_the_same_inputs_writes_nothing_and_reuses_the_pull_request():
    github = _github()
    first, _ = _deliver(github)
    head = github.refs[_BRANCH]
    mark = len(github.requests)

    again, ledger = _deliver(github)

    assert again.status == RUN_STATUS_UNCHANGED
    assert again.pull_request_number == first.pull_request_number
    assert again.commit_sha == head
    assert github.refs[_BRANCH] == head
    assert len(github.pulls) == 1
    assert _pull_writes(github, mark) == [], "an unchanged re-run must not push or edit the PR"
    assert ledger.finishes[0]["status"] == RUN_STATUS_UNCHANGED


def test_a_moved_base_rebuilds_the_branch_and_updates_the_same_pull_request():
    github = _github()
    _deliver(github)
    moved = github.commit_to("main", {"CONTRIBUTING.md": "be kind\n"})

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_UPDATED
    assert outcome.pull_request_number == 1
    assert len(github.pulls) == 1
    # Rebuilt on the latest base, not stacked on the previous delivery commit.
    assert github.commits[github.refs[_BRANCH]]["parents"] == [moved]
    assert github.files_at(_BRANCH)["CONTRIBUTING.md"] == "be kind\n"
    assert any(
        method == "PATCH" and "/git/refs/heads/" in path and body["force"] is True
        for method, path, body in github.requests
    )


def test_a_changed_api_updates_the_open_pull_request_not_a_second_one():
    github = _github()
    _deliver(github)

    outcome, _ = _deliver(github, api=_two_operation_api())

    assert outcome.status == RUN_STATUS_UPDATED
    assert len(github.pulls) == 1 and len(github.open_pulls()) == 1
    assert "sdks/ts/snippets/listWidgets.ts" in github.files_at(_BRANCH)
    assert "`sdks/ts/snippets/listWidgets.ts`" in github.pulls[0].body


def test_changed_branding_updates_the_same_pull_request():
    """Options change a pull request's content, never its identity."""
    github = _github()
    _deliver(github)

    rebranded = _settings(npm="@acme/widgets-client", pypi="acme-widgets")
    outcome, _ = _deliver(github, settings=rebranded)

    assert outcome.status == RUN_STATUS_UPDATED
    assert len(github.pulls) == 1
    assert json.loads(github.files_at(_BRANCH)["sdks/ts/package.json"])["name"] == "@acme/widgets-client"


def test_a_changed_base_branch_retargets_the_open_pull_request():
    github = _github()
    _deliver(github)
    github.refs["develop"] = github.refs["main"]
    target = DeliveryTarget(_TARGET, "npm", _REPOSITORY, "develop", "sdks/ts")

    outcome, _ = _deliver(github, target=target)

    assert outcome.status == RUN_STATUS_UPDATED
    assert outcome.base_branch == "develop"
    assert github.pulls[0].base == "develop"
    assert len(github.pulls) == 1


def test_after_the_pull_request_is_merged_an_unchanged_rerun_is_up_to_date():
    github = _github()
    _deliver(github)
    github.merge(1)
    mark = len(github.requests)

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_UP_TO_DATE
    assert outcome.pull_request_number is None
    assert len(github.pulls) == 1
    assert _pull_writes(github, mark) == []
    assert not [item for item in github.requests[mark:] if item[1].endswith("/git/trees") and item[0] == "POST"]


def test_after_a_merge_a_changed_api_opens_a_fresh_pull_request_on_the_same_branch():
    github = _github()
    _deliver(github)
    github.merge(1)

    outcome, _ = _deliver(github, api=_two_operation_api())

    assert outcome.status == RUN_STATUS_OPENED
    assert outcome.pull_request_number == 2
    assert [pull.number for pull in github.open_pulls()] == [2]
    assert github.commits[github.refs[_BRANCH]]["parents"] == [github.refs["main"]]


def test_a_closed_pull_request_is_proposed_again_on_rerun():
    github = _github()
    _deliver(github)
    github.close(1)
    mark = len(github.requests)

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_OPENED
    assert outcome.pull_request_number == 2
    # The branch already held exactly this SDK, so it was reused rather than pushed again.
    assert not [item for item in github.requests[mark:] if item[1].endswith("/git/commits")]


def test_a_base_that_already_contains_the_sdk_leaves_the_open_pull_request_alone():
    github = _github()
    _deliver(github)
    sdk = {path: text for path, text in github.files_at(_BRANCH).items() if path.startswith("sdks/")}
    github.commit_to("main", sdk)

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_UP_TO_DATE
    assert outcome.pull_request_number == 1
    assert github.pulls[0].state == "open"
    assert any("safe to close" in entry["message"] for entry in outcome.log)


# --------------------------------------------------------------------------------------------
# Only generated files are removed
# --------------------------------------------------------------------------------------------
def test_stale_generated_files_are_removed_and_hand_written_files_are_kept():
    github = _github()
    github.commit_to("main", {"sdks/ts/LICENSE": "MIT\n"})
    _deliver(github, api=_two_operation_api())
    github.merge(1)
    assert "sdks/ts/snippets/listWidgets.ts" in github.files_at("main")

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_OPENED
    files = github.files_at(outcome.branch_name)
    assert "sdks/ts/snippets/listWidgets.ts" not in files
    assert files["sdks/ts/LICENSE"] == "MIT\n"
    assert outcome.changes["removed"] == 1
    assert {"path": "sdks/ts/snippets/listWidgets.ts", "change": "removed"} in outcome.changes["files"]


def test_a_first_delivery_into_an_existing_directory_deletes_nothing():
    github = _github()
    github.commit_to("main", {"sdks/ts/snippets/handwritten.ts": "export {};\n"})

    outcome, _ = _deliver(github)

    assert outcome.changes["removed"] == 0
    assert github.files_at(_BRANCH)["sdks/ts/snippets/handwritten.ts"] == "export {};\n"


# --------------------------------------------------------------------------------------------
# The committed version
# --------------------------------------------------------------------------------------------
def test_the_committed_version_is_the_next_registry_release():
    github = _github()
    outcome, ledger = _deliver(github, counter=3)
    assert outcome.package_version == "1.4.3"
    assert (outcome.release_series, outcome.regen_counter) == ("1.4", 3)
    assert json.loads(github.files_at(_BRANCH)["sdks/ts/package.json"])["version"] == "1.4.3"
    assert ledger.finishes[0]["package_version"] == "1.4.3"


def test_a_pinned_counter_overrides_the_registry_counter():
    github = _github()
    outcome, _ = _deliver(github, counter=3, regen_counter=7)
    assert outcome.package_version == "1.4.7"
    assert any("(pinned)" in entry["message"] for entry in outcome.log)


def test_a_large_file_is_uploaded_as_a_blob_first():
    github = _github()
    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "Widgets API"}, "x-pad": "p" * 150_000})

    outcome, _ = _deliver(github, source_text=spec)

    assert outcome.status == RUN_STATUS_OPENED
    assert any(method == "POST" and path.endswith("/git/blobs") for method, path, _ in github.requests)
    assert github.files_at(_BRANCH)["sdks/ts/spec/spec.json"] == spec


# --------------------------------------------------------------------------------------------
# Credential failures are failed runs with actionable logs
# --------------------------------------------------------------------------------------------
def test_a_repository_whose_linked_account_has_no_token_is_a_failed_run():
    github = _github()

    outcome, ledger = _deliver(github, token=None)

    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == ERROR_CREDENTIAL_MISSING
    assert "Re-link" in outcome.error_message
    assert github.requests == [], "nothing is sent to GitHub without a credential"
    [finish] = ledger.finishes
    assert finish["status"] == RUN_STATUS_FAILED
    assert finish["error_code"] == ERROR_CREDENTIAL_MISSING
    assert finish["log"][-1]["level"] == "error"


def test_a_revoked_token_is_a_failed_run_naming_the_fix():
    github = _github(token="ghp_theTokenGitHubActuallyAccepts0001")

    outcome, ledger = _deliver(github, token="ghp_revokedTokenValueNoLongerValid99")

    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == ERROR_CREDENTIAL_REJECTED
    assert "re-link the GitHub account" in outcome.error_message
    assert ledger.finishes[0]["repository_full_name"] == "acme/widgets-sdk"


def test_a_read_only_account_is_refused_before_anything_is_written():
    github = _github(can_push=False)

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_PERMISSION_DENIED
    assert "cannot push" in outcome.error_message
    assert github.written() == []


def test_a_token_without_write_scope_fails_at_the_first_write():
    github = _github()
    github.fault("POST", r"/git/trees$", 403, "Resource not accessible by personal access token")

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == ERROR_PERMISSION_DENIED
    assert "`repo` scope" in outcome.error_message
    assert _BRANCH not in github.refs


def test_the_token_never_reaches_the_log_even_when_github_quotes_it():
    github = _github()
    github.fault("GET", r"/widgets-sdk$", 403, f"token {DEFAULT_TOKEN} lacks access")

    outcome, ledger = _deliver(github)

    assert outcome.status == RUN_STATUS_FAILED
    assert DEFAULT_TOKEN not in outcome.error_message
    assert GIT_TOKEN_REDACTION_MARKER in outcome.error_message
    assert DEFAULT_TOKEN not in json.dumps(outcome.log)
    assert DEFAULT_TOKEN not in json.dumps(ledger.finishes, default=str)


def test_rate_limiting_is_a_retryable_failure():
    github = _github()
    github.fault(
        "GET", r"/widgets-sdk$", 403, "API rate limit exceeded",
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1788000000"},
    )

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_RATE_LIMITED
    assert outcome.retryable is True
    assert "1788000000" in outcome.error_message


def test_github_being_unavailable_is_a_retryable_failure():
    github = _github()
    github.fault("GET", r"/git/ref/heads/main$", 502, "Bad Gateway")

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_PROVIDER_UNAVAILABLE
    assert outcome.retryable is True


# --------------------------------------------------------------------------------------------
# Push rejections are failed runs with actionable logs
# --------------------------------------------------------------------------------------------
def test_a_protected_delivery_branch_is_a_failed_run_that_keeps_what_it_learned():
    github = _github()
    _deliver(github)
    github.protected.append(_BRANCH)
    body_before = github.pulls[0].body

    outcome, ledger = _deliver(github, api=_two_operation_api())

    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == ERROR_PUSH_REJECTED
    assert "branch protection" in outcome.error_message
    assert "Protected branch update failed" in outcome.error_message
    assert github.pulls[0].body == body_before, "a rejected push must not rewrite the PR"
    finish = ledger.finishes[0]
    assert finish["branch_name"] == _BRANCH and finish["commit_sha"]
    assert finish["pull_request_number"] == 1


def test_a_refused_branch_creation_is_a_failed_run():
    github = _github()
    github.fault("POST", r"/git/refs$", 422, "Cannot create ref due to creations being restricted")

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_PUSH_REJECTED
    assert github.open_pulls() == []


def test_a_missing_base_branch_is_a_failed_run():
    github = _github()
    target = DeliveryTarget(_TARGET, "npm", _REPOSITORY, "develop", "sdks/ts")

    outcome, _ = _deliver(github, target=target)

    assert outcome.error_code == ERROR_BASE_BRANCH_MISSING
    assert "'develop'" in outcome.error_message


def test_an_archived_repository_is_refused():
    outcome, _ = _deliver(_github(archived=True))
    assert outcome.error_code == ERROR_REPOSITORY_ARCHIVED


def test_a_target_path_that_is_a_file_is_a_failed_run():
    github = _github()
    github.commit_to("main", {"sdks": "not a directory\n"})

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_TARGET_PATH_INVALID


def test_a_directory_too_large_to_list_is_a_failed_run():
    github = _github(truncate_trees=True)
    github.commit_to("main", {"sdks/ts/index.js": "module.exports = {};\n"})

    outcome, _ = _deliver(github)

    assert outcome.error_code == ERROR_TREE_TOO_LARGE
    assert github.written() == []


# --------------------------------------------------------------------------------------------
# Configuration and package problems are failed runs too
# --------------------------------------------------------------------------------------------
def test_a_removed_repository_is_a_failed_run():
    github = _github()
    outcome, ledger = _deliver(github, repository=None)
    assert outcome.error_code == "sdk-git-delivery-repository-missing"
    assert ledger.finishes[0]["status"] == RUN_STATUS_FAILED
    assert github.requests == []


def test_a_repository_on_another_provider_is_a_failed_run():
    outcome, _ = _deliver(_github(), repository=_repository(provider="gitlab"))
    assert outcome.error_code == "sdk-git-delivery-provider-unsupported"


def test_a_package_that_cannot_be_named_is_a_failed_run_with_the_publish_code():
    github = _github()
    outcome, _ = _deliver(github, settings=_settings(pypi="acme-widgets"))
    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == "sdk-publish-package-name-missing"
    assert github.requests == []


def test_an_unmappable_version_line_is_a_failed_run():
    context = PublishContext(
        tenant_id=_TENANT,
        tenant_slug="acme",
        project_id=_PROJECT,
        project_slug="widgets",
        version_record_id=_REVISION,
        version_line="latest",
    )
    outcome, _ = _deliver(_github(), context=context)
    assert outcome.error_code == "sdk-publish-version-line-invalid"
    assert outcome.branch_name is None


def test_an_unexpected_error_still_closes_the_run():
    github = _github()
    with patch.object(GitHubGitClient, "get_repository", side_effect=RuntimeError("boom")):
        outcome, ledger = _deliver(github)
    assert outcome.status == RUN_STATUS_FAILED
    assert outcome.error_code == ERROR_INTERNAL
    assert "boom" not in outcome.error_message
    assert ledger.finishes[0]["status"] == RUN_STATUS_FAILED


# --------------------------------------------------------------------------------------------
# Races with a concurrent delivery
# --------------------------------------------------------------------------------------------
def test_a_branch_created_concurrently_is_force_updated_rather_than_failing():
    github = _github()
    github.before("POST", r"/git/refs$", lambda: github.refs.__setitem__(_BRANCH, github.refs["main"]))

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_OPENED
    assert github.refs[_BRANCH] == outcome.commit_sha
    assert any("concurrent delivery" in entry["message"] for entry in outcome.log)


def test_a_pull_request_opened_concurrently_is_updated_not_duplicated():
    github = _github()
    github.before(
        "POST",
        r"/pulls$",
        lambda: github.pulls.append(FakePull(number=9, head=_BRANCH, base="main", title="x", body="y")),
    )

    outcome, _ = _deliver(github)

    assert outcome.status == RUN_STATUS_UPDATED
    assert outcome.pull_request_number == 9
    assert [pull.number for pull in github.open_pulls()] == [9]
    assert github.pulls[0].body.startswith(PULL_REQUEST_MARKER)


# --------------------------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------------------------
def test_a_stored_run_reads_back_as_an_outcome():
    row = {
        "id": _RUN,
        "status": "opened",
        "ecosystem": "npm",
        "version_line": "1.4.2",
        "release_series": "1.4",
        "regen_counter": 0,
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.0",
        "repository_id": _REPOSITORY,
        "repository_full_name": "acme/widgets-sdk",
        "base_branch": "main",
        "target_path": "sdks/ts",
        "branch_name": _BRANCH,
        "base_sha": "a" * 40,
        "commit_sha": "b" * 40,
        "pull_request_number": 4,
        "pull_request_url": "https://github.com/acme/widgets-sdk/pull/4",
        "changes": {"added": 3},
        "provenance": {"versionRecordId": _REVISION},
        "log": [{"step": "push"}],
        "error_code": None,
        "error_message": None,
    }
    outcome = run_row_to_outcome(row)
    assert outcome.run_id == _RUN
    assert outcome.pull_request_number == 4
    assert outcome.changes == {"added": 3}
    assert outcome.retryable is False


def test_a_stored_run_with_malformed_json_columns_reads_back_empty():
    outcome = run_row_to_outcome({"id": _RUN, "status": "failed", "changes": "x", "log": None})
    assert outcome.changes == {} and outcome.provenance == {} and outcome.log == []
