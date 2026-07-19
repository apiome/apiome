/**
 * Phased progress summarisation (UXE-1.3).
 *
 * Roadmap section 27.3 requires status to remain understandable with animation
 * disabled, which makes the announcement — not the bar — the primary output.
 * The other property under test: percentage is derived from *finished* phases,
 * so a bar can never claim progress a phase has not made.
 */

import {
  AUTHORING_BUILD_PHASES,
  summarizeAuthoringProgress,
  describeAuthoringPhaseStatus,
  type AuthoringPhaseStatus,
  type AuthoringProgressPhase,
} from '../../lib/authoring/progress';

/**
 * Build a phase list from a list of statuses.
 *
 * @param statuses - Status per phase, in order.
 */
function phases(...statuses: AuthoringPhaseStatus[]): AuthoringProgressPhase[] {
  return statuses.map((status, index) => ({
    id: `p${index}`,
    label: `Phase ${index}`,
    status,
  }));
}

describe('summarizeAuthoringProgress', () => {
  it('reports an empty list without claiming completion', () => {
    const summary = summarizeAuthoringProgress([]);

    expect(summary).toMatchObject({ total: 0, percent: 0, done: false });
    expect(summary.announcement).toBe('No phases to report.');
  });

  it('reports zero percent before anything starts', () => {
    expect(summarizeAuthoringProgress(phases('pending', 'pending')).percent).toBe(0);
  });

  it('does not credit the active phase with progress it has not made', () => {
    // One of four finished while the second runs: 25%, not 50%.
    expect(
      summarizeAuthoringProgress(phases('complete', 'active', 'pending', 'pending')).percent
    ).toBe(25);
  });

  it('counts a skipped phase as finished, because it will never run', () => {
    expect(summarizeAuthoringProgress(phases('complete', 'skipped')).percent).toBe(100);
  });

  it('names the active phase and its live detail', () => {
    const summary = summarizeAuthoringProgress([
      { id: 'a', label: 'Resolving sources', status: 'complete' },
      { id: 'b', label: 'Rendering pages', detail: '482 of 640 pages', status: 'active' },
      { id: 'c', label: 'Uploading assets', status: 'pending' },
    ]);

    expect(summary.announcement).toBe('Step 2 of 3: Rendering pages. 482 of 640 pages.');
    expect(summary.activePhase?.id).toBe('b');
    expect(summary.tone).toBe('info');
  });

  it('stops at the failure rather than advancing to completion', () => {
    const summary = summarizeAuthoringProgress([
      { id: 'a', label: 'Resolving sources', status: 'complete' },
      { id: 'b', label: 'Validating contracts', detail: 'Unresolved $ref', status: 'failed' },
      { id: 'c', label: 'Rendering pages', status: 'pending' },
    ]);

    expect(summary.announcement).toBe('Failed at step 2 of 3: Validating contracts. Unresolved $ref.');
    expect(summary.tone).toBe('danger');
    expect(summary.percent).toBe(33);
    expect(summary.done).toBe(false);
  });

  it('prefers the failure over the active phase when both are present', () => {
    expect(summarizeAuthoringProgress(phases('failed', 'active')).announcement).toMatch(/^Failed/);
  });

  it('announces completion once every phase is finished', () => {
    const summary = summarizeAuthoringProgress(phases('complete', 'complete'));

    expect(summary).toMatchObject({ done: true, percent: 100, tone: 'success' });
    expect(summary.announcement).toBe('All 2 phases complete.');
  });

  it('produces an announcement readable without any animation', () => {
    // Every branch yields a sentence, so a reduced-motion user is never left
    // with a static bar and no words.
    const cases = [
      phases('pending'),
      phases('active'),
      phases('failed'),
      phases('complete'),
      [],
    ];

    cases.forEach((list) => {
      expect(summarizeAuthoringProgress(list).announcement.length).toBeGreaterThan(0);
    });
  });
});

describe('AUTHORING_BUILD_PHASES', () => {
  it('matches the phase vocabulary named in roadmap section 27.2', () => {
    expect(AUTHORING_BUILD_PHASES.map((phase) => phase.label)).toEqual([
      'Resolving sources',
      'Validating contracts',
      'Rendering pages',
      'Uploading assets',
      'Activating edge release',
    ]);
  });

  it('starts every phase pending, so the template describes nothing in flight', () => {
    expect(AUTHORING_BUILD_PHASES.every((phase) => phase.status === 'pending')).toBe(true);
  });
});

describe('describeAuthoringPhaseStatus', () => {
  it.each(['pending', 'active', 'complete', 'failed', 'skipped'] as AuthoringPhaseStatus[])(
    'gives %s a text label alongside its icon',
    (status) => {
      const descriptor = describeAuthoringPhaseStatus(status);

      expect(descriptor.label).toBeTruthy();
      expect(descriptor.icon).toBeTruthy();
    }
  );
});
