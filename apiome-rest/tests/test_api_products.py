"""Pure rules for API products — APX-1.1 (#6098).

:mod:`app.api_products` holds the field rules (slug, name, version selector, environment), version
resolution (which version a ``project_latest`` or ``project_version`` member means today) and the
portal rule. None of it touches a database.
"""

from __future__ import annotations

import pytest

from app.api_products import (
    CODE_INVALID,
    ApiProductMember,
    ApiProductValidationError,
    normalize_environment,
    normalize_name,
    normalize_selector,
    pick_version,
    portal_blockers,
    resolve_slug,
    selector_matches,
)


def _version(label: str, published: bool, vid: str = "") -> dict:
    return {"id": vid or f"v-{label}", "label": label, "published": published}


# ---------------------------------------------------------------------------------------------
# Field rules
# ---------------------------------------------------------------------------------------------


def test_a_slug_is_derived_from_the_name_and_lowercased() -> None:
    assert resolve_slug(None, "Payments API") == "payments-api"
    assert resolve_slug("  Payments ", "ignored") == "payments"


@pytest.mark.parametrize("slug", ["-payments", "pay ments", "pay_ments", ""])
def test_a_malformed_slug_is_refused(slug: str) -> None:
    with pytest.raises(ApiProductValidationError) as caught:
        resolve_slug(slug, "Payments")
    assert caught.value.code == CODE_INVALID


def test_a_blank_name_is_refused() -> None:
    assert normalize_name("  Payments ") == "Payments"
    with pytest.raises(ApiProductValidationError):
        normalize_name("   ")


def test_a_project_version_member_needs_a_selector_and_only_it_takes_one() -> None:
    assert normalize_selector("project_version", " 2.x ") == "2.x"
    assert normalize_selector("project_latest", None) is None
    assert normalize_selector("mcp_server", "") is None
    with pytest.raises(ApiProductValidationError, match="needs a version"):
        normalize_selector("project_version", None)
    with pytest.raises(ApiProductValidationError, match="takes no version"):
        normalize_selector("project_latest", "1.0.0")
    with pytest.raises(ApiProductValidationError, match="not a version"):
        normalize_selector("project_version", "2 x")


def test_an_environment_is_a_short_lowercase_name() -> None:
    assert normalize_environment(" Production ") == "production"
    assert normalize_environment("") is None
    with pytest.raises(ApiProductValidationError):
        normalize_environment("prod env")


# ---------------------------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selector", "label", "expected"),
    [
        ("2.x", "2", True),
        ("2.x", "2.0.0", True),
        ("2.x", "2.9.1", True),
        ("2.x", "v2.1.0", True),
        ("v2.x", "2.1.0", True),
        ("2.x", "20.1.0", False),
        ("2.x", "3.0.0", False),
        ("2.1.x", "2.1.4", True),
        ("2.1.x", "2.10.0", False),
        ("1.4.0", "1.4.0", True),
        ("1.4.0", "1.4.1", False),
        ("2.x", None, False),
    ],
)
def test_a_selector_is_an_exact_label_or_a_dotted_range(selector: str, label: str, expected: bool) -> None:
    assert selector_matches(selector, label) is expected


def test_a_latest_member_follows_each_new_publish() -> None:
    versions = [_version("1.1.0", True), _version("1.0.0", True)]
    assert pick_version("project_latest", None, versions)["label"] == "1.1.0"
    # A new publish arrives newest first; the member moves with it and stores nothing.
    assert pick_version("project_latest", None, [_version("1.2.0", True), *versions])["label"] == "1.2.0"


def test_a_latest_member_skips_an_unpublished_draft() -> None:
    versions = [_version("2.0.0-draft", False), _version("1.1.0", True)]
    assert pick_version("project_latest", None, versions)["label"] == "1.1.0"


def test_a_range_member_resolves_to_the_newest_published_version_in_range() -> None:
    versions = [_version("3.0.0", True), _version("2.4.0", True), _version("2.3.0", True)]
    assert pick_version("project_version", "2.x", versions)["label"] == "2.4.0"


def test_a_member_with_nothing_published_points_at_its_newest_draft() -> None:
    chosen = pick_version("project_version", "2.x", [_version("2.1.0", False), _version("2.0.0", False)])
    assert chosen["label"] == "2.1.0" and chosen["published"] is False
    assert pick_version("project_version", "9.x", [_version("2.1.0", True)]) is None
    assert pick_version("project_latest", None, []) is None


# ---------------------------------------------------------------------------------------------
# The portal rule
# ---------------------------------------------------------------------------------------------


def _member(name: str, published: bool) -> ApiProductMember:
    return ApiProductMember(id=f"m-{name}", kind="project_latest", ref=f"r-{name}", name=name, published=published)


def test_portal_blockers_are_the_unpublished_members_in_order() -> None:
    members = [_member("payments", True), _member("refunds", False), _member("ledger", False)]
    assert portal_blockers(members) == [
        {"kind": "project_latest", "ref": "r-refunds", "name": "refunds"},
        {"kind": "project_latest", "ref": "r-ledger", "name": "ledger"},
    ]
    assert portal_blockers([_member("payments", True)]) == []
    assert portal_blockers([]) == []
