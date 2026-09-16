"""The pure half of branch-to-draft binding — GNC-2.1 (#4737).

:mod:`app.draft_bindings` holds no database handle and no HTTP client, so the digest, the ref and
path normalisation, and the browse-URL construction are all asserted against literals. The digest
matters most: it is what a later ref update is compared against, so every way a repository's source
can change has to change it.
"""

from __future__ import annotations

import pytest

from app.draft_bindings import (
    CANDIDATE_ORIGINS,
    CANDIDATE_STATUSES,
    PROVIDERS,
    RELEASE_REASONS,
    DraftBindingCreate,
    DraftBindingValidationError,
    SyncCandidateResolve,
    browse_url,
    normalize_path,
    normalize_ref,
    normalize_repo_full_name,
    source_digest,
)

# ---------------------------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------------------------


def test_the_digest_is_stable_and_prefixed():
    members = {"openapi.yaml": "openapi: 3.1.0\n", "common/types.yaml": "type: object\n"}
    first = source_digest(members)
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64
    assert first == source_digest(dict(reversed(list(members.items()))))


def test_the_digest_ignores_nothing_a_repository_can_change():
    base = {"a.yaml": "one", "b.yaml": "two"}
    edited = {"a.yaml": "one!", "b.yaml": "two"}
    renamed = {"a.yaml": "one", "c.yaml": "two"}
    # Moving content between two files keeps every byte and changes the selection all the same.
    moved = {"a.yaml": "onetwo", "b.yaml": ""}
    added = {"a.yaml": "one", "b.yaml": "two", "c.yaml": ""}
    digests = {source_digest(members) for members in (base, edited, renamed, moved, added)}
    assert len(digests) == 5


def test_an_empty_selection_has_its_own_digest():
    assert source_digest({}) != source_digest({"a.yaml": ""})


# ---------------------------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("refs/heads/main", "main"),
        ("refs/heads/feature/pets", "feature/pets"),
        ("refs/tags/v1.2.0", "v1.2.0"),
        ("  main  ", "main"),
        ("/main/", "main"),
        (None, ""),
        # Only the leading prefix is a ref namespace; a branch really called this keeps its name.
        ("refs/heads/refs/heads/odd", "refs/heads/odd"),
    ],
)
def test_a_ref_is_stored_in_its_short_form(raw, expected):
    assert normalize_ref(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("/protos/", "protos"), ("  spec/openapi.yaml ", "spec/openapi.yaml"), ("", ""), (None, "")],
)
def test_a_path_is_stored_without_surrounding_slashes(raw, expected):
    assert normalize_path(raw) == expected


def test_a_repository_full_name_is_lowercased_for_delivery_matching():
    assert normalize_repo_full_name("Acme", "Specs") == "acme/specs"


# ---------------------------------------------------------------------------------------------
# Browse URL
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("github", "https://host/acme/specs/tree/abc123/protos"),
        ("gitlab", "https://host/acme/specs/-/tree/abc123/protos"),
        ("bitbucket", "https://host/acme/specs/src/abc123/protos"),
    ],
)
def test_each_provider_browses_its_own_way(provider, expected):
    assert browse_url(provider, "https://host/acme/specs/", "abc123", "protos") == expected


def test_a_glob_browses_to_the_directory_it_starts_in():
    assert (
        browse_url("github", "https://host/acme/specs", "abc123", "protos/**/*.proto")
        == "https://host/acme/specs/tree/abc123/protos"
    )


def test_an_unreadable_binding_has_no_browse_url():
    assert browse_url("gerrit", "https://host/acme/specs", "abc123", "") is None
    assert browse_url("github", "", "abc123", "") is None
    assert browse_url("github", "https://host/acme/specs", "", "") is None


# ---------------------------------------------------------------------------------------------
# Vocabulary and models
# ---------------------------------------------------------------------------------------------


def test_the_vocabulary_matches_what_the_migration_checks_allow():
    assert PROVIDERS == ("github", "gitlab", "bitbucket")
    assert RELEASE_REASONS == ("replaced", "unbound", "repository_removed")
    assert CANDIDATE_ORIGINS == ("webhook", "manual", "sweep")
    assert CANDIDATE_STATUSES == ("pending", "applied", "dismissed", "superseded")


def test_a_bind_request_refuses_unknown_fields_and_defaults_to_not_replacing():
    request = DraftBindingCreate(repo_url="https://github.com/acme/specs")
    assert request.replace is False
    assert request.path == ""
    with pytest.raises(ValueError):
        DraftBindingCreate(repo_url="https://github.com/acme/specs", token="ghp_secret")


def test_a_candidate_can_only_be_settled_as_applied_or_dismissed():
    assert SyncCandidateResolve(status="applied").note is None
    with pytest.raises(ValueError):
        SyncCandidateResolve(status="superseded")
    with pytest.raises(ValueError):
        SyncCandidateResolve(status="pending")


def test_a_refusal_carries_its_code():
    error = DraftBindingValidationError("binding-not-found", "nope")
    assert error.code == "binding-not-found"
    assert str(error) == "nope"
