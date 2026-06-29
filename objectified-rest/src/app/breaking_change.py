"""Breaking-change classifier SPI: grade a model diff breaking-vs-safe — MFI-3.3 (#3744).

The compare-any-two diff (MFI-3.2, :mod:`app.diff`) says *what* changed between two
canonical models — every service / operation / message / channel / type / field that
was added, removed, or modified. This module answers the next question every consumer
asks: *is that change safe to ship, or will it break callers?*

It provides two things, mirroring the fingerprint-hasher (:mod:`app.fingerprint`) and
diff-labeler (:mod:`app.diff`) registries:

* **A per-format classifier hook** — the :class:`BreakingChangeClassifier` SPI and its
  registry. A format whose ecosystem defines authoritative compatibility rules
  registers a classifier under its format key. Ideally it *wraps the canonical tool*
  via the toolchain runner (EPIC-5) — Buf breaking (WIRE / WIRE_JSON), GraphQL-Inspector
  classes, ``@asyncapi/diff``, ``smithy diff`` evaluators, Confluent ``/compatibility``,
  the OData §5.2 policy — and maps that tool's verdict back onto the same per-change
  :class:`Severity`.

* **A format-agnostic built-in ruleset** — :class:`BuiltinBreakingChangeClassifier`,
  a conservative, *documented* grading of the structural diff that works for every
  paradigm without any external tool. Removing surface is breaking, additive surface
  is safe, and a modification is graded by which canonical attribute moved (a type
  narrowed to non-null is breaking, a constraint tightened is dangerous, a default
  changed is dangerous, a description-only edit is already invisible to the diff). This
  is the "where no tool exists (RAML, API Blueprint), a documented built-in ruleset"
  fallback the roadmap calls for, and it is what :func:`classify` uses when a format has
  registered no classifier of its own. A format pack may also subclass it to inherit
  the baseline and override only the rules its format sharpens.

The three severities — :attr:`Severity.SAFE`, :attr:`Severity.DANGEROUS`,
:attr:`Severity.BREAKING` — are the common ground across those ecosystems
(GraphQL-Inspector's ``NON_BREAKING`` / ``DANGEROUS`` / ``BREAKING``, Buf's allow / warn /
break, Confluent's compatible / incompatible). ``DANGEROUS`` is the "compatible by the
letter but review this" middle tier (a default changed, a constraint tightened, a field
deprecated, an enum's variant set moved).

The result of grading a whole diff is a :class:`ClassificationResult`: a per-change
:class:`ChangeClassification` (severity + stable ``rule_id`` + human rationale, carrying
the change's ``category`` / ``kind`` / ``key`` so a diff view can join severities back
onto the rendered changes), the worst :attr:`overall_severity`, and a tally per
severity. That is how the acceptance criterion "severities surfaced on the diff view"
is met: every change the diff lists gets a severity, in the diff's own stable order.

The module is **pure** for the built-in path: no DB, no network. Per-format classifiers
that shell out to a CLI do their I/O behind the toolchain runner; the SPI itself only
maps the result onto :class:`Severity`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange, ModelDiff, diff

__all__ = [
    "Severity",
    "ChangeClassification",
    "ClassificationResult",
    "BreakingChangeClassifier",
    "BuiltinBreakingChangeClassifier",
    "classify",
    "classify_models",
    "register_breaking_change_classifier",
    "get_breaking_change_classifier",
    "available_breaking_change_formats",
]


class Severity(str, Enum):
    """How a single change affects compatibility, worst-last.

    The three tiers are the common denominator of the per-format ecosystems this SPI
    abstracts over (GraphQL-Inspector ``NON_BREAKING`` / ``DANGEROUS`` / ``BREAKING``,
    Buf allow / warn / break, Confluent compatible / incompatible):

    * :attr:`SAFE` — additive or widening; existing callers keep working.
    * :attr:`DANGEROUS` — compatible by the letter but warrants review: a default or
      constraint moved, a field was deprecated, an enum's variant set changed, a
      content type changed. The change *can* surprise a caller even though no contract
      was strictly removed or narrowed.
    * :attr:`BREAKING` — removes or narrows surface existing callers may depend on.

    The string values are stable wire identifiers (persisted and surfaced on the diff
    view); :data:`_SEVERITY_RANK` gives their order for taking a worst-of aggregate.
    """

    SAFE = "safe"
    DANGEROUS = "dangerous"
    BREAKING = "breaking"


# Ordinal rank of each severity, used to take the worst severity across a set of
# changes (the overall grade of a diff is the max over its per-change grades).
_SEVERITY_RANK: Dict[Severity, int] = {
    Severity.SAFE: 0,
    Severity.DANGEROUS: 1,
    Severity.BREAKING: 2,
}


def _worst(severities: List[Severity]) -> Severity:
    """Return the highest-ranked (most breaking) severity, or :attr:`Severity.SAFE`.

    Args:
        severities: Zero or more severities to aggregate.

    Returns:
        The worst severity present, or :attr:`Severity.SAFE` for an empty list (an
        empty diff is, by definition, safe).
    """
    worst = Severity.SAFE
    for severity in severities:
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity
    return worst


class ChangeClassification(BaseModel):
    """The compatibility grade of one :class:`~app.diff.EntityChange`.

    Echoes the graded change's identity (:attr:`category` / :attr:`kind` / :attr:`key`)
    so a diff view — or any consumer holding the :class:`~app.diff.ModelDiff` — can join
    a severity back onto the exact change it rendered, without relying on list position.
    :attr:`rule_id` is a stable identifier of the rule that fired (so a grade can be
    explained, suppressed, or counted), and :attr:`rationale` is its one-line
    human-readable justification.
    """

    category: EntityCategory = Field(description="The graded change's entity category.")
    kind: ChangeKind = Field(description="Whether the change was added, removed, or modified.")
    key: str = Field(description="The graded change's stable canonical key (the join identity).")
    severity: Severity = Field(description="How this change affects compatibility.")
    rule_id: str = Field(
        description="Stable identifier of the rule that produced this grade "
        "(for example ``removed-entity`` or ``type-narrowed``)."
    )
    rationale: str = Field(
        description="One-line human-readable justification for the severity."
    )


class ClassificationResult(BaseModel):
    """The breaking-change grading of a whole :class:`~app.diff.ModelDiff`.

    :attr:`classifications` is 1:1 with and in the same stable order as
    :attr:`app.diff.ModelDiff.changes`, so the two zip together for a diff view.
    :attr:`overall_severity` is the worst per-change severity (``SAFE`` for an empty
    diff), and :attr:`breaking` is the convenience boolean a version-roll / publish gate
    keys on. :attr:`counts_by_severity` tallies the grades. Plain Pydantic, so it
    round-trips losslessly to JSONB for persistence alongside the version diff (MFI-3.4).
    """

    format: str = Field(description="The artifact's source format key (``target.format``).")
    classifier: str = Field(
        description="Identifier of the classifier that produced the grades "
        "(``builtin`` for the format-agnostic ruleset, else a format pack's id)."
    )
    overall_severity: Severity = Field(
        description="Worst severity across all changes; ``SAFE`` for an empty diff."
    )
    classifications: List[ChangeClassification] = Field(
        default_factory=list,
        description="Per-change grades, 1:1 with the diff's changes, in the same order.",
    )
    counts_by_severity: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of changes at each severity (only non-zero tiers present).",
    )

    @property
    def breaking(self) -> bool:
        """Whether any change is :attr:`Severity.BREAKING` (the publish-gate signal)."""
        return self.overall_severity is Severity.BREAKING


def _classifier_id(classifier: "BreakingChangeClassifier") -> str:
    """Return a classifier's stable id, defaulting to its class name when unset."""
    return classifier.classifier_id or type(classifier).__name__


def _assemble_result(
    classifier: "BreakingChangeClassifier",
    target: CanonicalApi,
    classifications: List[ChangeClassification],
) -> ClassificationResult:
    """Assemble a :class:`ClassificationResult` from per-change grades.

    Args:
        classifier: The classifier that produced the grades (for its id).
        target: The "to" model (for its format key).
        classifications: The per-change grades, in the diff's stable order.

    Returns:
        The aggregated result: worst-of overall severity and per-severity counts.
    """
    counts: Dict[str, int] = {}
    for classification in classifications:
        counts[classification.severity.value] = (
            counts.get(classification.severity.value, 0) + 1
        )
    overall = _worst([c.severity for c in classifications])
    return ClassificationResult(
        format=target.format,
        classifier=_classifier_id(classifier),
        overall_severity=overall,
        classifications=classifications,
        counts_by_severity=counts,
    )


# ===========================================================================
# Per-format classifier SPI + registry
# ===========================================================================


class BreakingChangeClassifier(ABC):
    """Service-provider contract for grading a diff breaking-vs-safe per format.

    A format whose ecosystem defines authoritative compatibility rules registers a
    classifier under its :attr:`format` key. The expected implementation *wraps the
    canonical tool* via the toolchain runner (EPIC-5) — Buf breaking, GraphQL-Inspector,
    ``@asyncapi/diff``, ``smithy diff``, Confluent ``/compatibility``, the OData policy —
    and maps that tool's verdict onto a per-change :class:`Severity`. A classifier that
    only sharpens a few rules over the structural baseline should instead subclass
    :class:`BuiltinBreakingChangeClassifier`.

    A classifier must be **deterministic**: the same diff and models yield the same
    grades. The only required method is :meth:`classify_change` (grade one change), which
    keeps every classifier able to answer "what is the severity of *this* change" for the
    diff view. A tool-wrapping classifier that runs its CLI once over the whole diff
    overrides :meth:`classify` and may memoize the tool's per-change verdicts for
    :meth:`classify_change` to read back.

    Subclasses register via the ``register=True`` flag
    (``class BufClassifier(BreakingChangeClassifier, register=True): ...``) or
    :func:`register_breaking_change_classifier`, and are looked up by ``format`` with
    :func:`get_breaking_change_classifier`.
    """

    #: Source format key this classifier applies to, matched against
    #: :attr:`app.canonical_model.CanonicalApi.format`.
    format: ClassVar[str] = ""

    #: Stable identifier recorded on the :class:`ClassificationResult`, e.g.
    #: ``"buf-breaking-wire"``. Defaults to the class name when left empty.
    classifier_id: ClassVar[str] = ""

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass in the classifier registry.

        Args:
            register: When ``True``, the subclass is added to the registry under its
                :attr:`format` key as soon as it is defined.
        """
        super().__init_subclass__(**kwargs)
        if register:
            register_breaking_change_classifier(cls)

    @abstractmethod
    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Return the compatibility grade of a single ``change``.

        Args:
            change: The diff change to grade. Must not be mutated.
            base: The "from" model the diff was computed against.
            target: The "to" model the diff was computed against.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        raise NotImplementedError

    def classify(
        self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi
    ) -> ClassificationResult:
        """Grade an entire ``model_diff`` by grading each change.

        The default walks :attr:`app.diff.ModelDiff.changes` in order, calling
        :meth:`classify_change` per change, then assembles the worst-of overall severity
        and per-severity tally. A tool-wrapping classifier may override this to run its
        CLI once over the whole diff.

        Args:
            model_diff: The diff to grade.
            base: The "from" model.
            target: The "to" model.

        Returns:
            The :class:`ClassificationResult` for the diff.
        """
        classifications = [
            self.classify_change(change, base, target) for change in model_diff.changes
        ]
        return _assemble_result(self, target, classifications)


# Format-key -> classifier-class registry. A format epic registers its classifier here
# so `classify` can grade per-format without this module importing every format package.
_CLASSIFIER_REGISTRY: Dict[str, type[BreakingChangeClassifier]] = {}


def register_breaking_change_classifier(
    cls: type[BreakingChangeClassifier],
) -> type[BreakingChangeClassifier]:
    """Register a concrete :class:`BreakingChangeClassifier` under its ``format`` key.

    Args:
        cls: A concrete :class:`BreakingChangeClassifier` subclass with a non-empty
            ``format``.

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
    existing = _CLASSIFIER_REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"breaking-change classifier for format {key!r} already registered to "
            f"{existing.__name__}; cannot re-register to {cls.__name__}"
        )
    _CLASSIFIER_REGISTRY[key] = cls
    return cls


def get_breaking_change_classifier(
    format_key: str,
) -> Optional[type[BreakingChangeClassifier]]:
    """Return the classifier class registered for ``format_key``, or ``None``."""
    return _CLASSIFIER_REGISTRY.get(format_key)


def available_breaking_change_formats() -> List[str]:
    """Return the sorted format keys that have a registered classifier."""
    return sorted(_CLASSIFIER_REGISTRY)


# ===========================================================================
# Format-agnostic built-in ruleset
# ===========================================================================


def _is_non_null_ref(type_ref: Any) -> bool:
    """Return whether a canonical ``TypeRef`` dict is non-nullable at its outer level.

    A field/parameter whose type is non-nullable (the GraphQL ``!``, an OpenAPI
    ``required`` member, a protobuf non-optional scalar) is mandatory; adding one or
    narrowing to one is the breaking/dangerous case the rules below pivot on.

    Args:
        type_ref: A ``TypeRef`` self-projection dict (or ``None``).

    Returns:
        ``True`` when the ref is present and its outer level is ``nullable=False``.
    """
    return isinstance(type_ref, dict) and type_ref.get("nullable") is False


def _classify_type_change(before: Any, after: Any) -> Severity:
    """Grade a change to a field/parameter ``type`` (a ``TypeRef``).

    Narrowing a nullable type to non-null removes callers' ability to omit/null the
    value, and any change to the referenced named type or list shape can change the
    wire contract — both breaking. Widening non-null to nullable (with the same
    underlying type) is safe.

    Args:
        before: The ``type`` ``TypeRef`` dict on the ``base`` side.
        after: The ``type`` ``TypeRef`` dict on the ``target`` side.

    Returns:
        :attr:`Severity.SAFE` for a pure nullable-widening, otherwise
        :attr:`Severity.BREAKING`.
    """
    before_non_null = _is_non_null_ref(before)
    after_non_null = _is_non_null_ref(after)
    if not before_non_null and after_non_null:
        return Severity.BREAKING  # nullable -> non-null: callers can no longer omit it
    if before_non_null and not after_non_null:
        # non-null -> nullable with the same underlying type is a pure widening.
        if isinstance(before, dict) and isinstance(after, dict):
            before_rest = {k: v for k, v in before.items() if k != "nullable"}
            after_rest = {k: v for k, v in after.items() if k != "nullable"}
            if before_rest == after_rest:
                return Severity.SAFE
    return Severity.BREAKING  # the referenced type / list shape changed


# Attributes whose movement on a MODIFIED entity is unconditionally breaking: a route /
# verb / kind / status / wire-identity / payload move existing callers cannot absorb.
_BREAKING_ATTRS = frozenset(
    {
        "http_method",     # the route's verb moved — old calls 404/405
        "http_path",       # the route moved
        "kind",            # operation/type semantics changed
        "status_code",     # a response's status moved
        "field_number",    # protobuf/Thrift wire identity reused
        "location",        # a parameter moved between path/query/header
        "role",            # a message flipped request<->response
        "streaming",       # a unary method became streaming or vice versa
        "payload",         # a message's payload type changed
        "payload_schema",  # a message's inline body changed
        "aliased",         # an ALIAS target changed
        "key_type",        # a MAP key type changed
        "value_type",      # a MAP value type changed
        "address",         # a channel's wire address changed
        "protocol",        # a channel's transport changed
    }
)

# Attributes whose movement is compatible by the letter but warrants review. This
# includes the *folded member lists* — ``parameters`` (off an operation), ``headers``
# (off a message), ``enum_values`` / ``union_members`` (off a type) — which the diff
# carries as part of their owner's self-projection rather than as their own category.
# The baseline cannot tell an added-optional-parameter (safe) from a
# made-required-parameter (breaking) inside such a list, so it grades any movement
# DANGEROUS and leaves the sharp call to a per-format classifier (e.g. one wrapping
# GraphQL-Inspector, which understands argument requiredness).
_DANGEROUS_ATTRS = frozenset(
    {
        "default",         # a default value changed — silently shifts behavior
        "constraints",     # a validation facet moved (tightening is breaking-ish)
        "content_types",   # the encodings a message accepts changed
        "parameters",      # an operation's (folded) parameter set moved
        "headers",         # a message's (folded) header set moved
        "enum_values",     # an enum's variant set moved (add or remove)
        "union_members",   # a union's variant set moved
        "bindings",        # a channel's protocol bindings changed
        "name",            # source name moved while the stable key held (display rename)
        "tags",            # grouping tags changed
        "namespace",       # a type's namespace moved
    }
)


def _classify_modified_attribute(change_field: Any) -> Severity:
    """Grade one attribute that moved on a MODIFIED entity.

    Args:
        change_field: A :class:`~app.diff.FieldChange` (``field`` / ``before`` /
            ``after``) from a modified entity's breakdown.

    Returns:
        The severity for this single attribute move.
    """
    name = change_field.field
    if name == "type":
        return _classify_type_change(change_field.before, change_field.after)
    if name == "deprecated":
        # Deprecating signals an upcoming removal — compatible now, review warranted.
        return Severity.DANGEROUS if change_field.after else Severity.SAFE
    if name in _BREAKING_ATTRS:
        return Severity.BREAKING
    if name in _DANGEROUS_ATTRS:
        return Severity.DANGEROUS
    return Severity.DANGEROUS  # unrecognized contract attribute moved — flag for review


class BuiltinBreakingChangeClassifier(BreakingChangeClassifier):
    """The format-agnostic, documented baseline grading of a structural diff.

    Used by :func:`classify` whenever the artifact's format has registered no classifier
    of its own, and available as a base class a format pack can subclass to inherit the
    baseline and override only the rules its format sharpens. It is deliberately
    **conservative** — it grades from structure alone, with no knowledge of any single
    format's compatibility tool — and **pure** (no I/O). Its :attr:`format` is empty, so
    it is never auto-registered; :func:`classify` reaches it as the fallback.

    The ruleset:

    * **Removed** anything (service / operation / message / channel / type / field) →
      :attr:`Severity.BREAKING`. Removing surface a caller may depend on is the
      canonical breaking change; direction (request vs response) is unknowable from the
      structure alone, so the safe default is to flag it.
    * **Added** an *optional* field, or any service / operation / message / channel /
      type → :attr:`Severity.SAFE` (additive surface). **Added** a *mandatory* field (a
      non-nullable type with no default) → :attr:`Severity.DANGEROUS`: additive on the
      output side, but a new required input breaks producers.
    * **Modified** an entity → the worst grade over the attributes that moved
      (:func:`_classify_modified_attribute`): a type narrowed to non-null, a route /
      verb / kind / status / wire-identity move is breaking; a default, constraint,
      deprecation, content-type move — or a movement inside a *folded member list* the
      baseline can't introspect (an operation's ``parameters``, a message's
      ``headers``, a type's ``enum_values`` / ``union_members``) — is dangerous; a pure
      widening is safe. A per-format classifier sharpens the folded-list cases.

    Documentation-only edits and source declaration order never reach a classifier:
    they are already invisible to the diff (MFI-3.2), which is taken over the scrubbed,
    order-normalized fingerprint projection (MFI-3.1).
    """

    #: Identifier recorded on every :class:`ClassificationResult` this produces.
    classifier_id: ClassVar[str] = "builtin"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade a single change with the built-in ruleset.

        Args:
            change: The diff change to grade.
            base: The "from" model (unused by the baseline; available to subclasses).
            target: The "to" model (unused by the baseline; available to subclasses).

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        severity, rule_id, rationale = self._grade(change)
        return ChangeClassification(
            category=change.category,
            kind=change.kind,
            key=change.key,
            severity=severity,
            rule_id=rule_id,
            rationale=rationale,
        )

    def _grade(self, change: EntityChange) -> Tuple[Severity, str, str]:
        """Return ``(severity, rule_id, rationale)`` for ``change`` per the ruleset."""
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "removed-entity",
                f"{change.category.value} {change.key!r} was removed; "
                "callers that depend on it break",
            )
        if change.kind is ChangeKind.ADDED:
            return self._grade_added(change)
        return self._grade_modified(change)

    def _grade_added(self, change: EntityChange) -> Tuple[Severity, str, str]:
        """Grade an addition: a mandatory new field is dangerous, all else additive."""
        if change.category is EntityCategory.FIELD and self._is_mandatory_field(
            change.after
        ):
            return (
                Severity.DANGEROUS,
                "added-mandatory-field",
                f"field {change.key!r} was added as mandatory (non-nullable, no "
                "default); producers that omit it break",
            )
        return (
            Severity.SAFE,
            "added-entity",
            f"{change.category.value} {change.key!r} was added; existing callers are "
            "unaffected",
        )

    def _grade_modified(self, change: EntityChange) -> Tuple[Severity, str, str]:
        """Grade a modification as the worst grade over its moved attributes."""
        if not change.fields:
            # A modification with no attribute breakdown should not occur (the diff only
            # emits MODIFIED when an attribute moved), but grade defensively.
            return (
                Severity.DANGEROUS,
                "modified-entity",
                f"{change.category.value} {change.key!r} changed",
            )
        graded = [
            (_classify_modified_attribute(field_change), field_change.field)
            for field_change in change.fields
        ]
        worst = _worst([severity for severity, _ in graded])
        moved = sorted({name for _, name in graded})
        culprits = sorted({name for severity, name in graded if severity is worst})
        return (
            worst,
            f"modified-{worst.value}",
            f"{change.category.value} {change.key!r} changed "
            f"{', '.join(moved)} (graded by {', '.join(culprits)})",
        )

    @staticmethod
    def _is_mandatory_field(after: Any) -> bool:
        """Return whether an added field's self-projection is mandatory.

        A field is mandatory when its type is non-nullable *and* it declares no default
        (a default lets a producer omit it safely).

        Args:
            after: The added field's ``after`` self-projection dict.

        Returns:
            ``True`` when the field must be supplied by producers.
        """
        if not isinstance(after, dict):
            return False
        if after.get("default") is not None:
            return False
        return _is_non_null_ref(after.get("type"))


# A single shared instance is safe: the built-in classifier is stateless and pure.
_BUILTIN = BuiltinBreakingChangeClassifier()


# ===========================================================================
# Top-level entry points
# ===========================================================================


def classify(
    model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi
) -> ClassificationResult:
    """Grade a ``model_diff`` breaking-vs-safe, dispatching to the right classifier.

    Resolves the classifier by ``target.format`` (the "to" side defines the resulting
    artifact's format); when a format pack has registered one, it grades the diff,
    otherwise the format-agnostic :class:`BuiltinBreakingChangeClassifier` does. The
    returned :class:`ClassificationResult` carries a per-change grade (1:1 with, and in
    the same order as, ``model_diff.changes``), the worst overall severity, and a
    per-severity tally — exactly what a diff view needs to surface severities.

    Args:
        model_diff: The :class:`~app.diff.ModelDiff` to grade (as produced by
            :func:`app.diff.diff`).
        base: The "from" / earlier model the diff was computed against.
        target: The "to" / later model the diff was computed against.

    Returns:
        The :class:`ClassificationResult`.
    """
    classifier_cls = get_breaking_change_classifier(target.format)
    classifier: BreakingChangeClassifier = (
        classifier_cls() if classifier_cls is not None else _BUILTIN
    )
    return classifier.classify(model_diff, base, target)


def classify_models(base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
    """Diff ``base`` → ``target`` and grade the result in one call.

    Convenience wrapper over :func:`app.diff.diff` + :func:`classify` for callers (a
    version roll, a compare API, the CLI) that hold the two models rather than a
    precomputed diff.

    Args:
        base: The earlier / "from" model.
        target: The later / "to" model.

    Returns:
        The :class:`ClassificationResult` for the diff of the two models.
    """
    return classify(diff(base, target), base, target)
