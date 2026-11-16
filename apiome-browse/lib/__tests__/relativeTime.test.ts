import { describe, expect, it } from 'vitest';
import { relativeTime } from '../relativeTime';

const NOW = Date.parse('2026-11-16T12:00:00Z');
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe('relativeTime', () => {
  it('steps through the units', () => {
    expect(relativeTime(ago(10_000), NOW)).toBe('just now');
    expect(relativeTime(ago(5 * MINUTE), NOW)).toBe('5m ago');
    expect(relativeTime(ago(3 * HOUR), NOW)).toBe('3h ago');
    expect(relativeTime(ago(3 * DAY), NOW)).toBe('3d ago');
    expect(relativeTime(ago(90 * DAY), NOW)).toBe('3mo ago');
    expect(relativeTime(ago(800 * DAY), NOW)).toBe('2y ago');
  });

  it('accepts a Date', () => {
    expect(relativeTime(new Date(NOW - 2 * DAY), NOW)).toBe('2d ago');
  });

  it('returns undefined for missing or invalid input', () => {
    expect(relativeTime(undefined, NOW)).toBeUndefined();
    expect(relativeTime(null, NOW)).toBeUndefined();
    expect(relativeTime('', NOW)).toBeUndefined();
    expect(relativeTime('not a date', NOW)).toBeUndefined();
  });
});
