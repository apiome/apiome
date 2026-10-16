/**
 * `lib/seen.ts` — per-device on/off flags behind the quiet pass (HIVE-11.5, #5601).
 *
 * Pins the key shapes (`hive.seen.<id>`, `hive.<page>.stats`), the value encoding, and that
 * every read and write is read-through safe when storage throws.
 */

import {
  SEEN_PREFIX,
  clearSeen,
  hasSeen,
  markSeen,
  readFlag,
  seenKey,
  statsKey,
  writeFlag,
} from '@lib/seen';

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('keys', () => {
  it('namespaces seen and stats flags', () => {
    expect(SEEN_PREFIX).toBe('hive.seen.');
    expect(seenKey('catalog-explainer')).toBe('hive.seen.catalog-explainer');
    expect(statsKey('catalog')).toBe('hive.catalog.stats');
  });
});

describe('readFlag / writeFlag', () => {
  it('round-trips on and off as "1" and "0"', () => {
    expect(writeFlag('k', true)).toBe(true);
    expect(window.localStorage.getItem('k')).toBe('1');
    expect(readFlag('k')).toBe(true);
    writeFlag('k', false);
    expect(window.localStorage.getItem('k')).toBe('0');
    expect(readFlag('k')).toBe(false);
  });

  it('reads unset or unrecognised values as undefined', () => {
    expect(readFlag('missing')).toBeUndefined();
    window.localStorage.setItem('k', 'true');
    expect(readFlag('k')).toBeUndefined();
  });

  it('never throws when storage does', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    expect(readFlag('k')).toBeUndefined();
    expect(writeFlag('k', true)).toBe(false);
  });
});

describe('hasSeen / markSeen / clearSeen', () => {
  it('remembers a dismissal and forgets it again', () => {
    expect(hasSeen('x')).toBe(false);
    expect(markSeen('x')).toBe(true);
    expect(window.localStorage.getItem('hive.seen.x')).toBe('1');
    expect(hasSeen('x')).toBe(true);
    clearSeen('x');
    expect(hasSeen('x')).toBe(false);
  });

  it('treats cleared storage as "not seen"', () => {
    markSeen('x');
    window.localStorage.clear();
    expect(hasSeen('x')).toBe(false);
  });

  it('reads as "not seen" and never throws when storage is blocked', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(hasSeen('x')).toBe(false);
    expect(markSeen('x')).toBe(false);
    expect(() => clearSeen('x')).not.toThrow();
  });
});
