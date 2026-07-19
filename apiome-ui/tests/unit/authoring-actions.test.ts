/**
 * Command actions and selection summaries (UXE-1.3).
 *
 * Roadmap section 27.2 forbids dead ends, which in practice means a disabled
 * control must say why. The type makes `disabledReason` the only way to disable
 * an action; these tests hold the gating helpers to the same rule.
 */

import {
  gateAuthoringBulkActions,
  isAuthoringActionDisabled,
  summarizeAuthoringSelection,
  type AuthoringCommandAction,
} from '../../lib/authoring/actions';

const ACTIONS: AuthoringCommandAction[] = [
  { id: 'regenerate', label: 'Regenerate', variant: 'secondary' },
  { id: 'review', label: 'Request review', variant: 'primary' },
];

describe('isAuthoringActionDisabled', () => {
  it('is disabled exactly when a reason is present', () => {
    expect(isAuthoringActionDisabled(ACTIONS[0])).toBe(false);
    expect(isAuthoringActionDisabled({ ...ACTIONS[0], disabledReason: 'Read only.' })).toBe(true);
  });
});

describe('gateAuthoringBulkActions', () => {
  it('leaves actions alone when something is selected', () => {
    expect(gateAuthoringBulkActions(ACTIONS, 3, 'page')).toEqual(ACTIONS);
  });

  it('disables every action with a stated reason when nothing is selected', () => {
    const gated = gateAuthoringBulkActions(ACTIONS, 0, 'page');

    gated.forEach((action) => {
      expect(isAuthoringActionDisabled(action)).toBe(true);
      expect(action.disabledReason).toBe('Select at least one page first.');
    });
  });

  it('uses the caller noun, so the reason names the right thing', () => {
    expect(gateAuthoringBulkActions(ACTIONS, 0, 'release')[0].disabledReason).toContain('release');
  });

  it('keeps a more specific existing reason rather than overwriting it', () => {
    const [gated] = gateAuthoringBulkActions(
      [{ ...ACTIONS[0], disabledReason: 'Export needs the hosted plan.' }],
      0,
      'page'
    );

    expect(gated.disabledReason).toBe('Export needs the hosted plan.');
  });

  it('does not mutate the actions it was given', () => {
    const original = [...ACTIONS];
    gateAuthoringBulkActions(ACTIONS, 0, 'page');

    expect(ACTIONS).toEqual(original);
  });
});

describe('summarizeAuthoringSelection', () => {
  it('names the noun in the announcement, so a count is never heard bare', () => {
    expect(summarizeAuthoringSelection(3, 24, 'page').announcement).toBe('3 pages selected of 24.');
  });

  it('uses singular wording for one item', () => {
    expect(summarizeAuthoringSelection(1, 24, 'page').announcement).toBe('1 page selected of 24.');
  });

  it('reports an empty selection plainly', () => {
    expect(summarizeAuthoringSelection(0, 24, 'page')).toMatchObject({
      count: 0,
      all: false,
      announcement: 'No pages selected.',
    });
  });

  it('detects a complete selection', () => {
    expect(summarizeAuthoringSelection(24, 24, 'page').all).toBe(true);
  });

  it('does not call an empty list fully selected', () => {
    expect(summarizeAuthoringSelection(0, 0, 'page').all).toBe(false);
  });
});
