"""The orderings of the tenant-configuration lists read through ``Database`` (DBP-1.13, #7196).

Each constant spells the ``ORDER BY`` of one accessor in :mod:`app.database`; the accessor builds
its window from it and the route builds its cursors from it, so the two cannot drift apart.
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn, by_name, newest_first

__all__ = [
    "AGENT_KEYS_ORDER",
    "CONSUMERS_ORDER",
    "CONVERSIONS_BY_SOURCE_ORDER",
    "EXPORT_AUTO_SUBSCRIPTIONS_ORDER",
    "EXPORT_DELIVERY_PROFILES_ORDER",
    "EXPORT_PRESETS_ORDER",
    "EXPORT_STORAGE_CREDENTIALS_ORDER",
]

#: ``apiome.export_storage_credentials``, by name.
EXPORT_STORAGE_CREDENTIALS_ORDER = by_name("export-storage-credentials")

#: ``apiome.export_delivery_profiles``, by name.
EXPORT_DELIVERY_PROFILES_ORDER = by_name("export-delivery-profiles")

#: ``apiome.export_presets x``, by name.
EXPORT_PRESETS_ORDER = by_name("export-presets", "x.name", "x.id")

#: Auto-export subscriptions, by project name, then preset name.
EXPORT_AUTO_SUBSCRIPTIONS_ORDER = ListOrder(
    "export-auto-subscriptions",
    (
        SortColumn("p.name", "text", ("project_name",)),
        SortColumn("x.name", "text", ("preset_name",)),
        SortColumn("s.id", "uuid", ("id",)),
    ),
)

#: Agent keys (``apiome.api_keys ak``), newest first.
AGENT_KEYS_ORDER = ListOrder(
    "agent-keys",
    (
        SortColumn("ak.created_at", "time", ("created_at",), descending=True),
        SortColumn("ak.id", "uuid", ("id",)),
    ),
)

#: A project's consumers, newest first; a slug is unique within its project.
CONSUMERS_ORDER = ListOrder(
    "consumers",
    (
        SortColumn("consumer.created_at", "time", ("created_at",), descending=True),
        SortColumn("consumer.slug", "text", ("slug",)),
    ),
)

#: A catalog item's conversion-provenance history, newest first.
CONVERSIONS_BY_SOURCE_ORDER = newest_first("conversions-by-source", "cp.created_at", "cp.id")
