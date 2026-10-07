"""Docs-site paths, URLs and front matter (DOCS-1.2, #5619)."""

from pathlib import Path

import pytest
import yaml

from app.axis_score import ALGORITHM_DOCS_PAGE
from app.docs_site import (
    DOCS_SITE_PAGES_ROOT,
    DOCS_SITE_URL,
    guide_page,
    render_front_matter,
    site_url,
)
from app.format_counts import MARKED_DOCUMENTS
from app.lint_rule_registry import LINT_RULE_DOCS_PAGE
from app.scanner_rule_transparency import (
    BLOCKING_RULES,
    MCP_CONFORMANCE_RULES_DOCS_PAGE,
    MCP_POSTURE_RULES_DOCS_PAGE,
    MCP_SURFACE_RULES_DOCS_PAGE,
    POLICY_DOCS_PAGE,
)
from app.supported_formats_doc import SUPPORTED_FORMATS_DOCS_PAGE

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_guide_page_builds_a_site_source_path() -> None:
    assert guide_page("build", "lint-rules") == "apiome-docs/docs/build/lint-rules.md"
    assert guide_page("/ship/mocks/", "mock-callbacks") == ("apiome-docs/docs/ship/mocks/mock-callbacks.md")


def test_site_url_drops_the_root_and_extension() -> None:
    page = guide_page("build", "lint-rules")
    assert site_url(page) == f"{DOCS_SITE_URL}build/lint-rules"
    assert site_url(page, "naming-schema-pascal-case") == (
        "https://apiome.github.io/apiome/build/lint-rules#naming-schema-pascal-case"
    )


def test_site_url_rejects_a_path_outside_the_site() -> None:
    with pytest.raises(ValueError):
        site_url("docs/guide/lint-rules.md")


def test_front_matter_is_valid_yaml_with_every_field() -> None:
    block = render_front_matter('Say "hi": a title', "Short description.", 4, ["lint", "mcp"])
    assert block.startswith("---\n") and block.endswith("---\n\n")
    data = yaml.safe_load(block.strip().strip("-"))
    assert data == {
        "title": 'Say "hi": a title',
        "description": "Short description.",
        "sidebar_position": 4,
        "tags": ["lint", "mcp"],
    }


@pytest.mark.parametrize(
    "page",
    [
        LINT_RULE_DOCS_PAGE,
        ALGORITHM_DOCS_PAGE,
        POLICY_DOCS_PAGE,
        MCP_CONFORMANCE_RULES_DOCS_PAGE,
        MCP_POSTURE_RULES_DOCS_PAGE,
        MCP_SURFACE_RULES_DOCS_PAGE,
        SUPPORTED_FORMATS_DOCS_PAGE,
        *[document for document in MARKED_DOCUMENTS if document != "README.md"],
    ],
)
def test_every_docs_page_the_api_names_is_a_site_page_that_exists(page: str) -> None:
    assert page.startswith(f"{DOCS_SITE_PAGES_ROOT}/"), page
    assert (REPO_ROOT / page).is_file(), page


def test_blocking_rules_point_at_site_pages() -> None:
    for meta in BLOCKING_RULES.values():
        assert meta.docs_page.startswith(f"{DOCS_SITE_PAGES_ROOT}/"), meta.rule_id
        assert "docs/guide/" not in meta.reference, meta.rule_id
