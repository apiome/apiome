/**
 * Impact-sheet gating (UXE-1.3).
 *
 * This is the safety-critical module in the ticket. Roadmap section 27.2
 * replaces generic confirmations with impact sheets, and the gate below is what
 * makes that more than cosmetic: friction scales with consequence, and
 * confirmation is impossible while the evidence is incomplete.
 */

import type { AuthoringCheck } from '../../lib/authoring/checks';
import {
  describeAuthoringImpactAction,
  gateAuthoringImpact,
  summarizeAuthoringImpact,
  type AuthoringImpactAction,
  type AuthoringImpactSheet,
} from '../../lib/authoring/impact';

const PASSING: AuthoringCheck[] = [
  { id: 'chk-1', label: 'Contract lint', status: 'passed', blocking: true },
];
const RUNNING: AuthoringCheck[] = [
  { id: 'chk-1', label: 'Contract lint', status: 'running', blocking: true },
];
const BLOCKING_FAILURE: AuthoringCheck[] = [
  { id: 'chk-1', label: 'Contract lint', status: 'failed', blocking: true },
];
const ADVISORY_FAILURE: AuthoringCheck[] = [
  { id: 'chk-1', label: 'Link check', status: 'failed', blocking: false },
];

/**
 * Build an impact sheet with sensible defaults.
 *
 * @param overrides - Fields to change, e.g. `severity` or `checks`.
 */
function sheet(overrides: Partial<AuthoringImpactSheet> = {}): AuthoringImpactSheet {
  return {
    action: 'promote',
    severity: 'routine',
    target: 'r-4821',
    environment: 'production',
    checks: PASSING,
    effects: [
      {
        id: 'eff-1',
        label: 'docs.example.com',
        detail: 'Serves r-4821 instead of r-4820.',
        tone: 'info',
        scope: '640 pages',
      },
    ],
    ...overrides,
  };
}

describe('gateAuthoringImpact', () => {
  it('allows a routine action whose checks all passed', () => {
    expect(gateAuthoringImpact(sheet(), { acknowledged: false })).toMatchObject({
      canConfirm: true,
    });
  });

  it('blocks while any check is unfinished, so nothing is confirmed against partial evidence', () => {
    const gate = gateAuthoringImpact(sheet({ checks: RUNNING }), { acknowledged: true });

    expect(gate.canConfirm).toBe(false);
    expect(gate.block?.reason).toBe('checks-running');
  });

  it('blocks on a required check failure', () => {
    const gate = gateAuthoringImpact(sheet({ checks: BLOCKING_FAILURE }), { acknowledged: true });

    expect(gate.canConfirm).toBe(false);
    expect(gate.block?.reason).toBe('checks-failed');
  });

  it('allows the action through an advisory failure, which warns rather than blocks', () => {
    expect(
      gateAuthoringImpact(sheet({ checks: ADVISORY_FAILURE }), { acknowledged: false }).canConfirm
    ).toBe(true);
  });

  it('prefers the failure message over the running one when both would apply', () => {
    const gate = gateAuthoringImpact(
      sheet({ checks: [...BLOCKING_FAILURE, ...RUNNING] }),
      { acknowledged: true }
    );

    expect(gate.block?.reason).toBe('checks-failed');
  });

  it('requires an acknowledgement for a notable action', () => {
    const unacknowledged = gateAuthoringImpact(sheet({ severity: 'notable' }), {
      acknowledged: false,
    });

    expect(unacknowledged.canConfirm).toBe(false);
    expect(unacknowledged.block?.reason).toBe('acknowledgement-required');
    expect(
      gateAuthoringImpact(sheet({ severity: 'notable' }), { acknowledged: true }).canConfirm
    ).toBe(true);
  });

  it('requires the target to be typed for an irreversible action', () => {
    const irreversible = sheet({ severity: 'irreversible', target: 'docs.example.com' });

    expect(gateAuthoringImpact(irreversible, { acknowledged: true }).block?.reason).toBe(
      'phrase-required'
    );
    expect(
      gateAuthoringImpact(irreversible, { acknowledged: false, typedPhrase: 'docs.example.com' })
        .canConfirm
    ).toBe(true);
  });

  it('uses an explicit confirmation phrase in preference to the target', () => {
    const irreversible = sheet({
      severity: 'irreversible',
      target: 'r-4821',
      confirmationPhrase: 'PURGE PRODUCTION',
    });

    expect(gateAuthoringImpact(irreversible, { acknowledged: true, typedPhrase: 'r-4821' }).canConfirm).toBe(
      false
    );
    expect(
      gateAuthoringImpact(irreversible, { acknowledged: true, typedPhrase: 'PURGE PRODUCTION' })
        .canConfirm
    ).toBe(true);
  });

  it('tolerates surrounding whitespace in the typed phrase but not a wrong one', () => {
    const irreversible = sheet({ severity: 'irreversible', target: 'docs.example.com' });

    expect(
      gateAuthoringImpact(irreversible, { acknowledged: true, typedPhrase: '  docs.example.com ' })
        .canConfirm
    ).toBe(true);
    expect(
      gateAuthoringImpact(irreversible, { acknowledged: true, typedPhrase: 'docs.example.co' })
        .canConfirm
    ).toBe(false);
  });

  it('does not let an acknowledgement substitute for the typed phrase', () => {
    expect(
      gateAuthoringImpact(sheet({ severity: 'irreversible' }), { acknowledged: true }).canConfirm
    ).toBe(false);
  });

  it('always states a reason when it blocks, so no control is disabled silently', () => {
    const blocked = [
      gateAuthoringImpact(sheet({ checks: RUNNING }), { acknowledged: false }),
      gateAuthoringImpact(sheet({ checks: BLOCKING_FAILURE }), { acknowledged: false }),
      gateAuthoringImpact(sheet({ severity: 'notable' }), { acknowledged: false }),
      gateAuthoringImpact(sheet({ severity: 'irreversible' }), { acknowledged: false }),
    ];

    blocked.forEach((gate) => {
      expect(gate.canConfirm).toBe(false);
      expect(gate.block?.message).toBeTruthy();
    });
  });

  it('takes the worst tone across checks and effects', () => {
    const gate = gateAuthoringImpact(
      sheet({
        effects: [
          { id: 'e1', label: 'Cache', detail: 'Discarded everywhere.', tone: 'danger' },
        ],
      }),
      { acknowledged: true }
    );

    expect(gate.tone).toBe('danger');
  });
});

describe('summarizeAuthoringImpact', () => {
  it('names the action, target, environment and scope', () => {
    const summary = summarizeAuthoringImpact(sheet());

    expect(summary).toContain('Promote to production');
    expect(summary).toContain('r-4821');
    expect(summary).toContain('production');
    expect(summary).toContain('640 pages');
  });

  it('warns that an irreversible action cannot be undone', () => {
    expect(summarizeAuthoringImpact(sheet({ severity: 'irreversible' }))).toMatch(
      /cannot be undone/i
    );
  });

  it('omits the irreversibility warning for reversible actions', () => {
    expect(summarizeAuthoringImpact(sheet({ severity: 'routine' }))).not.toMatch(/cannot be undone/i);
  });
});

describe('describeAuthoringImpactAction', () => {
  it.each(['publish', 'promote', 'rollback', 'purge', 'delete'] as AuthoringImpactAction[])(
    'gives %s a specific verb rather than a generic confirm label',
    (action) => {
      const { title, confirm } = describeAuthoringImpactAction(action);

      expect(title).toBeTruthy();
      expect(confirm).toBeTruthy();
      expect(confirm.toLowerCase()).not.toBe('ok');
    }
  );
});
