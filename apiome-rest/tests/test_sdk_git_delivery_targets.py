"""Where a project's SDK is delivered — SDK-4.2 (#4496).

Tests for :mod:`app.sdk_git_delivery_targets`: the branch naming rule that makes a delivery
idempotent per (version, target) and keeps several SDKs in one repository apart, git's ref-name
rules, target-path normalisation that cannot aim a delivery outside the repository, and the
repository eligibility rule that is the "no new credential type" criterion — a target can only name
a repository registered through a linked GitHub account.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.sdk_git_delivery_targets import (
    BRANCH_MAX_CHARS,
    GIT_DELIVERY_TARGET_SCHEMA_VERSION,
    TARGET_PATH_MAX_CHARS,
    GitDeliveryTargetError,
    branch_pattern,
    delete_target,
    list_targets,
    normalize_base_branch,
    normalize_ecosystem,
    normalize_target_path,
    parse_repository_full_name,
    ref_name_problem,
    ref_segment,
    regen_branch_name,
    repository_problem,
    resolve_target,
    save_target,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_TARGET = "66666666-6666-4666-8666-666666666666"


def _repository(**fields: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": _REPOSITORY,
        "provider": "github",
        "source": "linked_account",
        "repository_full_name": "acme/widgets-sdk",
        "linked_account_id": "77777777-7777-4777-8777-777777777777",
        "created_by": "88888888-8888-4888-8888-888888888888",
    }
    row.update(fields)
    return row


def _target_row(**fields: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": _TARGET,
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "ecosystem": "npm",
        "repository_id": _REPOSITORY,
        "base_branch": None,
        "target_path": "sdks/ts",
        "updated_by": None,
        "repository_full_name": "acme/widgets-sdk",
        "repository_provider": "github",
        "repository_source": "linked_account",
        "repository_default_branch": "main",
        "repository_has_linked_account": True,
    }
    row.update(fields)
    return row


# --------------------------------------------------------------------------------------------
# Branch names
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version, project, ecosystem, expected",
    [
        ("1.4.2", "widgets", "npm", "apiome/sdk-regen-1.4.2-widgets-npm"),
        ("1.4.2", "widgets", "pypi", "apiome/sdk-regen-1.4.2-widgets-pypi"),
        ("v3", "gadgets", "npm", "apiome/sdk-regen-v3-gadgets-npm"),
        ("2026-01-04", "widgets", "npm", "apiome/sdk-regen-2026-01-04-widgets-npm"),
        ("1.5.0-beta.2", "widgets", "npm", "apiome/sdk-regen-1.5.0-beta.2-widgets-npm"),
        ("Release 2 (beta)", "Widgets API", "npm", "apiome/sdk-regen-release-2-beta-widgets-api-npm"),
        (None, "widgets", "npm", "apiome/sdk-regen-unversioned-widgets-npm"),
        ("1..2", "a.lock", "npm", "apiome/sdk-regen-1.2-a-npm"),
        ("~^:?*[\\", "", "npm", "apiome/sdk-regen-unversioned-project-npm"),
    ],
)
def test_the_regen_branch_is_named_after_version_project_and_ecosystem(version, project, ecosystem, expected):
    name = regen_branch_name(version, project, ecosystem)
    assert name == expected
    assert ref_name_problem(name) is None


def test_two_projects_or_two_ecosystems_in_one_repository_never_share_a_branch():
    names = {
        regen_branch_name("1.4.2", "widgets", "npm"),
        regen_branch_name("1.4.2", "widgets", "pypi"),
        regen_branch_name("1.4.2", "gadgets", "npm"),
    }
    assert len(names) == 3


def test_the_same_inputs_always_name_the_same_branch():
    assert regen_branch_name("1.4.2", "widgets", "npm") == regen_branch_name("1.4.2", "widgets", "npm")


def test_a_very_long_label_still_yields_a_legal_bounded_branch():
    name = regen_branch_name("9" * 500, "p" * 500, "npm")
    assert len(name) <= BRANCH_MAX_CHARS
    assert ref_name_problem(name) is None


def test_ref_segment_never_ends_in_a_dot_lock_or_separator():
    assert ref_segment("thing.lock", "x") == "thing"
    assert ref_segment("-.abc.-", "x") == "abc"
    assert ref_segment("", "fallback") == "fallback"


def test_the_branch_pattern_describes_the_version_placeholder():
    assert branch_pattern("widgets", "npm") == "apiome/sdk-regen-{version}-widgets-npm"


@pytest.mark.parametrize(
    "name",
    ["", "a b", "a~b", "a^b", "a:b", "a?b", "a*b", "a[b", "a\\b", "a..b", "a@{b", "@", "-a",
     "/a", "a/", "a//b", "a.", ".a", "a/.b", "a.lock", "a/b.lock/c", "x" * 256],
)
def test_git_ref_rules_are_enforced(name):
    assert ref_name_problem(name) is not None


@pytest.mark.parametrize("name", ["main", "release/1.x", "feature/sdk-v2", "develop"])
def test_ordinary_branch_names_are_legal(name):
    assert ref_name_problem(name) is None


# --------------------------------------------------------------------------------------------
# Field normalisation
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [(None, ""), ("", ""), ("  /  ", ""), ("sdks/ts", "sdks/ts"), ("/sdks//ts/", "sdks/ts")],
)
def test_target_paths_are_normalised(raw, expected):
    assert normalize_target_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["../outside", "sdks/../../x", "./sdks", ".git/hooks", "sdks/.GIT/x", "sdks\\ts", "a\x00b",
     "a" * (TARGET_PATH_MAX_CHARS + 1)],
)
def test_unsafe_target_paths_are_refused(raw):
    with pytest.raises(GitDeliveryTargetError):
        normalize_target_path(raw)


def test_base_branch_blank_means_the_default_branch():
    assert normalize_base_branch(None) is None
    assert normalize_base_branch("   ") is None


def test_base_branch_accepts_a_fully_qualified_ref():
    assert normalize_base_branch("refs/heads/release/1.x") == "release/1.x"


def test_base_branch_must_be_a_legal_ref():
    with pytest.raises(GitDeliveryTargetError, match="not a legal branch name"):
        normalize_base_branch("bad branch")


def test_base_branch_cannot_be_an_apiome_delivery_branch():
    with pytest.raises(GitDeliveryTargetError, match="Apiome's own delivery branches"):
        normalize_base_branch("apiome/sdk-regen-1.4.2-widgets-npm")


def test_ecosystems_are_the_sdk_4_1_layouts():
    assert normalize_ecosystem(" NPM ") == "npm"
    assert normalize_ecosystem("pypi") == "pypi"
    with pytest.raises(GitDeliveryTargetError, match="SDK-4.1 package layout"):
        normalize_ecosystem("gomod")


@pytest.mark.parametrize(
    "full_name, expected",
    [("acme/widgets-sdk", ("acme", "widgets-sdk")), ("a-b/c.d_e", ("a-b", "c.d_e"))],
)
def test_repository_full_names_parse(full_name, expected):
    assert parse_repository_full_name(full_name) == expected


@pytest.mark.parametrize("full_name", [None, "", "acme", "acme/", "/repo", "a/b/c", "-acme/x"])
def test_malformed_repository_full_names_are_refused(full_name):
    with pytest.raises(ValueError):
        parse_repository_full_name(full_name)


# --------------------------------------------------------------------------------------------
# Repository eligibility — "no new credential type"
# --------------------------------------------------------------------------------------------
def test_a_linked_github_repository_is_eligible():
    assert repository_problem(_repository()) is None


def test_a_missing_repository_is_named():
    problem = repository_problem(None, _REPOSITORY)
    assert problem.code == "sdk-git-delivery-repository-missing"
    assert _REPOSITORY in problem.message


def test_a_repository_on_another_provider_is_refused_with_the_reason():
    problem = repository_problem(_repository(provider="gitlab"))
    assert problem.code == "sdk-git-delivery-provider-unsupported"
    assert "gitlab" in problem.message


def test_a_public_url_repository_holds_no_credential_and_is_refused():
    problem = repository_problem(_repository(source="public_url", linked_account_id=None))
    assert problem.code == "sdk-git-delivery-repository-unlinked"
    assert "linked GitHub account" in problem.message


def test_a_repository_without_an_owner_repo_name_is_refused():
    problem = repository_problem(_repository(repository_full_name="not a name"))
    assert problem.code == "sdk-git-delivery-repository-invalid"


# --------------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------------
def test_saving_a_target_validates_every_field_at_once():
    with patch("app.sdk_git_delivery_targets.db.get_tenant_repository") as lookup, pytest.raises(
        GitDeliveryTargetError
    ) as raised:
        save_target(
            _TENANT,
            _PROJECT,
            ecosystem="gomod",
            repository_id="not-a-uuid",
            base_branch="bad branch",
            target_path="../x",
        )
    assert len(raised.value.errors) == 4
    assert raised.value.code is None
    lookup.assert_not_called()


def test_saving_a_target_refuses_an_ineligible_repository_with_its_code():
    with patch(
        "app.sdk_git_delivery_targets.db.get_tenant_repository",
        return_value=_repository(linked_account_id=None),
    ), patch("app.sdk_git_delivery_targets.db.upsert_sdk_git_delivery_target") as upsert, pytest.raises(
        GitDeliveryTargetError
    ) as raised:
        save_target(_TENANT, _PROJECT, ecosystem="npm", repository_id=_REPOSITORY)
    assert raised.value.code == "sdk-git-delivery-repository-unlinked"
    upsert.assert_not_called()


def test_saving_a_target_stores_normalised_fields():
    with patch(
        "app.sdk_git_delivery_targets.db.get_tenant_repository", return_value=_repository()
    ) as lookup, patch(
        "app.sdk_git_delivery_targets.db.upsert_sdk_git_delivery_target",
        return_value=_target_row(base_branch="develop"),
    ) as upsert:
        stored = save_target(
            _TENANT,
            _PROJECT,
            ecosystem="NPM",
            repository_id=_REPOSITORY,
            base_branch="refs/heads/develop",
            target_path="/sdks/ts/",
            project_slug="widgets",
            actor_id="actor",
        )
    lookup.assert_called_once_with(_TENANT, _REPOSITORY)
    assert upsert.call_args.kwargs == {
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "ecosystem": "npm",
        "repository_id": _REPOSITORY,
        "base_branch": "develop",
        "target_path": "sdks/ts",
        "actor_id": "actor",
    }
    assert stored.schema_version == GIT_DELIVERY_TARGET_SCHEMA_VERSION
    assert stored.deliverable is True and stored.problem is None
    assert stored.branch_pattern == "apiome/sdk-regen-{version}-widgets-npm"


def test_a_listed_target_whose_repository_was_removed_is_not_deliverable():
    removed = _target_row(
        repository_full_name=None,
        repository_provider=None,
        repository_source=None,
        repository_has_linked_account=None,
    )
    with patch("app.sdk_git_delivery_targets.db.list_sdk_git_delivery_targets", return_value=[removed]):
        [target] = list_targets(_TENANT, _PROJECT, project_slug="widgets")
    assert target.deliverable is False
    assert target.problem["code"] == "sdk-git-delivery-repository-missing"


def test_a_listed_target_whose_repository_lost_its_linked_account_says_so():
    unlinked = _target_row(repository_has_linked_account=False)
    with patch("app.sdk_git_delivery_targets.db.list_sdk_git_delivery_targets", return_value=[unlinked]):
        [target] = list_targets(_TENANT, _PROJECT)
    assert target.problem["code"] == "sdk-git-delivery-repository-unlinked"


def test_listing_survives_a_store_fault():
    with patch(
        "app.sdk_git_delivery_targets.db.list_sdk_git_delivery_targets", side_effect=RuntimeError("down")
    ):
        assert list_targets(_TENANT, _PROJECT) == []


def test_deleting_a_target_reports_whether_one_existed():
    with patch("app.sdk_git_delivery_targets.db.delete_sdk_git_delivery_target", return_value=1) as delete:
        assert delete_target(_TENANT, _PROJECT, " PyPI ") is True
    delete.assert_called_once_with(_TENANT, _PROJECT, "pypi")
    with patch("app.sdk_git_delivery_targets.db.delete_sdk_git_delivery_target", return_value=0):
        assert delete_target(_TENANT, _PROJECT, "npm") is False


def test_resolving_a_target_projects_the_row():
    with patch("app.sdk_git_delivery_targets.db.get_sdk_git_delivery_target", return_value=_target_row()):
        target = resolve_target(_TENANT, _PROJECT, "npm")
    assert (target.target_id, target.repository_id, target.target_path) == (_TARGET, _REPOSITORY, "sdks/ts")
    assert target.base_branch is None
    with patch("app.sdk_git_delivery_targets.db.get_sdk_git_delivery_target", return_value=None):
        assert resolve_target(_TENANT, _PROJECT, "npm") is None
