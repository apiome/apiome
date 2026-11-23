"""Bounds of the public Browse lists (DBP-1.13, #7196).

The tenant directory and a tenant's projects are aggregates over published versions; a project's
versions are sorted by semantic version in Python. None of them could grow without limit before
this module, and all three now read a bounded window.
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn

__all__ = [
    "BROWSE_MEMBER_PROJECTS_ORDER",
    "BROWSE_PROJECTS_ORDER",
    "BROWSE_VERSIONS_CAP",
]

#: A tenant's Browse projects, by slug (unique per tenant among live projects). The anonymous
#: and the member queries name the column differently and share one cursor.
BROWSE_PROJECTS_ORDER = ListOrder("browse-projects", (SortColumn("a.slug", "text", ("slug",)),))
BROWSE_MEMBER_PROJECTS_ORDER = ListOrder(
    "browse-projects", (SortColumn("pb.slug", "text", ("slug",)),)
)

#: The most recently published versions of one project a Browse version list considers. The
#: list is sorted by semantic version after it is read, so the read itself needs a ceiling.
BROWSE_VERSIONS_CAP = 2000
