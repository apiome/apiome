"""Import review: conflict / dedupe classification and resolution (#3464).

The earlier import path committed every parsed definition blindly: a definition whose
registry identity (``$id``) already existed silently landed in a ``skipped`` bucket with
no signal to the caller and no way to act on it. This module supplies the *review* layer
the ticket asks for — it classifies each imported definition against the existing registry
(**New / Identical / Conflict**), and turns a caller's per-type **resolution choice**
(keep / overwrite / rename) into a concrete commit decision.

The logic here is intentionally **pure** — no database, no FastAPI — so it is unit-testable
in isolation. The route layer (:mod:`app.primitives_routes`) supplies the existing-row
lookup and executes the decisions (create / update / skip); this module only decides.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Per-type classification against the existing registry.
# ---------------------------------------------------------------------------

#: No existing visible type shares this definition's registry identity (``$id``).
STATUS_NEW = "new"
#: An existing type has the same identity *and* an identical schema — a true duplicate.
STATUS_IDENTICAL = "identical"
#: An existing type has the same identity but a *different* schema — needs resolution.
STATUS_CONFLICT = "conflict"
#: The definition is not a valid draft 2020-12 schema (or violates scope) — cannot commit.
STATUS_INVALID = "invalid"

# ---------------------------------------------------------------------------
# Conflict-resolution actions a caller may choose per type.
# ---------------------------------------------------------------------------

#: Leave the existing type untouched and do not import this definition (the default).
ACTION_KEEP = "keep"
#: Replace the existing type's schema with the imported definition.
ACTION_OVERWRITE = "overwrite"
#: Import the definition under a new name, giving it a fresh registry identity.
ACTION_RENAME = "rename"
#: The set of resolution actions the commit path accepts.
VALID_ACTIONS = {ACTION_KEEP, ACTION_OVERWRITE, ACTION_RENAME}

# ---------------------------------------------------------------------------
# What the commit actually did with a definition (report buckets — one per type).
# ---------------------------------------------------------------------------

OUTCOME_IMPORTED = "imported"        # A new row was created.
OUTCOME_OVERWRITTEN = "overwritten"  # An existing row's schema was replaced.
OUTCOME_RENAMED = "renamed"          # A new row was created under a different name.
OUTCOME_IDENTICAL = "identical"      # Deduped — skipped because already present unchanged.
OUTCOME_SKIPPED = "skipped"          # A conflict left unresolved / explicitly kept.
OUTCOME_ERROR = "error"              # The decision could not be carried out.


def schemas_equivalent(a: Any, b: Any) -> bool:
    """Return whether two stored schema documents are structurally identical.

    Both the candidate (after identity stamping) and the existing row carry the same
    derived ``$id`` whenever they share a registry identity, so a plain deep comparison
    distinguishes a true duplicate (Identical) from a divergent redefinition (Conflict).

    Python ``==`` on ``dict``/``list`` is recursive and *key-order independent* — two dicts
    are equal when they hold the same key/value pairs regardless of insertion order — so this
    is robust to the non-deterministic key ordering JSON/YAML deserialization can produce and
    needs no canonical (``sort_keys``) serialization to compare correctly.

    Args:
        a: One schema document (e.g. the existing row's ``schema``).
        b: The other schema document (e.g. the stamped candidate).

    Returns:
        ``True`` when the two documents are deep-equal, ``False`` otherwise.
    """
    return a == b


def classify_status(existing: Optional[Dict[str, Any]], candidate_schema: Dict[str, Any]) -> str:
    """Classify a candidate against the existing registry row sharing its identity.

    Args:
        existing: The primitive row already holding the candidate's ``$id`` within the
            caller's read scope, or ``None`` when no such row exists.
        candidate_schema: The stamped candidate schema being imported.

    Returns:
        :data:`STATUS_NEW` when nothing exists at the identity, :data:`STATUS_IDENTICAL`
        when the existing schema matches, otherwise :data:`STATUS_CONFLICT`.
    """
    if not existing:
        return STATUS_NEW
    if schemas_equivalent(existing.get("schema"), candidate_schema):
        return STATUS_IDENTICAL
    return STATUS_CONFLICT


def allowed_resolutions(status: str) -> list:
    """Return the resolution actions that make sense for a given classification.

    Used by the review report so a UI can present only the meaningful choices: a New or
    Identical type needs no resolution, while a Conflict offers keep / overwrite / rename.

    Args:
        status: One of the ``STATUS_*`` classifications.

    Returns:
        The ordered list of applicable ``ACTION_*`` values (empty when none apply).
    """
    if status == STATUS_CONFLICT:
        return [ACTION_KEEP, ACTION_OVERWRITE, ACTION_RENAME]
    return []


@dataclass
class CommitDecision:
    """The concrete action the commit path should take for one definition.

    Attributes:
        action: The mechanical step to perform — ``create`` (new row), ``update``
            (overwrite the existing row), ``rename`` (create under ``new_name``),
            ``skip`` (do nothing), or ``error`` (the resolution was unusable).
        outcome: The report bucket the definition lands in (an ``OUTCOME_*`` value).
        reason: A human-readable note for ``skip`` / ``error`` decisions, or ``None``.
        new_name: The target name when ``action == 'rename'``, else ``None``.
    """

    action: str
    outcome: str
    reason: Optional[str] = None
    new_name: Optional[str] = None


def decide(
    status: str,
    *,
    action: str = ACTION_KEEP,
    new_name: Optional[str] = None,
    dedupe: bool = True,
) -> CommitDecision:
    """Turn a classification plus a caller's resolution choice into a commit decision.

    The decision rules:

    - **New** → create the row.
    - **Identical** with ``dedupe`` on (the default) → skip as a deduplicated duplicate.
      With ``dedupe`` off, an identical type is treated like a conflict so the caller's
      explicit resolution still applies.
    - **Conflict** (or Identical with ``dedupe`` off) → apply the resolution:
      ``overwrite`` updates the existing row, ``rename`` creates a copy under ``new_name``
      (an error if ``new_name`` is missing), and ``keep`` (the default) skips it while
      surfacing the unresolved conflict.

    Invalid definitions are filtered out by the caller before reaching this function.

    Args:
        status: The candidate's classification (a ``STATUS_*`` value, never INVALID).
        action: The caller's chosen resolution action (a ``VALID_ACTIONS`` member).
        new_name: The rename target, required only when ``action == 'rename'``.
        dedupe: Whether an Identical type is auto-skipped (``True``) or surfaced for
            resolution (``False``).

    Returns:
        The :class:`CommitDecision` describing what to do.
    """
    if status == STATUS_NEW:
        return CommitDecision(action="create", outcome=OUTCOME_IMPORTED)

    if status == STATUS_IDENTICAL and dedupe:
        return CommitDecision(
            action="skip",
            outcome=OUTCOME_IDENTICAL,
            reason="identical to an existing type",
        )

    # Conflict (or an identical type the caller opted not to dedupe): apply the resolution.
    if action == ACTION_OVERWRITE:
        return CommitDecision(action="update", outcome=OUTCOME_OVERWRITTEN)

    if action == ACTION_RENAME:
        if not new_name:
            return CommitDecision(
                action="error",
                outcome=OUTCOME_ERROR,
                reason="rename resolution requires a new_name",
            )
        return CommitDecision(action="rename", outcome=OUTCOME_RENAMED, new_name=new_name)

    # ACTION_KEEP is the explicit default. The HTTP layer rejects any non-``VALID_ACTIONS``
    # value with a 400 (see ``_normalize_resolutions``) before reaching here, so an unrecognized
    # action is unreachable from a request; this pure function nonetheless degrades to the safe
    # default (keep) rather than raising, so a direct caller that forgets to validate still gets
    # a defined, non-destructive outcome. Either way: leave the existing type in place, but
    # report the conflict rather than dropping it silently.
    return CommitDecision(
        action="skip",
        outcome=OUTCOME_SKIPPED,
        reason="conflict left unresolved (existing type kept)",
    )
