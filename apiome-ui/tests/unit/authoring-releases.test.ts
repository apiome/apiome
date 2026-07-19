/**
 * Release lifecycle and the promote/rollback contract (UXE-1.3).
 *
 * The rule under test is from roadmap section 28.3: promotion changes routing
 * to an *already built* artifact. A release with nothing built therefore cannot
 * be promotable, and only the release actually serving traffic can be rolled
 * back.
 */

import {
  canPromoteAuthoringRelease,
  canRollbackAuthoringRelease,
  describeAuthoringRelease,
  isAuthoringReleaseTransient,
  type AuthoringReleaseStatus,
} from '../../lib/authoring/releases';

const ALL_STATUSES: AuthoringReleaseStatus[] = [
  'queued',
  'building',
  'ready',
  'review',
  'active',
  'superseded',
  'failed',
  'rolled-back',
];

describe('describeAuthoringRelease', () => {
  it.each(ALL_STATUSES)('gives %s a label, an explanation, a tone and an icon', (status) => {
    const descriptor = describeAuthoringRelease(status);

    expect(descriptor.label).toBeTruthy();
    expect(descriptor.description).toBeTruthy();
    expect(descriptor.icon).toBeTruthy();
  });

  it('tones only a failure as danger', () => {
    const danger = ALL_STATUSES.filter((status) => describeAuthoringRelease(status).tone === 'danger');

    expect(danger).toEqual(['failed']);
  });

  it('distinguishes rolled-back from failed, which are different events', () => {
    expect(describeAuthoringRelease('rolled-back').tone).toBe('warning');
    expect(describeAuthoringRelease('failed').tone).toBe('danger');
  });
});

describe('canPromoteAuthoringRelease', () => {
  it.each(['ready', 'superseded', 'rolled-back'] as AuthoringReleaseStatus[])(
    'allows promoting %s, which has a built artifact to route to',
    (status) => {
      expect(canPromoteAuthoringRelease(status)).toBe(true);
    }
  );

  it.each(['queued', 'building', 'failed'] as AuthoringReleaseStatus[])(
    'refuses to promote %s, which has no built artifact',
    (status) => {
      expect(canPromoteAuthoringRelease(status)).toBe(false);
    }
  );

  it('refuses to promote a release still awaiting approval', () => {
    expect(canPromoteAuthoringRelease('review')).toBe(false);
  });

  it('refuses to promote the release already serving traffic', () => {
    expect(canPromoteAuthoringRelease('active')).toBe(false);
  });
});

describe('canRollbackAuthoringRelease', () => {
  it('allows rollback only from the active release', () => {
    const rollbackable = ALL_STATUSES.filter(canRollbackAuthoringRelease);

    expect(rollbackable).toEqual(['active']);
  });
});

describe('isAuthoringReleaseTransient', () => {
  it('marks exactly the in-flight states, so only those rows poll', () => {
    const transient = ALL_STATUSES.filter(isAuthoringReleaseTransient);

    expect(transient).toEqual(['queued', 'building']);
  });
});
