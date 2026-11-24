"""The generated table on *Pact Broker compatibility* — PFX-1.8 (#6921).

The first test is the drift gate: it renders the table from the catalog and compares the committed
page with it, so a catalog change not followed by ``scripts/generate_pact_broker_compat_doc.py``
turns CI red. The rest check the table says what the catalog says, and that rewriting the region
leaves the hand-written prose alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pact_broker_compat import COMPATIBILITY_PAGE, ENDPOINTS, GROUPS, PACT_BROKER_VERSION, issue_url
from app.pact_broker_compat_doc import (
    BEGIN_MARKER,
    END_MARKER,
    REGENERATE_COMMAND,
    apply_compat_table,
    render_compat_table,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_PATH = REPO_ROOT / COMPATIBILITY_PAGE


@pytest.fixture(scope="module")
def page() -> str:
    """The committed page's text."""
    assert PAGE_PATH.is_file(), f"missing guide page: {PAGE_PATH}"
    return PAGE_PATH.read_text(encoding="utf-8")


def test_the_committed_table_matches_the_catalog(page: str) -> None:
    assert apply_compat_table(page) == page, f"Regenerate the table: {REGENERATE_COMMAND}"


def test_every_endpoint_has_one_row_under_its_section() -> None:
    table = render_compat_table()
    for endpoint in ENDPOINTS:
        assert table.count(f"| `{endpoint.path or '/'}` — ") == 1, endpoint.path
    positions = [table.index(f"### {group}") for group in GROUPS]
    assert positions == sorted(positions)


def test_the_table_names_the_broker_version_and_links_every_tracking_issue() -> None:
    table = render_compat_table()
    assert f"Pact Broker **{PACT_BROKER_VERSION}**" in table
    for endpoint in ENDPOINTS:
        if endpoint.tracking:
            assert issue_url(endpoint.tracking) in table


def test_no_cell_breaks_the_table_or_mdx() -> None:
    for line in render_compat_table().splitlines():
        if line.startswith("| `"):
            assert line.count(" | ") == 4, line
            # Braces outside inline code would be read as an MDX expression.
            outside_code = "".join(part for index, part in enumerate(line.split("`")) if index % 2 == 0)
            assert "{" not in outside_code and "}" not in outside_code, line


def test_only_the_generated_region_is_rewritten() -> None:
    text = f"intro\n\n{BEGIN_MARKER}\nstale\n{END_MARKER}\n\noutro\n"
    rewritten = apply_compat_table(text)
    assert rewritten.startswith("intro\n\n") and rewritten.endswith("\n\noutro\n")
    assert "stale" not in rewritten


def test_a_page_without_both_markers_is_refused() -> None:
    with pytest.raises(ValueError):
        apply_compat_table("no markers here")
    with pytest.raises(ValueError):
        apply_compat_table(f"{BEGIN_MARKER}\n{BEGIN_MARKER}\n{END_MARKER}")
