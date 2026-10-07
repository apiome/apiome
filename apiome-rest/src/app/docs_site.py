"""Where the user guide lives, spelled once (DOCS-1.2, #5619).

The guide moved from a flat ``docs/guide/`` folder into the Docusaurus site at ``apiome-docs/``,
grouped by the job a reader is doing (Build, Bring in, Ship, Govern, Reference, …). Several
surfaces name a guide page: the ``docs_page`` fields on lint, scanner and axis payloads, the
generators that write the reference pages, and the format-count pass. They all build their paths
and front matter here, so a page that moves again moves in one place.

A ``docs_page`` value is still a **monorepo-relative path to the page's source file** — the same
contract as before the move. Clients (``apiome-ui``'s ``buildDocsHref``) turn it into a site URL;
:func:`site_url` does the same for prose that must carry an absolute link.
"""

from __future__ import annotations

import json
from typing import Sequence

__all__ = [
    "DOCS_SITE_PAGES_ROOT",
    "DOCS_SITE_URL",
    "guide_page",
    "render_front_matter",
    "site_url",
]

#: Monorepo-relative directory holding the site's pages.
DOCS_SITE_PAGES_ROOT = "apiome-docs/docs"

#: The published site. Pages are served without a trailing slash or a ``.md`` suffix.
DOCS_SITE_URL = "https://apiome.github.io/apiome/"


def guide_page(group: str, slug: str) -> str:
    """Return the monorepo-relative source path of a guide page.

    Args:
        group: Sidebar folder under ``apiome-docs/docs``, e.g. ``build`` or ``ship/mocks``.
        slug: File name without the extension, e.g. ``lint-rules``.

    Returns:
        The path, e.g. ``apiome-docs/docs/build/lint-rules.md``.
    """
    return f"{DOCS_SITE_PAGES_ROOT}/{group.strip('/')}/{slug}.md"


def site_url(page: str, anchor: str | None = None) -> str:
    """Return the published URL of a guide page.

    Args:
        page: A path returned by :func:`guide_page`.
        anchor: Optional heading anchor, without the ``#``.

    Returns:
        The absolute URL, e.g. ``https://apiome.github.io/apiome/build/lint-rules#rule-id``.

    Raises:
        ValueError: When ``page`` is not under :data:`DOCS_SITE_PAGES_ROOT`.
    """
    prefix = f"{DOCS_SITE_PAGES_ROOT}/"
    if not page.startswith(prefix):
        raise ValueError(f"{page!r} is not a docs-site page (expected {prefix}…)")
    route = page[len(prefix) :].rsplit(".", 1)[0]
    url = f"{DOCS_SITE_URL}{route}"
    return f"{url}#{anchor}" if anchor else url


def render_front_matter(title: str, description: str, sidebar_position: int, tags: Sequence[str]) -> str:
    """Render the Docusaurus front matter every guide page starts with.

    Strings are JSON-quoted, which is valid YAML and keeps a colon or quote in a title safe.

    Args:
        title: Page title (sentence case); shown as the page heading and in the sidebar.
        description: One line, 14 words or fewer (``yarn docs:check`` enforces it).
        sidebar_position: Order within the sidebar group.
        tags: Tag names for the page.

    Returns:
        The front-matter block, ending with a blank line.
    """
    return "\n".join(
        [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            f"description: {json.dumps(description, ensure_ascii=False)}",
            f"sidebar_position: {sidebar_position}",
            f"tags: [{', '.join(tags)}]",
            "---",
            "",
            "",
        ]
    )
