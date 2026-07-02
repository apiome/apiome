"""
Manual-edit divergence guard for repository auto-refresh (RAR-4.4, #3530).

A spec-faithful auto-refresh (RAR-4.1) re-imports a changed source file and
supersedes the catalog version the original import produced (RAR-4.2). Nothing
on that path checks whether a human edited that version **in Apiome** after
the original import. Without a guard, the refresh would silently overwrite those
hand edits — a data-loss risk.

This module is that guard. It compares the *current* version's content lineage
to the snapshot the original import produced (a stored post-import checksum) and
decides whether the refresh may proceed:

    last import snapshot == current  -> safe: apply the refresh
    last import snapshot != current  -> DIVERGED: hold + flag (no overwrite)

The default policy is **hold-not-clobber**: a detected manual edit blocks the
silent overwrite, the file is flagged ``diverged`` (which
:func:`repository_refresh_status.compute_refresh_status` surfaces as the
``diverged`` state), and the divergence is surfaced for review and notification
(RAR-5.1 / RAR-5.4). A future per-repo/file policy (RAR-4.5) can opt into
overwriting a diverged version; this module accepts that policy as a parameter
so the dispatcher can pass it through without a second decision site.

Like the RAR-2.2 comparator and the RAR-2.4 idempotency guard, this is a pure,
side-effect-free decision function so it can be exercised by deterministic
fixtures. The caller supplies the two content identities (or the raw content via
:func:`compute_content_checksum`); capturing the post-import snapshot at import
time and persisting the ``diverged`` flag / firing the notification on a HOLD is
the EPIC-4 dispatcher's job, mirroring how RAR-4.1/4.2/4.3 deferred their
persistence and wiring.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DivergencePolicy(str, Enum):
    """How to act when a refresh would overwrite a hand-edited version.

    The MVP default is :attr:`HOLD` (hold-not-clobber). RAR-4.5 introduces a
    configurable per-repo/file policy that can select :attr:`OVERWRITE`; this
    enum is the contract the dispatcher passes through to the guard.
    """

    #: Hold-not-clobber (default): a detected manual edit blocks the overwrite,
    #: the file is flagged ``diverged``, and the divergence is surfaced.
    HOLD = "hold"
    #: Clobber: a detected manual edit is overwritten by the refresh anyway
    #: (RAR-4.5 opt-out). Divergence is still *detected* and reported, but the
    #: refresh is not held.
    OVERWRITE = "overwrite"


class DivergenceReason(str, Enum):
    """Why the guard reached its decision (stable codes for logging/audit/UI)."""

    #: No post-import snapshot was captured for this lineage, so a manual edit
    #: cannot be proven. The guard fails open (applies the refresh): there is no
    #: baseline to be "different from", so nothing indicates an edit to protect.
    NO_BASELINE = "no-baseline"
    #: The current version matches the post-import snapshot exactly -> no manual
    #: edit -> safe to apply the refresh.
    UNCHANGED = "unchanged"
    #: The current version differs from the post-import snapshot -> the version
    #: was hand-edited after import -> divergence detected.
    MANUAL_EDIT = "manual-edit"


@dataclass(frozen=True)
class DivergenceDecision:
    """Outcome of the manual-edit divergence guard for a single imported file.

    Attributes:
        diverged: True when a manual edit was *detected* (the current version no
            longer matches the post-import snapshot). This is independent of the
            policy: divergence is reported even when the policy permits an
            overwrite, so audit/notification always reflect reality.
        should_hold: True when the refresh must be **held** (the overwrite
            skipped) and the file flagged ``diverged``. True exactly when a
            manual edit was detected *and* the policy is
            :attr:`DivergencePolicy.HOLD`. The dispatcher gates the overwrite,
            the persistent ``diverged`` flag, and the RAR-5.4 notification on
            this field.
        reason: The :class:`DivergenceReason` code explaining the decision.
        policy: The :class:`DivergencePolicy` the decision was made under, echoed
            back for audit clarity.
    """

    diverged: bool
    should_hold: bool
    reason: DivergenceReason
    policy: DivergencePolicy


def _normalise_checksum(value: Optional[str]) -> Optional[str]:
    """Trim a content-identity token to a comparable form (``None`` when blank)."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def compute_content_checksum(content: Optional[str]) -> Optional[str]:
    """Compute a stable content checksum for a version's content lineage.

    Produces the content-identity token the guard compares: a hex SHA-256 digest
    of the content with surrounding whitespace trimmed, so an incidental trailing
    newline does not read as a divergence. Both the post-import snapshot and the
    current version content are hashed through this one function so the two sides
    are always directly comparable.

    Args:
        content: The version content (for example its canonical OpenAPI/spec
            render), or ``None`` when no content is available.

    Returns:
        The lowercase hex SHA-256 digest, or ``None`` when ``content`` is ``None``
        or blank after trimming.
    """
    if content is None:
        return None
    trimmed = content.strip()
    if not trimmed:
        return None
    return hashlib.sha256(trimmed.encode("utf-8")).hexdigest()


def evaluate_divergence(
    *,
    post_import_checksum: Optional[str],
    current_checksum: Optional[str],
    policy: DivergencePolicy = DivergencePolicy.HOLD,
) -> DivergenceDecision:
    """Decide whether an auto-refresh may overwrite the current version (RAR-4.4).

    Compares the post-import snapshot checksum (the content identity the original
    import produced) against the current version's content checksum to detect a
    hand edit made after import, then applies the divergence ``policy``:

        no post-import snapshot           -> apply  (NO_BASELINE; cannot prove an edit)
        snapshot == current               -> apply  (UNCHANGED; no manual edit)
        snapshot != current, policy HOLD  -> hold   (MANUAL_EDIT; diverged, no overwrite)
        snapshot != current, policy OVER. -> apply  (MANUAL_EDIT; diverged but clobbered)

    A missing *current* checksum (with a snapshot present) counts as a difference:
    the guard cannot confirm the version still matches the snapshot, so under the
    hold-not-clobber default it holds rather than risk clobbering an edit.

    Args:
        post_import_checksum: Content checksum captured for the version right
            after the original import (the snapshot baseline). ``None``/blank when
            no snapshot was captured for this lineage.
        current_checksum: Content checksum of the version as it stands now.
            ``None``/blank when the current content is unavailable.
        policy: The :class:`DivergencePolicy` to apply on a detected edit.
            Defaults to :attr:`DivergencePolicy.HOLD` (the MVP hold-not-clobber
            default); RAR-4.5 supplies a configured value.

    Returns:
        A :class:`DivergenceDecision` with the divergence verdict, whether to hold
        the refresh, a stable reason code, and the policy used.
    """
    baseline = _normalise_checksum(post_import_checksum)
    current = _normalise_checksum(current_checksum)

    # No snapshot to compare against: there is nothing proving a hand edit, so the
    # refresh proceeds. (Capturing a snapshot at import time is the dispatcher's
    # job; absent it, the guard cannot — and must not — invent a divergence.)
    if baseline is None:
        return DivergenceDecision(
            diverged=False,
            should_hold=False,
            reason=DivergenceReason.NO_BASELINE,
            policy=policy,
        )

    # Current content is byte-identical to the post-import snapshot: no human
    # touched it since import, so the refresh is safe to apply.
    if baseline == current:
        return DivergenceDecision(
            diverged=False,
            should_hold=False,
            reason=DivergenceReason.UNCHANGED,
            policy=policy,
        )

    # The version differs from the snapshot (or its current content is missing):
    # a manual edit is detected. Hold under the default policy; under an explicit
    # OVERWRITE policy (RAR-4.5) the divergence is still reported but not held.
    return DivergenceDecision(
        diverged=True,
        should_hold=policy is DivergencePolicy.HOLD,
        reason=DivergenceReason.MANUAL_EDIT,
        policy=policy,
    )


def guard_divergence(
    *,
    post_import_content: Optional[str],
    current_content: Optional[str],
    policy: DivergencePolicy = DivergencePolicy.HOLD,
) -> DivergenceDecision:
    """Run the divergence guard from raw content (convenience wrapper).

    Hashes both sides through :func:`compute_content_checksum` so a caller holding
    the raw post-import snapshot and the current version content can get the
    decision without checksumming each side itself. Equivalent to calling
    :func:`compute_content_checksum` on each input and passing the results to
    :func:`evaluate_divergence`.

    Args:
        post_import_content: The version content captured right after the original
            import (the snapshot baseline), or ``None`` when none was captured.
        current_content: The version content as it stands now, or ``None`` when
            unavailable.
        policy: The :class:`DivergencePolicy` to apply on a detected edit.

    Returns:
        The :class:`DivergenceDecision` describing whether to hold the refresh.
    """
    return evaluate_divergence(
        post_import_checksum=compute_content_checksum(post_import_content),
        current_checksum=compute_content_checksum(current_content),
        policy=policy,
    )
