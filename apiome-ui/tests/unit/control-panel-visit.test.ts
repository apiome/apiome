/**
 * The launcher's "last opened" stamp (HIVE-12.5, #5612): device-local, silent on failure.
 */
import {
  CONTROL_PANEL_VISIT_STORAGE_KEY,
  readControlPanelVisit,
  recordControlPanelVisit,
} from '../../src/app/components/shell/controlPanelVisit';

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('controlPanelVisit', () => {
  it('round-trips a visit', () => {
    recordControlPanelVisit(1_760_000_000_000);
    expect(window.localStorage.getItem(CONTROL_PANEL_VISIT_STORAGE_KEY)).toBe('1760000000000');
    expect(readControlPanelVisit()).toBe(1_760_000_000_000);
  });

  it('defaults to now', () => {
    const before = Date.now();
    recordControlPanelVisit();
    const at = readControlPanelVisit()!;
    expect(at).toBeGreaterThanOrEqual(before);
    expect(at).toBeLessThanOrEqual(Date.now());
  });

  it('reads nothing when nothing is stored', () => {
    expect(readControlPanelVisit()).toBeNull();
  });

  it.each([['not a number', 'yesterday'], ['negative', '-5'], ['zero', '0'], ['fractional', '1.5'], ['empty', '']])(
    'reads a %s value as nothing',
    (_label, raw) => {
      window.localStorage.setItem(CONTROL_PANEL_VISIT_STORAGE_KEY, raw);
      expect(readControlPanelVisit()).toBeNull();
    }
  );

  it('survives storage that refuses reads and writes', () => {
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(() => recordControlPanelVisit()).not.toThrow();
    expect(readControlPanelVisit()).toBeNull();
  });
});
