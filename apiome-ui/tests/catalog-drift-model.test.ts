/**
 * The catalog drift rules (MFI-31.3, #4400): wording, the event the "What changed" panel opens on,
 * the banner's deep link, the settings summary, and the BFF calls' error handling.
 */

import {
  DEFAULT_DRIFT_SETTINGS,
  driftBadgeLabel,
  driftBadgeTitle,
  driftBannerTitle,
  driftComparePair,
  driftCountsText,
  driftPrunedNote,
  driftSettingsSummary,
  driftVersionsSearch,
  DRIFT_SEVERITY_VIEW,
  fetchDriftEvents,
  saveDriftSettings,
  selectDriftEvent,
  type CatalogDriftBadgeData,
  type CatalogDriftEvent,
} from '../src/app/components/ade/catalog/catalogDriftModel';
import { catalogDetailActions, catalogDetailTabSearch } from '../src/app/components/ade/catalog/detail/catalogItemView';

const BADGE: CatalogDriftBadgeData = {
  eventId: 'e-1',
  severity: 'breaking',
  versionId: 'v-2',
  versionLabel: '2026-10-28T12:00Z',
  changeCount: 3,
  counts: { safe: 2, dangerous: 0, breaking: 1 },
  trigger: 'sweep',
  detectedAt: '2026-10-28T12:00:00Z',
  link: '/ade/dashboard/catalog/item-1?tab=versions&drift=e-1',
};

function event(id: string, dismissed = false): CatalogDriftEvent {
  return {
    ...BADGE,
    eventId: id,
    parentVersionId: 'v-1',
    parentVersionLabel: '1.0.0',
    notification: 'sent',
    notifiedAt: null,
    dismissedAt: dismissed ? '2026-10-28T13:00:00Z' : null,
    changes: [],
  };
}

describe('wording', () => {
  it('maps each severity to a tone', () => {
    expect(DRIFT_SEVERITY_VIEW.breaking.tone).toBe('danger');
    expect(DRIFT_SEVERITY_VIEW.dangerous.tone).toBe('warn');
    expect(DRIFT_SEVERITY_VIEW.safe.tone).toBe('ok');
  });

  it('labels, counts and titles', () => {
    expect(driftBadgeLabel('dangerous')).toBe('Dangerous drift');
    expect(driftCountsText(BADGE.counts)).toBe('1 breaking · 2 safe');
    expect(driftCountsText({})).toBe('No changes');
    expect(driftBadgeTitle(BADGE)).toBe('The live API changed in 2026-10-28T12:00Z: 1 breaking · 2 safe');
    expect(driftBannerTitle(BADGE)).toBe('Live refresh found breaking changes in version 2026-10-28T12:00Z');
    expect(driftBannerTitle({ ...BADGE, severity: 'safe' })).toBe(
      'Live refresh found safe changes in version 2026-10-28T12:00Z',
    );
  });
});

describe('selectDriftEvent', () => {
  it('prefers the requested event, then the newest open one, then the newest', () => {
    const list = [event('e-3', true), event('e-2'), event('e-1')];
    expect(selectDriftEvent(list, 'e-1')?.eventId).toBe('e-1');
    expect(selectDriftEvent(list, null)?.eventId).toBe('e-2');
    expect(selectDriftEvent(list, 'missing')?.eventId).toBe('e-2');
    expect(selectDriftEvent([event('e-9', true)], null)?.eventId).toBe('e-9');
    expect(selectDriftEvent([], 'e-1')).toBeNull();
  });
});

describe('the address', () => {
  it('opens the Versions pane on a drift, keeping unrelated params', () => {
    expect(driftVersionsSearch('?identityGroupId=g', 'e-1')).toBe('?identityGroupId=g&tab=versions&drift=e-1');
  });

  it('drops ?drift= when the reader leaves the Versions pane, and keeps it on Versions', () => {
    expect(catalogDetailTabSearch('?tab=versions&drift=e-1', 'lint')).toBe('?tab=lint');
    expect(catalogDetailTabSearch('?tab=lint&drift=e-1', 'versions')).toBe('?tab=versions&drift=e-1');
  });
});

describe('dismissDrift permission', () => {
  it('needs projects:edit on a live item', () => {
    const live = { deleted_at: null, sourceFormat: 'graphql', conversion: null };
    expect(catalogDetailActions(live).dismissDrift.shown).toBe(true);
    expect(catalogDetailActions(live, (p) => p !== 'projects:edit').dismissDrift.shown).toBe(false);
    expect(catalogDetailActions({ ...live, deleted_at: '2026-10-01' }).dismissDrift.shown).toBe(false);
  });
});

describe('driftSettingsSummary', () => {
  it('describes the defaults', () => {
    expect(driftSettingsSummary(DEFAULT_DRIFT_SETTINGS)).toBe(
      'Breaking and dangerous drift is announced right away; safe drift only shows a badge.',
    );
  });

  it('describes a digest that still sends breaking drift right away', () => {
    expect(driftSettingsSummary({ ...DEFAULT_DRIFT_SETTINGS, delivery: 'daily_digest', notifySafe: true })).toBe(
      'Breaking, dangerous and safe drift is announced in a daily digest (breaking drift right away).',
    );
  });

  it('describes nothing announced', () => {
    expect(
      driftSettingsSummary({ ...DEFAULT_DRIFT_SETTINGS, notifyBreaking: false, notifyDangerous: false }),
    ).toBe('No drift is announced; every drift only shows a badge.');
  });
});

describe('BFF calls', () => {
  afterEach(() => jest.restoreAllMocks());

  it('reads events and surfaces a refusal message', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ events: [event('e-1')] }) })
      .mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({ success: false, error: 'Catalog item not found' }) }) as unknown as typeof fetch;
    expect((await fetchDriftEvents('item-1'))[0].eventId).toBe('e-1');
    await expect(fetchDriftEvents('item-1')).rejects.toThrow('Catalog item not found');
  });

  it('saves only the settings fields', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => DEFAULT_DRIFT_SETTINGS });
    global.fetch = fetchMock as unknown as typeof fetch;
    await saveDriftSettings({ ...DEFAULT_DRIFT_SETTINGS, configured: true, updatedAt: 'x' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/catalog/drift-notifications');
    expect(init.method).toBe('PUT');
    expect(Object.keys(JSON.parse(init.body))).toEqual([
      'notifyBreaking',
      'notifyDangerous',
      'notifySafe',
      'delivery',
      'breakingImmediate',
      'emailEnabled',
    ]);
  });
});


describe('pruned baselines (MFI-31.5)', () => {
  it('compares against the version REST names, else the parent', () => {
    expect(driftComparePair(event('e-1'))).toEqual({ base: 'v-1', head: 'v-2' });
    expect(driftComparePair({ ...event('e-1'), compareBaseVersionId: 'v-0' })).toEqual({ base: 'v-0', head: 'v-2' });
    expect(driftComparePair({ ...event('e-1'), compareBaseVersionId: null })).toBeNull();
  });

  it('explains a pruned baseline', () => {
    expect(driftPrunedNote(event('e-1'))).toBeNull();
    const pruned = { ...event('e-1'), parentVersionPruned: true, compareBaseVersionId: 'v-0', compareBaseVersionLabel: '0.9.0' };
    expect(driftPrunedNote(pruned)).toBe('Version 1.0.0 was pruned by version retention; comparing with 0.9.0.');
    expect(driftPrunedNote({ ...pruned, compareBaseVersionId: null, compareBaseVersionLabel: null })).toBe(
      'Version 1.0.0 was pruned by version retention, and no earlier version is kept to compare with.',
    );
  });
});
