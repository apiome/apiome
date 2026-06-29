"""Version-on-change + date/time tagging for canonical artifacts — MFI-3.4 (#3745).

Each imported artifact should get a dated version **only when its fingerprint
changes**: re-importing an unchanged document must not mint a new version, while a
real change must produce one dated version plus the diff that explains it. The MCP
catalog already solved this for discovered MCP endpoints (V2-MCP-18.3 / MCAT-4.3
version-on-change and V2-MCP-18.4 / MCAT-4.4 date/time tagging, in
:func:`app.mcp_discovery_engine._persist_outcome` /
:meth:`app.database.Database.record_mcp_discovery_version`). This module lifts that
*decision* out of the MCP-specific path and generalizes it over the canonical model,
so every importable format (REST / RPC / event / graph / data-schema) gets the same
behavior for free — **no new mechanism**, just the proven recipe applied to
:class:`~app.canonical_model.CanonicalApi`.

It composes the three EPIC-3 primitives already in place:

* **fingerprint** (MFI-3.1, :func:`app.fingerprint.fingerprint`) — the stable
  semantic hash that *identifies* a revision. Two imports of the same document
  fingerprint identically, so an unchanged re-import is detected by string equality
  against the previously stored fingerprint — exactly the MCP
  ``previous.surface_fingerprint == fingerprint`` test, but over the canonical model.
* **diff** (MFI-3.2, :func:`app.diff.diff`) — when the fingerprint *did* change and
  the previous model is available, the structured before→after diff that a new
  version carries (the MCP ``mcp_version_changes`` rows, generalized).
* **date/time tag** — a compact, minute-precision UTC tag such as
  ``2026-06-26T14:03Z`` derived from the import time, with the same ``-N`` collision
  suffix the MCP tagger uses (:func:`app.database.format_mcp_version_tag` /
  ``Database._next_mcp_version_tag``) so two material changes within one minute still
  get distinct, per-artifact-unique tags.

The output is a :class:`VersionDecision`: whether to **create** a new version or
**skip** (unchanged), the freshly computed :class:`~app.fingerprint.FingerprintResult`,
the minted ``version_tag`` (on create), the ``current_version_tag`` the artifact
should point at afterward (the new tag on a change, the unchanged previous tag on a
skip — mirroring how ``mcp_endpoints.current_version_id`` is advanced only on change),
and the :class:`~app.diff.ModelDiff` to persist alongside the new version.

The module is **pure**: no DB, no network, no clock read. The caller supplies the
previously recorded version (fingerprint + tag, and optionally the previous model for
the diff), the import timestamp, and the set of already-used tags; it gets back a
plain decision it can act on. That keeps version-on-change unit-testable the same way
the sibling fingerprint/diff/breaking-change modules are, and lets the persistence
wiring (the per-format catalog write, MFI-2.2 and the format epics) reuse one
audited decision instead of re-deriving it per format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .diff import ModelDiff, diff
from .fingerprint import FingerprintResult, fingerprint

__all__ = [
    "VERSION_TAG_FORMAT",
    "format_version_tag",
    "mint_version_tag",
    "VersionAction",
    "PreviousVersion",
    "VersionDecision",
    "decide_version",
]


# ``strftime`` pattern for a minute-precision UTC date/time tag, e.g. ``2026-06-26T14:03Z``.
# Identical to the MCP tagger's format (``app.database.format_mcp_version_tag``); kept here
# verbatim rather than imported so this module stays free of the heavy ``database`` import
# (and the DB session it pulls in) — the value is the contract, not the call site.
VERSION_TAG_FORMAT = "%Y-%m-%dT%H:%MZ"


def format_version_tag(when: datetime) -> str:
    """Return the human-readable UTC date/time tag for a version minted at ``when``.

    Produces a compact, minute-precision ISO-8601-style label such as
    ``2026-06-26T14:03Z``. A naive ``when`` is treated as already-UTC; an aware one is
    converted to UTC, so the tag is stable and comparable regardless of the caller's
    timezone. This is the generalized form of
    :func:`app.database.format_mcp_version_tag`.

    Args:
        when: The moment the version is recorded (the import time).

    Returns:
        The minute-precision UTC tag, e.g. ``"2026-06-26T14:03Z"``.
    """
    aware = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime(VERSION_TAG_FORMAT)


def mint_version_tag(when: datetime, existing_tags: Iterable[str] = ()) -> str:
    """Return a per-artifact-unique date/time tag for a version minted at ``when``.

    The base tag is :func:`format_version_tag`. When two material changes land within
    the same minute, the base would collide, so the second and subsequent tags get a
    ``-2`` / ``-3`` / … suffix — the lowest free ordinal — exactly as the MCP tagger's
    ``Database._next_mcp_version_tag`` disambiguates same-minute snapshots. This keeps
    every tag distinct and human-readable without changing the minute-precision format.

    Args:
        when: The moment the version is recorded.
        existing_tags: The tags already used for this artifact (any iterable). Order is
            irrelevant; membership is all that matters.

    Returns:
        The base tag when it is free, else ``"<base>-<n>"`` for the lowest free ``n``
        starting at ``2``.
    """
    base = format_version_tag(when)
    taken = set(existing_tags)
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


class VersionAction(str, Enum):
    """What an import should do with respect to versioning.

    * :attr:`CREATE` — the artifact is new, or its fingerprint changed: record a new
      dated version (and, when a previous model is available, its diff).
    * :attr:`SKIP` — the fingerprint matches the current version: record nothing; the
      ``current_version`` pointer is left where it is.
    """

    CREATE = "create"
    SKIP = "skip"


class PreviousVersion(BaseModel):
    """The currently-recorded version of an artifact, as the decision input.

    A caller assembles this from the artifact's latest ``versions`` row (its stored
    fingerprint and date/time tag) before importing again. The previous ``model`` is
    optional: the fingerprint alone is enough to decide *whether* anything changed
    (the MCP test compares only stored fingerprints), but supplying the model lets the
    decision also compute the before→after :class:`~app.diff.ModelDiff` that a new
    version carries.
    """

    model_config = ConfigDict(frozen=True)

    version_tag: str = Field(
        description="The current version's date/time tag, e.g. ``2026-06-26T14:03Z``.",
    )
    fingerprint: str = Field(
        description="The current version's stored semantic fingerprint "
        "(``FingerprintResult.fingerprint``) to compare the re-import against.",
    )
    model: Optional[CanonicalApi] = Field(
        default=None,
        description="The current version's canonical model, when loaded; enables the "
        "before→after diff on a change. Omit to decide on fingerprint alone.",
    )


class VersionDecision(BaseModel):
    """The outcome of a version-on-change evaluation for one import.

    Carries everything the persistence layer needs to act: whether to create a version
    (:attr:`action` / :attr:`changed`), the freshly computed fingerprints to store
    (:attr:`fingerprint`), the date/time tag to stamp on the new version
    (:attr:`version_tag`), the diff to persist beside it (:attr:`diff`), and the tag
    the artifact's ``current_version`` should point at afterward
    (:attr:`current_version_tag`).
    """

    action: VersionAction = Field(description="Create a new version, or skip.")
    changed: bool = Field(
        description="Whether the import differs from the current version. ``True`` for "
        "the very first import (there is nothing to match), and whenever the "
        "fingerprint changed; ``False`` only when re-importing an unchanged document.",
    )
    is_initial: bool = Field(
        description="Whether this is the artifact's first version (no previous).",
    )
    fingerprint: FingerprintResult = Field(
        description="The new import's fingerprints (semantic + any per-format hash).",
    )
    previous_fingerprint: Optional[str] = Field(
        default=None,
        description="The current version's fingerprint the import was compared against; "
        "``None`` on the initial import.",
    )
    version_tag: Optional[str] = Field(
        default=None,
        description="The date/time tag minted for the new version; ``None`` on a skip.",
    )
    current_version_tag: Optional[str] = Field(
        default=None,
        description="The tag the artifact's ``current_version`` should point at after "
        "this import — the new tag on a change, the unchanged previous tag on a skip.",
    )
    diff: Optional[ModelDiff] = Field(
        default=None,
        description="The before→after diff for the new version, present on a change "
        "when the previous model was supplied; ``None`` on a skip or initial import.",
    )

    @property
    def created(self) -> bool:
        """Whether this decision creates a new version (sugar over :attr:`action`)."""
        return self.action is VersionAction.CREATE


def decide_version(
    model: CanonicalApi,
    *,
    previous: Optional[PreviousVersion] = None,
    when: datetime,
    existing_tags: Iterable[str] = (),
) -> VersionDecision:
    """Decide whether re-importing ``model`` should mint a new dated version.

    The generalized MCP version-on-change rule, over the canonical model:

    #. Fingerprint ``model`` (MFI-3.1) — the stable semantic identity of this revision.
    #. If there is no ``previous`` version, this is the artifact's first import: always
       :attr:`VersionAction.CREATE` a version (no diff — there is nothing to compare).
    #. Else compare the new semantic fingerprint to ``previous.fingerprint``. Equal →
       :attr:`VersionAction.SKIP` (an unchanged re-import mints nothing and leaves
       ``current_version`` where it is). Different → :attr:`VersionAction.CREATE` a new
       dated version, and — when ``previous.model`` was supplied — its before→after
       :class:`~app.diff.ModelDiff`.

    Every created version is stamped with a per-artifact-unique date/time
    :attr:`~VersionDecision.version_tag` (:func:`mint_version_tag`), and the decision
    reports the :attr:`~VersionDecision.current_version_tag` the artifact should point
    at afterward.

    Args:
        model: The freshly normalized canonical model being imported.
        previous: The artifact's current version (fingerprint + tag, optionally model),
            or ``None`` for a first import.
        when: The import timestamp used to mint the date/time tag (passed in so the
            decision stays pure and deterministic — no clock read here).
        existing_tags: Tags already used for this artifact, so a same-minute change gets
            a ``-N`` suffix instead of colliding. The ``previous.version_tag`` need not
            be included; it is always considered taken.

    Returns:
        A :class:`VersionDecision` describing the action, fingerprints, minted tag,
        current-version pointer, and (on a change with a previous model) the diff.
    """
    new_fingerprint = fingerprint(model)

    # First import: nothing to compare against, so always create — but there is no
    # prior revision to diff, so the new version carries no diff.
    if previous is None:
        version_tag = mint_version_tag(when, existing_tags)
        return VersionDecision(
            action=VersionAction.CREATE,
            changed=True,
            is_initial=True,
            fingerprint=new_fingerprint,
            previous_fingerprint=None,
            version_tag=version_tag,
            current_version_tag=version_tag,
            diff=None,
        )

    # Unchanged re-import: the semantic fingerprint matches the current version, so no
    # new version is minted and the current-version pointer is left untouched.
    if new_fingerprint.fingerprint == previous.fingerprint:
        return VersionDecision(
            action=VersionAction.SKIP,
            changed=False,
            is_initial=False,
            fingerprint=new_fingerprint,
            previous_fingerprint=previous.fingerprint,
            version_tag=None,
            current_version_tag=previous.version_tag,
            diff=None,
        )

    # Changed: mint a new dated version (its tag must not collide with the previous
    # one) and, when the previous model is loaded, the before→after diff it carries.
    taken: List[str] = [previous.version_tag, *existing_tags]
    version_tag = mint_version_tag(when, taken)
    model_diff = diff(previous.model, model) if previous.model is not None else None
    return VersionDecision(
        action=VersionAction.CREATE,
        changed=True,
        is_initial=False,
        fingerprint=new_fingerprint,
        previous_fingerprint=previous.fingerprint,
        version_tag=version_tag,
        current_version_tag=version_tag,
        diff=model_diff,
    )
