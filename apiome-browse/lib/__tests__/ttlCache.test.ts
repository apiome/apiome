/**
 * The directory cache (DBP-1.16, #7199): fresh for an interval, one load at a time, failures never
 * stored.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_BROWSE_CACHE_TTL_SECONDS,
  MAX_BROWSE_CACHE_TTL_SECONDS,
  TtlCache,
  browseCacheTtlMs,
  cachedRead,
  clearBrowseCache,
  directoryCache,
  searchFacetCache,
} from '../db/ttlCache';

beforeEach(() => {
  clearBrowseCache();
  delete process.env.BROWSE_CACHE_TTL_SECONDS;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('browseCacheTtlMs', () => {
  it('defaults to two minutes', () => {
    expect(DEFAULT_BROWSE_CACHE_TTL_SECONDS).toBe(120);
    expect(browseCacheTtlMs()).toBe(120_000);
  });

  it('reads BROWSE_CACHE_TTL_SECONDS, capped at five minutes', () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '60';
    expect(browseCacheTtlMs()).toBe(60_000);
    process.env.BROWSE_CACHE_TTL_SECONDS = '3600';
    expect(browseCacheTtlMs()).toBe(MAX_BROWSE_CACHE_TTL_SECONDS * 1000);
  });

  it('is off at 0', () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '0';
    expect(browseCacheTtlMs()).toBe(0);
  });

  it('falls back to the default for anything that is not a whole number of seconds', () => {
    for (const value of ['soon', '-5', '1.5', ' ']) {
      process.env.BROWSE_CACHE_TTL_SECONDS = value;
      expect(browseCacheTtlMs()).toBe(120_000);
    }
  });
});

describe('cachedRead', () => {
  it('loads once and serves the value until the interval passes', async () => {
    let clock = 1_000;
    const now = () => clock;
    const loader = vi.fn(async () => ({ n: loader.mock.calls.length }));

    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toEqual({ n: 1 });
    clock += 99;
    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toEqual({ n: 1 });
    expect(loader).toHaveBeenCalledTimes(1);

    clock += 1; // exactly at expiry: stale
    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toEqual({ n: 2 });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('keeps keys apart', async () => {
    expect(await cachedRead('a', async () => 1, { ttlMs: 100 })).toBe(1);
    expect(await cachedRead('b', async () => 2, { ttlMs: 100 })).toBe(2);
    expect(await cachedRead('a', async () => 3, { ttlMs: 100 })).toBe(1);
  });

  it('shares one load between concurrent callers', async () => {
    let release: (value: number) => void = () => undefined;
    const loader = vi.fn(() => new Promise<number>((resolve) => (release = resolve)));
    const first = cachedRead('k', loader, { ttlMs: 100 });
    const second = cachedRead('k', loader, { ttlMs: 100 });
    release(7);
    expect(await Promise.all([first, second])).toEqual([7, 7]);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('caches falsy values too', async () => {
    const loader = vi.fn(async () => 0);
    expect(await cachedRead('zero', loader, { ttlMs: 100 })).toBe(0);
    expect(await cachedRead('zero', loader, { ttlMs: 100 })).toBe(0);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('does not store a failure: the error reaches the caller and the next call loads again', async () => {
    const loader = vi.fn<() => Promise<number>>().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce(5);
    await expect(cachedRead('k', loader, { ttlMs: 100 })).rejects.toThrow('down');
    expect(await cachedRead('k', loader, { ttlMs: 100 })).toBe(5);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('serves the previous value when a refresh fails, and tries again on the next call', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let clock = 0;
    const now = () => clock;
    const loader = vi
      .fn<() => Promise<number>>()
      .mockResolvedValueOnce(1)
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce(3);
    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toBe(1);
    clock = 200;
    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toBe(1);
    expect(await cachedRead('k', loader, { ttlMs: 100, now })).toBe(3);
    expect(loader).toHaveBeenCalledTimes(3);
  });

  it('runs the loader every time when the cache is off', async () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '0';
    const loader = vi.fn(async () => 1);
    await cachedRead('k', loader);
    await cachedRead('k', loader);
    expect(loader).toHaveBeenCalledTimes(2);
  });
});

describe('TtlCache', () => {
  it('drops the entry stored longest ago when full', async () => {
    const cache = new TtlCache(2);
    await cache.read('a', async () => 'a', { ttlMs: 100 });
    await cache.read('b', async () => 'b', { ttlMs: 100 });
    await cache.read('c', async () => 'c', { ttlMs: 100 });
    expect(cache.peek('a')).toBeUndefined();
    expect(cache.peek('b')).toEqual({ value: 'b' });
    expect(cache.peek('c')).toEqual({ value: 'c' });
  });

  it('stores and peeks a value the caller already has, until it expires', () => {
    const cache = new TtlCache(4);
    let clock = 0;
    const now = () => clock;
    expect(cache.peek('k', { now })).toBeUndefined();
    cache.store('k', [1, 2], { ttlMs: 50, now });
    expect(cache.peek('k', { now })).toEqual({ value: [1, 2] });
    clock = 50;
    expect(cache.peek('k', { now })).toBeUndefined();
  });

  it('stores nothing when the cache is off', () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '0';
    const cache = new TtlCache(4);
    cache.store('k', 1);
    expect(cache.peek('k')).toBeUndefined();
  });

  it('keeps search facets out of the directory cache, so searches cannot evict the directory', () => {
    expect(directoryCache).not.toBe(searchFacetCache);
  });
});
