'use client';

/**
 * The AI proposal card (UXE-1.3).
 *
 * This is the primitive the mockups repeat most, and the one with the highest
 * cost of divergence. §27.2's rule — "AI proposals are never confused with
 * saved content" — is enforced three ways here rather than by convention:
 *
 * 1. The card is an `<article>` with a status chip naming its state, so a
 *    pending proposal is visibly and semantically not content.
 * 2. Its actions come from `availableAuthoringProposalActions`, so an already
 *    accepted proposal offers no way to be accepted twice.
 * 3. Ungrounded text and invalid examples are surfaced as warnings before the
 *    Accept button, not after it.
 */

import * as React from 'react';
import type { AuthoringCommandAction } from '@lib/authoring/actions';
import {
  authoringProposalNeedsExampleWarning,
  availableAuthoringProposalActions,
  describeAuthoringProposalStatus,
  isAuthoringProposalUngrounded,
  type AuthoringProposal,
  type AuthoringProposalAction,
} from '@lib/authoring/proposals';
import { cn } from '@lib/utils';
import {
  authoringAccentRuleClass,
  authoringMonoClass,
  authoringMutedTextClass,
  authoringSectionTitleClass,
  authoringSurfaceClass,
  authoringToneHookClass,
  authoringToneSurfaceClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';
import AuthoringActionButton from './AuthoringActionButton';
import AuthoringCitationList from './AuthoringCitationList';
import AuthoringToneBadge from './AuthoringToneBadge';

/** Presentation of each review gesture. */
const ACTION_DESCRIPTORS: Record<
  AuthoringProposalAction,
  Omit<AuthoringCommandAction, 'disabledReason'>
> = {
  accept: { id: 'accept', label: 'Accept', icon: 'Check', variant: 'primary' },
  edit: { id: 'edit', label: 'Edit', icon: 'PenTool', variant: 'secondary' },
  reject: { id: 'reject', label: 'Reject', icon: 'X', variant: 'secondary' },
  regenerate: { id: 'regenerate', label: 'Regenerate', icon: 'RefreshCw', variant: 'ghost' },
};

/** Props for {@link AuthoringProposalCard}. */
export type AuthoringProposalCardProps = {
  proposal: AuthoringProposal;
  /** Invoked with the chosen gesture. */
  onAction: (action: AuthoringProposalAction, proposalId: string) => void;
  /**
   * True when the current scope cannot be edited. Every applying gesture is
   * then disabled with that as the stated reason, rather than the card being
   * hidden — a read-only reviewer should still be able to read the proposal.
   */
  readOnly?: boolean;
  className?: string;
};

/**
 * Render one reviewable proposal.
 *
 * @param props - The proposal, its handler and the read-only flag.
 */
export default function AuthoringProposalCard({
  proposal,
  onAction,
  readOnly = false,
  className,
}: AuthoringProposalCardProps) {
  const headingId = React.useId();
  const status = describeAuthoringProposalStatus(proposal.status);
  const ungrounded = isAuthoringProposalUngrounded(proposal);
  const badExample = authoringProposalNeedsExampleWarning(proposal);

  const actions: AuthoringCommandAction[] = availableAuthoringProposalActions(proposal.status).map(
    (id) => ({
      ...ACTION_DESCRIPTORS[id],
      // Regeneration only reads the source, so it survives read-only scope;
      // everything that would write does not.
      disabledReason:
        readOnly && id !== 'regenerate'
          ? 'This scope is read only. Select a draft version to apply proposals.'
          : undefined,
    })
  );

  return (
    <article
      className={cn(
        authoringSurfaceClass,
        // Violet marks this as Scribe's, which is ownership, not status. The
        // status chip beside it carries the semantic tone.
        authoringAccentRuleClass.scribe,
        'flex flex-col gap-3 p-4',
        className
      )}
      aria-labelledby={headingId}
      data-proposal-id={proposal.id}
      data-proposal-status={proposal.status}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 id={headingId} className={authoringSectionTitleClass}>
            {proposal.title}
          </h3>
          <p className={authoringMonoClass}>
            {proposal.provenance.model} · {proposal.provenance.policy} ·{' '}
            {proposal.provenance.generatedAt}
          </p>
        </div>

        <AuthoringToneBadge
          label={status.label}
          tone={status.tone}
          icon={status.icon}
          description={status.description}
        />
      </header>

      {proposal.currentBody !== undefined ? (
        <section aria-label="Current content">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Current
          </h4>
          <p className={cn(authoringMutedTextClass, 'line-through decoration-gray-400')}>
            {proposal.currentBody}
          </p>
        </section>
      ) : null}

      <section aria-label="Proposed content">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Proposed
        </h4>
        <p className="text-sm text-gray-900 dark:text-gray-100">{proposal.body}</p>
      </section>

      {badExample ? (
        <p
          role="note"
          className={cn(
            'flex items-start gap-2 rounded-lg border p-2 text-sm text-rose-800 dark:text-rose-200',
            authoringToneSurfaceClass.danger,
            authoringToneHookClass.danger
          )}
        >
          <AuthoringIcon name="TriangleAlert" className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The generated example does not validate against its schema.
            {proposal.exampleValidation?.message ? ` ${proposal.exampleValidation.message}` : ''}
          </span>
        </p>
      ) : null}

      <AuthoringCitationList citations={proposal.citations} />

      {actions.length > 0 ? (
        <footer className="flex flex-wrap items-start gap-2">
          {actions.map((action) => (
            <AuthoringActionButton
              key={action.id}
              action={action}
              onAction={(id) => onAction(id as AuthoringProposalAction, proposal.id)}
            />
          ))}
          {ungrounded ? (
            <span className="self-center text-xs text-amber-700 dark:text-amber-300">
              Verify before accepting: no sources cited.
            </span>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}
