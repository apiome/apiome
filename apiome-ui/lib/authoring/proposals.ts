/**
 * AI proposals and their review contract (UXE-1.3).
 *
 * The mockups repeat one interaction everywhere: generated text with
 * Accept / Edit / Reject / Regenerate. Forking that per screen is how the same
 * gesture ends up meaning different things, so the state machine lives here and
 * every workspace renders the same one.
 *
 * The load-bearing rule from §27.2 is that **a proposal is never confused with
 * saved content**. A proposal is a distinct object with its own status; it
 * becomes content only by being accepted, and that transition is explicit.
 */

import type { AuthoringCitation } from './citations';
import type { AuthoringTone } from './tokens';

/** Lifecycle state of one proposal. */
export type AuthoringProposalStatus =
  /** Generated and awaiting review. */
  | 'pending'
  /** Applied verbatim. */
  | 'accepted'
  /** Applied after the reviewer changed it. */
  | 'edited'
  /** Declined; the existing content stands. */
  | 'rejected'
  /** The target changed underneath it, so it can no longer be applied. */
  | 'superseded';

/** A review gesture available on a proposal. */
export type AuthoringProposalAction = 'accept' | 'edit' | 'reject' | 'regenerate';

/** Outcome of validating a generated example against its schema. */
export type AuthoringExampleValidation = {
  status: 'valid' | 'invalid' | 'not-applicable';
  /** Why validation failed. Required reading before accepting an invalid example. */
  message?: string;
};

/** Provenance of a generated proposal, shown so a reviewer can judge it. */
export type AuthoringProposalProvenance = {
  /** Model identifier, e.g. `claude-opus-4-8`. */
  model: string;
  /** Tenant policy the generation ran under, e.g. `Grounded-only`. */
  policy: string;
  /** ISO-8601 generation timestamp. */
  generatedAt: string;
};

/** One reviewable AI proposal. */
export type AuthoringProposal = {
  id: string;
  /** What the proposal is for, e.g. `Description for GET /pets`. */
  title: string;
  /** The generated text itself. */
  body: string;
  status: AuthoringProposalStatus;
  provenance: AuthoringProposalProvenance;
  citations: readonly AuthoringCitation[];
  /** Present when the proposal contains an example payload. */
  exampleValidation?: AuthoringExampleValidation;
  /** Existing content the proposal would replace, for a before/after view. */
  currentBody?: string;
};

/** How a status is described and toned. */
type ProposalStatusDescriptor = {
  label: string;
  description: string;
  tone: AuthoringTone;
  icon: string;
};

const STATUS: Record<AuthoringProposalStatus, ProposalStatusDescriptor> = {
  pending: {
    label: 'Proposed',
    description: 'Generated content awaiting your review. It is not saved.',
    tone: 'info',
    icon: 'Sparkles',
  },
  accepted: {
    label: 'Accepted',
    description: 'Applied as written. The content is now human-approved.',
    tone: 'success',
    icon: 'Check',
  },
  edited: {
    label: 'Accepted with edits',
    description: 'Applied after you changed it. Recorded as AI-edited.',
    tone: 'success',
    icon: 'PenTool',
  },
  rejected: {
    label: 'Rejected',
    description: 'Declined. The existing content is unchanged.',
    tone: 'neutral',
    icon: 'X',
  },
  superseded: {
    label: 'Superseded',
    description: 'The target changed since this was generated. Regenerate to review current text.',
    tone: 'warning',
    icon: 'RefreshCw',
  },
};

/**
 * Describe a proposal status.
 *
 * @param status - Proposal status.
 * @returns Its label, explanation, tone and icon name.
 */
export function describeAuthoringProposalStatus(
  status: AuthoringProposalStatus
): ProposalStatusDescriptor {
  return STATUS[status];
}

/**
 * Which review gestures a proposal currently offers.
 *
 * Only a pending proposal can be accepted, edited or rejected — offering
 * "Accept" on something already applied would let a reviewer double-apply it.
 * Regeneration stays available after a decision so a reviewer can ask for
 * another attempt, but not once the proposal was accepted: the content is then
 * human-owned and a silent regeneration would overwrite that decision.
 *
 * @param status - Current proposal status.
 * @returns The permitted actions, in display order.
 */
export function availableAuthoringProposalActions(
  status: AuthoringProposalStatus
): AuthoringProposalAction[] {
  switch (status) {
    case 'pending':
      return ['accept', 'edit', 'reject', 'regenerate'];
    case 'rejected':
    case 'superseded':
      return ['regenerate'];
    case 'accepted':
    case 'edited':
      return [];
  }
}

/**
 * True when accepting the proposal would apply an example known to be invalid.
 *
 * Callers use this to require an extra confirmation rather than to disable
 * acceptance outright: a reviewer may knowingly accept prose whose example
 * still needs work, but must not do so unaware.
 *
 * @param proposal - Proposal under review.
 */
export function authoringProposalNeedsExampleWarning(proposal: AuthoringProposal): boolean {
  return proposal.exampleValidation?.status === 'invalid';
}

/**
 * True when the proposal has no grounding in the source.
 *
 * @param proposal - Proposal under review.
 */
export function isAuthoringProposalUngrounded(proposal: AuthoringProposal): boolean {
  return proposal.citations.length === 0;
}
