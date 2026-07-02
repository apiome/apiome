import {
  getRefreshStatusPresentation,
  refreshStatusChipToneClasses,
  type RefreshStatusCode,
} from '@/app/components/ade/dashboard/repositories/repository-refresh-status-chip-copy';

describe('getRefreshStatusPresentation', () => {
  const cases: Array<[RefreshStatusCode, string]> = [
    ['up-to-date', 'Up to date'],
    ['stale', 'Stale'],
    ['refreshing', 'Refreshing'],
    ['failed', 'Failed'],
    ['diverged', 'Diverged'],
  ];

  test.each(cases)('maps %s to its label and tone', (code, label) => {
    const p = getRefreshStatusPresentation(code);
    expect(p.label).toBe(label);
    expect(p.tone).toBe(code);
    expect(p.description.length).toBeGreaterThan(0);
  });

  test('falls back to up-to-date for unknown codes', () => {
    expect(getRefreshStatusPresentation('bogus').tone).toBe('up-to-date');
    expect(getRefreshStatusPresentation('bogus').label).toBe('Up to date');
  });

  test('falls back to up-to-date for null/undefined', () => {
    expect(getRefreshStatusPresentation(null).tone).toBe('up-to-date');
    expect(getRefreshStatusPresentation(undefined).tone).toBe('up-to-date');
  });
});

describe('refreshStatusChipToneClasses', () => {
  test('every tone yields a distinct, non-empty class string', () => {
    const tones: RefreshStatusCode[] = [
      'up-to-date',
      'stale',
      'refreshing',
      'failed',
      'diverged',
    ];
    const classStrings = tones.map(refreshStatusChipToneClasses);
    classStrings.forEach((c) => expect(c).toContain('inline-flex'));
    expect(new Set(classStrings).size).toBe(tones.length);
  });
});
