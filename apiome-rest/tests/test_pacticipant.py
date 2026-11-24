"""The pacticipant registry's vocabulary — PFX-1.1 (#6914).

Pure checks of :mod:`app.pacticipant`: every validator mirrors a V432 constraint, so what is
asserted here is that the API refuses what the database would refuse, with a stable code.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.pacticipant import (
    CODE_INVALID_BRANCH,
    CODE_INVALID_NAME,
    CODE_INVALID_SLUG,
    CODE_INVALID_TAG,
    CODE_INVALID_URL,
    CODE_INVALID_VERSION,
    MAX_LABEL_LENGTH,
    MAX_TAGS_PER_REQUEST,
    MAX_URL_LENGTH,
    PacticipantInput,
    PacticipantPatch,
    PacticipantValidationError,
    PacticipantVersionInput,
    branch_record_from_row,
    pacticipant_record_from_row,
    slugify_pacticipant_name,
    validate_branch,
    validate_name,
    validate_slug,
    validate_tag,
    validate_tags,
    validate_url,
    validate_version_number,
    version_record_from_row,
)


def _code(call, *args, **kwargs) -> str:
    """The refusal code ``call`` raises."""
    with pytest.raises(PacticipantValidationError) as caught:
        call(*args, **kwargs)
    return caught.value.code


# ---------------------------------------------------------------------------------------------
# Handles and names
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Billing Service", "billing-service"),
        ("  Example_App.v2  ", "example-app-v2"),
        ("billing-service", "billing-service"),
        ("!!!", ""),
    ],
)
def test_a_handle_is_derived_from_the_name(name: str, slug: str) -> None:
    assert slugify_pacticipant_name(name) == slug


def test_a_valid_slug_is_normalized() -> None:
    assert validate_slug("  Billing-Service ") == "billing-service"
    assert validate_slug("a") == "a"
    assert validate_slug("a" * 128) == "a" * 128


@pytest.mark.parametrize("slug", ["", "  ", "-billing", "billing-", "billing service", "a/b", "a" * 129, "ünï"])
def test_a_malformed_slug_is_refused(slug: str) -> None:
    assert _code(validate_slug, slug) == CODE_INVALID_SLUG


def test_a_name_is_trimmed_and_bounded() -> None:
    assert validate_name("  Billing Service ") == "Billing Service"
    assert validate_name("x" * MAX_LABEL_LENGTH) == "x" * MAX_LABEL_LENGTH
    assert _code(validate_name, "   ") == CODE_INVALID_NAME
    assert _code(validate_name, "x" * (MAX_LABEL_LENGTH + 1)) == CODE_INVALID_NAME


# ---------------------------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------------------------


def test_a_url_is_http_or_https() -> None:
    assert validate_url(" https://ci.example.com/builds/1 ", what="build URL") == "https://ci.example.com/builds/1"
    assert validate_url("HTTP://example.com", what="build URL") == "HTTP://example.com"
    assert validate_url(None, what="build URL") is None
    assert validate_url("   ", what="build URL") is None


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com", "javascript:alert(1)", "example.com", "https://exa mple.com", "https://"],
)
def test_a_url_that_is_not_http_is_refused(url: str) -> None:
    assert _code(validate_url, url, what="repository URL") == CODE_INVALID_URL


def test_a_url_is_bounded() -> None:
    assert _code(validate_url, "https://e.com/" + "a" * MAX_URL_LENGTH, what="build URL") == CODE_INVALID_URL


# ---------------------------------------------------------------------------------------------
# Version numbers, branches and tags
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("validate", "code"),
    [
        (validate_version_number, CODE_INVALID_VERSION),
        (validate_branch, CODE_INVALID_BRANCH),
        (validate_tag, CODE_INVALID_TAG),
    ],
)
def test_a_label_is_stored_exactly_or_refused(validate, code: str) -> None:
    # Kept as sent: case, dots, plus signs and slashes are all meaningful to the build.
    for value in ("1.2.3", "3f2a9c1e+build.7", "Feat/New-Invoice", "x" * MAX_LABEL_LENGTH):
        assert validate(value) == value
    # Refused rather than silently repaired.
    for value in ("", None, " 1.2.3", "1.2.3 ", "1.2\n.3", "a\x00b", "x" * (MAX_LABEL_LENGTH + 1)):
        assert _code(validate, value) == code


def test_tags_are_deduplicated_in_first_seen_order() -> None:
    assert validate_tags(["prod", "eu", "prod"]) == ["prod", "eu"]
    assert validate_tags(None) == []


def test_one_bad_tag_refuses_the_request() -> None:
    assert _code(validate_tags, ["prod", " padded"]) == CODE_INVALID_TAG


def test_a_request_carries_a_bounded_number_of_tags() -> None:
    assert len(validate_tags([f"t{i}" for i in range(MAX_TAGS_PER_REQUEST)])) == MAX_TAGS_PER_REQUEST
    assert _code(validate_tags, [f"t{i}" for i in range(MAX_TAGS_PER_REQUEST + 1)]) == CODE_INVALID_TAG


# ---------------------------------------------------------------------------------------------
# Bodies and records
# ---------------------------------------------------------------------------------------------


def test_request_bodies_refuse_unknown_fields() -> None:
    for model, payload in (
        (PacticipantInput, {"name": "A", "tenant_id": "x"}),
        (PacticipantPatch, {"slug": "renamed"}),
        (PacticipantVersionInput, {"number": "1"}),
    ):
        with pytest.raises(ValueError):
            model(**payload)


def test_a_patch_tells_an_omitted_field_from_a_cleared_one() -> None:
    assert PacticipantPatch().model_fields_set == set()
    assert PacticipantPatch(project=None).model_fields_set == {"project"}


def test_rows_are_adapted_into_records() -> None:
    when = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    pacticipant = pacticipant_record_from_row(
        {
            "id": "p1",
            "tenant_id": "t1",
            "slug": "billing-service",
            "name": "Billing Service",
            "project_id": None,
            "consumer_id": "c1",
            "created_at": when,
        }
    )
    assert pacticipant.project_id is None and pacticipant.consumer_id == "c1"
    assert pacticipant.created_at == when.isoformat()

    version = version_record_from_row(
        {"id": "v1", "pacticipant_id": "p1", "number": "1.0.0", "seq": 7, "branches": ["main"], "tags": None}
    )
    assert (version.seq, version.branches, version.tags) == (7, ["main"], [])

    branch = branch_record_from_row(
        {
            "id": "b1",
            "pacticipant_id": "p1",
            "name": "main",
            "head_version_id": "v1",
            "head_version": "1.0.0",
            "is_main": True,
        }
    )
    assert branch.head_version == "1.0.0" and branch.is_main is True
