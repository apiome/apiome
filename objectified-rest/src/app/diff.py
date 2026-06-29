"""Compare-any-two diff over the canonical model — MFI-3.2 (#3743).

Once every importable format is normalized into the one
:class:`~app.canonical_model.CanonicalApi` shape (MFI-2.1) and fingerprinted
uniformly (MFI-3.1), "what changed between these two artifacts?" can be answered
*once*, for every paradigm, by :func:`diff`. Given any two canonical models —
``base`` (the "from" / older side) and ``target`` (the "to" / newer side) —
:func:`diff` returns a structured :class:`ModelDiff` listing every
service / operation / message / channel / type / field that was **added**,
**removed**, or **modified**, with the before/after projection of each and
add/remove/modify counts (overall and per category).

This is the canonical-model generalization of the MCP surface diff
(V2-MCP-EPIC-18.2 / 24.3, :func:`app.mcp_client.diff.diff_surfaces`) and inherits
its two defining properties:

* **Compare-any-two, not just adjacent.** The two models are compared *directly*,
  never by chaining adjacent step-diffs, so the result is exact for an arbitrarily
  distant pair (``v1`` → ``v9``) just as it is for neighbors.
* **In lock-step with change detection.** The diff is taken over exactly the
  projection the fingerprint hashes — :func:`app.fingerprint.canonical_payload`
  (order-normalized, with descriptions/titles/``raw`` scrubbed). So documentation-
  only edits and source declaration-order differences are invisible to the diff,
  and two models with the same fingerprint always produce an *empty* diff. That is
  the MFI-3.2 acceptance criterion ("identical models → empty diff") by
  construction.

**Identity / stable keys.** Entities are paired across the two models by the
stable ``key`` every canonical entity carries (``GET /pets/{id}``, ``Pet.id``,
``user/signedup``, …). Pairing by key, not by position, is what makes a rename read
as remove + add while an in-place edit reads as a single modify — and what lets the
diff line up two versions whose sources ordered their paths/types differently.

**Flat, globally-keyed categories.** Operations live under services, messages under
operations, and fields under record types, but their keys are globally unique within
the model, so the diff flattens each category and pairs it independently. Removing a
whole service therefore surfaces the service *and* each of its operations/messages as
separate ``removed`` entries — a faithful, non-double-counted account of everything
that left (an entity is reported at exactly one category). An entity counts as
``modified`` only when its *own* attributes change: a type whose only change is a new
field is **not** itself "modified" (the field is reported as an ``added`` field), so
parent and child changes are never conflated.

**Per-format enrichment hook.** Some formats can describe a change better than the
structural category does (GraphQL "field became non-null", Avro "default added",
protobuf "field number reused"). A format epic registers a :class:`DiffLabeler`
under its format key (mirroring the normalizer and fingerprint-hasher registries);
:func:`diff` then asks it for a human-readable :attr:`EntityChange.label` per change.
Labeling is purely additive — it never changes which entities are reported.

The module is **pure**: no DB, no network. It takes two in-memory models and returns
a JSON-serializable :class:`ModelDiff`, cheap to call anywhere (version roll, compare
API, CLI) and trivially deterministic — changes are emitted in a fixed
(category, key) order, so the same pair of models always yields identical output.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field

from .canonical_model import CanonicalApi
from .fingerprint import canonical_fingerprint, canonical_payload

__all__ = [
    "ChangeKind",
    "EntityCategory",
    "FieldChange",
    "EntityChange",
    "DiffCounts",
    "ModelDiff",
    "diff",
    "DiffLabeler",
    "register_diff_labeler",
    "get_diff_labeler",
    "available_diff_formats",
]


class ChangeKind(str, Enum):
    """The direction of a single change, relative to ``base`` → ``target``.

    Mirrors the MCP diff's three directions (and ``mcp_version_changes.change_type``):
    an entity present only in ``target`` is :attr:`ADDED`, present only in ``base`` is
    :attr:`REMOVED`, and present in both with a differing self-projection is
    :attr:`MODIFIED`.
    """

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class EntityCategory(str, Enum):
    """Which canonical collection a change belongs to.

    These are exactly the load-bearing, stably-keyed entity kinds the diff reports
    over. Operations are flattened across all services, messages across all
    operations, and fields across all record types — each keyed globally.
    Order-meaningful or entity-internal members that are *not* separately keyed
    (a type's ``enum_values``/``union_members``, an operation's ``parameters``, a
    message's ``headers``, a channel's address ``parameters``) are compared as part
    of their owner's self-projection rather than as their own category.
    """

    SERVICE = "service"
    OPERATION = "operation"
    MESSAGE = "message"
    CHANNEL = "channel"
    TYPE = "type"
    FIELD = "field"


# Deterministic emission order of changes by category: the artifact's structural
# spine first (services → operations → messages), then channels, then the type
# system (types → fields). Within a category, changes sort by ``key``.
_CATEGORY_RANK: Dict[EntityCategory, int] = {
    EntityCategory.SERVICE: 0,
    EntityCategory.OPERATION: 1,
    EntityCategory.MESSAGE: 2,
    EntityCategory.CHANNEL: 3,
    EntityCategory.TYPE: 4,
    EntityCategory.FIELD: 5,
}


class FieldChange(BaseModel):
    """One attribute that differs between a ``modified`` entity's before and after.

    Emitted only for :attr:`ChangeKind.MODIFIED` entities — one per attribute of the
    entity's *self-projection* whose canonical value changed (for example ``kind``,
    ``http_method``, ``type``, ``constraints``, ``default``, ``parameters``). The name
    is the canonical-model attribute name as it appears in
    :func:`app.fingerprint.canonical_payload`.
    """

    field: str = Field(description="Canonical attribute name whose value changed.")
    before: Optional[Any] = Field(
        default=None, description="The attribute's value in ``base`` (``None`` if absent)."
    )
    after: Optional[Any] = Field(
        default=None, description="The attribute's value in ``target`` (``None`` if absent)."
    )


class EntityChange(BaseModel):
    """One added / removed / modified entity in a model diff.

    ``before`` and ``after`` carry the entity's *self-projection* — its canonical
    attributes with the child collections that are diffed in their own category
    removed (a service's ``operations``, an operation's ``messages``, a type's
    ``fields``) — so the payload describes only this entity, never its separately
    reported children. An addition carries only ``after``; a removal only ``before``;
    a modification both plus the per-attribute :attr:`fields` breakdown.
    """

    category: EntityCategory = Field(description="Which canonical collection this entity is in.")
    kind: ChangeKind = Field(description="Added, removed, or modified.")
    key: str = Field(description="The entity's stable canonical key (the pairing identity).")
    label: Optional[str] = Field(
        default=None,
        description="Optional human-readable change label supplied by a per-format "
        "``DiffLabeler``; ``None`` when no labeler is registered for the format.",
    )
    before: Optional[Any] = Field(
        default=None,
        description="The entity's self-projection in ``base``; ``None`` for an addition.",
    )
    after: Optional[Any] = Field(
        default=None,
        description="The entity's self-projection in ``target``; ``None`` for a removal.",
    )
    fields: List[FieldChange] = Field(
        default_factory=list,
        description="Per-attribute breakdown for a modification; empty otherwise.",
    )


class DiffCounts(BaseModel):
    """A tally of changes by direction, plus their total."""

    added: int = 0
    removed: int = 0
    modified: int = 0
    total: int = 0


class ModelDiff(BaseModel):
    """The structured difference between two canonical models.

    :attr:`changes` are deterministically ordered (by category spine, then key), so
    the same pair of models always serializes identically. :attr:`counts` aggregates
    all changes; :attr:`counts_by_category` breaks the tally down per
    :class:`EntityCategory` (only categories with at least one change appear).
    Persisted as JSONB alongside the version row by MFI-3.4.
    """

    base_fingerprint: str = Field(description="Semantic fingerprint of ``base``.")
    target_fingerprint: str = Field(description="Semantic fingerprint of ``target``.")
    changes: List[EntityChange] = Field(
        default_factory=list, description="Every add/remove/modify, in stable order."
    )
    counts: DiffCounts = Field(
        default_factory=DiffCounts, description="Overall add/remove/modify tally."
    )
    counts_by_category: Dict[str, DiffCounts] = Field(
        default_factory=dict,
        description="Per-category tally; only categories with changes are present.",
    )

    @property
    def identical(self) -> bool:
        """Whether the two models share a semantic fingerprint (nothing changed at all).

        ``True`` is the authoritative "no new version needed" signal MFI-3.4 keys on,
        and it *always* implies an empty :attr:`changes` (the diff is taken over the
        same projection the fingerprint hashes). The converse is *almost* always true:
        the only way :attr:`changes` is empty while ``identical`` is ``False`` is an
        artifact-level metadata edit — ``version``/``protocol``/``identity``/``servers``
        — which flips the fingerprint but is outside the six itemized entity categories.
        """
        return self.base_fingerprint == self.target_fingerprint

    def is_empty(self) -> bool:
        """Whether the diff records no entity changes.

        Empty does not by itself prove the models are identical (an artifact-level
        metadata edit leaves the entity diff empty yet flips the fingerprint); consult
        :attr:`identical` for the authoritative "nothing changed" answer.
        """
        return not self.changes


# Child collections diffed as their own category, removed from a parent entity's
# self-projection so a child change is never also counted as a parent modification.
_CHILD_KEYS: Dict[EntityCategory, str] = {
    EntityCategory.SERVICE: "operations",
    EntityCategory.OPERATION: "messages",
    EntityCategory.TYPE: "fields",
}


def _self_projection(entity: Dict[str, Any], category: EntityCategory) -> Dict[str, Any]:
    """Return ``entity`` without the child collection diffed under its own category.

    For a service/operation/type the corresponding ``operations``/``messages``/
    ``fields`` list is dropped (those entities are reported individually); every other
    category is returned unchanged. The input dict (already a fresh
    :func:`app.fingerprint.canonical_payload` node) is not mutated.

    Args:
        entity: One canonical-payload entity dict.
        category: The entity's category.

    Returns:
        A shallow copy of ``entity`` minus its separately-diffed child collection.
    """
    child_key = _CHILD_KEYS.get(category)
    if child_key is None:
        return entity
    return {k: v for k, v in entity.items() if k != child_key}


def _canonical(value: Any) -> str:
    """Return a byte-stable canonical JSON string of ``value`` for equality testing.

    Object keys are sorted recursively, so two values differing only in map ordering
    compare equal — matching the fingerprint's notion of equality and ensuring a mere
    key reshuffle is never reported as a change.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _index_by_key(entities: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a flat list of canonical-payload entities by their ``key``."""
    return {entity["key"]: entity for entity in entities}


def _diff_attributes(
    before: Dict[str, Any], after: Dict[str, Any]
) -> List[FieldChange]:
    """Compare two self-projections attribute by attribute.

    Walks the union of both dicts' keys in sorted order (for deterministic output) and
    emits one :class:`FieldChange` per attribute whose canonical value differs. ``key``
    is the pairing identity and, being equal for a matched pair, never appears.

    Args:
        before: The entity's self-projection in ``base``.
        after: The entity's self-projection in ``target``.

    Returns:
        The differing attributes, in sorted attribute-name order.
    """
    field_changes: List[FieldChange] = []
    for name in sorted(set(before) | set(after)):
        before_value = before.get(name)
        after_value = after.get(name)
        if _canonical(before_value) != _canonical(after_value):
            field_changes.append(
                FieldChange(field=name, before=before_value, after=after_value)
            )
    return field_changes


def _diff_category(
    category: EntityCategory,
    base_entities: List[Dict[str, Any]],
    target_entities: List[Dict[str, Any]],
) -> List[EntityChange]:
    """Diff one category's entities, paired by stable ``key``.

    Entities only in ``target`` are additions, only in ``base`` removals, and those in
    both with a differing self-projection are modifications (carrying the per-attribute
    :class:`FieldChange` breakdown). Entities whose self-projections match exactly
    produce no change. The returned list is unordered; :func:`diff` applies the final
    stable ordering across all categories.
    """
    base_by_key = _index_by_key(base_entities)
    target_by_key = _index_by_key(target_entities)
    changes: List[EntityChange] = []

    for key, entity in target_by_key.items():
        if key not in base_by_key:
            changes.append(
                EntityChange(
                    category=category,
                    kind=ChangeKind.ADDED,
                    key=key,
                    after=_self_projection(entity, category),
                )
            )

    for key, entity in base_by_key.items():
        if key not in target_by_key:
            changes.append(
                EntityChange(
                    category=category,
                    kind=ChangeKind.REMOVED,
                    key=key,
                    before=_self_projection(entity, category),
                )
            )

    for key, base_entity in base_by_key.items():
        target_entity = target_by_key.get(key)
        if target_entity is None:
            continue
        before = _self_projection(base_entity, category)
        after = _self_projection(target_entity, category)
        attribute_changes = _diff_attributes(before, after)
        if attribute_changes:
            changes.append(
                EntityChange(
                    category=category,
                    kind=ChangeKind.MODIFIED,
                    key=key,
                    before=before,
                    after=after,
                    fields=attribute_changes,
                )
            )
    return changes


def _collect_categories(
    payload: Dict[str, Any],
) -> Dict[EntityCategory, List[Dict[str, Any]]]:
    """Flatten a canonical-payload dict into per-category entity lists, keyed globally.

    Operations are gathered across all services, messages across all operations, and
    fields across all record types — each entity keeping its own stable ``key`` so the
    flattened lists pair correctly across two models.

    Args:
        payload: A :func:`app.fingerprint.canonical_payload` dict.

    Returns:
        One list of entity dicts per :class:`EntityCategory`.
    """
    services = payload.get("services") or []
    operations = [op for service in services for op in (service.get("operations") or [])]
    messages = [msg for op in operations for msg in (op.get("messages") or [])]
    types = payload.get("types") or []
    fields = [field for type_ in types for field in (type_.get("fields") or [])]
    return {
        EntityCategory.SERVICE: services,
        EntityCategory.OPERATION: operations,
        EntityCategory.MESSAGE: messages,
        EntityCategory.CHANNEL: payload.get("channels") or [],
        EntityCategory.TYPE: types,
        EntityCategory.FIELD: fields,
    }


def _tally(changes: List[EntityChange]) -> DiffCounts:
    """Tally a list of changes by direction into a :class:`DiffCounts`."""
    counts = DiffCounts()
    for change in changes:
        if change.kind is ChangeKind.ADDED:
            counts.added += 1
        elif change.kind is ChangeKind.REMOVED:
            counts.removed += 1
        else:
            counts.modified += 1
    counts.total = len(changes)
    return counts


def diff(base: CanonicalApi, target: CanonicalApi) -> ModelDiff:
    """Compute the structured diff from ``base`` to ``target``.

    Compares the two models' canonical projections
    (:func:`app.fingerprint.canonical_payload`) and returns every service, operation,
    message, channel, type, and field added/removed/modified, with before/after
    self-projections and add/remove/modify counts. The comparison is direction-aware
    ("added"/"removed" are relative to ``base``; "before"/"after" are ``base``/
    ``target``) and works for any two models — adjacent versions or arbitrarily distant
    ones, and across formats — because it compares them directly. When a
    :class:`DiffLabeler` is registered for ``target``'s format, each change is enriched
    with a human-readable :attr:`EntityChange.label`.

    Args:
        base: The earlier / "from" model.
        target: The later / "to" model.

    Returns:
        A :class:`ModelDiff` with both fingerprints, the ordered changes, and counts.
        When the models are identical the result is empty and
        :attr:`ModelDiff.identical` is ``True``.
    """
    base_categories = _collect_categories(canonical_payload(base))
    target_categories = _collect_categories(canonical_payload(target))

    changes: List[EntityChange] = []
    counts_by_category: Dict[str, DiffCounts] = {}
    for category in EntityCategory:
        category_changes = _diff_category(
            category, base_categories[category], target_categories[category]
        )
        if category_changes:
            counts_by_category[category.value] = _tally(category_changes)
        changes.extend(category_changes)

    changes.sort(key=lambda change: (_CATEGORY_RANK[change.category], change.key))

    _apply_labels(changes, base, target)

    return ModelDiff(
        base_fingerprint=canonical_fingerprint(base),
        target_fingerprint=canonical_fingerprint(target),
        changes=changes,
        counts=_tally(changes),
        counts_by_category=counts_by_category,
    )


# ===========================================================================
# Per-format change-label enrichment SPI + registry
# ===========================================================================


class DiffLabeler(ABC):
    """Service-provider contract for per-format change-label enrichment.

    The structural diff already says *what kind* of entity changed and *how* (the
    attribute breakdown). A format whose ecosystem has a richer vocabulary for change
    semantics — GraphQL's breaking/dangerous classes, Avro's compatibility-affecting
    edits, protobuf field-number reuse — registers a labeler to attach a concise,
    human-readable :attr:`EntityChange.label` (for example
    ``"field became non-null (breaking)"``). Labeling is **purely additive**: a labeler
    never adds, removes, or reclassifies a change, only annotates it.

    A labeler must be **deterministic and side-effect free**: given the same change and
    models it returns the same label and performs no I/O. It declares the
    :attr:`format` key it applies to.

    Subclasses register via the ``register=True`` flag
    (``class GraphQLDiffLabeler(DiffLabeler, register=True): ...``) or
    :func:`register_diff_labeler`, and are looked up by ``format`` with
    :func:`get_diff_labeler`.
    """

    #: Source format key this labeler applies to, matched against
    #: :attr:`app.canonical_model.CanonicalApi.format`.
    format: ClassVar[str] = ""

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass in the labeler registry.

        Args:
            register: When ``True``, the subclass is added to the registry under its
                :attr:`format` key as soon as it is defined.
        """
        super().__init_subclass__(**kwargs)
        if register:
            register_diff_labeler(cls)

    @abstractmethod
    def label(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[str]:
        """Return a human-readable label for ``change``, or ``None`` to leave it bare.

        Args:
            change: The change to (optionally) annotate. Must not be mutated.
            base: The "from" model the diff was computed against.
            target: The "to" model the diff was computed against.

        Returns:
            A short label string, or ``None`` to leave :attr:`EntityChange.label` unset
            for this change.
        """
        raise NotImplementedError


# Format-key → labeler-class registry. A format epic registers its labeler here so
# :func:`diff` can enrich change labels without this module importing every format
# package.
_LABELER_REGISTRY: Dict[str, type[DiffLabeler]] = {}


def register_diff_labeler(cls: type[DiffLabeler]) -> type[DiffLabeler]:
    """Register a concrete :class:`DiffLabeler` under its ``format`` key.

    Args:
        cls: A concrete :class:`DiffLabeler` subclass with a non-empty ``format``.

    Returns:
        ``cls`` unchanged, so this can also be used as a class decorator.

    Raises:
        ValueError: If ``cls.format`` is empty, or a *different* class is already
            registered under the same format key (re-registering the same class is a
            no-op, so module re-import is safe).
    """
    key = cls.format
    if not key:
        raise ValueError(f"{cls.__name__} must set a non-empty `format` to register")
    existing = _LABELER_REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"diff labeler for format {key!r} already registered to "
            f"{existing.__name__}; cannot re-register to {cls.__name__}"
        )
    _LABELER_REGISTRY[key] = cls
    return cls


def get_diff_labeler(format_key: str) -> Optional[type[DiffLabeler]]:
    """Return the labeler class registered for ``format_key``, or ``None``."""
    return _LABELER_REGISTRY.get(format_key)


def available_diff_formats() -> List[str]:
    """Return the sorted format keys that have a registered diff labeler."""
    return sorted(_LABELER_REGISTRY)


def _apply_labels(
    changes: List[EntityChange], base: CanonicalApi, target: CanonicalApi
) -> None:
    """Annotate ``changes`` in place using ``target``'s registered labeler, if any.

    The labeler is resolved by ``target.format`` (the "to" side defines the resulting
    artifact's format); when none is registered the changes are left unlabeled. A
    labeler returning ``None`` for a given change leaves that change's label unset.
    """
    labeler_cls = get_diff_labeler(target.format)
    if labeler_cls is None:
        return
    labeler = labeler_cls()
    for change in changes:
        change.label = labeler.label(change, base, target)
