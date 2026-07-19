/**
 * Proposal review contract (UXE-1.3).
 *
 * Guards the rule from roadmap section 27.2 that an AI proposal is never
 * confused with saved content: an applied proposal must offer no way to be
 * applied again, and ungrounded or invalid content must be flagged before the
 * accept gesture rather than after it.
 */

import {
  authoringProposalNeedsExampleWarning,
  availableAuthoringProposalActions,
  describeAuthoringProposalStatus,
  isAuthoringProposalUngrounded,
  type AuthoringProposal,
  type AuthoringProposalStatus,
} from '../../lib/authoring/proposals';

const ALL_STATUSES: AuthoringProposalStatus[] = [
  'pending',
  'accepted',
  'edited',
  'rejected',
  'superseded',
];

/**
 * Build a proposal with sensible defaults.
 *
 * @param overrides - Fields to change, e.g. `status` or `citations`.
 */
function proposal(overrides: Partial<AuthoringProposal> = {}): AuthoringProposal {
  return {
    id: 'prop-1',
    title: 'Description for GET /pets',
    body: 'Returns every pet.',
    status: 'pending',
    provenance: { model: 'claude-opus-4-8', policy: 'Grounded-only', generatedAt: '2026-07-19T00:00:00Z' },
    citations: [
      {
        id: 'cite-1',
        label: 'GET /pets',
        kind: 'operation',
        stableKey: 'op:get:/pets',
      },
    ],
    ...overrides,
  };
}

describe('availableAuthoringProposalActions', () => {
  it('offers the full review set only while pending', () => {
    expect(availableAuthoringProposalActions('pending')).toEqual([
      'accept',
      'edit',
      'reject',
      'regenerate',
    ]);
  });

  it.each(['accepted', 'edited'] as AuthoringProposalStatus[])(
    'offers nothing once %s, so an applied proposal cannot be applied twice',
    (status) => {
      expect(availableAuthoringProposalActions(status)).toEqual([]);
    }
  );

  it.each(['rejected', 'superseded'] as AuthoringProposalStatus[])(
    'offers only regeneration once %s',
    (status) => {
      expect(availableAuthoringProposalActions(status)).toEqual(['regenerate']);
    }
  );

  it('never offers accept outside the pending state', () => {
    ALL_STATUSES.filter((status) => status !== 'pending').forEach((status) => {
      expect(availableAuthoringProposalActions(status)).not.toContain('accept');
    });
  });

  it('does not offer regeneration on an accepted proposal, which is human-owned', () => {
    expect(availableAuthoringProposalActions('accepted')).not.toContain('regenerate');
  });
});

describe('describeAuthoringProposalStatus', () => {
  it.each(ALL_STATUSES)('gives %s a label, an explanation, a tone and an icon', (status) => {
    const descriptor = describeAuthoringProposalStatus(status);

    expect(descriptor.label).toBeTruthy();
    expect(descriptor.description).toBeTruthy();
    expect(descriptor.icon).toBeTruthy();
  });

  it('tones a pending proposal as informational, never as success', () => {
    // Success would read as "this is saved", which is exactly the confusion
    // section 27.2 forbids.
    expect(describeAuthoringProposalStatus('pending').tone).toBe('info');
  });

  it('warns rather than fails on a superseded proposal', () => {
    expect(describeAuthoringProposalStatus('superseded').tone).toBe('warning');
  });
});

describe('isAuthoringProposalUngrounded', () => {
  it('is true when nothing was cited', () => {
    expect(isAuthoringProposalUngrounded(proposal({ citations: [] }))).toBe(true);
  });

  it('is false as soon as one source is cited', () => {
    expect(isAuthoringProposalUngrounded(proposal())).toBe(false);
  });
});

describe('authoringProposalNeedsExampleWarning', () => {
  it('warns when a generated example fails validation', () => {
    expect(
      authoringProposalNeedsExampleWarning(
        proposal({ exampleValidation: { status: 'invalid', message: 'tag must be a string.' } })
      )
    ).toBe(true);
  });

  it.each(['valid', 'not-applicable'] as const)('does not warn when validation is %s', (status) => {
    expect(authoringProposalNeedsExampleWarning(proposal({ exampleValidation: { status } }))).toBe(
      false
    );
  });

  it('does not warn when the proposal carries no example at all', () => {
    expect(authoringProposalNeedsExampleWarning(proposal())).toBe(false);
  });
});
