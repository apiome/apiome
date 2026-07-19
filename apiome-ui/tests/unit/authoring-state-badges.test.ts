/**
 * Authoring shell state badges (UXE-1.2).
 *
 * Covers the acceptance criterion that read-only, conflict, offline, unsaved,
 * loading and entitlement states are consistent, and the accessibility rule
 * that status is never conveyed by color alone.
 */

import {
  getAuthoringStateBadge,
  hasUrgentAuthoringState,
  resolveAuthoringStateBadges,
  IDLE_AUTHORING_STATE,
  type AuthoringStateId,
  type AuthoringStateInput,
} from '../../lib/authoring/state-badges';

/**
 * Resolve badges for a state built from the idle default.
 *
 * @param overrides - Fields to change.
 * @returns The resulting badge ids, in order.
 */
function idsFor(overrides: Partial<AuthoringStateInput> = {}): AuthoringStateId[] {
  return resolveAuthoringStateBadges({ ...IDLE_AUTHORING_STATE, ...overrides }).map((b) => b.id);
}

describe('resolveAuthoringStateBadges', () => {
  it('reports Saved when nothing is happening', () => {
    expect(idsFor()).toEqual(['saved']);
  });

  it('never returns an empty list, so the status region is never silent', () => {
    expect(resolveAuthoringStateBadges(IDLE_AUTHORING_STATE).length).toBeGreaterThan(0);
  });

  it.each([
    ['offline', { online: false }, 'offline'],
    ['conflict', { conflict: true }, 'conflict'],
    ['unentitled', { entitled: false }, 'unentitled'],
    ['read-only', { readOnly: true }, 'read-only'],
    ['unsaved', { unsavedChanges: true }, 'unsaved'],
    ['saving', { saving: true }, 'saving'],
    ['loading', { loading: true }, 'loading'],
  ] as Array<[string, Partial<AuthoringStateInput>, AuthoringStateId]>)(
    'surfaces the %s state',
    (_name, overrides, expected) => {
      expect(idsFor(overrides)).toContain(expected);
    }
  );

  it('suppresses the save pipeline while offline, so it cannot claim to be saving', () => {
    expect(idsFor({ online: false, saving: true, unsavedChanges: true })).toEqual(['offline']);
  });

  it('suppresses the save pipeline during a conflict', () => {
    expect(idsFor({ conflict: true, unsavedChanges: true })).toEqual(['conflict']);
  });

  it('still explains read-only and entitlement while blocked', () => {
    expect(idsFor({ online: false, readOnly: true, entitled: false })).toEqual([
      'offline',
      'unentitled',
      'read-only',
    ]);
  });

  it('shows at most one save-pipeline badge', () => {
    const pipeline: AuthoringStateId[] = ['unsaved', 'saving', 'loading', 'saved'];
    const ids = idsFor({ unsavedChanges: true, saving: true, loading: true });
    expect(ids.filter((id) => pipeline.includes(id))).toEqual(['unsaved']);
  });

  it('prefers unsaved over saving, and saving over loading', () => {
    expect(idsFor({ unsavedChanges: true, saving: true })).toEqual(['unsaved']);
    expect(idsFor({ saving: true, loading: true })).toEqual(['saving']);
  });

  it('orders blocking states before advisory ones', () => {
    expect(idsFor({ conflict: true, readOnly: true })).toEqual(['conflict', 'read-only']);
  });
});

describe('badge descriptors', () => {
  const ids: AuthoringStateId[] = [
    'offline',
    'conflict',
    'unentitled',
    'read-only',
    'unsaved',
    'saving',
    'loading',
    'saved',
  ];

  it.each(ids)('%s carries a label, an icon and an explanation', (id) => {
    const badge = getAuthoringStateBadge(id);
    expect(badge.label.length).toBeGreaterThan(0);
    // An icon plus a text label is what keeps status from being color-only.
    expect(badge.icon.length).toBeGreaterThan(0);
    expect(badge.description.length).toBeGreaterThan(0);
  });

  it('marks only the interrupting states urgent', () => {
    expect(hasUrgentAuthoringState(resolveAuthoringStateBadges(IDLE_AUTHORING_STATE))).toBe(false);
    expect(
      hasUrgentAuthoringState(
        resolveAuthoringStateBadges({ ...IDLE_AUTHORING_STATE, conflict: true })
      )
    ).toBe(true);
  });
});
