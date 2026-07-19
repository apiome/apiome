/**
 * Check summarisation (UXE-1.3).
 *
 * The distinction this file exists to protect: "nothing failed" and "nothing
 * has finished" must never produce the same summary, because an operator who
 * confirms a publish against an unfinished run has confirmed against no
 * evidence at all.
 */

import {
  describeAuthoringCheckStatus,
  summarizeAuthoringChecks,
  type AuthoringCheck,
  type AuthoringCheckStatus,
} from '../../lib/authoring/checks';

/**
 * Build a check with sensible defaults.
 *
 * @param status - Outcome to record.
 * @param overrides - Fields to change, e.g. `blocking`.
 */
function check(status: AuthoringCheckStatus, overrides: Partial<AuthoringCheck> = {}): AuthoringCheck {
  return { id: `chk-${status}-${overrides.id ?? ''}`, label: status, status, blocking: false, ...overrides };
}

describe('summarizeAuthoringChecks', () => {
  it('reports an empty set without claiming success', () => {
    const summary = summarizeAuthoringChecks([]);

    expect(summary.total).toBe(0);
    expect(summary.label).toBe('No checks');
    expect(summary.blocked).toBe(false);
    expect(summary.description).not.toMatch(/passed/i);
  });

  it('counts each status independently', () => {
    const summary = summarizeAuthoringChecks([
      check('passed', { id: 'a' }),
      check('passed', { id: 'b' }),
      check('failed', { id: 'c' }),
      check('running', { id: 'd' }),
      check('pending', { id: 'e' }),
      check('skipped', { id: 'f' }),
    ]);

    expect(summary).toMatchObject({
      total: 6,
      passed: 2,
      failed: 1,
      running: 1,
      pending: 1,
      skipped: 1,
    });
  });

  it('reports an unfinished run as unfinished rather than as passing', () => {
    const summary = summarizeAuthoringChecks([check('passed', { id: 'a' }), check('running', { id: 'b' })]);

    expect(summary.settled).toBe(false);
    expect(summary.label).toBe('1 of 2 checks running');
    expect(summary.description).toMatch(/incomplete/i);
    expect(summary.label).not.toMatch(/passed/i);
  });

  it('treats a pending check as unfinished, not as skipped', () => {
    expect(summarizeAuthoringChecks([check('pending')]).settled).toBe(false);
  });

  it('blocks only when a required check fails', () => {
    const advisory = summarizeAuthoringChecks([check('failed', { blocking: false })]);
    const required = summarizeAuthoringChecks([check('failed', { blocking: true })]);

    expect(advisory.blocked).toBe(false);
    expect(advisory.description).toMatch(/can continue/i);
    expect(required.blocked).toBe(true);
    expect(required.description).toMatch(/blocked/i);
  });

  it('takes the tone of its worst member, so one failure is never softened', () => {
    const summary = summarizeAuthoringChecks([
      check('passed', { id: 'a' }),
      check('passed', { id: 'b' }),
      check('failed', { id: 'c' }),
    ]);

    expect(summary.tone).toBe('danger');
  });

  it('mentions skipped checks when everything applicable passed', () => {
    const summary = summarizeAuthoringChecks([
      check('passed', { id: 'a' }),
      check('skipped', { id: 'b' }),
    ]);

    expect(summary.blocked).toBe(false);
    expect(summary.description).toMatch(/1 were skipped|1 was skipped|skipped/i);
  });
});

describe('describeAuthoringCheckStatus', () => {
  it.each(['pending', 'running', 'passed', 'failed', 'skipped'] as AuthoringCheckStatus[])(
    'gives %s a text label, so the icon is never the only cue',
    (status) => {
      const descriptor = describeAuthoringCheckStatus(status);

      expect(descriptor.label).toBeTruthy();
      expect(descriptor.icon).toBeTruthy();
    }
  );
});
